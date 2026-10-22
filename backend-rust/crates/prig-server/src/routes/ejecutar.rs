//! Ejecutar el código del editor y de los cuadernos (`prig_plataforma::ejecucion`): `POST /api/run`,
//! `/api/run/cancel`, `/api/notebook/cell/run` y `/api/notebook/session/reset`. El tiempo límite es el de la
//! configuración de IA (`exec_timeout`).

use axum::{
    body::Bytes,
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{cuerpo, json_py};
use crate::state::AppState;

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

async fn bloque<F: FnOnce() -> Mapa + Send + 'static>(f: F) -> Response {
    match tokio::task::spawn_blocking(f).await {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

/// `_exec_timeout()`: `max(1, int(exec_timeout))`, o 25 si no es un número
pub fn tiempo_limite() -> i64 {
    let n = match prig_ia::motor::config_ia().get("exec_timeout") {
        Some(Valor::Entero(n)) => i64::try_from(*n).ok(),
        Some(Valor::Bool(b)) => Some(*b as i64),
        Some(Valor::Real(x)) if x.is_finite() => Some(x.trunc() as i64),
        Some(Valor::Texto(t)) => t.trim().parse::<i64>().ok(),
        _ => None,
    };
    n.map(|n| n.max(1)).unwrap_or(25)
}

fn opcional(c: &Mapa, k: &str) -> Option<String> {
    c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py)
}

/// `POST /api/run` (`path`, `run_id`): no responde hasta que termina
pub async fn ejecutar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("path", &Tipo::Texto, true), ("run_id", &TEXTO_OPC, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    bloque(move || {
        let ruta = c.valor("path").texto_py();
        let id = opcional(&c, "run_id");
        state.ejecutor.ejecutar_archivo(&ruta, None, Some(tiempo_limite()), id.as_deref(), &[])
    })
    .await
}

/// `POST /api/run/cancel` (`run_id`)
pub async fn cancelar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("run_id", &Tipo::Texto, true)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    bloque(move || state.ejecutor.cancelar(&c.valor("run_id").texto_py())).await
}

/// `POST /api/notebook/cell/run` (`code`, `path`): en la sesión del cuaderno (una por ruta), junto al cuaderno
pub async fn celda(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("code", &Tipo::Texto, true), ("path", &TEXTO_OPC, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let ruta = opcional(&c, "path").filter(|p| !p.is_empty());
    let cwd = match &ruta {
        Some(p) => prig_plataforma::py::dirname(p),
        None => espacio_de_trabajo(&state).await.to_string_lossy().into_owned(),
    };
    bloque(move || {
        let sesion = opcional(&c, "path");
        state.ejecutor.ejecutar_celda(&c.valor("code").texto_py(), Some(&cwd), sesion.as_deref(), Some(tiempo_limite()))
    })
    .await
}

/// `POST /api/notebook/session/reset` (`path`): descarta las variables del cuaderno
pub async fn reiniciar_sesion(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("path", &TEXTO_OPC, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    bloque(move || {
        let sesion = opcional(&c, "path");
        Mapa::new().con("status", "ok").con("restarted", state.ejecutor.sesiones.reiniciar(sesion.as_deref()))
    })
    .await
}
