//! Energía con root (prig_recursos::energia) para `backend/recursos/energia.py`. Las rutas del ayudante las da la
//! fachada en cada llamada (las pruebas las cambian).

use crate::valor::mapa_a_python;
use prig_recursos::energia::{self, ErrorEnergia, Rutas};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyInt};
use std::path::PathBuf;

fn rutas(ayudante: &str, politica: &str, fuente_ayudante: &str, fuente_politica: &str) -> Rutas {
    Rutas {
        ayudante: PathBuf::from(ayudante),
        politica: PathBuf::from(politica),
        fuente_ayudante: PathBuf::from(fuente_ayudante),
        fuente_politica: PathBuf::from(fuente_politica),
    }
}

/// ErrorEnergia → la clase de Python que da la fachada; el resto, OSError
fn error(clase: &Bound<'_, PyAny>, e: ErrorEnergia) -> PyErr {
    match e {
        ErrorEnergia::Energia(m) => match clase.call1((m,)) {
            Ok(exc) => PyErr::from_value(exc),
            Err(e) => e,
        },
        ErrorEnergia::Io(e) => e.into(),
    }
}

#[pyfunction]
fn instalacion<'py>(py: Python<'py>, rutas_: (String, String, String, String)) -> PyResult<Bound<'py, PyDict>> {
    let r = rutas(&rutas_.0, &rutas_.1, &rutas_.2, &rutas_.3);
    mapa_a_python(py, &energia::instalacion(&r))
}

#[pyfunction]
fn estado<'py>(py: Python<'py>, rutas_: (String, String, String, String)) -> PyResult<Bound<'py, PyDict>> {
    let r = rutas(&rutas_.0, &rutas_.1, &rutas_.2, &rutas_.3);
    mapa_a_python(py, &py.detach(|| energia::estado(&r)))
}

#[pyfunction]
fn instalar<'py>(py: Python<'py>, rutas_: (String, String, String, String), clase: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let r = rutas(&rutas_.0, &rutas_.1, &rutas_.2, &rutas_.3);
    let res = py.detach(|| energia::instalar(&r));
    mapa_a_python(py, &res.map_err(|e| error(clase, e))?)
}

/// `vatios` tiene que ser un entero de Python (un texto no vale)
#[pyfunction]
fn frio<'py>(
    py: Python<'py>,
    rutas_: (String, String, String, String),
    clase: &Bound<'py, PyAny>,
    vatios: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyDict>> {
    let r = rutas(&rutas_.0, &rutas_.1, &rutas_.2, &rutas_.3);
    let v = if vatios.is_instance_of::<PyInt>() { vatios.extract::<i64>().ok() } else { None };
    let res = py.detach(|| energia::frio(&r, v));
    mapa_a_python(py, &res.map_err(|e| error(clase, e))?)
}

#[pyfunction]
fn normal<'py>(py: Python<'py>, rutas_: (String, String, String, String), clase: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let r = rutas(&rutas_.0, &rutas_.1, &rutas_.2, &rutas_.3);
    let res = py.detach(|| energia::normal(&r));
    mapa_a_python(py, &res.map_err(|e| error(clase, e))?)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("VATIOS_POR_DEFECTO", energia::VATIOS_POR_DEFECTO)?;
    m.add_function(wrap_pyfunction!(instalacion, m)?)?;
    m.add_function(wrap_pyfunction!(estado, m)?)?;
    m.add_function(wrap_pyfunction!(instalar, m)?)?;
    m.add_function(wrap_pyfunction!(frio, m)?)?;
    m.add_function(wrap_pyfunction!(normal, m)?)?;
    Ok(())
}
