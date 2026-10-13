//! `prig_nativo`: los subsistemas de Prig ya portados a Rust, para el backend de Python mientras su anfitrión siga
//! allí (docs/plan-prig-rust.md, 4.1). Cada objeto vive una sola vez, dentro del proceso que lo usa.
//!
//! Un submódulo por subsistema: `prig_nativo.frio`, `.sensores`, `.gguf`, `.ficha`, `.perfiles`, `.calculadora`, `.almacen`, `.ritmo`, `.motor_suave`, `.energia`, `.termico`, `.detector`, `.servidor`, `.calibracion`, `.gestor`, `.audio`.

use pyo3::prelude::*;

mod almacen;
mod audio;
mod calculadora;
mod calibracion;
mod detector;
mod energia;
mod ficha;
mod frio;
mod gestor;
mod gguf;
mod motor_suave;
mod perfiles;
mod ritmo;
mod sensores;
mod servidor;
mod termico;
mod valor;

/// La versión de la interfaz que entiende backend/nativo_rust.py (se sube a la vez en los dos lados)
const INTERFAZ: u32 = 13;

#[pymodule]
fn prig_nativo(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("INTERFAZ", INTERFAZ)?;
    valor::submodulo(m, "frio", frio::registrar)?;
    valor::submodulo(m, "sensores", sensores::registrar)?;
    valor::submodulo(m, "gguf", gguf::registrar)?;
    valor::submodulo(m, "ficha", ficha::registrar)?;
    valor::submodulo(m, "perfiles", perfiles::registrar)?;
    valor::submodulo(m, "calculadora", calculadora::registrar)?;
    valor::submodulo(m, "almacen", almacen::registrar)?;
    valor::submodulo(m, "ritmo", ritmo::registrar)?;
    valor::submodulo(m, "motor_suave", motor_suave::registrar)?;
    valor::submodulo(m, "energia", energia::registrar)?;
    valor::submodulo(m, "termico", termico::registrar)?;
    valor::submodulo(m, "detector", detector::registrar)?;
    valor::submodulo(m, "servidor", servidor::registrar)?;
    valor::submodulo(m, "calibracion", calibracion::registrar)?;
    valor::submodulo(m, "gestor", gestor::registrar)?;
    valor::submodulo(m, "audio", audio::registrar)?;
    Ok(())
}
