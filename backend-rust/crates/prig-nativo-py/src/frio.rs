//! Modo frío (prig_recursos::frio) para `backend/recursos/frio.py`

use prig_recursos::frio;
use pyo3::prelude::*;
use std::collections::HashSet;

/// `frio.Proceso`: un proceso concreto, con las señales por pidfd
#[pyclass(name = "Proceso")]
pub struct ProcesoPy {
    inner: frio::Proceso,
}

#[pymethods]
impl ProcesoPy {
    #[new]
    fn new(pid: i32) -> Self {
        ProcesoPy { inner: frio::Proceso::new(pid) }
    }

    #[getter]
    fn pid(&self) -> i32 {
        self.inner.pid
    }

    #[getter]
    fn vivo(&self) -> bool {
        self.inner.vivo
    }

    fn senal(&mut self, sig: i32) -> bool {
        self.inner.senal(sig)
    }

    fn cerrar(&mut self) {
        self.inner.cerrar();
    }

    /// Segundos de CPU usados (usuario + sistema, todos sus hilos)
    fn tiempo_cpu(&self) -> Option<f64> {
        frio::tiempo_cpu(self.inner.pid)
    }
}

/// `frio.Pausador`: trabaja `fraccion` de cada ciclo y congela los motores el resto, en un hilo de Rust (sin GIL)
#[pyclass(name = "Pausador", frozen)]
pub struct PausadorPy {
    inner: frio::Pausador,
}

#[pymethods]
impl PausadorPy {
    #[new]
    #[pyo3(signature = (periodo_s = frio::PERIODO_S))]
    fn new(periodo_s: f64) -> Self {
        PausadorPy { inner: frio::Pausador::new(periodo_s) }
    }

    #[getter]
    fn periodo(&self) -> f64 {
        self.inner.periodo.as_secs_f64()
    }

    #[getter]
    fn fraccion(&self) -> f64 {
        self.inner.fraccion()
    }

    fn pids(&self) -> Vec<i32> {
        self.inner.pids()
    }

    fn congelados(&self) -> Vec<i32> {
        self.inner.congelados()
    }

    fn fijar(&self, py: Python<'_>, pids: HashSet<i32>, fraccion: f64) {
        py.detach(|| self.inner.fijar(&pids, fraccion));
    }

    fn cerrar(&self, py: Python<'_>) {
        py.detach(|| self.inner.cerrar());
    }
}

#[pyfunction]
pub fn tiempo_cpu(pid: i32) -> Option<f64> {
    frio::tiempo_cpu(pid)
}

#[pyfunction]
pub fn turbo_apagado() -> bool {
    frio::turbo_apagado()
}

#[pyfunction]
#[pyo3(signature = (temp, objetivo))]
pub fn fraccion_objetivo(temp: Option<f64>, objetivo: f64) -> f64 {
    frio::fraccion_objetivo(temp, objetivo)
}

/// Los llama-server de Prig: [(pid, blob, estado)]
#[pyfunction]
pub fn motores_de_prig(py: Python<'_>, raiz_prig: &str) -> Vec<(i32, Option<String>, String)> {
    let raiz = raiz_prig.to_string();
    py.detach(|| frio::motores_de_prig(&raiz)).into_iter().map(|m| (m.pid, m.blob, m.estado)).collect()
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("PERIODO_S", frio::PERIODO_S)?;
    m.add("BANDA_C", frio::BANDA_C)?;
    m.add("MINIMO", frio::MINIMO)?;
    m.add_class::<ProcesoPy>()?;
    m.add_class::<PausadorPy>()?;
    m.add_function(wrap_pyfunction!(tiempo_cpu, m)?)?;
    m.add_function(wrap_pyfunction!(turbo_apagado, m)?)?;
    m.add_function(wrap_pyfunction!(fraccion_objetivo, m)?)?;
    m.add_function(wrap_pyfunction!(motores_de_prig, m)?)?;
    Ok(())
}
