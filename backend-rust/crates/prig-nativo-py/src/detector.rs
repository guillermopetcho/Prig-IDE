//! Radiografía de la máquina (prig_recursos::detector) para `backend/recursos/detector.py`

use crate::valor::{mapa_a_python, mapa_de_python};
use prig_recursos::detector;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

#[pyfunction]
fn gpus_nvidia<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
    let g = py.detach(detector::gpus_nvidia).map_err(PyValueError::new_err)?;
    let l = PyList::empty(py);
    for x in &g {
        l.append(mapa_a_python(py, x)?)?;
    }
    Ok(l)
}

#[pyfunction]
fn gpus_amd<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
    let g = py.detach(detector::gpus_amd);
    let l = PyList::empty(py);
    for x in &g {
        l.append(mapa_a_python(py, x)?)?;
    }
    Ok(l)
}

#[pyfunction]
fn cpu<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &py.detach(detector::cpu))
}

#[pyfunction]
fn memoria<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &detector::memoria())
}

/// Velocidad de copia de memoria, en GB/s (tarda unos 200 ms; sin el GIL)
#[pyfunction]
#[pyo3(signature = (mb = 256))]
fn ancho_banda_ram(py: Python<'_>, mb: usize) -> f64 {
    py.detach(|| detector::ancho_banda_ram(mb))
}

#[pyfunction]
#[pyo3(signature = (ruta = None))]
fn disco<'py>(py: Python<'py>, ruta: Option<&str>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &detector::disco(ruta))
}

#[pyfunction]
fn energia<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &detector::energia())
}

#[pyfunction]
fn sistema<'py>(py: Python<'py>, version_python: &str, plataforma: &str) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &detector::sistema(version_python, plataforma))
}

/// Qué Ollama hay en `url` (y si su binario es del Prig de `raiz`)
#[pyfunction]
fn ollama<'py>(py: Python<'py>, url: &str, raiz: &str) -> PyResult<Bound<'py, PyDict>> {
    let o = py.detach(|| detector::ollama(url, raiz));
    mapa_a_python(py, &o)
}

#[pyfunction]
fn huella(datos: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(detector::huella(&mapa_de_python(datos)?))
}

#[pyfunction]
fn radiografia<'py>(
    py: Python<'py>,
    medir_ram: bool,
    version_python: &str,
    plataforma: &str,
    url: &str,
    raiz: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let r = py.detach(|| detector::radiografia(medir_ram, version_python, plataforma, url, raiz)).map_err(PyValueError::new_err)?;
    mapa_a_python(py, &r)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(gpus_nvidia, m)?)?;
    m.add_function(wrap_pyfunction!(gpus_amd, m)?)?;
    m.add_function(wrap_pyfunction!(cpu, m)?)?;
    m.add_function(wrap_pyfunction!(memoria, m)?)?;
    m.add_function(wrap_pyfunction!(ancho_banda_ram, m)?)?;
    m.add_function(wrap_pyfunction!(disco, m)?)?;
    m.add_function(wrap_pyfunction!(energia, m)?)?;
    m.add_function(wrap_pyfunction!(sistema, m)?)?;
    m.add_function(wrap_pyfunction!(ollama, m)?)?;
    m.add_function(wrap_pyfunction!(huella, m)?)?;
    m.add_function(wrap_pyfunction!(radiografia, m)?)?;
    Ok(())
}
