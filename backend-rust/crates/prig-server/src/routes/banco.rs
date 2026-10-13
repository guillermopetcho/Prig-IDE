//! Consultas de solo lectura al banco del proyecto que no tiene el backend de Python: símbolos, ficha y hechos del
//! grafo. Todo lo demás del banco (activar, sincronizar, buscar con vectores, contexto, memoria, ajustes, borrar) lo
//! atiende Python por el proxy: ahí viven el vigilante, el embebedor y los ajustes.

use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Json, Response},
};
use banco_core::banco::carpeta_de;
use banco_core::consultas::Consulta;
use serde::Deserialize;
use serde_json::{json, Value};
use std::path::Path;

use crate::routes::workspace::espacio_de_trabajo;
use crate::state::AppState;

#[derive(Deserialize)]
pub struct SimbolosQuery {
    pub nombre: Option<String>,
    pub ruta: Option<String>,
    pub tipo: Option<String>,
}

#[derive(Deserialize)]
pub struct FichaQuery {
    pub nombre: String,
}

#[derive(Deserialize)]
pub struct GrafoQuery {
    pub s: Option<String>,
    pub sj: Option<String>,
    pub r: Option<String>,
    pub o: Option<String>,
    pub limite: Option<i64>,
}

fn error(status: StatusCode, mensaje: impl Into<String>) -> Response {
    (status, Json(json!({ "detail": mensaje.into() }))).into_response()
}

/// Abre la consulta del banco de la carpeta de trabajo (la de Python) y corre `f` fuera de los hilos de Tokio.
async fn con_consulta<F>(state: &AppState, f: F) -> Response
where
    F: FnOnce(&Consulta) -> Result<Value, String> + Send + 'static,
{
    let raiz = espacio_de_trabajo(state).await.to_string_lossy().to_string();
    let db = format!("{}/banco.db", carpeta_de(&raiz));
    if !Path::new(&db).is_file() {
        return error(StatusCode::NOT_FOUND, "El banco del proyecto no existe. Actívalo primero.");
    }
    let resultado = tokio::task::spawn_blocking(move || {
        let consulta = Consulta::abrir(&db, &raiz)?;
        f(&consulta)
    })
    .await;
    match resultado {
        Ok(Ok(v)) => Json(v).into_response(),
        Ok(Err(e)) => error(StatusCode::BAD_REQUEST, e),
        Err(e) => error(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()),
    }
}

/// GET /api/banco/simbolos
pub async fn simbolos_banco(State(state): State<AppState>, Query(q): Query<SimbolosQuery>) -> Response {
    con_consulta(&state, move |c| {
        let sims = c.simbolos(q.nombre.as_deref(), q.ruta.as_deref(), q.tipo.as_deref())?;
        Ok(json!({ "simbolos": sims }))
    })
    .await
}

/// GET /api/banco/ficha
pub async fn ficha_banco(State(state): State<AppState>, Query(q): Query<FichaQuery>) -> Response {
    con_consulta(&state, move |c| c.ficha(&q.nombre)).await
}

/// GET /api/banco/grafo (`s` o `sj`: el sujeto; `r`: la relación; `o`: el objeto; con % como en SQL LIKE)
pub async fn grafo_banco(State(state): State<AppState>, Query(q): Query<GrafoQuery>) -> Response {
    let limite = q.limite.unwrap_or(100).clamp(1, 1000);
    con_consulta(&state, move |c| {
        let sujeto = q.s.or(q.sj);
        let hechos = c.hechos(sujeto.as_deref(), q.r.as_deref(), q.o.as_deref(), limite)?;
        Ok(json!({ "hechos": hechos }))
    })
    .await
}
