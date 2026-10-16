//! Ejecutar código (`runner.py` y `kernel_session.py`): archivos de Python, C y C++ (compilados con gcc/g++), JS,
//! bash y cuadernos (sus celdas de código juntas), con tiempo límite y cancelables desde otra petición (se mata el
//! grupo de procesos entero); y las sesiones persistentes de los cuadernos, un intérprete de Python vivo por
//! cuaderno al que se le mandan las celdas por stdin. Python es aquí una herramienta (el intérprete que corre el
//! código del usuario), que llega como `python`.
//!
//! Diferencias con Python, escritas: al pasarse del tiempo límite se mata el grupo de procesos entero (Python mataba
//! solo al proceso principal y, si un hijo seguía con la salida abierta, la espera no terminaba); y el error de una
//! sesión que escribe en stderr bytes que no son UTF-8 ya no deja de recoger stderr (Python dejaba de vaciar la
//! tubería y el intérprete del cuaderno se podía quedar bloqueado).

use crate::py::{self, ErrorPy};
use crate::valor::{redondear, Mapa, Valor};
use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const DRIVER: &str = include_str!("kernel_driver.py");

fn ahora() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

fn transcurrido(desde: f64) -> f64 {
    redondear(ahora() - desde, 3)
}

// =========================================================================== temporales

/// `tempfile.gettempdir()`
pub fn dir_temporal() -> String {
    for v in ["TMPDIR", "TEMP", "TMP"] {
        if let Ok(d) = std::env::var(v) {
            if !d.is_empty() && std::path::Path::new(&d).is_dir() {
                return py::abspath(&d);
            }
        }
    }
    "/tmp".into()
}

/// Un archivo temporal nuevo (`tempfile.mkstemp`), con permisos 0600: su ruta
fn temporal(prefijo: &str, sufijo: &str, contenido: &[u8]) -> Result<String, ErrorPy> {
    use std::os::unix::fs::OpenOptionsExt;
    const LETRAS: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789_";
    let dir = dir_temporal();
    let mut semilla = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(1) ^ (std::process::id() as u64) << 32;
    for _ in 0..100 {
        let mut nombre = String::new();
        for _ in 0..8 {
            semilla ^= semilla << 13;
            semilla ^= semilla >> 7;
            semilla ^= semilla << 17;
            nombre.push(LETRAS[(semilla % LETRAS.len() as u64) as usize] as char);
        }
        let ruta = py::join(&dir, &format!("{prefijo}{nombre}{sufijo}"));
        match std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&ruta) {
            Ok(mut f) => {
                f.write_all(contenido).map_err(|e| ErrorPy::os(&e, &ruta))?;
                return Ok(ruta);
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(ErrorPy::os(&e, &ruta)),
        }
    }
    Err(ErrorPy::OsTexto("No usable temporary file name found".into()))
}

// =========================================================================== texto de la salida

/// Lo que da `text=True` de subprocess: UTF-8 estricto (con el error de Python si no lo es) y saltos `\r\n` y `\r`
/// como `\n`
pub fn decodificar(b: &[u8]) -> Result<String, String> {
    match std::str::from_utf8(b) {
        Ok(t) => Ok(t.replace("\r\n", "\n").replace('\r', "\n")),
        Err(e) => {
            let pos = e.valid_up_to();
            let (largo, razon) = match e.error_len() {
                None => (b.len() - pos, "unexpected end of data"),
                Some(n) => {
                    let c = b[pos];
                    let inicio_valido = matches!(c, 0xc2..=0xf4);
                    (n, if inicio_valido { "invalid continuation byte" } else { "invalid start byte" })
                }
            };
            Err(if largo > 1 {
                format!("'utf-8' codec can't decode bytes in position {}-{}: {razon}", pos, pos + largo - 1)
            } else {
                format!("'utf-8' codec can't decode byte 0x{:02x} in position {pos}: {razon}", b[pos])
            })
        }
    }
}

fn codigo_de(estado: std::process::ExitStatus) -> i64 {
    match estado.code() {
        Some(c) => c as i64,
        None => -(estado.signal().unwrap_or(0) as i64),
    }
}

fn matar_grupo(pid: i32) -> bool {
    // SAFETY: getpgid y killpg solo mandan una señal
    unsafe {
        let g = libc::getpgid(pid);
        if g > 0 && libc::killpg(g, libc::SIGKILL) == 0 {
            return true;
        }
        libc::kill(pid, libc::SIGKILL);
    }
    false
}

/// Espera a que el proceso termine y cierre su salida, con tiempo límite: (código, stdout, stderr), o None si se pasó
fn comunicar(hijo: &mut Child, limite: Option<Duration>) -> (Option<i64>, Vec<u8>, Vec<u8>) {
    let mut out = hijo.stdout.take();
    let mut err = hijo.stderr.take();
    let (tx_o, rx_o) = mpsc::channel();
    let (tx_e, rx_e) = mpsc::channel();
    std::thread::spawn(move || {
        let mut b = Vec::new();
        if let Some(o) = out.as_mut() {
            let _ = o.read_to_end(&mut b);
        }
        let _ = tx_o.send(b);
    });
    std::thread::spawn(move || {
        let mut b = Vec::new();
        if let Some(e) = err.as_mut() {
            let _ = e.read_to_end(&mut b);
        }
        let _ = tx_e.send(b);
    });
    let fin = limite.map(|l| Instant::now() + l);
    let esperar = |rx: &Receiver<Vec<u8>>| -> Option<Vec<u8>> {
        match fin {
            None => rx.recv().ok(),
            Some(f) => rx.recv_timeout(f.saturating_duration_since(Instant::now())).ok(),
        }
    };
    let o = esperar(&rx_o);
    let e = if o.is_some() { esperar(&rx_e) } else { None };
    if let (Some(o), Some(e)) = (o, e) {
        loop {
            match hijo.try_wait() {
                Ok(Some(st)) => return (Some(codigo_de(st)), o, e),
                Ok(None) => {
                    if fin.is_some_and(|f| Instant::now() >= f) {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(2));
                }
                Err(_) => return (Some(-1), o, e),
            }
        }
        // se pasó: matar y devolver lo que haya
        matar_grupo(hijo.id() as i32);
        let _ = hijo.wait();
        return (None, o, e);
    }
    matar_grupo(hijo.id() as i32);
    let _ = hijo.wait();
    let o = rx_o.recv().unwrap_or_default();
    let e = rx_e.recv().unwrap_or_default();
    (None, o, e)
}

fn en_path(programa: &str) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::env::var("PATH").unwrap_or_default().split(':').any(|d| {
        let p = std::path::Path::new(if d.is_empty() { "." } else { d }).join(programa);
        p.metadata().map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0).unwrap_or(false)
    })
}

fn falla(stderr: impl Into<String>, codigo: i64, elapsed: f64) -> Mapa {
    Mapa::new().con("success", false).con("stdout", "").con("stderr", stderr.into()).con("exit_code", codigo).con("elapsed", elapsed)
}

// =========================================================================== ejecutar archivos

pub struct Ejecutor {
    pub timeout: i64,
    /// El intérprete de Python (la herramienta): `sys.executable`
    pub python: String,
    /// Las ejecuciones en marcha: identificador → pid (para cancelarlas desde otra petición)
    pub activos: Mutex<HashMap<String, i32>>,
    pub sesiones: Arc<Sesiones>,
}

impl Ejecutor {
    pub fn new(timeout: i64, python: String) -> Ejecutor {
        Ejecutor { timeout, python: python.clone(), activos: Mutex::new(HashMap::new()), sesiones: Arc::new(Sesiones::new(python)) }
    }

    pub fn registrar(&self, id: &str, pid: i32) {
        if !id.is_empty() {
            self.activos.lock().unwrap().insert(id.to_string(), pid);
        }
    }

    fn quitar(&self, id: Option<&str>) {
        if let Some(id) = id.filter(|i| !i.is_empty()) {
            self.activos.lock().unwrap().remove(id);
        }
    }

    /// `cancel`: detiene una ejecución en curso, con todo su grupo de procesos
    pub fn cancelar(&self, id: &str) -> Mapa {
        let pid = self.activos.lock().unwrap().get(id).copied();
        match pid {
            None => Mapa::new().con("cancelled", false).con("reason", "No hay ninguna ejecución con ese identificador."),
            Some(p) => {
                matar_grupo(p);
                Mapa::new().con("cancelled", true).con("run_id", id)
            }
        }
    }

    /// `cancel_all`
    pub fn cancelar_todo(&self) {
        let pids: Vec<i32> = self.activos.lock().unwrap().drain().map(|(_, p)| p).collect();
        for p in pids {
            matar_grupo(p);
        }
    }

    /// `shutdown`: los procesos de los scripts y las sesiones de los cuadernos
    pub fn apagar(&self) {
        self.cancelar_todo();
        self.sesiones.apagar_todas();
    }

    /// `run_file`
    pub fn ejecutar_archivo(
        &self,
        ruta: &str,
        cwd: Option<&str>,
        timeout: Option<i64>,
        id: Option<&str>,
        extra: &[String],
    ) -> Mapa {
        let limite = timeout.filter(|t| *t != 0).unwrap_or(self.timeout);
        let abs = py::abspath(ruta);
        if !std::path::Path::new(&abs).exists() {
            return Mapa::new()
                .con("error", format!("Archivo no existe: {ruta}"))
                .con("stdout", "")
                .con("stderr", "")
                .con("exit_code", 1);
        }
        let dir = match cwd {
            Some(c) if !c.is_empty() && std::path::Path::new(c).is_dir() => c.to_string(),
            _ => py::dirname(&abs),
        };
        let mut ext = py::extension(&abs).to_lowercase();
        let mut script = abs.clone();
        let mut temporales: Vec<String> = Vec::new();
        let limpiar = |t: &Vec<String>| {
            for p in t {
                let _ = std::fs::remove_file(p);
            }
        };

        if ext == ".ipynb" {
            match codigo_de_cuaderno(&abs).and_then(|c| temporal("tmp", ".py", c.as_bytes()).map_err(|e| e.texto())) {
                Ok(t) => {
                    script = t.clone();
                    temporales.push(t);
                    ext = ".py".into();
                }
                Err(e) => return falla(format!("Error al procesar cuaderno .ipynb: {e}"), 1, 0.0),
            }
        }

        let cmd: Vec<String> = if [".cpp", ".cc", ".cxx", ".c"].contains(&ext.as_str()) {
            let compilador = if ext == ".c" { "gcc" } else { "g++" };
            if !en_path(compilador) {
                limpiar(&temporales);
                return falla(format!("Error: No se encontró el compilador '{compilador}' en el sistema."), 1, 0.0);
            }
            let bin = match temporal("prig_bin_", "", b"") {
                Ok(b) => b,
                Err(e) => return falla(format!("Error al ejecutar: {}", e.texto()), 1, 0.0),
            };
            temporales.push(bin.clone());
            let estandar = if compilador == "gcc" { "-std=c11" } else { "-std=c++20" };
            let mut args = vec![estandar.to_string(), "-O2".into(), script.clone()];
            args.extend(extra.iter().map(|s| py::abspath(s)));
            args.extend(["-o".to_string(), bin.clone(), "-lm".into()]);
            let inicio = ahora();
            let hijo = Command::new(compilador)
                .args(&args)
                .current_dir(&dir)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn();
            let mut hijo = match hijo {
                Ok(h) => h,
                Err(e) => {
                    limpiar(&temporales);
                    return falla(format!("Error al ejecutar: {}", ErrorPy::os(&e, compilador).texto()), 1, 0.0);
                }
            };
            let (codigo, _, err) = comunicar(&mut hijo, Some(Duration::from_secs(25)));
            match codigo {
                None => {
                    limpiar(&temporales);
                    return falla(
                        format!("Error: Tiempo límite excedido durante la compilación ({compilador})."),
                        1,
                        transcurrido(inicio),
                    );
                }
                Some(c) if c != 0 => {
                    limpiar(&temporales);
                    let err = String::from_utf8_lossy(&err).replace("\r\n", "\n").replace('\r', "\n");
                    return falla(format!("Error de compilación ({compilador}):\n{err}"), c, transcurrido(inicio));
                }
                _ => {}
            }
            vec![bin]
        } else if ext == ".py" {
            vec![self.python.clone(), script.clone()]
        } else if ext == ".js" {
            vec!["node".into(), script.clone()]
        } else if ext == ".sh" || ext == ".bash" {
            vec!["bash".into(), script.clone()]
        } else {
            vec![self.python.clone(), script.clone()]
        };

        let inicio = ahora();
        let mut c = Command::new(&cmd[0]);
        c.args(&cmd[1..]).current_dir(&dir).stdin(Stdio::inherit()).stdout(Stdio::piped()).stderr(Stdio::piped());
        // SAFETY: setsid() en el hijo antes de exec (start_new_session=True)
        unsafe {
            c.pre_exec(|| {
                libc::setsid();
                Ok(())
            });
        }
        let mut hijo = match c.spawn() {
            Ok(h) => h,
            Err(e) => {
                limpiar(&temporales);
                return falla(format!("Error al ejecutar: {}", ErrorPy::os(&e, &cmd[0]).texto()), 1, 0.0);
            }
        };
        if let Some(i) = id {
            self.registrar(i, hijo.id() as i32);
        }
        let (codigo, out, err) = comunicar(&mut hijo, Some(Duration::from_secs(limite.max(0) as u64)));
        self.quitar(id);
        let (out_t, err_t) = match (decodificar(&out), decodificar(&err)) {
            (Ok(o), Ok(e)) => (o, e),
            (Err(x), _) | (_, Err(x)) => {
                limpiar(&temporales);
                return falla(format!("Error al ejecutar: {x}"), 1, 0.0);
            }
        };
        limpiar(&temporales);
        match codigo {
            None => Mapa::new()
                .con("success", false)
                .con("stdout", out_t)
                .con("stderr", format!("Error: Tiempo límite de ejecución excedido ({limite}s)"))
                .con("exit_code", -1)
                .con("elapsed", limite),
            Some(c) if c < 0 => Mapa::new()
                .con("success", false)
                .con("cancelled", true)
                .con("stdout", out_t)
                .con("stderr", "Ejecución detenida por el usuario.")
                .con("exit_code", c)
                .con("elapsed", transcurrido(inicio)),
            Some(c) => {
                let elapsed = transcurrido(inicio);
                Mapa::new()
                    .con("success", c == 0)
                    .con("stdout", out_t)
                    .con("stderr", err_t)
                    .con("exit_code", c)
                    .con("elapsed", elapsed)
            }
        }
    }

    /// `run_cell_code`: una celda en la sesión persistente del cuaderno
    pub fn ejecutar_celda(&self, codigo: &str, cwd: Option<&str>, sesion: Option<&str>, timeout: Option<i64>) -> Mapa {
        let dir = match cwd {
            Some(c) if !c.is_empty() && std::path::Path::new(c).is_dir() => c.to_string(),
            _ => py::getcwd(),
        };
        let limite = timeout.filter(|t| *t != 0).unwrap_or(self.timeout);
        let inicio = ahora();
        let r = self.sesiones.obtener(sesion, &dir).and_then(|s| s.ejecutar(codigo, limite));
        match r {
            Ok(res) => {
                let ok = res.get("ok").map(|v| v.verdad()).unwrap_or(false);
                Mapa::new()
                    .con("success", res.get("ok").cloned().unwrap_or(Valor::Bool(false)))
                    .con("stdout", res.get("stdout").cloned().unwrap_or_else(|| "".into()))
                    .con("stderr", res.get("stderr").cloned().unwrap_or_else(|| "".into()))
                    .con("exit_code", if ok { 0 } else { 1 })
                    .con("elapsed", transcurrido(inicio))
            }
            Err(ErrorKernel::Tiempo(t)) => {
                self.sesiones.reiniciar(sesion);
                falla(
                    format!("Error: {t}. La sesión del cuaderno se reinició; vuelve a ejecutar las celdas anteriores."),
                    -1,
                    limite as f64,
                )
                .con("elapsed", limite)
            }
            Err(ErrorKernel::Otro(t)) => {
                self.sesiones.reiniciar(sesion);
                falla(format!("Error al ejecutar celda: {t}"), 1, transcurrido(inicio))
            }
        }
    }
}

/// Las celdas de código de un cuaderno juntas, como el script que ejecuta Python
fn codigo_de_cuaderno(ruta: &str) -> Result<String, String> {
    let texto = py::leer_texto_estricto(ruta)?;
    let datos = crate::json::leer(&texto)?;
    let celdas = py::get(&datos, "cells", Valor::Lista(vec![]))?;
    let mut lineas = Vec::new();
    for c in py::iterar(&celdas)? {
        if py::get(&c, "cell_type", Valor::Nulo)? == Valor::Texto("code".into()) {
            let fuente = py::get(&c, "source", Valor::Lista(vec![]))?;
            lineas.push(match &fuente {
                Valor::Lista(_) => py::unir("", &fuente)?,
                otro => otro.texto_py(),
            });
            lineas.push("\n\n".to_string());
        }
    }
    Ok(lineas.join("\n"))
}

// =========================================================================== sesiones de cuadernos

#[derive(Debug)]
pub enum ErrorKernel {
    /// TimeoutError (su texto)
    Tiempo(String),
    /// Cualquier otro error (su texto)
    Otro(String),
}

/// Un intérprete de Python vivo asociado a un cuaderno
pub struct Sesion {
    pub cwd: String,
    pub driver: String,
    hijo: Mutex<Child>,
    entrada: Mutex<Option<ChildStdin>>,
    salida: Mutex<Receiver<Option<String>>>,
    cola_err: Arc<Mutex<VecDeque<String>>>,
    turno: Mutex<()>,
}

impl Sesion {
    pub fn new(cwd: &str, python: &str) -> Result<Sesion, String> {
        let driver = temporal("prig_kernel_", ".py", DRIVER.as_bytes()).map_err(|e| e.texto())?;
        let mut c = Command::new(python);
        c.args(["-u", &driver]).current_dir(cwd).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
        // SAFETY: setsid() en el hijo antes de exec
        unsafe {
            c.pre_exec(|| {
                libc::setsid();
                Ok(())
            });
        }
        let mut hijo = c.spawn().map_err(|e| {
            let _ = std::fs::remove_file(&driver);
            ErrorPy::os(&e, python).texto()
        })?;
        let (tx, rx) = mpsc::channel();
        let out = hijo.stdout.take().unwrap();
        std::thread::spawn(move || {
            let mut r = BufReader::new(out);
            loop {
                let mut b = Vec::new();
                match r.read_until(b'\n', &mut b) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => match String::from_utf8(b) {
                        Ok(l) => {
                            if tx.send(Some(l)).is_err() {
                                return;
                            }
                        }
                        Err(_) => break,
                    },
                }
            }
            let _ = tx.send(None);
        });
        let cola_err = Arc::new(Mutex::new(VecDeque::new()));
        let cola = cola_err.clone();
        let err = hijo.stderr.take().unwrap();
        std::thread::spawn(move || {
            // hay que vaciar stderr aunque no se use: si se llena la tubería, el intérprete se bloquea
            let mut r = BufReader::new(err);
            loop {
                let mut b = Vec::new();
                match r.read_until(b'\n', &mut b) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {
                        let mut c = cola.lock().unwrap();
                        c.push_back(String::from_utf8_lossy(&b).into_owned());
                        if c.len() > 50 {
                            c.pop_front();
                        }
                    }
                }
            }
        });
        let entrada = hijo.stdin.take();
        Ok(Sesion {
            cwd: cwd.to_string(),
            driver,
            hijo: Mutex::new(hijo),
            entrada: Mutex::new(entrada),
            salida: Mutex::new(rx),
            cola_err,
            turno: Mutex::new(()),
        })
    }

    pub fn viva(&self) -> bool {
        matches!(self.hijo.lock().unwrap().try_wait(), Ok(None))
    }

    pub fn pid(&self) -> u32 {
        self.hijo.lock().unwrap().id()
    }

    /// `execute`: manda la celda y espera su respuesta (`{ok, stdout, stderr}`)
    pub fn ejecutar(&self, codigo: &str, limite: i64) -> Result<Mapa, ErrorKernel> {
        let _turno = self.turno.lock().unwrap();
        if !self.viva() {
            return Err(ErrorKernel::Otro("La sesión del cuaderno no está activa.".into()));
        }
        let rx = self.salida.lock().unwrap();
        // restos de una ejecución anterior abortada
        while rx.try_recv().is_ok() {}
        let linea = crate::json::escribir_compacto(&Valor::Mapa(Mapa::new().con("code", codigo))) + "\n";
        {
            let mut e = self.entrada.lock().unwrap();
            let Some(w) = e.as_mut() else { return Err(ErrorKernel::Otro("[Errno 32] Broken pipe".into())) };
            if let Err(err) = w.write_all(linea.as_bytes()).and_then(|_| w.flush()) {
                return Err(ErrorKernel::Otro(ErrorPy::os(&err, "").texto().replace(": ''", "")));
            }
        }
        let r = rx.recv_timeout(Duration::from_secs(limite.max(0) as u64));
        drop(rx);
        match r {
            Err(RecvTimeoutError::Timeout) => {
                self.apagar();
                Err(ErrorKernel::Tiempo(format!("Tiempo límite de celda excedido ({limite}s)")))
            }
            Ok(None) | Err(RecvTimeoutError::Disconnected) => {
                let detalle: String = self.cola_err.lock().unwrap().iter().cloned().collect();
                let detalle = py::strip(&detalle).to_string();
                Err(ErrorKernel::Otro(if detalle.is_empty() {
                    "El proceso de la sesión terminó inesperadamente.".into()
                } else {
                    detalle
                }))
            }
            Ok(Some(l)) => match crate::json::leer(&l) {
                Ok(Valor::Mapa(m)) => Ok(m),
                Ok(_) => Err(ErrorKernel::Otro("respuesta inesperada de la sesión".into())),
                Err(e) => Err(ErrorKernel::Otro(e)),
            },
        }
    }

    /// `shutdown`: mata el intérprete (con su grupo) y borra el driver
    pub fn apagar(&self) {
        {
            let mut h = self.hijo.lock().unwrap();
            if matches!(h.try_wait(), Ok(None)) {
                matar_grupo(h.id() as i32);
                let fin = Instant::now() + Duration::from_secs(1);
                while Instant::now() < fin {
                    if !matches!(h.try_wait(), Ok(None)) {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(5));
                }
            }
        }
        let _ = std::fs::remove_file(&self.driver);
    }
}

/// `KernelSessionManager`: una sesión viva por cuaderno, que se rehace si murió o cambió de carpeta
pub struct Sesiones {
    python: String,
    pub mapa: Mutex<HashMap<String, Arc<Sesion>>>,
}

impl Sesiones {
    pub fn new(python: String) -> Sesiones {
        Sesiones { python, mapa: Mutex::new(HashMap::new()) }
    }

    pub fn clave(id: Option<&str>) -> String {
        match id {
            Some(i) if !i.is_empty() => py::abspath(i),
            _ => "__scratch__".into(),
        }
    }

    pub fn obtener(&self, id: Option<&str>, cwd: &str) -> Result<Arc<Sesion>, ErrorKernel> {
        let clave = Self::clave(id);
        let mut m = self.mapa.lock().unwrap();
        if let Some(s) = m.get(&clave) {
            if s.viva() && s.cwd == cwd {
                return Ok(s.clone());
            }
            s.apagar();
        }
        let s = Arc::new(Sesion::new(cwd, &self.python).map_err(ErrorKernel::Otro)?);
        m.insert(clave, s.clone());
        Ok(s)
    }

    pub fn reiniciar(&self, id: Option<&str>) -> bool {
        let s = self.mapa.lock().unwrap().remove(&Self::clave(id));
        match s {
            Some(s) => {
                s.apagar();
                true
            }
            None => false,
        }
    }

    pub fn apagar_todas(&self) {
        let todas: Vec<Arc<Sesion>> = self.mapa.lock().unwrap().drain().map(|(_, s)| s).collect();
        for s in todas {
            s.apagar();
        }
    }
}
