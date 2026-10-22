//! La cola de descargas de modelos (`descargas_modelos.py`): progreso, velocidad, tiempo restante y cancelación.
//!
//! Una sola descarga a la vez: varias en paralelo no bajan más rápido (se reparten el mismo ancho de banda) y
//! complican ver qué pasa. Antes de empezar se comprueba el manifiesto en el registro de origen (existe, tamaño
//! exacto) y que cabe en el disco donde Ollama guarda los modelos. Cancelar cierra la conexión: Ollama conserva lo
//! descargado y, si se reintenta, continúa desde ahí. Las descargas `hf_completo` copian un repositorio entero de
//! Hugging Face (`descargas_hf`).
//!
//! Los errores de Ollama se traducen a algo accionable: 412 (tu Ollama es anterior al modelo), manifiesto
//! inexistente, licencia sin aceptar, sin espacio o sin conexión.
//!
//! Un desvío decidido: si comprobar en el registro falla con un error (no con «no descargable»), Python dejaba la
//! descarga en «comprobando» para siempre (el hilo moría); aquí termina en error con su motivo.

use crate::descargas_hf;
use prig_modelos::buscador::{self as b, ErrorB};
use prig_modelos::explorar;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use std::io::{BufRead, BufReader};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

pub const MAX_HISTORIAL: usize = 40;
const ACTIVOS: [&str; 3] = ["en_cola", "comprobando", "descargando"];

/// `explicar_error(texto, codigo)`
pub fn explicar_error(texto: &str, codigo: Option<u16>) -> String {
    let t = texto.to_lowercase();
    if t.contains("llama-server binary not found") {
        return crate::gestor::MENSAJE_RUNTIME_INCOMPLETO.to_string();
    }
    if codigo == Some(412) || t.contains("412") || t.contains("newer version") || t.contains("requires a newer") {
        return "Este modelo necesita una versión de Ollama más nueva que la instalada.".into();
    }
    if t.contains("file does not exist") || t.contains("not found") || codigo == Some(404) {
        return "El modelo o la variante no existe en el registro.".into();
    }
    if matches!(codigo, Some(401 | 403)) || t.contains("unauthorized") || t.contains("forbidden") || t.contains("gated") {
        return "El modelo requiere iniciar sesión o aceptar su licencia en la web de la plataforma.".into();
    }
    if t.contains("no space") || (t.contains("disk") && t.contains("full")) {
        return "No queda espacio en el disco de los modelos.".into();
    }
    if t.contains("timeout") || t.contains("connection") || t.contains("max retries") || t.contains("eof") {
        return "Se cortó la conexión. Reintenta: continúa desde lo ya descargado.".into();
    }
    if texto.is_empty() {
        "Error desconocido".into()
    } else {
        texto.to_string()
    }
}

/// `_fase_legible(status)`
pub fn fase_legible(s: &str) -> String {
    if s.starts_with("pulling manifest") {
        "Leyendo el manifiesto"
    } else if s.starts_with("pulling") {
        "Descargando"
    } else if s.starts_with("verifying") {
        "Verificando"
    } else if s.starts_with("writing") {
        "Guardando"
    } else if s == "success" {
        "Listo"
    } else {
        s
    }
    .to_string()
}

fn ahora() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

/// `shutil.disk_usage(ruta).free`
pub fn libre(ruta: &str) -> Option<i128> {
    let c = std::ffi::CString::new(ruta).ok()?;
    // SAFETY: statvfs llena la estructura que se le da
    unsafe {
        let mut s: libc::statvfs = std::mem::zeroed();
        if libc::statvfs(c.as_ptr(), &mut s) != 0 {
            return None;
        }
        Some(s.f_bavail as i128 * s.f_frsize as i128)
    }
}

/// Una descarga: sus campos públicos (en el orden de Python) y la marca de cancelar
pub struct Item {
    pub datos: Mapa,
    pub cancelar: Arc<AtomicBool>,
}

impl Item {
    fn id(&self) -> i128 {
        self.datos.valor("id").entero().unwrap_or(0)
    }

    fn estado(&self) -> &str {
        self.datos.texto("estado").unwrap_or("")
    }

    fn activa(&self) -> bool {
        ACTIVOS.contains(&self.estado())
    }
}

/// `_publico(item)`: los campos y el porcentaje
fn publico(d: &Mapa) -> Mapa {
    let total = d.valor("total");
    let porcentaje = if total.verdad() {
        let c = d.valor("completado").num().unwrap_or(0.0);
        Valor::Real(prig_recursos::valor::redondear(100.0 * c / total.num().unwrap_or(1.0), 1))
    } else {
        Valor::Nulo
    };
    d.clone().con("porcentaje", porcentaje)
}

/// Lo que la cola necesita de fuera
pub struct Config {
    /// La URL de Ollama
    pub base: Box<dyn Fn() -> String + Send + Sync>,
    /// La carpeta de los modelos
    pub carpeta: Box<dyn Fn() -> String + Send + Sync>,
    /// Al terminar bien (con la vista pública)
    pub al_terminar: Box<dyn Fn(&Mapa) + Send + Sync>,
    /// El espacio de trabajo (donde van las copias de Hugging Face)
    pub espacio: Box<dyn Fn() -> String + Send + Sync>,
    /// `buscador.comprobar`
    pub comprobar: Box<dyn Fn(&str) -> Result<Valor, ErrorB> + Send + Sync>,
}

struct Estado {
    items: Vec<Item>,
    siguiente: i128,
    hilo: bool,
}

pub struct Cola {
    estado: Mutex<Estado>,
    hay_trabajo: Condvar,
    trabajo: Mutex<bool>,
    config: Config,
}

impl Cola {
    pub fn new(config: Config) -> Arc<Cola> {
        Arc::new(Cola {
            estado: Mutex::new(Estado { items: Vec::new(), siguiente: 1, hilo: false }),
            hay_trabajo: Condvar::new(),
            trabajo: Mutex::new(false),
            config,
        })
    }

    fn cerrojo(&self) -> std::sync::MutexGuard<'_, Estado> {
        self.estado.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// `encolar(ref, titulo, tipo, variante, destino)`
    pub fn encolar(self: &Arc<Self>, r: &str, titulo: Option<&str>, tipo: &str, variante: Option<&str>, destino: Option<&str>) -> Result<Mapa, ErrorB> {
        let r = b::validar_ref(r)?;
        let mut e = self.cerrojo();
        let clave = if tipo != "ollama" { format!("{tipo}:{r}") } else { r.clone() };
        if let Some(activo) = e.items.iter().find(|i| {
            let c = i.datos.get("clave_ref").filter(|v| v.verdad()).or(i.datos.get("ref")).map(Valor::texto_py).unwrap_or_default();
            c == clave && i.activa()
        }) {
            return Ok(publico(&activo.datos));
        }
        let id = e.siguiente;
        e.siguiente += 1;
        let opcional = |v: Option<&str>| v.map(Valor::from).unwrap_or(Valor::Nulo);
        let datos = Mapa::new()
            .con("id", id)
            .con("ref", r.as_str())
            .con("clave_ref", clave)
            .con("titulo", titulo.filter(|t| !t.is_empty()).unwrap_or(&r))
            .con("fuente", b::fuente_de_ref(&r))
            .con("tipo", tipo)
            .con("variante", opcional(variante))
            .con("destino", opcional(destino))
            .con("estado", "en_cola")
            .con("completado", 0)
            .con("total", Valor::Nulo)
            .con("velocidad", Valor::Nulo)
            .con("restante_s", Valor::Nulo)
            .con("fase", Valor::Nulo)
            .con("error", Valor::Nulo)
            .con("creado", ahora())
            .con("terminado", Valor::Nulo);
        let vista = publico(&datos);
        e.items.push(Item { datos, cancelar: Arc::new(AtomicBool::new(false)) });
        podar(&mut e.items);
        if !e.hilo {
            e.hilo = true;
            let cola = self.clone();
            std::thread::Builder::new().name("prig-descargas".into()).spawn(move || cola.bucle()).ok();
        }
        drop(e);
        *self.trabajo.lock().unwrap_or_else(|e| e.into_inner()) = true;
        self.hay_trabajo.notify_all();
        Ok(vista)
    }

    pub fn cancelar(&self, id: i128) -> Result<Mapa, ErrorB> {
        let mut e = self.cerrojo();
        let item = buscar(&mut e.items, id)?;
        if item.activa() {
            item.cancelar.store(true, Ordering::SeqCst);
            if item.estado() == "en_cola" {
                item.datos.poner("estado", "cancelado");
                item.datos.poner("terminado", ahora());
            }
        }
        Ok(publico(&item.datos))
    }

    pub fn reintentar(self: &Arc<Self>, id: i128) -> Result<Mapa, ErrorB> {
        let d = {
            let mut e = self.cerrojo();
            let item = buscar(&mut e.items, id)?;
            if !matches!(item.estado(), "error" | "cancelado") {
                return Ok(publico(&item.datos));
            }
            item.datos.clone()
        };
        let t = |k: &str| d.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py);
        let tipo = t("tipo").unwrap_or_else(|| "ollama".into());
        self.encolar(&t("ref").unwrap_or_default(), t("titulo").as_deref(), &tipo, t("variante").as_deref(), t("destino").as_deref())
    }

    pub fn limpiar_terminadas(&self) -> usize {
        let mut e = self.cerrojo();
        let antes = e.items.len();
        e.items.retain(Item::activa);
        antes - e.items.len()
    }

    pub fn lista(&self) -> Vec<Mapa> {
        let e = self.cerrojo();
        let mut v: Vec<&Item> = e.items.iter().collect();
        v.sort_by_key(|i| -i.id());
        v.into_iter().map(|i| publico(&i.datos)).collect()
    }

    fn fijar(&self, id: i128, cambios: Mapa) {
        let mut e = self.cerrojo();
        if let Some(i) = e.items.iter_mut().find(|i| i.id() == id) {
            for (k, v) in cambios.iter() {
                i.datos.poner(k.clone(), v.clone());
            }
        }
    }

    fn bucle(self: Arc<Self>) {
        loop {
            let siguiente = {
                let e = self.cerrojo();
                let mut en_cola: Vec<&Item> = e.items.iter().filter(|i| i.estado() == "en_cola").collect();
                en_cola.sort_by_key(|i| i.id());
                en_cola.first().map(|i| (i.datos.clone(), i.cancelar.clone()))
            };
            let Some((datos, cancelar)) = siguiente else {
                let mut hay = self.trabajo.lock().unwrap_or_else(|e| e.into_inner());
                *hay = false;
                let (hay, _) = self.hay_trabajo.wait_timeout_while(hay, Duration::from_secs(30), |h| !*h).unwrap_or_else(|e| e.into_inner());
                if !*hay {
                    let mut e = self.cerrojo();
                    if !e.items.iter().any(|i| i.estado() == "en_cola") {
                        e.hilo = false;
                        return;
                    }
                }
                continue;
            };
            self.descargar(&datos, &cancelar);
        }
    }

    fn terminar(&self, id: i128, estado: &str, error: Option<String>) {
        let fase = match estado {
            "completado" => "Listo",
            "cancelado" => "Cancelado (lo descargado se conserva)",
            _ => "Error",
        };
        self.fijar(
            id,
            Mapa::new()
                .con("estado", estado)
                .con("error", error.map(Valor::Texto).unwrap_or(Valor::Nulo))
                .con("terminado", ahora())
                .con("velocidad", Valor::Nulo)
                .con("restante_s", Valor::Nulo)
                .con("fase", fase),
        );
        if estado == "completado" {
            let vista = self.cerrojo().items.iter().find(|i| i.id() == id).map(|i| publico(&i.datos));
            if let Some(v) = vista {
                (self.config.al_terminar)(&v);
            }
        }
    }

    fn descargar_hf(&self, d: &Mapa, cancelar: &Arc<AtomicBool>) {
        let id = d.valor("id").entero().unwrap_or(0);
        let (repo, var_ref) = descargas_hf::limpiar_repo(&d.valor("ref").texto_py());
        let variante = d.get("variante").filter(|v| v.verdad()).map(Valor::texto_py).or(var_ref);
        let destino = d.get("destino").filter(|v| !v.es_nulo()).map(Valor::texto_py);
        self.fijar(id, Mapa::new().con("estado", "descargando").con("fase", "Iniciando respaldo completo de Hugging Face"));
        let espacio = (self.config.espacio)();
        let fijar = |m: Mapa| self.fijar(id, m);
        match descargas_hf::descargar_completo(&repo, variante.as_deref(), destino.as_deref(), &espacio, cancelar, &fijar) {
            Ok(r) => {
                self.fijar(id, Mapa::new().con("estado", "completado").con("carpeta_guardada", r.valor("carpeta").clone()));
                self.terminar(id, "completado", None);
            }
            Err(_) if cancelar.load(Ordering::SeqCst) => self.terminar(id, "cancelado", None),
            Err(e) => self.terminar(id, "error", Some(e)),
        }
    }

    fn descargar(&self, d: &Mapa, cancelar: &Arc<AtomicBool>) {
        if d.texto("tipo") == Some("hf_completo") {
            return self.descargar_hf(d, cancelar);
        }
        let id = d.valor("id").entero().unwrap_or(0);
        let r = d.valor("ref").texto_py();
        self.fijar(id, Mapa::new().con("estado", "comprobando").con("fase", "Comprobando en el registro"));
        let c = match (self.config.comprobar)(&r) {
            Ok(Valor::Mapa(c)) => c,
            Ok(_) => Mapa::new(),
            Err(e) => return self.terminar(id, "error", Some(explicar_error(&explorar::texto_error(&e), None))),
        };
        if !c.verdad("descargable") {
            let motivo = c.get("motivo").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| "No se puede descargar".into());
            return self.terminar(id, "error", Some(motivo));
        }
        let bytes = c.get("bytes").cloned().unwrap_or(Valor::Nulo);
        self.fijar(id, Mapa::new().con("total", bytes.clone()));
        let carpeta = (self.config.carpeta)();
        let donde = if std::path::Path::new(&carpeta).is_dir() { carpeta.clone() } else { py::expanduser("~") };
        if let (Some(libre), Some(n)) = (libre(&donde), bytes.num().filter(|_| bytes.verdad())) {
            if (libre as f64) < n * 1.05 {
                return self.terminar(
                    id,
                    "error",
                    Some(format!("No hay espacio: hacen falta {:.1} GB y quedan {:.1} GB libres en {carpeta}.", n / 1e9, libre as f64 / 1e9)),
                );
            }
        }
        if cancelar.load(Ordering::SeqCst) {
            return self.terminar(id, "cancelado", None);
        }
        self.fijar(id, Mapa::new().con("estado", "descargando").con("fase", "Conectando"));
        let total_previo = bytes.num().filter(|_| bytes.verdad());
        match self.tirar(id, &r, cancelar, total_previo) {
            Ok(()) => {}
            Err(e) => {
                if cancelar.load(Ordering::SeqCst) {
                    self.terminar(id, "cancelado", None)
                } else {
                    self.terminar(id, "error", Some(explicar_error(&e, None)))
                }
            }
        }
    }

    /// `POST /api/pull` en streaming; `Err` = la excepción de `requests` (su texto)
    fn tirar(&self, id: i128, r: &str, cancelar: &Arc<AtomicBool>, total_previo: Option<f64>) -> Result<(), String> {
        let cliente = reqwest::blocking::Client::builder()
            .connect_timeout(Duration::from_secs(15))
            .timeout(None)
            .build()
            .map_err(|e| e.to_string())?;
        let cuerpo = prig_plataforma::json::escribir_compacto(&Valor::Mapa(Mapa::new().con("model", r).con("stream", true)));
        let resp = cliente
            .post(format!("{}/api/pull", (self.config.base)()))
            .header("Content-Type", "application/json")
            .body(cuerpo)
            .send()
            .map_err(|e| e.to_string())?;
        let estado = resp.status().as_u16();
        if estado != 200 {
            let texto = resp.text().unwrap_or_default();
            let detalle = match prig_plataforma::json::leer(&texto) {
                Ok(Valor::Mapa(m)) => m.get("error").map(Valor::texto_py).unwrap_or_default(),
                _ => texto.chars().take(200).collect(),
            };
            self.terminar(id, "error", Some(explicar_error(&detalle, Some(estado))));
            return Ok(());
        }
        let mut capas: Vec<(String, f64, f64)> = Vec::new();
        let mut muestras: Vec<(Instant, f64)> = Vec::new();
        for linea in BufReader::new(resp).split(b'\n') {
            let linea = linea.map_err(|e| e.to_string())?;
            if cancelar.load(Ordering::SeqCst) {
                self.terminar(id, "cancelado", None);
                return Ok(());
            }
            if linea.iter().all(u8::is_ascii_whitespace) {
                continue;
            }
            let Ok(Valor::Mapa(d)) = prig_plataforma::json::leer(&String::from_utf8_lossy(&linea)) else { continue };
            if d.valor("error").verdad() {
                self.terminar(id, "error", Some(explicar_error(&d.valor("error").texto_py(), None)));
                return Ok(());
            }
            if d.valor("digest").verdad() && d.valor("total").verdad() {
                let digest = d.valor("digest").texto_py();
                let total = d.valor("total").num().unwrap_or(0.0);
                let hecho = d.get("completed").and_then(Valor::num).unwrap_or(0.0);
                match capas.iter_mut().find(|c| c.0 == digest) {
                    Some(c) => {
                        c.1 = total;
                        c.2 = hecho;
                    }
                    None => capas.push((digest, total, hecho)),
                }
            }
            let completado: f64 = capas.iter().map(|c| c.2).sum();
            let total = capas.iter().map(|c| c.1).sum::<f64>().max(total_previo.unwrap_or(0.0));
            let ya = Instant::now();
            muestras.push((ya, completado));
            muestras.retain(|m| ya.duration_since(m.0).as_secs_f64() <= 8.0);
            let velocidad = match (muestras.first(), muestras.last()) {
                (Some(a), Some(z)) if muestras.len() >= 2 && z.0 > a.0 => Some((z.1 - a.1) / z.0.duration_since(a.0).as_secs_f64()),
                _ => None,
            };
            let restante = velocidad.filter(|v| *v > 0.0).map(|v| (total - completado) / v);
            let fase = d.get("status").map(Valor::texto_py).unwrap_or_default();
            let num = |x: f64| if x.fract() == 0.0 && x.abs() < 1e18 { Valor::Entero(x as i128) } else { Valor::Real(x) };
            let total_v = if total != 0.0 { num(total) } else { total_previo.map(num).unwrap_or(Valor::Nulo) };
            let opt = |x: Option<f64>| x.map(Valor::Real).unwrap_or(Valor::Nulo);
            self.fijar(
                id,
                Mapa::new()
                    .con("completado", num(completado))
                    .con("total", total_v)
                    .con("velocidad", opt(velocidad))
                    .con("restante_s", opt(restante))
                    .con("fase", fase_legible(&fase)),
            );
            if fase == "success" {
                self.fijar(id, Mapa::new().con("completado", num(if total != 0.0 { total } else { completado })));
                self.terminar(id, "completado", None);
                return Ok(());
            }
        }
        self.terminar(id, "error", Some("La descarga terminó sin confirmación de Ollama. Reintenta.".into()));
        Ok(())
    }
}

fn buscar(items: &mut [Item], id: i128) -> Result<&mut Item, ErrorB> {
    items.iter_mut().find(|i| i.id() == id).ok_or_else(|| ErrorB::Buscador("Descarga desconocida".into()))
}

/// `_podar()`: se quedan las 40 terminadas más nuevas
fn podar(items: &mut Vec<Item>) {
    let mut terminadas: Vec<i128> = items.iter().filter(|i| !i.activa()).map(Item::id).collect();
    terminadas.sort();
    let sobran = terminadas.len().saturating_sub(MAX_HISTORIAL);
    let quitar: Vec<i128> = terminadas.into_iter().take(sobran).collect();
    items.retain(|i| !quitar.contains(&i.id()));
}

#[cfg(test)]
mod pruebas {
    use super::*;

    fn cola() -> Arc<Cola> {
        Cola::new(Config {
            base: Box::new(|| "http://127.0.0.1:9".into()),
            carpeta: Box::new(|| "/".into()),
            al_terminar: Box::new(|_| {}),
            espacio: Box::new(|| "/tmp".into()),
            comprobar: Box::new(|r| Ok(Valor::Mapa(Mapa::new().con("ref", r).con("descargable", false).con("motivo", "no está")))),
        })
    }

    #[test]
    fn la_cola_encola_cancela_y_limpia() {
        let c = cola();
        let a = c.encolar("qwen3:0.6b", None, "ollama", None, None).unwrap();
        assert_eq!(a.valor("id"), &Valor::Entero(1));
        assert_eq!(a.valor("titulo"), &Valor::Texto("qwen3:0.6b".into()));
        assert!(a.valor("porcentaje").es_nulo());
        assert!(matches!(c.cancelar(9), Err(ErrorB::Buscador(t)) if t == "Descarga desconocida"));
        for _ in 0..200 {
            if c.lista()[0].texto("estado") == Some("error") {
                break;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        let l = c.lista();
        assert_eq!(l[0].texto("error"), Some("no está"));
        assert_eq!(l[0].texto("fase"), Some("Error"));
        let b = c.reintentar(1).unwrap();
        assert_eq!(b.valor("id"), &Valor::Entero(2));
        std::thread::sleep(Duration::from_millis(300));
        assert_eq!(c.limpiar_terminadas(), 2);
    }

    #[test]
    fn los_errores_se_explican() {
        assert_eq!(explicar_error("pull model manifest: file does not exist", None), "El modelo o la variante no existe en el registro.");
        assert_eq!(explicar_error("", Some(412)), "Este modelo necesita una versión de Ollama más nueva que la instalada.");
        assert_eq!(explicar_error("", None), "Error desconocido");
        assert_eq!(explicar_error("error starting runner: llama-server binary not found", None), crate::gestor::MENSAJE_RUNTIME_INCOMPLETO);
        assert_eq!(fase_legible("pulling manifest"), "Leyendo el manifiesto");
        assert_eq!(fase_legible("pulling abc"), "Descargando");
    }
}
