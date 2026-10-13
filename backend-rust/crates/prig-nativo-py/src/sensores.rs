//! Sensores (prig_recursos::sensores y ::nvml) para `backend/recursos/termico.py` y `nvml.py`: los diccionarios con
//! las mismas claves que daba Python.

use prig_recursos::{nvml, sensores};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::path::Path;

fn gpu_nvml<'py>(py: Python<'py>, g: &nvml::GpuNvml) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("indice", g.indice)?;
    d.set_item("nombre", &g.nombre)?;
    d.set_item("temp", g.temp)?;
    d.set_item("consumo_w", g.consumo_w)?;
    d.set_item("uso_pct", g.uso_pct)?;
    d.set_item("ventilador_pct", g.ventilador_pct)?;
    d.set_item("vram_usada_mb", g.vram_usada_mb)?;
    d.set_item("vram_total_mb", g.vram_total_mb)?;
    d.set_item("reloj_mhz", g.reloj_mhz)?;
    Ok(d)
}

fn gpu_sensor<'py>(py: Python<'py>, g: &sensores::GpuSensor) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("id", &g.id)?;
    d.set_item("tipo", "gpu")?;
    d.set_item("nombre", &g.nombre)?;
    d.set_item("temp", g.temp)?;
    d.set_item("consumo_w", g.consumo_w)?;
    d.set_item("uso_pct", g.uso_pct)?;
    d.set_item("ventilador_pct", g.ventilador_pct)?;
    Ok(d)
}

fn componente<'py>(py: Python<'py>, c: &sensores::Componente) -> PyResult<Bound<'py, PyDict>> {
    use sensores::Componente;
    let (alto, critico) = match c {
        Componente::Gpu(g) => return gpu_sensor(py, g),
        Componente::Cpu { alto, critico, .. } | Componente::Otro { alto, critico, .. } => (alto, critico),
    };
    let d = PyDict::new(py);
    d.set_item("id", c.id())?;
    d.set_item("tipo", c.tipo())?;
    d.set_item("nombre", c.nombre())?;
    d.set_item("temp", c.temp())?;
    if let Componente::Cpu { nucleo_max, nucleos, .. } = c {
        d.set_item("nucleo_max", nucleo_max)?;
        let lista = PyList::empty(py);
        for (etiqueta, temp) in nucleos {
            let n = PyDict::new(py);
            n.set_item("etiqueta", etiqueta)?;
            n.set_item("temp", temp)?;
            lista.append(n)?;
        }
        d.set_item("nucleos", lista)?;
    }
    d.set_item("alto", alto)?;
    d.set_item("critico", critico)?;
    Ok(d)
}

pub fn lectura_a_python<'py>(py: Python<'py>, l: &sensores::Lectura) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("tomada", l.tomada)?;
    let componentes = PyList::empty(py);
    for c in &l.componentes {
        componentes.append(componente(py, c)?)?;
    }
    d.set_item("componentes", componentes)?;
    let ventiladores = PyList::empty(py);
    for v in &l.ventiladores {
        let f = PyDict::new(py);
        f.set_item("id", &v.id)?;
        f.set_item("nombre", &v.nombre)?;
        f.set_item("rpm", v.rpm)?;
        ventiladores.append(f)?;
    }
    d.set_item("ventiladores", ventiladores)?;
    Ok(d)
}

/// ¿Hay NVML? (la primera vez la carga: ~2 s)
#[pyfunction]
fn nvml_disponible(py: Python<'_>) -> bool {
    py.detach(nvml::disponible)
}

/// `nvml.lectura()`: [{indice, nombre, temp, consumo_w, uso_pct, ventilador_pct, vram_usada_mb, vram_total_mb,
/// reloj_mhz}] o None sin NVML
#[pyfunction]
fn nvml_lectura(py: Python<'_>) -> PyResult<Option<Vec<Bound<'_, PyDict>>>> {
    match py.detach(nvml::lectura) {
        Some(gpus) => Ok(Some(gpus.iter().map(|g| gpu_nvml(py, g)).collect::<PyResult<_>>()?)),
        None => Ok(None),
    }
}

/// `termico._nvidia()`: las GPU NVIDIA con temperatura, por NVML o nvidia-smi
#[pyfunction]
fn gpus_nvidia(py: Python<'_>) -> PyResult<Vec<Bound<'_, PyDict>>> {
    py.detach(sensores::gpus_nvidia).iter().map(|g| gpu_sensor(py, g)).collect()
}

/// `psutil.sensors_temperatures()`: {chip: [(etiqueta, actual, alto, crítico)]}
#[pyfunction]
fn temperaturas_hwmon(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let t = py.detach(|| sensores::temperaturas(Path::new("/")));
    let d = PyDict::new(py);
    for (chip, lecturas) in t {
        let v: Vec<_> = lecturas.into_iter().map(|s| (s.etiqueta, s.actual, s.alto, s.critico)).collect();
        d.set_item(chip, v)?;
    }
    Ok(d)
}

/// `psutil.sensors_fans()`: {chip: [(etiqueta, rpm)]}, o None donde psutil lanzaba una excepción
#[pyfunction]
fn ventiladores_hwmon(py: Python<'_>) -> PyResult<Option<Bound<'_, PyDict>>> {
    let Some(f) = py.detach(|| sensores::ventiladores(Path::new("/"))) else { return Ok(None) };
    let d = PyDict::new(py);
    for (chip, lecturas) in f {
        let v: Vec<_> = lecturas.into_iter().map(|s| (s.etiqueta, s.actual)).collect();
        d.set_item(chip, v)?;
    }
    Ok(Some(d))
}

/// (etiqueta, actual, alto, crítico): la tupla de psutil
type TuplaSensor = (String, Option<f64>, Option<f64>, Option<f64>);

fn opcional(d: &Bound<'_, PyDict>, clave: &str) -> PyResult<Option<f64>> {
    match d.get_item(clave)? {
        Some(v) if !v.is_none() => Ok(Some(v.extract()?)),
        _ => Ok(None),
    }
}

/// `termico.leer_sensores()` con las lecturas ya hechas (las pruebas las dan simuladas): {tomada, componentes,
/// ventiladores}
#[pyfunction]
fn clasificar_sensores<'py>(
    py: Python<'py>,
    gpus: Vec<Bound<'py, PyDict>>,
    temps: &Bound<'py, PyDict>,
    fans: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let gpus = gpus
        .iter()
        .map(|g| {
            Ok(sensores::GpuSensor {
                id: g.get_item("id")?.map(|v| v.extract()).transpose()?.unwrap_or_default(),
                nombre: g.get_item("nombre")?.map(|v| v.extract()).transpose()?.unwrap_or_default(),
                temp: opcional(g, "temp")?,
                consumo_w: opcional(g, "consumo_w")?,
                uso_pct: opcional(g, "uso_pct")?,
                ventilador_pct: opcional(g, "ventilador_pct")?,
            })
        })
        .collect::<PyResult<Vec<_>>>()?;
    let mut t = Vec::new();
    for (chip, lecturas) in temps.iter() {
        let lecturas: Vec<TuplaSensor> = lecturas.extract()?;
        let lecturas = lecturas
            .into_iter()
            .map(|(etiqueta, actual, alto, critico)| sensores::SensorT { etiqueta, actual, alto, critico })
            .collect();
        t.push((chip.extract::<String>()?, lecturas));
    }
    let mut f = Vec::new();
    for (chip, lecturas) in fans.iter() {
        let lecturas: Vec<(String, i64)> = lecturas.extract()?;
        let lecturas =
            lecturas.into_iter().map(|(etiqueta, actual)| sensores::VentiladorT { etiqueta, actual }).collect();
        f.push((chip.extract::<String>()?, lecturas));
    }
    lectura_a_python(py, &sensores::clasificar(gpus, &t, &f))
}

/// Toda la lectura en Rust (GPU, hwmon y clasificación), sin pasar por Python
#[pyfunction]
fn leer_sensores(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let l = py.detach(sensores::leer_sensores);
    lectura_a_python(py, &l)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(nvml_disponible, m)?)?;
    m.add_function(wrap_pyfunction!(nvml_lectura, m)?)?;
    m.add_function(wrap_pyfunction!(gpus_nvidia, m)?)?;
    m.add_function(wrap_pyfunction!(temperaturas_hwmon, m)?)?;
    m.add_function(wrap_pyfunction!(ventiladores_hwmon, m)?)?;
    m.add_function(wrap_pyfunction!(clasificar_sensores, m)?)?;
    m.add_function(wrap_pyfunction!(leer_sensores, m)?)?;
    Ok(())
}
