//! El árbol de archivos (`GET /api/tree`), con el mismo núcleo que `FileManager.get_file_tree` de Python
//! (prig_plataforma::archivos). Leer, escribir, crear y
//! borrar archivos lo hace el backend de Python (por el proxy): además de tocar el disco, avisa al director y aplica
//! sus reglas; reimplementarlo aquí dejaba esos efectos afuera.

use axum::{
    extract::{Query, State},
    Json,
};
use serde::Deserialize;

use crate::routes::workspace::espacio_de_trabajo;
use crate::state::AppState;

#[derive(Deserialize)]
pub struct TreeParams {
    pub path: Option<String>,
}

pub async fn get_tree(State(state): State<AppState>, Query(params): Query<TreeParams>) -> Json<serde_json::Value> {
    espacio_de_trabajo(&state).await;
    let fm = state.file_mgr.read().await.clone();
    let base = fm.base_dir.to_string_lossy().into_owned();
    let raices: Vec<String> = fm.allowed_roots().iter().map(|r| r.to_string_lossy().into_owned()).collect();
    // Recorrer hasta 6 niveles es E/S bloqueante: fuera de los hilos de Tokio (por ahí pasa el proxy del chat)
    let texto = tokio::task::spawn_blocking(move || {
        let mut avisos = Vec::new();
        let arbol = prig_plataforma::archivos::arbol(params.path.as_deref(), &base, &raices, 6, 0, &mut avisos);
        for a in avisos {
            tracing::warn!("{a}");
        }
        prig_plataforma::json::escribir_compacto(&prig_plataforma::valor::Valor::Lista(arbol))
    })
    .await
    .unwrap_or_else(|_| "[]".into());
    Json(serde_json::from_str(&texto).unwrap_or(serde_json::Value::Array(vec![])))
}
