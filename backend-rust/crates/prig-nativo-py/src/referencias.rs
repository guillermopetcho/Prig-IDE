//! Las referencias que vienen al caso de una pregunta (prig_biblioteca::referencias): `prig_nativo.referencias`.

use prig_biblioteca::referencias as rf;
use pyo3::prelude::*;
use std::collections::HashSet;

type RefPy = (bool, Vec<String>, Vec<String>, String, Option<String>);

#[pyclass(name = "Catalogo", frozen)]
pub struct CatalogoPy {
    inner: rf::Catalogo,
}

#[pymethods]
impl CatalogoPy {
    /// `categorias`: `[(id, claves)]`; `refs`: `[(caída, categorías, temas, título, tipo)]`; `genericos`: los temas
    /// que solos no hacen relevante una referencia
    #[new]
    fn new(py: Python<'_>, categorias: Vec<(String, Vec<String>)>, refs: Vec<RefPy>, genericos: HashSet<String>) -> Self {
        let categorias = categorias.into_iter().map(|(id, claves)| rf::Categoria { id, claves }).collect();
        let refs = refs
            .into_iter()
            .map(|(caida, categorias, temas, titulo, tipo)| rf::Referencia { caida, categorias, temas, titulo, tipo })
            .collect();
        CatalogoPy { inner: py.detach(|| rf::Catalogo::new(categorias, refs, &genericos)) }
    }

    /// Las posiciones de las referencias elegidas, en orden
    fn relacionadas(&self, py: Python<'_>, texto: String, maximo: usize) -> Vec<usize> {
        py.detach(|| self.inner.relacionadas(&texto, maximo))
    }
}

#[pyfunction]
fn normalizar(texto: &str) -> String {
    rf::normalizar(texto)
}

#[pyfunction]
fn aparece(clave: &str, texto: &str) -> bool {
    rf::aparece(clave, texto)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CatalogoPy>()?;
    m.add_function(wrap_pyfunction!(normalizar, m)?)?;
    m.add_function(wrap_pyfunction!(aparece, m)?)?;
    Ok(())
}
