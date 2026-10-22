//! El buscador de modelos (`buscador_modelos.py`) en las plataformas desde las que Ollama descarga: ollama.com (sin
//! API: se lee la página de búsqueda y la de etiquetas), Hugging Face y ModelScope (sus API). Antes de descargar,
//! cada variante se comprueba pidiendo su manifiesto al registro. Aquí está todo lo que pide y lee; repartir una
//! búsqueda entre las plataformas, juntar las variantes con sus comprobaciones y el seguimiento siguen en Python
//! (son finos y llaman a esto, sin el GIL).
//!
//! Las direcciones base (ollama.com, huggingface.co, modelscope.cn) y el registro de cada referencia los da quien
//! llama: en Python son atributos que las pruebas cambian por un servidor falso.

use crate::red::{self, ErrorRed, Respuesta};
use prig_plataforma::html::unescape;
use prig_plataforma::py::{self, ErrorPy};
use prig_plataforma::regex_py::ExpresionPy;
use prig_recursos::valor::{Mapa, Valor};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

pub const UA: &str = "Prig-IDE (buscador de modelos local)";
pub const UA_OLLAMA: &str = "ollama/0.34.1 (Prig)";
pub const ACEPTA_MANIFIESTO: &str = "application/vnd.docker.distribution.manifest.v2+json";
pub const CAPACIDADES_OLLAMA: [&str; 6] = ["tools", "thinking", "vision", "embedding", "audio", "cloud"];
pub const EXPANDIR: [&str; 10] =
    ["downloads", "likes", "lastModified", "createdAt", "gguf", "pipeline_tag", "tags", "trendingScore", "gated", "cardData"];

#[derive(Debug)]
pub enum ErrorB {
    /// ErrorBuscador
    Buscador(String),
    Red(ErrorRed),
    Py(ErrorPy),
}

impl From<ErrorRed> for ErrorB {
    fn from(e: ErrorRed) -> ErrorB {
        ErrorB::Red(e)
    }
}

impl From<ErrorPy> for ErrorB {
    fn from(e: ErrorPy) -> ErrorB {
        ErrorB::Py(e)
    }
}

type R<T> = Result<T, ErrorB>;

fn buscador(t: impl Into<String>) -> ErrorB {
    ErrorB::Buscador(t.into())
}

// =========================================================================== expresiones (las de Python)

macro_rules! expresion {
    ($nombre:ident, $patron:expr) => {
        fn $nombre() -> &'static ExpresionPy {
            static E: OnceLock<ExpresionPy> = OnceLock::new();
            E.get_or_init(|| ExpresionPy::compilar($patron, true).expect(stringify!($nombre)))
        }
    };
    ($nombre:ident, $patron:expr, anclada) => {
        fn $nombre() -> &'static ExpresionPy {
            static E: OnceLock<ExpresionPy> = OnceLock::new();
            E.get_or_init(|| ExpresionPy::anclada($patron, true).expect(stringify!($nombre)))
        }
    };
    ($nombre:ident, $patron:expr, entera) => {
        fn $nombre() -> &'static ExpresionPy {
            static E: OnceLock<ExpresionPy> = OnceLock::new();
            E.get_or_init(|| ExpresionPy::entera($patron, true).expect(stringify!($nombre)))
        }
    };
}

expresion!(re_cuant, r"(?i)(?:^|[-_.])((?:UD-)?(?:IQ\d(?:_[A-Z]+)?|Q\d(?:_[A-Z0-9]+)*|TQ\d_\d|F16|F32|BF16|MXFP4(?:_MOE)?|NVFP4))$");
expresion!(re_parte, r"(?i)-(\d{5})-of-(\d{5})$");
expresion!(re_gguf_final, r"(?i)\.gguf$");
expresion!(
    re_ref_valida,
    r"^(?:(?:hf\.co|huggingface\.co|modelscope\.cn)/[\w.\-]+/[\w.\-]+|(?:[a-z0-9][\w.\-]*/)?[a-z0-9][\w.\-]*)(?::[\w.\-]+)?$",
    anclada
);
expresion!(re_etiquetas_html, r"<[^>]+>");
expresion!(re_blancos, r"\s+");
expresion!(re_numero, r"(?i)^([\d.,]+)\s*([KMB])?$", anclada);
expresion!(re_bytes, r"(?i)^([\d.]+)\s*(KB|MB|GB|TB)$", anclada);
expresion!(re_li, r"<li\b");
expresion!(re_enlace_modelo, r#"<a href="/((?:library/)?[a-z0-9][\w.\-]*(?:/[\w.\-]+)?)" class="group w-full""#);
expresion!(re_titulo, r"<h2[^>]*>\s*<span[^>]*>([^<]+)</span>");
expresion!(re_desc, r#"(?s)<p class="max-w-lg[^"]*">(.*?)</p>"#);
expresion!(re_chip, r#"<span\s+class="inline-flex my-1[^"]*">([^<]+)</span>"#);
expresion!(re_tamano, r"(?i)^(?:e?\d+(?:\.\d+)?[bmk]|\d+x\d+(?:\.\d+)?b)$", anclada);
expresion!(re_tamano_entero, r"(?i)e?\d+(?:\.\d+)?[bmk]|\d+x\d+(?:\.\d+)?b", entera);
expresion!(re_pulls, r"(?i)([\d.,]+[KMB]?)\s*Pulls?");
expresion!(re_tags, r"(?i)(\d+)\s*Tags?");
expresion!(re_updated, r"(?i)Updated\s+(.+?ago|yesterday|today)");
expresion!(re_tam_variante, r"([\d.]+\s*(?:KB|MB|GB|TB))");
expresion!(re_contexto, r"([\d.]+[KM]?)\s*context window");
expresion!(re_entrada, r"((?:Text|Image|Audio)(?:,\s*(?:Text|Image|Audio))*)\s*input");
expresion!(re_digest, r"\b([0-9a-f]{12})\b");
expresion!(re_cuando, r"input\s*•\s*(.+?ago|yesterday|today)");
expresion!(re_link_next, r#"<([^>]+)>;\s*rel="next""#);
expresion!(re_repo, r"^[\w.\-]+/[\w.\-]+$", anclada);
expresion!(re_web, r"(?i)^(?:https?://)?(?:www\.)?(ollama\.com|huggingface\.co|hf\.co|modelscope\.cn)(?:/(.*))?$", anclada);
expresion!(re_segmento, r"^[\w.\-]+$", anclada);
expresion!(re_ollama_run, r"(?i)^ollama\s+(?:run|pull)\s+");
expresion!(re_repo_entero, r"[\w.\-]+/[\w.\-]+(?::[\w.\-]+)?", entera);
expresion!(re_nombre_tag, r"[\w.\-]+:[\w.\-]+", entera);
expresion!(re_palabra, r"\w");
expresion!(re_gguf_sufijo, r"[-_. ]?gguf$");
expresion!(re_no_alnum, r"[^a-z0-9]");
expresion!(re_no_alnum_mas, r"[^a-z0-9]+");
expresion!(re_ficha_entera, r"[\w.\-]+(?:/[\w.\-]+)?", entera);
expresion!(re_meta_desc, r#"<meta name="description" content="([^"]*)""#);
expresion!(re_chip_ficha, r#"<span\s+class="inline-flex[^"]*"[^>]*>\s*([^<]+?)\s*</span>"#);
expresion!(re_clave_ollama, r"[a-z0-9][a-z0-9.\-_]*", entera);

fn grupo(e: &ExpresionPy, t: &str, i: usize) -> Option<String> {
    e.buscar(t).and_then(|g| g.get(i).cloned().flatten())
}

// =========================================================================== utilidades

/// `_texto(fragmento)`: sin etiquetas, sin entidades y con los blancos juntos
pub fn texto(fragmento: &str) -> String {
    let sin = re_etiquetas_html().sustituir(fragmento, " ");
    py::strip(&re_blancos().sustituir(&unescape(&sin), " ")).to_string()
}

/// `float(texto)` con el ValueError de Python
fn float_py(t: &str) -> Result<f64, ErrorPy> {
    prig_recursos::valor::real_de_texto(t)
        .ok_or_else(|| ErrorPy::Valor(format!("could not convert string to float: {}", Valor::Texto(t.into()).repr_py())))
}

/// `_numero("105.3K")` → 105300
pub fn numero(t: &str) -> Result<Option<i128>, ErrorPy> {
    let Some(g) = re_numero().buscar(py::strip(t)) else { return Ok(None) };
    let valor = float_py(&g[1].clone().unwrap_or_default().replace(',', ""))?;
    let mult = match g[2].as_deref().map(|x| x.to_uppercase()) {
        Some(x) if x == "K" => 1e3,
        Some(x) if x == "M" => 1e6,
        Some(x) if x == "B" => 1e9,
        _ => 1.0,
    };
    Ok(Some((valor * mult).trunc() as i128))
}

/// `_bytes("5.2GB")` → 5200000000
pub fn bytes(t: &str) -> Result<Option<i128>, ErrorPy> {
    let Some(g) = re_bytes().buscar(py::strip(t)) else { return Ok(None) };
    let valor = float_py(g[1].as_deref().unwrap_or(""))?;
    let mult = match g[2].as_deref().unwrap_or("").to_uppercase().as_str() {
        "KB" => 1e3,
        "MB" => 1e6,
        "GB" => 1e9,
        _ => 1e12,
    };
    Ok(Some((valor * mult).trunc() as i128))
}

/// `cuantizacion_de("Qwen3-8B-UD-Q4_K_XL.gguf")` → "UD-Q4_K_XL"
pub fn cuantizacion_de(archivo: &str) -> Option<String> {
    let base = py::basename(archivo);
    let base = re_gguf_final().sustituir(&base, "");
    let base = re_parte().sustituir(&base, "");
    grupo(re_cuant(), &base, 1)
}

/// `validar_ref(ref)`
pub fn validar_ref(r: &str) -> R<String> {
    let r = py::strip(r).to_string();
    if re_ref_valida().buscar(&r).is_none() || r.contains("..") {
        return Err(buscador(format!("Nombre de modelo no válido: {}", Valor::Texto(r).repr_py())));
    }
    Ok(r)
}

/// `_motivo_registro`: lo que explica el registro, traducido
pub fn motivo_registro(codigo: u16, cuerpo: &str, tag: &str) -> String {
    let t = cuerpo.to_lowercase();
    if t.contains("sharded") {
        return "Partido en varios archivos: Ollama todavía no descarga GGUF partidos desde el registro.".into();
    }
    if t.contains("not a valid quantization") {
        return format!("El registro no reconoce «{tag}» como cuantización: esta variante no se puede descargar con Ollama.");
    }
    if t.contains("does not exist") || codigo == 404 {
        return "No existe en el registro.".into();
    }
    match codigo {
        401 => "Requiere iniciar sesión o aceptar una licencia.".into(),
        403 => "Acceso denegado: modelo privado o con licencia por aceptar.".into(),
        400 => "El registro no puede servir esta variante a Ollama.".into(),
        c => format!("El registro respondió HTTP {c}."),
    }
}

pub fn fuente_de_ref(r: &str) -> &'static str {
    if r.starts_with("hf.co/") || r.starts_with("huggingface.co/") {
        "huggingface"
    } else if r.starts_with("modelscope.cn/") {
        "modelscope"
    } else {
        "ollama"
    }
}

// =========================================================================== caché

/// `Cache`: lo pedido hace poco, con su edad (time.time())
#[derive(Default)]
pub struct Cache {
    datos: Mutex<HashMap<String, (f64, Valor, u64)>>,
    orden: std::sync::atomic::AtomicU64,
}

fn ahora() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

impl Cache {
    pub fn obtener(&self, clave: &str, ttl: f64) -> Option<Valor> {
        let d = self.datos.lock().unwrap();
        match d.get(clave) {
            Some((t, v, _)) if ahora() - t < ttl => Some(v.clone()),
            _ => None,
        }
    }

    pub fn guardar(&self, clave: &str, valor: Valor) -> Valor {
        let mut d = self.datos.lock().unwrap();
        let n = self.orden.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        d.insert(clave.to_string(), (ahora(), valor.clone(), n));
        if d.len() > 500 {
            let mut claves: Vec<(f64, u64, String)> = d.iter().map(|(k, (t, _, n))| (*t, *n, k.clone())).collect();
            claves.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal).then(a.1.cmp(&b.1)));
            for (_, _, k) in claves.into_iter().take(100) {
                d.remove(&k);
            }
        }
        valor
    }
}

// =========================================================================== peticiones

fn get(url: &str, params: &[(&str, String)], cabeceras: &[(&str, &str)], segundos: f64) -> R<Respuesta> {
    Ok(red::pedir("GET", &red::con_params(url, params), None, cabeceras, segundos)?)
}

fn json_de(r: &Respuesta) -> R<Valor> {
    Ok(r.json()?)
}

fn getv(v: &Valor, k: &str) -> R<Valor> {
    Ok(py::get(v, k, Valor::Nulo).map_err(ErrorPy::Atributo)?)
}

fn o_vacio(v: Valor) -> Valor {
    if v.verdad() {
        v
    } else {
        Valor::Mapa(Mapa::new())
    }
}

fn o_lista(v: Valor) -> Valor {
    if v.verdad() {
        v
    } else {
        Valor::Lista(vec![])
    }
}

/// `v[k]` con los errores de Python
fn item(v: &Valor, k: &str) -> R<Valor> {
    match v {
        Valor::Mapa(m) => m.get(k).cloned().ok_or_else(|| ErrorB::Py(ErrorPy::Clave(Valor::Texto(k.into()).repr_py()))),
        Valor::Lista(_) => Err(ErrorB::Py(ErrorPy::Tipo("list indices must be integers or slices, not str".into()))),
        Valor::Texto(_) => Err(ErrorB::Py(ErrorPy::Tipo("string indices must be integers, not 'str'".into()))),
        otro => Err(ErrorB::Py(ErrorPy::Tipo(format!("'{}' object is not subscriptable", py::tipo(otro))))),
    }
}

/// `" · ".join(x for x in partes if x)`: los vacíos fuera; un elemento que no es texto es TypeError
fn unir_partes(partes: Vec<Valor>) -> R<String> {
    let l = Valor::Lista(partes.into_iter().filter(|x| x.verdad()).collect());
    Ok(py::unir(" · ", &l).map_err(ErrorPy::Tipo)?)
}

fn texto_de(v: &Valor, metodo: &str) -> R<String> {
    match v {
        Valor::Texto(t) => Ok(t.clone()),
        otro => Err(ErrorB::Py(ErrorPy::Atributo(format!("'{}' object has no attribute '{metodo}'", py::tipo(otro))))),
    }
}

fn iter(v: &Valor) -> R<Vec<Valor>> {
    Ok(py::iterar(v).map_err(ErrorPy::Tipo)?)
}

fn suma(valores: impl Iterator<Item = Valor>) -> Valor {
    let mut total = Valor::Entero(0);
    for v in valores {
        total = match (total, v) {
            (Valor::Entero(a), Valor::Entero(b)) => Valor::Entero(a + b),
            (Valor::Entero(a), Valor::Bool(b)) => Valor::Entero(a + b as i128),
            (a, b) => Valor::Real(a.num().unwrap_or(0.0) + b.num().unwrap_or(0.0)),
        };
    }
    total
}

/// `comprobar(ref)`: ¿se puede descargar? Pide el manifiesto al registro (`registro`, `repo`, `tag` de
/// `registro_de`): el tamaño exacto, las capas y el digest con el que luego se detectan actualizaciones
pub fn comprobar(r: &str, registro: (&str, &str, &str), cache: &Cache, segundos: f64) -> R<Valor> {
    let r = validar_ref(r)?;
    let clave = format!("comprobar:{r}");
    if let Some(g) = cache.obtener(&clave, 600.0) {
        if g.verdad() {
            return Ok(g);
        }
    }
    let (reg, repo, tag) = registro;
    let ua = if reg.contains("modelscope.cn") { UA_OLLAMA } else { UA };
    let url = format!("{reg}/v2/{repo}/manifests/{tag}");
    let resp = match red::pedir("GET", &url, None, &[("Accept", ACEPTA_MANIFIESTO), ("User-Agent", ua)], segundos) {
        Ok(x) => x,
        Err(e) => {
            return Ok(Valor::Mapa(
                Mapa::new().con("ref", r).con("descargable", false).con("motivo", format!("Sin conexión con el registro: {}", e.texto())),
            ))
        }
    };
    if resp.estado != 200 {
        let m = Mapa::new()
            .con("ref", r)
            .con("descargable", false)
            .con("codigo", resp.estado as i64)
            .con("motivo", motivo_registro(resp.estado, &resp.texto(), tag));
        return Ok(cache.guardar(&clave, Valor::Mapa(m)));
    }
    let Ok(m) = resp.json() else {
        return Ok(Valor::Mapa(Mapa::new().con("ref", r).con("descargable", false).con("motivo", "Respuesta del registro no válida")));
    };
    let capas = iter(&o_lista(getv(&m, "layers")?))?;
    let mut tipos: Vec<String> = Vec::new();
    for c in &capas {
        let mt = match &c {
            Valor::Mapa(x) if x.contiene("mediaType") => x.valor("mediaType").clone(),
            Valor::Mapa(_) => Valor::Texto(String::new()),
            otro => return Err(ErrorB::Py(ErrorPy::Atributo(format!("'{}' object has no attribute 'get'", py::tipo(otro))))),
        };
        let t = texto_de(&mt, "split")?;
        let ultimo = t.rsplit('.').next().unwrap_or("").to_string();
        if !tipos.contains(&ultimo) {
            tipos.push(ultimo);
        }
    }
    tipos.sort();
    let total = suma(capas.iter().map(|c| match c {
        Valor::Mapa(x) if x.contiene("size") => x.valor("size").clone(),
        _ => Valor::Entero(0),
    }));
    let vision = tipos.iter().any(|t| t == "projector");
    let digest = crate::gestion::hex(&Sha256::digest(&resp.cuerpo));
    let res = Mapa::new()
        .con("ref", r)
        .con("descargable", true)
        .con("bytes", total)
        .con("capas", Valor::Lista(tipos.into_iter().map(Valor::Texto).collect()))
        .con("vision", vision)
        .con("digest", digest);
    Ok(cache.guardar(&clave, Valor::Mapa(res)))
}

// =========================================================================== ollama.com

fn quitar_library(ruta: &str) -> &str {
    ruta.strip_prefix("library/").unwrap_or(ruta)
}

/// `Ollama.buscar`: la página de búsqueda de ollama.com (las siguientes, como las pide htmx)
pub fn ollama_buscar(base: &str, consulta: &str, orden: &str, capacidad: Option<&str>, pagina: i64, cache: &Cache) -> R<Valor> {
    let mut params: Vec<(&str, String)> = Vec::new();
    if !consulta.is_empty() {
        params.push(("q", consulta.to_string()));
    }
    if orden == "recientes" {
        params.push(("o", "newest".into()));
    }
    if let Some(c) = capacidad.filter(|c| CAPACIDADES_OLLAMA.contains(c)) {
        params.push(("c", c.to_string()));
    }
    let mut cabeceras = vec![("User-Agent", UA)];
    if pagina > 1 {
        // las páginas siguientes las carga htmx al hacer scroll: sin esta cabecera ollama.com repite la primera
        params.push(("page", pagina.to_string()));
        cabeceras.push(("HX-Request", "true"));
    }
    let mut ordenados = params.clone();
    ordenados.sort_by(|a, b| a.0.cmp(b.0));
    let clave = format!("ollama:{ordenados:?}");
    if let Some(g) = cache.obtener(&clave, 600.0) {
        if g.verdad() {
            return Ok(g);
        }
    }
    let r = get(&format!("{base}/search"), &params, &cabeceras, 25.0)?;
    if r.estado != 200 {
        return Err(buscador(format!("ollama.com respondió {}", r.estado)));
    }
    let t = r.texto();
    let modelos = analizar_busqueda(&t)?;
    let hay_mas = t.contains(&format!("hx-get=\"/search?page={}", pagina + 1));
    let siguiente = if hay_mas && !modelos.is_empty() { Valor::Entero((pagina + 1) as i128) } else { Valor::Nulo };
    Ok(cache.guardar(&clave, Valor::Mapa(Mapa::new().con("modelos", Valor::Lista(modelos)).con("siguiente", siguiente))))
}

/// `Ollama.analizar_busqueda(pagina)`
pub fn analizar_busqueda(pagina: &str) -> R<Vec<Valor>> {
    let mut salida = Vec::new();
    for bloque in re_li().partir(pagina).into_iter().skip(1) {
        let Some(ruta) = grupo(re_enlace_modelo(), &bloque, 1) else { continue };
        let nombre = quitar_library(&ruta).to_string();
        let titulo = grupo(re_titulo(), &bloque, 1);
        let desc = grupo(re_desc(), &bloque, 1);
        let chips: Vec<String> = re_chip().todos(&bloque).into_iter().map(|g| py::strip(&unescape(g[1].as_deref().unwrap_or(""))).to_string()).collect();
        let tamanos: Vec<String> = chips.iter().filter(|c| re_tamano().buscar(c).is_some()).cloned().collect();
        let capacidades: Vec<String> = chips.iter().filter(|c| !tamanos.contains(c)).cloned().collect();
        let plano = texto(&bloque);
        let descargas = match grupo(re_pulls(), &plano, 1) {
            Some(d) => numero(&d)?.map(Valor::Entero).unwrap_or(Valor::Nulo),
            None => Valor::Nulo,
        };
        let etiquetas = match grupo(re_tags(), &plano, 1) {
            Some(e) => prig_recursos::valor::entero_de_texto(&e).map(Valor::Entero).unwrap_or(Valor::Nulo),
            None => Valor::Nulo,
        };
        let actualizado = grupo(re_updated(), &plano, 1).map(Valor::Texto).unwrap_or(Valor::Nulo);
        let solo_nube = capacidades == ["cloud"] || (capacidades.iter().any(|c| c == "cloud") && tamanos.is_empty());
        let autor = if nombre.contains('/') { nombre.split('/').next().unwrap_or("").to_string() } else { "ollama".into() };
        let lista = |l: Vec<String>| Valor::Lista(l.into_iter().map(Valor::Texto).collect());
        salida.push(Valor::Mapa(
            Mapa::new()
                .con("fuente", "ollama")
                .con("id", nombre.clone())
                .con("nombre", titulo.map(|t| py::strip(&unescape(&t)).to_string()).unwrap_or_else(|| nombre.clone()))
                .con("autor", autor)
                .con("oficial", !nombre.contains('/'))
                .con("descripcion", desc.map(|d| texto(&d)).unwrap_or_default())
                .con("capacidades", lista(capacidades))
                .con("tamanos", lista(tamanos))
                .con("descargas", descargas)
                .con("variantes_total", etiquetas)
                .con("actualizado", actualizado)
                .con("url", format!("https://ollama.com/{ruta}"))
                .con("solo_nube", solo_nube),
        ));
    }
    Ok(salida)
}

/// `Ollama.variantes(nombre)`: la página de etiquetas
pub fn ollama_variantes(base: &str, nombre: &str, cache: &Cache) -> R<Valor> {
    let nombre = validar_ref(nombre)?;
    let clave = format!("ollama-variantes:{nombre}");
    if let Some(g) = cache.obtener(&clave, 1800.0) {
        if g.verdad() {
            return Ok(g);
        }
    }
    let ruta = if nombre.contains('/') { nombre.clone() } else { format!("library/{nombre}") };
    let r = get(&format!("{base}/{ruta}/tags"), &[], &[("User-Agent", UA)], 25.0)?;
    if r.estado != 200 {
        return Err(buscador(format!("No se encontró {nombre} en ollama.com ({})", r.estado)));
    }
    let v = analizar_etiquetas(&r.texto(), &ruta)?;
    Ok(cache.guardar(&clave, Valor::Mapa(Mapa::new().con("id", nombre).con("variantes", Valor::Lista(v)))))
}

/// `Ollama.analizar_etiquetas(pagina, ruta)`
pub fn analizar_etiquetas(pagina: &str, ruta: &str) -> R<Vec<Valor>> {
    let patron = format!(r#"(?s)<a href="/{}:([^"]+)" class="md:hidden[^"]*"(.*?)</a>"#, regex::escape(ruta));
    let e = ExpresionPy::compilar(&patron, true).map_err(buscador)?;
    let mut vistos: Vec<String> = Vec::new();
    let mut salida = Vec::new();
    for g in e.todos(pagina) {
        let tag = unescape(g[1].as_deref().unwrap_or(""));
        if vistos.contains(&tag) {
            continue;
        }
        vistos.push(tag.clone());
        let plano = texto(g[2].as_deref().unwrap_or(""));
        let tam = match grupo(re_tam_variante(), &plano, 1) {
            Some(t) => bytes(&t)?.map(Valor::Entero).unwrap_or(Valor::Nulo),
            None => Valor::Nulo,
        };
        let ctx = grupo(re_contexto(), &plano, 1).map(Valor::Texto).unwrap_or(Valor::Nulo);
        let entrada: Vec<Valor> = match grupo(re_entrada(), &plano, 1) {
            Some(x) => x.split(',').map(|y| Valor::Texto(py::strip(y).to_string())).collect(),
            None => vec![],
        };
        let digest = grupo(re_digest(), &plano, 1).map(Valor::Texto).unwrap_or(Valor::Nulo);
        let cuando = grupo(re_cuando(), &plano, 1).map(Valor::Texto).unwrap_or(Valor::Nulo);
        let r = format!("{}:{tag}", quitar_library(ruta));
        let bajo = tag.to_lowercase();
        let nota = if bajo.contains("mlx") {
            Valor::from("Formato MLX: solo para Mac con Apple Silicon.")
        } else if bajo.contains("cloud") {
            Valor::from("Se ejecuta en la nube de Ollama: requiere cuenta.")
        } else {
            Valor::Nulo
        };
        let tras: String = plano.split_once(tag.as_str()).map(|(_, b)| b).unwrap_or(&plano).chars().take(40).collect();
        let descargable = if nota.es_nulo() { Valor::Nulo } else { Valor::Bool(false) };
        salida.push(Valor::Mapa(
            Mapa::new()
                .con("ref", r)
                .con("etiqueta", tag.clone())
                .con("bytes", tam)
                .con("contexto", ctx)
                .con("entrada", Valor::Lista(entrada))
                .con("digest", digest)
                .con("actualizado", cuando)
                .con("predeterminada", tras.contains("latest"))
                .con("nota", nota)
                .con("descargable", descargable),
        ));
    }
    Ok(salida)
}

// =========================================================================== Hugging Face

/// `base64.urlsafe_b64decode` de Python (sin validar: se saltan los caracteres que no son del alfabeto)
fn b64_decodificar(t: &str) -> Option<Vec<u8>> {
    let valor = |c: u8| -> Option<u32> {
        Some(match c {
            b'A'..=b'Z' => c - b'A',
            b'a'..=b'z' => c - b'a' + 26,
            b'0'..=b'9' => c - b'0' + 52,
            b'-' | b'+' => 62,
            b'_' | b'/' => 63,
            _ => return None,
        } as u32)
    };
    let mut salida = Vec::new();
    let (mut acum, mut n, mut rellenos) = (0u32, 0, 0);
    for &c in t.as_bytes() {
        if c == b'=' {
            if n >= 2 {
                rellenos += 1;
                if n + rellenos >= 4 {
                    break;
                }
            }
            continue;
        }
        let Some(v) = valor(c) else { continue };
        if rellenos > 0 {
            // datos después de un relleno incompleto: Python los sigue leyendo
            rellenos = 0;
        }
        acum = (acum << 6) | v;
        n += 1;
        if n == 4 {
            salida.extend_from_slice(&[(acum >> 16) as u8, (acum >> 8) as u8, acum as u8]);
            acum = 0;
            n = 0;
        }
    }
    match (n, rellenos) {
        (0, _) => Some(salida),
        (2, r) if r >= 2 => {
            salida.push((acum >> 4) as u8);
            Some(salida)
        }
        (3, r) if r >= 1 => {
            salida.extend_from_slice(&[(acum >> 10) as u8, (acum >> 2) as u8]);
            Some(salida)
        }
        _ => None,
    }
}

/// `base64.urlsafe_b64encode`
fn b64_codificar(b: &[u8]) -> String {
    const A: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut s = String::new();
    for trozo in b.chunks(3) {
        let n = (trozo[0] as u32) << 16 | (*trozo.get(1).unwrap_or(&0) as u32) << 8 | *trozo.get(2).unwrap_or(&0) as u32;
        for i in 0..4 {
            if i <= trozo.len() {
                s.push(A[((n >> (18 - 6 * i)) & 63) as usize] as char);
            } else {
                s.push('=');
            }
        }
    }
    s
}

fn orden_hf(orden: &str) -> &'static str {
    match orden {
        "relevancia" | "descargas" => "downloads",
        "tendencia" => "trendingScore",
        "me_gusta" => "likes",
        "actualizados" => "lastModified",
        "recientes" => "createdAt",
        _ => "downloads",
    }
}

/// `HuggingFace.buscar`: la API de modelos con `filter=gguf`, paginada por la cabecera Link
pub fn hf_buscar(base: &str, consulta: &str, orden: &str, pagina: Option<&str>, limite: i64, cache: &Cache) -> R<Valor> {
    let (url, params): (String, Vec<(&str, String)>) = match pagina.filter(|p| !p.is_empty()) {
        Some(p) => {
            let url = b64_decodificar(p).and_then(|b| String::from_utf8(b).ok()).ok_or_else(|| buscador("Página no válida"))?;
            if !url.starts_with(&format!("{base}/api/models?")) {
                return Err(buscador("Página no válida"));
            }
            (url, vec![])
        }
        None => {
            let mut p: Vec<(&str, String)> = vec![
                ("filter", "gguf".into()),
                ("sort", orden_hf(orden).into()),
                ("direction", "-1".into()),
                ("limit", limite.to_string()),
            ];
            for e in EXPANDIR {
                p.push(("expand[]", e.into()));
            }
            if !consulta.is_empty() {
                p.push(("search", consulta.to_string()));
            }
            (format!("{base}/api/models"), p)
        }
    };
    let clave = format!("hf:{url}{params:?}");
    if let Some(g) = cache.obtener(&clave, 600.0) {
        if g.verdad() {
            return Ok(g);
        }
    }
    let r = get(&url, &params, &[("User-Agent", UA)], 25.0)?;
    if r.estado != 200 {
        return Err(buscador(format!("Hugging Face respondió {}", r.estado)));
    }
    let siguiente = match grupo(re_link_next(), &r.link, 1) {
        Some(s) => Valor::Texto(b64_codificar(s.as_bytes())),
        None => Valor::Nulo,
    };
    let mut modelos = Vec::new();
    for x in iter(&json_de(&r)?)? {
        modelos.push(Valor::Mapa(hf_normalizar(&x)?));
    }
    Ok(cache.guardar(&clave, Valor::Mapa(Mapa::new().con("modelos", Valor::Lista(modelos)).con("siguiente", siguiente))))
}

fn empieza(t: &Valor, prefijo: &str) -> R<bool> {
    Ok(texto_de(t, "startswith")?.starts_with(prefijo))
}

/// `HuggingFace.normalizar(m)`
pub fn hf_normalizar(m: &Valor) -> R<Mapa> {
    let tags = o_lista(getv(m, "tags")?);
    let gguf = o_vacio(getv(m, "gguf")?);
    let mut capacidades: Vec<&str> = Vec::new();
    let pipeline = getv(m, "pipeline_tag")?;
    let contiene = |x: &str| -> R<bool> { Ok(py::contiene(&tags, x).map_err(ErrorPy::Tipo)?) };
    if pipeline == Valor::Texto("image-text-to-text".into()) || contiene("vision")? || contiene("multimodal")? {
        capacidades.push("vision");
    }
    if contiene("conversational")? {
        capacidades.push("chat");
    }
    let tags_l = iter(&tags)?;
    let mut base: Option<String> = None;
    for t in &tags_l {
        if empieza(t, "base_model:quantized:")? {
            base = Some(t.texto_py()["base_model:quantized:".len()..].to_string());
            break;
        }
    }
    // `next(...) or next(...)`: si el primero no da nada (o da ""), el segundo, aunque sea ""
    if base.as_deref().map(|b| b.is_empty()).unwrap_or(true) {
        base = None;
        for t in &tags_l {
            if empieza(t, "base_model:")? && t.texto_py().matches(':').count() == 1 {
                base = Some(t.texto_py().split_once(':').map(|x| x.1.to_string()).unwrap_or_default());
                break;
            }
        }
    }
    let mut arquitectura = getv(&gguf, "architecture")?;
    if arquitectura == Valor::Texto("clip".into()) {
        // los metadatos son los del proyector de visión, no los del modelo
        arquitectura = Valor::Nulo;
        if !capacidades.contains(&"vision") {
            capacidades.push("vision");
        }
    }
    let mut licencia = Valor::Nulo;
    for t in &tags_l {
        if empieza(t, "license:")? {
            licencia = Valor::Texto(t.texto_py().split_once(':').map(|x| x.1.to_string()).unwrap_or_default());
            break;
        }
    }
    let id = texto_de(&item(m, "id")?, "split")?;
    let basado = match base.as_deref().filter(|b| !b.is_empty()) {
        Some(b) => Valor::Texto(format!("basado en {b}")),
        None => Valor::Texto(String::new()),
    };
    let descripcion = unir_partes(vec![basado, if arquitectura.verdad() { arquitectura.clone() } else { Valor::Texto(String::new()) }])?;
    let parametros = if arquitectura.verdad() { getv(&gguf, "total")? } else { Valor::Nulo };
    Ok(Mapa::new()
        .con("fuente", "huggingface")
        .con("id", id.clone())
        .con("nombre", id.rsplit('/').next().unwrap_or("").to_string())
        .con("autor", id.split('/').next().unwrap_or("").to_string())
        .con("oficial", false)
        .con("descripcion", descripcion)
        .con("capacidades", Valor::Lista(capacidades.into_iter().map(Valor::from).collect()))
        .con("tamanos", Valor::Lista(vec![]))
        .con("descargas", getv(m, "downloads")?)
        .con("me_gusta", getv(m, "likes")?)
        .con("tendencia", getv(m, "trendingScore")?)
        .con("actualizado", getv(m, "lastModified")?)
        .con("creado", getv(m, "createdAt")?)
        .con("contexto", getv(&gguf, "context_length")?)
        .con("arquitectura", arquitectura)
        .con("parametros", parametros)
        .con("licencia", licencia)
        .con("modelo_base", base.map(Valor::Texto).unwrap_or(Valor::Nulo))
        .con("requiere_licencia", getv(m, "gated")?.verdad())
        .con("url", format!("https://huggingface.co/{id}")))
}

fn archivos_de(lista: &[Valor], ruta: &str, tam: &str, excluir_tipo: Option<&str>) -> R<Vec<(Valor, Valor)>> {
    let mut salida = Vec::new();
    for s in lista {
        if let Some(t) = excluir_tipo {
            if getv(s, "Type")? == Valor::Texto(t.into()) {
                continue;
            }
        }
        let r = item(s, ruta)?;
        let t = getv(s, tam)?;
        salida.push((r, if t.verdad() { t } else { Valor::Entero(0) }));
    }
    Ok(salida)
}

/// Las rutas como textos (`ruta.lower()` falla con lo que no lo es, como en Python)
fn rutas_texto(archivos: Vec<(Valor, Valor)>) -> R<Vec<(String, Valor)>> {
    archivos.into_iter().map(|(r, t)| Ok((texto_de(&r, "lower")?, t))).collect()
}

/// `HuggingFace.variantes(repo)`: los GGUF del repositorio, agrupados
pub fn hf_variantes(base: &str, repo: &str, cache: &Cache) -> R<Valor> {
    if re_repo().buscar(repo).is_none() {
        return Err(buscador("Repositorio no válido"));
    }
    let clave = format!("hf-variantes:{repo}");
    if let Some(g) = cache.obtener(&clave, 1800.0) {
        if g.verdad() {
            return Ok(g);
        }
    }
    let r = get(&format!("{base}/api/models/{repo}"), &[("blobs", "true".into())], &[("User-Agent", UA)], 25.0)?;
    if r.estado != 200 {
        return Err(buscador(format!("No se encontró {repo} en Hugging Face ({})", r.estado)));
    }
    let d = json_de(&r)?;
    let siblings = iter(&py::get(&d, "siblings", Valor::Lista(vec![])).map_err(ErrorPy::Atributo)?)?;
    let archivos = rutas_texto(archivos_de(&siblings, "rfilename", "size", None)?)?;
    let mut variantes = agrupar_gguf(&archivos, &format!("hf.co/{repo}"));
    for v in variantes.iter_mut() {
        let primero = v.lista("archivos").and_then(|l| l.first()).map(|x| x.texto_py()).unwrap_or_default();
        v.poner("url_archivo", format!("{base}/{repo}/resolve/main/{primero}"));
    }
    let gguf = o_vacio(getv(&d, "gguf")?);
    let vision = archivos.iter().any(|a| a.0.to_lowercase().contains("mmproj"));
    let res = Mapa::new()
        .con("id", repo)
        .con("variantes", Valor::Lista(variantes.into_iter().map(Valor::Mapa).collect()))
        .con("contexto", getv(&gguf, "context_length")?)
        .con("arquitectura", getv(&gguf, "architecture")?)
        .con("requiere_licencia", getv(&d, "gated")?.verdad())
        .con("vision", vision);
    Ok(cache.guardar(&clave, Valor::Mapa(res)))
}

// =========================================================================== ModelScope

fn orden_ms(orden: &str) -> &'static str {
    match orden {
        "descargas" => "DownloadsCount",
        "actualizados" => "GmtModified",
        _ => "Default",
    }
}

/// `ModelScope.buscar`
pub fn ms_buscar(base: &str, consulta: &str, orden: &str, pagina: i64, limite: i64, cache: &Cache) -> R<Valor> {
    let criterio = Mapa::new()
        .con("category", "libraries")
        .con("predicate", "contains")
        .con("values", Valor::Lista(vec!["gguf".into()]));
    let cuerpo = Mapa::new()
        .con("PageSize", limite)
        .con("PageNumber", pagina.max(1))
        .con("SortBy", orden_ms(orden))
        .con("Target", "")
        .con("Name", consulta)
        .con("Criterion", Valor::Lista(vec![Valor::Mapa(criterio)]));
    let clave = format!("ms:{}", prig_recursos::json::escribir_compacto(&Valor::Mapa(cuerpo.clone())));
    if let Some(g) = cache.obtener(&clave, 600.0) {
        if g.verdad() {
            return Ok(g);
        }
    }
    let r = red::pedir("PUT", &format!("{base}/api/v1/dolphin/models"), Some(&Valor::Mapa(cuerpo)), &[("User-Agent", UA)], 25.0)?;
    if r.estado != 200 {
        return Err(buscador(format!("ModelScope respondió {}", r.estado)));
    }
    let d = json_de(&r)?;
    let datos = o_vacio(getv(&o_vacio(getv(&d, "Data")?), "Model")?);
    let mut modelos = Vec::new();
    for m in iter(&o_lista(getv(&datos, "Models")?))? {
        let mut gguf = false;
        for x in iter(&o_lista(getv(&m, "Libraries")?))? {
            if texto_de(&x, "lower")?.to_lowercase() == "gguf" {
                gguf = true;
            }
        }
        if gguf {
            modelos.push(Valor::Mapa(ms_normalizar(&m)?));
        }
    }
    let total = getv(&datos, "TotalCount")?;
    let total = if total.verdad() { total.num().unwrap_or(0.0) } else { 0.0 };
    let siguiente = if ((pagina * limite) as f64) < total { Valor::Entero((pagina + 1) as i128) } else { Valor::Nulo };
    Ok(cache.guardar(&clave, Valor::Mapa(Mapa::new().con("modelos", Valor::Lista(modelos)).con("siguiente", siguiente))))
}

/// `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))`
fn fecha_utc(ts: f64) -> String {
    let s = ts.floor() as i64;
    let dias = s.div_euclid(86400);
    let resto = s.rem_euclid(86400);
    let (y, m, d) = civil(dias);
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z", resto / 3600, (resto % 3600) / 60, resto % 60)
}

fn civil(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// `ModelScope.normalizar(m)`
pub fn ms_normalizar(m: &Valor) -> R<Mapa> {
    let repo = format!("{}/{}", getv(m, "Path")?.texto_py(), getv(m, "Name")?.texto_py());
    let chino = getv(m, "ChineseName")?;
    let base_model = getv(m, "BaseModel")?;
    let basado = if base_model.verdad() {
        Valor::Texto(format!("basado en {}", py::unir(", ", &base_model).map_err(ErrorPy::Tipo)?))
    } else {
        Valor::Texto(String::new())
    };
    let descripcion = unir_partes(vec![if chino.verdad() { chino.clone() } else { Valor::Texto(String::new()) }, basado])?;
    // (en el orden del dict de Python: la fecha después de la descripción)
    let ts = getv(m, "LastUpdatedTime")?;
    let actualizado = if ts.verdad() {
        match ts.num() {
            Some(x) => Valor::Texto(fecha_utc(x)),
            None => return Err(ErrorB::Py(ErrorPy::Tipo(format!("'{}' object cannot be interpreted as an integer", py::tipo(&ts))))),
        }
    } else {
        Valor::Nulo
    };

    Ok(Mapa::new()
        .con("fuente", "modelscope")
        .con("id", repo.clone())
        .con("nombre", getv(m, "Name")?)
        .con("autor", getv(m, "Path")?)
        .con("oficial", false)
        .con("descripcion", descripcion)
        .con("capacidades", Valor::Lista(vec![]))
        .con("tamanos", Valor::Lista(vec![]))
        .con("descargas", getv(m, "Downloads")?)
        .con("me_gusta", getv(m, "Stars")?)
        .con("actualizado", actualizado)
        .con("licencia", getv(m, "License")?)
        .con("url", format!("https://modelscope.cn/models/{repo}")))
}

/// `ModelScope.variantes(repo)`
pub fn ms_variantes(base: &str, repo: &str, cache: &Cache) -> R<Valor> {
    if re_repo().buscar(repo).is_none() {
        return Err(buscador("Repositorio no válido"));
    }
    let clave = format!("ms-variantes:{repo}");
    if let Some(g) = cache.obtener(&clave, 1800.0) {
        if g.verdad() {
            return Ok(g);
        }
    }
    let r = get(&format!("{base}/api/v1/models/{repo}/repo/files"), &[("Recursive", "true".into())], &[("User-Agent", UA)], 25.0)?;
    if r.estado != 200 {
        return Err(buscador(format!("No se encontró {repo} en ModelScope ({})", r.estado)));
    }
    let d = json_de(&r)?;
    let files = o_lista(getv(&o_vacio(getv(&d, "Data")?), "Files")?);
    let archivos = rutas_texto(archivos_de(&iter(&files)?, "Path", "Size", Some("tree"))?)?;
    let mut variantes = agrupar_gguf(&archivos, &format!("modelscope.cn/{repo}"));
    for v in variantes.iter_mut() {
        let primero = v.lista("archivos").and_then(|l| l.first()).map(|x| x.texto_py()).unwrap_or_default();
        v.poner("url_archivo", format!("{base}/models/{repo}/resolve/master/{primero}"));
    }
    let vision = archivos.iter().any(|a| a.0.to_lowercase().contains("mmproj"));
    let res = Mapa::new().con("id", repo).con("variantes", Valor::Lista(variantes.into_iter().map(Valor::Mapa).collect())).con("vision", vision);
    Ok(cache.guardar(&clave, Valor::Mapa(res)))
}

// =========================================================================== agrupar GGUF

/// `agrupar_gguf`: archivos .gguf de un repositorio → variantes descargables por Ollama (una partida en varios
/// archivos es una sola; el proyector de visión no es una variante)
pub fn agrupar_gguf(archivos: &[(String, Valor)], prefijo: &str) -> Vec<Mapa> {
    let mut grupos: Vec<(String, String, Vec<String>, Valor, i64)> = Vec::new();
    for (ruta, tam) in archivos {
        let bajo = ruta.to_lowercase();
        if !bajo.ends_with(".gguf") || bajo.contains("mmproj") {
            continue;
        }
        let Some(cuant) = cuantizacion_de(ruta).or_else(|| cuantizacion_de(&format!("{}.gguf", py::dirname(ruta)))) else {
            continue;
        };
        let k = cuant.to_lowercase();
        let i = match grupos.iter().position(|g| g.0 == k) {
            Some(i) => i,
            None => {
                grupos.push((k, cuant, vec![], Valor::Entero(0), 0));
                grupos.len() - 1
            }
        };
        let g = &mut grupos[i];
        g.2.push(ruta.clone());
        g.3 = suma([g.3.clone(), tam.clone()].into_iter());
        g.4 += 1;
    }
    let mut salida: Vec<Mapa> = grupos
        .into_iter()
        .map(|(_, etiqueta, archivos, bytes, partes)| {
            let partido = partes > 1 || archivos.iter().any(|a| re_parte().buscar(&re_gguf_final().sustituir(a, "")).is_some());
            let mut ordenados = archivos.clone();
            ordenados.sort();
            Mapa::new()
                .con("ref", format!("{prefijo}:{etiqueta}"))
                .con("etiqueta", etiqueta)
                .con("bytes", bytes)
                .con("archivos", Valor::Lista(ordenados.into_iter().map(Valor::Texto).collect()))
                .con("partes", partes)
                .con(
                    "nota",
                    if partido {
                        Valor::from("Partido en varios archivos: Ollama no siempre puede descargarlo; se comprueba antes.")
                    } else {
                        Valor::Nulo
                    },
                )
                .con("descargable", Valor::Nulo)
        })
        .collect();
    salida.sort_by(|a, b| a.num_o("bytes", 0.0).partial_cmp(&b.num_o("bytes", 0.0)).unwrap_or(std::cmp::Ordering::Equal));
    salida
}

// =========================================================================== encontrar un modelo concreto

/// `urllib.parse.unquote` (UTF-8, con U+FFFD en lo que no lo es)
fn unquote(t: &str) -> String {
    let b = t.as_bytes();
    let mut salida = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let (Some(a), Some(c)) = ((b[i + 1] as char).to_digit(16), (b[i + 2] as char).to_digit(16)) {
                salida.push((a * 16 + c) as u8);
                i += 3;
                continue;
            }
        }
        salida.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&salida).into_owned()
}

/// `parse_qs(urlsplit(url).query)`: el primer valor (no vacío) de cada clave
fn consulta_de(resto: &str) -> HashMap<String, String> {
    let sin_fragmento = resto.split('#').next().unwrap_or("");
    let query = sin_fragmento.split_once('?').map(|x| x.1).unwrap_or("");
    let mut m = HashMap::new();
    for par in query.split('&') {
        let Some((k, v)) = par.split_once('=') else { continue };
        let (k, v) = (unquote(&k.replace('+', " ")), unquote(&v.replace('+', " ")));
        if !v.is_empty() {
            m.entry(k).or_insert(v);
        }
    }
    m
}

fn separar_etiqueta(nombre: &str) -> (String, Option<String>) {
    match nombre.split_once(':') {
        Some((b, t)) => (b.to_string(), if t.is_empty() { None } else { Some(t.to_string()) }),
        None => (nombre.to_string(), None),
    }
}

fn enlace(fuente: &str, id: &str, tag: Option<String>) -> R<Mapa> {
    let segmentos_ok = id.split('/').all(|x| re_segmento().buscar(x).is_some());
    if !segmentos_ok || id.matches('/').count() > 1 || id.contains("..") {
        return Err(buscador("El enlace no tiene un nombre de modelo válido"));
    }
    let tag = tag.filter(|t| re_segmento().buscar(t).is_some());
    Ok(Mapa::new()
        .con("tipo", "enlace")
        .con("fuente", fuente)
        .con("id", id)
        .con("etiqueta", tag.map(Valor::Texto).unwrap_or(Valor::Nulo))
        .con("consulta", id.rsplit('/').next().unwrap_or("").to_string()))
}

/// `interpretar(texto)`: un enlace (a una ficha, a las etiquetas, a un .gguf...), lo que se le pasa a Ollama
/// («ollama run hf.co/…:Q4_K_M»), «propietario/repositorio» o un nombre a buscar
pub fn interpretar(texto: &str) -> R<Mapa> {
    let t = py::strip(texto);
    let t = t.trim_matches(|c| "\"'`<>".contains(c));
    let t = re_ollama_run().sustituir(t, "");
    let t = py::strip(&t).to_string();
    if t.is_empty() {
        return Err(buscador("Escribe un nombre o pega un enlace"));
    }
    if t.chars().count() > 400 {
        return Err(buscador("Texto demasiado largo"));
    }
    let web = if !t.contains(' ') {
        let primero = t.split(|c: char| c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)).find(|x| !x.is_empty()).unwrap_or("");
        re_web().buscar(primero)
    } else {
        None
    };
    if let Some(g) = web {
        let sitio = g[1].clone().unwrap_or_default().to_lowercase();
        let resto = g[2].clone().unwrap_or_default();
        let antes = resto.split(['?', '#']).next().unwrap_or("");
        let ruta = unquote(antes).trim_matches('/').to_string();
        let consulta = consulta_de(&format!("x/{resto}"));
        let mut partes: Vec<String> = ruta.split('/').filter(|x| !x.is_empty()).map(String::from).collect();
        let fuente = match sitio.as_str() {
            "ollama.com" => "ollama",
            "modelscope.cn" => "modelscope",
            _ => "huggingface",
        };
        if let Some(b) = consulta.get("q").or_else(|| consulta.get("search")).or_else(|| consulta.get("name")) {
            return interpretar_nombre(b);
        }
        if fuente == "ollama" {
            if partes.first().map(String::as_str) == Some("library") {
                partes.remove(0);
            }
            if let Some(i) = partes.iter().position(|x| x == "tags" || x == "blobs") {
                partes.truncate(i);
            }
            if partes.is_empty()
                || partes.len() > 2
                || ["search", "models", "download", "blog", "settings", "signin"].contains(&partes[0].as_str())
            {
                return Err(buscador("El enlace de ollama.com no apunta a un modelo"));
            }
            let (base, tag) = separar_etiqueta(&partes.join("/"));
            return enlace("ollama", &base, tag);
        }
        if fuente == "modelscope" && partes.first().map(String::as_str) == Some("models") {
            partes.remove(0);
        }
        if fuente == "huggingface" && matches!(partes.first().map(String::as_str), Some("models" | "api")) {
            if partes.len() >= 2 && partes[0] == "api" && partes[1] == "models" {
                partes.drain(..2);
            } else {
                partes.remove(0);
            }
        }
        if partes.len() < 2 {
            return Err(buscador("El enlace no apunta a un repositorio (propietario/nombre)"));
        }
        let (repo, mut tag) = separar_etiqueta(&partes[1]);
        if tag.is_none() {
            // enlace a un archivo .gguf o a la carpeta de una cuantización
            tag = partes[2..].iter().rev().find_map(|x| cuantizacion_de(x));
        }
        return enlace(fuente, &format!("{}/{repo}", partes[0]), tag);
    }
    if re_repo_entero().buscar(&t).is_some() {
        let (base, tag) = separar_etiqueta(&t);
        let consulta = base.split('/').nth(1).unwrap_or("").to_string();
        return Ok(Mapa::new()
            .con("tipo", "repo")
            .con("fuente", Valor::Nulo)
            .con("id", base)
            .con("etiqueta", tag.map(Valor::Texto).unwrap_or(Valor::Nulo))
            .con("consulta", consulta));
    }
    interpretar_nombre(&t)
}

/// `interpretar_nombre(texto)`
pub fn interpretar_nombre(texto: &str) -> R<Mapa> {
    let mut t = py::strip(texto).to_string();
    let mut tag = None;
    if re_nombre_tag().buscar(&t).is_some() {
        let (b, g) = separar_etiqueta(&t);
        t = b;
        tag = g;
    }
    let t = re_blancos().sustituir(&t, " ");
    if re_palabra().buscar(&t).is_none() {
        return Err(buscador("Escribe un nombre o pega un enlace"));
    }
    Ok(Mapa::new()
        .con("tipo", "nombre")
        .con("fuente", Valor::Nulo)
        .con("id", Valor::Nulo)
        .con("etiqueta", tag.map(Valor::Texto).unwrap_or(Valor::Nulo))
        .con("consulta", t.chars().take(100).collect::<String>()))
}

/// `_clave(nombre)`: «unsloth/Qwen3-8B-GGUF», «qwen3-8b» y «Qwen3 8B» son el mismo nombre
pub fn clave(nombre: &str) -> String {
    let ultimo = nombre.rsplit('/').next().unwrap_or("");
    let base = ultimo.split(':').next().unwrap_or("").to_lowercase();
    let base = re_gguf_sufijo().sustituir(&base, "");
    re_no_alnum().sustituir(&base, "")
}

/// `_parecido(consulta, id_modelo)`: todas las palabras de la consulta están en el nombre
pub fn parecido(consulta: &str, id: &str) -> bool {
    let fichas: Vec<String> = re_no_alnum_mas().partir(&consulta.to_lowercase()).into_iter().filter(|x| !x.is_empty()).collect();
    let t = id.to_lowercase();
    !fichas.is_empty() && fichas.iter().all(|f| t.contains(f.as_str()))
}

/// `_clave_ollama(consulta)`: «Qwen3» → «qwen3» (los oficiales van en minúsculas y sin espacios)
pub fn clave_ollama(consulta: &str) -> Option<String> {
    let c = py::strip(consulta).to_lowercase();
    re_clave_ollama().buscar(&c).map(|_| c)
}

/// Las direcciones de las tres plataformas
pub struct Bases<'a> {
    pub ollama: &'a str,
    pub huggingface: &'a str,
    pub modelscope: &'a str,
}

/// `ficha_repo(fuente, id)`: los datos de un modelo concreto, o None si no existe (o es privado)
pub fn ficha_repo(fuente: &str, id: &str, bases: &Bases, cache: &Cache) -> R<Option<Mapa>> {
    if re_ficha_entera().buscar(id).is_none() || id.contains("..") {
        return Ok(None);
    }
    let clave_c = format!("ficha:{fuente}:{id}");
    if let Some(g) = cache.obtener(&clave_c, 600.0) {
        return Ok(match g {
            Valor::Mapa(m) if !m.is_empty() => Some(m),
            _ => None,
        });
    }
    let mut resultado: Option<Mapa> = None;
    if fuente == "huggingface" && id.contains('/') {
        let mut params: Vec<(&str, String)> = Vec::new();
        for e in EXPANDIR {
            params.push(("expand[]", e.into()));
        }
        let r = get(&format!("{}/api/models/{id}", bases.huggingface), &params, &[("User-Agent", UA)], 25.0)?;
        if r.estado == 200 {
            let d = json_de(&r)?;
            let mut f = hf_normalizar(&d)?;
            let tags = o_lista(getv(&d, "tags")?);
            let sin = !py::contiene(&tags, "gguf").map_err(ErrorPy::Tipo)? && !getv(&d, "gguf")?.verdad();
            f.poner("sin_gguf", sin);
            resultado = Some(f);
        } else if r.estado != 401 && r.estado != 404 {
            return Err(buscador(format!("Hugging Face respondió {}", r.estado)));
        }
    } else if fuente == "modelscope" && id.contains('/') {
        let r = get(&format!("{}/api/v1/models/{id}", bases.modelscope), &[], &[("User-Agent", UA)], 25.0)?;
        let con_nombre = r.estado == 200 && {
            let d = json_de(&r)?;
            getv(&o_vacio(getv(&d, "Data")?), "Name")?.verdad()
        };
        if con_nombre {
            let d = item(&json_de(&r)?, "Data")?;
            let mut f = ms_normalizar(&d)?;
            let mut gguf = false;
            for x in iter(&o_lista(getv(&d, "Libraries")?))? {
                if texto_de(&x, "lower")?.to_lowercase() == "gguf" {
                    gguf = true;
                }
            }
            f.poner("sin_gguf", !gguf);
            resultado = Some(f);
        } else if r.estado != 200 && r.estado != 404 {
            return Err(buscador(format!("ModelScope respondió {}", r.estado)));
        }
    } else if fuente == "ollama" {
        let ruta = if id.contains('/') { id.to_string() } else { format!("library/{id}") };
        let r = get(&format!("{}/{ruta}", bases.ollama), &[], &[("User-Agent", UA)], 25.0)?;
        if r.estado == 200 {
            let t = r.texto();
            let desc = grupo(re_meta_desc(), &t, 1).map(|d| unescape(&d)).unwrap_or_default();
            let chips: Vec<String> = re_chip_ficha().todos(&t).into_iter().map(|g| py::strip(&unescape(g[1].as_deref().unwrap_or(""))).to_string()).collect();
            let capacidades: Vec<Valor> = chips.iter().filter(|c| CAPACIDADES_OLLAMA.contains(&c.as_str())).map(|c| Valor::Texto(c.clone())).collect();
            let tamanos: Vec<Valor> = chips.iter().filter(|c| re_tamano_entero().buscar(c).is_some()).map(|c| Valor::Texto(c.clone())).collect();
            let autor = if id.contains('/') { id.split('/').next().unwrap_or("").to_string() } else { "ollama".into() };
            resultado = Some(
                Mapa::new()
                    .con("fuente", "ollama")
                    .con("id", id)
                    .con("nombre", id)
                    .con("autor", autor)
                    .con("oficial", !id.contains('/'))
                    .con("descripcion", desc)
                    .con("capacidades", Valor::Lista(capacidades))
                    .con("tamanos", Valor::Lista(tamanos))
                    .con("url", format!("{}/{ruta}", bases.ollama))
                    .con("sin_gguf", false),
            );
        } else if r.estado != 404 {
            return Err(buscador(format!("ollama.com respondió {}", r.estado)));
        }
    }
    cache.guardar(&clave_c, Valor::Mapa(resultado.clone().unwrap_or_default()));
    Ok(resultado)
}
