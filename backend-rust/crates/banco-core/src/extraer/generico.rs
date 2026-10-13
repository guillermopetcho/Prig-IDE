//! Otros lenguajes y Markdown (banco_proyecto.py: simbolos_genericos, secciones_markdown,
//! importaciones_genericas, hechos_texto): patrones por línea y cierre por llaves.

use std::collections::{BTreeSet, HashSet};
use std::sync::LazyLock;

use super::{dentro, ruta_http_canonica, Hecho, Simbolo, Uso};
use crate::py::cadena::{lstrip, primeros, rstrip, rstrip_de, splitlines, strip};
use crate::re::{Re, ReInicio};

pub static CONTROL: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "if", "for", "while", "switch", "catch", "return", "sizeof", "else", "do", "try", "new", "delete", "throw", "case",
        "typeof", "await", "yield", "function", "elif", "match", "with",
    ]
    .into_iter()
    .collect()
});

static PATRONES: LazyLock<Vec<(&'static str, Vec<(ReInicio, &'static str)>)>> = LazyLock::new(|| {
    let p = |s: &str| ReInicio::nuevo(s, "");
    vec![
        (
            "js",
            vec![
                (p(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"), "clase"),
                (p(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\("), "funcion"),
                (
                    p(concat!(
                        r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?",
                        r"(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|[A-Za-z_$][\w$]*\s*=>)"
                    )),
                    "funcion",
                ),
                (
                    p(concat!(
                        r"^\s+(?:(?:public|private|protected|static|async|get|set|readonly|override)\s+)*",
                        r"([A-Za-z_$][\w$]*)\s*\([^;]*\)\s*(?::\s*[^{;]+)?\{\s*$"
                    )),
                    "metodo",
                ),
                (p(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)"), "tipo"),
            ],
        ),
        (
            "c",
            vec![
                (p(r"^\s*(?:template\s*<.*>\s*)?(?:class|struct|union)\s+(?:\w+\s+)*?([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^;{]*)?\{?\s*$"), "clase"),
                (p(r"^\s*(?:enum)\s+(?:class\s+)?([A-Za-z_]\w*)"), "tipo"),
                (p(r"^\s*namespace\s+([A-Za-z_][\w:]*)"), "espacio"),
                (
                    p(concat!(
                        r"^\s*(?:template\s*<.*>\s*)?(?:(?:static|inline|virtual|extern|constexpr|explicit|",
                        r"__global__|__device__|__host__|__forceinline__|GGML_API|LLAMA_API|const|unsigned|",
                        r"signed|struct|friend)\s+)*[A-Za-z_][\w:<>,\s\*&]*?[\s\*&]+\**([A-Za-z_~][\w:~]*)\s*\([^;]*$"
                    )),
                    "funcion",
                ),
            ],
        ),
        (
            "java",
            vec![
                (
                    p(concat!(
                        r"^\s*(?:(?:public|private|protected|internal|static|abstract|final|sealed|data|open)\s+)*",
                        r"(?:class|interface|enum|record|object|struct|trait)\s+([A-Za-z_]\w*)"
                    )),
                    "clase",
                ),
                (
                    p(concat!(
                        r"^\s*(?:(?:public|private|protected|internal|static|abstract|final|override|synchronized|",
                        r"async|virtual|suspend|open)\s+)*(?:fun\s+|func\s+)?(?:[\w<>\[\],?\s]+\s+)?([A-Za-z_]\w*)\s*\([^;]*\)",
                        r"\s*(?:[:\w<>\[\],?\s]*)?(?:throws[\w\s,.]+)?\{?\s*$"
                    )),
                    "funcion",
                ),
            ],
        ),
        (
            "go",
            vec![
                (p(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("), "funcion"),
                (p(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)"), "clase"),
            ],
        ),
        (
            "rust",
            vec![
                (p(r#"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+"C"\s+)?fn\s+([A-Za-z_]\w*)"#), "funcion"),
                (p(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union)\s+([A-Za-z_]\w*)"), "clase"),
                (p(r"^\s*impl(?:<[^>]*>)?\s+(?:[\w:<>]+\s+for\s+)?([A-Za-z_][\w:]*)"), "clase"),
                (p(r"^\s*(?:pub\s+)?mod\s+([A-Za-z_]\w*)\s*\{"), "espacio"),
            ],
        ),
    ]
});

pub static LLAMADA: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"\b([A-Za-z_][\w]*)\s*\(", ""));
pub static COMENTARIO_LINEA: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^\s*(//+|#|\*|/\*\*?|--)\s?", ""));
static COMENTARIO_LINEA_SUB: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"^\s*(//+|#|\*|/\*\*?|--)\s?", ""));
static CADENAS_Y_COMENTARIO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//.*$"#, ""));

/// `_COMENTARIO_LINEA.sub("", s)`.
pub fn sin_comentario(s: &str) -> String {
    COMENTARIO_LINEA_SUB.sub("", s).into_owned()
}

/// `_fin_por_llaves`: índice de la línea que cierra el bloque abierto en `ini` (None si no abre bloque).
fn fin_por_llaves(lineas: &[&str], ini: usize) -> Option<usize> {
    let mut profundidad: i64 = 0;
    let mut abierto = false;
    let tope = lineas.len().min(ini + 4000);
    for i in ini..tope {
        let linea = CADENAS_Y_COMENTARIO.sub("", lineas[i]);
        for c in linea.chars() {
            if c == '{' {
                profundidad += 1;
                abierto = true;
            } else if c == '}' {
                profundidad -= 1;
                if abierto && profundidad <= 0 {
                    return Some(i);
                }
            }
        }
        if !abierto && (i - ini >= 3 || rstrip(&linea).ends_with(';')) {
            return None;
        }
    }
    if abierto {
        Some(lineas.len() - 1)
    } else {
        None
    }
}

/// `_doc_previa`: los comentarios justo encima de la línea.
fn doc_previa(lineas: &[&str], ini: usize) -> String {
    let mut doc: Vec<String> = vec![];
    let mut i = ini as isize - 1;
    while i >= 0 && doc.len() < 12 {
        let linea = lineas[i as usize];
        let s = strip(linea);
        if s.is_empty() || !(COMENTARIO_LINEA.hay(linea) || s.ends_with("*/")) {
            break;
        }
        let limpio = sin_comentario(s);
        doc.insert(0, strip(rstrip_de(&limpio, "*/ ")).to_string());
        i -= 1;
    }
    let unido: Vec<&str> = doc.iter().filter(|d| !d.is_empty()).map(|d| d.as_str()).collect();
    primeros(&unido.join(" "), 600).to_string()
}

/// `simbolos_genericos`.
pub fn simbolos_genericos(texto: &str, lenguaje: &str) -> Vec<Simbolo> {
    let Some((_, patrones)) = PATRONES.iter().find(|(l, _)| *l == lenguaje) else { return vec![] };
    let lineas = splitlines(texto);
    let mut simbolos: Vec<Simbolo> = vec![];
    let mut abiertos: Vec<usize> = vec![];
    let mut i = 0usize;
    while i < lineas.len() {
        let linea = lineas[i];
        while let Some(&u) = abiertos.last() {
            if simbolos[u].fin < (i as i64) + 1 {
                abiertos.pop();
            } else {
                break;
            }
        }
        let mut encontrado: Option<(String, &str)> = None;
        if !strip(linea).is_empty() && !COMENTARIO_LINEA.hay(linea) && !lstrip(linea).starts_with('#') {
            for (patron, tipo) in patrones {
                if let Some(m) = patron.coincide(linea) {
                    let g = m.g(1);
                    let ultimo = g.rsplit("::").next().unwrap_or(g);
                    if !CONTROL.contains(ultimo) {
                        encontrado = Some((g.to_string(), tipo));
                        break;
                    }
                }
            }
        }
        if let Some((crudo, tipo0)) = encontrado {
            let mut tipo = tipo0.to_string();
            let mut fin = fin_por_llaves(&lineas, i);
            if lenguaje == "go" && fin.is_none() && tipo == "clase" {
                fin = Some(i);
            }
            if let Some(fin) = fin {
                let corto = crudo.rsplit("::").next().unwrap_or(&crudo).to_string();
                let padre = match abiertos.last() {
                    Some(&u) if tipo == "funcion" || tipo == "metodo" => simbolos[u].nombre.clone(),
                    _ => String::new(),
                };
                if !padre.is_empty() && tipo == "funcion" {
                    tipo = "metodo".to_string();
                }
                let nombre = if padre.is_empty() { crudo.replace("::", ".") } else { format!("{padre}.{corto}") };
                let usos = if tipo == "funcion" || tipo == "metodo" {
                    let cuerpo = lineas[i..=fin].join("\n");
                    let nombres: BTreeSet<&str> = LLAMADA.findall1(&cuerpo).into_iter().filter(|n| !CONTROL.contains(n) && *n != corto).collect();
                    nombres.into_iter().map(|n| Uso { nombre: n.to_string(), linea: (i + 1) as i64, receptor: None }).collect()
                } else {
                    vec![]
                };
                let firma = strip(rstrip_de(primeros(strip(linea), 200), "{")).to_string();
                simbolos.push(Simbolo {
                    nombre,
                    corto,
                    tipo: tipo.clone(),
                    firma,
                    doc: doc_previa(&lineas, i),
                    ini: (i + 1) as i64,
                    fin: (fin + 1) as i64,
                    padre,
                    usos,
                });
                if tipo == "clase" || tipo == "espacio" {
                    abiertos.push(simbolos.len() - 1);
                } else {
                    i = fin;
                }
            }
        }
        i += 1;
    }
    simbolos
}

/// `_primera_linea`.
pub fn primera_linea(texto: &str, maximo: usize) -> String {
    for linea in splitlines(strip(texto)) {
        let l = strip(linea);
        if !l.is_empty() {
            return primeros(l, maximo).to_string();
        }
    }
    String::new()
}

static CABECERA_MD: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^(#{1,4})\s+(.+)$", ""));

/// `secciones_markdown`: cada cabecera hasta la siguiente de cualquier nivel.
pub fn secciones_markdown(texto: &str) -> Vec<Simbolo> {
    let lineas = splitlines(texto);
    let mut cabeceras: Vec<(usize, usize, String)> = vec![];
    for (i, l) in lineas.iter().enumerate() {
        if let Some(m) = CABECERA_MD.coincide(l) {
            cabeceras.push((i, m.g(1).chars().count(), strip(m.g(2)).to_string()));
        }
    }
    let mut salida = vec![];
    for (k, (i, nivel, titulo)) in cabeceras.iter().enumerate() {
        let fin = if k + 1 < cabeceras.len() { cabeceras[k + 1].0 as i64 - 1 } else { lineas.len() as i64 - 1 };
        let desde = i + 1;
        let hasta = (fin + 1).max(0) as usize;
        let cuerpo = if desde < hasta.min(lineas.len()) { lineas[desde..hasta.min(lineas.len())].join("\n") } else { String::new() };
        salida.push(Simbolo {
            nombre: titulo.clone(),
            corto: titulo.clone(),
            tipo: "seccion".to_string(),
            firma: format!("{} {}", "#".repeat(*nivel), titulo),
            doc: primera_linea(&cuerpo, 200),
            ini: (*i + 1) as i64,
            fin: fin + 1,
            padre: String::new(),
            usos: vec![],
        });
    }
    salida
}

static IMP_JS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"(?:from\s+|require\(\s*|import\s*\(\s*|import\s+)['"]([^'"]+)['"]"#, ""));
static IMP_C: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"^\s*#\s*include\s+"([^"]+)""#, "m"));
static IMP_GO_BLOQUE: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"import\s*\(([^)]*)\)", ""));
static IMP_GO_UNO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"import\s+("[^"]+")"#, ""));
static ENTRE_COMILLAS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#""([^"]+)""#, ""));
static IMP_RUST: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"^\s*(?:pub\s+)?(?:use|mod)\s+([\w:]+)", "m"));

/// `importaciones_genericas`.
pub fn importaciones_genericas(texto: &str, lenguaje: &str) -> Vec<String> {
    let v: Vec<&str> = match lenguaje {
        "js" => IMP_JS.findall1(texto),
        "c" => IMP_C.findall1(texto),
        "go" => {
            let mut bloques = IMP_GO_BLOQUE.findall1(texto);
            bloques.extend(IMP_GO_UNO.findall1(texto));
            let unido = bloques.join("\n");
            return ENTRE_COMILLAS.findall1(&unido).into_iter().map(|s| s.to_string()).collect();
        }
        "rust" => IMP_RUST.findall1(texto),
        _ => vec![],
    };
    v.into_iter().map(|s| s.to_string()).collect()
}

static API_JS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"([`'"])(/api/(?:[^`'"\\]|\$\{[^}]*\})*?)\1"#, ""));
static DOM_USO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"(?:getElementById|\$)\(\s*['"]([\w-]+)['"]\s*\)|querySelector(?:All)?\(\s*['"]#([\w-]+)"#, ""));
static DOM_DEF: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"\bid\s*=\s*["']([\w-]+)["']"#, ""));
static ENV_C: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"\bgetenv\(\s*"([^"]+)"\s*\)"#, ""));

/// `hechos_texto`.
pub fn hechos_texto(rel: &str, lenguaje: &str, texto: &str, simbolos: &[Simbolo]) -> Vec<Hecho> {
    let mut salida = vec![];
    let mut vistos: HashSet<(String, String, String)> = HashSet::new();
    let mut agregar = |s: String, r: &str, o: String, linea: i64, salida: &mut Vec<Hecho>| {
        if vistos.insert((s.clone(), r.to_string(), o.clone())) {
            salida.push(Hecho { s, r: r.to_string(), o, linea });
        }
    };
    let define_dom = [".html", ".htm", ".js", ".jsx", ".vue", ".svelte"].iter().any(|e| rel.ends_with(e));
    for (k, linea) in splitlines(texto).into_iter().enumerate() {
        let n = (k + 1) as i64;
        if lenguaje == "js" || lenguaje == "texto" || lenguaje == "md" {
            for m in API_JS.todos(linea) {
                agregar(dentro(simbolos, n, rel), "llama_api", ruta_http_canonica(m.g(2)), n, &mut salida);
            }
        }
        if lenguaje == "js" {
            for m in DOM_USO.todos(linea) {
                let o = m.grupo(1).filter(|s| !s.is_empty()).or(m.grupo(2)).unwrap_or("").to_string();
                agregar(dentro(simbolos, n, rel), "usa_dom", o, n, &mut salida);
            }
        }
        if (lenguaje == "js" || lenguaje == "texto") && define_dom {
            for m in DOM_DEF.todos(linea) {
                agregar(rel.to_string(), "define_dom", m.g(1).to_string(), n, &mut salida);
            }
        }
        if lenguaje == "c" || lenguaje == "rust" || lenguaje == "go" {
            for m in ENV_C.todos(linea) {
                agregar(dentro(simbolos, n, rel), "lee_entorno", m.g(1).to_string(), n, &mut salida);
            }
        }
    }
    salida
}
