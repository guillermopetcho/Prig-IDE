//! Los recursos con el programa en marcha (la parte viva de `backend/recursos/termico.py`, `ritmo.py`,
//! `motor_suave.py` y `frio.py`): el monitor que lee los sensores cada 2 s mientras alguien mire o trabaje, el
//! gobernador térmico con su mundo, el modo suave (ritmo, fijador de núcleos y el controlador del motor) y el modo
//! frío (pausas por ciclos de los motores en RAM). Las decisiones están en `prig_recursos`; aquí, los hilos y el
//! cableado entre piezas, sin el GIL.
//!
//! Mientras el backend de Python conviva, lo aprendido y los ajustes viven en el almacén compartido: antes de usarlos
//! se toma lo que el otro proceso haya guardado (`sincronizar`).

use prig_recursos::almacen::{self, Almacen};
use prig_recursos::energia;
use prig_recursos::frio::{self, ControladorFrio, MundoFrio, Pausador};
use prig_recursos::motor_suave::{self, ControladorSuave, EstadoMotor, MundoSuave};
use prig_recursos::ritmo::{self, FijadorCpu, MundoFijador, ProcesoCpu, Ritmo, SistemaReal};
use prig_recursos::sensores;
use prig_recursos::termico::{self, Gobernador, Guardar, MundoGobernador, NucleoMonitor, Tramo};
use prig_recursos::valor::{Mapa, Valor};
use std::collections::{HashMap, HashSet};
use std::convert::Infallible;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

fn bloquear<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// `time.time()`
pub fn ahora() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

/// `time.monotonic()` (solo cuentan las diferencias)
fn monotono() -> f64 {
    static INICIO: OnceLock<Instant> = OnceLock::new();
    INICIO.get_or_init(Instant::now).elapsed().as_secs_f64()
}

// =========================================================================== cancelar

/// Un `threading.Event`: se pone para cancelar, y `esperar` vuelve antes si se pone
#[derive(Default)]
pub struct Cancelar {
    puesto: Mutex<bool>,
    cambio: Condvar,
}

impl Cancelar {
    pub fn new() -> Arc<Cancelar> {
        Arc::new(Cancelar::default())
    }

    pub fn poner(&self) {
        *bloquear(&self.puesto) = true;
        self.cambio.notify_all();
    }

    pub fn quitar(&self) {
        *bloquear(&self.puesto) = false;
    }

    pub fn puesto(&self) -> bool {
        *bloquear(&self.puesto)
    }

    /// `Event.wait(s)`: true si se puso (antes o durante la espera)
    pub fn esperar(&self, s: f64) -> bool {
        let limite = Instant::now() + Duration::from_secs_f64(s.max(0.0));
        let mut p = bloquear(&self.puesto);
        while !*p {
            let ahora = Instant::now();
            if ahora >= limite {
                return false;
            }
            p = self.cambio.wait_timeout(p, limite - ahora).unwrap_or_else(|e| e.into_inner()).0;
        }
        true
    }
}

// =========================================================================== monitor

/// Lee los sensores cada 2 s mientras alguien mire o haya trabajo en marcha (el `Monitor` de Python)
#[derive(Default)]
pub struct Monitor {
    n: Mutex<NucleoMonitor>,
    hilo: Mutex<bool>,
}

/// Mientras vive, el monitor sigue leyendo (`with monitor.trabajando()`)
pub struct Trabajando(&'static Monitor);

impl Drop for Trabajando {
    fn drop(&mut self) {
        bloquear(&self.0.n).trabajos -= 1;
    }
}

impl Monitor {
    fn muestrear(&self) -> Valor {
        let l = sensores::leer_sensores().a_valor();
        bloquear(&self.n).registrar(l.clone());
        l
    }

    fn asegurar(&'static self) {
        let mut hilo = bloquear(&self.hilo);
        bloquear(&self.n).consulta = ahora();
        if !*hilo {
            *hilo = true;
            let r = std::thread::Builder::new().name("prig-monitor-termico".into()).spawn(move || loop {
                self.muestrear();
                {
                    let mut h = bloquear(&self.hilo);
                    if !bloquear(&self.n).vivo(ahora()) {
                        *h = false;
                        return;
                    }
                }
                std::thread::sleep(Duration::from_secs_f64(termico::INTERVALO_S));
            });
            if r.is_err() {
                *hilo = false;
            }
        }
    }

    /// La última lectura si tiene menos de `max_edad` segundos; si no, una nueva
    pub fn lectura(&'static self, max_edad: f64) -> Valor {
        self.asegurar();
        let ultima = bloquear(&self.n).ultima.clone();
        match ultima {
            Some(u) if !(ahora() - Self::tomada(&u) > max_edad) => u,
            _ => self.muestrear(),
        }
    }

    fn tomada(l: &Valor) -> f64 {
        match l {
            Valor::Mapa(m) => m.num_o("tomada", f64::NAN),
            _ => f64::NAN,
        }
    }

    /// La GPU más caliente (Nulo si no hay)
    pub fn gpu(&'static self, max_edad: f64) -> Valor {
        termico::temp_gpu(&self.lectura(max_edad))
    }

    pub fn tendencia_gpu(&self, desde: Option<f64>) -> f64 {
        bloquear(&self.n).tendencia_gpu(desde)
    }

    pub fn historial(&self) -> Vec<Valor> {
        bloquear(&self.n).historial.iter().cloned().map(Valor::Mapa).collect()
    }

    pub fn trabajando(&'static self) -> Trabajando {
        bloquear(&self.n).trabajos += 1;
        self.asegurar();
        Trabajando(self)
    }
}

pub fn monitor() -> &'static Monitor {
    static M: OnceLock<Monitor> = OnceLock::new();
    M.get_or_init(Monitor::default)
}

// =========================================================================== recursos

/// El gobernador y lo que lo rodea (el `Gobernador` de Python con su ritmo, fijador, motor suave y modo frío)
pub struct Recursos {
    pub raiz: PathBuf,
    pub gob: Mutex<Gobernador>,
    pub ritmo: Mutex<Ritmo>,
    /// Las secciones del almacén con las que se construyeron el gobernador y el ritmo
    vistos: Mutex<(Mapa, Mapa)>,
    fijador: Mutex<FijadorCpu>,
    /// Para preguntar a Ollama qué modelos caben en la GPU (el fijador también lo hace dentro de `aplicar`)
    consultor: Mutex<FijadorCpu>,
    pub suave: Mutex<ControladorSuave>,
    motor_suave: Mutex<Mapa>,
    pub frio: Mutex<ControladorFrio>,
    pausador: Pausador,
    ram: Mutex<(f64, Vec<i32>)>,
    parar: Arc<Cancelar>,
    iniciado: Mutex<bool>,
}

fn almacen() -> Arc<Almacen> {
    almacen::global()
}

static GLOBAL: OnceLock<Recursos> = OnceLock::new();

/// Los recursos del proceso. `raiz`: la carpeta de Prig (la del primer uso).
pub fn recursos(raiz: &Path) -> &'static Recursos {
    GLOBAL.get_or_init(|| Recursos::new(raiz))
}

/// Para el cierre: deja todos los motores trabajando y devuelve el control
pub fn cerrar() {
    if let Some(r) = GLOBAL.get() {
        r.parar.poner();
        r.pausador.cerrar();
        motor_suave::quitar_control(&motor_suave::Rutas::desde_entorno(&r.raiz));
    }
}

fn url_ollama() -> String {
    crate::ollama::base_url()
}

impl Recursos {
    fn new(raiz: &Path) -> Recursos {
        let a = almacen();
        let (termico, ritmo) = (a.seccion("termico"), a.seccion("ritmo"));
        let url = url_ollama();
        Recursos {
            raiz: raiz.to_path_buf(),
            gob: Mutex::new(Gobernador::new(Some(&termico), true)),
            ritmo: Mutex::new(Ritmo::new(Some(&ritmo))),
            vistos: Mutex::new((termico, ritmo)),
            fijador: Mutex::new(FijadorCpu::new(&url)),
            consultor: Mutex::new(FijadorCpu::new(&url)),
            suave: Mutex::new(ControladorSuave::default()),
            motor_suave: Mutex::new(Mapa::new().con("ok", false).con("motivo", "Sin iniciar.")),
            frio: Mutex::new(ControladorFrio::default()),
            pausador: Pausador::new(frio::PERIODO_S),
            ram: Mutex::new((f64::NEG_INFINITY, Vec::new())),
            parar: Cancelar::new(),
            iniciado: Mutex::new(false),
        }
    }

    pub fn monitor(&self) -> &'static Monitor {
        monitor()
    }

    fn rutas_suave(&self) -> motor_suave::Rutas {
        motor_suave::Rutas::desde_entorno(&self.raiz)
    }

    /// Toma lo que el otro proceso de Prig haya guardado del gobernador y del ritmo (sin perder la pausa en curso
    /// ni el estado de la rampa)
    pub fn sincronizar(&self) {
        let a = almacen();
        let (termico, ritmo) = (a.seccion("termico"), a.seccion("ritmo"));
        let mut vistos = bloquear(&self.vistos);
        if vistos.0 != termico {
            let mut g = bloquear(&self.gob);
            if g.pausa.is_none() {
                let nuevo = Gobernador::new(Some(&termico), true);
                g.ajustes = nuevo.ajustes;
                vistos.0 = termico;
            }
        }
        if vistos.1 != ritmo {
            bloquear(&self.ritmo).ajustes = ritmo::ajustes_por_defecto().fusion(&ritmo);
            vistos.1 = ritmo;
        }
    }

    fn persistir(&self, g: Guardar) {
        let a = almacen();
        let texto = g.texto.unwrap_or_default();
        let _ = a.guardar_seccion("termico", g.ajustes, Some(("termico", &texto, g.datos.map(Valor::Mapa))));
        bloquear(&self.vistos).0 = a.seccion("termico");
    }

    // ----------------------------------------------------------------- arranque

    /// Lo que Python hacía al crear el gobernador (`_preparar_motor`), en un hilo: el motor suave según el ritmo,
    /// su controlador, reanudar motores congelados por un cierre brusco y el modo frío. `PRIG_SIN_MOTOR_SUAVE=1`
    /// (las pruebas): nada, porque escribiría en el archivo de control de un Prig abierto a la vez.
    pub fn iniciar(&'static self) {
        if std::env::var("PRIG_SIN_MOTOR_SUAVE").as_deref() == Ok("1") {
            return;
        }
        {
            let mut i = bloquear(&self.iniciado);
            if *i {
                return;
            }
            *i = true;
        }
        let _ = std::thread::Builder::new().name("prig-motor-suave-inicio".into()).spawn(move || {
            let _ = prig_recursos::nvml::disponible(); // la primera carga de NVML tarda ~2 s: mejor ahora
            self.aplicar_motor_suave();
            let _ = std::thread::Builder::new().name("prig-motor-suave".into()).spawn(move || {
                while !self.parar.esperar(motor_suave::PERIODO_S) {
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.paso_suave()));
                }
            });
            reanudar_huerfanos(&self.raiz);
            let _ = std::thread::Builder::new().name("prig-modo-frio".into()).spawn(move || {
                while !self.parar.esperar(frio::controlador::PERIODO_S) {
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.paso_frio()));
                }
                self.pausador.cerrar();
            });
        });
    }

    // ----------------------------------------------------------------- motor suave

    /// Instala o retira el envoltorio del motor según el modo suave esté activo o no
    pub fn aplicar_motor_suave(&self) -> Mapa {
        let r = self.rutas_suave();
        let activo = bloquear(&self.ritmo).activo();
        let m = if activo {
            motor_suave::instalar(&r)
        } else {
            motor_suave::desinstalar(&r).map(|m| m.con("motivo", "Modo suave apagado."))
        };
        let m = m.unwrap_or_else(|e| {
            let texto: String = e.to_string().chars().take(200).collect();
            Mapa::new().con("ok", false).con("motivo", texto)
        });
        *bloquear(&self.motor_suave) = m.clone();
        if !activo {
            motor_suave::quitar_control(&r);
        }
        m
    }

    fn leer_estado_motor(&self) -> Option<EstadoMotor> {
        motor_suave::leer_estado(&self.rutas_suave())
    }

    pub fn estado_motor(&self) -> Mapa {
        let motor = self.leer_estado_motor();
        let ms = bloquear(&self.motor_suave).clone();
        let generando = match &motor {
            Some(e) => motor_suave::generando(Some(e), ahora()),
            None => motor_suave::generando(self.leer_estado_motor().as_ref(), ahora()),
        };
        let fraccion = bloquear(&self.suave).ultimo.get("fraccion").cloned().unwrap_or(Valor::Nulo);
        Mapa::new()
            .con("instalado", ms.verdad("instalado"))
            .con("motivo", ms.get("motivo").cloned().unwrap_or(Valor::Nulo))
            .con("generando", generando)
            .con("estado", motor.map(|e| Valor::Mapa(e.mapa())).unwrap_or(Valor::Nulo))
            .con("fraccion", fraccion)
    }

    /// El modo suave actúa dentro del motor (y no hace falta pausar peticiones)
    pub fn dosifica_el_motor(&self) -> bool {
        bloquear(&self.ritmo).activo()
            && bloquear(&self.motor_suave).verdad("instalado")
            && motor_suave::generando(self.leer_estado_motor().as_ref(), ahora())
    }

    pub fn paso_suave(&self) -> Mapa {
        let mut mundo = MundoSuaveNativo { r: self };
        let mut c = std::mem::take(&mut *bloquear(&self.suave));
        let m = c.paso(&self.ritmo, &mut mundo);
        *bloquear(&self.suave) = c;
        m
    }

    // ----------------------------------------------------------------- ritmo y fijador

    /// `{**ritmo.estado(gpu), "motor": estado_motor()}`
    pub fn estado_ritmo(&self) -> Mapa {
        let temp = monitor().gpu(2.5).num();
        let e = bloquear(&self.ritmo).estado(temp, ahora, ritmo::nucleos_eficientes);
        e.con("motor", self.estado_motor())
    }

    /// `ritmo.fijar(cambios)` y guardarlo. Error: el de Python (un valor que no es un número).
    pub fn fijar_ritmo(&self, cambios: &Mapa) -> Result<Mapa, String> {
        self.sincronizar();
        let (ajustes, texto) = bloquear(&self.ritmo).fijar(cambios).map_err(|e| format!("{e:?}"))?;
        let a = almacen();
        let _ = a.guardar_seccion("ritmo", ajustes.clone(), Some(("ritmo", &texto, None)));
        bloquear(&self.vistos).1 = a.seccion("ritmo");
        Ok(ajustes)
    }

    pub fn aplicar_fijador(&self, forzar: bool) -> Mapa {
        let mut mundo = MundoFijadorNativo { r: self };
        let mut f = std::mem::take(&mut *bloquear(&self.fijador));
        let m = f.aplicar(&mut mundo, forzar);
        *bloquear(&self.fijador) = f;
        m
    }

    pub fn soltar_fijador(&self) {
        bloquear(&self.fijador).soltar();
    }

    fn modelos_en_gpu(&self) -> HashMap<String, bool> {
        bloquear(&self.consultor).modelos_en_gpu()
    }

    fn ram_en_eficientes(&self) -> bool {
        frio::por_defecto().fusion(&almacen().seccion("frio")).verdad("activo")
    }

    // ----------------------------------------------------------------- modo frío

    fn pid_moe() -> Option<i32> {
        crate::motor::global_si_hay().and_then(|m| m.pid()).map(|p| p as i32)
    }

    pub fn moe_generando() -> bool {
        crate::motor::global_si_hay().is_some_and(|m| m.generando())
    }

    /// Motores de Prig cuyo modelo NO cabe entero en la GPU (se revisa cada 3 s), fijados a los núcleos E; y el
    /// motor MoE, que sigue en los P y solo se pausa por ciclos
    pub fn motores_en_ram(&self) -> Vec<i32> {
        let t = ahora();
        {
            let c = bloquear(&self.ram);
            if t - c.0 < 3.0 {
                return c.1.clone();
            }
        }
        let en_gpu = self.modelos_en_gpu();
        let mut pids: Vec<i32> = frio::motores_de_prig(&self.raiz.to_string_lossy())
            .into_iter()
            .filter(|m| m.blob.as_ref().is_some_and(|b| en_gpu.get(b) == Some(&false)))
            .map(|m| m.pid)
            .collect();
        let previos: HashSet<i32> = bloquear(&self.ram).1.iter().copied().collect();
        let eficientes = ritmo::nucleos_eficientes();
        if !eficientes.is_empty() {
            for pid in pids.iter().filter(|p| !previos.contains(p)) {
                ritmo::fijar_proceso(*pid, &eficientes);
            }
        }
        if let Some(moe) = Self::pid_moe() {
            if !pids.contains(&moe) {
                pids.push(moe);
            }
        }
        pids.sort_unstable();
        *bloquear(&self.ram) = (t, pids.clone());
        pids
    }

    fn holgura_frio(pids: &[i32]) -> f64 {
        match Self::pid_moe() {
            Some(moe) if pids == [moe] && frio::turbo_apagado() => frio::HOLGURA_MOE_SIN_TURBO_C,
            _ => 0.0,
        }
    }

    pub fn paso_frio(&self) -> Mapa {
        let mut mundo = MundoFrioNativo { r: self };
        let mut c = std::mem::take(&mut *bloquear(&self.frio));
        let m = match c.paso(&mut mundo) {
            Ok(m) => m,
            Err(e) => match e {},
        };
        *bloquear(&self.frio) = c;
        m
    }

    /// Lo que enseña el panel del modo frío
    pub fn estado_frio(&self, rutas: &energia::Rutas) -> Mapa {
        let ajustes = frio::por_defecto().fusion(&almacen().seccion("frio"));
        let control = bloquear(&self.frio).ultimo.clone();
        let eficientes = ritmo::nucleos_eficientes();
        let hilos = if eficientes.is_empty() { Valor::Nulo } else { Valor::from(eficientes.len()) };
        let vatios = match ajustes.get("vatios") {
            Some(v) if v.verdad() => v.num().map(|n| n.trunc() as i64).unwrap_or(20),
            _ => 20,
        };
        Mapa::new()
            .con("ajustes", ajustes)
            .con("control", control)
            .con("nucleos_eficientes", Valor::Lista(eficientes.into_iter().map(Valor::from).collect()))
            .con("hilos", hilos)
            .con("energia", energia::estado(rutas))
            .con("vatios", vatios)
    }

    // ----------------------------------------------------------------- gobernador

    /// `gob.estado()` con el ritmo y el motor
    pub fn estado_gobernador(&self) -> Mapa {
        self.sincronizar();
        let ritmo = self.estado_ritmo();
        bloquear(&self.gob).estado(ritmo)
    }

    pub fn fijar_limite(&self, limite: f64) -> Result<(), String> {
        self.sincronizar();
        let g = bloquear(&self.gob).fijar_limite(limite)?;
        if let Some(g) = g {
            self.persistir(g);
        }
        Ok(())
    }

    pub fn olvidar(&self) {
        self.sincronizar();
        let g = bloquear(&self.gob).olvidar();
        if let Some(g) = g {
            self.persistir(g);
        }
    }

    pub fn limite_y_reanudar(&self) -> (f64, f64) {
        self.sincronizar();
        let g = bloquear(&self.gob);
        (g.limite(), g.reanudar())
    }

    /// El mundo del gobernador para una generación (cancelar y avisos opcionales)
    pub fn mundo<'a, 'b>(&'a self, cancelar: Option<&'a Cancelar>, avisar: Option<&'b mut (dyn FnMut(Mapa) + 'b)>) -> MundoNativo<'a, 'b> {
        MundoNativo { r: self, cancelar, avisar, trabajo: None }
    }

    pub fn empezar_tramo(&self) -> Tramo {
        self.sincronizar();
        let Ok(t) = Gobernador::empezar_tramo(&mut self.mundo(None, None));
        t
    }

    pub fn debe_cortar(&self, tramo: &mut Tramo) -> Option<&'static str> {
        let g = bloquear(&self.gob).clone();
        let Ok(m) = g.debe_cortar(tramo, &mut self.mundo(None, None));
        m
    }

    /// `enfriar`: con «ritmo», la pausa corta del modo suave
    pub fn enfriar<'a, 'b>(
        &'a self,
        motivo: &str,
        cancelar: Option<&'a Cancelar>,
        avisar: Option<&'b mut (dyn FnMut(Mapa) + 'b)>,
        objetivo: Option<f64>,
        tramo: Option<&mut Tramo>,
    ) -> f64 {
        let mut mundo = self.mundo(cancelar, avisar);
        if motivo == "ritmo" {
            return match tramo {
                Some(t) => {
                    let Ok(s) = Gobernador::descansar(t, &mut mundo);
                    s
                }
                None => 0.0,
            };
        }
        let Ok(s) = Gobernador::enfriar(&self.gob, motivo, objetivo, termico::ESPERA_MAXIMA_S, tramo, &mut mundo);
        s
    }

    /// Entre pasos: si la GPU no está a la temperatura de reanudar, se espera
    pub fn antes_de_trabajar<'a, 'b>(&'a self, cancelar: Option<&'a Cancelar>, avisar: Option<&'b mut (dyn FnMut(Mapa) + 'b)>) -> f64 {
        self.sincronizar();
        let temp = monitor().gpu(2.5);
        let reanudar = bloquear(&self.gob).reanudar();
        if temp.es_nulo() || temp.num().unwrap_or(f64::NAN) <= reanudar {
            return 0.0;
        }
        self.enfriar("antes_de_paso", cancelar, avisar, None, None)
    }

    pub fn terminar_tramo(&self, tramo: &Tramo, motivo: Option<&str>) {
        let Ok(segundos) = termico::segundos_para_terminar::<Infallible>(tramo, motivo, || Ok(ahora()));
        let g = bloquear(&self.gob).terminar_tramo(tramo, motivo, segundos);
        if let Some(g) = g {
            self.persistir(g);
        }
    }
}

/// Al arrancar: si un cierre brusco dejó congelado un motor de Prig, se reanuda
pub fn reanudar_huerfanos(raiz: &Path) -> usize {
    frio::motores_de_prig(&raiz.to_string_lossy())
        .into_iter()
        .filter(|m| m.estado == "stopped" || m.estado == "tracing-stop")
        .filter(|m| frio::Proceso::new(m.pid).senal(libc::SIGCONT))
        .count()
}

// =========================================================================== mundos

/// El mundo del gobernador: el monitor, el ritmo, el fijador, el motor suave y el MoE de este proceso
pub struct MundoNativo<'a, 'b> {
    r: &'a Recursos,
    cancelar: Option<&'a Cancelar>,
    avisar: Option<&'b mut (dyn FnMut(Mapa) + 'b)>,
    trabajo: Option<Trabajando>,
}

impl MundoGobernador for MundoNativo<'_, '_> {
    type Error = Infallible;

    fn ahora(&mut self) -> Result<f64, Infallible> {
        Ok(ahora())
    }

    fn gpu(&mut self, max_edad: Option<f64>) -> Result<Valor, Infallible> {
        Ok(monitor().gpu(max_edad.unwrap_or(2.5)))
    }

    fn tendencia_gpu(&mut self, desde: f64) -> Result<f64, Infallible> {
        Ok(monitor().tendencia_gpu(Some(desde)))
    }

    fn trabajando_entrar(&mut self) -> Result<(), Infallible> {
        self.trabajo = Some(monitor().trabajando());
        Ok(())
    }

    fn trabajando_salir(&mut self) -> Result<(), Infallible> {
        self.trabajo = None;
        Ok(())
    }

    fn dosifica_el_motor(&mut self) -> Result<bool, Infallible> {
        Ok(self.r.dosifica_el_motor())
    }

    fn moe_generando(&mut self) -> Result<bool, Infallible> {
        Ok(Recursos::moe_generando())
    }

    fn ritmo_marcar(&mut self) -> Result<(), Infallible> {
        bloquear(&self.r.ritmo).marcar(ahora());
        Ok(())
    }

    fn ritmo_activo(&mut self) -> Result<bool, Infallible> {
        Ok(bloquear(&self.r.ritmo).activo())
    }

    fn ritmo_cpu_eficiente(&mut self) -> Result<bool, Infallible> {
        Ok(bloquear(&self.r.ritmo).ajustes.verdad("cpu_eficiente"))
    }

    fn ritmo_pausa(&mut self, segundos: f64, temp: &Valor) -> Result<Option<f64>, Infallible> {
        Ok(bloquear(&self.r.ritmo).pausa(segundos, temp, ahora, ahora))
    }

    fn aplicar_fijador(&mut self) {
        self.r.aplicar_fijador(false);
    }

    fn esperar(&mut self, s: f64) -> Result<bool, Infallible> {
        Ok(match self.cancelar {
            Some(c) => c.esperar(s),
            None => {
                std::thread::sleep(Duration::from_secs_f64(s.max(0.0)));
                false
            }
        })
    }

    fn hay_avisos(&mut self) -> bool {
        self.avisar.is_some()
    }

    fn avisar(&mut self, evento: Mapa) -> Result<(), Infallible> {
        if let Some(a) = self.avisar.as_mut() {
            a(evento);
        }
        Ok(())
    }

    fn persistir(&mut self, g: Guardar) -> Result<(), Infallible> {
        self.r.persistir(g);
        Ok(())
    }
}

struct MundoSuaveNativo<'a> {
    r: &'a Recursos,
}

impl MundoSuave for MundoSuaveNativo<'_> {
    fn leer_estado(&mut self) -> Option<EstadoMotor> {
        self.r.leer_estado_motor()
    }

    fn generando(&mut self, estado: Option<&EstadoMotor>) -> bool {
        match estado {
            Some(e) => motor_suave::generando(Some(e), ahora()),
            None => motor_suave::generando(self.r.leer_estado_motor().as_ref(), ahora()),
        }
    }

    fn gpu(&mut self, max_edad: f64) -> Option<Valor> {
        Some(monitor().gpu(max_edad)).filter(|v| !v.es_nulo())
    }

    fn ahora(&mut self) -> f64 {
        ahora()
    }

    fn escribir_control(&mut self, fraccion: f64, tramo: f64) {
        motor_suave::escribir_control(&self.r.rutas_suave(), fraccion, tramo, ahora());
    }

    fn quitar_control(&mut self) {
        motor_suave::quitar_control(&self.r.rutas_suave());
    }
}

struct MundoFijadorNativo<'a> {
    r: &'a Recursos,
}

impl MundoFijador for MundoFijadorNativo<'_> {
    fn nucleos_eficientes(&mut self) -> Vec<i64> {
        ritmo::nucleos_eficientes()
    }

    fn ahora(&mut self) -> f64 {
        ahora()
    }

    fn modelos_en_gpu(&mut self) -> HashMap<String, bool> {
        self.r.modelos_en_gpu()
    }

    fn ram_en_eficientes(&mut self) -> bool {
        self.r.ram_en_eficientes()
    }

    fn afinidad_propia(&mut self) -> Vec<i64> {
        ritmo::afinidad_propia()
    }

    fn uid(&mut self) -> Option<u32> {
        Some(SistemaReal::uid())
    }

    fn procesos(&mut self) -> Vec<ProcesoCpu> {
        SistemaReal::procesos()
    }

    fn hilos(&mut self, pid: i32) -> Option<Vec<i32>> {
        SistemaReal::hilos(pid)
    }

    fn fijar(&mut self, pid: i32, nucleos: &[i64]) -> bool {
        ritmo::fijar_afinidad(pid, nucleos).is_ok()
    }

    fn pids(&mut self) -> HashSet<i32> {
        ritmo::pids()
    }
}

struct MundoFrioNativo<'a> {
    r: &'a Recursos,
}

impl MundoFrio for MundoFrioNativo<'_> {
    type Error = Infallible;

    fn ajustes(&mut self) -> Result<Mapa, Infallible> {
        Ok(almacen().seccion("frio"))
    }

    fn motores_en_ram(&mut self) -> Result<Vec<i32>, Infallible> {
        Ok(self.r.motores_en_ram())
    }

    fn tiempo_cpu(&mut self, pid: i32) -> Result<Option<f64>, Infallible> {
        Ok(frio::tiempo_cpu(pid))
    }

    fn reloj(&mut self) -> Result<f64, Infallible> {
        Ok(monotono())
    }

    fn leer_temp(&mut self) -> Result<Valor, Infallible> {
        Ok(sensores::temp_cpu_rapida(Path::new("/")).map(Valor::Real).unwrap_or(Valor::Nulo))
    }

    fn holgura(&mut self, pids: &[i32]) -> Result<f64, Infallible> {
        Ok(Recursos::holgura_frio(pids))
    }

    fn sin_turbo(&mut self) -> Result<bool, Infallible> {
        Ok(frio::turbo_apagado())
    }

    fn fijar(&mut self, pids: &[i32], fraccion: f64) -> Result<(), Infallible> {
        let conjunto: HashSet<i32> = pids.iter().copied().collect();
        self.r.pausador.fijar(&conjunto, fraccion);
        Ok(())
    }
}
