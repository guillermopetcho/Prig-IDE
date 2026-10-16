//! Rutas de solo lectura de la biblioteca: las librerías (`LibreriasService.list_libraries`) y los papers
//! (`PapersService.list_papers`). Los catálogos son los mismos archivos que lee Python (`backend/catalogos/`), y lo
//! demás (citas, fichas y análisis) se lee del disco en cada llamada.

use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::Response,
};
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use serde::Deserialize;
use std::io::Read;
use std::path::{Path, PathBuf};

use crate::routes::json_py;
use crate::state::AppState;

fn error_500() -> Response {
    use axum::response::IntoResponse;
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn catalogo(state: &AppState, archivo: &str) -> Option<Vec<Valor>> {
    match prig_aprendizaje::desafios::leer_json(&state.base_dir.join("backend/catalogos").join(archivo)) {
        Some(Valor::Lista(l)) => Some(l),
        _ => None,
    }
}

/// `PRIG_BOOKS_DIR` o `~/.prig_books` (como `os.environ.get(..., defecto)`: vacía también cuenta)
fn libros_dir() -> PathBuf {
    let d = std::env::var("PRIG_BOOKS_DIR").unwrap_or_else(|_| py::expanduser("~/.prig_books"));
    PathBuf::from(py::abspath(&d))
}

/// `len(json.load(f).get("citas", []))`, 0 si algo falla
fn num_citas(ruta: &Path) -> i128 {
    match prig_aprendizaje::desafios::leer_json(ruta) {
        Some(Valor::Mapa(m)) => match m.get("citas") {
            None => 0,
            Some(Valor::Lista(l)) => l.len() as i128,
            Some(Valor::Mapa(x)) => x.len() as i128,
            Some(Valor::Texto(t)) => t.chars().count() as i128,
            Some(_) => 0,
        },
        _ => 0,
    }
}

fn librerias(state: &AppState) -> Result<Vec<Valor>, ()> {
    let dir = libros_dir().join("librerias");
    let base = catalogo(state, "librerias.json").ok_or(())?;
    // `json.load` dentro de `except Exception`: lo que no se lea es []
    let propias = match prig_aprendizaje::desafios::leer_json(&dir.join("lista_librerias.json")) {
        Some(Valor::Lista(l)) => l,
        Some(v) if !v.verdad() => Vec::new(),
        Some(_) => return Err(()), // iterar algo que no es una lista de dicts: error en Python
        None => Vec::new(),
    };
    // {id: lib}: las de serie y después las propias (una propia con el mismo id reemplaza a la de serie en su sitio)
    let mut todas: Vec<(String, Mapa)> = Vec::new();
    for lib in base.iter().chain(propias.iter()) {
        let Valor::Mapa(m) = lib else { return Err(()) };
        let Some(Valor::Texto(id)) = m.get("id") else { return Err(()) };
        match todas.iter_mut().find(|(k, _)| k == id) {
            Some(e) => e.1 = m.clone(),
            None => todas.push((id.clone(), m.clone())),
        }
    }
    Ok(todas
        .into_iter()
        .map(|(id, lib)| {
            let n = num_citas(&dir.join(format!("{id}.json")));
            Valor::Mapa(lib.con("total_citas", Valor::Entero(n)).con("archivo_json", format!("{id}.json")))
        })
        .collect())
}

/// `GET /api/librerias/list`
pub async fn librerias_list(State(state): State<AppState>) -> Response {
    match tokio::task::spawn_blocking(move || librerias(&state)).await {
        Ok(Ok(l)) => json_py(StatusCode::OK, &Valor::Lista(l)),
        _ => error_500(),
    }
}

const REPO: &str = "guillermopetcho/Prig-IDE";
const RAMA: &str = "main";

#[derive(Deserialize)]
pub struct PapersParams {
    q: Option<String>,
    categoria: Option<String>,
}

fn texto(m: &Mapa, k: &str) -> String {
    match m.get(k) {
        Some(Valor::Texto(t)) => t.clone(),
        _ => String::new(),
    }
}

fn unidos(m: &Mapa, k: &str) -> String {
    match m.get(k) {
        Some(Valor::Lista(l)) => l.iter().filter_map(|v| if let Valor::Texto(t) = v { Some(t.as_str()) } else { None }).collect::<Vec<_>>().join(" "),
        _ => String::new(),
    }
}

/// Los primeros 50 000 caracteres de un archivo de texto, en minúsculas (None si no es UTF-8 o no se puede leer)
fn principio(ruta: &Path) -> Option<String> {
    let mut f = std::fs::File::open(ruta).ok()?;
    let mut b = Vec::new();
    f.read_to_end(&mut b).ok()?;
    let t = String::from_utf8(b).ok()?;
    Some(t.chars().take(50_000).collect::<String>().to_lowercase())
}

fn papers(state: &AppState, q: &str, categoria: &str) -> Result<Mapa, ()> {
    let cat = catalogo(state, "papers_catalogo.json").ok_or(())?;
    let docs = state.base_dir.join("docs");
    let q = py::strip(q).to_lowercase();
    let categoria = py::strip(categoria).to_lowercase();
    let terminos: Vec<&str> = q.split_whitespace().collect();
    let mut salida = Vec::new();
    for item in &cat {
        let Valor::Mapa(m) = item else { return Err(()) };
        let id = texto(m, "id");
        let ficha = docs.join("algoritmos_ml").join(format!("{id}.md"));
        let analisis = docs.join("analisis_papers").join(format!("{id}.md"));
        let tam = |p: &Path| if p.is_file() { std::fs::metadata(p).map(|m| m.len() as i128).unwrap_or(0) } else { 0 };
        let entrada = m
            .clone()
            .con("ficha_existe", ficha.is_file())
            .con("analisis_existe", analisis.is_file())
            .con("ficha_bytes", Valor::Entero(tam(&ficha)))
            .con("analisis_bytes", Valor::Entero(tam(&analisis)))
            .con("github_url_ficha", format!("https://github.com/{REPO}/blob/{RAMA}/docs/algoritmos_ml/{id}.md"))
            .con("github_url_analisis", format!("https://github.com/{REPO}/blob/{RAMA}/docs/analisis_papers/{id}.md"))
            .con("github_raw_analisis", format!("https://raw.githubusercontent.com/{REPO}/{RAMA}/docs/analisis_papers/{id}.md"));
        if !categoria.is_empty() && categoria != "todas" && !texto(m, "categoria").to_lowercase().contains(&categoria) {
            continue;
        }
        if !q.is_empty() {
            let busqueda = format!(
                "{} {} {} {} {} {}",
                texto(m, "titulo"),
                texto(m, "categoria"),
                texto(m, "papers_clave"),
                unidos(m, "autores"),
                unidos(m, "conceptos"),
                texto(m, "resumen")
            )
            .to_lowercase();
            if !terminos.iter().all(|t| busqueda.contains(t)) {
                let en_archivo = analisis.is_file() && principio(&analisis).is_some_and(|c| terminos.iter().all(|t| c.contains(t)));
                if !en_archivo {
                    continue;
                }
            }
        }
        salida.push(Valor::Mapa(entrada));
    }
    Ok(Mapa::new().con("papers", Valor::Lista(salida)).con("total", Valor::Entero(cat.len() as i128)))
}

/// `GET /api/papers/list`
pub async fn papers_list(State(state): State<AppState>, Query(p): Query<PapersParams>) -> Response {
    let r = tokio::task::spawn_blocking(move || papers(&state, p.q.as_deref().unwrap_or(""), p.categoria.as_deref().unwrap_or(""))).await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        _ => error_500(),
    }
}
