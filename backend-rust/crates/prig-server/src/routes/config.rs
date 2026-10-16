//! La configuración del entorno (`GET /api/config/*`) con la lógica de `prig_plataforma::perfiles` (la misma que
//! usa `perfiles_config.py`): cada lectura va al JSON de `<Prig>/.prig_dataset/`, así que no hay estado que pueda
//! separarse del de Python. Guardar (POST) lo sigue haciendo Python por el proxy.

use axum::{extract::State, http::StatusCode, response::Response};
use prig_plataforma::perfiles;
use prig_plataforma::valor::{Mapa, Valor};
use std::path::PathBuf;

use crate::routes::json_py;
use crate::state::AppState;

fn dataset(state: &AppState) -> PathBuf {
    state.base_dir.join(".prig_dataset")
}

fn avisar(avisos: Vec<String>) {
    for a in avisos {
        tracing::warn!("{a}");
    }
}

/// `_cargar_json(<archivo>, {})`
fn seccion(state: &AppState, archivo: &str) -> Valor {
    let dir = dataset(state);
    let mut avisos = Vec::new();
    let v = perfiles::cargar(&dir, &dir.join(archivo), Valor::Mapa(Mapa::new()), &mut avisos);
    avisar(avisos);
    v
}

fn perfiles_de(state: &AppState) -> Valor {
    let dir = dataset(state);
    let mut avisos = Vec::new();
    let v = perfiles::cargar_perfiles(&dir, &dir.join("config_profiles.json"), &mut avisos);
    avisar(avisos);
    v
}

/// El archivo de cada sección (las RUTA_* de perfiles_config.py)
fn archivo(seccion: &str) -> &'static str {
    match seccion {
        "apariencia" => "apariencia.json",
        "sintaxis" => "sintaxis_personalizada.json",
        "motor_movimiento" => "motor_movimiento.json",
        "accesibilidad" => "accesibilidad.json",
        _ => "audio_reactivo.json",
    }
}

macro_rules! ruta_seccion {
    ($nombre:ident, $seccion:literal) => {
        pub async fn $nombre(State(state): State<AppState>) -> Response {
            let v = tokio::task::spawn_blocking(move || seccion(&state, archivo($seccion))).await.unwrap_or(Valor::Nulo);
            json_py(StatusCode::OK, &v)
        }
    };
}

ruta_seccion!(apariencia, "apariencia");
ruta_seccion!(sintaxis, "sintaxis");
ruta_seccion!(motor_movimiento, "motor_movimiento");
ruta_seccion!(accesibilidad, "accesibilidad");
ruta_seccion!(audio_reactivo, "audio_reactivo");

pub async fn profiles(State(state): State<AppState>) -> Response {
    let v = tokio::task::spawn_blocking(move || perfiles_de(&state)).await.unwrap_or(Valor::Nulo);
    json_py(StatusCode::OK, &v)
}

/// `cargar_estado_completo()`: las secciones en el orden de Python
pub async fn estado_completo(State(state): State<AppState>) -> Response {
    let v = tokio::task::spawn_blocking(move || {
        let mut m = Mapa::new();
        for s in ["apariencia", "sintaxis", "motor_movimiento", "audio_reactivo", "accesibilidad"] {
            m.poner(s, seccion(&state, archivo(s)));
        }
        m.poner("perfiles", perfiles_de(&state));
        Valor::Mapa(m)
    })
    .await
    .unwrap_or(Valor::Nulo);
    json_py(StatusCode::OK, &v)
}

// ---------------------------------------------------------------------------------------------- guardar

use axum::body::Bytes;
use crate::routes::{cuerpo, detalle};

fn guardar(state: &AppState, archivo: &str, datos: &Valor) -> bool {
    let dir = dataset(state);
    let mut avisos = Vec::new();
    let ok = perfiles::guardar(&dir, &dir.join(archivo), datos, &mut avisos);
    avisar(avisos);
    ok
}

/// `POST /api/config/<sección>`: el JSON tal cual al archivo; `{"ok": true}` o 500 con el texto de Python
async fn guardar_seccion(state: AppState, seccion: &'static str, nombre_error: &'static str, b: Bytes) -> Response {
    let datos = match cuerpo::dict(&b) {
        Ok(m) => Valor::Mapa(m),
        Err(r) => return r,
    };
    let ok = tokio::task::spawn_blocking(move || guardar(&state, archivo(seccion), &datos)).await.unwrap_or(false);
    if ok {
        json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("ok", true)))
    } else {
        detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("No se pudo guardar {nombre_error} en disco."))
    }
}

macro_rules! ruta_guardar {
    ($nombre:ident, $seccion:literal, $error:literal) => {
        pub async fn $nombre(State(state): State<AppState>, b: Bytes) -> Response {
            guardar_seccion(state, $seccion, $error, b).await
        }
    };
}

ruta_guardar!(guardar_apariencia, "apariencia", "la apariencia");
ruta_guardar!(guardar_sintaxis, "sintaxis", "la configuración de sintaxis");
ruta_guardar!(guardar_motor_movimiento, "motor_movimiento", "la configuración del motor de movimiento");
ruta_guardar!(guardar_audio_reactivo, "audio_reactivo", "la configuración de audio reactivo");
ruta_guardar!(guardar_accesibilidad, "accesibilidad", "la accesibilidad");

/// `POST /api/config/profiles` (PerfilGuardarRequest: `perfil_activo: Optional[str]`, `perfiles: List[Dict]`)
pub async fn guardar_perfiles(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let activo = c.texto("perfil_activo", Some(Valor::Texto("catppuccin_equilibrado".into())));
    let perfiles = c.lista_de_dicts("perfiles");
    if let Err(r) = c.fin() {
        return r;
    }
    // req.model_dump(): los campos del modelo, en su orden
    let datos = Valor::Mapa(Mapa::new().con("perfil_activo", activo.clone()).con("perfiles", Valor::Lista(perfiles)));
    let ok = tokio::task::spawn_blocking(move || guardar(&state, "config_profiles.json", &datos)).await.unwrap_or(false);
    if !ok {
        return detalle(StatusCode::INTERNAL_SERVER_ERROR, "No se pudo guardar la configuración de perfiles en disco.");
    }
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("exito", true).con("perfil_activo", activo)))
}

/// `POST /api/config/profiles/reset`: los perfiles de fábrica
pub async fn restablecer_perfiles(State(state): State<AppState>) -> Response {
    let datos = Valor::Mapa(Mapa::new().con("perfil_activo", "catppuccin_equilibrado").con("perfiles", perfiles::predeterminados()));
    let d = datos.clone();
    let _ = tokio::task::spawn_blocking(move || guardar(&state, "config_profiles.json", &d)).await;
    json_py(StatusCode::OK, &datos)
}

/// `POST /api/config/estado_completo`: cada sección que venga como objeto, en el orden de Python
pub async fn guardar_estado_completo(State(state): State<AppState>, b: Bytes) -> Response {
    let datos = match cuerpo::dict(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let res = tokio::task::spawn_blocking(move || {
        let mut res = Mapa::new();
        for s in perfiles::SECCIONES {
            if let Some(v @ Valor::Mapa(_)) = datos.get(s) {
                let archivo = if s == "perfiles" { "config_profiles.json" } else { archivo(s) };
                res.poner(s, guardar(&state, archivo, v));
            }
        }
        res
    })
    .await
    .unwrap_or_default();
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("ok", true).con("detalle", res)))
}
