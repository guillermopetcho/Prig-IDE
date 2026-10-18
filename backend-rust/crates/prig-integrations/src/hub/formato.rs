//! Leer y escribir un repositorio de Prig Hub (`hub/formato.py`, formato 1, ver docs/prig-hub.md).
//!
//! Regla de lectura: NUNCA fallar por un archivo mal escrito. Lo que no se entiende se salta, se anota en `avisos` y
//! se sigue. Los campos desconocidos se ignoran.
//!
//! Escritura: agregar un elemento AÑADE texto al final del archivo, así se conservan los comentarios y el orden que el
//! usuario escribió a mano. Editar o quitar sí reescribe la lista.

use super::enlaces;
use super::yaml;
use crate::kaggle_red::splitlines;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::path::Path;
use std::sync::LazyLock;
use unicode_normalization::UnicodeNormalization;

pub const FORMATO: i128 = 1;
pub const NIVELES: [&str; 3] = ["principiante", "intermedio", "avanzado"];
pub const MANIFIESTO: &str = "prig.yaml";
pub const MARCA_README: &str = "<!-- generado por Prig Hub: si lo editas a mano, borra esta línea y Prig no lo tocará -->";
pub static ID_VALIDO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-z0-9][a-z0-9_\-]{0,60}$").unwrap());
const MAX_ARCHIVO: u64 = 512 * 1024;
const MAX_ELEMENTOS: usize = 2000;
const LICENCIA_MIT: &str = "MIT License

Copyright (c) {anio} {autor}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
";

static NO_SLUG: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^a-z0-9]+").unwrap());
static SEPARA_ETIQUETAS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[,\s]+").unwrap());
static CABECERA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?s)^---\s*\n(.*?)\n---\s*(?:\n|$)(.*)$").unwrap());
static PASO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(?:[-*+]|\d+[.)])\s+(.*)$").unwrap());
static ENLACE_MD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\[([^\]]*)\]\(([^)\s]+)\)").unwrap());
pub static ARCHIVO_PY: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z_][A-Za-z0-9_]{0,40}\.py$").unwrap());

#[derive(Debug, Clone)]
pub struct ErrorFormato(pub String);

pub type Avisos = Vec<Valor>;

fn aviso(avisos: &mut Avisos, archivo: &str, mensaje: impl Into<String>) {
    avisos.push(Valor::Mapa(Mapa::new().con("archivo", archivo).con("mensaje", mensaje.into())));
}

// ============================================================================ utilidades

fn corto(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

/// `str.splitlines()`
pub fn lineas(t: &str) -> Vec<String> {
    splitlines(t)
        .into_iter()
        .map(|mut l| {
            if l.ends_with("\r\n") {
                l.truncate(l.len() - 2);
            } else if let Some(c) = l.chars().last() {
                if matches!(c, '\n' | '\r' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}') {
                    l.truncate(l.len() - c.len_utf8());
                }
            }
            l
        })
        .collect()
}

/// `str.strip("-")` y similares
fn quitar_guiones(t: &str) -> &str {
    t.trim_matches('-')
}

/// `slug(texto, maximo)`: NFKD, sin lo que no es ASCII, minúsculas y guiones
pub fn slug(texto: &str, maximo: usize) -> String {
    let t: String = texto.nfkd().filter(char::is_ascii).collect::<String>().to_lowercase();
    let t = NO_SLUG.replace_all(&t, "-");
    let t = quitar_guiones(&t);
    let t = quitar_guiones(&t[..t.len().min(maximo)]);
    if t.is_empty() { "sin-nombre".into() } else { t.into() }
}

/// `slug(v)` con `str(v or "")`
pub fn slug_valor(v: &Valor, maximo: usize) -> String {
    slug(&if v.verdad() { v.texto_py() } else { String::new() }, maximo)
}

/// `_leer_texto`: el texto de un archivo, o None (con aviso si existe pero no se puede leer)
fn leer_texto(ruta: &Path, avisos: &mut Avisos, nombre: &str) -> Option<String> {
    let md = match std::fs::metadata(ruta) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return None,
        Err(e) => {
            aviso(avisos, nombre, format!("No se pudo leer: {}", py::error_os(&e, &ruta.to_string_lossy())));
            return None;
        }
    };
    if md.len() > MAX_ARCHIVO {
        aviso(avisos, nombre, "Es demasiado grande (más de 512 KB): se ignora.");
        return None;
    }
    match py::leer_texto_estricto(&ruta.to_string_lossy()) {
        Ok(t) => Some(t),
        Err(e) if e.contains("[Errno 2]") => None,
        Err(e) => {
            aviso(avisos, nombre, format!("No se pudo leer: {e}"));
            None
        }
    }
}

/// `_yaml(texto, avisos, nombre)`: None si está mal escrito (con aviso)
pub fn leer_yaml(texto: &str, avisos: &mut Avisos, nombre: &str) -> Option<Valor> {
    match yaml::cargar(texto) {
        Ok(v) => Some(v),
        Err(e) => {
            let donde = e.linea.map(|l| format!(" (línea {l})")).unwrap_or_default();
            aviso(avisos, nombre, format!("YAML mal escrito{donde}: se ignora el archivo."));
            None
        }
    }
}

/// `_texto(v, maximo)`
pub fn texto(v: Option<&Valor>, maximo: usize) -> String {
    match v {
        None | Some(Valor::Nulo | Valor::Mapa(_) | Valor::Lista(_)) => String::new(),
        Some(v) => corto(py::strip(&v.texto_py()), maximo),
    }
}

fn texto_de(m: &Mapa, k: &str, maximo: usize) -> String {
    texto(m.get(k), maximo)
}

/// `_etiquetas(v)`
pub fn etiquetas(v: Option<&Valor>) -> Vec<Valor> {
    let lista: Vec<Valor> = match v {
        Some(Valor::Texto(t)) => SEPARA_ETIQUETAS.split(t).filter(|x| !x.is_empty()).map(|x| Valor::Texto(x.into())).collect(),
        Some(Valor::Lista(l)) => l.clone(),
        _ => return Vec::new(),
    };
    lista.iter().filter(|x| !texto(Some(x), 300).is_empty()).map(|x| Valor::Texto(slug_valor(x, 30))).take(20).collect()
}

/// `_nivel(v)`
pub fn nivel(v: Option<&Valor>) -> String {
    let n = texto(v, 300).to_lowercase();
    if NIVELES.contains(&n.as_str()) { n } else { String::new() }
}

pub fn es_nivel(n: &str) -> bool {
    NIVELES.contains(&n)
}

/// `capitalize()`
fn capitalizar(t: &str) -> String {
    let mut c = t.chars();
    match c.next() {
        Some(p) => p.to_uppercase().chain(c.flat_map(char::to_lowercase)).collect(),
        None => String::new(),
    }
}

/// `cabecera(texto)`: (datos de la cabecera YAML entre ---, cuerpo, error) de un Markdown
pub fn cabecera(texto: &str) -> (Mapa, String, Option<&'static str>) {
    let Some(m) = CABECERA.captures(texto) else { return (Mapa::new(), texto.to_string(), None) };
    let cuerpo = m[2].to_string();
    match yaml::cargar(&m[1]) {
        Ok(v) if !v.verdad() => (Mapa::new(), cuerpo, None),
        Ok(Valor::Mapa(d)) => (d, cuerpo, None),
        Ok(_) => (Mapa::new(), cuerpo, Some("La cabecera no es una lista de campos.")),
        Err(_) => (Mapa::new(), cuerpo, Some("La cabecera YAML está mal escrita.")),
    }
}

/// `v in (None, "", [], {})`
fn vacio(v: &Valor) -> bool {
    match v {
        Valor::Nulo => true,
        Valor::Texto(t) => t.is_empty(),
        Valor::Lista(l) => l.is_empty(),
        Valor::Mapa(m) => m.is_empty(),
        _ => false,
    }
}

pub fn con_cabecera(datos: &Mapa, cuerpo: &str) -> String {
    let mut limpios = Mapa::new();
    for (k, v) in datos.iter() {
        if !vacio(v) {
            limpios.poner(k.clone(), v.clone());
        }
    }
    format!("---\n{}\n---\n\n{}\n", py::strip(&yaml::volcar(&Valor::Mapa(limpios), 80)), py::strip(cuerpo))
}

// ============================================================================ lectura

fn es_int_py(v: &Valor) -> bool {
    matches!(v, Valor::Entero(_) | Valor::Bool(_))
}

fn como_entero(v: &Valor) -> i128 {
    match v {
        Valor::Entero(n) => *n,
        Valor::Bool(b) => *b as i128,
        _ => 0,
    }
}

pub fn leer_manifiesto(carpeta: &Path, avisos: &mut Avisos) -> Option<Mapa> {
    let texto_ = leer_texto(&carpeta.join(MANIFIESTO), avisos, MANIFIESTO)?;
    let datos = match leer_yaml(&texto_, avisos, MANIFIESTO)? {
        Valor::Mapa(d) => d,
        Valor::Nulo => return None,
        _ => {
            aviso(avisos, MANIFIESTO, "Debe ser una lista de campos (clave: valor).");
            return None;
        }
    };
    let mut formato = datos.valor("formato").clone();
    if !es_int_py(&formato) || como_entero(&formato) < 1 {
        aviso(avisos, MANIFIESTO, "Falta «formato: 1»; se lee como formato 1.");
        formato = Valor::Entero(1);
    } else if como_entero(&formato) > FORMATO {
        aviso(
            avisos,
            MANIFIESTO,
            format!("Lo creó una versión más nueva de Prig (formato {}); se lee lo que se entiende.", formato.texto_py()),
        );
    }
    let mut tipo = texto_de(&datos, "tipo", 300).to_lowercase();
    if tipo != "perfil" && tipo != "pack" {
        aviso(
            avisos,
            MANIFIESTO,
            format!("«tipo» debe ser perfil o pack (es «{}»); se trata como pack.", if tipo.is_empty() { "nada" } else { &tipo }),
        );
        tipo = "pack".into();
    }
    let autor = match datos.get("autor") {
        Some(Valor::Mapa(a)) => a.clone(),
        otro => Mapa::new().con("nombre", texto(otro, 300)),
    };
    let licencia = datos.mapa("licencia").cloned().unwrap_or_default();
    let titulo = texto_de(&datos, "titulo", 120);
    if titulo.is_empty() {
        aviso(avisos, MANIFIESTO, "Falta «titulo».");
    }
    let mut enlaces_ = Vec::new();
    if let Some(Valor::Lista(l)) = datos.get("enlaces") {
        for u in l {
            match enlaces::reconocer(&u.texto_py()) {
                Ok(i) => enlaces_.push(Valor::Mapa(i)),
                Err(_) => aviso(avisos, MANIFIESTO, format!("Enlace no válido en «enlaces»: {}", corto(&u.texto_py(), 80))),
            }
        }
    }
    let titulo = if titulo.is_empty() { py::basename(&py::abspath(&carpeta.to_string_lossy())) } else { titulo };
    Some(
        Mapa::new()
            .con("formato", formato)
            .con("tipo", tipo)
            .con("titulo", titulo)
            .con("descripcion", texto_de(&datos, "descripcion", 600))
            .con("autor", Mapa::new().con("nombre", texto_de(&autor, "nombre", 80)).con("github", texto_de(&autor, "github", 60)))
            .con("idioma", texto_de(&datos, "idioma", 10))
            .con("nivel", nivel(datos.get("nivel")))
            .con("etiquetas", Valor::Lista(etiquetas(datos.get("etiquetas"))))
            .con("version", texto_de(&datos, "version", 30))
            .con("licencia", Mapa::new().con("contenido", texto_de(&licencia, "contenido", 40)).con("codigo", texto_de(&licencia, "codigo", 40)))
            .con("enlaces", Valor::Lista(enlaces_)),
    )
}

/// `leer_lista`: personas.yaml, recursos.yaml o suscripciones.yaml: una lista de entradas con url
pub fn leer_lista(carpeta: &Path, nombre: &str, avisos: &mut Avisos, solo_personas: bool) -> Vec<Mapa> {
    let Some(texto_) = leer_texto(&carpeta.join(nombre), avisos, nombre) else { return Vec::new() };
    let datos = match leer_yaml(&texto_, avisos, nombre) {
        None | Some(Valor::Nulo) => return Vec::new(),
        Some(Valor::Lista(l)) => l,
        Some(_) => {
            aviso(avisos, nombre, "Debe ser una lista (cada entrada empieza por «- url: …»).");
            return Vec::new();
        }
    };
    let mut salida = Vec::new();
    let mut vistas = std::collections::HashSet::new();
    for (i, e) in datos.iter().take(MAX_ELEMENTOS).enumerate() {
        let i = i + 1;
        let e = match e {
            Valor::Texto(t) => Mapa::new().con("url", t.clone()),
            Valor::Mapa(m) => m.clone(),
            _ => Mapa::new(),
        };
        let url = texto_de(&e, "url", 2000);
        if url.is_empty() {
            aviso(avisos, nombre, format!("Entrada {i}: falta «url»; se salta."));
            continue;
        }
        let info = match enlaces::reconocer(&url) {
            Ok(x) => x,
            Err(err) => {
                aviso(avisos, nombre, format!("Entrada {i}: {err}"));
                continue;
            }
        };
        let tipo_info = enlaces::campo(&info, "tipo").to_string();
        let mut tipo = texto_de(&e, "tipo", 300).to_lowercase();
        if tipo.is_empty() {
            tipo = tipo_info.clone();
        }
        if !enlaces::es_tipo(&tipo) {
            aviso(avisos, nombre, format!("Entrada {i}: tipo «{tipo}» desconocido; se usa «{tipo_info}»."));
            tipo = tipo_info.clone();
        }
        if solo_personas {
            tipo = "persona".into();
        }
        let mut id = texto_de(&e, "id", 80);
        if !id.is_empty() && !ID_VALIDO.is_match(&id) {
            aviso(
                avisos,
                nombre,
                format!("Entrada {i}: id «{id}» no válido (minúsculas, números y guiones); se usa el del enlace."),
            );
            id.clear();
        }
        let clave = if id.is_empty() { enlaces::campo(&info, "clave").to_string() } else { format!("id:{id}") };
        if vistas.contains(&clave) {
            aviso(avisos, nombre, format!("Entrada {i}: repetida ({}); se salta.", enlaces::campo(&info, "url")));
            continue;
        }
        vistas.insert(clave.clone());
        let minutos = match e.get("minutos") {
            Some(v @ (Valor::Entero(_) | Valor::Bool(_) | Valor::Real(_))) => {
                let x = v.num().unwrap_or(0.0);
                if 0.0 < x && x < 100000.0 { Valor::Entero(v.entero().unwrap_or(0)) } else { Valor::Nulo }
            }
            _ => Valor::Nulo,
        };
        let miniatura = match e.get("miniatura") {
            Some(v) if v.verdad() => texto(Some(v), 500),
            _ => texto(e.get("imagen"), 500),
        };
        let mut x = info;
        x.poner("tipo", tipo);
        x.poner("clave", clave);
        x.poner("id", id);
        x.poner("titulo", texto_de(&e, "titulo", 200));
        x.poner("etiquetas", Valor::Lista(etiquetas(e.get("etiquetas"))));
        x.poner("nivel", nivel(e.get("nivel")));
        x.poner("nota", texto_de(&e, "nota", 1000));
        x.poner("minutos", minutos);
        x.poner("miniatura", miniatura);
        x.poner("playlist", texto_de(&e, "playlist", 100));
        salida.push(x);
    }
    salida
}

pub fn leer_ruta(texto_: &str, id: &str, nombre: &str, avisos: &mut Avisos) -> Mapa {
    let (datos, cuerpo, error) = cabecera(texto_);
    if let Some(e) = error {
        aviso(avisos, nombre, e);
    }
    let mut titulo = texto_de(&datos, "titulo", 150);
    if titulo.is_empty() {
        aviso(avisos, nombre, "Falta «titulo» en la cabecera; se usa el nombre del archivo.");
        titulo = capitalizar(&id.replace('-', " "));
    }
    struct P {
        texto: String,
        extra: Vec<String>,
    }
    let mut pasos: Vec<P> = Vec::new();
    let mut intro: Vec<String> = Vec::new();
    let mut actual = false;
    for linea in lineas(&cuerpo) {
        if let Some(m) = PASO.captures(&linea) {
            pasos.push(P { texto: py::strip(&m[1]).to_string(), extra: Vec::new() });
            actual = true;
        } else if actual && (linea.starts_with([' ', '\t']) || py::strip(&linea).is_empty()) {
            pasos.last_mut().unwrap().extra.push(py::strip(&linea).to_string());
        } else if !actual {
            intro.push(linea);
        } else {
            actual = false;
            intro.push(linea);
        }
    }
    let mut salida = Vec::new();
    for (i, p) in pasos.iter().enumerate() {
        let i = i + 1;
        let mut trozos = vec![p.texto.clone()];
        trozos.extend(p.extra.iter().filter(|x| !x.is_empty()).cloned());
        let t = py::strip(&trozos.join(" ")).to_string();
        let sin_enlaces = ENLACE_MD.replace_all(&t, "$1");
        let mut paso = Mapa::new().con("n", i as i128).con("texto", corto(&sin_enlaces, 600)).con("titulo", "").con("destino", Valor::Nulo);
        if let Some(e) = ENLACE_MD.captures(&t) {
            paso.poner("titulo", corto(py::strip(&e[1]), 200));
            let destino = py::strip(&e[2]).to_string();
            if let Some(did) = destino.strip_prefix("desafio:") {
                paso.poner("destino", Mapa::new().con("tipo", "desafio").con("id", did).con("clave", format!("desafio:{did}")));
            } else {
                match enlaces::reconocer(&destino) {
                    Ok(info) => paso.poner("destino", info),
                    Err(_) => aviso(avisos, nombre, format!("Paso {i}: el enlace «{}» no es válido.", corto(&destino, 80))),
                }
            }
        }
        salida.push(Valor::Mapa(paso));
    }
    if salida.is_empty() {
        aviso(avisos, nombre, "La ruta no tiene pasos (cada paso es un elemento de lista: «- [Título](enlace)»).");
    }
    Mapa::new()
        .con("id", id)
        .con("titulo", titulo)
        .con("descripcion", texto_de(&datos, "descripcion", 600))
        .con("nivel", nivel(datos.get("nivel")))
        .con("etiquetas", Valor::Lista(etiquetas(datos.get("etiquetas"))))
        .con("introduccion", corto(py::strip(&intro.join("\n")), 4000))
        .con("pasos", Valor::Lista(salida))
}

/// `sorted(os.listdir(carpeta))`
pub fn listar(carpeta: &Path) -> Vec<String> {
    let mut v: Vec<String> = match std::fs::read_dir(carpeta) {
        Ok(it) => it.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().into_owned()).collect(),
        Err(_) => Vec::new(),
    };
    v.sort();
    v
}

fn archivos_py(carpeta: &Path, avisos: &mut Avisos, nombre: &str) -> Vec<Valor> {
    let mut salida = Vec::new();
    if !carpeta.is_dir() {
        return salida;
    }
    for n in listar(carpeta) {
        let ruta = carpeta.join(&n);
        if !ruta.is_file() || ruta.is_symlink() {
            continue;
        }
        let donde = format!("{nombre}/{n}");
        if !ARCHIVO_PY.is_match(&n) {
            aviso(
                avisos,
                &donde,
                "Nombre de archivo no válido para una página (letras, números y _, terminado en .py); se ignora.",
            );
            continue;
        }
        if let Some(t) = leer_texto(&ruta, avisos, &donde) {
            salida.push(Valor::Mapa(Mapa::new().con("nombre", n).con("contenido", t)));
        }
    }
    salida
}

fn nombres(l: &[Valor]) -> Vec<String> {
    let mut v: Vec<String> = l.iter().map(|p| match p {
        Valor::Mapa(m) => m.texto("nombre").unwrap_or("").to_string(),
        _ => String::new(),
    }).collect();
    v.sort();
    v
}

pub fn leer_desafio(carpeta: &Path, id: &str, avisos: &mut Avisos) -> Option<Mapa> {
    let nombre = format!("desafios/{id}");
    let Some(texto_) = leer_texto(&carpeta.join("desafio.md"), avisos, &format!("{nombre}/desafio.md")) else {
        aviso(avisos, &nombre, "Falta desafio.md; se ignora el desafío.");
        return None;
    };
    let (datos, enunciado, error) = cabecera(&texto_);
    if let Some(e) = error {
        aviso(avisos, &format!("{nombre}/desafio.md"), e);
    }
    let inicio = archivos_py(&carpeta.join("inicio"), avisos, &format!("{nombre}/inicio"));
    let solucion = archivos_py(&carpeta.join("solucion"), avisos, &format!("{nombre}/solucion"));
    let pruebas = archivos_py(&carpeta.join("pruebas"), avisos, &format!("{nombre}/pruebas"));
    let mut problemas: Vec<String> = Vec::new();
    if inicio.is_empty() {
        problemas.push("no tiene código de partida (inicio/)".into());
    }
    if pruebas.is_empty() {
        problemas.push("no tiene pruebas (pruebas/)".into());
    }
    if solucion.is_empty() {
        problemas.push("no tiene solución de referencia (solucion/)".into());
    } else if nombres(&solucion) != nombres(&inicio) {
        problemas.push("solucion/ e inicio/ no tienen los mismos archivos".into());
    }
    let mut lenguaje = texto_de(&datos, "lenguaje", 300).to_lowercase();
    if lenguaje.is_empty() {
        lenguaje = "python".into();
    }
    if lenguaje != "python" {
        problemas.push(format!("lenguaje «{lenguaje}» todavía no se puede comprobar (solo python)"));
    }
    if !problemas.is_empty() {
        aviso(avisos, &nombre, format!("No se podrá verificar: {}.", problemas.join("; ")));
    }
    let mut titulo = texto_de(&datos, "titulo", 150);
    if titulo.is_empty() {
        titulo = capitalizar(&id.replace('-', " "));
    }
    let minutos = match datos.get("minutos") {
        Some(v @ (Valor::Entero(_) | Valor::Bool(_))) => v.clone(),
        _ => Valor::Nulo,
    };
    Some(
        Mapa::new()
            .con("id", id)
            .con("titulo", titulo)
            .con("nivel", nivel(datos.get("nivel")))
            .con("etiquetas", Valor::Lista(etiquetas(datos.get("etiquetas"))))
            .con("lenguaje", lenguaje)
            .con("minutos", minutos)
            .con("enunciado", corto(py::strip(&enunciado), 20000))
            .con("inicio", Valor::Lista(inicio))
            .con("solucion", Valor::Lista(solucion))
            .con("pruebas", Valor::Lista(pruebas))
            .con("verificable", problemas.is_empty()),
    )
}

fn lista_mapas(v: Vec<Mapa>) -> Valor {
    Valor::Lista(v.into_iter().map(Valor::Mapa).collect())
}

/// `leer_repo(carpeta)`: todo el contenido de un repositorio de Prig Hub, con los avisos de lo que no se entendió
pub fn leer_repo(carpeta: &Path) -> Result<Mapa, ErrorFormato> {
    let mut avisos: Avisos = Vec::new();
    let Some(manifiesto) = leer_manifiesto(carpeta, &mut avisos) else {
        let extra = match avisos.first() {
            Some(Valor::Mapa(a)) => format!(" {}", a.texto("mensaje").unwrap_or("")),
            _ => String::new(),
        };
        return Err(ErrorFormato(format!("No es un repositorio de Prig Hub: falta prig.yaml o no se puede leer.{extra}")));
    };
    let personas = leer_lista(carpeta, "personas.yaml", &mut avisos, true);
    let recursos = leer_lista(carpeta, "recursos.yaml", &mut avisos, false);
    for r in &recursos {
        if r.texto("tipo") == Some("persona") {
            aviso(&mut avisos, "recursos.yaml", format!("{} es una persona: mejor en personas.yaml.", r.texto("url").unwrap_or("")));
        }
    }
    let suscripciones =
        if manifiesto.texto("tipo") == Some("perfil") { leer_lista(carpeta, "suscripciones.yaml", &mut avisos, false) } else { Vec::new() };
    let mut rutas = Vec::new();
    let d_rutas = carpeta.join("rutas");
    if d_rutas.is_dir() {
        for n in listar(&d_rutas) {
            let Some(id) = n.strip_suffix(".md") else { continue };
            if !ID_VALIDO.is_match(id) {
                aviso(&mut avisos, &format!("rutas/{n}"), "Nombre de archivo no válido (minúsculas, números y guiones); se ignora.");
                continue;
            }
            if let Some(t) = leer_texto(&d_rutas.join(&n), &mut avisos, &format!("rutas/{n}")) {
                rutas.push(leer_ruta(&t, id, &format!("rutas/{n}"), &mut avisos));
            }
        }
    }
    let mut desafios = Vec::new();
    let d_des = carpeta.join("desafios");
    if d_des.is_dir() {
        for n in listar(&d_des) {
            let ruta = d_des.join(&n);
            if !ruta.is_dir() {
                continue;
            }
            if !ID_VALIDO.is_match(&n) {
                aviso(&mut avisos, &format!("desafios/{n}"), "Nombre de carpeta no válido; se ignora.");
                continue;
            }
            if let Some(d) = leer_desafio(&ruta, &n, &mut avisos) {
                desafios.push(d);
            }
        }
    }
    let ids: std::collections::HashSet<String> = desafios.iter().map(|d| d.texto("id").unwrap_or("").to_string()).collect();
    for r in &rutas {
        for p in r.lista("pasos").unwrap_or(&[]) {
            let Valor::Mapa(p) = p else { continue };
            if let Some(dest) = p.mapa("destino") {
                if dest.texto("tipo") == Some("desafio") && !ids.contains(dest.texto("id").unwrap_or("")) {
                    aviso(
                        &mut avisos,
                        &format!("rutas/{}.md", r.texto("id").unwrap_or("")),
                        format!("Paso {}: no existe el desafío «{}».", p.valor("n").texto_py(), dest.texto("id").unwrap_or("")),
                    );
                }
            }
        }
    }
    Ok(Mapa::new()
        .con("manifiesto", manifiesto)
        .con("personas", lista_mapas(personas))
        .con("recursos", lista_mapas(recursos))
        .con("suscripciones", lista_mapas(suscripciones))
        .con("rutas", lista_mapas(rutas))
        .con("desafios", lista_mapas(desafios))
        .con("avisos", Valor::Lista(avisos)))
}

// ============================================================================ escritura

/// `v in (None, "", [])`
fn vacio_entrada(v: &Valor) -> bool {
    match v {
        Valor::Nulo => true,
        Valor::Texto(t) => t.is_empty(),
        Valor::Lista(l) => l.is_empty(),
        _ => false,
    }
}

fn dump_entrada(e: &Mapa) -> String {
    let mut limpia = Mapa::new();
    for k in ["url", "titulo", "tipo", "etiquetas", "nivel", "minutos", "nota", "id"] {
        if let Some(v) = e.get(k) {
            if !vacio_entrada(v) {
                limpia.poner(k, v.clone());
            }
        }
    }
    yaml::volcar(&Valor::Lista(vec![Valor::Mapa(limpia)]), 100)
}

/// `_escribir(ruta, texto)`: de una vez (archivo temporal y renombrar)
pub fn escribir(ruta: &Path, texto: &str) -> Result<(), String> {
    if let Some(p) = ruta.parent() {
        py::makedirs(&p.to_string_lossy())?;
    }
    let tmp = format!("{}.tmp", ruta.display());
    py::escribir_texto(&tmp, texto)?;
    std::fs::rename(&tmp, ruta).map_err(|e| py::error_os(&e, &tmp))
}

#[derive(Debug)]
pub enum ErrorEscritura {
    Formato(ErrorFormato),
    Os(String),
}

impl From<String> for ErrorEscritura {
    fn from(e: String) -> Self {
        ErrorEscritura::Os(e)
    }
}

impl From<ErrorFormato> for ErrorEscritura {
    fn from(e: ErrorFormato) -> Self {
        ErrorEscritura::Formato(e)
    }
}

/// `agregar_entrada`: añade una entrada al final de una lista YAML sin reescribir lo que había
pub fn agregar_entrada(carpeta: &Path, nombre: &str, entrada: &Mapa) -> Result<(), ErrorEscritura> {
    let ruta = carpeta.join(nombre);
    let mut previo = String::new();
    if ruta.exists() {
        previo = py::leer_texto_estricto(&ruta.to_string_lossy())?;
        let datos = if py::strip(&previo).is_empty() {
            Valor::Lista(Vec::new())
        } else {
            yaml::cargar(&previo)
                .map_err(|_| ErrorFormato(format!("{nombre} tiene un error de escritura: arréglalo a mano antes de agregar.")))?
        };
        let nada = matches!(&datos, Valor::Nulo) || matches!(&datos, Valor::Lista(l) if l.is_empty());
        if !nada && !matches!(datos, Valor::Lista(_)) {
            return Err(ErrorFormato(format!("{nombre} no es una lista: arréglalo a mano antes de agregar.")).into());
        }
        if nada {
            // Lista vacía escrita como «[]»: se quita para poder seguir con «- url: …» (los comentarios quedan)
            previo = splitlines(&previo).into_iter().filter(|l| !matches!(py::strip(l), "[]" | "---")).collect();
        }
    }
    let separador = if previo.is_empty() || previo.ends_with('\n') { "" } else { "\n" };
    escribir(&ruta, &format!("{previo}{separador}{}", dump_entrada(entrada)))?;
    Ok(())
}

pub fn reescribir_lista(carpeta: &Path, nombre: &str, entradas: &[Mapa], cabecera_texto: &str) -> Result<(), String> {
    let texto_ = if entradas.is_empty() {
        format!("{cabecera_texto}[]\n")
    } else {
        format!("{cabecera_texto}{}", entradas.iter().map(dump_entrada).collect::<String>())
    };
    escribir(&carpeta.join(nombre), &texto_)
}

/// `entradas_crudas`: la lista tal como está en el YAML ([] si falta, está mal escrita o no es una lista)
pub fn entradas_crudas(carpeta: &Path, nombre: &str) -> Result<Vec<Valor>, String> {
    let ruta = carpeta.join(nombre);
    let t = match py::leer_texto_estricto(&ruta.to_string_lossy()) {
        Ok(t) => t,
        Err(e) if e.contains("[Errno 2]") => return Ok(Vec::new()),
        Err(e) => return Err(e),
    };
    Ok(match yaml::cargar(&t) {
        Ok(Valor::Lista(l)) => l,
        _ => Vec::new(),
    })
}

pub fn escribir_manifiesto(carpeta: &Path, datos: &Mapa) -> Result<(), String> {
    let mut limpio = Mapa::new();
    for k in ["formato", "tipo", "titulo", "descripcion", "autor", "idioma", "nivel", "etiquetas", "version", "licencia", "enlaces"] {
        let mut v = datos.valor(k).clone();
        if let Valor::Mapa(m) = &v {
            let mut f = Mapa::new();
            for (kk, vv) in m.iter() {
                if !vacio_entrada(vv) {
                    f.poner(kk.clone(), vv.clone());
                }
            }
            v = Valor::Mapa(f);
        }
        if !vacio(&v) {
            limpio.poner(k, v);
        }
    }
    let f = datos.valor("formato");
    limpio.poner("formato", if f.verdad() { f.clone() } else { Valor::Entero(FORMATO) });
    escribir(
        &carpeta.join(MANIFIESTO),
        &format!(
            "# Prig Hub · formato de repositorio: https://github.com/guillermopetcho/Prig-IDE/blob/main/docs/prig-hub.md\n{}",
            yaml::volcar(&Valor::Mapa(limpio), 100)
        ),
    )
}

#[allow(clippy::too_many_arguments)]
pub fn escribir_ruta(
    carpeta: &Path,
    id: &str,
    titulo: &str,
    pasos: &[Mapa],
    descripcion: &str,
    nivel_: &str,
    etiquetas_: Vec<Valor>,
    introduccion: &str,
) -> Result<(), ErrorEscritura> {
    if !ID_VALIDO.is_match(id) {
        return Err(ErrorFormato("Id de ruta no válido.".into()).into());
    }
    let mut lin = Vec::new();
    for p in pasos {
        let t = p.texto("titulo").unwrap_or("").replace(']', ")");
        let t = py::strip(&t);
        let t = if t.is_empty() { "Paso" } else { t };
        let destino = p.texto("destino").unwrap_or("");
        let nota = py::strip(p.texto("nota").unwrap_or(""));
        lin.push(format!("1. [{t}]({destino}){}", if nota.is_empty() { String::new() } else { format!(" — {nota}") }));
    }
    let intro = py::strip(introduccion);
    let cuerpo = format!("{}{}", if intro.is_empty() { String::new() } else { format!("{intro}\n\n") }, lin.join("\n"));
    let datos = Mapa::new().con("titulo", titulo).con("descripcion", descripcion).con("nivel", nivel_).con("etiquetas", Valor::Lista(etiquetas_));
    escribir(&carpeta.join("rutas").join(format!("{id}.md")), &con_cabecera(&datos, &cuerpo))?;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub fn escribir_desafio(
    carpeta: &Path,
    id: &str,
    titulo: &str,
    enunciado: &str,
    inicio: &[(String, String)],
    solucion: &[(String, String)],
    pruebas: &[(String, String)],
    nivel_: &str,
    etiquetas_: Vec<Valor>,
) -> Result<(), ErrorEscritura> {
    if !ID_VALIDO.is_match(id) {
        return Err(ErrorFormato("Id de desafío no válido.".into()).into());
    }
    let base = carpeta.join("desafios").join(id);
    let datos = Mapa::new().con("titulo", titulo).con("nivel", nivel_).con("etiquetas", Valor::Lista(etiquetas_)).con("lenguaje", "python");
    escribir(&base.join("desafio.md"), &con_cabecera(&datos, enunciado))?;
    for (sub, paginas) in [("inicio", inicio), ("solucion", solucion), ("pruebas", pruebas)] {
        for (n, c) in paginas {
            if !ARCHIVO_PY.is_match(n) {
                return Err(ErrorFormato(format!("Nombre de archivo no válido: {n}")).into());
            }
            escribir(&base.join(sub).join(n), c)?;
        }
    }
    Ok(())
}

fn anio() -> String {
    py::ahora_iso().chars().take(4).collect()
}

pub fn escribir_licencia(carpeta: &Path, autor: &str) -> Result<(), String> {
    let (contenido, codigo) = ("CC-BY-4.0", "MIT");
    let mut t = format!(
        "# Licencias\n\n- **Contenido** (listas, rutas y enunciados): [{contenido}](https://spdx.org/licenses/{contenido}.html). \
         Puedes compartirlo y adaptarlo citando la fuente.\n\
         - **Código** (`desafios/*/inicio`, `solucion` y `pruebas`): {codigo}, texto completo abajo.\n\n---\n\n"
    );
    t.push_str(&LICENCIA_MIT.replace("{anio}", &anio()).replace("{autor}", if autor.is_empty() { "los autores" } else { autor }));
    escribir(&carpeta.join("LICENSE.md"), &t)
}

fn icono(tipo: &str) -> &'static str {
    match tipo {
        "curso" => "🎓",
        "video" => "▶️",
        "lista" => "📺",
        "notebook" => "📓",
        "dataset" => "🗂️",
        "competicion" => "🏆",
        "repositorio" => "📦",
        "archivo" => "📄",
        "modelo" => "🧠",
        "articulo" => "📰",
        "ejercicio" => "🧩",
        "web" => "🔗",
        "persona" => "👤",
        _ => "🔗",
    }
}

fn mapas(v: &Mapa, k: &str) -> Vec<Mapa> {
    v.lista(k).unwrap_or(&[]).iter().filter_map(|x| if let Valor::Mapa(m) = x { Some(m.clone()) } else { None }).collect()
}

fn t<'a>(m: &'a Mapa, k: &str) -> &'a str {
    m.texto(k).unwrap_or("")
}

/// `x or y` entre textos
fn o<'a>(a: &'a str, b: &'a str) -> &'a str {
    if a.is_empty() { b } else { a }
}

/// `generar_readme`: portada del repositorio para quien lo mire en GitHub sin Prig. Solo reescribe un README que
/// lleve la marca de Prig (o que no exista).
pub fn generar_readme(carpeta: &Path, datos: &Mapa, url_repo: &str) -> Result<bool, String> {
    let ruta = carpeta.join("README.md");
    if ruta.exists() {
        let actual = py::leer_texto_estricto(&ruta.to_string_lossy())?;
        if !actual.contains(MARCA_README) {
            return Ok(false);
        }
    }
    let m = datos.mapa("manifiesto").cloned().unwrap_or_default();
    let mut lin: Vec<String> = vec![MARCA_README.into(), String::new(), format!("# {}", t(&m, "titulo")), String::new()];
    if !t(&m, "descripcion").is_empty() {
        lin.push(t(&m, "descripcion").into());
        lin.push(String::new());
    }
    let etiq: Vec<String> = m.lista("etiquetas").unwrap_or(&[]).iter().map(Valor::texto_py).collect();
    let version = if t(&m, "version").is_empty() { String::new() } else { format!("v{}", t(&m, "version")) };
    let meta: Vec<String> = [
        (if t(&m, "tipo") == "perfil" { "Perfil de Prig" } else { "Pack de Prig" }).to_string(),
        t(&m, "nivel").to_string(),
        version,
        etiq.join(", "),
    ]
    .into_iter()
    .filter(|x| !x.is_empty())
    .collect();
    lin.push(meta.join(" · "));
    lin.push(String::new());
    if !url_repo.is_empty() {
        lin.push(format!("> Ábrelo en [Prig IDE](https://github.com/guillermopetcho/Prig-IDE): **Prig Hub → Agregar enlace** → `{url_repo}`"));
        lin.push(String::new());
    }
    let enl = mapas(&m, "enlaces");
    if !enl.is_empty() {
        lin.extend(["## Dónde encontrarme".to_string(), String::new()]);
        lin.extend(enl.iter().map(|e| format!("- [{0}]({0})", t(e, "url"))));
        lin.push(String::new());
    }
    let rutas = mapas(datos, "rutas");
    if !rutas.is_empty() {
        lin.extend(["## Rutas".to_string(), String::new()]);
        for r in &rutas {
            let n = r.lista("pasos").map(|l| l.len()).unwrap_or(0);
            let d = t(r, "descripcion");
            lin.push(format!(
                "- [{}](rutas/{}.md) · {n} pasos{}",
                t(r, "titulo"),
                t(r, "id"),
                if d.is_empty() { String::new() } else { format!(" — {d}") }
            ));
        }
        lin.push(String::new());
    }
    let recursos = mapas(datos, "recursos");
    if !recursos.is_empty() {
        lin.extend(["## Recursos".to_string(), String::new()]);
        for e in &recursos {
            let nota = t(e, "nota");
            lin.push(format!(
                "- {} [{}]({}){}",
                icono(t(e, "tipo")),
                o(t(e, "titulo"), t(e, "url")),
                t(e, "url"),
                if nota.is_empty() { String::new() } else { format!(" — {nota}") }
            ));
        }
        lin.push(String::new());
    }
    let personas = mapas(datos, "personas");
    if !personas.is_empty() {
        lin.extend(["## Personas que sigo".to_string(), String::new()]);
        for e in &personas {
            lin.push(format!("- [{}]({}) · {}", o(t(e, "titulo"), t(e, "url")), t(e, "url"), enlaces::nombre_plataforma(t(e, "plataforma"))));
        }
        lin.push(String::new());
    }
    let desafios = mapas(datos, "desafios");
    if !desafios.is_empty() {
        lin.extend(["## Desafíos".to_string(), String::new()]);
        lin.extend(desafios.iter().map(|d| format!("- [{}](desafios/{}/desafio.md)", t(d, "titulo"), t(d, "id"))));
        lin.push(String::new());
    }
    let sus = mapas(datos, "suscripciones");
    if !sus.is_empty() {
        lin.extend(["## Sigo en Prig".to_string(), String::new()]);
        lin.extend(sus.iter().map(|s| format!("- [{}]({})", o(t(s, "titulo"), t(s, "url")), t(s, "url"))));
        lin.push(String::new());
    }
    lin.extend([
        "---".to_string(),
        String::new(),
        "Formato: [Prig Hub v1](https://github.com/guillermopetcho/Prig-IDE/blob/main/docs/prig-hub.md) · Licencias en [LICENSE.md](LICENSE.md)"
            .to_string(),
        String::new(),
    ]);
    escribir(&ruta, &lin.join("\n"))?;
    Ok(true)
}
