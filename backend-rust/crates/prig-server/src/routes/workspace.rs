//! El espacio de trabajo. Su dueño es el backend de Python: abrir una carpeta (`/api/workspace/open`, `/browse`)
//! va por el proxy, Python cambia su `FileManager`, reconecta el banco y lo demás (`rebind_workspace`) y guarda la
//! carpeta en `~/.prig_config.json` (`last_workspace`). Aquí se lee de ese archivo cada vez que cambia, así las
//! rutas que atiende Rust (árbol, búsqueda, consultas del banco) trabajan siempre sobre la misma carpeta que Python.

use axum::{extract::State, response::Json};
use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

use crate::state::AppState;

#[derive(Serialize)]
pub struct WorkspaceResponse {
    pub path: String,
    pub name: String,
}

pub fn get_config_path() -> Option<PathBuf> {
    dirs_or_home().map(|h| h.join(".prig_config.json"))
}

pub fn dirs_or_home() -> Option<PathBuf> {
    std::env::var("HOME").ok().map(PathBuf::from).or_else(|| std::env::current_dir().ok())
}

fn leer_last_workspace(config_path: &Path) -> Option<String> {
    let texto = fs::read_to_string(config_path).ok()?;
    let valor: Value = serde_json::from_str(&texto).ok()?;
    valor.get("last_workspace").and_then(|v| v.as_str()).map(|s| s.to_string())
}

/// `FileManager._load_last_workspace` de Python: la última carpeta si existe; si no, la raíz de Prig (el directorio
/// desde el que se arranca el backend de Python).
pub fn load_last_workspace(config_path: &Path, fallback: &Path) -> PathBuf {
    match leer_last_workspace(config_path) {
        Some(ruta) if Path::new(&ruta).is_dir() => PathBuf::from(ruta),
        _ => fallback.to_path_buf(),
    }
}

/// La carpeta de trabajo actual, la misma que la de Python. Relee `last_workspace` solo si el archivo cambió; un
/// archivo a medio escribir (Python no lo escribe de forma atómica) o una carpeta que ya no existe no cambian nada.
pub async fn espacio_de_trabajo(state: &AppState) -> PathBuf {
    let mtime = fs::metadata(&state.config_path).and_then(|m| m.modified()).ok();
    {
        let mut visto = state.config_visto.lock().await;
        if *visto != mtime {
            *visto = mtime;
            if let Some(ruta) = leer_last_workspace(&state.config_path) {
                if Path::new(&ruta).is_dir() {
                    let mut fm = state.file_mgr.write().await;
                    let _ = fm.set_base_dir(Path::new(&ruta));
                }
            }
        }
    }
    state.file_mgr.read().await.base_dir.clone()
}

/// GET /api/workspace (igual que Python: `{"path": base_dir, "name": basename or base_dir}`)
pub async fn get_workspace(State(state): State<AppState>) -> Json<WorkspaceResponse> {
    let ws = espacio_de_trabajo(&state).await;
    let ruta = ws.to_string_lossy().to_string();
    let nombre = ws.file_name().map(|n| n.to_string_lossy().to_string()).filter(|n| !n.is_empty()).unwrap_or_else(|| ruta.clone());
    Json(WorkspaceResponse { path: ruta, name: nombre })
}
