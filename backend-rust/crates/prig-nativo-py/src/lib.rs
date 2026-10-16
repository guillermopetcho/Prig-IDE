//! `prig_nativo`: los subsistemas de Prig ya portados a Rust, para el backend de Python mientras su anfitrión siga
//! allí (docs/plan-prig-rust.md, 4.1). Cada objeto vive una sola vez, dentro del proceso que lo usa.
//!
//! Un submódulo por subsistema: `prig_nativo.frio`, `.sensores`, `.gguf`, `.ficha`, `.perfiles`, `.calculadora`, `.almacen`, `.ritmo`, `.motor_suave`, `.energia`, `.termico`, `.detector`, `.servidor`, `.calibracion`, `.gestor`, `.audio`; de la plataforma (F2): `.banderas`, `.perfiles_config`, `.archivos`, `.ide`, `.explorador`, `.inicio`, `.ejecucion`; de los modelos (F3): `.opciones`, `.gestion`, `.buscador`; del motor de IA (F4): `.moe`, `.web`; de la biblioteca (F5): `.pdf`, `.indices`, `.troceado`, `.vectores`, `.documentos` (PDF con Typst), `.referencias`; de aprendizaje y desafíos (F6): `.desafios`; de las integraciones (F7): `.http`.

use pyo3::prelude::*;

mod almacen;
mod gil;
mod archivos;
mod audio;
mod buscador;
mod calculadora;
mod calibracion;
mod detector;
mod ejecucion;
mod energia;
mod explorador;
mod ficha;
mod frio;
mod gestion;
mod gestor;
mod gguf;
mod ide;
mod indices;
mod troceado;
mod vectores;
mod documentos;
mod referencias;
mod desafios;
mod http;
mod inicio;
mod moe;
mod motor_suave;
mod opciones;
mod pdf;
mod perfiles;
mod plataforma;
mod ritmo;
mod sensores;
mod servidor;
mod termico;
mod valor;
mod web;

/// La versión de la interfaz que entiende backend/nativo_rust.py (se sube a la vez en los dos lados)
const INTERFAZ: u32 = 23;

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
    plataforma::registrar(m)?;
    valor::submodulo(m, "archivos", archivos::registrar)?;
    valor::submodulo(m, "ide", ide::registrar)?;
    valor::submodulo(m, "explorador", explorador::registrar)?;
    valor::submodulo(m, "inicio", inicio::registrar)?;
    valor::submodulo(m, "ejecucion", ejecucion::registrar)?;
    valor::submodulo(m, "opciones", opciones::registrar)?;
    valor::submodulo(m, "gestion", gestion::registrar)?;
    valor::submodulo(m, "buscador", buscador::registrar)?;
    valor::submodulo(m, "moe", moe::registrar)?;
    valor::submodulo(m, "web", web::registrar)?;
    valor::submodulo(m, "pdf", pdf::registrar)?;
    valor::submodulo(m, "indices", indices::registrar)?;
    valor::submodulo(m, "troceado", troceado::registrar)?;
    valor::submodulo(m, "vectores", vectores::registrar)?;
    valor::submodulo(m, "documentos", documentos::registrar)?;
    valor::submodulo(m, "referencias", referencias::registrar)?;
    valor::submodulo(m, "desafios", desafios::registrar)?;
    valor::submodulo(m, "http", http::registrar)?;
    Ok(())
}
