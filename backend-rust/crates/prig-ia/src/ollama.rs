//! Ollama desde Prig (la parte de `AIEngine` que no genera): elegir el mejor ejecutable (completo, más nuevo, el de
//! Prig primero), arrancarlo si no responde o se queda viejo, su estado, la lista de modelos (con el motor MoE) y
//! borrar y descargar modelos. El `ollama serve` que arranca Prig es de este servidor: se lanza desde el hilo lanzador
//! del motor, con PDEATHSIG, así que muere con Prig.
//!
//! `PRIG_SIN_AUTOARRANQUE_OLLAMA=1` (las pruebas): nunca arranca ni para ningún Ollama.

use crate::motor;
use prig_plataforma::valor::{redondear, Mapa, Valor};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

pub const COMPLETO: i64 = 2;
pub const DESCONOCIDO: i64 = 1;
pub const INCOMPLETO: i64 = 0;

/// La URL de Ollama de la configuración de IA (`ollama_url`) o la de siempre
pub fn base_url() -> String {
    match std::fs::read_to_string(motor::ruta_config_de_ia()).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        Some(Valor::Mapa(m)) => match m.get("ollama_url") {
            Some(Valor::Texto(u)) if !u.is_empty() => u.trim_end_matches('/').to_string(),
            _ => "http://localhost:11434".into(),
        },
        _ => "http://localhost:11434".into(),
    }
}

fn sin_autoarranque() -> bool {
    std::env::var("PRIG_SIN_AUTOARRANQUE_OLLAMA").as_deref() == Ok("1")
}

fn cliente(segundos: f64) -> Option<reqwest::blocking::Client> {
    reqwest::blocking::Client::builder().timeout(Duration::from_secs_f64(segundos)).build().ok()
}

fn get_json(url: &str, segundos: f64) -> Result<(u16, Valor), String> {
    let r = cliente(segundos).ok_or("cliente")?.get(url).send().map_err(|e| e.to_string())?;
    let estado = r.status().as_u16();
    let t = r.text().map_err(|e| e.to_string())?;
    Ok((estado, prig_plataforma::json::leer(&t).unwrap_or(Valor::Nulo)))
}

/// `GET /api/version` (None si no responde)
pub fn version_en_marcha(base: &str) -> Option<String> {
    match get_json(&format!("{base}/api/version"), 2.0) {
        Ok((200, Valor::Mapa(m))) => m.get("version").map(|v| v.texto_py()),
        _ => None,
    }
}

// ---------------------------------------------------------------------------------------------- ejecutables

fn dirs_libreria(binario: &Path) -> Vec<PathBuf> {
    let exe = std::fs::canonicalize(binario).ok().and_then(|p| p.parent().map(Path::to_path_buf)).unwrap_or_default();
    vec![exe.join("../lib/ollama"), exe.join("build/lib/ollama"), exe.join("dist/linux-amd64/lib/ollama"), exe.join("dist/linux_amd64/lib/ollama")]
}

fn ejecutable(p: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(p).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
}

/// `estado_runtime_ollama(binario)`: ¿tiene su llama-server al lado?
pub fn estado_runtime(binario: &Path) -> i64 {
    let dirs = dirs_libreria(binario);
    if dirs.iter().any(|d| ejecutable(&d.join("llama-server"))) {
        return COMPLETO;
    }
    if dirs.iter().any(|d| d.is_dir()) {
        return INCOMPLETO;
    }
    DESCONOCIDO
}

fn en_path(nombre: &str) -> Option<PathBuf> {
    std::env::var_os("PATH").and_then(|p| std::env::split_paths(&p).map(|d| d.join(nombre)).find(|x| ejecutable(x)))
}

/// `_candidatos_ollama()`: el de Prig primero
fn candidatos(raiz: &Path) -> Vec<PathBuf> {
    let casa = PathBuf::from(prig_plataforma::py::expanduser("~"));
    let mut v = vec![raiz.join("bin/ollama"), raiz.join("bin/bin/ollama"), casa.join(".local/bin/ollama"), "/usr/local/bin/ollama".into(), "/usr/bin/ollama".into()];
    if let Some(p) = en_path("ollama") {
        v.push(p);
    }
    v
}

/// `_parse_version`: los tres primeros números
fn version_num(v: &str) -> Vec<i64> {
    let re = regex::Regex::new(r"\d+").unwrap();
    let mut n: Vec<i64> = re.find_iter(v).take(3).filter_map(|m| m.as_str().parse().ok()).collect();
    n.resize(3, 0);
    n
}

/// `get_best_ollama_binary()`: (ruta, versión) del mejor: completo, más nuevo y, a igualdad, el primero de la lista
pub fn mejor_binario(raiz: &Path) -> Option<(PathBuf, String)> {
    let re = regex::Regex::new(r"(\d+\.\d+[\.\d]*)").unwrap();
    let mut vistos = Vec::new();
    let mut mejor: Option<((i64, Vec<i64>, i64), PathBuf, String)> = None;
    for (i, c) in candidatos(raiz).into_iter().enumerate() {
        let real = std::fs::canonicalize(&c).unwrap_or_else(|_| c.clone());
        if vistos.contains(&real) {
            continue;
        }
        vistos.push(real);
        if !ejecutable(&c) {
            continue;
        }
        let ver = Command::new(&c)
            .arg("--version")
            .stdin(Stdio::null())
            .output()
            .ok()
            .and_then(|o| re.captures(&format!("{}{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr))).map(|m| m[1].to_string()));
        let clave = (estado_runtime(&c), version_num(ver.as_deref().unwrap_or("0.0.0")), -(i as i64));
        if mejor.as_ref().is_none_or(|m| clave > m.0) {
            mejor = Some((clave, c, ver.unwrap_or_else(|| "0.0.0".into())));
        }
    }
    mejor.map(|m| (m.1, m.2))
}

/// `binario_ollama_en_marcha()`: el ejecutable del `ollama serve` que corre (por /proc)
pub fn en_marcha() -> Option<PathBuf> {
    for e in std::fs::read_dir("/proc").ok()?.flatten() {
        let Some(pid) = e.file_name().to_str().and_then(|n| n.parse::<u32>().ok()) else { continue };
        let Ok(cmd) = std::fs::read(format!("/proc/{pid}/cmdline")) else { continue };
        let partes: Vec<String> = cmd.split(|b| *b == 0).filter(|p| !p.is_empty()).map(|p| String::from_utf8_lossy(p).into_owned()).collect();
        if partes.len() >= 2 && Path::new(&partes[0]).file_name().is_some_and(|n| n == "ollama") && partes[1..].iter().any(|p| p == "serve") {
            if let Ok(exe) = std::fs::read_link(format!("/proc/{pid}/exe")) {
                return Some(exe);
            }
        }
    }
    None
}

/// El `ollama serve` que arrancó Prig (si lo arrancó)
static PROPIO: Mutex<Option<Child>> = Mutex::new(None);

fn terminar(pid: i32) {
    // SAFETY: señales a un proceso del usuario
    unsafe {
        libc::kill(pid, libc::SIGTERM);
    }
    for _ in 0..20 {
        if !Path::new(&format!("/proc/{pid}")).exists() {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    // SAFETY: igual que arriba
    unsafe {
        libc::kill(pid, libc::SIGKILL);
    }
}

/// `kill_ollama_processes()`: para todo `ollama` en marcha (para reiniciarlo limpio)
fn parar_todos() {
    let yo = std::process::id();
    for e in std::fs::read_dir("/proc").into_iter().flatten().flatten() {
        let Some(pid) = e.file_name().to_str().and_then(|n| n.parse::<u32>().ok()) else { continue };
        if pid == yo {
            continue;
        }
        let nombre = std::fs::read_to_string(format!("/proc/{pid}/comm")).unwrap_or_default().trim().to_lowercase();
        let cmd = std::fs::read(format!("/proc/{pid}/cmdline")).map(|b| String::from_utf8_lossy(&b).replace('\0', " ").to_lowercase()).unwrap_or_default();
        if nombre.contains("ollama") || cmd.contains("ollama serve") {
            terminar(pid as i32);
        }
    }
    if let Some(mut c) = PROPIO.lock().unwrap().take() {
        let _ = c.kill();
        let _ = c.wait();
    }
    std::thread::sleep(Duration::from_secs(1));
}

/// Para el `ollama serve` que arrancó Prig (al cerrar o al apagar los procesos de IA)
pub fn detener_propio() {
    if let Some(mut c) = PROPIO.lock().unwrap().take() {
        if c.try_wait().ok().flatten().is_none() {
            terminar(c.id() as i32);
            let _ = c.wait();
        }
    }
}

/// Qué hacer con el Ollama que responde (o no)
#[derive(Debug, PartialEq)]
pub enum Decision {
    /// Responde y está bien: no se toca
    Dejar,
    /// Responde pero está roto (incompleto, con uno completo disponible) o se queda viejo: se para y se arranca el mejor
    Reiniciar,
    /// No responde: se arranca el mejor
    Arrancar,
}

/// La decisión de `try_autostart_ollama`, sin efectos: la versión que responde, el ejecutable en marcha y el mejor
pub fn decidir(activa: Option<&str>, en_marcha: Option<&Path>, mejor: Option<&(PathBuf, String)>, forzar: bool) -> Decision {
    let Some(activa) = activa else { return if forzar { Decision::Reiniciar } else { Decision::Arrancar } };
    if forzar {
        return Decision::Reiniciar;
    }
    let (mb, mv) = match mejor {
        Some((b, v)) => (Some(b.clone()), v.clone()),
        None => (None, "0.0.0".into()),
    };
    let roto = match (en_marcha, &mb) {
        (Some(e), Some(b)) => std::fs::canonicalize(e).ok() != std::fs::canonicalize(b).ok() && estado_runtime(e) == INCOMPLETO && estado_runtime(b) == COMPLETO,
        _ => false,
    };
    if !roto && version_num(activa) >= version_num(&mv) {
        return Decision::Dejar;
    }
    Decision::Reiniciar
}

/// `try_autostart_ollama(force_restart)`: arranca (o reinicia) Ollama si no responde, está incompleto o hay un
/// ejecutable más nuevo
pub fn asegurar(raiz: &Path, forzar: bool) -> bool {
    if sin_autoarranque() {
        return false;
    }
    let base = base_url();
    let mejor = mejor_binario(raiz);
    let forzar = match decidir(version_en_marcha(&base).as_deref(), en_marcha().as_deref(), mejor.as_ref(), forzar) {
        Decision::Dejar => return true,
        Decision::Reiniciar => true,
        Decision::Arrancar => false,
    };
    if forzar {
        parar_todos();
    }
    let Some((bin, _)) = mejor else { return false };
    // el entorno: el de Prig con las variables del servidor guardadas encima y su carpeta en el PATH
    let mut base_env = Mapa::new();
    for (k, v) in std::env::vars() {
        base_env.poner(k, v);
    }
    let guardado = prig_recursos::almacen::Almacen::abrir(&prig_recursos::almacen::ruta_por_defecto()).seccion("entorno_servidor");
    let env = prig_recursos::servidor::entorno_arranque(&base_env, &guardado);
    let dir_bin = bin.parent().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default();
    let mut c = Command::new(&bin);
    c.arg("serve").env_clear().stdin(Stdio::null());
    for (k, v) in env.iter() {
        c.env(k, v.texto_py());
    }
    c.env("PATH", format!("{dir_bin}:{}", env.get("PATH").map(|v| v.texto_py()).unwrap_or_default()));
    let casa_ollama = PathBuf::from(prig_plataforma::py::expanduser("~/.ollama"));
    if std::fs::create_dir_all(&casa_ollama).is_err() {
        let local = raiz.join(".ollama");
        if std::fs::create_dir_all(&local).is_ok() {
            c.env("OLLAMA_MODELS", local.join("models"));
        }
    }
    let registro = prig_plataforma::py::expanduser("~/.prig_ollama.log");
    prig_recursos::servidor::rotar_registro(&registro);
    match std::fs::OpenOptions::new().create(true).append(true).open(&registro) {
        Ok(f) => {
            let f2 = f.try_clone().ok();
            c.stdout(f);
            match f2 {
                Some(f2) => c.stderr(f2),
                None => c.stderr(Stdio::null()),
            };
        }
        Err(_) => {
            c.stdout(Stdio::null()).stderr(Stdio::null());
        }
    }
    match motor::lanzar(c) {
        Ok(hijo) => *PROPIO.lock().unwrap() = Some(hijo),
        Err(e) => {
            eprintln!("Error intentando iniciar Ollama con {}: {e}", bin.display());
            return false;
        }
    }
    for _ in 0..12 {
        std::thread::sleep(Duration::from_millis(500));
        if version_en_marcha(&base).is_some() {
            return true;
        }
    }
    false
}

// ---------------------------------------------------------------------------------------------- estado y modelos

/// `_modelos_propios()`: el motor MoE, si está compilado y el modelo descargado
pub fn modelos_propios(raiz: &Path) -> Vec<Valor> {
    let rutas = motor::Rutas::de_prig(raiz);
    use std::os::unix::fs::PermissionsExt;
    let servidor = std::fs::metadata(&rutas.servidor).is_ok_and(|m| m.permissions().mode() & 0o111 != 0);
    let Some(blob) = rutas.blob_del_modelo().filter(|_| servidor) else { return Vec::new() };
    let tam = std::fs::metadata(&blob).map(|m| m.len()).unwrap_or(0);
    let fecha = std::fs::metadata(&rutas.servidor)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| {
            // SAFETY: localtime_r con una estructura propia
            unsafe {
                let s = d.as_secs() as libc::time_t;
                let mut tm: libc::tm = std::mem::zeroed();
                libc::localtime_r(&s, &mut tm);
                format!("{:04}-{:02}-{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday)
            }
        })
        .unwrap_or_default();
    vec![Valor::Mapa(
        Mapa::new()
            .con("name", crate::moe::NOMBRE)
            .con("size_gb", Valor::Real(redondear(tam as f64 / 1073741824.0, 2)))
            .con("quantization", "Q4_K_S")
            .con("family", "qwen35moe")
            .con("parameter_size", "35B-A3B")
            .con("format", "gguf")
            .con("modified_at", fecha)
            .con("available", true)
            .con("motor", "moe"),
    )]
}

/// `check_health()`: arranca si hace falta; los modelos (los de Ollama y los propios) y la versión
pub fn estado(raiz: &Path) -> Mapa {
    asegurar(raiz, false);
    let base = base_url();
    match get_json(&format!("{base}/api/tags"), 5.0) {
        Ok((200, tags)) => {
            let mut modelos: Vec<Valor> = match tags {
                Valor::Mapa(m) => m.lista("models").unwrap_or(&[]).iter().map(|x| match x {
                    Valor::Mapa(x) => x.get("name").cloned().unwrap_or(Valor::Nulo),
                    _ => Valor::Nulo,
                }).collect(),
                _ => Vec::new(),
            };
            modelos.extend(modelos_propios(raiz).into_iter().map(|p| match p {
                Valor::Mapa(m) => m.valor("name").clone(),
                _ => Valor::Nulo,
            }));
            let ver = version_en_marcha(&base).unwrap_or_else(|| "?".into());
            Mapa::new().con("status", "ok").con("online", true).con("version", ver).con("models", Valor::Lista(modelos)).con("url", base)
        }
        Ok((e, _)) => Mapa::new().con("status", "error").con("online", false).con("message", format!("Ollama HTTP {e}")).con("models", Valor::Lista(vec![])),
        Err(e) => Mapa::new().con("status", "offline").con("online", false).con("message", e).con("models", Valor::Lista(vec![])),
    }
}

/// `get_detailed_models()`
pub fn modelos_detallados(raiz: &Path) -> Mapa {
    asegurar(raiz, false);
    let base = base_url();
    let ver = version_en_marcha(&base).unwrap_or_else(|| "?".into());
    let propios = modelos_propios(raiz);
    match get_json(&format!("{base}/api/tags"), 5.0) {
        Ok((200, tags)) => {
            let mut v = Vec::new();
            for m in match &tags {
                Valor::Mapa(t) => t.lista("models").unwrap_or(&[]).to_vec(),
                _ => Vec::new(),
            } {
                let Valor::Mapa(m) = m else { continue };
                let d = m.mapa("details").cloned().unwrap_or_default();
                let o = |k: &str, def: &str| d.get(k).cloned().unwrap_or_else(|| Valor::Texto(def.into()));
                let fecha: String = m.get("modified_at").map(|v| v.texto_py()).unwrap_or_default().chars().take(10).collect();
                v.push(Valor::Mapa(
                    Mapa::new()
                        .con("name", m.get("name").cloned().unwrap_or(Valor::Nulo))
                        .con("size_gb", Valor::Real(redondear(m.get("size").and_then(|x| x.num()).unwrap_or(0.0) / 1073741824.0, 2)))
                        .con("quantization", o("quantization_level", "N/A"))
                        .con("family", o("family", "N/A"))
                        .con("parameter_size", o("parameter_size", "N/A"))
                        .con("format", o("format", "gguf"))
                        .con("modified_at", fecha)
                        .con("available", true),
                ));
            }
            v.extend(propios);
            Mapa::new().con("online", true).con("models", Valor::Lista(v)).con("version", ver).con("url", base)
        }
        Ok((e, _)) => Mapa::new().con("online", false).con("models", Valor::Lista(propios)).con("version", ver).con("message", format!("HTTP {e}")),
        Err(e) => Mapa::new().con("online", false).con("models", Valor::Lista(propios)).con("version", ver).con("message", e),
    }
}

/// `delete_model(nombre)`
pub fn borrar_modelo(nombre: &str) -> bool {
    let Some(c) = cliente(10.0) else { return false };
    let cuerpo = prig_plataforma::json::escribir_compacto(&Valor::Mapa(Mapa::new().con("name", nombre)));
    c.delete(format!("{}/api/delete", base_url())).header("Content-Type", "application/json").body(cuerpo).send().is_ok_and(|r| r.status().as_u16() == 200)
}

/// `pull_model(nombre)`: descarga un modelo; cada línea de progreso (texto) a `linea` (que dice si seguir)
pub fn descargar_modelo(raiz: &Path, nombre: &str, linea: &mut dyn FnMut(String) -> bool) {
    asegurar(raiz, false);
    let crudo = prig_plataforma::py::strip(nombre);
    let limpio = if crudo.is_empty() {
        String::new()
    } else {
        prig_plataforma::py::strip(crudo.split(|c: char| c.is_whitespace() || c == '(').next().unwrap_or("")).to_lowercase()
    };
    let destino = match limpio.as_str() {
        "qwen3-30b-a3b:r1-distill" | "qwen3-30b-a3b" => "qwen3:30b-a3b".to_string(),
        "qwen3.6-35b-a3b" => "qwen3.6:35b-a3b".to_string(),
        "deepseek-coder-v2-lite" | "deepseek-coder-v2:lite" => "deepseek-coder-v2:16b".to_string(),
        otro => otro.to_string(),
    };
    let base = base_url();
    let cuerpo = prig_plataforma::json::escribir_compacto(&Valor::Mapa(Mapa::new().con("name", destino.clone()).con("stream", true)));
    let resp = reqwest::blocking::Client::builder()
        .timeout(None)
        .connect_timeout(Duration::from_secs(600))
        .build()
        .ok()
        .and_then(|c| c.post(format!("{base}/api/pull")).header("Content-Type", "application/json").body(cuerpo).send().map_err(|e| e.to_string()).ok());
    let Some(mut resp) = resp else {
        linea(format!("Error de conexión de red con Ollama ({base}): no se pudo conectar\n"));
        return;
    };
    let estado = resp.status().as_u16();
    if estado != 200 {
        let t = resp.text().unwrap_or_default();
        let tl = t.to_lowercase();
        let m = if estado == 412 || tl.contains("newer version") {
            format!("Error desde Ollama: El modelo '{destino}' requiere una versión más reciente de Ollama. Actualiza desde Configuración o ejecuta 'run.sh'.\n")
        } else if tl.contains("file does not exist") || tl.contains("not found") || estado == 404 {
            format!("Error desde Ollama: El modelo '{destino}' no existe en el registro central de Ollama.\n")
        } else {
            format!("Error desde Ollama (HTTP {estado}): {t}\n")
        };
        linea(m);
        return;
    }
    use std::io::BufRead;
    let lector = std::io::BufReader::new(&mut resp);
    for l in lector.split(b'\n') {
        let Ok(l) = l else { break };
        let l = String::from_utf8_lossy(&l).trim_end_matches('\r').to_string();
        if l.is_empty() {
            continue;
        }
        let salida = match prig_plataforma::json::leer(&l) {
            Ok(Valor::Mapa(d)) => {
                if let Some(e) = d.get("error") {
                    let em = e.texto_py();
                    let el = em.to_lowercase();
                    let m = if el.contains("newer version") {
                        format!("Error en descarga: Ollama necesita actualizarse para '{destino}'. Actualiza desde Configuración o ejecuta 'run.sh'.\n")
                    } else if el.contains("file does not exist") || el.contains("not found") {
                        format!(
                            "Error en descarga: El modelo '{destino}' no se encuentra en el registro oficial de Ollama. Si es un modelo GGUF comunitario de Hugging Face, impórtalo con: 'ollama create {limpio} -f Modelfile'.\n"
                        )
                    } else if el.contains("directorio") || el.contains("directory") || el.contains("invalid") {
                        format!("Error en descarga: Tag de modelo inválido ('{crudo}'). Usa solo letras, números y dos puntos (ej: qwen3:30b-a3b).\n")
                    } else {
                        format!("Error en descarga: {em}\n")
                    };
                    linea(m);
                    return;
                }
                let estado = d.get("status").map(|v| v.texto_py()).unwrap_or_default();
                match (d.get("completed").and_then(|v| v.num()), d.get("total").and_then(|v| v.num())) {
                    (Some(c), Some(t)) if t > 0.0 => {
                        let pct = (c / t * 100.0) as i64;
                        format!(
                            "{estado} ({pct}%) - {}MB / {}MB\n",
                            prig_plataforma::valor::repr_real(redondear(c / 1048576.0, 1)),
                            prig_plataforma::valor::repr_real(redondear(t / 1048576.0, 1))
                        )
                    }
                    _ if !estado.is_empty() => format!("{estado}\n"),
                    _ => continue,
                }
            }
            _ => format!("{l}\n"),
        };
        if !linea(salida) {
            return;
        }
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    /// Un ollama falso en `<dir>/<nombre>/bin/ollama` (con su lib completa, incompleta o sin ella)
    fn ollama(dir: &Path, nombre: &str, estado: &str) -> PathBuf {
        use std::os::unix::fs::PermissionsExt;
        let bin = dir.join(nombre).join("bin");
        std::fs::create_dir_all(&bin).unwrap();
        let exe = bin.join("ollama");
        std::fs::write(&exe, "#!/bin/sh\necho 0.34.1\n").unwrap();
        std::fs::set_permissions(&exe, std::fs::Permissions::from_mode(0o755)).unwrap();
        let lib = dir.join(nombre).join("lib/ollama");
        match estado {
            "completo" => {
                std::fs::create_dir_all(&lib).unwrap();
                let ls = lib.join("llama-server");
                std::fs::write(&ls, "").unwrap();
                std::fs::set_permissions(&ls, std::fs::Permissions::from_mode(0o755)).unwrap();
            }
            "incompleto" => std::fs::create_dir_all(&lib).unwrap(),
            _ => {}
        }
        exe
    }

    fn temporal(n: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("prig_ollama_{n}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn estado_del_runtime() {
        let d = temporal("runtime");
        assert_eq!(estado_runtime(&ollama(&d, "a", "completo")), COMPLETO);
        assert_eq!(estado_runtime(&ollama(&d, "b", "incompleto")), INCOMPLETO);
        assert_eq!(estado_runtime(&ollama(&d, "c", "nada")), DESCONOCIDO);
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn roto_en_marcha_se_cambia_por_el_completo() {
        let d = temporal("roto");
        let prig = ollama(&d, "prig", "completo");
        let usr = ollama(&d, "usr", "incompleto");
        assert_eq!(decidir(Some("0.34.1"), Some(&usr), Some(&(prig.clone(), "0.34.1".into())), false), Decision::Reiniciar);
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn sano_en_marcha_no_se_toca() {
        let d = temporal("sano");
        let prig = ollama(&d, "prig", "completo");
        let otro = ollama(&d, "otro", "completo");
        for en in [Some(prig.clone()), Some(otro), None] {
            assert_eq!(decidir(Some("0.34.1"), en.as_deref(), Some(&(prig.clone(), "0.34.1".into())), false), Decision::Dejar);
        }
        // uno más nuevo disponible: se reinicia; sin nada que responda: se arranca
        assert_eq!(decidir(Some("0.30.0"), None, Some(&(prig.clone(), "0.34.1".into())), false), Decision::Reiniciar);
        assert_eq!(decidir(None, None, Some(&(prig, "0.34.1".into())), false), Decision::Arrancar);
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn si_el_mejor_tambien_esta_roto_no_se_reinicia_en_bucle() {
        let d = temporal("bucle");
        let usr = ollama(&d, "usr", "incompleto");
        let usr2 = ollama(&d, "usr2", "incompleto");
        assert_eq!(decidir(Some("0.34.1"), Some(&usr), Some(&(usr2, "0.34.1".into())), false), Decision::Dejar);
        std::fs::remove_dir_all(d).ok();
    }
}

/// Descarga de Ollama los modelos de Prig que estén cargados (`_descargar_ollama` de Python): libera la VRAM, por
/// ejemplo para el motor MoE. Los que cargó otro programa se dejan en paz.
pub fn descargar_propios(propios: &[String]) {
    let base = base_url();
    let c = reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(2)).build();
    let Ok(c) = c else { return };
    let cargados: Vec<String> = match c.get(format!("{base}/api/ps")).send().and_then(|r| r.text()) {
        Ok(t) => match prig_plataforma::json::leer(&t) {
            Ok(Valor::Mapa(m)) => m
                .lista("models")
                .unwrap_or(&[])
                .iter()
                .filter_map(|x| if let Valor::Mapa(x) = x { x.texto("name").map(String::from) } else { None })
                .collect(),
            _ => propios.to_vec(),
        },
        Err(_) => propios.to_vec(),
    };
    for m in cargados.into_iter().filter(|m| propios.contains(m)) {
        let cuerpo = format!("{{\"model\": {}, \"keep_alive\": 0}}", prig_plataforma::json::escribir_linea(&Valor::Texto(m)));
        let _ = c.post(format!("{base}/api/generate")).header("Content-Type", "application/json").body(cuerpo).send();
    }
}

/// `_parse_version`: los tres primeros números
fn tres_numeros(v: &str) -> Vec<i64> {
    let mut n: Vec<i64> = regex::Regex::new(r"\d+").unwrap().find_iter(v).take(3).filter_map(|m| m.as_str().parse().ok()).collect();
    n.resize(3, 0);
    n
}

/// `_version_ollama()`: la del Ollama en marcha o la del mejor binario instalado (la mayor de las dos), o «?»
pub fn version_texto(raiz: &Path) -> String {
    let activa = cliente(3.0)
        .and_then(|c| c.get(format!("{}/api/version", base_url())).send().ok())
        .filter(|r| r.status().as_u16() == 200)
        .and_then(|r| r.text().ok())
        .and_then(|t| prig_plataforma::json::leer(&t).ok())
        .and_then(|v| match v {
            Valor::Mapa(m) => m.get("version").filter(|x| x.verdad()).map(Valor::texto_py),
            _ => None,
        });
    let mejor = mejor_binario(raiz).map(|(_, v)| v).filter(|v| v != "0.0.0");
    match (activa, mejor) {
        (Some(a), Some(m)) => {
            if tres_numeros(&m) >= tres_numeros(&a) { m } else { a }
        }
        (Some(a), None) => a,
        (None, Some(m)) => m,
        (None, None) => "?".into(),
    }
}
