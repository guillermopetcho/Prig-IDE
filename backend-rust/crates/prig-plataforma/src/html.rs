//! `html.unescape` de Python: referencias numéricas (con la tabla de Python para las inválidas) y las 2231
//! entidades de HTML5, también las que se admiten sin «;» (`&amp` → `&`). La tabla sale del propio Python.

use crate::valor::Valor;
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

struct Tablas {
    html5: HashMap<String, String>,
    invalidas: HashMap<u32, String>,
    sin_codigo: HashSet<u32>,
}

fn tablas() -> &'static Tablas {
    static T: OnceLock<Tablas> = OnceLock::new();
    T.get_or_init(|| {
        let Ok(Valor::Mapa(m)) = crate::json::leer(include_str!("html_entidades.json")) else { panic!("entidades HTML") };
        let html5 = m.mapa("html5").map(|x| x.iter().map(|(k, v)| (k.clone(), v.texto_py())).collect()).unwrap_or_default();
        let invalidas = m
            .mapa("invalid_charrefs")
            .map(|x| x.iter().filter_map(|(k, v)| Some((k.parse().ok()?, v.texto_py()))).collect())
            .unwrap_or_default();
        let sin_codigo =
            m.lista("invalid_codepoints").map(|l| l.iter().filter_map(|v| v.entero().map(|n| n as u32)).collect()).unwrap_or_default();
        Tablas { html5, invalidas, sin_codigo }
    })
}

/// Lo que viene después de «&» y casa con `#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?`: su largo en bytes
fn referencia(s: &str) -> Option<usize> {
    let b = s.as_bytes();
    if b.first() == Some(&b'#') {
        let (ini, hex) = if matches!(b.get(1), Some(b'x' | b'X')) { (2, true) } else { (1, false) };
        let mut i = ini;
        while i < b.len() && (if hex { b[i].is_ascii_hexdigit() } else { b[i].is_ascii_digit() }) {
            i += 1;
        }
        if i == ini {
            return None;
        }
        if b.get(i) == Some(&b';') {
            i += 1;
        }
        return Some(i);
    }
    let mut n = 0;
    let mut fin = 0;
    for (i, c) in s.char_indices() {
        if n == 32 || matches!(c, '\t' | '\n' | '\x0c' | ' ' | '<' | '&' | '#' | ';') {
            break;
        }
        n += 1;
        fin = i + c.len_utf8();
    }
    if n == 0 {
        return None;
    }
    if s[fin..].starts_with(';') {
        fin += 1;
    }
    Some(fin)
}

fn reemplazo(s: &str) -> String {
    let t = tablas();
    if let Some(num) = s.strip_prefix('#') {
        let num = num.trim_end_matches(';');
        let n = if let Some(h) = num.strip_prefix(['x', 'X']) { u64::from_str_radix(h, 16) } else { num.parse::<u64>() };
        let n = n.unwrap_or(u64::MAX);
        if n <= u32::MAX as u64 {
            if let Some(r) = t.invalidas.get(&(n as u32)) {
                return r.clone();
            }
        }
        if (0xD800..=0xDFFF).contains(&n) || n > 0x10FFFF {
            return "\u{FFFD}".into();
        }
        if t.sin_codigo.contains(&(n as u32)) {
            return String::new();
        }
        return char::from_u32(n as u32).map(String::from).unwrap_or_else(|| "\u{FFFD}".into());
    }
    if let Some(r) = t.html5.get(s) {
        return r.clone();
    }
    // la entidad más larga sin «;» que esté al principio (`&ampx` → `&x`)
    let limites: Vec<usize> = s.char_indices().map(|(i, _)| i).skip(2).collect();
    for &x in limites.iter().rev() {
        if let Some(r) = t.html5.get(&s[..x]) {
            return format!("{r}{}", &s[x..]);
        }
    }
    format!("&{s}")
}

/// `html.unescape(s)`
pub fn unescape(s: &str) -> String {
    if !s.contains('&') {
        return s.to_string();
    }
    let mut salida = String::with_capacity(s.len());
    let mut resto = s;
    while let Some(i) = resto.find('&') {
        salida.push_str(&resto[..i]);
        let tras = &resto[i + 1..];
        match referencia(tras) {
            Some(n) => {
                salida.push_str(&reemplazo(&tras[..n]));
                resto = &tras[n..];
            }
            None => {
                salida.push('&');
                resto = tras;
            }
        }
    }
    salida.push_str(resto);
    salida
}
