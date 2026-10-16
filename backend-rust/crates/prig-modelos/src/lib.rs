//! Modelos de Ollama (F3 de docs/plan-prig-rust.md): `ollama_opciones.py` (`opciones`), `ollama_gestion.py`
//! (`gestion`) y `buscador_modelos.py` (`buscador`).

pub mod buscador;
pub mod gestion;
pub mod opciones;
pub mod red;

pub use prig_recursos::{json, valor};
