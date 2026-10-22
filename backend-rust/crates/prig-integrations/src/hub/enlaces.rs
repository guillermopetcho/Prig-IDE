//! Reconocer enlaces (`hub/enlaces.py`): de qué plataforma son, qué tipo de elemento y cuál es su clave estable.
//!
//! La clave canónica es la identidad de un elemento en Prig Hub. Varias formas de escribir el mismo enlace dan la
//! misma clave (youtu.be/x, m.youtube.com/watch?v=x&t=30 → youtube:video:x), así que el progreso no se pierde al
//! reordenar ni se duplica entre packs.
//!
//! ```text
//! reconocer(url) → {"url", "plataforma", "tipo", "clave", "ref", "prig"}
//! ```

use prig_plataforma::valor::Mapa;
use regex::Regex;
use std::sync::LazyLock;

pub const TIPOS_RECURSO: [&str; 12] =
    ["curso", "video", "lista", "notebook", "dataset", "competicion", "repositorio", "archivo", "modelo", "articulo", "ejercicio", "web"];

pub fn es_tipo(t: &str) -> bool {
    t == "persona" || TIPOS_RECURSO.contains(&t)
}

pub const PLATAFORMAS: [(&str, &str); 17] = [
    ("github", "GitHub"),
    ("kaggle", "Kaggle"),
    ("youtube", "YouTube"),
    ("huggingface", "Hugging Face"),
    ("coursera", "Coursera"),
    ("udemy", "Udemy"),
    ("edx", "edX"),
    ("freecodecamp", "freeCodeCamp"),
    ("platzi", "Platzi"),
    ("exercism", "Exercism"),
    ("leetcode", "LeetCode"),
    ("arxiv", "arXiv"),
    ("gitlab", "GitLab"),
    ("codeberg", "Codeberg"),
    ("linkedin", "LinkedIn"),
    ("x", "X"),
    ("web", "Web"),
];

pub fn plataformas() -> Mapa {
    let mut m = Mapa::new();
    for (k, v) in PLATAFORMAS {
        m.poner(k, v);
    }
    m
}

/// `PLATAFORMAS.get(p, p)`
pub fn nombre_plataforma(p: &str) -> String {
    PLATAFORMAS.iter().find(|(k, _)| *k == p).map(|(_, v)| v.to_string()).unwrap_or_else(|| p.to_string())
}

const RESERVADAS_GITHUB: [&str; 17] = [
    "settings", "orgs", "topics", "trending", "explore", "marketplace", "sponsors", "features", "about", "pricing", "login", "join",
    "search", "notifications", "collections", "events", "apps",
];
const RESERVADAS_KAGGLE: [&str; 15] = [
    "code", "datasets", "competitions", "c", "models", "learn", "discussions", "search", "account", "settings", "docs", "rankings",
    "organizations", "benchmarks", "static",
];
const RESERVADAS_HF: [&str; 15] = [
    "models", "datasets", "spaces", "docs", "blog", "learn", "papers", "pricing", "settings", "login", "join", "organizations",
    "collections", "posts", "tasks",
];

static SEGURO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9_.\-]{1,100}$").unwrap());
static ID_YT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9_\-]{6,20}$").unwrap());
static QUITAR_PARAMS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)^(utm_.*|fbclid|gclid|si|feature|ref|ref_src|source)\n?$").unwrap());
static HTTP: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)^https?://").unwrap());
static DOMINIO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)^[\w.-]+\.[a-z]{2,}(/|$)").unwrap());
static ARXIV: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(v\d+)?(\.pdf)?$").unwrap());

#[derive(Debug, Clone)]
pub struct EnlaceInvalido(pub String);

impl std::fmt::Display for EnlaceInvalido {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn corto(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

/// Lo que `urllib.parse.urlsplit` saca de un enlace http(s)
struct Partido {
    netloc: String,
    path: String,
    query: String,
}

fn urlsplit(url: &str) -> Partido {
    // urlsplit quita los tabuladores y saltos de línea de cualquier sitio
    let u: String = url.chars().filter(|c| !matches!(c, '\t' | '\r' | '\n')).collect();
    let resto = match u.find(':') {
        Some(i) => &u[i + 1..],
        None => &u[..],
    };
    let (netloc, mut resto) = if let Some(r) = resto.strip_prefix("//") {
        let fin = r.find(['/', '?', '#']).unwrap_or(r.len());
        (r[..fin].to_string(), r[fin..].to_string())
    } else {
        (String::new(), resto.to_string())
    };
    if let Some(i) = resto.find('#') {
        resto.truncate(i);
    }
    let (path, query) = match resto.find('?') {
        Some(i) => (resto[..i].to_string(), resto[i + 1..].to_string()),
        None => (resto, String::new()),
    };
    Partido { netloc, path, query }
}

/// `SplitResult.hostname`
fn hostname(netloc: &str) -> String {
    let info = netloc.rsplit_once('@').map(|x| x.1).unwrap_or(netloc);
    let h = match info.split_once('[') {
        Some((_, b)) => b.split_once(']').map(|x| x.0).unwrap_or(b),
        None => info.split_once(':').map(|x| x.0).unwrap_or(info),
    };
    h.to_lowercase()
}

fn host_limpio(h: &str) -> String {
    let mut h = h.to_lowercase().split(':').next().unwrap_or("").to_string();
    for p in ["www.", "m.", "mobile."] {
        if let Some(r) = h.strip_prefix(p) {
            h = r.to_string();
        }
    }
    h
}

fn hex(c: u8) -> Option<u8> {
    (c as char).to_digit(16).map(|d| d as u8)
}

/// `urllib.parse.unquote` (utf-8, con reemplazo)
fn unquote(t: &str) -> String {
    if !t.contains('%') {
        return t.to_string();
    }
    let b = t.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let (Some(a), Some(c)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push(a * 16 + c);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// `parse_qsl(q, keep_blank_values=False)` pasado a `dict`: la última aparición gana, en el sitio de la primera
fn parse_qs(q: &str) -> Mapa {
    let mut m = Mapa::new();
    for trozo in q.split('&') {
        if trozo.is_empty() {
            continue;
        }
        let Some((k, v)) = trozo.split_once('=') else { continue };
        if v.is_empty() {
            continue;
        }
        m.poner(unquote(&k.replace('+', " ")), unquote(&v.replace('+', " ")));
    }
    m
}

/// `quote_plus(t, safe='')`
fn quote_plus(t: &str) -> String {
    let mut s = String::new();
    for b in t.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => s.push(b as char),
            b' ' => s.push('+'),
            b => s.push_str(&format!("%{b:02X}")),
        }
    }
    s
}

struct Partes {
    host: String,
    tramos: Vec<String>,
    params: Mapa,
    query: String,
}

/// `partes(url)`: (host, tramos de la ruta, parámetros) de un enlace http(s)
fn partes(url: &str) -> Result<Partes, EnlaceInvalido> {
    let mut texto = prig_plataforma::py::strip(url).to_string();
    if texto.is_empty() {
        return Err(EnlaceInvalido("El enlace está vacío.".into()));
    }
    if !HTTP.is_match(&texto) {
        if DOMINIO.is_match(&texto) {
            texto = format!("https://{texto}");
        } else {
            return Err(EnlaceInvalido(format!("«{}» no es un enlace web (http o https).", corto(&texto, 80))));
        }
    }
    let s = urlsplit(&texto);
    let host = host_limpio(&hostname(&s.netloc));
    if host.is_empty() || !host.contains('.') {
        return Err(EnlaceInvalido(format!("«{}» no tiene un dominio válido.", corto(&texto, 80))));
    }
    let tramos = s.path.split('/').filter(|t| !t.is_empty()).map(String::from).collect();
    Ok(Partes { host, tramos, params: parse_qs(&s.query), query: s.query })
}

fn res(url: &str, plataforma: &str, tipo: &str, id: &str, r#ref: Option<&str>, prig: bool) -> Mapa {
    Mapa::new()
        .con("url", url)
        .con("plataforma", plataforma)
        .con("tipo", tipo)
        .con("clave", format!("{plataforma}:{tipo}:{id}"))
        .con("ref", r#ref.unwrap_or(id))
        .con("prig", prig)
}

fn es_prig(repo: &str) -> bool {
    let r = repo.to_lowercase();
    r == "prig" || r.starts_with("prig-")
}

fn github(url: &str, t: &[String]) -> Option<Mapa> {
    let u = t.first()?.to_lowercase();
    if RESERVADAS_GITHUB.contains(&u.as_str()) || !SEGURO.is_match(&u) {
        return None;
    }
    if t.len() == 1 {
        return Some(res(url, "github", "persona", &u, None, false));
    }
    let mut repo = t[1].to_lowercase();
    if repo.ends_with(".git") {
        repo.truncate(repo.len() - 4);
    }
    if !SEGURO.is_match(&repo) {
        return None;
    }
    let r = format!("{u}/{repo}");
    if t.len() >= 4 && (t[2] == "blob" || t[2] == "tree") {
        let ruta = t[4..].join("/");
        if t[2] == "blob" && !ruta.is_empty() {
            return Some(res(url, "github", "archivo", &format!("{r}/{ruta}"), Some(&r), false));
        }
    }
    Some(res(url, "github", "repositorio", &r, None, es_prig(&repo)))
}

fn git_generico(plataforma: &str, url: &str, t: &[String]) -> Option<Mapa> {
    if t.len() < 2 || !t[..2].iter().all(|x| SEGURO.is_match(x)) {
        return match t.first() {
            Some(x) if SEGURO.is_match(x) => Some(res(url, plataforma, "persona", &x.to_lowercase(), None, false)),
            _ => None,
        };
    }
    let bajo = t[1].to_lowercase();
    let repo = bajo.strip_suffix(".git").unwrap_or(&bajo);
    Some(res(url, plataforma, "repositorio", &format!("{}/{repo}", t[0].to_lowercase()), None, es_prig(repo)))
}

fn kaggle(url: &str, tramos: &[String]) -> Option<Mapa> {
    if tramos.is_empty() {
        return None;
    }
    let t: Vec<String> = tramos.iter().map(|x| x.to_lowercase()).collect();
    let k = |tipo: &str, id: String| Some(res(url, "kaggle", tipo, &id, None, false));
    match t[0].as_str() {
        "code" if t.len() >= 3 => return k("notebook", format!("{}/{}", t[1], t[2])),
        "datasets" if t.len() >= 3 => return k("dataset", format!("{}/{}", t[1], t[2])),
        "competitions" | "c" if t.len() >= 2 => return k("competicion", t[1].clone()),
        "models" if t.len() >= 3 => return k("modelo", format!("{}/{}", t[1], t[2])),
        "learn" if t.len() >= 2 => return k("curso", t[1].clone()),
        _ => {}
    }
    if RESERVADAS_KAGGLE.contains(&t[0].as_str()) {
        return None;
    }
    if t.len() >= 2 && SEGURO.is_match(&t[1]) {
        return k("notebook", format!("{}/{}", t[0], t[1]));
    }
    if SEGURO.is_match(&t[0]) {
        k("persona", t[0].clone())
    } else {
        None
    }
}

fn youtube(url: &str, t: &[String], params: &Mapa, host: &str) -> Option<Mapa> {
    let y = |tipo: &str, id: &str| Some(res(url, "youtube", tipo, id, None, false));
    if host == "youtu.be" && t.first().is_some_and(|x| ID_YT.is_match(x)) {
        return y("video", &t[0]);
    }
    let lista = params.texto("list").unwrap_or("");
    if t.first().is_some_and(|x| x == "playlist") && !lista.is_empty() {
        return y("lista", lista);
    }
    let v = params.texto("v").unwrap_or("");
    if t.first().is_some_and(|x| x == "watch") && ID_YT.is_match(v) {
        return y("video", v);
    }
    if t.len() >= 2 && ["shorts", "live", "embed"].contains(&t[0].as_str()) && ID_YT.is_match(&t[1]) {
        return y("video", &t[1]);
    }
    if t.first().is_some_and(|x| x.starts_with('@')) {
        return y("persona", &t[0].to_lowercase());
    }
    if t.len() >= 2 && ["channel", "c", "user"].contains(&t[0].as_str()) {
        let id = format!("{}/{}", t[0], if t[0] == "channel" { t[1].clone() } else { t[1].to_lowercase() });
        return y("persona", &id);
    }
    None
}

fn huggingface(url: &str, t: &[String]) -> Option<Mapa> {
    let h = |tipo: &str, id: String| Some(res(url, "huggingface", tipo, &id, None, false));
    let primero = t.first()?;
    if (primero == "datasets" || primero == "spaces") && t.len() >= 3 {
        return h(if primero == "datasets" { "dataset" } else { "web" }, format!("{}/{}/{}", t[0], t[1], t[2]).to_lowercase());
    }
    if primero == "learn" && t.len() >= 2 {
        return h("curso", t[1].to_lowercase());
    }
    if RESERVADAS_HF.contains(&primero.as_str()) {
        return None;
    }
    if t.len() >= 2 {
        return h("modelo", format!("{}/{}", t[0], t[1]).to_lowercase());
    }
    h("persona", t[0].to_lowercase())
}

fn cursos(url: &str, host: &str, tramos: &[String]) -> Option<Mapa> {
    let t: Vec<String> = tramos.iter().map(|x| x.to_lowercase()).collect();
    let r = |p: &str, tipo: &str, id: String| Some(res(url, p, tipo, &id, None, false));
    let t0 = t.first().map(String::as_str).unwrap_or("");
    if host.ends_with("coursera.org") && t.len() >= 2 && ["learn", "specializations", "professional-certificates", "projects"].contains(&t0) {
        return r("coursera", "curso", format!("{}/{}", t[0], t[1]));
    }
    if host.ends_with("udemy.com") && t.len() >= 2 && t0 == "course" {
        return r("udemy", "curso", t[1].clone());
    }
    if host.ends_with("edx.org") && t.len() >= 2 && ["learn", "course", "professional-certificate"].contains(&t0) {
        return r("edx", "curso", t[..t.len().min(3)].join("/"));
    }
    if host.ends_with("freecodecamp.org") && t0 == "learn" {
        let id = t[1..t.len().min(3)].join("/");
        return r("freecodecamp", "curso", if id.is_empty() { "learn".into() } else { id });
    }
    if host.ends_with("platzi.com") && t.len() >= 2 && t0 == "cursos" {
        return r("platzi", "curso", t[1].clone());
    }
    if host.ends_with("exercism.org") && t.len() >= 4 && t0 == "tracks" && t[2] == "exercises" {
        return r("exercism", "ejercicio", format!("{}/{}", t[1], t[3]));
    }
    if host.ends_with("leetcode.com") && t.len() >= 2 && t0 == "problems" {
        return r("leetcode", "ejercicio", t[1].clone());
    }
    if host == "arxiv.org" && t.len() >= 2 && (t0 == "abs" || t0 == "pdf") {
        return r("arxiv", "articulo", ARXIV.replacen(&t[1], 1, "").into_owned());
    }
    if host.ends_with("linkedin.com") && t.len() >= 2 && t0 == "in" {
        return r("linkedin", "persona", t[1].clone());
    }
    if (host == "x.com" || host == "twitter.com") && t.len() == 1 && SEGURO.is_match(&t[0]) {
        return r("x", "persona", t[0].clone());
    }
    None
}

/// `normalizar(url)`: https, sin www., sin barra final, sin parámetros de seguimiento ni ancla
pub fn normalizar(url: &str) -> Result<String, EnlaceInvalido> {
    let p = partes(url)?;
    let mut limpios: Vec<(String, String)> =
        p.params.iter().filter(|(k, _)| !QUITAR_PARAMS.is_match(k)).map(|(k, v)| (k.clone(), v.texto_py())).collect();
    limpios.sort();
    let ruta = if p.tramos.is_empty() { String::new() } else { format!("/{}", p.tramos.join("/")) };
    let consulta = if limpios.is_empty() {
        String::new()
    } else {
        format!("?{}", limpios.iter().map(|(k, v)| format!("{}={}", quote_plus(k), quote_plus(v))).collect::<Vec<_>>().join("&"))
    };
    Ok(format!("https://{}{ruta}{consulta}", p.host))
}

/// `reconocer(url)`: plataforma, tipo y clave estable. Todo enlace http(s) válido se reconoce (como mínimo, «web»)
pub fn reconocer(url: &str) -> Result<Mapa, EnlaceInvalido> {
    let limpio = normalizar(url)?;
    let p = partes(&limpio)?;
    let (host, t) = (p.host.as_str(), &p.tramos[..]);
    let r = match host {
        "github.com" => github(&limpio, t),
        "gitlab.com" => git_generico("gitlab", &limpio, t),
        "codeberg.org" => git_generico("codeberg", &limpio, t),
        "kaggle.com" => kaggle(&limpio, t),
        "youtube.com" | "youtu.be" | "music.youtube.com" => youtube(&limpio, t, &p.params, host),
        "huggingface.co" | "hf.co" => huggingface(&limpio, t),
        _ => cursos(&limpio, host, t),
    };
    if let Some(r) = r {
        return Ok(r);
    }
    let id = if t.is_empty() { host.to_string() } else { format!("{host}/{}", t.join("/")) };
    let id = if p.query.is_empty() { id } else { format!("{id}?{}", p.query) };
    Ok(res(&limpio, "web", if t.is_empty() { "web" } else { "articulo" }, &id.to_lowercase(), None, false))
}

/// `url_git(url)`: la URL para clonar un repositorio de GitHub, GitLab o Codeberg
pub fn url_git(url: &str) -> Option<String> {
    let info = reconocer(url).ok()?;
    if info.texto("tipo") != Some("repositorio") {
        return None;
    }
    let dominio = match info.texto("plataforma")? {
        "github" => "github.com",
        "gitlab" => "gitlab.com",
        "codeberg" => "codeberg.org",
        _ => return None,
    };
    Some(format!("https://{dominio}/{}.git", info.texto("ref")?))
}

/// Un campo de texto de la ficha de un enlace
pub fn campo<'a>(info: &'a Mapa, k: &str) -> &'a str {
    info.texto(k).unwrap_or("")
}
