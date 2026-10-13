//! Perfiles de uso (prig_recursos::perfiles) para `backend/recursos/perfiles.py`

use crate::valor::mapa_a_python;
use prig_recursos::perfiles;
use pyo3::exceptions::PyKeyError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pyfunction]
fn perfiles_<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &perfiles::perfiles())
}

#[pyfunction]
fn tiradores<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &perfiles::tiradores())
}

/// {"id": nombre, **PERFILES[nombre]}; KeyError si no existe
#[pyfunction]
fn perfil<'py>(py: Python<'py>, nombre: &str) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &perfiles::perfil_mapa(nombre).map_err(PyKeyError::new_err)?)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("perfiles", wrap_pyfunction!(perfiles_, m)?)?;
    m.add_function(wrap_pyfunction!(tiradores, m)?)?;
    m.add_function(wrap_pyfunction!(perfil, m)?)?;
    Ok(())
}
