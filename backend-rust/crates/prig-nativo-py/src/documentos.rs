//! Documentos PDF con Typst (prig_documentos): `prig_nativo.documentos`. Compila sin el GIL.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// El documento (JSON de bloques, ver prig_documentos::bloques) a PDF: `(bytes, páginas)`
#[pyfunction]
fn pdf<'py>(py: Python<'py>, documento: String) -> PyResult<(Bound<'py, PyBytes>, usize)> {
    let (bytes, paginas) = py.detach(|| prig_documentos::pdf_de_json(&documento)).map_err(PyValueError::new_err)?;
    Ok((PyBytes::new(py, &bytes), paginas))
}

/// Texto que va dentro de Markdown sin que se interprete
#[pyfunction]
fn escapar_md(texto: &str) -> String {
    prig_documentos::marcado::escapar_md(texto)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(pdf, m)?)?;
    m.add_function(wrap_pyfunction!(escapar_md, m)?)?;
    Ok(())
}
