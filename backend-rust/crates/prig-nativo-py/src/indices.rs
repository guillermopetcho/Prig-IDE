//! Los índices de la biblioteca (prig_biblioteca::indices): `prig_nativo.indices`. Construir y buscar sin el GIL.

use prig_biblioteca::indices as ix;
use pyo3::prelude::*;

#[pyclass(name = "Bm25", frozen)]
pub struct Bm25Py {
    inner: ix::Bm25,
}

#[pymethods]
impl Bm25Py {
    #[new]
    #[pyo3(signature = (textos, k1 = 1.5, b = 0.75))]
    fn new(py: Python<'_>, textos: Vec<String>, k1: f64, b: f64) -> Self {
        Bm25Py { inner: py.detach(|| ix::Bm25::new(&textos, k1, b)) }
    }

    fn buscar(&self, py: Python<'_>, consulta: String, top_k: usize) -> Vec<(usize, f64)> {
        py.detach(|| self.inner.buscar(&consulta, top_k))
    }

    fn __len__(&self) -> usize {
        self.inner.documentos()
    }
}

#[pyclass(name = "Vectorial", frozen)]
pub struct VectorialPy {
    inner: ix::Vectorial,
}

#[pymethods]
impl VectorialPy {
    #[new]
    fn new(py: Python<'_>, textos: Vec<String>) -> Self {
        VectorialPy { inner: py.detach(|| ix::Vectorial::new(&textos)) }
    }

    fn buscar(&self, py: Python<'_>, consulta: String, top_k: usize) -> Vec<(usize, f64)> {
        py.detach(|| self.inner.buscar(&consulta, top_k))
    }

    fn __len__(&self) -> usize {
        self.inner.documentos()
    }
}

#[pyfunction]
fn tokenizar(texto: &str) -> Vec<String> {
    ix::tokenizar(texto)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Bm25Py>()?;
    m.add_class::<VectorialPy>()?;
    m.add_function(wrap_pyfunction!(tokenizar, m)?)?;
    Ok(())
}
