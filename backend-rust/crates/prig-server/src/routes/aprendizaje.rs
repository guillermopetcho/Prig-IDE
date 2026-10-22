//! Aprendizaje: las métricas de la telemetría (`GET /api/learning/metrics`), con la lógica de
//! `prig_aprendizaje::telemetria` (la misma base SQLite del espacio de trabajo que usa `learning_telemetry.py`).

use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::Response,
};
use prig_plataforma::valor::Valor;
use std::collections::HashMap;

use crate::routes::cuerpo::entero_consulta;
use crate::routes::json_py;
use crate::routes::workspace::espacio_de_trabajo;
use crate::state::AppState;

/// `GET /api/learning/metrics?days=30`
pub async fn metricas(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let dias = match entero_consulta(&q, "days", 30, 1, 365) {
        Ok(d) => d,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || {
        let c = prig_aprendizaje::telemetria::abrir(&espacio)?;
        prig_aprendizaje::telemetria::metricas(&c, dias)
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        _ => {
            use axum::response::IntoResponse;
            (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
        }
    }
}
