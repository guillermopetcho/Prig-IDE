//! El índice semántico de conceptos (prig_biblioteca::vectores): `prig_nativo.vectores`. Puntúa sin el GIL.

use prig_biblioteca::vectores as vs;
use pyo3::prelude::*;

#[pyclass(name = "Vectores", frozen)]
pub struct VectoresPy {
    inner: vs::Vectores,
}

#[pymethods]
impl VectoresPy {
    /// Las filas `(concept_id, blob)` de la tabla `vectores`
    #[new]
    fn new(py: Python<'_>, filas: Vec<(String, Vec<u8>)>) -> Self {
        VectoresPy { inner: py.detach(|| vs::Vectores::new(filas.into_iter().map(|(id, b)| (id, vs::desempaquetar(&b))).collect())) }
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    fn __contains__(&self, id: &str) -> bool {
        self.inner.contiene(id)
    }

    /// `[(parecido, concept_id)]` de más a menos; vacío si no hay candidatos o la pregunta tiene otra dimensión
    /// (`puntuar` de Python). Sin `ids` (o vacío), todos
    #[pyo3(signature = (q, ids = None))]
    fn puntuar(&self, py: Python<'_>, q: Vec<f64>, ids: Option<Vec<String>>) -> Vec<(f64, String)> {
        py.detach(|| {
            let candidatos = self.inner.candidatos(ids.as_deref());
            match candidatos.first() {
                Some(&i) if self.inner.dimension_de(i) == q.len() => self.inner.puntuar(&q, &candidatos),
                _ => Vec::new(),
            }
        })
    }
}

#[pyfunction]
fn coseno(a: Vec<f64>, b: Vec<f64>) -> f64 {
    vs::coseno(&a, &b)
}

#[pyfunction]
fn desempaquetar(b: Vec<u8>) -> Vec<f64> {
    vs::desempaquetar(&b)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<VectoresPy>()?;
    m.add_function(wrap_pyfunction!(coseno, m)?)?;
    m.add_function(wrap_pyfunction!(desempaquetar, m)?)?;
    Ok(())
}
