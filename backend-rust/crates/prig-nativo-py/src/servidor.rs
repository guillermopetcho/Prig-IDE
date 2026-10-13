//! Ajustes del servidor de Ollama (prig_recursos::servidor) para `backend/recursos/servidor.py`

use crate::valor::{a_python, mapa_a_python, mapa_de_python};
use prig_recursos::servidor as srv;
use prig_recursos::valor::Valor;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::Path;

#[pyfunction]
fn librerias_disponibles(raiz: &str) -> Vec<String> {
    srv::librerias_disponibles(Path::new(raiz))
}

/// Las variables limpias; ValueError con el motivo si alguna no vale
#[pyfunction]
fn validar<'py>(py: Python<'py>, cambios: &Bound<'py, PyAny>, raiz: &str) -> PyResult<Bound<'py, PyDict>> {
    let c = mapa_de_python(cambios)?;
    mapa_a_python(py, &srv::validar(&c, Path::new(raiz)).map_err(PyValueError::new_err)?)
}

#[pyfunction]
fn estado<'py>(py: Python<'py>, info: &Bound<'py, PyAny>, guardado: &Bound<'py, PyAny>, raiz: &str, registro: &str) -> PyResult<Bound<'py, PyDict>> {
    let (i, g) = (mapa_de_python(info)?, mapa_de_python(guardado)?);
    mapa_a_python(py, &srv::estado(&i, &g, Path::new(raiz), registro))
}

#[pyfunction]
#[pyo3(signature = (dueno, entorno))]
fn instrucciones(dueno: Option<&str>, entorno: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(srv::instrucciones(dueno, &mapa_de_python(entorno)?))
}

#[pyfunction]
fn entorno_arranque<'py>(py: Python<'py>, base: &Bound<'py, PyAny>, guardado: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let (b, g) = (mapa_de_python(base)?, mapa_de_python(guardado)?);
    mapa_a_python(py, &srv::entorno_arranque(&b, &g))
}

#[pyfunction]
fn rotar_registro(ruta: &str) {
    srv::rotar_registro(ruta);
}

#[pyfunction]
#[pyo3(signature = (lineas, dueno, ruta))]
fn leer_registro<'py>(py: Python<'py>, lineas: i64, dueno: Option<&str>, ruta: &str) -> PyResult<Bound<'py, PyDict>> {
    let r = py.detach(|| srv::leer_registro(lineas, dueno, ruta));
    mapa_a_python(py, &r)
}

/// SIGTERM, hasta 10 s esperando y SIGKILL si sigue (sin el GIL)
#[pyfunction]
fn parar_ollama(py: Python<'_>, pid: i32) {
    py.detach(|| srv::parar_ollama(pid));
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("GESTIONADAS", srv::GESTIONADAS.to_vec())?;
    let validos = PyDict::new(py);
    for (k, v) in srv::VALORES_VALIDOS {
        validos.set_item(k, v.to_vec())?;
    }
    m.add("VALORES_VALIDOS", validos)?;
    m.add("DESCRIPCIONES", a_python(py, &Valor::Mapa(srv::descripciones()))?)?;
    m.add_function(wrap_pyfunction!(librerias_disponibles, m)?)?;
    m.add_function(wrap_pyfunction!(validar, m)?)?;
    m.add_function(wrap_pyfunction!(estado, m)?)?;
    m.add_function(wrap_pyfunction!(instrucciones, m)?)?;
    m.add_function(wrap_pyfunction!(entorno_arranque, m)?)?;
    m.add_function(wrap_pyfunction!(rotar_registro, m)?)?;
    m.add_function(wrap_pyfunction!(leer_registro, m)?)?;
    m.add_function(wrap_pyfunction!(parar_ollama, m)?)?;
    Ok(())
}
