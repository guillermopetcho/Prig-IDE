//! Expresiones de Python en Rust. Se copian tal cual de Python y se traducen al compilar:
//!   · `\s` es el espacio de Python (incluye \x1c-\x1f) y `\w` su palabra (letras y números de Unicode y «_»);
//!   · con «mirar adelante/atrás» ((?=, (?!, (?<=, (?<!) se usa fancy-regex; si no, regex (más rápido);
//!   · `re.match` se ancla al principio sin cambiar la alternativa que gana.

use std::borrow::Cow;

/// Traduce la sintaxis de Python a la de Rust para `\s`, `\S`, `\w` y `\W`.
pub fn traducir(patron: &str) -> String {
    let mut salida = String::with_capacity(patron.len() + 16);
    let mut en_clase = false;
    let mut chars = patron.chars().peekable();
    let mut primero_en_clase = false;
    while let Some(c) = chars.next() {
        if c == '\\' {
            let Some(n) = chars.next() else {
                salida.push('\\');
                break;
            };
            match (n, en_clase) {
                ('s', false) => salida.push_str(r"[\s\x1c-\x1f]"),
                ('s', true) => salida.push_str(r"\s\x1c-\x1f"),
                ('S', false) => salida.push_str(r"[^\s\x1c-\x1f]"),
                ('w', false) => salida.push_str(r"[\p{L}\p{N}_]"),
                ('w', true) => salida.push_str(r"\p{L}\p{N}_"),
                ('W', false) => salida.push_str(r"[^\p{L}\p{N}_]"),
                _ => {
                    salida.push('\\');
                    salida.push(n);
                }
            }
            primero_en_clase = false;
            continue;
        }
        if en_clase {
            if c == ']' && !primero_en_clase {
                en_clase = false;
            }
            primero_en_clase = false;
            salida.push(c);
            continue;
        }
        if c == '[' {
            en_clase = true;
            primero_en_clase = true;
            salida.push(c);
            if chars.peek() == Some(&'^') {
                salida.push(chars.next().unwrap());
            }
            continue;
        }
        salida.push(c);
    }
    salida
}

fn necesita_fancy(patron: &str) -> bool {
    patron.contains("(?=") || patron.contains("(?!") || patron.contains("(?<=") || patron.contains("(?<!") || patron.contains("\\1")
}

/// Una expresión compilada (regex o fancy-regex).
#[derive(Clone, Debug)]
pub enum Re {
    Simple(regex::Regex),
    Fancy(fancy_regex::Regex),
}

/// Un acierto: tramo total y grupos (por bytes).
#[derive(Clone, Debug)]
pub struct Acierto<'t> {
    pub texto: &'t str,
    pub inicio: usize,
    pub fin: usize,
    grupos: Vec<Option<(usize, usize)>>,
}

impl<'t> Acierto<'t> {
    pub fn todo(&self) -> &'t str {
        &self.texto[self.inicio..self.fin]
    }

    /// `m.group(n)` (None si el grupo no participó).
    pub fn grupo(&self, n: usize) -> Option<&'t str> {
        self.grupos.get(n).copied().flatten().map(|(a, b)| &self.texto[a..b])
    }

    /// `m.group(n) or ""`.
    pub fn g(&self, n: usize) -> &'t str {
        self.grupo(n).unwrap_or("")
    }
}

impl Re {
    /// Compila un patrón con la sintaxis de Python. `banderas`: "i", "m", "s" (re.I, re.M, re.S).
    pub fn nuevo(patron: &str, banderas: &str) -> Re {
        Self::intentar(patron, banderas).unwrap_or_else(|e| panic!("expresión inválida {patron:?}: {e}"))
    }

    pub fn intentar(patron: &str, banderas: &str) -> Result<Re, String> {
        let mut p = traducir(patron);
        if !banderas.is_empty() {
            p = format!("(?{banderas}){p}");
        }
        if necesita_fancy(patron) {
            // El tope de retroceso por defecto (1 millón) puede cortar líneas muy largas donde `re` de Python sigue
            fancy_regex::RegexBuilder::new(&p).backtrack_limit(200_000_000).build().map(Re::Fancy).map_err(|e| e.to_string())
        } else {
            regex::Regex::new(&p).map(Re::Simple).map_err(|e| e.to_string())
        }
    }

    /// `re.escape`: el texto literal, escapado para la sintaxis de Rust (lo que casa es lo mismo).
    pub fn escapar(s: &str) -> String {
        regex::escape(s)
    }

    fn convertir<'t>(texto: &'t str, caps: &regex::Captures<'t>) -> Acierto<'t> {
        let m = caps.get(0).unwrap();
        Acierto { texto, inicio: m.start(), fin: m.end(), grupos: (0..caps.len()).map(|i| caps.get(i).map(|g| (g.start(), g.end()))).collect() }
    }

    fn convertir_f<'t>(texto: &'t str, caps: &fancy_regex::Captures<'t, str>) -> Acierto<'t> {
        let m = caps.get(0).unwrap();
        Acierto { texto, inicio: m.start(), fin: m.end(), grupos: (0..caps.len()).map(|i| caps.get(i).map(|g| (g.start(), g.end()))).collect() }
    }

    /// `re.search`.
    pub fn buscar<'t>(&self, texto: &'t str) -> Option<Acierto<'t>> {
        match self {
            Re::Simple(r) => r.captures(texto).map(|c| Self::convertir(texto, &c)),
            Re::Fancy(r) => r.captures(texto).ok().flatten().map(|c| Self::convertir_f(texto, &c)),
        }
    }

    /// `bool(re.search(...))`.
    pub fn hay(&self, texto: &str) -> bool {
        match self {
            Re::Simple(r) => r.is_match(texto),
            Re::Fancy(r) => r.is_match(texto).unwrap_or(false),
        }
    }

    /// `re.finditer`: los aciertos sin solaparse, de izquierda a derecha.
    pub fn todos<'t>(&self, texto: &'t str) -> Vec<Acierto<'t>> {
        match self {
            Re::Simple(r) => r.captures_iter(texto).map(|c| Self::convertir(texto, &c)).collect(),
            Re::Fancy(r) => r.captures_iter(texto).filter_map(|c| c.ok()).map(|c| Self::convertir_f(texto, &c)).collect(),
        }
    }

    /// `re.findall` con un grupo: el grupo 1 de cada acierto ("" si no participó).
    pub fn findall1<'t>(&self, texto: &'t str) -> Vec<&'t str> {
        self.todos(texto).into_iter().map(|a| a.g(1)).collect()
    }

    /// `re.findall` sin grupos: el texto de cada acierto.
    pub fn findall0<'t>(&self, texto: &'t str) -> Vec<&'t str> {
        match self {
            Re::Simple(r) => r.find_iter(texto).map(|m| m.as_str()).collect(),
            Re::Fancy(r) => r.find_iter(texto).filter_map(|m| m.ok()).map(|m| m.as_str()).collect(),
        }
    }

    /// `re.sub(patron, reemplazo_literal, texto)` (el reemplazo sin grupos).
    pub fn sub<'t>(&self, reemplazo: &str, texto: &'t str) -> Cow<'t, str> {
        match self {
            Re::Simple(r) => r.replace_all(texto, regex::NoExpand(reemplazo)),
            Re::Fancy(r) => r.replace_all(texto, fancy_regex::NoExpand(reemplazo)),
        }
    }
}


static CACHE: std::sync::LazyLock<std::sync::Mutex<std::collections::HashMap<(String, String), Re>>> =
    std::sync::LazyLock::new(|| std::sync::Mutex::new(std::collections::HashMap::new()));

impl Re {
    /// Como `re.compile` con su caché: las expresiones que se arman por consulta no se recompilan.
    pub fn cache(patron: &str, banderas: &str) -> Re {
        let clave = (patron.to_string(), banderas.to_string());
        if let Some(r) = CACHE.lock().unwrap().get(&clave) {
            return r.clone();
        }
        let r = Re::nuevo(patron, banderas);
        let mut c = CACHE.lock().unwrap();
        if c.len() > 2000 {
            c.clear();
        }
        c.insert(clave, r.clone());
        r
    }
}

/// Una expresión para `re.match`: la misma, anclada al principio.
#[derive(Clone, Debug)]
pub struct ReInicio(Re);

impl ReInicio {
    pub fn nuevo(patron: &str, banderas: &str) -> ReInicio {
        ReInicio(Re::nuevo(&format!(r"\A(?:{patron})"), banderas))
    }

    pub fn coincide<'t>(&self, texto: &'t str) -> Option<Acierto<'t>> {
        self.0.buscar(texto)
    }

    pub fn hay(&self, texto: &str) -> bool {
        self.0.hay(texto)
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn traduce() {
        assert_eq!(traducir(r"\s*[\w$]+"), r"[\s\x1c-\x1f]*[\p{L}\p{N}_$]+");
        let r = Re::nuevo(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", "");
        assert_eq!(r.findall0("HTTPServer2xEsto"), vec!["HTTP", "Server", "2", "x", "Esto"]);
        assert!(Re::nuevo(&Re::escapar("a.b_c-d #&~"), "").hay("x a.b_c-d #&~ y"));
    }
}
