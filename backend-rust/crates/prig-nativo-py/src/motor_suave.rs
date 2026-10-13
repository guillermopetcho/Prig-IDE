//! Motor suave (prig_recursos::motor_suave) para `backend/recursos/motor_suave.py`

use crate::ritmo::{reloj, RitmoPy};
use crate::valor::{a_python, de_python, mapa_a_python};
use prig_recursos::motor_suave::{self as ms, ControladorSuave, EstadoMotor, MundoSuave, Rutas};
use prig_recursos::valor::Valor;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::PathBuf;
use std::sync::Mutex;

fn rutas(raiz: &str) -> Rutas {
    Rutas::desde_entorno(&PathBuf::from(raiz))
}

fn estado_de(d: &Bound<'_, PyAny>) -> PyResult<Option<EstadoMotor>> {
    if d.is_none() {
        return Ok(None);
    }
    Ok(Some(EstadoMotor {
        pid: d.get_item("pid")?.extract()?,
        ultima: d.get_item("ultima")?.extract()?,
        fraccion: d.get_item("fraccion")?.extract()?,
        tramo: d.get_item("tramo")?.extract()?,
        esperas_s: d.get_item("esperas_s")?.extract()?,
    }))
}

fn estado_a<'py>(py: Python<'py>, e: Option<&EstadoMotor>) -> PyResult<Bound<'py, PyAny>> {
    match e {
        Some(e) => Ok(mapa_a_python(py, &e.mapa())?.into_any()),
        None => Ok(py.None().into_bound(py)),
    }
}

#[pyfunction]
#[pyo3(signature = (raiz, forzar = false))]
fn compilar<'py>(py: Python<'py>, raiz: &str, forzar: bool) -> PyResult<Bound<'py, PyDict>> {
    let r = rutas(raiz);
    mapa_a_python(py, &py.detach(|| ms::compilar(&r, forzar))?)
}

#[pyfunction]
fn instalar<'py>(py: Python<'py>, raiz: &str) -> PyResult<Bound<'py, PyDict>> {
    let r = rutas(raiz);
    mapa_a_python(py, &py.detach(|| ms::instalar(&r))?)
}

#[pyfunction]
fn desinstalar<'py>(py: Python<'py>, raiz: &str) -> PyResult<Bound<'py, PyDict>> {
    let r = rutas(raiz);
    mapa_a_python(py, &py.detach(|| ms::desinstalar(&r))?)
}

#[pyfunction]
fn instalado(raiz: &str) -> bool {
    ms::instalado(&rutas(raiz))
}

#[pyfunction]
fn leer_estado<'py>(py: Python<'py>, raiz: &str) -> PyResult<Bound<'py, PyAny>> {
    estado_a(py, ms::leer_estado(&rutas(raiz)).as_ref())
}

#[pyfunction]
fn generando(estado: &Bound<'_, PyAny>, ahora: f64) -> PyResult<bool> {
    Ok(ms::generando(estado_de(estado)?.as_ref(), ahora))
}

#[pyfunction]
fn escribir_control(raiz: &str, fraccion: f64, tramo: f64, ahora: f64) {
    ms::escribir_control(&rutas(raiz), fraccion, tramo, ahora);
}

#[pyfunction]
fn quitar_control(raiz: &str) {
    ms::quitar_control(&rutas(raiz));
}

/// El mundo del controlador: la fachada de Python (su `_leer_estado`, `_generando`, `monitor`, `_escribir_control`
/// y `_quitar_control`), para que las pruebas puedan sustituir cada pieza
struct MundoPython<'a, 'py> {
    py: Python<'py>,
    fachada: &'a Bound<'py, PyAny>,
    error: Option<PyErr>,
}

impl MundoPython<'_, '_> {
    fn apuntar(&mut self, e: PyErr) {
        if self.error.is_none() {
            self.error = Some(e);
        }
    }
}

impl MundoSuave for MundoPython<'_, '_> {
    fn leer_estado(&mut self) -> Option<EstadoMotor> {
        match self.fachada.call_method0("_leer_estado").and_then(|e| estado_de(&e)) {
            Ok(e) => e,
            Err(e) => {
                self.apuntar(e);
                None
            }
        }
    }

    fn generando(&mut self, estado: Option<&EstadoMotor>) -> bool {
        let r = estado_a(self.py, estado).and_then(|e| self.fachada.call_method1("_generando", (e,))).and_then(|v| v.is_truthy());
        r.unwrap_or_else(|e| {
            self.apuntar(e);
            false
        })
    }

    fn gpu(&mut self, max_edad: f64) -> Option<Valor> {
        // Un fallo del sensor no para el controlador (como el try/except de Python)
        let kw = PyDict::new(self.py);
        kw.set_item("max_edad", max_edad).ok()?;
        let v = self.fachada.getattr("monitor").ok()?.call_method("gpu", (), Some(&kw)).ok()?;
        de_python(&v).ok().filter(|v| !v.es_nulo())
    }

    fn ahora(&mut self) -> f64 {
        reloj(self.py).unwrap_or_else(|e| {
            self.apuntar(e);
            f64::NAN
        })
    }

    fn escribir_control(&mut self, fraccion: f64, tramo: f64) {
        if let Err(e) = self.fachada.call_method1("_escribir_control", (fraccion, tramo)) {
            self.apuntar(e);
        }
    }

    fn quitar_control(&mut self) {
        if let Err(e) = self.fachada.call_method0("_quitar_control") {
            self.apuntar(e);
        }
    }
}

/// El estado del `Controlador` de Python: temperatura media, fracción y último paso
#[pyclass(name = "Controlador", frozen)]
pub struct ControladorPy {
    inner: Mutex<ControladorSuave>,
}

#[pymethods]
impl ControladorPy {
    #[new]
    fn new() -> Self {
        ControladorPy { inner: Mutex::new(ControladorSuave::default()) }
    }

    /// Un paso con el ritmo y el mundo de la fachada
    fn paso<'py>(&self, py: Python<'py>, fachada: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
        let ritmo = fachada.getattr("ritmo")?;
        let ritmo = ritmo.cast::<RitmoPy>()?;
        let mut mundo = MundoPython { py, fachada, error: None };
        let r = self.inner.lock().unwrap_or_else(|e| e.into_inner()).paso(&ritmo.get().inner, &mut mundo);
        if let Some(e) = mundo.error {
            return Err(e);
        }
        mapa_a_python(py, &r)
    }

    #[getter]
    fn temp_media<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let t = self.inner.lock().unwrap_or_else(|e| e.into_inner()).temp_media.clone();
        a_python(py, &t.unwrap_or(Valor::Nulo))
    }

    #[getter]
    fn fraccion(&self) -> Option<f64> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner()).fraccion
    }

    #[getter]
    fn ultimo<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let u = self.inner.lock().unwrap_or_else(|e| e.into_inner()).ultimo.clone();
        mapa_a_python(py, &u)
    }
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("MARCA_ENVOLTORIO", ms::MARCA_ENVOLTORIO)?;
    m.add("ACTIVO_S", ms::ACTIVO_S)?;
    m.add("PERIODO_S", ms::PERIODO_S)?;
    m.add("SUBIDA", ms::SUBIDA)?;
    m.add("BAJADA", ms::BAJADA)?;
    m.add("SUAVIZADO", ms::SUAVIZADO)?;
    m.add_class::<ControladorPy>()?;
    m.add_function(wrap_pyfunction!(compilar, m)?)?;
    m.add_function(wrap_pyfunction!(instalar, m)?)?;
    m.add_function(wrap_pyfunction!(desinstalar, m)?)?;
    m.add_function(wrap_pyfunction!(instalado, m)?)?;
    m.add_function(wrap_pyfunction!(leer_estado, m)?)?;
    m.add_function(wrap_pyfunction!(generando, m)?)?;
    m.add_function(wrap_pyfunction!(escribir_control, m)?)?;
    m.add_function(wrap_pyfunction!(quitar_control, m)?)?;
    Ok(())
}
