//! Los archivos (prig_plataforma::archivos y ::espacio) para `file_manager.py`: `prig_nativo.archivos`. Sin estado:
//! la carpeta de trabajo y las raíces permitidas llegan en cada llamada.

use crate::plataforma::imprimir;
use crate::valor::{a_python, mapa_a_python};
use prig_plataforma::{archivos as a, espacio as e};
use pyo3::exceptions::PyPermissionError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};

#[pyfunction]
fn permitida(py: Python<'_>, abs_path: String, raices: Vec<String>) -> bool {
    py.detach(|| a::permitida(&abs_path, &raices))
}

#[pyfunction]
fn resolver(py: Python<'_>, ruta: String, base: String, raices: Vec<String>) -> PyResult<String> {
    py.detach(|| a::resolver(&ruta, &base, &raices)).map_err(PyPermissionError::new_err)
}

#[pyfunction]
#[pyo3(signature = (ruta, base, raices, max_depth = 6, current_depth = 0))]
fn arbol<'py>(
    py: Python<'py>,
    ruta: Option<String>,
    base: String,
    raices: Vec<String>,
    max_depth: i64,
    current_depth: i64,
) -> PyResult<Bound<'py, PyAny>> {
    let mut avisos = Vec::new();
    let v = py.detach(|| a::arbol(ruta.as_deref(), &base, &raices, max_depth, current_depth, &mut avisos));
    imprimir(py, avisos)?;
    a_python(py, &prig_plataforma::valor::Valor::Lista(v))
}

#[pyfunction]
fn leer(py: Python<'_>, ruta: String, base: String, raices: Vec<String>) -> PyResult<Bound<'_, PyDict>> {
    let m = py.detach(|| a::leer(&ruta, &base, &raices));
    mapa_a_python(py, &m)
}

#[pyfunction]
fn cuaderno(py: Python<'_>, json_str: String, ruta: String) -> PyResult<Bound<'_, PyDict>> {
    let m = py.detach(|| a::cuaderno(&json_str, &ruta));
    mapa_a_python(py, &m)
}

#[pyfunction]
fn escribir<'py>(
    py: Python<'py>,
    ruta: String,
    contenido: &Bound<'py, PyAny>,
    base: String,
    raices: Vec<String>,
) -> PyResult<Bound<'py, PyDict>> {
    // Un texto que no se puede pasar a UTF-8 (un sustituto suelto) da el mismo error que daba `f.write`, pero solo
    // después de comprobar la ruta y crear la carpeta, como en Python
    let texto: Result<String, String> = match contenido.cast::<PyString>() {
        Ok(s) => match s.to_str() {
            Ok(t) => Ok(t.to_string()),
            Err(err) => Err(err.value(py).str()?.to_string()),
        },
        // (como Python: «not None» y no «not NoneType»)
        Err(_) if contenido.is_none() => Err("write() argument must be str, not None".into()),
        Err(_) => Err(format!("write() argument must be str, not {}", contenido.get_type().name()?)),
    };
    let m = match texto {
        Ok(t) => py.detach(|| a::escribir(&ruta, &t, &base, &raices)),
        Err(err) => {
            let abs = py.detach(|| a::resolver(&ruta, &base, &raices));
            match abs {
                Err(e) => prig_plataforma::valor::Mapa::new().con("error", e),
                Ok(abs) => match prig_plataforma::py::makedirs(&prig_plataforma::py::dirname(&abs)) {
                    Err(e) => prig_plataforma::valor::Mapa::new().con("error", e),
                    Ok(()) => {
                        // `open(abs, "w")` ya había vaciado el archivo
                        match prig_plataforma::py::escribir_texto(&abs, "") {
                            Err(e) => prig_plataforma::valor::Mapa::new().con("error", e),
                            Ok(()) => prig_plataforma::valor::Mapa::new().con("error", err),
                        }
                    }
                },
            }
        }
    };
    mapa_a_python(py, &m)
}

#[pyfunction]
#[pyo3(signature = (ruta, carpeta, base, raices))]
fn crear(py: Python<'_>, ruta: String, carpeta: bool, base: String, raices: Vec<String>) -> PyResult<Bound<'_, PyDict>> {
    let m = py.detach(|| a::crear(&ruta, carpeta, &base, &raices));
    mapa_a_python(py, &m)
}

#[pyfunction]
fn borrar(py: Python<'_>, ruta: String, base: String, raices: Vec<String>) -> PyResult<Bound<'_, PyDict>> {
    let m = py.detach(|| a::borrar(&ruta, &base, &raices));
    mapa_a_python(py, &m)
}

#[pyfunction]
fn cargar_ultima(py: Python<'_>, config: String) -> String {
    py.detach(|| e::cargar_ultima(&config))
}

#[pyfunction]
fn leer_config(py: Python<'_>, config: String) -> PyResult<Bound<'_, PyDict>> {
    let m = py.detach(|| e::leer_config(&config));
    mapa_a_python(py, &m)
}

#[pyfunction]
#[pyo3(signature = (config, clave, valor = None))]
fn guardar_clave(py: Python<'_>, config: String, clave: String, valor: Option<String>) {
    py.detach(|| e::guardar_clave(&config, &clave, valor.as_deref()))
}

/// `(ruta absoluta o None, respuesta)`
#[pyfunction]
fn carpeta(py: Python<'_>, ruta: String) -> PyResult<(Option<String>, Bound<'_, PyDict>)> {
    match py.detach(|| e::carpeta(&ruta)) {
        Ok((abs, r)) => Ok((Some(abs), mapa_a_python(py, &r)?)),
        Err(r) => Ok((None, mapa_a_python(py, &r)?)),
    }
}

#[pyfunction]
#[pyo3(signature = (abs = None))]
fn respuesta_segunda(py: Python<'_>, abs: Option<String>) -> PyResult<Bound<'_, PyDict>> {
    mapa_a_python(py, &e::respuesta_segunda(abs.as_deref()))
}

#[pyfunction]
fn elegir_con_zenity(py: Python<'_>, titulo: String) -> Option<String> {
    py.detach(|| e::elegir_con_zenity(&titulo))
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("IGNORADAS", a::IGNORADAS.to_vec())?;
    m.add_function(wrap_pyfunction!(permitida, m)?)?;
    m.add_function(wrap_pyfunction!(resolver, m)?)?;
    m.add_function(wrap_pyfunction!(arbol, m)?)?;
    m.add_function(wrap_pyfunction!(leer, m)?)?;
    m.add_function(wrap_pyfunction!(cuaderno, m)?)?;
    m.add_function(wrap_pyfunction!(escribir, m)?)?;
    m.add_function(wrap_pyfunction!(crear, m)?)?;
    m.add_function(wrap_pyfunction!(borrar, m)?)?;
    m.add_function(wrap_pyfunction!(cargar_ultima, m)?)?;
    m.add_function(wrap_pyfunction!(leer_config, m)?)?;
    m.add_function(wrap_pyfunction!(guardar_clave, m)?)?;
    m.add_function(wrap_pyfunction!(carpeta, m)?)?;
    m.add_function(wrap_pyfunction!(respuesta_segunda, m)?)?;
    m.add_function(wrap_pyfunction!(elegir_con_zenity, m)?)?;
    Ok(())
}
