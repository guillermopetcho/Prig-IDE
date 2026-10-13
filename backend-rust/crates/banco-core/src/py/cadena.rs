//! Los métodos de `str` de Python que usa el banco, con su semántica exacta: Python cuenta y corta por
//! caracteres (no bytes), `splitlines` corta en más separadores que `\n` y `isspace` incluye \x1c-\x1f.
//! Cada diferencia con la versión «natural» de Rust cambiaría líneas, firmas o resúmenes del banco.

use unicode_general_category::{get_general_category, GeneralCategory as G};

/// `str.isspace()` de un carácter: la propiedad White_Space de Unicode más \x1c-\x1f (separadores de
/// archivo, grupo, registro y unidad, que Python también considera espacio).
pub fn es_espacio(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.isalpha()` de un carácter: categorías L* (Lu, Ll, Lt, Lm, Lo).
pub fn es_letra(c: char) -> bool {
    matches!(
        get_general_category(c),
        G::UppercaseLetter | G::LowercaseLetter | G::TitlecaseLetter | G::ModifierLetter | G::OtherLetter
    )
}

/// `str.isdecimal()` de un carácter (Nd).
pub fn es_decimal(c: char) -> bool {
    matches!(get_general_category(c), G::DecimalNumber)
}

/// `str.isnumeric()` aproximado por las categorías N* (Nd, Nl, No).
pub fn es_numerico(c: char) -> bool {
    matches!(get_general_category(c), G::DecimalNumber | G::LetterNumber | G::OtherNumber)
}

/// `str.isalnum()` de un carácter.
pub fn es_alnum(c: char) -> bool {
    es_letra(c) || es_numerico(c)
}

/// `\w` de las expresiones de Python sobre str: alfanumérico o «_».
pub fn es_palabra(c: char) -> bool {
    c == '_' || es_alnum(c)
}

/// `str.isprintable()` de un carácter: no lo es lo de las categorías Cc, Cf, Cs, Co, Cn, Zl, Zp y Zs
/// (salvo el espacio).
pub fn es_imprimible(c: char) -> bool {
    if c == ' ' {
        return true;
    }
    !matches!(
        get_general_category(c),
        G::Control
            | G::Format
            | G::Surrogate
            | G::PrivateUse
            | G::Unassigned
            | G::LineSeparator
            | G::ParagraphSeparator
            | G::SpaceSeparator
    )
}

/// `str.isupper()` de un texto: hay al menos una letra con caja y todas son mayúsculas.
pub fn es_mayuscula(s: &str) -> bool {
    let mut alguna = false;
    for c in s.chars() {
        if c.is_lowercase() || get_general_category(c) == G::TitlecaseLetter {
            return false;
        }
        if c.is_uppercase() {
            alguna = true;
        }
    }
    alguna
}

/// `str.isalpha()` de un texto (no vacío y todo letras).
pub fn es_alfabetico(s: &str) -> bool {
    !s.is_empty() && s.chars().all(es_letra)
}

/// `len(s)`: caracteres, no bytes.
pub fn largo(s: &str) -> usize {
    s.chars().count()
}

/// Índice de byte del carácter número `n` (o el final del texto).
pub fn byte_de(s: &str, n: usize) -> usize {
    s.char_indices().nth(n).map(|(i, _)| i).unwrap_or(s.len())
}

/// `s[:n]` por caracteres.
pub fn primeros(s: &str, n: usize) -> &str {
    &s[..byte_de(s, n)]
}

/// `s[n:]` por caracteres.
pub fn desde(s: &str, n: usize) -> &str {
    &s[byte_de(s, n)..]
}

/// `s[a:b]` por caracteres (sin índices negativos).
pub fn tramo(s: &str, a: usize, b: usize) -> &str {
    if b <= a {
        return "";
    }
    let ia = byte_de(s, a);
    let resto = &s[ia..];
    &resto[..byte_de(resto, b - a)]
}

/// `s[:-1]` y compañía: los últimos `n` caracteres fuera.
pub fn sin_ultimos(s: &str, n: usize) -> &str {
    let total = largo(s);
    primeros(s, total.saturating_sub(n))
}

/// `str.splitlines()`: corta en \n, \r, \r\n, \v, \f, \x1c, \x1d, \x1e, \x85,   y  ; sin la línea
/// vacía final.
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut salida = Vec::new();
    let mut inicio = 0;
    let bytes = s.as_bytes();
    let mut iter = s.char_indices().peekable();
    while let Some((i, c)) = iter.next() {
        match c {
            '\n' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}' => {
                salida.push(&s[inicio..i]);
                inicio = i + c.len_utf8();
            }
            '\r' => {
                salida.push(&s[inicio..i]);
                if i + 1 < bytes.len() && bytes[i + 1] == b'\n' {
                    iter.next();
                    inicio = i + 2;
                } else {
                    inicio = i + 1;
                }
            }
            _ => {}
        }
    }
    if inicio < s.len() {
        salida.push(&s[inicio..]);
    }
    salida
}

/// `str.strip()` sin argumentos.
pub fn strip(s: &str) -> &str {
    s.trim_matches(es_espacio)
}

/// `str.lstrip()` sin argumentos.
pub fn lstrip(s: &str) -> &str {
    s.trim_start_matches(es_espacio)
}

/// `str.rstrip()` sin argumentos.
pub fn rstrip(s: &str) -> &str {
    s.trim_end_matches(es_espacio)
}

/// `str.strip(chars)`.
pub fn strip_de<'a>(s: &'a str, chars: &str) -> &'a str {
    s.trim_matches(|c| chars.contains(c))
}

/// `str.lstrip(chars)`.
pub fn lstrip_de<'a>(s: &'a str, chars: &str) -> &'a str {
    s.trim_start_matches(|c| chars.contains(c))
}

/// `str.rstrip(chars)`.
pub fn rstrip_de<'a>(s: &'a str, chars: &str) -> &'a str {
    s.trim_end_matches(|c| chars.contains(c))
}

/// `str.split()` sin argumentos: por tramos de espacio, sin vacíos.
pub fn split_espacios(s: &str) -> Vec<&str> {
    s.split(es_espacio).filter(|p| !p.is_empty()).collect()
}

/// `s.rsplit(sep, 1)`: [antes, después] o [s] si no aparece.
pub fn rsplit1<'a>(s: &'a str, sep: &str) -> Vec<&'a str> {
    match s.rfind(sep) {
        Some(i) => vec![&s[..i], &s[i + sep.len()..]],
        None => vec![s],
    }
}

/// `s.split(sep, 1)`.
pub fn split1<'a>(s: &'a str, sep: &str) -> Vec<&'a str> {
    match s.find(sep) {
        Some(i) => vec![&s[..i], &s[i + sep.len()..]],
        None => vec![s],
    }
}

/// `s.split(sep, 1)[-1]`: lo que sigue al primer separador, o todo.
pub fn tras_primero<'a>(s: &'a str, sep: &str) -> &'a str {
    match s.find(sep) {
        Some(i) => &s[i + sep.len()..],
        None => s,
    }
}

/// `s.split(sep)[-1]`.
pub fn ultimo_trozo<'a>(s: &'a str, sep: &str) -> &'a str {
    match s.rfind(sep) {
        Some(i) => &s[i + sep.len()..],
        None => s,
    }
}

/// `s.split(sep)[0]`.
pub fn primer_trozo<'a>(s: &'a str, sep: &str) -> &'a str {
    match s.find(sep) {
        Some(i) => &s[..i],
        None => s,
    }
}

/// `str.partition(sep)`.
pub fn partition<'a>(s: &'a str, sep: &str) -> (&'a str, &'a str, &'a str) {
    match s.find(sep) {
        Some(i) => (&s[..i], &s[i..i + sep.len()], &s[i + sep.len()..]),
        None => (s, "", ""),
    }
}

/// `str.rfind(sub)` en caracteres (-1 si no está).
pub fn rfind_car(s: &str, sub: &str) -> isize {
    match s.rfind(sub) {
        Some(b) => largo(&s[..b]) as isize,
        None => -1,
    }
}

/// `str.expandtabs(8)`: la columna vuelve a cero en \n y \r.
pub fn expandtabs(s: &str) -> String {
    let mut salida = String::with_capacity(s.len());
    let mut columna = 0usize;
    for c in s.chars() {
        match c {
            '\t' => {
                let n = 8 - (columna % 8);
                for _ in 0..n {
                    salida.push(' ');
                }
                columna += n;
            }
            '\n' | '\r' => {
                salida.push(c);
                columna = 0;
            }
            _ => {
                salida.push(c);
                columna += 1;
            }
        }
    }
    salida
}

/// `str.lower()`.
pub fn lower(s: &str) -> String {
    s.to_lowercase()
}

/// `str.upper()`.
pub fn upper(s: &str) -> String {
    s.to_uppercase()
}

/// `inspect.cleandoc` de Python 3.12.
pub fn cleandoc(doc: &str) -> String {
    let expandido = expandtabs(doc);
    let mut lineas: Vec<String> = expandido.split('\n').map(|l| l.to_string()).collect();
    let mut margen = usize::MAX;
    for linea in lineas.iter().skip(1) {
        let contenido = largo(lstrip(linea));
        if contenido > 0 {
            let sangria = largo(linea) - contenido;
            margen = margen.min(sangria);
        }
    }
    if !lineas.is_empty() {
        lineas[0] = lstrip(&lineas[0]).to_string();
    }
    if margen < usize::MAX {
        for linea in lineas.iter_mut().skip(1) {
            *linea = desde(linea, margen).to_string();
        }
    }
    while lineas.last().map(|l| l.is_empty()).unwrap_or(false) {
        lineas.pop();
    }
    while lineas.first().map(|l| l.is_empty()).unwrap_or(false) {
        lineas.remove(0);
    }
    lineas.join("\n")
}

/// `repr(str)` de Python: comillas simples salvo que haya ' y no ", escapes de \\, \n, \r, \t y de lo no
/// imprimible (\xNN, \uNNNN, \UNNNNNNNN).
pub fn repr_str(s: &str) -> String {
    let comilla = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut salida = String::with_capacity(s.len() + 2);
    salida.push(comilla);
    for c in s.chars() {
        if c == comilla || c == '\\' {
            salida.push('\\');
            salida.push(c);
        } else if c == '\t' {
            salida.push_str("\\t");
        } else if c == '\n' {
            salida.push_str("\\n");
        } else if c == '\r' {
            salida.push_str("\\r");
        } else if (c as u32) < 0x20 || c as u32 == 0x7f {
            salida.push_str(&format!("\\x{:02x}", c as u32));
        } else if (c as u32) < 0x7f {
            salida.push(c);
        } else if es_imprimible(c) {
            salida.push(c);
        } else {
            let n = c as u32;
            if n <= 0xff {
                salida.push_str(&format!("\\x{:02x}", n));
            } else if n <= 0xffff {
                salida.push_str(&format!("\\u{:04x}", n));
            } else {
                salida.push_str(&format!("\\U{:08x}", n));
            }
        }
    }
    salida.push(comilla);
    salida
}

/// `repr(bytes)` de Python.
pub fn repr_bytes(b: &[u8]) -> String {
    let comilla = if b.contains(&b'\'') && !b.contains(&b'"') { b'"' } else { b'\'' };
    let mut salida = String::from("b");
    salida.push(comilla as char);
    for &x in b {
        if x == comilla || x == b'\\' {
            salida.push('\\');
            salida.push(x as char);
        } else if x == b'\t' {
            salida.push_str("\\t");
        } else if x == b'\n' {
            salida.push_str("\\n");
        } else if x == b'\r' {
            salida.push_str("\\r");
        } else if !(0x20..0x7f).contains(&x) {
            salida.push_str(&format!("\\x{:02x}", x));
        } else {
            salida.push(x as char);
        }
    }
    salida.push(comilla as char);
    salida
}

/// `c.encode("unicode_escape").decode("ascii")` para un carácter (lo usa el unparse de cadenas).
pub fn unicode_escape(c: char) -> String {
    let n = c as u32;
    match c {
        '\\' => "\\\\".to_string(),
        '\t' => "\\t".to_string(),
        '\n' => "\\n".to_string(),
        '\r' => "\\r".to_string(),
        _ if (0x20..0x7f).contains(&n) => c.to_string(),
        _ if n < 0x100 => format!("\\x{:02x}", n),
        _ if n < 0x10000 => format!("\\u{:04x}", n),
        _ => format!("\\U{:08x}", n),
    }
}

/// `"{:>ancho}".format(n)` para enteros (lo usan los números de línea).
pub fn derecha(n: i64, ancho: usize) -> String {
    format!("{:>ancho$}", n, ancho = ancho)
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn splitlines_como_python() {
        assert_eq!(splitlines("a\x0cb\x1cc\u{85}d\u{2028}e\x0bf\rg\r\nh"), vec!["a", "b", "c", "d", "e", "f", "g", "h"]);
        assert_eq!(splitlines("\n"), vec![""]);
        assert_eq!(splitlines("a\n"), vec!["a"]);
        assert!(splitlines("").is_empty());
    }

    #[test]
    fn cleandoc_como_python() {
        assert_eq!(cleandoc("  Hola.\n\n    Más texto\n      sangrado\n  "), "Hola.\n\nMás texto\n  sangrado");
    }

    #[test]
    fn repr_como_python() {
        assert_eq!(repr_str("it's"), "\"it's\"");
        assert_eq!(repr_str("a\"b'c"), "'a\"b\\'c'");
        assert_eq!(repr_str("ñ\u{200b}\x07"), "'ñ\\u200b\\x07'");
    }
}
