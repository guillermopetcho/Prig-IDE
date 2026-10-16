//! El almacén de desafíos (prig_aprendizaje::desafios): `prig_nativo.desafios`. Lee sin el GIL.

use crate::valor::mapa_a_python;
use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use pyo3::types::PyList;

/// `Almacen.lista()` de la carpeta `dir` (la de los JSON)
#[pyfunction]
fn lista<'py>(py: Python<'py>, dir: String) -> PyResult<Bound<'py, PyList>> {
    let filas = py.detach(|| prig_aprendizaje::desafios::lista(std::path::Path::new(&dir))).map_err(|e| PyOSError::new_err(e.to_string()))?;
    let salida = PyList::empty(py);
    for m in &filas {
        salida.append(mapa_a_python(py, m)?)?;
    }
    Ok(salida)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(lista, m)?)?;
    Ok(())
}
