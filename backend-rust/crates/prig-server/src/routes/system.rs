//! Salud del servidor y telemetría propia de Rust. `/api/system/stats` y `/api/system/health` los atiende Python
//! (lee la GPU por NVML; lanzar nvidia-smi en cada consulta calentaba la CPU) por el proxy.

use axum::{extract::State, response::Json};
use prig_hardware::{HardwareMonitor, HardwareTelemetry};
use serde_json::{json, Value};
use std::time::Duration;

use crate::state::AppState;

/// ¿Responde el backend de Python? (una conexión TCP corta, sin pedirle nada)
async fn respaldo_activo(state: &AppState) -> bool {
    let destino = state.fallback_url.trim_start_matches("http://").trim_end_matches('/').to_string();
    matches!(
        tokio::time::timeout(Duration::from_millis(300), tokio::net::TcpStream::connect(destino)).await,
        Ok(Ok(_))
    )
}

/// GET /api/health
pub async fn health_check(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "status": "ok",
        "servidor": "prig-server",
        "segundos": (state.start_time.elapsed().as_secs_f64() * 10.0).round() / 10.0,
        "respaldo": { "url": state.fallback_url, "activo": respaldo_activo(&state).await }
    }))
}

/// GET /api/hardware, /api/system/hardware
pub async fn get_hardware_telemetry() -> Json<HardwareTelemetry> {
    Json(tokio::task::spawn_blocking(HardwareMonitor::read_telemetry).await.unwrap_or_else(|_| HardwareTelemetry {
        cpu_temp_c: None,
        thermal_zones: Vec::new(),
        memory: None,
        cpu: None,
    }))
}
