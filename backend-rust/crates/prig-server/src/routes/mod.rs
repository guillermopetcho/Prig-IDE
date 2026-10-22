pub mod aprendizaje;
pub mod asistente;
pub mod banco;
pub mod biblioteca;
pub mod buscador;
pub mod config;
pub mod conocimiento;
pub mod cuerpo;
pub mod desafios;
pub mod descargas;
pub mod director;
pub mod director_ast;
pub mod desafios_tutor;
pub mod desafios_crear;
pub mod desafios_fuentes;
pub mod ejecutar;
pub mod ejercicios;
pub mod escritorio;
pub mod estante;
pub mod exportar;
pub mod files;
pub mod flujos;
pub mod flujos_motor;
pub mod ia;
pub mod guiado;
pub mod guiado_ia;
pub mod hub;
pub mod aprendizaje_grafo;
pub mod plan_estudio;
pub mod navegar;
pub mod ide;
pub mod modelos;
pub mod moe;
pub mod plataforma;
pub mod inicio;
pub mod integraciones;
pub mod kb;
pub mod librerias;
pub mod libros;
pub mod profesor;
pub mod proxy;
pub mod recursos;
pub mod referencias;
pub mod sql;
pub mod system;
pub mod trabajos;
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
