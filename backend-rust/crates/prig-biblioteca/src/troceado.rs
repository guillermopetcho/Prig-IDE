//! El fragmentador semántico de la biblioteca (`knowledge/ingestion/semantic_chunker.py` y
//! `structure_detector.py`): partir las páginas de un libro en fragmentos del tamaño pedido, ubicar cada uno en su
//! sección y capítulo y clasificar su contenido.
//!
//! Mismo resultado que Python carácter por carácter: longitudes en caracteres (no bytes), los espacios de
//! `str.isspace()` (también `\x1c`–`\x1f`, que `\s` de Rust no cuenta) y la truncación de `int(len / 3.6)`.
//! Una diferencia escrita: Python devuelve los símbolos en el orden (al azar) de un `set`; aquí, por orden de
//! aparición.

use regex::Regex;
use std::sync::LazyLock;

pub const CARACTERES_POR_TOKEN: f64 = 3.6;
pub const MINIMO_BLOQUE: usize = 20;

/// `str.isspace()` de un carácter
pub fn es_espacio(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

fn largo(t: &str) -> usize {
    t.chars().count()
}

fn strip(t: &str) -> &str {
    t.trim_matches(es_espacio)
}

/// `int(len(texto) / CARACTERES_POR_TOKEN) + 1`
pub fn tokens_de(texto: &str) -> i64 {
    tokens_de_largo(largo(texto))
}

fn tokens_de_largo(n: usize) -> i64 {
    (n as f64 / CARACTERES_POR_TOKEN) as i64 + 1
}

/// Separa en párrafos (`SemanticChunker._parrafos`)
pub fn parrafos(texto: &str) -> Vec<String> {
    let texto = texto.replace("\r\n", "\n");
    let partes: Vec<String> =
        texto.split("\n\n").map(strip).filter(|p| largo(p) > MINIMO_BLOQUE).map(String::from).collect();
    if !partes.is_empty() {
        return partes;
    }
    let mut parrafos = Vec::new();
    let mut actual: Vec<&str> = Vec::new();
    for linea in texto.split('\n').filter(|l| !strip(l).is_empty()) {
        let nuevo = sangria(linea)
            || actual.last().is_some_and(|a| a.ends_with(['.', ':', '?', '!']) && empieza_frase(linea));
        if nuevo && !actual.is_empty() {
            parrafos.push(actual.join(" "));
            actual.clear();
        }
        actual.push(strip(linea));
    }
    if !actual.is_empty() {
        parrafos.push(actual.join(" "));
    }
    parrafos.retain(|p| largo(p) > MINIMO_BLOQUE);
    parrafos
}

/// `re.match(r"\s{2,}\S", linea)`
fn sangria(linea: &str) -> bool {
    let n = linea.chars().take_while(|&c| es_espacio(c)).count();
    n >= 2 && linea.chars().nth(n).is_some()
}

/// `re.match(r"\s*[A-ZÁÉÍÓÚÑ0-9]", linea)`
fn empieza_frase(linea: &str) -> bool {
    linea.chars().find(|&c| !es_espacio(c)).is_some_and(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || "ÁÉÍÓÚÑ".contains(c))
}

/// `re.split(r"(?<=[.!?:])\s+", texto)`
fn frases(texto: &str) -> Vec<&str> {
    let mut salida = Vec::new();
    let mut inicio = 0;
    let mut previo: Option<char> = None;
    let mut it = texto.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        if es_espacio(c) && matches!(previo, Some('.' | '!' | '?' | ':')) {
            salida.push(&texto[inicio..i]);
            let mut fin = i + c.len_utf8();
            while let Some(&(j, d)) = it.peek() {
                if !es_espacio(d) {
                    break;
                }
                fin = j + d.len_utf8();
                it.next();
            }
            inicio = fin;
            previo = None;
            continue;
        }
        previo = Some(c);
    }
    salida.push(&texto[inicio..]);
    salida
}

/// Un texto que se va alargando, con su largo en caracteres
#[derive(Default)]
struct Acumulado {
    s: String,
    n: usize,
}

impl Acumulado {
    fn poner(&mut self, t: &str, n: usize) {
        self.s.push_str(t);
        self.s.push(' ');
        self.n += n + 1;
    }
    fn vaciar(&mut self) -> String {
        self.n = 0;
        std::mem::take(&mut self.s)
    }
}

/// Parte un bloque que no cabe, por frases (`SemanticChunker._partir`)
pub fn partir(texto: &str, tope: i64) -> Vec<String> {
    if tokens_de(texto) <= tope {
        return vec![texto.to_string()];
    }
    let limite = (tope as f64 * CARACTERES_POR_TOKEN) as i64;
    let mut trozos: Vec<String> = Vec::new();
    let mut actual = Acumulado::default();
    for frase in frases(texto) {
        let nf = largo(frase);
        if nf as i64 > limite {
            if !actual.s.is_empty() {
                trozos.push(strip(&actual.vaciar()).to_string());
            }
            let mut linea = Acumulado::default();
            for w in frase.split(es_espacio).filter(|w| !w.is_empty()) {
                let nw = largo(w);
                if (linea.n + nw + 1) as i64 > limite {
                    trozos.push(strip(&linea.vaciar()).to_string());
                }
                linea.poner(w, nw);
            }
            if !strip(&linea.s).is_empty() {
                actual = linea;
            }
            continue;
        }
        if !actual.s.is_empty() && (actual.n + nf + 1) as i64 > limite {
            trozos.push(strip(&actual.vaciar()).to_string());
        }
        actual.poner(frase, nf);
    }
    if !strip(&actual.s).is_empty() {
        trozos.push(strip(&actual.s).to_string());
    }
    trozos.retain(|t| largo(t) > MINIMO_BLOQUE);
    trozos
}

// ---------------------------------------------------------------- clasificar (StructureDetector)

static ECUACION: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\$\$|\$.*?\$|\\[a-zA-Z]+|∂|∑|∫|=|\\begin\{equation\}").unwrap());
static CODIGO: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"def[\s\x1c-\x1f]+\w+|class[\s\x1c-\x1f]+\w+|import[\s\x1c-\x1f]+\w+|from[\s\x1c-\x1f]+\w+|return[\s\x1c-\x1f]+|for[\s\x1c-\x1f]+.*in[\s\x1c-\x1f]+|torch\.|nn\.|np\.").unwrap()
});
// `\$$\s*\\begin` del patrón de Python no puede casar nunca (tras el final del texto no queda nada): no se copia
static PRUEBA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)demostración|proof|teorema|lemma").unwrap());
static DEFINICION: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)\A(?:definición|definition|se define como)").unwrap());
static ALGORITMO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)algoritmo|algorithm|paso 1|step 1").unwrap());
static EJEMPLO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)ejemplo|example|por ejemplo").unwrap());
static EJERCICIO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)ejercicio|exercise|problema").unwrap());
static SIMBOLOS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\\[a-zA-Z]+|def[\s\x1c-\x1f]+\w+|class[\s\x1c-\x1f]+\w+|torch\.\w+").unwrap()
});

pub struct Clase {
    pub tipo: &'static str,
    pub ecuacion: bool,
    pub codigo: bool,
    pub simbolos: Vec<String>,
}

/// `StructureDetector.detect_structure`
pub fn clasificar(t: &str) -> Clase {
    let ecuacion = ECUACION.is_match(t);
    let codigo = CODIGO.is_match(t);
    let tipo = if codigo {
        "CODE"
    } else if ecuacion && PRUEBA.is_match(t) {
        "PROOF"
    } else if ecuacion {
        "MATHEMATICS"
    } else if DEFINICION.is_match(t) {
        "DEFINITION"
    } else if ALGORITMO.is_match(t) {
        "ALGORITHM"
    } else if EJEMPLO.is_match(t) {
        "EXAMPLE"
    } else if EJERCICIO.is_match(t) {
        "EXERCISE"
    } else {
        "TEXT"
    };
    let mut simbolos: Vec<String> = Vec::new();
    for m in SIMBOLOS.find_iter(t) {
        if simbolos.len() == 10 {
            break;
        }
        if !simbolos.iter().any(|s| s == m.as_str()) {
            simbolos.push(m.as_str().to_string());
        }
    }
    Clase { tipo, ecuacion, codigo, simbolos }
}

// ---------------------------------------------------------------- fragmentar (SemanticChunker.chunk_document)

/// Una sección o capítulo ya ordenado (`_ordenar_secciones`, que sigue en Python porque marca los dicts)
pub struct Seccion {
    pub es_seccion: bool,
    pub inicio: i64,
    pub fin: i64,
    pub section_id: Option<String>,
    pub chapter_id: Option<String>,
}

/// Un fragmento, sin `chunk_id` ni fechas (los pone quien lo entrega)
pub struct Fragmento {
    pub numero: usize,
    pub texto: String,
    pub tokens: i64,
    pub pagina_inicio: i64,
    pub pagina_fin: i64,
    pub section_id: Option<String>,
    pub chapter_id: Option<String>,
    pub clase: Clase,
}

fn verdad(v: &Option<String>) -> bool {
    v.as_deref().is_some_and(|s| !s.is_empty())
}

/// `_ubicar`: en qué sección y capítulo cae una página
fn ubicar(pagina: i64, secciones: &[Seccion]) -> (Option<String>, Option<String>) {
    let (mut sec, mut chp): (Option<String>, Option<String>) = (None, None);
    for s in secciones {
        if s.inicio <= pagina && pagina <= s.fin {
            if s.es_seccion && sec.is_none() {
                sec = s.section_id.clone();
                if !verdad(&chp) {
                    chp = s.chapter_id.clone();
                }
            } else if !s.es_seccion && chp.is_none() {
                chp = s.chapter_id.clone();
            }
        }
        if verdad(&sec) && verdad(&chp) {
            break;
        }
    }
    (sec, chp)
}

/// Fragmenta las páginas `(número, texto)` de un documento
pub fn fragmentar(paginas: &[(i64, String)], secciones: &[Seccion], max_tokens: i64) -> Vec<Fragmento> {
    struct Bloque {
        pagina: i64,
        texto: String,
        tokens: i64,
    }
    let bloques: Vec<Bloque> = paginas
        .iter()
        .flat_map(|(n, t)| {
            parrafos(t).into_iter().flat_map(move |p| {
                partir(&p, max_tokens).into_iter().map(move |trozo| Bloque { pagina: *n, tokens: tokens_de(&trozo), texto: trozo })
            })
        })
        .collect();
    let Some(primero) = bloques.first() else { return Vec::new() };

    // Primero los grupos de bloques; la clasificación (lo caro) va después, en paralelo
    let mut grupos: Vec<(Vec<&str>, i64, i64)> = Vec::new();
    let mut actual: Vec<&str> = Vec::new();
    let mut tokens_actual = 0;
    let (mut inicio, mut fin) = (primero.pagina, primero.pagina);
    for b in &bloques {
        if !actual.is_empty() && tokens_actual + b.tokens > max_tokens {
            grupos.push((std::mem::take(&mut actual), inicio, fin));
            tokens_actual = 0;
            inicio = b.pagina;
        }
        actual.push(&b.texto);
        tokens_actual += b.tokens;
        fin = b.pagina;
    }
    if !actual.is_empty() {
        grupos.push((actual, inicio, fin));
    }

    let crear = |i: usize, (partes, inicio, fin): &(Vec<&str>, i64, i64)| {
        let texto = partes.join("\n\n");
        let (section_id, chapter_id) = ubicar(*inicio, secciones);
        Fragmento {
            numero: i + 1,
            tokens: tokens_de(&texto),
            clase: clasificar(&texto),
            texto,
            pagina_inicio: *inicio,
            pagina_fin: *fin,
            section_id,
            chapter_id,
        }
    };
    let hilos = std::thread::available_parallelism().map_or(1, |n| n.get()).min(8);
    if grupos.len() < 64 || hilos == 1 {
        return grupos.iter().enumerate().map(|(i, g)| crear(i, g)).collect();
    }
    let trozo = grupos.len().div_ceil(hilos);
    std::thread::scope(|s| {
        let tareas: Vec<_> = grupos
            .chunks(trozo)
            .enumerate()
            .map(|(k, parte)| {
                let crear = &crear;
                s.spawn(move || parte.iter().enumerate().map(|(i, g)| crear(k * trozo + i, g)).collect::<Vec<_>>())
            })
            .collect();
        tareas.into_iter().flat_map(|t| t.join().unwrap()).collect()
    })
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn frases_como_re_split() {
        assert_eq!(frases("Hola. Qué tal?  Bien"), vec!["Hola.", "Qué tal?", "Bien"]);
        assert_eq!(frases(" a. "), vec![" a.", ""]);
        assert_eq!(frases("x"), vec!["x"]);
    }

    #[test]
    fn tokens_como_python() {
        assert_eq!(tokens_de(""), 1);
        assert_eq!(tokens_de("abcd"), 2);
        assert_eq!(tokens_de("ñññ"), 1);
    }

    #[test]
    fn clasifica() {
        assert_eq!(clasificar("def f(x): return x").tipo, "CODE");
        assert_eq!(clasificar("Teorema: a = b").tipo, "PROOF");
        assert_eq!(clasificar("Definición de algo").tipo, "DEFINITION");
        assert_eq!(clasificar("texto").tipo, "TEXT");
    }
}
