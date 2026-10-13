//! Monitor de audio (prig_recursos::audio) para `backend/audio_monitor.py`: la captura y la FFT en un hilo de Rust,
//! sin el GIL

use crate::valor::{de_python, mapa_a_python};
use prig_recursos::audio::{Analizador, MonitorAudio};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

#[pyclass(name = "MonitorAudio", frozen)]
pub struct MonitorAudioPy {
    inner: MonitorAudio,
}

#[pymethods]
impl MonitorAudioPy {
    #[new]
    fn new() -> Self {
        MonitorAudioPy { inner: MonitorAudio::new() }
    }

    /// Las aplicaciones y pestañas que suenan (pactl), con «todo el sistema» primero
    fn listar_aplicaciones_audio<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let apps = py.detach(|| self.inner.listar());
        let l = PyList::empty(py);
        for a in &apps {
            l.append(mapa_a_python(py, a)?)?;
        }
        Ok(l)
    }

    fn seleccionar_fuente(&self, fuente: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.seleccionar_fuente(de_python(fuente)?);
        Ok(())
    }

    #[getter]
    fn datos_actuales<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.datos())
    }

    fn incrementar_suscriptor(&self, py: Python<'_>) {
        py.detach(|| self.inner.incrementar());
    }

    fn decrementar_suscriptor(&self, py: Python<'_>) {
        py.detach(|| self.inner.decrementar());
    }
}

/// El análisis de un trozo de 512 muestras s16le (para comprobarlo contra el de Python)
#[pyfunction]
fn analizar<'py>(py: Python<'py>, pcm: &[u8], fuente: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &Analizador::new().analizar(pcm, &de_python(fuente)?))
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<MonitorAudioPy>()?;
    m.add_function(wrap_pyfunction!(analizar, m)?)?;
    Ok(())
}
