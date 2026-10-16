//! El buscador de modelos (prig_modelos::buscador) para `buscador_modelos.py`: `prig_nativo.buscador`. Las
//! peticiones no retienen el GIL; los errores de red llegan como las excepciones de `requests`.

use crate::plataforma::lanzar_con;
use crate::valor::{a_python, de_python, mapa_a_python};
use prig_modelos::buscador::{self as b, Bases, Cache, ErrorB};
use prig_modelos::red::ErrorRed;
use prig_recursos::valor::Valor;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pyo3::create_exception!(prig_nativo, ErrorBuscador, pyo3::exceptions::PyException, "Un error del buscador de modelos (el texto es para el usuario)");

fn de_requests(py: Python<'_>, clase: &str, texto: String) -> PyErr {
    match py.import("requests.exceptions").and_then(|m| m.getattr(clase)).and_then(|c| c.call1((texto.clone(),))) {
        Ok(e) => PyErr::from_value(e),
        Err(_) => pyo3::exceptions::PyOSError::new_err(texto),
    }
}

fn lanzar(py: Python<'_>, e: ErrorB) -> PyErr {
    match e {
        ErrorB::Buscador(t) => ErrorBuscador::new_err(t),
        ErrorB::Py(e) => lanzar_con(py, e, ErrorBuscador::new_err),
        ErrorB::Red(ErrorRed::Conexion(t)) => de_requests(py, "ConnectionError", t),
        ErrorB::Red(ErrorRed::Tiempo(t)) => de_requests(py, "ReadTimeout", t),
        ErrorB::Red(ErrorRed::Json(t, doc)) => crate::plataforma::json_decode_error(py, &t, &doc),
    }
}

fn devolver<'py>(py: Python<'py>, r: Result<Valor, ErrorB>) -> PyResult<Bound<'py, PyAny>> {
    a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

/// `Cache()`: lo pedido hace poco (cada proceso tiene la suya; las pruebas usan una nueva)
#[pyclass(name = "Cache", frozen)]
#[derive(Default)]
pub struct CachePy {
    inner: Cache,
}

#[pymethods]
impl CachePy {
    #[new]
    fn new() -> Self {
        CachePy::default()
    }

    fn obtener<'py>(&self, py: Python<'py>, clave: &str, ttl: f64) -> PyResult<Option<Bound<'py, PyAny>>> {
        self.inner.obtener(clave, ttl).map(|v| a_python(py, &v)).transpose()
    }

    fn guardar<'py>(&self, py: Python<'py>, clave: &str, valor: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let v = self.inner.guardar(clave, de_python(valor)?);
        a_python(py, &v)
    }
}

#[pyfunction]
fn texto(fragmento: &str) -> String {
    b::texto(fragmento)
}

#[pyfunction]
fn numero(py: Python<'_>, t: Option<&str>) -> PyResult<Option<i128>> {
    b::numero(t.unwrap_or("")).map_err(|e| lanzar(py, ErrorB::Py(e)))
}

#[pyfunction]
fn bytes_(py: Python<'_>, t: Option<&str>) -> PyResult<Option<i128>> {
    b::bytes(t.unwrap_or("")).map_err(|e| lanzar(py, ErrorB::Py(e)))
}

#[pyfunction]
fn cuantizacion_de(archivo: &str) -> Option<String> {
    b::cuantizacion_de(archivo)
}

#[pyfunction]
fn validar_ref(py: Python<'_>, r: Option<&str>) -> PyResult<String> {
    b::validar_ref(r.unwrap_or("")).map_err(|e| lanzar(py, e))
}

#[pyfunction]
fn motivo_registro(codigo: u16, cuerpo: Option<&str>, tag: &str) -> String {
    b::motivo_registro(codigo, cuerpo.unwrap_or(""), tag)
}

#[pyfunction]
fn fuente_de_ref(r: &str) -> &'static str {
    b::fuente_de_ref(r)
}

#[pyfunction]
#[pyo3(signature = (r, registro, cache, timeout = 30.0))]
fn comprobar<'py>(py: Python<'py>, r: String, registro: (String, String, String), cache: &CachePy, timeout: f64) -> PyResult<Bound<'py, PyAny>> {
    let res = py.detach(|| b::comprobar(&r, (&registro.0, &registro.1, &registro.2), &cache.inner, timeout));
    devolver(py, res)
}

#[pyfunction]
#[pyo3(signature = (base, consulta, orden, capacidad, pagina, cache))]
fn ollama_buscar<'py>(py: Python<'py>, base: String, consulta: String, orden: String, capacidad: Option<String>, pagina: i64, cache: &CachePy) -> PyResult<Bound<'py, PyAny>> {
    let res = py.detach(|| b::ollama_buscar(&base, &consulta, &orden, capacidad.as_deref(), pagina, &cache.inner));
    devolver(py, res)
}

#[pyfunction]
fn analizar_busqueda<'py>(py: Python<'py>, pagina: &str) -> PyResult<Bound<'py, PyAny>> {
    devolver(py, b::analizar_busqueda(pagina).map(Valor::Lista))
}

#[pyfunction]
fn ollama_variantes<'py>(py: Python<'py>, base: String, nombre: String, cache: &CachePy) -> PyResult<Bound<'py, PyAny>> {
    let res = py.detach(|| b::ollama_variantes(&base, &nombre, &cache.inner));
    devolver(py, res)
}

#[pyfunction]
fn analizar_etiquetas<'py>(py: Python<'py>, pagina: &str, ruta: &str) -> PyResult<Bound<'py, PyAny>> {
    devolver(py, b::analizar_etiquetas(pagina, ruta).map(Valor::Lista))
}

#[pyfunction]
#[pyo3(signature = (base, consulta, orden, pagina, limite, cache))]
fn hf_buscar<'py>(py: Python<'py>, base: String, consulta: String, orden: String, pagina: Option<String>, limite: i64, cache: &CachePy) -> PyResult<Bound<'py, PyAny>> {
    let res = py.detach(|| b::hf_buscar(&base, &consulta, &orden, pagina.as_deref(), limite, &cache.inner));
    devolver(py, res)
}

#[pyfunction]
fn hf_normalizar<'py>(py: Python<'py>, m: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let v = de_python(m)?;
    devolver(py, b::hf_normalizar(&v).map(Valor::Mapa))
}

#[pyfunction]
fn hf_variantes<'py>(py: Python<'py>, base: String, repo: String, cache: &CachePy) -> PyResult<Bound<'py, PyAny>> {
    let res = py.detach(|| b::hf_variantes(&base, &repo, &cache.inner));
    devolver(py, res)
}

#[pyfunction]
fn ms_buscar<'py>(py: Python<'py>, base: String, consulta: String, orden: String, pagina: i64, limite: i64, cache: &CachePy) -> PyResult<Bound<'py, PyAny>> {
    let res = py.detach(|| b::ms_buscar(&base, &consulta, &orden, pagina, limite, &cache.inner));
    devolver(py, res)
}

#[pyfunction]
fn ms_normalizar<'py>(py: Python<'py>, m: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let v = de_python(m)?;
    devolver(py, b::ms_normalizar(&v).map(Valor::Mapa))
}

#[pyfunction]
fn ms_variantes<'py>(py: Python<'py>, base: String, repo: String, cache: &CachePy) -> PyResult<Bound<'py, PyAny>> {
    let res = py.detach(|| b::ms_variantes(&base, &repo, &cache.inner));
    devolver(py, res)
}

#[pyfunction]
fn agrupar_gguf<'py>(py: Python<'py>, archivos: Vec<(String, Bound<'py, PyAny>)>, prefijo: &str) -> PyResult<Bound<'py, PyAny>> {
    let a: Vec<(String, Valor)> = archivos.iter().map(|(r, t)| Ok((r.clone(), de_python(t)?))).collect::<PyResult<_>>()?;
    a_python(py, &Valor::Lista(b::agrupar_gguf(&a, prefijo).into_iter().map(Valor::Mapa).collect()))
}

#[pyfunction]
fn interpretar<'py>(py: Python<'py>, texto: Option<&str>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &b::interpretar(texto.unwrap_or("")).map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn interpretar_nombre<'py>(py: Python<'py>, texto: &str) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &b::interpretar_nombre(texto).map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn clave(nombre: Option<&str>) -> String {
    b::clave(nombre.unwrap_or(""))
}

#[pyfunction]
fn parecido(consulta: &str, id_modelo: &str) -> bool {
    b::parecido(consulta, id_modelo)
}

#[pyfunction]
fn clave_ollama(consulta: &str) -> Option<String> {
    b::clave_ollama(consulta)
}

#[pyfunction]
fn ficha_repo<'py>(py: Python<'py>, fuente: String, id_modelo: Option<String>, bases: (String, String, String), cache: &CachePy) -> PyResult<Option<Bound<'py, PyDict>>> {
    let id = id_modelo.unwrap_or_default();
    let res = py.detach(|| {
        let bases = Bases { ollama: &bases.0, huggingface: &bases.1, modelscope: &bases.2 };
        b::ficha_repo(&fuente, &id, &bases, &cache.inner)
    });
    res.map_err(|e| lanzar(py, e))?.map(|m| mapa_a_python(py, &m)).transpose()
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("ErrorBuscador", py.get_type::<ErrorBuscador>())?;
    m.add("UA", b::UA)?;
    m.add("UA_OLLAMA", b::UA_OLLAMA)?;
    m.add("ACEPTA_MANIFIESTO", b::ACEPTA_MANIFIESTO)?;
    m.add("CAPACIDADES_OLLAMA", b::CAPACIDADES_OLLAMA.to_vec())?;
    m.add("EXPANDIR", b::EXPANDIR.to_vec())?;
    m.add_class::<CachePy>()?;
    for f in [
        wrap_pyfunction!(texto, m)?,
        wrap_pyfunction!(numero, m)?,
        wrap_pyfunction!(bytes_, m)?,
        wrap_pyfunction!(cuantizacion_de, m)?,
        wrap_pyfunction!(validar_ref, m)?,
        wrap_pyfunction!(motivo_registro, m)?,
        wrap_pyfunction!(fuente_de_ref, m)?,
        wrap_pyfunction!(comprobar, m)?,
        wrap_pyfunction!(ollama_buscar, m)?,
        wrap_pyfunction!(analizar_busqueda, m)?,
        wrap_pyfunction!(ollama_variantes, m)?,
        wrap_pyfunction!(analizar_etiquetas, m)?,
        wrap_pyfunction!(hf_buscar, m)?,
        wrap_pyfunction!(hf_normalizar, m)?,
        wrap_pyfunction!(hf_variantes, m)?,
        wrap_pyfunction!(ms_buscar, m)?,
        wrap_pyfunction!(ms_normalizar, m)?,
        wrap_pyfunction!(ms_variantes, m)?,
        wrap_pyfunction!(agrupar_gguf, m)?,
        wrap_pyfunction!(interpretar, m)?,
        wrap_pyfunction!(interpretar_nombre, m)?,
        wrap_pyfunction!(clave, m)?,
        wrap_pyfunction!(parecido, m)?,
        wrap_pyfunction!(clave_ollama, m)?,
        wrap_pyfunction!(ficha_repo, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}
