//! El motor MoE (`prig_ia::motor`): este servidor es el único dueño de su llama-server. Mientras el chat y la lectura
//! por unidades sigan en Python, `ai_engine/motor_moe.py` es un cliente de estas rutas (como lo es de Ollama):
//!
//! * `POST /api/moe/ollama/chat` y `/api/moe/ollama/generate`: una petición de Ollama servida por el motor (NDJSON en
//!   streaming o el objeto entero). `_prig_liberar`: los modelos de Ollama que cargó Prig, para descargarlos antes de
//!   arrancar el motor y dejarle la VRAM.
//! * `POST /api/moe/directo`: una petición cruda a llama-server (la lectura por unidades).
//! * `GET /api/moe/estado`, `POST /api/moe/detener`, `/podar`, `/olvidar`, `/ultimo_proyecto`.

#![allow(clippy::result_large_err)]

use axum::{
    body::{Body, Bytes},
    extract::{Path as Ruta, State},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
};
use prig_ia::motor::{self, Motor, Respuesta};
use prig_plataforma::valor::{Mapa, Valor};
use std::sync::Arc;

use crate::routes::{detalle, json_py};
use crate::state::AppState;

fn el_motor(state: &AppState) -> Arc<Motor> {
    motor::global(&state.base_dir)
}

fn cuerpo(b: &Bytes) -> Result<Mapa, Response> {
    match prig_plataforma::json::leer(&String::from_utf8_lossy(b)) {
        Ok(Valor::Mapa(m)) => Ok(m),
        _ => Err(detalle(StatusCode::BAD_REQUEST, "Se esperaba un objeto JSON.")),
    }
}

/// La URL de Ollama de los ajustes de IA (o la de siempre)
/// `_descargar_ollama`: descarga de Ollama los modelos de Prig que estén cargados (los de otros programas, no)
fn descargar_de_ollama(propios: Vec<String>) {
    prig_ia::ollama::descargar_propios(&propios);
}

/// `POST /api/moe/ollama/{chat|generate}`
pub async fn ollama_compatible(State(state): State<AppState>, Ruta(tipo): Ruta<String>, b: Bytes) -> Response {
    if tipo != "chat" && tipo != "generate" {
        return detalle(StatusCode::NOT_FOUND, "Not Found");
    }
    let mut pedido = match cuerpo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let propios: Vec<String> = match pedido.quitar("_prig_liberar") {
        Some(Valor::Lista(l)) => l.iter().filter_map(|x| if let Valor::Texto(t) = x { Some(t.clone()) } else { None }).collect(),
        _ => Vec::new(),
    };
    let timeout = pedido.quitar("_prig_timeout").and_then(|v| v.num()).unwrap_or(600.0);
    let m = el_motor(&state);
    m.poner_liberar(if propios.is_empty() { None } else { Some(Arc::new(move || descargar_de_ollama(propios.clone()))) });
    let ruta = format!("/api/{tipo}");
    let r = tokio::task::spawn_blocking(move || m.post(&ruta, &Valor::Mapa(pedido), timeout, false)).await;
    match r {
        Ok(Respuesta::Entera(estado, v)) => {
            let s = StatusCode::from_u16(estado).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
            ([(header::CONTENT_TYPE, "application/json")], prig_plataforma::json::escribir_linea(&v)).into_response().with_status(s)
        }
        Ok(Respuesta::Flujo(flujo, guarda)) => {
            let (tx, rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(64);
            std::thread::Builder::new()
                .name("moe-ndjson".into())
                .spawn(move || {
                    let _guarda = guarda; // se descuenta la petición al terminar (o al cortar)
                    loop {
                        let linea = match flujo.siguiente() {
                            Ok(Some(v)) => prig_plataforma::json::escribir_linea(&v),
                            Ok(None) => break,
                            Err(e) => prig_plataforma::json::escribir_linea(&Valor::Mapa(Mapa::new().con("error", e))),
                        };
                        if tx.blocking_send(Ok(Bytes::from(linea + "\n"))).is_err() {
                            // quien preguntó cerró la conexión («Detener»): llama-server deja de generar
                            flujo.cerrar();
                            break;
                        }
                    }
                })
                .ok();
            let flujo = futures_util::stream::unfold(rx, |mut rx| async move { rx.recv().await.map(|x| (x, rx)) });
            let cuerpo = Body::from_stream(flujo);
            ([(header::CONTENT_TYPE, "application/x-ndjson")], cuerpo).into_response()
        }
        Err(_) => detalle(StatusCode::INTERNAL_SERVER_ERROR, "El motor MoE falló."),
    }
}

trait ConEstado {
    fn with_status(self, s: StatusCode) -> Response;
}
impl ConEstado for Response {
    fn with_status(mut self, s: StatusCode) -> Response {
        *self.status_mut() = s;
        self
    }
}

/// `POST /api/moe/directo` (`metodo`, `ruta`, `cuerpo`, `timeout`): petición cruda a llama-server
pub async fn directo(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let metodo = c.texto("metodo").unwrap_or("POST").to_uppercase();
    let Some(ruta) = c.texto("ruta").filter(|r| r.starts_with('/')).map(String::from) else {
        return detalle(StatusCode::BAD_REQUEST, "Falta la ruta de llama-server.");
    };
    let datos = c.get("cuerpo").cloned().filter(|v| !v.es_nulo());
    let timeout = c.num("timeout").unwrap_or(900.0);
    let m = el_motor(&state);
    match tokio::task::spawn_blocking(move || m.directo(&metodo, &ruta, datos.as_ref(), timeout)).await {
        Ok(Ok(v)) => json_py(StatusCode::OK, &v),
        Ok(Err(e)) => detalle(StatusCode::BAD_GATEWAY, &e),
        Err(_) => detalle(StatusCode::INTERNAL_SERVER_ERROR, "El motor MoE falló."),
    }
}

/// `GET /api/moe/estado`: el estado del panel y lo que necesitan el modo frío y el banco
pub async fn estado(State(state): State<AppState>) -> Response {
    let m = el_motor(&state);
    match tokio::task::spawn_blocking(move || {
        let mut e = m.estado();
        e.poner("generando", m.generando());
        e.poner("contexto_deseado", m.contexto_actual_deseado() as i128);
        e
    })
    .await
    {
        Ok(e) => json_py(StatusCode::OK, &Valor::Mapa(e)),
        Err(_) => detalle(StatusCode::INTERNAL_SERVER_ERROR, "El motor MoE falló."),
    }
}

/// `POST /api/moe/{detener|podar|olvidar|ultimo_proyecto}`
pub async fn accion(State(state): State<AppState>, Ruta(accion): Ruta<String>) -> Response {
    let m = el_motor(&state);
    let r = tokio::task::spawn_blocking(move || match accion.as_str() {
        "detener" => {
            m.detener();
            Some(Mapa::new().con("ok", true))
        }
        "podar" => Some(Mapa::new().con("borrados", m.podar() as i128)),
        "olvidar" => Some(Mapa::new().con("borrados", m.olvidar_proyectos() as i128)),
        // lo que hizo el motor con el prefijo de la última conversación; se olvida al leerlo
        "ultimo_proyecto" => Some(Mapa::new().con("proyecto", Valor::Mapa(std::mem::take(&mut m.estado_mut().ultimo_proyecto)))),
        _ => None,
    })
    .await;
    match r {
        Ok(Some(v)) => json_py(StatusCode::OK, &Valor::Mapa(v)),
        Ok(None) => detalle(StatusCode::NOT_FOUND, "Not Found"),
        Err(_) => detalle(StatusCode::INTERNAL_SERVER_ERROR, "El motor MoE falló."),
    }
}

/// Al arrancar Prig: cierra los llama-server del motor que dejó una sesión anterior (salvo que se pida no hacerlo: un
/// segundo servidor, como el comparador de rutas, tocaría el del Prig abierto)
pub fn limpiar_huerfanos(raiz: &std::path::Path) -> usize {
    if std::env::var("PRIG_SIN_LIMPIAR_HUERFANOS").as_deref() == Ok("1") {
        return 0;
    }
    motor::limpiar_huerfanos(&raiz.join("lib/moe/llama-server"), None)
}

/// Al cerrar Prig: para el llama-server del motor y el `ollama serve` que arrancó Prig (si los hay)
pub fn detener() {
    motor::detener_global();
    prig_ia::ollama::detener_propio();
}

/// `GET /api/moe/actividad`: lo que mira el modo frío cada pocos segundos (sin leer el disco)
pub async fn actividad(State(state): State<AppState>) -> Response {
    let m = el_motor(&state);
    let pid = m.pid().map(|p| Valor::Entero(p as i128)).unwrap_or(Valor::Nulo);
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("generando", m.generando()).con("pid", pid)))
}

/// `_moe_estado`: el estado del motor, sus ajustes y los modos
fn estado_del_panel(m: &Motor) -> Mapa {
    let cfg = motor::config_de_ia();
    let ajustes = Mapa::new()
        .con("contexto", cfg.valor("moe_contexto").clone())
        .con("hilos", cfg.valor("moe_hilos").clone())
        .con("calientes", cfg.valor("moe_calientes").clone())
        .con("modo", cfg.valor("moe_modo").clone())
        .con("mtp", cfg.valor("moe_mtp").clone())
        .con("nucleo", cfg.valor("moe_nucleo").clone())
        .con("cache_gb", cfg.valor("moe_cache_gb").clone())
        .con("cache_reserva_gb", cfg.valor("moe_cache_reserva_gb").clone());
    m.estado()
        .con("ajustes", ajustes)
        .con("modos", Valor::Lista(motor::MODOS.iter().map(|(n, _)| Valor::Texto(n.to_string())).collect()))
}

/// `GET /api/recursos/moe`
pub async fn panel(State(state): State<AppState>) -> Response {
    let m = el_motor(&state);
    match tokio::task::spawn_blocking(move || estado_del_panel(&m)).await {
        Ok(e) => json_py(StatusCode::OK, &Valor::Mapa(e)),
        Err(_) => detalle(StatusCode::INTERNAL_SERVER_ERROR, "El motor MoE falló."),
    }
}

/// `POST /api/recursos/moe`: los ajustes valen en el próximo arranque del motor; «detener» lo para ya
pub async fn panel_ajustar(State(state): State<AppState>, b: Bytes) -> Response {
    use crate::routes::cuerpo;
    let c = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut campos = cuerpo::Campos::new(&c);
    let contexto = campos.texto("contexto", Some(Valor::Nulo));
    let calientes = campos.texto("calientes", Some(Valor::Nulo));
    let modo = campos.texto("modo", Some(Valor::Nulo));
    let nucleo = campos.texto("nucleo", Some(Valor::Nulo));
    let mtp = campos.booleano_opcional("mtp");
    let detener = campos.booleano_opcional("detener").unwrap_or(false);
    let olvidar = campos.booleano_opcional("olvidar_proyectos").unwrap_or(false);
    let hilos = match c.get("hilos") {
        None | Some(Valor::Nulo) => None,
        Some(_) => campos.entero("hilos"),
    };
    if let Err(r) = campos.fin() {
        return r;
    }
    let real = |k: &str| -> Result<Option<f64>, Response> {
        match c.get(k) {
            None | Some(Valor::Nulo) => Ok(None),
            Some(v) => v.num().or_else(|| v.texto_py().trim().parse().ok()).map(Some).ok_or_else(|| detalle(StatusCode::UNPROCESSABLE_ENTITY, format!("{k}: un número"))),
        }
    };
    let (cache, reserva) = match (real("cache_gb"), real("cache_reserva_gb")) {
        (Ok(a), Ok(b)) => (a, b),
        (Err(r), _) | (_, Err(r)) => return r,
    };
    let mut cambios = Mapa::new();
    if let Valor::Texto(t) = &contexto {
        let v = t.trim().to_lowercase();
        if v == "auto" {
            cambios.poner("moe_contexto", "auto");
        } else {
            match v.parse::<i64>() {
                Ok(n) => cambios.poner("moe_contexto", n.clamp(2048, prig_ia::moe::CONTEXTO_MAX) as i128),
                Err(_) => return detalle(StatusCode::BAD_REQUEST, "contexto: «auto» o un número de tokens"),
            }
        }
    }
    if let Some(h) = hilos {
        cambios.poner("moe_hilos", h.clamp(0, 16));
    }
    if let Valor::Texto(t) = &calientes {
        let v = t.trim().to_lowercase();
        if v == "auto" {
            cambios.poner("moe_calientes", "auto");
        } else {
            match v.parse::<i64>() {
                Ok(n) => cambios.poner("moe_calientes", n.clamp(0, 128) as i128),
                Err(_) => return detalle(StatusCode::BAD_REQUEST, "calientes: «auto» o un número"),
            }
        }
    }
    if let Valor::Texto(t) = &modo {
        if !motor::MODOS.iter().any(|(n, _)| n == t) {
            return detalle(StatusCode::BAD_REQUEST, format!("modo: uno de {}", motor::MODOS.iter().map(|m| m.0).collect::<Vec<_>>().join(", ")));
        }
        cambios.poner("moe_modo", t.clone());
    }
    if let Some(b) = mtp {
        cambios.poner("moe_mtp", b);
    }
    if let Valor::Texto(t) = &nucleo {
        if t != "q8" && t != "q4" {
            return detalle(StatusCode::BAD_REQUEST, "nucleo: q8 o q4");
        }
        cambios.poner("moe_nucleo", t.clone());
    }
    if let Some(x) = cache {
        if !(0.0..=2000.0).contains(&x) {
            return detalle(StatusCode::BAD_REQUEST, "cache_gb: entre 0 y 2000 GB (0 = no guardar)");
        }
        cambios.poner("moe_cache_gb", Valor::Real(x));
    }
    if let Some(x) = reserva {
        if !(0.0..=1000.0).contains(&x) {
            return detalle(StatusCode::BAD_REQUEST, "cache_reserva_gb: entre 0 y 1000 GB");
        }
        cambios.poner("moe_cache_reserva_gb", Valor::Real(x));
    }
    let m = el_motor(&state);
    let podar = cache.is_some() || reserva.is_some();
    let r = tokio::task::spawn_blocking(move || {
        if !cambios.is_empty() {
            motor::guardar_config_de_ia(&cambios).map_err(|e| e.to_string())?;
        }
        if podar {
            m.podar(); // el tope nuevo se aplica ya
        }
        if detener {
            m.detener();
        }
        if olvidar {
            m.olvidar_proyectos();
        }
        Ok::<_, String>(estado_del_panel(&m))
    })
    .await;
    match r {
        Ok(Ok(e)) => json_py(StatusCode::OK, &Valor::Mapa(e)),
        Ok(Err(e)) => detalle(StatusCode::INTERNAL_SERVER_ERROR, &e),
        Err(_) => detalle(StatusCode::INTERNAL_SERVER_ERROR, "El motor MoE falló."),
    }
}
