//! Recursos de la máquina (backend/recursos/ de Python), en Rust: sin el GIL de Python, los hilos que vigilan y
//! frenan a los motores trabajan con la precisión que piden (docs/informe-rust-moe.md, §2).

pub mod almacen;
pub mod audio;
pub mod calculadora;
pub mod calibracion;
pub mod detector;
pub mod energia;
pub mod ficha;
pub mod frio;
pub mod gestor;
pub mod gguf;
pub mod http;
pub mod json;
pub mod motor_suave;
pub mod nvml;
pub mod perfiles;
pub mod ritmo;
pub mod sensores;
pub mod servidor;
pub mod termico;
pub mod valor;
