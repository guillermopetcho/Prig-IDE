//! Fichas de modelos (prig_recursos::ficha) para `backend/recursos/ficha.py`: la parte que no toca la red

use crate::valor::{de_python, mapa_a_python, mapa_de_python};
use prig_recursos::ficha;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pyfunction]
#[pyo3(signature = (meta, nombre, bytes_peso, capacidades = None, plantilla = "", origen = "ollama", cuantizacion = ""))]
#[allow(clippy::too_many_arguments)]
fn desde_metadatos<'py>(
    py: Python<'py>,
    meta: &Bound<'py, PyAny>,
    nombre: &str,
    bytes_peso: &Bound<'py, PyAny>,
    capacidades: Option<Vec<String>>,
    plantilla: Option<&str>,
    origen: &str,
    cuantizacion: Option<&str>,
) -> PyResult<Bound<'py, PyDict>> {
    let f = ficha::desde_metadatos(
        &mapa_de_python(meta)?,
        nombre,
        &de_python(bytes_peso)?,
        &capacidades.unwrap_or_default(),
        plantilla.unwrap_or(""),
        origen,
        cuantizacion.unwrap_or(""),
    );
    mapa_a_python(py, &f)
}

/// Caché KV (bytes) para un contexto y un número de peticiones simultáneas
#[pyfunction]
#[pyo3(signature = (ficha, contexto, paralelo = 1, tipo = "f16"))]
fn kv_bytes(ficha: &Bound<'_, PyAny>, contexto: i64, paralelo: i64, tipo: &str) -> PyResult<i128> {
    Ok(ficha::kv_bytes(&mapa_de_python(ficha)?, contexto, paralelo, tipo))
}

#[pyfunction]
fn desde_catalogo<'py>(py: Python<'py>, nombre: &str, info: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let f = ficha::desde_catalogo(nombre, &mapa_de_python(info)?).map_err(PyValueError::new_err)?;
    mapa_a_python(py, &f)
}

/// (url del registro, repo, etiqueta)
#[pyfunction]
fn registro_de(nombre: &str) -> (String, String, String) {
    ficha::registro_de(nombre)
}

fn error(e: ficha::ErrorFicha) -> PyErr {
    match e {
        ficha::ErrorFicha::NoEncontrada(m) => pyo3::exceptions::PyLookupError::new_err(m),
        ficha::ErrorFicha::Otro(m) => pyo3::exceptions::PyOSError::new_err(m),
    }
}

/// Nombre → {tamaño, digest, detalles} de lo que Ollama tiene descargado
#[pyfunction]
fn instalados<'py>(py: Python<'py>, ollama: &str) -> PyResult<Bound<'py, PyDict>> {
    let r = py.detach(|| ficha::instalados(ollama)).map_err(error)?;
    mapa_a_python(py, &r)
}

#[pyfunction]
fn desde_ollama<'py>(py: Python<'py>, ollama: &str, nombre: &str) -> PyResult<Bound<'py, PyDict>> {
    let r = py.detach(|| ficha::desde_ollama(ollama, nombre)).map_err(error)?;
    mapa_a_python(py, &r)
}

/// La ficha leyendo solo la cabecera GGUF del registro (con la caché por digest en `cache`)
#[pyfunction]
fn desde_registro<'py>(py: Python<'py>, nombre: &str, cache: &str) -> PyResult<Bound<'py, PyDict>> {
    let r = py.detach(|| ficha::desde_registro(nombre, std::path::Path::new(cache))).map_err(error)?;
    mapa_a_python(py, &r)
}

/// La mejor ficha: Ollama, el registro (si `red`) o el catálogo. LookupError si no hay ninguna.
#[pyfunction]
#[pyo3(signature = (ollama, nombre, catalogo, red, cache))]
fn obtener<'py>(
    py: Python<'py>,
    ollama: &str,
    nombre: &str,
    catalogo: Option<&Bound<'py, PyAny>>,
    red: bool,
    cache: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let c = match catalogo {
        Some(c) if c.is_truthy()? => Some(mapa_de_python(c)?),
        _ => None,
    };
    let r = py
        .detach(|| ficha::obtener(ollama, nombre, c.as_ref(), red, std::path::Path::new(cache)))
        .map_err(pyo3::exceptions::PyLookupError::new_err)?;
    mapa_a_python(py, &r)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(instalados, m)?)?;
    m.add_function(wrap_pyfunction!(desde_ollama, m)?)?;
    m.add_function(wrap_pyfunction!(desde_registro, m)?)?;
    m.add_function(wrap_pyfunction!(obtener, m)?)?;
    let bytes_kv = PyDict::new(m.py());
    for (k, v) in ficha::BYTES_KV {
        bytes_kv.set_item(k, v)?;
    }
    m.add("BYTES_KV", bytes_kv)?;
    m.add("REGISTRO", ficha::REGISTRO)?;
    let externos = PyDict::new(m.py());
    for (k, v) in ficha::REGISTROS_EXTERNOS {
        externos.set_item(k, v)?;
    }
    m.add("REGISTROS_EXTERNOS", externos)?;
    m.add_function(wrap_pyfunction!(desde_metadatos, m)?)?;
    m.add_function(wrap_pyfunction!(kv_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(desde_catalogo, m)?)?;
    m.add_function(wrap_pyfunction!(registro_de, m)?)?;
    Ok(())
}
