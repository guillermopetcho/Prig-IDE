//! Energía de la CPU con permisos de root, opcional (backend/recursos/energia.py): turbo apagado, CPU en ahorro y
//! tope de potencia sostenida. Complementa al modo frío: cada token cuesta menos calor, así que a la misma temperatura
//! el modelo va más rápido.
//!
//! El trabajo de root lo hace SOLO el ayudante `prig-energia` (backend/recursos/nativo/), instalado una vez como root
//! en /usr/local/libexec/ con su política de polkit. Cada uso pasa por pkexec, que pide la contraseña de
//! administrador: Prig nunca guarda contraseñas ni corre como root. Leer el estado no necesita permisos.
//!
//! Pruebas: PRIG_ENERGIA_AYUDANTE (el script a ejecutar), PRIG_ENERGIA_SIN_PKEXEC=1 (ejecutarlo directamente, como
//! usuario) y PRIG_ENERGIA_RAIZ (un /sys falso).

use crate::json;
use crate::motor_suave::{correr, ejecutable, primeros};
use crate::valor::{Mapa, Valor};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const VATIOS_POR_DEFECTO: i64 = 20;

/// Dónde están el ayudante y su política, instalados y en las fuentes de Prig
#[derive(Debug, Clone)]
pub struct Rutas {
    pub ayudante: PathBuf,
    pub politica: PathBuf,
    pub fuente_ayudante: PathBuf,
    pub fuente_politica: PathBuf,
}

#[derive(Debug)]
pub enum ErrorEnergia {
    /// El ErrorEnergia de Python, con su mensaje
    Energia(String),
    /// Un error del sistema (OSError en Python)
    Io(std::io::Error),
}

impl From<std::io::Error> for ErrorEnergia {
    fn from(e: std::io::Error) -> Self {
        ErrorEnergia::Io(e)
    }
}

fn entorno(nombre: &str) -> Option<String> {
    std::env::var(nombre).ok().filter(|v| !v.is_empty())
}

fn raiz() -> String {
    std::env::var("PRIG_ENERGIA_RAIZ").unwrap_or_default()
}

fn ayudante(r: &Rutas) -> PathBuf {
    entorno("PRIG_ENERGIA_AYUDANTE").map(PathBuf::from).unwrap_or_else(|| r.ayudante.clone())
}

fn leer(ruta: &str) -> Option<String> {
    std::fs::read_to_string(format!("{}{ruta}", raiz())).ok().map(|t| t.trim().to_string())
}

/// `_sha(a) == _sha(b)`: mismo contenido (dos archivos ilegibles también cuentan como iguales, como en Python)
fn mismo_contenido(a: &Path, b: &Path) -> bool {
    std::fs::read(a).ok() == std::fs::read(b).ok()
}

/// ¿Está el ayudante instalado, es de root y es la versión de este Prig?
pub fn instalacion(r: &Rutas) -> Mapa {
    if entorno("PRIG_ENERGIA_AYUDANTE").is_some() {
        return Mapa::new().con("instalado", true).con("al_dia", true).con("seguro", true);
    }
    let pkexec = ejecutable("pkexec").is_some();
    let Ok(st) = std::fs::metadata(&r.ayudante) else {
        return Mapa::new().con("instalado", false).con("al_dia", false).con("seguro", false).con("pkexec", pkexec);
    };
    // Solo es seguro si nadie más que root puede cambiarlo
    let seguro = st.uid() == 0 && st.mode() & 0o022 == 0;
    Mapa::new()
        .con("instalado", r.politica.is_file())
        .con(
            "al_dia",
            mismo_contenido(&r.ayudante, &r.fuente_ayudante) && mismo_contenido(&r.politica, &r.fuente_politica),
        )
        .con("seguro", seguro)
        .con("pkexec", pkexec)
}

/// Turbo, gobernador, preferencia de energía y tope de potencia, sin permisos
pub fn estado(r: &Rutas) -> Mapa {
    let no_turbo = leer("/sys/devices/system/cpu/intel_pstate/no_turbo");
    let boost = leer("/sys/devices/system/cpu/cpufreq/boost");
    let turbo: Valor = match (&no_turbo, &boost) {
        (Some(n), _) => (n == "0").into(),
        (None, Some(b)) => (b == "1").into(),
        _ => Valor::Nulo,
    };
    let pl1 = leer("/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw");
    let pl1_w: Valor = match &pl1 {
        Some(p) if !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()) => {
            p.parse::<i128>().map(|v| Valor::Entero(v / 1_000_000)).unwrap_or(Valor::Nulo)
        }
        _ => Valor::Nulo,
    };
    let modo = leer("/run/prig-energia/modo").filter(|m| !m.is_empty()).unwrap_or_else(|| "normal".into());
    let auto = ["/snap/bin/auto-cpufreq", "/usr/local/bin/auto-cpufreq", "/usr/bin/auto-cpufreq"]
        .iter()
        .any(|p| Path::new(&format!("{}{p}", raiz())).exists());
    Mapa::new()
        .con("turbo", turbo)
        .con("gobernador", leer("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"))
        .con("preferencia", leer("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"))
        .con("pl1_w", pl1_w)
        .con("modo", modo)
        .con("auto_cpufreq", auto)
        .fusion(&instalacion(r))
}

/// (código, stdout, stderr) de la orden, como root por pkexec (o directa con PRIG_ENERGIA_SIN_PKEXEC=1)
fn pkexec(args: &[String]) -> Result<(i32, String, String), ErrorEnergia> {
    let plazo = Duration::from_secs(120);
    if std::env::var("PRIG_ENERGIA_SIN_PKEXEC").as_deref() == Ok("1") {
        return Ok(correr(Path::new(&args[0]), &args[1..], plazo)?);
    }
    let Some(pk) = ejecutable("pkexec") else {
        return Err(ErrorEnergia::Energia("Falta pkexec (polkit): no se puede pedir permiso de administrador.".into()));
    };
    let r = correr(&pk, args, plazo)?;
    match r.0 {
        126 => Err(ErrorEnergia::Energia("Cancelaste la contraseña: no se cambió nada.".into())),
        127 => Err(ErrorEnergia::Energia("El sistema no dio permiso de administrador.".into())),
        _ => Ok(r),
    }
}

fn texto(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

/// `(r.stderr or r.stdout).strip()[:300]`
fn resumen(salida: &str, error: &str) -> String {
    primeros(if error.is_empty() { salida } else { error }.trim(), 300)
}

/// Copia el ayudante y su política como root (pide la contraseña una vez)
pub fn instalar(r: &Rutas) -> Result<Mapa, ErrorEnergia> {
    let orden = "install -D -o root -g root -m 0755 \"$1\" \"$2\" && install -D -o root -g root -m 0644 \"$3\" \"$4\"";
    let args: Vec<String> = vec![
        "/bin/sh".into(),
        "-c".into(),
        orden.into(),
        "prig-energia".into(),
        texto(&r.fuente_ayudante),
        texto(&r.ayudante),
        texto(&r.fuente_politica),
        texto(&r.politica),
    ];
    let (codigo, salida, error) = pkexec(&args)?;
    if codigo != 0 {
        return Err(ErrorEnergia::Energia(format!("No se pudo instalar el ayudante: {}", resumen(&salida, &error))));
    }
    Ok(estado(r))
}

fn ejecutar(r: &Rutas, orden: &[&str]) -> Result<Mapa, ErrorEnergia> {
    let inst = instalacion(r);
    if !inst.verdad("instalado") {
        return Err(ErrorEnergia::Energia("Primero instala el ayudante de energía (pide la contraseña una vez).".into()));
    }
    if !inst.verdad("seguro") {
        return Err(ErrorEnergia::Energia(format!(
            "{} no es solo de root: por seguridad no se usa. Reinstálalo.",
            texto(&r.ayudante)
        )));
    }
    let mut args = vec![texto(&ayudante(r))];
    args.extend(orden.iter().map(|s| s.to_string()));
    let (_, salida, error) = pkexec(&args)?;
    let ultima = salida.trim().lines().last();
    let datos = ultima.and_then(|l| json::leer(l).ok());
    let Some(datos) = datos else {
        return Err(ErrorEnergia::Energia(format!("El ayudante no respondió bien: {}", resumen(&salida, &error))));
    };
    let Valor::Mapa(datos) = datos else {
        return Err(ErrorEnergia::Energia("El ayudante rechazó la orden.".into()));
    };
    if !datos.verdad("ok") {
        let e = match datos.get("error") {
            Some(v) if v.verdad() => v.texto_py(),
            _ => "El ayudante rechazó la orden.".into(),
        };
        return Err(ErrorEnergia::Energia(e));
    }
    Ok(datos)
}

/// Turbo apagado, CPU en ahorro y tope de potencia en `vatios` (None: no era un entero)
pub fn frio(r: &Rutas, vatios: Option<i64>) -> Result<Mapa, ErrorEnergia> {
    let Some(v) = vatios.filter(|v| (10..=65).contains(v)) else {
        return Err(ErrorEnergia::Energia("El tope de potencia debe estar entre 10 y 65 W.".into()));
    };
    ejecutar(r, &["frio", &v.to_string()])?;
    Ok(estado(r))
}

/// Lo que había antes de «frio»
pub fn normal(r: &Rutas) -> Result<Mapa, ErrorEnergia> {
    ejecutar(r, &["normal"])?;
    Ok(estado(r))
}
