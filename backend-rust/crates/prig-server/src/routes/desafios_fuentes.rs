//! Desafíos de internet que se pueden copiar legalmente (`desafios/fuentes.py`) y el catálogo de repositorios de
//! GitHub para replicar (`desafios/catalogo_github.py`), con sus rutas de app.py: `GET /api/desafios/fuentes`,
//! `/api/desafios/internet/buscar`, `POST /api/desafios/internet/importar`, `GET /api/desafios/github/catalogo` y
//! `/api/desafios/github/ejercicios`.
//!
//! Las fuentes se eligieron por su licencia: Exercism (Python y C++, MIT), TheAlgorithms (Python y C++, MIT) y
//! Project Euler (CC BY-NC-SA 4.0). Todo se descarga de las URL «raw» de GitHub y de la vista mínima de Project Euler
//! y se guarda en disco (la misma caché que usaba Python): el índice una semana, cada ejercicio un mes.
//!
//! Lo que depende del propio Python (leer un archivo de TheAlgorithms con `ast`, compilar con los mensajes exactos de
//! `SyntaxError`) lo hace `desafios/arneses/codigo.py` con el intérprete que comprueba los desafíos.

use axum::{
    body::Bytes,
    extract::{Query, State},
    http::StatusCode,
    response::Response,
};
use banco_core::py::cadena;
use prig_aprendizaje::desafios::{self as d, ErrorObtener};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::collections::{BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use crate::routes::desafios::{carpeta_base, comprobar, error_500, error_obtener, mapa_de};
use crate::routes::desafios_tutor::{motor, pedido, TEXTO_OPC};
use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

type R<T> = Result<T, ErrorObtener>;

fn falla(t: impl Into<String>) -> ErrorObtener {
    ErrorObtener::Desafio(t.into())
}

fn otro(t: impl ToString) -> ErrorObtener {
    ErrorObtener::Otro(t.to_string())
}

fn re(p: &str) -> Regex {
    Regex::new(p).unwrap()
}

const UA: &str = "Prig-IDE (desafios de programacion; uso educativo local)";
const SEMANA: f64 = 7.0 * 86400.0;
const MES: f64 = 30.0 * 86400.0;

// =========================================================================== utilidades de Python

/// `str.title()`: mayúscula al empezar cada tramo de letras, minúsculas en el resto
pub(crate) fn title(t: &str) -> String {
    let mut s = String::new();
    let mut previa = false;
    for c in t.chars() {
        let con_caja = c.is_lowercase() || c.is_uppercase();
        if con_caja {
            if previa {
                s.extend(c.to_lowercase());
            } else {
                s.extend(c.to_uppercase());
            }
        } else {
            s.push(c);
        }
        previa = con_caja;
    }
    s
}

/// `str.capitalize()`
fn capitalize(t: &str) -> String {
    let mut cs = t.chars();
    match cs.next() {
        Some(p) => p.to_uppercase().chain(cs.flat_map(|c| c.to_lowercase())).collect(),
        None => String::new(),
    }
}

/// `os.path.basename`
fn basename(p: &str) -> String {
    p.rsplit('/').next().unwrap_or("").to_string()
}

/// `x[:-n]` en caracteres
fn sin_cola(t: &str, n: usize) -> String {
    cadena::sin_ultimos(t, n).to_string()
}

/// `x.get(k, defecto)`: el valor si la clave está (aunque sea None)
fn get_o(m: &Mapa, k: &str, defecto: Valor) -> Valor {
    m.get(k).cloned().unwrap_or(defecto)
}

/// `x.get(k) or defecto`
fn o_bien(m: &Mapa, k: &str, defecto: Valor) -> Valor {
    match m.get(k) {
        Some(v) if v.verdad() => v.clone(),
        _ => defecto,
    }
}

fn lista_de(v: &Valor) -> Vec<Valor> {
    match v {
        Valor::Lista(l) => l.clone(),
        _ => Vec::new(),
    }
}

/// `for x in v` de Python: las listas, sus elementos; los textos, sus caracteres; los dicts, sus claves
pub(crate) fn iterar(v: &Valor) -> Result<Vec<Valor>, String> {
    match v {
        Valor::Lista(l) => Ok(l.clone()),
        Valor::Texto(t) => Ok(t.chars().map(|c| Valor::Texto(c.to_string())).collect()),
        Valor::Mapa(m) => Ok(m.claves().map(|k| Valor::Texto(k.clone())).collect()),
        otro => Err(format!("'{}' object is not iterable", py::tipo(otro))),
    }
}

fn textos(v: &[&str]) -> Valor {
    Valor::Lista(v.iter().map(|s| Valor::Texto((*s).into())).collect())
}

// =========================================================================== descargas con caché en disco

fn cache_dir() -> PathBuf {
    let d = carpeta_base().join("cache");
    if std::fs::create_dir_all(&d).is_ok() {
        return d;
    }
    let d = std::env::temp_dir().join("prig_desafios_cache");
    let _ = std::fs::create_dir_all(&d);
    d
}

fn sha1(t: &str) -> String {
    sha1_smol::Sha1::from(t.as_bytes()).digest().to_string()
}

fn host(url: &str) -> &str {
    url.split('/').nth(2).unwrap_or("")
}

fn leer_cache(ruta: &Path) -> R<Option<String>> {
    let texto = std::fs::read_to_string(ruta).map_err(otro)?;
    Ok(if texto == "\x00404" { None } else { Some(texto) })
}

/// `descargar(url, ttl, obligatorio)`: el texto de `url`, desde la caché si es reciente. Sin red, la copia vieja.
pub(crate) fn descargar(url: &str, ttl: f64, obligatorio: bool) -> R<Option<String>> {
    let ruta = cache_dir().join(format!("{}.txt", sha1(url)));
    if let Ok(meta) = std::fs::metadata(&ruta) {
        let edad = meta.modified().ok().and_then(|m| m.elapsed().ok()).map(|e| e.as_secs_f64()).unwrap_or(0.0);
        if edad < ttl {
            return leer_cache(&ruta);
        }
    }
    let r = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(25))
        .build()
        .map_err(otro)?
        .get(url)
        .header("User-Agent", UA)
        .send();
    let r = match r {
        Ok(r) => r,
        Err(e) => {
            if ruta.exists() {
                return leer_cache(&ruta);
            }
            return Err(falla(format!("Sin conexión con {}: {e}", host(url))));
        }
    };
    let codigo = r.status().as_u16();
    if codigo == 404 {
        let _ = std::fs::write(&ruta, "\x00404");
        if obligatorio {
            return Err(falla(format!("No existe: {url}")));
        }
        return Ok(None);
    }
    if codigo != 200 {
        return Err(falla(format!("{} respondió {codigo}", host(url))));
    }
    let texto = String::from_utf8_lossy(&r.bytes().map_err(otro)?).into_owned();
    std::fs::write(&ruta, &texto).map_err(otro)?;
    Ok(Some(texto))
}

/// `descargar(...)` obligatorio: siempre hay texto
fn bajar(url: &str, ttl: f64) -> R<String> {
    Ok(descargar(url, ttl, true)?.unwrap_or_default())
}

fn json_de(t: &str) -> R<Valor> {
    prig_plataforma::json::leer(t).map_err(otro)
}

// =========================================================================== búsqueda por tema (también en castellano)

/// `normalizar`: minúsculas, sin acentos y solo [a-z0-9] separados por un espacio
pub(crate) fn normalizar(texto: &str) -> String {
    let t = prig_biblioteca::referencias::normalizar(texto);
    let mut s = String::new();
    let mut hueco = false;
    for c in t.chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() {
            if hueco && !s.is_empty() {
                s.push(' ');
            }
            hueco = false;
            s.push(c);
        } else {
            hueco = true;
        }
    }
    s
}

fn palabras_de(t: &str) -> Valor {
    Valor::Lista(normalizar(t).split_whitespace().map(|p| Valor::Texto(p.into())).collect())
}

/// frase (normalizada) → etiquetas en el vocabulario de las fuentes
const SINONIMOS: &[(&str, &[&str])] = &[
    ("recursion", &["recursion"]), ("recursividad", &["recursion"]), ("recursivo", &["recursion"]), ("recursiva", &["recursion"]),
    ("comprension de listas", &["list-comprehensions"]), ("comprensiones", &["list-comprehensions", "other-comprehensions"]),
    ("list comprehension", &["list-comprehensions"]),
    ("lista", &["lists", "list-methods"]), ("listas", &["lists", "list-methods"]), ("arreglo", &["lists"]), ("arreglos", &["lists"]),
    ("array", &["lists"]),
    ("diccionario", &["dicts", "dict-methods", "hashes"]), ("diccionarios", &["dicts", "dict-methods", "hashes"]),
    ("hash", &["dicts", "hashes"]), ("mapa", &["dicts"]),
    ("conjunto", &["sets"]), ("conjuntos", &["sets"]), ("tupla", &["tuples"]), ("tuplas", &["tuples"]),
    ("cadena", &["strings", "string-methods"]), ("cadenas", &["strings", "string-methods"]), ("texto", &["strings"]),
    ("string", &["strings"]), ("formato", &["string-formatting"]),
    ("bucle", &["loops", "iteration"]), ("bucles", &["loops", "iteration"]), ("ciclo", &["loops"]), ("ciclos", &["loops"]),
    ("iteracion", &["iteration", "loops"]), ("for", &["loops"]), ("while", &["loops"]),
    ("condicional", &["conditionals", "bools"]), ("condicionales", &["conditionals", "bools"]), ("if", &["conditionals"]),
    ("booleano", &["bools"]), ("booleanos", &["bools", "boolean-algebra"]), ("logica", &["bools", "boolean-algebra"]),
    ("comparacion", &["comparisons"]), ("comparaciones", &["comparisons"]),
    ("numero", &["numbers", "maths"]), ("numeros", &["numbers", "maths"]), ("matematica", &["maths"]), ("matematicas", &["maths"]),
    ("aritmetica", &["numbers", "maths"]), ("primo", &["prime", "maths"]), ("primos", &["prime", "maths"]),
    ("funcion", &["functions", "function-arguments"]), ("funciones", &["functions", "function-arguments"]),
    ("argumentos", &["function-arguments"]), ("parametros", &["function-arguments"]),
    ("orden superior", &["higher-order-functions"]), ("lambda", &["anonymous-functions", "higher-order-functions"]),
    ("clase", &["classes"]), ("clases", &["classes", "class-inheritance", "class-composition"]),
    ("objeto", &["classes"]), ("objetos", &["classes"]), ("poo", &["classes", "class-inheritance", "class-composition"]),
    ("programacion orientada a objetos", &["classes", "class-inheritance", "class-composition"]),
    ("herencia", &["class-inheritance"]), ("composicion", &["class-composition"]),
    ("excepcion", &["raising-and-handling-errors", "user-defined-errors"]),
    ("excepciones", &["raising-and-handling-errors", "user-defined-errors"]), ("errores", &["raising-and-handling-errors"]),
    ("generador", &["generators", "generator-expressions"]), ("generadores", &["generators", "generator-expressions"]),
    ("iterador", &["iterators"]), ("iteradores", &["iterators"]), ("decorador", &["decorators"]), ("decoradores", &["decorators"]),
    ("expresiones regulares", &["regular-expressions"]), ("regex", &["regular-expressions"]),
    ("enumeracion", &["enums"]), ("desempaquetado", &["unpacking-and-multiple-assignment"]),
    ("busqueda", &["searches", "binary-search"]), ("buscar", &["searches"]), ("busqueda binaria", &["binary-search", "searches"]),
    ("binaria", &["binary-search"]), ("ordenamiento", &["sorts"]), ("ordenar", &["sorts"]), ("ordenacion", &["sorts"]),
    ("grafo", &["graphs"]), ("grafos", &["graphs"]), ("arbol", &["data-structures", "binary-tree", "tree"]),
    ("arboles", &["data-structures", "binary-tree", "tree"]), ("pila", &["data-structures", "stack"]),
    ("cola", &["data-structures", "queue"]), ("lista enlazada", &["data-structures", "linked-list"]),
    ("estructuras de datos", &["data-structures"]), ("estructura de datos", &["data-structures"]),
    ("heap", &["data-structures", "heap"]), ("monticulo", &["data-structures", "heap"]),
    ("programacion dinamica", &["dynamic-programming"]), ("dinamica", &["dynamic-programming"]),
    ("memoizacion", &["dynamic-programming"]), ("voraz", &["greedy-methods"]), ("voraces", &["greedy-methods"]),
    ("greedy", &["greedy-methods"]), ("backtracking", &["backtracking"]), ("vuelta atras", &["backtracking"]),
    ("divide y venceras", &["divide-and-conquer"]), ("mochila", &["knapsack"]),
    ("bits", &["bit-manipulation"]), ("binario", &["bit-manipulation", "conversions"]), ("conversion", &["conversions"]),
    ("cifrado", &["ciphers"]), ("criptografia", &["ciphers"]), ("compresion", &["data-compression"]),
    ("matriz", &["matrix", "linear-algebra"]), ("matrices", &["matrix", "linear-algebra"]),
    ("geometria", &["geometry"]), ("algoritmos", &["searches", "sorts"]), ("algoritmo", &["searches", "sorts"]),
    ("fibonacci", &["fibonacci"]), ("factorial", &["factorial"]), ("palindromo", &["palindrome"]),
    ("burbuja", &["sorts", "bubble"]), ("insercion", &["sorts", "insertion"]), ("seleccion", &["sorts", "selection"]),
    ("quicksort", &["sorts", "quick"]), ("rapido", &["quick"]), ("mezcla", &["sorts", "merge"]), ("merge sort", &["sorts", "merge"]),
    ("anchura", &["graphs", "breadth-first"]), ("profundidad", &["graphs", "depth-first"]), ("camino mas corto", &["graphs", "dijkstra"]),
    ("parentesis", &["balanced-parentheses", "matching-brackets"]), ("anagrama", &["anagram"]), ("subcadena", &["substring"]),
    ("puntero", &["pointers", "memory"]), ("punteros", &["pointers", "memory"]), ("referencia", &["references"]),
    ("referencias", &["references"]), ("template", &["templates", "generics"]), ("templates", &["templates", "generics"]),
    ("stl", &["containers", "standard-library"]), ("vector", &["lists", "vectors"]), ("c++", &["cpp", "c++"]), ("cpp", &["cpp", "c++"]),
];

const VACIAS: &str = "de la el los las un una y o en a con para por que del al como sobre practicar quiero ejercicio \
ejercicios desafio desafios python nivel basico intermedio avanzado principiante the of and to";

fn palabra(c: Option<char>) -> bool {
    c.is_some_and(|c| c.is_alphanumeric() || c == '_')
}

/// `re.search(rf"\b{re.escape(frase)}\b", q)` con una frase que empieza y acaba en letra o cifra
fn aparece(frase: &str, q: &str) -> bool {
    let mut desde = 0;
    while let Some(i) = q[desde..].find(frase) {
        let a = desde + i;
        let b = a + frase.len();
        if !palabra(q[..a].chars().next_back()) && !palabra(q[b..].chars().next()) {
            return true;
        }
        desde = a + q[a..].chars().next().map_or(1, char::len_utf8);
    }
    false
}

/// `terminos(consulta, extra)`: (etiquetas, palabras) de una consulta en castellano o inglés
pub(crate) fn terminos(consulta: &str, extra: &[String]) -> (BTreeSet<String>, BTreeSet<String>) {
    let q = normalizar(consulta);
    let mut etiquetas = BTreeSet::new();
    let mut palabras = BTreeSet::new();
    let mut frases: Vec<&(&str, &[&str])> = SINONIMOS.iter().collect();
    frases.sort_by_key(|(f, _)| std::cmp::Reverse(f.chars().count()));
    for (frase, et) in frases {
        if aparece(frase, &q) {
            etiquetas.extend(et.iter().map(|s| s.to_string()));
        }
    }
    let vacias: Vec<&str> = VACIAS.split(' ').collect();
    let textos: Vec<String> = std::iter::once(q.clone()).chain(extra.iter().map(|e| normalizar(e))).collect();
    for texto in &textos {
        for p in texto.split_whitespace() {
            let n = p.chars().count();
            if n >= 3 && !vacias.contains(&p) {
                palabras.insert(p.to_string());
                if p.ends_with('s') && n > 4 {
                    palabras.insert(sin_cola(p, 1));
                }
            }
        }
    }
    for e in extra {
        etiquetas.insert(normalizar(e).replace(' ', "-"));
    }
    (etiquetas, palabras)
}

fn nivel_por(valor: Option<&Valor>, cortes: (f64, f64)) -> &'static str {
    match valor.filter(|v| !v.es_nulo()).and_then(Valor::num) {
        None => "intermedio",
        Some(v) if v <= cortes.0 => "principiante",
        Some(v) if v <= cortes.1 => "intermedio",
        Some(_) => "avanzado",
    }
}

// =========================================================================== las fuentes

#[derive(Clone, Copy, PartialEq)]
enum Fuente {
    Exercism,
    ExercismCpp,
    TheAlgorithms,
    TheAlgorithmsCpp,
    ProjectEuler,
}

const FUENTES: [Fuente; 5] = [Fuente::Exercism, Fuente::ExercismCpp, Fuente::TheAlgorithms, Fuente::TheAlgorithmsCpp, Fuente::ProjectEuler];

impl Fuente {
    fn id(self) -> &'static str {
        match self {
            Fuente::Exercism => "exercism",
            Fuente::ExercismCpp => "exercism_cpp",
            Fuente::TheAlgorithms => "thealgorithms",
            Fuente::TheAlgorithmsCpp => "thealgorithms_cpp",
            Fuente::ProjectEuler => "projecteuler",
        }
    }

    fn nombre(self) -> &'static str {
        match self {
            Fuente::Exercism => "Exercism",
            Fuente::ExercismCpp => "Exercism (C++)",
            Fuente::TheAlgorithms => "TheAlgorithms",
            Fuente::TheAlgorithmsCpp => "TheAlgorithms (C++)",
            Fuente::ProjectEuler => "Project Euler",
        }
    }

    fn licencia(self) -> &'static str {
        match self {
            Fuente::ProjectEuler => "CC BY-NC-SA 4.0",
            _ => "MIT",
        }
    }

    fn de(id: &str) -> Option<Fuente> {
        FUENTES.into_iter().find(|f| f.id() == id)
    }

    fn indice(self) -> R<Vec<Mapa>> {
        match self {
            Fuente::Exercism => indice_exercism(false),
            Fuente::ExercismCpp => indice_exercism(true),
            Fuente::TheAlgorithms => indice_thealgorithms(),
            Fuente::TheAlgorithmsCpp => indice_thealgorithms_cpp(),
            Fuente::ProjectEuler => indice_euler(),
        }
    }
}

// --------------------------------------------------------------------------------------------- Exercism

fn raw_exercism(cpp: bool) -> &'static str {
    if cpp {
        "https://raw.githubusercontent.com/exercism/cpp/main"
    } else {
        "https://raw.githubusercontent.com/exercism/python/main"
    }
}

fn clave<'a>(v: &'a Valor, k: &str) -> R<&'a Valor> {
    match v {
        Valor::Mapa(m) => m.get(k).ok_or_else(|| otro(format!("KeyError: '{k}'"))),
        otro_ => Err(otro(format!("'{}' object is not subscriptable", py::tipo(otro_)))),
    }
}

fn indice_exercism(cpp: bool) -> R<Vec<Mapa>> {
    let cfg = json_de(&bajar(&format!("{}/config.json", raw_exercism(cpp)), SEMANA)?)?;
    let ejercicios = mapa_de(Some(clave(&cfg, "exercises")?));
    let (id, pista) = if cpp { ("exercism_cpp", "cpp") } else { ("exercism", "python") };
    let mut salida = Vec::new();
    for tipo in ["concept", "practice"] {
        for e in lista_de(&get_o(&ejercicios, tipo, Valor::Lista(Vec::new()))) {
            let Valor::Mapa(e) = e else { return Err(otro("AttributeError: 'get'")) };
            let estado = e.texto("status");
            let slug = e.get("slug").ok_or_else(|| otro("KeyError: 'slug'"))?.texto_py();
            if matches!(estado, Some("deprecated") | Some("wip")) || slug == "hello-world" {
                continue;
            }
            let nombre = e.get("name").ok_or_else(|| otro("KeyError: 'name'"))?.clone();
            let mut principales = lista_de(&o_bien(&e, "practices", o_bien(&e, "concepts", Valor::Lista(Vec::new()))));
            let (titulo, extra_palabras) = if cpp {
                principales.push(Valor::Texto("cpp".into()));
                principales.push(Valor::Texto("c++".into()));
                (Valor::Texto(format!("{} (C++)", nombre.texto_py())), " cpp c++")
            } else {
                (nombre.clone(), "")
            };
            let mut it = Mapa::new()
                .con("fuente", id)
                .con("ref", format!("{tipo}/{slug}"))
                .con("titulo", titulo)
                .con("etiquetas", Valor::Lista(principales))
                .con("previas", o_bien(&e, "prerequisites", Valor::Lista(Vec::new())))
                .con("palabras", palabras_de(&format!("{slug} {}{extra_palabras}", nombre.texto_py())))
                .con("nivel", if tipo == "concept" { "principiante" } else { nivel_por(e.get("difficulty"), (2.0, 5.0)) })
                .con("tipo", if tipo == "concept" { "concepto" } else { "práctica" })
                .con("verificable", true);
            if cpp {
                it.poner("lenguaje", "cpp");
            }
            it.poner("url", format!("https://exercism.org/tracks/{pista}/exercises/{slug}"));
            it.poner("licencia", "MIT");
            salida.push(it);
        }
    }
    Ok(salida)
}

/// `~~~~exercism/note … ~~~~` → cita en markdown
fn admoniciones(md: &str) -> String {
    static RE: LazyLock<Regex> = LazyLock::new(|| re(r"(?s)~~~~exercism/(\w+)\n(.*?)\n~~~~"));
    RE.replace_all(md, |c: &regex::Captures| {
        let t = &c[1];
        let tipo = match t {
            "note" => "Nota".to_string(),
            "caution" => "Cuidado".into(),
            "tip" => "Consejo".into(),
            "advanced" => "Avanzado".into(),
            otro => capitalize(otro),
        };
        let cuerpo: Vec<String> = cadena::splitlines(cadena::strip(&c[2])).iter().map(|l| format!("> {l}")).collect();
        format!("> **{tipo}**\n>\n{}\n", cuerpo.join("\n"))
    })
    .into_owned()
}

fn cargar_exercism(cpp: bool, r: &str) -> R<Mapa> {
    static REF: LazyLock<Regex> = LazyLock::new(|| re(r"^(concept|practice)/[a-z0-9\-]+$"));
    if !REF.is_match(r) {
        return Err(falla("Ejercicio de Exercism no válido"));
    }
    let (tipo, slug) = r.split_once('/').unwrap_or_default();
    let base = format!("{}/exercises/{tipo}/{slug}", raw_exercism(cpp));
    let meta = json_de(&bajar(&format!("{base}/.meta/config.json"), MES)?)?;
    let meta = match meta {
        Valor::Mapa(m) => m,
        _ => return Err(otro("AttributeError: 'get'")),
    };
    let archivos = mapa_de(Some(&o_bien(&meta, "files", Valor::Mapa(Mapa::new()))));
    let nombres = |k: &str| -> Vec<String> { lista_de(&o_bien(&archivos, k, Valor::Lista(Vec::new()))).iter().map(Valor::texto_py).collect() };
    let solucion = nombres("solution");
    let pruebas = nombres("test");
    let ejemplo = {
        let e = nombres("example");
        if e.is_empty() { nombres("exemplar") } else { e }
    };
    let editor = nombres("editor");
    if solucion.is_empty() || pruebas.is_empty() || ejemplo.is_empty() {
        return Err(falla(format!("«{slug}» no trae código de partida, pruebas y solución.")));
    }
    let mut paginas = Vec::new();
    for n in &solucion {
        paginas.push(Mapa::new().con("nombre", basename(n)).con("contenido", bajar(&format!("{base}/{n}"), MES)?).con("descripcion", ""));
    }
    for n in &editor {
        paginas.push(
            Mapa::new()
                .con("nombre", basename(n))
                .con("contenido", bajar(&format!("{base}/{n}"), MES)?)
                .con("descripcion", "Página de apoyo: no hace falta cambiarla.")
                .con("solo_lectura", true),
        );
    }
    let bases: Vec<String> = solucion.iter().map(|s| basename(s)).collect();
    let mut referencia = Vec::new();
    for (i, n) in ejemplo.iter().enumerate() {
        let destino = if bases.contains(&basename(n)) { basename(n) } else { bases[i.min(bases.len() - 1)].clone() };
        referencia.push(Valor::Mapa(Mapa::new().con("nombre", destino).con("contenido", bajar(&format!("{base}/{n}"), MES)?)));
    }
    referencia.extend(paginas.iter().filter(|p| p.verdad("solo_lectura")).cloned().map(Valor::Mapa));
    let mut tests = Mapa::new();
    for n in &pruebas {
        tests.poner(basename(n), bajar(&format!("{base}/{n}"), MES)?);
    }
    let mut docs = HashMap::new();
    for n in ["introduction.md", "instructions.md", "instructions.append.md", "hints.md"] {
        docs.insert(n, descargar(&format!("{base}/.docs/{n}"), MES, false)?.unwrap_or_default());
    }
    let enunciado: Vec<String> = ["instructions.md", "instructions.append.md"].iter().filter(|n| !docs[*n].is_empty()).map(|n| admoniciones(&docs[*n])).collect();
    let teoria = admoniciones(&docs["introduction.md"]);
    let indice = if cpp { indice_exercism(true)? } else { indice_exercism(false)? };
    // `{e["ref"]: e for e in indice}`: con refs repetidas, la última
    let e = indice.into_iter().rev().find(|x| x.texto("ref") == Some(r)).unwrap_or_default();
    let mut autores = lista_de(&o_bien(&meta, "authors", Valor::Lista(Vec::new())));
    autores.extend(lista_de(&o_bien(&meta, "contributors", Valor::Lista(Vec::new()))));
    autores.truncate(8);
    let mut conceptos = lista_de(&o_bien(&e, "etiquetas", Valor::Lista(Vec::new())));
    conceptos.extend(lista_de(&o_bien(&e, "previas", Valor::Lista(Vec::new()))).into_iter().take(3));
    let (pista, nombre_origen, tipo_c) = if cpp { ("cpp", "Exercism · pista de C++", "cpp_test") } else { ("python", "Exercism · pista de Python", "unittest") };
    let titulo = o_bien(&e, "titulo", Valor::Texto(if cpp { format!("{} (C++)", title(&slug.replace('-', " "))) } else { title(&slug.replace('-', " ")) }));
    let mut d = Mapa::new()
        .con("titulo", titulo)
        .con("enunciado", cadena::strip(&enunciado.join("\n\n")))
        .con("teoria", cadena::strip(&teoria))
        .con("idioma", "en")
        .con("nivel", get_o(&e, "nivel", Valor::Texto("intermedio".into())))
        .con("conceptos", Valor::Lista(conceptos))
        .con("paginas", Valor::Lista(paginas.into_iter().map(Valor::Mapa).collect()));
    if cpp {
        d.poner("lenguaje", "cpp");
    }
    d.poner("comprobacion", Mapa::new().con("tipo", tipo_c).con("pruebas_visibles", false));
    let mut origen = Mapa::new()
        .con("tipo", if cpp { "exercism_cpp" } else { "exercism" })
        .con("nombre", nombre_origen)
        .con("ref", r)
        .con("url", o_bien(&e, "url", Valor::Texto(format!("https://exercism.org/tracks/{pista}/exercises/{slug}"))))
        .con("codigo", format!("https://github.com/exercism/{pista}/tree/main/exercises/{tipo}/{slug}"))
        .con("licencia", "MIT")
        .con("autores", Valor::Lista(autores));
    if cpp {
        origen.poner("lenguaje", "cpp");
    }
    origen.poner("atribucion", format!("Ejercicio de Exercism (github.com/exercism/{pista}), licencia MIT."));
    d.poner("origen", origen);
    d.poner(
        "privado",
        Mapa::new()
            .con("comprobacion", Mapa::new().con("tipo", tipo_c).con("archivos", tests))
            .con("referencia", Valor::Lista(referencia))
            .con("pistas_fuente", admoniciones(&docs["hints.md"])),
    );
    Ok(d)
}

// --------------------------------------------------------------------------------------------- TheAlgorithms

const RAW_TA: &str = "https://raw.githubusercontent.com/TheAlgorithms/Python/master";
const RAW_TA_CPP: &str = "https://raw.githubusercontent.com/TheAlgorithms/C-Plus-Plus/master";
/// Categorías que necesitan numpy, red, imágenes o sonido, o que no son ejercicios
const EXCLUIDAS: &[&str] = &[
    "audio_filters", "computer_vision", "digital_image_processing", "file_transfer", "fractals", "graphics", "machine_learning",
    "neural_network", "quantum", "web_programming", "docs", "project_euler", "scripts", "tests", "genetic_algorithm", "fuzzy_logic",
    "linear_programming", "blockchain", "networking_flow",
];
const EXCLUIDAS_CPP: &[&str] = &["docs", "scripts", "build", "cmake"];

fn nivel_categoria(c: &str) -> &'static str {
    if ["dynamic_programming", "graphs", "backtracking"].contains(&c) {
        "avanzado"
    } else {
        "intermedio"
    }
}

static CATEGORIA: LazyLock<Regex> = LazyLock::new(|| re(r"^## \[([^\]]+)\]\(([^)]+)\)"));

fn indice_thealgorithms() -> R<Vec<Mapa>> {
    static ARCHIVO: LazyLock<Regex> = LazyLock::new(|| re(r"^\s*\* \[([^\]]+)\]\((?:https://github\.com/TheAlgorithms/Python/blob/master/)?([^)]+\.py)\)"));
    static SUB: LazyLock<Regex> = LazyLock::new(|| re(r"^\s*\* ([^\[\]]+)$"));
    let texto = bajar(&format!("{RAW_TA}/DIRECTORY.md"), SEMANA)?;
    let mut salida = Vec::new();
    let (mut categoria, mut sub): (Option<String>, Option<String>) = (None, None);
    for linea in cadena::splitlines(&texto) {
        if let Some(m) = CATEGORIA.captures(linea) {
            categoria = Some(m[2].trim_matches('/').to_string());
            sub = None;
            continue;
        }
        let Some(cat) = categoria.as_deref().filter(|c| !c.is_empty() && !EXCLUIDAS.contains(c)) else { continue };
        if let Some(m) = ARCHIVO.captures(linea) {
            let ruta = m[2].to_string();
            if ruta.contains("/tests/") || basename(&ruta).starts_with("__") {
                continue;
            }
            let sub_v = sub.clone().filter(|s| !s.is_empty());
            let mut etiquetas = vec![Valor::Texto(cat.replace('_', "-"))];
            if let Some(s) = &sub_v {
                etiquetas.push(Valor::Texto(s.clone()));
            }
            salida.push(
                Mapa::new()
                    .con("fuente", "thealgorithms")
                    .con("ref", ruta.clone())
                    .con("titulo", &m[1])
                    .con("etiquetas", Valor::Lista(etiquetas))
                    .con("previas", Valor::Lista(Vec::new()))
                    .con("palabras", palabras_de(&format!("{} {} {}", &m[1], sin_cola(&basename(&ruta), 3), sub.clone().unwrap_or_default())))
                    .con("nivel", nivel_categoria(cat))
                    .con("tipo", cat.replace('_', " "))
                    .con("verificable", true)
                    .con("url", format!("https://github.com/TheAlgorithms/Python/blob/master/{ruta}"))
                    .con("licencia", "MIT"),
            );
            continue;
        }
        if let Some(m) = SUB.captures(linea) {
            sub = Some(normalizar(&m[1]).replace(' ', "-"));
        }
    }
    Ok(salida)
}

/// Lo que hace `desafios/arneses/codigo.py` (una operación con su entrada)
pub(crate) fn codigo_py(state: &AppState, entrada: Mapa) -> R<Valor> {
    const MARCA: &str = "__PRIG_CODIGO__";
    let script = std::fs::read_to_string(state.base_dir.join("backend/desafios/arneses/codigo.py")).map_err(otro)?;
    let dir = (0..100)
        .map(|_| std::env::temp_dir().join(format!("prig_codigo_{}", &uuid::Uuid::new_v4().simple().to_string()[..8])))
        .find(|r| std::fs::create_dir(r).is_ok())
        .ok_or_else(|| otro("no se pudo crear la carpeta temporal"))?;
    struct Borrar(PathBuf);
    impl Drop for Borrar {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    let _b = Borrar(dir.clone());
    std::fs::write(dir.join("_prig_codigo.py"), script).map_err(otro)?;
    std::fs::write(dir.join("_prig_codigo.json"), prig_plataforma::json::escribir_linea(&Valor::Mapa(entrada))).map_err(otro)?;
    let d = dir.to_string_lossy().into_owned();
    let r = state.ejecutor.ejecutar_archivo(&format!("{d}/_prig_codigo.py"), Some(&d), Some(60), None, &[]);
    let stdout = r.texto("stdout").unwrap_or_default();
    let Some(linea) = stdout.lines().rev().find_map(|l| l.strip_prefix(MARCA)) else {
        return Err(otro(format!("codigo.py: {}", r.texto("stderr").or(r.texto("error")).unwrap_or_default())));
    };
    let Valor::Mapa(mut salida) = json_de(linea)? else { return Err(otro("codigo.py: salida rara")) };
    if let Some(v) = salida.quitar("ok") {
        return Ok(v);
    }
    if let Some(Valor::Texto(e)) = salida.get("error") {
        return Err(falla(e.clone()));
    }
    Err(otro(salida.valor("excepcion").texto_py()))
}

fn cargar_thealgorithms(state: &AppState, r: &str, funcion: Option<&str>) -> R<Mapa> {
    static REF: LazyLock<Regex> = LazyLock::new(|| re(r"^[a-z0-9_]+(?:/[a-z0-9_]+)*\.py$"));
    if !REF.is_match(r) || r.contains("..") {
        return Err(falla("Archivo de TheAlgorithms no válido"));
    }
    let fuente = bajar(&format!("{RAW_TA}/{r}"), MES)?;
    let mut entrada = Mapa::new().con("operacion", "thealgorithms").con("fuente", fuente);
    if let Some(f) = funcion.filter(|f| !f.is_empty()) {
        entrada.poner("funcion", f);
    }
    let x = mapa_de(Some(&codigo_py(state, entrada)?));
    let t = |k: &str| x.valor(k).texto_py();
    let funcion = t("funcion");
    // los nombres del archivo ya son [a-z0-9_]: `re.sub(r"\W", "_", ...)` no cambia nada
    let mut modulo = sin_cola(&basename(r), 3);
    if !modulo.starts_with(|c: char| c.is_ascii_alphabetic() || c == '_') {
        modulo = format!("algoritmo_{modulo}");
    }
    let nombre = format!("{modulo}.py");
    let ejemplos = t("ejemplos");
    let e = indice_thealgorithms()?.into_iter().find(|x| x.texto("ref") == Some(r)).unwrap_or_default();
    let enunciado = format!(
        "{}\n\n**Implement** `{funcion}` in the page `{nombre}`.\n\n```python\n{}\n```\n\n**Examples** (these are also the tests):\n\n```python\n{ejemplos}\n```",
        t("prosa"),
        t("firma")
    );
    let base_titulo = o_bien(&e, "titulo", Valor::Texto(title(&modulo.replace('_', " ")))).texto_py();
    Ok(Mapa::new()
        .con("titulo", format!("{base_titulo} · {funcion}"))
        .con("enunciado", enunciado)
        .con("teoria", "")
        .con("idioma", "en")
        .con("nivel", get_o(&e, "nivel", Valor::Texto("intermedio".into())))
        .con("conceptos", o_bien(&e, "etiquetas", Valor::Lista(Vec::new())))
        .con("paginas", Valor::Lista(vec![Valor::Mapa(Mapa::new().con("nombre", nombre.clone()).con("contenido", t("partida")).con("descripcion", ""))]))
        .con("comprobacion", Mapa::new().con("tipo", "doctest").con("pruebas_visibles", true))
        .con(
            "origen",
            Mapa::new()
                .con("tipo", "thealgorithms")
                .con("nombre", "TheAlgorithms/Python")
                .con("ref", r)
                .con("funcion", funcion.clone())
                .con("url", format!("https://github.com/TheAlgorithms/Python/blob/master/{r}"))
                .con("licencia", "MIT")
                .con("otras_funciones", x.valor("otras_funciones").clone())
                .con("atribucion", "Algoritmo de TheAlgorithms/Python (github.com/TheAlgorithms/Python), licencia MIT."),
        )
        .con(
            "privado",
            Mapa::new()
                .con("comprobacion", Mapa::new().con("tipo", "doctest").con("modulo", modulo).con("ejemplos", ejemplos))
                .con("referencia", Valor::Lista(vec![Valor::Mapa(Mapa::new().con("nombre", nombre).con("contenido", t("completa")))])),
        ))
}

fn indice_thealgorithms_cpp() -> R<Vec<Mapa>> {
    static ARCHIVO: LazyLock<Regex> =
        LazyLock::new(|| re(r"^\s*\* \[([^\]]+)\]\((?:https://github\.com/TheAlgorithms/C-Plus-Plus/blob/master/)?([^)]+\.cpp)\)"));
    let mut salida = Vec::new();
    let Some(texto) = descargar(&format!("{RAW_TA_CPP}/DIRECTORY.md"), SEMANA, false)?.filter(|t| !t.is_empty()) else { return Ok(salida) };
    let mut categoria: Option<String> = None;
    for linea in cadena::splitlines(&texto) {
        if let Some(m) = CATEGORIA.captures(linea) {
            categoria = Some(m[2].trim_matches('/').to_string());
            continue;
        }
        let Some(cat) = categoria.as_deref().filter(|c| !c.is_empty() && !EXCLUIDAS_CPP.contains(c)) else { continue };
        if let Some(m) = ARCHIVO.captures(linea) {
            let ruta = m[2].to_string();
            salida.push(
                Mapa::new()
                    .con("fuente", "thealgorithms_cpp")
                    .con("ref", ruta.clone())
                    .con("titulo", format!("{} (C++)", &m[1]))
                    .con("etiquetas", Valor::Lista(vec![Valor::Texto(cat.replace('_', "-")), Valor::Texto("cpp".into()), Valor::Texto("c++".into())]))
                    .con("previas", Valor::Lista(Vec::new()))
                    .con("palabras", palabras_de(&format!("{} {} cpp c++ ", &m[1], sin_cola(&basename(&ruta), 4))))
                    .con("nivel", nivel_categoria(cat))
                    .con("tipo", cat.replace('_', " "))
                    .con("verificable", false)
                    .con("lenguaje", "cpp")
                    .con("url", format!("https://github.com/TheAlgorithms/C-Plus-Plus/blob/master/{ruta}"))
                    .con("licencia", "MIT"),
            );
        }
    }
    Ok(salida)
}

fn cargar_thealgorithms_cpp(r: &str) -> R<Mapa> {
    static REF: LazyLock<Regex> = LazyLock::new(|| re(r"(?i)^[a-z0-9_]+(?:/[a-z0-9_]+)*\.cpp$"));
    if !REF.is_match(r) || r.contains("..") {
        return Err(falla("Archivo de TheAlgorithms C++ no válido"));
    }
    let fuente = bajar(&format!("{RAW_TA_CPP}/{r}"), MES)?;
    let nombre = basename(r);
    let e = indice_thealgorithms_cpp()?.into_iter().find(|x| x.texto("ref") == Some(r)).unwrap_or_default();
    Ok(Mapa::new()
        .con("titulo", o_bien(&e, "titulo", Valor::Texto(title(&nombre.replace(".cpp", "").replace('_', " ")))))
        .con(
            "enunciado",
            format!("Implementa y experimenta con el algoritmo `{nombre}` de TheAlgorithms C++.\n\nExamina el archivo de partida, adapta la solución y ejecuta tu código."),
        )
        .con("teoria", "")
        .con("idioma", "en")
        .con("nivel", get_o(&e, "nivel", Valor::Texto("intermedio".into())))
        .con("conceptos", o_bien(&e, "etiquetas", textos(&["cpp"])))
        .con("paginas", Valor::Lista(vec![Valor::Mapa(Mapa::new().con("nombre", nombre.clone()).con("contenido", fuente.clone()).con("descripcion", "Código de partida en C++"))]))
        .con("lenguaje", "cpp")
        .con("comprobacion", Mapa::new().con("tipo", "ninguna").con("pruebas_visibles", false))
        .con(
            "origen",
            Mapa::new()
                .con("tipo", "thealgorithms_cpp")
                .con("nombre", "TheAlgorithms · C++")
                .con("ref", r)
                .con("url", format!("https://github.com/TheAlgorithms/C-Plus-Plus/blob/master/{r}"))
                .con("licencia", "MIT")
                .con("lenguaje", "cpp")
                .con("atribucion", "Algoritmo de TheAlgorithms/C-Plus-Plus, licencia MIT."),
        )
        .con(
            "privado",
            Mapa::new()
                .con("comprobacion", Mapa::new().con("tipo", "ninguna"))
                .con("referencia", Valor::Lista(vec![Valor::Mapa(Mapa::new().con("nombre", nombre).con("contenido", fuente))])),
        ))
}

// --------------------------------------------------------------------------------------------- Project Euler

fn indice_euler() -> R<Vec<Mapa>> {
    let texto = bajar("https://projecteuler.net/minimal=problems;csv", SEMANA)?;
    let mut lector = csv::ReaderBuilder::new().flexible(true).from_reader(texto.as_bytes());
    let cabecera: Vec<String> = lector.headers().map_err(otro)?.iter().map(String::from).collect();
    let mut salida = Vec::new();
    for fila in lector.records() {
        let fila = fila.map_err(otro)?;
        // `csv.DictReader`: lo que falta vale None (y `.get(k, "")` da None, no "")
        let campo = |k: &str| -> Option<Option<String>> { cabecera.iter().position(|c| c == k).map(|i| fila.get(i).map(String::from)) };
        let Some(Some(id)) = campo("ID") else { continue };
        let Some(n) = prig_plataforma::valor::entero_de_texto(&id) else { continue };
        let resueltos = match campo("Solved By").flatten().filter(|s| !s.is_empty()) {
            None => 0,
            Some(s) => match prig_plataforma::valor::entero_de_texto(&s) {
                Some(x) => x,
                None => continue,
            },
        };
        let titulo = match campo("Title") {
            None => String::new(),
            Some(None) => "None".into(),
            Some(Some(t)) => t,
        };
        salida.push(
            Mapa::new()
                .con("fuente", "projecteuler")
                .con("ref", n.to_string())
                .con("titulo", format!("{n}. {titulo}"))
                .con("etiquetas", textos(&["maths"]))
                .con("previas", Valor::Lista(Vec::new()))
                .con("palabras", palabras_de(&titulo))
                .con("nivel", if resueltos > 100_000 { "principiante" } else if resueltos > 20_000 { "intermedio" } else { "avanzado" })
                .con("resueltos", Valor::Entero(resueltos))
                .con("tipo", "matemáticas")
                .con("verificable", false)
                .con("url", format!("https://projecteuler.net/problem={n}"))
                .con("licencia", "CC BY-NC-SA 4.0"),
        );
    }
    Ok(salida)
}

/// `<(?!/?(table|tr|td|th|tbody|thead)\b)[^>]+>` → "" (las etiquetas que no son de tablas)
fn sin_etiquetas(t: &str) -> String {
    let es_tabla = |s: &str| {
        ["table", "tr", "td", "th", "tbody", "thead"].iter().any(|w| s.starts_with(w) && !palabra(s[w.len()..].chars().next()))
    };
    let mut salida = String::new();
    let mut i = 0;
    while i < t.len() {
        let resto = &t[i..];
        if resto.starts_with('<') {
            let tras = &resto[1..];
            let tabla = es_tabla(tras) || tras.strip_prefix('/').is_some_and(es_tabla);
            if !tabla && !tras.starts_with('>') {
                if let Some(j) = tras.find('>') {
                    i += 1 + j + 1;
                    continue;
                }
            }
        }
        let c = resto.chars().next().unwrap();
        salida.push(c);
        i += c.len_utf8();
    }
    salida
}

/// `a_markdown`: la vista mínima de Project Euler en markdown (las tablas se quedan en HTML)
fn a_markdown(pagina: &str) -> String {
    static IMG: LazyLock<Regex> = LazyLock::new(|| re(r#"<img[^>]*src="([^"]+)"[^>]*>"#));
    static A: LazyLock<Regex> = LazyLock::new(|| re(r#"(?s)<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>"#));
    static B: LazyLock<Regex> = LazyLock::new(|| re(r"</?(b|strong)>"));
    static I: LazyLock<Regex> = LazyLock::new(|| re(r"</?(i|em|var)>"));
    static BR: LazyLock<Regex> = LazyLock::new(|| re(r"<br\s*/?>"));
    static SUP: LazyLock<Regex> = LazyLock::new(|| re(r"<sup>(.*?)</sup>"));
    static SUB: LazyLock<Regex> = LazyLock::new(|| re(r"<sub>(.*?)</sub>"));
    static P_FIN: LazyLock<Regex> = LazyLock::new(|| re(r"</p>\s*"));
    static P: LazyLock<Regex> = LazyLock::new(|| re(r"<p[^>]*>"));
    let t = IMG.replace_all(pagina, |c: &regex::Captures| format!("![imagen](https://projecteuler.net/{})", c[1].trim_start_matches('/')));
    let t = A.replace_all(&t, |c: &regex::Captures| {
        let h = &c[1];
        let destino = if h.starts_with("http") { h.to_string() } else { format!("https://projecteuler.net/{}", h.trim_start_matches('/')) };
        format!("[{}]({destino})", &c[2])
    });
    let t = B.replace_all(&t, "**");
    let t = I.replace_all(&t, "*");
    let t = BR.replace_all(&t, "  \n");
    let t = SUP.replace_all(&t, "^{$1}");
    let t = SUB.replace_all(&t, "_{$1}");
    let t = P_FIN.replace_all(&t, "\n\n");
    let t = P.replace_all(&t, "");
    let t = sin_etiquetas(&t);
    cadena::strip(&prig_plataforma::html::unescape(&t)).to_string()
}

fn cargar_euler(r: &str, lenguaje: &str) -> R<Mapa> {
    static REF: LazyLock<Regex> = LazyLock::new(|| re(r"^\d{1,4}$"));
    if !REF.is_match(r) {
        return Err(falla("Problema de Project Euler no válido"));
    }
    let n: u32 = r.parse().unwrap_or(0);
    let texto = bajar(&format!("https://projecteuler.net/minimal={n}"), 90.0 * 86400.0)?;
    if cadena::strip(&texto).is_empty() {
        return Err(falla(format!("No existe el problema {n} de Project Euler.")));
    }
    let e = indice_euler()?.into_iter().find(|x| x.texto("ref") == Some(r)).unwrap_or_default();
    let pagina = if lenguaje == "cpp" {
        Mapa::new().con("nombre", format!("euler_{n}.cpp")).con("descripcion", "").con(
            "contenido",
            format!(
                "#include <iostream>\n\n// Resuelve el problema {n} de Project Euler\nlong long solucion() {{\n    // Escribe aquí tu solución\n    return 0;\n}}\n\n\
int main() {{\n    std::cout << solucion() << std::endl;\n    return 0;\n}}\n"
            ),
        )
    } else {
        Mapa::new().con("nombre", format!("euler_{n}.py")).con("descripcion", "").con(
            "contenido",
            format!(
                "def solucion():\n    \"\"\"Devuelve la respuesta del problema {n}.\"\"\"\n    # Escribe aquí tu solución\n    raise NotImplementedError\n\n\n\
if __name__ == \"__main__\":\n    print(solucion())\n"
            ),
        )
    };
    Ok(Mapa::new()
        .con("titulo", o_bien(&e, "titulo", Valor::Texto(format!("Problema {n}"))))
        .con("enunciado", a_markdown(&texto))
        .con("teoria", "")
        .con("idioma", "en")
        .con("nivel", get_o(&e, "nivel", Valor::Texto("intermedio".into())))
        .con("conceptos", textos(&["maths"]))
        .con("paginas", Valor::Lista(vec![Valor::Mapa(pagina)]))
        .con("lenguaje", lenguaje)
        .con("comprobacion", Mapa::new().con("tipo", "ninguna").con("pruebas_visibles", false))
        .con(
            "origen",
            Mapa::new()
                .con("tipo", "projecteuler")
                .con("nombre", "Project Euler")
                .con("ref", r)
                .con("url", format!("https://projecteuler.net/problem={n}"))
                .con("licencia", "CC BY-NC-SA 4.0")
                .con("lenguaje", lenguaje)
                .con(
                    "atribucion",
                    format!("Problema {n} de Project Euler (projecteuler.net), licencia CC BY-NC-SA 4.0. Si se traduce, la traducción se comparte con la misma licencia."),
                )
                .con("nota", "Project Euler no publica las respuestas: ejecuta tu página y compruébala en su web (hace falta cuenta)."),
        )
        .con("privado", Mapa::new().con("comprobacion", Mapa::new().con("tipo", "ninguna")).con("referencia", Valor::Lista(Vec::new()))))
}

// =========================================================================== buscar e importar

/// `buscar(tema, nivel, fuentes, extra, por_fuente=8, lenguaje)`: los desafíos de cada fuente sobre `tema`
fn buscar(tema: &str, nivel: Option<&str>, fuentes: Option<&[String]>, extra: &[String], lenguaje: Option<&str>) -> R<Mapa> {
    let (etiquetas, palabras) = terminos(tema, extra);
    let mut resultados = Vec::new();
    let mut errores = Mapa::new();
    let disponibles: Vec<String> = match lenguaje {
        Some("cpp") => vec!["exercism_cpp".into(), "thealgorithms_cpp".into(), "projecteuler".into()],
        Some("python") => vec!["exercism".into(), "thealgorithms".into(), "projecteuler".into()],
        _ => FUENTES.iter().map(|f| f.id().to_string()).collect(),
    };
    let lenguaje = lenguaje.filter(|l| !l.is_empty());
    for fid in fuentes.unwrap_or(&disponibles) {
        let Some(f) = Fuente::de(fid) else { continue };
        let items = match f.indice() {
            Ok(i) => i,
            Err(ErrorObtener::Desafio(e)) => {
                errores.poner(fid.clone(), e);
                continue;
            }
            Err(e) => return Err(e),
        };
        let mut puntuados: Vec<(f64, Mapa)> = Vec::new();
        for it in items {
            if let (Some(l), Some(propio)) = (lenguaje, it.get("lenguaje").filter(|v| v.verdad())) {
                if propio.texto_py() != l && f != Fuente::ProjectEuler {
                    continue;
                }
            }
            let conjunto = |k: &str| -> BTreeSet<String> { lista_de(it.valor(k)).iter().map(Valor::texto_py).collect() };
            let suyas = conjunto("etiquetas");
            let propias = conjunto("palabras");
            let mut p = 0.0;
            p += 5.0 * etiquetas.intersection(&suyas).count() as f64;
            p += 2.0 * etiquetas.intersection(&conjunto("previas")).count() as f64;
            p += 3.0 * palabras.intersection(&propias).count() as f64;
            // Etiqueta traducida que aparece en el nombre: «busqueda binaria» → binary_search.py / binary_search.cpp
            for et in &etiquetas {
                let trozos: Vec<&str> = et.split('-').filter(|t| !t.is_empty()).collect();
                let casa = |t: &str| {
                    propias.iter().any(|w| w == t || (t.chars().count() >= 6 && cadena::primeros(w, 6) == cadena::primeros(t, 6)))
                };
                if !trozos.is_empty() && trozos.iter().all(|t| casa(t)) {
                    p += 4.0;
                }
            }
            let lista_et: Vec<String> = lista_de(it.valor("etiquetas")).iter().map(Valor::texto_py).collect();
            p += 1.5 * palabras.iter().map(|w| lista_et.iter().filter(|et| et.split('-').any(|x| x == w)).count()).sum::<usize>() as f64;
            if p <= 0.0 {
                continue;
            }
            if nivel.is_some_and(|n| it.texto("nivel") == Some(n)) {
                p += 1.0;
            }
            if f == Fuente::ProjectEuler {
                if let Some(r) = it.get("resueltos").and_then(Valor::num).filter(|r| *r != 0.0) {
                    p += (r / 500_000.0).min(1.0); // a igualdad, los más asequibles
                }
            }
            puntuados.push((p, it));
        }
        puntuados.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        for (p, it) in puntuados.into_iter().take(8) {
            let mut x = Mapa::new();
            for (k, v) in it.iter() {
                if k != "palabras" && k != "previas" {
                    x.poner(k.clone(), v.clone());
                }
            }
            x.poner("puntuacion", Valor::Real(prig_plataforma::valor::redondear(p, 1)));
            resultados.push(Valor::Mapa(x));
        }
    }
    let lista = |s: BTreeSet<String>| Valor::Lista(s.into_iter().map(Valor::Texto).collect());
    Ok(Mapa::new()
        .con("resultados", Valor::Lista(resultados))
        .con("etiquetas", lista(etiquetas))
        .con("palabras", lista(palabras))
        .con("errores", errores))
}

/// `ejecucion.validar_desafio`: vale si la referencia pasa TODO y el código de partida NO (descarta pruebas que no
/// comprueban nada, como `assert True`). `{"valido", "motivo", "pruebas"}`
pub(crate) fn validar_desafio(state: &AppState, iniciales: &[Valor], referencia: &[Valor], privado: &Mapa, minimo: i128) -> R<Mapa> {
    let no = |m: String| Ok(Mapa::new().con("valido", false).con("motivo", m));
    let iniciales = match d::validar_paginas(iniciales, false) {
        Ok(p) => p,
        Err(e) => return no(e),
    };
    let referencia = match d::validar_paginas(referencia, false) {
        Ok(p) => p,
        Err(e) => return no(e),
    };
    let nombres = |p: &[Mapa]| {
        let mut n: Vec<String> = p.iter().map(|x| x.texto("nombre").unwrap_or_default().to_string()).collect();
        n.sort();
        n
    };
    if nombres(&iniciales) != nombres(&referencia) {
        return no("La solución de referencia no tiene las mismas páginas que el código de partida.".into());
    }
    let r = comprobar(state, &referencia, privado, "")?;
    let total = r.get("total").and_then(Valor::entero).unwrap_or(0);
    if !r.verdad("aprobado") {
        let detalle = match r.get("error") {
            Some(e) if e.verdad() => e.texto_py(),
            _ => match r.lista("fallos").and_then(|f| f.first()) {
                Some(f) => mapa_de(Some(f)).valor("mensaje").texto_py(),
                None => String::new(),
            },
        };
        let m = format!("La solución de referencia no pasa sus pruebas ({}/{total}). {detalle}", r.valor("pasados").texto_py());
        return no(cadena::strip(&m).to_string());
    }
    if total < minimo {
        return no(format!("Tiene {total} pruebas; hacen falta al menos {minimo}."));
    }
    let inicial = comprobar(state, &iniciales, privado, "")?;
    if inicial.verdad("aprobado") {
        return no("Las pruebas pasan también con el código de partida: no comprueban nada.".into());
    }
    Ok(Mapa::new().con("valido", true).con("motivo", "OK").con("pruebas", Valor::Entero(total)))
}

/// `importar(fuente, ref, runner, funcion, lenguaje)`: trae el desafío y, si es verificable, comprueba ejecutándolo
/// que sus pruebas funcionan aquí
fn importar(state: &AppState, fuente: &str, r: &str, funcion: Option<&str>, lenguaje: Option<&str>) -> R<Mapa> {
    let Some(f) = Fuente::de(fuente) else { return Err(falla("Fuente desconocida")) };
    let mut des = match f {
        Fuente::Exercism => cargar_exercism(false, r)?,
        Fuente::ExercismCpp => cargar_exercism(true, r)?,
        Fuente::TheAlgorithms => cargar_thealgorithms(state, r, funcion)?,
        Fuente::TheAlgorithmsCpp => cargar_thealgorithms_cpp(r)?,
        Fuente::ProjectEuler => cargar_euler(r, lenguaje.filter(|l| !l.is_empty()).unwrap_or("python"))?,
    };
    let privado = mapa_de(des.get("privado"));
    if mapa_de(privado.get("comprobacion")).get("tipo") != Some(&Valor::Texto("ninguna".into())) {
        let v = validar_desafio(state, des.lista("paginas").unwrap_or(&[]), privado.lista("referencia").unwrap_or(&[]), &privado, 1)?;
        if !v.verdad("valido") {
            return Err(falla(format!("Este desafío no se puede comprobar en tu equipo: {}", v.valor("motivo").texto_py())));
        }
        let mut c = mapa_de(des.get("comprobacion"));
        c.poner("pruebas", v.valor("pruebas").clone());
        des.poner("comprobacion", c);
    }
    Ok(des)
}

/// `_contexto_bloque(ruta_id, bloque_id)`: la ruta de aprendizaje y el bloque para el que se crea el desafío (404 si
/// no existen)
pub(crate) fn contexto_bloque(espacio: &Path, ruta_id: Option<&str>, bloque_id: Option<&str>) -> Result<Mapa, Response> {
    let Some(ruta_id) = ruta_id.filter(|r| !r.is_empty()) else { return Ok(Mapa::new()) };
    let ruta = match prig_aprendizaje::planes::cargar_seguimiento(espacio, ruta_id) {
        Ok(Some(r)) => r,
        Ok(None) => return Err(detalle(StatusCode::NOT_FOUND, "Ruta de aprendizaje no encontrada")),
        Err(e) => {
            tracing::warn!("contexto del bloque: {e}");
            return Err(error_500());
        }
    };
    let bloque_id = bloque_id.filter(|b| !b.is_empty());
    let bloque = bloque_id.and_then(|b| {
        ruta.lista("blocks").unwrap_or(&[]).iter().filter_map(|x| if let Valor::Mapa(m) = x { Some(m) } else { None }).find(|x| x.texto("block_id") == Some(b)).cloned()
    });
    if bloque_id.is_some() && bloque.is_none() {
        return Err(detalle(StatusCode::NOT_FOUND, "Bloque no encontrado en la ruta"));
    }
    let mut info = Mapa::new().con("ruta_id", ruta.valor("id").clone()).con("meta", ruta.valor("goal").clone());
    if let Some(b) = bloque {
        info.poner("bloque_id", b.valor("block_id").clone());
        info.poner("bloque", b.valor("title").clone());
        info.poner("temas", b.valor("topics").clone());
        info.poner("objetivo", b.valor("learning_objective").clone());
        info.poner("validacion", b.valor("validation_check").clone());
    }
    Ok(info)
}

/// `desafios_almacen.guardar(d)` y `_registrar_telemetria(d, evento, attempt_num=...)`: el desafío ya guardado
pub(crate) fn guardar_y_registrar(espacio: &Path, des: &mut Mapa, evento: &str, intento: i64) -> R<()> {
    d::guardar(&carpeta_base(), des)?;
    let banderas = prig_plataforma::banderas::Banderas::new(PathBuf::from(py::expanduser("~/.prig_flags.json")));
    if banderas.activa("learning_telemetry") {
        if let Err(e) = prig_aprendizaje::telemetria::registrar_evento(espacio, des, evento, intento) {
            tracing::warn!("⚠️ Telemetría de desafíos: {e}");
        }
    }
    Ok(())
}

// =========================================================================== catálogo de GitHub

static CATALOGO: LazyLock<Mapa> = LazyLock::new(|| match prig_plataforma::json::leer(include_str!("catalogo_repos.json")) {
    Ok(Valor::Mapa(m)) => m,
    _ => Mapa::new(),
});

fn repositorios() -> Vec<Mapa> {
    CATALOGO.lista("repositorios").unwrap_or(&[]).iter().map(|r| mapa_de(Some(r))).collect()
}

/// `listar_repositorios(lenguaje, categoria, busqueda)`
fn listar_repositorios(lenguaje: Option<&str>, categoria: Option<&str>, busqueda: Option<&str>) -> Vec<Valor> {
    let q = busqueda.filter(|b| !b.is_empty()).map(normalizar).unwrap_or_default();
    let mut res = Vec::new();
    for r in repositorios() {
        if let Some(l) = lenguaje.filter(|l| !l.is_empty() && *l != "todos") {
            if !lista_de(r.valor("lenguajes")).iter().any(|x| x.texto_py() == l) {
                continue;
            }
        }
        if let Some(c) = categoria.filter(|c| !c.is_empty() && *c != "todos") {
            if r.valor("categoria").texto_py() != c {
                continue;
            }
        }
        if !q.is_empty() {
            let etiquetas: Vec<String> = lista_de(r.valor("etiquetas")).iter().map(Valor::texto_py).collect();
            let buscable = normalizar(&format!("{} {} {} {}", r.valor("nombre").texto_py(), r.valor("ref").texto_py(), r.valor("descripcion").texto_py(), etiquetas.join(" ")));
            if !q.split_whitespace().all(|t| buscable.contains(t)) {
                continue;
            }
        }
        res.push(Valor::Mapa(r));
    }
    res
}

fn obtener_repositorio(r: &str) -> Option<Mapa> {
    let r = r.to_lowercase();
    repositorios().into_iter().find(|x| x.valor("ref").texto_py().to_lowercase() == r)
}

/// `_dentro_de(ruta, carpeta)`: ¿`ruta` está dentro de `carpeta` (o es ella)?
fn dentro_de(ruta: &str, carpeta: &str) -> bool {
    let carpeta = carpeta.trim_matches('/');
    let ruta = ruta.trim_start_matches('/');
    carpeta.is_empty() || ruta == carpeta || ruta.starts_with(&format!("{carpeta}/"))
}

fn lenguaje_por_ruta(p: &str) -> &'static str {
    if p.ends_with(".py") {
        "python"
    } else if [".cpp", ".cc", ".cxx", ".h", ".hpp"].iter().any(|e| p.ends_with(e)) {
        "cpp"
    } else {
        "markdown"
    }
}

/// `listar_ejercicios_repo(ref, ruta_sub, limite=50)`: los archivos de ejercicios de un repositorio (la lista viva de
/// GitHub con los destacados primero; sin GitHub, los destacados)
fn listar_ejercicios_repo(r: &str, ruta_sub: &str) -> Mapa {
    const LIMITE: usize = 50;
    let meta = obtener_repositorio(r);
    let mut nombre = meta.as_ref().map(|m| m.valor("nombre").clone()).unwrap_or(Valor::Texto(r.into()));
    let mut descripcion = meta.as_ref().map(|m| m.valor("descripcion").clone()).unwrap_or(Valor::Texto(String::new()));
    let tabla = CATALOGO.mapa("destacados").cloned().unwrap_or_default();
    let destacados: Vec<Mapa> = match tabla.get(&r.to_lowercase()).filter(|v| v.verdad()).or_else(|| tabla.get(r).filter(|v| v.verdad())) {
        Some(v) => lista_de(v).iter().map(|x| mapa_de(Some(x))).collect(),
        None => Vec::new(),
    };
    let mut salida: Vec<Mapa> = Vec::new();
    if let Ok(info) = prig_integrations::github::abrir(r, false) {
        if info.verdad("nombre") {
            nombre = info.valor("nombre").clone();
        }
        if info.verdad("descripcion") {
            descripcion = info.valor("descripcion").clone();
        }
        for a in lista_de(&o_bien(&info, "archivos", Valor::Lista(Vec::new()))) {
            let a = mapa_de(Some(&a));
            let path = a.valor("ruta").texto_py();
            if !ruta_sub.is_empty() && !dentro_de(&path, ruta_sub) {
                continue;
            }
            let ext = py::splitext(&path).1.to_lowercase();
            if ![".py", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".md", ".ipynb"].contains(&ext.as_str()) {
                continue;
            }
            // Excluir tests internos, configs, builds
            if path.split('/').any(|p| [".", "test_", "tests_", "CMake"].iter().any(|x| p.starts_with(x))) {
                let bajo = path.to_lowercase();
                if !(bajo.contains("challenge") || bajo.contains("exercise") || bajo.contains("problem")) {
                    continue;
                }
            }
            let lang = if [".cpp", ".cc", ".cxx", ".h", ".hpp"].contains(&ext.as_str()) {
                "cpp"
            } else if ext == ".ipynb" {
                let langs: Vec<String> = meta.as_ref().map(|m| lista_de(&o_bien(m, "lenguajes", Valor::Lista(Vec::new()))).iter().map(Valor::texto_py).collect()).unwrap_or_default();
                if langs.iter().any(|l| l == "cpp") && !langs.iter().any(|l| l == "python") { "cpp" } else { "python" }
            } else if ext == ".md" {
                "markdown"
            } else {
                "python"
            };
            salida.push(
                Mapa::new()
                    .con("ruta", path.clone())
                    .con("nombre", basename(&path))
                    .con("bytes", get_o(&a, "bytes", Valor::Entero(0)))
                    .con("lenguaje", lang)
                    .con("es_ejercicio", true),
            );
        }
        // Los destacados curados van primero; solo los que existen de verdad en el repositorio
        if !destacados.is_empty() && !salida.is_empty() {
            let mut vivos: Vec<Option<Mapa>> = salida.into_iter().map(Some).collect();
            let mut primero = Vec::new();
            for dd in &destacados {
                let ruta = dd.valor("ruta").texto_py();
                if let Some(i) = vivos.iter().position(|x| x.as_ref().is_some_and(|x| x.valor("ruta").texto_py() == ruta)) {
                    let mut x = vivos[i].take().unwrap();
                    if dd.verdad("lenguaje") {
                        x.poner("lenguaje", dd.valor("lenguaje").clone());
                    }
                    if dd.verdad("nombre") {
                        x.poner("nombre", dd.valor("nombre").clone());
                    }
                    primero.push(x);
                }
            }
            primero.extend(vivos.into_iter().flatten());
            salida = primero;
        }
        salida.truncate(LIMITE);
    }
    // Si la lista viva no devolvió ejercicios o falló la API, los destacados
    if salida.is_empty() {
        for dd in &destacados {
            let path = dd.valor("ruta").texto_py();
            if !ruta_sub.is_empty() && !dentro_de(&path, ruta_sub) {
                continue;
            }
            salida.push(
                Mapa::new()
                    .con("ruta", path.clone())
                    .con("nombre", o_bien(dd, "nombre", Valor::Texto(basename(&path))))
                    .con("bytes", get_o(dd, "bytes", Valor::Entero(1500)))
                    .con("lenguaje", get_o(dd, "lenguaje", Valor::Texto(lenguaje_por_ruta(&path).into())))
                    .con("es_ejercicio", true),
            );
            if salida.len() >= LIMITE {
                break;
            }
        }
    }
    Mapa::new()
        .con("ref", r)
        .con("nombre", nombre)
        .con("descripcion", descripcion)
        .con("archivos", Valor::Lista(salida.into_iter().map(Valor::Mapa).collect()))
}

/// `requests.utils.quote(ruta)`: todo escapado menos letras, cifras, `_.-~` y `/`
fn quote(t: &str) -> String {
    let mut s = String::new();
    for b in t.bytes() {
        if b.is_ascii_alphanumeric() || b"_.-~/".contains(&b) {
            s.push(b as char);
        } else {
            s.push_str(&format!("%{b:02X}"));
        }
    }
    s
}

/// `descargar_contenido_archivo(ref, ruta)`: el texto de un archivo de GitHub, de la caché en disco, de
/// raw.githubusercontent.com (sin gastar cuota de la API) o, si no, con el lector de GitHub. "" si no se pudo.
pub(crate) fn descargar_contenido_archivo(r: &str, ruta: &str) -> String {
    let limpia = r.trim_matches('/');
    let limpia = limpia.strip_suffix(".git").unwrap_or(limpia).to_string();
    let ruta = ruta.trim_start_matches('/').to_string();
    if limpia.is_empty() || ruta.is_empty() {
        return String::new();
    }
    let dir = prig_integrations::github::carpeta().join("archivos").join(limpia.replace('/', "__"));
    let archivo = dir.join(format!("{}.txt", sha1(&ruta)));
    if dir.exists() && archivo.exists() {
        if let Ok(t) = std::fs::read_to_string(&archivo) {
            return t;
        }
    }
    let mut ramas: Vec<String> = vec!["main".into(), "master".into(), "release".into()];
    if let Some(rama) = obtener_repositorio(&limpia).and_then(|m| m.get("rama").filter(|v| v.verdad()).map(Valor::texto_py)) {
        ramas.insert(0, rama);
    }
    let mut vistas = Vec::new();
    ramas.retain(|x| if vistas.contains(x) { false } else { vistas.push(x.clone()); true });
    let token = prig_integrations::github::token().ok().flatten().map(|t| t.0);
    if let Ok(cliente) = reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(10)).build() {
        for rama in &ramas {
            let url = format!("https://raw.githubusercontent.com/{limpia}/{rama}/{}", quote(&ruta));
            let mut pedido = cliente.get(&url).header("User-Agent", "Prig-IDE/1.0");
            if let Some(t) = &token {
                pedido = pedido.header("Authorization", format!("Bearer {t}"));
            }
            let Ok(resp) = pedido.send() else { continue };
            if resp.status().as_u16() == 200 {
                let Ok(b) = resp.bytes() else { continue };
                let contenido = String::from_utf8_lossy(&b).into_owned();
                if std::fs::create_dir_all(&dir).is_ok() {
                    let _ = std::fs::write(&archivo, &contenido);
                }
                return contenido;
            }
        }
    }
    match prig_integrations::github::leer_archivo(&limpia, &ruta) {
        Ok(info) => o_bien(&info, "contenido", Valor::Texto(String::new())).texto_py(),
        Err(_) => String::new(),
    }
}

// =========================================================================== rutas

/// `GET /api/desafios/fuentes`
pub async fn fuentes() -> Response {
    let lista: Vec<Valor> =
        FUENTES.iter().map(|f| Valor::Mapa(Mapa::new().con("id", f.id()).con("nombre", f.nombre()).con("licencia", f.licencia()))).collect();
    json_py(
        StatusCode::OK,
        &Valor::Mapa(Mapa::new().con("fuentes", Valor::Lista(lista)).con("no_incluidas", "LeetCode, HackerRank y Codewars no permiten copiar su contenido.")),
    )
}

/// `GET /api/desafios/github/catalogo`
pub async fn github_catalogo(Query(q): Query<HashMap<String, String>>) -> Response {
    let r = listar_repositorios(q.get("lenguaje").map(String::as_str), q.get("categoria").map(String::as_str), q.get("q").map(String::as_str));
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("categorias", CATALOGO.valor("categorias").clone()).con("repositorios", Valor::Lista(r))))
}

/// `GET /api/desafios/github/ejercicios`
pub async fn github_ejercicios(Query(q): Query<HashMap<String, String>>) -> Response {
    let r = match cuerpo::texto_consulta(&q, "ref") {
        Ok(r) => r,
        Err(e) => return e,
    };
    let ruta = q.get("ruta").cloned().unwrap_or_default();
    match tokio::task::spawn_blocking(move || listar_ejercicios_repo(&r, &ruta)).await {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

/// `palabras_clave(ai, modelo, tema)`: términos en inglés para buscar en fuentes que usan ese idioma ([] si falla)
fn palabras_clave(raiz: &Path, m: &prig_ia::tutor::Motor, nombre: &str, tema: &str) -> Vec<String> {
    let sistema = "Devuelve ÚNICAMENTE un JSON {\"terminos\": [\"...\", \"...\"]} con 3 a 6 términos cortos en INGLÉS \
(nombres de algoritmos, estructuras de datos o conceptos de Python) que describan el tema.";
    let c = prig_ia::vivo::Cancelar::default();
    let prompt = format!("Tema: {}", cadena::primeros(tema, 500));
    let Ok(texto) = prig_ia::tutor::generar_texto(raiz, m, nombre, &prompt, sistema, 0.1, None, &c, None) else { return Vec::new() };
    let Ok(datos) = prig_ia::json_modelo::reparar(&texto) else { return Vec::new() };
    let Ok(lista) = iterar(&o_bien(&datos, "terminos", Valor::Lista(Vec::new()))) else { return Vec::new() };
    lista.iter().take(6).map(|t| cadena::primeros(&t.texto_py(), 40).to_string()).collect()
}

/// `GET /api/desafios/internet/buscar`: con `ayuda_modelo`, si no hay nada, el modelo propone términos en inglés y se
/// vuelve a buscar
pub async fn internet_buscar(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let tema = match cuerpo::texto_consulta(&q, "tema") {
        Ok(t) => t,
        Err(e) => return e,
    };
    let ayuda = match cuerpo::booleano_consulta(&q, "ayuda_modelo") {
        Ok(b) => b.unwrap_or(false),
        Err(e) => return e,
    };
    let nivel = q.get("nivel").cloned();
    let lenguaje = q.get("lenguaje").cloned();
    let modelo = q.get("modelo").cloned();
    let fuentes: Vec<String> = q.get("fuentes").map(|f| f.split(',').filter(|x| !x.is_empty()).map(String::from).collect()).unwrap_or_default();
    let raiz = state.base_dir.clone();
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, Response> {
        let lista = if fuentes.is_empty() { None } else { Some(fuentes.as_slice()) };
        let nivel = nivel.as_deref().filter(|n| !n.is_empty());
        let r = buscar(&tema, nivel, lista, &[], lenguaje.as_deref()).map_err(error_obtener)?;
        if r.lista("resultados").unwrap_or(&[]).is_empty() && ayuda && !cadena::strip(&tema).is_empty() {
            let modelo = prig_ia::tutor::modelo_desafios(modelo.as_deref().filter(|m| !m.is_empty()), None);
            let (m, nombre) = motor(Some(&modelo), None)?;
            let extra = palabras_clave(&raiz, &m, &nombre, &tema);
            if !extra.is_empty() {
                let mut r = buscar(&tema, nivel, lista, &extra, lenguaje.as_deref()).map_err(error_obtener)?;
                r.poner("terminos_del_modelo", Valor::Lista(extra.into_iter().map(Valor::Texto).collect()));
                return Ok(r);
            }
        }
        Ok(r)
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e)) => e,
        Err(_) => error_500(),
    }
}

/// `POST /api/desafios/internet/importar`
pub async fn internet_importar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(
        &b,
        &[
            ("fuente", &Tipo::Texto, true),
            ("ref", &Tipo::Texto, true),
            ("funcion", &TEXTO_OPC, false),
            ("lenguaje", &TEXTO_OPC, false),
            ("tema", &TEXTO_OPC, false),
            ("ruta_id", &TEXTO_OPC, false),
            ("bloque_id", &TEXTO_OPC, false),
        ],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    // `lenguaje: Optional[str] = "python"`
    let lenguaje = if c.contiene("lenguaje") { c.get("lenguaje").filter(|v| !v.es_nulo()).map(Valor::texto_py) } else { Some("python".into()) };
    let texto = move |k: &str| c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py);
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, Response> {
        let mut des = importar(&state, &texto("fuente").unwrap_or_default(), &texto("ref").unwrap_or_default(), texto("funcion").as_deref(), lenguaje.as_deref())
            .map_err(error_obtener)?;
        let bloque = contexto_bloque(&espacio, texto("ruta_id").as_deref(), texto("bloque_id").as_deref())?;
        let mut origen = mapa_de(des.get("origen"));
        for (k, v) in bloque.iter() {
            origen.poner(k.clone(), v.clone());
        }
        if let Some(t) = texto("tema").filter(|t| !t.is_empty()) {
            origen.poner("tema", t);
        }
        if let Some(l) = lenguaje.filter(|l| !l.is_empty()) {
            des.poner("lenguaje", l.clone());
            origen.poner("lenguaje", l);
        }
        des.poner("origen", origen);
        guardar_y_registrar(&espacio, &mut des, "generated", 1).map_err(error_obtener)?;
        Ok(d::publico(&des))
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e)) => e,
        Err(_) => error_500(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normaliza_como_python() {
        assert_eq!(normalizar("  Búsqueda BINARIA, ¡ya! "), "busqueda binaria ya");
        assert_eq!(normalizar("C++ y __init__"), "c y init");
        assert_eq!(title("two-fer 2nd o'neil"), "Two-Fer 2Nd O'Neil");
    }

    #[test]
    fn terminos_en_castellano() {
        let (et, pal) = terminos("Quiero practicar búsqueda binaria y listas", &[]);
        assert!(et.contains("binary-search") && et.contains("searches") && et.contains("lists"));
        assert!(pal.contains("binaria") && pal.contains("lista") && pal.contains("listas") && !pal.contains("quiero"));
        let (et, _) = terminos("x", &["Binary Search".into()]);
        assert!(et.contains("binary-search"));
    }

    #[test]
    fn markdown_de_euler() {
        let t = "<p>Si <b>n</b> es 10<sup>2</sup>, <a href=\"about\">mira</a>.</p>\n<table><tr><td>1</td></tr></table><span class=\"x\">&lt;fin&gt;</span>";
        assert_eq!(a_markdown(t), "Si **n** es 10^{2}, [mira](https://projecteuler.net/about).\n\n<table><tr><td>1</td></tr></table>&lt;fin&gt;".replace("&lt;", "<").replace("&gt;", ">"));
        assert_eq!(sin_etiquetas("a<>b<thx>c</th>d<tablex>"), "a<>bc</th>d");
    }

    #[test]
    fn admoniciones_de_exercism() {
        assert_eq!(admoniciones("x\n~~~~exercism/note\nuno\ndos\n~~~~\ny"), "x\n> **Nota**\n>\n> uno\n> dos\n\ny");
        assert_eq!(admoniciones("~~~~exercism/WARNING\nojo\n~~~~"), "> **Warning**\n>\n> ojo\n");
    }

    #[test]
    fn dentro_de_una_carpeta() {
        assert!(dentro_de("ejercicios/a.py", "ejercicios/"));
        assert!(!dentro_de("ejercicios_avanzados/a.py", "ejercicios"));
        assert_eq!(quote("src/mi archivo+ñ.py"), "src/mi%20archivo%2B%C3%B1.py");
    }
}
