//! Leer y anotar los elementos de la biblioteca (`book_service.py`): el contenido de un libro, documento o proyecto,
//! la ficha de IA (y pedirle al modelo que la haga), los recortes, el lector de PDF página a página con sus ediciones
//! y búsqueda, y las citas de cada libro (`citas/<nombre>.json`). Los archivos son los mismos que escribía Python,
//! byte a byte. El PDF lo lee PDFium (`prig_biblioteca::pdf`, como `pdf_nativo.py`).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use axum::{
    body::Bytes,
    extract::{Path as Ruta, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_biblioteca::estante::{categoria_de, titulo_de_nombre, Estante};
use prig_biblioteca::pdf;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

async fn en_hilo<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| error_500())
}

fn ok(v: Valor) -> Response {
    json_py(StatusCode::OK, &v)
}

/// `{"error": ...}` con 200 (las rutas que devuelven el dict de error tal cual)
fn con_error(m: String) -> Valor {
    Valor::Mapa(Mapa::new().con("error", m))
}

fn ahora() -> String {
    py::ahora_iso()
}

fn escribir(ruta: &Path, v: &Valor) -> Result<(), String> {
    std::fs::write(ruta, prig_plataforma::json::escribir(v, 2)).map_err(|e| py::error_os(&e, &ruta.to_string_lossy()))
}

fn leer_json(ruta: &Path) -> Option<Valor> {
    prig_plataforma::json::leer(&std::fs::read_to_string(ruta).ok()?).ok()
}

/// `open(ruta, encoding="utf-8", errors="replace").read(n)` en modo texto (\r\n y \r pasan a \n)
fn leer_texto(ruta: &str, n: Option<usize>) -> Result<String, String> {
    let b = std::fs::read(ruta).map_err(|e| py::error_os(&e, ruta))?;
    let t = String::from_utf8_lossy(&b).replace("\r\n", "\n").replace('\r', "\n");
    Ok(match n {
        Some(n) => t.chars().take(n).collect(),
        None => t,
    })
}

// =========================================================================== la biblioteca

fn estante() -> Estante {
    Estante::por_defecto()
}

fn raiz() -> String {
    estante().raiz
}

fn citas_dir() -> PathBuf {
    PathBuf::from(raiz()).join("citas")
}

fn ediciones_dir() -> PathBuf {
    citas_dir().join("ediciones")
}

const CATEGORIAS: [&str; 7] = ["books", "documentation", "papers", "code", "notebooks", "datasets", "projects"];

/// `BookService.__init__`: las carpetas de la biblioteca y la guía de muestra, una sola vez en su vida
pub fn preparar() {
    let r = PathBuf::from(raiz());
    for c in CATEGORIAS {
        let _ = std::fs::create_dir_all(r.join(c));
    }
    for d in ["metadata", "citas", "citas/ediciones"] {
        let _ = std::fs::create_dir_all(r.join(d));
    }
    let marca = r.join(".index").join(".sample_created");
    if marca.exists() || tiene_contenido(&r) {
        return;
    }
    let guia = r.join("documentation").join("Guia_Fundamentos_Deep_Learning.md");
    if !guia.exists() {
        let _ = std::fs::write(
            &guia,
            "# Guía de Fundamentos de Deep Learning\n\n## 1. Redes Neuronales y Tensores\nUn Tensor es una matriz multidimensional. La capa lineal realiza la operación:\n$$y = \\sigma(W \\cdot x + b)$$\n\n## 2. Optimizadores\nAdam ajusta la tasa de aprendizaje para cada parámetro individualmente:\n$$\\theta_{t+1} = \\theta_t - \\frac{\\eta}{\\sqrt{\\hat{v}_t} + \\epsilon} \\hat{m}_t$$\n",
        );
    }
    let _ = std::fs::create_dir_all(r.join(".index"));
    let _ = std::fs::write(&marca, "La guía de muestra ya se creó una vez; no se vuelve a generar.\n");
}

/// `_library_has_content`: ¿algún archivo del usuario?
fn tiene_contenido(dir: &Path) -> bool {
    let Ok(l) = std::fs::read_dir(dir) else { return false };
    let mut dirs = Vec::new();
    for e in l.flatten() {
        let n = e.file_name().to_string_lossy().to_string();
        let es_dir = std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false);
        if es_dir {
            if !["metadata", ".index"].contains(&n.as_str()) && !n.starts_with('.') && !e.file_type().map(|t| t.is_symlink()).unwrap_or(false) {
                dirs.push(e.path());
            }
        } else if !n.starts_with('.') {
            return true;
        }
    }
    dirs.iter().any(|d| tiene_contenido(d))
}

/// `_resolve_item`: dentro de la biblioteca (o un proyecto guardado)
fn resolver(state: &AppState, id: &str) -> Option<String> {
    let proyectos = crate::routes::estante::rutas_guardadas(&crate::routes::estante::guardados(state));
    estante().resolver(id, &proyectos).map(|e| e.ruta)
}

/// `get_metadata(id)`: la ficha por la ruta relativa (`a__b.json`) o, si no, la antigua por nombre
fn ficha(state: &AppState, id: &str) -> Option<Valor> {
    let raiz = raiz();
    let dir = PathBuf::from(&raiz).join("metadata");
    let abs = if py::isabs(id) { Some(id.to_string()) } else { resolver(state, id) };
    let mut candidatos = Vec::new();
    if let Some(a) = abs {
        candidatos.push(format!("{}.json", py::relpath(&a, &raiz).replace('/', "__")));
    }
    candidatos.push(format!("{}.json", py::basename(id)));
    candidatos.iter().map(|n| dir.join(n)).find_map(|f| if f.exists() { leer_json(&f) } else { None })
}

fn guardar_ficha(state: &AppState, ruta: &str, v: &Valor) {
    let raiz = raiz();
    let abs = if py::isabs(ruta) { Some(ruta.to_string()) } else { resolver(state, ruta) };
    let clave = abs.map(|a| py::relpath(&a, &raiz).replace('/', "__")).unwrap_or_else(|| py::basename(ruta));
    let _ = escribir(&PathBuf::from(&raiz).join("metadata").join(format!("{clave}.json")), v);
}

/// `(meta or {}).get("title") or _fallback_title(nombre)`
fn titulo(meta: Option<&Valor>, nombre: &str) -> Valor {
    match meta {
        Some(Valor::Mapa(m)) => m.get("title").filter(|t| t.verdad()).cloned().unwrap_or_else(|| Valor::Texto(titulo_de_nombre(nombre))),
        _ => Valor::Texto(titulo_de_nombre(nombre)),
    }
}

// =========================================================================== PDF

/// `pdf_nativo.lector()`: PDFium cargado (lib/pdfium o `PRIG_PDFIUM`), o None
fn pdfium(state: &AppState) -> bool {
    static L: OnceLock<bool> = OnceLock::new();
    *L.get_or_init(|| {
        let ruta = std::env::var("PRIG_PDFIUM").ok().filter(|r| !r.is_empty()).unwrap_or_else(|| state.base_dir.join("lib/pdfium/libpdfium.so").to_string_lossy().to_string());
        let r = if Path::new(&ruta).is_file() { pdf::cargar(&ruta) } else { Err(format!("[Errno 2] No such file or directory: '{ruta}'")) };
        if let Err(e) = &r {
            println!("PDFium no disponible ({e}).");
        }
        r.is_ok()
    })
}

/// `extract_pdf_text`: las primeras páginas con su cabecera
fn texto_pdf(state: &AppState, ruta: &str, max: usize) -> String {
    if !pdfium(state) {
        return "pypdf no disponible para extracción de PDF.".into();
    }
    match pdf::primeras(ruta, max) {
        Ok(p) => p.iter().enumerate().filter(|(_, t)| !t.is_empty()).map(|(i, t)| format!("--- Página {} ---\n{t}", i + 1)).collect::<Vec<_>>().join("\n\n"),
        Err(e) => format!("Error extrayendo texto del PDF: {e}"),
    }
}

/// `extract_document_text`
fn texto_documento(state: &AppState, ruta: &str, max: usize) -> String {
    let ext = py::splitext(ruta).1.to_lowercase();
    let cortar = |t: String| t.chars().take(max).collect::<String>();
    if ext == ".pdf" {
        return cortar(texto_pdf(state, ruta, 25));
    }
    if ext == ".ipynb" {
        if let Some(t) = celdas_notebook(ruta) {
            return cortar(t);
        }
    }
    match leer_texto(ruta, None) {
        Ok(t) => cortar(t),
        Err(e) => format!("Error leyendo documento: {e}"),
    }
}

/// Las celdas de un cuaderno como `[TIPO]\nfuente`; None si Python fallaría (y lee el archivo como texto)
fn celdas_notebook(ruta: &str) -> Option<String> {
    let Valor::Mapa(nb) = prig_plataforma::json::leer(&leer_texto(ruta, None).ok()?).ok()? else { return None };
    let celdas = match nb.get("cells") {
        None => Vec::new(),
        Some(Valor::Lista(l)) => l.clone(),
        Some(_) => return None,
    };
    let mut salida = Vec::new();
    for c in celdas {
        let Valor::Mapa(c) = c else { return None };
        let tipo = match c.get("cell_type") {
            None => String::new(),
            Some(Valor::Texto(t)) => t.clone(),
            Some(_) => return None,
        };
        let fuente = match c.get("source") {
            None => String::new(),
            Some(Valor::Texto(t)) => t.clone(),
            Some(Valor::Lista(l)) => {
                let mut s = String::new();
                for x in l {
                    let Valor::Texto(x) = x else { return None };
                    s.push_str(x);
                }
                s
            }
            Some(_) => return None,
        };
        if !py::strip(&fuente).is_empty() {
            salida.push(format!("[{}]\n{fuente}", tipo.to_uppercase()));
        }
    }
    Some(salida.join("\n\n"))
}

/// `urllib.parse.quote(t, safe='')`
fn citar_url(t: &str) -> String {
    let mut s = String::new();
    for b in t.bytes() {
        if b.is_ascii_alphanumeric() || b"_.-~".contains(&b) {
            s.push(b as char);
        } else {
            s.push_str(&format!("%{b:02X}"));
        }
    }
    s
}

// =========================================================================== contenido

/// `get_book_content`: un proyecto (resumen de su árbol), un PDF (primeras páginas) o un texto (hasta 400.000)
fn contenido(state: &AppState, id: &str) -> Valor {
    let Some(ruta) = resolver(state, id) else {
        return con_error(format!("Elemento no encontrado en el Knowledge Repository: {id}"));
    };
    let nombre = py::basename(&ruta);
    if Path::new(&ruta).is_dir() {
        let meta = ficha(state, &nombre).filter(|m| m.verdad());
        let (mut archivos, mut carpetas, mut muestra) = (0usize, 0usize, Vec::new());
        recorrer_proyecto(Path::new(&ruta), &ruta, &mut archivos, &mut carpetas, &mut muestra);
        let por_defecto = || Valor::Mapa(Mapa::new().con("title", titulo_de_nombre(&nombre)).con("path", ruta.as_str()).con("is_project", true));
        return Valor::Mapa(
            Mapa::new()
                .con("id", nombre.as_str())
                .con("type", "project")
                .con("is_project", true)
                .con("path", ruta.as_str())
                .con("title", titulo(meta.as_ref(), &nombre))
                .con("files_count", archivos as i64)
                .con("dirs_count", carpetas as i64)
                .con("sample_files", Valor::Lista(muestra.into_iter().map(Valor::Texto).collect()))
                .con("metadata", meta.unwrap_or_else(por_defecto)),
        );
    }
    let meta = ficha(state, &nombre).unwrap_or(Valor::Nulo);
    if py::splitext(&ruta).1.to_lowercase() == ".pdf" {
        let texto: String = texto_pdf(state, &ruta, 5).chars().take(2000).collect();
        return Valor::Mapa(
            Mapa::new()
                .con("id", nombre.as_str())
                .con("type", "pdf")
                .con("path", ruta.as_str())
                .con("url", format!("/api/raw-file?path={}", citar_url(&ruta)))
                .con("preview_text", texto)
                .con("metadata", meta),
        );
    }
    const MAX: usize = 400_000;
    match leer_texto(&ruta, Some(MAX + 1)) {
        Ok(mut t) => {
            let truncado = t.chars().count() > MAX;
            if truncado {
                t = t.chars().take(MAX).collect();
            }
            Valor::Mapa(
                Mapa::new()
                    .con("id", nombre.as_str())
                    .con("type", "text")
                    .con("path", ruta.as_str())
                    .con("content", t)
                    .con("truncated", truncado)
                    .con("size_bytes", std::fs::metadata(&ruta).map(|m| m.len() as i64).unwrap_or(0))
                    .con("metadata", meta),
            )
        }
        Err(e) => con_error(format!("Error leyendo elemento: {e}")),
    }
}

/// El `os.walk` del resumen de un proyecto: sin carpetas ocultas ni de entorno; hasta 20 archivos de muestra
fn recorrer_proyecto(dir: &Path, raiz: &str, archivos: &mut usize, carpetas: &mut usize, muestra: &mut Vec<String>) {
    let Ok(l) = std::fs::read_dir(dir) else { return };
    let (mut dirs, mut fs) = (Vec::new(), Vec::new());
    for e in l.flatten() {
        let n = e.file_name().to_string_lossy().to_string();
        if std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false) {
            dirs.push((n, e.file_type().map(|t| t.is_symlink()).unwrap_or(false)));
        } else {
            fs.push(n);
        }
    }
    let dirs: Vec<(String, bool)> = dirs.into_iter().filter(|(d, _)| !d.starts_with('.') && !["node_modules", "__pycache__", ".git", "venv", ".venv"].contains(&d.as_str())).collect();
    *carpetas += dirs.len();
    *archivos += fs.len();
    if muestra.len() < 20 {
        for f in &fs {
            if !f.starts_with('.') {
                muestra.push(py::relpath(&dir.join(f).to_string_lossy(), raiz));
                if muestra.len() >= 20 {
                    break;
                }
            }
        }
    }
    for (d, enlace) in dirs {
        if !enlace {
            recorrer_proyecto(&dir.join(d), raiz, archivos, carpetas, muestra);
        }
    }
}

/// `GET /api/books/read?id=`
pub async fn leer(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let id = match cuerpo::texto_consulta(&q, "id") {
        Ok(i) => i,
        Err(r) => return r,
    };
    en_hilo(move || ok(contenido(&state, &id))).await
}

/// `GET /api/books/metadata?id=` y `/api/books/metadata/{id}`: la ficha de IA (404 si no hay)
fn ficha_o_404(state: &AppState, id: &str) -> Response {
    match ficha(state, id).filter(|m| m.verdad()) {
        Some(m) => ok(m),
        None => detalle(StatusCode::NOT_FOUND, "Metadatos de IA no encontrados"),
    }
}

pub async fn ficha_consulta(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let id = match cuerpo::texto_consulta(&q, "id") {
        Ok(i) => i,
        Err(r) => return r,
    };
    en_hilo(move || ficha_o_404(&state, &id)).await
}

pub async fn ficha_ruta(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    en_hilo(move || ficha_o_404(&state, &id)).await
}

// =========================================================================== analizar

/// `analyze_document`: el modelo hace la ficha (JSON); si falla, una ficha que lo dice (sin inventar nada)
fn analizar(state: &AppState, id: &str, modelo: &str) -> Valor {
    let Some(ruta) = resolver(state, id) else {
        return con_error(format!("Elemento no encontrado para análisis: {id}"));
    };
    let nombre = py::basename(&ruta);
    let categoria = categoria_de(&ruta);
    let texto = texto_documento(state, &ruta, 12000);
    let tres: String = categoria.chars().take(3).collect();
    let tipo = categoria.strip_suffix('s').unwrap_or(categoria);
    let id_nuevo = || format!("{tres}_{}", &uuid::Uuid::new_v4().simple().to_string()[..8]);
    let contenido: String = texto.chars().take(10000).collect();
    let prompt = format!(
        "Analiza a fondo el elemento de conocimiento de la Biblioteca del repositorio titulado '{nombre}'.\nCategoría asignada: {} (Opciones: BOOKS, DOCUMENTATION, PAPERS, CODE, NOTEBOOKS, DATASETS, PROJECTS).\n\nCONTENIDO / CÓDIGO EXTRAÍDO DEL ELEMENTO:\n```\n{contenido}\n```\n\nDEVUELVE ÚNICAMENTE UN OBJETO JSON VÁLIDO con la siguiente estructura completa (sin texto explicativo fuera del JSON):\n{{\n  \"id\": \"{}\",\n  \"category\": \"{}\",\n  \"type\": \"{tipo}\",\n  \"title\": \"Nombre o Título descriptivo claro del elemento\",\n  \"filename\": \"{nombre}\",\n  \"topics\": [\"tema 1\", \"tema 2\", \"tema 3\"],\n  \"concepts\": [\"concepto 1\", \"concepto 2\", \"concepto 3\"],\n  \"libraries\": [\"librería 1\", \"librería 2\"],\n  \"dataset\": \"Nombre del Dataset asociado si aplica o N/A\",\n  \"level\": \"beginner|intermediate|advanced\",\n  \"languages\": [\"python\", \"bash\"],\n  \"dependencies\": [\"prerrequisito o dependencia 1\", \"dependencia 2\"],\n  \"summary\": \"Resumen claro, técnico y estructurado del conocimiento contenido en 2 párrafos.\",\n  \"key_takeaways\": [\"Insight o aprendizaje clave 1\", \"Insight clave 2\", \"Insight 3\"],\n  \"code_examples\": [\"# Ejemplo práctico de código o uso derivado\\nprint('Práctica')\"]\n}}\n",
        categoria.to_uppercase(),
        id_nuevo(),
        categoria.to_uppercase(),
    );
    let sistema = "Eres un Arquitecto de Conocimiento e Ingeniero de Software Senior. Devuelve EXCLUSIVAMENTE un objeto JSON válido estructurado sin bloques ni texto adicional fuera del JSON.";
    let p = prig_ia::generar::PedidoGenerar { prompt, modelo: modelo.into(), sistema: sistema.into(), gobernador: true, ..Default::default() };
    let mut respuesta = String::new();
    let cancelar = prig_ia::vivo::Cancelar::default();
    prig_ia::generar::generar(&state.base_dir, &p, &cancelar, &mut |e: Mapa| {
        if e.get("t") == Some(&Valor::Texto("texto".into())) {
            respuesta.push_str(&e.valor("v").texto_py());
        }
    });
    let mut limpio = py::strip(&respuesta).to_string();
    if limpio.contains("```") {
        if let (Some(s), Some(e)) = (limpio.find('{'), limpio.rfind('}')) {
            limpio = if e >= s { limpio[s..=e].to_string() } else { String::new() };
        }
    }
    let error = match prig_plataforma::json::leer(&limpio) {
        Ok(Valor::Mapa(mut m)) => {
            m.poner("category", categoria.to_uppercase());
            m.poner("filename", nombre.as_str());
            m.poner("file_path", ruta.as_str());
            m.poner("created_at", ahora());
            if !m.contiene("title") {
                m.poner("title", titulo_de_nombre(&nombre));
            }
            m.poner("analysis_failed", false);
            let v = Valor::Mapa(m);
            guardar_ficha(state, &ruta, &v);
            return v;
        }
        Ok(Valor::Lista(_)) => "list indices must be integers or slices, not str".to_string(),
        Ok(otro) => format!("'{}' object does not support item assignment", py::tipo(&otro)),
        Err(e) => e,
    };
    let fallo = Valor::Mapa(
        Mapa::new()
            .con("id", id_nuevo())
            .con("category", categoria.to_uppercase())
            .con("type", tipo)
            .con("title", titulo_de_nombre(&nombre))
            .con("filename", nombre.as_str())
            .con("analysis_failed", true)
            .con("analysis_error", error.as_str())
            .con("topics", Valor::Lista(vec![]))
            .con("concepts", Valor::Lista(vec![]))
            .con("libraries", Valor::Lista(vec![]))
            .con("dataset", "N/A")
            .con("level", "unknown")
            .con("languages", Valor::Lista(vec![]))
            .con("dependencies", Valor::Lista(vec![]))
            .con("summary", format!("No se pudo analizar '{nombre}'. Motivo: {error}"))
            .con("key_takeaways", Valor::Lista(vec![]))
            .con("code_examples", Valor::Lista(vec![]))
            .con("file_path", ruta.as_str())
            .con("created_at", ahora()),
    );
    guardar_ficha(state, &ruta, &fallo);
    fallo
}

/// `POST /api/books/analyze` (`book_id`, `path`, `model`)
pub async fn analizar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("book_id", &Tipo::Texto, true), ("path", &TEXTO_OPC, false), ("model", &Tipo::Texto, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        let objetivo = c.get("path").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| c.valor("book_id").texto_py());
        let modelo = c.get("model").map(Valor::texto_py).unwrap_or_else(|| "qwen2.5-coder:7b".into());
        ok(analizar(&state, &objetivo, &modelo))
    })
    .await
}

// =========================================================================== recortes

fn archivo_recortes() -> PathBuf {
    match std::env::var("PRIG_SNIPPETS_FILE") {
        Ok(r) if !r.is_empty() => PathBuf::from(r),
        _ => PathBuf::from(raiz()).join("snippets.json"),
    }
}

/// `load_snippets`: lo guardado, o {}
fn recortes() -> Valor {
    let f = archivo_recortes();
    if f.exists() {
        if let Some(v) = leer_json(&f) {
            return v;
        }
    }
    Valor::Mapa(Mapa::new())
}

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const DICT_OPC: Tipo = Tipo::Opcional(&Tipo::Dict(&Tipo::Cualquiera));
const DICT: Tipo = Tipo::Dict(&Tipo::Cualquiera);

/// `POST /api/books/snippet` (`book_id`, `page`, `box`, `text`, `label`)
pub async fn recorte_guardar(b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(&m, &[("book_id", &Tipo::Texto, true), ("page", &Tipo::Entero, false), ("box", &DICT_OPC, false), ("text", &TEXTO_OPC, false), ("label", &TEXTO_OPC, false)])
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        let Valor::Mapa(mut todos) = recortes() else { return error_500() };
        let id = format!("snp_{}", &uuid::Uuid::new_v4().simple().to_string()[..8]);
        let pagina = c.get("page").cloned().unwrap_or(Valor::Entero(1));
        let lleno = |k: &str| c.get(k).filter(|v| v.verdad()).cloned();
        let etiqueta = lleno("label").unwrap_or_else(|| Valor::Texto(format!("Cita pág. {}", pagina.texto_py())));
        let r = Mapa::new()
            .con("id", id.as_str())
            .con("book_id", c.valor("book_id").clone())
            .con("page", pagina)
            .con("box", lleno("box").unwrap_or_else(|| Valor::Mapa(Mapa::new())))
            .con("text", lleno("text").unwrap_or_else(|| Valor::Texto(String::new())))
            .con("label", etiqueta)
            .con("cite_tag", format!("::cite[{id}]"));
        todos.poner(id, r.clone());
        let _ = escribir(&archivo_recortes(), &Valor::Mapa(todos));
        ok(Valor::Mapa(r))
    })
    .await
}

/// `GET /api/books/snippets`
pub async fn recortes_ruta() -> Response {
    en_hilo(|| ok(recortes())).await
}

/// `GET /api/books/snippet/{id}`
pub async fn recorte(Ruta(id): Ruta<String>) -> Response {
    en_hilo(move || match recortes() {
        Valor::Mapa(m) => ok(m.get(&id).cloned().unwrap_or_else(|| con_error("Cita no encontrada".into()))),
        Valor::Lista(_) | Valor::Texto(_) => error_500(),
        _ => error_500(),
    })
    .await
}

// =========================================================================== lector de PDF

fn raiz_de(ruta: &str) -> String {
    py::splitext(&py::basename(ruta)).0
}

fn archivo_edicion(raiz_libro: &str, pagina: i64) -> PathBuf {
    ediciones_dir().join(format!("{raiz_libro}_p{pagina}.txt"))
}

/// `get_pdf_pages`: una página (la edición guardada si la hay), cuántas tiene y dónde aparece lo buscado
fn paginas(state: &AppState, id: &str, pagina: i64, buscar: Option<&str>) -> Result<Valor, String> {
    let Some(ruta) = resolver(state, id) else { return Err(format!("Documento no encontrado: {id}")) };
    let stem = raiz_de(&ruta);
    let nombre = py::basename(&ruta);
    let meta = ficha(state, &ruta);
    let t = titulo(meta.as_ref(), &nombre);
    let uid = py::relpath(&ruta, &raiz());
    if py::splitext(&ruta).1.to_lowercase() != ".pdf" {
        let contenido = leer_texto(&ruta, Some(400_000)).map_err(|e| format!("Error leyendo documento: {e}"))?;
        return Ok(Valor::Mapa(
            Mapa::new()
                .con("id", nombre.as_str())
                .con("uid", uid)
                .con("title", t)
                .con("filename", nombre.as_str())
                .con("is_pdf", false)
                .con("total_pages", 1)
                .con("current_page", 1)
                .con("page_text", contenido)
                .con("has_edit", false)
                .con("stem", stem),
        ));
    }
    if !pdfium(state) {
        return Err("pypdf no está instalado en el entorno. No se puede leer el PDF página por página.".into());
    }
    let total = pdf::num_paginas(&ruta).map_err(|e| format!("Error abriendo PDF: {e}"))?;
    if total == 0 {
        return Err("El archivo PDF no contiene páginas legibles.".into());
    }
    let idx = (if pagina == 0 { 1 } else { pagina }).min(total as i64).max(1);
    let edicion = archivo_edicion(&stem, idx);
    let (mut texto, mut editada) = (String::new(), false);
    if edicion.exists() {
        if let Ok(t) = py::leer_texto_estricto(&edicion.to_string_lossy()) {
            texto = t;
            editada = true;
        }
    }
    if texto.is_empty() {
        texto = match pdf::pagina(&ruta, (idx - 1) as usize) {
            Ok(t) => t.replace("\r\n", "\n"),
            Err(e) => format!("(No se pudo extraer texto de la página {idx}: {e})"),
        };
    }
    let mut coincidencias = Vec::new();
    if let Some(q) = buscar.map(py::strip).filter(|q| !q.is_empty()) {
        for (n, s) in pdf::buscar(&ruta, &q.to_lowercase(), total.min(200)).map_err(|e| format!("Error abriendo PDF: {e}"))? {
            coincidencias.push(Valor::Mapa(Mapa::new().con("page", n as i64).con("snippet", s)));
        }
    }
    Ok(Valor::Mapa(
        Mapa::new()
            .con("id", nombre.as_str())
            .con("uid", uid)
            .con("title", t)
            .con("filename", nombre.as_str())
            .con("is_pdf", true)
            .con("total_pages", total as i64)
            .con("current_page", idx)
            .con("page_text", texto)
            .con("has_edit", editada)
            .con("stem", stem)
            .con("search_matches", Valor::Lista(coincidencias)),
    ))
}

/// `GET /api/books/pdf-pages?id=&page=&search=`
pub async fn paginas_ruta(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let id = match cuerpo::texto_consulta(&q, "id") {
        Ok(i) => i,
        Err(r) => return r,
    };
    let pagina = match cuerpo::entero_consulta(&q, "page", 1, i64::MIN, i64::MAX) {
        Ok(p) => p,
        Err(r) => return r,
    };
    en_hilo(move || match paginas(&state, &id, pagina, q.get("search").map(String::as_str)) {
        Ok(v) => ok(v),
        Err(e) => detalle(StatusCode::BAD_REQUEST, e),
    })
    .await
}

/// `POST /api/books/pdf-page-save` (`book_id`, `page`, `text`): la página corregida a mano
pub async fn pagina_guardar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("book_id", &Tipo::Texto, true), ("page", &Tipo::Entero, true), ("text", &Tipo::Texto, true)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        let id = c.valor("book_id").texto_py();
        let stem = raiz_de(&resolver(&state, &id).unwrap_or_else(|| id.clone()));
        let pagina = c.valor("page");
        let ruta = archivo_edicion(&stem, pagina.num().unwrap_or(0.0) as i64);
        let ruta_t = ruta.to_string_lossy().to_string();
        match std::fs::write(&ruta, c.valor("text").texto_py()) {
            Ok(()) => ok(Valor::Mapa(Mapa::new().con("success", true).con("ok", true).con("book_id", id).con("page", pagina.clone()).con("path", ruta_t))),
            Err(e) => detalle(StatusCode::BAD_REQUEST, format!("No se pudo guardar la edición de la página: {}", py::error_os(&e, &ruta_t))),
        }
    })
    .await
}

// =========================================================================== citas

fn archivo_citas(stem: &str) -> PathBuf {
    citas_dir().join(format!("{stem}.json"))
}

/// `get_book_citations`: lo guardado o una plantilla nueva (que se escribe)
fn citas(state: &AppState, id: &str) -> Valor {
    let ruta = resolver(state, id);
    let stem = match &ruta {
        Some(r) => raiz_de(r),
        None => titulo_de_nombre(id).replace(' ', "_"),
    };
    let archivo = archivo_citas(&stem);
    if archivo.exists() {
        if let Some(v) = leer_json(&archivo) {
            return v;
        }
    }
    let meta = ruta.as_ref().and_then(|r| ficha(state, r));
    let nombre_t = ruta.as_ref().map(|r| py::basename(r)).unwrap_or_else(|| id.to_string());
    let libro = ruta.as_ref().map(|r| py::basename(r)).unwrap_or_else(|| format!("{stem}.pdf"));
    let inicial = Valor::Mapa(
        Mapa::new()
            .con("libro", libro)
            .con("titulo", titulo(meta.as_ref(), &nombre_t))
            .con("stem", stem.as_str())
            .con("archivo_json", format!("{stem}.json"))
            .con("total_citas", 0)
            .con("fecha_actualizacion", ahora())
            .con("citas", Valor::Lista(vec![])),
    );
    let _ = escribir(&archivo, &inicial);
    inicial
}

/// El dict de citas y su `stem` (`current.get("stem") or _book_stem(book_id)`); None si no es un dict
fn actual(state: &AppState, id: &str) -> Option<(Mapa, String)> {
    let Valor::Mapa(m) = citas(state, id) else { return None };
    let stem = m.get("stem").filter(|s| s.verdad()).map(Valor::texto_py).unwrap_or_else(|| raiz_de(id));
    Some((m, stem))
}

/// `(x or "").strip()`; None si no es texto (Python revienta)
fn limpio(v: Option<&Valor>) -> Option<String> {
    match v.filter(|v| v.verdad()) {
        None => Some(String::new()),
        Some(Valor::Texto(t)) => Some(py::strip(t).to_string()),
        Some(_) => None,
    }
}

/// `int(x)` de Python para la página de una cita
fn entero_py(v: Option<&Valor>) -> Option<Valor> {
    match v {
        None => Some(Valor::Entero(1)),
        Some(Valor::Entero(n)) => Some(Valor::Entero(*n)),
        Some(Valor::Bool(b)) => Some(Valor::Entero(*b as i128)),
        Some(Valor::Real(r)) if r.is_finite() => Some(Valor::Entero(r.trunc() as i128)),
        Some(Valor::Texto(t)) => py::strip(t).replace('_', "").parse::<i128>().ok().map(Valor::Entero),
        _ => None,
    }
}

/// La clave de orden `(pagina, id)`: Python compara números con números y textos con textos
#[derive(PartialEq, PartialOrd)]
enum Orden {
    Num(f64),
    Texto(String),
}

fn orden(v: &Valor) -> Option<Orden> {
    match v {
        Valor::Entero(n) => Some(Orden::Num(*n as f64)),
        Valor::Real(r) => Some(Orden::Num(*r)),
        Valor::Bool(b) => Some(Orden::Num(*b as i64 as f64)),
        Valor::Texto(t) => Some(Orden::Texto(t.clone())),
        _ => None,
    }
}

fn ordenar_citas(l: &mut [Valor]) -> Option<()> {
    let mut claves = Vec::with_capacity(l.len());
    for c in l.iter() {
        let Valor::Mapa(c) = c else { return None };
        let p = orden(&c.get("pagina").cloned().unwrap_or(Valor::Entero(0)))?;
        let i = orden(&c.get("id").cloned().unwrap_or(Valor::Texto(String::new())))?;
        claves.push((p, i));
    }
    // tipos mezclados en la misma posición: Python lanza TypeError
    let mezcla = |f: &dyn Fn(&(Orden, Orden)) -> &Orden| {
        let num = claves.iter().filter(|k| matches!(f(k), Orden::Num(_))).count();
        num != 0 && num != claves.len()
    };
    if mezcla(&|k| &k.0) {
        return None;
    }
    let mut idx: Vec<usize> = (0..l.len()).collect();
    let mut roto = false;
    idx.sort_by(|a, b| {
        let (ka, kb) = (&claves[*a], &claves[*b]);
        match ka.0.partial_cmp(&kb.0) {
            Some(std::cmp::Ordering::Equal) => ka.1.partial_cmp(&kb.1).unwrap_or_else(|| {
                roto = true;
                std::cmp::Ordering::Equal
            }),
            Some(o) => o,
            None => std::cmp::Ordering::Equal,
        }
    });
    if roto {
        return None;
    }
    let copia: Vec<Valor> = idx.iter().map(|i| l[*i].clone()).collect();
    l.clone_from_slice(&copia);
    Some(())
}

fn lista_o_comas(v: Option<&Valor>) -> Valor {
    match v {
        Some(Valor::Lista(l)) => Valor::Lista(l.clone()),
        otro => {
            let t = otro.filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default();
            Valor::Lista(t.split(',').map(py::strip).filter(|p| !p.is_empty()).map(|p| Valor::Texto(p.to_string())).collect())
        }
    }
}

enum Fallo {
    Mensaje(String),
    Interno,
}

fn responder(r: Result<Valor, Fallo>) -> Response {
    match r {
        Ok(v) => ok(v),
        Err(Fallo::Mensaje(m)) => detalle(StatusCode::BAD_REQUEST, m),
        Err(Fallo::Interno) => error_500(),
    }
}

fn guardar_cita(state: &AppState, id: &str, datos: &Mapa) -> Result<Valor, Fallo> {
    let (mut actual, stem) = actual(state, id).ok_or(Fallo::Interno)?;
    let cid = datos.get("id").filter(|v| v.verdad()).cloned().unwrap_or_else(|| {
        let s = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        Valor::Texto(format!("cita_{s}_{}", &uuid::Uuid::new_v4().simple().to_string()[..4]))
    });
    let entrada = Mapa::new()
        .con("id", cid.clone())
        .con("pagina", entero_py(datos.get("pagina")).ok_or(Fallo::Interno)?)
        .con("capitulo", limpio(datos.get("capitulo")).ok_or(Fallo::Interno)?)
        .con("texto", limpio(datos.get("texto")).ok_or(Fallo::Interno)?)
        .con("nota", limpio(datos.get("nota")).ok_or(Fallo::Interno)?)
        .con("tags", lista_o_comas(datos.get("tags")))
        .con("fecha", ahora());
    let mut existentes = match actual.get("citas") {
        None => Vec::new(),
        Some(Valor::Lista(l)) => l.clone(),
        Some(_) => return Err(Fallo::Interno),
    };
    let mismo = |c: &Valor| matches!(c, Valor::Mapa(c) if c.get("id") == Some(&cid));
    match existentes.iter().position(mismo) {
        Some(i) => existentes[i] = Valor::Mapa(entrada.clone()),
        None => existentes.push(Valor::Mapa(entrada.clone())),
    }
    ordenar_citas(&mut existentes).ok_or(Fallo::Interno)?;
    let n = existentes.len();
    actual.poner("citas", Valor::Lista(existentes));
    actual.poner("total_citas", n as i64);
    actual.poner("fecha_actualizacion", ahora());
    escribir(&archivo_citas(&stem), &Valor::Mapa(actual.clone())).map_err(|e| Fallo::Mensaje(format!("Error guardando {stem}.json: {e}")))?;
    Ok(Valor::Mapa(
        Mapa::new().con("success", true).con("ok", true).con("cita", entrada).con("book_citations", actual).con("archivo_json", format!("{stem}.json")),
    ))
}

fn borrar_cita(state: &AppState, id: &str, cita: &str) -> Result<Valor, Fallo> {
    let (mut actual, stem) = actual(state, id).ok_or(Fallo::Interno)?;
    let existentes = match actual.get("citas") {
        None => Vec::new(),
        Some(Valor::Lista(l)) => l.clone(),
        Some(_) => return Err(Fallo::Interno),
    };
    let antes = existentes.len();
    let quedan: Vec<Valor> = existentes.into_iter().filter(|c| !matches!(c, Valor::Mapa(c) if c.get("id") == Some(&Valor::Texto(cita.to_string())))).collect();
    if quedan.len() == antes {
        return Err(Fallo::Mensaje(format!("Cita no encontrada: {cita}")));
    }
    let n = quedan.len();
    actual.poner("citas", Valor::Lista(quedan));
    actual.poner("total_citas", n as i64);
    actual.poner("fecha_actualizacion", ahora());
    escribir(&archivo_citas(&stem), &Valor::Mapa(actual)).map_err(|e| Fallo::Mensaje(format!("Error actualizando {stem}.json: {e}")))?;
    Ok(Valor::Mapa(Mapa::new().con("success", true).con("ok", true).con("deleted_id", cita).con("total_citas", n as i64)))
}

fn exportar(state: &AppState, id: &str, ws: &str) -> Result<Valor, Fallo> {
    let (actual, stem) = actual(state, id).ok_or(Fallo::Interno)?;
    let origen = archivo_citas(&stem);
    if !origen.exists() {
        return Err(Fallo::Mensaje(format!("No hay archivo de citas para {id}")));
    }
    let dir = py::abspath(ws);
    py::makedirs(&dir).map_err(|_| Fallo::Interno)?;
    let destino = py::join(&dir, &format!("{stem}.json"));
    crate::routes::librerias::copiar2(&origen, Path::new(&destino)).map_err(|e| Fallo::Mensaje(format!("Error copiando al espacio de trabajo: {}", py::error_os(&e, &destino))))?;
    Ok(Valor::Mapa(
        Mapa::new()
            .con("success", true)
            .con("ok", true)
            .con("exported_to", destino.as_str())
            .con("filename", format!("{stem}.json"))
            .con("total_citas", actual.get("total_citas").cloned().unwrap_or(Valor::Entero(0))),
    ))
}

/// `get_all_citations_for_ai`: las citas de todos los libros (con `query`, las que encajan, por coincidencias)
pub fn todas_las_citas(query: Option<&str>, max: usize) -> Vec<Valor> {
    let dir = citas_dir();
    let Ok(entradas) = std::fs::read_dir(&dir) else { return Vec::new() };
    let terminos: Vec<String> = query.unwrap_or("").split_whitespace().map(str::to_lowercase).filter(|t| t.chars().count() > 2).collect();
    let mut salida: Vec<(i64, Mapa)> = Vec::new();
    for e in entradas.flatten() {
        let f = e.file_name().to_string_lossy().to_string();
        if !f.ends_with(".json") || f == "ediciones" {
            continue;
        }
        let Some(Valor::Mapa(datos)) = leer_json(&dir.join(&f)) else { continue };
        let lleno = |k: &str| datos.get(k).filter(|v| v.verdad()).cloned();
        let titulo = lleno("titulo").or_else(|| lleno("libro")).unwrap_or_else(|| Valor::Texto(f.clone()));
        let libro = lleno("libro").unwrap_or_else(|| Valor::Texto(f.clone()));
        let citas = match datos.get("citas") {
            None => continue,
            Some(Valor::Lista(l)) => l.clone(),
            Some(_) => continue,
        };
        for c in citas {
            let Valor::Mapa(c) = c else { break };
            let g = |k: &str, d: Valor| c.get(k).cloned().unwrap_or(d);
            let vacio = || Valor::Texto(String::new());
            let item = Mapa::new()
                .con("libro", libro.clone())
                .con("titulo", titulo.clone())
                .con("pagina", g("pagina", Valor::Entero(1)))
                .con("capitulo", g("capitulo", vacio()))
                .con("texto", g("texto", vacio()))
                .con("nota", g("nota", vacio()))
                .con("tags", g("tags", Valor::Lista(vec![])))
                .con("id", g("id", vacio()));
            if terminos.is_empty() {
                salida.push((0, item));
                continue;
            }
            let mut n = 0i64;
            let mut roto = false;
            'terminos: for t in &terminos {
                for k in ["texto", "nota"] {
                    match item.get(k) {
                        Some(Valor::Texto(x)) if x.to_lowercase().contains(t.as_str()) => {
                            n += 1;
                            continue 'terminos;
                        }
                        Some(Valor::Texto(_)) => {}
                        _ => {
                            roto = true;
                            break 'terminos;
                        }
                    }
                }
                let partes: Vec<String> = match item.get("tags") {
                    Some(Valor::Lista(l)) => l.iter().map(|x| x.texto_py().to_lowercase()).collect(),
                    Some(Valor::Texto(x)) => x.chars().map(|c| c.to_lowercase().collect()).collect(),
                    Some(Valor::Mapa(m)) => m.claves().map(|k| k.to_lowercase()).collect(),
                    _ => {
                        roto = true;
                        break 'terminos;
                    }
                };
                if partes.iter().any(|x| x.contains(t.as_str())) {
                    n += 1;
                }
            }
            if roto {
                break;
            }
            if n > 0 {
                salida.push((n, item.con("_score", n)));
            }
        }
    }
    if !terminos.is_empty() {
        salida.sort_by(|a, b| b.0.cmp(&a.0));
    }
    salida.into_iter().take(max).map(|(_, m)| Valor::Mapa(m)).collect()
}

/// `GET /api/books/citations?id=`
pub async fn citas_ruta(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let id = match cuerpo::texto_consulta(&q, "id") {
        Ok(i) => i,
        Err(r) => return r,
    };
    en_hilo(move || ok(citas(&state, &id))).await
}

/// `POST /api/books/citations/save` (`book_id`, `citation`)
pub async fn cita_guardar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("book_id", &Tipo::Texto, true), ("citation", &DICT, true)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || responder(guardar_cita(&state, &c.valor("book_id").texto_py(), &c.mapa("citation").cloned().unwrap_or_default()))).await
}

/// `POST /api/books/citations/delete` (`book_id`, `citation_id`)
pub async fn cita_borrar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("book_id", &Tipo::Texto, true), ("citation_id", &Tipo::Texto, true)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || responder(borrar_cita(&state, &c.valor("book_id").texto_py(), &c.valor("citation_id").texto_py()))).await
}

/// `POST /api/books/citations/export` (`book_id`, `workspace_path`)
pub async fn citas_exportar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("book_id", &Tipo::Texto, true), ("workspace_path", &TEXTO_OPC, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    en_hilo(move || {
        let ws = c.get("workspace_path").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| espacio.to_string_lossy().to_string());
        responder(exportar(&state, &c.valor("book_id").texto_py(), &ws))
    })
    .await
}

/// `GET /api/books/all-citations?query=`
pub async fn todas_ruta(Query(q): Query<HashMap<String, String>>) -> Response {
    en_hilo(move || ok(Valor::Lista(todas_las_citas(q.get("query").map(String::as_str), 12)))).await
}
