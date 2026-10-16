//! Kaggle (`kaggle_lector.py`, `kaggle_colecciones.py`): las credenciales (en el mismo orden que el cliente oficial),
//! la API (`https://www.kaggle.com/api/v1`, o `PRIG_KAGGLE_API` en las pruebas), las colecciones y lo leído. Todo se
//! lee del disco en cada llamada y se escribe de una vez (archivo temporal y rename), en los mismos archivos que Python.

use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};

/// Un error para el usuario (FastAPI lo devolvía como 400 con este texto)
#[derive(Debug, Clone, PartialEq)]
pub struct ErrorKaggle(pub String);

impl std::fmt::Display for ErrorKaggle {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn error<T>(t: &str) -> Result<T, ErrorKaggle> {
    Err(ErrorKaggle(t.into()))
}

fn entorno(var: &str) -> Option<String> {
    std::env::var(var).ok().filter(|v| !v.is_empty())
}

fn ruta_de(var: &str, defecto: &str) -> PathBuf {
    PathBuf::from(entorno(var).unwrap_or_else(|| py::expanduser(defecto)))
}

/// `carpeta()`: `PRIG_KAGGLE_DIR` o `~/.prig_kaggle`
pub fn carpeta() -> PathBuf {
    ruta_de("PRIG_KAGGLE_DIR", "~/.prig_kaggle")
}

/// `ruta_credenciales_prig()`
pub fn ruta_credenciales() -> PathBuf {
    ruta_de("PRIG_KAGGLE_CREDENCIALES", "~/.prig_kaggle.json")
}

pub fn api() -> String {
    entorno("PRIG_KAGGLE_API").unwrap_or_else(|| "https://www.kaggle.com/api/v1".into())
}

/// `REF_VALIDA`: usuario/slug
pub static REF_VALIDA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9_\-]{1,60}/[A-Za-z0-9_\-.]{1,120}$").unwrap());
static SLUG: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9_\-.]{1,120}$").unwrap());
static ENLACE_COMPETICION: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"kaggle\.com/(?:competitions|c)/([A-Za-z0-9_\-.]+)").unwrap());

/// `_leer_json`: solo un objeto (otra cosa, o un error, es None)
pub fn leer_objeto(ruta: &Path) -> Option<Mapa> {
    match prig_plataforma::json::leer(&std::fs::read_to_string(ruta).ok()?).ok()? {
        Valor::Mapa(m) => Some(m),
        _ => None,
    }
}

fn escribir_de_una_vez(ruta: &Path, texto: &str, modo: Option<u32>) -> std::io::Result<()> {
    if let Some(p) = ruta.parent() {
        std::fs::create_dir_all(p)?;
    }
    let tmp = PathBuf::from(format!("{}.tmp", ruta.display()));
    {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let mut o = std::fs::OpenOptions::new();
        o.write(true).create(true).truncate(true);
        if let Some(m) = modo {
            o.mode(m);
        }
        let mut f = o.open(&tmp)?;
        f.write_all(texto.as_bytes())?;
    }
    std::fs::rename(&tmp, ruta)?;
    if let Some(m) = modo {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(ruta, std::fs::Permissions::from_mode(m))?;
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------------- credenciales

/// Unas credenciales: token (Bearer) o usuario y clave (autenticación básica)
#[derive(Clone, Debug)]
pub enum Cuenta {
    Token { token: String, usuario: Valor, origen: String },
    Clave { usuario: Valor, clave: String, origen: String },
}

impl Cuenta {
    fn tipo(&self) -> &'static str {
        match self {
            Cuenta::Token { .. } => "token",
            Cuenta::Clave { .. } => "clave",
        }
    }
}

fn dirs_config() -> Vec<PathBuf> {
    let mut d = Vec::new();
    if let Some(c) = entorno("KAGGLE_CONFIG_DIR") {
        d.push(PathBuf::from(c));
    }
    d.push(PathBuf::from(py::expanduser("~/.kaggle")));
    d.push(PathBuf::from(entorno("XDG_CONFIG_HOME").unwrap_or_else(|| py::expanduser("~/.config"))).join("kaggle"));
    d
}

/// La ruta para enseñar: la carpeta personal como «~»
fn legible(ruta: &Path) -> String {
    ruta.to_string_lossy().replace(&py::expanduser("~"), "~")
}

fn texto_de(v: Option<&Valor>) -> String {
    v.map(|v| v.texto_py()).unwrap_or_default()
}

/// `credenciales()`
pub fn credenciales() -> Option<Cuenta> {
    if let Some(p) = leer_objeto(&ruta_credenciales()).filter(|m| !m.is_empty()) {
        if p.verdad("token") {
            return Some(Cuenta::Token { token: texto_de(p.get("token")), usuario: p.get("usuario").cloned().unwrap_or(Valor::Nulo), origen: "Prig".into() });
        }
        if p.verdad("username") && p.verdad("key") {
            return Some(Cuenta::Clave { usuario: p.valor("username").clone(), clave: texto_de(p.get("key")), origen: "Prig".into() });
        }
    }
    if let Some(t) = entorno("KAGGLE_API_TOKEN") {
        return Some(Cuenta::Token { token: t, usuario: Valor::Nulo, origen: "variable KAGGLE_API_TOKEN".into() });
    }
    for d in dirs_config() {
        let ruta = d.join("access_token");
        if let Ok(t) = std::fs::read_to_string(&ruta) {
            let t = t.trim();
            if !t.is_empty() {
                return Some(Cuenta::Token { token: t.into(), usuario: Valor::Nulo, origen: legible(&ruta) });
            }
        }
    }
    if let (Some(u), Some(k)) = (entorno("KAGGLE_USERNAME"), entorno("KAGGLE_KEY")) {
        return Some(Cuenta::Clave { usuario: Valor::Texto(u), clave: k, origen: "variables KAGGLE_USERNAME y KAGGLE_KEY".into() });
    }
    for d in dirs_config() {
        let ruta = d.join("kaggle.json");
        if let Some(m) = leer_objeto(&ruta).filter(|m| !m.is_empty()) {
            if m.verdad("username") && m.verdad("key") {
                return Some(Cuenta::Clave { usuario: m.valor("username").clone(), clave: texto_de(m.get("key")), origen: legible(&ruta) });
            }
        }
    }
    None
}

/// `estado()`: si hay cuenta (nunca la clave ni el token)
pub fn estado() -> Mapa {
    let c = credenciales();
    let (usuario, origen, metodo) = match &c {
        Some(Cuenta::Token { usuario, origen, .. }) | Some(Cuenta::Clave { usuario, origen, .. }) => {
            (usuario.clone(), Valor::Texto(origen.clone()), Valor::Texto(c.as_ref().map(|c| c.tipo()).unwrap_or_default().into()))
        }
        None => (Valor::Nulo, Valor::Nulo, Valor::Nulo),
    };
    Mapa::new()
        .con("conectado", c.is_some())
        .con("usuario", usuario)
        .con("origen", origen)
        .con("metodo", metodo)
        .con("url_token", "https://www.kaggle.com/settings/account")
        .con("nota", "Sin cuenta puedes abrir cualquier notebook público pegando su enlace; para buscar hace falta conectar Kaggle.")
}

/// `guardar_credenciales`: el contenido de kaggle.json o un token; se comprueba con Kaggle antes de guardarlo
pub fn guardar_credenciales(texto: &str) -> Result<Mapa, ErrorKaggle> {
    let t = py::strip(texto).trim_matches(|c| c == '"' || c == '\'' || c == '`');
    if t.is_empty() {
        return error("Pega el contenido de kaggle.json o tu token de API de Kaggle.");
    }
    let (nuevo, cuenta) = if t.starts_with('{') {
        let Ok(Valor::Mapa(d)) = prig_plataforma::json::leer(t) else {
            return error("Eso parece un kaggle.json pero no se puede leer: cópialo entero, con las llaves.");
        };
        if !(d.verdad("username") && d.verdad("key")) {
            return error("El kaggle.json debe tener «username» y «key».");
        }
        let (u, k) = (d.valor("username").texto_py(), d.valor("key").texto_py());
        (Mapa::new().con("username", u.clone()).con("key", k.clone()), Cuenta::Clave { usuario: Valor::Texto(u), clave: k, origen: String::new() })
    } else {
        if t.chars().any(char::is_whitespace) || t.chars().count() < 20 {
            return error("El token tiene espacios o es demasiado corto: cópialo con el botón de Kaggle.");
        }
        (Mapa::new().con("token", t), Cuenta::Token { token: t.into(), usuario: Valor::Nulo, origen: String::new() })
    };
    pedir("kernels/list", &[("pageSize", "1".into()), ("search", "titanic".into())], Some(&cuenta), true)?;
    let ahora: String = py::ahora_iso().chars().take(19).collect();
    let doc = nuevo.con("guardado", ahora);
    escribir_de_una_vez(&ruta_credenciales(), &prig_plataforma::json::escribir_compacto(&Valor::Mapa(doc)), Some(0o600))
        .map_err(|e| ErrorKaggle(e.to_string()))?;
    Ok(estado())
}

/// `borrar_credenciales`
pub fn borrar_credenciales() -> Mapa {
    let _ = std::fs::remove_file(ruta_credenciales());
    estado()
}

// ---------------------------------------------------------------------------------------------- API

const UA: &str = "Prig-IDE (lector de notebooks; uso educativo local)";

/// `_pedir(ruta, params, c, obligar_cuenta)`: GET a la API con las credenciales y los mensajes de error de Prig
pub fn pedir(ruta: &str, params: &[(&str, String)], cuenta: Option<&Cuenta>, obligar_cuenta: bool) -> Result<Valor, ErrorKaggle> {
    let propia;
    let c = match cuenta {
        Some(c) => Some(c),
        None => {
            propia = credenciales();
            propia.as_ref()
        }
    };
    if obligar_cuenta && c.is_none() {
        return error("Para buscar en Kaggle hace falta conectar tu cuenta. Sin ella puedes abrir un notebook pegando su enlace.");
    }
    let cliente = reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(30)).build().map_err(|e| ErrorKaggle(e.to_string()))?;
    let mut r = cliente.get(format!("{}/{ruta}", api())).query(params).header("User-Agent", UA);
    match c {
        Some(Cuenta::Token { token, .. }) => r = r.bearer_auth(token),
        Some(Cuenta::Clave { usuario, clave, .. }) => r = r.basic_auth(usuario.texto_py(), Some(clave)),
        None => {}
    }
    let Ok(r) = r.send() else { return error("Sin conexión con Kaggle: comprueba internet.") };
    match r.status().as_u16() {
        200 => {}
        401 => return error("Kaggle no aceptó tus credenciales: crea un token nuevo en kaggle.com → Settings → API y vuelve a conectar."),
        403 => return error("Kaggle no permite ver ese notebook (puede ser privado)."),
        404 => return error("Ese notebook no existe o ya no es público."),
        429 => return error("Kaggle limitó las peticiones por un momento. Espera unos segundos y reintenta."),
        s => return Err(ErrorKaggle(format!("Kaggle respondió {s}."))),
    }
    let t = r.text().map_err(|_| ErrorKaggle("Sin conexión con Kaggle: comprueba internet.".into()))?;
    prig_plataforma::json::leer(&t).map_err(|_| ErrorKaggle("Kaggle devolvió una respuesta que no se puede leer.".into()))
}

// ---------------------------------------------------------------------------------------------- colecciones

pub const TIPOS: [&str; 3] = ["notebook", "dataset", "competicion"];
pub const COLORES: [&str; 8] = ["#20beff", "#cba6f7", "#a6e3a1", "#f9e2af", "#fab387", "#f38ba8", "#94e2d5", "#89b4fa"];
const CAMPOS_ITEM: [&str; 6] = ["titulo", "subtitulo", "autor", "imagen", "votos", "url"];
const MAX_COLECCIONES: usize = 200;
const MAX_ITEMS: usize = 1000;

/// Un error que en Python no era `ErrorKaggle` (un archivo con otra forma): 500
#[derive(Debug)]
pub enum Fallo {
    Usuario(ErrorKaggle),
    Interno,
}

impl From<ErrorKaggle> for Fallo {
    fn from(e: ErrorKaggle) -> Fallo {
        Fallo::Usuario(e)
    }
}

static CERROJO: Mutex<()> = Mutex::new(());

fn ruta_colecciones() -> PathBuf {
    carpeta().join("colecciones.json")
}

fn ahora_s() -> String {
    py::ahora_iso().chars().take(19).collect()
}

/// `_leer()`: el documento, con `colecciones` (cada una un objeto con `items`, lista de objetos con `tipo` y `ref`)
fn leer_doc() -> Result<Mapa, Fallo> {
    let mut d = leer_objeto(&ruta_colecciones()).unwrap_or_default();
    if !d.contiene("colecciones") {
        d.poner("colecciones", Valor::Lista(Vec::new()));
    }
    Ok(d)
}

fn cols(d: &Mapa) -> Result<Vec<Mapa>, Fallo> {
    match d.get("colecciones") {
        Some(Valor::Lista(l)) => l.iter().map(|c| if let Valor::Mapa(m) = c { Ok(m.clone()) } else { Err(Fallo::Interno) }).collect(),
        _ => Err(Fallo::Interno),
    }
}

fn items(c: &Mapa) -> Result<Vec<Mapa>, Fallo> {
    match c.get("items") {
        Some(Valor::Lista(l)) => l.iter().map(|i| if let Valor::Mapa(m) = i { Ok(m.clone()) } else { Err(Fallo::Interno) }).collect(),
        _ => Err(Fallo::Interno),
    }
}

fn texto_req(m: &Mapa, k: &str) -> Result<String, Fallo> {
    match m.get(k) {
        Some(Valor::Texto(t)) => Ok(t.clone()),
        _ => Err(Fallo::Interno),
    }
}

fn escribir_doc(cs: Vec<Mapa>, mut d: Mapa) -> Result<(), Fallo> {
    d.poner("colecciones", Valor::Lista(cs.into_iter().map(Valor::Mapa).collect()));
    escribir_de_una_vez(&ruta_colecciones(), &prig_plataforma::json::escribir(&Valor::Mapa(d), 1), None).map_err(|_| Fallo::Interno)
}

/// `sorted(key=x.get(k) or "", reverse=True)` (estable)
fn ordenar_desc(v: &mut [Mapa], k: &str) {
    v.sort_by_key(|m| std::cmp::Reverse(match m.get(k) {
        Some(Valor::Texto(t)) => t.clone(),
        _ => String::new(),
    }));
}

/// `_resumen(c)`
pub fn resumen(c: &Mapa) -> Result<Mapa, Fallo> {
    let its = items(c)?;
    let mut cuenta = Mapa::new();
    for t in TIPOS {
        cuenta.poner(t, Valor::Entero(0));
    }
    for it in &its {
        let tipo = texto_req(it, "tipo")?;
        let n = cuenta.get(&tipo).and_then(Valor::entero).unwrap_or(0);
        cuenta.poner(tipo, Valor::Entero(n + 1));
    }
    let portadas: Vec<Valor> = its.iter().filter_map(|i| i.get("imagen").filter(|v| v.verdad()).cloned()).take(4).collect();
    let mut r = Mapa::new();
    for k in ["id", "nombre", "descripcion", "color", "creada", "actualizada"] {
        r.poner(k, c.get(k).cloned().ok_or(Fallo::Interno)?);
    }
    Ok(r.con("total", Valor::Entero(its.len() as i128)).con("cuenta", cuenta).con("portadas", Valor::Lista(portadas)))
}

/// `listar()`, `guardados()` y los colores (`GET /api/kaggle/colecciones`)
pub fn listado() -> Result<Mapa, Fallo> {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let mut cs = cols(&leer_doc()?)?;
    let mut guardados = Mapa::new();
    for c in &cs {
        for it in items(c)? {
            let clave = format!("{}:{}", texto_req(&it, "tipo")?, texto_req(&it, "ref")?);
            let mut ids = match guardados.get(&clave) {
                Some(Valor::Lista(l)) => l.clone(),
                _ => Vec::new(),
            };
            ids.push(c.get("id").cloned().ok_or(Fallo::Interno)?);
            guardados.poner(clave, Valor::Lista(ids));
        }
    }
    ordenar_desc(&mut cs, "actualizada");
    let resumenes: Vec<Valor> = cs.iter().map(|c| resumen(c).map(Valor::Mapa)).collect::<Result<_, _>>()?;
    Ok(Mapa::new()
        .con("colecciones", Valor::Lista(resumenes))
        .con("guardados", guardados)
        .con("colores", Valor::Lista(COLORES.iter().map(|c| Valor::Texto(c.to_string())).collect())))
}

fn posicion(cs: &[Mapa], id: &str) -> Result<usize, Fallo> {
    cs.iter().position(|c| matches!(c.get("id"), Some(Valor::Texto(t)) if t == id)).ok_or_else(|| Fallo::Usuario(ErrorKaggle("Esa colección no existe.".into())))
}

/// `obtener(id)`: la colección con sus elementos (lo último añadido primero)
pub fn obtener(id: &str) -> Result<Mapa, Fallo> {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let cs = cols(&leer_doc()?)?;
    let c = &cs[posicion(&cs, id)?];
    let mut its = items(c)?;
    ordenar_desc(&mut its, "anadido");
    Ok(resumen(c)?.con("items", Valor::Lista(its.into_iter().map(Valor::Mapa).collect())))
}

/// `_limpiar_nombre`: espacios colapsados, hasta 80 caracteres
fn limpiar_nombre(nombre: &str) -> Result<String, ErrorKaggle> {
    let n: String = py::strip(nombre).split_whitespace().collect::<Vec<_>>().join(" ").chars().take(80).collect();
    if n.is_empty() {
        return error("Ponle un nombre a la colección.");
    }
    Ok(n)
}

fn mismo_nombre(a: &str, b: &str) -> bool {
    a.to_lowercase() == b.to_lowercase()
}

/// `crear(nombre, descripcion, color)`
pub fn crear(nombre: &str, descripcion: &str, color: Option<&str>) -> Result<Mapa, Fallo> {
    let nombre = limpiar_nombre(nombre)?;
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let d = leer_doc()?;
    let mut cs = cols(&d)?;
    if cs.len() >= MAX_COLECCIONES {
        return Err(ErrorKaggle(format!("Como mucho {MAX_COLECCIONES} colecciones.")).into());
    }
    for c in &cs {
        if mismo_nombre(&texto_req(c, "nombre")?, &nombre) {
            return Err(ErrorKaggle(format!("Ya tienes una colección llamada «{nombre}».")).into());
        }
    }
    let color = match color {
        Some(c) if COLORES.contains(&c) => c.to_string(),
        _ => COLORES[cs.len() % COLORES.len()].to_string(),
    };
    let ahora = ahora_s();
    let c = Mapa::new()
        .con("id", uuid_corto(10))
        .con("nombre", nombre)
        .con("descripcion", py::strip(descripcion).chars().take(400).collect::<String>())
        .con("color", color)
        .con("creada", ahora.clone())
        .con("actualizada", ahora)
        .con("items", Valor::Lista(Vec::new()));
    cs.push(c.clone());
    escribir_doc(cs, d)?;
    resumen(&c)
}

fn uuid_corto(n: usize) -> String {
    let mut b = [0u8; 16];
    // SAFETY: getrandom llena el búfer que se le da
    unsafe {
        libc::getrandom(b.as_mut_ptr() as *mut libc::c_void, b.len(), 0);
    }
    b.iter().map(|x| format!("{x:02x}")).collect::<String>()[..n].to_string()
}

/// `editar(id, nombre, descripcion, color)` (None = no se toca)
pub fn editar(id: &str, nombre: Option<&str>, descripcion: Option<&str>, color: Option<&str>) -> Result<Mapa, Fallo> {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let d = leer_doc()?;
    let mut cs = cols(&d)?;
    let i = posicion(&cs, id)?;
    if let Some(n) = nombre {
        let n = limpiar_nombre(n)?;
        for o in &cs {
            if o.texto("id") != Some(id) && mismo_nombre(&texto_req(o, "nombre")?, &n) {
                return Err(ErrorKaggle(format!("Ya tienes una colección llamada «{n}».")).into());
            }
        }
        cs[i].poner("nombre", n);
    }
    if let Some(desc) = descripcion {
        cs[i].poner("descripcion", py::strip(desc).chars().take(400).collect::<String>());
    }
    if let Some(c) = color.filter(|c| COLORES.contains(c)) {
        cs[i].poner("color", c);
    }
    cs[i].poner("actualizada", ahora_s());
    let c = cs[i].clone();
    escribir_doc(cs, d)?;
    resumen(&c)
}

/// `borrar(id)`
pub fn borrar(id: &str) -> Result<Mapa, Fallo> {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let d = leer_doc()?;
    let mut cs = cols(&d)?;
    posicion(&cs, id)?;
    cs.retain(|c| !matches!(c.get("id"), Some(Valor::Texto(t)) if t == id));
    escribir_doc(cs, d)?;
    Ok(Mapa::new().con("ok", true))
}

/// `ref_competicion`: el slug de una competición (o su enlace)
pub fn ref_competicion(texto: &str) -> Result<String, ErrorKaggle> {
    let t = py::strip(texto);
    let slug = match ENLACE_COMPETICION.captures(t) {
        Some(c) => c[1].to_string(),
        None => t.trim_matches('/').to_string(),
    };
    if !SLUG.is_match(&slug) || slug.contains("..") {
        return error("Eso no es una competición de Kaggle: pega un enlace como kaggle.com/competitions/titanic.");
    }
    Ok(slug)
}

/// `_validar_item`
fn validar_item(tipo: &str, r: &str) -> Result<String, ErrorKaggle> {
    if !TIPOS.contains(&tipo) {
        return error("Solo se guardan notebooks, datasets y competiciones.");
    }
    let r = py::strip(r);
    if tipo == "competicion" {
        return ref_competicion(r);
    }
    if !REF_VALIDA.is_match(r) || r.contains("..") {
        return error("Referencia no válida.");
    }
    Ok(r.to_string())
}

fn mismo_item(it: &Mapa, tipo: &str, r: &str) -> bool {
    it.texto("tipo") == Some(tipo) && it.texto("ref") == Some(r)
}

/// `anadir(id, tipo, ref, datos)`: añade (o actualiza) un elemento con lo necesario para pintarlo sin red
pub fn anadir(id: &str, tipo: &str, r: &str, datos: Option<&Mapa>) -> Result<Mapa, Fallo> {
    let r = validar_item(tipo, r)?;
    let vacio = Mapa::new();
    let datos = datos.unwrap_or(&vacio);
    let mut extra = Mapa::new();
    for k in CAMPOS_ITEM {
        extra.poner(k, datos.get(k).cloned().unwrap_or(Valor::Nulo));
    }
    let titulo = match extra.get("titulo") {
        Some(v) if v.verdad() => v.clone(),
        _ => Valor::Texto(r.clone()),
    };
    let titulo = match titulo {
        Valor::Texto(t) => Valor::Texto(t.chars().take(200).collect()),
        // `(x or ref)[:200]`: una lista se recorta; otra cosa (un número) falla en Python
        Valor::Lista(l) => Valor::Lista(l.into_iter().take(200).collect()),
        _ => return Err(Fallo::Interno),
    };
    extra.poner("titulo", titulo);
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let d = leer_doc()?;
    let mut cs = cols(&d)?;
    let i = posicion(&cs, id)?;
    let mut its = items(&cs[i])?;
    match its.iter_mut().find(|it| mismo_item(it, tipo, &r)) {
        Some(e) => {
            for (k, v) in extra.iter() {
                if !v.es_nulo() {
                    e.poner(k.clone(), v.clone());
                }
            }
        }
        None => {
            if its.len() >= MAX_ITEMS {
                return Err(ErrorKaggle(format!("Una colección admite como mucho {MAX_ITEMS} elementos.")).into());
            }
            let mut nuevo = Mapa::new().con("tipo", tipo).con("ref", r.clone());
            for (k, v) in extra.iter() {
                nuevo.poner(k.clone(), v.clone());
            }
            its.push(nuevo.con("nota", "").con("anadido", ahora_s()));
        }
    }
    cs[i].poner("items", Valor::Lista(its.into_iter().map(Valor::Mapa).collect()));
    cs[i].poner("actualizada", ahora_s());
    let c = cs[i].clone();
    escribir_doc(cs, d)?;
    resumen(&c)
}

/// `quitar(id, tipo, ref)`
pub fn quitar(id: &str, tipo: &str, r: &str) -> Result<Mapa, Fallo> {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let d = leer_doc()?;
    let mut cs = cols(&d)?;
    let i = posicion(&cs, id)?;
    let its: Vec<Valor> = items(&cs[i])?.into_iter().filter(|it| !mismo_item(it, tipo, r)).map(Valor::Mapa).collect();
    cs[i].poner("items", Valor::Lista(its));
    cs[i].poner("actualizada", ahora_s());
    let c = cs[i].clone();
    escribir_doc(cs, d)?;
    resumen(&c)
}

/// `anotar(id, tipo, ref, nota)`
pub fn anotar(id: &str, tipo: &str, r: &str, nota: &str) -> Result<Mapa, Fallo> {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let d = leer_doc()?;
    let mut cs = cols(&d)?;
    let i = posicion(&cs, id)?;
    let mut its = items(&cs[i])?;
    let Some(it) = its.iter_mut().find(|it| mismo_item(it, tipo, r)) else {
        return Err(ErrorKaggle("Ese elemento no está en la colección.".into()).into());
    };
    it.poner("nota", py::strip(nota).chars().take(2000).collect::<String>());
    cs[i].poner("items", Valor::Lista(its.into_iter().map(Valor::Mapa).collect()));
    cs[i].poner("actualizada", ahora_s());
    escribir_doc(cs, d)?;
    Ok(Mapa::new().con("ok", true))
}

// ---------------------------------------------------------------------------------------------- lecturas

/// `resumen_lecturas()`: lo leído de cada notebook, lo último primero
pub fn resumen_lecturas() -> Result<Vec<Mapa>, Fallo> {
    let l = leer_objeto(&carpeta().join("lecturas.json")).unwrap_or_default();
    let mut v = Vec::new();
    for (r, x) in l.iter() {
        let Valor::Mapa(x) = x else { return Err(Fallo::Interno) };
        let leidas = match x.get("leidas") {
            None | Some(Valor::Nulo) => 0,
            Some(Valor::Lista(l)) => l.len(),
            Some(Valor::Mapa(m)) => m.len(),
            Some(Valor::Texto(t)) => t.chars().count(),
            Some(v) if !v.verdad() => 0,
            Some(_) => return Err(Fallo::Interno),
        };
        let total = match x.get("total") {
            Some(v) if v.verdad() => v.clone(),
            _ => Valor::Entero(0),
        };
        v.push(
            Mapa::new()
                .con("ref", r.clone())
                .con("titulo", x.get("titulo").cloned().unwrap_or(Valor::Nulo))
                .con("leidas", leidas as i128)
                .con("total", total)
                .con("ultima", x.get("ultima").cloned().unwrap_or(Valor::Nulo))
                .con("ultima_celda", x.get("ultima_celda").cloned().unwrap_or(Valor::Nulo)),
        );
    }
    ordenar_desc(&mut v, "ultima");
    Ok(v)
}

/// `recientes(n)`: lo último guardado en cualquier colección
pub fn recientes(n: usize) -> Result<Vec<Mapa>, Fallo> {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let mut todos = Vec::new();
    for c in cols(&leer_doc()?)? {
        for it in items(&c)? {
            let mut m = it.clone();
            m.poner("coleccion", c.get("nombre").cloned().ok_or(Fallo::Interno)?);
            m.poner("coleccion_id", c.get("id").cloned().ok_or(Fallo::Interno)?);
            m.poner("color", c.get("color").cloned().ok_or(Fallo::Interno)?);
            todos.push(m);
        }
    }
    ordenar_desc(&mut todos, "anadido");
    todos.truncate(n);
    Ok(todos)
}
