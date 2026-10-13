//! Decisiones del gestor de recursos (prig_recursos::gestor) para `backend/recursos/gestor.py`

use crate::valor::{mapa_a_python, mapa_de_python};
use prig_recursos::gestor;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pyfunction]
fn medidas<'py>(py: Python<'py>, pruebas: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &gestor::medidas(&mapa_de_python(pruebas)?))
}

#[pyfunction]
fn estado_vivo<'py>(py: Python<'py>, rad: &Bound<'py, PyAny>, limite: f64, reanudar: f64) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &gestor::estado_vivo(&mapa_de_python(rad)?, limite, reanudar))
}

#[pyfunction]
#[pyo3(signature = (rec, prueba, ficha))]
fn completar_recomendacion<'py>(
    py: Python<'py>,
    rec: &Bound<'py, PyAny>,
    prueba: Option<&Bound<'py, PyAny>>,
    ficha: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyDict>> {
    let p = match prueba {
        Some(p) if p.is_truthy()? => Some(mapa_de_python(p)?),
        _ => None,
    };
    mapa_a_python(py, &gestor::completar_recomendacion(mapa_de_python(rec)?, p.as_ref(), &mapa_de_python(ficha)?))
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(medidas, m)?)?;
    m.add_function(wrap_pyfunction!(estado_vivo, m)?)?;
    m.add_function(wrap_pyfunction!(completar_recomendacion, m)?)?;
    Ok(())
}
