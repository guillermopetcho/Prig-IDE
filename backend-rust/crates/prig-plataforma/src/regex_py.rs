//! Expresiones regulares con la sintaxis y el comportamiento de `re` de Python, sobre `fancy-regex` (que tiene lo
//! que `regex` no: mirar atrás y referencias a grupos).
//!
//! Se traduce lo que cambia de significado: `\Z`, `$` (que en Python también casa antes del último salto),
//! `{` que no es una repetición (literal en Python), `(?P=nombre)`, `(?#...)` y, dentro de `[...]`, los `[`, `&&`,
//! `--` y `~~` (literales en Python, operaciones de conjuntos en Rust). Las plantillas de reemplazo (`\1`,
//! `\g<nombre>`, `\n`) se expanden como `re.sub`, con los mismos errores.
//!
//! Los aciertos se recorren como en Python (`recorrer`): también el vacío justo después de un acierto no vacío.
//!
//! Diferencias que quedan, escritas: el texto de los errores de una expresión mal escrita es el de Rust; y después
//! de un acierto vacío, si el patrón podía casar algo no vacío en ese mismo sitio con otra alternativa (`(|a)` sobre
//! «a»), Python lo toma y aquí se sigue desde el carácter siguiente.

use fancy_regex::RegexBuilder;

/// El motor de una expresión: el de `regex` si el patrón no necesita nada más (mucho más rápido, sobre todo con
/// `\b`), o `fancy-regex` si mira atrás o adelante o usa referencias a grupos
pub enum Motor {
    Simple(regex::Regex),
    Fancy(fancy_regex::Regex),
}

/// Los grupos de un acierto, de cualquiera de los dos motores
pub enum Grupos<'t> {
    Simple(regex::Captures<'t>),
    Fancy(fancy_regex::Captures<'t, str>),
}

impl<'t> Grupos<'t> {
    pub fn get(&self, i: usize) -> Option<(usize, usize, &'t str)> {
        match self {
            Grupos::Simple(c) => c.get(i).map(|m| (m.start(), m.end(), m.as_str())),
            Grupos::Fancy(c) => c.get(i).map(|m| (m.start(), m.end(), m.as_str())),
        }
    }
}

impl Motor {
    fn compilar(patron: &str, mayusculas: bool) -> Result<Motor, String> {
        if let Ok(r) = regex::RegexBuilder::new(patron).case_insensitive(!mayusculas).build() {
            return Ok(Motor::Simple(r));
        }
        RegexBuilder::new(patron).case_insensitive(!mayusculas).build().map(Motor::Fancy).map_err(|e| e.to_string())
    }

    fn buscar(&self, t: &str, pos: usize) -> Option<(usize, usize)> {
        match self {
            Motor::Simple(r) => r.find_at(t, pos).map(|m| (m.start(), m.end())),
            Motor::Fancy(r) => r.find_from_pos(t, pos).ok().flatten().map(|m| (m.start(), m.end())),
        }
    }

    fn grupos<'t>(&self, t: &'t str, pos: usize) -> Option<Grupos<'t>> {
        match self {
            Motor::Simple(r) => r.captures_at(t, pos).map(Grupos::Simple),
            Motor::Fancy(r) => r.captures_from_pos(t, pos).ok().flatten().map(Grupos::Fancy),
        }
    }

    fn casa(&self, t: &str) -> bool {
        match self {
            Motor::Simple(r) => r.is_match(t),
            Motor::Fancy(r) => r.is_match(t).unwrap_or(true),
        }
    }

    fn nombres(&self) -> Vec<Option<String>> {
        match self {
            Motor::Simple(r) => r.capture_names().map(|n| n.map(String::from)).collect(),
            Motor::Fancy(r) => r.capture_names().map(|n| n.map(String::from)).collect(),
        }
    }
}

pub struct ExpresionPy {
    re: Motor,
    /// Los nombres de los grupos, por número (el 0 es todo)
    nombres: Vec<Option<String>>,
    /// «Palabra completa» de un texto literal: los bordes `(?<!\w)…(?!\w)` se miran a mano, sin mirar atrás en
    /// cada posición (con un literal da lo mismo: en cada inicio hay como mucho un acierto, de largo fijo)
    bordes: bool,
    /// La misma expresión con `\b` ASCII, para textos solo ASCII (si el patrón tiene `\b` o `\B`)
    re_ascii: Option<Motor>,
    /// Si casar sobre el texto entero dice algo de cada línea: sin anclas ni lookarounds, un archivo en el que el
    /// patrón no casa en ningún sitio no tiene ninguna línea donde case
    filtro_seguro: bool,
}

fn quantificador(c: &[char], i: usize) -> Option<(String, usize)> {
    // c[i] == '{'
    if c.get(i + 1) == Some(&'}') {
        return None;
    }
    let mut j = i + 1;
    let mut lo = String::new();
    while j < c.len() && c[j].is_ascii_digit() {
        lo.push(c[j]);
        j += 1;
    }
    
    let coma = c.get(j) == Some(&',');
    let hi = if coma {
        j += 1;
        let mut h = String::new();
        while j < c.len() && c[j].is_ascii_digit() {
            h.push(c[j]);
            j += 1;
        }
        h
    } else {
        lo.clone()
    };
    if c.get(j) != Some(&'}') {
        return None;
    }
    let lo = if lo.is_empty() { "0".to_string() } else { lo };
    let texto = if coma { format!("{{{lo},{hi}}}") } else { format!("{{{lo}}}") };
    Some((texto, j + 1))
}

/// `(?i)` (o `(?is)`...) al principio del patrón, y el resto
fn flags_al_principio(patron: &str) -> (&str, &str) {
    if let Some(r) = patron.strip_prefix("(?") {
        let n = r.chars().take_while(|c| "aiLmsux".contains(*c)).count();
        if n > 0 && r[n..].starts_with(')') {
            return patron.split_at(2 + n + 1);
        }
    }
    ("", patron)
}

/// Python 3.11+ no admite `(?i)` y compañía salvo al principio del patrón
fn flags_globales(patron: &str) -> Result<(), String> {
    let c: Vec<char> = patron.chars().collect();
    let mut i = 0;
    let mut en_clase = false;
    while i < c.len() {
        match c[i] {
            '\\' => i += 1,
            '[' if !en_clase => en_clase = true,
            ']' if en_clase => en_clase = false,
            '(' if !en_clase && c.get(i + 1) == Some(&'?') => {
                let mut j = i + 2;
                while j < c.len() && "aiLmsux".contains(c[j]) {
                    j += 1;
                }
                if j > i + 2 && c.get(j) == Some(&')') && i > 0 {
                    return Err(format!("global flags not at the start of the expression at position {i}"));
                }
            }
            _ => {}
        }
        i += 1;
    }
    Ok(())
}

/// El patrón de Python escrito para fancy-regex
pub fn traducir(patron: &str) -> String {
    traducir_con(patron, false)
}

/// Con `bordes_ascii`, `\b` y `\B` como bordes ASCII: sobre un texto solo ASCII son los mismos que los Unicode, y el
/// motor rápido de Rust no sabe hacer los Unicode
fn traducir_con(patron: &str, bordes_ascii: bool) -> String {
    let c: Vec<char> = patron.chars().collect();
    let multilinea = patron.starts_with("(?") && c.iter().skip(2).take_while(|x| x.is_ascii_alphabetic()).any(|x| *x == 'm');
    let mut s = String::with_capacity(patron.len() + 8);
    let mut i = 0;
    while i < c.len() {
        let x = c[i];
        match x {
            '\\' if i + 1 < c.len() && c[i + 1].is_ascii_digit() => {
                // `\0oo` y `\ooo` son octales; `\n` y `\nn` (sin tercer octal) son referencias a grupos
                let oct = |z: Option<&char>| matches!(z, Some('0'..='7'));
                let y = c[i + 1];
                if y == '0' {
                    let mut v = String::from("0");
                    let mut j = i + 2;
                    while j < c.len() && v.len() < 3 && oct(c.get(j)) {
                        v.push(c[j]);
                        j += 1;
                    }
                    s.push_str(&format!("\\x{{{:x}}}", u32::from_str_radix(&v, 8).unwrap_or(0)));
                    i = j;
                } else if oct(c.get(i + 1)) && oct(c.get(i + 2)) && oct(c.get(i + 3)) {
                    let v: String = c[i + 1..i + 4].iter().collect();
                    s.push_str(&format!("\\x{{{:x}}}", u32::from_str_radix(&v, 8).unwrap_or(0)));
                    i += 4;
                } else {
                    let largo = if c.get(i + 2).is_some_and(|z| z.is_ascii_digit()) { 2 } else { 1 };
                    let v: String = c[i + 1..i + 1 + largo].iter().collect();
                    s.push('\\');
                    s.push_str(&v);
                    i += 1 + largo;
                }
            }
            '\\' if i + 1 < c.len() => {
                let y = c[i + 1];
                if y == 's' {
                    // `\s` de Python también es \x1c-\x1f (str.isspace)
                    s.push_str("[\\s\\x1c-\\x1f]");
                } else if y == 'S' {
                    s.push_str("[^\\s\\x1c-\\x1f]");
                } else if y == 'Z' {
                    s.push_str("\\z");
                } else if bordes_ascii && (y == 'b' || y == 'B') {
                    s.push_str(&format!("(?-u:\\{y})"));
                } else {
                    s.push('\\');
                    s.push(y);
                }
                i += 2;
            }
            '[' => {
                s.push('[');
                i += 1;
                if c.get(i) == Some(&'^') {
                    s.push('^');
                    i += 1;
                }
                if c.get(i) == Some(&']') {
                    s.push_str("\\]");
                    i += 1;
                }
                while i < c.len() && c[i] != ']' {
                    match c[i] {
                        '\\' if i + 1 < c.len() => {
                            s.push('\\');
                            s.push(c[i + 1]);
                            i += 2;
                            continue;
                        }
                        '[' => s.push_str("\\["),
                        '&' | '~' => {
                            s.push('\\');
                            s.push(c[i]);
                        }
                        '-' if c.get(i + 1) == Some(&'-') => s.push_str("\\-"),
                        otro => s.push(otro),
                    }
                    i += 1;
                }
                if i < c.len() {
                    s.push(']');
                    i += 1;
                }
            }
            '$' if !multilinea => {
                s.push_str("(?=\\n?\\z)");
                i += 1;
            }
            '{' => match quantificador(&c, i) {
                Some((q, j)) if !s.is_empty() => {
                    s.push_str(&q);
                    i = j;
                }
                _ => {
                    s.push_str("\\{");
                    i += 1;
                }
            },
            '}' => {
                s.push_str("\\}");
                i += 1;
            }
            '(' if c.get(i + 1) == Some(&'?') && c.get(i + 2) == Some(&'#') => {
                // un comentario
                while i < c.len() && c[i] != ')' {
                    i += 1;
                }
                i += 1;
            }
            '(' if c[i..].starts_with(&['(', '?', 'P', '=']) => {
                let fin = c[i..].iter().position(|&z| z == ')').map(|p| p + i).unwrap_or(c.len());
                let nombre: String = c[i + 4..fin].iter().collect();
                s.push_str(&format!("\\k<{nombre}>"));
                i = fin + 1;
            }
            otro => {
                s.push(otro);
                i += 1;
            }
        }
    }
    s
}

impl ExpresionPy {
    /// `re.compile(patron, re.IGNORECASE si no mayusculas)`
    pub fn compilar(patron: &str, mayusculas: bool) -> Result<ExpresionPy, String> {
        flags_globales(patron)?;
        let re = Motor::compilar(&traducir(patron), mayusculas)?;
        let nombres = re.nombres();
        let t = traducir(patron);
        let filtro_seguro = !["(?<", "(?=", "(?!", "^", "$", "\\A", "\\z", "\\Z"].iter().any(|x| t.contains(x));
        let ascii = traducir_con(patron, true);
        let re_ascii = if ascii != t {
            Motor::compilar(&ascii, mayusculas).ok()
        } else {
            None
        };
        Ok(ExpresionPy { re, nombres, bordes: false, re_ascii, filtro_seguro })
    }

    /// Un texto literal como «palabra completa» (`(?<!\w)literal(?!\w)` de Python)
    pub fn palabra_literal(literal: &str, mayusculas: bool) -> Result<ExpresionPy, String> {
        let mut e = ExpresionPy::compilar(&escapar(literal), mayusculas)?;
        e.bordes = true;
        Ok(e)
    }

    /// El motor para un texto: el de `\b` ASCII si el texto es solo ASCII
    fn motor(&self, texto: &str) -> &Motor {
        match &self.re_ascii {
            Some(r) if texto.is_ascii() => r,
            _ => &self.re,
        }
    }

    /// Puede casar en alguna línea del texto (si no se puede saber, true)
    pub fn posible(&self, texto: &str) -> bool {
        if !self.filtro_seguro {
            return true;
        }
        self.motor(texto).casa(texto)
    }

    fn borde_ok(texto: &str, ini: usize, fin: usize) -> bool {
        let antes = texto[..ini].chars().next_back();
        let despues = texto[fin..].chars().next();
        !antes.is_some_and(regex_syntax::is_word_character) && !despues.is_some_and(regex_syntax::is_word_character)
    }

    pub fn grupos(&self) -> usize {
        self.nombres.len() - 1
    }

    /// Los aciertos de un texto como los recorre `re` de Python: después de un acierto no vacío se admite uno
    /// vacío justo donde terminó (Rust lo salta); después de uno vacío, el siguiente tiene que avanzar
    fn recorrer<'t>(&self, texto: &'t str) -> Vec<Grupos<'t>> {
        let re = self.motor(texto);
        let mut salida = Vec::new();
        let mut pos = 0;
        let mut vacio_antes = false;
        while pos <= texto.len() {
            let Some(mut c) = re.grupos(texto, pos) else { break };
            let (ini, fin, _) = c.get(0).unwrap();
            if self.bordes && !Self::borde_ok(texto, ini, fin) {
                // como el motor de Python: se vuelve a probar desde el carácter siguiente al inicio
                pos = ini + texto[ini..].chars().next().map(char::len_utf8).unwrap_or(1);
                continue;
            }
            if vacio_antes && ini == pos && fin == pos {
                // tiene que avanzar: se busca desde el carácter siguiente
                let Some(sig) = texto[pos..].chars().next().map(|ch| pos + ch.len_utf8()) else { break };
                match re.grupos(texto, sig) {
                    Some(otra) => c = otra,
                    None => break,
                }
            }
            let (ini, fin, _) = c.get(0).unwrap();
            pos = fin;
            vacio_antes = ini == fin;
            salida.push(c);
        }
        salida
    }

    /// `re.search`: los grupos del primer acierto (el 0 es todo)
    pub fn buscar(&self, texto: &str) -> Option<Vec<Option<String>>> {
        let g = self.recorrer_uno(texto)?;
        Some((0..self.nombres.len()).map(|i| g.get(i).map(|(_, _, t)| t.to_string())).collect())
    }

    fn recorrer_uno<'t>(&self, texto: &'t str) -> Option<Grupos<'t>> {
        let re = self.motor(texto);
        let mut pos = 0;
        loop {
            let c = re.grupos(texto, pos)?;
            let (ini, fin, _) = c.get(0).unwrap();
            if self.bordes && !Self::borde_ok(texto, ini, fin) {
                pos = ini + texto[ini..].chars().next().map(char::len_utf8).unwrap_or(1);
                if pos > texto.len() {
                    return None;
                }
                continue;
            }
            return Some(c);
        }
    }

    /// `re.finditer`: los grupos de cada acierto
    pub fn todos(&self, texto: &str) -> Vec<Vec<Option<String>>> {
        self.recorrer(texto).iter().map(|g| (0..self.nombres.len()).map(|i| g.get(i).map(|(_, _, t)| t.to_string())).collect()).collect()
    }

    /// `re.split` (sin grupos en el patrón)
    pub fn partir(&self, texto: &str) -> Vec<String> {
        let mut salida = Vec::new();
        let mut ultimo = 0;
        for (ini, fin) in self.aciertos(texto) {
            salida.push(texto[ultimo..ini].to_string());
            ultimo = fin;
        }
        salida.push(texto[ultimo..].to_string());
        salida
    }

    /// `re.sub` con un texto literal
    pub fn sustituir(&self, texto: &str, por: &str) -> String {
        self.subn(texto, &Reemplazo::Literal(por.to_string())).0
    }

    /// `re.match`: anclado al principio
    pub fn anclada(patron: &str, mayusculas: bool) -> Result<ExpresionPy, String> {
        let (flags, resto) = flags_al_principio(patron);
        ExpresionPy::compilar(&format!("{flags}\\A(?:{resto})"), mayusculas)
    }

    /// `re.fullmatch`: el texto entero
    pub fn entera(patron: &str, mayusculas: bool) -> Result<ExpresionPy, String> {
        let (flags, resto) = flags_al_principio(patron);
        ExpresionPy::compilar(&format!("{flags}\\A(?:{resto})\\z"), mayusculas)
    }

    /// Los aciertos (inicio, fin en bytes) de un texto, como `finditer` (sin grupos: más rápido)
    pub fn aciertos(&self, texto: &str) -> Vec<(usize, usize)> {
        let re = self.motor(texto);
        let mut salida = Vec::new();
        let mut pos = 0;
        let mut vacio_antes = false;
        while pos <= texto.len() {
            let Some(mut m) = re.buscar(texto, pos) else { break };
            if self.bordes && !Self::borde_ok(texto, m.0, m.1) {
                pos = m.0 + texto[m.0..].chars().next().map(char::len_utf8).unwrap_or(1);
                continue;
            }
            if vacio_antes && m.0 == pos && m.1 == pos {
                let Some(sig) = texto[pos..].chars().next().map(|ch| pos + ch.len_utf8()) else { break };
                match re.buscar(texto, sig) {
                    Some(otra) => m = otra,
                    None => break,
                }
            }
            pos = m.1;
            vacio_antes = m.0 == m.1;
            salida.push(m);
        }
        salida
    }

    /// `re.subn(plantilla, texto)` con una plantilla de Python (o un texto literal)
    pub fn subn(&self, texto: &str, reemplazo: &Reemplazo) -> (String, usize) {
        let mut salida = String::with_capacity(texto.len());
        let mut ultimo = 0;
        let mut n = 0;
        for caps in self.recorrer(texto) {
            let (ini, fin, _) = caps.get(0).unwrap();
            salida.push_str(&texto[ultimo..ini]);
            match reemplazo {
                Reemplazo::Literal(t) => salida.push_str(t),
                Reemplazo::Plantilla(partes) => expandir(partes, &caps, &mut salida),
            }
            ultimo = fin;
            n += 1;
        }
        salida.push_str(&texto[ultimo..]);
        (salida, n)
    }

    fn indice_de(&self, nombre: &str) -> Option<usize> {
        self.nombres.iter().position(|n| n.as_deref() == Some(nombre))
    }
}

pub enum Parte {
    Texto(String),
    Grupo(usize),
}

pub enum Reemplazo {
    Literal(String),
    Plantilla(Vec<Parte>),
}

fn expandir(partes: &[Parte], caps: &Grupos<'_>, salida: &mut String) {
    for p in partes {
        match p {
            Parte::Texto(t) => salida.push_str(t),
            Parte::Grupo(g) => {
                if let Some((_, _, t)) = caps.get(*g) {
                    salida.push_str(t);
                }
            }
        }
    }
}

/// `_parser.parse_template` de Python 3.12: la plantilla en partes, o el texto del error
pub fn plantilla(fuente: &str, expr: &ExpresionPy) -> Result<Vec<Parte>, String> {
    let c: Vec<char> = fuente.chars().collect();
    let mut partes: Vec<Parte> = Vec::new();
    let mut literal = String::new();
    let mut i = 0;
    let error = |msg: String, pos: usize| Err(format!("{msg} at position {pos}"));
    let grupo = |g: usize, partes: &mut Vec<Parte>, literal: &mut String| {
        if !literal.is_empty() {
            partes.push(Parte::Texto(std::mem::take(literal)));
        }
        partes.push(Parte::Grupo(g));
    };
    while i < c.len() {
        if c[i] != '\\' {
            literal.push(c[i]);
            i += 1;
            continue;
        }
        let Some(&y) = c.get(i + 1) else {
            return error("bad escape (end of pattern)".into(), i);
        };
        let inicio = i;
        i += 2;
        match y {
            'g' => {
                if c.get(i) != Some(&'<') {
                    return error("missing <".into(), i);
                }
                i += 1;
                let ini_nombre = i;
                let Some(fin) = c[i..].iter().position(|&z| z == '>').map(|p| p + i) else {
                    if i >= c.len() {
                        return error("missing group name".into(), i);
                    }
                    return error("missing >, unterminated name".into(), ini_nombre);
                };
                let nombre: String = c[ini_nombre..fin].iter().collect();
                if nombre.is_empty() {
                    return error("missing group name".into(), ini_nombre);
                }
                i = fin + 1;
                let indice = if nombre.chars().all(|z| z.is_ascii_digit()) {
                    let n: usize = nombre.parse().unwrap_or(usize::MAX);
                    if n > expr.grupos() {
                        return error(format!("invalid group reference {n}"), ini_nombre);
                    }
                    n
                } else if es_identificador(&nombre) {
                    match expr.indice_de(&nombre) {
                        Some(n) => n,
                        None => return Err(format!("unknown group name '{nombre}'")),
                    }
                } else {
                    return error(format!("bad character in group name '{nombre}'"), ini_nombre);
                };
                grupo(indice, &mut partes, &mut literal);
            }
            '0' => {
                let mut v = String::from("0");
                for _ in 0..2 {
                    if matches!(c.get(i), Some('0'..='7')) {
                        v.push(c[i]);
                        i += 1;
                    }
                }
                let n = u32::from_str_radix(&v, 8).unwrap_or(0) & 0xff;
                literal.push(char::from_u32(n).unwrap_or('\0'));
            }
            '1'..='9' => {
                let mut v = String::from(y);
                let mut octal = false;
                if matches!(c.get(i), Some('0'..='9')) {
                    v.push(c[i]);
                    i += 1;
                    let oct = |z: char| ('0'..='7').contains(&z);
                    if oct(y) && oct(v.chars().nth(1).unwrap()) && matches!(c.get(i), Some(z) if oct(*z)) {
                        v.push(c[i]);
                        i += 1;
                        octal = true;
                        let n = u32::from_str_radix(&v, 8).unwrap_or(0);
                        if n > 0o377 {
                            return error(format!("octal escape value \\{v} outside of range 0-0o377"), inicio);
                        }
                        literal.push(char::from_u32(n).unwrap_or('\0'));
                    }
                }
                if !octal {
                    let n: usize = v.parse().unwrap_or(0);
                    if n > expr.grupos() {
                        return error(format!("invalid group reference {n}"), inicio + 1);
                    }
                    grupo(n, &mut partes, &mut literal);
                }
            }
            otro => {
                let escape = match otro {
                    'a' => Some('\x07'),
                    'b' => Some('\x08'),
                    'f' => Some('\x0c'),
                    'n' => Some('\n'),
                    'r' => Some('\r'),
                    't' => Some('\t'),
                    'v' => Some('\x0b'),
                    '\\' => Some('\\'),
                    _ => None,
                };
                match escape {
                    Some(e) => literal.push(e),
                    None if otro.is_ascii_alphabetic() => return error(format!("bad escape \\{otro}"), inicio),
                    None => {
                        literal.push('\\');
                        literal.push(otro);
                    }
                }
            }
        }
    }
    if !literal.is_empty() {
        partes.push(Parte::Texto(literal));
    }
    Ok(partes)
}

/// `str.isidentifier()` (aproximado: letras, cifras y «_», sin empezar por cifra)
fn es_identificador(t: &str) -> bool {
    let mut it = t.chars();
    match it.next() {
        Some(c) if c == '_' || c.is_alphabetic() => it.all(|c| c == '_' || c.is_alphanumeric()),
        _ => false,
    }
}

/// `re.escape`
pub fn escapar(t: &str) -> String {
    regex::escape(t)
}
