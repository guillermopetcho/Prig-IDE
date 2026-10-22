//! El ciclo de vida del motor MoE (antes la clase `Motor` de `ai_engine/motor_moe.py`): un `llama-server` propio
//! (el fork de llama.cpp con el parche de Prig) que arranca bajo demanda, se para sin uso, guarda y restaura el estado
//! de los proyectos y pone en la GPU los expertos que usa cada uno. Lo que trabaja por petición y por token está en
//! `moe.rs`; aquí está el dueño del proceso.
//!
//! Respecto a Python:
//!
//! * **`llama-server` muere con Prig.** Se lanzaba en su propia sesión y, si Prig moría de golpe, seguía ocupando ~6 GB
//!   de VRAM hasta el siguiente arranque. Ahora lleva `PR_SET_PDEATHSIG`. Ese aviso va ligado al HILO que lanza el hijo
//!   (no al proceso): por eso todos los lanzamientos pasan por un hilo dedicado que vive lo que vive Prig; si se lanzara
//!   desde un hilo de tokio que luego termina, el modelo moriría a media respuesta.
//! * **El arranque tiene un tope total** (`ESPERA_TOTAL_S`): la escalera de intentos (n calientes, n-8, sin MTP, 0)
//!   esperaba hasta 240 s cada uno, hasta 20 minutos si el servidor se colgaba sin salir.

use crate::moe;
use prig_plataforma::valor::{Mapa, Valor};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const MODELO_OLLAMA: [&str; 4] = ["hf.co", "Elsephire", "Qwen3.6-35B-A3B-vocabulary-trimming-GGUF", "Q4_K_S"];
pub const CAPACIDADES: [&str; 3] = ["completion", "tools", "thinking"];
pub const MODOS: [(&str, Option<f64>); 3] = [("exacto", None), ("equilibrado", Some(0.08)), ("rapido", Some(0.10))];
pub const MODO: &str = "equilibrado";
pub const NUCLEO: &str = "q8";
pub const ARCHIVO_NUCLEO_Q8: &str = "nucleo-q8-expertos-q4.gguf";
pub const CACHE_RAM_MB: i64 = 16384;
pub const PROYECTOS_MAX_MB: f64 = 32768.0;
pub const BYTES_POR_TOKEN_ESTADO: f64 = 10_904.0;
pub const BYTES_FIJOS_ESTADO: f64 = 65_900_000.0;
pub const ESPERA_ARRANQUE_S: f64 = 240.0;
/// Tope de toda la escalera de intentos de arranque
pub const ESPERA_TOTAL_S: f64 = 600.0;

fn ahora() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

fn umbral_de(modo: &str) -> Option<Option<f64>> {
    MODOS.iter().find(|(m, _)| *m == modo).map(|(_, u)| *u)
}

/// `estimar_estado_mb`: MB que ocupará en disco el estado tras leer `tokens`
pub fn estimar_estado_mb(tokens: i64) -> f64 {
    (tokens.max(0) as f64 * BYTES_POR_TOKEN_ESTADO + BYTES_FIJOS_ESTADO) / 1e6
}

// ---------------------------------------------------------------------------------------------- rutas

/// Dónde vive cada cosa (en las pruebas, carpetas temporales)
#[derive(Clone, Debug)]
pub struct Rutas {
    pub lib: PathBuf,
    pub servidor: PathBuf,
    pub lista: PathBuf,
    pub registro: PathBuf,
    pub proyectos: PathBuf,
    pub modelos_prig: PathBuf,
    /// La carpeta de modelos de Ollama (`OLLAMA_MODELS` o `~/.ollama/models`)
    pub ollama: PathBuf,
}

impl Rutas {
    pub fn de_prig(raiz: &Path) -> Rutas {
        let casa = PathBuf::from(prig_plataforma::py::expanduser("~"));
        let lib = raiz.join("lib/moe");
        Rutas {
            servidor: lib.join("llama-server"),
            lib,
            lista: raiz.join("backend/recursos/nativo/moe/qwen36_calientes.txt"),
            registro: casa.join(".prig_moe.log"),
            proyectos: casa.join(".cache/prig-moe/proyectos"),
            modelos_prig: casa.join(".cache/prig-moe/modelos"),
            ollama: std::env::var("OLLAMA_MODELS").ok().filter(|v| !v.is_empty()).map(PathBuf::from).unwrap_or_else(|| casa.join(".ollama/models")),
        }
    }

    /// `blob_del_modelo`: el GGUF que descargó Ollama (hf.co/Elsephire/…:Q4_K_S)
    pub fn blob_del_modelo(&self) -> Option<PathBuf> {
        let mut m = self.ollama.join("manifests");
        for p in MODELO_OLLAMA {
            m = m.join(p);
        }
        let Valor::Mapa(doc) = prig_plataforma::json::leer(&std::fs::read_to_string(m).ok()?).ok()? else { return None };
        for capa in doc.lista("layers").unwrap_or(&[]) {
            let Valor::Mapa(c) = capa else { continue };
            if c.get("mediaType").map(|v| v.texto_py()).unwrap_or_default().ends_with(".model") {
                let r = self.ollama.join("blobs").join(c.get("digest").map(|v| v.texto_py()).unwrap_or_default().replace(':', "-"));
                return r.is_file().then_some(r);
            }
        }
        None
    }

    /// `modelo_para`: el híbrido con núcleo Q8 si existe (y terminó de construirse); si no, el Q4 de Ollama
    pub fn modelo_para(&self, nucleo: Option<&str>) -> Option<PathBuf> {
        if nucleo.unwrap_or(NUCLEO) == "q8" {
            let r = self.modelos_prig.join(ARCHIVO_NUCLEO_Q8);
            if r.is_file() && !PathBuf::from(format!("{}.partes", r.display())).exists() {
                return Some(r);
            }
        }
        self.blob_del_modelo()
    }

    /// `lista_global`: la lista caliente global, por capa del más al menos usado
    pub fn lista_global(&self) -> Vec<Vec<i64>> {
        let Ok(t) = std::fs::read_to_string(&self.lista) else { return Vec::new() };
        let mut capas = Vec::new();
        for l in t.lines() {
            let partes: Vec<&str> = l.split_whitespace().collect();
            if partes.is_empty() {
                continue;
            }
            match partes[1..].iter().map(|x| x.parse::<i64>()).collect::<Result<Vec<_>, _>>() {
                Ok(v) => capas.push(v),
                Err(_) => return capas,
            }
        }
        capas
    }

    fn version(&self) -> String {
        std::fs::read_to_string(self.lib.join("VERSION")).unwrap_or_default()
    }
}

/// `mb_por_caliente`: MB de un experto caliente más en cada capa (+0,8 % de alineación)
pub fn mb_por_caliente(gguf: Option<&Path>) -> f64 {
    let expertos = gguf.map(|g| moe::tamanos_gguf(&g.to_string_lossy()).0).unwrap_or(0);
    if expertos > 0 { expertos as f64 / 1048576.0 * 1.008 } else { moe::MB_POR_CALIENTE }
}

/// `mb_nucleo_extra`: VRAM de más del núcleo de este GGUF frente al Q4
pub fn mb_nucleo_extra(gguf: Option<&Path>, q4: Option<&Path>) -> f64 {
    let t = |g: Option<&Path>| g.map(|g| moe::tamanos_gguf(&g.to_string_lossy()).1).unwrap_or(0);
    let (propio, base) = (t(gguf), t(q4));
    if propio > 0 && base > 0 { ((propio - base) as f64 / 1048576.0 * 1.008).max(0.0) } else { 0.0 }
}

// ---------------------------------------------------------------------------------------------- sistema

/// `nucleos_rendimiento`: un hilo lógico por núcleo P
pub fn nucleos_rendimiento() -> Vec<i64> {
    let eficientes = prig_recursos::ritmo::nucleos_eficientes();
    let mut cpus: Vec<i64> = std::fs::read_dir("/sys/devices/system/cpu")
        .map(|l| {
            l.flatten()
                .filter_map(|e| e.file_name().to_str().and_then(|n| n.strip_prefix("cpu")).and_then(|n| n.parse::<i64>().ok()))
                .collect()
        })
        .unwrap_or_default();
    cpus.sort();
    let mut vistos = std::collections::HashSet::new();
    let mut elegidos = Vec::new();
    for cpu in cpus {
        if eficientes.contains(&cpu) {
            continue;
        }
        let hermanos = std::fs::read_to_string(format!("/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list"))
            .map(|t| t.trim().to_string())
            .unwrap_or_else(|_| cpu.to_string());
        if vistos.insert(hermanos) {
            elegidos.push(cpu);
        }
    }
    elegidos
}

/// `vram_libre_mb` (nvidia-smi: solo lee)
pub fn vram_libre_mb() -> Option<f64> {
    let s = Command::new("nvidia-smi").args(["--query-gpu=memory.free", "--format=csv,noheader,nounits"]).stderr(Stdio::null()).output().ok()?;
    String::from_utf8_lossy(&s.stdout).split_whitespace().next()?.parse().ok()
}

/// `vram_libre_estable`: la VRAM libre cuando deja de cambiar (Ollama tarda en soltar un modelo)
pub fn vram_libre_estable(espera_max: f64) -> Option<f64> {
    let t0 = Instant::now();
    let mut previa = vram_libre_mb();
    while t0.elapsed().as_secs_f64() < espera_max {
        std::thread::sleep(Duration::from_millis(500));
        let a = vram_libre_mb();
        match (a, previa) {
            (None, _) | (_, None) => return a,
            (Some(x), Some(p)) if (x - p).abs() < 50.0 && t0.elapsed().as_secs_f64() >= 1.0 => return a,
            _ => previa = a,
        }
    }
    previa
}

/// Disco libre (MB) en `carpeta` (o en el HOME, si todavía no existe)
pub fn libre_mb(carpeta: &Path) -> Option<i64> {
    let c = if carpeta.is_dir() { carpeta.to_path_buf() } else { PathBuf::from(prig_plataforma::py::expanduser("~")) };
    libre_bytes(&c).map(|b| (b / 1e6) as i64)
}

fn libre_bytes(c: &Path) -> Option<f64> {
    let cs = std::ffi::CString::new(c.to_string_lossy().as_bytes()).ok()?;
    // SAFETY: statvfs escribe en la estructura que se le da
    unsafe {
        let mut s: libc::statvfs = std::mem::zeroed();
        (libc::statvfs(cs.as_ptr(), &mut s) == 0).then_some(s.f_bavail as f64 * s.f_frsize as f64)
    }
}

fn bins(carpeta: &Path) -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = std::fs::read_dir(carpeta)
        .map(|l| l.flatten().map(|e| e.path()).filter(|p| p.extension().is_some_and(|x| x == "bin")).collect())
        .unwrap_or_default();
    v.sort();
    v
}

/// `proyectos_guardados`
pub fn proyectos_guardados(carpeta: &Path) -> Mapa {
    let b = bins(carpeta);
    let total: u64 = b.iter().filter_map(|a| std::fs::metadata(a).ok()).map(|m| m.len()).sum();
    Mapa::new()
        .con("archivos", b.len() as i128)
        .con("mb", (total as f64 / 1e6).round_ties_even() as i128)
        .con("carpeta", carpeta.to_string_lossy().into_owned())
}

fn sin_bin(a: &Path) -> PathBuf {
    let s = a.to_string_lossy();
    PathBuf::from(format!("{}.calientes.json", &s[..s.len() - 4]))
}

/// `podar_proyectos`: borra los usados hace más tiempo hasta quedar bajo el límite y, si el disco tiene menos libre
/// que la reserva, hasta recuperar la diferencia
pub fn podar_proyectos(carpeta: &Path, limite_mb: f64, reserva_mb: f64) -> usize {
    let mut archivos: Vec<(SystemTime, u64, PathBuf)> = bins(carpeta)
        .into_iter()
        .filter_map(|a| {
            let m = std::fs::metadata(&a).ok()?;
            Some((m.modified().ok()?, m.len(), a))
        })
        .collect();
    let mut total: f64 = archivos.iter().map(|a| a.1 as f64).sum();
    let mut falta = 0.0;
    if reserva_mb > 0.0 && !archivos.is_empty() {
        falta = libre_bytes(carpeta).map(|l| (reserva_mb * 1e6 - l).max(0.0)).unwrap_or(0.0);
    }
    let objetivo = (limite_mb.max(0.0) * 1e6).min(total - falta);
    archivos.sort();
    let mut borrados = 0;
    for (_, tam, a) in archivos {
        if total <= objetivo {
            break;
        }
        if std::fs::remove_file(&a).is_ok() {
            total -= tam as f64;
            borrados += 1;
        }
        let _ = std::fs::remove_file(sin_bin(&a));
    }
    borrados
}

// ---------------------------------------------------------------------------------------------- lanzador

/// Lanza procesos desde un hilo que no termina nunca: `PR_SET_PDEATHSIG` va ligado al hilo que hace el fork
struct Lanzador {
    tx: Mutex<mpsc::Sender<(Command, mpsc::Sender<std::io::Result<Child>>)>>,
}

fn lanzador() -> &'static Lanzador {
    static L: std::sync::OnceLock<Lanzador> = std::sync::OnceLock::new();
    L.get_or_init(|| {
        let (tx, rx) = mpsc::channel::<(Command, mpsc::Sender<std::io::Result<Child>>)>();
        std::thread::Builder::new()
            .name("moe-lanzador".into())
            .spawn(move || {
                for (mut c, resp) in rx {
                    let _ = resp.send(c.spawn());
                }
            })
            .expect("hilo lanzador del motor MoE");
        Lanzador { tx: Mutex::new(tx) }
    })
}

pub fn lanzar(mut c: Command) -> std::io::Result<Child> {
    use std::os::unix::process::CommandExt;
    // SAFETY: setsid y prctl en el hijo antes de exec. Su propia sesión (como start_new_session): las señales al grupo
    // de Prig no le llegan; y PDEATHSIG: si Prig muere, el kernel le manda SIGTERM (no se queda con la VRAM)
    unsafe {
        c.pre_exec(|| {
            libc::setsid();
            libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
            Ok(())
        });
    }
    let (tx, rx) = mpsc::channel();
    lanzador().tx.lock().unwrap().send((c, tx)).map_err(|_| std::io::Error::other("lanzador cerrado"))?;
    rx.recv().map_err(|_| std::io::Error::other("lanzador cerrado"))?
}

// ---------------------------------------------------------------------------------------------- HTTP

fn cliente(timeout: f64) -> reqwest::blocking::Client {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs_f64(timeout))
        .connect_timeout(Duration::from_secs_f64(timeout.min(30.0)))
        .build()
        .expect("cliente HTTP")
}

/// (estado, JSON) de una petición a llama-server
fn http(metodo: &str, url: &str, cuerpo: Option<&Valor>, timeout: f64) -> Result<(u16, Valor), String> {
    let c = cliente(timeout);
    let mut r = match metodo {
        "GET" => c.get(url),
        "DELETE" => c.delete(url),
        _ => c.post(url),
    };
    if let Some(b) = cuerpo {
        r = r.header("Content-Type", "application/json").body(prig_plataforma::json::escribir_compacto(b));
    }
    let r = r.send().map_err(|e| e.to_string())?;
    let estado = r.status().as_u16();
    let b = r.bytes().map_err(|e| e.to_string())?;
    let v = if b.is_empty() { Valor::Mapa(Mapa::new()) } else { prig_plataforma::json::leer(&String::from_utf8_lossy(&b)).unwrap_or(Valor::Texto(String::from_utf8_lossy(&b).into_owned())) };
    Ok((estado, v))
}

// ---------------------------------------------------------------------------------------------- motor

pub type Ajustes = Arc<dyn Fn() -> Mapa + Send + Sync>;
/// (comando, cambios del entorno: None = quitar, modo)
pub type Orden = (Vec<String>, Vec<(String, Option<String>)>, String);

/// Sustitutos para las pruebas: lanzar (calientes, mtp) → ¿arrancó?, la VRAM libre y el modelo disponible
#[derive(Default, Clone)]
pub struct Ganchos {
    pub lanzar: Option<Arc<dyn Fn(i64, bool) -> bool + Send + Sync>>,
    pub vram: Option<Option<f64>>,
    pub modelo: Option<PathBuf>,
}
pub type Liberar = Arc<dyn Fn() + Send + Sync>;

pub struct Estado {
    proc: Option<Child>,
    pub puerto: Option<u16>,
    pub calientes: i64,
    pub mtp: bool,
    pub modo: String,
    pub modelo: Option<PathBuf>,
    pub contexto: i64,
    contexto_pedido: i64,
    proyecto_cargado: Option<String>,
    pub lista_actual: Option<String>,
    pub ultimo_proyecto: Mapa,
    pub nucleos: Vec<i64>,
    pub activas: i64,
    ultimo_uso: f64,
    pub keep_alive_s: f64,
    pub ultimo_error: String,
    vigia: bool,
}

pub struct Motor {
    pub rutas: Rutas,
    ajustes: Mutex<Ajustes>,
    liberar: Mutex<Option<Liberar>>,
    e: Mutex<Estado>,
    /// Para las pruebas: con un llama-server ya en marcha (falso), no se lanza ni se para nada
    externo: bool,
    pub ganchos: Mutex<Ganchos>,
}

/// Lo que devuelve una petición de Ollama al motor
pub enum Respuesta {
    /// (estado, objeto de Ollama o `{"error": ...}`)
    Entera(u16, Valor),
    /// El flujo NDJSON; al soltar la guarda se descuenta la petición
    Flujo(moe::Flujo, Guarda),
}

/// Cuenta una petición activa mientras vive (el vigía no para el motor con una respuesta en curso)
pub struct Guarda {
    motor: Arc<Motor>,
}

impl Drop for Guarda {
    fn drop(&mut self) {
        let mut e = self.motor.estado_mut();
        e.activas = (e.activas - 1).max(0);
        e.ultimo_uso = ahora();
    }
}

fn error(estado: u16, mensaje: &str) -> Respuesta {
    Respuesta::Entera(estado, Valor::Mapa(Mapa::new().con("error", mensaje)))
}

impl Motor {
    pub fn new(rutas: Rutas, ajustes: Ajustes) -> Arc<Motor> {
        Arc::new(Motor {
            rutas,
            ajustes: Mutex::new(ajustes),
            liberar: Mutex::new(None),
            e: Mutex::new(Estado {
                proc: None,
                puerto: None,
                calientes: 0,
                mtp: false,
                modo: MODO.into(),
                modelo: None,
                contexto: moe::CONTEXTO_INICIAL,
                contexto_pedido: moe::CONTEXTO_INICIAL,
                proyecto_cargado: None,
                lista_actual: None,
                ultimo_proyecto: Mapa::new(),
                nucleos: Vec::new(),
                activas: 0,
                ultimo_uso: 0.0,
                keep_alive_s: 300.0,
                ultimo_error: String::new(),
                vigia: false,
            }),
            externo: false,
            ganchos: Mutex::new(Ganchos::default()),
        })
    }

    /// Para las pruebas: un motor que habla con un llama-server ya en marcha en `puerto`
    pub fn con_servidor(rutas: Rutas, ajustes: Ajustes, puerto: u16) -> Arc<Motor> {
        let m = Motor::new(rutas, ajustes);
        let mut m = Arc::try_unwrap(m).ok().expect("recién creado");
        m.externo = true;
        m.e.get_mut().unwrap().puerto = Some(puerto);
        Arc::new(m)
    }

    pub fn poner_ajustes(&self, a: Ajustes) {
        *self.ajustes.lock().unwrap() = a;
    }
    pub fn poner_liberar(&self, l: Option<Liberar>) {
        *self.liberar.lock().unwrap() = l;
    }
    fn ajustes(&self) -> Mapa {
        let f = self.ajustes.lock().unwrap().clone();
        f()
    }
    pub fn estado_mut(&self) -> MutexGuard<'_, Estado> {
        self.e.lock().unwrap_or_else(|e| e.into_inner())
    }

    // -- estado ------------------------------------------------------------------------------------------------------

    /// `contexto_deseado`: el de los ajustes o, en automático, el que pidió la petición más grande
    fn contexto_deseado(a: &Mapa, pedido: i64) -> i64 {
        match a.get("contexto") {
            None | Some(Valor::Nulo) => moe::CONTEXTO_INICIAL.max(pedido),
            Some(Valor::Texto(t)) if t.is_empty() || t == "auto" => moe::CONTEXTO_INICIAL.max(pedido),
            Some(v) => match v.entero().or_else(|| v.texto_py().trim().parse::<i128>().ok()) {
                Some(n) => (n as i64).clamp(2048, moe::CONTEXTO_MAX),
                None => moe::CONTEXTO_INICIAL.max(pedido),
            },
        }
    }

    pub fn contexto_actual_deseado(&self) -> i64 {
        let a = self.ajustes();
        Self::contexto_deseado(&a, self.estado_mut().contexto_pedido)
    }

    fn automatico(a: &Mapa) -> bool {
        matches!(a.get("contexto"), None | Some(Valor::Nulo)) || matches!(a.get("contexto"), Some(Valor::Texto(t)) if t.is_empty() || t == "auto")
    }

    /// `disponible`
    pub fn disponible(&self) -> Mapa {
        let servidor = self.externo || std::fs::metadata(&self.rutas.servidor).is_ok_and(|m| {
            use std::os::unix::fs::PermissionsExt;
            m.permissions().mode() & 0o111 != 0
        });
        let blob = self.rutas.blob_del_modelo();
        let motivo = if !servidor {
            Valor::Texto("Falta compilar el motor: backend/recursos/nativo/moe/compilar.sh".into())
        } else if blob.is_none() && !self.externo {
            Valor::Texto(format!("Falta el modelo: ollama pull {}:{}", MODELO_OLLAMA[..3].join("/"), MODELO_OLLAMA[3]))
        } else {
            Valor::Nulo
        };
        Mapa::new()
            .con("disponible", motivo.es_nulo())
            .con("motivo", motivo)
            .con("servidor", servidor)
            .con("modelo", blob.map(|b| Valor::Texto(b.to_string_lossy().into_owned())).unwrap_or(Valor::Nulo))
    }

    fn vivo(e: &mut Estado) -> bool {
        match e.proc.as_mut() {
            Some(c) => c.try_wait().ok().flatten().is_none(),
            None => false,
        }
    }

    pub fn en_marcha(&self) -> bool {
        self.externo || Self::vivo(&mut self.estado_mut())
    }

    pub fn pid(&self) -> Option<u32> {
        let mut e = self.estado_mut();
        if Self::vivo(&mut e) { e.proc.as_ref().map(|c| c.id()) } else { None }
    }

    pub fn generando(&self) -> bool {
        let mut e = self.estado_mut();
        (self.externo || Self::vivo(&mut e)) && e.activas > 0
    }

    /// `estado()`: lo que enseña el panel de recursos
    pub fn estado(&self) -> Mapa {
        let disp = self.disponible();
        let blob = self.rutas.blob_del_modelo();
        let q8 = self.rutas.modelo_para(Some("q8"));
        let tope = self.tope_cache_mb();
        let reserva = self.reserva_mb();
        let mut e = self.estado_mut();
        let vivo = self.externo || Self::vivo(&mut e);
        let pid = if vivo { e.proc.as_ref().map(|c| Valor::Entero(c.id() as i128)).unwrap_or(Valor::Nulo) } else { Valor::Nulo };
        let mut m = disp;
        m.poner("nombre", moe::NOMBRE);
        m.poner("en_marcha", vivo);
        m.poner("pid", pid);
        m.poner("puerto", if vivo { e.puerto.map(|p| Valor::Entero(p as i128)).unwrap_or(Valor::Nulo) } else { Valor::Nulo });
        m.poner("calientes_por_capa", e.calientes as i128);
        m.poner("mtp", e.mtp);
        m.poner("modo", e.modo.clone());
        m.poner("nucleo", if e.modelo.is_some() && e.modelo != blob { "q8" } else { "q4" });
        m.poner("nucleo_q8_disponible", q8 != blob);
        m.poner("contexto", e.contexto as i128);
        m.poner("nucleos", Valor::Lista(e.nucleos.iter().map(|n| Valor::Entero(*n as i128)).collect()));
        m.poner("activas", e.activas as i128);
        m.poner("keep_alive_s", Valor::Real(e.keep_alive_s));
        m.poner("ultimo_error", e.ultimo_error.clone());
        m.poner("version", self.rutas.version().trim().to_string());
        let mut p = proyectos_guardados(&self.rutas.proyectos);
        p.poner("ultimo", Valor::Mapa(e.ultimo_proyecto.clone()));
        p.poner("tope_mb", Valor::Real(tope));
        p.poner("reserva_mb", Valor::Real(reserva));
        p.poner("libre_mb", libre_mb(&self.rutas.proyectos).map(|x| Valor::Entero(x as i128)).unwrap_or(Valor::Nulo));
        m.poner("proyectos", p);
        m
    }

    // -- caché de estados --------------------------------------------------------------------------------------------

    /// `tope_cache_mb`: `moe_cache_gb` (0 = no se guarda ninguno); sin ajuste o inválido, `PROYECTOS_MAX_MB`
    pub fn tope_cache_mb(&self) -> f64 {
        match self.ajustes().get("cache_gb") {
            None | Some(Valor::Nulo) => PROYECTOS_MAX_MB,
            Some(Valor::Texto(t)) if t.is_empty() => PROYECTOS_MAX_MB,
            Some(v) => v.num().or_else(|| v.texto_py().trim().parse().ok()).map(|x: f64| x.max(0.0) * 1000.0).unwrap_or(PROYECTOS_MAX_MB),
        }
    }

    /// `reserva_mb`: disco libre que el caché nunca toca (`moe_cache_reserva_gb`)
    pub fn reserva_mb(&self) -> f64 {
        match self.ajustes().get("cache_reserva_gb") {
            None | Some(Valor::Nulo) => 0.0,
            Some(Valor::Texto(t)) if t.is_empty() => 0.0,
            Some(v) => v.num().or_else(|| v.texto_py().trim().parse().ok()).map(|x: f64| x.max(0.0) * 1000.0).unwrap_or(0.0),
        }
    }

    pub fn podar(&self) -> usize {
        podar_proyectos(&self.rutas.proyectos, self.tope_cache_mb(), self.reserva_mb())
    }

    // -- ciclo de vida -----------------------------------------------------------------------------------------------

    fn registro(&self, texto: &str) {
        use std::io::Write;
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&self.rutas.registro) {
            let _ = writeln!(f, "{} {texto}", prig_plataforma::py::ahora_iso().replace('T', " ").chars().take(19).collect::<String>());
        }
    }

    fn puerto_libre() -> u16 {
        std::net::TcpListener::bind("127.0.0.1:0").and_then(|l| l.local_addr()).map(|a| a.port()).unwrap_or(0)
    }

    /// `orden`: comando, cambios del entorno (None = quitar) y modo con que se lanza llama-server
    pub fn orden(&self, e: &mut Estado, blob: &Path, calientes: i64, mtp: bool) -> Orden {
        let a = self.ajustes();
        e.contexto = Self::contexto_deseado(&a, e.contexto_pedido);
        let lote = moe::lote_para(e.contexto);
        e.nucleos = nucleos_rendimiento();
        let hilos = a.get("hilos").and_then(|h| h.entero()).filter(|h| *h > 0).map(|h| h as usize).unwrap_or_else(|| if e.nucleos.is_empty() { 4 } else { e.nucleos.len().min(4) });
        e.puerto = Some(Self::puerto_libre());
        let s = |x: &str| x.to_string();
        let mut cmd = vec![
            self.rutas.servidor.to_string_lossy().into_owned(), s("-m"), blob.to_string_lossy().into_owned(), s("-ngl"), s("99"),
            s("--n-cpu-moe"), s("99"), s("-c"), e.contexto.to_string(), s("-t"), hilos.to_string(), s("-tb"), hilos.to_string(),
            s("--no-mmap"), s("-fa"), s("on"), s("--jinja"), s("-np"), s("1"), s("--host"), s("127.0.0.1"), s("--port"),
            e.puerto.unwrap_or(0).to_string(), s("--no-webui"), s("-ub"), lote.to_string(), s("-b"), lote.to_string(),
            s("-ctk"), s("q8_0"), s("-ctv"), s("q8_0"), s("--cache-ram"), CACHE_RAM_MB.to_string(),
            s("--slot-save-path"), self.rutas.proyectos.to_string_lossy().into_owned(),
        ];
        let _ = std::fs::create_dir_all(&self.rutas.proyectos);
        if mtp {
            cmd.extend([s("--spec-type"), s("draft-mtp"), s("--spec-draft-n-max"), s("2")]);
        }
        let mut env: Vec<(String, Option<String>)> = vec![(s("LD_LIBRARY_PATH"), None)];
        for (k, _) in std::env::vars() {
            if k.starts_with("AIPC_") {
                env.push((k, None));
            }
        }
        let modo = a.get("modo").map(|m| m.texto_py()).filter(|m| !m.is_empty() && m != "None").unwrap_or_else(|| MODO.into());
        let modo = if umbral_de(&modo).is_some() { modo } else { MODO.into() };
        if calientes > 0 {
            for (k, v) in [
                ("AIPC_MOE_HOT_LIST", self.rutas.lista.to_string_lossy().into_owned()),
                ("AIPC_MOE_HOT_N", calientes.to_string()),
                ("AIPC_NO_PAD", s("1")),
                ("AIPC_COLD_SKIP", s("1")),
                ("AIPC_OVERLAP", s("1")),
                ("AIPC_CONTAR", s("1")),
            ] {
                env.push((k.into(), Some(v)));
            }
            if let Some(Some(u)) = umbral_de(&modo) {
                env.push((s("AIPC_COLD_DROP"), Some(prig_plataforma::valor::repr_real(u))));
            }
        }
        let nucleos: Vec<i64> = e.nucleos.iter().take(hilos).copied().collect();
        if !nucleos.is_empty() && which("taskset") {
            let mut c = vec![s("taskset"), s("-c"), nucleos.iter().map(|n| n.to_string()).collect::<Vec<_>>().join(",")];
            c.extend(cmd);
            cmd = c;
        }
        self.registro(&format!(
            "arranque: {calientes} calientes/capa, contexto {}, núcleos {:?}, MTP {}, modo {modo}",
            e.contexto,
            nucleos,
            if mtp { "sí" } else { "no" }
        ));
        (cmd, env, modo)
    }

    /// `_lanzar`: arranca y espera a /health (hasta `limite`)
    fn lanzar_con(&self, e: &mut Estado, blob: &Path, calientes: i64, mtp: bool, limite: Instant) -> bool {
        let (cmd, env, modo) = self.orden(e, blob, calientes, mtp);
        let mut c = Command::new(&cmd[0]);
        c.args(&cmd[1..]).stdin(Stdio::null());
        for (k, v) in env {
            match v {
                Some(v) => c.env(k, v),
                None => c.env_remove(k),
            };
        }
        if let Ok(f) = std::fs::OpenOptions::new().create(true).append(true).open(&self.rutas.registro) {
            if let Ok(f2) = f.try_clone() {
                c.stdout(f).stderr(f2);
            }
        }
        match lanzar(c) {
            Ok(h) => e.proc = Some(h),
            Err(x) => {
                self.registro(&format!("no se pudo lanzar: {x}"));
                return false;
            }
        }
        let puerto = e.puerto.unwrap_or(0);
        let fin = limite.min(Instant::now() + Duration::from_secs_f64(ESPERA_ARRANQUE_S));
        while Instant::now() < fin {
            if !Self::vivo(e) {
                return false;
            }
            if matches!(http("GET", &format!("http://127.0.0.1:{puerto}/health"), None, 2.0), Ok((200, _))) {
                e.calientes = calientes;
                e.mtp = mtp;
                e.modo = modo;
                e.modelo = Some(blob.to_path_buf());
                e.lista_actual = None; // servidor nuevo: vuelve la lista global
                e.proyecto_cargado = None;
                return true;
            }
            std::thread::sleep(Duration::from_millis(500));
        }
        Self::parar(e);
        false
    }

    /// `asegurar`: arranca el servidor si hace falta; los segundos de carga (0 si ya estaba)
    fn asegurar_en(self: &Arc<Self>, e: &mut Estado) -> Result<f64, String> {
        if self.externo || Self::vivo(e) {
            return Ok(0.0);
        }
        let g = self.ganchos.lock().unwrap().clone();
        let disp = self.disponible();
        if !disp.verdad("disponible") && g.modelo.is_none() {
            return Err(disp.texto("motivo").unwrap_or_default().to_string());
        }
        let t0 = Instant::now();
        let limite = t0 + Duration::from_secs_f64(ESPERA_TOTAL_S);
        if let Some(l) = self.liberar.lock().unwrap().clone() {
            l();
        }
        let a = self.ajustes();
        let contexto = Self::contexto_deseado(&a, e.contexto_pedido);
        let mtp = !matches!(a.get("mtp"), Some(Valor::Bool(false)));
        let modelo = g.modelo.clone().or_else(|| self.rutas.modelo_para(a.get("nucleo").map(|n| n.texto_py()).filter(|n| !n.is_empty() && n != "None").as_deref()));
        let Some(modelo) = modelo else { return Err("Falta el modelo".into()) };
        let pedido = a.get("calientes").cloned().unwrap_or(Valor::Nulo);
        let automatico = matches!(&pedido, Valor::Nulo) || matches!(&pedido, Valor::Texto(t) if t.is_empty() || t == "auto");
        let libre = if automatico { g.vram.unwrap_or_else(|| vram_libre_estable(8.0)) } else { None };
        let q4 = self.rutas.blob_del_modelo();
        let mut intentos: Vec<(i64, bool)> = Vec::new();
        let opciones: &[bool] = if mtp && moe::cabe_mtp(libre, contexto) { &[true, false] } else { &[false] };
        for &con in opciones {
            let n = if automatico {
                moe::calientes_para(libre, contexto, con, mb_por_caliente(Some(&modelo)), mb_nucleo_extra(Some(&modelo), q4.as_deref()))
            } else {
                pedido.entero().map(|x| x as i64).or_else(|| pedido.texto_py().trim().parse().ok()).unwrap_or(0)
            };
            intentos.push((n, con));
            intentos.push(((n - 8).max(0), con));
        }
        intentos.push((0, false));
        let mut vistos = Vec::new();
        for (n, con) in intentos {
            if vistos.contains(&(n, con)) {
                continue;
            }
            vistos.push((n, con));
            if Instant::now() >= limite {
                self.registro("arranque: se agotó el tiempo total");
                break;
            }
            let arranco = match &g.lanzar {
                Some(f) => f(n, con),
                None => self.lanzar_con(e, &modelo, n, con, limite),
            };
            if arranco {
                e.ultimo_error.clear();
                e.ultimo_uso = ahora(); // el keep-alive cuenta desde el arranque
                self.arrancar_vigia(e);
                let _ = self.podar();
                return Ok(t0.elapsed().as_secs_f64());
            }
            self.registro(&format!("no arrancó con {n} calientes/capa{}", if con { " y MTP" } else { "" }));
        }
        e.ultimo_error = format!("llama-server no arrancó (ver {})", self.rutas.registro.display());
        Err(e.ultimo_error.clone())
    }

    pub fn asegurar(self: &Arc<Self>) -> Result<f64, String> {
        let mut e = self.estado_mut();
        self.asegurar_en(&mut e)
    }

    fn parar(e: &mut Estado) {
        let Some(mut c) = e.proc.take() else { return };
        let pid = c.id() as i32;
        // SAFETY: señales a un hijo propio (por si el modo frío lo dejó en pausa)
        unsafe {
            libc::kill(pid, libc::SIGCONT);
            libc::kill(pid, libc::SIGTERM);
        }
        let t0 = Instant::now();
        while t0.elapsed() < Duration::from_secs(15) {
            if c.try_wait().ok().flatten().is_some() {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = c.kill();
        let _ = c.wait();
    }

    pub fn detener(&self) {
        let mut e = self.estado_mut();
        if e.proc.is_some() {
            self.registro("parado");
        }
        Self::parar(&mut e);
    }

    fn arrancar_vigia(self: &Arc<Self>, e: &mut Estado) {
        if e.vigia {
            return;
        }
        e.vigia = true;
        let m = Arc::downgrade(self);
        std::thread::Builder::new()
            .name("motor-moe-vigia".into())
            .spawn(move || loop {
                std::thread::sleep(Duration::from_secs(5));
                let Some(m) = m.upgrade() else { return };
                let mut e = m.estado_mut();
                if !Self::vivo(&mut e) {
                    e.vigia = false;
                    return;
                }
                if e.activas == 0 && e.keep_alive_s >= 0.0 && ahora() - e.ultimo_uso > e.keep_alive_s {
                    m.registro(&format!("sin uso durante {:.0} s", e.keep_alive_s));
                    Self::parar(&mut e);
                    e.vigia = false;
                    return;
                }
            })
            .ok();
    }

    /// `_crecer`: contexto automático; si la petición no cabe, se reinicia con uno mayor
    fn crecer(&self, objetivo: i64) -> bool {
        let mut e = self.estado_mut();
        let vivo = self.externo || Self::vivo(&mut e);
        if objetivo <= e.contexto_pedido && (!vivo || e.contexto >= objetivo) {
            return false;
        }
        e.contexto_pedido = e.contexto_pedido.max(objetivo);
        if vivo && e.contexto < objetivo {
            if e.activas > 0 || self.externo {
                return false; // otra respuesta en curso: no se corta
            }
            self.registro(&format!("contexto {} → {objetivo}: reinicio", e.contexto));
            Self::parar(&mut e);
        }
        true
    }

    // -- proyectos ---------------------------------------------------------------------------------------------------

    fn base(&self) -> String {
        format!("http://127.0.0.1:{}", self.estado_mut().puerto.unwrap_or(0))
    }

    /// `_preparar_proyecto`: deja el motor con el estado exacto tras leer el proyecto (restaurado de disco o leído y
    /// guardado). None si la conversación no empieza con un bloque grande
    fn preparar_proyecto(&self, cuerpo: &Mapa) -> Option<Mapa> {
        let prefijo = moe::prefijo_de(&Valor::Mapa(cuerpo.clone())).ok()??;
        let tope = self.tope_cache_mb();
        if tope <= 0.0 {
            return None;
        }
        let base = self.base();
        let plantilla = Mapa::new()
            .con("messages", Valor::Lista(prefijo))
            .con("tools", cuerpo.get("tools").cloned().unwrap_or(Valor::Nulo))
            .con("add_generation_prompt", false)
            .con("chat_template_kwargs", cuerpo.get("chat_template_kwargs").filter(|v| v.verdad()).cloned().unwrap_or(Valor::Mapa(Mapa::new())));
        let texto = match http("POST", &format!("{base}/apply-template"), Some(&Valor::Mapa(plantilla)), 60.0) {
            Ok((200, Valor::Mapa(m))) => m.texto("prompt").filter(|t| !t.is_empty()).map(String::from),
            _ => None,
        }?;
        let (modelo, modo, calientes, cargado) = {
            let e = self.estado_mut();
            (e.modelo.as_ref().map(|m| m.to_string_lossy().into_owned()).unwrap_or_else(|| "None".into()), e.modo.clone(), e.calientes, e.proyecto_cargado.clone())
        };
        let mut h = Sha256::new();
        h.update(format!("{}|{modelo}|{modo}|", self.rutas.version()).as_bytes());
        h.update(texto.as_bytes());
        let clave: String = h.finalize().iter().map(|b| format!("{b:02x}")).collect::<String>()[..32].to_string();
        let archivo = format!("{clave}.bin");
        let ruta = self.rutas.proyectos.join(&archivo);
        if cargado.as_deref() == Some(clave.as_str()) {
            return None; // ya está justo al final del proyecto
        }
        let t0 = Instant::now();
        let nombre = Valor::Mapa(Mapa::new().con("filename", archivo.clone()));
        if ruta.exists() {
            if let Ok((200, r)) = http("POST", &format!("{base}/slots/0?action=restore"), Some(&nombre), 600.0) {
                if let Ok(f) = std::fs::File::options().write(true).open(&ruta) {
                    let _ = f.set_modified(SystemTime::now()); // usado ahora: el último en borrarse
                }
                self.estado_mut().proyecto_cargado = Some(clave.clone());
                self.aplicar_calientes(&clave);
                let p = Mapa::new()
                    .con("origen", "disco")
                    .con("tokens", match &r { Valor::Mapa(m) => m.get("n_restored").cloned().unwrap_or(Valor::Nulo), _ => Valor::Nulo })
                    .con("segundos", Valor::Real(prig_plataforma::valor::redondear(t0.elapsed().as_secs_f64(), 2)))
                    .con("clave", clave.clone());
                self.estado_mut().ultimo_proyecto = p.clone();
                self.registro(&format!("proyecto {} restaurado: {}", &clave[..8], prig_plataforma::json::escribir_compacto(&Valor::Mapa(p.clone()))));
                return Some(p);
            }
            let _ = std::fs::remove_file(&ruta); // no se pudo restaurar (otra versión…): se vuelve a leer
        }
        if calientes > 0 {
            let _ = http("GET", &format!("{base}/aipc/uso?reset=1"), None, 30.0);
        }
        let leer = Mapa::new().con("prompt", texto).con("n_predict", 0).con("cache_prompt", true);
        let datos = match http("POST", &format!("{base}/completion"), Some(&Valor::Mapa(leer)), 7200.0) {
            Ok((200, Valor::Mapa(d))) => d,
            _ => return None,
        };
        let leidos = datos.get("tokens_evaluated").and_then(|v| v.num()).unwrap_or(0.0) as i64;
        let lectura_ms = datos.mapa("timings").and_then(|t| t.num("prompt_ms")).unwrap_or(0.0);
        let cabe = estimar_estado_mb(leidos) <= tope;
        let guardado = cabe && matches!(http("POST", &format!("{base}/slots/0?action=save"), Some(&nombre), 600.0), Ok((200, _)));
        if cabe && !guardado && http("GET", &format!("{base}/health"), None, 5.0).is_err() {
            return None;
        }
        if guardado {
            self.estado_mut().proyecto_cargado = Some(clave.clone());
            self.calientes_del_proyecto(&clave);
            self.podar();
        }
        let mut p = Mapa::new()
            .con("origen", "leido")
            .con("tokens", leidos as i128)
            .con("segundos", Valor::Real(prig_plataforma::valor::redondear(t0.elapsed().as_secs_f64(), 1)))
            .con("guardado", guardado)
            .con("clave", clave.clone());
        if !cabe {
            p.poner("motivo", "no cabe en el caché");
        }
        self.estado_mut().ultimo_proyecto = p.clone();
        self.registro(&format!("proyecto {} leído: {}", &clave[..8], prig_plataforma::json::escribir_compacto(&Valor::Mapa(p.clone()))));
        Some(p.con("leidos", leidos as i128).con("lectura_ms", Valor::Real(lectura_ms)))
    }

    /// `_calientes_del_proyecto`: los expertos más usados al leerlo pasan a la GPU y la lista se guarda
    fn calientes_del_proyecto(&self, clave: &str) {
        if self.estado_mut().calientes == 0 {
            return;
        }
        let Ok((_, Valor::Mapa(r))) = http("GET", &format!("{}/aipc/uso?reset=1", self.base()), None, 30.0) else { return };
        let uso: Vec<Vec<i64>> = r
            .lista("capas")
            .unwrap_or(&[])
            .iter()
            .map(|c| match c {
                Valor::Lista(l) => l.iter().filter_map(|x| x.entero().map(|n| n as i64)).collect(),
                _ => Vec::new(),
            })
            .collect();
        let Some(lista) = moe::lista_caliente(&uso, &self.rutas.lista_global()) else { return };
        let v = Valor::Lista(lista.iter().map(|c| Valor::Lista(c.iter().map(|x| Valor::Entero(*x as i128)).collect())).collect());
        let _ = std::fs::write(self.rutas.proyectos.join(format!("{clave}.calientes.json")), prig_plataforma::json::escribir_compacto(&v));
        self.enviar_calientes(v, clave);
    }

    fn aplicar_calientes(&self, clave: &str) {
        {
            let e = self.estado_mut();
            if e.calientes == 0 || e.lista_actual.as_deref() == Some(clave) {
                return;
            }
        }
        let Ok(t) = std::fs::read_to_string(self.rutas.proyectos.join(format!("{clave}.calientes.json"))) else { return };
        let Ok(v) = prig_plataforma::json::leer(&t) else { return };
        self.enviar_calientes(v, clave);
    }

    fn enviar_calientes(&self, lista: Valor, clave: &str) {
        let t0 = Instant::now();
        if let Ok((200, r)) = http("POST", &format!("{}/aipc/calientes", self.base()), Some(&Valor::Mapa(Mapa::new().con("capas", lista))), 120.0) {
            self.estado_mut().lista_actual = Some(clave.to_string());
            let n = match r {
                Valor::Mapa(m) => m.get("capas_cambiadas").map(|v| v.texto_o_repr()).unwrap_or_default(),
                _ => String::new(),
            };
            self.registro(&format!("calientes del proyecto {}: {n} capas en {:.2} s", &clave[..8.min(clave.len())], t0.elapsed().as_secs_f64()));
        }
    }

    /// `olvidar_proyectos`: borra los estados guardados
    pub fn olvidar_proyectos(&self) -> usize {
        let mut n = 0;
        if let Ok(l) = std::fs::read_dir(&self.rutas.proyectos) {
            for a in l.flatten().map(|e| e.path()) {
                let s = a.to_string_lossy();
                if (s.ends_with(".bin") || s.ends_with(".calientes.json")) && std::fs::remove_file(&a).is_ok() && s.ends_with(".bin") {
                    n += 1;
                }
            }
        }
        self.estado_mut().proyecto_cargado = None;
        n
    }

    // -- peticiones --------------------------------------------------------------------------------------------------

    /// `directo`: una petición cruda a llama-server (lectura por unidades). Cuenta como actividad y deja el hueco sin
    /// proyecto cargado
    pub fn directo(self: &Arc<Self>, metodo: &str, ruta: &str, cuerpo: Option<&Valor>, timeout: f64) -> Result<Valor, String> {
        {
            let mut e = self.estado_mut();
            self.asegurar_en(&mut e)?;
            e.activas += 1;
            e.ultimo_uso = ahora();
        }
        let r = http(metodo, &format!("{}{ruta}", self.base()), cuerpo, timeout);
        {
            let mut e = self.estado_mut();
            e.activas = (e.activas - 1).max(0);
            e.ultimo_uso = ahora();
            e.proyecto_cargado = None;
        }
        match r {
            Ok((200, v)) => Ok(v),
            Ok((s, v)) => Err(format!("llama-server {s} en {ruta}: {}", v.texto_o_repr().chars().take(300).collect::<String>())),
            Err(x) => Err(x),
        }
    }

    /// `post`: una petición de Ollama (/api/chat o /api/generate) servida por este motor
    pub fn post(self: &Arc<Self>, ruta: &str, pedido: &Valor, timeout: f64, reintento: bool) -> Respuesta {
        let Valor::Mapa(p) = pedido else { return error(400, "petición inválida") };
        let vacia = !p.verdad("messages") && !p.verdad("prompt");
        if vacia {
            if moe::segundos_keep_alive(p.get("keep_alive").unwrap_or(&Valor::Nulo), 300.0) == 0.0 {
                self.detener();
            } else if let Err(x) = self.asegurar() {
                return error(500, &x);
            }
            return match moe::final_(ruta, Some("stop"), &Valor::Mapa(Mapa::new()), 0.0, Vec::new(), None, &Valor::Nulo) {
                Ok(m) => Respuesta::Entera(200, Valor::Mapa(m)),
                Err(x) => error(500, &x.texto()),
            };
        }
        let automatico = Self::automatico(&self.ajustes());
        let necesarios = moe::estimar_tokens(pedido).unwrap_or(0);
        if automatico {
            let Some(objetivo) = moe::contexto_para(necesarios) else {
                let n = miles(necesarios as i64);
                return error(400, &format!("La petición necesita ~{n} tokens y el máximo del modelo es {}: divide el proyecto o pregunta por partes.", miles(moe::CONTEXTO_MAX)));
            };
            self.crecer(objetivo);
        }
        let carga_s = {
            let mut e = self.estado_mut();
            match self.asegurar_en(&mut e) {
                Ok(s) => s,
                Err(x) => return error(500, &x),
            }
        };
        {
            let mut e = self.estado_mut();
            e.activas += 1;
            e.ultimo_uso = ahora();
            let ka = e.keep_alive_s;
            e.keep_alive_s = moe::segundos_keep_alive(p.get("keep_alive").unwrap_or(&Valor::Nulo), ka);
        }
        let guarda = Guarda { motor: self.clone() };
        let (cuerpo, prefijos) = match moe::a_openai(ruta, pedido) {
            Ok(x) => x,
            Err(x) => return error(400, &x.texto()),
        };
        let proyecto = if ruta.ends_with("/api/chat") { self.preparar_proyecto(&cuerpo) } else { None };
        self.estado_mut().proyecto_cargado = None;
        let proyecto = proyecto.map(Valor::Mapa).unwrap_or(Valor::Nulo);
        let (base, contexto) = {
            let e = self.estado_mut();
            (format!("http://127.0.0.1:{}", e.puerto.unwrap_or(0)), e.contexto)
        };
        let stream = cuerpo.verdad("stream");
        let r = match moe::pedir(&format!("{base}/v1/chat/completions"), &cuerpo, stream, timeout) {
            Ok(r) => r,
            Err(x) => return error(503, &format!("El motor MoE no responde: {x}")),
        };
        match r {
            moe::Respuesta::Flujo(lector) => Respuesta::Flujo(moe::Flujo::new(lector, moe::Traductor::new(ruta, &prefijos, carga_s, Some(contexto), proyecto)), guarda),
            moe::Respuesta::Entera(200, b) => {
                let v = prig_plataforma::json::leer(&String::from_utf8_lossy(&b)).unwrap_or(Valor::Nulo);
                drop(guarda);
                match moe::a_ollama_completo(ruta, &v, &prefijos, carga_s, Some(contexto), &proyecto) {
                    Ok(m) => Respuesta::Entera(200, Valor::Mapa(m)),
                    Err(x) => error(500, &x.texto()),
                }
            }
            moe::Respuesta::Entera(estado, b) => {
                drop(guarda);
                let texto = String::from_utf8_lossy(&b).into_owned();
                let err = match prig_plataforma::json::leer(&texto) {
                    Ok(Valor::Mapa(m)) => m.get("error").cloned().unwrap_or(Valor::Nulo),
                    _ => Valor::Texto(texto.clone()),
                };
                // la estimación por caracteres se quedó corta: llama-server dice cuántos tokens son
                if let Valor::Mapa(em) = &err {
                    if automatico && !reintento && em.texto("type") == Some("exceed_context_size_error") {
                        let tope = p.mapa("options").and_then(|o| o.get("num_predict")).and_then(|v| v.entero()).unwrap_or(0) as i64;
                        let n = em.get("n_prompt_tokens").and_then(|v| v.entero()).unwrap_or(0) as i64;
                        if let Some(obj) = moe::contexto_para((n + if tope > 0 { tope } else { 4096 } + 512) as i128) {
                            if self.crecer(obj) {
                                return self.post(ruta, pedido, timeout, true);
                            }
                        }
                    }
                }
                let detalle = match &err {
                    Valor::Mapa(m) => m.get("message").map(|v| v.texto_o_repr()).unwrap_or_default(),
                    Valor::Nulo => String::new(),
                    otro => otro.texto_o_repr(),
                };
                error(estado, &detalle.chars().take(500).collect::<String>())
            }
        }
    }
}

/// `f"{n:,}".replace(",", ".")`
fn miles(n: i64) -> String {
    let s = n.abs().to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i).is_multiple_of(3) {
            out.push('.');
        }
        out.push(c);
    }
    if n < 0 { format!("-{out}") } else { out }
}

fn which(prog: &str) -> bool {
    std::env::var_os("PATH").is_some_and(|p| std::env::split_paths(&p).any(|d| d.join(prog).is_file()))
}

// ---------------------------------------------------------------------------------------------- el motor de Prig

/// Los ajustes del motor tal como los guarda el motor de IA (`~/.prig_ai_config.json`, claves `moe_*`): se leen en cada
/// llamada, así un cambio hecho desde el panel vale en el próximo arranque
pub fn ajustes_de_prig() -> Mapa {
    let cfg = config_de_ia();
    let mut a = Mapa::new();
    for (k, de) in [
        ("contexto", "moe_contexto"),
        ("hilos", "moe_hilos"),
        ("calientes", "moe_calientes"),
        ("modo", "moe_modo"),
        ("mtp", "moe_mtp"),
        ("nucleo", "moe_nucleo"),
        ("cache_gb", "moe_cache_gb"),
        ("cache_reserva_gb", "moe_cache_reserva_gb"),
    ] {
        if let Some(v) = cfg.get(de) {
            a.poner(k, v.clone());
        }
    }
    a
}

/// Los valores por defecto de la configuración de IA para el motor (`AIEngine.config`), si el archivo no los tiene
/// (clave, valor por defecto)
pub type Ajuste = (&'static str, fn() -> Valor);

pub const AJUSTES_POR_DEFECTO: [Ajuste; 8] = [
    ("moe_contexto", || Valor::Texto("auto".into())),
    ("moe_hilos", || Valor::Entero(0)),
    ("moe_calientes", || Valor::Texto("auto".into())),
    ("moe_modo", || Valor::Texto(MODO.into())),
    ("moe_mtp", || Valor::Bool(true)),
    ("moe_nucleo", || Valor::Texto(NUCLEO.into())),
    ("moe_cache_gb", || Valor::Entero(32)),
    ("moe_cache_reserva_gb", || Valor::Entero(20)),
];

pub fn ruta_config_de_ia() -> PathBuf {
    PathBuf::from(prig_plataforma::py::expanduser("~/.prig_ai_config.json"))
}

/// Las claves `moe_*` de `~/.prig_ai_config.json`, con los valores por defecto de Python para las que falten (y la
/// misma migración: 16K sin `moe_modo` era el contexto por defecto de antes de que existiera el automático)
pub fn config_de_ia() -> Mapa {
    let guardada = match std::fs::read_to_string(ruta_config_de_ia()).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    };
    let viejo = guardada.get("moe_contexto") == Some(&Valor::Entero(16384)) && !guardada.contiene("moe_modo");
    let mut cfg = Mapa::new();
    for (k, defecto) in AJUSTES_POR_DEFECTO {
        let v = match guardada.get(k) {
            Some(v) if !v.es_nulo() && !(viejo && k == "moe_contexto") => v.clone(),
            _ => defecto(),
        };
        cfg.poner(k, v);
    }
    cfg
}

/// Guarda cambios en `~/.prig_ai_config.json` como `AIEngine.update_config` (lo demás del archivo, intacto; el backend
/// de Python lo relee al ver que cambió)
pub fn guardar_config_de_ia(cambios: &Mapa) -> std::io::Result<()> {
    let ruta = ruta_config_de_ia();
    let mut cfg = match std::fs::read_to_string(&ruta).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    };
    for (k, v) in cambios.iter() {
        if !v.es_nulo() {
            cfg.poner(k.clone(), v.clone());
        }
    }
    let tmp = ruta.with_extension("json.tmp");
    std::fs::write(&tmp, prig_plataforma::json::escribir(&Valor::Mapa(cfg), 2))?;
    std::fs::rename(tmp, ruta)
}

static GLOBAL: std::sync::OnceLock<Arc<Motor>> = std::sync::OnceLock::new();

/// El motor de este proceso (uno solo: es el único dueño de su llama-server)
pub fn global(raiz: &Path) -> Arc<Motor> {
    GLOBAL.get_or_init(|| Motor::new(Rutas::de_prig(raiz), Arc::new(ajustes_de_prig))).clone()
}

/// El motor de este proceso si ya se creó (sin crearlo)
pub fn global_si_hay() -> Option<Arc<Motor>> {
    GLOBAL.get().cloned()
}

/// Para el cierre ordenado de Prig: para el llama-server si lo hay
pub fn detener_global() {
    if let Some(m) = GLOBAL.get() {
        m.detener();
    }
}

// ---------------------------------------------------------------------------------------------- huérfanos

/// `servidores_huerfanos`: llama-server de este motor que siguen vivos sin su Prig (salvo `propio`)
pub fn servidores_huerfanos(servidor: &Path, propio: Option<u32>) -> Vec<i32> {
    let real = std::fs::canonicalize(servidor).unwrap_or_else(|_| servidor.to_path_buf());
    // SAFETY: getuid no falla
    let uid = unsafe { libc::getuid() };
    let mut v = Vec::new();
    for e in std::fs::read_dir("/proc").into_iter().flatten().flatten() {
        let Some(pid) = e.file_name().to_str().and_then(|n| n.parse::<u32>().ok()) else { continue };
        if Some(pid) == propio {
            continue;
        }
        use std::os::unix::fs::MetadataExt;
        let exe = std::fs::read_link(format!("/proc/{pid}/exe"));
        if exe.is_ok_and(|x| x == real) && std::fs::metadata(format!("/proc/{pid}")).is_ok_and(|m| m.uid() == uid) {
            v.push(pid as i32);
        }
    }
    v
}

/// `limpiar_huerfanos`: al abrir Prig, cierra los servidores MoE que dejó una sesión anterior
pub fn limpiar_huerfanos(servidor: &Path, propio: Option<u32>) -> usize {
    let p = servidores_huerfanos(servidor, propio);
    for pid in &p {
        // SAFETY: señales a procesos propios del usuario que son este binario
        unsafe {
            libc::kill(*pid, libc::SIGCONT);
            libc::kill(*pid, libc::SIGTERM);
        }
    }
    p.len()
}

#[cfg(test)]
mod pruebas {
    use super::*;
    use std::io::{BufRead, BufReader, Read, Write};

    /// Un llama-server falso: /health, /apply-template, /completion, /slots, /aipc y /v1/chat/completions
    type Pedidos = Arc<Mutex<Vec<(String, Valor)>>>;

    struct Falso {
        puerto: u16,
        pedidos: Pedidos,
        uso: Arc<Mutex<Option<Valor>>>,
    }

    fn sse(trozos: &[&str]) -> String {
        let mut s = String::new();
        for t in trozos {
            s += &format!("data: {{\"choices\": [{{\"index\": 0, \"finish_reason\": null, \"delta\": {t}}}]}}\n\n");
        }
        s += "data: {\"choices\": [{\"index\": 0, \"finish_reason\": \"stop\", \"delta\": {}}], \"timings\": {\"prompt_n\": 10, \"prompt_ms\": 100, \"predicted_n\": 2, \"predicted_ms\": 50}}\n\ndata: [DONE]\n\n";
        s
    }

    impl Falso {
        fn new(carpeta: PathBuf) -> Falso {
            let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            let puerto = l.local_addr().unwrap().port();
            let pedidos: Pedidos = Default::default();
            let uso: Arc<Mutex<Option<Valor>>> = Default::default();
            let (p, u) = (pedidos.clone(), uso.clone());
            std::thread::spawn(move || {
                for c in l.incoming().flatten() {
                    let (p, u, carpeta) = (p.clone(), u.clone(), carpeta.clone());
                    std::thread::spawn(move || {
                        let mut r = BufReader::new(c.try_clone().unwrap());
                        let mut linea = String::new();
                        r.read_line(&mut linea).unwrap();
                        let partes: Vec<&str> = linea.split_whitespace().collect();
                        let (metodo, ruta) = (partes[0].to_string(), partes[1].to_string());
                        let mut largo = 0;
                        loop {
                            let mut h = String::new();
                            r.read_line(&mut h).unwrap();
                            if h.trim().is_empty() {
                                break;
                            }
                            if let Some(v) = h.to_lowercase().strip_prefix("content-length:") {
                                largo = v.trim().parse().unwrap();
                            }
                        }
                        let mut b = vec![0; largo];
                        r.read_exact(&mut b).unwrap();
                        let cuerpo = if largo > 0 { prig_plataforma::json::leer(&String::from_utf8_lossy(&b)).unwrap() } else { Valor::Nulo };
                        if ruta != "/health" {
                            p.lock().unwrap().push((ruta.clone(), cuerpo.clone()));
                        }
                        let m = match &cuerpo {
                            Valor::Mapa(m) => m.clone(),
                            _ => Mapa::new(),
                        };
                        let mut w = c;
                        let json = |w: &mut std::net::TcpStream, estado: u16, v: String| {
                            let _ = write!(w, "HTTP/1.1 {estado} OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{v}", v.len());
                        };
                        if metodo == "GET" {
                            if ruta.starts_with("/aipc/uso") {
                                let capas = u.lock().unwrap().clone().unwrap_or(Valor::Lista(vec![]));
                                return json(&mut w, 200, format!("{{\"capas\": {}}}", prig_plataforma::json::escribir_compacto(&capas)));
                            }
                            return json(&mut w, 200, "{\"status\":\"ok\"}".into());
                        }
                        match ruta.as_str() {
                            "/apply-template" => {
                                let mut t = String::new();
                                for x in m.lista("messages").unwrap() {
                                    if let Valor::Mapa(x) = x {
                                        t += &format!("<{r}>{}</{r}>", x.texto("content").unwrap_or(""), r = x.texto("role").unwrap());
                                    }
                                }
                                json(&mut w, 200, prig_plataforma::json::escribir_compacto(&Valor::Mapa(Mapa::new().con("prompt", t))))
                            }
                            "/completion" => {
                                let n = m.texto("prompt").unwrap().len() / 3;
                                json(&mut w, 200, format!("{{\"tokens_evaluated\": {n}, \"timings\": {{\"prompt_ms\": 2000.0}}}}"))
                            }
                            "/aipc/calientes" => json(&mut w, 200, format!("{{\"capas_cambiadas\": {}}}", m.lista("capas").unwrap().len())),
                            r if r.starts_with("/slots/0?action=") => {
                                let a = carpeta.join(m.texto("filename").unwrap());
                                if r.contains("save") {
                                    std::fs::write(a, "estado").unwrap();
                                    json(&mut w, 200, "{\"n_saved\": 100}".into())
                                } else if a.exists() {
                                    json(&mut w, 200, "{\"n_restored\": 100}".into())
                                } else {
                                    json(&mut w, 400, "{\"error\": \"no existe\"}".into())
                                }
                            }
                            _ if !m.verdad("stream") => json(
                                &mut w,
                                200,
                                "{\"choices\": [{\"finish_reason\": \"stop\", \"message\": {\"content\": \"listo\"}}], \"timings\": {\"prompt_n\": 10, \"prompt_ms\": 100, \"predicted_n\": 2, \"predicted_ms\": 50}}".into(),
                            ),
                            _ => {
                                let _ = write!(w, "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n");
                                let _ = w.write_all(sse(&["{\"reasoning_content\": \"pienso\"}", "{\"content\": \"Hola\"}", "{\"content\": \" Prig\"}"]).as_bytes());
                            }
                        }
                    });
                }
            });
            Falso { puerto, pedidos, uso }
        }

        fn rutas(&self) -> Vec<String> {
            self.pedidos.lock().unwrap().iter().map(|p| p.0.clone()).collect()
        }
        fn limpiar(&self) {
            self.pedidos.lock().unwrap().clear();
        }
    }

    fn temporal(nombre: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("prig_motor_{nombre}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn rutas_en(d: &Path) -> Rutas {
        Rutas {
            lib: d.join("lib"),
            servidor: d.join("lib/llama-server"),
            lista: d.join("lista.txt"),
            registro: d.join("registro.log"),
            proyectos: d.join("proyectos"),
            modelos_prig: d.join("modelos"),
            ollama: d.join("ollama"),
        }
    }

    fn ajustes(m: Mapa) -> Ajustes {
        Arc::new(move || m.clone())
    }

    fn json(t: &str) -> Valor {
        prig_plataforma::json::leer(t).unwrap()
    }

    fn texto_del_flujo(r: Respuesta) -> (String, Vec<Valor>) {
        let Respuesta::Flujo(f, _g) = r else { panic!("se esperaba un flujo") };
        let mut texto = String::new();
        let mut todos = Vec::new();
        while let Some(v) = f.siguiente().unwrap() {
            if let Valor::Mapa(m) = &v {
                if let Some(Valor::Mapa(msg)) = m.get("message") {
                    texto += msg.texto("content").unwrap_or("");
                }
            }
            todos.push(v);
        }
        (texto, todos)
    }

    /// Un proyecto grande seguido de una pregunta (formato de Ollama)
    fn con_proyecto(pregunta: &str) -> Valor {
        let proyecto = format!("### Archivo: a.py\n{}", "x = 1\n".repeat(4000));
        Valor::Mapa(Mapa::new().con(
            "messages",
            Valor::Lista(vec![
                json(r#"{"role": "system", "content": "tutor"}"#),
                Valor::Mapa(Mapa::new().con("role", "user").con("content", proyecto)),
                Valor::Mapa(Mapa::new().con("role", "user").con("content", pregunta)),
            ]),
        ))
    }

    fn ultimo(todos: &[Valor]) -> Mapa {
        match todos.last() {
            Some(Valor::Mapa(m)) => m.clone(),
            _ => panic!(),
        }
    }

    #[test]
    fn sin_streaming_y_streaming() {
        let d = temporal("simple");
        let f = Falso::new(d.join("proyectos"));
        let m = Motor::con_servidor(rutas_en(&d), ajustes(Mapa::new()), f.puerto);
        let r = m.post("/api/chat", &json(r#"{"messages": [{"role": "user", "content": "x"}], "stream": false}"#), 60.0, false);
        let Respuesta::Entera(200, Valor::Mapa(v)) = r else { panic!() };
        assert_eq!(v.mapa("message").unwrap().texto("content"), Some("listo"));
        let (texto, _) = texto_del_flujo(m.post("/api/chat", &json(r#"{"messages": [{"role": "user", "content": "x"}]}"#), 60.0, false));
        assert_eq!(texto, "Hola Prig");
        assert_eq!(m.estado_mut().activas, 0);
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn cerrar_a_mitad_corta_y_descuenta() {
        let d = temporal("cerrar");
        let f = Falso::new(d.join("proyectos"));
        let m = Motor::con_servidor(rutas_en(&d), ajustes(Mapa::new()), f.puerto);
        let r = m.post("/api/chat", &json(r#"{"messages": [{"role": "user", "content": "x"}]}"#), 60.0, false);
        let Respuesta::Flujo(flujo, guarda) = r else { panic!() };
        flujo.siguiente().unwrap().unwrap();
        assert_eq!(m.estado_mut().activas, 1);
        flujo.cerrar();
        drop(guarda);
        assert!(flujo.siguiente().unwrap().is_none());
        assert_eq!(m.estado_mut().activas, 0);
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn peticion_que_no_cabe_ni_en_el_maximo() {
        let d = temporal("grande");
        let f = Falso::new(d.join("proyectos"));
        let m = Motor::con_servidor(rutas_en(&d), ajustes(Mapa::new()), f.puerto);
        let p = Valor::Mapa(Mapa::new().con("messages", Valor::Lista(vec![Valor::Mapa(Mapa::new().con("role", "user").con("content", "x".repeat(900000)))])));
        let Respuesta::Entera(400, Valor::Mapa(e)) = m.post("/api/chat", &p, 60.0, false) else { panic!() };
        assert!(e.texto("error").unwrap().contains("262.144"), "{:?}", e);
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn proyecto_se_lee_una_vez_y_despues_se_restaura() {
        let d = temporal("proyecto");
        let r = rutas_en(&d);
        std::fs::create_dir_all(&r.proyectos).unwrap();
        let f = Falso::new(r.proyectos.clone());
        let m = Motor::con_servidor(r.clone(), ajustes(Mapa::new()), f.puerto);
        let (texto, todos) = texto_del_flujo(m.post("/api/chat", &con_proyecto("¿qué hace?"), 60.0, false));
        assert_eq!(texto, "Hola Prig");
        assert_eq!(f.rutas(), ["/apply-template", "/completion", "/slots/0?action=save", "/v1/chat/completions"]);
        let plantilla = f.pedidos.lock().unwrap()[0].1.clone();
        let Valor::Mapa(pl) = plantilla else { panic!() };
        assert!(!pl.verdad("add_generation_prompt"));
        assert_eq!(pl.lista("messages").unwrap().len(), 2);
        assert_eq!(ultimo(&todos).mapa("proyecto").and_then(|p| p.texto("origen")), Some("leido"));
        assert_eq!(std::fs::read_dir(&r.proyectos).unwrap().count(), 1);
        // otra pregunta sobre el mismo proyecto: se restaura de disco
        f.limpiar();
        let (_, todos) = texto_del_flujo(m.post("/api/chat", &con_proyecto("¿y los tests?"), 60.0, false));
        assert_eq!(f.rutas(), ["/apply-template", "/slots/0?action=restore", "/v1/chat/completions"]);
        assert_eq!(ultimo(&todos).mapa("proyecto").and_then(|p| p.texto("origen")), Some("disco"));
        assert_eq!(m.estado().mapa("proyectos").unwrap().valor("archivos"), &Valor::Entero(1));
        assert_eq!(m.olvidar_proyectos(), 1);
        assert_eq!(std::fs::read_dir(&r.proyectos).unwrap().count(), 0);
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn cache_apagado_y_estado_que_no_cabe() {
        let d = temporal("cache");
        let r = rutas_en(&d);
        std::fs::create_dir_all(&r.proyectos).unwrap();
        std::fs::write(r.proyectos.join("otro.bin"), "x").unwrap();
        let f = Falso::new(r.proyectos.clone());
        let m = Motor::con_servidor(r.clone(), ajustes(Mapa::new().con("cache_gb", 0)), f.puerto);
        let (texto, _) = texto_del_flujo(m.post("/api/chat", &con_proyecto("¿qué hace?"), 60.0, false));
        assert_eq!(texto, "Hola Prig");
        assert_eq!(f.rutas(), ["/v1/chat/completions"]);
        assert_eq!(std::fs::read_dir(&r.proyectos).unwrap().count(), 1);
        // 50 MB: menos que la parte fija de un estado
        f.limpiar();
        m.poner_ajustes(ajustes(Mapa::new().con("cache_gb", Valor::Real(0.05))));
        texto_del_flujo(m.post("/api/chat", &con_proyecto("¿qué hace?"), 60.0, false));
        assert!(f.rutas().contains(&"/completion".to_string()));
        assert!(!f.rutas().contains(&"/slots/0?action=save".to_string()));
        let u = m.estado_mut().ultimo_proyecto.clone();
        assert!(!u.verdad("guardado"));
        assert_eq!(u.texto("motivo"), Some("no cabe en el caché"));
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn el_proyecto_trae_su_lista_caliente() {
        let d = temporal("calientes");
        let r = rutas_en(&d);
        std::fs::create_dir_all(&r.proyectos).unwrap();
        let f = Falso::new(r.proyectos.clone());
        *f.uso.lock().unwrap() = Some(json("[[0, 5, 1, 9], [3, 0, 0, 1]]"));
        let m = Motor::con_servidor(r.clone(), ajustes(Mapa::new()), f.puerto);
        m.estado_mut().calientes = 2;
        let conv = Valor::Mapa(Mapa::new().con(
            "messages",
            Valor::Lista(vec![
                Valor::Mapa(Mapa::new().con("role", "user").con("content", "x = 1\n".repeat(4000))),
                json(r#"{"role": "user", "content": "¿qué hace?"}"#),
            ]),
        ));
        texto_del_flujo(m.post("/api/chat", &conv, 60.0, false));
        assert_eq!(f.rutas()[..6], ["/apply-template", "/aipc/uso?reset=1", "/completion", "/slots/0?action=save", "/aipc/uso?reset=1", "/aipc/calientes"]);
        let enviada = f.pedidos.lock().unwrap().iter().find(|p| p.0 == "/aipc/calientes").unwrap().1.clone();
        let Valor::Mapa(e) = enviada else { panic!() };
        let primeros: Vec<Vec<i128>> = e.lista("capas").unwrap().iter().map(|c| match c {
            Valor::Lista(l) => l[..2].iter().map(|x| x.entero().unwrap()).collect(),
            _ => vec![],
        }).collect();
        assert_eq!(primeros, vec![vec![3, 1], vec![0, 3]]);
        // misma lista ya en la GPU: al restaurar no se vuelve a enviar
        f.limpiar();
        texto_del_flujo(m.post("/api/chat", &conv, 60.0, false));
        assert!(!f.rutas().contains(&"/aipc/calientes".to_string()));
        // servidor nuevo (lista global): al restaurar se aplica la del proyecto
        f.limpiar();
        m.estado_mut().lista_actual = None;
        texto_del_flujo(m.post("/api/chat", &conv, 60.0, false));
        assert!(f.rutas().contains(&"/aipc/calientes".to_string()));
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn sin_proyecto_no_se_guarda_nada() {
        let d = temporal("sinproyecto");
        let r = rutas_en(&d);
        let f = Falso::new(r.proyectos.clone());
        let m = Motor::con_servidor(r, ajustes(Mapa::new()), f.puerto);
        let p = Valor::Mapa(Mapa::new().con("messages", Valor::Lista(vec![Valor::Mapa(Mapa::new().con("role", "user").con("content", "x".repeat(50000)))])));
        texto_del_flujo(m.post("/api/chat", &p, 60.0, false));
        assert_eq!(f.rutas(), ["/v1/chat/completions"]);
        std::fs::remove_dir_all(d).ok();
    }

    fn tres_estados(d: &Path) {
        std::fs::create_dir_all(d).unwrap();
        for (i, n) in ["viejo", "medio", "nuevo"].iter().enumerate() {
            let r = d.join(format!("{n}.bin"));
            std::fs::write(&r, vec![b'x'; 1_000_000]).unwrap();
            std::fs::File::options().write(true).open(&r).unwrap().set_modified(UNIX_EPOCH + Duration::from_secs(1000 + i as u64)).unwrap();
        }
    }

    fn nombres(d: &Path) -> Vec<String> {
        let mut v: Vec<String> = std::fs::read_dir(d).unwrap().flatten().map(|e| e.file_name().to_string_lossy().into_owned()).collect();
        v.sort();
        v
    }

    #[test]
    fn podar_y_tope_del_cache() {
        let d = temporal("podar");
        tres_estados(&d);
        assert_eq!(proyectos_guardados(&d).valor("mb"), &Valor::Entero(3));
        assert_eq!(podar_proyectos(&d, 2.0, 0.0), 1);
        assert_eq!(nombres(&d), ["medio.bin", "nuevo.bin"]);
        let r = Rutas { proyectos: d.clone(), ..rutas_en(&d) };
        let m = Motor::new(r.clone(), ajustes(Mapa::new().con("cache_gb", Valor::Real(0.001))));
        assert_eq!(m.tope_cache_mb(), 1.0);
        assert_eq!(m.podar(), 1);
        assert_eq!(nombres(&d), ["nuevo.bin"]);
        assert_eq!(Motor::new(r.clone(), ajustes(Mapa::new())).tope_cache_mb(), PROYECTOS_MAX_MB);
        assert_eq!(Motor::new(r.clone(), ajustes(Mapa::new().con("cache_gb", "nada"))).tope_cache_mb(), PROYECTOS_MAX_MB);
        let p = Motor::new(r, ajustes(Mapa::new().con("cache_gb", 5).con("cache_reserva_gb", 20))).estado();
        let p = p.mapa("proyectos").unwrap();
        assert_eq!((p.num("tope_mb"), p.num("reserva_mb")), (Some(5000.0), Some(20000.0)));
        assert!(p.contiene("libre_mb"));
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn orden_segun_modo_y_mtp() {
        let d = temporal("orden");
        let r = rutas_en(&d);
        let m = Motor::new(r.clone(), ajustes(Mapa::new().con("contexto", 8192).con("modo", "rapido")));
        let mut e = m.estado_mut();
        let (cmd, env, modo) = m.orden(&mut e, Path::new("/m.gguf"), 40, true);
        assert_eq!(modo, "rapido");
        assert!(cmd.contains(&"draft-mtp".to_string()));
        let tras = &cmd[cmd.iter().position(|x| x.ends_with("llama-server")).unwrap()..];
        let i = tras.iter().position(|x| x == "-c").unwrap();
        assert_eq!(tras[i + 1], "8192");
        let val = |k: &str| env.iter().find(|(x, _)| x == k).and_then(|(_, v)| v.clone());
        assert_eq!(
            (val("AIPC_MOE_HOT_N"), val("AIPC_COLD_SKIP"), val("AIPC_OVERLAP"), val("AIPC_COLD_DROP")),
            (Some("40".into()), Some("1".into()), Some("1".into()), Some("0.1".into()))
        );
        drop(e);
        m.poner_ajustes(ajustes(Mapa::new().con("modo", "exacto")));
        let (cmd, env, _) = m.orden(&mut m.estado_mut(), Path::new("/m.gguf"), 40, false);
        assert!(!cmd.contains(&"draft-mtp".to_string()));
        assert!(!env.iter().any(|(k, v)| k == "AIPC_COLD_DROP" && v.is_some()));
        let (_, env, _) = m.orden(&mut m.estado_mut(), Path::new("/m.gguf"), 0, false);
        assert!(env.iter().all(|(k, v)| !k.starts_with("AIPC_") || v.is_none()), "sin calientes, nada de AIPC");
        m.poner_ajustes(ajustes(Mapa::new().con("modo", "inventado")));
        assert_eq!(m.orden(&mut m.estado_mut(), Path::new("/m.gguf"), 40, false).2, MODO);
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn si_no_cabe_reintenta_sin_mtp() {
        let d = temporal("reintento");
        let m = Motor::new(rutas_en(&d), ajustes(Mapa::new().con("contexto", 16384)));
        let intentos: Arc<Mutex<Vec<(i64, bool)>>> = Default::default();
        let i2 = intentos.clone();
        *m.ganchos.lock().unwrap() = Ganchos {
            lanzar: Some(Arc::new(move |n, mtp| {
                i2.lock().unwrap().push((n, mtp));
                !mtp && n > 0
            })),
            vram: Some(Some(6100.0)),
            modelo: Some(PathBuf::from("/m.gguf")),
        };
        m.asegurar().unwrap();
        let v = intentos.lock().unwrap().clone();
        assert!(v[..2].iter().all(|(_, mtp)| *mtp));
        assert_eq!(*v.last().unwrap(), (moe::calientes_para(Some(6100.0), 16384, false, moe::MB_POR_CALIENTE, 0.0), false));
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn blob_q8_y_disponible() {
        let d = temporal("blob");
        let r = rutas_en(&d);
        assert!(r.blob_del_modelo().is_none());
        let mut manif = r.ollama.join("manifests");
        for p in MODELO_OLLAMA {
            manif = manif.join(p);
        }
        std::fs::create_dir_all(manif.parent().unwrap()).unwrap();
        std::fs::write(&manif, r#"{"layers": [{"mediaType": "application/vnd.ollama.image.template", "digest": "sha256:aa"}, {"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:bb"}]}"#).unwrap();
        assert!(r.blob_del_modelo().is_none());
        std::fs::create_dir_all(r.ollama.join("blobs")).unwrap();
        std::fs::write(r.ollama.join("blobs/sha256-bb"), "").unwrap();
        assert_eq!(r.blob_del_modelo(), Some(r.ollama.join("blobs/sha256-bb")));
        // núcleo Q8: a medias, el Q4; terminado, el Q8
        let q8 = r.modelos_prig.join(ARCHIVO_NUCLEO_Q8);
        std::fs::create_dir_all(&r.modelos_prig).unwrap();
        std::fs::write(&q8, "").unwrap();
        std::fs::write(format!("{}.partes", q8.display()), "").unwrap();
        assert_eq!(r.modelo_para(Some("q8")), r.blob_del_modelo());
        std::fs::remove_file(format!("{}.partes", q8.display())).unwrap();
        assert_eq!(r.modelo_para(Some("q8")), Some(q8.clone()));
        assert_eq!(r.modelo_para(Some("q4")), r.blob_del_modelo());
        assert_eq!(mb_por_caliente(Some(&q8)), moe::MB_POR_CALIENTE);
        // sin servidor compilado: no disponible
        let m = Motor::new(r, ajustes(Mapa::new()));
        let disp = m.disponible();
        assert!(!disp.verdad("disponible"));
        assert!(disp.texto("motivo").unwrap().contains("compilar.sh"));
        std::fs::remove_dir_all(d).ok();
    }

    #[test]
    fn nucleos_de_rendimiento() {
        let n = nucleos_rendimiento();
        assert!(!n.is_empty());
        let e = prig_recursos::ritmo::nucleos_eficientes();
        assert!(n.iter().all(|x| !e.contains(x)));
        assert_eq!(miles(262144), "262.144");
    }

    #[test]
    fn lanzado_lleva_pdeathsig_desde_un_hilo_que_vive() {
        // un hijo lanzado desde un hilo que termina no debe morir con ese hilo
        let h = std::thread::spawn(|| {
            let mut c = Command::new("sleep");
            c.arg("5");
            lanzar(c).unwrap()
        });
        let mut hijo = h.join().unwrap();
        std::thread::sleep(Duration::from_millis(300));
        assert!(hijo.try_wait().unwrap().is_none(), "el hijo murió con el hilo que lo pidió");
        let pid = hijo.id();
        let estado = std::fs::read_to_string(format!("/proc/{pid}/status")).unwrap();
        assert!(estado.contains("State:"));
        let _ = hijo.kill();
        let _ = hijo.wait();
    }
}

// ---------------------------------------------------------------------------------------------- la configuración de IA

/// `AIEngine.config` por defecto, en su orden
pub fn config_ia_por_defecto() -> Mapa {
    Mapa::new()
        .con("ollama_url", "http://localhost:11434")
        .con("agent1_model", "qwen2.5-coder:7b")
        .con("agent2_model", "qwen2.5-coder:7b")
        .con("agent3_model", "qwen2.5-coder:7b")
        .con("designer_model", "qwen2.5-coder:7b")
        .con("modelo_codigo", "")
        .con("modelo_explicar", "")
        .con("modelo_autocompletar", "")
        .con("depth_level", "intermediate")
        .con("temperature", Valor::Real(0.3))
        .con("num_ctx", 4096)
        .con("num_gpu", -1)
        .con("num_thread", 0)
        .con("num_predict", 2048)
        .con("low_vram", false)
        .con("f16_kv", true)
        .con("muestreo_del_modelo", true)
        .con("keep_alive", "5m")
        .con("top_k", 40)
        .con("top_p", Valor::Real(0.9))
        .con("repeat_penalty", Valor::Real(1.1))
        .con("exec_timeout", 25)
        .con("moe_contexto", "auto")
        .con("moe_hilos", 0)
        .con("moe_calientes", "auto")
        .con("moe_modo", MODO)
        .con("moe_mtp", true)
        .con("moe_nucleo", NUCLEO)
        .con("moe_cache_gb", 32)
        .con("moe_cache_reserva_gb", 20)
        .con("banco_presupuesto", 6000)
        .con("banco_mapa", 3000)
        .con("banco_modelo", "")
        .con("banco_modo", "auto")
}

/// `AIEngine.config` tras `_load_config()`: lo guardado (solo claves conocidas y no nulas) sobre lo de por defecto
pub fn config_ia() -> Mapa {
    let mut c = config_ia_por_defecto();
    if let Some(Valor::Mapa(mut g)) = std::fs::read_to_string(ruta_config_de_ia()).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        // 16K sin `moe_modo` era el contexto por defecto de antes del automático
        if g.get("moe_contexto") == Some(&Valor::Entero(16384)) && !g.contiene("moe_modo") {
            g.quitar("moe_contexto");
        }
        for (k, v) in g.iter() {
            if c.contiene(k) && !v.es_nulo() {
                c.poner(k.clone(), v.clone());
            }
        }
    }
    c
}

/// `update_config(cambios)`: aplica lo conocido y no nulo y guarda la configuración entera (como Python)
pub fn guardar_config_ia(cambios: &Mapa) -> std::io::Result<Mapa> {
    let mut c = config_ia();
    for (k, v) in cambios.iter() {
        if c.contiene(k) && !v.es_nulo() {
            c.poner(k.clone(), v.clone());
        }
    }
    let ruta = ruta_config_de_ia();
    std::fs::write(&ruta, prig_plataforma::json::escribir(&Valor::Mapa(c.clone()), 2))?;
    Ok(c)
}
