//! Calculadora (prig_recursos::calculadora) para `backend/recursos/calculadora.py`

use crate::valor::{a_python, mapa_a_python, mapa_de_python};
use prig_recursos::calculadora::{self as calc, Maquina};
use prig_recursos::valor::Mapa;
use pyo3::exceptions::PyKeyError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

/// `calculadora.Maquina(radiografia, calibracion=None)`: la máquina ya destilada para la calculadora
#[pyclass(name = "Maquina", frozen)]
pub struct MaquinaPy {
    inner: Maquina,
    radiografia: Py<PyAny>,
}

#[pymethods]
impl MaquinaPy {
    #[new]
    #[pyo3(signature = (radiografia, calibracion = None))]
    fn new(radiografia: &Bound<'_, PyAny>, calibracion: Option<&Bound<'_, PyAny>>) -> PyResult<Self> {
        let rad = mapa_de_python(radiografia)?;
        let cal = match calibracion {
            Some(c) if c.is_truthy()? => Some(mapa_de_python(c)?),
            _ => None,
        };
        Ok(MaquinaPy { inner: Maquina::new(&rad, cal.as_ref()), radiografia: radiografia.clone().unbind() })
    }

    /// La radiografía que se le dio (el mismo objeto)
    #[getter]
    fn radiografia(&self, py: Python<'_>) -> Py<PyAny> {
        self.radiografia.clone_ref(py)
    }
    #[getter]
    fn hay_gpu(&self) -> bool {
        self.inner.hay_gpu
    }
    #[getter]
    fn gpu_nombre(&self) -> &str {
        &self.inner.gpu_nombre
    }
    #[getter]
    fn unificada(&self) -> bool {
        self.inner.unificada
    }
    #[getter]
    fn vram_total(&self) -> f64 {
        self.inner.vram_total
    }
    #[getter]
    fn vram_libre(&self) -> f64 {
        self.inner.vram_libre
    }
    #[getter]
    fn ram_disponible(&self) -> f64 {
        self.inner.ram_disponible
    }
    #[getter]
    fn ram_total(&self) -> f64 {
        self.inner.ram_total
    }
    #[getter]
    fn nucleos<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.nucleos)
    }
    #[getter]
    fn flash_attention(&self) -> bool {
        self.inner.flash_attention
    }
    #[getter]
    fn presupuesto_gpu(&self) -> f64 {
        self.inner.presupuesto_gpu
    }
    #[getter]
    fn origen_presupuesto(&self) -> &str {
        self.inner.origen_presupuesto
    }
    #[getter]
    fn vram_parcial(&self) -> f64 {
        self.inner.vram_parcial
    }
    #[getter]
    fn ancho_gpu(&self) -> f64 {
        self.inner.ancho_gpu
    }
    #[getter]
    fn origen_ancho_gpu(&self) -> &str {
        self.inner.origen_ancho_gpu
    }
    #[getter]
    fn ancho_cpu(&self) -> f64 {
        self.inner.ancho_cpu
    }
    #[getter]
    fn origen_ancho_cpu(&self) -> &str {
        self.inner.origen_ancho_cpu
    }
    #[getter]
    fn overhead_entero(&self) -> f64 {
        self.inner.overhead_entero
    }
    #[getter]
    fn overhead_parcial(&self) -> f64 {
        self.inner.overhead_parcial
    }
    /// Lo que el servidor de Ollama aplica de verdad: {kv, paralelo, flash_attention, max_modelos}
    #[getter]
    fn servidor<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.servidor.mapa())
    }
    #[getter]
    fn calibrada(&self) -> bool {
        self.inner.calibrada()
    }

    fn resumen<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.resumen())
    }
}

impl MaquinaPy {
    /// La máquina de Rust que hay dentro
    pub fn nucleo(&self) -> &Maquina {
        &self.inner
    }
}

/// La ficha como Mapa, con las claves que Python lee con `ficha[...]` (KeyError si faltan)
fn ficha_de(ficha: &Bound<'_, PyAny>) -> PyResult<Mapa> {
    let f = mapa_de_python(ficha)?;
    for clave in ["bytes_peso", "nombre"] {
        if !f.contiene(clave) {
            return Err(PyKeyError::new_err(clave));
        }
    }
    Ok(f)
}

#[pyfunction]
#[pyo3(signature = (ficha, maq, ctx, paralelo = 1, kv = "f16"))]
fn estimar<'py>(
    py: Python<'py>,
    ficha: &Bound<'py, PyAny>,
    maq: &MaquinaPy,
    ctx: i64,
    paralelo: i64,
    kv: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let f = mapa_de_python(ficha)?;
    if !f.contiene("bytes_peso") {
        return Err(PyKeyError::new_err("bytes_peso"));
    }
    mapa_a_python(py, &calc::estimar(&f, &maq.inner, ctx, paralelo, kv).mapa())
}

#[pyfunction]
#[pyo3(signature = (ficha, maq, nombre_perfil, tirador = "equilibrado"))]
fn recomendar<'py>(
    py: Python<'py>,
    ficha: &Bound<'py, PyAny>,
    maq: &MaquinaPy,
    nombre_perfil: &str,
    tirador: &str,
) -> PyResult<Bound<'py, PyDict>> {
    prig_recursos::perfiles::perfil(nombre_perfil).map_err(PyKeyError::new_err)?;
    let f = ficha_de(ficha)?;
    let r = calc::recomendar(&f, &maq.inner, nombre_perfil, tirador).map_err(PyKeyError::new_err)?;
    mapa_a_python(py, &r)
}

#[pyfunction]
#[pyo3(signature = (fichas, maq, nombre_perfil, tirador = "equilibrado", medidas = None))]
fn elegir_modelo<'py>(
    py: Python<'py>,
    fichas: Vec<Bound<'py, PyAny>>,
    maq: &MaquinaPy,
    nombre_perfil: &str,
    tirador: &str,
    medidas: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyList>> {
    prig_recursos::perfiles::perfil(nombre_perfil).map_err(PyKeyError::new_err)?;
    let mut lista = Vec::with_capacity(fichas.len());
    for f in &fichas {
        let m = mapa_de_python(f)?;
        lista.push(if m.verdad("embedding") { m } else { ficha_de(f)? });
    }
    let medidas = match medidas {
        Some(m) if m.is_truthy()? => mapa_de_python(m)?,
        _ => Mapa::new(),
    };
    let filas = calc::elegir_modelo(&lista, &maq.inner, nombre_perfil, tirador, &medidas).map_err(PyKeyError::new_err)?;
    let salida = PyList::empty(py);
    for f in &filas {
        salida.append(mapa_a_python(py, f)?)?;
    }
    Ok(salida)
}

#[pyfunction]
fn calidad_esperada(ficha: &Bound<'_, PyAny>) -> PyResult<f64> {
    Ok(calc::calidad_esperada(&mapa_de_python(ficha)?))
}

/// Tokens por segundo sumando todas las ranuras de una estimación
#[pyfunction]
fn rendimiento(e: &Bound<'_, PyAny>) -> PyResult<f64> {
    let tok_s: f64 = e.get_item("tok_s")?.extract()?;
    let paralelo: i64 = e.get_item("paralelo")?.extract()?;
    Ok(calc::rendimiento(tok_s, paralelo))
}

#[pyfunction]
fn penalizacion_contexto(ctx: f64) -> f64 {
    calc::penalizacion_contexto(ctx)
}

#[pyfunction]
fn servidor_efectivo<'py>(py: Python<'py>, entorno: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &calc::servidor_efectivo(&mapa_de_python(entorno)?).mapa())
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("GB", calc::GB)?;
    m.add("OVERHEAD_ENTERO", calc::OVERHEAD_ENTERO)?;
    m.add("OVERHEAD_PARCIAL", calc::OVERHEAD_PARCIAL)?;
    m.add("MARGEN_RAM", calc::MARGEN_RAM)?;
    m.add("FACTOR_BANCO_RAM", calc::FACTOR_BANCO_RAM)?;
    m.add("EFICIENCIA_GPU", calc::EFICIENCIA_GPU)?;
    m.add("LATENCIA_CAPA_S", calc::LATENCIA_CAPA_S)?;
    m.add("GANANCIA_RANURA", calc::GANANCIA_RANURA)?;
    let ancho = PyDict::new(py);
    for (k, v) in calc::ANCHO_GPU {
        ancho.set_item(k, v)?;
    }
    m.add("ANCHO_GPU", ancho)?;
    let veredictos = PyDict::new(py);
    for (k, v) in calc::VEREDICTOS {
        veredictos.set_item(k, v)?;
    }
    m.add("VEREDICTOS", veredictos)?;
    m.add_class::<MaquinaPy>()?;
    m.add_function(wrap_pyfunction!(estimar, m)?)?;
    m.add_function(wrap_pyfunction!(recomendar, m)?)?;
    m.add_function(wrap_pyfunction!(elegir_modelo, m)?)?;
    m.add_function(wrap_pyfunction!(calidad_esperada, m)?)?;
    m.add_function(wrap_pyfunction!(rendimiento, m)?)?;
    m.add_function(wrap_pyfunction!(penalizacion_contexto, m)?)?;
    m.add_function(wrap_pyfunction!(servidor_efectivo, m)?)?;
    Ok(())
}
