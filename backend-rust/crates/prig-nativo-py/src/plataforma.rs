//! La plataforma (prig_plataforma, F2): `prig_nativo.banderas` para `feature_flags.py` y `prig_nativo.perfiles_config`
//! para `perfiles_config.py`

use crate::valor::{a_python, de_python, mapa_a_python};
use prig_plataforma::{banderas, perfiles};
use pyo3::exceptions::PyKeyError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::PathBuf;
use std::sync::Mutex;

/// Lo que Python imprimía (`print`), por el `print` de Python: así sale donde salía
pub fn imprimir(py: Python<'_>, avisos: Vec<String>) -> PyResult<()> {
    if avisos.is_empty() {
        return Ok(());
    }
    let print = py.import("builtins")?.getattr("print")?;
    for a in avisos {
        print.call1((a,))?;
    }
    Ok(())
}

// =========================================================================== banderas

#[pyclass(name = "FeatureFlags", frozen)]
pub struct FeatureFlagsPy {
    inner: Mutex<banderas::Banderas>,
}

impl FeatureFlagsPy {
    fn con<T>(&self, py: Python<'_>, f: impl FnOnce(&mut banderas::Banderas) -> T) -> PyResult<T> {
        let (r, avisos) = {
            let mut b = self.inner.lock().unwrap();
            // el servidor de Rust también guarda banderas (POST /api/flags): se lee lo último del archivo
            b.refrescar();
            let r = f(&mut b);
            (r, std::mem::take(&mut b.avisos))
        };
        imprimir(py, avisos)?;
        Ok(r)
    }
}

#[pymethods]
impl FeatureFlagsPy {
    #[new]
    fn new(py: Python<'_>, path: PathBuf) -> PyResult<Self> {
        let mut b = banderas::Banderas::new(path);
        imprimir(py, std::mem::take(&mut b.avisos))?;
        Ok(FeatureFlagsPy { inner: Mutex::new(b) })
    }

    #[getter]
    fn path(&self) -> PathBuf {
        self.inner.lock().unwrap().ruta.clone()
    }

    fn is_enabled(&self, py: Python<'_>, name: &str) -> PyResult<bool> {
        self.con(py, |b| b.activa(name))
    }

    fn set(&self, py: Python<'_>, name: &str, value: &Bound<'_, PyAny>) -> PyResult<bool> {
        let v = value.is_truthy()?;
        self.con(py, |b| b.poner(name, v))?.map_err(PyKeyError::new_err)
    }

    fn reset(&self, py: Python<'_>, name: &str) -> PyResult<bool> {
        self.con(py, |b| b.reiniciar(name))
    }

    fn all<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let m = self.con(py, |b| b.todas())?;
        mapa_a_python(py, &m)
    }
}

fn registrar_banderas(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("DEFAULT_FLAGS", mapa_a_python(m.py(), &banderas::declaradas())?)?;
    m.add_class::<FeatureFlagsPy>()?;
    Ok(())
}

// =========================================================================== perfiles

#[pyfunction]
fn predeterminados(py: Python<'_>) -> PyResult<Bound<'_, PyAny>> {
    a_python(py, &perfiles::predeterminados())
}

#[pyfunction]
fn cargar_json<'py>(py: Python<'py>, dir: PathBuf, ruta: PathBuf, por_defecto: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let mut avisos = Vec::new();
    let defecto = de_python(por_defecto)?;
    let v = py.detach(|| perfiles::cargar(&dir, &ruta, defecto, &mut avisos));
    imprimir(py, avisos)?;
    a_python(py, &v)
}

#[pyfunction]
fn guardar_json(py: Python<'_>, dir: PathBuf, ruta: PathBuf, datos: &Bound<'_, PyAny>) -> PyResult<bool> {
    let mut avisos = Vec::new();
    let v = de_python(datos)?;
    let ok = py.detach(|| perfiles::guardar(&dir, &ruta, &v, &mut avisos));
    imprimir(py, avisos)?;
    Ok(ok)
}

#[pyfunction]
fn cargar_perfiles(py: Python<'_>, dir: PathBuf, ruta: PathBuf) -> PyResult<Bound<'_, PyAny>> {
    let mut avisos = Vec::new();
    let v = py.detach(|| perfiles::cargar_perfiles(&dir, &ruta, &mut avisos));
    imprimir(py, avisos)?;
    a_python(py, &v)
}

fn registrar_perfiles(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(predeterminados, m)?)?;
    m.add_function(wrap_pyfunction!(cargar_json, m)?)?;
    m.add_function(wrap_pyfunction!(guardar_json, m)?)?;
    m.add_function(wrap_pyfunction!(cargar_perfiles, m)?)?;
    Ok(())
}

pub fn registrar(padre: &Bound<'_, PyModule>) -> PyResult<()> {
    crate::valor::submodulo(padre, "banderas", registrar_banderas)?;
    crate::valor::submodulo(padre, "perfiles_config", registrar_perfiles)?;
    Ok(())
}

// =========================================================================== excepciones

pyo3::create_exception!(prig_nativo, ErrorIDE, pyo3::exceptions::PyException, "Un error de los servicios del IDE (el texto es para el usuario)");

/// La excepción de Python que lanzaba el código de Python
pub fn lanzar(py: Python<'_>, e: prig_plataforma::py::ErrorPy) -> PyErr {
    lanzar_con(py, e, ErrorIDE::new_err)
}

/// Como `lanzar`, con la excepción propia del módulo que llama (ErrorConfig, ErrorGestion, ...)
pub fn lanzar_con(py: Python<'_>, e: prig_plataforma::py::ErrorPy, propia: impl FnOnce(String) -> PyErr) -> PyErr {
    use prig_plataforma::py::ErrorPy as E;
    use pyo3::exceptions::*;
    match e {
        E::Propia(t) => propia(t),
        E::Desborde(t) => PyOverflowError::new_err(t),
        E::Permiso(t) => PyPermissionError::new_err(t),
        E::Os { errno, ruta, ruta2 } => {
            // OSError(errno, strerror, archivo, None, archivo2): Python elige la subclase (FileNotFoundError, ...)
            let texto = prig_plataforma::py::strerror(errno);
            let r = py.import("builtins").and_then(|b| b.getattr("OSError")).and_then(|c| match &ruta2 {
                Some(b) => c.call1((errno, texto, ruta, py.None(), b)),
                None => c.call1((errno, texto, ruta)),
            });
            match r {
                Ok(exc) => PyErr::from_value(exc),
                Err(err) => err,
            }
        }
        E::OsTexto(t) => PyOSError::new_err(t),
        E::NoEsCarpeta(t) => PyNotADirectoryError::new_err(t),
        // KeyError(slice(...)): su str() es el repr de la clave, que aquí ya viene escrito
        E::Clave(t) => match py.eval(&std::ffi::CString::new(t.clone()).unwrap_or_default(), None, None) {
            Ok(clave) => PyKeyError::new_err(clave.unbind()),
            Err(_) => PyKeyError::new_err(t),
        },
        E::Shutil(lista) => match py.import("shutil").and_then(|m| m.getattr("Error")).and_then(|c| c.call1((lista,))) {
            Ok(exc) => PyErr::from_value(exc),
            Err(err) => err,
        },
        E::Atributo(t) => PyAttributeError::new_err(t),
        E::Tipo(t) => PyTypeError::new_err(t),
        E::Valor(t) => PyValueError::new_err(t),
    }
}

/// `requests.exceptions.JSONDecodeError(msg, doc, pos)` a partir del texto «msg: line L column C (char N)» del
/// lector JSON (así su `str()` y su tipo son los de Python)
pub fn json_decode_error(py: Python<'_>, mensaje: &str, doc: &str) -> PyErr {
    let (msg, pos) = match mensaje.rsplit_once(": line ") {
        Some((m, resto)) => {
            let pos = resto.rsplit_once("(char ").and_then(|(_, n)| n.trim_end_matches(')').parse::<usize>().ok()).unwrap_or(0);
            (m.to_string(), pos)
        }
        None => (mensaje.to_string(), 0),
    };
    match py.import("requests.exceptions").and_then(|m| m.getattr("JSONDecodeError")).and_then(|c| c.call1((msg, doc, pos))) {
        Ok(e) => PyErr::from_value(e),
        Err(e) => e,
    }
}
