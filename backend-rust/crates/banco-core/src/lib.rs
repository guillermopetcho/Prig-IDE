//! El motor del banco del proyecto de Prig (port de backend/banco_proyecto.py, particion_proyecto.py y las
//! consultas de memoria_consulta.py). Plan, reglas y bitácora: Prig/docs/plan-banco-rust.md

pub mod banco;
pub mod consultas;
pub mod extraer;
pub mod particion;
pub mod py;
pub mod pyast;
pub mod re;
pub mod texto;

/// Versión de SQLite con la que corre el motor (tiene que ser la misma que la de Python).
pub fn version_sqlite() -> String {
    rusqlite::version().to_string()
}
