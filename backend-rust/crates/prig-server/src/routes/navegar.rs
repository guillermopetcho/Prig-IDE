//! Rutas de solo lectura del explorador de libros, del IDE y de las banderas, con la lógica de `prig_plataforma`
//! (la misma que usan `explorador.py`, `ide_servicios.py` y `feature_flags.py`). Todo se lee del disco en cada
//! llamada (configuración, `~/.prig_flags.json`): no hay estado que pueda separarse del de Python. Cambiar algo
//! (POST) lo sigue haciendo Python por el proxy.

use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::Response,
};
use prig_plataforma::explorador::Ambito;
use prig_plataforma::py::ErrorPy;
use prig_plataforma::valor::{Mapa, Valor};
use prig_plataforma::{banderas::Banderas, ide, py};
use serde::Deserialize;
use std::path::PathBuf;

use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{detalle, json_py};
use crate::state::AppState;

fn casa() -> String {
    py::abspath(&py::expanduser("~"))
}

/// Una excepción que FastAPI no captura: 500 con su texto plano
fn error_500() -> Response {
    use axum::response::IntoResponse;
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

/// El 422 de FastAPI para un parámetro de consulta que falta o no vale
fn validacion(tipo: &str, campo: &str, mensaje: &str, entrada: Valor) -> Response {
    let error = Mapa::new()
        .con("type", tipo)
        .con("loc", Valor::Lista(vec![Valor::Texto("query".into()), Valor::Texto(campo.into())]))
        .con("msg", mensaje)
        .con("input", entrada);
    json_py(StatusCode::UNPROCESSABLE_ENTITY, &Valor::Mapa(Mapa::new().con("detail", Valor::Lista(vec![Valor::Mapa(error)]))))
}

async fn espacio(state: &AppState) -> String {
    espacio_de_trabajo(state).await.to_string_lossy().into_owned()
}

// ------------------------------------------------------------------ explorador de libros

pub async fn explorador_atajos(State(state): State<AppState>) -> Response {
    let ws = espacio(&state).await;
    let raiz = casa();
    let atajos = tokio::task::spawn_blocking(move || Ambito { raiz: &raiz, workspace: Some(&ws) }.atajos()).await.unwrap_or_default();
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("atajos", Valor::Lista(atajos))))
}

#[derive(Deserialize)]
pub struct ListarParams {
    ruta: Option<String>,
    #[serde(default)]
    recursivo: Option<String>,
}

/// `bool` de un parámetro de consulta como lo lee FastAPI
fn booleano(v: &Option<String>) -> Option<bool> {
    match v.as_deref().map(|t| t.to_ascii_lowercase()) {
        None => Some(false),
        Some(t) if ["1", "true", "on", "yes", "y", "t"].contains(&t.as_str()) => Some(true),
        Some(t) if ["0", "false", "off", "no", "n", "f"].contains(&t.as_str()) => Some(false),
        _ => None,
    }
}

pub async fn explorador_listar(State(state): State<AppState>, Query(p): Query<ListarParams>) -> Response {
    let Some(recursivo) = booleano(&p.recursivo) else {
        let entrada = p.recursivo.clone().unwrap_or_default();
        return validacion("bool_parsing", "recursivo", "Input should be a valid boolean, unable to interpret input", Valor::Texto(entrada));
    };
    let ws = espacio(&state).await;
    let raiz = casa();
    let r = tokio::task::spawn_blocking(move || Ambito { raiz: &raiz, workspace: Some(&ws) }.listar(p.ruta.as_deref(), recursivo)).await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e @ ErrorPy::Permiso(_))) => detalle(StatusCode::FORBIDDEN, e.texto()),
        Ok(Err(e @ ErrorPy::NoEsCarpeta(_))) => detalle(StatusCode::NOT_FOUND, e.texto()),
        Ok(Err(e @ ErrorPy::Os { errno: 2 | 20, .. })) => detalle(StatusCode::NOT_FOUND, e.texto()),
        _ => error_500(),
    }
}

#[derive(Deserialize)]
pub struct BuscarParams {
    q: Option<String>,
    desde: Option<String>,
}

pub async fn explorador_buscar(State(state): State<AppState>, Query(p): Query<BuscarParams>) -> Response {
    let Some(q) = p.q else {
        return validacion("missing", "q", "Field required", Valor::Nulo);
    };
    let ws = espacio(&state).await;
    let raiz = casa();
    let r = tokio::task::spawn_blocking(move || Ambito { raiz: &raiz, workspace: Some(&ws) }.buscar(&q, p.desde.as_deref(), 120)).await;
    match r {
        Ok(Ok(v)) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("resultados", Valor::Lista(v)))),
        Ok(Err(e @ ErrorPy::Permiso(_))) => detalle(StatusCode::FORBIDDEN, e.texto()),
        _ => error_500(),
    }
}

// ------------------------------------------------------------------ IDE: recientes, carpetas, proyectos

fn configuracion(state: &AppState) -> String {
    state.config_path.to_string_lossy().into_owned()
}

pub async fn ide_recientes(State(state): State<AppState>) -> Response {
    let base = espacio(&state).await;
    let cfg = configuracion(&state);
    match tokio::task::spawn_blocking(move || ide::recientes(&cfg, &base)).await {
        Ok(Ok(v)) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("carpetas", Valor::Lista(v)))),
        _ => error_500(),
    }
}

#[derive(Deserialize)]
pub struct CarpetasParams {
    ruta: Option<String>,
}

pub async fn workspace_directories(State(state): State<AppState>, Query(p): Query<CarpetasParams>) -> Response {
    let base = espacio(&state).await;
    match tokio::task::spawn_blocking(move || ide::listar_directorios(p.ruta.as_deref(), &base)).await {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

fn nombre_de(ruta: &str) -> String {
    let n = py::basename(ruta);
    if n.is_empty() { ruta.to_string() } else { n }
}

pub async fn workspace_projects(State(state): State<AppState>) -> Response {
    let base = espacio(&state).await;
    let cfg = configuracion(&state);
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, ErrorPy> {
        let guardados = ide::proyectos_guardados(&cfg, &base)?;
        let recientes = ide::recientes(&cfg, &base)?;
        Ok(Mapa::new()
            .con("actual", Mapa::new().con("path", base.clone()).con("name", nombre_de(&base)))
            .con("guardados", Valor::Lista(guardados))
            .con("recientes", Valor::Lista(recientes)))
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        _ => error_500(),
    }
}

pub async fn workspace_segunda(State(state): State<AppState>) -> Response {
    espacio_de_trabajo(&state).await;
    let segunda: Option<PathBuf> = state.file_mgr.read().await.segunda_dir.clone();
    let m = match segunda {
        Some(r) => {
            let r = r.to_string_lossy().into_owned();
            Mapa::new().con("path", r.clone()).con("name", nombre_de(&r))
        }
        None => Mapa::new().con("path", Valor::Nulo).con("name", Valor::Nulo),
    };
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

// ------------------------------------------------------------------ banderas

pub async fn flags() -> Response {
    let ruta = PathBuf::from(py::expanduser("~/.prig_flags.json"));
    let m = tokio::task::spawn_blocking(move || Banderas::new(ruta).todas()).await.unwrap_or_default();
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

/// `POST /api/flags` (FlagUpdateRequest: `name: str`, `enabled: Optional[bool]`; None vuelve al valor por defecto).
/// Una bandera que no existe: 404 con el texto de KeyError (entre comillas)
pub async fn flags_poner(b: axum::body::Bytes) -> Response {
    use crate::routes::cuerpo;
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let nombre = c.texto("name", None);
    let valor = c.booleano_opcional("enabled");
    if let Err(r) = c.fin() {
        return r;
    }
    let Valor::Texto(nombre) = nombre else { return error_500() };
    let ruta = PathBuf::from(py::expanduser("~/.prig_flags.json"));
    let r = tokio::task::spawn_blocking(move || {
        let mut f = Banderas::new(ruta);
        let v = match valor {
            None => Ok(f.reiniciar(&nombre)),
            Some(v) => f.poner(&nombre, v),
        };
        for a in std::mem::take(&mut f.avisos) {
            tracing::warn!("{a}");
        }
        v.map(|v| (nombre, v, f.todas()))
    })
    .await;
    match r {
        Ok(Ok((nombre, v, todas))) => json_py(
            StatusCode::OK,
            &Valor::Mapa(Mapa::new().con("name", nombre).con("enabled", v).con("flags", todas)),
        ),
        Ok(Err(e)) => detalle(StatusCode::NOT_FOUND, format!("'{e}'")),
        Err(_) => error_500(),
    }
}
