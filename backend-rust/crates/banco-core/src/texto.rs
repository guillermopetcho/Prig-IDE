//! Utilidades de texto del banco (banco_proyecto.py, «Utilidades»): tokens estimados, sha1, términos
//! buscables, identificadores nombrados y el lenguaje de una ruta. Las constantes son las de Python.

use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use unicode_normalization::char::canonical_combining_class;
use unicode_normalization::UnicodeNormalization;

use crate::py::cadena::{largo, strip_de};
use crate::py::ruta::basename;
use crate::re::{Re, ReInicio};

pub const VERSION_ESQUEMA: i64 = 6;
pub const MAX_ARCHIVOS: usize = 20000;
pub const MAX_BYTES: usize = 1_000_000;
pub const MAX_BYTES_DATOS: usize = 200_000;
pub const MAX_LINEAS_FRAGMENTO: i64 = 120;
pub const LINEAS_BLOQUE_SUELTO: usize = 60;
pub const MAX_DIFF: usize = 3000;
pub const MAX_CAMBIOS_GUARDADOS: i64 = 3000;
pub const CARACTERES_POR_TOKEN: f64 = 3.5;
pub const RRF_K: f64 = 60.0;

pub static IGNORADAS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "__pycache__", "node_modules", "venv", ".venv", "env", ".git", ".github", ".ipynb_checkpoints", "dist", "build",
        ".cache", "site-packages", ".idea", ".vscode", ".gemini", ".mypy_cache", ".pytest_cache", ".tox", ".next", "target",
        "coverage", ".gradle", "vendor",
    ]
    .into_iter()
    .collect()
});

pub static LENGUAJES: LazyLock<HashMap<&'static str, &'static str>> = LazyLock::new(|| {
    [
        ("py", "python"), ("pyi", "python"),
        ("js", "js"), ("jsx", "js"), ("ts", "js"), ("tsx", "js"), ("mjs", "js"), ("cjs", "js"), ("vue", "js"), ("svelte", "js"),
        ("c", "c"), ("h", "c"), ("cc", "c"), ("cpp", "c"), ("cxx", "c"), ("hpp", "c"), ("hh", "c"), ("hxx", "c"),
        ("cu", "c"), ("cuh", "c"), ("m", "c"), ("mm", "c"),
        ("java", "java"), ("kt", "java"), ("kts", "java"), ("cs", "java"), ("scala", "java"), ("swift", "java"), ("dart", "java"),
        ("go", "go"), ("rs", "rust"),
        ("md", "md"), ("markdown", "md"), ("rst", "md"), ("txt", "md"), ("tex", "md"),
        ("html", "texto"), ("htm", "texto"), ("css", "texto"), ("scss", "texto"), ("sql", "texto"), ("sh", "texto"),
        ("bash", "texto"), ("zsh", "texto"), ("ps1", "texto"), ("bat", "texto"), ("r", "texto"), ("jl", "texto"),
        ("lua", "texto"), ("rb", "texto"), ("php", "texto"), ("pl", "texto"), ("cmake", "texto"), ("proto", "texto"),
        ("yaml", "datos"), ("yml", "datos"), ("toml", "datos"), ("json", "datos"), ("ini", "datos"), ("cfg", "datos"),
        ("xml", "datos"), ("csv", "datos"), ("gbnf", "texto"), ("ipynb", "cuaderno"),
    ]
    .into_iter()
    .collect()
});

pub static SIN_EXTENSION: LazyLock<HashMap<&'static str, &'static str>> = LazyLock::new(|| {
    [
        ("makefile", "texto"), ("dockerfile", "texto"), ("cmakelists.txt", "texto"), ("readme", "md"), ("license", "md"),
        ("procfile", "texto"), ("gemfile", "texto"),
    ]
    .into_iter()
    .collect()
});

pub static EXCLUIR_NOMBRES: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"(\.min\.(js|css)$|\.lock$|-lock\.json$|\.map$|^package-lock\.json$)", ""));

pub fn bloque_lenguaje(lenguaje: &str) -> &'static str {
    match lenguaje {
        "python" => "python",
        "js" => "javascript",
        "c" => "cpp",
        "java" => "java",
        "go" => "go",
        "rust" => "rust",
        "md" => "markdown",
        _ => "",
    }
}

pub static PALABRAS_VACIAS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "the", "a", "an", "of",
        "que", "como", "cual", "cuales", "para", "por", "con", "sin", "sobre", "entre", "este", "esta",
        "esto", "estos", "estas", "ese", "esa", "eso", "esos", "esas", "cuando", "donde", "porque", "pero",
        "mas", "muy", "son", "ser", "estar", "hay", "tiene", "hace", "puede", "debe", "y", "o", "en", "se",
        "lo", "le", "les", "me", "mi", "tu", "su", "sus", "es", "no", "si", "ya", "todo", "toda", "todos",
        "explicame", "explica", "explicar", "dime", "quiero", "necesito", "saber", "funciona", "significa",
        "ayuda", "ayudame", "haz", "hacer", "podrias", "puedes", "algo", "cosa", "codigo", "archivo",
        "funcion", "clase", "metodo", "and", "or", "to", "in", "is", "it", "for", "on", "with", "this", "that",
        "what", "how", "why", "does", "do", "can", "be", "are", "was", "from", "by", "at", "as", "not",
        "self", "none", "true", "false", "return", "def", "import", "const", "let", "var", "int", "void",
    ]
    .into_iter()
    .collect()
});

pub const TIPOS_CONOCIMIENTO: [&str; 5] = ["definicion", "teoria", "decision", "contexto", "nota"];

/// `estimar_tokens`: caracteres / 3,5 + 1 (caracteres de Python, no bytes).
pub fn estimar_tokens(texto: &str) -> i64 {
    (largo(texto) as f64 / CARACTERES_POR_TOKEN) as i64 + 1
}

/// `_sha`: sha1 del texto en UTF-8.
pub fn sha(texto: &str) -> String {
    sha1_smol::Sha1::from(texto.as_bytes()).digest().to_string()
}

/// `_sin_acentos`: NFKD sin las marcas que se combinan.
pub fn sin_acentos(texto: &str) -> String {
    texto.nfkd().filter(|c| canonical_combining_class(*c) == 0).collect()
}

static IDENT: LazyLock<Re> = LazyLock::new(|| Re::nuevo("[A-Za-z_\u{00C0}-\u{024F}][A-Za-z0-9_\u{00C0}-\u{024F}]*", ""));
static PARTES: LazyLock<Re> = LazyLock::new(|| Re::nuevo("[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z\u{00E0}-\u{024F}]+|[A-Z]+|\\d+", ""));

/// Los identificadores de un texto (`_IDENT.findall`).
pub fn identificadores(texto: &str) -> Vec<&str> {
    IDENT.findall0(texto)
}

/// `terminos`: identificadores completos y sus partes (snake_case y camelCase), sin acentos, en minúscula,
/// de 2 caracteres o más, sin repetir y hasta `limite`.
pub fn terminos(texto: &str, limite: usize) -> Vec<String> {
    let mut salida: Vec<String> = Vec::new();
    let mut vistos: HashSet<String> = HashSet::new();
    for ident in IDENT.findall0(texto) {
        let base = sin_acentos(ident).to_lowercase();
        let mut candidatos = vec![base];
        if ident.contains('_') || ident.chars().skip(1).any(|c| c.is_uppercase()) {
            for trozo in ident.split('_') {
                for p in PARTES.findall0(trozo) {
                    candidatos.push(sin_acentos(p).to_lowercase());
                }
            }
        }
        for t in candidatos {
            if largo(&t) >= 2 && !vistos.contains(&t) {
                vistos.insert(t.clone());
                salida.push(t);
                if salida.len() >= limite {
                    return salida;
                }
            }
        }
    }
    salida
}

/// `terminos_consulta`.
pub fn terminos_consulta(texto: &str) -> Vec<String> {
    terminos(texto, 64).into_iter().filter(|t| largo(t) >= 3 && !PALABRAS_VACIAS.contains(t.as_str())).collect()
}

static EN_COMILLAS_BANCO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"`([^`]{2,80})`", ""));
static MINUS_MAYUS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"[a-z][A-Z]", ""));
static CAMEL_INICIO: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^[A-Z][a-z]+[A-Z]", ""));
static LLAMADA_NOMBRADA: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"([A-Za-z_][\w]*)\s*\(", ""));

/// `identificadores_nombrados`: lo que en una pregunta parece un nombre de código. En Python es un set (orden
/// al azar entre procesos): aquí, ordenado.
pub fn identificadores_nombrados(texto: &str) -> Vec<String> {
    let mut salida: HashSet<String> = HashSet::new();
    for m in EN_COMILLAS_BANCO.findall1(texto) {
        for i in IDENT.findall0(m) {
            salida.insert(i.to_string());
        }
    }
    for ident in IDENT.findall0(texto) {
        if strip_de(ident, "_").contains('_') || MINUS_MAYUS.hay(ident) || CAMEL_INICIO.hay(ident) {
            salida.insert(ident.to_string());
        }
    }
    for m in LLAMADA_NOMBRADA.findall1(texto) {
        salida.insert(m.to_string());
    }
    let mut v: Vec<String> = salida
        .into_iter()
        .filter(|s| largo(s) >= 3 && !PALABRAS_VACIAS.contains(s.to_lowercase().as_str()))
        .collect();
    v.sort();
    v
}

/// `lenguaje_de`.
pub fn lenguaje_de(ruta: &str) -> Option<&'static str> {
    let nombre = basename(ruta).to_lowercase();
    if let Some(l) = SIN_EXTENSION.get(nombre.as_str()) {
        return Some(l);
    }
    let (_, ext) = nombre.rsplit_once('.')?;
    LENGUAJES.get(ext).copied()
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn terminos_como_python() {
        assert_eq!(terminos("def calcularPrecioHTTPServer(x_y): pass", 4000), vec!["def", "calcularpreciohttpserver", "calcular", "precio", "http", "server", "x_y", "pass"]);
        assert_eq!(estimar_tokens("ñandú"), 2);
        assert_eq!(sha("hola"), "99800b85d3383e3a2fb45eb7d0066a4879a9dad0");
        assert_eq!(lenguaje_de("a/B.PY"), Some("python"));
        assert_eq!(lenguaje_de("Makefile"), Some("texto"));
    }
}
