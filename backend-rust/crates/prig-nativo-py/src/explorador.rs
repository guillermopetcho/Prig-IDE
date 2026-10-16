//! El explorador de libros (prig_plataforma::explorador) para `explorador.py`: `prig_nativo.explorador`. La
//! carpeta personal y el espacio de trabajo llegan en cada llamada (son atributos del objeto de Python).

use crate::plataforma::lanzar;
use crate::valor::{a_python, mapa_a_python};
use prig_plataforma::explorador::{self as x, Ambito};
use prig_plataforma::valor::Valor;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pyfunction]
#[pyo3(signature = (raiz, workspace, ruta))]
fn permitida(py: Python<'_>, raiz: String, workspace: Option<String>, ruta: String) -> bool {
    py.detach(|| Ambito { raiz: &raiz, workspace: workspace.as_deref() }.permitida(&ruta))
}

#[pyfunction]
#[pyo3(signature = (raiz, workspace))]
fn atajos(py: Python<'_>, raiz: String, workspace: Option<String>) -> PyResult<Bound<'_, PyAny>> {
    let v = py.detach(|| Ambito { raiz: &raiz, workspace: workspace.as_deref() }.atajos());
    a_python(py, &Valor::Lista(v))
}

#[pyfunction]
#[pyo3(signature = (raiz, workspace, ruta = None, recursivo = false))]
fn listar(py: Python<'_>, raiz: String, workspace: Option<String>, ruta: Option<String>, recursivo: bool) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| Ambito { raiz: &raiz, workspace: workspace.as_deref() }.listar(ruta.as_deref(), recursivo));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
#[pyo3(signature = (raiz, workspace, texto, desde = None, tope = 120))]
fn buscar(py: Python<'_>, raiz: String, workspace: Option<String>, texto: String, desde: Option<String>, tope: usize) -> PyResult<Bound<'_, PyAny>> {
    let r = py.detach(|| Ambito { raiz: &raiz, workspace: workspace.as_deref() }.buscar(&texto, desde.as_deref(), tope));
    a_python(py, &Valor::Lista(r.map_err(|e| lanzar(py, e))?))
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    let ext = PyDict::new(py);
    for (k, v) in x::EXTENSIONES {
        ext.set_item(k, v)?;
    }
    m.add("EXTENSIONES", ext)?;
    m.add("IGNORADAS", x::IGNORADAS.to_vec())?;
    m.add("ATAJOS", x::ATAJOS.to_vec())?;
    m.add_function(wrap_pyfunction!(permitida, m)?)?;
    m.add_function(wrap_pyfunction!(atajos, m)?)?;
    m.add_function(wrap_pyfunction!(listar, m)?)?;
    m.add_function(wrap_pyfunction!(buscar, m)?)?;
    Ok(())
}
