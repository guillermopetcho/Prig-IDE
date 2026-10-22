//! Las opciones de los modelos (prig_modelos::opciones) para `ollama_opciones.py`: `prig_nativo.opciones`

use crate::plataforma::lanzar_con;
use crate::valor::{a_python, de_python, mapa_a_python, mapa_de_python};
use prig_modelos::opciones as o;
use prig_recursos::valor::Valor;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pyo3::create_exception!(prig_nativo, ErrorConfig, pyo3::exceptions::PyValueError, "Un valor de configuración de los modelos no válido");

fn lanzar(py: Python<'_>, e: prig_plataforma::py::ErrorPy) -> PyErr {
    lanzar_con(py, e, ErrorConfig::new_err)
}

#[pyfunction]
fn validar<'py>(py: Python<'py>, valores: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let v = de_python(valores)?;
    mapa_a_python(py, &o::validar(&v).map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn separar<'py>(py: Python<'py>, valores: &Bound<'py, PyAny>) -> PyResult<(Bound<'py, PyDict>, Bound<'py, PyDict>)> {
    let (a, b) = o::separar(&mapa_de_python(valores)?);
    Ok((mapa_a_python(py, &a)?, mapa_a_python(py, &b)?))
}

#[pyfunction]
fn limpiar_para_ollama<'py>(py: Python<'py>, opciones: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let m = if opciones.is_truthy()? { mapa_de_python(opciones)? } else { Default::default() };
    mapa_a_python(py, &o::limpiar_para_ollama(&m))
}

#[pyfunction]
#[pyo3(signature = (num_gpus = 1))]
fn catalogo(py: Python<'_>, num_gpus: i64) -> PyResult<Bound<'_, PyDict>> {
    mapa_a_python(py, &o::catalogo(num_gpus))
}

#[pyfunction]
fn base(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    mapa_a_python(py, o::catalogo_base())
}

#[pyclass(name = "ConfigModelos", frozen)]
pub struct ConfigModelosPy {
    inner: o::ConfigModelos,
}

#[pymethods]
impl ConfigModelosPy {
    #[new]
    fn new(py: Python<'_>, ruta: String) -> Self {
        ConfigModelosPy { inner: py.detach(|| o::ConfigModelos::new(&ruta)) }
    }

    #[getter]
    fn ruta(&self) -> String {
        self.inner.ruta.clone()
    }

    #[pyo3(signature = (capa, modelo = None, uso = None))]
    fn capa<'py>(&self, py: Python<'py>, capa: &str, modelo: Option<&str>, uso: Option<&str>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.capa(capa, modelo, uso).map_err(|e| lanzar(py, e))?)
    }

    #[pyo3(signature = (capa, valores, modelo = None, uso = None, reemplazar = false))]
    fn fijar<'py>(
        &self,
        py: Python<'py>,
        capa: &str,
        valores: &Bound<'py, PyAny>,
        modelo: Option<&str>,
        uso: Option<&str>,
        reemplazar: bool,
    ) -> PyResult<Bound<'py, PyDict>> {
        let v = mapa_de_python(valores)?;
        mapa_a_python(py, &self.inner.fijar(capa, &v, modelo, uso, reemplazar).map_err(|e| lanzar(py, e))?)
    }

    fn embeddings<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.embeddings())
    }

    #[pyo3(signature = (modelo = None, dimensiones = None, truncar = None, quitar_dimensiones = false))]
    fn fijar_embeddings<'py>(
        &self,
        py: Python<'py>,
        modelo: Option<&Bound<'py, PyAny>>,
        dimensiones: Option<&Bound<'py, PyAny>>,
        truncar: Option<&Bound<'py, PyAny>>,
        quitar_dimensiones: bool,
    ) -> PyResult<Bound<'py, PyDict>> {
        let conv = |x: Option<&Bound<'py, PyAny>>| -> PyResult<Option<Valor>> {
            match x {
                Some(v) if !v.is_none() => Ok(Some(de_python(v)?)),
                _ => Ok(None),
            }
        };
        let (m, d, t) = (conv(modelo)?, conv(dimensiones)?, conv(truncar)?);
        let r = self.inner.fijar_embeddings(m.as_ref(), d.as_ref(), t.as_ref(), quitar_dimensiones);
        mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
    }

    fn renombrar_modelo(&self, py: Python<'_>, anterior: &str, nuevo: &str) -> PyResult<()> {
        self.inner.renombrar_modelo(anterior, nuevo).map_err(|e| lanzar(py, e))
    }

    #[pyo3(signature = (modelo, uso = None))]
    fn resolver<'py>(&self, py: Python<'py>, modelo: Option<&str>, uso: Option<&Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyDict>> {
        // `uso in USOS`: solo un texto puede estar
        let uso: Option<String> = match uso {
            Some(u) => u.extract::<String>().ok(),
            None => None,
        };
        mapa_a_python(py, &self.inner.resolver(modelo, uso.as_deref()))
    }

    fn todo<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.todo())
    }
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("ErrorConfig", py.get_type::<ErrorConfig>())?;
    m.add("CAPAS", o::CAPAS.to_vec())?;
    m.add_function(wrap_pyfunction!(validar, m)?)?;
    m.add_function(wrap_pyfunction!(separar, m)?)?;
    m.add_function(wrap_pyfunction!(limpiar_para_ollama, m)?)?;
    m.add_function(wrap_pyfunction!(catalogo, m)?)?;
    m.add_function(wrap_pyfunction!(base, m)?)?;
    m.add_class::<ConfigModelosPy>()?;
    let _ = a_python;
    Ok(())
}
