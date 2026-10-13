//! Almacén de recursos (prig_recursos::almacen) para `backend/recursos/almacen.py`

use crate::valor::{a_python, de_python, mapa_a_python, mapa_de_python};
use prig_recursos::almacen::Almacen;
use prig_recursos::json;
use prig_recursos::valor::Valor;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::path::PathBuf;

/// El almacén de un archivo. `Almacen(ruta)`: la ruta la decide Python (`ruta_por_defecto()`).
#[pyclass(name = "Almacen", frozen)]
pub struct AlmacenPy {
    inner: Almacen,
    ruta: String,
}

fn opcional<'py>(py: Python<'py>, v: Option<Valor>) -> PyResult<Bound<'py, PyAny>> {
    match v {
        Some(v) => a_python(py, &v),
        None => Ok(py.None().into_bound(py)),
    }
}

fn datos(v: Option<&Bound<'_, PyAny>>) -> PyResult<Option<Valor>> {
    v.filter(|v| !v.is_none()).map(de_python).transpose()
}

#[pymethods]
impl AlmacenPy {
    #[new]
    fn new(py: Python<'_>, ruta: String) -> Self {
        let inner = py.detach(|| Almacen::abrir(&PathBuf::from(&ruta)));
        AlmacenPy { inner, ruta }
    }

    /// La ruta tal como se dio (texto, como en Python)
    #[getter]
    fn ruta(&self) -> &str {
        &self.ruta
    }

    /// Guarda la radiografía y dice si la máquina cambió: {cambio, anterior, calibrada}
    fn registrar_radiografia<'py>(&self, py: Python<'py>, radiografia: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
        let rad = mapa_de_python(radiografia)?;
        let r = py.detach(|| self.inner.registrar_radiografia(rad))?;
        mapa_a_python(py, &r)
    }

    #[pyo3(signature = (huella = None))]
    fn calibracion<'py>(&self, py: Python<'py>, huella: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
        opcional(py, self.inner.calibracion(huella).map(Valor::Mapa))
    }

    #[pyo3(signature = (huella, valores, detalle = None))]
    fn guardar_calibracion(
        &self,
        py: Python<'_>,
        huella: &Bound<'_, PyAny>,
        valores: &Bound<'_, PyAny>,
        detalle: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<()> {
        let valores = mapa_de_python(valores)?;
        let detalle = datos(detalle)?;
        let huella = de_python(huella)?;
        Ok(py.detach(|| self.inner.guardar_calibracion(&huella, &valores, detalle.as_ref()))?)
    }

    #[pyo3(signature = (huella = None))]
    fn olvidar_calibracion(&self, py: Python<'_>, huella: Option<String>) -> PyResult<()> {
        Ok(py.detach(|| self.inner.olvidar_calibracion(huella.as_deref()))?)
    }

    #[staticmethod]
    fn clave_prueba(modelo: &str, perfil: &str) -> String {
        Almacen::clave_prueba(modelo, perfil)
    }

    fn guardar_prueba(
        &self,
        py: Python<'_>,
        huella: &Bound<'_, PyAny>,
        modelo: &str,
        perfil: &str,
        resultado: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let resultado = mapa_de_python(resultado)?;
        let huella = de_python(huella)?;
        Ok(py.detach(|| self.inner.guardar_prueba(&huella, modelo, perfil, &resultado))?)
    }

    #[pyo3(signature = (huella = None))]
    fn pruebas<'py>(&self, py: Python<'py>, huella: Option<&str>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.pruebas(huella))
    }

    #[pyo3(signature = (modelo, perfil, huella = None))]
    fn prueba<'py>(&self, py: Python<'py>, modelo: &str, perfil: &str, huella: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
        opcional(py, self.inner.prueba(modelo, perfil, huella))
    }

    /// Solo si se midió en ESTA máquina
    fn ultima_buena<'py>(&self, py: Python<'py>, perfil: &str) -> PyResult<Bound<'py, PyAny>> {
        opcional(py, self.inner.ultima_buena(perfil))
    }

    fn registrar_aplicado(
        &self,
        py: Python<'_>,
        perfil: &str,
        modelo: &Bound<'_, PyAny>,
        opciones: &Bound<'_, PyAny>,
        anterior: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let (modelo, opciones, anterior) = (de_python(modelo)?, de_python(opciones)?, de_python(anterior)?);
        Ok(py.detach(|| self.inner.registrar_aplicado(perfil, &modelo, &opciones, &anterior))?)
    }

    fn aplicado<'py>(&self, py: Python<'py>, perfil: &str) -> PyResult<Bound<'py, PyAny>> {
        opcional(py, self.inner.aplicado(perfil))
    }

    /// Devuelve lo que había antes de aplicar y olvida la aplicación
    fn quitar_aplicado<'py>(&self, py: Python<'py>, perfil: &str) -> PyResult<Bound<'py, PyAny>> {
        let a = py.detach(|| self.inner.quitar_aplicado(perfil))?;
        opcional(py, a)
    }

    fn entorno_servidor<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.seccion("entorno_servidor"))
    }

    fn guardar_entorno_servidor(&self, py: Python<'_>, entorno: &Bound<'_, PyAny>) -> PyResult<()> {
        let entorno = mapa_de_python(entorno)?;
        Ok(py.detach(|| self.inner.guardar_entorno_servidor(&entorno))?)
    }

    fn termico<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.seccion("termico"))
    }

    #[pyo3(signature = (ajustes, texto = None, datos = None))]
    fn guardar_termico(
        &self,
        py: Python<'_>,
        ajustes: &Bound<'_, PyAny>,
        texto: Option<String>,
        datos: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<()> {
        let ajustes = mapa_de_python(ajustes)?;
        let d = self::datos(datos)?;
        let texto = texto.unwrap_or_default();
        Ok(py.detach(|| self.inner.guardar_seccion("termico", ajustes, Some(("termico", &texto, d))))?)
    }

    fn frio<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.seccion("frio"))
    }

    #[pyo3(signature = (ajustes, texto = None))]
    fn guardar_frio(&self, py: Python<'_>, ajustes: &Bound<'_, PyAny>, texto: Option<String>) -> PyResult<()> {
        let ajustes = mapa_de_python(ajustes)?;
        let texto = texto.unwrap_or_default();
        Ok(py.detach(|| self.inner.guardar_seccion("frio", ajustes, Some(("frio", &texto, None))))?)
    }

    fn ritmo<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        mapa_a_python(py, &self.inner.seccion("ritmo"))
    }

    #[pyo3(signature = (ajustes, texto = None))]
    fn guardar_ritmo(&self, py: Python<'_>, ajustes: &Bound<'_, PyAny>, texto: Option<String>) -> PyResult<()> {
        let ajustes = mapa_de_python(ajustes)?;
        let texto = texto.unwrap_or_default();
        Ok(py.detach(|| self.inner.guardar_seccion("ritmo", ajustes, Some(("ritmo", &texto, None))))?)
    }

    /// Apunta un evento sin guardar
    #[pyo3(signature = (tipo, texto, datos = None))]
    fn _evento(&self, tipo: &str, texto: &str, datos: Option<&Bound<'_, PyAny>>) -> PyResult<()> {
        self.inner.apuntar_evento(tipo, texto, self::datos(datos)?);
        Ok(())
    }

    #[pyo3(signature = (tipo, texto, datos = None))]
    fn evento(&self, py: Python<'_>, tipo: &str, texto: &str, datos: Option<&Bound<'_, PyAny>>) -> PyResult<()> {
        let d = self::datos(datos)?;
        Ok(py.detach(|| self.inner.evento(tipo, texto, d))?)
    }

    /// Los últimos `limite`, del más nuevo al más viejo
    #[pyo3(signature = (limite = 50))]
    fn eventos<'py>(&self, py: Python<'py>, limite: i64) -> PyResult<Bound<'py, PyList>> {
        let l = PyList::empty(py);
        for e in self.inner.eventos(limite) {
            l.append(a_python(py, &e)?)?;
        }
        Ok(l)
    }

    #[getter]
    fn huella_actual<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.huella_actual())
    }

    #[getter]
    fn radiografia<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.radiografia())
    }
}

/// `json.loads` de Python, en Rust
#[pyfunction]
fn leer_json<'py>(py: Python<'py>, texto: &str) -> PyResult<Bound<'py, PyAny>> {
    a_python(py, &json::leer(texto).map_err(PyValueError::new_err)?)
}

/// `json.dumps(obj, ensure_ascii=False, indent=sangria)`, en Rust
#[pyfunction]
#[pyo3(signature = (obj, sangria = 1))]
fn escribir_json(obj: &Bound<'_, PyAny>, sangria: usize) -> PyResult<String> {
    Ok(json::escribir(&de_python(obj)?, sangria))
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("VERSION", prig_recursos::almacen::VERSION)?;
    m.add("MAX_HUELLAS", prig_recursos::almacen::MAX_HUELLAS)?;
    m.add("MAX_EVENTOS", prig_recursos::almacen::MAX_EVENTOS)?;
    m.add("MAX_PRUEBAS_POR_HUELLA", prig_recursos::almacen::MAX_PRUEBAS_POR_HUELLA)?;
    m.add_class::<AlmacenPy>()?;
    m.add_function(wrap_pyfunction!(leer_json, m)?)?;
    m.add_function(wrap_pyfunction!(escribir_json, m)?)?;
    Ok(())
}
