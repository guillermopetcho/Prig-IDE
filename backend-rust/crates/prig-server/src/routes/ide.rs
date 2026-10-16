//! Ir a archivo (`GET /api/ide/archivos`) y buscar en archivos (`POST /api/ide/buscar`) con la misma lógica que usa
//! el backend de Python (`prig_plataforma::ide`, la de `ide_servicios`): una sola implementación, comprobada con su
//! diferencial y con el comparador de rutas. Lo demás del IDE (reemplazar, renombrar, duplicar, problemas,
//! recientes…) lo atiende Python por el proxy.

use axum::{extract::State, http::StatusCode, response::Response, Json};
use prig_plataforma::ide;
use prig_plataforma::py::ErrorPy;
use prig_plataforma::valor::Valor;
use serde::Deserialize;

use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{detalle, json_py};
use crate::state::AppState;

pub async fn ide_archivos(State(state): State<AppState>) -> Response {
    let raiz = espacio_de_trabajo(&state).await.to_string_lossy().into_owned();
    match tokio::task::spawn_blocking(move || ide::listar(&raiz, ide::MAX_ARCHIVOS)).await {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(e) => detalle(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()),
    }
}

#[derive(Deserialize)]
pub struct IdeBuscarRequest {
    pub consulta: String,
    #[serde(default)]
    pub regex: bool,
    #[serde(default)]
    pub mayusculas: bool,
    #[serde(default)]
    pub palabra: bool,
    #[serde(default)]
    pub incluir: String,
    #[serde(default)]
    pub excluir: String,
}

/// `_ide` de app.py: PermissionError → 403; ErrorIDE y OSError → 400
fn error_ide(e: ErrorPy) -> Response {
    let estado = if matches!(e, ErrorPy::Permiso(_)) { StatusCode::FORBIDDEN } else { StatusCode::BAD_REQUEST };
    detalle(estado, e.texto())
}

pub async fn ide_buscar(State(state): State<AppState>, Json(req): Json<IdeBuscarRequest>) -> Response {
    let raiz = espacio_de_trabajo(&state).await.to_string_lossy().into_owned();
    let r = tokio::task::spawn_blocking(move || {
        ide::buscar(&raiz, &req.consulta, req.regex, req.mayusculas, req.palabra, &req.incluir, &req.excluir, ide::MAX_COINCIDENCIAS)
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e)) => error_ide(e),
        Err(e) => detalle(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()),
    }
}
