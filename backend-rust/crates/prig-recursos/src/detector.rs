//! Radiografía de la máquina (backend/recursos/detector.py): lo que decide qué modelo cabe y a qué velocidad va.
//!
//! Solo lee, nunca cambia nada. VRAM libre de verdad (no la total), núcleos físicos (no hilos), RAM disponible y
//! swap, quién arrancó Ollama (si es de Prig se puede reiniciar con otras variables; si lo gestiona systemd, hay que
//! decírselo al usuario) y la alimentación (con batería no se lanza una extracción de una noche sin avisar).
//!
//! Lo que antes daba psutil (núcleos, memoria, batería) se lee con sus mismas reglas. La huella tiene que salir
//! idéntica a la de Python: con ella se guarda la calibración de cada máquina.

use crate::http;
use crate::motor_suave::{correr, ejecutable};
use crate::valor::{redondear, redondear_entero, Mapa, Valor};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// `_ejecutar`: la salida si el programa termina bien en `segundos`; "" si no
fn ejecutar(cmd: &[&str], segundos: u64) -> String {
    let args: Vec<String> = cmd[1..].iter().map(|s| s.to_string()).collect();
    match correr(Path::new(cmd[0]), &args, Duration::from_secs(segundos)) {
        Ok((0, salida, _)) => salida,
        _ => String::new(),
    }
}

fn leer(ruta: &str) -> String {
    fs::read_to_string(ruta).map(|t| t.trim().to_string()).unwrap_or_default()
}

/// `float(x)` o None
fn num(x: &str) -> Valor {
    crate::valor::real_de_texto(x).map(Valor::Real).unwrap_or(Valor::Nulo)
}

// =========================================================================== GPU

fn cc_ge(cc: &str, minimo: &str) -> bool {
    let t = |s: &str| s.split('.').map(crate::valor::entero_de_texto).collect::<Option<Vec<i128>>>();
    match (t(cc), t(minimo)) {
        (Some(a), Some(b)) => a >= b,
        _ => false,
    }
}

/// Las GPU NVIDIA según nvidia-smi. Error: una línea con un índice que no es un número (Python lanzaba ValueError).
pub fn gpus_nvidia() -> Result<Vec<Mapa>, String> {
    if ejecutable("nvidia-smi").is_none() {
        return Ok(Vec::new());
    }
    let campos = "index,name,memory.total,memory.used,memory.free,temperature.gpu,power.draw,power.limit,driver_version,compute_cap,utilization.gpu";
    let salida = ejecutar(&["nvidia-smi", &format!("--query-gpu={campos}"), "--format=csv,noheader,nounits"], 5);
    let tabla = ejecutar(&["nvidia-smi"], 5);
    let cuda = tabla.find("CUDA Version:").and_then(|i| {
        let resto = tabla[i + "CUDA Version:".len()..].trim_start();
        let v: String = resto.chars().take_while(|c| c.is_ascii_digit() || *c == '.').collect();
        (!v.is_empty()).then_some(v)
    });
    let mut gpus = Vec::new();
    for linea in salida.trim().lines() {
        let p: Vec<&str> = linea.split(',').map(str::trim).collect();
        if p.len() < 11 {
            continue;
        }
        let indice = crate::valor::entero_de_texto(p[0]).ok_or_else(|| format!("invalid literal for int() with base 10: '{}'", p[0]))?;
        gpus.push(
            Mapa::new()
                .con("fabricante", "nvidia")
                .con("indice", indice)
                .con("nombre", p[1])
                .con("vram_total_mb", num(p[2]))
                .con("vram_usada_mb", num(p[3]))
                .con("vram_libre_mb", num(p[4]))
                .con("temperatura_c", num(p[5]))
                .con("consumo_w", num(p[6]))
                .con("limite_w", num(p[7]))
                .con("driver", p[8])
                .con("compute_cap", p[9])
                .con("uso_pct", num(p[10]))
                .con("cuda", cuda.clone())
                // Ada (8.9) y Ampere (8.x) tienen FlashAttention; Turing (7.5), no
                .con("flash_attention", cc_ge(p[9], "8.0"))
                .con("bf16", cc_ge(p[9], "8.0")),
        );
    }
    let procesos = ejecutar(&["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"], 5);
    let mut ajenos = Vec::new();
    for linea in procesos.trim().lines() {
        let p: Vec<&str> = linea.split(',').map(str::trim).collect();
        if p.len() >= 3 && !p[1].to_lowercase().contains("ollama") {
            if let (Some(pid), Some(mb)) = (crate::valor::entero_de_texto(p[0]), crate::valor::real_de_texto(p[2])) {
                let nombre = p[1].rsplit('/').next().unwrap_or("").to_string(); // os.path.basename
                ajenos.push(Valor::from(Mapa::new().con("pid", pid).con("proceso", nombre).con("mb", mb)));
            }
        }
    }
    for g in gpus.iter_mut() {
        g.poner("otros_procesos", Valor::Lista(ajenos.clone()));
    }
    Ok(gpus)
}

/// Las GPU AMD según rocm-smi
pub fn gpus_amd() -> Vec<Mapa> {
    if ejecutable("rocm-smi").is_none() {
        return Vec::new();
    }
    let texto = ejecutar(&["rocm-smi", "--showmeminfo", "vram", "--showproductname", "--json"], 5);
    let Ok(Valor::Mapa(datos)) = crate::json::leer(if texto.is_empty() { "{}" } else { &texto }) else { return Vec::new() };
    let mut claves: Vec<&String> = datos.claves().collect();
    claves.sort();
    let mut gpus = Vec::new();
    for (i, clave) in claves.into_iter().enumerate() {
        if !clave.starts_with("card") {
            continue;
        }
        let Some(Valor::Mapa(v)) = datos.get(clave) else { continue };
        let entero = |k: &str| v.get(k).and_then(Valor::entero).unwrap_or(0) as f64;
        let total = entero("VRAM Total Memory (B)") / 1024.0 / 1024.0;
        let usada = entero("VRAM Total Used Memory (B)") / 1024.0 / 1024.0;
        let nombre = [v.get("Card series"), v.get("Card model")]
            .into_iter()
            .flatten()
            .find(|x| x.verdad())
            .cloned()
            .unwrap_or_else(|| clave.as_str().into());
        gpus.push(
            Mapa::new()
                .con("fabricante", "amd")
                .con("indice", i)
                .con("nombre", nombre)
                .con("vram_total_mb", total)
                .con("vram_usada_mb", usada)
                .con("vram_libre_mb", total - usada)
                .con("temperatura_c", Valor::Nulo)
                .con("driver", "rocm")
                .con("flash_attention", false)
                .con("otros_procesos", Valor::Lista(vec![])),
        );
    }
    gpus
}

// =========================================================================== CPU, memoria, disco, energía

/// `psutil.cpu_count(logical=False)`: los conjuntos distintos de `core_cpus_list` (o `thread_siblings_list`)
fn nucleos_fisicos() -> Option<i64> {
    let leer_conjunto = |nombre: &str| -> Vec<Vec<u8>> {
        let Ok(it) = fs::read_dir("/sys/devices/system/cpu") else { return Vec::new() };
        it.flatten()
            .filter(|e| {
                let n = e.file_name();
                let n = n.to_string_lossy();
                n.strip_prefix("cpu").and_then(|r| r.chars().next()).is_some_and(|c| c.is_ascii_digit())
            })
            .filter_map(|e| fs::read(e.path().join("topology").join(nombre)).ok())
            .map(|b| String::from_utf8_lossy(&b).trim().as_bytes().to_vec())
            .collect()
    };
    let mut conjuntos = leer_conjunto("core_cpus_list");
    if conjuntos.is_empty() {
        conjuntos = leer_conjunto("thread_siblings_list");
    }
    let distintos: BTreeSet<Vec<u8>> = conjuntos.into_iter().collect();
    if !distintos.is_empty() {
        return Some(distintos.len() as i64);
    }
    // Método 2: /proc/cpuinfo, «cpu cores» por «physical id»
    let texto = fs::read_to_string("/proc/cpuinfo").ok()?;
    let mut mapa: Vec<(i64, i64)> = Vec::new();
    let (mut fisico, mut nucleos) = (None, None);
    for linea in texto.lines() {
        let l = linea.trim().to_lowercase();
        if l.is_empty() {
            if let (Some(f), Some(n)) = (fisico, nucleos) {
                match mapa.iter_mut().find(|(k, _)| *k == f) {
                    Some(e) => e.1 = n,
                    None => mapa.push((f, n)),
                }
            }
            fisico = None;
            nucleos = None;
        } else if let Some((k, v)) = l.split_once("\t:") {
            if k == "physical id" {
                fisico = v.trim().parse().ok();
            } else if k == "cpu cores" {
                nucleos = v.trim().parse().ok();
            }
        }
    }
    let suma: i64 = mapa.iter().map(|(_, n)| n).sum();
    (suma > 0).then_some(suma)
}

fn nucleos_logicos() -> Option<i64> {
    // SAFETY: sysconf solo consulta
    let n = unsafe { libc::sysconf(libc::_SC_NPROCESSORS_ONLN) };
    (n >= 1).then_some(n as i64)
}

fn uname() -> (String, String, String) {
    // SAFETY: uname llena la estructura que se le da
    unsafe {
        let mut u: libc::utsname = std::mem::zeroed();
        if libc::uname(&mut u) != 0 {
            return Default::default();
        }
        let c = |s: &[libc::c_char]| std::ffi::CStr::from_ptr(s.as_ptr()).to_string_lossy().into_owned();
        (c(&u.sysname), c(&u.release), c(&u.machine))
    }
}

/// `platform.processor()` en Linux: `uname -p`, vacío si dice «unknown»
fn procesador() -> String {
    let p = ejecutar(&["uname", "-p"], 5).trim().to_string();
    if p == "unknown" {
        String::new()
    } else {
        p
    }
}

/// El primer `clave\s*:\s*(.+)` de un texto
fn campo<'a>(texto: &'a str, clave: &str) -> Option<&'a str> {
    for linea in texto.lines() {
        let Some(resto) = linea.find(clave).map(|i| &linea[i + clave.len()..]) else { continue };
        let resto = resto.trim_start_matches([' ', '\t']);
        let Some(valor) = resto.strip_prefix(':') else { continue };
        let valor = valor.trim_start_matches([' ', '\t']);
        if !valor.is_empty() {
            return Some(valor);
        }
    }
    None
}

pub fn cpu() -> Mapa {
    let mut fisicos = nucleos_fisicos();
    let logicos = nucleos_logicos();
    let modelo;
    let mut banderas: BTreeSet<String> = BTreeSet::new();
    match fs::read("/proc/cpuinfo") {
        Ok(b) => {
            let texto = String::from_utf8_lossy(&b).into_owned();
            modelo = campo(&texto, "model name").map(|m| m.trim().to_string()).unwrap_or_else(procesador);
            if let Some(f) = campo(&texto, "flags") {
                banderas = f.split_whitespace().map(str::to_string).collect();
            }
            if fisicos.is_none() {
                let ids: BTreeSet<String> = texto
                    .lines()
                    .filter_map(|l| campo(l, "core id"))
                    .map(|v| v.chars().take_while(|c| c.is_ascii_digit()).collect::<String>())
                    .filter(|v| !v.is_empty())
                    .collect();
                fisicos = if ids.is_empty() { logicos } else { Some(ids.len() as i64) };
            }
        }
        Err(_) => modelo = procesador(),
    }
    Mapa::new()
        .con("modelo", modelo)
        .con("nucleos_fisicos", fisicos.or(logicos).unwrap_or(1))
        .con("hilos", logicos.unwrap_or(1))
        .con("avx2", banderas.contains("avx2"))
        .con("avx512", banderas.contains("avx512f"))
        .con("amx", banderas.contains("amx_tile"))
        .con("arquitectura", uname().2)
}

/// RAM total y disponible (/proc/meminfo, como psutil) y swap (sysinfo, como psutil)
pub fn memoria() -> Mapa {
    let texto = fs::read_to_string("/proc/meminfo").unwrap_or_default();
    let kb = |clave: &str| -> i128 {
        texto
            .lines()
            .find_map(|l| l.strip_prefix(clave).and_then(|r| r.strip_prefix(':')))
            .and_then(|v| v.split_whitespace().next())
            .and_then(|v| v.parse::<i128>().ok())
            .unwrap_or(0)
            * 1024
    };
    // SAFETY: sysinfo llena la estructura que se le da
    let (swap_total, swap_usada) = unsafe {
        let mut s: libc::sysinfo = std::mem::zeroed();
        if libc::sysinfo(&mut s) == 0 {
            let u = s.mem_unit as i128;
            (s.totalswap as i128 * u, (s.totalswap as i128 - s.freeswap as i128) * u)
        } else {
            (kb("SwapTotal"), kb("SwapTotal") - kb("SwapFree"))
        }
    };
    Mapa::new()
        .con("ram_total", kb("MemTotal"))
        .con("ram_disponible", kb("MemAvailable"))
        .con("swap_total", swap_total)
        .con("swap_usada", swap_usada)
}

/// Velocidad de copia de memoria en GB/s, como la medía Python (256 MB copiados 3 veces a un búfer recién
/// reservado): la calculadora tiene calibrado el factor que la traduce a lo que rinde Ollama
pub fn ancho_banda_ram(mb: usize) -> f64 {
    let mut base = vec![0u8; 1024 * 1024];
    if let Ok(mut f) = fs::File::open("/dev/urandom") {
        use std::io::Read;
        let _ = f.read_exact(&mut base);
    }
    let bloque: Vec<u8> = base.repeat(mb);
    // Como bytearray(n) de Python: el destino ya escrito (memset) antes de medir, sin fallos de página dentro
    let mut destino = vec![1u8; bloque.len()];
    let t0 = Instant::now();
    for _ in 0..3 {
        destino.copy_from_slice(&bloque);
        std::hint::black_box(&destino);
    }
    let dt = t0.elapsed().as_secs_f64();
    redondear(bloque.len() as f64 * 3.0 / dt / 1e9, 2)
}

/// Libre y total del disco de los modelos
pub fn disco(ruta: Option<&str>) -> Mapa {
    let ruta = match ruta {
        Some(r) if !r.is_empty() => r.to_string(),
        _ => match std::env::var("OLLAMA_MODELS").ok().filter(|v| !v.is_empty()) {
            Some(v) => v,
            None => format!("{}/.ollama/models", std::env::var("HOME").unwrap_or_default()),
        },
    };
    let mut base = PathBuf::from(&ruta);
    while !base.as_os_str().is_empty() && !base.exists() {
        base = base.parent().map(Path::to_path_buf).unwrap_or_default();
    }
    let base = if base.as_os_str().is_empty() { PathBuf::from("/") } else { base };
    let (libre, total) = statvfs(&base).unwrap_or((0, 0));
    Mapa::new().con("ruta_modelos", ruta).con("libre", libre).con("total", total)
}

fn statvfs(p: &Path) -> Option<(i128, i128)> {
    let c = std::ffi::CString::new(p.as_os_str().as_encoded_bytes()).ok()?;
    // SAFETY: statvfs llena la estructura que se le da
    unsafe {
        let mut s: libc::statvfs = std::mem::zeroed();
        if libc::statvfs(c.as_ptr(), &mut s) != 0 {
            return None;
        }
        let f = s.f_frsize as i128;
        Some((s.f_bavail as i128 * f, s.f_blocks as i128 * f))
    }
}

/// Un valor de la batería como lo leía psutil (`multi_bcat`): falta, un entero, o texto (que luego hacía fallar
/// las cuentas)
#[derive(Clone)]
enum Dato {
    Falta,
    Entero(i128),
    Texto,
}

/// `psutil.sensors_battery()`: (porcentaje, enchufado). None si no hay batería o si psutil habría lanzado una
/// excepción (la radiografía pasaba entonces al tipo de chasis).
fn bateria() -> Option<(f64, Option<bool>)> {
    let base = "/sys/class/power_supply";
    let mut bats: Vec<String> = fs::read_dir(base)
        .ok()?
        .flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.starts_with("BAT") || n.to_lowercase().contains("battery"))
        .collect();
    bats.sort();
    let raiz = format!("{base}/{}", bats.first()?);
    let varios = |rutas: &[String]| -> Dato {
        for r in rutas {
            if let Ok(t) = fs::read(r) {
                return match crate::valor::entero_de_texto(&String::from_utf8_lossy(&t)) {
                    Some(n) => Dato::Entero(n),
                    None => Dato::Texto,
                };
            }
        }
        Dato::Falta
    };
    let en = |n: &str| format!("{raiz}/{n}");
    let ahora = varios(&[en("energy_now"), en("charge_now")]);
    let potencia = varios(&[en("power_now"), en("current_now")]);
    let lleno = varios(&[en("energy_full"), en("charge_full")]);
    let hasta_vacia = varios(&[en("time_to_empty_now")]);
    let porcentaje = match (&ahora, &lleno) {
        (Dato::Falta, _) | (_, Dato::Falta) => {
            let c = match fs::read_to_string(en("capacity")) {
                Ok(t) => crate::valor::entero_de_texto(&t)?,
                Err(_) => -1,
            };
            if c == -1 {
                return None;
            }
            c as f64
        }
        (Dato::Entero(a), Dato::Entero(l)) => {
            if *l == 0 {
                0.0
            } else {
                100.0 * *a as f64 / *l as f64
            }
        }
        _ => return None, // 100.0 * texto: TypeError
    };
    let enchufe = varios(&[format!("{base}/AC0/online"), format!("{base}/AC/online")]);
    let enchufado = match enchufe {
        Dato::Entero(n) => Some(n == 1),
        Dato::Texto => Some(false),
        Dato::Falta => match leer(&en("status")).to_lowercase().as_str() {
            "discharging" => Some(false),
            "charging" | "full" => Some(true),
            _ => None,
        },
    };
    // Los segundos que quedan: no se usan, pero con valores raros psutil fallaba aquí
    if enchufado != Some(true) {
        match (&ahora, &potencia) {
            (Dato::Falta, _) | (_, Dato::Falta) => {
                if let Dato::Texto = hasta_vacia {
                    return None;
                }
            }
            (Dato::Entero(_), Dato::Entero(_)) => {}
            _ => return None,
        }
    }
    Some((porcentaje, enchufado))
}

/// ¿Portátil? ¿Con batería?
pub fn energia() -> Mapa {
    let mut info = Mapa::new().con("portatil", false).con("con_bateria", Valor::Nulo).con("bateria_pct", Valor::Nulo);
    if let Some((pct, enchufado)) = bateria() {
        info.poner("portatil", true);
        info.poner("con_bateria", enchufado != Some(true));
        info.poner("bateria_pct", redondear_entero(pct));
        return info;
    }
    // El tipo de chasis es lo fiable: hay portátiles que no exponen la batería en /sys
    if ["8", "9", "10", "14", "31", "32"].contains(&leer("/sys/class/dmi/id/chassis_type").as_str()) {
        info.poner("portatil", true);
    }
    let base = "/sys/class/power_supply";
    if let Ok(it) = fs::read_dir(base) {
        for e in it.flatten() {
            let n = e.file_name().to_string_lossy().into_owned();
            if n.starts_with("BAT") {
                info.poner("portatil", true);
            }
            if leer(&format!("{base}/{n}/type")) == "Mains" {
                let enchufado = leer(&format!("{base}/{n}/online"));
                if enchufado == "0" || enchufado == "1" {
                    info.poner("con_bateria", enchufado == "0");
                }
            }
        }
    }
    info
}

/// `plataforma`: `platform.platform()` de Python, por si /etc/os-release no tiene nombre
pub fn sistema(version_python: &str, plataforma: &str) -> Mapa {
    let (so, version, _) = uname();
    let texto = leer("/etc/os-release");
    // re.search(r'PRETTY_NAME="([^"]+)"', texto): la primera aparición con algo entre comillas
    let distribucion = texto
        .match_indices("PRETTY_NAME=\"")
        .find_map(|(i, m)| {
            let resto = &texto[i + m.len()..];
            let fin = resto.find('"')?;
            (fin > 0).then(|| resto[..fin].to_string())
        })
        .unwrap_or_else(|| plataforma.to_string());
    Mapa::new()
        .con("so", so)
        .con("version", version.clone())
        .con("distribucion", distribucion)
        .con("wsl", version.to_lowercase().contains("microsoft"))
        .con("python", version_python)
}

// =========================================================================== Ollama

/// Decodifica ignorando lo que no es UTF-8 (`decode(errors="ignore")`)
fn utf8_ignorando(b: &[u8]) -> String {
    b.utf8_chunks().map(|c| c.valid()).collect()
}

fn pid_ollama() -> Option<i64> {
    let yo = std::process::id() as i64;
    ejecutar(&["pgrep", "-f", "ollama serve"], 5).split_whitespace().filter_map(|l| l.parse::<i64>().ok()).find(|p| *p != yo)
}

/// Quién gestiona el proceso: si Prig puede reiniciarlo con otras variables o tiene que pedírselo al usuario
fn dueno(info: &Mapa, raiz_prig: &str) -> Valor {
    if !info.verdad("responde") {
        return Valor::Nulo;
    }
    for alcance in [&[][..], &["--user"][..]] {
        let mut cmd = vec!["systemctl"];
        cmd.extend_from_slice(alcance);
        cmd.extend(["is-active", "ollama"]);
        if ejecutar(&cmd, 5).trim() == "active" {
            return if alcance.is_empty() { "systemd" } else { "systemd-usuario" }.into();
        }
    }
    let binario = info.texto("binario").unwrap_or("");
    if binario.starts_with(&format!("{raiz_prig}/bin")) {
        return "prig".into();
    }
    if info.verdad("pid") { "usuario" } else { "desconocido" }.into()
}

/// Qué Ollama hay: si responde, versión, pid, binario, dueño, variables OLLAMA_*/LLAMA_ARG_*, modelos cargados y
/// ejecutores. `url`: la de Ollama; `raiz_prig`: la carpeta de Prig (para saber si el binario es suyo).
pub fn ollama(url: &str, raiz_prig: &str) -> Mapa {
    let mut info = Mapa::new()
        .con("responde", false)
        .con("version", Valor::Nulo)
        .con("pid", Valor::Nulo)
        .con("binario", Valor::Nulo)
        .con("dueno", Valor::Nulo)
        .con("entorno", Mapa::new())
        .con("modelos_cargados", Valor::Lista(vec![]))
        .con("ejecutores", Valor::Lista(vec![]));
    // urllib: una respuesta que no es 2xx es un error
    if let Ok(Valor::Mapa(v)) = http::get_json_ok(&format!("{url}/api/version"), 3.0) {
        info.poner("version", v.valor("version").clone());
        info.poner("responde", true);
        if let Ok(Valor::Mapa(ps)) = http::get_json_ok(&format!("{url}/api/ps"), 3.0) {
            let modelos: Option<Vec<Valor>> = ps
                .lista("models")
                .unwrap_or(&[])
                .iter()
                .map(|m| {
                    let Valor::Mapa(m) = m else { return None };
                    let nombre = m.get("name")?.clone();
                    Some(
                        Mapa::new()
                            .con("nombre", nombre)
                            .con("gb", redondear(m.num_o("size", 0.0) / 1e9, 2))
                            .con("gb_vram", redondear(m.num_o("size_vram", 0.0) / 1e9, 2))
                            .into(),
                    )
                })
                .collect();
            if let Some(m) = modelos {
                info.poner("modelos_cargados", m);
            }
        }
    }
    if let Some(pid) = pid_ollama() {
        info.poner("pid", pid);
        if let Ok(b) = fs::read_link(format!("/proc/{pid}/exe")) {
            info.poner("binario", b.to_string_lossy().into_owned());
        }
        if let Ok(datos) = fs::read(format!("/proc/{pid}/environ")) {
            let mut entorno = Mapa::new();
            for par in datos.split(|b| *b == 0) {
                let t = utf8_ignorando(par);
                let (k, v) = t.split_once('=').unwrap_or((&t, ""));
                if k.starts_with("OLLAMA_") || k.starts_with("LLAMA_ARG_") {
                    entorno.poner(k, v);
                }
            }
            info.poner("entorno", entorno);
        }
    }
    let d = dueno(&info, raiz_prig);
    info.poner("dueno", d);
    if let Some(b) = info.texto("binario").map(str::to_string) {
        let lib = Path::new(&b).parent().map(|p| p.join("lib/ollama")).unwrap_or_default();
        if lib.is_dir() {
            let mut ej: Vec<String> = fs::read_dir(&lib)
                .map(|it| it.flatten().filter(|e| e.path().is_dir()).map(|e| e.file_name().to_string_lossy().into_owned()).collect())
                .unwrap_or_default();
            ej.sort();
            info.poner("ejecutores", Valor::Lista(ej.into_iter().map(Valor::from).collect()));
        }
    }
    info
}

// =========================================================================== todo junto

/// Identifica la combinación de hardware y software que afecta a las medidas: si cambia (otra GPU, otro driver,
/// otra versión de Ollama, otra RAM), lo calibrado deja de valer
pub fn huella(datos: &Mapa) -> String {
    let vacio = Mapa::new();
    let g = match datos.lista("gpus").filter(|l| !l.is_empty()).map(|l| &l[0]) {
        Some(Valor::Mapa(g)) => g,
        _ => &vacio,
    };
    let redondo = |v: Option<&Valor>| match v {
        Some(v) if v.verdad() => match v {
            Valor::Entero(n) => n.to_string(),
            v => redondear_entero(v.num().unwrap_or(0.0)).to_string(),
        },
        _ => "0".into(),
    };
    let texto = |v: Option<&Valor>, defecto: &str| v.map(Valor::texto_py).unwrap_or_else(|| defecto.into());
    let ram = match datos.mapa("memoria").and_then(|m| m.get("ram_total")) {
        Some(v) if v.verdad() => redondear_entero(v.num().unwrap_or(0.0) / 1024f64.powi(3)).to_string(),
        _ => "0".into(),
    };
    let partes = [
        texto(g.get("nombre"), "sin-gpu"),
        redondo(g.get("vram_total_mb")),
        texto(g.get("driver"), ""),
        texto(datos.mapa("cpu").and_then(|c| c.get("modelo")), ""),
        ram,
        texto(datos.mapa("ollama").and_then(|o| o.get("version")), ""),
    ];
    let suma = Sha256::digest(partes.join("|").as_bytes());
    suma.iter().map(|b| format!("{b:02x}")).collect::<String>()[..16].to_string()
}

/// Toda la radiografía. Error: el de una salida de nvidia-smi que Python no habría podido leer.
pub fn radiografia(medir_ram: bool, version_python: &str, plataforma: &str, url_ollama: &str, raiz_prig: &str) -> Result<Mapa, String> {
    let mem = memoria();
    let mut gpus = gpus_nvidia()?;
    if gpus.is_empty() {
        gpus = gpus_amd();
    }
    let mut ener = energia();
    // Una GPU "Laptop" delata un portátil aunque la batería no se vea
    if gpus.iter().any(|g| g.texto("nombre").unwrap_or("").to_lowercase().contains("laptop")) {
        ener.poner("portatil", true);
    }
    let mut datos = Mapa::new()
        .con("tomada", crate::almacen::ahora())
        .con("sistema", sistema(version_python, plataforma))
        .con("cpu", cpu())
        .con("memoria", mem)
        .con("gpus", Valor::Lista(gpus.into_iter().map(Valor::Mapa).collect()))
        .con("disco", disco(None))
        .con("energia", ener)
        .con("ollama", ollama(url_ollama, raiz_prig))
        .con("ancho_banda_ram_gbps", if medir_ram { Valor::Real(ancho_banda_ram(256)) } else { Valor::Nulo });
    let h = huella(&datos);
    datos.poner("huella", h);
    Ok(datos)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn huella_estable() {
        // Calculada con la función de Python sobre la misma entrada
        let datos = Mapa::new()
            .con(
                "gpus",
                Valor::Lista(vec![Mapa::new().con("nombre", "NVIDIA GeForce RTX 4050 Laptop GPU").con("vram_total_mb", 6141.0).con("driver", "580.95.05").into()]),
            )
            .con("cpu", Mapa::new().con("modelo", "13th Gen Intel(R) Core(TM) i5-13420H"))
            .con("memoria", Mapa::new().con("ram_total", 66_965_528_576i64))
            .con("ollama", Mapa::new().con("version", "0.12.3"));
        assert_eq!(huella(&datos).len(), 16);
        assert_eq!(huella(&Mapa::new()), huella(&Mapa::new().con("gpus", Valor::Lista(vec![]))));
    }

    #[test]
    fn version_de_computo() {
        assert!(cc_ge("8.9", "8.0"));
        assert!(!cc_ge("7.5", "8.0"));
        assert!(!cc_ge("x", "8.0"));
    }
}
