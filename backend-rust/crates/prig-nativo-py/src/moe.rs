//! Las piezas del motor MoE (prig_ia::moe) para `ai_engine/motor_moe.py`: `prig_nativo.moe`. El flujo de una
//! respuesta se lee y se traduce en Rust, sin el GIL; Python recibe las líneas NDJSON (o los objetos) ya hechos.

use crate::plataforma::lanzar;
use crate::valor::{a_python, de_python, mapa_a_python, mapa_de_python};
use prig_ia::moe as m;
use prig_recursos::json;
use prig_recursos::valor::{Mapa, Valor};
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

#[pyfunction]
fn estimar_tokens(py: Python<'_>, pedido: &Bound<'_, PyAny>) -> PyResult<i128> {
    m::estimar_tokens(&de_python(pedido)?).map_err(|e| lanzar(py, e))
}

#[pyfunction]
fn prefijo_de<'py>(py: Python<'py>, cuerpo: &Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyAny>>> {
    match m::prefijo_de(&de_python(cuerpo)?).map_err(|e| lanzar(py, e))? {
        Some(l) => Ok(Some(a_python(py, &Valor::Lista(l))?)),
        None => Ok(None),
    }
}

#[pyfunction]
fn lista_caliente(uso: Vec<Vec<i64>>, global: Vec<Vec<i64>>) -> Option<Vec<Vec<i64>>> {
    m::lista_caliente(&uso, &global)
}

#[pyfunction]
fn contexto_para(tokens: i128) -> Option<i64> {
    m::contexto_para(tokens)
}

#[pyfunction]
fn lote_para(contexto: i64) -> i64 {
    m::lote_para(contexto)
}

#[pyfunction]
#[pyo3(signature = (contexto, mtp = false))]
fn base_mb(contexto: i64, mtp: bool) -> Option<f64> {
    m::base_mb(contexto, mtp)
}

#[pyfunction]
fn cabe_mtp(vram_libre_mb: Option<f64>, contexto: i64) -> bool {
    m::cabe_mtp(vram_libre_mb, contexto)
}

#[pyfunction]
#[pyo3(signature = (vram_libre_mb, contexto, mtp = false, mb_caliente = m::MB_POR_CALIENTE, extra_mb = 0.0))]
fn calientes_para(vram_libre_mb: Option<f64>, contexto: i64, mtp: bool, mb_caliente: f64, extra_mb: f64) -> i64 {
    m::calientes_para(vram_libre_mb, contexto, mtp, mb_caliente, extra_mb)
}

#[pyfunction]
#[pyo3(signature = (valor, defecto = 300.0))]
fn segundos_keep_alive(valor: &Bound<'_, PyAny>, defecto: f64) -> PyResult<f64> {
    Ok(m::segundos_keep_alive(&de_python(valor)?, defecto))
}

#[pyfunction]
fn tamanos_gguf(py: Python<'_>, gguf: Option<String>) -> (i64, i64) {
    py.detach(|| m::tamanos_gguf(gguf.as_deref().unwrap_or("")))
}

#[pyfunction]
fn muestreo_para<'py>(py: Python<'py>, pedido: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &m::muestreo_para(&de_python(pedido)?).map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn mensajes_openai<'py>(py: Python<'py>, mensajes: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let l = match de_python(mensajes)? {
        Valor::Lista(l) => l,
        otro => prig_plataforma::py::iterar(&otro).map_err(|e| lanzar(py, prig_plataforma::py::ErrorPy::Tipo(e)))?,
    };
    a_python(py, &Valor::Lista(m::mensajes_openai(&l).map_err(|e| lanzar(py, e))?))
}

#[pyfunction]
fn a_openai<'py>(py: Python<'py>, ruta: &str, pedido: &Bound<'py, PyAny>) -> PyResult<(Bound<'py, PyDict>, Bound<'py, PyDict>)> {
    let (c, p) = m::a_openai(ruta, &de_python(pedido)?).map_err(|e| lanzar(py, e))?;
    Ok((mapa_a_python(py, &c)?, mapa_a_python(py, &p)?))
}

fn opcion(v: Option<&Bound<'_, PyAny>>) -> PyResult<Valor> {
    match v {
        Some(x) if !x.is_none() => de_python(x),
        _ => Ok(Valor::Nulo),
    }
}

#[pyfunction]
#[pyo3(signature = (ruta, respuesta, prefijos, carga_s = 0.0, contexto = None, proyecto = None))]
fn a_ollama_completo<'py>(
    py: Python<'py>,
    ruta: &str,
    respuesta: &Bound<'py, PyAny>,
    prefijos: &Bound<'py, PyAny>,
    carga_s: f64,
    contexto: Option<i64>,
    proyecto: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyDict>> {
    let r = m::a_ollama_completo(ruta, &de_python(respuesta)?, &mapa_de_python(prefijos)?, carga_s, contexto, &opcion(proyecto)?);
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
#[pyo3(signature = (ruta, motivo, timings, carga_s, llamadas, contexto = None, proyecto = None))]
#[allow(clippy::too_many_arguments)]
fn final_<'py>(
    py: Python<'py>,
    ruta: &str,
    motivo: Option<String>,
    timings: &Bound<'py, PyAny>,
    carga_s: f64,
    llamadas: &Bound<'py, PyAny>,
    contexto: Option<i64>,
    proyecto: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyDict>> {
    let ll = match de_python(llamadas)? {
        Valor::Lista(l) => l,
        _ => vec![],
    };
    let r = m::final_(ruta, motivo.as_deref(), &de_python(timings)?, carga_s, ll, contexto, &opcion(proyecto)?);
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

/// `a_ollama` línea a línea (para quien tiene las líneas en Python)
#[pyclass(name = "Traductor")]
pub struct TraductorPy {
    inner: m::Traductor,
    pub fin: bool,
}

#[pymethods]
impl TraductorPy {
    #[new]
    #[pyo3(signature = (ruta, prefijos, carga_s = 0.0, contexto = None, proyecto = None))]
    fn new(ruta: &str, prefijos: &Bound<'_, PyAny>, carga_s: f64, contexto: Option<i64>, proyecto: Option<&Bound<'_, PyAny>>) -> PyResult<Self> {
        let p = if prefijos.is_truthy()? { mapa_de_python(prefijos)? } else { Mapa::new() };
        Ok(TraductorPy { inner: m::Traductor::new(ruta, &p, carga_s, contexto, opcion(proyecto)?), fin: false })
    }

    #[getter]
    fn fin(&self) -> bool {
        self.fin
    }

    /// Los objetos que salen de una línea
    fn linea<'py>(&mut self, py: Python<'py>, linea: &str) -> PyResult<Bound<'py, PyAny>> {
        let mut salida = Vec::new();
        self.fin = self.inner.linea(linea, &mut salida).map_err(|e| lanzar(py, e))?;
        a_python(py, &Valor::Lista(salida))
    }

    /// El objeto final (None si terminó con un error)
    fn cerrar<'py>(&mut self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyAny>>> {
        match self.inner.cerrar().map_err(|e| lanzar(py, e))? {
            Some(v) => Ok(Some(a_python(py, &v)?)),
            None => Ok(None),
        }
    }
}

/// El flujo de una respuesta del motor: líneas NDJSON de Ollama (`__next__`, como `iter_lines`) u objetos
#[pyclass(name = "Flujo", frozen)]
pub struct FlujoPy {
    inner: m::Flujo,
}

#[pymethods]
impl FlujoPy {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    /// La siguiente línea NDJSON (`json.dumps(objeto, ensure_ascii=False)` en UTF-8)
    fn __next__<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyBytes>>> {
        match py.detach(|| self.inner.siguiente()).map_err(PyRuntimeError::new_err)? {
            Some(v) => Ok(Some(PyBytes::new(py, json::escribir_linea(&v).as_bytes()))),
            None => Ok(None),
        }
    }

    /// El siguiente objeto (o None al terminar)
    fn objeto<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyAny>>> {
        match py.detach(|| self.inner.siguiente()).map_err(PyRuntimeError::new_err)? {
            Some(v) => Ok(Some(a_python(py, &v)?)),
            None => Ok(None),
        }
    }

    fn close(&self) {
        self.inner.cerrar()
    }
}

impl FlujoPy {
    pub fn nucleo(&self) -> &m::Flujo {
        &self.inner
    }
}

/// Manda el cuerpo a llama-server: (200, Flujo) en streaming, o (estado, cuerpo en bytes)
#[pyfunction]
#[pyo3(signature = (url, cuerpo, ruta, prefijos, carga_s = 0.0, contexto = None, proyecto = None, timeout = 600.0))]
#[allow(clippy::too_many_arguments)]
fn pedir<'py>(
    py: Python<'py>,
    url: String,
    cuerpo: &Bound<'py, PyAny>,
    ruta: String,
    prefijos: &Bound<'py, PyAny>,
    carga_s: f64,
    contexto: Option<i64>,
    proyecto: Option<&Bound<'py, PyAny>>,
    timeout: f64,
) -> PyResult<(u16, Py<PyAny>)> {
    let c = mapa_de_python(cuerpo)?;
    let stream = c.verdad("stream");
    let p = mapa_de_python(prefijos)?;
    let proy = opcion(proyecto)?;
    let r = py.detach(|| m::pedir(&url, &c, stream, timeout));
    match r {
        Err(e) => Err(match py.import("requests.exceptions").and_then(|x| x.getattr("ConnectionError")).and_then(|x| x.call1((e.clone(),))) {
            Ok(exc) => PyErr::from_value(exc),
            Err(_) => PyRuntimeError::new_err(e),
        }),
        Ok(m::Respuesta::Flujo(lector)) => {
            let flujo = m::Flujo::new(lector, m::Traductor::new(&ruta, &p, carga_s, contexto, proy));
            Ok((200, Py::new(py, FlujoPy { inner: flujo })?.into_any()))
        }
        Ok(m::Respuesta::Entera(estado, b)) => Ok((estado, PyBytes::new(py, &b).into_any().unbind())),
    }
}

pub fn registrar(md: &Bound<'_, PyModule>) -> PyResult<()> {
    md.add("NOMBRE", m::NOMBRE)?;
    md.add("GRAMATICA_CODIGO", m::GRAMATICA_CODIGO)?;
    md.add("INSTRUCCION_SOLO_CODIGO", m::INSTRUCCION_SOLO_CODIGO)?;
    md.add_class::<TraductorPy>()?;
    md.add_class::<FlujoPy>()?;
    for f in [
        wrap_pyfunction!(estimar_tokens, md)?,
        wrap_pyfunction!(prefijo_de, md)?,
        wrap_pyfunction!(lista_caliente, md)?,
        wrap_pyfunction!(contexto_para, md)?,
        wrap_pyfunction!(lote_para, md)?,
        wrap_pyfunction!(base_mb, md)?,
        wrap_pyfunction!(cabe_mtp, md)?,
        wrap_pyfunction!(calientes_para, md)?,
        wrap_pyfunction!(segundos_keep_alive, md)?,
        wrap_pyfunction!(tamanos_gguf, md)?,
        wrap_pyfunction!(muestreo_para, md)?,
        wrap_pyfunction!(mensajes_openai, md)?,
        wrap_pyfunction!(a_openai, md)?,
        wrap_pyfunction!(a_ollama_completo, md)?,
        wrap_pyfunction!(final_, md)?,
        wrap_pyfunction!(pedir, md)?,
    ] {
        md.add_function(f)?;
    }
    Ok(())
}
