//! La búsqueda web del motor de IA (`ai_engine/web_search_engine.py`): si una pregunta pide internet, reordenar los
//! resultados (dominios oficiales, palabras de la consulta), descargar las páginas en paralelo y quedarse con su
//! texto principal, la caché en disco (24 h) y el bloque de contexto para el modelo. Encontrar los resultados
//! (DuckDuckGo por la biblioteca `ddgs`) sigue en Python, como herramienta.
//!
//! Diferencia escrita: el HTML se lee con html5ever (el parser de los navegadores) y no con el `html.parser` de
//! BeautifulSoup; con HTML mal cerrado (un <p> sin cierre) el texto que se extrae puede repartirse distinto.

use prig_plataforma::py;
use prig_plataforma::regex_py::ExpresionPy;
use prig_recursos::json;
use prig_recursos::valor::{Mapa, Valor};
use scraper::{ElementRef, Html, Node};
use std::sync::OnceLock;
use std::time::Duration;

pub const AGENTE: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

pub const DOMINIOS_OFICIALES: &[&str] = &[
    "docs.python.org", "numpy.org", "pandas.pydata.org", "scikit-learn.org", "pytorch.org", "tensorflow.org",
    "matplotlib.org", "scipy.org", "pypi.org", "developer.mozilla.org", "fastapi.tiangolo.com",
    "flask.palletsprojects.com", "djangoproject.com", "react.dev", "nextjs.org", "vuejs.org", "nodejs.org",
    "docs.docker.com", "kubernetes.io", "git-scm.com", "docs.github.com", "registry.terraform.io", "ansible.com",
    "arxiv.org", "wikipedia.org", "paperswithcode.com", "github.com", "gitlab.com",
];

const DISPARADORES: &[&str] = &[
    r"\b(cómo|como)\s+(hacer|usar|implementar|crear|configurar)\b",
    r"\b(ejemplo|tutorial|documentación|docs|oficial)\b",
    r"\b(error|exception|traceback|attributeerror|typeerror|importerror|valderror)\b",
    r"\b(novedades|versión|version|diferencia|vs|comparación)\b",
    r"\b(fastapi|python|pandas|numpy|pytorch|tensorflow|react|docker|kubernetes|flask|django|scikit-learn)\b",
    r"\b(sintaxis|método|metodo|función|funcion|clase|librería|libreria|paquete)\b",
];

fn disparadores() -> &'static Vec<ExpresionPy> {
    static D: OnceLock<Vec<ExpresionPy>> = OnceLock::new();
    D.get_or_init(|| DISPARADORES.iter().map(|p| ExpresionPy::compilar(p, true).expect("disparador")).collect())
}

fn palabras() -> &'static ExpresionPy {
    static P: OnceLock<ExpresionPy> = OnceLock::new();
    P.get_or_init(|| ExpresionPy::compilar(r"\w+", true).expect("palabras"))
}

/// `should_auto_search(prompt)`: ¿la pregunta pide documentación o información de internet?
pub fn pide_internet(prompt: &str) -> bool {
    if py::strip(prompt).chars().count() < 4 {
        return false;
    }
    let bajo = prompt.to_lowercase();
    disparadores().iter().any(|e| e.buscar(&bajo).is_some())
}

fn conjunto(t: &str) -> std::collections::HashSet<String> {
    palabras().todos(&t.to_lowercase()).into_iter().filter_map(|g| g[0].clone()).collect()
}

fn texto_de(item: &Mapa, k: &str) -> String {
    match item.get(k) {
        Some(Valor::Texto(t)) => t.clone(),
        Some(Valor::Nulo) | None => String::new(),
        Some(otro) => otro.texto_py(),
    }
}

/// `score_and_rerank(query, items)`: los oficiales primero, después por palabras de la consulta; sin repetidos
pub fn reordenar(consulta: &str, items: &[Mapa], maximo: usize) -> Vec<Mapa> {
    let q = conjunto(consulta);
    let puntos = |item: &Mapa| -> f64 {
        let href = texto_de(item, "href").to_lowercase();
        let mut p = 0.0;
        if DOMINIOS_OFICIALES.iter().any(|d| href.contains(d)) {
            p += 50.0;
        }
        p += q.intersection(&conjunto(&texto_de(item, "title"))).count() as f64 * 10.0;
        p += q.intersection(&conjunto(&texto_de(item, "snippet"))).count() as f64 * 3.0;
        if href.contains("geeksforgeeks.org") || href.contains("javatpoint.com") {
            p -= 10.0;
        }
        p
    };
    let mut con: Vec<(f64, &Mapa)> = items.iter().map(|i| (puntos(i), i)).collect();
    // sorted(reverse=True) de Python: estable, los empates en su orden
    con.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut vistos = std::collections::HashSet::new();
    let mut salida = Vec::new();
    for (_, item) in con {
        let url = item.valor("href");
        if url.verdad() && vistos.insert(url.texto_py()) {
            salida.push(item.clone());
        }
    }
    salida.truncate(maximo);
    salida
}

const QUITAR: &[&str] = &["script", "style", "nav", "footer", "header", "form", "aside", "noscript", "svg"];
const BLOQUES: &[&str] = &["h1", "h2", "h3", "p", "pre", "code", "li"];

/// `get_text(strip=True)` de BeautifulSoup: cada trozo de texto sin blancos alrededor, todos juntos (sin lo quitado)
fn texto_limpio(e: ElementRef) -> String {
    let mut s = String::new();
    fn recorrer(n: ego_tree::NodeRef<Node>, s: &mut String) {
        for h in n.children() {
            match h.value() {
                Node::Text(t) => s.push_str(py::strip(t)),
                Node::Element(el) if QUITAR.contains(&el.name()) => {}
                Node::Element(_) => recorrer(h, s),
                _ => {}
            }
        }
    }
    recorrer(*e, &mut s);
    s
}

fn dentro_de_quitado(e: ElementRef) -> bool {
    e.ancestors().any(|a| matches!(a.value(), Node::Element(el) if QUITAR.contains(&el.name())))
}

/// El texto principal de una página: títulos, párrafos, código y listas, en el orden del documento
pub fn texto_de_pagina(html: &str, max_caracteres: usize) -> String {
    let doc = Html::parse_document(html);
    let mut lineas = Vec::new();
    for nodo in doc.tree.root().descendants() {
        let Some(e) = ElementRef::wrap(nodo) else { continue };
        let nombre = e.value().name();
        if !BLOQUES.contains(&nombre) || dentro_de_quitado(e) {
            continue;
        }
        let t = texto_limpio(e);
        if t.is_empty() {
            continue;
        }
        lineas.push(match nombre {
            "h1" | "h2" | "h3" => format!("\n### {t}"),
            "pre" | "code" => format!("```\n{t}\n```"),
            _ => t,
        });
    }
    let todo = lineas.join("\n");
    // re.sub(r'\n{3,}', '\n\n', ...)
    let mut s = String::with_capacity(todo.len());
    let mut saltos = 0;
    for c in todo.chars() {
        if c == '\n' {
            saltos += 1;
            continue;
        }
        if saltos > 0 {
            s.push_str(if saltos >= 2 { "\n\n" } else { "\n" });
            saltos = 0;
        }
        s.push(c);
    }
    if saltos > 0 {
        s.push_str(if saltos >= 2 { "\n\n" } else { "\n" });
    }
    s.chars().take(max_caracteres).collect()
}

/// `fetch_url_content(url)`: la página y su texto principal ("" si no se pudo)
pub fn leer_pagina(url: &str, segundos: f64, max_caracteres: usize) -> String {
    if url.is_empty() || !url.starts_with("http") {
        return String::new();
    }
    let Ok(c) = reqwest::blocking::Client::builder().timeout(Duration::from_secs_f64(segundos)).build() else { return String::new() };
    let Ok(r) = c.get(url).header("User-Agent", AGENTE).send() else { return String::new() };
    if r.status().as_u16() != 200 {
        return String::new();
    }
    let Ok(t) = r.text() else { return String::new() };
    texto_de_pagina(&t, max_caracteres)
}

fn dominio(url: &str) -> String {
    // urllib.parse.urlparse(url).netloc
    let resto = url.split_once("://").map(|x| x.1).unwrap_or("");
    if !url.contains("://") {
        return String::new();
    }
    resto.split(['/', '?', '#']).next().unwrap_or("").to_string()
}

/// El bloque de contexto para el modelo a partir de los resultados (descargando sus páginas en paralelo, de 3 en 3)
pub fn contexto(resultados: &[Mapa], segundos: f64, max_caracteres: usize) -> (String, Vec<Valor>) {
    let con_url: Vec<&Mapa> = resultados.iter().filter(|r| r.valor("href").verdad()).collect();
    let contenidos: Vec<String> = {
        let siguiente = std::sync::atomic::AtomicUsize::new(0);
        let salida: Vec<std::sync::Mutex<String>> = con_url.iter().map(|_| Default::default()).collect();
        std::thread::scope(|s| {
            for _ in 0..3 {
                s.spawn(|| loop {
                    let i = siguiente.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                    if i >= con_url.len() {
                        break;
                    }
                    *salida[i].lock().unwrap() = leer_pagina(&texto_de(con_url[i], "href"), segundos, max_caracteres);
                });
            }
        });
        salida.into_iter().map(|m| m.into_inner().unwrap()).collect()
    };
    let mut fuentes = Vec::new();
    let mut paginas = Vec::new();
    for (item, contenido) in con_url.iter().zip(contenidos) {
        if contenido.is_empty() || py::strip(&contenido).chars().count() <= 50 {
            continue;
        }
        let href = texto_de(item, "href");
        let d = dominio(&href);
        let titulo = item.valor("title").texto_py();
        fuentes.push(Valor::Mapa(
            Mapa::new()
                .con("title", item.valor("title").clone())
                .con("url", href.clone())
                .con("domain", d.clone())
                .con("snippet", item.get("snippet").cloned().unwrap_or(Valor::Texto(String::new()))),
        ));
        paginas.push(format!("📌 **Fuente [{d}]**: {titulo}\n**URL**: {href}\n\n{contenido}\n"));
    }
    if paginas.is_empty() {
        for item in resultados {
            let href = texto_de(item, "href");
            let d = if href.is_empty() { "Web".to_string() } else { dominio(&href) };
            let titulo = item.get("title").cloned().unwrap_or(Valor::Texto("Sin título".into()));
            let snippet = item.get("snippet").cloned().unwrap_or(Valor::Texto(String::new()));
            fuentes.push(Valor::Mapa(
                Mapa::new().con("title", titulo.clone()).con("url", href.clone()).con("domain", d.clone()).con("snippet", snippet.clone()),
            ));
            paginas.push(format!(
                "📌 **Fuente [{d}]**: {}\n**URL**: {href}\n**Resumen**: {}\n",
                titulo.texto_py(),
                snippet.texto_py()
            ));
        }
    }
    let texto = format!(
        "\n---\n🌐 **INFORMACIÓN Y DOCUMENTACIÓN OFICIAL DE INTERNET (RAG)**:\n{}\n---\n",
        paginas.join("\n---\n")
    );
    (texto, fuentes)
}

// =========================================================================== caché

fn clave(consulta: &str) -> String {
    use md5::{Digest, Md5};
    let h = Md5::digest(py::strip(consulta).to_lowercase().as_bytes());
    h.iter().map(|b| format!("{b:02x}")).collect()
}

fn ahora() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

/// `WebSearchCache.get`: (contexto, fuentes) si se guardó hace menos de `ttl` segundos; los avisos van a `avisos`
pub fn cache_leer(dir: &str, consulta: &str, ttl: f64, avisos: &mut Vec<String>) -> Option<(Valor, Valor)> {
    let ruta = py::join(dir, &format!("{}.json", clave(consulta)));
    if !std::path::Path::new(&ruta).exists() {
        return None;
    }
    match prig_plataforma::leer_json(std::path::Path::new(&ruta)) {
        Ok(Valor::Mapa(d)) => {
            let marca = d.get("timestamp").and_then(|v| v.num()).unwrap_or(0.0);
            if ahora() - marca < ttl {
                let c = d.get("context").cloned().unwrap_or(Valor::Texto(String::new()));
                let f = d.get("sources").cloned().unwrap_or(Valor::Lista(vec![]));
                return Some((c, f));
            }
            None
        }
        Ok(_) => {
            avisos.push("⚠️ Error leyendo caché de búsqueda: el archivo no es un objeto".into());
            None
        }
        Err(e) => {
            avisos.push(format!("⚠️ Error leyendo caché de búsqueda: {e}"));
            None
        }
    }
}

/// `WebSearchCache.set`
pub fn cache_guardar(dir: &str, consulta: &str, contexto: &str, fuentes: &Valor, avisos: &mut Vec<String>) {
    let ruta = py::join(dir, &format!("{}.json", clave(consulta)));
    let d = Mapa::new()
        .con("query", consulta)
        .con("timestamp", ahora())
        .con("context", contexto)
        .con("sources", fuentes.clone());
    if let Err(e) = std::fs::write(&ruta, json::escribir(&Valor::Mapa(d), 2)) {
        avisos.push(format!("⚠️ Error guardando en caché de búsqueda: {e}"));
    }
}
