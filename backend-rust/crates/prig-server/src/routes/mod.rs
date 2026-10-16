pub mod aprendizaje;
pub mod banco;
pub mod biblioteca;
pub mod config;
pub mod cuerpo;
pub mod desafios;
pub mod ejercicios;
pub mod estante;
pub mod files;
pub mod ia;
pub mod guiado;
pub mod navegar;
pub mod ide;
pub mod moe;
pub mod integraciones;
pub mod proxy;
pub mod recursos;
pub mod sql;
pub mod system;
pub mod workspace;

use axum::http::{header, StatusCode};
use axum::response::{IntoResponse, Response};
use prig_plataforma::valor::{Mapa, Valor};

/// Una respuesta JSON escrita con el escritor de Python (prig_recursos::json): las claves en el orden en que las
/// pone la lógica, como las devuelve FastAPI (serde_json las reordenaba)
pub fn json_py(estado: StatusCode, v: &Valor) -> Response {
    (estado, [(header::CONTENT_TYPE, "application/json")], prig_plataforma::json::escribir_compacto(v)).into_response()
}

/// El error de una ruta como `HTTPException(status_code, detail=...)` de FastAPI
pub fn detalle(estado: StatusCode, texto: impl Into<String>) -> Response {
    json_py(estado, &Valor::Mapa(Mapa::new().con("detail", texto.into())))
}
