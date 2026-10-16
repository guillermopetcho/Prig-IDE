//! Los servicios del IDE (prig_plataforma::ide) para `ide_servicios.py`: `prig_nativo.ide`. Sin estado: la carpeta
//! de trabajo, las raíces y la configuración llegan en cada llamada.

use crate::plataforma::{lanzar, ErrorIDE};
use crate::valor::{a_python, de_python, mapa_a_python};
use prig_plataforma::ide as i;
use prig_plataforma::valor::Valor;
use pyo3::prelude::*;
use pyo3::types::PyDict;

fn lista<'py>(py: Python<'py>, v: Vec<Valor>) -> PyResult<Bound<'py, PyAny>> {
    a_python(py, &Valor::Lista(v))
}

#[pyfunction]
#[pyo3(signature = (base, limite = i::MAX_ARCHIVOS))]
fn listar(py: Python<'_>, base: String, limite: usize) -> PyResult<Bound<'_, PyDict>> {
    let m = py.detach(|| i::listar(&base, limite));
    mapa_a_python(py, &m)
}

#[pyfunction]
fn renombrar(py: Python<'_>, ruta: String, destino: String, base: String, raices: Vec<String>) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| i::renombrar(&ruta, &destino, &base, &raices));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn duplicar(py: Python<'_>, ruta: String, base: String, raices: Vec<String>) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| i::duplicar(&ruta, &base, &raices));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
#[pyo3(signature = (base, consulta, regex = false, mayusculas = false, palabra = false, incluir = String::new(), excluir = String::new(), limite = i::MAX_COINCIDENCIAS))]
#[allow(clippy::too_many_arguments)]
fn buscar(
    py: Python<'_>,
    base: String,
    consulta: String,
    regex: bool,
    mayusculas: bool,
    palabra: bool,
    incluir: String,
    excluir: String,
    limite: usize,
) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| i::buscar(&base, &consulta, regex, mayusculas, palabra, &incluir, &excluir, limite));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
#[pyo3(signature = (base, raices, consulta, reemplazo, regex = false, mayusculas = false, palabra = false, incluir = String::new(), excluir = String::new(), solo = None))]
#[allow(clippy::too_many_arguments)]
fn reemplazar(
    py: Python<'_>,
    base: String,
    raices: Vec<String>,
    consulta: String,
    reemplazo: String,
    regex: bool,
    mayusculas: bool,
    palabra: bool,
    incluir: String,
    excluir: String,
    solo: Option<Vec<String>>,
) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| {
        i::reemplazar(&base, &raices, &consulta, &reemplazo, regex, mayusculas, palabra, &incluir, &excluir, solo.as_deref())
    });
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn recientes(py: Python<'_>, config: String, base: String) -> PyResult<Bound<'_, PyAny>> {
    let r = py.detach(|| i::recientes(&config, &base));
    lista(py, r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn anotar_reciente(py: Python<'_>, config: String, ruta: &Bound<'_, PyAny>) -> PyResult<()> {
    let ruta = de_python(ruta)?;
    py.detach(|| i::anotar_reciente(&config, &ruta)).map_err(|e| lanzar(py, e))
}

#[pyfunction]
fn olvidar_recientes(py: Python<'_>, config: String) -> PyResult<()> {
    py.detach(|| i::olvidar_recientes(&config)).map_err(|e| lanzar(py, e))
}

#[pyfunction]
fn proyectos_guardados(py: Python<'_>, config: String, base: String) -> PyResult<Bound<'_, PyAny>> {
    let r = py.detach(|| i::proyectos_guardados(&config, &base));
    lista(py, r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
#[pyo3(signature = (config, ruta, nombre = None, origen = None))]
fn guardar_proyecto<'py>(
    py: Python<'py>,
    config: String,
    ruta: String,
    nombre: Option<String>,
    origen: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyDict>> {
    let origen = match origen {
        Some(o) => de_python(o)?,
        None => Valor::Texto("biblioteca".into()),
    };
    let r = py.detach(|| i::guardar_proyecto(&config, &ruta, nombre.as_deref(), &origen));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
fn eliminar_proyecto(py: Python<'_>, config: String, ruta: String) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| i::eliminar_proyecto(&config, &ruta));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

#[pyfunction]
#[pyo3(signature = (ruta, base))]
fn listar_directorios(py: Python<'_>, ruta: Option<String>, base: String) -> PyResult<Bound<'_, PyDict>> {
    let m = py.detach(|| i::listar_directorios(ruta.as_deref(), &base));
    mapa_a_python(py, &m)
}

#[pyfunction]
fn mostrar_en_sistema(py: Python<'_>, ruta: String, base: String, raices: Vec<String>) -> PyResult<Bound<'_, PyDict>> {
    let r = py.detach(|| i::mostrar_en_sistema(&ruta, &base, &raices));
    mapa_a_python(py, &r.map_err(|e| lanzar(py, e))?)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("ErrorIDE", py.get_type::<ErrorIDE>())?;
    m.add("IGNORADAS", i::IGNORADAS.to_vec())?;
    m.add("MAX_ARCHIVOS", i::MAX_ARCHIVOS)?;
    m.add("MAX_BYTES_BUSQUEDA", i::MAX_BYTES_BUSQUEDA)?;
    m.add("MAX_COINCIDENCIAS", i::MAX_COINCIDENCIAS)?;
    m.add("MAX_RECIENTES", i::MAX_RECIENTES)?;
    m.add_function(wrap_pyfunction!(listar, m)?)?;
    m.add_function(wrap_pyfunction!(renombrar, m)?)?;
    m.add_function(wrap_pyfunction!(duplicar, m)?)?;
    m.add_function(wrap_pyfunction!(buscar, m)?)?;
    m.add_function(wrap_pyfunction!(reemplazar, m)?)?;
    m.add_function(wrap_pyfunction!(recientes, m)?)?;
    m.add_function(wrap_pyfunction!(anotar_reciente, m)?)?;
    m.add_function(wrap_pyfunction!(olvidar_recientes, m)?)?;
    m.add_function(wrap_pyfunction!(proyectos_guardados, m)?)?;
    m.add_function(wrap_pyfunction!(guardar_proyecto, m)?)?;
    m.add_function(wrap_pyfunction!(eliminar_proyecto, m)?)?;
    m.add_function(wrap_pyfunction!(listar_directorios, m)?)?;
    m.add_function(wrap_pyfunction!(mostrar_en_sistema, m)?)?;
    Ok(())
}
