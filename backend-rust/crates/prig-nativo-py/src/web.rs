//! La búsqueda web (prig_ia::web) para `ai_engine/web_search_engine.py`: `prig_nativo.web`. Descargar y leer las
//! páginas, en paralelo y sin el GIL.

use crate::plataforma::imprimir;
use crate::valor::{a_python, de_python, mapa_de_python};
use prig_ia::web as w;
use prig_recursos::valor::Valor;
use pyo3::prelude::*;

#[pyfunction]
fn pide_internet(prompt: Option<&str>) -> bool {
    w::pide_internet(prompt.unwrap_or(""))
}

#[pyfunction]
fn reordenar<'py>(py: Python<'py>, consulta: &str, items: Vec<Bound<'py, PyAny>>, maximo: usize) -> PyResult<Bound<'py, PyAny>> {
    let l = items.iter().map(mapa_de_python).collect::<PyResult<Vec<_>>>()?;
    a_python(py, &Valor::Lista(w::reordenar(consulta, &l, maximo).into_iter().map(Valor::Mapa).collect()))
}

#[pyfunction]
fn texto_de_pagina(py: Python<'_>, html: String, max_caracteres: usize) -> String {
    py.detach(|| w::texto_de_pagina(&html, max_caracteres))
}

#[pyfunction]
fn leer_pagina(py: Python<'_>, url: String, segundos: f64, max_caracteres: usize) -> String {
    py.detach(|| w::leer_pagina(&url, segundos, max_caracteres))
}

#[pyfunction]
fn contexto<'py>(py: Python<'py>, resultados: Vec<Bound<'py, PyAny>>, segundos: f64, max_caracteres: usize) -> PyResult<(String, Bound<'py, PyAny>)> {
    let l = resultados.iter().map(mapa_de_python).collect::<PyResult<Vec<_>>>()?;
    let (t, f) = py.detach(|| w::contexto(&l, segundos, max_caracteres));
    Ok((t, a_python(py, &Valor::Lista(f))?))
}

#[pyfunction]
fn cache_leer<'py>(py: Python<'py>, dir: String, consulta: String, ttl: f64) -> PyResult<Option<(Bound<'py, PyAny>, Bound<'py, PyAny>)>> {
    let mut avisos = Vec::new();
    let r = py.detach(|| w::cache_leer(&dir, &consulta, ttl, &mut avisos));
    imprimir(py, avisos)?;
    match r {
        Some((c, f)) => Ok(Some((a_python(py, &c)?, a_python(py, &f)?))),
        None => Ok(None),
    }
}

#[pyfunction]
fn cache_guardar(py: Python<'_>, dir: String, consulta: String, contexto: String, fuentes: &Bound<'_, PyAny>) -> PyResult<()> {
    let f = de_python(fuentes)?;
    let mut avisos = Vec::new();
    py.detach(|| w::cache_guardar(&dir, &consulta, &contexto, &f, &mut avisos));
    imprimir(py, avisos)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("AGENTE", w::AGENTE)?;
    m.add("DOMINIOS_OFICIALES", w::DOMINIOS_OFICIALES.to_vec())?;
    for f in [
        wrap_pyfunction!(pide_internet, m)?,
        wrap_pyfunction!(reordenar, m)?,
        wrap_pyfunction!(texto_de_pagina, m)?,
        wrap_pyfunction!(leer_pagina, m)?,
        wrap_pyfunction!(contexto, m)?,
        wrap_pyfunction!(cache_leer, m)?,
        wrap_pyfunction!(cache_guardar, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}
