//! Leer PDF con PDFium (prig_biblioteca::pdf): `prig_nativo.pdf`. Sin el GIL.

use prig_biblioteca::pdf as p;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

fn err(e: String) -> PyErr {
    PyRuntimeError::new_err(e)
}

#[pyfunction]
fn cargar(py: Python<'_>, ruta: String) -> PyResult<()> {
    py.detach(|| p::cargar(&ruta)).map_err(err)
}

#[pyfunction]
fn num_paginas(py: Python<'_>, ruta: String) -> PyResult<usize> {
    py.detach(|| p::num_paginas(&ruta)).map_err(err)
}

#[pyfunction]
fn paginas(py: Python<'_>, ruta: String) -> PyResult<Vec<(usize, String)>> {
    py.detach(|| p::paginas(&ruta)).map_err(err)
}

#[pyfunction]
fn pagina(py: Python<'_>, ruta: String, indice: usize) -> PyResult<String> {
    py.detach(|| p::pagina(&ruta, indice)).map_err(err)
}

#[pyfunction]
fn primeras(py: Python<'_>, ruta: String, n: usize) -> PyResult<Vec<String>> {
    py.detach(|| p::primeras(&ruta, n)).map_err(err)
}

#[pyfunction]
fn marcadores(py: Python<'_>, ruta: String) -> PyResult<Vec<(String, usize, Option<usize>)>> {
    py.detach(|| p::marcadores(&ruta)).map_err(err)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    for f in [
        wrap_pyfunction!(cargar, m)?,
        wrap_pyfunction!(num_paginas, m)?,
        wrap_pyfunction!(paginas, m)?,
        wrap_pyfunction!(pagina, m)?,
        wrap_pyfunction!(primeras, m)?,
        wrap_pyfunction!(marcadores, m)?,
        wrap_pyfunction!(sondeo, m)?,
        wrap_pyfunction!(buscar, m)?,
        wrap_pyfunction!(es_de_contrasena, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}

/// `[(página, «...trozo...»)]` de las primeras `n` páginas que contienen la consulta
#[pyfunction]
fn buscar(py: Python<'_>, ruta: String, consulta: String, n: usize) -> PyResult<Vec<(usize, String)>> {
    py.detach(|| p::buscar(&ruta, &consulta, n)).map_err(err)
}

/// `(total, [(índice, texto)], imágenes, [(título, nivel)], [(clave, valor)])` del sondeo de un libro
#[pyfunction]
#[allow(clippy::type_complexity)]
fn sondeo(py: Python<'_>, ruta: String, n_muestra: usize) -> PyResult<(usize, Vec<(usize, String)>, usize, Vec<(String, usize)>, Vec<(&'static str, String)>)> {
    let s = py.detach(|| p::sondeo(&ruta, n_muestra)).map_err(err)?;
    Ok((s.total, s.muestra, s.imagenes, s.marcadores, s.metadatos))
}

#[pyfunction]
fn es_de_contrasena(error: &str) -> bool {
    p::es_de_contrasena(error)
}
