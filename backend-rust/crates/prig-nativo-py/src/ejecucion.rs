//! Ejecutar código (prig_plataforma::ejecucion) para `runner.py` y `kernel_session.py`: `prig_nativo.ejecucion`.
//! Esperar a un proceso no retiene el GIL: otra petición puede cancelarlo mientras tanto.

use crate::valor::mapa_a_python;
use prig_plataforma::ejecucion::{ErrorKernel, Ejecutor, Sesion, Sesiones};
use pyo3::exceptions::{PyBrokenPipeError, PyTimeoutError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Arc;

fn error_kernel(e: ErrorKernel) -> PyErr {
    match e {
        ErrorKernel::Tiempo(t) => PyTimeoutError::new_err(t),
        ErrorKernel::Otro(t) => PyBrokenPipeError::new_err(t),
    }
}

#[pyclass(name = "Ejecutor", frozen)]
pub struct EjecutorPy {
    inner: Arc<Ejecutor>,
}

#[pymethods]
impl EjecutorPy {
    #[new]
    fn new(timeout_seconds: i64, python: String) -> Self {
        EjecutorPy { inner: Arc::new(Ejecutor::new(timeout_seconds, python)) }
    }

    #[getter]
    fn timeout_seconds(&self) -> i64 {
        self.inner.timeout
    }

    #[getter]
    fn sesiones(&self) -> SesionesPy {
        SesionesPy { inner: self.inner.sesiones.clone() }
    }

    /// {identificador: pid} de las ejecuciones en marcha
    fn activos(&self) -> std::collections::HashMap<String, i32> {
        self.inner.activos.lock().unwrap().clone()
    }

    fn registrar(&self, run_id: &str, pid: i32) {
        self.inner.registrar(run_id, pid)
    }

    fn quitar(&self, run_id: &str) {
        self.inner.activos.lock().unwrap().remove(run_id);
    }

    fn cancel<'py>(&self, py: Python<'py>, run_id: &str) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.cancelar(run_id))
    }

    fn cancel_all(&self, py: Python<'_>) {
        py.detach(|| self.inner.cancelar_todo())
    }

    fn shutdown(&self, py: Python<'_>) {
        py.detach(|| self.inner.apagar())
    }

    #[pyo3(signature = (file_path, cwd = None, timeout = None, run_id = None, extra_sources = None))]
    fn run_file<'py>(
        &self,
        py: Python<'py>,
        file_path: String,
        cwd: Option<String>,
        timeout: Option<i64>,
        run_id: Option<String>,
        extra_sources: Option<Vec<String>>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let extra = extra_sources.unwrap_or_default();
        let m = py.detach(|| self.inner.ejecutar_archivo(&file_path, cwd.as_deref(), timeout, run_id.as_deref(), &extra));
        mapa_a_python(py, &m)
    }

    #[pyo3(signature = (code_string, cwd = None, session_id = None, timeout = None))]
    fn run_cell_code<'py>(
        &self,
        py: Python<'py>,
        code_string: String,
        cwd: Option<String>,
        session_id: Option<String>,
        timeout: Option<i64>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let m = py.detach(|| self.inner.ejecutar_celda(&code_string, cwd.as_deref(), session_id.as_deref(), timeout));
        mapa_a_python(py, &m)
    }
}

#[pyclass(name = "Sesiones", frozen)]
pub struct SesionesPy {
    inner: Arc<Sesiones>,
}

#[pymethods]
impl SesionesPy {
    #[new]
    fn new(python: String) -> Self {
        SesionesPy { inner: Arc::new(Sesiones::new(python)) }
    }

    fn get(&self, py: Python<'_>, session_id: Option<String>, cwd: String) -> PyResult<SesionPy> {
        let s = py.detach(|| self.inner.obtener(session_id.as_deref(), &cwd)).map_err(error_kernel)?;
        Ok(SesionPy { inner: s })
    }

    #[pyo3(signature = (session_id = None))]
    fn reset(&self, py: Python<'_>, session_id: Option<String>) -> bool {
        py.detach(|| self.inner.reiniciar(session_id.as_deref()))
    }

    fn shutdown_all(&self, py: Python<'_>) {
        py.detach(|| self.inner.apagar_todas())
    }

    fn claves(&self) -> Vec<String> {
        self.inner.mapa.lock().unwrap().keys().cloned().collect()
    }
}

#[pyclass(name = "Sesion", frozen)]
pub struct SesionPy {
    inner: Arc<Sesion>,
}

#[pymethods]
impl SesionPy {
    #[new]
    fn new(cwd: String, python: String) -> PyResult<Self> {
        let s = Sesion::new(&cwd, &python).map_err(PyBrokenPipeError::new_err)?;
        Ok(SesionPy { inner: Arc::new(s) })
    }

    #[getter]
    fn cwd(&self) -> String {
        self.inner.cwd.clone()
    }

    #[getter]
    fn driver(&self) -> String {
        self.inner.driver.clone()
    }

    #[getter]
    fn pid(&self) -> u32 {
        self.inner.pid()
    }

    fn is_alive(&self) -> bool {
        self.inner.viva()
    }

    fn execute<'py>(&self, py: Python<'py>, code: String, timeout: i64) -> PyResult<Bound<'py, PyDict>> {
        let r = py.detach(|| self.inner.ejecutar(&code, timeout)).map_err(error_kernel)?;
        mapa_a_python(py, &r)
    }

    fn shutdown(&self, py: Python<'_>) {
        py.detach(|| self.inner.apagar())
    }
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("DRIVER", prig_plataforma::ejecucion::DRIVER)?;
    m.add_class::<EjecutorPy>()?;
    m.add_class::<SesionesPy>()?;
    m.add_class::<SesionPy>()?;
    Ok(())
}
