//! Extracción de símbolos, importaciones y hechos (banco_proyecto.py, «Extracción de símbolos» y «Hechos»).

pub mod generico;
pub mod python;

use std::sync::LazyLock;

use crate::re::Re;

/// Un uso dentro de un símbolo: (nombre llamado, línea, receptor). Receptor None: lenguajes sin él (JS, C…).
#[derive(Clone, Debug, PartialEq)]
pub struct Uso {
    pub nombre: String,
    pub linea: i64,
    pub receptor: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Simbolo {
    pub nombre: String,
    pub corto: String,
    pub tipo: String,
    pub firma: String,
    pub doc: String,
    pub ini: i64,
    pub fin: i64,
    pub padre: String,
    pub usos: Vec<Uso>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Hecho {
    pub s: String,
    pub r: String,
    pub o: String,
    pub linea: i64,
}

impl Hecho {
    pub fn nuevo(s: &str, r: &str, o: &str, linea: i64) -> Hecho {
        Hecho { s: s.to_string(), r: r.to_string(), o: o.to_string(), linea }
    }
}

pub static ES_TEST: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$", ""));

/// `_dentro`: el símbolo más interno que contiene la línea (a igual inicio, el último).
pub fn dentro(simbolos: &[Simbolo], linea: i64, defecto: &str) -> String {
    let mut mejor: Option<&Simbolo> = None;
    for s in simbolos {
        if s.ini <= linea && linea <= s.fin && mejor.map(|m| s.ini >= m.ini).unwrap_or(true) {
            mejor = Some(s);
        }
    }
    mejor.map(|m| m.nombre.clone()).unwrap_or_else(|| defecto.to_string())
}

static PARAM_JS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"(?<=/)\$\{[^}]*\}", ""));
static PLANTILLA: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"\$\{[^}]*\}", ""));
static PARAM: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"\{[^}]*\}", ""));

/// `ruta_http_canonica`: /api/x/{id} y `/api/x/${id}` → /api/x/* (sin consulta ni barra final).
pub fn ruta_http_canonica(ruta: &str) -> String {
    let r = PARAM_JS.sub("*", ruta);
    let r = PLANTILLA.sub("", &r);
    let r = r.split('?').next().unwrap_or("");
    let r = r.split('#').next().unwrap_or("");
    let r = PARAM.sub("*", r);
    let r = r.trim_end_matches('/');
    if r.is_empty() {
        "/".to_string()
    } else {
        r.to_string()
    }
}

/// `endpoint_de`: la ruta expuesta que atiende una consumida (la misma o la más larga que sea sufijo).
pub fn endpoint_de<'a>(consumida: &str, expuestas: impl IntoIterator<Item = &'a str>) -> Option<String> {
    let mut mejor: Option<&str> = None;
    for e in expuestas {
        if e == consumida {
            return Some(consumida.to_string());
        }
        if e.chars().count() > 1 && consumida.ends_with(e) && mejor.map(|m| e.chars().count() > m.chars().count()).unwrap_or(true) {
            mejor = Some(e);
        }
    }
    mejor.map(|m| m.to_string())
}

/// `extraer_hechos`: un extractor que falla no impide indexar el archivo (deja sin hechos).
pub fn extraer_hechos(rel: &str, lenguaje: &str, texto: &str, simbolos: &[Simbolo], arbol: Option<&crate::pyast::Arbol>) -> Vec<Hecho> {
    if lenguaje == "python" || lenguaje == "cuaderno" {
        match arbol {
            Some(a) => python::hechos_de(a, rel, simbolos),
            None => vec![],
        }
    } else {
        generico::hechos_texto(rel, lenguaje, texto, simbolos)
    }
}
