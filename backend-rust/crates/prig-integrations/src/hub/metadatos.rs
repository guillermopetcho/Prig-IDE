//! Títulos de los enlaces (`hub/metadatos.py`): cuando el usuario pega un enlace sin título, Prig lo busca.
//!
//! Solo metadatos públicos y livianos: el oEmbed de YouTube (título y canal, sin clave) y, para el resto, el <title>
//! u og:title de la página, leyendo como mucho 256 KB. Se guarda en caché (una semana) para no repetir peticiones.
//! Si falla, no pasa nada: el elemento se guarda con su enlace y el título queda vacío.

use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use std::time::Duration;

const UA: &str = "Mozilla/5.0 (X11; Linux x86_64) Prig-IDE/1.0 (Prig Hub; lee solo el título)";
const SEMANA: f64 = 7.0 * 24.0 * 3600.0;
const MAX_BYTES: usize = 256 * 1024;
static CERROJO: Mutex<()> = Mutex::new(());

static PATRONES_TITULO: LazyLock<[Regex; 3]> = LazyLock::new(|| {
    [
        Regex::new(r#"(?is)<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)"#).unwrap(),
        Regex::new(r#"(?is)<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:title"#).unwrap(),
        Regex::new(r"(?is)<title[^>]*>(.*?)</title>").unwrap(),
    ]
});
static PATRONES_IMAGEN: LazyLock<[Regex; 2]> = LazyLock::new(|| {
    [
        Regex::new(r#"(?is)<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)"#).unwrap(),
        Regex::new(r#"(?is)<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image"#).unwrap(),
    ]
});
static ESPACIOS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s+").unwrap());
static SITIO: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\s*[|·–-]\s*(YouTube|Kaggle|GitHub|Coursera|Udemy|Hugging Face)\s*$").unwrap());

fn ruta_cache(base: &Path) -> PathBuf {
    base.join("cache").join("titulos.json")
}

fn cache(base: &Path) -> Mapa {
    match std::fs::read_to_string(ruta_cache(base)).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    }
}

fn guardar_cache(base: &Path, datos: &Mapa) {
    let ruta = ruta_cache(base);
    if let Some(p) = ruta.parent() {
        let _ = std::fs::create_dir_all(p);
    }
    let saltar = datos.len().saturating_sub(3000);
    let mut ultimos = Mapa::new();
    for (k, v) in datos.iter().skip(saltar) {
        ultimos.poner(k.clone(), v.clone());
    }
    let tmp = PathBuf::from(format!("{}.tmp", ruta.display()));
    if std::fs::write(&tmp, prig_plataforma::json::escribir_linea(&Valor::Mapa(ultimos))).is_ok() {
        let _ = std::fs::rename(&tmp, &ruta);
    }
}

fn cliente() -> Option<reqwest::blocking::Client> {
    reqwest::blocking::Client::builder().timeout(Duration::from_secs(6)).build().ok()
}

fn corto(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

fn youtube(url: &str) -> Option<Mapa> {
    let r = cliente()?.get("https://www.youtube.com/oembed").query(&[("url", url), ("format", "json")]).header("User-Agent", UA).send().ok()?;
    if r.status().as_u16() != 200 {
        return None;
    }
    let Valor::Mapa(d) = prig_plataforma::json::leer(&r.text().ok()?).ok()? else { return None };
    let o = |k: &str| if d.valor(k).verdad() { d.valor(k).texto_py() } else { String::new() };
    let mut res = Mapa::new().con("titulo", corto(&o("title"), 200)).con("autor", corto(&o("author_name"), 100));
    if d.valor("thumbnail_url").verdad() {
        res.poner("miniatura", corto(&d.valor("thumbnail_url").texto_py(), 500));
    }
    Some(res)
}

/// El texto de la página como lo decodifica requests: el charset de la cabecera o, para text/*, ISO-8859-1
fn decodificar(b: &[u8], tipo: &str) -> String {
    let bajo = tipo.to_lowercase();
    let charset = bajo.split(';').skip(1).find_map(|p| p.trim().strip_prefix("charset=").map(|c| c.trim_matches(['"', '\''])).map(String::from));
    let latin1 = |b: &[u8]| b.iter().map(|&c| c as char).collect::<String>();
    match charset.as_deref() {
        Some("iso-8859-1" | "latin-1" | "latin1") => latin1(b),
        Some(_) => String::from_utf8_lossy(b).into_owned(),
        None if bajo.contains("text") => latin1(b),
        None => String::from_utf8_lossy(b).into_owned(),
    }
}

fn pagina(url: &str) -> Option<Mapa> {
    let mut r = cliente()?.get(url).header("User-Agent", UA).send().ok()?;
    let tipo = r.headers().get("Content-Type").and_then(|v| v.to_str().ok()).unwrap_or("").to_string();
    if r.status().as_u16() != 200 || !tipo.contains("html") {
        return None;
    }
    let mut trozo: Vec<u8> = Vec::new();
    let mut buf = vec![0u8; 16384];
    loop {
        let n = r.read(&mut buf).ok()?;
        if n == 0 {
            break;
        }
        trozo.extend_from_slice(&buf[..n]);
        if trozo.len() >= MAX_BYTES || trozo.to_ascii_lowercase().windows(7).any(|w| w == b"</head>") {
            break;
        }
    }
    let texto = decodificar(&trozo, &tipo);
    let mut res = Mapa::new();
    for p in PATRONES_TITULO.iter() {
        if let Some(m) = p.captures(&texto) {
            let t = ESPACIOS.replace_all(&prig_plataforma::html::unescape(&m[1]), " ").trim().to_string();
            let t = SITIO.replace(&t, "").into_owned();
            if !t.is_empty() {
                res.poner("titulo", corto(&t, 200));
                break;
            }
        }
    }
    for p in PATRONES_IMAGEN.iter() {
        if let Some(m) = p.captures(&texto) {
            let img = prig_plataforma::html::unescape(&m[1]).trim().to_string();
            if img.starts_with("http") {
                res.poner("miniatura", corto(&img, 500));
                break;
            }
        }
    }
    if res.is_empty() { None } else { Some(res) }
}

fn ahora() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

/// `titulo(base, info)`: {"titulo", "autor"?…} de un enlace reconocido; {} si no se pudo
pub fn titulo(base: &Path, info: &Mapa) -> Mapa {
    let clave = info.texto("clave").unwrap_or("").to_string();
    let guardado = {
        let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
        cache(base).get(&clave).cloned()
    };
    if let Some(Valor::Mapa(g)) = &guardado {
        if !g.is_empty() && ahora() - g.num("ts").unwrap_or(0.0) < SEMANA {
            let mut s = Mapa::new();
            for (k, v) in g.iter() {
                if k != "ts" {
                    s.poner(k.clone(), v.clone());
                }
            }
            return s;
        }
    }
    let plataforma = info.texto("plataforma").unwrap_or("");
    let tipo = info.texto("tipo").unwrap_or("");
    let url = info.texto("url").unwrap_or("");
    let datos = if plataforma == "youtube" {
        youtube(url)
    } else if plataforma == "github" && (tipo == "repositorio" || tipo == "persona") {
        Some(Mapa::new().con("titulo", info.valor("ref").clone()))
    } else {
        pagina(url)
    }
    .unwrap_or_default();
    // Un fallo (sin conexión, página caída) se recuerda solo una hora, no una semana
    let ts = if datos.is_empty() { ahora() - SEMANA + 3600.0 } else { ahora() };
    {
        let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
        let mut c = cache(base);
        c.poner(clave, datos.clone().con("ts", ts));
        guardar_cache(base, &c);
    }
    datos
}
