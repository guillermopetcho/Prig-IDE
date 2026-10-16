//! La plataforma de Prig (F2 de docs/plan-prig-rust.md): lo que en Python eran `feature_flags.py`,
//! `perfiles_config.py`, `file_manager.py`, `ide_servicios.py`, `explorador.py`, `runner.py`, `kernel_session.py` e
//! `inicio.py`. Los valores y el JSON con la semántica de Python vienen de `prig_recursos` (`valor`, `json`).

pub mod modelo;
pub mod banderas;
pub mod archivos;
pub mod ejecucion;
pub mod espacio;
pub mod explorador;
pub mod html;
pub mod ide;
pub mod inicio;
pub mod perfiles;
pub mod py;
pub mod regex_py;

pub use prig_recursos::{json, valor};

/// Lee un JSON como `json.load(open(ruta, encoding="utf-8"))`
pub fn leer_json(ruta: &std::path::Path) -> Result<valor::Valor, String> {
    let bytes = std::fs::read(ruta).map_err(|e| e.to_string())?;
    let texto = String::from_utf8(bytes).map_err(|e| e.to_string())?;
    json::leer(&texto)
}

/// Escribe como `json.dump(datos, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=sangria)`
pub fn escribir_json(ruta: &std::path::Path, v: &valor::Valor, sangria: usize) -> Result<(), String> {
    std::fs::write(ruta, json::escribir(v, sangria)).map_err(|e| e.to_string())
}

#[cfg(test)]
mod pruebas;
