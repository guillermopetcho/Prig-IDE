//! Referencias de ML (`prig_biblioteca::referencias_ml`): el catálogo, el detalle, las relacionadas con un texto, el
//! PDF servido desde Prig (solo URLs del catálogo verificado) y abrirla en el navegador. Guardar el PDF en la
//! biblioteca sigue en Python, con la indexación de libros.

use std::collections::HashMap;

use axum::{
    body::Bytes,
    extract::{Query, State},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
};
use prig_biblioteca::referencias_ml as rml;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

const MAX_PDF: usize = 80 * 1024 * 1024;

fn ok(m: Mapa) -> Response {
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

fn falta(campo: &str) -> Response {
    cuerpo::respuesta(vec![cuerpo::Error {
        tipo: "missing",
        loc: vec!["query".into(), campo.into()],
        msg: "Field required".into(),
        entrada: Valor::Nulo,
        ctx: None,
    }])
}

fn o_404(raiz: &std::path::Path, id: &str) -> Result<Mapa, Response> {
    rml::referencia(raiz, id).ok_or_else(|| detalle(StatusCode::NOT_FOUND, format!("No existe la referencia «{id}»")))
}

/// `GET /api/referencias?q=&categoria=&tipo=`: el catálogo ordenado por familia (sin el resumen original)
pub async fn listar(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let raiz = state.base_dir.clone();
    let g = |k: &str| q.get(k).cloned().unwrap_or_default();
    let (consulta, categoria, tipo) = (g("q"), g("categoria"), g("tipo"));
    tokio::task::spawn_blocking(move || {
        let datos = rml::cargar(&raiz);
        let ligeras: Vec<Valor> = rml::listar(&raiz, &consulta, &categoria, &tipo)
            .iter()
            .map(|r| {
                let mut m = Mapa::new();
                for (k, v) in r.iter().filter(|(k, _)| k.as_str() != "resumen_original" && k.as_str() != "nota_verificacion") {
                    m.poner(k.clone(), v.clone());
                }
                Valor::Mapa(m.con("tiene_pdf", rml::pdf_de(r).is_some()).con("cita", rml::cita_corta(r)))
            })
            .collect();
        let categorias: Vec<Valor> = datos
            .categorias
            .iter()
            .map(|c| {
                let mut m = Mapa::new();
                for k in ["id", "nombre", "icono"] {
                    m.poner(k, c.get(k).cloned().unwrap_or(Valor::Nulo));
                }
                Valor::Mapa(m)
            })
            .collect();
        ok(Mapa::new()
            .con("categorias", Valor::Lista(categorias))
            .con("tipos", datos.tipos.clone())
            .con("referencias", Valor::Lista(ligeras))
            .con("total", datos.referencias.len()))
    })
    .await
    .unwrap_or_else(|_| (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response())
}

/// `GET /api/referencias/detalle?id=`
pub async fn detalle_ref(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let Some(id) = q.get("id").cloned() else { return falta("id") };
    let r = match o_404(&state.base_dir, &id) {
        Ok(r) => r,
        Err(e) => return e,
    };
    let datos = rml::cargar(&state.base_dir);
    let nombres: Vec<Valor> = r
        .lista("categorias")
        .unwrap_or(&[])
        .iter()
        .filter_map(|c| datos.categorias.iter().find(|x| x.get("id") == Some(c)).and_then(|x| x.get("nombre").cloned()))
        .collect();
    let tiene = rml::pdf_de(&r).is_some();
    let cita = rml::cita_corta(&r);
    ok(r.con("tiene_pdf", tiene).con("cita", cita).con("categorias_nombres", Valor::Lista(nombres)))
}

/// `GET /api/referencias/relacionadas?q=&maximo=5`
pub async fn relacionadas(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let Some(texto) = q.get("q").cloned() else { return falta("q") };
    let maximo = match cuerpo::entero_consulta(&q, "maximo", 5, i64::MIN, i64::MAX) {
        Ok(m) => m.max(0) as usize,
        Err(r) => return r,
    };
    let refs: Vec<Valor> = rml::relacionadas(&state.base_dir, &texto, maximo).iter().map(|r| Valor::Mapa(rml::resumen_publico(r))).collect();
    ok(Mapa::new().con("referencias", Valor::Lista(refs)))
}

/// Solo URLs del catálogo verificado (nunca una que mande el cliente)
fn descargar_pdf(url: &str) -> Result<Vec<u8>, Response> {
    use std::io::Read;
    let error = |e: String| detalle(StatusCode::BAD_GATEWAY, format!("No se pudo descargar el PDF: {e}"));
    let c = reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(60)).build().map_err(|e| error(e.to_string()))?;
    let r = c
        .get(url)
        .header("User-Agent", rml::AGENTE)
        .header("Accept", "application/pdf,*/*")
        .send()
        .map_err(|e| error(e.to_string()))?;
    if !r.status().is_success() {
        return Err(error(format!("HTTP Error {}: {}", r.status().as_u16(), r.status().canonical_reason().unwrap_or(""))));
    }
    let mut datos = Vec::new();
    r.take(MAX_PDF as u64 + 1).read_to_end(&mut datos).map_err(|e| error(e.to_string()))?;
    if datos.len() > MAX_PDF {
        return Err(detalle(StatusCode::PAYLOAD_TOO_LARGE, "El PDF supera 80 MB: ábrelo en el navegador."));
    }
    if !datos.starts_with(b"%PDF-") {
        return Err(detalle(StatusCode::BAD_GATEWAY, "El enlace no devolvió un PDF: ábrelo en el navegador."));
    }
    Ok(datos)
}

/// `GET /api/referencias/pdf?id=`: el PDF servido desde Prig para leerlo dentro de la Biblioteca
pub async fn pdf(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let Some(id) = q.get("id").cloned() else { return falta("id") };
    let r = match o_404(&state.base_dir, &id) {
        Ok(r) => r,
        Err(e) => return e,
    };
    let Some(url) = rml::pdf_de(&r) else {
        return detalle(StatusCode::NOT_FOUND, "Esta referencia no tiene PDF directo: ábrela en el navegador.");
    };
    match tokio::task::spawn_blocking(move || descargar_pdf(&url)).await {
        Ok(Ok(datos)) => (
            [
                (header::CONTENT_TYPE, "application/pdf".to_string()),
                (header::CONTENT_DISPOSITION, format!("inline; filename=\"{id}.pdf\"")),
                (header::CACHE_CONTROL, "max-age=86400".to_string()),
            ],
            datos,
        )
            .into_response(),
        Ok(Err(r)) => r,
        Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response(),
    }
}

/// `POST /api/referencias/abrir` (`id`): en el navegador del sistema
pub async fn abrir(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(&m, &[("id", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let r = match o_404(&state.base_dir, &c.valor("id").texto_py()) {
        Ok(r) => r,
        Err(e) => return e,
    };
    let url = r.get("url").map(Valor::texto_py).unwrap_or_default();
    let abierto = prig_integrations::youtube::abrir_en_navegador(&url);
    ok(Mapa::new().con("ok", abierto).con("url", url))
}
