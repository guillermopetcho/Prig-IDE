//! El motor de aprendizaje por grafo de nodos (`/api/aprendizaje/*` de app.py): el grafo, un nodo, buscar, ejecutar
//! la tarea de un nodo, abrirla en el editor, marcar el progreso y las estadísticas. El motor está en
//! `prig_aprendizaje::grafo`; un error que en Python era una excepción responde 200 con `{"ok": false, "error"}`.

use std::collections::HashMap;
use std::sync::LazyLock;

use axum::{
    body::Bytes,
    extract::{Path, Query},
    http::StatusCode,
    response::Response,
};
use prig_aprendizaje::grafo::Motor;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, detalle, json_py};

static MOTOR: LazyLock<Motor> = LazyLock::new(Motor::default);

fn ok(v: Mapa) -> Response {
    json_py(StatusCode::OK, &Valor::Mapa(v))
}

fn fallo(e: String) -> Response {
    ok(Mapa::new().con("ok", false).con("error", e))
}

async fn en_hilo(f: impl FnOnce() -> Response + Send + 'static) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| fallo("error interno".into()))
}

/// `GET /api/aprendizaje/grafo?nivel=`
pub async fn grafo(Query(q): Query<HashMap<String, String>>) -> Response {
    en_hilo(move || match MOTOR.grafo(q.get("nivel").map(String::as_str)) {
        Ok(g) => ok(g),
        Err(e) => fallo(e),
    })
    .await
}

/// `GET /api/aprendizaje/nodo/{nodo_id}`
pub async fn nodo(Path(id): Path<String>) -> Response {
    en_hilo(move || match MOTOR.nodo(&id) {
        Ok(Some(n)) => ok(Mapa::new().con("ok", true).con("nodo", n)),
        Ok(None) => detalle(StatusCode::NOT_FOUND, format!("Nodo '{id}' no encontrado")),
        Err(e) => fallo(e),
    })
    .await
}

/// `GET /api/aprendizaje/buscar?q=&limite=15`
pub async fn buscar(Query(q): Query<HashMap<String, String>>) -> Response {
    let limite = match cuerpo::entero_consulta(&q, "limite", 15, i64::MIN, i64::MAX) {
        Ok(n) => n,
        Err(r) => return r,
    };
    let consulta = q.get("q").cloned().unwrap_or_default();
    en_hilo(move || {
        let r = MOTOR.buscar(&consulta, limite as i128);
        ok(Mapa::new()
            .con("ok", true)
            .con("total", r.len() as i128)
            .con("resultados", Valor::Lista(r.into_iter().map(Valor::Mapa).collect())))
    })
    .await
}

/// `POST /api/aprendizaje/nodo/{nodo_id}/ejecutar` (`{codigo: Optional[str] = "", usar_solucion: bool = False}`)
pub async fn ejecutar(Path(id): Path<String>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(&m, &[("codigo", &Tipo::Opcional(&Tipo::Texto), false), ("usar_solucion", &Tipo::Booleano, false)])
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let codigo = c.texto("codigo").unwrap_or("").to_string();
    let usar = c.verdad("usar_solucion");
    en_hilo(move || ok(MOTOR.ejecutar(&id, &codigo, usar))).await
}

/// `POST /api/aprendizaje/nodo/{nodo_id}/abrir_en_editor`
pub async fn abrir_en_editor(Path(id): Path<String>) -> Response {
    en_hilo(move || match MOTOR.abrir_en_editor(&id) {
        Ok(r) => ok(r),
        Err(e) => fallo(e),
    })
    .await
}

/// `POST /api/aprendizaje/nodo/{nodo_id}/progreso` (`{completado: bool = True}`)
pub async fn progreso(Path(id): Path<String>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("completado", &Tipo::Booleano, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let completado = c.get("completado").map(Valor::verdad).unwrap_or(true);
    en_hilo(move || match MOTOR.marcar(&id, completado, None) {
        Ok(()) => ok(Mapa::new().con("ok", true).con("nodo_id", id).con("completado", completado)),
        Err(e) => fallo(e),
    })
    .await
}

/// `GET /api/aprendizaje/estadisticas`
pub async fn estadisticas() -> Response {
    en_hilo(|| match MOTOR.estadisticas() {
        Ok(e) => ok(Mapa::new().con("ok", true).con("estadisticas", e)),
        Err(e) => fallo(e),
    })
    .await
}
