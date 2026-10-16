//! JSON como el módulo `json` de Python, para los archivos que Prig comparte con su backend de Python: se lee lo que
//! acepta `json.load` (también `NaN` e `Infinity`, que Python escribe si le llega uno) y se escribe exactamente lo
//! que escribe `json.dump(datos, f, ensure_ascii=False, indent=n)`, byte a byte. Así un archivo puede pasar de un
//! lado a otro sin cambiar.

use crate::valor::{repr_real, Mapa, Valor};

// =========================================================================== escribir

/// `json.dumps(v, ensure_ascii=False, indent=sangria)`
pub fn escribir(v: &Valor, sangria: usize) -> String {
    let mut s = String::new();
    valor(&mut s, v, sangria, 0);
    s
}

fn texto(s: &mut String, t: &str) {
    s.push('"');
    for c in t.chars() {
        match c {
            '\\' => s.push_str("\\\\"),
            '"' => s.push_str("\\\""),
            '\n' => s.push_str("\\n"),
            '\r' => s.push_str("\\r"),
            '\t' => s.push_str("\\t"),
            '\u{8}' => s.push_str("\\b"),
            '\u{c}' => s.push_str("\\f"),
            c if (c as u32) < 0x20 => s.push_str(&format!("\\u{:04x}", c as u32)),
            c => s.push(c),
        }
    }
    s.push('"');
}

fn real(x: f64) -> String {
    if x.is_nan() {
        "NaN".into()
    } else if x.is_infinite() {
        if x > 0.0 { "Infinity" } else { "-Infinity" }.into()
    } else {
        repr_real(x)
    }
}

fn valor(s: &mut String, v: &Valor, sangria: usize, nivel: usize) {
    match v {
        Valor::Nulo => s.push_str("null"),
        Valor::Bool(true) => s.push_str("true"),
        Valor::Bool(false) => s.push_str("false"),
        Valor::Entero(n) => s.push_str(&n.to_string()),
        Valor::Real(x) => s.push_str(&real(*x)),
        Valor::Texto(t) => texto(s, t),
        Valor::Lista(l) => {
            if l.is_empty() {
                s.push_str("[]");
                return;
            }
            let dentro = format!("\n{}", " ".repeat(sangria * (nivel + 1)));
            s.push('[');
            for (i, x) in l.iter().enumerate() {
                if i > 0 {
                    s.push(',');
                }
                s.push_str(&dentro);
                valor(s, x, sangria, nivel + 1);
            }
            s.push('\n');
            s.push_str(&" ".repeat(sangria * nivel));
            s.push(']');
        }
        Valor::Mapa(m) => {
            if m.is_empty() {
                s.push_str("{}");
                return;
            }
            let dentro = format!("\n{}", " ".repeat(sangria * (nivel + 1)));
            s.push('{');
            for (i, (k, x)) in m.iter().enumerate() {
                if i > 0 {
                    s.push(',');
                }
                s.push_str(&dentro);
                texto(s, k);
                s.push_str(": ");
                valor(s, x, sangria, nivel + 1);
            }
            s.push('\n');
            s.push_str(&" ".repeat(sangria * nivel));
            s.push('}');
        }
    }
}

/// `json.dumps(v, ensure_ascii=False)`: en una línea, con «, » y «: », sin escapar lo que no es ASCII
pub fn escribir_linea(v: &Valor) -> String {
    let mut s = String::new();
    linea(&mut s, v);
    s
}

fn linea(s: &mut String, v: &Valor) {
    match v {
        Valor::Lista(l) => {
            s.push('[');
            for (i, x) in l.iter().enumerate() {
                if i > 0 {
                    s.push_str(", ");
                }
                linea(s, x);
            }
            s.push(']');
        }
        Valor::Mapa(m) => {
            s.push('{');
            for (i, (k, x)) in m.iter().enumerate() {
                if i > 0 {
                    s.push_str(", ");
                }
                texto(s, k);
                s.push_str(": ");
                linea(s, x);
            }
            s.push('}');
        }
        otro => valor(s, otro, 0, 0),
    }
}

/// `json.dumps(v)` con lo de siempre de Python (lo que manda `requests` con `json=`): en una línea, con «, » y «: »,
/// y lo que no es ASCII escapado
pub fn escribir_compacto(v: &Valor) -> String {
    let mut s = String::new();
    compacto(&mut s, v);
    s
}

fn texto_ascii(s: &mut String, t: &str) {
    s.push('"');
    for c in t.chars() {
        match c {
            '\\' => s.push_str("\\\\"),
            '"' => s.push_str("\\\""),
            '\n' => s.push_str("\\n"),
            '\r' => s.push_str("\\r"),
            '\t' => s.push_str("\\t"),
            '\u{8}' => s.push_str("\\b"),
            '\u{c}' => s.push_str("\\f"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                let mut b = [0u16; 2];
                for u in c.encode_utf16(&mut b) {
                    s.push_str(&format!("\\u{:04x}", u));
                }
            }
            c => s.push(c),
        }
    }
    s.push('"');
}

fn compacto(s: &mut String, v: &Valor) {
    match v {
        Valor::Texto(t) => texto_ascii(s, t),
        Valor::Lista(l) => {
            s.push('[');
            for (i, x) in l.iter().enumerate() {
                if i > 0 {
                    s.push_str(", ");
                }
                compacto(s, x);
            }
            s.push(']');
        }
        Valor::Mapa(m) => {
            s.push('{');
            for (i, (k, x)) in m.iter().enumerate() {
                if i > 0 {
                    s.push_str(", ");
                }
                texto_ascii(s, k);
                s.push_str(": ");
                compacto(s, x);
            }
            s.push('}');
        }
        otro => valor(s, otro, 0, 0),
    }
}

// =========================================================================== leer

/// `json.loads(texto)`. Las claves repetidas se quedan con el último valor en el sitio de la primera, como un dict.
/// Los errores, con el texto de `json.JSONDecodeError`: `Expecting value: line 1 column 1 (char 0)`.
pub fn leer(texto: &str) -> Result<Valor, String> {
    if texto.starts_with('\u{feff}') {
        return Err("Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)".into());
    }
    let mut l = Lector { c: texto.as_bytes(), p: 0, t: texto };
    l.blancos();
    let v = l.valor(0)?;
    l.blancos();
    if l.p != l.c.len() {
        return l.error("Extra data");
    }
    Ok(v)
}

/// `msg: line L column C (char N)`, con la posición en caracteres (no en bytes), como `JSONDecodeError`
fn mensaje(t: &str, byte: usize, que: &str) -> String {
    let antes = &t[..byte.min(t.len())];
    let pos = antes.chars().count();
    let linea = antes.matches('\n').count() + 1;
    let columna = match antes.rfind('\n') {
        Some(i) => antes[i + 1..].chars().count() + 1,
        None => pos + 1,
    };
    format!("{que}: line {linea} column {columna} (char {pos})")
}

struct Lector<'a> {
    c: &'a [u8],
    p: usize,
    t: &'a str,
}

impl<'a> Lector<'a> {
    fn blancos(&mut self) {
        while self.p < self.c.len() && matches!(self.c[self.p], b' ' | b'\t' | b'\n' | b'\r') {
            self.p += 1;
        }
    }

    fn error<T>(&self, que: &str) -> Result<T, String> {
        self.error_en(self.p, que)
    }

    fn error_en<T>(&self, byte: usize, que: &str) -> Result<T, String> {
        Err(mensaje(self.t, byte, que))
    }

    fn literal(&mut self, palabra: &str) -> bool {
        if self.c[self.p..].starts_with(palabra.as_bytes()) {
            self.p += palabra.len();
            true
        } else {
            false
        }
    }

    fn valor(&mut self, profundidad: usize) -> Result<Valor, String> {
        if profundidad > 900 {
            return self.error("demasiado anidado");
        }
        let Some(&c) = self.c.get(self.p) else { return self.error("Expecting value") };
        match c {
            b'{' => self.objeto(profundidad),
            b'[' => self.lista(profundidad),
            b'"' => Ok(Valor::Texto(self.cadena()?)),
            b'n' if self.literal("null") => Ok(Valor::Nulo),
            b't' if self.literal("true") => Ok(Valor::Bool(true)),
            b'f' if self.literal("false") => Ok(Valor::Bool(false)),
            b'N' if self.literal("NaN") => Ok(Valor::Real(f64::NAN)),
            b'I' if self.literal("Infinity") => Ok(Valor::Real(f64::INFINITY)),
            b'-' if self.c[self.p..].starts_with(b"-Infinity") => {
                self.p += 9;
                Ok(Valor::Real(f64::NEG_INFINITY))
            }
            b'-' | b'0'..=b'9' => self.numero(),
            _ => self.error("Expecting value"),
        }
    }

    /// `-?(0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?`: entero si no tiene parte decimal ni exponente
    fn numero(&mut self) -> Result<Valor, String> {
        let ini = self.p;
        let digitos = |l: &mut Lector| {
            let a = l.p;
            while l.p < l.c.len() && l.c[l.p].is_ascii_digit() {
                l.p += 1;
            }
            l.p - a
        };
        if self.c[self.p] == b'-' {
            self.p += 1;
        }
        match self.c.get(self.p) {
            Some(b'0') => self.p += 1,
            Some(b'1'..=b'9') => {
                digitos(self);
            }
            _ => {
                self.p = ini;
                return self.error("Expecting value");
            }
        }
        let mut es_real = false;
        if self.c.get(self.p) == Some(&b'.') {
            let guardado = self.p;
            self.p += 1;
            if digitos(self) == 0 {
                self.p = guardado; // «1.» no es un número: el punto queda fuera y dará error después
            } else {
                es_real = true;
            }
        }
        if matches!(self.c.get(self.p), Some(b'e' | b'E')) {
            let guardado = self.p;
            self.p += 1;
            if matches!(self.c.get(self.p), Some(b'+' | b'-')) {
                self.p += 1;
            }
            if digitos(self) == 0 {
                self.p = guardado;
            } else {
                es_real = true;
            }
        }
        let texto = &self.t[ini..self.p];
        if es_real {
            texto.parse::<f64>().map(Valor::Real).or_else(|_| self.error("número"))
        } else {
            match texto.parse::<i128>() {
                Ok(n) => Ok(Valor::Entero(n)),
                Err(_) => texto.parse::<f64>().map(Valor::Real).or_else(|_| self.error("número")),
            }
        }
    }

    /// Las 4 cifras de `\uXXXX` (`self.p` justo después de la `u`); el error, en la `u`, como Python
    fn hex4(&mut self) -> Result<u32, String> {
        let malo = || self.error_en(self.p - 1, "Invalid \\uXXXX escape");
        let Some(h) = self.t.get(self.p..self.p + 4) else { return malo() };
        if !h.chars().all(|c| c.is_ascii_hexdigit()) {
            return malo();
        }
        let n = u32::from_str_radix(h, 16).or_else(|_| malo())?;
        self.p += 4;
        Ok(n)
    }

    fn cadena(&mut self) -> Result<String, String> {
        let inicio = self.p;
        self.p += 1; // la comilla
        let mut s = String::new();
        loop {
            let Some(&c) = self.c.get(self.p) else { return self.error_en(inicio, "Unterminated string starting at") };
            match c {
                b'"' => {
                    self.p += 1;
                    return Ok(s);
                }
                b'\\' => {
                    self.p += 1;
                    let Some(&e) = self.c.get(self.p) else { return self.error_en(inicio, "Unterminated string starting at") };
                    self.p += 1;
                    match e {
                        b'"' => s.push('"'),
                        b'\\' => s.push('\\'),
                        b'/' => s.push('/'),
                        b'b' => s.push('\u{8}'),
                        b'f' => s.push('\u{c}'),
                        b'n' => s.push('\n'),
                        b'r' => s.push('\r'),
                        b't' => s.push('\t'),
                        b'u' => {
                            let mut u = self.hex4()?;
                            // un par sustituto se junta en un carácter; uno suelto no cabe en un String de Rust
                            if (0xd800..0xdc00).contains(&u) && self.c[self.p..].starts_with(b"\\u") {
                                let guardado = self.p;
                                self.p += 2;
                                let bajo = self.hex4()?;
                                if (0xdc00..0xe000).contains(&bajo) {
                                    u = 0x10000 + ((u - 0xd800) << 10) + (bajo - 0xdc00);
                                } else {
                                    self.p = guardado;
                                }
                            }
                            s.push(char::from_u32(u).unwrap_or('\u{fffd}'));
                        }
                        _ => return self.error_en(self.p - 2, "Invalid \\escape"),
                    }
                }
                c if c < 0x20 => return self.error("Invalid control character at"),
                _ => {
                    // un trozo sin escapes de una vez (el texto ya es UTF-8 válido)
                    let ini = self.p;
                    while self.p < self.c.len() && !matches!(self.c[self.p], b'"' | b'\\') && self.c[self.p] >= 0x20 {
                        self.p += 1;
                    }
                    s.push_str(&self.t[ini..self.p]);
                }
            }
        }
    }

    fn lista(&mut self, profundidad: usize) -> Result<Valor, String> {
        self.p += 1;
        let mut l = Vec::new();
        self.blancos();
        if self.c.get(self.p) == Some(&b']') {
            self.p += 1;
            return Ok(Valor::Lista(l));
        }
        loop {
            self.blancos();
            l.push(self.valor(profundidad + 1)?);
            self.blancos();
            match self.c.get(self.p) {
                Some(b',') => self.p += 1,
                Some(b']') => {
                    self.p += 1;
                    return Ok(Valor::Lista(l));
                }
                _ => return self.error("Expecting ',' delimiter"),
            }
        }
    }

    fn objeto(&mut self, profundidad: usize) -> Result<Valor, String> {
        self.p += 1;
        let mut m = Mapa::new();
        self.blancos();
        if self.c.get(self.p) == Some(&b'}') {
            self.p += 1;
            return Ok(Valor::Mapa(m));
        }
        loop {
            self.blancos();
            if self.c.get(self.p) != Some(&b'"') {
                return self.error("Expecting property name enclosed in double quotes");
            }
            let clave = self.cadena()?;
            self.blancos();
            if self.c.get(self.p) != Some(&b':') {
                return self.error("Expecting ':' delimiter");
            }
            self.p += 1;
            self.blancos();
            let v = self.valor(profundidad + 1)?;
            m.poner(clave, v);
            self.blancos();
            match self.c.get(self.p) {
                Some(b',') => self.p += 1,
                Some(b'}') => {
                    self.p += 1;
                    return Ok(Valor::Mapa(m));
                }
                _ => return self.error("Expecting ',' delimiter"),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ida_y_vuelta_como_python() {
        let t = "{\n \"a\": [\n  1,\n  2.5,\n  \"ñ\\n\\u0001\"\n ],\n \"b\": {},\n \"c\": [],\n \"d\": null,\n \"e\": NaN,\n \"f\": 1e+16\n}";
        let v = leer(t).unwrap();
        assert_eq!(escribir(&v, 1), t);
    }

    #[test]
    fn claves_repetidas_como_un_dict() {
        let v = leer(r#"{"a": 1, "b": 2, "a": 3}"#).unwrap();
        assert_eq!(escribir(&v, 1), "{\n \"a\": 3,\n \"b\": 2\n}");
    }

    #[test]
    fn rechaza_lo_que_python_rechaza() {
        for t in ["{roto", "[1,]", "{\"a\" 1}", "01", "1.", "\"a\nb\"", "[1] x", ""] {
            assert!(leer(t).is_err(), "{t}");
        }
        assert_eq!(leer("-0").unwrap(), Valor::Entero(0));
        assert!(matches!(leer("1E2").unwrap(), Valor::Real(x) if x == 100.0));
    }
}

#[cfg(test)]
mod errores_python {
    /// Los mensajes de `json.loads` de Python para documentos rotos (generados con Python 3.12)
    #[test]
    fn mismos_mensajes_que_python() {
        let mut malos = Vec::new();
        for linea in include_str!("json_errores_python.txt").lines() {
            let par = super::leer(linea).unwrap();
            let super::Valor::Lista(par) = par else { panic!() };
            let (super::Valor::Texto(t), super::Valor::Texto(m)) = (&par[0], &par[1]) else { panic!() };
            match super::leer(t) {
                Err(e) if &e == m => {}
                otro => malos.push(format!("{t:?}\n  python: {m}\n  rust:   {otro:?}")),
            }
        }
        assert!(malos.is_empty(), "{} distintos:\n{}", malos.len(), malos.join("\n"));
    }
}
