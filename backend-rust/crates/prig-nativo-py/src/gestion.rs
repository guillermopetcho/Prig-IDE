//! La gestión de modelos de Ollama (prig_modelos::gestion) para `ollama_gestion.py`: `prig_nativo.gestion`. Las
//! peticiones no retienen el GIL; los errores de red llegan como las excepciones de `requests`.

use crate::opciones::ErrorConfig;
use crate::plataforma::lanzar_con;
use crate::valor::{a_python, de_python, mapa_a_python, mapa_de_python};
use prig_modelos::gestion::{self as g, ErrorG, Gestor, Pasos};
use prig_modelos::red::ErrorRed;
use prig_recursos::valor::Valor;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Mutex;

pyo3::create_exception!(prig_nativo, ErrorGestion, pyo3::exceptions::PyException, "Un error de la gestión de modelos (el texto es para el usuario)");

/// La excepción de `requests` que corresponde (la que captura app.py)
fn de_requests(py: Python<'_>, clase: &str, texto: String) -> PyErr {
    match py.import("requests.exceptions").and_then(|m| m.getattr(clase)).and_then(|c| c.call1((texto.clone(),))) {
        Ok(e) => PyErr::from_value(e),
        Err(_) => pyo3::exceptions::PyOSError::new_err(texto),
    }
}

pub fn lanzar(py: Python<'_>, e: ErrorG) -> PyErr {
    match e {
        ErrorG::Gestion(t) => ErrorGestion::new_err(t),
        ErrorG::Py(e) => lanzar_con(py, e, ErrorConfig::new_err),
        ErrorG::Red(ErrorRed::Conexion(t)) => de_requests(py, "ConnectionError", t),
        ErrorG::Red(ErrorRed::Tiempo(t)) => de_requests(py, "ReadTimeout", t),
        ErrorG::Red(ErrorRed::Json(t, doc)) => crate::plataforma::json_decode_error(py, &t, &doc),
    }
}

fn gestor(base: String) -> Gestor {
    Gestor { base: base.trim_end_matches('/').to_string() }
}

fn lista<'py>(py: Python<'py>, r: Result<Vec<Valor>, ErrorG>) -> PyResult<Bound<'py, PyAny>> {
    a_python(py, &Valor::Lista(r.map_err(|e| lanzar(py, e))?))
}

#[pyfunction]
fn nombre(py: Python<'_>, n: &str) -> PyResult<String> {
    g::nombre(n).map_err(|e| lanzar(py, e))
}

#[pyfunction]
fn parametros<'py>(py: Python<'py>, texto: Option<&str>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &g::parametros(texto.unwrap_or("")))
}

#[pyfunction]
fn instalados(py: Python<'_>, base: String) -> PyResult<Bound<'_, PyAny>> {
    let r = py.detach(|| gestor(base).instalados());
    lista(py, r)
}

#[pyfunction]
fn ficha(py: Python<'_>, base: String, modelo: String) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| gestor(base).ficha(&modelo));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn copiar(py: Python<'_>, base: String, origen: String, destino: String) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| gestor(base).copiar(&origen, &destino));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn borrar(py: Python<'_>, base: String, modelo: String) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| gestor(base).borrar(&modelo));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn actualizaciones(py: Python<'_>, base: String, registro: String) -> PyResult<Bound<'_, PyAny>> {
    let r = py.detach(|| gestor(base).actualizaciones(registro.trim_end_matches('/')));
    lista(py, r)
}

#[pyfunction]
fn cargados(py: Python<'_>, base: String) -> PyResult<Bound<'_, PyAny>> {
    let r = py.detach(|| gestor(base).cargados());
    lista(py, r)
}

#[pyfunction]
#[pyo3(signature = (base, modelo, opciones, keep_alive = None))]
fn precargar<'py>(py: Python<'py>, base: String, modelo: String, opciones: &Bound<'py, PyAny>, keep_alive: Option<&Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyDict>> {
    let o = de_python(opciones)?;
    let k = match keep_alive {
        Some(k) if !k.is_none() => Some(de_python(k)?),
        _ => None,
    };
    let r = py.detach(|| gestor(base).precargar(&modelo, &o, k.as_ref()));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn descargar(py: Python<'_>, base: String, modelo: String) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| gestor(base).descargar(&modelo));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
#[pyo3(signature = (base, cuerpo, timeout = 900.0))]
fn probar<'py>(py: Python<'py>, base: String, cuerpo: &Bound<'py, PyAny>, timeout: f64) -> PyResult<Bound<'py, PyAny>> {
    let c = mapa_de_python(cuerpo)?;
    let r = py.detach(|| gestor(base).probar(&c, timeout));
    a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn uso_disco(py: Python<'_>, base: String) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| gestor(base).uso_disco());
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn carpeta_modelos() -> String {
    g::carpeta_modelos()
}

#[pyfunction]
#[pyo3(signature = (carpeta = None))]
fn parciales(py: Python<'_>, carpeta: Option<String>) -> PyResult<Bound<'_, PyDict>> {
    let m = py.detach(|| g::parciales(carpeta.as_deref()));
    mapa_a_python(py, &m)
}

#[pyfunction]
#[pyo3(signature = (carpeta = None))]
fn borrar_parciales(py: Python<'_>, carpeta: Option<String>) -> PyResult<Bound<'_, PyDict>> {
    let m = py.detach(|| g::borrar_parciales(carpeta.as_deref()));
    mapa_a_python(py, &m)
}

/// Los pasos de un flujo largo, como un generador de Python
#[pyclass(name = "Pasos")]
pub struct PasosPy {
    inner: Mutex<Pasos>,
}

#[pymethods]
impl PasosPy {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&self, py: Python<'_>) -> PyResult<Option<Py<PyAny>>> {
        let r = py.detach(|| self.inner.lock().unwrap().siguiente());
        match r.map_err(|e| lanzar(py, e))? {
            Some(v) => Ok(Some(a_python(py, &v)?.unbind())),
            None => Ok(None),
        }
    }

    /// `generator.close()`
    fn close(&self) {
        *self.inner.lock().unwrap() = Pasos::Fin;
    }
}

#[pyfunction]
#[pyo3(signature = (base, nombre, desde, system = String::new(), parametros = None, mensajes = None, licencia = String::new()))]
#[allow(clippy::too_many_arguments)]
fn crear_variante<'py>(
    base: String,
    nombre: String,
    desde: String,
    system: String,
    parametros: Option<&Bound<'py, PyAny>>,
    mensajes: Option<&Bound<'py, PyAny>>,
    licencia: String,
) -> PyResult<PasosPy> {
    let conv = |x: Option<&Bound<'py, PyAny>>| -> PyResult<Option<Valor>> {
        match x {
            Some(v) if !v.is_none() => Ok(Some(de_python(v)?)),
            _ => Ok(None),
        }
    };
    let pasos = gestor(base).crear_variante(nombre, desde, system, conv(parametros)?, conv(mensajes)?, licencia);
    Ok(PasosPy { inner: Mutex::new(pasos) })
}

#[pyfunction]
#[pyo3(signature = (base, ruta, nombre, cancelar = None))]
fn importar_gguf(base: String, ruta: String, nombre: String, cancelar: Option<Py<PyAny>>) -> PasosPy {
    let cancelar: Option<Box<dyn FnMut() -> bool + Send>> = cancelar.map(|c| {
        Box::new(move || Python::attach(|py| c.call0(py).and_then(|r| r.bind(py).is_truthy()).unwrap_or(false))) as Box<dyn FnMut() -> bool + Send>
    });
    PasosPy { inner: Mutex::new(gestor(base).importar_gguf(ruta, nombre, cancelar)) }
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("ErrorGestion", py.get_type::<ErrorGestion>())?;
    m.add("REGISTRO", g::REGISTRO)?;
    m.add_class::<PasosPy>()?;
    for f in [
        wrap_pyfunction!(nombre, m)?,
        wrap_pyfunction!(parametros, m)?,
        wrap_pyfunction!(instalados, m)?,
        wrap_pyfunction!(ficha, m)?,
        wrap_pyfunction!(copiar, m)?,
        wrap_pyfunction!(borrar, m)?,
        wrap_pyfunction!(actualizaciones, m)?,
        wrap_pyfunction!(cargados, m)?,
        wrap_pyfunction!(precargar, m)?,
        wrap_pyfunction!(descargar, m)?,
        wrap_pyfunction!(probar, m)?,
        wrap_pyfunction!(uso_disco, m)?,
        wrap_pyfunction!(carpeta_modelos, m)?,
        wrap_pyfunction!(parciales, m)?,
        wrap_pyfunction!(borrar_parciales, m)?,
        wrap_pyfunction!(crear_variante, m)?,
        wrap_pyfunction!(importar_gguf, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}
