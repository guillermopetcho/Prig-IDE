//! Generar con los modelos (el núcleo de `AIEngine` de Python): las opciones de cada petición (configuración de IA,
//! capas por modelo y uso, lo que pide la llamada), las capacidades del modelo, la recuperación de una falta de
//! memoria, el motor MoE, y las tres formas de generar con el gobernador térmico:
//!
//!   · `generar` (generate_response): texto, razonamiento y métricas por eventos;
//!   · `generar_con_pausas`: la respuesta entera, parando a enfriar cuando hace falta;
//!   · `chat_eventos`: el chat con razonamiento, herramientas, confianza, cortes por bucle y pausas térmicas.
//!
//! Cortar la conexión detiene la generación en Ollama (medido: de 40 a 15 W en 1,5 s), que es lo que enfría; lo ya
//! escrito se reenvía como principio de la respuesta del asistente y el modelo sigue desde ahí (Ollama reaprovecha
//! la caché del prefijo: retomar cuesta milisegundos).

use crate::gestor;
use crate::moe;
use crate::motor::{self, Respuesta};
use crate::ollama;
use crate::vivo::{self, Cancelar};
use prig_recursos::frio;
use prig_recursos::json;
use prig_recursos::ritmo;
use prig_recursos::termico::Tramo;
use prig_recursos::valor::{fijo, redondear, Mapa, Valor};
use std::collections::{BTreeSet, HashMap};
use std::io::BufRead;
use std::path::Path;
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::time::Duration;

pub const CONSULTA_REPETIDA: &str = "Ya hiciste exactamente esta consulta y su resultado está más arriba: no la repitas. \
Usa ese resultado, prueba una consulta DISTINTA o responde.";
pub const SIN_MAS_CONSULTAS: &str = "No hay más consultas: responde ahora la pregunta con lo que ya obtuviste. Si algo \
no lo pudiste confirmar, dilo en lugar de suponerlo.";
pub const SALIR_DEL_BUCLE: &str = "Te estás repitiendo. Detente y da ahora tu conclusión final en pocas líneas, sin \
repetir lo anterior.";

fn bloquear<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// Los modelos que ha usado este proceso (se descargan de Ollama para dejarle la VRAM al motor MoE, y al cerrar)
fn usados() -> &'static Mutex<BTreeSet<String>> {
    static U: OnceLock<Mutex<BTreeSet<String>>> = OnceLock::new();
    U.get_or_init(|| Mutex::new(BTreeSet::new()))
}

pub fn es_moe(modelo: &str) -> bool {
    modelo.trim() == moe::NOMBRE
}

/// Los modelos de Ollama que usa Prig: los usados y los de la configuración (sin el MoE)
pub fn modelos_propios() -> Vec<String> {
    let cfg = motor::config_ia();
    let mut propios = bloquear(usados()).clone();
    for k in ["agent1_model", "agent2_model", "agent3_model"] {
        if let Some(Valor::Texto(m)) = cfg.get(k) {
            propios.insert(m.clone());
        }
    }
    propios.into_iter().filter(|m| !m.is_empty() && !es_moe(m)).collect()
}

/// `int(x)` de Python para un valor de la configuración (None si no se puede)
fn entero(v: Option<&Valor>) -> Option<i64> {
    match v? {
        Valor::Entero(n) => Some(*n as i64),
        Valor::Bool(b) => Some(*b as i64),
        Valor::Real(x) if x.is_finite() => Some(x.trunc() as i64),
        Valor::Texto(t) => t.trim().parse().ok(),
        _ => None,
    }
}

/// `int(x or d)`
fn entero_o(v: Option<&Valor>, d: i64) -> i64 {
    match v {
        Some(x) if x.verdad() => entero(Some(x)).unwrap_or(d),
        _ => d,
    }
}

// =========================================================================== opciones

/// Las opciones que se mandan a Ollama, de menos a más prioridad: la configuración global de IA, las capas de Prig
/// (todos los modelos → este modelo → este uso → modelo en uso) y lo que exige la llamada. Lo que ninguna fija no se
/// envía y Ollama usa lo del modelo.
pub fn opciones(overrides: Option<&Mapa>, modelo: &str, uso: Option<&str>, raiz: &Path) -> Mapa {
    let cfg = motor::config_ia();
    let mut o = Mapa::new();
    if !cfg.get("muestreo_del_modelo").is_none_or(Valor::verdad) {
        for (clave, es_real) in [("temperature", true), ("top_k", false), ("top_p", true), ("repeat_penalty", true)] {
            if let Some(v) = cfg.get(clave).filter(|v| !v.es_nulo()) {
                if es_real {
                    if let Some(x) = v.num() {
                        o.poner(clave, x);
                    }
                } else if let Some(n) = entero(Some(v)) {
                    o.poner(clave, n);
                }
            }
        }
    }
    match cfg.get("num_ctx") {
        None => o.poner("num_ctx", 4096),
        Some(v) => {
            if let Some(n) = entero(Some(v)) {
                o.poner("num_ctx", n);
            }
        }
    }
    let num_gpu = entero_o(cfg.get("num_gpu"), -1);
    if num_gpu >= 0 {
        o.poner("num_gpu", num_gpu);
    }
    let num_thread = entero_o(cfg.get("num_thread"), 0);
    if num_thread > 0 {
        o.poner("num_thread", num_thread);
    } else {
        // Modo frío: con el modelo en RAM, 4 hilos en los núcleos E rinden como 8 en todos y calientan menos. Solo
        // si el usuario no fijó los hilos.
        let a = frio::por_defecto().fusion(&prig_recursos::almacen::global().seccion("frio"));
        if a.verdad("activo") {
            let e = ritmo::nucleos_eficientes();
            if !e.is_empty() {
                o.poner("num_thread", e.len());
            }
        }
    }
    let num_predict = entero_o(cfg.get("num_predict"), 0);
    if num_predict > 0 {
        o.poner("num_predict", num_predict);
    }
    let capas = prig_modelos::opciones::config().resolver(Some(modelo).filter(|m| !m.is_empty()), uso);
    if let Some(c) = capas.mapa("opciones") {
        for (k, v) in c.iter() {
            o.poner(k.clone(), v.clone());
        }
    }
    if let Some(over) = overrides {
        for (k, v) in over.iter().filter(|(_, v)| !v.es_nulo()) {
            o.poner(k.clone(), v.clone());
        }
    }
    if es_moe(modelo) {
        // El contexto del motor MoE se fija al arrancarlo: las métricas se calculan con ese
        o.poner("num_ctx", motor::global(raiz).contexto_actual_deseado());
    }
    prig_modelos::opciones::limpiar_para_ollama(&o)
}

/// keep_alive, think, instrucciones extra, truncate y shift de las capas
pub fn campos(modelo: &str, uso: Option<&str>) -> Mapa {
    prig_modelos::opciones::config().resolver(Some(modelo).filter(|m| !m.is_empty()), uso).mapa("campos").cloned().unwrap_or_default()
}

/// completion, tools, thinking, insert, vision, embedding (con caché de 10 min). Mandar `think` a un modelo que no
/// piensa da error 400 (medido).
pub fn capacidades(modelo: &str) -> Vec<String> {
    if es_moe(modelo) {
        return motor::CAPACIDADES.iter().map(|c| c.to_string()).collect();
    }
    static CACHE: OnceLock<Mutex<HashMap<String, (f64, Vec<String>)>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    let ahora = vivo::ahora();
    if let Some((t, c)) = bloquear(cache).get(modelo) {
        if ahora - t < 600.0 {
            return c.clone();
        }
    }
    let caps = (|| {
        let c = reqwest::blocking::Client::builder().timeout(Duration::from_secs(10)).build().ok()?;
        let cuerpo = json::escribir_compacto(&Valor::Mapa(Mapa::new().con("model", modelo)));
        let r = c.post(format!("{}/api/show", ollama::base_url())).header("Content-Type", "application/json").body(cuerpo).send().ok()?;
        // Python: `r.json().get("capabilities") or [] if r.status_code == 200 else []`
        match json::leer(&r.text().ok()?).ok()? {
            Valor::Mapa(m) => match m.get("capabilities") {
                Some(Valor::Lista(l)) if !l.is_empty() => Some(l.iter().map(Valor::texto_py).collect()),
                _ => Some(Vec::new()),
            },
            _ => None,
        }
    })()
    .unwrap_or_default();
    bloquear(cache).insert(modelo.to_string(), (ahora, caps.clone()));
    caps
}

/// Los campos de la petición a partir de las capas y de lo que pide la llamada; devuelve el sistema
pub fn completar_payload(payload: &mut Mapa, modelo: &str, uso: Option<&str>, think: Option<bool>, sistema: &str) -> String {
    let c = campos(modelo, uso);
    let keep_alive = match c.get("keep_alive") {
        Some(v) => Some(v.clone()),
        None => motor::config_ia().get("keep_alive").cloned(),
    };
    if let Some(k) = keep_alive.filter(|k| !k.es_nulo()) {
        payload.poner("keep_alive", k);
    }
    let think = match think {
        Some(t) => Some(t),
        None => c.get("think").filter(|v| !v.es_nulo()).map(Valor::verdad),
    };
    if let Some(t) = think {
        if capacidades(modelo).iter().any(|c| c == "thinking") {
            payload.poner("think", t);
        }
    }
    let extra = c.get("system_extra").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default();
    let extra = extra.trim();
    for clave in ["truncate", "shift"] {
        if let Some(v) = c.get(clave) {
            payload.poner(clave, v.clone());
        }
    }
    [sistema, extra].iter().filter(|t| !t.is_empty()).copied().collect::<Vec<_>>().join("\n\n")
}

/// Lo que Ollama devuelve al terminar, en unidades legibles
pub fn metricas(datos: &Mapa, num_ctx: Option<&Valor>) -> Mapa {
    let seg = |k: &str| redondear(datos.get(k).and_then(Valor::num).unwrap_or(0.0) / 1e9, 3);
    let num_ctx = match datos.get("contexto") {
        Some(v) if v.verdad() => Some(v.clone()),
        _ => num_ctx.cloned(),
    };
    let (eval_s, prompt_s) = (seg("eval_duration"), seg("prompt_eval_duration"));
    let contar = |k: &str| datos.get(k).cloned().unwrap_or(Valor::Entero(0));
    let (tp, tr) = (contar("prompt_eval_count"), contar("eval_count"));
    let velocidad = |n: &Valor, s: f64| if s != 0.0 { Valor::Real(redondear(n.num().unwrap_or(0.0) / s, 1)) } else { Valor::Nulo };
    let motivo = datos.get("done_reason").cloned().unwrap_or(Valor::Nulo);
    let mut m = Mapa::new()
        .con("total_s", seg("total_duration"))
        .con("carga_s", seg("load_duration"))
        .con("tokens_prompt", tp.clone())
        .con("tokens_respuesta", tr.clone())
        .con("lectura_tok_s", velocidad(&tp, prompt_s))
        .con("generacion_tok_s", velocidad(&tr, eval_s))
        .con("motivo_fin", motivo.clone())
        .con("proyecto", datos.get("proyecto").cloned().unwrap_or(Valor::Nulo))
        .con("cortada", motivo == Valor::Texto("length".into()));
    if let Some(n) = num_ctx.filter(Valor::verdad) {
        let usados = tp.num().unwrap_or(0.0) + tr.num().unwrap_or(0.0);
        let pct = redondear(100.0 * usados / n.num().unwrap_or(f64::NAN), 1);
        m.poner("contexto", n);
        m.poner("contexto_usado_pct", pct);
    }
    m
}

/// Si el final del texto ya apareció literal `veces - 1` veces antes, el modelo está en un bucle: dónde termina la
/// primera aparición (en caracteres; lo de antes del bucle). Medido: en 132 respuestas, solo una dispara esto.
pub fn corte_de_bucle(texto: &str, largo: usize, veces: usize) -> Option<usize> {
    let n = texto.chars().count();
    if n < largo * veces {
        return None;
    }
    let corte = texto.char_indices().nth(n - largo).map(|(i, _)| i)?;
    let (previo, cola) = (&texto[..corte], &texto[corte..]);
    if previo.matches(cola).count() < veces - 1 {
        return None;
    }
    let i = previo.find(cola)?;
    Some(previo[..i].chars().count() + largo)
}

fn prefijo(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

// =========================================================================== conexión

/// Una respuesta en streaming de Ollama o del motor MoE (líneas NDJSON); soltarla corta la generación
pub enum Conexion {
    Ollama(std::io::Lines<std::io::BufReader<reqwest::blocking::Response>>),
    Moe(moe::Flujo, motor::Guarda),
}

impl Conexion {
    /// La siguiente línea con algo (None al terminar). Error: la conexión o un JSON roto.
    pub fn siguiente(&mut self) -> Result<Option<Mapa>, String> {
        match self {
            Conexion::Ollama(lineas) => loop {
                let Some(l) = lineas.next() else { return Ok(None) };
                let l = l.map_err(|e| e.to_string())?;
                if l.is_empty() {
                    continue;
                }
                return match json::leer(&l)? {
                    Valor::Mapa(m) => Ok(Some(m)),
                    _ => Ok(Some(Mapa::new())),
                };
            },
            Conexion::Moe(f, _) => match f.siguiente()? {
                Some(Valor::Mapa(m)) => Ok(Some(m)),
                Some(_) => Ok(Some(Mapa::new())),
                None => Ok(None),
            },
        }
    }

    pub fn cerrar(self) {
        if let Conexion::Moe(f, _) = self {
            f.cerrar();
        }
    }
}

/// Lo que respondió el motor: la conexión, o el estado y el detalle del error (`_error_de`)
pub enum Envio {
    Bien(Conexion),
    Mal(u16, String),
}

fn detalle_de(texto: &str) -> String {
    match json::leer(texto) {
        Ok(Valor::Mapa(m)) => prefijo(&m.get("error").filter(|e| e.verdad()).map(Valor::texto_py).unwrap_or_default(), 300),
        _ => prefijo(texto, 300),
    }
}

fn cliente() -> Result<reqwest::blocking::Client, String> {
    static C: OnceLock<Result<reqwest::blocking::Client, String>> = OnceLock::new();
    C.get_or_init(|| {
        reqwest::blocking::Client::builder()
            .connect_timeout(Duration::from_secs(300))
            .timeout(None)
            .build()
            .map_err(|e| e.to_string())
    })
    .clone()
}

/// POST a Ollama que sobrevive a una falta de memoria al cargar: con menos contexto y después menos capas en GPU
/// (lo que funcionó se anota en los eventos de recursos). El motor MoE se sirve en su propio llama-server, con el
/// formato de Ollama. Error: la conexión.
pub fn post(raiz: &Path, ruta: &str, payload: Mapa, intentos: usize) -> Result<Envio, String> {
    let modelo = payload.get("model").map(Valor::texto_py).unwrap_or_default();
    if !modelo.is_empty() {
        bloquear(usados()).insert(modelo.clone());
    }
    if es_moe(&modelo) {
        let m = motor::global(raiz);
        let propios = modelos_propios();
        m.poner_liberar(if propios.is_empty() {
            None
        } else {
            Some(std::sync::Arc::new(move || ollama::descargar_propios(&propios)))
        });
        return Ok(match m.post(ruta, &Valor::Mapa(payload), 600.0, false) {
            Respuesta::Flujo(f, g) => Envio::Bien(Conexion::Moe(f, g)),
            Respuesta::Entera(estado, v) => {
                let t = json::escribir_compacto(&v);
                Envio::Mal(estado, detalle_de(&t))
            }
        });
    }
    let url = format!("{}{ruta}", ollama::base_url());
    let mut payload = payload;
    for n in 0..=intentos {
        let r = cliente()?
            .post(&url)
            .header("Content-Type", "application/json")
            .body(json::escribir_compacto(&Valor::Mapa(payload.clone())))
            .send()
            .map_err(|e| e.to_string())?;
        let estado = r.status().as_u16();
        if estado == 200 {
            return Ok(Envio::Bien(Conexion::Ollama(std::io::BufReader::new(r).lines())));
        }
        let detalle = detalle_de(&r.text().unwrap_or_default());
        if n == intentos {
            return Ok(Envio::Mal(estado, detalle));
        }
        let opciones = payload.mapa("options").cloned().unwrap_or_default();
        let Some(siguiente) = gestor::gestor(raiz).recuperar_oom(&modelo, &opciones, &detalle) else {
            return Ok(Envio::Mal(estado, detalle));
        };
        let mut nuevas = opciones;
        nuevas.quitar("num_gpu");
        for (k, v) in siguiente.iter() {
            nuevas.poner(k.clone(), v.clone());
        }
        payload.poner("options", nuevas);
        eprintln!("⚠️ {modelo} sin memoria; reintentando con {}", Valor::Mapa(siguiente).repr_py());
    }
    Err("sin respuesta".into())
}

// =========================================================================== el gobernador de una generación

/// El gobernador de una generación: cuándo cortar, enfriar y aprender de cada tramo. El de verdad es el de este
/// proceso (`vivo`); las pruebas ponen uno que corta cuando se les dice.
pub trait Gobernar {
    fn empezar(&self) -> Option<Tramo>;
    fn debe_cortar(&self, tramo: &mut Option<Tramo>) -> Option<&'static str>;
    fn terminar(&self, tramo: &Option<Tramo>, motivo: Option<&str>);
    /// Espera a que la GPU baje (o la pausa corta del modo suave); los segundos esperados
    fn enfriar(&self, motivo: &str, tramo: &mut Option<Tramo>, avisar: Option<&mut dyn FnMut(Mapa)>) -> f64;
    /// (temperatura de la GPU, límite, reanudar), o None sin gobernador
    fn temperaturas(&self, max_edad: f64) -> Option<(Valor, f64, f64)>;
    /// Cada cuánto se pregunta si hay que cortar (s)
    fn intervalo(&self) -> f64 {
        1.0
    }
}

/// El gobernador térmico de este proceso, si la generación lo usa
pub struct Gob<'a> {
    r: Option<&'static vivo::Recursos>,
    cancelar: &'a Cancelar,
    _trabajo: Option<vivo::Trabajando>,
}

impl<'a> Gob<'a> {
    pub fn new(raiz: &Path, usar: bool, cancelar: &'a Cancelar) -> Gob<'a> {
        let r = usar.then(|| vivo::recursos(raiz));
        if let Some(r) = r {
            r.sincronizar(); // lo que el otro proceso haya cambiado (límite, modo suave)
        }
        let trabajo = r.map(|r| r.monitor().trabajando());
        Gob { r, cancelar, _trabajo: trabajo }
    }
}

impl Gobernar for Gob<'_> {
    fn empezar(&self) -> Option<Tramo> {
        self.r.map(|r| r.empezar_tramo())
    }

    fn debe_cortar(&self, tramo: &mut Option<Tramo>) -> Option<&'static str> {
        match (self.r, tramo.as_mut()) {
            (Some(r), Some(t)) => r.debe_cortar(t),
            _ => None,
        }
    }

    fn terminar(&self, tramo: &Option<Tramo>, motivo: Option<&str>) {
        if let (Some(r), Some(t)) = (self.r, tramo.as_ref()) {
            r.terminar_tramo(t, motivo);
        }
    }

    fn enfriar(&self, motivo: &str, tramo: &mut Option<Tramo>, avisar: Option<&mut dyn FnMut(Mapa)>) -> f64 {
        match self.r {
            Some(r) => r.enfriar(motivo, Some(self.cancelar), avisar, None, tramo.as_mut()),
            None => 0.0,
        }
    }

    fn temperaturas(&self, max_edad: f64) -> Option<(Valor, f64, f64)> {
        let r = self.r?;
        let (limite, reanudar) = r.limite_y_reanudar();
        Some((r.monitor().gpu(max_edad), limite, reanudar))
    }
}

// =========================================================================== generar

/// Lo que pide `generate_response`
#[derive(Debug, Clone, Default)]
pub struct PedidoGenerar {
    pub prompt: String,
    pub modelo: String,
    pub sistema: String,
    pub opciones: Option<Mapa>,
    pub think: Option<bool>,
    /// Quien pide quiere el razonamiento (`on_thinking`): si el modelo piensa y no se dijo nada, se le pide
    pub con_pensamiento: bool,
    pub uso: Option<String>,
    pub gobernador: bool,
}

/// `generate_response` por eventos: `{"t": "texto", "v", "token"}` (cada trozo de la respuesta; `token`: si va
/// fuera de un bloque `<think>`), `{"t": "pensando", "v"}` y `{"t": "stats", "v"}`. Los errores llegan como texto
/// («[Error Ollama: …]»), como los devolvía Python.
pub fn generar(raiz: &Path, p: &PedidoGenerar, cancelar: &Cancelar, emitir: &mut dyn FnMut(Mapa)) {
    let gob = Gob::new(raiz, p.gobernador, cancelar);
    generar_con(raiz, p, cancelar, emitir, &gob)
}

/// `generar` con un gobernador dado
pub fn generar_con(raiz: &Path, p: &PedidoGenerar, cancelar: &Cancelar, emitir: &mut dyn FnMut(Mapa), gob: &dyn Gobernar) {
    let texto = |v: &str, token: bool| Mapa::new().con("t", "texto").con("v", v).con("token", token);
    let mut payload = Mapa::new()
        .con("model", p.modelo.as_str())
        .con("prompt", p.prompt.as_str())
        .con("stream", true)
        .con("options", opciones(p.opciones.as_ref(), &p.modelo, p.uso.as_deref(), raiz));
    if let Some(f) = p.opciones.as_ref().and_then(|o| o.get("format")).filter(|f| f.verdad()) {
        payload.poner("format", f.clone());
    }
    let mut think = p.think;
    if think.is_none() && p.con_pensamiento && capacidades(&p.modelo).iter().any(|c| c == "thinking") {
        think = Some(true);
    }
    let sistema = completar_payload(&mut payload, &p.modelo, p.uso.as_deref(), think, &p.sistema);
    if !sistema.is_empty() {
        payload.poner("system", sistema.as_str());
    }
    let tope = entero_o(payload.mapa("options").and_then(|o| o.get("num_predict")), 0);
    let num_ctx = payload.mapa("options").and_then(|o| o.get("num_ctx")).cloned();
    let (mut respuesta, mut pensamiento, mut generados) = (String::new(), String::new(), 0i64);
    let mut en_etiqueta = false;
    let mut primera = true;
    let r = (|| -> Result<(), String> {
        loop {
            let envio = if primera {
                post(raiz, "/api/generate", payload.clone(), 3)?
            } else {
                let mut mensajes = Vec::new();
                if !sistema.is_empty() {
                    mensajes.push(Valor::Mapa(Mapa::new().con("role", "system").con("content", sistema.as_str())));
                }
                mensajes.push(Valor::Mapa(Mapa::new().con("role", "user").con("content", p.prompt.as_str())));
                let mut asistente = Mapa::new().con("role", "assistant").con("content", respuesta.as_str());
                if !pensamiento.is_empty() {
                    asistente.poner("thinking", pensamiento.as_str());
                }
                mensajes.push(Valor::Mapa(asistente));
                let mut seguir = Mapa::new();
                for (k, v) in payload.iter().filter(|(k, _)| !["prompt", "system", "raw", "context"].contains(&k.as_str())) {
                    seguir.poner(k.clone(), v.clone());
                }
                let mut o = payload.mapa("options").cloned().unwrap_or_default();
                if tope > 0 {
                    o.poner("num_predict", (tope - generados).max(1));
                }
                seguir.poner("options", o);
                seguir.poner("messages", Valor::Lista(mensajes));
                post(raiz, "/api/chat", seguir, 3)?
            };
            let mut con = match envio {
                Envio::Bien(c) => c,
                Envio::Mal(estado, detalle) => {
                    let d = if detalle.is_empty() { String::new() } else { format!(": {detalle}") };
                    emitir(texto(&format!("[Error Ollama: {estado}{d}]"), false));
                    return Ok(());
                }
            };
            let mut tramo = gob.empezar();
            let mut ultimo_control = vivo::ahora();
            let (mut motivo, mut terminado, mut pensando_ahora) = (None, false, false);
            let lectura = (|| -> Result<(), String> {
                while let Some(datos) = con.siguiente()? {
                    if cancelar.puesto() {
                        break; // cerrar la conexión hace que Ollama deje de generar
                    }
                    let mensaje = datos.mapa("message").cloned().unwrap_or_default();
                    let parte_pensamiento = [datos.get("thinking"), mensaje.get("thinking")]
                        .into_iter()
                        .flatten()
                        .find(|v| v.verdad())
                        .map(Valor::texto_py)
                        .unwrap_or_default();
                    if !parte_pensamiento.is_empty() {
                        pensamiento.push_str(&parte_pensamiento);
                        generados += 1;
                        pensando_ahora = true;
                        emitir(Mapa::new().con("t", "pensando").con("v", parte_pensamiento.as_str()));
                    }
                    let parte = [datos.get("response"), mensaje.get("content")]
                        .into_iter()
                        .flatten()
                        .find(|v| v.verdad())
                        .map(Valor::texto_py)
                        .unwrap_or_default();
                    if !parte.is_empty() {
                        respuesta.push_str(&parte);
                        generados += 1;
                        pensando_ahora = false;
                        if parte.contains("<think>") {
                            en_etiqueta = true;
                        }
                        if en_etiqueta {
                            let limpio = parte.replace("<think>", "").replace("</think>", "");
                            if !limpio.is_empty() && p.con_pensamiento {
                                emitir(Mapa::new().con("t", "pensando").con("v", limpio.as_str()));
                            }
                            if parte.contains("</think>") {
                                en_etiqueta = false;
                            }
                            emitir(texto(&parte, false));
                        } else {
                            emitir(texto(&parte, true));
                        }
                    }
                    if datos.verdad("done") {
                        terminado = true;
                        emitir(Mapa::new().con("t", "stats").con("v", metricas(&datos, num_ctx.as_ref())));
                        break;
                    }
                    let ahora = vivo::ahora();
                    if ahora - ultimo_control >= gob.intervalo() {
                        ultimo_control = ahora;
                        motivo = gob.debe_cortar(&mut tramo);
                        // Cortar a mitad del razonamiento hace que el modelo lo dé por cerrado: el modo suave espera
                        // a que empiece a responder (el límite, no)
                        if motivo == Some("ritmo") && (pensando_ahora || en_etiqueta) {
                            motivo = None;
                        }
                        if motivo.is_some() {
                            break;
                        }
                    }
                }
                Ok(())
            })();
            con.cerrar();
            lectura?;
            if terminado || motivo.is_none() || cancelar.puesto() || (tope > 0 && generados >= tope) {
                gob.terminar(&tramo, if terminado { None } else { motivo });
                return Ok(());
            }
            let m = motivo.unwrap_or("limite");
            gob.enfriar(m, &mut tramo, None);
            gob.terminar(&tramo, Some(m));
            if cancelar.puesto() {
                return Ok(());
            }
            primera = false;
        }
    })();
    if let Err(e) = r {
        emitir(texto(&format!("[Error de conexión con Ollama: {e}]"), false));
    }
}

// =========================================================================== generar con pausas

#[derive(Debug, Clone, Default)]
pub struct PedidoPausas {
    pub prompt: String,
    pub modelo: String,
    pub sistema: String,
    pub opciones: Option<Mapa>,
    pub think: Option<bool>,
    pub uso: Option<String>,
    pub gobernador: bool,
}

/// La respuesta completa por /api/chat (que permite CONTINUAR), parando a enfriar la GPU cuando hace falta. Si se
/// corta durante el razonamiento de un modelo que piensa, al retomar Ollama cierra ese razonamiento y pasa a la
/// respuesta: se avisa. Error: el de Ollama o la conexión (el RuntimeError de Python).
pub fn generar_con_pausas(raiz: &Path, p: &PedidoPausas, cancelar: &Cancelar, avisar: Option<&mut dyn FnMut(Mapa)>) -> Result<String, String> {
    let gob = Gob::new(raiz, p.gobernador, cancelar);
    generar_con_pausas_con(raiz, p, cancelar, avisar, &gob)
}

/// `generar_con_pausas` con un gobernador dado
pub fn generar_con_pausas_con(
    raiz: &Path,
    p: &PedidoPausas,
    cancelar: &Cancelar,
    mut avisar: Option<&mut dyn FnMut(Mapa)>,
    gob: &dyn Gobernar,
) -> Result<String, String> {
    let opc = opciones(p.opciones.as_ref(), &p.modelo, p.uso.as_deref(), raiz);
    let tope = entero_o(opc.get("num_predict"), 0);
    let mut base = Mapa::new();
    let sistema = completar_payload(&mut base, &p.modelo, p.uso.as_deref(), p.think, &p.sistema);
    let think = base.get("think").cloned();
    let mut mensajes = Vec::new();
    if !sistema.is_empty() {
        mensajes.push(Valor::Mapa(Mapa::new().con("role", "system").con("content", sistema.as_str())));
    }
    mensajes.push(Valor::Mapa(Mapa::new().con("role", "user").con("content", p.prompt.as_str())));
    let (mut contenido, mut pensamiento, mut generados) = (String::new(), String::new(), 0i64);
    let keep_alive = base.get("keep_alive").cloned();
    loop {
        if cancelar.puesto() {
            break;
        }
        let mut payload = Mapa::new().con("model", p.modelo.as_str()).con("stream", true).con("options", opc.clone());
        for k in ["truncate", "shift"] {
            if let Some(v) = base.get(k) {
                payload.poner(k, v.clone());
            }
        }
        if tope > 0 {
            let mut o = opc.clone();
            o.poner("num_predict", (tope - generados).max(1));
            payload.poner("options", o);
        }
        if let Some(k) = keep_alive.clone().filter(|k| !k.es_nulo()) {
            payload.poner("keep_alive", k);
        }
        if let Some(t) = think.clone().filter(|t| !t.es_nulo()) {
            payload.poner("think", t.verdad());
        }
        if let Some(f) = p.opciones.as_ref().and_then(|o| o.get("format")).filter(|f| f.verdad()) {
            payload.poner("format", f.clone());
        }
        let mut todos = mensajes.clone();
        if !contenido.is_empty() || !pensamiento.is_empty() {
            let mut asistente = Mapa::new().con("role", "assistant").con("content", contenido.as_str());
            if !pensamiento.is_empty() {
                asistente.poner("thinking", pensamiento.as_str());
            }
            todos.push(Valor::Mapa(asistente));
        }
        payload.poner("messages", Valor::Lista(todos));
        let mut tramo = gob.empezar();
        let envio = post(raiz, "/api/chat", payload, 3)?;
        let (mut motivo, mut terminado) = (None, false);
        let mut ultimo_control = vivo::ahora();
        let mut con = match envio {
            Envio::Bien(c) => c,
            Envio::Mal(estado, detalle) => return Err(format!("Error Ollama {estado}: {detalle}")),
        };
        let lectura = (|| -> Result<(), String> {
            while let Some(datos) = con.siguiente()? {
                if datos.verdad("error") {
                    return Err(datos.valor("error").texto_py());
                }
                let msg = datos.mapa("message").cloned().unwrap_or_default();
                let piensa = msg.get("thinking").filter(|v| v.verdad()).map(Valor::texto_py);
                let dice = msg.get("content").filter(|v| v.verdad()).map(Valor::texto_py);
                if let Some(t) = &piensa {
                    pensamiento.push_str(t);
                    generados += 1;
                }
                if let Some(c) = &dice {
                    contenido.push_str(c);
                    generados += 1;
                }
                if datos.verdad("done") {
                    terminado = true;
                    break;
                }
                if cancelar.puesto() {
                    break;
                }
                let ahora = vivo::ahora();
                if ahora - ultimo_control >= gob.intervalo() {
                    ultimo_control = ahora;
                    motivo = gob.debe_cortar(&mut tramo);
                    if motivo == Some("ritmo") && piensa.is_some() && dice.is_none() {
                        motivo = None;
                    }
                    if motivo.is_some() {
                        break;
                    }
                }
            }
            Ok(())
        })();
        con.cerrar();
        lectura?;
        if terminado || motivo.is_none() || (tope > 0 && generados >= tope) {
            gob.terminar(&tramo, motivo);
            break;
        }
        let m = motivo.unwrap_or("limite");
        if let Some(a) = avisar.as_deref_mut() {
            if contenido.is_empty() && !pensamiento.is_empty() && m != "ritmo" {
                a(Mapa::new().con("tipo", "aviso_termico").con(
                    "mensaje",
                    "Pausa durante el razonamiento: al retomar, el modelo cerrará ese razonamiento y pasará a responder.",
                ));
            }
        }
        let a: Option<&mut dyn FnMut(Mapa)> = match avisar {
            Some(ref mut f) => Some(&mut **f),
            None => None,
        };
        gob.enfriar(m, &mut tramo, a);
        gob.terminar(&tramo, Some(m));
    }
    Ok(contenido)
}

// =========================================================================== chat

/// Las herramientas de un chat: sus definiciones (para el modelo) y quien las ejecuta
pub trait Herramientas {
    fn definiciones(&mut self) -> Option<Vec<Valor>>;
    fn ejecutar(&mut self, nombre: &str, argumentos: &Valor) -> String;
}

#[derive(Debug, Clone)]
pub struct PedidoChat {
    pub mensajes: Vec<Valor>,
    pub modelo: String,
    pub uso: Option<String>,
    pub think: Option<bool>,
    pub logprobs: i64,
    pub max_rondas: usize,
    pub gobernador: bool,
    pub extra: Option<Mapa>,
    pub max_tokens: Option<i64>,
}

impl Default for PedidoChat {
    fn default() -> Self {
        PedidoChat {
            mensajes: Vec::new(),
            modelo: String::new(),
            uso: Some("tutor".into()),
            think: None,
            logprobs: 0,
            max_rondas: 6,
            gobernador: false,
            extra: None,
            max_tokens: None,
        }
    }
}

/// `json.dumps(x, sort_keys=True)`: para reconocer una consulta repetida
fn ordenado(v: &Valor) -> Valor {
    match v {
        Valor::Mapa(m) => {
            let mut claves: Vec<&String> = m.claves().collect();
            claves.sort();
            let mut o = Mapa::new();
            for k in claves {
                o.poner(k.clone(), ordenado(m.valor(k)));
            }
            Valor::Mapa(o)
        }
        Valor::Lista(l) => Valor::Lista(l.iter().map(ordenado).collect()),
        x => x.clone(),
    }
}

fn aviso(v: &str) -> Mapa {
    Mapa::new().con("t", "aviso").con("v", v)
}

/// El chat por eventos: `texto`, `pensando`, `herramienta`, `resultado`, `logprobs`, `stats`, `aviso`, `error` y
/// `termico` (pausa para enfriar y reanudación). Si el último mensaje es del asistente, el modelo lo CONTINÚA.
///
/// Con herramientas: una consulta idéntica a otra ya hecha no se vuelve a ejecutar (se le recuerda que el resultado
/// está arriba) y, si insiste o se llega a la última ronda, se le pide responder; si aun así pide otra, esa ronda va
/// SIN herramientas. Medido (docs/estudio-banco.md): de las respuestas con 9 o más consultas solo 1 de 5 fue correcta.
pub fn chat_eventos(
    raiz: &Path,
    p: &PedidoChat,
    herramientas: Option<&mut dyn Herramientas>,
    cancelar: &Cancelar,
    emitir: &mut dyn FnMut(Mapa),
) {
    let gob = Gob::new(raiz, p.gobernador, cancelar);
    chat_eventos_con(raiz, p, herramientas, cancelar, emitir, &gob)
}

/// `chat_eventos` con un gobernador dado
pub fn chat_eventos_con(
    raiz: &Path,
    p: &PedidoChat,
    mut herramientas: Option<&mut dyn Herramientas>,
    cancelar: &Cancelar,
    emitir: &mut dyn FnMut(Mapa),
    gob: &dyn Gobernar,
) {
    let mut opc = opciones(None, &p.modelo, p.uso.as_deref(), raiz);
    let configurado = entero_o(opc.get("num_predict"), 0);
    if let Some(m) = p.max_tokens.filter(|m| *m != 0) {
        if configurado <= 0 || (p.think == Some(true) && configurado < m) {
            opc.poner("num_predict", m);
        }
    }
    let mut base = Mapa::new();
    let extra_sistema = completar_payload(&mut base, &p.modelo, p.uso.as_deref(), p.think, "");
    let mut msgs: Vec<Valor> = p.mensajes.clone();
    if !extra_sistema.is_empty() {
        match msgs.first_mut() {
            Some(Valor::Mapa(m)) if m.texto("role") == Some("system") => {
                let c = m.get("content").map(Valor::texto_py).unwrap_or_default();
                m.poner("content", format!("{c}\n\n{extra_sistema}"));
            }
            _ => msgs.insert(0, Valor::Mapa(Mapa::new().con("role", "system").con("content", extra_sistema.as_str()))),
        }
    }
    let caps = capacidades(&p.modelo);
    let mut definiciones = herramientas.as_deref_mut().and_then(|h| h.definiciones()).filter(|d| !d.is_empty());
    if definiciones.is_some() && !caps.iter().any(|c| c == "tools") {
        emitir(aviso(&format!("{} no admite herramientas: responde sin ellas.", p.modelo)));
        definiciones = None;
    }
    if p.think == Some(true) && !caps.iter().any(|c| c == "thinking") {
        emitir(aviso(&format!("{} no razona antes de responder.", p.modelo)));
    }
    let num_ctx = opc.get("num_ctx").cloned();

    // Espera a que la GPU baje, contando lo que pasa en el chat
    let enfriar = |motivo: &str, tramo: &mut Option<Tramo>, emitir: &mut dyn FnMut(Mapa)| {
        let Some((temp, limite, reanudar)) = gob.temperaturas(1.0) else { return };
        if motivo == "ritmo" {
            gob.enfriar("ritmo", tramo, None); // modo suave: pausa corta y sin avisos
            return;
        }
        let Some(t) = temp.num().filter(|t| *t > reanudar) else { return };
        emitir(Mapa::new().con("t", "termico").con("pausa", true).con(
            "v",
            format!(
                "GPU a {} °C (límite {} °C): pausa para enfriar; se sigue a {} °C sin perder la respuesta.",
                fijo(t, 0),
                fijo(limite, 0),
                fijo(reanudar, 0)
            ),
        ));
        let esperado = gob.enfriar(motivo, tramo, None);
        let ahora = gob.temperaturas(2.5).and_then(|(t, _, _)| t.num()).unwrap_or(0.0);
        emitir(Mapa::new().con("t", "termico").con("pausa", false).con(
            "v",
            format!("GPU a {} °C tras {} s: se reanuda.", fijo(ahora, 0), fijo(esperado, 0)),
        ));
    };

    enfriar("antes_de_paso", &mut None, emitir);
    let mut hechas: HashMap<String, String> = HashMap::new();
    let mut repetidas = 0;
    // Cuando se le pide responder, las herramientas SIGUEN en la petición: quitarlas cambia el prefijo que el motor
    // MoE guardó y lo relee entero (26 s y un estado nuevo de 246 MB). Recién si pide otra consulta hay una ronda
    // más, esa sí sin herramientas.
    let mut forzada = false;
    let mut salio_de_bucle = false;
    let (mut ronda, mut limite) = (0usize, p.max_rondas);
    while ronda < limite {
        if definiciones.is_some() && !forzada && ronda > 0 && ronda + 1 == p.max_rondas {
            forzada = true;
            msgs.push(Valor::Mapa(Mapa::new().con("role", "user").con("content", SIN_MAS_CONSULTAS)));
            emitir(aviso("Última ronda: se le pide al modelo que responda con lo que ya consultó."));
        }
        let (mut contenido, mut pensamiento) = (String::new(), String::new());
        let (mut llamadas, mut probabilidades): (Vec<Valor>, Vec<Valor>) = (Vec::new(), Vec::new());
        let (mut revisado, mut bucle) = (0usize, None);
        let mut estadisticas = None;
        loop {
            let mut todos = msgs.clone();
            if !contenido.is_empty() || !pensamiento.is_empty() {
                let mut parcial = Mapa::new().con("role", "assistant").con("content", contenido.as_str());
                if !pensamiento.is_empty() {
                    parcial.poner("thinking", pensamiento.as_str());
                }
                todos.push(Valor::Mapa(parcial));
            }
            let mut payload = Mapa::new()
                .con("model", p.modelo.as_str())
                .con("messages", Valor::Lista(todos))
                .con("stream", true)
                .con("options", opc.clone());
            for (k, v) in base.iter() {
                payload.poner(k.clone(), v.clone());
            }
            if let Some(e) = &p.extra {
                for (k, v) in e.iter() {
                    payload.poner(k.clone(), v.clone());
                }
            }
            if let Some(d) = &definiciones {
                payload.poner("tools", Valor::Lista(d.clone()));
            }
            if p.logprobs != 0 {
                payload.poner("logprobs", true);
                payload.poner("top_logprobs", p.logprobs);
            }
            let mut tramo = gob.empezar();
            let (mut motivo, mut terminado) = (None, false);
            let mut ultimo_control = vivo::ahora();
            let mut con = match post(raiz, "/api/chat", payload, 3) {
                Ok(Envio::Bien(c)) => c,
                Ok(Envio::Mal(estado, detalle)) => {
                    emitir(Mapa::new().con("t", "error").con("v", format!("Ollama {estado}: {detalle}")));
                    return;
                }
                Err(e) => {
                    emitir(Mapa::new().con("t", "error").con("v", format!("Error de conexión con Ollama: {e}")));
                    return;
                }
            };
            // Ok(true): se terminó la respuesta (error o «Detenido.» ya contados)
            let lectura = (|| -> Result<bool, String> {
                while let Some(datos) = con.siguiente()? {
                    if datos.verdad("error") {
                        emitir(Mapa::new().con("t", "error").con("v", datos.valor("error").texto_py()));
                        return Ok(true);
                    }
                    let msg = datos.mapa("message").cloned().unwrap_or_default();
                    let piensa = msg.get("thinking").filter(|v| v.verdad()).map(Valor::texto_py);
                    let dice = msg.get("content").filter(|v| v.verdad()).map(Valor::texto_py);
                    if let Some(t) = &piensa {
                        pensamiento.push_str(t);
                        emitir(Mapa::new().con("t", "pensando").con("v", t.as_str()));
                    }
                    if let Some(c) = &dice {
                        contenido.push_str(c);
                        emitir(Mapa::new().con("t", "texto").con("v", c.as_str()));
                        let largo = contenido.chars().count();
                        if largo - revisado >= 200 && !salio_de_bucle {
                            revisado = largo;
                            bucle = corte_de_bucle(&contenido, 240, 3);
                            if bucle.is_some() {
                                break;
                            }
                        }
                    }
                    if let Some(Valor::Lista(l)) = msg.get("tool_calls").filter(|v| v.verdad()) {
                        llamadas.extend(l.iter().cloned());
                    }
                    if let Some(Valor::Lista(l)) = datos.get("logprobs").filter(|v| v.verdad()) {
                        probabilidades.extend(l.iter().cloned());
                    }
                    if datos.verdad("done") {
                        estadisticas = Some(metricas(&datos, num_ctx.as_ref()));
                        terminado = true;
                        break;
                    }
                    if cancelar.puesto() {
                        emitir(aviso("Detenido."));
                        return Ok(true);
                    }
                    let ahora = vivo::ahora();
                    if ahora - ultimo_control >= gob.intervalo() {
                        ultimo_control = ahora;
                        motivo = gob.debe_cortar(&mut tramo);
                        // El modo suave no corta a mitad del razonamiento (el modelo lo daría por cerrado)
                        if motivo == Some("ritmo") && piensa.is_some() && dice.is_none() {
                            motivo = None;
                        }
                        if motivo.is_some() {
                            break;
                        }
                    }
                }
                Ok(false)
            })();
            con.cerrar();
            match lectura {
                Ok(true) => return,
                Ok(false) => {}
                Err(e) => {
                    emitir(Mapa::new().con("t", "error").con("v", format!("Error de conexión con Ollama: {e}")));
                    return;
                }
            }
            if terminado || motivo.is_none() {
                gob.terminar(&tramo, motivo);
                break;
            }
            let m = motivo.unwrap_or("limite");
            // Cortar la conexión detiene la generación en Ollama: es lo que enfría
            if contenido.is_empty() && !pensamiento.is_empty() && m != "ritmo" {
                emitir(aviso(
                    "Hubo una pausa térmica durante el razonamiento: al retomar, el modelo lo cerró y pasó a responder.",
                ));
            }
            enfriar(m, &mut tramo, emitir);
            gob.terminar(&tramo, Some(m));
            if cancelar.puesto() {
                emitir(aviso("Detenido."));
                return;
            }
        }

        if !probabilidades.is_empty() {
            let lista = probabilidades
                .iter()
                .take(4000)
                .map(|x| {
                    let x = match x {
                        Valor::Mapa(m) => m.clone(),
                        _ => Mapa::new(),
                    };
                    let alternativas = match x.get("top_logprobs") {
                        Some(Valor::Lista(l)) => l
                            .iter()
                            .map(|a| {
                                let a = match a {
                                    Valor::Mapa(m) => m.clone(),
                                    _ => Mapa::new(),
                                };
                                Valor::Mapa(
                                    Mapa::new()
                                        .con("token", a.get("token").cloned().unwrap_or(Valor::Nulo))
                                        .con("logprob", a.get("logprob").cloned().unwrap_or(Valor::Nulo)),
                                )
                            })
                            .collect(),
                        _ => Vec::new(),
                    };
                    Valor::Mapa(
                        Mapa::new()
                            .con("token", x.get("token").cloned().unwrap_or(Valor::Nulo))
                            .con("logprob", x.get("logprob").cloned().unwrap_or(Valor::Nulo))
                            .con("alternativas", Valor::Lista(alternativas)),
                    )
                })
                .collect();
            emitir(Mapa::new().con("t", "logprobs").con("v", Valor::Lista(lista)));
        }
        if let Some(b) = bucle {
            // Cortado por repetirse: lo de antes del bucle queda como su mensaje, y se le pide la conclusión
            salio_de_bucle = true;
            msgs.push(Valor::Mapa(Mapa::new().con("role", "assistant").con("content", prefijo(&contenido, b))));
            msgs.push(Valor::Mapa(Mapa::new().con("role", "user").con("content", SALIR_DEL_BUCLE)));
            emitir(aviso("El modelo repetía el mismo texto: se cortó y se le pide la conclusión."));
            forzada = forzada || definiciones.is_some();
            limite = limite.max(ronda + 2);
            ronda += 1;
            continue;
        }
        let Some(h) = herramientas.as_deref_mut().filter(|_| !llamadas.is_empty()) else {
            if let Some(e) = estadisticas {
                emitir(Mapa::new().con("t", "stats").con("v", e.con("rondas", ronda + 1)));
            }
            return;
        };
        if forzada && definiciones.is_some() {
            definiciones = None;
            limite = ronda + 2;
            ronda += 1;
            emitir(aviso(
                "El modelo pidió otra consulta en vez de responder: no se ejecuta; se le vuelve a pedir que responda, ya sin herramientas.",
            ));
            continue;
        }
        let mut asistente = Mapa::new()
            .con("role", "assistant")
            .con("content", contenido.as_str())
            .con("tool_calls", Valor::Lista(llamadas.clone()));
        if !pensamiento.is_empty() {
            asistente.poner("thinking", pensamiento.as_str());
        }
        msgs.push(Valor::Mapa(asistente));
        for llamada in &llamadas {
            let funcion = match llamada {
                Valor::Mapa(l) => l.mapa("function").cloned().unwrap_or_default(),
                _ => Mapa::new(),
            };
            let nombre = funcion.get("name").map(Valor::texto_py).unwrap_or_default();
            let argumentos = funcion.get("arguments").filter(|a| a.verdad()).cloned().unwrap_or(Valor::Mapa(Mapa::new()));
            emitir(Mapa::new().con("t", "herramienta").con("nombre", nombre.as_str()).con("argumentos", argumentos.clone()));
            let clave = format!("{nombre}:{}", json::escribir_compacto(&ordenado(&argumentos)));
            let resultado = match hechas.get(&clave) {
                Some(_) => {
                    repetidas += 1;
                    CONSULTA_REPETIDA.to_string()
                }
                None => {
                    let r = h.ejecutar(&nombre, &argumentos);
                    hechas.insert(clave, r.clone());
                    r
                }
            };
            emitir(Mapa::new().con("t", "resultado").con("nombre", nombre.as_str()).con("v", prefijo(&resultado, 2000)));
            msgs.push(Valor::Mapa(Mapa::new().con("role", "tool").con("tool_name", nombre.as_str()).con("content", resultado)));
        }
        if repetidas >= 2 && definiciones.is_some() && !forzada {
            forzada = true;
            msgs.push(Valor::Mapa(Mapa::new().con("role", "user").con("content", SIN_MAS_CONSULTAS)));
            emitir(aviso("El modelo repetía consultas: se le pide que responda con lo que ya tiene."));
        }
        ronda += 1;
    }
    emitir(aviso(&format!("Se alcanzó el máximo de {} rondas de herramientas.", p.max_rondas)));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bucle_como_python() {
        let frase: String = "Espera, creo que el error está en la línea 96. ".repeat(6);
        let texto = format!("Inicio único. {}", frase.repeat(4)); // más de 720 caracteres
        let corte = corte_de_bucle(&texto, 240, 3);
        assert!(corte.is_some());
        assert_eq!(corte_de_bucle("corto", 240, 3), None);
        let distinto: String = (0..800u32).map(|i| char::from_u32(0x61 + i % 26).unwrap_or('a')).collect();
        assert_eq!(corte_de_bucle(&format!("{distinto}ñ"), 240, 3), None);
    }

    #[test]
    fn metricas_de_ollama() {
        let d = Mapa::new()
            .con("total_duration", 2_500_000_000i64)
            .con("load_duration", 0)
            .con("prompt_eval_count", 100)
            .con("prompt_eval_duration", 500_000_000i64)
            .con("eval_count", 50)
            .con("eval_duration", 1_000_000_000i64)
            .con("done_reason", "length");
        let m = metricas(&d, Some(&Valor::Entero(4096)));
        assert_eq!(m.valor("total_s"), &Valor::Real(2.5));
        assert_eq!(m.valor("lectura_tok_s"), &Valor::Real(200.0));
        assert_eq!(m.valor("generacion_tok_s"), &Valor::Real(50.0));
        assert_eq!(m.valor("cortada"), &Valor::Bool(true));
        assert_eq!(m.valor("contexto_usado_pct"), &Valor::Real(3.7));
        let sin = metricas(&Mapa::new(), None);
        assert_eq!(sin.valor("lectura_tok_s"), &Valor::Nulo);
        assert!(!sin.contiene("contexto"));
    }
}
