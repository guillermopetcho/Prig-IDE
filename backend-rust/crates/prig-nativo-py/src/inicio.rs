//! La pantalla de inicio (prig_plataforma::inicio) para `inicio.py`: `prig_nativo.inicio`

use crate::plataforma::lanzar;
use crate::valor::{a_python, de_python, mapa_a_python, mapa_de_python};
use prig_plataforma::inicio as i;
use prig_plataforma::valor::Valor;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pyfunction]
fn por_defecto(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    mapa_a_python(py, &i::por_defecto())
}

#[pyfunction]
fn ruta_perfil() -> String {
    i::ruta_perfil()
}

#[pyfunction]
fn perfil(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(i::perfil);
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn guardar_perfil<'py>(py: Python<'py>, cambios: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let c = mapa_de_python(cambios)?;
    let r = py.detach(|| i::guardar_perfil(&c));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
#[pyo3(signature = (historial, lecturas, colecciones, descargas, ejercicios, n = 14))]
fn actividad<'py>(
    py: Python<'py>,
    historial: &Bound<'py, PyAny>,
    lecturas: &Bound<'py, PyAny>,
    colecciones: &Bound<'py, PyAny>,
    descargas: &Bound<'py, PyAny>,
    ejercicios: &Bound<'py, PyAny>,
    n: usize,
) -> PyResult<Bound<'py, PyAny>> {
    let (h, l, c, d, e) = (de_python(historial)?, de_python(lecturas)?, de_python(colecciones)?, de_python(descargas)?, de_python(ejercicios)?);
    let r = i::actividad(&h, &l, &c, &d, &e, n).map_err(|e| lanzar(py, e))?;
    a_python(py, &Valor::Lista(r))
}

#[pyfunction]
#[pyo3(signature = (actividad_por_dia, dias = 7))]
fn semana<'py>(py: Python<'py>, actividad_por_dia: &Bound<'py, PyAny>, dias: i64) -> PyResult<Bound<'py, PyAny>> {
    let r = i::semana(&de_python(actividad_por_dia)?, dias).map_err(|e| lanzar(py, e))?;
    a_python(py, &Valor::Lista(r))
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("NIVELES", i::NIVELES.to_vec())?;
    m.add_function(wrap_pyfunction!(por_defecto, m)?)?;
    m.add_function(wrap_pyfunction!(ruta_perfil, m)?)?;
    m.add_function(wrap_pyfunction!(perfil, m)?)?;
    m.add_function(wrap_pyfunction!(guardar_perfil, m)?)?;
    m.add_function(wrap_pyfunction!(actividad, m)?)?;
    m.add_function(wrap_pyfunction!(semana, m)?)?;
    Ok(())
}
