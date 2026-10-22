//! Temperaturas y ventiladores de la máquina (backend/recursos/termico.py, «Sensores»): la GPU por NVML (o
//! nvidia-smi), y del sistema lo que publique el kernel en hwmon: CPU (paquete y núcleos), SSD NVMe, placa, wifi,
//! batería, ventiladores.
//!
//! `temperaturas` y `ventiladores` leen /sys como `psutil.sensors_temperatures()` y `psutil.sensors_fans()` (psutil
//! 7.2.2, el del .venv de Prig): las mismas entradas, en el mismo orden. `clasificar` es `leer_sensores` de Python.

use crate::nvml;
use std::collections::{BTreeSet, HashSet};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// Una temperatura de hwmon (la tupla de psutil: etiqueta, actual, alto, crítico; en °C)
#[derive(Debug, Clone, PartialEq)]
pub struct SensorT {
    pub etiqueta: String,
    pub actual: Option<f64>,
    pub alto: Option<f64>,
    pub critico: Option<f64>,
}

/// Un ventilador de hwmon (etiqueta, rpm)
#[derive(Debug, Clone, PartialEq)]
pub struct VentiladorT {
    pub etiqueta: String,
    pub actual: i64,
}

/// Una GPU tal como la da `_nvidia()` de Python
#[derive(Debug, Clone, PartialEq)]
pub struct GpuSensor {
    pub id: String,
    pub nombre: String,
    pub temp: Option<f64>,
    pub consumo_w: Option<f64>,
    pub uso_pct: Option<f64>,
    pub ventilador_pct: Option<f64>,
}

/// Un componente de la lectura. Las claves que llegan a la interfaz dependen del origen, como en Python.
#[derive(Debug, Clone, PartialEq)]
pub enum Componente {
    Gpu(GpuSensor),
    Cpu {
        temp: f64,
        nucleo_max: Option<f64>,
        nucleos: Vec<(String, f64)>,
        alto: Option<f64>,
        critico: Option<f64>,
    },
    Otro {
        id: String,
        tipo: &'static str,
        nombre: &'static str,
        temp: f64,
        alto: Option<f64>,
        critico: Option<f64>,
    },
}

impl Componente {
    pub fn id(&self) -> &str {
        match self {
            Componente::Gpu(g) => &g.id,
            Componente::Cpu { .. } => "cpu",
            Componente::Otro { id, .. } => id,
        }
    }

    pub fn tipo(&self) -> &str {
        match self {
            Componente::Gpu(_) => "gpu",
            Componente::Cpu { .. } => "cpu",
            Componente::Otro { tipo, .. } => tipo,
        }
    }

    pub fn nombre(&self) -> &str {
        match self {
            Componente::Gpu(g) => &g.nombre,
            Componente::Cpu { .. } => "CPU",
            Componente::Otro { nombre, .. } => nombre,
        }
    }

    pub fn temp(&self) -> Option<f64> {
        match self {
            Componente::Gpu(g) => g.temp,
            Componente::Cpu { temp, .. } | Componente::Otro { temp, .. } => Some(*temp),
        }
    }

    fn redondear(&mut self) {
        match self {
            Componente::Gpu(g) => g.temp = g.temp.map(redondear_1),
            Componente::Cpu { temp, .. } | Componente::Otro { temp, .. } => *temp = redondear_1(*temp),
        }
    }
}

/// Un ventilador de la lectura
#[derive(Debug, Clone, PartialEq)]
pub struct Ventilador {
    pub id: String,
    pub nombre: String,
    pub rpm: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Lectura {
    pub tomada: f64,
    pub componentes: Vec<Componente>,
    pub ventiladores: Vec<Ventilador>,
}

/// `round(x, 1)` de Python. `{:.1}` redondea el valor decimal exacto, con los empates al par, igual que Python:
/// comprobado en los 220 002 valores de 0 a 200 °C en milésimas y en octavos, sin ninguna diferencia.
pub fn redondear_1(x: f64) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.1}").parse().unwrap_or(x)
}

// =========================================================================== hwmon, como psutil

fn leer_texto(p: &Path) -> Option<String> {
    fs::read(p).ok().map(|b| String::from_utf8_lossy(&b).into_owned())
}

/// `float(bcat(p))` de Python: el número que haya en el archivo (sin espacios alrededor)
fn numero(texto: &str) -> Option<f64> {
    texto.trim().parse::<f64>().ok()
}

/// Los archivos `<carpeta>/<prefijo>*_*` de cada `hwmon*` (o de su `device/`), cortados en el primer «_» de su
/// nombre: «…/hwmon3/temp1_input» → «…/hwmon3/temp1». `glob` + `x.split('_')[0]` de psutil (en /sys/class/hwmon
/// no hay «_» antes del nombre del archivo).
fn bases(hwmon: &Path, sub: Option<&str>, prefijo: &str) -> Vec<String> {
    let mut salida = Vec::new();
    let Ok(entradas) = fs::read_dir(hwmon) else { return salida };
    for e in entradas.flatten() {
        let nombre = e.file_name();
        let Some(nombre) = nombre.to_str() else { continue };
        if !nombre.starts_with("hwmon") {
            continue;
        }
        let mut dir = hwmon.join(nombre);
        if let Some(s) = sub {
            dir = dir.join(s);
        }
        let Ok(archivos) = fs::read_dir(&dir) else { continue };
        for a in archivos.flatten() {
            let n = a.file_name();
            let Some(n) = n.to_str() else { continue };
            if n.starts_with(prefijo) && n[prefijo.len()..].contains('_') {
                let corte = n.split('_').next().unwrap_or(n);
                if let Some(d) = dir.to_str() {
                    salida.push(format!("{d}/{corte}"));
                }
            }
        }
    }
    salida
}

fn agregar<T>(por_chip: &mut Vec<(String, Vec<T>)>, chip: String, valor: T) {
    match por_chip.iter_mut().find(|(c, _)| *c == chip) {
        Some((_, v)) => v.push(valor),
        None => por_chip.push((chip, vec![valor])),
    }
}

fn carpeta_de(base: &str) -> PathBuf {
    Path::new(base).parent().map(Path::to_path_buf).unwrap_or_default()
}

/// ¿Hay sensores de coretemp colgando de la plataforma? (psutil los añade a la lista, pero con rutas que nunca se
/// pueden leer; lo único que cambia es que ya no se mira /sys/class/thermal)
fn hay_coretemp_de_plataforma(raiz: &Path) -> bool {
    let plataforma = raiz.join("sys/devices/platform");
    let Ok(entradas) = fs::read_dir(&plataforma) else { return false };
    for e in entradas.flatten() {
        let n = e.file_name();
        if !n.to_str().is_some_and(|n| n.starts_with("coretemp.")) {
            continue;
        }
        if !bases(&e.path().join("hwmon"), None, "temp").is_empty() {
            return true;
        }
    }
    false
}

/// `psutil.sensors_temperatures()`: {chip: [(etiqueta, actual, alto, crítico)]}, en el orden de psutil.
/// `raiz` es «/» (otra carpeta en las pruebas).
pub fn temperaturas(raiz: &Path) -> Vec<(String, Vec<SensorT>)> {
    temperaturas_de(raiz, |_| true, true)
}

/// Como `temperaturas`, pero solo de los chips que `quiere` (por su nombre) y, sin `umbrales`, sin leer `_max` ni
/// `_crit`: cada lectura de un NVMe o de ACPI cuesta milisegundos y despierta al dispositivo.
pub fn temperaturas_de(raiz: &Path, quiere: impl Fn(&str) -> bool, umbrales: bool) -> Vec<(String, Vec<SensorT>)> {
    let hwmon = raiz.join("sys/class/hwmon");
    let mut todas = bases(&hwmon, None, "temp");
    todas.extend(bases(&hwmon, Some("device"), "temp"));
    let todas: BTreeSet<String> = todas.into_iter().collect();
    let mut por_chip = Vec::new();
    for base in &todas {
        // el nombre primero (barato): así no se lee nada de los chips que no hacen falta
        let Some(chip) = leer_texto(&carpeta_de(base).join("name")) else { continue };
        let chip = chip.trim().to_string();
        if !quiere(&chip) {
            continue;
        }
        let Some(actual) = leer_texto(Path::new(&format!("{base}_input"))).and_then(|t| numero(&t)) else { continue };
        let umbral = |sufijo: &str| {
            if !umbrales {
                return None;
            }
            leer_texto(Path::new(&format!("{base}_{sufijo}"))).and_then(|t| numero(&t)).map(|v| v / 1000.0)
        };
        let (alto, critico) = (umbral("max"), umbral("crit"));
        let etiqueta = leer_texto(Path::new(&format!("{base}_label"))).unwrap_or_default();
        agregar(&mut por_chip, chip, SensorT { etiqueta: etiqueta.trim().to_string(), actual: Some(actual / 1000.0), alto, critico });
    }
    if todas.is_empty() && !hay_coretemp_de_plataforma(raiz) {
        temperaturas_de_zonas(raiz, &mut por_chip);
        por_chip.retain(|(chip, _)| quiere(chip));
    }
    for (_, lecturas) in por_chip.iter_mut() {
        lecturas.iter_mut().for_each(completar_umbrales);
    }
    por_chip
}

/// `psutil.sensors_temperatures()` (la función pública, no la de _pslinux) completa un umbral con el otro:
/// `if high and not critical: critical = high`, y al revés. Por eso el NVMe tiene «crítico» sin archivo `_crit`.
fn completar_umbrales(s: &mut SensorT) {
    let verdadero = |v: Option<f64>| v.is_some_and(|x| x != 0.0); // la verdad de un float en Python (NaN cuenta)
    if verdadero(s.alto) && !verdadero(s.critico) {
        s.critico = s.alto;
    } else if verdadero(s.critico) && !verdadero(s.alto) {
        s.alto = s.critico;
    }
}

/// Sin nada en hwmon: /sys/class/thermal/thermal_zone*. psutil aquí convierte los umbrales dentro del bucle de los
/// puntos de disparo (los divide por 1000 otra vez en cada vuelta, y el orden de las vueltas es el de un conjunto,
/// que cambia de una ejecución a otra); aquí se convierte cada uno una vez y, si hay varios del mismo tipo, gana el
/// último por nombre.
fn temperaturas_de_zonas(raiz: &Path, por_chip: &mut Vec<(String, Vec<SensorT>)>) {
    let thermal = raiz.join("sys/class/thermal");
    let Ok(entradas) = fs::read_dir(&thermal) else { return };
    let zonas: BTreeSet<String> = entradas
        .flatten()
        .filter_map(|e| e.file_name().to_str().map(str::to_string))
        .filter(|n| n.starts_with("thermal_zone"))
        .collect();
    for zona in zonas {
        let base = thermal.join(&zona);
        let Some(actual) = leer_texto(&base.join("temp")).and_then(|t| numero(&t)) else { continue };
        let Some(chip) = leer_texto(&base.join("type")) else { continue };
        let puntos: BTreeSet<String> = fs::read_dir(&base)
            .map(|it| {
                it.flatten()
                    .filter_map(|e| e.file_name().to_str().map(str::to_string))
                    .filter(|n| n.starts_with("trip_point"))
                    .map(|n| n.split('_').take(3).collect::<Vec<_>>().join("_"))
                    .collect()
            })
            .unwrap_or_default();
        let (mut alto, mut critico) = (None, None);
        for p in puntos {
            let tipo = leer_texto(&base.join(format!("{p}_type"))).unwrap_or_default();
            let valor = || leer_texto(&base.join(format!("{p}_temp"))).and_then(|t| numero(&t)).map(|v| v / 1000.0);
            match tipo.trim() {
                "critical" => critico = valor(),
                "high" => alto = valor(),
                _ => {}
            }
        }
        agregar(
            por_chip,
            chip.trim().to_string(),
            SensorT { etiqueta: String::new(), actual: Some(actual / 1000.0), alto, critico },
        );
    }
}

/// `psutil.sensors_fans()`: {chip: [(etiqueta, rpm)]}. `None` donde psutil lanzaría una excepción (un valor que no
/// es un entero, un chip sin nombre); `leer_sensores` de Python lo trataba como «sin ventiladores».
pub fn ventiladores(raiz: &Path) -> Option<Vec<(String, Vec<VentiladorT>)>> {
    let hwmon = raiz.join("sys/class/hwmon");
    let mut todas = bases(&hwmon, None, "fan");
    if todas.is_empty() {
        todas = bases(&hwmon, Some("device"), "fan");
    }
    let todas: BTreeSet<String> = todas.into_iter().collect();
    let mut por_chip = Vec::new();
    for base in &todas {
        let Some(texto) = leer_texto(Path::new(&format!("{base}_input"))) else { continue };
        let actual = texto.trim().parse::<i64>().ok()?;
        let chip = leer_texto(&carpeta_de(base).join("name"))?;
        let etiqueta = leer_texto(Path::new(&format!("{base}_label"))).unwrap_or_default();
        agregar(&mut por_chip, chip.trim().to_string(), VentiladorT { etiqueta: etiqueta.trim().to_string(), actual });
    }
    Some(por_chip)
}

// =========================================================================== GPU

/// Las GPU NVIDIA: por NVML (microsegundos, sin procesos) o, sin NVML, por nvidia-smi
pub fn gpus_nvidia() -> Vec<GpuSensor> {
    if let Some(gpus) = nvml::lectura() {
        return gpus
            .into_iter()
            .filter(|g| g.temp.is_some())
            .map(|g| GpuSensor {
                id: format!("gpu{}", g.indice),
                nombre: g.nombre,
                temp: g.temp,
                consumo_w: g.consumo_w,
                uso_pct: g.uso_pct,
                ventilador_pct: g.ventilador_pct,
            })
            .collect();
    }
    match ejecutable("nvidia-smi").and_then(|p| salida_con_plazo(&p, CONSULTA_NVIDIA_SMI, Duration::from_secs(3))) {
        Some(s) => gpus_de_nvidia_smi(&s),
        None => Vec::new(),
    }
}

const CONSULTA_NVIDIA_SMI: &[&str] =
    &["--query-gpu=index,name,temperature.gpu,power.draw,utilization.gpu,fan.speed", "--format=csv,noheader,nounits"];

/// La salida CSV de nvidia-smi (sin cabecera ni unidades)
pub fn gpus_de_nvidia_smi(salida: &str) -> Vec<GpuSensor> {
    let num = |x: &str| x.parse::<f64>().ok();
    salida
        .trim()
        .lines()
        .filter_map(|linea| {
            let p: Vec<&str> = linea.split(',').map(str::trim).collect();
            if p.len() < 6 {
                return None;
            }
            let temp = num(p[2])?;
            Some(GpuSensor {
                id: format!("gpu{}", p[0]),
                nombre: p[1].to_string(),
                temp: Some(temp),
                consumo_w: num(p[3]),
                uso_pct: num(p[4]),
                ventilador_pct: num(p[5]),
            })
        })
        .collect()
}

/// `shutil.which`: la primera ruta del PATH con ese ejecutable
fn ejecutable(nombre: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path).map(|d| d.join(nombre)).find(|p| {
        let Ok(c) = std::ffi::CString::new(p.as_os_str().as_encoded_bytes()) else { return false };
        // SAFETY: access(2) solo lee la ruta terminada en NUL
        p.is_file() && unsafe { libc::access(c.as_ptr(), libc::X_OK) } == 0
    })
}

/// La salida de un programa, o `None` si falla o no termina a tiempo (entonces se lo mata)
fn salida_con_plazo(programa: &Path, args: &[&str], plazo: Duration) -> Option<String> {
    let mut hijo = Command::new(programa)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    let mut tubo = hijo.stdout.take()?;
    let lector = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = tubo.read_to_end(&mut b);
        b
    });
    let fin = Instant::now() + plazo;
    loop {
        match hijo.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) if Instant::now() < fin => std::thread::sleep(Duration::from_millis(10)),
            _ => {
                let _ = hijo.kill();
                let _ = hijo.wait();
                return None;
            }
        }
    }
    let bytes = lector.join().ok()?;
    String::from_utf8(bytes).ok()
}

// =========================================================================== la lectura

// Cómo se llaman los sensores en hwmon según el fabricante
const CPU: &[&str] = &["coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "soc_thermal"];
const DISCO: &[&str] = &["nvme", "drivetemp"];
const PLACA: &[&str] = &["acpitz", "pch_", "thinkpad", "dell_smm", "asus", "hp"];
const OTROS: &[(&str, &str, &str)] = &[
    ("iwlwifi", "wifi", "Wi-Fi"),
    ("BAT", "bateria", "Batería"),
    ("amdgpu", "gpu", "GPU AMD"),
    ("radeon", "gpu", "GPU AMD"),
];

/// El primero con la temperatura más alta (`max` de Python)
fn mas_caliente<'a>(valores: &[(&'a SensorT, f64)]) -> (&'a SensorT, f64) {
    let mut mejor = valores[0];
    for v in &valores[1..] {
        if v.1 > mejor.1 {
            mejor = *v;
        }
    }
    mejor
}

/// `leer_sensores` de Python, con las lecturas ya hechas: las GPU, las temperaturas y los ventiladores de hwmon
pub fn clasificar(
    gpus: Vec<GpuSensor>,
    temps: &[(String, Vec<SensorT>)],
    fans: &[(String, Vec<VentiladorT>)],
) -> Lectura {
    let mut componentes: Vec<Componente> = gpus.into_iter().map(Componente::Gpu).collect();
    for (chip, lecturas) in temps {
        let valores: Vec<(&SensorT, f64)> = lecturas
            .iter()
            .filter_map(|s| s.actual.filter(|&t| 0.0 < t && t < 150.0).map(|t| (s, t)))
            .collect();
        if valores.is_empty() {
            continue;
        }
        let empieza = |prefijos: &[&str]| prefijos.iter().any(|p| chip.starts_with(p));
        if empieza(CPU) {
            let paquete = valores.iter().find(|(s, _)| {
                let e = s.etiqueta.to_lowercase();
                e.starts_with("package") || e.starts_with("tctl") || e.starts_with("tdie")
            });
            let nucleos: Vec<(String, f64)> = valores
                .iter()
                .filter(|(s, _)| s.etiqueta.to_lowercase().starts_with("core"))
                .map(|(s, t)| (s.etiqueta.clone(), *t))
                .collect();
            let (principal, temp) = paquete.copied().unwrap_or_else(|| mas_caliente(&valores));
            componentes.push(Componente::Cpu {
                temp,
                nucleo_max: nucleos.iter().map(|n| n.1).reduce(|a, b| if b > a { b } else { a }),
                nucleos,
                alto: principal.alto,
                critico: principal.critico,
            });
        } else if empieza(DISCO) {
            for (i, (s, temp)) in valores.iter().enumerate() {
                if !s.etiqueta.is_empty() && s.etiqueta.to_lowercase().starts_with("sensor") {
                    continue; // sensores internos del NVMe, con límites absurdos
                }
                componentes.push(Componente::Otro {
                    id: format!("{chip}{i}"),
                    tipo: "disco",
                    nombre: "SSD",
                    temp: *temp,
                    alto: s.alto,
                    critico: s.critico,
                });
            }
        } else if empieza(PLACA) {
            let (s, temp) = mas_caliente(&valores);
            componentes.push(Componente::Otro {
                id: chip.clone(),
                tipo: "placa",
                nombre: "Placa",
                temp,
                alto: s.alto,
                critico: s.critico,
            });
        } else if let Some(&(_, tipo, nombre)) = OTROS.iter().find(|(p, _, _)| chip.starts_with(p)) {
            let (s, temp) = mas_caliente(&valores);
            componentes.push(Componente::Otro {
                id: chip.clone(),
                tipo,
                nombre,
                temp,
                alto: s.alto,
                critico: s.critico,
            });
        }
    }

    // Un solo registro por placa: acpitz y el del fabricante suelen medir lo mismo
    #[derive(PartialEq, Eq, Hash)]
    enum Clave {
        Par(String, String),
        Id(String),
    }
    let mut vistos = HashSet::new();
    let mut unicos = Vec::new();
    for mut c in componentes {
        let clave = if matches!(c.tipo(), "placa" | "cpu") {
            Clave::Par(c.tipo().to_string(), c.nombre().to_string())
        } else {
            Clave::Id(c.id().to_string())
        };
        if vistos.insert(clave) {
            c.redondear();
            unicos.push(c);
        }
    }

    let mut ventiladores: Vec<Ventilador> = fans
        .iter()
        .flat_map(|(chip, lecturas)| {
            lecturas.iter().enumerate().map(move |(i, s)| Ventilador {
                id: format!("{chip}{i}"),
                nombre: if s.etiqueta.is_empty() { chip.clone() } else { s.etiqueta.clone() },
                rpm: s.actual,
            })
        })
        .collect();
    // acpi_fan suele duplicar uno de los del fabricante
    if ventiladores.len() > 1 {
        let sin_acpi: Vec<Ventilador> =
            ventiladores.iter().filter(|v| !v.id.starts_with("acpi_fan")).cloned().collect();
        if !sin_acpi.is_empty() {
            ventiladores = sin_acpi;
        }
    }

    let tomada = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    Lectura { tomada, componentes: unicos, ventiladores }
}

/// La temperatura de la CPU, leyendo solo sus sensores: la misma que daría `temp_cpu(leer_sensores())` (la del
/// primer chip de CPU con lecturas válidas, su «paquete» o la más alta), sin tocar el disco, la GPU ni ACPI.
/// Para el modo frío, que la pide cada segundo mientras un modelo en RAM genera.
pub fn temp_cpu_rapida(raiz: &Path) -> Option<f64> {
    let es_cpu = |chip: &str| CPU.iter().any(|p| chip.starts_with(p));
    let temps = temperaturas_de(raiz, es_cpu, false);
    let l = clasificar(Vec::new(), &temps, &[]);
    l.componentes.iter().find(|c| c.tipo() == "cpu").and_then(Componente::temp)
}

/// Lee todos los sensores de la máquina
pub fn leer_sensores() -> Lectura {
    let raiz = Path::new("/");
    clasificar(gpus_nvidia(), &temperaturas(raiz), &ventiladores(raiz).unwrap_or_default())
}

// =========================================================================== como valor

fn gpu_valor(g: &GpuSensor) -> crate::valor::Mapa {
    crate::valor::Mapa::new()
        .con("id", g.id.as_str())
        .con("tipo", "gpu")
        .con("nombre", g.nombre.as_str())
        .con("temp", g.temp)
        .con("consumo_w", g.consumo_w)
        .con("uso_pct", g.uso_pct)
        .con("ventilador_pct", g.ventilador_pct)
}

impl Componente {
    /// El diccionario que daba Python (mismas claves, mismo orden)
    pub fn a_valor(&self) -> crate::valor::Valor {
        use crate::valor::{Mapa, Valor};
        let (alto, critico) = match self {
            Componente::Gpu(g) => return gpu_valor(g).into(),
            Componente::Cpu { alto, critico, .. } | Componente::Otro { alto, critico, .. } => (*alto, *critico),
        };
        let mut d = Mapa::new().con("id", self.id()).con("tipo", self.tipo()).con("nombre", self.nombre()).con("temp", self.temp());
        if let Componente::Cpu { nucleo_max, nucleos, .. } = self {
            d.poner("nucleo_max", *nucleo_max);
            let lista = nucleos.iter().map(|(e, t)| Mapa::new().con("etiqueta", e.as_str()).con("temp", *t).into()).collect();
            d.poner("nucleos", Valor::Lista(lista));
        }
        d.con("alto", alto).con("critico", critico).into()
    }
}

impl Lectura {
    /// `{tomada, componentes, ventiladores}` como la daba Python
    pub fn a_valor(&self) -> crate::valor::Valor {
        use crate::valor::{Mapa, Valor};
        let ventiladores = self
            .ventiladores
            .iter()
            .map(|v| Mapa::new().con("id", v.id.as_str()).con("nombre", v.nombre.as_str()).con("rpm", v.rpm).into())
            .collect();
        Mapa::new()
            .con("tomada", self.tomada)
            .con("componentes", Valor::Lista(self.componentes.iter().map(Componente::a_valor).collect()))
            .con("ventiladores", Valor::Lista(ventiladores))
            .into()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(etiqueta: &str, actual: f64, alto: Option<f64>, critico: Option<f64>) -> SensorT {
        SensorT { etiqueta: etiqueta.into(), actual: Some(actual), alto, critico }
    }

    fn f(etiqueta: &str, actual: i64) -> VentiladorT {
        VentiladorT { etiqueta: etiqueta.into(), actual }
    }

    // PruebaSensores.test_lee_intel_nvme_placa_y_ventiladores de Python
    #[test]
    fn lee_intel_nvme_placa_y_ventiladores() {
        let temps = vec![
            (
                "coretemp".to_string(),
                vec![
                    s("Package id 0", 76.0, Some(100.0), Some(100.0)),
                    s("Core 0", 81.0, Some(100.0), Some(100.0)),
                    s("Core 4", 70.0, Some(100.0), Some(100.0)),
                ],
            ),
            (
                "nvme".to_string(),
                vec![s("Composite", 38.85, Some(80.85), Some(83.85)), s("Sensor 1", 38.85, Some(65261.85), Some(65261.85))],
            ),
            ("acpitz".to_string(), vec![s("", 45.0, None, None)]),
        ];
        let fans = vec![
            ("acpi_fan".to_string(), vec![f("", 2204)]),
            ("hp".to_string(), vec![f("", 2204), f("", 2000)]),
        ];
        let gpu = GpuSensor {
            id: "gpu0".into(),
            nombre: "RTX".into(),
            temp: Some(58.0),
            consumo_w: None,
            uso_pct: None,
            ventilador_pct: None,
        };
        let l = clasificar(vec![gpu], &temps, &fans);
        let cpu = l.componentes.iter().find(|c| c.tipo() == "cpu").unwrap();
        assert_eq!(cpu.temp(), Some(76.0));
        let Componente::Cpu { nucleo_max, .. } = cpu else { unreachable!() };
        assert_eq!(*nucleo_max, Some(81.0));
        let discos: Vec<_> = l.componentes.iter().filter(|c| c.tipo() == "disco").collect();
        assert_eq!(discos.len(), 1);
        assert_eq!(discos[0].temp(), Some(38.9));
        assert!(l.componentes.iter().any(|c| c.tipo() == "placa"));
        assert_eq!(l.ventiladores.len(), 2); // sin el acpi_fan duplicado
        assert_eq!(l.componentes[0].temp(), Some(58.0));
    }

    #[test]
    fn amd() {
        let temps = vec![
            ("k10temp".to_string(), vec![s("Tctl", 66.5, None, None)]),
            ("amdgpu".to_string(), vec![s("edge", 55.0, Some(100.0), Some(105.0))]),
        ];
        let l = clasificar(vec![], &temps, &[]);
        assert_eq!(l.componentes.iter().find(|c| c.tipo() == "cpu").unwrap().temp(), Some(66.5));
        assert_eq!(l.componentes.iter().find(|c| c.tipo() == "gpu").unwrap().temp(), Some(55.0));
    }

    #[test]
    fn redondea_como_python() {
        assert_eq!(redondear_1(38.25), 38.2); // empate exacto: al par
        assert_eq!(redondear_1(38.75), 38.8);
        assert_eq!(redondear_1(38.85), 38.9);
    }

    #[test]
    fn nvidia_smi() {
        let g = gpus_de_nvidia_smi("0, NVIDIA GeForce RTX 4050, 45, 7.52, 3, [N/A]\n1, Otra, [N/A], 1, 2, 3\n");
        assert_eq!(g.len(), 1);
        assert_eq!(g[0].id, "gpu0");
        assert_eq!(g[0].temp, Some(45.0));
        assert_eq!(g[0].ventilador_pct, None);
    }

    /// Un /sys de mentira en una carpeta temporal
    struct Sys(PathBuf);

    impl Sys {
        fn nuevo(nombre: &str) -> Sys {
            let p = std::env::temp_dir().join(format!("prig-sensores-{nombre}-{}", std::process::id()));
            let _ = fs::remove_dir_all(&p);
            fs::create_dir_all(&p).unwrap();
            Sys(p)
        }

        fn escribir(&self, ruta: &str, texto: &str) {
            let p = self.0.join(ruta);
            fs::create_dir_all(p.parent().unwrap()).unwrap();
            fs::write(p, texto).unwrap();
        }
    }

    impl Drop for Sys {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn hwmon_como_psutil() {
        let sys = Sys::nuevo("hwmon");
        sys.escribir("sys/class/hwmon/hwmon2/name", "coretemp\n");
        sys.escribir("sys/class/hwmon/hwmon2/temp1_input", "76000\n");
        sys.escribir("sys/class/hwmon/hwmon2/temp1_label", "Package id 0\n");
        sys.escribir("sys/class/hwmon/hwmon2/temp1_max", "100000\n");
        sys.escribir("sys/class/hwmon/hwmon2/temp1_crit", "x\n"); // no es un número: None
        sys.escribir("sys/class/hwmon/hwmon2/temp2_input", "81000\n");
        sys.escribir("sys/class/hwmon/hwmon2/temp3_label", "sin _input\n"); // se salta
        sys.escribir("sys/class/hwmon/hwmon10/name", "nvme\n");
        sys.escribir("sys/class/hwmon/hwmon10/device/name", "nvme\n"); // la carpeta intermedia de CentOS
        sys.escribir("sys/class/hwmon/hwmon10/device/temp1_input", "38850\n");
        sys.escribir("sys/class/hwmon/hwmon10/fan1_input", "2204\n");
        let t = temperaturas(&sys.0);
        // orden de psutil: rutas ordenadas como texto («hwmon10» antes que «hwmon2»)
        assert_eq!(t.iter().map(|(c, _)| c.as_str()).collect::<Vec<_>>(), ["nvme", "coretemp"]);
        assert_eq!(t[0].1, vec![SensorT { etiqueta: String::new(), actual: Some(38.85), alto: None, critico: None }]);
        assert_eq!(t[1].1[0], s("Package id 0", 76.0, Some(100.0), Some(100.0))); // crítico = alto, como psutil
        assert_eq!(t[1].1[1], s("", 81.0, None, None));
        assert_eq!(ventiladores(&sys.0).unwrap(), vec![("nvme".to_string(), vec![f("", 2204)])]);
        // un ventilador con un valor que no es un entero: psutil lanzaba una excepción
        sys.escribir("sys/class/hwmon/hwmon10/fan2_input", "x\n");
        assert_eq!(ventiladores(&sys.0), None);
    }

    #[test]
    fn la_cpu_sola_da_lo_mismo_que_todo() {
        let sys = Sys::nuevo("cpu-sola");
        sys.escribir("sys/class/hwmon/hwmon1/name", "nvme\n");
        sys.escribir("sys/class/hwmon/hwmon1/temp1_input", "38850\n");
        sys.escribir("sys/class/hwmon/hwmon3/name", "coretemp\n");
        sys.escribir("sys/class/hwmon/hwmon3/temp1_input", "76000\n");
        sys.escribir("sys/class/hwmon/hwmon3/temp1_label", "Core 0\n");
        sys.escribir("sys/class/hwmon/hwmon3/temp2_input", "81250\n");
        sys.escribir("sys/class/hwmon/hwmon3/temp2_label", "Package id 0\n");
        let todo = clasificar(vec![], &temperaturas(&sys.0), &[]);
        let cpu = todo.componentes.iter().find(|c| c.tipo() == "cpu").and_then(Componente::temp);
        assert_eq!(cpu, Some(81.2)); // el paquete, redondeado como en Python (81,25 → 81,2)
        assert_eq!(temp_cpu_rapida(&sys.0), cpu);
        let t = temperaturas_de(&sys.0, |c| c == "coretemp", false);
        assert_eq!(t.len(), 1);
        assert!(t[0].1.iter().all(|s| s.alto.is_none() && s.critico.is_none()));
    }

    #[test]
    fn zonas_termicas_sin_hwmon() {
        let sys = Sys::nuevo("zonas");
        sys.escribir("sys/class/thermal/thermal_zone0/type", "x86_pkg_temp\n");
        sys.escribir("sys/class/thermal/thermal_zone0/temp", "52000\n");
        sys.escribir("sys/class/thermal/thermal_zone0/trip_point_0_type", "critical\n");
        sys.escribir("sys/class/thermal/thermal_zone0/trip_point_0_temp", "105000\n");
        sys.escribir("sys/class/thermal/thermal_zone0/trip_point_1_type", "passive\n");
        sys.escribir("sys/class/thermal/thermal_zone0/trip_point_1_temp", "95000\n");
        let t = temperaturas(&sys.0);
        assert_eq!(t, vec![("x86_pkg_temp".to_string(), vec![s("", 52.0, Some(105.0), Some(105.0))])]);
        // con coretemp en la plataforma, psutil ya no mira las zonas
        sys.escribir("sys/devices/platform/coretemp.0/hwmon/hwmon5/temp1_input", "50000\n");
        assert!(temperaturas(&sys.0).is_empty());
    }
}
