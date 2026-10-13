//! El árbol de archivos (`GET /api/tree`), igual que `FileManager.get_file_tree` de Python. Leer, escribir, crear y
//! borrar archivos lo hace el backend de Python (por el proxy): además de tocar el disco, avisa al director y aplica
//! sus reglas; reimplementarlo aquí dejaba esos efectos afuera.

use axum::{
    extract::{Query, State},
    Json,
};
use prig_fs::FileNode;
use serde::Deserialize;

use crate::routes::workspace::espacio_de_trabajo;
use crate::state::AppState;

#[derive(Deserialize)]
pub struct TreeParams {
    pub path: Option<String>,
}

pub async fn get_tree(State(state): State<AppState>, Query(params): Query<TreeParams>) -> Json<Vec<FileNode>> {
    espacio_de_trabajo(&state).await;
    let fm = state.file_mgr.read().await.clone();
    // Recorrer hasta 6 niveles es E/S bloqueante: fuera de los hilos de Tokio (por ahí pasa el proxy del chat)
    let arbol = tokio::task::spawn_blocking(move || fm.get_file_tree(params.path.as_deref(), 6)).await.unwrap_or_default();
    Json(arbol)
}
