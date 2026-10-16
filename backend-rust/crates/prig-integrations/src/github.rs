//! GitHub (`github_lector.py`, sin el modelo): el token opcional, buscar repositorios, abrirlos (ficha, lenguajes,
//! árbol y README; un día en disco), leer archivos (en crudo, guardados por su sha), los guardados, descargar el
//! repositorio al proyecto y exportar las explicaciones ya hechas a Markdown o PDF.

use crate::kaggle::Fallo;
use crate::kaggle::ErrorKaggle as ErrorUsuario;
use prig_plataforma::py;
use prig_plataforma::valor::{redondear, Mapa, Valor};
use regex::Regex;
use sha1::{Digest, Sha1};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

fn error<T>(t: impl Into<String>) -> Result<T, Fallo> {
    Err(Fallo::Usuario(ErrorUsuario(t.into())))
}

fn entorno(v: &str) -> Option<String> {
    std::env::var(v).ok().filter(|x| !x.is_empty())
}

fn api() -> String {
    entorno("PRIG_GITHUB_API").unwrap_or_else(|| "https://api.github.com".into())
}
fn raw() -> String {
    entorno("PRIG_GITHUB_RAW").unwrap_or_else(|| "https://raw.githubusercontent.com".into())
}
fn codeload() -> String {
    entorno("PRIG_GITHUB_CODELOAD").unwrap_or_else(|| "https://codeload.github.com".into())
}

const UA: &str = "Prig-IDE (lector de repositorios; uso educativo local)";
const ACCEPT: &str = "application/vnd.github+json";
const MAX_ARCHIVO: f64 = 400_000.0;
pub const CARPETA_REPOS: &str = "github_repos";
pub const CARPETA_EXPORT: &str = "github_explicaciones";

static REF_VALIDA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9_.\-]{1,100}/[A-Za-z0-9_.\-]{1,100}$").unwrap());
static ENLACE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"github\.com[/:]([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)").unwrap());
static BINARIOS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)\.(png|jpe?g|gif|webp|ico|bmp|pdf|zip|gz|tar|whl|so|dll|exe|bin|pkl|pt|pth|h5|onnx|npy|npz|parquet|mp[34]|wav|ttf|woff2?|eot|jar|class|pyc)$").unwrap()
});
static README: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)^readme(\.(md|rst|txt|markdown))?$").unwrap());

pub fn carpeta() -> PathBuf {
    PathBuf::from(entorno("PRIG_GITHUB_DIR").unwrap_or_else(|| py::expanduser("~/.prig_github")))
}

fn ruta_token() -> PathBuf {
    PathBuf::from(entorno("PRIG_GITHUB_CREDENCIALES").unwrap_or_else(|| py::expanduser("~/.prig_github.json")))
}

/// `_leer_json`: cualquier JSON (None si falta o está roto)
fn leer_json(ruta: &Path) -> Option<Valor> {
    prig_plataforma::json::leer(&std::fs::read_to_string(ruta).ok()?).ok()
}

/// `_escribir_json`: compacto, de una vez
fn escribir_json(ruta: &Path, v: &Valor) -> Result<(), Fallo> {
    std::fs::create_dir_all(ruta.parent().ok_or(Fallo::Interno)?).map_err(|_| Fallo::Interno)?;
    let tmp = PathBuf::from(format!("{}.tmp", ruta.display()));
    std::fs::write(&tmp, prig_plataforma::json::escribir_linea(v)).map_err(|_| Fallo::Interno)?;
    std::fs::rename(&tmp, ruta).map_err(|_| Fallo::Interno)
}

static CERROJO: Mutex<()> = Mutex::new(());

fn ahora_s() -> String {
    py::ahora_iso().chars().take(19).collect()
}

// ---------------------------------------------------------------------------------------------- token

/// `token()`: (token, origen)
fn token() -> Result<Option<(String, String)>, Fallo> {
    let g = match leer_json(&ruta_token()) {
        Some(Valor::Mapa(m)) => m,
        Some(v) if v.verdad() => return Err(Fallo::Interno),
        _ => Mapa::new(),
    };
    if g.verdad("token") {
        return Ok(Some((g.valor("token").texto_py(), "Prig".into())));
    }
    for v in ["GITHUB_TOKEN", "GH_TOKEN"] {
        if let Some(t) = entorno(v) {
            return Ok(Some((t, format!("variable {v}"))));
        }
    }
    Ok(None)
}

/// `estado()`
pub fn estado() -> Result<Mapa, Fallo> {
    let t = token()?;
    Ok(Mapa::new()
        .con("con_token", t.is_some())
        .con("origen", t.as_ref().map(|t| Valor::Texto(t.1.clone())).unwrap_or(Valor::Nulo))
        .con("limite", if t.is_some() { "5000 consultas por hora" } else { "60 consultas por hora y 10 búsquedas por minuto" })
        .con("url_token", "https://github.com/settings/tokens?type=beta"))
}

fn cliente(segundos: u64) -> Result<reqwest::blocking::Client, Fallo> {
    reqwest::blocking::Client::builder().timeout(Duration::from_secs(segundos)).build().map_err(|_| Fallo::Interno)
}

/// GET con las cabeceras de Prig (y el token, si hay; `con_token=false` para el crudo)
fn get(url: &str, params: &[(&str, String)], con_token: bool, token_propio: Option<&str>) -> Result<reqwest::blocking::Response, Fallo> {
    let mut r = cliente(30)?.get(url).query(params).header("User-Agent", UA).header("Accept", ACCEPT);
    let t = match token_propio {
        Some(t) => Some(t.to_string()),
        None if con_token => token()?.map(|t| t.0),
        None => None,
    };
    if let Some(t) = t {
        r = r.header("Authorization", format!("Bearer {t}"));
    }
    r.send().or_else(|_| error("Sin conexión con GitHub: comprueba internet."))
}

/// `guardar_token(texto)`: se comprueba con GitHub y se guarda con permisos 600
pub fn guardar_token(texto: &str) -> Result<Mapa, Fallo> {
    let t = py::strip(texto);
    if t.is_empty() || t.chars().any(char::is_whitespace) || t.chars().count() < 20 {
        return error("Pega el token completo (empieza por github_pat_ o ghp_).");
    }
    let r = get(&format!("{}/rate_limit", api()), &[], false, Some(t))?;
    if r.status().as_u16() == 401 {
        return error("GitHub no aceptó ese token.");
    }
    let doc = Mapa::new().con("token", t).con("guardado", ahora_s());
    let ruta = ruta_token();
    let tmp = PathBuf::from(format!("{}.tmp", ruta.display()));
    {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let mut f = std::fs::OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(&tmp).map_err(|_| Fallo::Interno)?;
        f.write_all(prig_plataforma::json::escribir_compacto(&Valor::Mapa(doc)).as_bytes()).map_err(|_| Fallo::Interno)?;
    }
    std::fs::rename(&tmp, &ruta).map_err(|_| Fallo::Interno)?;
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(&ruta, std::fs::Permissions::from_mode(0o600)).map_err(|_| Fallo::Interno)?;
    estado()
}

/// `borrar_token()`
pub fn borrar_token() -> Result<Mapa, Fallo> {
    let _ = std::fs::remove_file(ruta_token());
    estado()
}

// ---------------------------------------------------------------------------------------------- API

/// `_api(ruta, params)`: la API con los mensajes de Prig para cada estado
fn llamar(ruta: &str, params: &[(&str, String)]) -> Result<Valor, Fallo> {
    let r = get(&format!("{}/{ruta}", api()), params, true, None)?;
    let estado = r.status().as_u16();
    let cab = |k: &str| r.headers().get(k).and_then(|v| v.to_str().ok()).map(String::from);
    if (estado == 403 || estado == 429) && (cab("X-RateLimit-Remaining").as_deref() == Some("0") || estado == 429) {
        let reset: f64 = cab("X-RateLimit-Reset").and_then(|x| x.trim().parse().ok()).unwrap_or(0.0);
        let ahora = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
        let minutos = if reset != 0.0 { Some((((reset - ahora) / 60.0).round_ties_even() as i64).max(1)) } else { None };
        let busquedas = cab("X-RateLimit-Resource").as_deref() == Some("search");
        return error(format!(
            "GitHub limitó las {} sin cuenta{}. Con un token gratuito de GitHub el límite sube mucho.",
            if busquedas { "búsquedas" } else { "consultas" },
            minutos.map(|m| format!(": vuelve a probar en {m} min")).unwrap_or_default()
        ));
    }
    match estado {
        200 => {}
        401 => return error("GitHub no aceptó el token guardado: vuelve a pegarlo o bórralo."),
        404 => return error("Ese repositorio no existe o es privado."),
        422 => return error("GitHub no entendió la búsqueda: prueba con otras palabras."),
        s => return error(format!("GitHub respondió {s}.")),
    }
    let t = r.text().map_err(|_| Fallo::Interno)?;
    prig_plataforma::json::leer(&t).map_err(|_| Fallo::Interno)
}

fn get_v(v: &Valor, k: &str) -> Result<Valor, Fallo> {
    match v {
        Valor::Mapa(m) => Ok(m.get(k).cloned().unwrap_or(Valor::Nulo)),
        _ => Err(Fallo::Interno),
    }
}

fn o(v: Valor, y: Valor) -> Valor {
    if v.verdad() { v } else { y }
}

fn s(v: &Valor) -> String {
    v.texto_py()
}

// ---------------------------------------------------------------------------------------------- buscar

/// `ref_desde`: «dueño/repo» de un enlace o de la referencia
pub fn ref_desde(texto: &str) -> Result<String, Fallo> {
    let t = py::strip(texto);
    let r = match ENLACE.captures(t) {
        Some(c) => format!("{}/{}", &c[1], &c[2]),
        None => t.trim_matches('/').to_string(),
    };
    let r = r.strip_suffix(".git").map(String::from).unwrap_or(r);
    if !REF_VALIDA.is_match(&r) || r.contains("..") {
        return error("Eso no es un repositorio de GitHub: pega un enlace como github.com/usuario/repositorio.");
    }
    Ok(r)
}

/// `_corto(r)`
fn corto(r: &Valor) -> Result<Mapa, Fallo> {
    let dueno = o(get_v(r, "owner")?, Valor::Mapa(Mapa::new()));
    let licencia = o(get_v(r, "license")?, Valor::Mapa(Mapa::new()));
    let mut temas = match o(get_v(r, "topics")?, Valor::Lista(vec![])) {
        Valor::Lista(l) => l,
        _ => return Err(Fallo::Interno),
    };
    temas.truncate(10);
    Ok(Mapa::new()
        .con("ref", get_v(r, "full_name")?)
        .con("nombre", get_v(r, "name")?)
        .con("dueno", get_v(&dueno, "login")?)
        .con("avatar", get_v(&dueno, "avatar_url")?)
        .con("descripcion", o(get_v(r, "description")?, Valor::Texto(String::new())))
        .con("estrellas", get_v(r, "stargazers_count")?)
        .con("forks", get_v(r, "forks_count")?)
        .con("lenguaje", get_v(r, "language")?)
        .con("temas", Valor::Lista(temas))
        .con("actualizado", o(get_v(r, "pushed_at")?, get_v(r, "updated_at")?))
        .con("licencia", o(get_v(&licencia, "spdx_id")?, get_v(&licencia, "name")?))
        .con("rama", get_v(r, "default_branch")?)
        .con("kb", get_v(r, "size")?)
        .con("issues", get_v(r, "open_issues_count")?)
        .con("web", o(get_v(r, "homepage")?, Valor::Texto(String::new())))
        .con("archivado", get_v(r, "archived")?.verdad())
        .con("fork", get_v(r, "fork")?.verdad())
        .con("url", o(get_v(r, "html_url")?, Valor::Texto(format!("https://github.com/{}", s(&get_v(r, "full_name")?))))))
}

static CACHE: LazyLock<Mutex<HashMap<String, (Instant, Mapa)>>> = LazyLock::new(|| Mutex::new(HashMap::new()));

const ORDENES: [(&str, &str); 4] = [("estrellas", "stars"), ("actualizados", "updated"), ("forks", "forks"), ("relevancia", "")];

/// `buscar(consulta, lenguaje, orden, pagina, estrellas_min, tema)`
pub fn buscar(consulta: &str, lenguaje: &str, orden: &str, pagina: i64, estrellas_min: i64, tema: &str) -> Result<Mapa, Fallo> {
    let mut partes = Vec::new();
    let c = py::strip(consulta);
    if !c.is_empty() {
        partes.push(c.chars().take(200).collect::<String>());
    }
    if !py::strip(lenguaje).is_empty() {
        partes.push(format!("language:{}", py::strip(lenguaje)));
    }
    if estrellas_min != 0 {
        partes.push(format!("stars:>={estrellas_min}"));
    }
    if !py::strip(tema).is_empty() {
        partes.push(format!("topic:{}", py::strip(tema)));
    }
    if partes.is_empty() {
        return error("Escribe qué buscar.");
    }
    let pagina = pagina.max(1);
    let mut params: Vec<(&str, String)> = vec![("q", partes.join(" ")), ("per_page", "20".into()), ("page", pagina.to_string())];
    if let Some((_, o)) = ORDENES.iter().find(|x| x.0 == orden).filter(|x| !x.1.is_empty()) {
        params.push(("sort", o.to_string()));
        params.push(("order", "desc".into()));
    }
    let mut ord: Vec<&(&str, String)> = params.iter().collect();
    ord.sort_by_key(|x| x.0);
    let clave = ord.iter().map(|(k, v)| format!("{k}={v}")).collect::<Vec<_>>().join("&");
    if let Some((t, m)) = CACHE.lock().unwrap().get(&clave) {
        if t.elapsed() < Duration::from_secs(600) {
            return Ok(m.clone());
        }
    }
    let d = llamar("search/repositories", &params)?;
    let items = match o(get_v(&d, "items")?, Valor::Lista(vec![])) {
        Valor::Lista(l) => l,
        _ => return Err(Fallo::Interno),
    };
    let total = match get_v(&d, "total_count")? {
        Valor::Nulo => Valor::Entero(0),
        v => v,
    };
    let repos: Vec<Valor> = items.iter().map(|r| corto(r).map(Valor::Mapa)).collect::<Result<_, _>>()?;
    let total_n = total.num().unwrap_or(0.0);
    let r = Mapa::new()
        .con("repos", Valor::Lista(repos))
        .con("total", total)
        .con("pagina", pagina as i128)
        .con("hay_mas", (pagina as f64) * 20.0 < total_n.min(1000.0));
    CACHE.lock().unwrap().insert(clave, (Instant::now(), r.clone()));
    Ok(r)
}

// ---------------------------------------------------------------------------------------------- abrir

fn ruta_repo(r: &str) -> PathBuf {
    carpeta().join("repos").join(format!("{}.json", r.replace('/', "__")))
}

/// `requests.utils.quote(ruta)`: todo salvo letras, cifras, «_.-~» y «/»
fn citar(t: &str) -> String {
    let mut o = String::new();
    for b in t.as_bytes() {
        if b.is_ascii_alphanumeric() || b"_.-~/".contains(b) {
            o.push(*b as char);
        } else {
            o.push_str(&format!("%{b:02X}"));
        }
    }
    o
}

/// `_crudo(ref, rama, ruta)`: un archivo en crudo
fn crudo(r: &str, rama: &str, ruta: &str) -> Result<String, Fallo> {
    let resp = get(&format!("{}/{r}/{rama}/{}", raw(), citar(ruta)), &[], false, None)?;
    match resp.status().as_u16() {
        200 => {}
        404 => return error(format!("No se encontró {ruta} en el repositorio.")),
        e => return error(format!("GitHub respondió {e} al leer {ruta}.")),
    }
    let b = resp.bytes().map_err(|_| Fallo::Interno)?;
    Ok(String::from_utf8_lossy(&b).into_owned())
}

/// `abrir(texto, refrescar)`: ficha, lenguajes, árbol de archivos y README
pub fn abrir(texto: &str, refrescar: bool) -> Result<Mapa, Fallo> {
    let pedido = ref_desde(texto)?;
    let ruta = ruta_repo(&pedido);
    if !refrescar {
        if let Ok(m) = std::fs::metadata(&ruta) {
            if m.modified().ok().and_then(|t| t.elapsed().ok()).is_some_and(|e| e.as_secs_f64() < 86400.0) {
                match leer_json(&ruta) {
                    Some(Valor::Mapa(g)) if !g.is_empty() => return Ok(g),
                    Some(v) if v.verdad() => return Err(Fallo::Interno),
                    _ => {}
                }
            }
        }
    }
    let meta = llamar(&format!("repos/{pedido}"), &[])?;
    let mut info = corto(&meta)?;
    let r = s(info.valor("ref"));
    let lenguajes = match llamar(&format!("repos/{r}/languages"), &[]) {
        Ok(Valor::Mapa(m)) => m,
        Ok(_) => return Err(Fallo::Interno),
        Err(Fallo::Usuario(_)) => Mapa::new(),
        Err(e) => return Err(e),
    };
    let rama = s(info.valor("rama"));
    let arbol = llamar(&format!("repos/{r}/git/trees/{rama}"), &[("recursive", "1".into())])?;
    let mut archivos = Vec::new();
    for t in match o(get_v(&arbol, "tree")?, Valor::Lista(vec![])) {
        Valor::Lista(l) => l,
        _ => return Err(Fallo::Interno),
    } {
        if get_v(&t, "type")? == Valor::Texto("blob".into()) {
            archivos.push(Mapa::new().con("ruta", get_v(&t, "path")?).con("bytes", o(get_v(&t, "size")?, Valor::Entero(0))).con("sha", get_v(&t, "sha")?));
        }
    }
    let suma: f64 = lenguajes.iter().map(|(_, v)| v.num().unwrap_or(0.0)).sum();
    let total = if suma == 0.0 { 1.0 } else { suma };
    let mut lens: Vec<(&String, f64)> = lenguajes.iter().map(|(k, v)| (k, v.num().unwrap_or(0.0))).collect();
    lens.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    let lens: Vec<Valor> =
        lens.into_iter().take(8).map(|(k, v)| Valor::Mapa(Mapa::new().con("nombre", k.clone()).con("pct", Valor::Real(redondear(100.0 * v / total, 1))))).collect();
    let n = archivos.len();
    let truncado = get_v(&arbol, "truncated")?.verdad() || n > 5000;
    let readme = archivos.iter().map(|a| s(a.valor("ruta"))).find(|r| README.is_match(r));
    info.poner("lenguajes", Valor::Lista(lens));
    info.poner("archivos", Valor::Lista(archivos.into_iter().take(5000).map(Valor::Mapa).collect()));
    info.poner("truncado", truncado);
    info.poner("descargado", ahora_s());
    info.poner("readme_ruta", readme.clone().map(Valor::Texto).unwrap_or(Valor::Nulo));
    let texto_readme = match &readme {
        Some(rr) => crudo(&r, &rama, rr)?.chars().take(60000).collect(),
        None => String::new(),
    };
    info.poner("readme", texto_readme);
    escribir_json(&ruta_repo(&r), &Valor::Mapa(info.clone()))?;
    if r != pedido {
        escribir_json(&ruta, &Valor::Mapa(info.clone()))?;
    }
    Ok(info)
}

fn archivos(info: &Mapa) -> Vec<Mapa> {
    info.lista("archivos").unwrap_or(&[]).iter().filter_map(|a| if let Valor::Mapa(m) = a { Some(m.clone()) } else { None }).collect()
}

/// `_lenguaje(ruta)`
fn lenguaje(ruta: &str) -> &'static str {
    let ext = if ruta.contains('.') { ruta.rsplit('.').next().unwrap_or("").to_lowercase() } else { String::new() };
    match ext.as_str() {
        "py" => "python",
        "js" | "mjs" | "jsx" => "javascript",
        "ts" | "tsx" => "typescript",
        "md" => "markdown",
        "json" | "ipynb" => "json",
        "yml" | "yaml" => "yaml",
        "toml" => "toml",
        "sh" => "bash",
        "go" => "go",
        "rs" => "rust",
        "java" => "java",
        "c" | "h" => "c",
        "cpp" | "hpp" => "cpp",
        "cs" => "csharp",
        "rb" => "ruby",
        "php" => "php",
        "html" => "html",
        "css" => "css",
        "sql" => "sql",
        "r" => "r",
        "kt" => "kotlin",
        "swift" => "swift",
        "scala" => "scala",
        "lua" => "lua",
        "jl" => "julia",
        _ => "plaintext",
    }
}

/// `str.splitlines()`: cuántas líneas
fn lineas(t: &str) -> usize {
    crate::kaggle_red::splitlines(t).len()
}

/// `leer_archivo(texto, ruta)`
pub fn leer_archivo(texto: &str, ruta: &str) -> Result<Mapa, Fallo> {
    let info = abrir(texto, false)?;
    let Some(a) = archivos(&info).into_iter().find(|x| x.texto("ruta") == Some(ruta)) else {
        return error("Ese archivo no está en el repositorio.");
    };
    let bytes = a.valor("bytes").clone();
    if BINARIOS.is_match(ruta) {
        return Ok(Mapa::new().con("ruta", ruta).con("bytes", bytes).con("binario", true).con("contenido", ""));
    }
    if bytes.num().unwrap_or(0.0) > MAX_ARCHIVO {
        return Ok(Mapa::new().con("ruta", ruta).con("bytes", bytes).con("grande", true).con("contenido", ""));
    }
    let r = s(info.valor("ref"));
    let sha = match a.get("sha") {
        Some(v) if v.verdad() => s(v),
        _ => Sha1::digest(ruta.as_bytes()).iter().map(|b| format!("{b:02x}")).collect(),
    };
    let cache = carpeta().join("archivos").join(r.replace('/', "__")).join(format!("{sha}.txt"));
    let contenido = match std::fs::read(&cache) {
        Ok(b) => String::from_utf8(b).map_err(|_| Fallo::Interno)?,
        Err(_) => {
            let c = crudo(&r, &s(info.valor("rama")), ruta)?;
            std::fs::create_dir_all(cache.parent().ok_or(Fallo::Interno)?).map_err(|_| Fallo::Interno)?;
            std::fs::write(&cache, &c).map_err(|_| Fallo::Interno)?;
            c
        }
    };
    if contenido.chars().take(2000).any(|c| c == '\0') {
        return Ok(Mapa::new().con("ruta", ruta).con("bytes", bytes).con("binario", true).con("contenido", ""));
    }
    let n = lineas(&contenido).max(1);
    Ok(Mapa::new()
        .con("ruta", ruta)
        .con("bytes", bytes)
        .con("sha", a.get("sha").cloned().unwrap_or(Valor::Nulo))
        .con("contenido", contenido)
        .con("lineas", n as i128)
        .con("lenguaje", lenguaje(ruta)))
}

// ---------------------------------------------------------------------------------------------- explicaciones

fn explicaciones(r: &str) -> Result<Mapa, Fallo> {
    match leer_json(&carpeta().join("explicaciones").join(format!("{}.json", r.replace('/', "__")))) {
        Some(Valor::Mapa(m)) => Ok(m),
        Some(v) if v.verdad() => Err(Fallo::Interno),
        _ => Ok(Mapa::new()),
    }
}

/// `explicadas(info)`: la del repositorio y, por archivo, la más reciente cuyo archivo no cambió
pub fn explicadas(info: &Mapa) -> Result<Mapa, Fallo> {
    let vigentes: Vec<(String, String)> = archivos(info)
        .iter()
        .map(|a| (s(a.valor("ruta")), match a.get("sha") {
            Some(v) if v.verdad() => s(v).chars().take(10).collect(),
            _ => String::new(),
        }))
        .collect();
    let mut repo: Option<Mapa> = None;
    let mut por_archivo = Mapa::new();
    let fecha = |m: &Mapa| -> Result<String, Fallo> {
        match m.get("fecha") {
            Some(Valor::Texto(t)) => Ok(t.clone()),
            _ => Err(Fallo::Interno),
        }
    };
    for (clave, e) in explicaciones(&s(info.valor("ref")))?.iter() {
        let Valor::Mapa(e) = e else { return Err(Fallo::Interno) };
        if clave.starts_with("repo:") {
            if repo.as_ref().map(|r| fecha(e).and_then(|f| fecha(r).map(|g| f > g))).transpose()?.unwrap_or(true) {
                repo = Some(e.clone());
            }
            continue;
        }
        let ruta = e.get("ruta").map(s).unwrap_or_default();
        let Some((_, sha)) = vigentes.iter().find(|(r, _)| *r == ruta && e.get("ruta").is_some_and(|v| !v.es_nulo())) else { continue };
        if !clave.ends_with(&format!(":{sha}")) {
            continue;
        }
        let mejor = match por_archivo.get(&ruta) {
            None => true,
            Some(Valor::Mapa(prev)) => fecha(e)? > fecha(prev)?,
            _ => true,
        };
        if mejor {
            por_archivo.poner(ruta, e.clone());
        }
    }
    Ok(Mapa::new().con("repo", repo.map(Valor::Mapa).unwrap_or(Valor::Nulo)).con("archivos", por_archivo))
}

// ---------------------------------------------------------------------------------------------- guardados y descargas

fn ruta_guardados() -> PathBuf {
    carpeta().join("guardados.json")
}

fn guardados() -> Result<Vec<Valor>, Fallo> {
    match leer_json(&ruta_guardados()) {
        Some(Valor::Lista(l)) => Ok(l),
        Some(v) if v.verdad() => Err(Fallo::Interno),
        _ => Ok(Vec::new()),
    }
}

fn ref_de(g: &Valor) -> Result<String, Fallo> {
    match get_v(g, "ref")? {
        Valor::Texto(t) => Ok(t),
        _ => Err(Fallo::Interno),
    }
}

/// `guardar(texto, nota)`: lo pone el primero de la lista
pub fn guardar(texto: &str, nota: &str) -> Result<Vec<Valor>, Fallo> {
    let info = abrir(texto, false)?;
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let r = s(info.valor("ref"));
    let mut lista = Vec::new();
    for g in guardados()? {
        if Valor::Texto(ref_de(&g)?) != *info.valor("ref") {
            lista.push(g);
        }
    }
    let _ = r;
    let mut nuevo = Mapa::new();
    for k in ["ref", "nombre", "dueno", "avatar", "descripcion", "estrellas", "lenguaje", "temas", "url"] {
        nuevo.poner(k, info.get(k).cloned().unwrap_or(Valor::Nulo));
    }
    nuevo.poner("nota", py::strip(nota).chars().take(1000).collect::<String>());
    nuevo.poner("guardado", ahora_s());
    lista.insert(0, Valor::Mapa(nuevo));
    escribir_json(&ruta_guardados(), &Valor::Lista(lista.clone()))?;
    Ok(lista)
}

/// `quitar(ref)`
pub fn quitar(r: &str) -> Result<Vec<Valor>, Fallo> {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let mut lista = Vec::new();
    for g in guardados()? {
        if ref_de(&g)?.to_lowercase() != r.to_lowercase() {
            lista.push(g);
        }
    }
    escribir_json(&ruta_guardados(), &Valor::Lista(lista.clone()))?;
    Ok(lista)
}

pub fn esta_guardado(r: &Valor) -> Result<bool, Fallo> {
    for g in guardados()? {
        if Valor::Texto(ref_de(&g)?) == *r {
            return Ok(true);
        }
    }
    Ok(false)
}

fn carpeta_local(r: &str, espacio: &Path) -> PathBuf {
    espacio.join(CARPETA_REPOS).join(r.split('/').nth(1).unwrap_or(""))
}

/// `local(ref, workspace)`: lo descargado (archivos y bytes)
pub fn local(r: &str, espacio: &Path) -> Result<Option<Mapa>, Fallo> {
    let raiz = carpeta_local(r, espacio);
    if !raiz.is_dir() {
        return Ok(None);
    }
    let (mut n, mut total) = (0usize, 0u64);
    let mut pila = vec![raiz.clone()];
    while let Some(d) = pila.pop() {
        let Ok(l) = std::fs::read_dir(&d) else { continue };
        for e in l.flatten() {
            let p = e.path();
            if p.is_dir() {
                if !e.file_type().is_ok_and(|t| t.is_symlink()) {
                    pila.push(p);
                }
            } else {
                n += 1;
                total += std::fs::metadata(&p).map_err(|_| Fallo::Interno)?.len();
            }
        }
    }
    Ok(Some(
        Mapa::new()
            .con("carpeta", raiz.to_string_lossy().into_owned())
            .con("relativa", py::relpath(&raiz.to_string_lossy(), &espacio.to_string_lossy()))
            .con("archivos", n as i128)
            .con("bytes", total as i128),
    ))
}

/// `descargar(texto, workspace, avisar)`: el repositorio (rama principal, sin historial) en github_repos/<repo>/
pub fn descargar(texto: &str, espacio: &Path, avisar: &mut dyn FnMut(Mapa) -> bool) -> Result<Mapa, Fallo> {
    use std::io::Read;
    let info = abrir(texto, false)?;
    let r = s(info.valor("ref"));
    let url = format!("{}/{r}/zip/refs/heads/{}", codeload(), s(info.valor("rama")));
    let mut req = reqwest::blocking::Client::builder().connect_timeout(Duration::from_secs(60)).build().map_err(|_| Fallo::Interno)?.get(url);
    req = req.header("User-Agent", UA).header("Accept", ACCEPT);
    if let Some((t, _)) = token()? {
        req = req.header("Authorization", format!("Bearer {t}"));
    }
    let Ok(mut resp) = req.send() else { return error("Sin conexión con GitHub: comprueba internet.") };
    if resp.status().as_u16() != 200 {
        return error(format!("GitHub respondió {} al descargar el repositorio.", resp.status().as_u16()));
    }
    let mut buf: Vec<u8> = Vec::new();
    let mut trozo = vec![0u8; 1 << 16];
    let mut ultimo: Option<Instant> = None;
    loop {
        let n = resp.read(&mut trozo).or_else(|_| error("Sin conexión con GitHub: comprueba internet."))?;
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&trozo[..n]);
        if buf.len() > 2 << 30 {
            return error("El repositorio pesa más de 2 GB: descárgalo con git.");
        }
        if ultimo.is_none_or(|u| u.elapsed() > Duration::from_millis(400)) {
            ultimo = Some(Instant::now());
            let m = format!("Descargando {:.1} MB", buf.len() as f64 / 1048576.0);
            if !avisar(Mapa::new().con("tipo", "progreso").con("bytes", buf.len() as i128).con("mensaje", m)) {
                return error("Descarga cancelada.");
            }
        }
    }
    avisar(Mapa::new().con("tipo", "progreso").con("bytes", buf.len() as i128).con("mensaje", "Descomprimiendo…"));
    let destino = carpeta_local(&r, espacio);
    if destino.is_dir() {
        std::fs::remove_dir_all(&destino).map_err(|_| Fallo::Interno)?;
    }
    std::fs::create_dir_all(&destino).map_err(|_| Fallo::Interno)?;
    let raiz = std::fs::canonicalize(&destino).map_err(|_| Fallo::Interno)?;
    let mut z = zip::ZipArchive::new(std::io::Cursor::new(buf)).map_err(|_| Fallo::Interno)?;
    for i in 0..z.len() {
        let mut e = z.by_index(i).map_err(|_| Fallo::Interno)?;
        // el zip trae una carpeta «repo-rama/» delante de todo: se quita
        let nombre = e.name().to_string();
        let Some((_, rel)) = nombre.split_once('/') else { continue };
        if rel.is_empty() {
            continue;
        }
        let ruta = PathBuf::from(py::normpath(&raiz.join(rel).to_string_lossy()));
        if !ruta.starts_with(&raiz) || ruta == raiz {
            continue;
        }
        if e.is_dir() {
            std::fs::create_dir_all(&ruta).map_err(|_| Fallo::Interno)?;
            continue;
        }
        std::fs::create_dir_all(ruta.parent().ok_or(Fallo::Interno)?).map_err(|_| Fallo::Interno)?;
        let mut f = std::fs::File::create(&ruta).map_err(|_| Fallo::Interno)?;
        std::io::copy(&mut e, &mut f).map_err(|_| Fallo::Interno)?;
    }
    Ok(local(&r, espacio)?.unwrap_or_default())
}

// ---------------------------------------------------------------------------------------------- exportar

fn hoy() -> String {
    let h = py::ahora_iso();
    format!("{}/{}/{}", &h[8..10], &h[5..7], &h[..4])
}

fn sin_explicaciones() -> Result<Mapa, Fallo> {
    error("Todavía no hay explicaciones de este repositorio: pide la del repositorio o la de algún archivo.")
}

fn texto_de(e: &Valor) -> String {
    match e {
        Valor::Mapa(m) => m.get("texto").map(s).unwrap_or_default(),
        _ => String::new(),
    }
}

/// `exportar_markdown`
pub fn exportar_markdown(texto: &str, espacio: &Path) -> Result<Mapa, Fallo> {
    let info = abrir(texto, false)?;
    let e = explicadas(&info)?;
    let repo = e.valor("repo").clone();
    let archs = e.mapa("archivos").cloned().unwrap_or_default();
    if repo.es_nulo() && archs.is_empty() {
        return sin_explicaciones();
    }
    let o_vacio = |k: &str| match info.get(k) {
        Some(v) if v.verdad() => s(v),
        _ => String::new(),
    };
    let mut partes = vec![
        format!("# {}\n", s(info.valor("ref"))),
        format!("{}\n", o_vacio("descripcion")),
        format!(
            "<{}> · ⭐ {} · {} · licencia {}\n",
            s(info.valor("url")),
            s(info.valor("estrellas")),
            o_vacio("lenguaje"),
            if o_vacio("licencia").is_empty() { "sin indicar".to_string() } else { o_vacio("licencia") }
        ),
    ];
    if !repo.es_nulo() {
        partes.extend(["\n# El repositorio en conjunto\n".to_string(), texto_de(&repo), "\n".into()]);
    }
    let mut rutas: Vec<&String> = archs.claves().collect();
    rutas.sort();
    for r in rutas {
        partes.extend([format!("\n# `{r}`\n"), texto_de(archs.valor(r)), "\n".into()]);
    }
    partes.push(format!("\n---\nExplicado con Prig el {}. Las explicaciones las generó un modelo de IA: pueden contener errores.\n", hoy()));
    let destino = espacio.join(CARPETA_EXPORT).join(format!("{}.md", s(info.valor("ref")).replace('/', "__")));
    std::fs::create_dir_all(destino.parent().ok_or(Fallo::Interno)?).map_err(|_| Fallo::Interno)?;
    std::fs::write(&destino, partes.join("\n")).map_err(|_| Fallo::Interno)?;
    Ok(Mapa::new()
        .con("ruta", destino.to_string_lossy().into_owned())
        .con("relativa", py::relpath(&destino.to_string_lossy(), &espacio.to_string_lossy()))
        .con("archivos", archs.len() as i128)
        .con("con_resumen", !repo.es_nulo())
        .con("bytes", std::fs::metadata(&destino).map(|m| m.len() as i128).unwrap_or(0)))
}

/// `exportar_pdf`: el resumen y, por archivo explicado, su código con la explicación debajo
pub fn exportar_pdf(texto: &str, espacio: &Path) -> Result<Mapa, Fallo> {
    let info = abrir(texto, false)?;
    let e = explicadas(&info)?;
    let repo = e.valor("repo").clone();
    let archs = e.mapa("archivos").cloned().unwrap_or_default();
    if repo.es_nulo() && archs.is_empty() {
        return sin_explicaciones();
    }
    let md = prig_documentos::marcado::escapar_md;
    let o_vacio = |k: &str| match info.get(k) {
        Some(v) if v.verdad() => s(v),
        _ => String::new(),
    };
    let url = s(info.valor("url"));
    let lineas = vec![
        format!("de **{}** · {} estrellas · {}", md(&o_vacio("dueno")), s(info.valor("estrellas")), md(&o_vacio("lenguaje"))),
        format!("[{}](<{}>)", md(&url), url.replace('<', "%3C").replace('>', "%3E")),
        format!("{} archivos explicados", archs.len()),
    ];
    let b = |t: &str| Mapa::new().con("tipo", t);
    let profesor = |t: String, etiqueta: String| b("profesor").con("etiqueta", etiqueta).con("texto", t);
    let mut h = vec![b("portada")
        .con("etiqueta", "REPOSITORIO DE GITHUB EXPLICADO")
        .con("titulo", info.valor("ref").clone())
        .con("lineas", Valor::Lista(lineas.into_iter().map(Valor::Texto).collect()))
        .con("fecha", format!("Generado con Prig el {}", hoy()))];
    h.push(b("espacio").con("alto", 20));
    h.push(b("markdown").con("texto", md(&o_vacio("descripcion"))));
    let lic = if o_vacio("licencia").is_empty() { "sin indicar".to_string() } else { o_vacio("licencia") };
    h.push(b("nota").con("texto", md(&format!("Licencia del código original: {lic}. Las explicaciones las generó un modelo de IA: pueden contener errores."))));
    if !repo.es_nulo() {
        h.push(b("salto"));
        h.push(b("seccion").con("texto", "El repositorio en conjunto"));
        h.push(profesor(texto_de(&repo), "PROFESOR · VISIÓN GENERAL".into()));
    }
    let mut rutas: Vec<String> = archs.claves().cloned().collect();
    rutas.sort();
    let r = s(info.valor("ref"));
    for ruta in rutas {
        h.push(b("salto"));
        h.push(b("seccion").con("texto", ruta.clone()));
        let codigo = match leer_archivo(&r, &ruta) {
            Ok(a) => a.get("contenido").filter(|v| v.verdad()).map(s).unwrap_or_default(),
            Err(Fallo::Usuario(_)) => String::new(),
            Err(e) => return Err(e),
        };
        if !codigo.is_empty() {
            let recortado = codigo.matches('\n').count() > 400;
            let len = lenguaje(&ruta);
            h.push(
                b("codigo")
                    .con("texto", codigo.split('\n').take(400).collect::<Vec<_>>().join("\n"))
                    .con("lenguaje", if len == "plaintext" { Valor::Nulo } else { Valor::Texto(len.into()) })
                    .con("salida", false)
                    .con("max_lineas", Valor::Nulo),
            );
            if recortado {
                h.push(b("nota").con("texto", "… (el archivo sigue: se muestran las primeras 400 líneas)"));
            }
        }
        let ex = archs.valor(&ruta);
        let nivel = match ex {
            Valor::Mapa(m) => m.get("nivel").filter(|v| v.verdad()).map(s).unwrap_or_default(),
            _ => String::new(),
        };
        h.push(profesor(texto_de(ex), format!("PROFESOR{}", if nivel.is_empty() { String::new() } else { format!(" · NIVEL {}", nivel.to_uppercase()) })));
    }
    let destino = espacio.join(CARPETA_EXPORT).join(format!("{}.pdf", r.replace('/', "__")));
    std::fs::create_dir_all(destino.parent().ok_or(Fallo::Interno)?).map_err(|_| Fallo::Interno)?;
    let doc = Mapa::new()
        .con("titulo", info.valor("ref").clone())
        .con("asunto", "Repositorio de GitHub explicado")
        .con("estilo", "notebook")
        .con("pie", true)
        .con("bloques", Valor::Lista(h.into_iter().map(Valor::Mapa).collect()));
    let (datos, paginas) = prig_documentos::pdf_de_json(&prig_plataforma::json::escribir_linea(&Valor::Mapa(doc))).map_err(|_| Fallo::Interno)?;
    let tmp = PathBuf::from(format!("{}.tmp", destino.display()));
    std::fs::write(&tmp, datos).map_err(|_| Fallo::Interno)?;
    std::fs::rename(&tmp, &destino).map_err(|_| Fallo::Interno)?;
    Ok(Mapa::new()
        .con("ruta", destino.to_string_lossy().into_owned())
        .con("relativa", py::relpath(&destino.to_string_lossy(), &espacio.to_string_lossy()))
        .con("paginas", paginas as i128)
        .con("archivos", archs.len() as i128)
        .con("con_resumen", !repo.es_nulo())
        .con("bytes", std::fs::metadata(&destino).map(|m| m.len() as i128).unwrap_or(0)))
}

/// La ruta de un archivo exportado dentro de <proyecto>/github_explicaciones (None si no)
pub fn exportado(ruta: &str, espacio: &Path) -> Option<PathBuf> {
    let raiz = std::fs::canonicalize(espacio.join(CARPETA_EXPORT)).ok()?;
    let real = std::fs::canonicalize(ruta).ok()?;
    (real.starts_with(&raiz) && real != raiz && real.is_file()).then_some(real)
}
