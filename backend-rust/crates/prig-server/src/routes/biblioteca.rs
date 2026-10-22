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
pub fn libros_dir() -> PathBuf {
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

pub fn librerias(state: &AppState) -> Result<Vec<Valor>, ()> {
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
    // `LibreriasService()` al arrancar Python: la carpeta y las citas de muestra
    match tokio::task::spawn_blocking(move || {
        crate::routes::librerias::preparar();
        librerias(&state)
    })
    .await
    {
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

// =========================================================================== un paper: leerlo, guardarlo, preguntarle

/// `PapersService.get_paper`: el Markdown (análisis o ficha) con sus metadatos; `Err` con el mensaje (un 404)
fn paper(state: &AppState, id: &str, tipo: &str) -> Result<Mapa, String> {
    let limpio = py::basename(id).replace(".md", "");
    let cat = catalogo(state, "papers_catalogo.json").unwrap_or_default();
    let de = |f: &dyn Fn(&Mapa) -> bool| cat.iter().find_map(|v| if let Valor::Mapa(m) = v { f(m).then(|| m.clone()) } else { None });
    let mut meta = de(&|m| m.get("id") == Some(&Valor::Texto(limpio.clone())));
    if meta.is_none() && !limpio.is_empty() && limpio.chars().all(|c| c.is_ascii_digit()) {
        if let Ok(n) = limpio.parse::<i128>() {
            meta = de(&|m| m.get("num").and_then(Valor::num).is_some_and(|x| x == n as f64));
        }
    }
    let carpeta = state.base_dir.join("docs").join(if tipo == "analisis" { "analisis_papers" } else { "algoritmos_ml" });
    let archivo = if limpio.ends_with(".md") { limpio.clone() } else { format!("{limpio}.md") };
    let ruta = carpeta.join(&archivo);
    if !ruta.is_file() {
        return Err(format!("No se encontró el documento para '{id}' (tipo: {tipo})"));
    }
    let contenido = py::leer_texto_estricto(&ruta.to_string_lossy()).map_err(|e| format!("Error leyendo archivo de paper: {e}"))?;
    let rel = py::relpath(&ruta.to_string_lossy(), &state.base_dir.to_string_lossy());
    let campo = |k: &str, d: &str| meta.as_ref().and_then(|m| m.get(k).cloned()).unwrap_or_else(|| Valor::Texto(d.into()));
    Ok(Mapa::new()
        .con("success", true)
        .con("id", limpio.as_str())
        .con("tipo", tipo)
        .con("titulo", campo("titulo", &limpio))
        .con("categoria", campo("categoria", "Algoritmo ML"))
        .con("meta", meta.clone().map(Valor::Mapa).unwrap_or(Valor::Nulo))
        .con("tamano_bytes", Valor::Entero(contenido.len() as i128))
        .con("lineas", Valor::Entero(prig_recursos::servidor::lineas_como_python(&contenido).len() as i128))
        .con("contenido", contenido)
        .con("archivo_relativo", rel.as_str())
        .con("github_url", format!("https://github.com/{REPO}/blob/{RAMA}/{rel}"))
        .con("github_repo", REPO))
}

/// `GET /api/papers/detail?id=&tipo=`
pub async fn paper_detalle(State(state): State<AppState>, Query(q): Query<std::collections::HashMap<String, String>>) -> Response {
    let id = match crate::routes::cuerpo::texto_consulta(&q, "id") {
        Ok(i) => i,
        Err(r) => return r,
    };
    let tipo = q.get("tipo").cloned().unwrap_or_else(|| "analisis".into());
    let r = tokio::task::spawn_blocking(move || paper(&state, &id, &tipo)).await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(reordenar_paper(m))),
        Ok(Err(e)) => crate::routes::detalle(StatusCode::NOT_FOUND, e),
        Err(_) => error_500(),
    }
}

/// El orden de las claves de Python (`contenido` antes de `tamano_bytes`)
fn reordenar_paper(m: Mapa) -> Mapa {
    let mut s = Mapa::new();
    for k in ["success", "id", "tipo", "titulo", "categoria", "meta", "contenido", "tamano_bytes", "lineas", "archivo_relativo", "github_url", "github_repo"] {
        if let Some(v) = m.get(k) {
            s.poner(k, v.clone());
        }
    }
    s
}

use prig_plataforma::modelo::Tipo;

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const HISTORIAL: Tipo = Tipo::Opcional(&Tipo::Lista(&Tipo::Dict(&Tipo::Cualquiera)));

/// `POST /api/papers/download` (`paper_id`, `tipo`, `workspace_path`): el Markdown a `papers_ml/` del proyecto
pub async fn paper_descargar(State(state): State<AppState>, b: axum::body::Bytes) -> Response {
    let c = match crate::routes::cuerpo::modelo(&b)
        .and_then(|m| crate::routes::cuerpo::tipados(&m, &[("paper_id", &Tipo::Texto, true), ("tipo", &TEXTO_OPC, false), ("workspace_path", &TEXTO_OPC, false)]))
    {
        Ok(c) => c,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || {
        let lleno = |k: &str| c.get(k).filter(|v| v.verdad()).map(Valor::texto_py);
        let ws = lleno("workspace_path").unwrap_or_else(|| espacio.to_string_lossy().to_string());
        let tipo = lleno("tipo").unwrap_or_else(|| "analisis".into());
        let p = paper(&state, &c.valor("paper_id").texto_py(), &tipo)?;
        let carpeta = py::join(&ws, "papers_ml");
        py::makedirs(&carpeta).map_err(|_| String::new())?;
        let nombre = format!("{}_{tipo}.md", p.valor("id").texto_py());
        let destino = py::join(&carpeta, &nombre);
        let contenido = p.valor("contenido").texto_py();
        if let Err(e) = std::fs::write(&destino, &contenido) {
            return Err(format!("Error al guardar monografía en el proyecto: {}", py::error_os(&e, &destino)));
        }
        let rel = py::relpath(&destino, &ws);
        Ok(Mapa::new()
            .con("success", true)
            .con("ok", true)
            .con("saved_to", destino.as_str())
            .con("rel_path", rel.as_str())
            .con("filename", nombre)
            .con("bytes", Valor::Entero(contenido.len() as i128))
            .con("mensaje", format!("Monografía guardada exitosamente en {rel}")))
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e)) if !e.is_empty() => crate::routes::detalle(StatusCode::BAD_REQUEST, e),
        _ => error_500(),
    }
}

/// `POST /api/papers/ask`: la monografía (hasta 22.000 caracteres) y la conversación reciente, y el tutor responde en
/// texto continuo
pub async fn paper_preguntar(State(state): State<AppState>, b: axum::body::Bytes) -> Response {
    let c = match crate::routes::cuerpo::modelo(&b).and_then(|m| {
        crate::routes::cuerpo::tipados(
            &m,
            &[("paper_id", &Tipo::Texto, true), ("pregunta", &Tipo::Texto, true), ("modelo", &TEXTO_OPC, false), ("tipo", &TEXTO_OPC, false), ("historial", &HISTORIAL, false)],
        )
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let lleno = |k: &str| c.get(k).filter(|v| v.verdad()).map(Valor::texto_py);
    let id = c.valor("paper_id").texto_py();
    let pregunta = c.valor("pregunta").texto_py();
    let tipo = lleno("tipo").unwrap_or_else(|| "analisis".into());
    let modelo = lleno("modelo").unwrap_or_else(|| {
        prig_ia::motor::config_ia().get("agent1_model").map(Valor::texto_py).unwrap_or_else(|| "qwen2.5-coder:7b".into())
    });
    let historial: Vec<Valor> = c.lista("historial").map(<[Valor]>::to_vec).unwrap_or_default();
    let raiz = state.base_dir.clone();
    crate::routes::asistente::flujo_de_texto(move |cancelar, enviar| {
        let pregunta = prig_biblioteca::referencias_ml::con_referencias(&raiz, &format!("{} {pregunta}", id.replace('_', " ")), &pregunta).0;
        let doc = paper(&state, &id, &tipo).ok();
        let contenido = doc.as_ref().map(|d| d.valor("contenido").texto_py()).unwrap_or_default();
        let titulo = doc.as_ref().map(|d| d.valor("titulo").texto_py()).unwrap_or_else(|| id.clone());
        let contexto: String = contenido.chars().take(22000).collect();
        let sistema = format!(
            "Eres un Catedrático y Tutor Senior de Inteligencia Artificial y Machine Learning en Prig IDE. Estás analizando la monografía del paper seminal '{titulo}'. Responde a las preguntas del desarrollador o estudiante con máximo rigor matemático, claridad didáctica, fórmulas en LaTeX (usando $ o $$) y ejemplos de código en Python/NumPy cuando sea oportuno. Basa tus explicaciones y deducciones estrictamente en el contenido y derivaciones de la monografía proporcionada."
        );
        let mut conversacion = String::new();
        for m in historial.iter().skip(historial.len().saturating_sub(6)) {
            let Valor::Mapa(m) = m else { continue };
            let rol = if matches!(m.get("rol"), Some(Valor::Texto(r)) if r == "user" || r == "usuario") { "Alumno" } else { "Profesor" };
            let texto = m.get("texto").map(Valor::texto_py).unwrap_or_default();
            conversacion.push_str(&format!("\n{rol}: {texto}"));
        }
        let prompt = format!("=== DOCUMENTO SEMINAL: {titulo} ===\n\n{contexto}\n\n=== FIN DEL DOCUMENTO ===\n{conversacion}\n\nPregunta del Alumno: {pregunta}\n\nProfesor:");
        let p = prig_ia::generar::PedidoGenerar { prompt, modelo, sistema, uso: Some("tutor_papers".into()), gobernador: true, ..Default::default() };
        prig_ia::generar::generar(&raiz, &p, cancelar, &mut |e: Mapa| {
            if e.get("t") == Some(&Valor::Texto("texto".into())) {
                enviar(e.valor("v").texto_py());
            }
        });
    })
}
