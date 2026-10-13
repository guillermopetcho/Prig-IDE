//! Modo suave (backend/recursos/ritmo.py): que los modelos trabajen de forma continua y gradual, sin picos de calor.
//!
//! Medido en el portátil del usuario (i5-13420H + RTX 4050 6 GB, qwen2.5-coder:7b): la GPU pasa de 7 a 40 W al
//! empezar a generar y sube unos 7 °C en un segundo. Prig no puede bajar su límite de potencia sin ser administrador,
//! pero sí DOSIFICAR el trabajo: con tramos de 0,25 s y pausas iguales la media baja de 40 a 32 W y la temperatura
//! estable de 64,5 a 60 °C. La pausa es un termostato proporcional (a pleno lejos del objetivo, más pausa al
//! acercarse) con ARRANQUE GRADUAL tras un rato sin trabajar.
//!
//! CPU: con el modelo entero en la GPU, un hilo del motor espera a la GPU sin parar (la CPU saltaba de 43 a
//! 80-92 °C). Fijar el llama-server a los núcleos de EFICIENCIA la deja en 69-72 °C a la misma velocidad. Solo si el
//! modelo cabe entero en la GPU; si una parte va en la CPU, esos núcleos lo frenarían.
//!
//! El reloj viene siempre de fuera (`ahora`): quien llama decide cuándo se lee, como hacía Python.

use crate::http;
use crate::valor::{fijo, redondear, Mapa, Valor};
use std::collections::{HashMap, HashSet};
use std::fs;

pub const BANDA_C: f64 = 8.0; // por debajo de objetivo − BANDA trabaja a pleno
pub const REPOSO_S: f64 = 30.0; // tras este tiempo sin generar, la rampa vuelve a empezar
pub const PAUSA_MAXIMA_S: f64 = 4.0;
/// El servidor del motor MoE fija sus propios núcleos (P): con los E rinde la mitad (medido: 10-12 tok/s en lugar
/// de 45-57)
pub const MOTOR_MOE: &str = "lib/moe/llama-server";

pub fn ajustes_por_defecto() -> Mapa {
    Mapa::new()
        .con("activo", true)
        .con("objetivo_c", 55.0) // temperatura a la que se quiere mantener la GPU trabajando
        .con("rampa_s", 60.0) // arranque gradual: segundos hasta llegar al 100 %
        .con("inicio_rampa", 0.2) // fracción con la que arranca una respuesta tras un rato parado
        .con("ritmo_minimo", 0.25) // fracción mínima del tiempo trabajando (nunca se para del todo)
        .con("tramo_s", 1.0) // pausando peticiones (sin motor suave): cuánto trabaja entre pausas
        .con("tramo_motor_s", 0.02) // dentro del motor: tramos de 20 ms
        .con("cpu_eficiente", true) // fijar el motor a los núcleos de eficiencia
}

const LIMITES: &[(&str, f64, f64)] = &[
    ("objetivo_c", 40.0, 90.0),
    ("rampa_s", 0.0, 300.0),
    ("ritmo_minimo", 0.1, 1.0),
    ("tramo_s", 0.25, 5.0),
    ("tramo_motor_s", 0.005, 0.5),
    ("inicio_rampa", 0.1, 1.0),
];

/// Un error que en Python era una excepción: (tipo, mensaje)
#[derive(Debug, Clone, PartialEq)]
pub enum ErrorPy {
    Valor(String),
    Tipo(String),
}

/// `float(v)` de Python, con sus errores
pub fn float_py(v: &Valor) -> Result<f64, ErrorPy> {
    match v {
        Valor::Texto(_) => v.real().ok_or_else(|| ErrorPy::Valor(format!("could not convert string to float: {}", v.repr_py()))),
        Valor::Lista(_) => Err(ErrorPy::Tipo("float() argument must be a string or a real number, not 'list'".into())),
        Valor::Mapa(_) => Err(ErrorPy::Tipo("float() argument must be a string or a real number, not 'dict'".into())),
        Valor::Nulo => Err(ErrorPy::Tipo("float() argument must be a string or a real number, not 'NoneType'".into())),
        v => Ok(v.num().unwrap_or(f64::NAN)),
    }
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

/// Cuánto trabajar y cuánto descansar en cada momento
#[derive(Debug, Clone)]
pub struct Ritmo {
    pub ajustes: Mapa,
    inicio_actividad: Option<f64>,
    ultima_actividad: f64,
    pub ultimo: Mapa,
}

impl Ritmo {
    pub fn new(ajustes: Option<&Mapa>) -> Ritmo {
        let a = match ajustes {
            Some(m) => ajustes_por_defecto().fusion(m),
            None => ajustes_por_defecto(),
        };
        Ritmo { ajustes: a, inicio_actividad: None, ultima_actividad: 0.0, ultimo: Mapa::new() }
    }

    /// Cambia los ajustes acotándolos; devuelve los ajustes y el texto para guardarlos. Si un valor no es un número,
    /// el error de Python, con los cambios anteriores ya hechos (como dentro del `with` de Python).
    pub fn fijar(&mut self, cambios: &Mapa) -> Result<(Mapa, String), ErrorPy> {
        for (clave, valor) in cambios.iter() {
            if clave == "activo" || clave == "cpu_eficiente" {
                self.ajustes.poner(clave.clone(), valor.verdad());
            } else if let Some((_, bajo, alto)) = LIMITES.iter().find(|(k, _, _)| k == clave) {
                if !valor.es_nulo() {
                    let v = float_py(valor)?;
                    self.ajustes.poner(clave.clone(), redondear(min_py(*alto, max_py(*bajo, v)), 2));
                }
            }
        }
        let a = &self.ajustes;
        let texto = format!(
            "Modo suave {}: objetivo {} °C, arranque gradual de {} s.",
            if a.verdad("activo") { "activado" } else { "desactivado" },
            fijo(a.num_o("objetivo_c", f64::NAN), 0),
            fijo(a.num_o("rampa_s", f64::NAN), 0)
        );
        Ok((self.ajustes.clone(), texto))
    }

    pub fn activo(&self) -> bool {
        self.ajustes.verdad("activo")
    }

    /// Hubo actividad en `ahora` (para la rampa)
    pub fn marcar(&mut self, ahora: f64) {
        if self.inicio_actividad.is_none() || ahora - self.ultima_actividad > REPOSO_S {
            self.inicio_actividad = Some(ahora);
        }
        self.ultima_actividad = ahora;
    }

    /// Fracción del tiempo que se trabaja (1 = sin pausas)
    pub fn fraccion(&self, temp: Option<f64>, ahora: f64) -> f64 {
        let a = &self.ajustes;
        let minimo = a.num_o("ritmo_minimo", f64::NAN);
        let mut por_temp = 1.0;
        if let Some(t) = temp {
            let margen = a.num_o("objetivo_c", f64::NAN) - t;
            por_temp = min_py(1.0, max_py(minimo, minimo + (1.0 - minimo) * margen / BANDA_C));
        }
        let mut por_rampa = 1.0;
        let rampa = a.num_o("rampa_s", f64::NAN);
        if rampa > 0.0 {
            let arranque = a.num_o("inicio_rampa", 0.3);
            match self.inicio_actividad {
                Some(inicio) if ahora - self.ultima_actividad <= REPOSO_S => {
                    por_rampa = min_py(1.0, max_py(minimo, arranque + (1.0 - arranque) * (ahora - inicio) / rampa));
                }
                _ => por_rampa = max_py(minimo, arranque), // parado: la próxima respuesta empieza suave
            }
        }
        redondear(min_py(por_temp, por_rampa), 3)
    }

    /// Si toca descansar tras este tramo, cuántos segundos. El reloj solo se lee si hace falta, y en el orden de
    /// Python: `ahora` para la fracción y `cuando` para apuntarlo en `ultimo`.
    pub fn pausa(
        &mut self,
        segundos_trabajando: f64,
        temp: &Valor,
        ahora: impl FnOnce() -> f64,
        cuando: impl FnOnce() -> f64,
    ) -> Option<f64> {
        if !self.activo() || segundos_trabajando < self.ajustes.num_o("tramo_s", f64::NAN) {
            return None;
        }
        let f = self.fraccion(temp.num(), ahora());
        self.ultimo = Mapa::new().con("fraccion", f).con("temp", temp.clone()).con("cuando", cuando());
        if f >= 0.98 {
            return None;
        }
        Some(redondear(min_py(PAUSA_MAXIMA_S, segundos_trabajando * (1.0 - f) / f), 2))
    }

    /// `{**ajustes, fraccion_ahora, ultimo, nucleos_eficientes}`
    pub fn estado(&self, temp: Option<f64>, ahora: impl FnOnce() -> f64, nucleos: impl FnOnce() -> Vec<i64>) -> Mapa {
        let fraccion = if self.activo() { self.fraccion(temp, ahora()) } else { 1.0 };
        let nucleos = nucleos();
        self.ajustes
            .clone()
            .con("fraccion_ahora", fraccion)
            .con("ultimo", self.ultimo.clone())
            .con("nucleos_eficientes", Valor::Lista(nucleos.into_iter().map(Valor::from).collect()))
    }
}

// =========================================================================== núcleos

/// «8-11» → [8, 9, 10, 11]; «0,2-3» → [0, 2, 3]. `None` donde Python lanzaría ValueError.
pub fn leer_lista_cpus(texto: &str) -> Option<Vec<i64>> {
    let mut cpus = Vec::new();
    for parte in texto.trim().split(',') {
        if parte.contains('-') {
            let mut trozos = parte.split('-');
            let (a, b) = (trozos.next()?, trozos.next()?);
            if trozos.next().is_some() {
                return None;
            }
            let a = crate::valor::entero_de_texto(a)? as i64;
            let b = crate::valor::entero_de_texto(b)? as i64;
            cpus.extend(a..=b);
        } else if !parte.trim().is_empty() && parte.trim().chars().all(|c| c.is_ascii_digit()) {
            cpus.push(parte.trim().parse().ok()?);
        }
    }
    Some(cpus)
}

/// Los núcleos en los que puede correr este proceso (`os.sched_getaffinity(0)`, ordenados)
pub fn afinidad_propia() -> Vec<i64> {
    // SAFETY: sched_getaffinity escribe en el conjunto que se le da, de su tamaño
    unsafe {
        let mut conjunto: libc::cpu_set_t = std::mem::zeroed();
        if libc::sched_getaffinity(0, std::mem::size_of::<libc::cpu_set_t>(), &mut conjunto) != 0 {
            return Vec::new();
        }
        (0..libc::CPU_SETSIZE as usize).filter(|&c| libc::CPU_ISSET(c, &conjunto)).map(|c| c as i64).collect()
    }
}

/// Fija un proceso (o un hilo) a esos núcleos
pub fn fijar_afinidad(pid: i32, nucleos: &[i64]) -> std::io::Result<()> {
    // SAFETY: el conjunto se construye aquí; sched_setaffinity solo lo lee
    unsafe {
        let mut conjunto: libc::cpu_set_t = std::mem::zeroed();
        for &c in nucleos {
            if (0..libc::CPU_SETSIZE as i64).contains(&c) {
                libc::CPU_SET(c as usize, &mut conjunto);
            }
        }
        if libc::sched_setaffinity(pid, std::mem::size_of::<libc::cpu_set_t>(), &conjunto) != 0 {
            return Err(std::io::Error::last_os_error());
        }
    }
    Ok(())
}

/// Los E-cores de los Intel híbridos (12.ª generación en adelante) en los que puede correr Prig. Vacío si no hay.
pub fn nucleos_eficientes() -> Vec<i64> {
    let Ok(texto) = fs::read_to_string("/sys/devices/cpu_atom/cpus") else { return Vec::new() };
    let eficientes = leer_lista_cpus(&texto).unwrap_or_default();
    let disponibles: HashSet<i64> = afinidad_propia().into_iter().collect();
    eficientes.into_iter().filter(|c| disponibles.contains(c)).collect()
}

/// El proceso y todos sus hilos a esos núcleos (`FijadorCPU.fijar_proceso`)
pub fn fijar_proceso(pid: i32, nucleos: &[i64]) -> bool {
    if fijar_afinidad(pid, nucleos).is_err() {
        return false;
    }
    let Ok(hilos) = fs::read_dir(format!("/proc/{pid}/task")) else { return false };
    for h in hilos.flatten() {
        if let Some(t) = h.file_name().to_str().and_then(|t| t.parse::<i32>().ok()) {
            let _ = fijar_afinidad(t, nucleos);
        }
    }
    true
}

// =========================================================================== el fijador

/// Un proceso tal como lo daba `psutil.process_iter(["pid", "cmdline", "uids"])`
#[derive(Debug, Clone)]
pub struct ProcesoCpu {
    pub pid: i32,
    pub cmdline: Vec<String>,
    /// uid real (None si no se pudo leer)
    pub uid: Option<u32>,
}

/// Lo que el fijador necesita del sistema y de Prig (el reloj, los núcleos, Ollama), para poder probarlo
pub trait MundoFijador {
    fn nucleos_eficientes(&mut self) -> Vec<i64>;
    fn ahora(&mut self) -> f64;
    fn modelos_en_gpu(&mut self) -> HashMap<String, bool>;
    fn ram_en_eficientes(&mut self) -> bool;
    fn afinidad_propia(&mut self) -> Vec<i64>;
    fn uid(&mut self) -> Option<u32>;
    fn procesos(&mut self) -> Vec<ProcesoCpu>;
    /// Los hilos del proceso; None si el proceso ya no está (psutil.Error)
    fn hilos(&mut self, pid: i32) -> Option<Vec<i32>>;
    /// ¿Se pudo fijar? (OSError en Python)
    fn fijar(&mut self, pid: i32, nucleos: &[i64]) -> bool;
    fn pids(&mut self) -> HashSet<i32>;
}

/// El primer «sha256-<64 hex>» de un texto
pub fn blob_en(linea: &str) -> Option<String> {
    for (i, _) in linea.match_indices("sha256-") {
        let resto = &linea[i + 7..];
        if resto.len() >= 64 && resto[..64].bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
            return Some(resto[..64].to_string());
        }
    }
    None
}

/// Pone el motor del modelo (llama-server) en los núcleos de eficiencia si el modelo está entero en la GPU, y lo
/// devuelve a todos si no. Solo toca procesos del usuario.
#[derive(Debug, Default)]
pub struct FijadorCpu {
    pub url: String,
    hechos: HashMap<i32, &'static str>, // pid → "eficientes" | "todos"
    blobs: HashMap<String, Option<String>>,
    ultimo: f64,
}

impl FijadorCpu {
    pub fn new(url: &str) -> FijadorCpu {
        FijadorCpu { url: url.to_string(), ..Default::default() }
    }

    /// El archivo de pesos del modelo (lo que aparece en la línea de llama-server). El «digest» de /api/ps es el
    /// del manifiesto, no este: hay que pedírselo a /api/show. Un fallo de red no se recuerda.
    fn blob(&mut self, modelo: &str) -> Option<String> {
        if let Some(b) = self.blobs.get(modelo) {
            return b.clone();
        }
        let ficha = http::post_json(&format!("{}/api/show", self.url), &Mapa::new().con("model", modelo).into(), 3.0).ok()?;
        let modelfile = match &ficha {
            Valor::Mapa(m) => m.texto("modelfile").unwrap_or("").to_string(),
            _ => String::new(),
        };
        let b = blob_en(&modelfile);
        self.blobs.insert(modelo.to_string(), b.clone());
        b
    }

    /// blob de pesos → True si el modelo está entero en la VRAM (preguntando a Ollama)
    pub fn modelos_en_gpu(&mut self) -> HashMap<String, bool> {
        let Ok(ps) = http::get_json(&format!("{}/api/ps", self.url), 2.0) else { return HashMap::new() };
        let modelos = match &ps {
            Valor::Mapa(m) => m.lista("models").unwrap_or(&[]).to_vec(),
            _ => Vec::new(),
        };
        let mut salida = HashMap::new();
        for m in modelos {
            let Valor::Mapa(m) = m else { continue };
            let nombre = [m.get("name"), m.get("model")]
                .into_iter()
                .flatten()
                .find(|v| v.verdad())
                .map(Valor::texto_py)
                .unwrap_or_default();
            if let Some(blob) = self.blob(&nombre) {
                let size = m.num_o("size", 1.0);
                salida.insert(blob, m.num_o("size_vram", 0.0) >= 0.98 * size.max(1.0));
            }
        }
        salida
    }

    /// `aplicar(forzar)`: {aplicado, cambiados, eficientes} (o el motivo de no hacerlo)
    pub fn aplicar(&mut self, mundo: &mut dyn MundoFijador, forzar: bool) -> Mapa {
        let eficientes = mundo.nucleos_eficientes();
        if eficientes.is_empty() {
            return Mapa::new()
                .con("aplicado", false)
                .con("motivo", "Este procesador no tiene núcleos de eficiencia.");
        }
        if !forzar && mundo.ahora() - self.ultimo < 5.0 {
            return Mapa::new().con("aplicado", Valor::Nulo);
        }
        self.ultimo = mundo.ahora();
        let en_gpu = mundo.modelos_en_gpu();
        let todos = mundo.afinidad_propia();
        let yo = mundo.uid();
        let mut cambiados = Vec::new();
        for p in mundo.procesos() {
            let linea = p.cmdline.join(" ");
            if !linea.contains("llama-server") || (yo.is_some() && p.uid.is_some() && p.uid != yo) {
                continue;
            }
            if linea.contains(MOTOR_MOE) {
                continue; // el motor MoE fija sus propios núcleos (P)
            }
            let blob = blob_en(&linea);
            let mut entero = blob.as_ref().is_some_and(|b| en_gpu.get(b) == Some(&true));
            if !entero && blob.as_ref().is_some_and(|b| en_gpu.contains_key(b)) && mundo.ram_en_eficientes() {
                entero = true; // modelo en RAM con el modo frío: también a los núcleos E
            }
            let destino = if entero { "eficientes" } else { "todos" };
            if self.hechos.get(&p.pid) == Some(&destino) && !forzar {
                continue;
            }
            let nucleos = if entero { &eficientes } else { &todos };
            if !mundo.fijar(p.pid, nucleos) {
                continue;
            }
            // Los hilos ya creados no heredan la máscara: se aplica a cada uno
            let Some(hilos) = mundo.hilos(p.pid) else { continue };
            for h in hilos {
                mundo.fijar(h, nucleos);
            }
            self.hechos.insert(p.pid, destino);
            cambiados.push(Valor::from(Mapa::new().con("pid", p.pid).con("nucleos", destino)));
        }
        let vivos = mundo.pids();
        self.hechos.retain(|pid, _| vivos.contains(pid));
        Mapa::new()
            .con("aplicado", true)
            .con("cambiados", cambiados)
            .con("eficientes", Valor::Lista(eficientes.into_iter().map(Valor::from).collect()))
    }

    /// Devuelve todos los núcleos a los procesos que se habían fijado
    pub fn soltar(&mut self) {
        let todos = afinidad_propia();
        for pid in self.hechos.keys() {
            let _ = fijar_afinidad(*pid, &todos);
        }
        self.hechos.clear();
    }
}

// =========================================================================== el sistema de verdad

/// `cmdline` como psutil: por NUL; si no termina en NUL, por espacios (procesos que reescriben su línea)
pub fn cmdline(pid: i32) -> Option<Vec<String>> {
    let datos = fs::read(format!("/proc/{pid}/cmdline")).ok()?;
    if datos.is_empty() {
        return Some(Vec::new());
    }
    let texto = String::from_utf8_lossy(&datos).into_owned();
    let sep = if texto.ends_with('\0') { '\0' } else { ' ' };
    let texto = texto.strip_suffix(sep).unwrap_or(&texto);
    let mut partes: Vec<String> = texto.split(sep).map(str::to_string).collect();
    if sep == '\0' && partes.len() == 1 && texto.contains(' ') {
        partes = texto.split(' ').map(str::to_string).collect();
    }
    Some(partes)
}

/// El uid real de un proceso (/proc/<pid>/status)
pub fn uid_real(pid: i32) -> Option<u32> {
    let status = fs::read_to_string(format!("/proc/{pid}/status")).ok()?;
    status.lines().find_map(|l| l.strip_prefix("Uid:")).and_then(|r| r.split_whitespace().next()).and_then(|u| u.parse().ok())
}

/// Los pids de /proc
pub fn pids() -> HashSet<i32> {
    fs::read_dir("/proc")
        .map(|it| it.flatten().filter_map(|e| e.file_name().to_str().and_then(|n| n.parse().ok())).collect())
        .unwrap_or_default()
}

/// Las operaciones del sistema de verdad (procesos, hilos, afinidad); el resto lo pone quien lo usa
pub struct SistemaReal;

impl SistemaReal {
    pub fn procesos() -> Vec<ProcesoCpu> {
        let mut todos: Vec<i32> = pids().into_iter().collect();
        todos.sort();
        todos
            .into_iter()
            .map(|pid| ProcesoCpu { pid, cmdline: cmdline(pid).unwrap_or_default(), uid: uid_real(pid) })
            .collect()
    }

    pub fn hilos(pid: i32) -> Option<Vec<i32>> {
        let it = fs::read_dir(format!("/proc/{pid}/task")).ok()?;
        let mut h: Vec<i32> = it.flatten().filter_map(|e| e.file_name().to_str().and_then(|t| t.parse().ok())).collect();
        h.sort();
        Some(h)
    }

    pub fn uid() -> u32 {
        // SAFETY: getuid no falla ni toca memoria
        unsafe { libc::getuid() }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ritmo(extra: Mapa) -> Ritmo {
        Ritmo::new(Some(&Mapa::new().con("objetivo_c", 60).con("rampa_s", 0).con("ritmo_minimo", 0.3).fusion(&extra)))
    }

    // TestFraccion de Python
    #[test]
    fn termostato_proporcional() {
        let r = ritmo(Mapa::new());
        assert_eq!(r.fraccion(Some(45.0), 0.0), 1.0);
        assert_eq!(r.fraccion(Some(52.0), 0.0), 1.0);
        assert!((r.fraccion(Some(56.0), 0.0) - 0.65).abs() < 0.005);
        assert_eq!(r.fraccion(Some(60.0), 0.0), 0.3);
        assert_eq!(r.fraccion(Some(75.0), 0.0), 0.3);
        assert_eq!(r.fraccion(None, 0.0), 1.0);
    }

    #[test]
    fn arranque_gradual() {
        let mut r = ritmo(Mapa::new().con("rampa_s", 40).con("inicio_rampa", 0.35));
        assert!((r.fraccion(Some(40.0), 990.0) - 0.35).abs() < 1e-9);
        r.marcar(1000.0);
        for t in (1000..1041).step_by(10) {
            r.marcar(t as f64);
            if t == 1020 {
                assert!((r.fraccion(Some(40.0), 1020.0) - 0.675).abs() < 1e-9);
            }
        }
        assert_eq!(r.fraccion(Some(40.0), 1040.0), 1.0);
        r.marcar(1050.0 + REPOSO_S + 1.0);
        assert!((r.fraccion(Some(40.0), 1050.0 + REPOSO_S + 1.0) - 0.35).abs() < 1e-9);
    }

    #[test]
    fn fijar_acota() {
        let mut r = Ritmo::new(None);
        let (a, texto) = r
            .fijar(&Mapa::new().con("objetivo_c", 200).con("rampa_s", -5).con("ritmo_minimo", 0.01).con("activo", 0).con("raro", 1))
            .unwrap();
        assert_eq!(a.valor("objetivo_c"), &Valor::Real(90.0));
        assert_eq!(a.valor("activo"), &Valor::Bool(false));
        assert!(!a.contiene("raro"));
        assert!(texto.contains("desactivado"));
        assert!(matches!(r.fijar(&Mapa::new().con("tramo_s", "x")), Err(ErrorPy::Valor(_))));
    }

    #[test]
    fn lista_de_cpus() {
        assert_eq!(leer_lista_cpus("8-11"), Some(vec![8, 9, 10, 11]));
        assert_eq!(leer_lista_cpus("0,2-3\n"), Some(vec![0, 2, 3]));
    }
}
