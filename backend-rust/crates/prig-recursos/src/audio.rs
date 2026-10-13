//! Monitor de audio del sistema (backend/audio_monitor.py): las aplicaciones que suenan (PulseAudio/PipeWire) y el
//! espectro en tiempo real para los efectos visuales.
//!
//! En Python la FFT se hacía en un hilo propio a ~50 cuadros por segundo, y ese hilo se quedaba el GIL: era lo que
//! estiraba el tramo de trabajo del modo frío de 6 a 11 ms (docs/informe-rust-moe.md §2). Aquí la captura y el
//! análisis van en un hilo de Rust que no toca Python. Las cuentas son las de Python, en el mismo orden (la FFT
//! recursiva con los giros calculados como `math.e ** complex`, la suma compensada de `sum()`, el redondeo), así que
//! el espectro sale idéntico.

use crate::valor::{redondear, Mapa, Valor};
use std::f64::consts::{E, PI};
use std::io::Read;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

pub const N: usize = 512;
pub const RATE: u32 = 16000;
const BANDAS: usize = 32;

// =========================================================================== las cuentas de Python

/// `sum()` de Python 3.12 sobre floats: empieza por el primero y compensa (Neumaier)
pub fn suma(xs: impl IntoIterator<Item = f64>) -> f64 {
    let mut it = xs.into_iter();
    let Some(primero) = it.next() else { return 0.0 };
    let (mut f, mut c) = (primero, 0.0f64);
    for x in it {
        let t = f + x;
        if f.abs() >= x.abs() {
            c += (f - t) + x;
        } else {
            c += (x - t) + f;
        }
        f = t;
    }
    if c != 0.0 && c.is_finite() {
        f += c;
    }
    f
}

type Complejo = (f64, f64);

fn mul(a: Complejo, b: Complejo) -> Complejo {
    (a.0 * b.0 - a.1 * b.1, a.0 * b.1 + a.1 * b.0)
}

/// `math.e ** (-2j * math.pi * k / n)` como lo calcula CPython (`_Py_c_pow` con base real)
fn giro(k: usize, n: usize) -> Complejo {
    // -2j * pi → (0.0, -2π); * k → (0.0, -2π·k); / n → (0.0, (-2π·k)/n)
    let theta = ((-2.0 * PI) * k as f64) / n as f64;
    if theta == 0.0 {
        return (1.0, 0.0);
    }
    let fase = 0.0 + theta * E.ln();
    (fase.cos(), fase.sin())
}

/// La FFT Cooley-Tukey de Python, recursiva y en el mismo orden
pub fn fft(x: &[Complejo]) -> Vec<Complejo> {
    let n = x.len();
    if n <= 1 {
        return x.to_vec();
    }
    let pares: Vec<Complejo> = x.iter().step_by(2).copied().collect();
    let impares: Vec<Complejo> = x.iter().skip(1).step_by(2).copied().collect();
    let even = fft(&pares);
    let odd = fft(&impares);
    let t: Vec<Complejo> = (0..n / 2).map(|k| mul(giro(k, n), odd[k])).collect();
    let mut r = Vec::with_capacity(n);
    for k in 0..n / 2 {
        r.push((even[k].0 + t[k].0, even[k].1 + t[k].1));
    }
    for k in 0..n / 2 {
        r.push((even[k].0 - t[k].0, even[k].1 - t[k].1));
    }
    r
}

fn min_py(a: f64, b: f64) -> f64 {
    if b < a {
        b
    } else {
        a
    }
}

/// La ventana de Hann y las 32 bandas logarítmicas (30-6000 Hz)
pub struct Analizador {
    hann: Vec<f64>,
    bandas: Vec<(usize, usize)>,
}

impl Default for Analizador {
    fn default() -> Self {
        Self::new()
    }
}

impl Analizador {
    pub fn new() -> Analizador {
        let hann = (0..N).map(|i| 0.5 * (1.0 - ((2.0 * PI) * i as f64 / (N - 1) as f64).cos())).collect();
        let (min_f, max_f) = (30.0f64, 6000.0f64);
        let puntos: Vec<f64> = (0..=BANDAS).map(|i| min_f * (max_f / min_f).powf(i as f64 / BANDAS as f64)).collect();
        let df = RATE as f64 / N as f64;
        let mut bandas = Vec::with_capacity(BANDAS);
        for i in 0..BANDAS {
            let k_min = ((puntos[i] / df).trunc() as usize).max(1);
            let mut k_max = (N / 2).min((puntos[i + 1] / df).trunc() as usize + 1);
            if k_min >= k_max {
                k_max = k_min + 1;
            }
            bandas.push((k_min, k_max));
        }
        Analizador { hann, bandas }
    }

    /// Un trozo de 512 muestras s16le: {activo, fuente, bass, mids, treble, energy, rms, spectrum}
    pub fn analizar(&self, pcm: &[u8], fuente: &Valor) -> Mapa {
        let muestras: Vec<f64> = pcm.as_chunks::<2>().0.iter().take(N).map(|b| i16::from_le_bytes(*b) as f64).collect();
        let norm: Vec<f64> = muestras.iter().zip(&self.hann).map(|(s, w)| (s / 32768.0) * w).collect();
        let rms = (suma(norm.iter().map(|s| s * s)) / N as f64).sqrt();
        let complejos: Vec<Complejo> = norm.iter().map(|&s| (s, 0.0)).collect();
        let res = fft(&complejos);
        let mags: Vec<f64> = res[..N / 2].iter().map(|c| c.0.hypot(c.1) * (2.0 / N as f64)).collect();
        let mut espectro = [0.0f64; BANDAS];
        for (b, &(k_min, k_max)) in self.bandas.iter().enumerate() {
            let fin = k_max.min(mags.len());
            let bins = if k_min < fin { &mags[k_min..fin] } else { &[][..] };
            let media = if bins.is_empty() { 0.0 } else { suma(bins.iter().copied()) / bins.len() as f64 };
            espectro[b] = redondear(min_py(1.0, (media * 20.0).sqrt()), 3);
        }
        let bass = suma(espectro[0..6].iter().copied()) / 6.0;
        let mids = suma(espectro[6..20].iter().copied()) / 14.0;
        let treble = suma(espectro[20..32].iter().copied()) / 12.0;
        let mezcla = bass * 0.5 + mids * 0.35 + treble * 0.15;
        let pico = espectro.iter().copied().fold(espectro[0], |m, x| if x > m { x } else { m }) * 0.8;
        // max(a, b, c) de Python: el primero de los mayores
        let mut energy = bass;
        for x in [mezcla, pico] {
            if x > energy {
                energy = x;
            }
        }
        Mapa::new()
            .con("activo", true)
            .con("fuente", fuente.clone())
            .con("bass", redondear(min_py(1.0, bass * 1.5), 3))
            .con("mids", redondear(min_py(1.0, mids * 1.4), 3))
            .con("treble", redondear(min_py(1.0, treble * 1.3), 3))
            .con("energy", redondear(min_py(1.0, energy * 1.5), 3))
            .con("rms", redondear(rms, 4))
            .con("spectrum", Valor::Lista(espectro.iter().map(|&x| Valor::Real(x)).collect()))
    }
}

// =========================================================================== PulseAudio

/// El entorno para pactl y parec: con XDG_RUNTIME_DIR y PULSE_SERVER si faltan, y en inglés (LC_ALL=C)
fn entorno(cmd: &mut Command) {
    // SAFETY: getuid no falla
    let uid = unsafe { libc::getuid() };
    let xdg = std::env::var("XDG_RUNTIME_DIR").ok();
    let usuario = format!("/run/user/{uid}");
    if xdg.as_deref().is_none_or(|x| !std::path::Path::new(x).exists()) && std::path::Path::new(&usuario).exists() {
        cmd.env("XDG_RUNTIME_DIR", &usuario);
    }
    if std::env::var_os("PULSE_SERVER").is_none() && std::path::Path::new(&format!("{usuario}/pulse/native")).exists() {
        cmd.env("PULSE_SERVER", format!("unix:{usuario}/pulse/native"));
    }
    cmd.env("LC_ALL", "C");
}

/// El primer `clave\s*=\s*"([^"]+)"` de un bloque
fn propiedad(bloque: &str, clave: &str) -> Option<String> {
    for (i, _) in bloque.match_indices(clave) {
        let resto = bloque[i + clave.len()..].trim_start();
        let Some(resto) = resto.strip_prefix('=') else { continue };
        let Some(resto) = resto.trim_start().strip_prefix('"') else { continue };
        if let Some(fin) = resto.find('"') {
            if fin > 0 {
                return Some(resto[..fin].to_string());
            }
        }
    }
    None
}

/// Corta la salida de `pactl list sink-inputs` en un bloque por entrada
fn bloques(salida: &str) -> Vec<String> {
    let bajo = salida.to_lowercase();
    let mut cortes: Vec<(usize, usize)> = Vec::new(); // (inicio del separador, fin)
    for sep in ["sink input", "entrada del destino", "entrada de sumidero"] {
        for (i, _) in bajo.match_indices(sep) {
            let mut j = i + sep.len();
            while bajo[j..].starts_with(char::is_whitespace) {
                j += bajo[j..].chars().next().map(char::len_utf8).unwrap_or(1);
            }
            if bajo[j..].starts_with('#') {
                cortes.push((i, j + 1));
            }
        }
    }
    cortes.sort();
    let mut salida_bloques = Vec::new();
    let mut desde = 0;
    for (i, fin) in cortes {
        if i < desde {
            continue;
        }
        salida_bloques.push(salida[desde..i].to_string());
        desde = fin;
    }
    salida_bloques.push(salida[desde..].to_string());
    salida_bloques
}

fn icono(texto: &str) -> &'static str {
    let t = texto.to_lowercase();
    if t.contains("firefox") {
        "fa-brands fa-firefox-browser"
    } else if ["chrome", "chromium", "brave", "edge"].iter().any(|n| t.contains(n)) {
        "fa-brands fa-chrome"
    } else if t.contains("spotify") {
        "fa-brands fa-spotify"
    } else if t.contains("youtube") {
        "fa-brands fa-youtube"
    } else if t.contains("vlc") {
        "fa-video"
    } else if t.contains("discord") {
        "fa-brands fa-discord"
    } else if t.contains("steam") || t.contains("game") {
        "fa-gamepad"
    } else {
        "fa-music"
    }
}

/// Las aplicaciones y pestañas que suenan, con la opción de todo el sistema primero
pub fn listar_aplicaciones(fuente_actual: &str) -> Vec<Mapa> {
    let mut apps = vec![Mapa::new()
        .con("id", "sistema_global")
        .con("app", "Todo el Sistema (Global)")
        .con("title", "Salida de audio completa de la PC (Todos los programas)")
        .con("binary", "system")
        .con("icono", "fa-volume-high")
        .con("activo", fuente_actual == "sistema_global")];
    let mut cmd = Command::new("pactl");
    cmd.args(["list", "sink-inputs"]).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null());
    entorno(&mut cmd);
    let Ok(hijo) = cmd.spawn() else { return apps };
    let Some(salida) = esperar_salida(hijo, Duration::from_secs(3)) else { return apps };
    for b in bloques(&salida) {
        if b.trim().is_empty() {
            continue;
        }
        let primera = b.trim().split('\n').next().unwrap_or("").trim().to_string();
        let num: String = primera.chars().take_while(|c| c.is_ascii_digit()).collect();
        if num.is_empty() {
            continue;
        }
        let app = propiedad(&b, "application.name").unwrap_or_default();
        let media = propiedad(&b, "media.name").unwrap_or_default();
        let binario = propiedad(&b, "application.process.binary").unwrap_or_default();
        // Servicios mudos internos del sistema
        if ["speech-dispatcher-dummy", "sd_dummy"].contains(&app.to_lowercase().as_str()) {
            continue;
        }
        let pausado = corked(&b).is_some_and(|v| ["yes", "sí", "si", "true", "1"].contains(&v.to_lowercase().as_str()));
        let nombre = if !app.is_empty() {
            app.clone()
        } else if !binario.is_empty() {
            binario.clone()
        } else {
            format!("Aplicación #{num}")
        };
        apps.push(
            Mapa::new()
                .con("id", num.clone())
                .con("app", nombre)
                .con("title", if media.is_empty() { "Reproducción de Audio".to_string() } else { media.clone() })
                .con("binary", binario.clone())
                .con("icono", icono(&format!("{app} {binario} {media}")))
                .con("pausado", pausado)
                .con("activo", fuente_actual == num),
        );
    }
    apps
}

/// `(?:Corked|Pausado):\s*(\w+)` (sin distinguir mayúsculas)
fn corked(bloque: &str) -> Option<String> {
    let bajo = bloque.to_lowercase();
    let mut mejor: Option<(usize, String)> = None;
    for clave in ["corked:", "pausado:"] {
        for (i, _) in bajo.match_indices(clave) {
            let resto = bloque[i + clave.len()..].trim_start();
            let palabra: String = resto.chars().take_while(|c| c.is_alphanumeric() || *c == '_').collect();
            if !palabra.is_empty() && mejor.as_ref().is_none_or(|(j, _)| i < *j) {
                mejor = Some((i, palabra));
            }
        }
    }
    mejor.map(|(_, p)| p)
}

fn esperar_salida(mut hijo: Child, plazo: Duration) -> Option<String> {
    let mut tubo = hijo.stdout.take()?;
    let lector = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = tubo.read_to_end(&mut b);
        b
    });
    let fin = std::time::Instant::now() + plazo;
    loop {
        match hijo.try_wait() {
            Ok(Some(st)) if st.success() => break,
            Ok(Some(_)) => return None,
            Ok(None) if std::time::Instant::now() < fin => std::thread::sleep(Duration::from_millis(10)),
            _ => {
                let _ = hijo.kill();
                let _ = hijo.wait();
                return None;
            }
        }
    }
    String::from_utf8(lector.join().ok()?).ok()
}

// =========================================================================== el monitor

struct Estado {
    fuente: Valor,
    suscriptores: i64,
    datos: Mapa,
    /// El parec de la captura en marcha (para pararlo al irse el último suscriptor)
    pid: Option<u32>,
}

/// Captura (parec del monitor de la salida por defecto) y análisis en un hilo propio mientras haya suscriptores.
/// Cada hilo de captura tiene su número de generación y su propio parec: si alguien se va y vuelve enseguida, el
/// hilo viejo termina solo y no toca el parec del nuevo.
pub struct MonitorAudio {
    estado: Arc<Mutex<Estado>>,
    generacion: Arc<AtomicU64>,
    activa: AtomicBool,
}

impl Default for MonitorAudio {
    fn default() -> Self {
        Self::new()
    }
}

fn reposo() -> Mapa {
    Mapa::new()
        .con("activo", false)
        .con("fuente", "sistema_global")
        .con("bass", 0.0)
        .con("mids", 0.0)
        .con("treble", 0.0)
        .con("energy", 0.0)
        .con("rms", 0.0)
        .con("spectrum", Valor::Lista(vec![Valor::Real(0.0); BANDAS]))
}

fn bloquear(estado: &Mutex<Estado>) -> MutexGuard<'_, Estado> {
    estado.lock().unwrap_or_else(|e| e.into_inner())
}

impl MonitorAudio {
    pub fn new() -> MonitorAudio {
        MonitorAudio {
            estado: Arc::new(Mutex::new(Estado { fuente: "sistema_global".into(), suscriptores: 0, datos: reposo(), pid: None })),
            generacion: Arc::new(AtomicU64::new(0)),
            activa: AtomicBool::new(false),
        }
    }

    pub fn datos(&self) -> Mapa {
        bloquear(&self.estado).datos.clone()
    }

    pub fn fuente(&self) -> Valor {
        bloquear(&self.estado).fuente.clone()
    }

    pub fn seleccionar_fuente(&self, fuente: Valor) {
        bloquear(&self.estado).fuente = fuente;
    }

    pub fn listar(&self) -> Vec<Mapa> {
        let f = self.fuente().texto_py();
        listar_aplicaciones(&f)
    }

    pub fn incrementar(&self) {
        let mut e = bloquear(&self.estado);
        e.suscriptores += 1;
        if !self.activa.swap(true, Ordering::SeqCst) {
            let g = self.generacion.fetch_add(1, Ordering::SeqCst) + 1;
            let (estado, generacion) = (self.estado.clone(), self.generacion.clone());
            std::thread::Builder::new().name("prig-audio".into()).spawn(move || bucle(estado, generacion, g)).ok();
        }
    }

    pub fn decrementar(&self) {
        let mut e = bloquear(&self.estado);
        e.suscriptores = (e.suscriptores - 1).max(0);
        if e.suscriptores == 0 {
            self.activa.store(false, Ordering::SeqCst);
            self.generacion.fetch_add(1, Ordering::SeqCst); // el hilo de captura termina solo
            if let Some(pid) = e.pid.take() {
                // SAFETY: SIGTERM al parec que lanzó este monitor (lo recoge su hilo)
                unsafe {
                    libc::kill(pid as i32, libc::SIGTERM);
                }
            }
            e.datos.poner("activo", false);
        }
    }
}

/// El bucle de captura de la generación `g`: lanza parec si no está, lee trozos de 512 muestras y publica el
/// análisis (~50 por segundo). Si parec termina, se vuelve a lanzar (en Python se quedaba esperando sin fin a un
/// tubo vacío).
fn bucle(estado: Arc<Mutex<Estado>>, generacion: Arc<AtomicU64>, g: u64) {
    let vigente = || generacion.load(Ordering::SeqCst) == g;
    let analizador = Analizador::new();
    let bytes = N * 2;
    let mut hijo: Option<Child> = None;
    let mut tubo: Option<std::process::ChildStdout> = None;
    let terminar = |hijo: &mut Option<Child>| {
        if let Some(mut h) = hijo.take() {
            let _ = h.kill();
            let _ = h.wait();
        }
    };
    while vigente() {
        if tubo.is_none() {
            let mut cmd = Command::new("parec");
            cmd.args(["--format=s16le", &format!("--rate={RATE}"), "--channels=1", "--latency-msec=20", "-d", "@DEFAULT_SINK@.monitor"])
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::null());
            entorno(&mut cmd);
            match cmd.spawn() {
                Ok(mut h) => {
                    tubo = h.stdout.take();
                    let mut e = bloquear(&estado);
                    if vigente() {
                        e.pid = Some(h.id());
                    }
                    hijo = Some(h);
                }
                Err(e) => {
                    eprintln!("[AudioMonitorNativo] Error ejecutando parec: {e}");
                    std::thread::sleep(Duration::from_secs(1));
                    continue;
                }
            }
        }
        let mut buf = vec![0u8; bytes];
        let mut leidos = 0;
        let mut cerrado = false;
        while leidos < bytes && vigente() {
            match tubo.as_mut().map(|t| t.read(&mut buf[leidos..])) {
                Some(Ok(0)) | Some(Err(_)) | None => {
                    cerrado = true;
                    break;
                }
                Some(Ok(n)) => leidos += n,
            }
        }
        if cerrado {
            tubo = None;
            terminar(&mut hijo);
            std::thread::sleep(Duration::from_millis(50));
            continue;
        }
        if leidos < bytes {
            continue;
        }
        let fuente = bloquear(&estado).fuente.clone();
        let datos = analizador.analizar(&buf, &fuente);
        let mut e = bloquear(&estado);
        if vigente() {
            e.datos = datos;
        }
        drop(e);
        std::thread::sleep(Duration::from_millis(15));
    }
    terminar(&mut hijo);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn suma_como_python() {
        assert_eq!(suma([0.1; 10]), 1.0); // Python 3.12: sum([0.1] * 10) == 1.0
        assert_eq!(suma([]), 0.0);
    }

    #[test]
    fn silencio() {
        let a = Analizador::new();
        let d = a.analizar(&[0u8; N * 2], &"x".into());
        assert_eq!(d.num_o("energy", 1.0), 0.0);
        assert_eq!(d.lista("spectrum").map(|l| l.len()), Some(32));
    }

    #[test]
    fn bloques_de_pactl() {
        let salida = "Sink Input #12\n\tCorked: no\n\tProperties:\n\t\tapplication.name = \"Firefox\"\n\t\tmedia.name = \"YouTube\"\nSink Input #13\n\tCorked: yes\n";
        let b = bloques(salida);
        assert_eq!(b.len(), 3);
        assert_eq!(propiedad(&b[1], "application.name").as_deref(), Some("Firefox"));
        assert_eq!(corked(&b[2]).as_deref(), Some("yes"));
    }
}
