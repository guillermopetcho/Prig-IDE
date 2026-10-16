//! Gestión de modelos de Ollama (`ollama_gestion.py`): ficha, variantes, copias, importar GGUF, actualizaciones,
//! modelos cargados y descargas a medias. Verificado contra Ollama 0.34.1 (ver `ollama_opciones.EXCLUIDAS`).
//!
//! Los flujos largos (crear una variante, importar un GGUF) son iteradores de pasos, como los generadores de Python:
//! nada se comprueba ni se pide hasta el primer paso.

use crate::red::{self, ErrorRed, Lineas, Respuesta};
use prig_plataforma::py::{self, ErrorPy};
use prig_plataforma::regex_py::ExpresionPy;
use prig_recursos::valor::{Mapa, Valor};
use sha2::{Digest, Sha256};
use std::io::Read;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, OnceLock};

pub const REGISTRO: &str = "https://registry.ollama.ai";

#[derive(Debug)]
pub enum ErrorG {
    /// ErrorGestion
    Gestion(String),
    /// Un error de ollama_opciones (ErrorConfig) u otra excepción de Python
    Py(ErrorPy),
    Red(ErrorRed),
}

impl From<ErrorRed> for ErrorG {
    fn from(e: ErrorRed) -> ErrorG {
        ErrorG::Red(e)
    }
}

type R<T> = Result<T, ErrorG>;

fn nombre_valido() -> &'static ExpresionPy {
    static N: OnceLock<ExpresionPy> = OnceLock::new();
    N.get_or_init(|| {
        ExpresionPy::compilar(r"^[a-zA-Z0-9][a-zA-Z0-9._\-/]{0,120}(:[a-zA-Z0-9._\-]{1,80})?$", true).expect("NOMBRE_VALIDO")
    })
}

/// `_nombre`: el nombre sin espacios alrededor, o ErrorGestion
pub fn nombre(n: &str) -> R<String> {
    let n = py::strip(n).to_string();
    // `re.match` con `$`: también casa antes de un salto final
    let ok = matches!(nombre_valido().aciertos(&n).first(), Some(&(0, _)));
    if !ok {
        return Err(ErrorG::Gestion(
            "Nombre de modelo no válido: letras, números, guiones, puntos y opcionalmente :etiqueta".into(),
        ));
    }
    Ok(n)
}

/// `_parametros`: "temperature 0.6\nstop \"<|im_end|>\"" → {"temperature": "0.6", "stop": [...]}
pub fn parametros(texto: &str) -> Mapa {
    let mut salida = Mapa::new();
    for linea in prig_recursos::servidor::lineas_como_python(texto) {
        let l = py::strip(linea);
        let Some(i) = l.find(|c: char| c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)) else { continue };
        let (clave, resto) = (&l[..i], &l[i..]);
        let mut valor = py::strip(resto).to_string();
        if valor.is_empty() {
            continue;
        }
        if valor.starts_with('"') && valor.ends_with('"') {
            let c: Vec<char> = valor.chars().collect();
            valor = if c.len() >= 2 { c[1..c.len() - 1].iter().collect() } else { String::new() };
        }
        let nuevo = match salida.get(clave) {
            Some(Valor::Lista(l)) => {
                let mut l = l.clone();
                l.push(Valor::Texto(valor));
                Valor::Lista(l)
            }
            Some(otro) => Valor::Lista(vec![otro.clone(), Valor::Texto(valor)]),
            None => Valor::Texto(valor),
        };
        salida.poner(clave, nuevo);
    }
    salida
}

fn contar(valores: impl Iterator<Item = Valor>) -> Mapa {
    let mut cuenta = Mapa::new();
    for v in valores {
        let k = if v.verdad() { v.texto_py() } else { "?".into() };
        let n = cuenta.num(&k).unwrap_or(0.0) as i64;
        cuenta.poner(k, n + 1);
    }
    cuenta
}

fn get(m: &Valor, k: &str) -> Valor {
    match m {
        Valor::Mapa(m) => m.valor(k).clone(),
        _ => Valor::Nulo,
    }
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

/// Lo mismo que `ThreadPoolExecutor(6).map`: en paralelo y en el orden de entrada
fn en_paralelo<T: Sync, U: Send>(cosas: &[T], f: impl Fn(&T) -> U + Sync) -> Vec<U> {
    let siguiente = AtomicU64::new(0);
    let resultados: Vec<std::sync::Mutex<Option<U>>> = cosas.iter().map(|_| std::sync::Mutex::new(None)).collect();
    std::thread::scope(|s| {
        for _ in 0..6.min(cosas.len().max(1)) {
            s.spawn(|| loop {
                let i = siguiente.fetch_add(1, Ordering::SeqCst) as usize;
                if i >= cosas.len() {
                    break;
                }
                let r = f(&cosas[i]);
                *resultados[i].lock().unwrap() = Some(r);
            });
        }
    });
    resultados.into_iter().map(|m| m.into_inner().unwrap().unwrap()).collect()
}

pub struct Gestor {
    pub base: String,
}

impl Gestor {
    fn get_(&self, ruta: &str, segundos: f64) -> R<Valor> {
        let r = red::pedir("GET", &format!("{}{ruta}", self.base), None, &[], segundos)?;
        if r.estado != 200 {
            return Err(ErrorG::Gestion(r.error()));
        }
        Ok(r.json()?)
    }

    fn post_(&self, ruta: &str, cuerpo: &Valor, segundos: f64) -> R<Valor> {
        let r = red::pedir("POST", &format!("{}{ruta}", self.base), Some(cuerpo), &[], segundos)?;
        if r.estado != 200 {
            return Err(ErrorG::Gestion(r.error()));
        }
        if r.cuerpo.is_empty() {
            return Ok(Valor::Mapa(Mapa::new()));
        }
        Ok(r.json()?)
    }

    fn modelos_de(v: &Valor) -> R<Vec<Valor>> {
        let m = py::get(v, "models", Valor::Lista(vec![])).map_err(|e| ErrorG::Py(ErrorPy::Atributo(e)))?;
        py::iterar(&m).map_err(|e| ErrorG::Py(ErrorPy::Tipo(e)))
    }

    fn nombre_de(m: &Valor) -> R<Valor> {
        match m {
            Valor::Mapa(x) => x.get("name").cloned().ok_or_else(|| ErrorG::Py(ErrorPy::Clave("'name'".into()))),
            otro => Err(ErrorG::Py(ErrorPy::Tipo(format!("{} indices must be integers", py::tipo(otro))))),
        }
    }

    /// `instalados`: los modelos con su ficha corta (y si están cargados)
    pub fn instalados(&self) -> R<Vec<Valor>> {
        let modelos = Self::modelos_de(&self.get_("/api/tags", 15.0)?)?;
        let mut cargados = Mapa::new();
        for m in Self::modelos_de(&self.get_("/api/ps", 15.0)?)? {
            let n = Self::nombre_de(&m)?.texto_py();
            cargados.poner(n, m);
        }
        let fichas = en_paralelo(&modelos, |m| -> R<Valor> {
            let nombre = Self::nombre_de(m)?;
            let d = self.post_("/api/show", &Valor::Mapa(Mapa::new().con("model", nombre.clone())), 20.0).unwrap_or(Valor::Mapa(Mapa::new()));
            let det = o_vacio(get(m, "details"));
            let info = o_vacio(get(&d, "model_info"));
            let arq = match &info {
                Valor::Mapa(i) if i.contiene("general.architecture") => i.valor("general.architecture").clone(),
                _ => match &det {
                    Valor::Mapa(x) if x.contiene("family") => x.valor("family").clone(),
                    _ => Valor::Texto(String::new()),
                },
            };
            let c = cargados.get(&nombre.texto_py()).cloned();
            let cargado = match c {
                Some(c) if c.verdad() => Valor::Mapa(
                    Mapa::new()
                        .con("bytes", get(&c, "size"))
                        .con("vram", get(&c, "size_vram"))
                        .con("contexto", get(&c, "context_length"))
                        .con("expira", get(&c, "expires_at")),
                ),
                _ => Valor::Nulo,
            };
            let tam = match m {
                Valor::Mapa(x) if x.contiene("size") => x.valor("size").clone(),
                _ => Valor::Entero(0),
            };
            Ok(Valor::Mapa(
                Mapa::new()
                    .con("nombre", nombre)
                    .con("bytes", tam)
                    .con("digest", get(m, "digest"))
                    .con("modificado", get(m, "modified_at"))
                    .con("familia", get(&det, "family"))
                    .con("parametros", get(&det, "parameter_size"))
                    .con("cuantizacion", get(&det, "quantization_level"))
                    .con("formato", get(&det, "format"))
                    .con("capacidades", o_lista(get(&d, "capabilities")))
                    .con("contexto_max", get(&info, &format!("{}.context_length", arq.texto_py())))
                    .con("cargado", cargado),
            ))
        });
        fichas.into_iter().collect()
    }

    /// `ficha(modelo)`: todo lo que dice Ollama de un modelo (sin los vocabularios largos)
    pub fn ficha(&self, modelo: &str) -> R<Mapa> {
        let d = self.post_("/api/show", &Valor::Mapa(Mapa::new().con("model", modelo).con("verbose", true)), 60.0)?;
        let tensores = o_lista(get(&d, "tensors"));
        let tensores = match tensores {
            Valor::Lista(l) => l,
            otro => py::iterar(&otro).map_err(|e| ErrorG::Py(ErrorPy::Tipo(e)))?,
        };
        let mut info = Mapa::new();
        if let Valor::Mapa(i) = o_vacio(get(&d, "model_info")) {
            for (k, v) in i.iter() {
                if !matches!(v, Valor::Lista(l) if l.len() > 64) {
                    info.poner(k.clone(), v.clone());
                }
            }
        }
        let texto = |k: &str| match &d {
            Valor::Mapa(m) if m.contiene(k) => m.valor(k).clone(),
            _ => Valor::Texto(String::new()),
        };
        let params = match texto("parameters") {
            Valor::Texto(t) => parametros(&t),
            v if !v.verdad() => Mapa::new(),
            otro => parametros(&otro.texto_py()),
        };
        let tipos = contar(tensores.iter().map(|t| get(t, "type")));
        Ok(Mapa::new()
            .con("modelo", modelo)
            .con("capacidades", o_lista(get(&d, "capabilities")))
            .con("detalles", o_vacio(get(&d, "details")))
            .con("info", info)
            .con("parametros", params)
            .con("plantilla", texto("template"))
            .con("system", texto("system"))
            .con("licencia", texto("license"))
            .con("modelfile", texto("modelfile"))
            .con("mensajes", o_lista(get(&d, "messages")))
            .con("modificado", get(&d, "modified_at"))
            .con(
                "tensores",
                Mapa::new()
                    .con("total", tensores.len())
                    .con("lista", Valor::Lista(tensores.iter().take(400).cloned().collect()))
                    .con("tipos", tipos),
            ))
    }

    /// `copiar(origen, destino)`
    pub fn copiar(&self, origen: &str, destino: &str) -> R<Mapa> {
        let destino = nombre(destino)?;
        let cuerpo = Mapa::new().con("source", origen).con("destination", destino.clone());
        let r = red::pedir("POST", &format!("{}/api/copy", self.base), Some(&Valor::Mapa(cuerpo)), &[], 120.0)?;
        if r.estado != 200 {
            return Err(ErrorG::Gestion(r.error()));
        }
        Ok(Mapa::new().con("ok", true).con("modelo", destino))
    }

    /// `borrar(modelo)`
    pub fn borrar(&self, modelo: &str) -> R<Mapa> {
        let cuerpo = Valor::Mapa(Mapa::new().con("model", modelo));
        let r = red::pedir("DELETE", &format!("{}/api/delete", self.base), Some(&cuerpo), &[], 120.0)?;
        if r.estado != 200 {
            return Err(ErrorG::Gestion(r.error()));
        }
        Ok(Mapa::new().con("ok", true))
    }

    /// `actualizaciones(registro)`: si cada modelo instalado está al día con el registro
    pub fn actualizaciones(&self, registro: &str) -> R<Vec<Valor>> {
        let modelos = Self::modelos_de(&self.get_("/api/tags", 15.0)?)?;
        let r = en_paralelo(&modelos, |m| -> R<Valor> {
            let n = Self::nombre_de(m)?.texto_py();
            let (base, tag) = match n.find(':') {
                Some(i) => (&n[..i], &n[i + 1..]),
                None => (n.as_str(), ""),
            };
            let repo = if base.contains('/') { base.to_string() } else { format!("library/{base}") };
            let tag = if tag.is_empty() { "latest" } else { tag };
            let url = format!("{registro}/v2/{repo}/manifests/{tag}");
            let resp = red::pedir("GET", &url, None, &[("Accept", "application/vnd.docker.distribution.manifest.v2+json")], 20.0);
            let base_m = |estado: &str, detalle: Valor| Valor::Mapa(Mapa::new().con("modelo", n.clone()).con("estado", estado).con("detalle", detalle));
            Ok(match resp {
                Err(e) => base_m("error", Valor::Texto(e.texto())),
                Ok(r) if r.estado == 404 => base_m("local", "No está en el registro (creado o importado aquí)".into()),
                Ok(r) if r.estado != 200 => base_m("error", Valor::Texto(format!("HTTP {}", r.estado))),
                Ok(r) => {
                    let remoto = hex(&Sha256::digest(&r.cuerpo));
                    let local = get(m, "digest");
                    let al_dia = matches!(&local, Valor::Texto(l) if *l == remoto);
                    let local_corto: String = if local.verdad() { local.texto_py().chars().take(12).collect() } else { String::new() };
                    Valor::Mapa(
                        Mapa::new()
                            .con("modelo", n.clone())
                            .con("estado", if al_dia { "al_dia" } else { "actualizable" })
                            .con("local", local_corto)
                            .con("remoto", remoto[..12].to_string()),
                    )
                }
            })
        });
        r.into_iter().collect()
    }

    /// `cargados()`
    pub fn cargados(&self) -> R<Vec<Valor>> {
        let mut salida = Vec::new();
        for m in Self::modelos_de(&self.get_("/api/ps", 15.0)?)? {
            let n = Self::nombre_de(&m)?;
            let o = |k: &str, d: Valor| match &m {
                Valor::Mapa(x) if x.contiene(k) => x.valor(k).clone(),
                _ => d,
            };
            salida.push(Valor::Mapa(
                Mapa::new()
                    .con("nombre", n)
                    .con("bytes", o("size", Valor::Entero(0)))
                    .con("vram", o("size_vram", Valor::Entero(0)))
                    .con("contexto", get(&m, "context_length"))
                    .con("expira", get(&m, "expires_at")),
            ));
        }
        Ok(salida)
    }

    /// `precargar(modelo, opciones, keep_alive)`
    pub fn precargar(&self, modelo: &str, opciones: &Valor, keep_alive: Option<&Valor>) -> R<Mapa> {
        let mut cuerpo = Mapa::new().con("model", modelo).con("prompt", "").con("stream", false).con("options", opciones.clone());
        if let Some(k) = keep_alive {
            cuerpo.poner("keep_alive", k.clone());
        }
        self.post_("/api/generate", &Valor::Mapa(cuerpo), 600.0)?;
        Ok(Mapa::new().con("ok", true).con("cargados", Valor::Lista(self.cargados()?)))
    }

    /// `descargar(modelo)`: lo saca de la memoria
    pub fn descargar(&self, modelo: &str) -> R<Mapa> {
        self.post_("/api/generate", &Valor::Mapa(Mapa::new().con("model", modelo).con("keep_alive", 0)), 60.0)?;
        Ok(Mapa::new().con("ok", true).con("cargados", Valor::Lista(self.cargados()?)))
    }

    /// `probar(cuerpo)`
    pub fn probar(&self, cuerpo: &Mapa, segundos: f64) -> R<Valor> {
        let mut c = cuerpo.clone();
        c.poner("stream", false);
        let r = red::pedir("POST", &format!("{}/api/generate", self.base), Some(&Valor::Mapa(c)), &[], segundos)?;
        if r.estado != 200 {
            return Err(ErrorG::Gestion(r.error()));
        }
        Ok(r.json()?)
    }

    /// `uso_disco()`
    pub fn uso_disco(&self) -> R<Mapa> {
        let modelos = Self::modelos_de(&self.get_("/api/tags", 15.0)?)?;
        let mut total = Valor::Entero(0);
        for m in &modelos {
            let t = match m {
                Valor::Mapa(x) if x.contiene("size") => x.valor("size").clone(),
                _ => Valor::Entero(0),
            };
            total = match (total, t) {
                (Valor::Entero(a), Valor::Entero(b)) => Valor::Entero(a + b),
                (a, b) => Valor::Real(a.num().unwrap_or(0.0) + b.num().unwrap_or(0.0)),
            };
        }
        Ok(Mapa::new().con("modelos", modelos.len()).con("bytes", total).con("carpeta", carpeta_modelos()))
    }

    /// `crear_variante(...)`: los pasos de `/api/create`
    pub fn crear_variante(&self, n: String, desde: String, system: String, parametros: Option<Valor>, mensajes: Option<Valor>, licencia: String) -> Pasos {
        Pasos::Variante { base: self.base.clone(), datos: Box::new(Some((n, desde, system, parametros, mensajes, licencia))), lineas: Box::new(None) }
    }

    /// `importar_gguf(ruta, nombre, cancelar)`: huella, subida y creación
    pub fn importar_gguf(&self, ruta: String, n: String, cancelar: Option<Box<dyn FnMut() -> bool + Send>>) -> Pasos {
        Pasos::Importar(Box::new(Importar {
            base: self.base.clone(),
            ruta,
            nombre: n,
            cancelar,
            fase: FaseImportar::Inicio,
        }))
    }
}

pub fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

/// `carpeta_modelos()`: `OLLAMA_MODELS` o `~/.ollama/models`
pub fn carpeta_modelos() -> String {
    match std::env::var("OLLAMA_MODELS") {
        Ok(c) if !c.is_empty() => c,
        _ => py::expanduser("~/.ollama/models"),
    }
}

/// `parciales(carpeta)`: las descargas a medias (archivos con «partial» en el nombre dentro de blobs/)
pub fn parciales(carpeta: Option<&str>) -> Mapa {
    let base = match carpeta {
        Some(c) if !c.is_empty() => c.to_string(),
        _ => carpeta_modelos(),
    };
    let blobs = py::join(&base, "blobs");
    let mut archivos = Vec::new();
    let mut total: i64 = 0;
    if let Ok(leidas) = std::fs::read_dir(&blobs) {
        for e in leidas.flatten() {
            let n = e.file_name().to_string_lossy().into_owned();
            if n.contains("partial") {
                let ruta = py::join(&blobs, &n);
                if let Ok(m) = std::fs::metadata(&ruta) {
                    total += m.len() as i64;
                    archivos.push(Valor::Mapa(Mapa::new().con("nombre", n).con("bytes", m.len() as i64).con("ruta", ruta)));
                }
            }
        }
    }
    Mapa::new().con("carpeta", blobs).con("archivos", Valor::Lista(archivos)).con("bytes", total)
}

/// `borrar_parciales(carpeta)`: solo archivos con «partial» en el nombre dentro de blobs/, nunca un modelo completo
pub fn borrar_parciales(carpeta: Option<&str>) -> Mapa {
    let info = parciales(carpeta);
    let dir = info.texto("carpeta").unwrap_or("").to_string();
    let mut borrados = 0;
    for a in info.lista("archivos").unwrap_or(&[]) {
        let (ruta, n) = (get(a, "ruta").texto_py(), get(a, "nombre").texto_py());
        if py::dirname(&ruta) != dir || !n.contains("partial") {
            continue;
        }
        if std::fs::remove_file(&ruta).is_ok() {
            borrados += 1;
        }
    }
    Mapa::new().con("borrados", borrados).con("bytes", info.valor("bytes").clone())
}

// =========================================================================== pasos

/// Lo que hace falta para crear una variante: (nombre, desde, system, parámetros, mensajes, licencia)
type DatosVariante = (String, String, String, Option<Valor>, Option<Valor>, String);

pub enum Pasos {
    Variante { base: String, datos: Box<Option<DatosVariante>>, lineas: Box<Option<Lineas>> },
    Importar(Box<Importar>),
    Fin,
}

fn abrir_stream(base: &str, ruta: &str, mut cuerpo: Mapa) -> R<Lineas> {
    cuerpo.poner("stream", true);
    match red::post_lineas(&format!("{base}{ruta}"), &Valor::Mapa(cuerpo))? {
        Ok(l) => Ok(l),
        Err(r) => Err(ErrorG::Gestion(r.error())),
    }
}

/// Una línea del stream: el JSON, o ErrorGestion si trae `error`
fn linea_stream(l: &mut Lineas) -> R<Option<Valor>> {
    let Some(t) = l.siguiente()? else { return Ok(None) };
    let d = prig_recursos::json::leer(&t).map_err(|e| ErrorG::Red(ErrorRed::Json(e, t.clone())))?;
    let e = py::get(&d, "error", Valor::Nulo).map_err(|e| ErrorG::Py(ErrorPy::Atributo(e)))?;
    if e.verdad() {
        return Err(ErrorG::Gestion(e.texto_py()));
    }
    Ok(Some(d))
}

impl Pasos {
    /// El siguiente paso, o None al terminar
    pub fn siguiente(&mut self) -> R<Option<Valor>> {
        let r = self.paso();
        if !matches!(r, Ok(Some(_))) {
            *self = Pasos::Fin;
        }
        r
    }

    fn paso(&mut self) -> R<Option<Valor>> {
        match self {
            Pasos::Fin => Ok(None),
            Pasos::Variante { base, datos, lineas } => {
                if let Some((n, desde, system, params, mensajes, licencia)) = datos.take() {
                    let n = nombre(&n)?;
                    if n == desde || n == format!("{desde}:latest") {
                        return Err(ErrorG::Gestion("La variante necesita un nombre distinto del modelo base".into()));
                    }
                    let mut cuerpo = Mapa::new().con("model", n).con("from", desde);
                    if !py::strip(&system).is_empty() {
                        cuerpo.poner("system", system);
                    }
                    if let Some(Valor::Mapa(p)) = params.filter(|p| p.verdad()) {
                        let mut filtrado = Mapa::new();
                        for (k, v) in p.iter() {
                            if !["keep_alive", "think", "system_extra", "truncate", "shift"].contains(&k.as_str()) {
                                filtrado.poner(k.clone(), v.clone());
                            }
                        }
                        let validos = crate::opciones::validar(&Valor::Mapa(filtrado)).map_err(ErrorG::Py)?;
                        cuerpo.poner("parameters", validos);
                    }
                    if let Some(ms) = mensajes.filter(|m| m.verdad()) {
                        let mut limpios = Vec::new();
                        for m in py::iterar(&ms).map_err(|e| ErrorG::Py(ErrorPy::Tipo(e)))? {
                            let rol = get(&m, "role");
                            let ok_rol = matches!(&rol, Valor::Texto(r) if ["user", "assistant", "system"].contains(&r.as_str()));
                            let contenido = get(&m, "content");
                            let tiene = contenido.verdad() && !py::strip(&contenido.texto_py()).is_empty();
                            if ok_rol && tiene {
                                limpios.push(Valor::Mapa(Mapa::new().con("role", rol).con("content", contenido)));
                            }
                        }
                        if !limpios.is_empty() {
                            cuerpo.poner("messages", Valor::Lista(limpios));
                        }
                    }
                    if !py::strip(&licencia).is_empty() {
                        cuerpo.poner("license", licencia);
                    }
                    **lineas = Some(abrir_stream(base, "/api/create", cuerpo)?);
                }
                match lineas.as_mut() {
                    Some(l) => linea_stream(l),
                    None => Ok(None),
                }
            }
            Pasos::Importar(i) => i.paso(),
        }
    }
}

enum FaseImportar {
    Inicio,
    Huella { f: std::fs::File, h: Sha256, leidos: u64, total: u64 },
    Subiendo { hilo: std::thread::JoinHandle<Result<Respuesta, ErrorRed>>, enviado: Arc<AtomicU64>, total: u64, digest: String, dormir: bool },
    SubidaHecha { total: u64, digest: String },
    Crear { digest: String },
    Creando { lineas: Lineas },
    Listo,
    Fin,
}

pub struct Importar {
    base: String,
    ruta: String,
    nombre: String,
    cancelar: Option<Box<dyn FnMut() -> bool + Send>>,
    fase: FaseImportar,
}

const BLOQUE: usize = 8 * 1024 * 1024;

struct Contador<R: Read> {
    r: R,
    n: Arc<AtomicU64>,
}

impl<R: Read> Read for Contador<R> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let k = self.r.read(buf)?;
        self.n.fetch_add(k as u64, Ordering::SeqCst);
        Ok(k)
    }
}

fn progreso(fase: &str, hecho: u64, total: u64) -> Valor {
    Valor::Mapa(Mapa::new().con("fase", fase).con("hecho", hecho as i64).con("total", total as i64))
}

impl Importar {
    fn os(&self, e: std::io::Error) -> ErrorG {
        ErrorG::Py(ErrorPy::os(&e, &self.ruta))
    }

    /// Un paso, en el mismo momento que el generador de Python (cada petición, justo después del paso anterior)
    fn paso(&mut self) -> R<Option<Valor>> {
        loop {
            match std::mem::replace(&mut self.fase, FaseImportar::Fin) {
                FaseImportar::Inicio => {
                    self.nombre = nombre(&self.nombre)?;
                    if !std::path::Path::new(&self.ruta).is_file() {
                        return Err(ErrorG::Gestion(format!("No existe el archivo: {}", self.ruta)));
                    }
                    let mut firma = Vec::new();
                    std::fs::File::open(&self.ruta).map_err(|e| self.os(e))?.take(4).read_to_end(&mut firma).map_err(|e| self.os(e))?;
                    if firma != b"GGUF" {
                        return Err(ErrorG::Gestion("El archivo no es un modelo GGUF (no empieza por la firma GGUF)".into()));
                    }
                    let total = std::fs::metadata(&self.ruta).map(|m| m.len()).unwrap_or(0);
                    let f = std::fs::File::open(&self.ruta).map_err(|e| self.os(e))?;
                    self.fase = FaseImportar::Huella { f, h: Sha256::new(), leidos: 0, total };
                }
                // 1. Huella del archivo, de 8 MB en 8 MB
                FaseImportar::Huella { mut f, mut h, mut leidos, total } => {
                    let mut bloque = Vec::with_capacity(BLOQUE);
                    (&mut f).take(BLOQUE as u64).read_to_end(&mut bloque).map_err(|e| self.os(e))?;
                    if !bloque.is_empty() {
                        h.update(&bloque);
                        leidos += bloque.len() as u64;
                        if let Some(c) = self.cancelar.as_mut() {
                            if c() {
                                return Err(ErrorG::Gestion("Cancelado".into()));
                            }
                        }
                        self.fase = FaseImportar::Huella { f, h, leidos, total };
                        return Ok(Some(progreso("huella", leidos, total)));
                    }
                    let digest = format!("sha256:{}", hex(&h.finalize()));
                    // 2. Subirlo a Ollama si no lo tiene ya (en otro hilo, para poder informar del avance)
                    let url = format!("{}/api/blobs/{digest}", self.base);
                    if red::pedir("HEAD", &url, None, &[], 30.0)?.estado != 200 {
                        let enviado = Arc::new(AtomicU64::new(0));
                        let lector = Contador { r: std::fs::File::open(&self.ruta).map_err(|e| self.os(e))?, n: enviado.clone() };
                        let hilo = std::thread::spawn(move || red::subir(&url, std::io::BufReader::with_capacity(BLOQUE, lector)));
                        self.fase = FaseImportar::Subiendo { hilo, enviado, total, digest, dormir: false };
                    } else {
                        self.fase = FaseImportar::SubidaHecha { total, digest };
                    }
                }
                FaseImportar::Subiendo { hilo, enviado, total, digest, dormir } => {
                    if dormir {
                        std::thread::sleep(std::time::Duration::from_millis(500));
                    }
                    if !hilo.is_finished() {
                        let hecho = enviado.load(Ordering::SeqCst);
                        self.fase = FaseImportar::Subiendo { hilo, enviado, total, digest, dormir: true };
                        return Ok(Some(progreso("subida", hecho, total)));
                    }
                    let r = hilo.join().map_err(|_| ErrorG::Gestion("la subida terminó con un error interno".into()))??;
                    if r.estado != 200 && r.estado != 201 {
                        return Err(ErrorG::Gestion(format!("Ollama rechazó el archivo: {}", r.error())));
                    }
                    self.fase = FaseImportar::SubidaHecha { total, digest };
                }
                FaseImportar::SubidaHecha { total, digest } => {
                    self.fase = FaseImportar::Crear { digest };
                    return Ok(Some(progreso("subida", total, total)));
                }
                // 3. Crear el modelo a partir del archivo
                FaseImportar::Crear { digest } => {
                    let archivo = py::basename(&self.ruta);
                    let cuerpo = Mapa::new().con("model", self.nombre.clone()).con("files", Mapa::new().con(archivo, digest));
                    self.fase = FaseImportar::Creando { lineas: abrir_stream(&self.base, "/api/create", cuerpo)? };
                }
                FaseImportar::Creando { mut lineas } => match linea_stream(&mut lineas)? {
                    Some(d) => {
                        let estado = get(&d, "status");
                        self.fase = FaseImportar::Creando { lineas };
                        return Ok(Some(Valor::Mapa(Mapa::new().con("fase", "creando").con("estado", estado))));
                    }
                    None => self.fase = FaseImportar::Listo,
                },
                FaseImportar::Listo => {
                    return Ok(Some(Valor::Mapa(Mapa::new().con("fase", "listo").con("modelo", self.nombre.clone()))));
                }
                FaseImportar::Fin => return Ok(None),
            }
        }
    }
}
