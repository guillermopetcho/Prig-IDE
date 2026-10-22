//! El estante de la biblioteca (`prig_biblioteca::estante`): la lista de elementos, lo que Prig guarda de cada uno,
//! quitarlos de la vista (sin borrar los archivos del usuario) eligiendo qué borrar de lo guardado, y volver a ponerlos.

use axum::{
    body::Bytes,
    extract::{Query, State},
    http::StatusCode,
    response::Response,
};
use prig_biblioteca::estante::{Elemento, Estante, PIEZAS};
use prig_plataforma::valor::{Mapa, Valor};
use std::collections::{BTreeSet, HashMap};

use crate::routes::cuerpo;
use crate::routes::{detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    use axum::response::IntoResponse;
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

/// `get_saved_projects`: `saved_projects` de la configuración, tal cual
pub fn guardados(state: &AppState) -> Vec<Valor> {
    match prig_aprendizaje::desafios::leer_json(&state.config_path) {
        Some(Valor::Mapa(m)) => match m.get("saved_projects") {
            Some(Valor::Lista(l)) => l.clone(),
            _ => Vec::new(),
        },
        _ => Vec::new(),
    }
}

pub fn rutas_guardadas(l: &[Valor]) -> Vec<String> {
    l.iter()
        .filter_map(|p| match p {
            Valor::Mapa(m) => m.texto("path").map(String::from),
            Valor::Texto(t) => Some(t.clone()),
            _ => None,
        })
        .collect()
}

/// `GET /api/books/list?category=`: los elementos que se ven, con `indexed` (si el tutor puede consultarlos)
pub async fn listar(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let r = tokio::task::spawn_blocking(move || {
        let e = Estante::por_defecto();
        let mut items = e.listar(q.get("category").map(String::as_str), &guardados(&state))?;
        let indexadas = e.rutas_indexadas();
        for i in &mut items {
            let v = match &indexadas {
                Some(s) => Valor::Bool(s.contains(&prig_plataforma::py::abspath(i.texto("path").unwrap_or_default()))),
                None => Valor::Nulo,
            };
            i.poner("indexed", v);
        }
        Ok::<_, String>(items)
    })
    .await;
    match r {
        Ok(Ok(v)) => json_py(StatusCode::OK, &Valor::Lista(v.into_iter().map(Valor::Mapa).collect())),
        _ => error_500(),
    }
}

fn resolver(state: &AppState, id: &str) -> Option<Elemento> {
    Estante::por_defecto().resolver(id, &rutas_guardadas(&guardados(state)))
}

/// `GET /api/books/inventario?id=`: lo que Prig guarda del elemento (y, si es una carpeta, de cada archivo suyo)
pub async fn inventario(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let id = q.get("id").cloned().unwrap_or_default();
    let r = tokio::task::spawn_blocking(move || resolver(&state, &id).map(|e| Estante::por_defecto().inventario(&e))).await;
    match r {
        Ok(Some(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(None) => detalle(StatusCode::NOT_FOUND, "Elemento no encontrado en la biblioteca."),
        Err(_) => error_500(),
    }
}

/// `POST /api/books/delete` (`id`; opcionales `piezas`, lo que se borra de lo guardado —todo si falta—, y `archivos`,
/// rutas relativas dentro de una carpeta para quitar solo esas). Los archivos del usuario no se tocan nunca: el
/// elemento deja de verse y de indexarse, y se puede volver a poner desde «Quitados»
pub async fn quitar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let id = c.texto("id", None);
    if let Err(r) = c.fin() {
        return r;
    }
    let Valor::Texto(id) = id else { return error_500() };
    let textos = |k: &str| -> Option<Result<Vec<String>, String>> {
        match m.get(k) {
            None | Some(Valor::Nulo) => None,
            Some(Valor::Lista(l)) => Some(l.iter().map(|x| match x { Valor::Texto(t) => Some(t.clone()), _ => None }.ok_or_else(|| format!("«{k}» debe ser una lista de textos"))).collect()),
            Some(_) => Some(Err(format!("«{k}» debe ser una lista de textos"))),
        }
    };
    let piezas: BTreeSet<String> = match textos("piezas") {
        None => PIEZAS.iter().map(|p| p.0.to_string()).collect(),
        Some(Ok(l)) => {
            if let Some(x) = l.iter().find(|x| !PIEZAS.iter().any(|p| p.0 == x.as_str())) {
                return detalle(StatusCode::BAD_REQUEST, format!("Pieza desconocida: {x}"));
            }
            l.into_iter().collect()
        }
        Some(Err(e)) => return detalle(StatusCode::BAD_REQUEST, &e),
    };
    let archivos = match textos("archivos") {
        None => None,
        Some(Ok(l)) if !l.is_empty() => Some(l),
        Some(Ok(_)) => return detalle(StatusCode::BAD_REQUEST, "No elegiste ningún archivo."),
        Some(Err(e)) => return detalle(StatusCode::BAD_REQUEST, &e),
    };
    let r = tokio::task::spawn_blocking(move || {
        let Some(e) = resolver(&state, &id) else { return Err((StatusCode::NOT_FOUND, format!("Elemento no encontrado: {id}"))) };
        let est = Estante::por_defecto();
        if archivos.is_none() && !e.proyecto {
            let rel = prig_plataforma::py::relpath(&e.ruta, &est.raiz);
            if e.ruta == est.raiz || prig_biblioteca::estante::CATEGORIAS.contains(&rel.as_str()) {
                return Err((StatusCode::BAD_REQUEST, format!("«{rel}» es una carpeta de la biblioteca y no se puede quitar.")));
            }
        }
        // un proyecto guardado también se oculta (sigue guardado para el explorador de archivos)
        est.quitar(&e, &piezas, archivos.as_deref()).map_err(|x| (StatusCode::BAD_REQUEST, x))
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err((s, t))) => detalle(s, &t),
        Err(_) => error_500(),
    }
}

/// `GET /api/books/ocultos`: lo quitado de la biblioteca, con si sigue existiendo en disco
pub async fn ocultos() -> Response {
    let r = tokio::task::spawn_blocking(|| {
        Estante::por_defecto()
            .ocultos()
            .into_iter()
            .rev()
            .map(|mut m| {
                let existe = std::path::Path::new(m.texto("ruta").unwrap_or_default()).exists();
                m.poner("existe", existe);
                Valor::Mapa(m)
            })
            .collect::<Vec<_>>()
    })
    .await;
    match r {
        Ok(l) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("ocultos", Valor::Lista(l)))),
        Err(_) => error_500(),
    }
}

/// `POST /api/books/restaurar` (`ruta`): lo vuelve a mostrar
pub async fn restaurar(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let ruta = c.texto("ruta", None);
    if let Err(r) = c.fin() {
        return r;
    }
    let Valor::Texto(ruta) = ruta else { return error_500() };
    let r = tokio::task::spawn_blocking(move || Estante::por_defecto().restaurar(&ruta)).await;
    match r {
        Ok(Ok(Some(e))) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("success", true).con("restaurado", e))),
        Ok(Ok(None)) => detalle(StatusCode::NOT_FOUND, "Ese elemento no estaba quitado."),
        _ => error_500(),
    }
}

/// `POST /api/books/import` (`path`, `category`): copia a la biblioteca e indexa en el acto (si se separan, el tutor
/// deja de «ver» lo que el usuario añadió)
pub async fn importar(State(state): State<AppState>, b: Bytes) -> Response {
    use prig_plataforma::modelo::Tipo;
    const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("path", &Tipo::Texto, true), ("category", &TEXTO_OPC, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let r = tokio::task::spawn_blocking(move || {
        let categoria = c.get("category").filter(|v| !v.es_nulo()).map(Valor::texto_py);
        importar_e_indexar(&state, &c.valor("path").texto_py(), categoria.as_deref())
    })
    .await;
    match r {
        Ok(m) if m.contiene("error") => detalle(StatusCode::BAD_REQUEST, m.valor("error").texto_py()),
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

/// `book_service.import_file` + `knowledge_service.index_single`: el resultado, o `{"error"}`
pub fn importar_e_indexar(state: &AppState, origen: &str, categoria: Option<&str>) -> Mapa {
    let mut res = Estante::por_defecto().importar(origen, categoria);
    if res.contiene("error") {
        return res;
    }
    let ruta = res.valor("path").texto_py();
    let tipo = res.get("category").map(Valor::texto_py).unwrap_or_else(|| "book".into()).to_lowercase();
    match crate::routes::conocimiento::servicio(state).and_then(|k| k.indexar_uno(&ruta, &tipo)) {
        Ok((estado, n)) => {
            res.poner("indexed", estado == "INGESTED" || estado == "ALREADY_EXISTS");
            res.poner("chunks_count", n as i64);
        }
        Err(e) => {
            res.poner("indexed", false);
            res.poner("index_error", e);
        }
    }
    res
}
