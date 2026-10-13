//! Cabecera GGUF (prig_recursos::gguf) para `backend/recursos/gguf.py`

use crate::valor::mapa_a_python;
use prig_recursos::gguf::{self, ErrorGguf, ErrorRangos};
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

pyo3::create_exception!(gguf, FaltanBytes, PyException, "El búfer se acabó antes que la cabecera: hay que pedir más");

fn error(e: ErrorGguf) -> PyErr {
    match e {
        ErrorGguf::FaltanBytes => FaltanBytes::new_err(()),
        ErrorGguf::Invalido(m) => PyValueError::new_err(m),
    }
}

/// Metadatos de una cabecera GGUF completa. Lanza FaltanBytes si no llega.
#[pyfunction]
fn leer_metadatos<'py>(py: Python<'py>, datos: &[u8]) -> PyResult<Bound<'py, PyDict>> {
    let meta = gguf::leer_metadatos(datos).map_err(error)?;
    mapa_a_python(py, &meta)
}

/// Lee la cabecera pidiendo bytes por rangos, cada vez más, hasta que llega. `pedir(desde, hasta)` devuelve los bytes
/// de ese rango; si lanza una excepción, sale tal cual.
#[pyfunction]
#[pyo3(signature = (pedir, inicial = 256 * 1024, maximo = 48 * 1024 * 1024))]
fn leer_con_rangos<'py>(
    py: Python<'py>,
    pedir: &Bound<'py, PyAny>,
    inicial: usize,
    maximo: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let r = gguf::leer_con_rangos(
        |desde, hasta| -> PyResult<Vec<u8>> {
            let trozo = pedir.call1((desde, hasta))?;
            Ok(trozo.cast::<PyBytes>()?.as_bytes().to_vec())
        },
        inicial,
        maximo,
    );
    match r {
        Ok(meta) => mapa_a_python(py, &meta),
        Err(ErrorRangos::Pedir(e)) => Err(e),
        Err(ErrorRangos::Gguf(e)) => Err(error(e)),
    }
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("FaltanBytes", m.py().get_type::<FaltanBytes>())?;
    m.add("NO_GUARDAR", gguf::NO_GUARDAR.to_vec())?;
    m.add_function(wrap_pyfunction!(leer_metadatos, m)?)?;
    m.add_function(wrap_pyfunction!(leer_con_rangos, m)?)?;
    Ok(())
}
