//! La cola de descargas de modelos (`/api/descargas*`, `prig_ia::descargas`) y la inspección de un repositorio entero
//! de Hugging Face para copiarlo completo (`/api/buscador/hf/inspeccionar_completo`, `prig_ia::descargas_hf`).

use std::collections::HashMap;
use std::sync::{Arc, OnceLock};

use axum::{
    body::Bytes,
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_ia::descargas::{Cola, Config};
use prig_ia::descargas_hf::{self as hf, ErrorHf};
use prig_ia::{gestor, ollama};
use prig_modelos::explorar as x;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::buscador::de_error;
use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);

fn ok(v: Valor) -> Response {
    json_py(StatusCode::OK, &v)
}

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

async fn bloque<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| error_500())
}

/// La cola, una para todo el servidor; se crea con la primera petición
fn cola(state: &AppState) -> Arc<Cola> {
    static COLA: OnceLock<Arc<Cola>> = OnceLock::new();
    COLA.get_or_init(|| {
        let raiz = state.base_dir.clone();
        let raiz2 = raiz.clone();
        let st = state.clone();
        let rt = tokio::runtime::Handle::current();
        Cola::new(Config {
            base: Box::new(|| ollama::base_url().trim_end_matches('/').to_string()),
            carpeta: Box::new(move || {
                crate::routes::modelos::carpeta_servidor(&raiz).filter(|c| !c.is_empty()).unwrap_or_else(prig_modelos::gestion::carpeta_modelos)
            }),
            al_terminar: Box::new(move |item: &Mapa| {
                gestor::gestor(&raiz2).olvidar_fichas();
                x::marcar_actualizado(&item.valor("ref").texto_py());
            }),
            espacio: Box::new(move || rt.block_on(crate::routes::workspace::espacio_de_trabajo(&st)).to_string_lossy().into_owned()),
            comprobar: Box::new(x::comprobar),
        })
    })
    .clone()
}

/// El `id_: int` de la ruta, con el 422 de FastAPI
fn id_de(crudo: &str) -> Result<i128, Response> {
    crudo.trim().parse::<i128>().map_err(|_| {
        cuerpo::respuesta(vec![cuerpo::Error {
            tipo: "int_parsing",
            loc: vec!["path".into(), "id_".into()],
            msg: "Input should be a valid integer, unable to parse string as an integer".into(),
            entrada: Valor::Texto(crudo.to_string()),
            ctx: None,
        }])
    })
}

/// `POST /api/descargas` `{ref, titulo?, tipo?, variante?, destino?}`
pub async fn encolar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(
            &m,
            &[
                ("ref", &Tipo::Texto, true),
                ("titulo", &TEXTO_OPC, false),
                ("tipo", &TEXTO_OPC, false),
                ("variante", &TEXTO_OPC, false),
                ("destino", &TEXTO_OPC, false),
            ],
        )
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let t = move |k: &str| c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py);
    let tipo = t("tipo").filter(|t| !t.is_empty()).unwrap_or_else(|| "ollama".into());
    let cola = cola(&state);
    bloque(move || match cola.encolar(&t("ref").unwrap_or_default(), t("titulo").as_deref(), &tipo, t("variante").as_deref(), t("destino").as_deref()) {
        Ok(m) => ok(Valor::Mapa(m)),
        Err(e) => de_error(e),
    })
    .await
}

/// `GET /api/descargas`
pub async fn lista(State(state): State<AppState>) -> Response {
    let l = cola(&state).lista();
    ok(Valor::Mapa(Mapa::new().con("descargas", Valor::Lista(l.into_iter().map(Valor::Mapa).collect()))))
}

/// `POST /api/descargas/{id_}/cancelar`
pub async fn cancelar(State(state): State<AppState>, Path(id): Path<String>) -> Response {
    let id = match id_de(&id) {
        Ok(i) => i,
        Err(r) => return r,
    };
    match cola(&state).cancelar(id) {
        Ok(m) => ok(Valor::Mapa(m)),
        Err(e) => de_error(e),
    }
}

/// `POST /api/descargas/{id_}/reintentar`
pub async fn reintentar(State(state): State<AppState>, Path(id): Path<String>) -> Response {
    let id = match id_de(&id) {
        Ok(i) => i,
        Err(r) => return r,
    };
    let cola = cola(&state);
    bloque(move || match cola.reintentar(id) {
        Ok(m) => ok(Valor::Mapa(m)),
        Err(e) => de_error(e),
    })
    .await
}

/// `DELETE /api/descargas/terminadas`
pub async fn limpiar(State(state): State<AppState>) -> Response {
    let n = cola(&state).limpiar_terminadas();
    ok(Valor::Mapa(Mapa::new().con("borradas", n as i128)))
}

/// `GET /api/buscador/hf/inspeccionar_completo?repo=|repo_id=&variante=`
pub async fn inspeccionar_completo(Query(q): Query<HashMap<String, String>>) -> Response {
    let Some(ident) = q.get("repo").filter(|r| !r.is_empty()).or(q.get("repo_id").filter(|r| !r.is_empty())).cloned() else {
        return detalle(StatusCode::BAD_REQUEST, "Falta el identificador del repositorio ('repo' o 'repo_id').".to_string());
    };
    let variante = q.get("variante").cloned();
    bloque(move || match hf::inspeccionar(&ident, variante.as_deref(), None) {
        Ok(m) => ok(Valor::Mapa(m)),
        Err(ErrorHf::Red(t)) => detalle(StatusCode::SERVICE_UNAVAILABLE, format!("Sin conexión con la plataforma: {t}")),
        Err(ErrorHf::Otro(_)) => error_500(),
    })
    .await
}
