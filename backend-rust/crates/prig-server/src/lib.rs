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
        .route("/system/stats", propia(get(routes::inicio::stats)))
        .route("/system/health", propia(get(routes::inicio::salud)))
        .route("/inicio", propia(get(routes::inicio::resumen)))
        .route("/inicio/perfil", propia(get(routes::inicio::perfil).patch(routes::inicio::guardar_perfil)))
        .route("/file", propia(get(routes::plataforma::leer).post(routes::plataforma::escribir).delete(routes::plataforma::borrar)))
        .route("/file/raw", propia(get(routes::plataforma::crudo)))
        .route("/raw-file", propia(get(routes::plataforma::crudo)))
        .route("/create", propia(post(routes::plataforma::crear)))
        .route("/workspace/open", propia(post(routes::plataforma::abrir)))
        .route("/workspace/browse", propia(post(routes::plataforma::elegir)))
        .route("/workspace/segunda/browse", propia(post(routes::plataforma::segunda_elegir)))
        .route("/workspace/projects/save", propia(post(routes::plataforma::guardar_proyecto)))
        .route("/workspace/projects/remove", propia(post(routes::plataforma::quitar_proyecto)))
        .route("/ide/reemplazar", propia(post(routes::plataforma::reemplazar)))
        .route("/ide/renombrar", propia(post(routes::plataforma::renombrar)))
        .route("/ide/duplicar", propia(post(routes::plataforma::duplicar)))
        .route("/ide/mostrar-en-sistema", propia(post(routes::plataforma::mostrar)))
        .route("/ide/problemas", propia(post(routes::plataforma::problemas)))
        .route("/ide/acerca", propia(get(routes::plataforma::acerca)))
        .route("/tree", propia(get(routes::files::get_tree)))
        .route("/ide/archivos", propia(get(routes::ide::ide_archivos)))
        .route("/ide/buscar", propia(post(routes::ide::ide_buscar)))
        .route("/desafios", propia(get(routes::desafios::desafios_lista)))
        .route("/desafios/:id_", propia(get(routes::desafios::desafios_obtener).delete(routes::desafios::desafios_borrar)))
        .route("/desafios/:id_/paginas", propia(axum::routing::put(routes::desafios::desafios_guardar_paginas)))
        .route("/desafios/:id_/razonamiento/visto", propia(post(routes::desafios::desafios_pasos_vistos)))
        .route("/desafios/:id_/rendirse", propia(post(routes::desafios::desafios_rendirse)))
        .route("/desafios/:id_/ejecutar", propia(post(routes::desafios::desafios_ejecutar)))
        .route("/desafios/:id_/detener", propia(post(routes::desafios::desafios_detener)))
        .route("/desafios/:id_/comprobar", propia(post(routes::desafios::desafios_comprobar)))
        .route("/recursos/maquina", propia(get(routes::recursos::maquina)))
        .route("/recursos/estado", propia(get(routes::recursos::estado)))
        .route("/recursos/perfiles", propia(get(routes::recursos::perfiles_lista)))
        .route("/recursos/modelos", propia(get(routes::recursos::modelos)))
        .route("/recursos/recomendar", propia(post(routes::recursos::recomendar)))
        .route("/recursos/aplicar", propia(post(routes::recursos::aplicar)))
        .route("/recursos/restaurar", propia(post(routes::recursos::restaurar)))
        .route("/recursos/probar", propia(post(routes::recursos::probar)))
        .route("/recursos/calibrar", propia(post(routes::recursos::calibrar)))
        .route("/recursos/cancelar", propia(post(routes::recursos::cancelar)))
        .route("/recursos/olvidar-calibracion", propia(post(routes::recursos::olvidar_calibracion)))
        .route("/recursos/servidor", propia(get(routes::recursos::servidor_estado).post(routes::recursos::servidor_aplicar)))
        .route("/recursos/temperaturas", propia(get(routes::recursos::temperaturas)))
        .route("/recursos/termico", propia(post(routes::recursos::termico_ajustar)))
        .route("/recursos/ritmo", propia(get(routes::recursos::ritmo).post(routes::recursos::ritmo_ajustar)))
        .route("/recursos/frio", propia(get(routes::recursos::frio).post(routes::recursos::frio_ajustar)))
        .route("/recursos/energia/instalar", propia(post(routes::recursos::energia_instalar)))
        .route("/recursos/energia", propia(post(routes::recursos::energia)))
        .route("/recursos/eventos", propia(get(routes::recursos::eventos)))
        .route("/recursos/moe", propia(get(routes::moe::panel).post(routes::moe::panel_ajustar)))
        .route("/github/explicar", propia(post(routes::profesor::github_explicar)))
        .route("/github/preguntar", propia(post(routes::profesor::github_preguntar)))
        .route("/youtube/analizar", propia(post(routes::profesor::youtube_analizar)))
        .route("/youtube/traducir_texto", propia(post(routes::profesor::youtube_traducir)))
        .route("/kaggle/explicar_datos", propia(post(routes::profesor::kaggle_explicar_datos)))
        .route("/kaggle/explicar", propia(post(routes::profesor::kaggle_explicar)))
        .route("/kaggle/guia", propia(post(routes::profesor::kaggle_guia)))
        .route("/kaggle/notebook/estudio_optimo", propia(post(routes::profesor::kaggle_estudio)))
        .route("/kaggle/preguntar", propia(post(routes::profesor::kaggle_preguntar)))
        .route("/referencias", propia(get(routes::referencias::listar)))
        .route("/referencias/detalle", propia(get(routes::referencias::detalle_ref)))
        .route("/referencias/relacionadas", propia(get(routes::referencias::relacionadas)))
        .route("/referencias/pdf", propia(get(routes::referencias::pdf)))
        .route("/referencias/abrir", propia(post(routes::referencias::abrir)))
        .route("/audio/aplicaciones", propia(get(routes::escritorio::aplicaciones)))
        .route("/audio/seleccionar_fuente", propia(post(routes::escritorio::seleccionar_fuente)))
        .route("/audio/datos_actuales", propia(get(routes::escritorio::datos_actuales)))
        .route("/note/open-standalone", propia(post(routes::escritorio::nota_suelta)))
        .route("/note/explain", propia(post(routes::escritorio::nota_explicar)))
        .route("/ide/pantalla-completa", propia(post(routes::escritorio::pantalla_completa)))
        .route("/folder/code-files", propia(get(routes::exportar::archivos_de_codigo)))
        .route("/export/pdf-preview", propia(post(routes::exportar::vista_previa)))
        .route("/export/pdf-download", propia(post(routes::exportar::descargar)))
        .route("/buscador/fuentes", propia(get(routes::buscador::fuentes)))
        .route("/buscador/buscar", propia(get(routes::buscador::buscar)))
        .route("/buscador/localizar", propia(get(routes::buscador::localizar)))
        .route("/buscador/variantes", propia(get(routes::buscador::variantes)))
        .route("/buscador/comprobar", propia(get(routes::buscador::comprobar)))
        .route("/buscador/analizar", propia(get(routes::buscador::analizar)))
        .route("/buscador/novedades", propia(get(routes::buscador::novedades)))
        .route("/buscador/actualizaciones", propia(get(routes::buscador::actualizaciones)))
        .route("/buscador/seguidos", propia(get(routes::buscador::seguidos).post(routes::buscador::seguir)))
        .route("/buscador/seguidos/dejar", propia(post(routes::buscador::dejar)))
        .route("/buscador/seguidos/visto", propia(post(routes::buscador::visto)))
        .route("/modelos", propia(get(routes::modelos::lista)))
        .route("/modelos/catalogo", propia(get(routes::modelos::catalogo)))
        .route("/modelos/ficha", propia(get(routes::modelos::ficha)))
        .route("/modelos/config", propia(get(routes::modelos::config).post(routes::modelos::config_fijar)))
        .route("/modelos/plantilla", propia(post(routes::modelos::plantilla)))
        .route("/modelos/probar", propia(post(routes::modelos::probar)))
        .route("/modelos/crear", propia(post(routes::modelos::crear)))
        .route("/modelos/copiar", propia(post(routes::modelos::copiar)))
        .route("/modelos/borrar", propia(post(routes::modelos::borrar)))
        .route("/modelos/importar", propia(post(routes::modelos::importar)))
        .route("/modelos/actualizaciones", propia(get(routes::modelos::actualizaciones)))
        .route("/modelos/cargados", propia(get(routes::modelos::cargados)))
        .route("/modelos/precargar", propia(post(routes::modelos::precargar)))
        .route("/modelos/descargar", propia(post(routes::modelos::descargar)))
        .route("/modelos/parciales", propia(get(routes::modelos::parciales).delete(routes::modelos::borrar_parciales)))
        .route("/modelos/registro", propia(get(routes::modelos::registro)))
        .route("/ia/generar", post(routes::ia::ia_generar))
        .route("/ia/gemini", post(routes::ia::ia_gemini))
        .route("/gemini/estado", propia(get(routes::ia::gemini_estado)))
        .route("/gemini/clave", propia(post(routes::ia::gemini_guardar).delete(routes::ia::gemini_borrar)))
        .route("/gemini/modelos", propia(get(routes::ia::gemini_modelos)))
        .route("/ia/pausas", post(routes::ia::ia_pausas))
        .route("/ia/chat", post(routes::ia::ia_chat))
        .route("/ia/capacidades", get(routes::ia::ia_capacidades))
        .route("/ia/descargar", post(routes::ia::ia_descargar))
        .route("/ai/cancel", propia(post(routes::asistente::cancelar)))
        .route("/guided/cancel", propia(post(routes::asistente::cancelar)))
        .route("/ai/catalog", propia(get(routes::asistente::catalogo)))
        .route("/ai/search", propia(post(routes::asistente::buscar)))
        .route("/ai/inline-complete", propia(post(routes::asistente::completar)))
        .route("/ai/inline-prompt", propia(post(routes::asistente::instruccion)))
        .route("/ai/status", propia(get(routes::ia::estado)))
        .route("/ai/reload", propia(get(routes::ia::recargar).post(routes::ia::recargar)))
        .route("/ai/models", propia(get(routes::ia::modelos)))
        .route("/ai/models/detailed", propia(get(routes::ia::modelos_detallados)))
        .route("/ai/models/delete", propia(post(routes::ia::borrar_modelo)))
        .route("/ai/pull", propia(post(routes::ia::descargar_modelo)))
        .route("/ai/config", propia(get(routes::ia::config).post(routes::ia::guardar_config)))
        .route("/ollama/asegurar", post(routes::ia::asegurar))
        .route("/ollama/detener", post(routes::ia::detener))
        .route("/moe/ollama/:tipo", post(routes::moe::ollama_compatible))
        .route("/moe/directo", post(routes::moe::directo))
        .route("/moe/estado", get(routes::moe::estado))
        .route("/moe/actividad", get(routes::moe::actividad))
        .route("/moe/:accion", post(routes::moe::accion))
        .route("/books/list", propia(get(routes::estante::listar)))
        .route("/books/inventario", propia(get(routes::estante::inventario)))
        .route("/books/delete", propia(post(routes::estante::quitar)))
        .route("/books/ocultos", propia(get(routes::estante::ocultos)))
        .route("/books/restaurar", propia(post(routes::estante::restaurar)))
        .route("/books/read", propia(get(routes::libros::leer)))
        .route("/books/analyze", propia(post(routes::libros::analizar_ruta)))
        .route("/books/metadata", propia(get(routes::libros::ficha_consulta)))
        .route("/books/metadata/:book_id", propia(get(routes::libros::ficha_ruta)))
        .route("/books/snippet", propia(post(routes::libros::recorte_guardar)))
        .route("/books/snippets", propia(get(routes::libros::recortes_ruta)))
        .route("/books/snippet/:snippet_id", propia(get(routes::libros::recorte)))
        .route("/books/pdf-pages", propia(get(routes::libros::paginas_ruta)))
        .route("/books/pdf-page-save", propia(post(routes::libros::pagina_guardar)))
        .route("/books/citations", propia(get(routes::libros::citas_ruta)))
        .route("/books/citations/save", propia(post(routes::libros::cita_guardar)))
        .route("/books/citations/delete", propia(post(routes::libros::cita_borrar)))
        .route("/books/citations/export", propia(post(routes::libros::citas_exportar)))
        .route("/books/all-citations", propia(get(routes::libros::todas_ruta)))
        .route("/learning/metrics", propia(get(routes::aprendizaje::metricas)))
        .route("/exercise/recent", propia(get(routes::ejercicios::recientes)))
        .route("/guided/list", propia(get(routes::guiado::guiado_lista)))
        .route("/guided/:path_id", propia(get(routes::guiado::guiado_ver).delete(routes::guiado::guiado_borrar)))
        .route("/seguimiento/list", propia(get(routes::guiado::seguimiento_lista)))
        .route("/seguimiento/:seg_id", propia(get(routes::guiado::seguimiento_ver).delete(routes::guiado::seguimiento_borrar)))
        .route("/guided/:path_id/progress", propia(post(routes::guiado::guiado_progreso)))
        .route("/seguimiento/:seg_id/progress", propia(post(routes::guiado::seguimiento_progreso)))
        .route("/study-plan/progress/:que", propia(post(routes::guiado::plan_alternar)))
        .route("/dataset/summary", propia(get(routes::guiado::dataset_resumen)))
        .route("/dataset/export", propia(get(routes::guiado::dataset_exportar)))
        .route("/study-plan/list", propia(get(routes::guiado::planes_lista)))
        .route("/study-plan/:plan_id", propia(axum::routing::delete(routes::guiado::plan_borrar)))
        .route("/exercise/submit", propia(post(routes::ejercicios::entregar)))
        .route("/exercise/:exercise_id", propia(get(routes::ejercicios::ver)))
        .route("/exercise/:exercise_id/solution", propia(get(routes::ejercicios::solucion)))
        .route("/progreso/analisis", propia(get(routes::desafios::progreso_analisis)))
        .route("/progreso/historial", propia(get(routes::desafios::progreso_historial)))
        .route("/progreso/resumen", propia(get(routes::desafios::progreso_resumen)))
        .route(
            "/github/guardados",
            propia(get(routes::desafios::github_guardados).post(routes::integraciones::github_guardar).delete(routes::integraciones::github_quitar)),
        )
        .route("/youtube/palabras_registradas", propia(get(routes::integraciones::youtube_palabras)))
        .route("/youtube/sugerencias", propia(get(routes::integraciones::youtube_sugerencias)))
        .route("/youtube/buscar", propia(get(routes::integraciones::youtube_buscar)))
        .route("/youtube/abrir_externo", propia(post(routes::integraciones::youtube_abrir)))
        .route("/youtube/transcripcion", propia(get(routes::integraciones::youtube_transcripcion)))
        .route("/github/widget/config", propia(get(routes::integraciones::widget_config).post(routes::integraciones::widget_guardar)))
        .route("/github/widget/preview", propia(post(routes::integraciones::widget_preview)))
        .route("/github/widget/publicar", propia(post(routes::integraciones::widget_publicar)))
        .route("/github/token", propia(post(routes::integraciones::github_token).delete(routes::integraciones::github_borrar_token)))
        .route("/github/buscar", propia(get(routes::integraciones::github_buscar)))
        .route("/github/repo", propia(get(routes::integraciones::github_repo)))
        .route("/github/archivo", propia(get(routes::integraciones::github_archivo)))
        .route("/github/descargar", propia(post(routes::integraciones::github_descargar)))
        .route("/github/exportar", propia(post(routes::integraciones::github_exportar)))
        .route("/github/exportado", propia(get(routes::integraciones::github_exportado)))
        .route("/github/estado", propia(get(routes::integraciones::github_estado)))
        .route("/kaggle/estado", propia(get(routes::integraciones::kaggle_estado)))
        .route("/kaggle/credenciales", propia(post(routes::integraciones::kaggle_credenciales).delete(routes::integraciones::kaggle_borrar_credenciales)))
        .route("/kaggle/buscar", propia(get(routes::integraciones::kaggle_buscar)))
        .route("/kaggle/notebook", propia(get(routes::integraciones::kaggle_notebook)))
        .route("/kaggle/importar", propia(post(routes::integraciones::kaggle_importar)))
        .route("/kaggle/datasets", propia(get(routes::integraciones::kaggle_datasets)))
        .route("/kaggle/competiciones", propia(get(routes::integraciones::kaggle_competiciones)))
        .route("/kaggle/dataset", propia(get(routes::integraciones::kaggle_dataset)))
        .route("/kaggle/competicion", propia(get(routes::integraciones::kaggle_competicion)))
        .route("/kaggle/descargar", propia(post(routes::integraciones::kaggle_descargar)))
        .route("/kaggle/pdf", propia(get(routes::integraciones::kaggle_pdf_archivo).post(routes::integraciones::kaggle_pdf_crear)))
        .route("/kaggle/pdf/abrir", propia(post(routes::integraciones::kaggle_pdf_abrir)))
        .route("/kaggle/mis_datos", propia(get(routes::integraciones::kaggle_mis_datos)))
        .route("/kaggle/previa", propia(get(routes::integraciones::kaggle_previa)))
        .route("/kaggle/archivo", propia(get(routes::integraciones::kaggle_archivo)))
        .route("/kaggle/lecturas", propia(get(routes::integraciones::kaggle_lecturas)))
        .route("/kaggle/colecciones", propia(get(routes::integraciones::kaggle_colecciones_listar).post(routes::integraciones::kaggle_colecciones_crear)))
        .route(
            "/kaggle/colecciones/:id_",
            propia(
                get(routes::integraciones::kaggle_coleccion)
                    .patch(routes::integraciones::kaggle_coleccion_editar)
                    .delete(routes::integraciones::kaggle_coleccion_borrar),
            ),
        )
        .route(
            "/kaggle/colecciones/:id_/items",
            propia(
                post(routes::integraciones::kaggle_coleccion_anadir)
                    .patch(routes::integraciones::kaggle_coleccion_nota)
                    .delete(routes::integraciones::kaggle_coleccion_quitar),
            ),
        )
        .route("/librerias/list", propia(get(routes::biblioteca::librerias_list)))
        .route("/librerias/add", propia(post(routes::librerias::agregar_ruta)))
        .route("/librerias/citations", propia(get(routes::librerias::citas_ruta)))
        .route("/librerias/citations/save", propia(post(routes::librerias::guardar_ruta)))
        .route("/librerias/citations/delete", propia(post(routes::librerias::borrar_ruta)))
        .route("/librerias/citations/export", propia(post(routes::librerias::exportar_ruta)))
        .route("/librerias/analyze", propia(post(routes::librerias::analizar_ruta)))
        .route("/librerias/all-citations", propia(get(routes::librerias::todas_ruta)))
        .route("/papers/list", propia(get(routes::biblioteca::papers_list)))
        .route("/papers/detail", propia(get(routes::biblioteca::paper_detalle)))
        .route("/papers/download", propia(post(routes::biblioteca::paper_descargar)))
        .route("/papers/ask", propia(post(routes::biblioteca::paper_preguntar)))
        .route("/config/profiles", propia(get(routes::config::profiles).post(routes::config::guardar_perfiles)))
        .route("/config/profiles/reset", propia(post(routes::config::restablecer_perfiles)))
        .route("/config/apariencia", propia(get(routes::config::apariencia).post(routes::config::guardar_apariencia)))
        .route("/config/sintaxis", propia(get(routes::config::sintaxis).post(routes::config::guardar_sintaxis)))
        .route("/config/motor_movimiento", propia(get(routes::config::motor_movimiento).post(routes::config::guardar_motor_movimiento)))
        .route("/config/audio_reactivo", propia(get(routes::config::audio_reactivo).post(routes::config::guardar_audio_reactivo)))
        .route("/config/accesibilidad", propia(get(routes::config::accesibilidad).post(routes::config::guardar_accesibilidad)))
        .route("/config/estado_completo", propia(get(routes::config::estado_completo).post(routes::config::guardar_estado_completo)))
        .route("/explorador/atajos", propia(get(routes::navegar::explorador_atajos)))
        .route("/explorador/listar", propia(get(routes::navegar::explorador_listar)))
        .route("/explorador/buscar", propia(get(routes::navegar::explorador_buscar)))
        .route("/ide/recientes", propia(get(routes::navegar::ide_recientes).delete(routes::plataforma::olvidar_recientes)))
        .route("/workspace/directories", propia(get(routes::navegar::workspace_directories)))
        .route("/workspace/projects", propia(get(routes::navegar::workspace_projects)))
        .route("/workspace/segunda", propia(get(routes::navegar::workspace_segunda).post(routes::plataforma::segunda)))
        .route("/flags", propia(get(routes::navegar::flags).post(routes::navegar::flags_poner)))
        .route("/banco/simbolos", propia(get(routes::banco::simbolos_banco)))
        .route("/banco/ficha", propia(get(routes::banco::ficha_banco)))
        .route("/banco/grafo", propia(get(routes::banco::grafo_banco)))
        .route("/health", propia(get(routes::system::health_check)))
        .route("/hardware", propia(get(routes::system::get_hardware_telemetry)))
        .route("/system/hardware", propia(get(routes::system::get_hardware_telemetry)))
        .route("/sql/databases", propia(get(routes::sql::listar_bases_datos)))
        .route("/sql/databases/create", propia(post(routes::sql::crear_base_datos)))
        .route("/sql/tables", propia(get(routes::sql::listar_tablas)))
        .route("/sql/schema", propia(get(routes::sql::obtener_esquema)))
        .route("/sql/query", propia(post(routes::sql::ejecutar_consulta)))
        .route("/sql/seed", propia(post(routes::sql::sembrar_datos_ejemplo)));

    let mut app = Router::new()
        .route("/", propia(get(serve_index)))
        .route("/ws/audio_reactivo", get(routes::escritorio::ws_audio))
        .nest("/api", api_routes)
        .nest_service("/static", ServeDir::new(&state.frontend_dir));

    if let Some(ref a_dir) = state.assets_dir {
        app = app.nest_service("/assets", ServeDir::new(a_dir));
    }

    app.fallback(routes::proxy::proxy_fallback).layer(cors).with_state(state)
}
