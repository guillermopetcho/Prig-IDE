//! La copia completa de un repositorio de Hugging Face (`descargas_hf_completo.py`): no solo los pesos (.gguf o
//! .safetensors), también la configuración, el tokenizer y los metadatos (config.json, tokenizer.json, README,
//! LICENSE…), para que el modelo quede guardado en el equipo aunque el autor o Hugging Face lo borren o lo cambien.
//!
//! Deja en la carpeta un `prig_backup_manifest.json` con lo copiado y, si hay un GGUF, un `Modelfile` para Ollama.

use prig_modelos::buscador::{agrupar_gguf, UA};
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::io::{Read, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

pub const BASE_HF: &str = "https://huggingface.co";
pub const CARPETA_DEFECTO: &str = "modelos_completos";

const NOMBRES_CONFIG: &[&str] = &[
    "config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
    "vocab.json", "merges.txt", "chat_template.json", "added_tokens.json", "preprocessor_config.json",
    "adapter_config.json", "README.md", "readme.md", "LICENSE", "license", "LICENSE.txt", "license.txt", "LICENSE.md",
    "license.md", ".gitattributes", "params", "template", "Modelfile", "modelfile", "model.safetensors.index.json",
    "pytorch_model.bin.index.json",
];
const EXTS_CONFIG: [&str; 8] = [".json", ".txt", ".yaml", ".yml", ".py", ".md", ".jinja", ".jinja2"];
const EXTS_PESOS: [&str; 7] = [".gguf", ".safetensors", ".bin", ".pt", ".pth", ".onnx", ".h5"];

/// Lo que falla al inspeccionar: sin red (`requests.RequestException`, la ruta da 503) o lo demás (`ValueError`,
/// `PermissionError`, `RuntimeError`: la ruta da 500)
#[derive(Debug)]
pub enum ErrorHf {
    Red(String),
    Otro(String),
}

impl ErrorHf {
    pub fn texto(&self) -> String {
        match self {
            ErrorHf::Red(t) | ErrorHf::Otro(t) => t.clone(),
        }
    }
}

/// `obtener_token_hf()`: las variables de entorno o la caché de `huggingface_hub`
pub fn obtener_token() -> Option<String> {
    for var in ["HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"] {
        if let Ok(t) = std::env::var(var) {
            if !t.trim().is_empty() {
                return Some(t.trim().to_string());
            }
        }
    }
    let t = std::fs::read_to_string(py::expanduser("~/.cache/huggingface/token")).ok()?;
    Some(t.trim().to_string()).filter(|t| !t.is_empty())
}

/// `cabeceras_hf(token)`
pub fn cabeceras(token: Option<&str>) -> Vec<(String, String)> {
    let mut c = vec![("User-Agent".to_string(), UA.to_string())];
    if let Some(t) = token.map(str::to_string).or_else(obtener_token) {
        c.push(("Authorization".into(), format!("Bearer {t}")));
    }
    c
}

fn re(patron: &'static str, celda: &'static OnceLock<Regex>) -> &'static Regex {
    celda.get_or_init(|| Regex::new(patron).expect("regex"))
}

/// `limpiar_repo_hf(ref_o_url)` → (repo_id, variante)
pub fn limpiar_repo(r: &str) -> (String, Option<String>) {
    static A: OnceLock<Regex> = OnceLock::new();
    static B: OnceLock<Regex> = OnceLock::new();
    static C: OnceLock<Regex> = OnceLock::new();
    static D: OnceLock<Regex> = OnceLock::new();
    let t = r.trim();
    let t = re(r"(?i)^https?://(?:www\.)?(?:huggingface\.co|hf\.co)/", &A).replace(t, "");
    let t = re(r"(?i)^(?:hf\.co|huggingface\.co)/", &B).replace(&t, "");
    let mut t = re(r"(?i)^models/", &C).replace(&t, "").into_owned();
    let mut variante = None;
    if let Some((a, b)) = t.split_once(':') {
        variante = Some(b.trim().to_string()).filter(|v| !v.is_empty());
        t = a.to_string();
    }
    let t = re(r"/(?:tree|blob|resolve)/[\w.\-]+(?:/.*)?$", &D).replace(&t, "");
    (t.trim().to_string(), variante)
}

/// `es_archivo_config(nombre, tam_bytes)`
pub fn es_archivo_config(nombre: &str, tam: i128) -> bool {
    let base = py::basename(nombre).to_lowercase();
    if NOMBRES_CONFIG.iter().any(|n| n.to_lowercase() == base) {
        return true;
    }
    if base.starts_with("imatrix") && base.ends_with(".dat") {
        return true;
    }
    let ext = py::splitext(&base).1;
    EXTS_CONFIG.contains(&ext.as_str()) && !EXTS_PESOS.contains(&ext.as_str()) && tam < 50 * 1024 * 1024
}

fn archivo(nombre: &str, bytes: i128, url: String) -> Mapa {
    Mapa::new().con("nombre", nombre).con("bytes", bytes).con("url", url)
}

fn bytes_de(m: &Mapa) -> i128 {
    m.valor("bytes").entero().unwrap_or(0)
}

fn lista(v: Vec<Mapa>) -> Valor {
    Valor::Lista(v.into_iter().map(Valor::Mapa).collect())
}

/// `inspeccionar_modelo_hf(repo_o_ref, variante, token)`: los archivos del repositorio, separados en configuración
/// y pesos de la variante pedida
pub fn inspeccionar(repo_o_ref: &str, variante: Option<&str>, token: Option<&str>) -> Result<Mapa, ErrorHf> {
    inspeccionar_en(BASE_HF, repo_o_ref, variante, token)
}

pub fn inspeccionar_en(base: &str, repo_o_ref: &str, variante: Option<&str>, token: Option<&str>) -> Result<Mapa, ErrorHf> {
    static REPO: OnceLock<Regex> = OnceLock::new();
    let (repo, var_ref) = limpiar_repo(repo_o_ref);
    let elegida = variante.filter(|v| !v.is_empty()).map(str::to_string).or(var_ref);
    if !re(r"^[\w.\-]+/[\w.\-]+$", &REPO).is_match(&repo) {
        return Err(ErrorHf::Otro(format!("Identificador de repositorio Hugging Face no válido: {}", Valor::Texto(repo).repr_py())));
    }
    let cab = cabeceras(token);
    let cab: Vec<(&str, &str)> = cab.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
    let url = format!("{base}/api/models/{repo}?blobs=true");
    let r = prig_modelos::red::pedir("GET", &url, None, &cab, 25.0).map_err(|e| ErrorHf::Red(e.texto()))?;
    match r.estado {
        200 => {}
        404 => return Err(ErrorHf::Otro(format!("El modelo '{repo}' no existe en Hugging Face (404)."))),
        401 | 403 => return Err(ErrorHf::Otro(format!("El modelo '{repo}' requiere autenticación o aceptar su licencia (gated)."))),
        e => return Err(ErrorHf::Otro(format!("Hugging Face respondió {e}: {}", r.texto().chars().take(200).collect::<String>()))),
    }
    let datos = match r.json().map_err(|e| ErrorHf::Red(e.texto()))? {
        Valor::Mapa(m) => m,
        _ => Mapa::new(),
    };
    let siblings = datos.lista("siblings").map(<[Valor]>::to_vec).unwrap_or_default();
    let mut configs = Vec::new();
    let mut pesos = Vec::new();
    let mut gguf: Vec<(String, Valor)> = Vec::new();
    for s in &siblings {
        let Valor::Mapa(s) = s else { continue };
        let nombre = s.get("rfilename").map(Valor::texto_py).unwrap_or_default();
        let tam = s.get("size").and_then(Valor::entero).unwrap_or(0);
        let a = archivo(&nombre, tam, format!("{BASE_HF}/{repo}/resolve/main/{nombre}"));
        if es_archivo_config(&nombre, tam) {
            configs.push(a);
        } else {
            pesos.push(a);
            let bajo = nombre.to_lowercase();
            if bajo.ends_with(".gguf") && !bajo.contains("mmproj") {
                gguf.push((nombre, Valor::Entero(tam)));
            }
        }
    }
    let variantes = agrupar_gguf(&gguf, &format!("hf.co/{repo}"));
    let nombre_de = |p: &Mapa| p.valor("nombre").texto_py();
    let seleccion: Vec<Mapa> = match elegida.as_deref().map(str::to_lowercase) {
        Some(v) if matches!(v.as_str(), "solo_configs" | "__solo_configs__" | "configs") => Vec::new(),
        Some(v) if !v.is_empty() && v != "todo" => {
            let grupo = variantes.iter().find(|g| g.valor("etiqueta").texto_py().to_lowercase() == v);
            let mut s: Vec<Mapa> = match grupo {
                Some(g) => {
                    let buscados: Vec<String> = g.lista("archivos").map(|l| l.iter().map(Valor::texto_py).collect()).unwrap_or_default();
                    pesos.iter().filter(|p| buscados.contains(&nombre_de(p))).cloned().collect()
                }
                None => pesos.iter().filter(|p| nombre_de(p).to_lowercase().contains(&v)).cloned().collect(),
            };
            s.extend(pesos.iter().filter(|p| nombre_de(p).to_lowercase().contains("mmproj")).cloned());
            s
        }
        _ => pesos.clone(),
    };
    let bytes_configs: i128 = configs.iter().map(bytes_de).sum();
    let bytes_pesos: i128 = seleccion.iter().map(bytes_de).sum();
    let autor = repo.split('/').next().unwrap_or("").to_string();
    let nombre = repo.rsplit('/').next().unwrap_or("").to_string();
    let g = match datos.valor("gguf") {
        Valor::Mapa(m) => m.clone(),
        _ => Mapa::new(),
    };
    let es_gguf = !gguf.is_empty();
    Ok(Mapa::new()
        .con("ok", true)
        .con("repo_id", repo.as_str())
        .con("url_hf", format!("{BASE_HF}/{repo}"))
        .con("autor", autor.as_str())
        .con("nombre", nombre.as_str())
        .con("variante_elegida", elegida.map(Valor::Texto).unwrap_or(Valor::Nulo))
        .con("carpeta_sugerida", py::join(CARPETA_DEFECTO, &format!("{autor}__{nombre}")))
        .con("requiere_licencia", datos.valor("gated").verdad())
        .con("arquitectura", g.valor("architecture").clone())
        .con("context_length", g.valor("context_length").clone())
        .con("chat_template", g.valor("chat_template").clone())
        .con("total_archivos_repo", siblings.len() as i128)
        .con("archivos_config", lista(configs))
        .con("bytes_configs", bytes_configs)
        .con("archivos_pesos_seleccionados", lista(seleccion))
        .con("bytes_pesos_seleccionados", bytes_pesos)
        .con("total_bytes_respaldo", bytes_configs + bytes_pesos)
        .con("variantes_gguf", lista(variantes))
        .con("es_gguf", es_gguf))
}

/// `descargar_archivo_individual`: por trozos a un `.part` (continúa con `Range` si ya hay uno) y se renombra al
/// terminar
pub fn descargar_archivo(url: &str, destino: &str, cab: &[(String, String)], cancelar: &AtomicBool,
                         trozo: &mut dyn FnMut(usize)) -> Result<i128, String> {
    py::makedirs(&py::dirname(&py::abspath(destino)))?;
    let part = format!("{destino}.part");
    let mut existentes = std::fs::metadata(&part).ok().filter(|m| m.is_file()).map(|m| m.len() as i128).unwrap_or(0);
    let cliente = reqwest::blocking::Client::builder()
        .connect_timeout(Duration::from_secs(15))
        .timeout(None)
        .build()
        .map_err(|e| e.to_string())?;
    let mut rb = cliente.get(url);
    for (k, v) in cab {
        rb = rb.header(k.as_str(), v.as_str());
    }
    if existentes > 0 {
        rb = rb.header("Range", format!("bytes={existentes}-"));
    }
    let mut r = rb.send().map_err(|e| e.to_string())?;
    let estado = r.status().as_u16();
    let anadir = estado == 206 && existentes > 0;
    if !anadir {
        existentes = 0;
    }
    if estado != 200 && estado != 206 {
        return Err(format!("Error descargando {}: HTTP {estado}", py::basename(destino)));
    }
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .append(anadir)
        .truncate(!anadir)
        .open(&part)
        .map_err(|e| py::error_os(&e, &part))?;
    let mut buf = vec![0u8; 512 * 1024];
    let mut sesion: i128 = 0;
    loop {
        let n = r.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        if cancelar.load(Ordering::SeqCst) {
            return Err("Descarga cancelada por el usuario.".into());
        }
        f.write_all(&buf[..n]).map_err(|e| py::error_os(&e, &part))?;
        sesion += n as i128;
        trozo(n);
    }
    drop(f);
    if std::path::Path::new(destino).exists() {
        std::fs::remove_file(destino).map_err(|e| py::error_os(&e, destino))?;
    }
    std::fs::rename(&part, destino).map_err(|e| py::error_os(&e, &part))?;
    Ok(existentes + sesion)
}

/// `time.strftime("%Y-%m-%dT%H:%M:%SZ")` (hora local, con la Z de Python)
fn marca_local() -> String {
    let s = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) as libc::time_t;
    // SAFETY: localtime_r escribe en la estructura que se le da
    unsafe {
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&s, &mut tm);
        format!(
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
            tm.tm_year + 1900,
            tm.tm_mon + 1,
            tm.tm_mday,
            tm.tm_hour,
            tm.tm_min,
            tm.tm_sec
        )
    }
}

/// `ejecutar_descarga_completa_hf`: inspecciona, comprueba el espacio, baja la configuración y los pesos elegidos
/// (lo que ya está con su tamaño exacto se salta) y escribe el manifiesto y el Modelfile. `fijar` recibe los cambios
/// de la descarga (fase, total, completado, velocidad, restante_s)
pub fn descargar_completo(repo: &str, variante: Option<&str>, destino: Option<&str>, espacio: &str, cancelar: &AtomicBool,
                          fijar: &dyn Fn(Mapa)) -> Result<Mapa, String> {
    let ws = if espacio.is_empty() { py::getcwd() } else { espacio.to_string() };
    let token = obtener_token();
    let cab = cabeceras(token.as_deref());
    fijar(Mapa::new().con("fase", "Consultando catálogo e inspeccionando archivos en Hugging Face"));
    let info = inspeccionar(repo, variante, token.as_deref()).map_err(|e| e.texto())?;
    let dest = match destino.filter(|d| !d.is_empty()) {
        Some(d) => py::abspath(d),
        None => py::join(&ws, &info.valor("carpeta_sugerida").texto_py()),
    };
    py::makedirs(&dest)?;
    let de = |k: &str| -> Vec<Mapa> {
        info.lista(k).map(|l| l.iter().filter_map(|v| if let Valor::Mapa(m) = v { Some(m.clone()) } else { None }).collect()).unwrap_or_default()
    };
    let (configs, pesos) = (de("archivos_config"), de("archivos_pesos_seleccionados"));
    let todos: Vec<Mapa> = configs.iter().chain(pesos.iter()).cloned().collect();
    let total: i128 = todos.iter().map(bytes_de).sum();
    if let Some(libre) = crate::descargas::libre(&dest) {
        if (libre as f64) < total as f64 * 1.03 {
            return Err(format!(
                "Espacio insuficiente: hacen falta {:.2} GB y solo quedan {:.2} GB libres.",
                total as f64 / 1e9,
                libre as f64 / 1e9
            ));
        }
    }
    fijar(Mapa::new().con("total", total).con("completado", 0).con("fase", "Iniciando descarga de respaldo"));
    let n = todos.len();
    let mut acumulado: i128 = 0;
    let mut muestras: Vec<(Instant, i128)> = Vec::new();
    for (i, a) in todos.iter().enumerate() {
        if cancelar.load(Ordering::SeqCst) {
            return Err("Descarga cancelada.".into());
        }
        let nombre = a.valor("nombre").texto_py();
        let local = py::join(&dest, &nombre);
        fijar(Mapa::new().con("fase", format!("Descargando [{}/{n}] {nombre}", i + 1)));
        let b = bytes_de(a);
        if b > 0 && std::fs::metadata(&local).map(|m| m.is_file() && m.len() as i128 == b).unwrap_or(false) {
            acumulado += b;
            fijar(Mapa::new().con("completado", acumulado));
            continue;
        }
        let mut trozo = |t: usize| {
            acumulado += t as i128;
            let ya = Instant::now();
            muestras.push((ya, acumulado));
            muestras.retain(|m| ya.duration_since(m.0).as_secs_f64() <= 8.0);
            let vel = match (muestras.first(), muestras.last()) {
                (Some(p), Some(u)) if muestras.len() >= 2 && u.0 > p.0 => Some((u.1 - p.1) as f64 / u.0.duration_since(p.0).as_secs_f64()),
                _ => None,
            };
            let restante = vel.filter(|v| *v > 0.0).map(|v| (total - acumulado) as f64 / v);
            let opt = |x: Option<f64>| x.map(Valor::Real).unwrap_or(Valor::Nulo);
            fijar(Mapa::new().con("completado", acumulado).con("velocidad", opt(vel)).con("restante_s", opt(restante)));
        };
        descargar_archivo(&a.valor("url").texto_py(), &local, &cab, cancelar, &mut trozo)?;
    }
    fijar(Mapa::new().con("fase", "Generando manifiesto de respaldo y Modelfile"));
    let nombres = |l: &[Mapa]| Valor::Lista(l.iter().map(|a| a.valor("nombre").clone()).collect());
    let variante_sel = info.valor("variante_elegida");
    let manifiesto = Mapa::new()
        .con("origen", "huggingface")
        .con("repo_id", repo)
        .con("url_origen", info.valor("url_hf").clone())
        .con("fecha_respaldo", marca_local())
        .con("variante_seleccionada", if variante_sel.verdad() { variante_sel.clone() } else { Valor::from("completo") })
        .con("total_archivos", n as i128)
        .con("total_bytes", total)
        .con("archivos_configuracion", nombres(&configs))
        .con("archivos_pesos", nombres(&pesos))
        .con("preservado_contra_borrado", true)
        .con(
            "nota",
            "Copia completa con todos los archivos de configuración y pesos preservados localmente para uso autónomo por si se borra de Hugging Face.",
        );
    let ruta_manifiesto = py::join(&dest, "prig_backup_manifest.json");
    prig_plataforma::escribir_json(std::path::Path::new(&ruta_manifiesto), &Valor::Mapa(manifiesto), 2)?;
    if let Some(principal) = pesos.iter().map(|a| a.valor("nombre").texto_py()).find(|n| n.to_lowercase().ends_with(".gguf")) {
        let plantilla = info.valor("chat_template");
        let plantilla = if plantilla.verdad() { plantilla.texto_py() } else { String::new() };
        let mut t = format!("# Modelfile generado por Prig IDE para respaldo de {repo}\nFROM ./{principal}\n\n");
        if !plantilla.is_empty() && plantilla.chars().count() < 4000 {
            t.push_str(&format!("TEMPLATE \"\"\"{plantilla}\"\"\"\n\n"));
        }
        t.push_str("# Respaldo local completo preservado offline\n");
        py::escribir_texto(&py::join(&dest, "Modelfile"), &t)?;
    }
    let relativa = py::relpath(&dest, &ws);
    fijar(
        Mapa::new()
            .con("completado", total)
            .con("velocidad", Valor::Nulo)
            .con("restante_s", Valor::Nulo)
            .con("fase", format!("Respaldo completo guardado en {relativa}")),
    );
    Ok(Mapa::new()
        .con("ok", true)
        .con("repo_id", repo)
        .con("carpeta", dest.as_str())
        .con("carpeta_relativa", relativa)
        .con("total_archivos", n as i128)
        .con("total_bytes", total)
        .con("manifiesto", ruta_manifiesto))
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn limpia_las_referencias() {
        assert_eq!(limpiar_repo("hf.co/unsloth/Qwen3-8B-GGUF:Q4_K_M"), ("unsloth/Qwen3-8B-GGUF".into(), Some("Q4_K_M".into())));
        assert_eq!(limpiar_repo("https://huggingface.co/Qwen/Qwen2.5-Coder-7B"), ("Qwen/Qwen2.5-Coder-7B".into(), None));
        assert_eq!(limpiar_repo("https://huggingface.co/a/b/tree/main/x"), ("a/b".into(), None));
        assert_eq!(limpiar_repo(" models/a/b: "), ("a/b".into(), None));
    }

    #[test]
    fn distingue_la_configuracion() {
        assert!(es_archivo_config("sub/README.md", 10));
        assert!(es_archivo_config("imatrix_x.dat", 10));
        assert!(es_archivo_config("notas.txt", 10));
        assert!(!es_archivo_config("enorme.json", 60 * 1024 * 1024));
        assert!(!es_archivo_config("m.gguf", 10));
    }

    #[test]
    fn un_repo_no_valido_falla_sin_red() {
        let e = inspeccionar("a b", None, None).unwrap_err();
        assert!(matches!(e, ErrorHf::Otro(t) if t == "Identificador de repositorio Hugging Face no válido: 'a b'"));
    }
}
