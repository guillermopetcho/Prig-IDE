//! El fragmentador de la biblioteca (prig_biblioteca::troceado): `prig_nativo.troceado`. Trabaja sin el GIL y
//! entrega los fragmentos ya como los dicts de `SemanticChunker` (mismas claves, mismo orden).

use prig_biblioteca::troceado as tr;
use prig_plataforma::py::ahora_iso;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

/// Una sección ya ordenada: `(es_seccion, inicio, fin, section_id, chapter_id)`
type SeccionPy = (bool, i64, i64, Option<String>, Option<String>);

/// `chunk_document`: las páginas `(número, texto)` y las secciones ya ordenadas
/// `(es_seccion, inicio, fin, section_id, chapter_id)`
#[pyfunction]
fn fragmentar<'py>(
    py: Python<'py>,
    paginas: Vec<(i64, String)>,
    secciones: Vec<SeccionPy>,
    source_id: &str,
    max_tokens: i64,
) -> PyResult<Bound<'py, PyList>> {
    let secciones: Vec<tr::Seccion> = secciones
        .into_iter()
        .map(|(es_seccion, inicio, fin, section_id, chapter_id)| tr::Seccion { es_seccion, inicio, fin, section_id, chapter_id })
        .collect();
    let fragmentos = py.detach(|| tr::fragmentar(&paginas, &secciones, max_tokens));
    let ids: Vec<String> = fragmentos.iter().map(|f| format!("chk_{source_id}_{:04}", f.numero)).collect();
    let salida = PyList::empty(py);
    for (i, f) in fragmentos.into_iter().enumerate() {
        let d = PyDict::new(py);
        d.set_item("chunk_id", &ids[i])?;
        d.set_item("source_id", source_id)?;
        d.set_item("section_id", f.section_id)?;
        d.set_item("chapter_id", f.chapter_id)?;
        d.set_item("content", f.texto)?;
        d.set_item("content_type", f.clase.tipo)?;
        d.set_item("token_count", f.tokens)?;
        d.set_item("previous_chunk_id", if i > 0 { Some(&ids[i - 1]) } else { None })?;
        d.set_item("next_chunk_id", ids.get(i + 1))?;
        d.set_item("contains_equation", f.clase.ecuacion)?;
        d.set_item("contains_code", f.clase.codigo)?;
        d.set_item("topics", PyList::empty(py))?;
        d.set_item("concepts", PyList::empty(py))?;
        d.set_item("symbols", f.clase.simbolos)?;
        d.set_item("page_start", f.pagina_inicio)?;
        d.set_item("page_end", f.pagina_fin)?;
        d.set_item("created_at", ahora_iso())?;
        salida.append(d)?;
    }
    Ok(salida)
}

/// `StructureDetector.detect_structure`
#[pyfunction]
fn clasificar<'py>(py: Python<'py>, texto: &str) -> PyResult<Bound<'py, PyDict>> {
    let c = tr::clasificar(texto);
    let d = PyDict::new(py);
    d.set_item("content_type", c.tipo)?;
    d.set_item("contains_equation", c.ecuacion)?;
    d.set_item("contains_code", c.codigo)?;
    d.set_item("symbols", c.simbolos)?;
    Ok(d)
}

#[pyfunction]
fn parrafos(texto: &str) -> Vec<String> {
    tr::parrafos(texto)
}

#[pyfunction]
fn partir(texto: &str, tope: i64) -> Vec<String> {
    tr::partir(texto, tope)
}

#[pyfunction]
fn tokens_de(texto: &str) -> i64 {
    tr::tokens_de(texto)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(fragmentar, m)?)?;
    m.add_function(wrap_pyfunction!(clasificar, m)?)?;
    m.add_function(wrap_pyfunction!(parrafos, m)?)?;
    m.add_function(wrap_pyfunction!(partir, m)?)?;
    m.add_function(wrap_pyfunction!(tokens_de, m)?)?;
    Ok(())
}
