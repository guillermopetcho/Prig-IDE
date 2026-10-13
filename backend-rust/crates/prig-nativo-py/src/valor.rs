//! `Valor` (prig_recursos::valor) ↔ objetos de Python: los diccionarios que van y vienen entre el backend y Rust

use prig_recursos::valor::{Mapa, Valor};
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

pub fn a_python<'py>(py: Python<'py>, v: &Valor) -> PyResult<Bound<'py, PyAny>> {
    Ok(match v {
        Valor::Nulo => py.None().into_bound(py),
        Valor::Bool(b) => PyBool::new(py, *b).to_owned().into_any(),
        Valor::Entero(n) => n.into_pyobject(py)?.into_any(),
        Valor::Real(x) => PyFloat::new(py, *x).into_any(),
        Valor::Texto(t) => PyString::new(py, t).into_any(),
        Valor::Lista(l) => {
            let lista = PyList::empty(py);
            for x in l {
                lista.append(a_python(py, x)?)?;
            }
            lista.into_any()
        }
        Valor::Mapa(m) => mapa_a_python(py, m)?.into_any(),
    })
}

pub fn mapa_a_python<'py>(py: Python<'py>, m: &Mapa) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    for (k, v) in m.iter() {
        d.set_item(k, a_python(py, v)?)?;
    }
    Ok(d)
}

pub fn de_python(obj: &Bound<'_, PyAny>) -> PyResult<Valor> {
    if obj.is_none() {
        return Ok(Valor::Nulo);
    }
    if let Ok(b) = obj.cast::<PyBool>() {
        return Ok(Valor::Bool(b.is_true()));
    }
    if obj.is_instance_of::<PyInt>() {
        return Ok(match obj.extract::<i128>() {
            Ok(n) => Valor::Entero(n),
            Err(_) => Valor::Real(obj.extract::<f64>()?), // un entero más grande que i128
        });
    }
    if let Ok(x) = obj.cast::<PyFloat>() {
        return Ok(Valor::Real(x.value()));
    }
    if let Ok(t) = obj.cast::<PyString>() {
        return Ok(Valor::Texto(t.to_str()?.to_string()));
    }
    if let Ok(d) = obj.cast::<PyDict>() {
        return Ok(Valor::Mapa(mapa_de_dict(d)?));
    }
    if obj.is_instance_of::<PyList>() || obj.is_instance_of::<PyTuple>() {
        return Ok(Valor::Lista(obj.try_iter()?.map(|x| de_python(&x?)).collect::<PyResult<_>>()?));
    }
    // Números de otras bibliotecas (numpy): por __index__ o __float__
    if let Ok(n) = obj.extract::<i128>() {
        return Ok(Valor::Entero(n));
    }
    if let Ok(x) = obj.extract::<f64>() {
        return Ok(Valor::Real(x));
    }
    Err(PyTypeError::new_err(format!("valor no admitido: {}", obj.get_type().name()?)))
}

fn mapa_de_dict(d: &Bound<'_, PyDict>) -> PyResult<Mapa> {
    let mut m = Mapa::new();
    for (k, v) in d.iter() {
        let clave = match k.cast::<PyString>() {
            Ok(s) => s.to_str()?.to_string(),
            Err(_) => k.str()?.to_str()?.to_string(),
        };
        m.poner(clave, de_python(&v)?);
    }
    Ok(m)
}

/// Un diccionario de Python (TypeError si no lo es)
pub fn mapa_de_python(obj: &Bound<'_, PyAny>) -> PyResult<Mapa> {
    match obj.cast::<PyDict>() {
        Ok(d) => mapa_de_dict(d),
        Err(_) => Err(PyTypeError::new_err(format!("se esperaba un dict, no {}", obj.get_type().name()?))),
    }
}

/// Un submódulo de `prig_nativo`, también importable como `prig_nativo.<nombre>`
pub fn submodulo<'py>(
    padre: &Bound<'py, PyModule>,
    nombre: &str,
    registrar: impl FnOnce(&Bound<'py, PyModule>) -> PyResult<()>,
) -> PyResult<()> {
    let py = padre.py();
    let sub = PyModule::new(py, nombre)?;
    registrar(&sub)?;
    padre.add_submodule(&sub)?;
    py.import("sys")?.getattr("modules")?.set_item(format!("prig_nativo.{nombre}"), &sub)?;
    Ok(())
}
