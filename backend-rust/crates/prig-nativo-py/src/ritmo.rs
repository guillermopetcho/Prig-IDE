//! Modo suave (prig_recursos::ritmo) para `backend/recursos/ritmo.py`.
//!
//! El reloj es `time.time()` de Python, leído en los mismos sitios que antes: las pruebas lo cambian por uno
//! controlado y cuentan las lecturas.

use crate::valor::{de_python, mapa_a_python, mapa_de_python};
use prig_recursos::ritmo::{self, ErrorPy, FijadorCpu, MundoFijador, ProcesoCpu, Ritmo, SistemaReal};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, MutexGuard};

/// `time.time()` de Python (el que haya en ese momento: las pruebas lo sustituyen)
pub fn reloj(py: Python<'_>) -> PyResult<f64> {
    py.import("time")?.getattr("time")?.call0()?.extract()
}

fn error_py(e: ErrorPy) -> PyErr {
    match e {
        ErrorPy::Valor(m) => PyValueError::new_err(m),
        ErrorPy::Tipo(m) => PyTypeError::new_err(m),
    }
}

/// `Ritmo(ajustes=None, guardar=None)`: cuánto trabajar y cuánto descansar. Se puede heredar desde Python.
#[pyclass(name = "Ritmo", subclass, frozen)]
pub struct RitmoPy {
    pub inner: Mutex<Ritmo>,
    guardar: Option<Py<PyAny>>,
}

impl RitmoPy {
    pub fn bloquear(&self) -> MutexGuard<'_, Ritmo> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }
}

/// `ahora or time.time()`
fn ahora_o_reloj(py: Python<'_>, ahora: Option<f64>) -> PyResult<f64> {
    match ahora {
        Some(a) if a != 0.0 => Ok(a),
        _ => reloj(py),
    }
}

#[pymethods]
impl RitmoPy {
    #[new]
    #[pyo3(signature = (ajustes = None, guardar = None))]
    fn new(py: Python<'_>, ajustes: Option<&Bound<'_, PyAny>>, guardar: Option<Py<PyAny>>) -> PyResult<Self> {
        let a = match ajustes {
            Some(a) if a.is_truthy()? => Some(mapa_de_python(a)?),
            _ => None,
        };
        Ok(RitmoPy { inner: Mutex::new(Ritmo::new(a.as_ref())), guardar: guardar.filter(|g| !g.is_none(py)) })
    }

    /// Cambia los ajustes (acotados) y los guarda si hay dónde
    fn fijar<'py>(&self, py: Python<'py>, cambios: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
        let cambios = mapa_de_python(cambios)?;
        let (ajustes, texto) = self.bloquear().fijar(&cambios).map_err(error_py)?;
        let d = mapa_a_python(py, &ajustes)?;
        if let Some(g) = &self.guardar {
            g.bind(py).call1((d.clone(), texto))?;
        }
        Ok(d)
    }

    #[getter]
    fn activo(&self) -> bool {
        self.bloquear().activo()
    }

    #[getter]
    fn ajustes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let a = self.bloquear().ajustes.clone();
        mapa_a_python(py, &a)
    }

    #[getter]
    fn ultimo<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let u = self.bloquear().ultimo.clone();
        mapa_a_python(py, &u)
    }

    #[pyo3(signature = (ahora = None))]
    fn marcar(&self, py: Python<'_>, ahora: Option<f64>) -> PyResult<()> {
        let a = ahora_o_reloj(py, ahora)?;
        self.bloquear().marcar(a);
        Ok(())
    }

    /// Fracción del tiempo que se trabaja (1 = sin pausas)
    #[pyo3(signature = (temp, ahora = None))]
    fn fraccion(&self, py: Python<'_>, temp: Option<f64>, ahora: Option<f64>) -> PyResult<f64> {
        let a = ahora_o_reloj(py, ahora)?;
        Ok(self.bloquear().fraccion(temp, a))
    }

    /// Si toca descansar tras este tramo, cuántos segundos; si no, None
    #[pyo3(signature = (segundos_trabajando, temp, ahora = None))]
    fn pausa(&self, py: Python<'_>, segundos_trabajando: f64, temp: &Bound<'_, PyAny>, ahora: Option<f64>) -> PyResult<Option<f64>> {
        let temp = de_python(temp)?;
        let mut error = None;
        let r = self.bloquear().pausa(
            segundos_trabajando,
            &temp,
            || ahora_o_reloj(py, ahora).unwrap_or_else(|e| { error = Some(e); f64::NAN }),
            || reloj(py).unwrap_or(f64::NAN),
        );
        match error {
            Some(e) => Err(e),
            None => Ok(r),
        }
    }

    /// `{**ajustes, fraccion_ahora, ultimo, nucleos_eficientes}`. `nucleos`: la función que da los núcleos E
    /// (la de Python, para poder sustituirla); sin ella, la de Rust.
    #[pyo3(signature = (temp = None, nucleos = None))]
    fn estado<'py>(&self, py: Python<'py>, temp: Option<f64>, nucleos: Option<&Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyDict>> {
        let mut error = None;
        let e = self.bloquear().estado(
            temp,
            || reloj(py).unwrap_or(f64::NAN),
            || match nucleos {
                Some(f) => f.call0().and_then(|v| v.extract::<Vec<i64>>()).unwrap_or_else(|e| {
                    error = Some(e);
                    Vec::new()
                }),
                None => ritmo::nucleos_eficientes(),
            },
        );
        if let Some(e) = error {
            return Err(e);
        }
        mapa_a_python(py, &e)
    }
}

// =========================================================================== fijador

/// El mundo del fijador: el objeto `FijadorCPU` de Python (sus `_nucleos`, `_modelos_en_gpu`, `ram_en_eficientes`)
/// y, para procesos y núcleos, su `_sistema` (uno falso en las pruebas) o el de verdad si es None
struct MundoPython<'a, 'py> {
    py: Python<'py>,
    fachada: &'a Bound<'py, PyAny>,
    sistema: Option<Bound<'py, PyAny>>,
    error: Option<PyErr>,
}

impl MundoPython<'_, '_> {
    fn guardar<T>(&mut self, r: PyResult<T>, defecto: T) -> T {
        r.unwrap_or_else(|e| {
            if self.error.is_none() {
                self.error = Some(e);
            }
            defecto
        })
    }
}

impl MundoFijador for MundoPython<'_, '_> {
    fn nucleos_eficientes(&mut self) -> Vec<i64> {
        let r = self.fachada.call_method0("_nucleos").and_then(|v| v.extract());
        self.guardar(r, Vec::new())
    }

    fn ahora(&mut self) -> f64 {
        let r = reloj(self.py);
        self.guardar(r, f64::NAN)
    }

    fn modelos_en_gpu(&mut self) -> HashMap<String, bool> {
        let r = self.fachada.call_method0("_modelos_en_gpu").and_then(|v| {
            let d = v.cast_into::<PyDict>()?;
            d.iter().map(|(k, v)| Ok((k.extract::<String>()?, v.is_truthy()?))).collect::<PyResult<HashMap<_, _>>>()
        });
        self.guardar(r, HashMap::new())
    }

    fn ram_en_eficientes(&mut self) -> bool {
        let r = self.fachada.getattr("ram_en_eficientes").and_then(|f| f.call0()).and_then(|v| v.is_truthy());
        self.guardar(r, false)
    }

    fn afinidad_propia(&mut self) -> Vec<i64> {
        match self.sistema.clone() {
            None => ritmo::afinidad_propia(),
            Some(s) => {
                let r = s.call_method0("afinidad_propia").and_then(|v| v.extract::<Vec<i64>>()).map(|mut v| {
                    v.sort();
                    v
                });
                self.guardar(r, Vec::new())
            }
        }
    }

    fn uid(&mut self) -> Option<u32> {
        match self.sistema.clone() {
            None => Some(SistemaReal::uid()),
            Some(s) => {
                let r = s.call_method0("uid").and_then(|v| v.extract::<Option<u32>>());
                self.guardar(r, None)
            }
        }
    }

    fn procesos(&mut self) -> Vec<ProcesoCpu> {
        match self.sistema.clone() {
            None => SistemaReal::procesos(),
            Some(s) => {
                let r = s.call_method0("procesos").and_then(|v| {
                    v.extract::<Vec<(i32, Vec<String>, Option<u32>)>>().map(|l| {
                        l.into_iter().map(|(pid, cmdline, uid)| ProcesoCpu { pid, cmdline, uid }).collect()
                    })
                });
                self.guardar(r, Vec::new())
            }
        }
    }

    fn hilos(&mut self, pid: i32) -> Option<Vec<i32>> {
        match self.sistema.clone() {
            None => SistemaReal::hilos(pid),
            Some(s) => s.call_method1("hilos", (pid,)).and_then(|v| v.extract::<Vec<i32>>()).ok(),
        }
    }

    fn fijar(&mut self, pid: i32, nucleos: &[i64]) -> bool {
        match self.sistema.clone() {
            None => ritmo::fijar_afinidad(pid, nucleos).is_ok(),
            Some(s) => s.call_method1("fijar", (pid, nucleos.to_vec())).is_ok(),
        }
    }

    fn pids(&mut self) -> HashSet<i32> {
        match self.sistema.clone() {
            None => ritmo::pids(),
            Some(s) => {
                let r = s.call_method0("pids").and_then(|v| v.try_iter()?.map(|x| x?.extract::<i32>()).collect());
                self.guardar(r, HashSet::new())
            }
        }
    }
}

/// El núcleo del `FijadorCPU` de Python: lo que ya se fijó, los blobs de cada modelo y cuándo se miró
#[pyclass(name = "FijadorCPU", frozen)]
pub struct FijadorPy {
    inner: Mutex<FijadorCpu>,
}

#[pymethods]
impl FijadorPy {
    #[new]
    fn new(url: &str) -> Self {
        FijadorPy { inner: Mutex::new(FijadorCpu::new(url)) }
    }

    /// blob de pesos → True si el modelo está entero en la VRAM (pregunta a Ollama)
    fn modelos_en_gpu(&self, py: Python<'_>) -> HashMap<String, bool> {
        py.detach(|| self.inner.lock().unwrap_or_else(|e| e.into_inner()).modelos_en_gpu())
    }

    /// `aplicar(forzar)` con el mundo que da la fachada de Python
    fn aplicar<'py>(&self, py: Python<'py>, fachada: &Bound<'py, PyAny>, forzar: bool) -> PyResult<Bound<'py, PyDict>> {
        let sistema = fachada.getattr("_sistema")?;
        let sistema = if sistema.is_none() { None } else { Some(sistema) };
        let mut mundo = MundoPython { py, fachada, sistema, error: None };
        let r = self.inner.lock().unwrap_or_else(|e| e.into_inner()).aplicar(&mut mundo, forzar);
        if let Some(e) = mundo.error {
            return Err(e);
        }
        mapa_a_python(py, &r)
    }

    /// Devuelve todos los núcleos a los procesos que se habían fijado
    fn soltar(&self) {
        self.inner.lock().unwrap_or_else(|e| e.into_inner()).soltar();
    }
}

#[pyfunction]
fn nucleos_eficientes() -> Vec<i64> {
    ritmo::nucleos_eficientes()
}

#[pyfunction]
fn leer_lista_cpus(texto: &str) -> PyResult<Vec<i64>> {
    ritmo::leer_lista_cpus(texto).ok_or_else(|| PyValueError::new_err(format!("lista de núcleos inválida: {texto:?}")))
}

/// El proceso y todos sus hilos a esos núcleos
#[pyfunction]
fn fijar_proceso(pid: i32, nucleos: Vec<i64>) -> bool {
    ritmo::fijar_proceso(pid, &nucleos)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("AJUSTES_POR_DEFECTO", mapa_a_python(py, &ritmo::ajustes_por_defecto())?)?;
    m.add("BANDA_C", ritmo::BANDA_C)?;
    m.add("REPOSO_S", ritmo::REPOSO_S)?;
    m.add("PAUSA_MAXIMA_S", ritmo::PAUSA_MAXIMA_S)?;
    m.add("MOTOR_MOE", ritmo::MOTOR_MOE)?;
    m.add_class::<RitmoPy>()?;
    m.add_class::<FijadorPy>()?;
    m.add_function(wrap_pyfunction!(nucleos_eficientes, m)?)?;
    m.add_function(wrap_pyfunction!(leer_lista_cpus, m)?)?;
    m.add_function(wrap_pyfunction!(fijar_proceso, m)?)?;
    Ok(())
}
