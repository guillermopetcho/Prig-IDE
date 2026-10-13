//! Prig Native: el servidor HTTP de Prig en Rust (Axum). Sirve el frontend y atiende lo que hace mejor que Python
//! sin estado propio (el árbol de archivos, ir a archivo y buscar en archivos, consultas de solo lectura al banco,
//! telemetría). Todo lo demás va al backend de Python por el proxy (`routes::proxy`): el chat y el motor MoE, la
//! configuración de IA, el banco con su vigilante, los recursos y el modo frío, las descargas, el director, el
//! aprendizaje, la ejecución de código y la escritura de archivos. Esas partes tienen su estado en el proceso de
//! Python; respondidas aquí, los dos procesos quedaban con estados distintos (docs/revision-rust-2026-10-13.md).

use axum::{
    body::Body,
    extract::State,
    http::{header, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post, MethodRouter},
    Router,
};
use std::path::PathBuf;
use tower_http::cors::{AllowHeaders, AllowMethods, AllowOrigin, CorsLayer};
use tower_http::services::ServeDir;
use tracing::error;

pub mod routes;
pub mod state;

pub use state::AppState;

/// Sirve frontend/index.html con `no-cache` (como Python: tras actualizar Prig, la ventana revalida el índice)
pub async fn serve_index(State(state): State<AppState>) -> Response {
    let index_path = state.frontend_dir.join("index.html");
    match tokio::fs::read(&index_path).await {
        Ok(bytes) => Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, "text/html; charset=utf-8")
            .header(header::CACHE_CONTROL, "no-cache")
            .body(Body::from(bytes))
            .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response()),
        Err(err) => {
            error!("Error leyendo {}: {}", index_path.display(), err);
            (StatusCode::NOT_FOUND, format!("index.html no encontrado en {}", state.frontend_dir.display())).into_response()
        }
    }
}

pub fn resolve_project_root() -> PathBuf {
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    if cwd.join("frontend").join("index.html").exists() {
        return cwd;
    }
    if let Ok(exe_path) = std::env::current_exe() {
        let mut cur = exe_path.as_path();
        while let Some(parent) = cur.parent() {
            if parent.join("frontend").join("index.html").exists() {
                return parent.to_path_buf();
            }
            cur = parent;
        }
    }
    cwd
}

/// Los mismos orígenes que acepta el backend de Python (`LOCAL_ORIGINS` en app.py), más el puerto de este servidor.
/// Con `*`, cualquier página abierta en el navegador podía leer y escribir archivos y ejecutar código por esta API.
pub fn origenes_locales(puerto: u16) -> Vec<HeaderValue> {
    let mut puertos = vec![8000u16, 8080, puerto];
    puertos.sort_unstable();
    puertos.dedup();
    let mut salida = Vec::new();
    for host in ["127.0.0.1", "localhost"] {
        for p in &puertos {
            if let Ok(v) = HeaderValue::from_str(&format!("http://{host}:{p}")) {
                salida.push(v);
            }
        }
    }
    salida
}

/// Una ruta propia: los métodos que atiende Rust y, para cualquier otro, el proxy (sin esto, Axum responde 405 y
/// la petición nunca llega a Python: así se rompían POST /api/descargas, /api/flags y otras).
fn propia(metodos: MethodRouter<AppState>) -> MethodRouter<AppState> {
    metodos.fallback(routes::proxy::proxy_fallback)
}

/// La aplicación completa, lista para servir o para los tests
pub fn create_app(state: AppState) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::list(origenes_locales(state.puerto)))
        .allow_methods(AllowMethods::mirror_request())
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true);

    let api_routes = Router::new()
        .route("/workspace", propia(get(routes::workspace::get_workspace)))
        .route("/tree", propia(get(routes::files::get_tree)))
        .route("/ide/archivos", propia(get(routes::ide::ide_archivos)))
        .route("/ide/buscar", propia(post(routes::ide::ide_buscar)))
        .route("/banco/simbolos", propia(get(routes::banco::simbolos_banco)))
        .route("/banco/ficha", propia(get(routes::banco::ficha_banco)))
        .route("/banco/grafo", propia(get(routes::banco::grafo_banco)))
        .route("/health", propia(get(routes::system::health_check)))
        .route("/hardware", propia(get(routes::system::get_hardware_telemetry)))
        .route("/system/hardware", propia(get(routes::system::get_hardware_telemetry)));

    let mut app = Router::new()
        .route("/", propia(get(serve_index)))
        .nest("/api", api_routes)
        .nest_service("/static", ServeDir::new(&state.frontend_dir));

    if let Some(ref a_dir) = state.assets_dir {
        app = app.nest_service("/assets", ServeDir::new(a_dir));
    }

    app.fallback(routes::proxy::proxy_fallback).layer(cors).with_state(state)
}
