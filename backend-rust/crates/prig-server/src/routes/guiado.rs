//! Aprendizaje guiado, seguimientos y planes de estudio sin modelo: las listas y los borrados
//! (`GuidedLearningService.list_paths/delete`, `SeguimientoRepository.list_all/delete`,
//! `StudyPlanRepository.list_plans/delete_plan`). Los datos son archivos del espacio de trabajo
//! (`.prig_seguimientos/`, `.prig_plans/`); generar, ver con su modelo y el progreso siguen en Python.

use axum::{
    extract::{Path as Ruta, State},
    http::StatusCode,
    response::Response,
};
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    use axum::response::IntoResponse;
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

/// Un id que se usa como nombre de archivo o carpeta: un nombre suelto (ni «.», ni «..», ni «/», ni NUL)
fn id_seguro(id: &str) -> bool {
    !id.is_empty() && id != "." && id != ".." && !id.contains('/') && !id.contains('\0')
}

/// `GET /api/seguimiento/list` (obsoleta, la sigue usando quien no se actualizó)
pub async fn seguimiento_lista(State(state): State<AppState>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    match tokio::task::spawn_blocking(move || prig_aprendizaje::planes::listar_seguimientos(&espacio)).await {
        Ok(v) => json_py(StatusCode::OK, &Valor::Lista(v.into_iter().map(Valor::Mapa).collect())),
        Err(_) => error_500(),
    }
}

/// `GET /api/guided/list`: los seguimientos con su origen y su número de bloques
pub async fn guiado_lista(State(state): State<AppState>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Vec<Mapa>, ()> {
        // {id: resumen}: un id repetido se queda con el último resumen en el sitio del primero
        let mut resumen: Vec<(Valor, Mapa)> = Vec::new();
        for s in prig_aprendizaje::planes::listar_seguimientos(&espacio) {
            let id = s.valor("id").clone();
            match resumen.iter_mut().find(|(k, _)| *k == id) {
                Some(e) => e.1 = s,
                None => resumen.push((id, s)),
            }
        }
        for ruta in prig_aprendizaje::planes::jsons(&espacio.join(".prig_seguimientos")) {
            let Some(Valor::Mapa(raw)) = prig_aprendizaje::desafios::leer_json(&ruta) else { continue };
            let id = raw.get("id").cloned().unwrap_or(Valor::Nulo);
            if let Some((_, r)) = resumen.iter_mut().find(|(k, _)| *k == id) {
                r.poner("source", raw.get("source").cloned().unwrap_or(Valor::Texto("rapido".into())));
                let bloques = match raw.get("blocks") {
                    None => 0,
                    Some(Valor::Lista(l)) => l.len(),
                    Some(Valor::Mapa(m)) => m.len(),
                    Some(Valor::Texto(t)) => t.chars().count(),
                    Some(_) => return Err(()),
                };
                r.poner("blocks_total", Valor::Entero(bloques as i128));
            }
        }
        let mut v: Vec<Mapa> = resumen.into_iter().map(|(_, m)| m).collect();
        prig_aprendizaje::planes::ordenar_desc(&mut v, "created_at");
        Ok(v)
    })
    .await;
    match r {
        Ok(Ok(v)) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("paths", Valor::Lista(v.into_iter().map(Valor::Mapa).collect())))),
        _ => error_500(),
    }
}

/// `DELETE /api/guided/{path_id}` y `DELETE /api/seguimiento/{seg_id}`: el archivo del seguimiento
async fn borrar_seguimiento(state: &AppState, id: String, no_encontrado: &str) -> Response {
    let espacio = espacio_de_trabajo(state).await;
    let i = id.clone();
    let borrado = tokio::task::spawn_blocking(move || {
        let ruta = espacio.join(".prig_seguimientos").join(format!("{i}.json"));
        id_seguro(&i) && ruta.exists() && std::fs::remove_file(&ruta).is_ok()
    })
    .await
    .unwrap_or(false);
    if !borrado {
        return detalle(StatusCode::NOT_FOUND, no_encontrado);
    }
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("status", "deleted").con("id", id)))
}

pub async fn guiado_borrar(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    borrar_seguimiento(&state, id, "Ruta no encontrada").await
}

pub async fn seguimiento_borrar(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    borrar_seguimiento(&state, id, "Seguimiento no encontrado").await
}

/// `GET /api/study-plan/list`
pub async fn planes_lista(State(state): State<AppState>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    match tokio::task::spawn_blocking(move || prig_aprendizaje::planes::listar_planes(&espacio)).await {
        Ok(v) => json_py(StatusCode::OK, &Valor::Lista(v.into_iter().map(Valor::Mapa).collect())),
        Err(_) => error_500(),
    }
}

/// `DELETE /api/study-plan/{plan_id}`: su carpeta o, si es antiguo, su archivo
pub async fn plan_borrar(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    let i = id.clone();
    let borrado = tokio::task::spawn_blocking(move || {
        if !id_seguro(&i) {
            return false;
        }
        let dir = espacio.join(".prig_plans");
        let carpeta = dir.join(&i);
        if carpeta.is_dir() {
            return std::fs::remove_dir_all(&carpeta).is_ok();
        }
        let antiguo = dir.join(format!("{i}.json"));
        antiguo.exists() && std::fs::remove_file(&antiguo).is_ok()
    })
    .await
    .unwrap_or(false);
    if !borrado {
        return detalle(StatusCode::NOT_FOUND, "Plan no encontrado para eliminar.");
    }
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("status", "deleted").con("plan_id", id)))
}

async fn ver_seguimiento(state: &AppState, id: String, no_encontrado: &str) -> Response {
    let espacio = espacio_de_trabajo(state).await;
    match tokio::task::spawn_blocking(move || prig_aprendizaje::planes::cargar_seguimiento(&espacio, &id)).await {
        Ok(Ok(Some(m))) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Ok(None)) => detalle(StatusCode::NOT_FOUND, no_encontrado),
        Ok(Err(e)) => {
            tracing::warn!("seguimiento: {e}");
            error_500()
        }
        Err(_) => error_500(),
    }
}

/// `GET /api/guided/{path_id}`
pub async fn guiado_ver(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    ver_seguimiento(&state, id, "Ruta no encontrada").await
}

/// `GET /api/seguimiento/{seg_id}`
pub async fn seguimiento_ver(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    ver_seguimiento(&state, id, "Seguimiento no encontrado").await
}

/// `POST /api/guided/{id}/progress` y `/api/seguimiento/{id}/progress` (`completed_blocks`): marca los bloques (con la
/// fecha en que se marcó cada uno), guarda y reconstruye el dataset de aprendizaje
async fn progreso_seguimiento(state: &AppState, id: String, b: &axum::body::Bytes, no_encontrado: &str) -> Response {
    let m = match crate::routes::cuerpo::modelo(b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = crate::routes::cuerpo::Campos::new(&m);
    let hechos = c.lista_de_textos("completed_blocks");
    if let Err(r) = c.fin() {
        return r;
    }
    let espacio = espacio_de_trabajo(state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Option<Mapa>, String> {
        use prig_aprendizaje::planes;
        let Some(mut s) = planes::cargar_seguimiento(&espacio, &id)? else { return Ok(None) };
        planes::marcar_bloques(&mut s, &hechos);
        planes::guardar_seguimiento(&espacio, &s).map_err(|e| e.to_string())?;
        prig_aprendizaje::dataset::construir(&espacio)?;
        Ok(Some(s))
    })
    .await;
    match r {
        Ok(Ok(Some(s))) => json_py(StatusCode::OK, &Valor::Mapa(s)),
        Ok(Ok(None)) => detalle(StatusCode::NOT_FOUND, no_encontrado),
        Ok(Err(e)) => {
            tracing::warn!("progreso del seguimiento: {e}");
            error_500()
        }
        Err(_) => error_500(),
    }
}

pub async fn guiado_progreso(State(state): State<AppState>, Ruta(id): Ruta<String>, b: axum::body::Bytes) -> Response {
    progreso_seguimiento(&state, id, &b, "Ruta no encontrada").await
}

pub async fn seguimiento_progreso(State(state): State<AppState>, Ruta(id): Ruta<String>, b: axum::body::Bytes) -> Response {
    progreso_seguimiento(&state, id, &b, "Seguimiento no encontrado").await
}

/// `POST /api/study-plan/progress/toggle-criterion` (`plan_id`, `module_id`, `criterion_text`) y `toggle-notebook`
/// (`plan_id`, `notebook_id`): marca o desmarca, recalcula el progreso y guarda una versión nueva del plan
pub async fn plan_alternar(State(state): State<AppState>, Ruta(que): Ruta<String>, b: axum::body::Bytes) -> Response {
    let m = match crate::routes::cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = crate::routes::cuerpo::Campos::new(&m);
    let plan_id = c.texto("plan_id", None);
    let (a, b2) = match que.as_str() {
        "toggle-criterion" => (c.texto("module_id", None), c.texto("criterion_text", None)),
        "toggle-notebook" => (c.texto("notebook_id", None), Valor::Nulo),
        _ => return detalle(StatusCode::NOT_FOUND, "Not Found"),
    };
    if let Err(r) = c.fin() {
        return r;
    }
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Option<Mapa>, String> {
        use prig_aprendizaje::planes;
        let Some(mut p) = planes::cargar_plan(&espacio, &plan_id.texto_py())? else { return Ok(None) };
        if que == "toggle-criterion" {
            planes::alternar_criterio(&mut p, &a.texto_py(), &b2.texto_py());
        } else {
            planes::alternar_cuaderno(&mut p, &a.texto_py());
        }
        planes::guardar_plan(&espacio, &mut p).map_err(|e| e.to_string())?;
        Ok(Some(p))
    })
    .await;
    match r {
        Ok(Ok(Some(p))) => json_py(StatusCode::OK, &Valor::Mapa(p)),
        Ok(Ok(None)) => detalle(StatusCode::NOT_FOUND, "Plan no encontrado."),
        Ok(Err(e)) => {
            tracing::warn!("plan de estudio: {e}");
            error_500()
        }
        Err(_) => error_500(),
    }
}

/// `GET /api/dataset/summary`: el dataset de aprendizaje, reconstruido
pub async fn dataset_resumen(State(state): State<AppState>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    match tokio::task::spawn_blocking(move || prig_aprendizaje::dataset::construir(&espacio)).await {
        Ok(Ok(d)) => json_py(StatusCode::OK, &Valor::Mapa(d)),
        _ => error_500(),
    }
}

/// `GET /api/dataset/export`: el archivo del dataset, para descargar
pub async fn dataset_exportar(State(state): State<AppState>) -> Response {
    use axum::response::IntoResponse;
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Vec<u8>, String> {
        prig_aprendizaje::dataset::construir(&espacio)?;
        std::fs::read(espacio.join(".prig_dataset/user_learning_dataset.json")).map_err(|e| e.to_string())
    })
    .await;
    match r {
        Ok(Ok(b)) => (
            [
                (axum::http::header::CONTENT_TYPE, "application/json"),
                (axum::http::header::CONTENT_DISPOSITION, "attachment; filename=\"user_learning_dataset.json\""),
            ],
            b,
        )
            .into_response(),
        _ => error_500(),
    }
}
