//! Todo lo que no atiende Rust va al backend de Python, tal cual: HTTP (con las respuestas en streaming) y
//! WebSocket (`/ws/audio_reactivo`). Si Python no responde (arrancando o reiniciándose), la petición espera hasta
//! `plazo_respaldo`; pasado ese plazo sin respuesta, fallan enseguida con 502 hasta que vuelva.

use axum::{
    body::Body,
    extract::{
        ws::{CloseFrame, Message as MensajeAxum, WebSocket, WebSocketUpgrade},
        FromRequestParts, Request, State,
    },
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use futures_util::{SinkExt, StreamExt};
use http_body_util::BodyExt;
use serde_json::json;
use std::time::{Duration, Instant};
use tokio_tungstenite::tungstenite::protocol::{frame::coding::CloseCode, CloseFrame as CierreTungstenite};
use tokio_tungstenite::tungstenite::Message as MensajeTungstenite;
use tracing::{debug, warn};

use crate::state::AppState;

fn es_hop_by_hop(nombre: &str) -> bool {
    matches!(
        nombre,
        "connection" | "keep-alive" | "proxy-authenticate" | "proxy-authorization" | "te" | "trailers" | "transfer-encoding" | "upgrade" | "host"
    )
}

fn es_websocket(cabeceras: &HeaderMap) -> bool {
    cabeceras
        .get(header::UPGRADE)
        .and_then(|v| v.to_str().ok())
        .map(|v| v.eq_ignore_ascii_case("websocket"))
        .unwrap_or(false)
}

fn sin_respaldo(destino: &str, detalle: String) -> Response {
    (
        StatusCode::BAD_GATEWAY,
        Json(json!({
            "ok": false,
            "detail": "El backend de Python de Prig no responde.",
            "error": "Backend Python de respaldo no disponible",
            "target": destino,
            "detalle": detalle
        })),
    )
        .into_response()
}

/// ¿Esperar a Python o fallar ya? Espera mientras no lleve más de `plazo_respaldo` sin responder.
async fn puede_esperar(state: &AppState) -> bool {
    let mut r = state.respaldo.lock().await;
    let desde = *r.caido_desde.get_or_insert_with(Instant::now);
    desde.elapsed() < state.plazo_respaldo
}

/// ¿La petición no llegó a Python? Sin conexión, o la conexión reutilizada del pool ya estaba cerrada porque Python
/// murió (sin esto, la primera petición después de un reinicio fallaba con 502 en vez de esperar).
fn no_llego(e: &reqwest::Error) -> bool {
    if e.is_connect() {
        return true;
    }
    let mut fuente: Option<&(dyn std::error::Error + 'static)> = std::error::Error::source(e);
    while let Some(f) = fuente {
        if let Some(io) = f.downcast_ref::<std::io::Error>() {
            use std::io::ErrorKind::*;
            if matches!(io.kind(), ConnectionReset | ConnectionAborted | ConnectionRefused | BrokenPipe | UnexpectedEof) {
                return true;
            }
        }
        if f.to_string().contains("connection closed before message completed") {
            return true;
        }
        fuente = f.source();
    }
    false
}

async fn respaldo_responde(state: &AppState) {
    state.respaldo.lock().await.caido_desde = None;
}

pub async fn proxy_fallback(State(state): State<AppState>, req: Request) -> Response {
    if es_websocket(req.headers()) {
        return proxy_websocket(state, req).await;
    }
    let method = req.method().clone();
    let uri = req.uri().clone();
    let ruta = uri.path_and_query().map(|pq| pq.as_str()).unwrap_or_else(|| uri.path()).to_string();
    let destino = format!("{}{}", state.fallback_url.trim_end_matches('/'), ruta);
    debug!("Proxy: {} {} -> {}", method, uri, destino);

    let mut cabeceras = HeaderMap::new();
    for (nombre, valor) in req.headers() {
        if !es_hop_by_hop(nombre.as_str()) {
            cabeceras.append(nombre.clone(), valor.clone());
        }
    }
    let cuerpo = match req.into_body().collect().await {
        Ok(c) => c.to_bytes(),
        Err(err) => {
            return (StatusCode::BAD_REQUEST, Json(json!({"detail": format!("Error leyendo el cuerpo de la petición: {err}")})))
                .into_response()
        }
    };

    let respuesta = loop {
        let mut pedido = state.http_client.request(method.clone(), &destino).headers(cabeceras.clone());
        if !cuerpo.is_empty() {
            pedido = pedido.body(cuerpo.clone());
        }
        match pedido.send().await {
            Ok(r) => {
                respaldo_responde(&state).await;
                break r;
            }
            // Sin conexión (Python arrancando o reiniciándose): se espera un poco y se reintenta
            Err(e) if no_llego(&e) && puede_esperar(&state).await => {
                tokio::time::sleep(Duration::from_millis(250)).await;
            }
            Err(e) => {
                warn!("Backend de Python no disponible en {}: {}", destino, e);
                return sin_respaldo(&destino, e.to_string());
            }
        }
    };

    let mut salida = Response::builder().status(respuesta.status());
    if let Some(h) = salida.headers_mut() {
        for (nombre, valor) in respuesta.headers() {
            let n = nombre.as_str();
            // Las de CORS las pone este servidor (CorsLayer): duplicadas, el navegador rechaza la respuesta
            if !es_hop_by_hop(n) && !n.starts_with("access-control-") {
                h.append(nombre.clone(), valor.clone());
            }
        }
    }
    salida.body(Body::from_stream(respuesta.bytes_stream())).unwrap_or_else(|err| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"detail": format!("Error armando la respuesta: {err}")}))).into_response()
    })
}

// =========================================================================
// WebSocket
// =========================================================================

async fn proxy_websocket(state: AppState, req: Request) -> Response {
    let (mut partes, _cuerpo) = req.into_parts();
    let ws = match WebSocketUpgrade::from_request_parts(&mut partes, &state).await {
        Ok(ws) => ws,
        Err(rechazo) => return rechazo.into_response(),
    };
    let ruta = partes.uri.path_and_query().map(|pq| pq.as_str().to_string()).unwrap_or_else(|| partes.uri.path().to_string());
    let base = state.fallback_url.trim_end_matches('/');
    let destino = match base.strip_prefix("https://") {
        Some(resto) => format!("wss://{resto}{ruta}"),
        None => format!("ws://{}{}", base.trim_start_matches("http://"), ruta),
    };
    // Primero se conecta con Python: si no está, el navegador recibe un 502 en vez de un WebSocket que se cierra
    let arriba = loop {
        match tokio_tungstenite::connect_async(destino.as_str()).await {
            Ok((s, _)) => {
                respaldo_responde(&state).await;
                break s;
            }
            Err(tokio_tungstenite::tungstenite::Error::Io(e)) if puede_esperar(&state).await => {
                debug!("WebSocket a {} sin respuesta ({}): se reintenta", destino, e);
                tokio::time::sleep(Duration::from_millis(250)).await;
            }
            Err(e) => return sin_respaldo(&destino, e.to_string()),
        }
    };
    ws.on_upgrade(move |cliente| puente(cliente, arriba))
}

fn a_python(m: MensajeAxum) -> MensajeTungstenite {
    match m {
        MensajeAxum::Text(t) => MensajeTungstenite::Text(t),
        MensajeAxum::Binary(b) => MensajeTungstenite::Binary(b),
        MensajeAxum::Ping(b) => MensajeTungstenite::Ping(b),
        MensajeAxum::Pong(b) => MensajeTungstenite::Pong(b),
        MensajeAxum::Close(c) => MensajeTungstenite::Close(c.map(|c| CierreTungstenite { code: CloseCode::from(c.code), reason: c.reason })),
    }
}

fn al_navegador(m: MensajeTungstenite) -> Option<MensajeAxum> {
    Some(match m {
        MensajeTungstenite::Text(t) => MensajeAxum::Text(t),
        MensajeTungstenite::Binary(b) => MensajeAxum::Binary(b),
        MensajeTungstenite::Ping(b) => MensajeAxum::Ping(b),
        MensajeTungstenite::Pong(b) => MensajeAxum::Pong(b),
        MensajeTungstenite::Close(c) => MensajeAxum::Close(c.map(|c| CloseFrame { code: u16::from(c.code), reason: c.reason })),
        MensajeTungstenite::Frame(_) => return None,
    })
}

async fn puente(
    cliente: WebSocket,
    arriba: tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>,
) {
    let (mut cliente_tx, mut cliente_rx) = cliente.split();
    let (mut arriba_tx, mut arriba_rx) = arriba.split();
    let hacia_python = async {
        while let Some(Ok(m)) = cliente_rx.next().await {
            let cierre = matches!(m, MensajeAxum::Close(_));
            if arriba_tx.send(a_python(m)).await.is_err() || cierre {
                break;
            }
        }
        let _ = arriba_tx.close().await;
    };
    let hacia_navegador = async {
        while let Some(Ok(m)) = arriba_rx.next().await {
            let Some(m) = al_navegador(m) else { continue };
            let cierre = matches!(m, MensajeAxum::Close(_));
            if cliente_tx.send(m).await.is_err() || cierre {
                break;
            }
        }
        let _ = cliente_tx.close().await;
    };
    // Cuando un lado termina, se cierran los dos
    tokio::select! {
        _ = hacia_python => {},
        _ = hacia_navegador => {},
    }
}
