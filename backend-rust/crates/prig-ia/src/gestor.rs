//! El gestor de recursos con el programa en marcha (`backend/recursos/gestor.py` y el encadenado de
//! `calibracion.py`): la radiografía con caché (lo estático se mide una vez por huella), las fichas de los modelos,
//! los veredictos para un uso, la recomendación ajustada por lo probado, las opciones de una petición, la recuperación
//! de una falta de memoria; y la calibración y la prueba de una recomendación con un modelo de verdad.

use crate::vivo::{self, Cancelar};
use prig_recursos::almacen::{self, Almacen};
use prig_recursos::calculadora::{self, Maquina};
use prig_recursos::calibracion::{self, FinGenerar, MundoPrueba};
use prig_recursos::valor::{redondear_entero, Mapa, Valor};
use prig_recursos::{detector, ficha, gestor as reglas};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock};
use std::time::Duration;

pub const REFRESCO_S: f64 = 5.0;

fn bloquear<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

fn almacen() -> Arc<Almacen> {
    almacen::global()
}

/// La URL de Ollama de los recursos: `PRIG_OLLAMA_URL` o la de siempre (no la de la configuración de IA)
pub fn url_ollama() -> String {
    std::env::var("PRIG_OLLAMA_URL").ok().filter(|u| !u.is_empty()).unwrap_or_else(|| "http://localhost:11434".into())
}

fn cache_fichas() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default().join(".prig_recursos_fichas.json")
}

/// El catálogo de Prig (los modelos de `agent_flows.py` y los de embeddings marcados como tales), para las fichas
/// de modelos sin descargar. Copia de agent_flows: lo comprueba `backend/tests/test_catalogo_rust.py`.
pub fn catalogo() -> &'static Mapa {
    static C: OnceLock<Mapa> = OnceLock::new();
    C.get_or_init(|| {
        let Ok(Valor::Mapa(c)) = prig_recursos::json::leer(include_str!("catalogo_modelos.json")) else { return Mapa::new() };
        let mut todo = c.mapa("modelos").cloned().unwrap_or_default();
        for (k, v) in c.mapa("embedding").cloned().unwrap_or_default().iter() {
            if let Valor::Mapa(m) = v {
                todo.poner(k.clone(), m.clone().con("embedding", true));
            }
        }
        todo
    })
}

/// El catálogo por partes: los modelos que generan (`agent_flows.MODELOS`) y los de embeddings
/// (`MODELOS_EMBEDDING`), cada uno tal cual
pub fn catalogo_partes() -> &'static (Mapa, Mapa) {
    static C: OnceLock<(Mapa, Mapa)> = OnceLock::new();
    C.get_or_init(|| {
        let Ok(Valor::Mapa(c)) = prig_recursos::json::leer(include_str!("catalogo_modelos.json")) else { return Default::default() };
        (c.mapa("modelos").cloned().unwrap_or_default(), c.mapa("embedding").cloned().unwrap_or_default())
    })
}

/// La versión y la plataforma del Python de Prig (lo que daba `platform` en el backend), para la radiografía. No
/// entran en la huella.
fn python_de_prig(raiz: &Path) -> &'static (String, String) {
    static P: OnceLock<(String, String)> = OnceLock::new();
    P.get_or_init(|| {
        let venv = raiz.join(".venv/bin/python");
        let python = if venv.exists() { venv } else { PathBuf::from("python3") };
        let salida = std::process::Command::new(python)
            .args(["-I", "-c", "import platform;print(platform.python_version());print(platform.platform())"])
            .output();
        match salida {
            Ok(s) if s.status.success() => {
                let t = String::from_utf8_lossy(&s.stdout).into_owned();
                let mut l = t.lines();
                (l.next().unwrap_or("").to_string(), l.next().unwrap_or("").to_string())
            }
            _ => (String::new(), String::new()),
        }
    })
}

// =========================================================================== el gestor

#[derive(Default)]
struct Cache {
    rad: Option<Mapa>,
    rad_t: f64,
    fichas: HashMap<String, Mapa>, // nombre | «nombre|digest» → ficha
}

pub struct Gestor {
    pub raiz: PathBuf,
    cache: Mutex<Cache>,
    /// Solo la radiografía: medir tarda un segundo y no se hace dos veces a la vez
    midiendo: Mutex<()>,
    pub ultimo_oom: Mutex<Mapa>,
}

pub fn gestor(raiz: &Path) -> &'static Gestor {
    static G: OnceLock<Gestor> = OnceLock::new();
    G.get_or_init(|| Gestor {
        raiz: raiz.to_path_buf(),
        cache: Mutex::new(Cache::default()),
        midiendo: Mutex::new(()),
        ultimo_oom: Mutex::new(Mapa::new()),
    })
}

impl Gestor {
    // ------------------------------------------------------------------ máquina

    /// Error: el mensaje de un fallo al leer la máquina
    pub fn radiografia(&self, fresca: bool) -> Result<Mapa, String> {
        let _m = bloquear(&self.midiendo);
        let (actual, t) = {
            let c = bloquear(&self.cache);
            (c.rad.clone(), c.rad_t)
        };
        if let Some(r) = &actual {
            if !fresca && vivo::ahora() - t < REFRESCO_S {
                return Ok(r.clone());
            }
        }
        let previa = match &actual {
            Some(r) => r.clone(),
            None => match almacen().radiografia() {
                Valor::Mapa(m) => m,
                _ => Mapa::new(),
            },
        };
        let (version, plataforma) = python_de_prig(&self.raiz);
        let mut rad = detector::radiografia(false, version, plataforma, &url_ollama(), &self.raiz.to_string_lossy())?;
        let ancho_previo = previa.get("ancho_banda_ram_gbps").filter(|v| v.verdad()).cloned();
        match ancho_previo {
            Some(a) if previa.get("huella") == rad.get("huella") => rad.poner("ancho_banda_ram_gbps", a),
            _ => rad.poner("ancho_banda_ram_gbps", detector::ancho_banda_ram(256)),
        }
        let cambia = actual.as_ref().is_none_or(|r| r.get("huella") != rad.get("huella"));
        if cambia || fresca {
            let _ = almacen().registrar_radiografia(rad.clone());
        }
        let mut c = bloquear(&self.cache);
        c.rad = Some(rad.clone());
        c.rad_t = vivo::ahora();
        Ok(rad)
    }

    pub fn maquina(&self, fresca: bool) -> Result<Maquina, String> {
        let rad = self.radiografia(fresca)?;
        let huella = rad.texto("huella").map(str::to_string);
        let cal = almacen().calibracion(huella.as_deref());
        Ok(Maquina::new(&rad, cal.as_ref()))
    }

    // ------------------------------------------------------------------ fichas

    /// Error: el mensaje del LookupError (no hay ficha)
    pub fn ficha(&self, nombre: &str, red: bool) -> Result<Mapa, String> {
        if let Some(f) = bloquear(&self.cache).fichas.get(nombre) {
            return Ok(f.clone());
        }
        let f = ficha::obtener(&url_ollama(), nombre, Some(catalogo()), red, &cache_fichas())?;
        if !f.verdad("estimada") {
            bloquear(&self.cache).fichas.insert(nombre.to_string(), f.clone());
        }
        Ok(f)
    }

    pub fn fichas_instaladas(&self) -> Vec<Mapa> {
        let url = url_ollama();
        let Ok(inst) = ficha::instalados(&url) else { return Vec::new() };
        let mut salida = Vec::new();
        for (nombre, info) in inst.iter() {
            let digest = match info {
                Valor::Mapa(i) => i.get("digest").map(Valor::texto_py).unwrap_or_default(),
                _ => String::new(),
            };
            let clave = format!("{nombre}|{digest}");
            let guardada = bloquear(&self.cache).fichas.get(&clave).cloned();
            let f = match guardada {
                Some(f) => f,
                None => {
                    let Ok(f) = ficha::desde_ollama(&url, nombre) else { continue };
                    let mut c = bloquear(&self.cache);
                    c.fichas.insert(clave, f.clone());
                    c.fichas.insert(nombre.clone(), f.clone());
                    f
                }
            };
            salida.push(f);
        }
        salida
    }

    pub fn olvidar_fichas(&self) {
        bloquear(&self.cache).fichas.clear();
    }

    // ------------------------------------------------------------------ recomendar

    /// Calidad del canario por modelo, de las pruebas en esta máquina
    pub fn medidas(&self) -> Mapa {
        reglas::medidas(&almacen().pruebas(None))
    }

    pub fn veredictos(&self, perfil: &str, tirador: &str) -> Result<Mapa, String> {
        let maq = self.maquina(false)?;
        let mut filas = calculadora::elegir_modelo(&self.fichas_instaladas(), &maq, perfil, tirador, &self.medidas())?;
        let pruebas = almacen().pruebas(None);
        for fila in filas.iter_mut() {
            let clave = Almacen::clave_prueba(&fila.valor("modelo").texto_py(), perfil);
            if let Some(Valor::Mapa(p)) = pruebas.get(&clave).filter(|p| p.verdad()) {
                let mut resumen = Mapa::new();
                for k in ["ok", "tok_s", "calidad", "fecha", "error", "opciones"] {
                    resumen.poner(k, p.get(k).cloned().unwrap_or(Valor::Nulo));
                }
                fila.poner("prueba", resumen);
            }
        }
        Ok(Mapa::new()
            .con("perfil", perfil)
            .con("tirador", tirador)
            .con("maquina", maq.resumen())
            .con("servidor", maq.servidor.mapa())
            .con("modelos", Valor::Lista(filas.into_iter().map(Valor::Mapa).collect())))
    }

    /// Error: `(es_lookup, mensaje)`; un LookupError (no hay ficha) es un 404
    pub fn recomendar(&self, modelo: &str, perfil: &str, tirador: &str) -> Result<Mapa, (bool, String)> {
        let maq = self.maquina(false).map_err(|e| (false, e))?;
        let f = self.ficha(modelo, true).map_err(|e| (true, e))?;
        let rec = calculadora::recomendar(&f, &maq, perfil, tirador).map_err(|e| (false, e))?;
        let prueba = almacen().prueba(&f.valor("nombre").texto_py(), perfil, None);
        let prueba = match prueba {
            Some(Valor::Mapa(p)) => Some(p),
            _ => None,
        };
        Ok(reglas::completar_recomendacion(rec, prueba.as_ref(), &f))
    }

    /// Lo que una petición de este uso debe mandar a Ollama: lo aplicado por el usuario o la recomendación
    pub fn opciones_para(&self, perfil: &str, modelo: &str) -> Mapa {
        if let Some(Valor::Mapa(a)) = almacen().aplicado(perfil) {
            if a.get("modelo") == Some(&Valor::Texto(modelo.into())) {
                return a.mapa("opciones").cloned().unwrap_or_default();
            }
        }
        self.recomendar(modelo, perfil, "equilibrado").ok().and_then(|r| r.mapa("opciones").cloned()).unwrap_or_default()
    }

    // ------------------------------------------------------------------ en vivo

    pub fn estado_vivo(&self) -> Result<Mapa, String> {
        let rad = self.radiografia(false)?;
        let (limite, reanudar) = vivo::recursos(&self.raiz).limite_y_reanudar();
        Ok(reglas::estado_vivo(&rad, limite, reanudar))
    }

    // ------------------------------------------------------------------ OOM

    /// Opciones más pequeñas tras una falta de memoria, o None si no queda margen
    pub fn recuperar_oom(&self, modelo: &str, opciones: &Mapa, mensaje: &str) -> Option<Mapa> {
        if !calibracion::es_oom(mensaje) {
            return None;
        }
        let f = self.ficha(modelo, false).unwrap_or_else(|_| Mapa::new().con("capas", 32));
        let mut base = Mapa::new();
        for (k, v) in opciones.iter() {
            if k == "num_ctx" || k == "num_gpu" {
                base.poner(k.clone(), v.clone());
            }
        }
        if base.get("num_gpu").and_then(Valor::num).unwrap_or(-1.0) < 0.0 {
            base.quitar("num_gpu");
        }
        let siguiente = calibracion::reducir(&f, &base)?;
        bloquear(&self.ultimo_oom).poner(
            modelo,
            Mapa::new().con("fecha", almacen::ahora()).con("antes", base.clone()).con("despues", siguiente.clone()),
        );
        let mensaje_corto: String = mensaje.chars().take(300).collect();
        let _ = almacen().evento(
            "oom",
            &format!("{modelo} se quedó sin memoria; reintento con {}.", Valor::Mapa(siguiente.clone()).repr_py()),
            Some(Valor::Mapa(
                Mapa::new()
                    .con("modelo", modelo)
                    .con("antes", base)
                    .con("despues", siguiente.clone())
                    .con("mensaje", mensaje_corto),
            )),
        );
        Some(siguiente)
    }
}

// =========================================================================== calibrar y probar

/// Solo una calibración o prueba a la vez
static EN_CURSO: AtomicBool = AtomicBool::new(false);

struct Turno;

impl Turno {
    fn tomar() -> Option<Turno> {
        EN_CURSO.compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire).ok().map(|_| Turno)
    }
}

impl Drop for Turno {
    fn drop(&mut self) {
        EN_CURSO.store(false, Ordering::Release);
    }
}

/// Por qué no terminó una prueba: cancelada (el `Cancelado` de Python) o un error con su mensaje
#[derive(Debug)]
pub enum Fallo {
    Cancelado,
    Error(String),
}

impl Fallo {
    /// El mensaje del evento de error del flujo NDJSON
    pub fn mensaje(&self) -> String {
        match self {
            Fallo::Cancelado => "Cancelado.".into(),
            Fallo::Error(e) => e.clone(),
        }
    }
}

pub const MENSAJE_RUNTIME_INCOMPLETO: &str = "El Ollama que está en marcha está incompleto: le falta su motor llama-server \
(y sin él tampoco usa la GPU), así que no puede cargar ningún modelo. Reinicia Ollama desde Prig (Modelos → Servidor → \
Guardar y reiniciar Ollama) para que use uno completo.";

/// Mensaje accionable para los errores de Ollama que no dependen del modelo (`explicar_error_motor`)
pub fn explicar_error_motor(texto: &str) -> Option<&'static str> {
    texto.contains("llama-server binary not found").then_some(MENSAJE_RUNTIME_INCOMPLETO)
}

#[derive(Default)]
struct Muestras {
    vram_pico_mb: f64,
    temp_max: f64,
    caliente: bool,
}

/// El mundo de una prueba: Ollama de los recursos, la GPU, el gobernador, el reloj y los avisos
struct MundoNativo<'a> {
    raiz: &'a Path,
    avisar: &'a mut dyn FnMut(Mapa),
    cancelar: &'a Cancelar,
    muestras: Arc<Mutex<Muestras>>,
    parar_muestreo: Option<(Arc<Cancelar>, std::thread::JoinHandle<()>)>,
}

impl MundoPrueba for MundoNativo<'_> {
    type Error = Fallo;

    fn cancelado(&mut self) -> Result<bool, Fallo> {
        Ok(self.cancelar.puesto())
    }

    fn cancelar(&mut self) -> Fallo {
        Fallo::Cancelado
    }

    fn esperar(&mut self, s: f64) -> Result<bool, Fallo> {
        Ok(self.cancelar.esperar(s))
    }

    fn dormir(&mut self, s: f64) -> Result<(), Fallo> {
        std::thread::sleep(Duration::from_secs_f64(s.max(0.0)));
        Ok(())
    }

    fn ahora(&mut self) -> Result<f64, Fallo> {
        Ok(vivo::ahora())
    }

    fn estado_gpu(&mut self) -> Result<Option<Mapa>, Fallo> {
        Ok(calibracion::estado_gpu())
    }

    fn reanudar(&mut self) -> Result<f64, Fallo> {
        Ok(vivo::recursos(self.raiz).limite_y_reanudar().1)
    }

    fn limite(&mut self) -> Result<f64, Fallo> {
        Ok(vivo::recursos(self.raiz).limite_y_reanudar().0)
    }

    fn avisar(&mut self, evento: Mapa) -> Result<(), Fallo> {
        (self.avisar)(evento);
        Ok(())
    }

    fn muestreo_empezar(&mut self, limite: f64) -> Result<(), Fallo> {
        *bloquear(&self.muestras) = Muestras::default();
        let parar = Cancelar::new();
        let (m, p) = (self.muestras.clone(), parar.clone());
        let hilo = std::thread::spawn(move || {
            while !p.puesto() {
                if let Some(e) = calibracion::estado_gpu() {
                    let mut s = bloquear(&m);
                    s.vram_pico_mb = s.vram_pico_mb.max(e.num_o("vram_mb", 0.0));
                    let t = e.num_o("temp_c", 0.0);
                    s.temp_max = s.temp_max.max(t);
                    if t >= limite {
                        s.caliente = true;
                    }
                }
                p.esperar(0.5);
            }
        });
        self.parar_muestreo = Some((parar, hilo));
        Ok(())
    }

    fn muestreo_terminar(&mut self) -> Result<(f64, f64), Fallo> {
        if let Some((p, hilo)) = self.parar_muestreo.take() {
            p.poner();
            let _ = hilo.join();
        }
        let s = bloquear(&self.muestras);
        Ok((s.vram_pico_mb, s.temp_max))
    }

    fn generar(&mut self, cuerpo: &Mapa) -> Result<FinGenerar, Fallo> {
        let m = self.muestras.clone();
        Ok(calibracion::generar_stream(&url_ollama(), cuerpo, || bloquear(&m).caliente, 600.0))
    }

    fn ps(&mut self, modelo: &str) -> Result<Option<Mapa>, Fallo> {
        Ok(calibracion::ps(&url_ollama(), modelo))
    }

    fn descargar(&mut self, modelo: &str) -> Result<(), Fallo> {
        calibracion::descargar(&url_ollama(), modelo);
        Ok(())
    }

    fn explicar(&mut self, error: &str) -> Result<String, Fallo> {
        Ok(explicar_error_motor(error).map(str::to_string).unwrap_or_else(|| error.to_string()))
    }
}

fn probar(raiz: &Path, f: &Mapa, opciones: &Mapa, avisar: &mut dyn FnMut(Mapa), cancelar: &Cancelar) -> Result<Mapa, Fallo> {
    let mut mundo =
        MundoNativo { raiz, avisar, cancelar, muestras: Arc::new(Mutex::new(Muestras::default())), parar_muestreo: None };
    let r = calibracion::probar(f, opciones, &mut mundo, 200, false);
    let _ = mundo.muestreo_terminar();
    r
}

fn prevision(f: &Mapa, maq: &Maquina, ctx: i64) -> Mapa {
    let e = calculadora::estimar(f, maq, ctx, 1, "f16").mapa();
    let mut p = Mapa::new();
    for k in ["tok_s", "total_gb", "fraccion_gpu"] {
        p.poner(k, e.get(k).cloned().unwrap_or(Valor::Nulo));
    }
    p
}

/// Calibrar con dos modelos instalados que den información distinta
pub fn calibrar(raiz: &Path, fichas: &[Mapa], maq: Maquina, avisar: &mut dyn FnMut(Mapa), cancelar: &Cancelar, previa: Option<&Mapa>) -> Result<Mapa, Fallo> {
    let Some(_turno) = Turno::tomar() else { return Err(Fallo::Error("Ya hay una calibración en marcha.".into())) };
    let mut maq = maq;
    let elegidos = calibracion::elegir_modelos_prueba(fichas, &maq);
    if elegidos.is_empty() {
        return Ok(Mapa::new().con("ok", false).con("error", "No hay ningún modelo instalado con el que medir."));
    }
    let nombres: Vec<String> = elegidos.iter().map(|f| f.valor("nombre").texto_py()).collect();
    avisar(
        Mapa::new()
            .con("tipo", "plan")
            .con("modelos", Valor::Lista(nombres.iter().map(|n| Valor::from(n.as_str())).collect()))
            .con(
                "mensaje",
                format!(
                    "Voy a medir con {}. Cada prueba dura unos segundos y el modelo se descarga al terminar.",
                    nombres.join(" y ")
                ),
            ),
    );
    let (mut pruebas, mut deducidos) = (Vec::new(), Vec::new());
    for f in &elegidos {
        let mut r = probar(raiz, f, &Mapa::new().con("num_ctx", 4096), avisar, cancelar)?;
        let ctx = r.mapa("opciones").and_then(|o| o.get("num_ctx")).and_then(Valor::num).map(|n| n as i64).unwrap_or(4096);
        r.poner("prevision", prevision(f, &maq, ctx));
        let d = calibracion::deducir(f, &r, &maq);
        pruebas.push(Valor::Mapa(r));
        if !d.is_empty() {
            deducidos.push(d);
            // Lo recién medido de la GPU sirve para despejar la CPU en la siguiente
            maq = Maquina::new(&maq.radiografia, Some(&calibracion::combinar(previa, &deducidos)));
        }
        std::thread::sleep(Duration::from_secs(3));
    }
    if deducidos.is_empty() {
        let error = pruebas
            .iter()
            .find_map(|p| match p {
                Valor::Mapa(m) => m.get("error").filter(|e| e.verdad()).map(Valor::texto_py),
                _ => None,
            })
            .unwrap_or_else(|| "Las pruebas no dieron medidas utilizables.".into());
        return Ok(Mapa::new().con("ok", false).con("pruebas", pruebas).con("error", error));
    }
    let valores = calibracion::combinar(previa, &deducidos);
    let mut sin_muestras = Mapa::new();
    for (k, v) in valores.iter() {
        if k != "muestras" {
            sin_muestras.poner(k.clone(), v.clone());
        }
    }
    avisar(Mapa::new().con("tipo", "calibrado").con("valores", sin_muestras));
    Ok(Mapa::new().con("ok", true).con("valores", valores).con("pruebas", pruebas))
}

/// El botón «Probar»: la recomendación con la máquina, y la comparación
pub fn probar_recomendacion(
    raiz: &Path,
    f: &Mapa,
    maq: &Maquina,
    perfil: &str,
    tirador: &str,
    avisar: &mut dyn FnMut(Mapa),
    cancelar: &Cancelar,
) -> Result<Mapa, Fallo> {
    let Some(_turno) = Turno::tomar() else { return Err(Fallo::Error("Ya hay una prueba o calibración en marcha.".into())) };
    let rec = calculadora::recomendar(f, maq, perfil, tirador).map_err(Fallo::Error)?;
    if rec.texto("veredicto") == Some("no_viable") {
        return Ok(Mapa::new().con("ok", false).con("error", rec.valor("motivo").clone()).con("recomendacion", rec));
    }
    let opciones = rec.mapa("opciones").cloned().unwrap_or_default();
    let mut r = probar(raiz, f, &opciones, avisar, cancelar)?;
    r.poner("recomendacion", rec.clone());
    if r.verdad("ok") {
        let prev = rec.mapa("estimacion").cloned().unwrap_or_default();
        let (tok, prev_tok) = (r.num_o("tok_s", 0.0), prev.num_o("tok_s", 0.0));
        let total = if r.verdad("total_gb") {
            let (t, p) = (r.num_o("total_gb", 0.0), prev.num_o("total_gb", 0.0));
            Valor::from(redondear_entero(100.0 * (t - p) / p.max(0.01)))
        } else {
            Valor::Nulo
        };
        r.poner(
            "desvio",
            Mapa::new().con("tok_s_pct", redondear_entero(100.0 * (tok - prev_tok) / prev_tok.max(0.1))).con("total_gb_pct", total),
        );
        r.poner("deducido", calibracion::deducir(f, &r, maq));
        let mut pedidas = Mapa::new();
        for (k, v) in opciones.iter() {
            if k == "num_ctx" || k == "num_gpu" {
                pedidas.poner(k.clone(), v.clone());
            }
        }
        let usadas = r.mapa("opciones").cloned().unwrap_or_default();
        if usadas != pedidas {
            r.poner(
                "aviso",
                format!(
                    "La recomendación no cupo tal cual: funcionó con {}. Se usará esto.",
                    Valor::Mapa(usadas).repr_py()
                ),
            );
        }
    }
    Ok(r)
}
