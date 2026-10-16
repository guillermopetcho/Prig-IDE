//! HTTP con conexiones reutilizadas (prig_modelos::red::enviar): `prig_nativo.http`. La petición la prepara
//! `requests` en Python (red_http.py) y la respuesta vuelve a ser un `requests.Response`; aquí solo se envía, sin el
//! GIL, por el cliente compartido del proceso.

use prig_modelos::red::{self, ErrorRed};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

fn de_requests(py: Python<'_>, clase: &str, texto: String) -> PyErr {
    match py.import("requests.exceptions").and_then(|m| m.getattr(clase)).and_then(|c| c.call1((texto.clone(),))) {
        Ok(e) => PyErr::from_value(e),
        Err(_) => pyo3::exceptions::PyOSError::new_err(texto),
    }
}

type RespuestaPy<'py> = (u16, String, Vec<(String, String)>, Bound<'py, PyBytes>, String);

/// `(estado, razón, cabeceras, cuerpo, url final)`; lanza `requests.ConnectionError` o `requests.Timeout`
#[pyfunction]
#[pyo3(signature = (metodo, url, cabeceras, cuerpo = None, segundos = None, redirigir = true))]
fn enviar<'py>(py: Python<'py>, metodo: String, url: String, cabeceras: Vec<(String, String)>, cuerpo: Option<Vec<u8>>,
               segundos: Option<f64>, redirigir: bool) -> PyResult<RespuestaPy<'py>> {
    let r = py.detach(|| red::enviar(&metodo, &url, &cabeceras, cuerpo, segundos, redirigir)).map_err(|e| match e {
        ErrorRed::Tiempo(t) => de_requests(py, "Timeout", t),
        ErrorRed::Conexion(t) | ErrorRed::Json(t, _) => de_requests(py, "ConnectionError", t),
    })?;
    Ok((r.estado, r.razon, r.cabeceras, PyBytes::new(py, &r.cuerpo), r.url))
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(enviar, m)?)?;
    Ok(())
}
