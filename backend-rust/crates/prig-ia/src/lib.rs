//! El motor de IA (F4 de docs/plan-prig-rust.md): `moe` (las piezas de `ai_engine/motor_moe.py`).

pub mod generar;
pub mod gestor;
pub mod moe;
pub mod motor;
pub mod ollama;
pub mod vivo;
pub mod web;

pub use prig_recursos::{json, valor};
