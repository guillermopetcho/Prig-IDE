//! Modo frío (backend/recursos/frio.py): congelar (SIGSTOP) y reanudar (SIGCONT) los motores de los modelos que
//! viven en RAM una parte de cada ciclo de 50 ms, para que la CPU no se caliente.
//!
//! El pausador de Python corría en un hilo con el GIL: si otro hilo de Prig estaba trabajando, el tramo de trabajo de
//! 6 ms se estiraba hasta 11,2 ms (medido, docs/informe-rust-moe.md §2). Aquí corre en un hilo propio, con plazos
//! absolutos (el ciclo no se corre) y las señales por pidfd (nunca llegan a otro proceso que reutilice el número).

use std::collections::hash_map::Entry;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

pub const PERIODO_S: f64 = 0.05;
pub const BANDA_C: f64 = 8.0;
pub const MINIMO: f64 = 0.12;

// =========================================================================== señales seguras

/// Un proceso concreto. Las señales van por pidfd: si termina y el sistema reutiliza su número para otro
/// programa, a ese otro no le llega nada (`frio.Proceso`).
#[derive(Debug)]
pub struct Proceso {
    pub pid: i32,
    fd: Option<i32>,
    pub vivo: bool,
}

fn pidfd_open(pid: i32) -> Option<i32> {
    // SAFETY: la llamada al sistema solo lee sus argumentos; devuelve un descriptor o -1
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if fd >= 0 {
        Some(fd as i32)
    } else {
        None
    }
}

impl Proceso {
    pub fn new(pid: i32) -> Proceso {
        let fd = if pid > 0 { pidfd_open(pid) } else { None };
        Proceso { pid, vivo: fd.is_some(), fd }
    }

    /// Manda una señal (0 solo comprueba que siga vivo). false si ya no existe.
    pub fn senal(&mut self, sig: i32) -> bool {
        if !self.vivo {
            return false;
        }
        let Some(fd) = self.fd else {
            self.vivo = false;
            return false;
        };
        // SAFETY: fd es un pidfd propio y abierto; info nulo es válido para pidfd_send_signal
        let r = unsafe { libc::syscall(libc::SYS_pidfd_send_signal, fd, sig, std::ptr::null::<libc::siginfo_t>(), 0) };
        if r == 0 {
            true
        } else {
            self.vivo = false;
            false
        }
    }

    pub fn cerrar(&mut self) {
        if let Some(fd) = self.fd.take() {
            // SAFETY: el descriptor es nuestro y no se usa después
            unsafe {
                libc::close(fd);
            }
        }
    }
}

impl Drop for Proceso {
    fn drop(&mut self) {
        self.cerrar();
    }
}

/// Segundos de CPU usados por un proceso (usuario + sistema, todos sus hilos), de /proc/<pid>/stat
pub fn tiempo_cpu(pid: i32) -> Option<f64> {
    let texto = fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let campos: Vec<&str> = texto.rsplit_once(')')?.1.split_whitespace().collect();
    let utime: f64 = campos.get(11)?.parse().ok()?;
    let stime: f64 = campos.get(12)?.parse().ok()?;
    // SAFETY: sysconf no tiene efectos
    let tick = unsafe { libc::sysconf(libc::_SC_CLK_TCK) };
    Some((utime + stime) / if tick > 0 { tick as f64 } else { 100.0 })
}

/// ¿Está apagado el turbo de la CPU? (intel_pstate/no_turbo o cpufreq/boost; sin root)
pub fn turbo_apagado() -> bool {
    for (ruta, apagado) in [("/sys/devices/system/cpu/intel_pstate/no_turbo", "1"), ("/sys/devices/system/cpu/cpufreq/boost", "0")] {
        if let Ok(v) = fs::read_to_string(ruta) {
            return v.trim() == apagado;
        }
    }
    false
}

/// `ControladorFrio.fraccion_objetivo`: sin pausas por debajo de objetivo − BANDA, el mínimo en el objetivo
pub fn fraccion_objetivo(temp: Option<f64>, objetivo: f64) -> f64 {
    match temp {
        None => 1.0,
        Some(t) if t <= objetivo - BANDA_C => 1.0,
        Some(t) if t >= objetivo => MINIMO,
        Some(t) => MINIMO + (1.0 - MINIMO) * (objetivo - t) / BANDA_C,
    }
}

// =========================================================================== el pausador

struct Interno {
    procesos: HashMap<i32, Proceso>,
    fraccion: f64,
    congelados: HashSet<i32>,
    parar: bool,
}

struct Compartido {
    interno: Mutex<Interno>,
    despertar: Condvar,
}

impl Compartido {
    /// Duerme hasta `plazo` o hasta que se pida parar (true). Con plazos absolutos el ciclo no se corre.
    fn esperar_hasta(&self, plazo: Instant) -> bool {
        let mut g = self.interno.lock().unwrap();
        loop {
            if g.parar {
                return true;
            }
            let ahora = Instant::now();
            if ahora >= plazo {
                return false;
            }
            g = self.despertar.wait_timeout(g, plazo - ahora).unwrap().0;
        }
    }

    fn todos(&self, sig: i32) {
        let mut g = self.interno.lock().unwrap();
        let Interno { procesos, congelados, .. } = &mut *g;
        for p in procesos.values_mut() {
            if p.senal(sig) {
                if sig == libc::SIGSTOP {
                    congelados.insert(p.pid);
                } else {
                    congelados.remove(&p.pid);
                }
            }
        }
    }
}

/// Trabaja `fraccion` de cada ciclo de `periodo` y congela los motores el resto (`frio.Pausador`)
pub struct Pausador {
    pub periodo: Duration,
    compartido: Arc<Compartido>,
    hilo: Mutex<Option<JoinHandle<()>>>,
}

impl Pausador {
    pub fn new(periodo_s: f64) -> Pausador {
        Pausador {
            periodo: Duration::from_secs_f64(periodo_s.max(0.001)),
            compartido: Arc::new(Compartido {
                interno: Mutex::new(Interno { procesos: HashMap::new(), fraccion: 1.0, congelados: HashSet::new(), parar: false }),
                despertar: Condvar::new(),
            }),
            hilo: Mutex::new(None),
        }
    }

    pub fn fraccion(&self) -> f64 {
        self.compartido.interno.lock().unwrap().fraccion
    }

    pub fn pids(&self) -> Vec<i32> {
        let mut v: Vec<i32> = self.compartido.interno.lock().unwrap().procesos.keys().copied().collect();
        v.sort_unstable();
        v
    }

    pub fn congelados(&self) -> Vec<i32> {
        let mut v: Vec<i32> = self.compartido.interno.lock().unwrap().congelados.iter().copied().collect();
        v.sort_unstable();
        v
    }

    pub fn fijar(&self, pids: &HashSet<i32>, fraccion: f64) {
        let arrancar = {
            let mut g = self.compartido.interno.lock().unwrap();
            let fuera: Vec<i32> = g.procesos.keys().filter(|p| !pids.contains(p)).copied().collect();
            for pid in fuera {
                if let Some(mut p) = g.procesos.remove(&pid) {
                    p.senal(libc::SIGCONT);
                    p.cerrar();
                }
                g.congelados.remove(&pid);
            }
            for &pid in pids {
                if let Entry::Vacant(hueco) = g.procesos.entry(pid) {
                    let p = Proceso::new(pid);
                    if p.vivo {
                        hueco.insert(p);
                    }
                }
            }
            g.fraccion = fraccion.clamp(0.0, 1.0);
            !g.procesos.is_empty() && g.fraccion < 0.995
        };
        if arrancar {
            self.arrancar();
        }
    }

    fn arrancar(&self) {
        let mut hilo = self.hilo.lock().unwrap();
        if hilo.as_ref().map(|h| !h.is_finished()).unwrap_or(false) {
            return;
        }
        self.compartido.interno.lock().unwrap().parar = false;
        let c = self.compartido.clone();
        let periodo = self.periodo;
        *hilo = Some(
            std::thread::Builder::new()
                .name("prig-modo-frio-pausas".into())
                .spawn(move || bucle(c, periodo))
                .expect("hilo del modo frío"),
        );
    }

    /// Para las pausas y deja todos los motores trabajando
    pub fn cerrar(&self) {
        {
            let mut g = self.compartido.interno.lock().unwrap();
            g.parar = true;
        }
        self.compartido.despertar.notify_all();
        if let Some(h) = self.hilo.lock().unwrap().take() {
            let _ = h.join();
        }
        self.compartido.todos(libc::SIGCONT);
        let mut g = self.compartido.interno.lock().unwrap();
        for p in g.procesos.values_mut() {
            p.cerrar();
        }
        g.procesos.clear();
        g.congelados.clear();
    }
}

impl Drop for Pausador {
    fn drop(&mut self) {
        self.cerrar();
    }
}

fn bucle(c: Arc<Compartido>, periodo: Duration) {
    let mut inicio = Instant::now();
    loop {
        let (fraccion, hay) = {
            let g = c.interno.lock().unwrap();
            if g.parar {
                break;
            }
            (g.fraccion, !g.procesos.is_empty())
        };
        if !hay || fraccion >= 0.995 {
            if c.esperar_hasta(Instant::now() + periodo * 4) {
                break;
            }
            inicio = Instant::now();
            continue;
        }
        // Si el ciclo se atrasó (el sistema no nos dio la CPU), se vuelve a empezar desde ahora
        let ahora = Instant::now();
        if ahora.duration_since(inicio) > periodo {
            inicio = ahora;
        }
        if c.esperar_hasta(inicio + periodo.mul_f64(fraccion)) {
            break;
        }
        c.todos(libc::SIGSTOP);
        let parar = c.esperar_hasta(inicio + periodo);
        c.todos(libc::SIGCONT); // pase lo que pase, se reanuda
        if parar {
            break;
        }
        inicio += periodo;
    }
    c.todos(libc::SIGCONT);
}

// =========================================================================== los motores de Prig

/// Los estados de psutil (`proceso.status()`), desde la letra de /proc/<pid>/stat
fn estado_psutil(letra: &str) -> &'static str {
    match letra {
        "R" => "running",
        "S" => "sleeping",
        "D" => "disk-sleep",
        "T" => "stopped",
        "t" => "tracing-stop",
        "Z" => "zombie",
        "X" | "x" => "dead",
        "K" => "wake-kill",
        "W" => "waking",
        "P" => "parked",
        "I" => "idle",
        _ => "?",
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Motor {
    pub pid: i32,
    pub blob: Option<String>,
    pub estado: String,
}

/// `motores_de_prig`: los llama-server de Prig del usuario (los que están bajo `raiz_prig`), con el blob de pesos
/// y su estado. Leído de /proc, sin psutil.
pub fn motores_de_prig(raiz_prig: &str) -> Vec<Motor> {
    // SAFETY: getuid no tiene efectos
    let yo = unsafe { libc::getuid() };
    let mut salida = Vec::new();
    let Ok(entradas) = fs::read_dir("/proc") else { return salida };
    let mut pids: Vec<i32> = entradas.flatten().filter_map(|e| e.file_name().to_str()?.parse().ok()).collect();
    pids.sort_unstable();
    for pid in pids {
        let Ok(crudo) = fs::read(format!("/proc/{pid}/cmdline")) else { continue };
        let cmd: Vec<String> = crudo.split(|b| *b == 0).filter(|s| !s.is_empty()).map(|s| String::from_utf8_lossy(s).into_owned()).collect();
        let Some(primero) = cmd.first() else { continue };
        let uid_real = fs::read_to_string(format!("/proc/{pid}/status"))
            .ok()
            .and_then(|t| t.lines().find(|l| l.starts_with("Uid:")).and_then(|l| l.split_whitespace().nth(1)?.parse::<u32>().ok()));
        if uid_real.is_some_and(|u| u != yo) {
            continue;
        }
        let base = primero.rsplit('/').next().unwrap_or(primero);
        if !base.contains("llama-server") || !cmd.iter().any(|a| a == "--model") {
            continue;
        }
        let real = fs::canonicalize(primero).map(|p| p.to_string_lossy().into_owned()).unwrap_or_else(|_| primero.clone());
        if !real.starts_with(&format!("{}/", raiz_prig.trim_end_matches('/'))) {
            continue; // solo el motor de Prig
        }
        // re.search(r"sha256-([0-9a-f]{64})", " ".join(cmd)): la primera aparición que sigue con 64 hexadecimales
        let unido = cmd.join(" ");
        let blob = unido.match_indices("sha256-").find_map(|(i, _)| {
            let hex: String = unido[i + 7..].chars().take(64).collect();
            (hex.len() == 64 && hex.chars().all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c))).then_some(hex)
        });
        let estado = fs::read_to_string(format!("/proc/{pid}/stat"))
            .ok()
            .and_then(|t| t.rsplit_once(')').and_then(|(_, r)| r.split_whitespace().next().map(|s| estado_psutil(s).to_string())))
            .unwrap_or_else(|| "?".into());
        salida.push(Motor { pid, blob, estado });
    }
    salida
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::{Command, Stdio};

    fn ocupado() -> std::process::Child {
        Command::new("sh").args(["-c", "while :; do :; done"]).stdout(Stdio::null()).spawn().unwrap()
    }

    fn estado(pid: u32) -> String {
        let t = fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
        t.rsplit_once(')').unwrap().1.split_whitespace().next().unwrap().to_string()
    }

    #[test]
    fn fraccion_objetivo_como_python() {
        assert_eq!(fraccion_objetivo(None, 60.0), 1.0);
        assert_eq!(fraccion_objetivo(Some(50.0), 60.0), 1.0);
        assert_eq!(fraccion_objetivo(Some(61.0), 60.0), MINIMO);
        assert!((fraccion_objetivo(Some(56.0), 60.0) - (MINIMO + (1.0 - MINIMO) * 0.5)).abs() < 1e-12);
    }

    #[test]
    fn al_50_por_ciento_usa_la_mitad_y_no_queda_congelado() {
        let mut p = ocupado();
        let pid = p.id() as i32;
        let pausador = Pausador::new(PERIODO_S);
        std::thread::sleep(Duration::from_millis(300));
        let (t0, c0) = (Instant::now(), tiempo_cpu(pid).unwrap());
        pausador.fijar(&HashSet::from([pid]), 0.5);
        std::thread::sleep(Duration::from_secs(2));
        let uso = (tiempo_cpu(pid).unwrap() - c0) / t0.elapsed().as_secs_f64();
        assert!(uso > 0.3 && uso < 0.7, "uso {uso}");
        pausador.cerrar();
        std::thread::sleep(Duration::from_millis(100));
        assert_ne!(estado(p.id()), "T");
        p.kill().unwrap();
        p.wait().unwrap();
    }

    #[test]
    fn un_proceso_terminado_no_recibe_nada() {
        let mut p = Command::new("sleep").arg("30").spawn().unwrap();
        let mut proc = Proceso::new(p.id() as i32);
        p.kill().unwrap();
        p.wait().unwrap();
        assert!(!proc.senal(0));
    }
}

// =========================================================================== el controlador

pub const POR_DEFECTO_ACTIVO: bool = true;
pub const POR_DEFECTO_OBJETIVO_C: f64 = 60.0; // temperatura de la CPU a la que se tiende
pub const INICIO: f64 = 0.30; // tras un rato sin trabajar, la próxima respuesta arranca suave (con turbo)
pub const ACTIVIDAD: f64 = 0.5; // núcleos (descontando las pausas) que cuentan como «generando»
/// Motor MoE con el turbo apagado: las pausas le cuestan casi la mitad de la velocidad y ahorran poco calor (medido:
/// con pausas a 60 °C, 22,8 tok/s; sin pausas, 38,4 tok/s y la CPU a 57-63 °C). Con esta holgura solo se le pausa
/// como protección, por encima del objetivo.
pub const HOLGURA_MOE_SIN_TURBO_C: f64 = 8.0;

pub mod controlador {
    pub const PERIODO_S: f64 = 1.0;
    pub const SUBIDA: f64 = 0.03;
    pub const BAJADA: f64 = 0.08;
    pub const SUAVIZADO: f64 = 0.3;
}

use crate::valor::{redondear, Mapa, Valor};

pub fn por_defecto() -> Mapa {
    Mapa::new().con("activo", POR_DEFECTO_ACTIVO).con("objetivo_c", POR_DEFECTO_OBJETIVO_C)
}

/// Lo que el controlador lee y manda fuera de sí. `Error` es el de quien lo implementa: se propaga.
pub trait MundoFrio {
    type Error;
    fn ajustes(&mut self) -> Result<Mapa, Self::Error>;
    /// Los motores en RAM, en el orden en que se recorren (el de un set de Python)
    fn motores_en_ram(&mut self) -> Result<Vec<i32>, Self::Error>;
    fn tiempo_cpu(&mut self, pid: i32) -> Result<Option<f64>, Self::Error>;
    fn reloj(&mut self) -> Result<f64, Self::Error>;
    fn leer_temp(&mut self) -> Result<Valor, Self::Error>;
    fn holgura(&mut self, pids: &[i32]) -> Result<f64, Self::Error>;
    fn sin_turbo(&mut self) -> Result<bool, Self::Error>;
    fn fijar(&mut self, pids: &[i32], fraccion: f64) -> Result<(), Self::Error>;
}

fn min_py(a: f64, b: f64) -> f64 {
    if b < a {
        b
    } else {
        a
    }
}

fn max_py(a: f64, b: f64) -> f64 {
    if b > a {
        b
    } else {
        a
    }
}

/// Cada segundo: temperatura de la CPU → parte de cada ciclo en que trabajan los motores de los modelos que viven en
/// RAM. Termostato proporcional con media exponencial de la temperatura y cambios limitados por paso, para que la
/// potencia cambie en rampas y la temperatura no oscile.
#[derive(Debug, Default)]
pub struct ControladorFrio {
    pub generaba: bool,
    pub fraccion: Option<f64>,
    pub temp_media: Option<Valor>,
    cpu_previa: Vec<(i32, f64, f64)>,
    pub ultimo: Mapa,
}

impl ControladorFrio {
    /// Núcleos que usarían los motores sin pausas (lo medido, descontando la fracción)
    fn actividad<M: MundoFrio>(&mut self, pids: &[i32], mundo: &mut M) -> Result<Option<f64>, M::Error> {
        let ahora = mundo.reloj()?;
        let (mut total, mut hubo) = (0.0, false);
        let mut nuevos = Vec::new();
        for &pid in pids {
            let Some(t) = mundo.tiempo_cpu(pid)? else { continue };
            nuevos.push((pid, ahora, t));
            if let Some(&(_, t0, c0)) = self.cpu_previa.iter().find(|(p, _, _)| *p == pid) {
                if ahora > t0 {
                    total += (t - c0) / (ahora - t0);
                    hubo = true;
                }
            }
        }
        self.cpu_previa = nuevos;
        if !hubo {
            return Ok(None);
        }
        let f = match self.fraccion {
            Some(f) if f != 0.0 => f,
            _ => 1.0,
        };
        Ok(Some(total / max_py(f, MINIMO)))
    }

    pub fn paso<M: MundoFrio>(&mut self, mundo: &mut M) -> Result<Mapa, M::Error> {
        let a = por_defecto().fusion(&mundo.ajustes()?);
        let objetivo_base = a.num_o("objetivo_c", f64::NAN);
        let pids = if a.verdad("activo") { mundo.motores_en_ram()? } else { Vec::new() };
        if pids.is_empty() {
            mundo.fijar(&[], 1.0)?;
            self.fraccion = None;
            self.temp_media = None;
            self.cpu_previa.clear();
            self.ultimo = Mapa::new()
                .con("activo", a.verdad("activo"))
                .con("en_ram", 0)
                .con("fraccion", Valor::Nulo)
                .con("objetivo_c", objetivo_base);
            return Ok(self.ultimo.clone());
        }
        let actividad = self.actividad(&pids, mundo)?;
        let generando = actividad.is_some_and(|a| a >= ACTIVIDAD);
        let mut temp = Valor::Nulo;
        if generando {
            // Los sensores solo se leen con el motor trabajando: en reposo no cuesta nada
            temp = mundo.leer_temp()?;
            if !temp.es_nulo() {
                self.temp_media = Some(match &self.temp_media {
                    None => temp.clone(),
                    Some(m) => Valor::Real(
                        controlador::SUAVIZADO * temp.num().unwrap_or(f64::NAN)
                            + (1.0 - controlador::SUAVIZADO) * m.num().unwrap_or(f64::NAN),
                    ),
                });
            }
        }
        let objetivo_c = objetivo_base + mundo.holgura(&pids)?;
        let objetivo = fraccion_objetivo(self.temp_media.as_ref().and_then(Valor::num), objetivo_c);
        // La rampa desde el 30 % evita el salto del turbo (50 → 90 °C en segundos). Sin turbo no hay salto: cada
        // respuesta arranca con lo que permite la temperatura de ese momento.
        let sin_turbo = mundo.sin_turbo()?;
        let fraccion = if !generando {
            self.temp_media = None;
            if sin_turbo { 1.0 } else { INICIO }
        } else {
            match self.fraccion {
                Some(f) if !(sin_turbo && !self.generaba) => {
                    min_py(f + controlador::SUBIDA, max_py(f - controlador::BAJADA, objetivo))
                }
                _ => {
                    if sin_turbo {
                        objetivo
                    } else {
                        min_py(objetivo, INICIO)
                    }
                }
            }
        };
        self.generaba = generando;
        let fraccion = redondear(fraccion, 3);
        self.fraccion = Some(fraccion);
        mundo.fijar(&pids, fraccion)?;
        let media = match &self.temp_media {
            None => Valor::Nulo,
            Some(Valor::Entero(n)) => Valor::Entero(*n), // round(int, 1) de Python es el mismo int
            Some(v) => Valor::Real(redondear(v.num().unwrap_or(f64::NAN), 1)),
        };
        self.ultimo = Mapa::new()
            .con("activo", true)
            .con("en_ram", pids.len())
            .con("generando", generando)
            .con("temp", temp)
            .con("temp_media", media)
            .con("fraccion", fraccion)
            .con("objetivo_c", objetivo_base)
            .con("objetivo_efectivo_c", objetivo_c);
        Ok(self.ultimo.clone())
    }
}
