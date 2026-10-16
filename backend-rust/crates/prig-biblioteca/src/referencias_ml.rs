//! El catálogo de referencias de Machine Learning (`backend/referencias_ml.py`): libros, papers, formularios, cursos
//! y documentación, ordenados por familia de modelo. Vive en frontend/data/referencias_ml.json (y las familias, tipos
//! y temas genéricos en referencias_ml_categorias.json, que también lee Python). Sirve para navegarlo en la Biblioteca
//! y para que el chat de cualquier sección cite lo que viene al caso (`bloque_para_prompt`).

use crate::json;
use crate::referencias::{normalizar, Catalogo, Categoria, Referencia};
use crate::valor::{Mapa, Valor};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::SystemTime;

pub const AGENTE: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 PrigIDE";

/// Lo cargado: las referencias en su orden, las familias y tipos, y el índice para el chat
pub struct Datos {
    pub referencias: Vec<Mapa>,
    pub categorias: Vec<Mapa>,
    pub tipos: Mapa,
    catalogo: Catalogo,
}

fn ruta(raiz: &Path) -> PathBuf {
    raiz.join("frontend").join("data").join("referencias_ml.json")
}

fn categorias_base(raiz: &Path) -> (Vec<Mapa>, Mapa, HashSet<String>) {
    let t = std::fs::read_to_string(raiz.join("frontend/data/referencias_ml_categorias.json")).unwrap_or_default();
    let Ok(Valor::Mapa(m)) = json::leer(&t) else { return (Vec::new(), Mapa::new(), HashSet::new()) };
    let cats = m.lista("categorias").unwrap_or(&[]).iter().filter_map(|c| if let Valor::Mapa(c) = c { Some(c.clone()) } else { None }).collect();
    let genericos = m.lista("temas_genericos").unwrap_or(&[]).iter().map(Valor::texto_py).collect();
    (cats, m.mapa("tipos").cloned().unwrap_or_default(), genericos)
}

fn textos(v: Option<&Valor>) -> Vec<String> {
    match v {
        Some(Valor::Lista(l)) => l.iter().map(Valor::texto_py).collect(),
        _ => Vec::new(),
    }
}

fn texto(m: &Mapa, k: &str) -> String {
    m.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py).unwrap_or_default()
}

/// `cargar()`: se relee si el archivo cambió
pub fn cargar(raiz: &Path) -> Arc<Datos> {
    static CACHE: OnceLock<Mutex<Option<(PathBuf, Option<SystemTime>, Arc<Datos>)>>> = OnceLock::new();
    let r = ruta(raiz);
    let mtime = std::fs::metadata(&r).and_then(|m| m.modified()).ok();
    let mut c = CACHE.get_or_init(Default::default).lock().unwrap_or_else(|e| e.into_inner());
    if let Some((p, t, d)) = c.as_ref() {
        if *p == r && *t == mtime && mtime.is_some() {
            return d.clone();
        }
    }
    let (categorias, tipos, genericos) = categorias_base(raiz);
    let mut refs: Vec<Mapa> = match mtime.and_then(|_| std::fs::read_to_string(&r).ok()).and_then(|t| json::leer(&t).ok()) {
        Some(Valor::Mapa(m)) => textos_mapas(m.get("referencias")),
        Some(Valor::Lista(l)) => textos_mapas(Some(&Valor::Lista(l))),
        _ => Vec::new(),
    };
    let orden_cat = |id: &str| categorias.iter().position(|c| texto(c, "id") == id).unwrap_or(99);
    let tipos_orden = ["formulario", "libro", "apuntes", "curso", "survey", "paper", "articulo", "documentacion"];
    let orden_tipo = |t: &str| tipos_orden.iter().position(|x| *x == t).unwrap_or(9);
    refs.sort_by(|a, b| {
        let clave = |r: &Mapa| {
            let cat = textos(r.get("categorias")).first().map(|c| orden_cat(c)).unwrap_or(99);
            let anio = r.get("anio").filter(|v| v.verdad()).and_then(Valor::num).unwrap_or(0.0);
            (cat, orden_tipo(&texto(r, "tipo")), anio, texto(r, "titulo"))
        };
        let (x, y) = (clave(a), clave(b));
        (x.0, x.1).cmp(&(y.0, y.1)).then(x.2.partial_cmp(&y.2).unwrap_or(std::cmp::Ordering::Equal)).then(x.3.cmp(&y.3))
    });
    let catalogo = Catalogo::new(
        categorias.iter().map(|c| Categoria { id: texto(c, "id"), claves: textos(c.get("claves")) }).collect(),
        refs.iter()
            .map(|r| Referencia {
                caida: r.get("estado") == Some(&Valor::Texto("caido".into())),
                categorias: textos(r.get("categorias")),
                temas: textos(r.get("temas")),
                titulo: texto(r, "titulo"),
                tipo: r.get("tipo").filter(|t| !t.es_nulo()).map(Valor::texto_py),
            })
            .collect(),
        &genericos,
    );
    let d = Arc::new(Datos { referencias: refs, categorias, tipos, catalogo });
    if mtime.is_some() {
        *c = Some((r, mtime, d.clone()));
    }
    d
}

fn textos_mapas(v: Option<&Valor>) -> Vec<Mapa> {
    match v {
        Some(Valor::Lista(l)) => l.iter().filter_map(|x| if let Valor::Mapa(m) = x { Some(m.clone()) } else { None }).collect(),
        _ => Vec::new(),
    }
}

pub fn referencia(raiz: &Path, id: &str) -> Option<Mapa> {
    cargar(raiz).referencias.iter().find(|r| r.get("id") == Some(&Valor::Texto(id.into()))).cloned()
}

fn texto_busqueda(r: &Mapa) -> String {
    let anio = r.get("anio").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default();
    normalizar(
        &[
            texto(r, "titulo"),
            textos(r.get("autores")).join(" "),
            texto(r, "descripcion"),
            textos(r.get("temas")).join(" "),
            anio,
            texto(r, "fuente"),
        ]
        .join(" "),
    )
}

pub fn listar(raiz: &Path, q: &str, categoria: &str, tipo: &str) -> Vec<Mapa> {
    let palabras: Vec<String> = normalizar(q).split_whitespace().map(String::from).collect();
    cargar(raiz)
        .referencias
        .iter()
        .filter(|r| categoria.is_empty() || textos(r.get("categorias")).iter().any(|c| c == categoria))
        .filter(|r| tipo.is_empty() || texto(r, "tipo") == tipo)
        .filter(|r| {
            if palabras.is_empty() {
                return true;
            }
            let t = texto_busqueda(r);
            palabras.iter().all(|p| t.contains(p.as_str()))
        })
        .cloned()
        .collect()
}

/// Las referencias que vienen al caso de una pregunta o un texto
pub fn relacionadas(raiz: &Path, texto: &str, maximo: usize) -> Vec<Mapa> {
    let d = cargar(raiz);
    d.catalogo.relacionadas(texto, maximo).into_iter().filter_map(|i| d.referencias.get(i).cloned()).collect()
}

/// «Apellido, año», «A y B, año», «A et al., año» o el nombre de la organización
pub fn cita_corta(r: &Mapa) -> String {
    let autores = textos(r.get("autores"));
    let ultimo = |a: &str| a.split_whitespace().last().unwrap_or("").to_string();
    let organizacion = autores.len() == 1
        && (texto(r, "tipo") == "documentacion"
            || ["developers", "team", "contributors", "foundation", "google", "meta", "microsoft", "openai", "hugging face", "keras", "mlflow", "dlr-rm"]
                .iter()
                .any(|p| autores[0].to_lowercase().contains(p)));
    let mut quien = if autores.is_empty() {
        texto(r, "fuente")
    } else if organizacion {
        autores[0].clone()
    } else {
        ultimo(&autores[0])
    };
    if autores.len() == 2 {
        quien = format!("{} y {}", ultimo(&autores[0]), ultimo(&autores[1]));
    } else if autores.len() > 2 {
        quien.push_str(" et al.");
    }
    let anio = match r.get("anio").filter(|v| v.verdad()) {
        Some(a) => format!(", {}", a.texto_py()),
        None => String::new(),
    };
    format!("{quien}{anio}").trim_matches(|c| c == ',' || c == ' ').to_string()
}

/// (bloque de texto para el prompt, referencias elegidas). Vacío si no hay nada relacionado
pub fn bloque_para_prompt(raiz: &Path, texto_pregunta: &str, maximo: usize) -> (String, Vec<Mapa>) {
    let refs = relacionadas(raiz, texto_pregunta, maximo);
    if refs.is_empty() {
        return (String::new(), refs);
    }
    let tipos = cargar(raiz).tipos.clone();
    let mut lineas = vec!["REFERENCIAS DE LA BIBLIOTECA DE PRIG relacionadas con la pregunta (catálogo verificado). Si alguna \
viene al caso, cítala al final con su enlace en Markdown, así: [Título](url) — Autores, año. No cites ninguna que no esté en \
esta lista ni inventes páginas o capítulos:"
        .to_string()];
    for r in &refs {
        let url = texto(r, "url");
        let pdf = r.get("url_pdf").filter(|v| v.verdad()).map(Valor::texto_py);
        // si el enlace principal es la editorial (DOI) y hay PDF abierto del autor, se cita el que se puede leer
        let enlace = match pdf {
            Some(p) if url.starts_with("https://doi.org/") => p,
            _ => url,
        };
        let tipo = texto(r, "tipo");
        let nombre_tipo = tipos.get(&tipo).map(Valor::texto_py).unwrap_or_else(|| r.get("tipo").map(Valor::texto_py).unwrap_or_else(|| "None".into()));
        let desc = r.get("descripcion").filter(|v| v.verdad()).map(|d| format!(": {}", d.texto_py())).unwrap_or_default();
        lineas.push(format!("- [{nombre_tipo}] [{}]({enlace}) — {}{desc}", texto(r, "titulo"), cita_corta(r)));
    }
    (lineas.join("\n"), refs)
}

/// Lo que la interfaz necesita para mostrar una referencia como chip o enlace
pub fn resumen_publico(r: &Mapa) -> Mapa {
    let mut m = Mapa::new();
    for k in ["id", "titulo", "autores", "anio", "tipo", "url", "url_pdf", "categorias", "acceso"] {
        m.poner(k, r.get(k).cloned().unwrap_or(Valor::Nulo));
    }
    m.con("cita", cita_corta(r))
}

/// El PDF de una referencia: el enlace directo al PDF, o la página si ya es un PDF
pub fn pdf_de(r: &Mapa) -> Option<String> {
    if let Some(p) = r.get("url_pdf").filter(|v| v.verdad()) {
        return Some(p.texto_py());
    }
    let url = texto(r, "url");
    url.to_lowercase().split('?').next().unwrap_or("").ends_with(".pdf").then_some(url)
}

/// `prompt` con el bloque de referencias relacionadas delante (lo usan los chats de todas las secciones)
pub fn con_referencias(raiz: &Path, texto_para_buscar: &str, prompt: &str) -> (String, Vec<Mapa>) {
    let (bloque, refs) = bloque_para_prompt(raiz, texto_para_buscar, 5);
    (if bloque.is_empty() { prompt.to_string() } else { format!("{bloque}\n\n{prompt}") }, refs)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn raiz() -> &'static Path {
        Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/../../.."))
    }

    #[test]
    fn listar_detalle_y_pdf() {
        let libros = listar(raiz(), "", "", "libro");
        assert!(!libros.is_empty() && libros.iter().all(|r| texto(r, "tipo") == "libro"));
        let atencion = listar(raiz(), "attention is all you need", "", "");
        let r = atencion.iter().find(|r| texto(r, "titulo") == "Attention Is All You Need").expect("el paper");
        assert_eq!(pdf_de(r).as_deref(), Some("https://arxiv.org/pdf/1706.03762"));
        assert!(referencia(raiz(), "no-existe").is_none());
        let sin_pdf = cargar(raiz()).referencias.iter().find(|r| pdf_de(r).is_none()).cloned().expect("una sin PDF");
        assert!(pdf_de(&sin_pdf).is_none());
    }

    #[test]
    fn relacionadas_y_bloque_para_el_chat() {
        let r = relacionadas(raiz(), "¿cómo funciona XGBoost con gradient boosting?", 5);
        assert!(r.iter().any(|x| texto(x, "titulo") == "XGBoost: A Scalable Tree Boosting System"));
        assert!(r.iter().all(|x| resumen_publico(x).contiene("cita")));
        let (prompt, refs) = con_referencias(raiz(), "resume el paper de XGBoost", "PREGUNTA");
        assert!(prompt.ends_with("PREGUNTA") && prompt.contains("REFERENCIAS DE LA BIBLIOTECA") && !refs.is_empty());
        assert!(prompt.contains("arxiv.org/abs/1603.02754"));
        assert_eq!(con_referencias(raiz(), "hola", "PREGUNTA").0, "PREGUNTA");
    }
}
