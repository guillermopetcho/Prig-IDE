//! Exportar una carpeta a PDF (`pdf_exporter.py`): los cuadernos y archivos de código que hay
//! (`/api/folder/code-files`), la vista previa en HTML con el código resaltado (`/api/export/pdf-preview`) y el PDF,
//! que compone Typst (`/api/export/pdf-download`). El resaltado de la vista previa lo hace syntect con colores en
//! línea: Python usaba pygments (mismo HTML alrededor, otros colores dentro del bloque de código).

use std::collections::HashMap;
use std::sync::OnceLock;

use axum::{
    body::Bytes,
    extract::Query,
    http::{header, StatusCode},
    response::{IntoResponse, Response},
};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use prig_recursos::servidor::lineas_como_python;
use syntect::easy::HighlightLines;
use syntect::highlighting::{FontStyle, Theme};
use syntect::parsing::SyntaxSet;

use crate::routes::{cuerpo, json_py};

const EXTENSIONES: [(&str, &str); 22] = [
    (".py", "python"),
    (".js", "javascript"),
    (".ts", "typescript"),
    (".jsx", "jsx"),
    (".tsx", "tsx"),
    (".html", "html"),
    (".css", "css"),
    (".json", "json"),
    (".md", "markdown"),
    (".sh", "bash"),
    (".bash", "bash"),
    (".c", "c"),
    (".cpp", "cpp"),
    (".h", "c"),
    (".hpp", "cpp"),
    (".java", "java"),
    (".sql", "sql"),
    (".yml", "yaml"),
    (".yaml", "yaml"),
    (".r", "r"),
    (".php", "php"),
    (".rb", "ruby"),
];

const IGNORADAS: [&str; 17] = [
    "__pycache__", "node_modules", "venv", ".venv", "env", ".env", ".git", ".github", ".ipynb_checkpoints", "dist", "build", ".cache",
    "site-packages", ".idea", ".vscode", ".gemini", ".antigravity",
];

fn lenguaje(ext: &str) -> Option<&'static str> {
    EXTENSIONES.iter().find(|(e, _)| *e == ext).map(|(_, l)| *l)
}

fn ext_de(nombre: &str) -> String {
    py::splitext(nombre).1.to_lowercase()
}

fn escapar(t: &str) -> String {
    t.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&#x27;")
}

fn sin_menor_mayor(t: &str) -> String {
    t.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}

/// Leer como `open(..., encoding="utf-8", errors="replace")` en modo texto (\r\n y \r pasan a \n)
fn leer_texto(ruta: &str) -> Result<String, String> {
    let b = std::fs::read(ruta).map_err(|e| py::error_os(&e, ruta))?;
    Ok(String::from_utf8_lossy(&b).replace("\r\n", "\n").replace('\r', "\n"))
}

// =========================================================================== lista de archivos

/// Las líneas como `sum(1 for _ in f)` en modo texto
fn contar_lineas(b: &[u8]) -> usize {
    let mut n = 0;
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'\n' || b[i] == b'\r' {
            n += 1;
            if b[i] == b'\r' && b.get(i + 1) == Some(&b'\n') {
                i += 1;
            }
        }
        i += 1;
    }
    if !b.is_empty() && !matches!(b[b.len() - 1], b'\n' | b'\r') {
        n += 1;
    }
    n
}

fn celdas(b: &[u8]) -> usize {
    match prig_plataforma::json::leer(&String::from_utf8_lossy(b)) {
        Ok(Valor::Mapa(m)) => match m.get("cells") {
            None => 0,
            Some(Valor::Lista(l)) => l.len(),
            Some(Valor::Mapa(c)) => c.len(),
            Some(Valor::Texto(t)) => t.chars().count(),
            _ => 0,
        },
        _ => 0,
    }
}

/// `os.walk` de arriba abajo (las carpetas en el orden del sistema, sin seguir enlaces) con los archivos ordenados
fn recorrer(raiz: &str, carpeta: &str, salida: &mut Vec<Valor>) {
    let Ok(entradas) = std::fs::read_dir(carpeta) else { return };
    let (mut dirs, mut archivos) = (Vec::new(), Vec::new());
    for e in entradas.flatten() {
        let nombre = e.file_name().to_string_lossy().to_string();
        let es_dir = std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false);
        if es_dir {
            let enlace = e.file_type().map(|t| t.is_symlink()).unwrap_or(false);
            dirs.push((nombre, enlace));
        } else {
            archivos.push(nombre);
        }
    }
    archivos.sort();
    for f in archivos {
        if f.starts_with('.') {
            continue;
        }
        let ext = ext_de(&f);
        let es_nb = ext == ".ipynb";
        if !es_nb && lenguaje(&ext).is_none() {
            continue;
        }
        let ruta = py::join(carpeta, &f);
        let bytes = std::fs::read(&ruta).unwrap_or_default();
        let tam = std::fs::metadata(&ruta).map(|m| m.len()).unwrap_or(0);
        salida.push(Valor::Mapa(
            Mapa::new()
                .con("name", f.as_str())
                .con("path", ruta.as_str())
                .con("rel_path", py::relpath(&ruta, raiz))
                .con("extension", ext.as_str())
                .con("is_notebook", es_nb)
                .con("size", tam as i64)
                .con("lines_count", if es_nb { 0 } else { contar_lineas(&bytes) as i64 })
                .con("cells_count", if es_nb { celdas(&bytes) as i64 } else { 0 }),
        ));
    }
    for (d, enlace) in dirs {
        if IGNORADAS.contains(&d.as_str()) || d.starts_with('.') || enlace {
            continue;
        }
        recorrer(raiz, &py::join(carpeta, &d), salida);
    }
}

/// `GET /api/folder/code-files?path=`
pub async fn archivos_de_codigo(Query(q): Query<HashMap<String, String>>) -> Response {
    let ruta = match cuerpo::texto_consulta(&q, "path") {
        Ok(r) => r,
        Err(r) => return r,
    };
    tokio::task::spawn_blocking(move || {
        let abs = py::abspath(&ruta);
        if !std::path::Path::new(&abs).is_dir() {
            return Valor::Mapa(Mapa::new().con("error", format!("La carpeta no existe: {ruta}")).con("files", Valor::Lista(vec![])));
        }
        let mut archivos = Vec::new();
        recorrer(&abs, &abs, &mut archivos);
        let nombre = Some(py::basename(&abs)).filter(|n| !n.is_empty()).unwrap_or_else(|| abs.clone());
        Valor::Mapa(
            Mapa::new()
                .con("folder_name", nombre)
                .con("folder_path", abs.as_str())
                .con("total_files", archivos.len() as i64)
                .con("files", Valor::Lista(archivos)),
        )
    })
    .await
    .map(|v| json_py(StatusCode::OK, &v))
    .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response())
}

// =========================================================================== resaltado

fn sintaxis() -> &'static SyntaxSet {
    static S: OnceLock<SyntaxSet> = OnceLock::new();
    S.get_or_init(two_face::syntax::extra_newlines)
}

/// El estilo de pygments de cada tema (default, dracula, friendly) y su fondo
fn estilo(tema: &str) -> (&'static Theme, &'static str) {
    use two_face::theme::EmbeddedThemeName as T;
    static S: OnceLock<two_face::theme::EmbeddedLazyThemeSet> = OnceLock::new();
    let temas = S.get_or_init(two_face::theme::extra);
    match tema {
        "light" => (temas.get(T::InspiredGithub), "#f8f8f8"),
        "dark" => (temas.get(T::Dracula), "#282a36"),
        _ => (temas.get(T::Github), "#f0f0f0"),
    }
}

fn token_de(lenguaje: Option<&str>) -> &'static str {
    match lenguaje {
        Some("python") => "py",
        Some("javascript") | Some("jsx") => "js",
        Some("typescript") => "ts",
        Some("tsx") => "tsx",
        Some("html") => "html",
        Some("css") => "css",
        Some("json") => "json",
        Some("markdown") => "md",
        Some("bash") => "sh",
        Some("c") => "c",
        Some("cpp") => "cpp",
        Some("java") => "java",
        Some("sql") => "sql",
        Some("yaml") => "yaml",
        Some("r") => "r",
        Some("php") => "php",
        Some("ruby") => "rb",
        _ => "txt",
    }
}

/// `pygments.highlight(codigo, lexer, HtmlFormatter(noclasses=True))`: un `div.highlight` con el `pre` y los colores
/// en línea
fn resaltar(codigo: &str, lenguaje: Option<&str>, tema: &str) -> String {
    let ss = sintaxis();
    let sint = ss.find_syntax_by_token(token_de(lenguaje)).unwrap_or_else(|| ss.find_syntax_plain_text());
    let (t, fondo) = estilo(tema);
    let base = t.settings.foreground;
    let mut h = HighlightLines::new(sint, t);
    let mut texto = codigo.to_string();
    if !texto.ends_with('\n') {
        texto.push('\n');
    }
    let mut cuerpo = String::new();
    for linea in syntect::util::LinesWithEndings::from(&texto) {
        let Ok(trozos) = h.highlight_line(linea, ss) else {
            cuerpo.push_str(&escapar(linea));
            continue;
        };
        for (s, t) in trozos {
            if t.is_empty() {
                continue;
            }
            let mut css = Vec::new();
            if Some(s.foreground) != base {
                css.push(format!("color: #{:02X}{:02X}{:02X}", s.foreground.r, s.foreground.g, s.foreground.b).to_lowercase());
            }
            if s.font_style.contains(FontStyle::BOLD) {
                css.push("font-weight: bold".into());
            }
            if s.font_style.contains(FontStyle::ITALIC) {
                css.push("font-style: italic".into());
            }
            if css.is_empty() || t.trim().is_empty() {
                cuerpo.push_str(&escapar(t));
            } else {
                cuerpo.push_str(&format!("<span style=\"{}\">{}</span>", css.join("; "), escapar(t)));
            }
        }
    }
    format!("<div class=\"highlight\" style=\"background: {fondo}\"><pre style=\"line-height: 125%;\"><span></span>{cuerpo}</pre></div>\n")
}

// =========================================================================== vista previa

fn css_tema(tema: &str, tam: &str, pagina: &str) -> String {
    let (bg_main, bg_card, bg_code, text_main, text_muted, border_col, accent_blue, accent_purple, accent_tag, banner_bg) = match tema {
        "dark" => ("#141417", "#1e1e24", "#18181c", "#e0e0e6", "#8a8a99", "#2d2d38", "#61afef", "#c678dd", "#98c379", "linear-gradient(135deg, #1f2335 0%, #282c34 100%)"),
        "executive" => ("#f9f8f6", "#ffffff", "#f4f3ef", "#2c2c2c", "#666666", "#d8d6d0", "#2b5797", "#68217a", "#008a00", "linear-gradient(135deg, #2b5797 0%, #1e395b 100%)"),
        _ => ("#ffffff", "#ffffff", "#f8f9fa", "#1a1a1a", "#555555", "#e1e4e8", "#0969da", "#8250df", "#1a7f37", "linear-gradient(135deg, #0969da 0%, #0349b4 100%)"),
    };
    let fuente = if tema == "executive" { "Georgia, serif" } else { "'Inter', system-ui, -apple-system, sans-serif" };
    let titulo = if tema == "dark" || tema == "executive" { "#ffffff" } else { "#0969da" };
    let valores: [(&str, &str); 15] = [
        ("fuente", fuente),
        ("titulo_portada", titulo),
        ("page_size", pagina),
        ("base_size", tam),
        ("bg_main", bg_main),
        ("bg_card", bg_card),
        ("bg_code", bg_code),
        ("text_main", text_main),
        ("text_muted", text_muted),
        ("border_col", border_col),
        ("accent_blue", accent_blue),
        ("accent_purple", accent_purple),
        ("accent_tag", accent_tag),
        ("banner_bg", banner_bg),
        ("theme", tema),
    ];
    // La plantilla es la f-string de Python: {{ y }} son llaves; {nombre}, un valor
    let plantilla = include_str!("exportar_tema.css");
    let mut s = String::with_capacity(plantilla.len() + 512);
    let mut resto = plantilla;
    while let Some(i) = resto.find(['{', '}']) {
        s.push_str(&resto[..i]);
        let r = &resto[i..];
        if r.starts_with("{{") || r.starts_with("}}") {
            s.push_str(&r[..1]);
            resto = &r[2..];
        } else if let (true, Some(f)) = (r.starts_with('{'), r.find('}')) {
            let nombre = &r[1..f];
            s.push_str(valores.iter().find(|(n, _)| *n == nombre).map(|(_, v)| *v).unwrap_or(""));
            resto = &r[f + 1..];
        } else {
            s.push_str(&r[..1]);
            resto = &r[1..];
        }
    }
    s.push_str(resto);
    s
}

fn markdown_simple(t: &str) -> String {
    static R: OnceLock<[(regex::Regex, &'static str); 6]> = OnceLock::new();
    let r = R.get_or_init(|| {
        [
            (regex::Regex::new(r"(?m)^# (.*$)").unwrap(), r#"<h1 class="pdf-h1">$1</h1>"#),
            (regex::Regex::new(r"(?m)^## (.*$)").unwrap(), r#"<h2 class="pdf-h2">$1</h2>"#),
            (regex::Regex::new(r"(?m)^### (.*$)").unwrap(), r#"<h3 class="pdf-h3">$1</h3>"#),
            (regex::Regex::new(r"\*\*([^*]+)\*\*").unwrap(), "<strong>$1</strong>"),
            (regex::Regex::new(r"\*([^*]+)\*").unwrap(), "<em>$1</em>"),
            (regex::Regex::new(r"`([^`]+)`").unwrap(), r#"<code class="pdf-inline-code">$1</code>"#),
        ]
    });
    let mut s = sin_menor_mayor(t);
    for (re, por) in r.iter() {
        s = re.replace_all(&s, *por).into_owned();
    }
    s.replace('\n', "<br>")
}

fn numeros(n: usize) -> String {
    (1..=n).map(|i| format!("<span class=\"lineno\">{i}</span>")).collect::<Vec<_>>().join("\n")
}

fn codigo_con_numeros(resaltado: &str, n: usize, numerar: bool, sangria: &str) -> String {
    if numerar {
        format!(
            "<div class=\"pdf-code-container\">\n{sangria}    <div class=\"pdf-lineno-col\">{}</div>\n{sangria}    <div class=\"pdf-code-content\">{resaltado}</div>\n{sangria}</div>",
            numeros(n)
        )
    } else {
        format!("<div class=\"pdf-code-content\">{resaltado}</div>")
    }
}

/// `str()` de Python de un valor de las opciones
fn texto(v: &Valor) -> String {
    v.texto_py()
}

struct Opciones {
    salidas: bool,
    numeros: bool,
    portada: bool,
    tam: String,
    pagina: String,
}

fn opciones(o: Option<&Mapa>) -> Opciones {
    let vacio = Mapa::new();
    let o = o.unwrap_or(&vacio);
    let si = |k: &str| o.get(k).is_none_or(Valor::verdad);
    Opciones {
        salidas: si("include_outputs"),
        numeros: si("show_line_numbers"),
        portada: si("include_cover"),
        tam: o.get("font_size").filter(|v| v.verdad()).map(texto).unwrap_or_else(|| "13px".into()),
        pagina: o.get("page_size").map(texto).unwrap_or_else(|| "a4".into()),
    }
}

fn salida_de(o: &serde_json::Value) -> String {
    let campo = |k: &str| match o.get(k) {
        Some(serde_json::Value::String(s)) => s.clone(),
        Some(serde_json::Value::Null) | None => String::new(),
        Some(v) => v.to_string(),
    };
    match o.get("type").and_then(|t| t.as_str()).unwrap_or("") {
        "error" => format!(
            "<div class=\"pdf-out-line pdf-out-err\"><i class=\"fa-solid fa-triangle-exclamation\"></i> <pre>{}</pre></div>",
            sin_menor_mayor(&campo("text"))
        ),
        "html" => format!("<div class=\"pdf-out-line pdf-out-html\">{}</div>", campo("text")),
        "image" => {
            let b64: String = campo("data").replace(['\n', '\r'], "");
            let mime = o.get("mime").and_then(|m| m.as_str()).unwrap_or("image/png");
            format!("<div class=\"pdf-out-line pdf-out-img\"><img src=\"data:{mime};base64,{}\" alt=\"Notebook Plot\" /></div>", b64.trim())
        }
        _ => format!("<div class=\"pdf-out-line pdf-out-stdout\"><pre>{}</pre></div>", sin_menor_mayor(&campo("text"))),
    }
}

fn notebook_html(ruta: &str, rel: &str, tema: &str, op: &Opciones) -> String {
    let crudo = match leer_texto(ruta) {
        Ok(t) => t,
        Err(e) => return format!("<div class=\"pdf-section-card\"><div class=\"pdf-error\">Error al leer notebook {rel}: {e}</div></div>"),
    };
    let nb = prig_fs::FileManager::new(std::path::PathBuf::from("/")).read_notebook_structured(&crudo, ruta);
    let nombre = py::basename(ruta);
    let mut celdas = Vec::new();
    for (i, c) in nb.cells.iter().enumerate() {
        let idx = i + 1;
        if c.cell_type == "markdown" {
            celdas.push(format!(
                "\n                <div class=\"pdf-nb-cell pdf-cell-markdown\">\n                    <div class=\"pdf-cell-header\">\n                        <span class=\"pdf-tag pdf-tag-md\"><i class=\"fa-solid fa-align-left\"></i> Markdown</span>\n                    </div>\n                    <div class=\"pdf-cell-body pdf-md-body\">\n                        {}\n                    </div>\n                </div>\n                ",
                markdown_simple(&c.source)
            ));
            continue;
        }
        let resaltado = resaltar(&c.source, Some("python"), tema);
        let lineas = codigo_con_numeros(&resaltado, lineas_como_python(&c.source).len(), op.numeros, "                    ");
        let n = c.execution_count.map(|e| e.to_string()).unwrap_or_else(|| idx.to_string());
        let mut salidas = String::new();
        if op.salidas && !c.outputs.is_empty() {
            let items: String = c.outputs.iter().map(salida_de).collect();
            salidas = format!(
                "\n                    <div class=\"pdf-nb-outputs\">\n                        <div class=\"pdf-nb-out-tag\">Out [{n}]:</div>\n                        {items}\n                    </div>\n                    "
            );
        }
        celdas.push(format!(
            "\n                <div class=\"pdf-nb-cell pdf-cell-code\">\n                    <div class=\"pdf-cell-header\">\n                        <span class=\"pdf-tag pdf-tag-code\"><i class=\"fa-brands fa-python\"></i> In [{n}]:</span>\n                    </div>\n                    <div class=\"pdf-cell-body\">\n                        {lineas}\n                    </div>\n                    {salidas}\n                </div>\n                "
        ));
    }
    format!(
        "\n        <div class=\"pdf-file-document\">\n            <div class=\"pdf-file-banner pdf-banner-notebook\">\n                <div class=\"pdf-banner-title\"><i class=\"fa-solid fa-book-bookmark\"></i> {}</div>\n                <div class=\"pdf-banner-path\"><i class=\"fa-solid fa-folder\"></i> {}</div>\n                <div class=\"pdf-banner-badge\">{} CELDAS</div>\n            </div>\n            <div class=\"pdf-file-body\">\n                {}\n            </div>\n        </div>\n        ",
        escapar(&nombre),
        escapar(rel),
        nb.cells.len(),
        celdas.join("")
    )
}

fn codigo_html(ruta: &str, rel: &str, tema: &str, op: &Opciones) -> String {
    let nombre = py::basename(ruta);
    let codigo = match leer_texto(ruta) {
        Ok(t) => t,
        Err(e) => return format!("<div class=\"pdf-section-card\"><div class=\"pdf-error\">Error al leer código {rel}: {e}</div></div>"),
    };
    let resaltado = resaltar(&codigo, lenguaje(&ext_de(&nombre)), tema);
    let n = lineas_como_python(&codigo).len();
    let marca = codigo_con_numeros(&resaltado, n, op.numeros, "            ");
    let ext = py::splitext(&nombre).1.to_uppercase().replace('.', "");
    let ext = if ext.is_empty() { "FILE".to_string() } else { ext };
    format!(
        "\n        <div class=\"pdf-file-document\">\n            <div class=\"pdf-file-banner pdf-banner-code\">\n                <div class=\"pdf-banner-title\"><i class=\"fa-solid fa-code\"></i> {nombre}</div>\n                <div class=\"pdf-banner-path\"><i class=\"fa-solid fa-folder\"></i> {rel}</div>\n                <div class=\"pdf-banner-badge\">{n} LÍNEAS | {ext}</div>\n            </div>\n            <div class=\"pdf-file-body\">\n                <div class=\"pdf-code-block\">\n                    {marca}\n                </div>\n            </div>\n        </div>\n        "
    )
}

const LISTA_TEXTOS: Tipo = Tipo::Lista(&Tipo::Texto);
const DICT_OPC: Tipo = Tipo::Opcional(&Tipo::Dict(&Tipo::Cualquiera));

/// El cuerpo `PDFExportRequest`
fn pedido(b: &Bytes) -> Result<(String, Vec<String>, String, Option<Mapa>), Response> {
    let m = cuerpo::modelo(b)?;
    let c = cuerpo::tipados(&m, &[("folder_path", &Tipo::Texto, true), ("file_paths", &LISTA_TEXTOS, true), ("theme", &Tipo::Texto, false), ("options", &DICT_OPC, false)])?;
    let archivos = c.lista("file_paths").unwrap_or(&[]).iter().map(Valor::texto_py).collect();
    let tema = c.get("theme").map(Valor::texto_py).unwrap_or_else(|| "light".into());
    let op = c.mapa("options").cloned();
    Ok((c.valor("folder_path").texto_py(), archivos, tema, op))
}

fn es_archivo(r: &str) -> bool {
    std::path::Path::new(r).is_file()
}

/// `POST /api/export/pdf-preview`
pub async fn vista_previa(b: Bytes) -> Response {
    let (carpeta, archivos, tema, op) = match pedido(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    tokio::task::spawn_blocking(move || {
        let op = opciones(op.as_ref());
        let abs = py::abspath(&carpeta);
        let nombre = Some(py::basename(&abs)).filter(|n| !n.is_empty()).unwrap_or_else(|| abs.clone());
        let secciones: Vec<String> = archivos
            .iter()
            .filter(|r| es_archivo(r))
            .map(|r| {
                let rel = py::relpath(r, &abs);
                if ext_de(&py::basename(r)) == ".ipynb" {
                    notebook_html(r, &rel, &tema, &op)
                } else {
                    codigo_html(r, &rel, &tema, &op)
                }
            })
            .collect();
        let portada = if op.portada {
            format!(
                "\n            <div class=\"pdf-cover-page\">\n                <div class=\"pdf-cover-badge\"><i class=\"fa-solid fa-file-pdf\"></i> DOCUMENTO EXPORTADO</div>\n                <h1 class=\"pdf-cover-title\">{}</h1>\n                <p class=\"pdf-cover-subtitle\">Cuadernos Jupyter y Código Fuente Estilizado</p>\n                <div class=\"pdf-cover-meta\">\n                    <div class=\"meta-item\"><strong>Ruta:</strong> <code>{}</code></div>\n                    <div class=\"meta-item\"><strong>Archivos exportados:</strong> {}</div>\n                    <div class=\"meta-item\"><strong>Generado con:</strong> Prig IDE - Editor & Tutor IA</div>\n                </div>\n            </div>\n            <div class=\"pdf-page-break\"></div>\n            ",
                escapar(&nombre),
                escapar(&abs),
                archivos.len()
            )
        } else {
            String::new()
        };
        let css = css_tema(&tema, &op.tam, &op.pagina);
        let html = format!(
            "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n    <meta charset=\"UTF-8\">\n    <title>Exportación PDF - {}</title>\n    <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css\">\n    <link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Inter:wght@300;400;500;600;700&display=swap\">\n    <style>\n        {css}\n    </style>\n</head>\n<body class=\"theme-{tema}\">\n    <div class=\"pdf-container\">\n        {portada}\n        {}\n    </div>\n</body>\n</html>",
            escapar(&nombre),
            secciones.join("<div class=\"pdf-page-break\"></div>")
        );
        json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("html", html)))
    })
    .await
    .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response())
}

/// `POST /api/export/pdf-download`: el PDF lo compone Typst (prig-documentos)
pub async fn descargar(b: Bytes) -> Response {
    let (carpeta, archivos, _tema, _op) = match pedido(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    tokio::task::spawn_blocking(move || {
        let abs = py::abspath(&carpeta);
        let nombre = Some(py::basename(&abs)).filter(|n| !n.is_empty()).unwrap_or_else(|| abs.clone());
        let mut bloques = vec![Valor::Mapa(
            Mapa::new()
                .con("tipo", "titulo")
                .con("texto", format!("Exportación de Código: {nombre}"))
                .con("sub", format!("Generado con Prig IDE | Total archivos: {}", archivos.len())),
        )];
        let bloque = |tipo: &str, texto: String| Valor::Mapa(Mapa::new().con("tipo", tipo).con("texto", texto));
        let codigo = |texto: String, lenguaje: Option<&str>| Valor::Mapa(Mapa::new().con("tipo", "codigo").con("texto", texto).con("lenguaje", lenguaje.map(Valor::from).unwrap_or(Valor::Nulo)));
        let primeras = |t: &str, n: usize| lineas_como_python(t).into_iter().take(n).collect::<Vec<_>>().join("\n");
        for r in archivos.iter().filter(|r| es_archivo(r)) {
            let f = py::basename(r);
            let ext = ext_de(&f);
            bloques.push(bloque("banner", format!("{f}  ({})", py::relpath(r, &abs))));
            match (ext == ".ipynb", leer_texto(r)) {
                (true, Ok(crudo)) => {
                    let nb = prig_fs::FileManager::new(std::path::PathBuf::from("/")).read_notebook_structured(&crudo, r);
                    for (i, c) in nb.cells.iter().enumerate() {
                        let md = c.cell_type == "markdown";
                        let n = c.execution_count.filter(|e| *e != 0).map(|e| e.to_string()).unwrap_or_else(|| (i + 1).to_string());
                        bloques.push(bloque("celda", if md { "Markdown".into() } else { format!("In [{n}]:") }));
                        bloques.push(codigo(primeras(&c.source, 100), if md { None } else { Some("python") }));
                    }
                }
                (true, Err(e)) => bloques.push(bloque("nota", format!("Error procesando notebook: {e}"))),
                (false, Ok(t)) => bloques.push(codigo(primeras(&t, 300), lenguaje(&ext))),
                (false, Err(e)) => bloques.push(bloque("nota", format!("Error procesando archivo: {e}"))),
            }
            bloques.push(Valor::Mapa(Mapa::new().con("tipo", "espacio").con("alto", 15)));
        }
        let doc = Mapa::new().con("titulo", format!("Exportación de Código: {nombre}")).con("estilo", "codigo").con("bloques", Valor::Lista(bloques));
        let datos = match prig_documentos::pdf_de_json(&prig_plataforma::json::escribir_compacto(&Valor::Mapa(doc))) {
            Ok((d, _)) => d,
            Err(_) => return StatusCode::INTERNAL_SERVER_ERROR.into_response(),
        };
        let carpeta_n = Some(py::basename(&abs)).filter(|n| !n.is_empty()).unwrap_or_else(|| "export".into());
        (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "application/pdf".to_string()), (header::CONTENT_DISPOSITION, format!("attachment; filename=\"{carpeta_n}_code_notebooks.pdf\""))],
            datos,
        )
            .into_response()
    })
    .await
    .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response())
}
