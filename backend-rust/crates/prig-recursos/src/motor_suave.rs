//! Motor suave (backend/recursos/motor_suave.py): el modo suave aplicado DENTRO del proceso del modelo, no cortando
//! peticiones.
//!
//! Pieza nativa: backend/recursos/nativo/prig_suave.c (con sus mediciones). Se compila con el gcc del sistema a
//! <Prig>/lib/prig/prig_suave.so y se precarga en el llama-server del Ollama PROPIO de Prig con un envoltorio:
//!     llama-server        → guion de Prig: al cargar un modelo añade LD_PRELOAD y --poll 0
//!     llama-server.real   → el lanzador original de Ollama, intacto
//! El Ollama del sistema nunca se toca.
//!
//! Control: dos veces por segundo se escribe «fraccion tramo marca» en el archivo de control (tmpfs del usuario). Si
//! Prig se cierra, la marca caduca a los 5 s y el motor vuelve a trabajar a pleno. El motor escribe su estado cada
//! segundo en «<control>.estado».

use crate::ritmo::Ritmo;
use crate::valor::{Mapa, Valor};
use std::io::{self, Read};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub const MARCA_ENVOLTORIO: &str = "# Prig · motor suave";
pub const ACTIVO_S: f64 = 2.0; // el motor escribió su estado hace menos de esto → está generando

/// Las rutas del motor suave (cada una se puede cambiar por el entorno, como en Python)
#[derive(Debug, Clone)]
pub struct Rutas {
    pub control: PathBuf,
    pub biblioteca: PathBuf,
    pub ollama: PathBuf,
    pub fuente: PathBuf,
}

fn entorno(nombre: &str) -> Option<String> {
    std::env::var(nombre).ok().filter(|v| !v.is_empty())
}

impl Rutas {
    /// `ruta_control()`, `ruta_biblioteca()`, `dir_ollama()` y la fuente C, para la carpeta de Prig `raiz`
    pub fn desde_entorno(raiz: &Path) -> Rutas {
        let control = entorno("PRIG_SUAVE_CONTROL").map(PathBuf::from).unwrap_or_else(|| {
            PathBuf::from(entorno("XDG_RUNTIME_DIR").unwrap_or_else(|| "/tmp".into())).join("prig_suave")
        });
        Rutas {
            control,
            biblioteca: entorno("PRIG_SUAVE_SO").map(PathBuf::from).unwrap_or_else(|| raiz.join("lib/prig/prig_suave.so")),
            ollama: entorno("PRIG_OLLAMA_LIB").map(PathBuf::from).unwrap_or_else(|| raiz.join("lib/ollama")),
            fuente: raiz.join("backend/recursos/nativo/prig_suave.c"),
        }
    }

    fn con_sufijo(p: &Path, sufijo: &str) -> PathBuf {
        let mut s = p.as_os_str().to_owned();
        s.push(sufijo);
        PathBuf::from(s)
    }
}

fn texto(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

/// `shutil.which`
pub fn ejecutable(nombre: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path).map(|d| d.join(nombre)).find(|p| {
        p.is_file() && std::fs::metadata(p).map(|m| m.permissions().mode() & 0o111 != 0).unwrap_or(false)
    })
}

/// La salida de un programa con plazo: (código, stdout, stderr). Err si no arranca o no termina a tiempo.
pub fn correr(programa: &Path, args: &[String], plazo: Duration) -> io::Result<(i32, String, String)> {
    let mut hijo = Command::new(programa).args(args).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()?;
    let mut so = hijo.stdout.take();
    let mut se = hijo.stderr.take();
    let lector_o = std::thread::spawn(move || {
        let mut b = Vec::new();
        if let Some(s) = so.as_mut() {
            let _ = s.read_to_end(&mut b);
        }
        b
    });
    let lector_e = std::thread::spawn(move || {
        let mut b = Vec::new();
        if let Some(s) = se.as_mut() {
            let _ = s.read_to_end(&mut b);
        }
        b
    });
    let fin = Instant::now() + plazo;
    let codigo = loop {
        if let Some(st) = hijo.try_wait()? {
            break st.code().unwrap_or(-1);
        }
        if Instant::now() >= fin {
            let _ = hijo.kill();
            let _ = hijo.wait();
            return Err(io::Error::new(io::ErrorKind::TimedOut, "tiempo agotado"));
        }
        std::thread::sleep(Duration::from_millis(10));
    };
    let o = String::from_utf8_lossy(&lector_o.join().unwrap_or_default()).into_owned();
    let e = String::from_utf8_lossy(&lector_e.join().unwrap_or_default()).into_owned();
    Ok((codigo, o, e))
}

/// Los primeros `n` caracteres
pub fn primeros(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

// =========================================================================== compilar e instalar

pub fn compilar(r: &Rutas, forzar: bool) -> io::Result<Mapa> {
    let destino = &r.biblioteca;
    if !forzar && destino.exists() && std::fs::metadata(destino)?.modified()? >= std::fs::metadata(&r.fuente)?.modified()? {
        return Ok(Mapa::new().con("ok", true).con("ruta", texto(destino)));
    }
    let Some(compilador) = ejecutable("gcc").or_else(|| ejecutable("cc")) else {
        return Ok(Mapa::new().con("ok", false).con("motivo", "No hay compilador de C (gcc) en el sistema."));
    };
    if let Some(carpeta) = destino.parent() {
        std::fs::create_dir_all(carpeta)?;
    }
    let tmp = Rutas::con_sufijo(destino, ".tmp");
    let args: Vec<String> =
        ["-O2", "-shared", "-fPIC", "-o", &texto(&tmp), &texto(&r.fuente), "-ldl"].iter().map(|s| s.to_string()).collect();
    let (codigo, _, error) = correr(&compilador, &args, Duration::from_secs(60))?;
    if codigo != 0 {
        return Ok(Mapa::new().con("ok", false).con("motivo", format!("No se pudo compilar: {}", primeros(error.trim(), 300))));
    }
    std::fs::rename(&tmp, destino)?;
    Ok(Mapa::new().con("ok", true).con("ruta", texto(destino)))
}

fn es_envoltorio(ruta: &Path) -> bool {
    let Ok(mut f) = std::fs::File::open(ruta) else { return false };
    let mut b = vec![0u8; 400];
    let mut n = 0;
    while n < b.len() {
        match f.read(&mut b[n..]) {
            Ok(0) => break,
            Ok(k) => n += k,
            Err(_) => return false,
        }
    }
    b[..n].windows(MARCA_ENVOLTORIO.len()).any(|w| w == MARCA_ENVOLTORIO.as_bytes())
}

/// `shlex.quote` de Python
pub fn shlex_quote(s: &str) -> String {
    if s.is_empty() {
        return "''".into();
    }
    let seguro = s.chars().all(|c| c.is_ascii_alphanumeric() || "_@%+=:,./-".contains(c));
    if seguro {
        return s.into();
    }
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}

fn guion(biblioteca: &str, control: &str) -> String {
    let (so, ctl) = (shlex_quote(biblioteca), shlex_quote(control));
    format!(
        "#!/bin/sh\n{MARCA_ENVOLTORIO} (backend/recursos/motor_suave.py). El original está en llama-server.real.\n\
         # Al cargar un modelo: espera a la GPU durmiendo en vez de girando y acepta la dosificación de Prig.\n\
         DIR=$(dirname \"$0\")\n\
         if [ -f {so} ] && [ -z \"$PRIG_SUAVE_DESACTIVADO\" ]; then\n  \
         case \" $* \" in\n    \
         *\" --model \"*)\n      \
         LD_PRELOAD={so}${{LD_PRELOAD:+:$LD_PRELOAD}} PRIG_SUAVE_CONTROL=\"${{PRIG_SUAVE_CONTROL:-{ctl}}}\" \\\n        \
         exec \"$DIR/llama-server.real\" \"$@\" --poll 0 ;;\n  \
         esac\n\
         fi\n\
         exec \"$DIR/llama-server.real\" \"$@\"\n"
    )
}

/// Compila la biblioteca y pone el envoltorio en el Ollama de Prig. Idempotente.
pub fn instalar(r: &Rutas) -> io::Result<Mapa> {
    let original = r.ollama.join("llama-server");
    let real = r.ollama.join("llama-server.real");
    if !original.exists() && !real.exists() {
        return Ok(Mapa::new()
            .con("ok", false)
            .con("motivo", "Prig no tiene su propio Ollama: el modo suave pausa las peticiones."));
    }
    let c = compilar(r, false)?;
    if !c.verdad("ok") {
        return Ok(c);
    }
    if original.exists() && !es_envoltorio(&original) {
        std::fs::rename(&original, &real)?; // primera vez, o Ollama se actualizó y trajo uno nuevo
    }
    if !real.exists() {
        return Ok(Mapa::new().con("ok", false).con("motivo", "Falta el llama-server original de Ollama."));
    }
    let contenido = guion(&texto(&r.biblioteca), &texto(&r.control));
    if let Ok(actual) = std::fs::read(&original) {
        match String::from_utf8(actual) {
            Ok(t) if t == contenido => {
                return Ok(Mapa::new().con("ok", true).con("instalado", true).con("cambiado", false));
            }
            Ok(_) => {}
            Err(_) => return Err(io::Error::new(io::ErrorKind::InvalidData, "llama-server no es texto UTF-8")),
        }
    }
    let tmp = Rutas::con_sufijo(&original, ".tmp");
    std::fs::write(&tmp, contenido)?;
    std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(0o755))?;
    std::fs::rename(&tmp, &original)?;
    Ok(Mapa::new().con("ok", true).con("instalado", true).con("cambiado", true))
}

/// Deja el Ollama de Prig exactamente como venía
pub fn desinstalar(r: &Rutas) -> io::Result<Mapa> {
    let original = r.ollama.join("llama-server");
    let real = r.ollama.join("llama-server.real");
    if real.exists() && (!original.exists() || es_envoltorio(&original)) {
        std::fs::rename(&real, &original)?;
    }
    Ok(Mapa::new().con("ok", true).con("instalado", false))
}

pub fn instalado(r: &Rutas) -> bool {
    es_envoltorio(&r.ollama.join("llama-server")) && r.ollama.join("llama-server.real").exists()
}

// =========================================================================== estado y control

/// Lo que escribió el motor
#[derive(Debug, Clone, PartialEq)]
pub struct EstadoMotor {
    pub pid: i128,
    pub ultima: f64,
    pub fraccion: f64,
    pub tramo: f64,
    pub esperas_s: f64,
}

impl EstadoMotor {
    pub fn mapa(&self) -> Mapa {
        Mapa::new()
            .con("pid", self.pid)
            .con("ultima", self.ultima)
            .con("fraccion", self.fraccion)
            .con("tramo", self.tramo)
            .con("esperas_s", self.esperas_s)
    }
}

/// `leer_estado()`: {pid, ultima, fraccion, tramo, esperas_s} o None
pub fn leer_estado(r: &Rutas) -> Option<EstadoMotor> {
    let t = std::fs::read_to_string(Rutas::con_sufijo(&r.control, ".estado")).ok()?;
    let p: Vec<&str> = t.split_whitespace().collect();
    let real = |i: usize| p.get(i).and_then(|x| crate::valor::real_de_texto(x));
    Some(EstadoMotor {
        pid: crate::valor::entero_de_texto(p.first()?)?,
        ultima: real(1)?,
        fraccion: real(2)?,
        tramo: real(3)?,
        esperas_s: real(4)?,
    })
}

pub fn generando(estado: Option<&EstadoMotor>, ahora: f64) -> bool {
    estado.is_some_and(|e| ahora - e.ultima < ACTIVO_S)
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

pub fn escribir_control(r: &Rutas, fraccion: f64, tramo: f64, ahora: f64) {
    let tmp = Rutas::con_sufijo(&r.control, ".tmp");
    let linea = format!("{:.3} {:.4} {:.3}\n", max_py(0.05, min_py(1.0, fraccion)), tramo, ahora);
    if std::fs::write(&tmp, linea).is_ok() {
        let _ = std::fs::rename(&tmp, &r.control);
    }
}

pub fn quitar_control(r: &Rutas) {
    let _ = std::fs::remove_file(&r.control);
    let _ = std::fs::remove_file(Rutas::con_sufijo(&r.control, ".tmp"));
}

// =========================================================================== el controlador

pub const PERIODO_S: f64 = 0.5;
pub const SUBIDA: f64 = 0.02;
pub const BAJADA: f64 = 0.06;
pub const SUAVIZADO: f64 = 0.3; // peso de la lectura nueva en la media de temperatura

/// Lo que el controlador lee y escribe fuera de sí (para poder probarlo y para que Python pueda sustituirlo)
pub trait MundoSuave {
    fn leer_estado(&mut self) -> Option<EstadoMotor>;
    fn generando(&mut self, estado: Option<&EstadoMotor>) -> bool;
    /// La temperatura de la GPU (None si no hay o falla)
    fn gpu(&mut self, max_edad: f64) -> Option<Valor>;
    fn ahora(&mut self) -> f64;
    fn escribir_control(&mut self, fraccion: f64, tramo: f64);
    fn quitar_control(&mut self);
}

/// Dos veces por segundo: temperatura → fracción de trabajo → archivo de control. La temperatura se suaviza con una
/// media exponencial y la fracción cambia despacio (sube como mucho SUBIDA por paso y baja como mucho BAJADA): medido,
/// aplicar directamente la fracción del termostato hacía oscilar la potencia entre 21 y 33 W.
#[derive(Debug, Default)]
pub struct ControladorSuave {
    pub temp_media: Option<Valor>,
    pub fraccion: Option<f64>,
    pub ultimo: Mapa,
}

impl ControladorSuave {
    pub fn paso(&mut self, ritmo: &Mutex<Ritmo>, mundo: &mut dyn MundoSuave) -> Mapa {
        let estado = mundo.leer_estado();
        let activo = mundo.generando(estado.as_ref());
        if activo {
            let a = mundo.ahora();
            ritmo.lock().unwrap_or_else(|e| e.into_inner()).marcar(a);
        }
        let ritmo_activo = || ritmo.lock().unwrap_or_else(|e| e.into_inner()).activo();
        let mut temp = None;
        if activo || ritmo_activo() {
            temp = mundo.gpu(if activo { 1.0 } else { 3.0 });
        }
        if let Some(t) = temp.as_ref().filter(|t| !t.es_nulo()) {
            self.temp_media = Some(match (&self.temp_media, t.num()) {
                (Some(m), Some(x)) => Valor::Real(SUAVIZADO * x + (1.0 - SUAVIZADO) * m.num().unwrap_or(f64::NAN)),
                _ => t.clone(),
            });
        }
        let fraccion;
        if ritmo_activo() {
            let a = mundo.ahora();
            let media = self.temp_media.as_ref().and_then(Valor::num);
            let (objetivo, tramo) = {
                let r = ritmo.lock().unwrap_or_else(|e| e.into_inner());
                let tramo = match r.ajustes.get("tramo_motor_s") {
                    Some(v) if v.verdad() => v.num().unwrap_or(0.02),
                    _ => 0.02,
                };
                (r.fraccion(media, a), tramo)
            };
            fraccion = match self.fraccion {
                Some(f) if activo => min_py(f + SUBIDA, max_py(f - BAJADA, objetivo)),
                _ => objetivo, // parado: la próxima respuesta arranca ya en su punto
            };
            self.fraccion = Some(fraccion);
            mundo.escribir_control(fraccion, tramo);
        } else {
            fraccion = 1.0;
            self.fraccion = None;
            mundo.quitar_control();
        }
        self.ultimo = Mapa::new()
            .con("generando", activo)
            .con("temp", temp.unwrap_or(Valor::Nulo))
            .con("temp_media", self.temp_media.clone().unwrap_or(Valor::Nulo))
            .con("fraccion", fraccion)
            .con("motor", estado.map(|e| Valor::Mapa(e.mapa())).unwrap_or(Valor::Nulo));
        self.ultimo.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn comillas_como_shlex() {
        assert_eq!(shlex_quote("/a/b.so"), "/a/b.so");
        assert_eq!(shlex_quote("/a b/c"), "'/a b/c'");
        assert_eq!(shlex_quote("it's"), "'it'\"'\"'s'");
        assert_eq!(shlex_quote(""), "''");
        assert_eq!(shlex_quote("/ñ"), "'/ñ'");
    }
}
