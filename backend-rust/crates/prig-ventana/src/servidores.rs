//! Los servidores de Prig, lo que hacía main.py: elegir el puerto (o reutilizar un Prig ya abierto), cerrar los
//! servidores que quedaron sueltos de una sesión anterior, arrancar el servidor de Rust (aquí, en el mismo proceso) y
//! el backend de Python (proceso hijo, mientras quede algo en él), vigilarlos y cerrarlos en orden.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

pub const HOST: &str = "127.0.0.1";
pub const PUERTO_PREFERIDO: u16 = 8000;
pub const RANGO: u16 = 20;

/// Una petición GET mínima (sin dependencias): `Some((estado, cuerpo))` si el servidor contesta
pub fn pedir(puerto: u16, ruta: &str, espera: Duration) -> Option<(u16, String)> {
    let addr: SocketAddr = format!("{HOST}:{puerto}").parse().ok()?;
    let mut s = TcpStream::connect_timeout(&addr, espera).ok()?;
    s.set_read_timeout(Some(espera)).ok()?;
    s.set_write_timeout(Some(espera)).ok()?;
    write!(s, "GET {ruta} HTTP/1.0\r\nHost: {HOST}:{puerto}\r\nConnection: close\r\n\r\n").ok()?;
    let mut buf = Vec::new();
    let _ = s.take(64 * 1024).read_to_end(&mut buf);
    let texto = String::from_utf8_lossy(&buf).into_owned();
    let estado = texto.split_whitespace().nth(1)?.parse().ok()?;
    let cuerpo = texto.split_once("\r\n\r\n").map(|(_, c)| c.to_string()).unwrap_or_default();
    Some((estado, cuerpo))
}

/// ¿Lo que ocupa el puerto es otra instancia de Prig?
fn prig_en_marcha(puerto: u16) -> bool {
    matches!(pedir(puerto, "/api/workspace", Duration::from_secs(2)), Some((200, c)) if c.contains("\"path\""))
}

pub enum Puerto {
    /// Libre: el listener ya reservado (sin carrera entre comprobar y usar)
    Libre(TcpListener),
    /// Ya hay un Prig en ese puerto: se abre una ventana sobre él
    EnMarcha(u16),
}

pub fn elegir_puerto() -> Result<Puerto, String> {
    if let Ok(l) = TcpListener::bind((HOST, PUERTO_PREFERIDO)) {
        return Ok(Puerto::Libre(l));
    }
    if prig_en_marcha(PUERTO_PREFERIDO) {
        println!("ℹ️  Prig ya estaba en marcha en el puerto {PUERTO_PREFERIDO}: se abre una ventana sobre esa instancia.");
        return Ok(Puerto::EnMarcha(PUERTO_PREFERIDO));
    }
    for p in PUERTO_PREFERIDO + 1..PUERTO_PREFERIDO + RANGO {
        if let Ok(l) = TcpListener::bind((HOST, p)) {
            println!("ℹ️  El puerto {PUERTO_PREFERIDO} está ocupado por otro programa: se usa el {p}.");
            return Ok(Puerto::Libre(l));
        }
    }
    Err(format!("No hay ningún puerto libre entre {PUERTO_PREFERIDO} y {}.", PUERTO_PREFERIDO + RANGO - 1))
}

fn puerto_libre_desde(desde: u16, excluir: u16) -> Option<u16> {
    (desde..desde + RANGO).filter(|p| *p != excluir).find(|p| TcpListener::bind((HOST, *p)).is_ok())
}

// ---------------------------------------------------------------------------------------------- huérfanos

fn leer(p: impl AsRef<Path>) -> String {
    std::fs::read_to_string(p).unwrap_or_default()
}

fn padre_de(pid: u32) -> Option<u32> {
    // /proc/<pid>/stat: «pid (comm) estado ppid ...»; comm puede llevar espacios y paréntesis
    let stat = leer(format!("/proc/{pid}/stat"));
    stat.rsplit_once(')')?.1.split_whitespace().nth(1)?.parse().ok()
}

/// Servidores de Prig que quedaron sueltos de una sesión anterior (su padre ya es init/systemd): un `prig-server`
/// o un `prig` de esta carpeta y el backend de Python (`uvicorn backend.app:app` lanzado desde la raíz). Uno
/// arrancado a mano desde una terminal no se toca.
pub fn limpiar_huerfanos(raiz: &Path) {
    if prig_server::routes::moe::limpiar_huerfanos(raiz) > 0 {
        println!("🧹 Motor MoE: cerrado un servidor que quedó de una sesión anterior");
    }
    let yo = std::process::id();
    let uid = unsafe { libc::getuid() };
    let binarios: Vec<PathBuf> = ["prig-server", "prig"]
        .iter()
        .map(|b| raiz.join("backend-rust/target/release").join(b))
        .filter_map(|p| p.canonicalize().ok())
        .collect();
    let Ok(dir) = std::fs::read_dir("/proc") else { return };
    for e in dir.flatten() {
        let Some(pid) = e.file_name().to_str().and_then(|n| n.parse::<u32>().ok()) else { continue };
        if pid == yo {
            continue;
        }
        let ruta = e.path();
        if std::os::unix::fs::MetadataExt::uid(&match ruta.metadata() {
            Ok(m) => m,
            Err(_) => continue,
        }) != uid
        {
            continue;
        }
        let exe = std::fs::read_link(ruta.join("exe")).ok().and_then(|p| p.canonicalize().ok());
        let cmd: Vec<String> = leer(ruta.join("cmdline")).split('\0').filter(|s| !s.is_empty()).map(String::from).collect();
        let es_rust = exe.as_ref().is_some_and(|x| binarios.contains(x));
        let cwd = std::fs::read_link(ruta.join("cwd")).ok();
        let es_python = cmd.join(" ").contains("uvicorn") && cmd.iter().any(|c| c == "backend.app:app") && cwd.as_deref() == Some(raiz);
        if !(es_rust || es_python) {
            continue;
        }
        let Some(ppid) = padre_de(pid) else { continue };
        let comm_padre = leer(format!("/proc/{ppid}/comm")).trim().to_string();
        if ppid != 1 && comm_padre != "systemd" && comm_padre != "init" {
            continue;
        }
        println!("🧹 Cerrando un servidor de Prig que quedó suelto de una sesión anterior (pid {pid}).");
        unsafe { libc::kill(pid as i32, libc::SIGTERM) };
        let limite = Instant::now() + Duration::from_secs(8);
        while Instant::now() < limite && Path::new(&format!("/proc/{pid}")).exists() {
            std::thread::sleep(Duration::from_millis(100));
        }
        if Path::new(&format!("/proc/{pid}")).exists() {
            unsafe { libc::kill(pid as i32, libc::SIGKILL) };
        }
    }
}

// ---------------------------------------------------------------------------------------------- Python

fn interprete(raiz: &Path) -> PathBuf {
    let venv = raiz.join(".venv/bin/python");
    if venv.exists() {
        venv
    } else {
        PathBuf::from("python3")
    }
}

fn lanzar_python(raiz: &Path, puerto: u16, puerto_rust: u16) -> std::io::Result<Child> {
    let backend = raiz.join("backend");
    let pythonpath = match std::env::var("PYTHONPATH") {
        Ok(p) if !p.is_empty() => format!("{}:{p}", backend.display()),
        _ => backend.display().to_string(),
    };
    let mut c = Command::new(interprete(raiz));
    c.args(["-m", "uvicorn", "backend.app:app", "--host", HOST, "--port", &puerto.to_string(), "--log-level", "error"])
        .current_dir(raiz)
        .env("PYTHONPATH", pythonpath)
        // el motor MoE es del servidor de Rust: Python le pide ahí (ai_engine/motor_moe.py)
        .env("PRIG_PUERTO_RUST", puerto_rust.to_string())
        .stdin(Stdio::null());
    // SAFETY: prctl en el hijo antes de exec: si Prig muere de golpe, el kernel le manda SIGTERM (no queda suelto
    // ocupando el puerto ni la VRAM)
    unsafe {
        c.pre_exec(|| {
            libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
            Ok(())
        });
    }
    c.spawn()
}

/// Espera a que el puerto conteste a `ruta` (cualquier estado) mientras el proceso siga vivo
fn esperar(puerto: u16, ruta: &str, hijo: &Mutex<Option<Child>>, segundos: u64) -> bool {
    let limite = Instant::now() + Duration::from_secs(segundos);
    while Instant::now() < limite {
        if let Some(c) = hijo.lock().unwrap().as_mut() {
            if c.try_wait().ok().flatten().is_some() {
                return false;
            }
        }
        if pedir(puerto, ruta, Duration::from_secs(1)).is_some() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

fn terminar(hijo: &mut Child, espera: Duration) {
    if hijo.try_wait().ok().flatten().is_some() {
        return;
    }
    unsafe { libc::kill(hijo.id() as i32, libc::SIGTERM) };
    let limite = Instant::now() + espera;
    while Instant::now() < limite {
        if hijo.try_wait().ok().flatten().is_some() {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = hijo.kill();
    let _ = hijo.wait();
}

// ---------------------------------------------------------------------------------------------- el conjunto

pub struct Servidores {
    pub puerto: u16,
    pub puerto_python: u16,
    raiz: PathBuf,
    python: Arc<Mutex<Option<Child>>>,
    apagando: Arc<AtomicBool>,
    parar_rust: Mutex<Option<tokio::sync::oneshot::Sender<()>>>,
    hilo_rust: Mutex<Option<std::thread::JoinHandle<()>>>,
}

impl Servidores {
    /// Arranca el servidor de Rust en `listener` (ya reservado) y Python en el primer puerto libre siguiente
    pub fn arrancar(raiz: &Path, listener: TcpListener) -> Result<Arc<Servidores>, String> {
        let puerto = listener.local_addr().map_err(|e| e.to_string())?.port();
        let puerto_python = puerto_libre_desde(puerto + 1, puerto).ok_or("No hay puerto libre para el backend de Python.")?;
        let hijo = lanzar_python(raiz, puerto_python, puerto).map_err(|e| format!("No se pudo arrancar el backend de Python: {e}"))?;

        // El servidor de Rust, en este proceso, con su propio runtime
        let (parar, al_parar) = tokio::sync::oneshot::channel::<()>();
        let raiz_srv = raiz.to_path_buf();
        listener.set_nonblocking(true).map_err(|e| e.to_string())?;
        let hilo = std::thread::Builder::new()
            .name("prig-servidor".into())
            .spawn(move || {
                let rt = match tokio::runtime::Builder::new_multi_thread().enable_all().build() {
                    Ok(rt) => rt,
                    Err(e) => return eprintln!("❌ No se pudo crear el runtime del servidor: {e}"),
                };
                rt.block_on(async move {
                    let frontend = raiz_srv.join("frontend");
                    let assets = Some(raiz_srv.join("assets")).filter(|a| a.exists());
                    let mut estado = prig_server::AppState::new(raiz_srv.clone(), frontend, assets, format!("http://{HOST}:{puerto_python}"));
                    estado.puerto = puerto;
                    // lo que Python preparaba al arrancar (las citas de muestra de las librerías)
                    prig_server::routes::librerias::preparar();
                    let app = prig_server::create_app(estado);
                    let l = match tokio::net::TcpListener::from_std(listener) {
                        Ok(l) => l,
                        Err(e) => return eprintln!("❌ El servidor de Rust no pudo usar el puerto {puerto}: {e}"),
                    };
                    let parar = async {
                        let _ = al_parar.await;
                    };
                    if let Err(e) = axum::serve(l, app).with_graceful_shutdown(parar).await {
                        eprintln!("❌ El servidor de Rust se detuvo: {e}");
                    }
                });
            })
            .map_err(|e| e.to_string())?;

        let s = Arc::new(Servidores {
            puerto,
            puerto_python,
            raiz: raiz.to_path_buf(),
            python: Arc::new(Mutex::new(Some(hijo))),
            apagando: Arc::new(AtomicBool::new(false)),
            parar_rust: Mutex::new(Some(parar)),
            hilo_rust: Mutex::new(Some(hilo)),
        });
        if !esperar(puerto, "/api/health", &Mutex::new(None), 15) {
            s.apagar();
            return Err("El servidor de Rust no respondió.".into());
        }
        Ok(s)
    }

    /// Espera a que Python conteste (la interfaz no se carga antes: si no, medio programa daba 502)
    pub fn esperar_python(&self) -> bool {
        esperar(self.puerto_python, "/api/workspace", &self.python, 120)
    }

    /// Si Python se cae con Prig abierto, se vuelve a arrancar (mientras tanto el proxy hace esperar a las peticiones
    /// hasta un minuto); más de 5 caídas en un minuto, no se insiste
    pub fn vigilar(self: &Arc<Self>) {
        let s = Arc::clone(self);
        let _ = std::thread::Builder::new().name("prig-vigilante".into()).spawn(move || {
            let mut caidas: Vec<Instant> = Vec::new();
            while !s.apagando.load(Ordering::SeqCst) {
                std::thread::sleep(Duration::from_secs(1));
                if s.apagando.load(Ordering::SeqCst) {
                    break;
                }
                let mut g = s.python.lock().unwrap();
                let muerto = g.as_mut().is_some_and(|c| c.try_wait().ok().flatten().is_some());
                if !muerto {
                    continue;
                }
                caidas.retain(|t| t.elapsed() < Duration::from_secs(60));
                if caidas.len() >= 5 {
                    eprintln!("❌ El backend de Python se cayó 5 veces en un minuto: no se reinicia más.");
                    *g = None;
                    continue;
                }
                caidas.push(Instant::now());
                eprintln!("⚠️ El backend de Python se cayó: se vuelve a arrancar.");
                match lanzar_python(&s.raiz, s.puerto_python, s.puerto) {
                    Ok(c) => *g = Some(c),
                    Err(e) => {
                        eprintln!("❌ No se pudo volver a arrancar Python: {e}");
                        *g = None;
                    }
                }
            }
        });
    }

    /// Primero Rust (deja de recibir peticiones) y después Python, con tiempo para su limpieza: soltar los modelos
    /// de la GPU, parar el motor MoE y las ejecuciones en curso
    pub fn apagar(&self) {
        if self.apagando.swap(true, Ordering::SeqCst) {
            return;
        }
        println!("\n🛑 Cerrando Prig IDE: apagando análisis y procesos en ejecución...");
        if let Some(p) = self.parar_rust.lock().unwrap().take() {
            let _ = p.send(());
        }
        if let Some(h) = self.hilo_rust.lock().unwrap().take() {
            let limite = Instant::now() + Duration::from_secs(3);
            while !h.is_finished() && Instant::now() < limite {
                std::thread::sleep(Duration::from_millis(50));
            }
        }
        if let Some(mut c) = self.python.lock().unwrap().take() {
            terminar(&mut c, Duration::from_secs(20));
        }
        // el llama-server del motor MoE (si muriera Prig de golpe, lo para el kernel: PDEATHSIG)
        prig_server::routes::moe::detener();
        println!("✅ Procesos y análisis apagados correctamente.");
    }
}

impl Drop for Servidores {
    fn drop(&mut self) {
        self.apagar();
    }
}
