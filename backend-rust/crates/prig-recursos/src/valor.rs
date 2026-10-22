//! Valores con la forma de los diccionarios de Python: las fichas, las radiografías y los resultados que el backend
//! de Python manda y recibe (y que el servidor en Rust devolverá como JSON). El orden de las claves se conserva,
//! como en un `dict`.
//!
//! También están aquí las operaciones de Python que cambian el resultado si se hacen «a la Rust»: `round`, la
//! representación de un `float` dentro de un texto (`repr`), `int()`, `float()`, `str()` y la verdad de un valor.

use std::fmt::Write;

#[derive(Debug, Clone)]
pub enum Valor {
    Nulo,
    Bool(bool),
    Entero(i128),
    Real(f64),
    Texto(String),
    Lista(Vec<Valor>),
    Mapa(Mapa),
}

/// Un diccionario de Python: claves de texto en orden de inserción. Reasignar una clave la deja en su sitio.
#[derive(Debug, Clone, Default)]
pub struct Mapa(Vec<(String, Valor)>);

impl Mapa {
    pub fn new() -> Mapa {
        Mapa(Vec::new())
    }

    pub fn get(&self, clave: &str) -> Option<&Valor> {
        self.0.iter().find(|(k, _)| k == clave).map(|(_, v)| v)
    }

    pub fn get_mut(&mut self, clave: &str) -> Option<&mut Valor> {
        self.0.iter_mut().find(|(k, _)| k == clave).map(|(_, v)| v)
    }

    pub fn contiene(&self, clave: &str) -> bool {
        self.get(clave).is_some()
    }

    /// `d[clave] = valor`
    pub fn poner(&mut self, clave: impl Into<String>, valor: impl Into<Valor>) {
        let clave = clave.into();
        let valor = valor.into();
        match self.0.iter_mut().find(|(k, _)| *k == clave) {
            Some((_, v)) => *v = valor,
            None => self.0.push((clave, valor)),
        }
    }

    /// Para construir: `Mapa::new().con("a", 1).con("b", 2)`
    pub fn con(mut self, clave: impl Into<String>, valor: impl Into<Valor>) -> Mapa {
        self.poner(clave, valor);
        self
    }

    /// `d.pop(clave, None)`
    pub fn quitar(&mut self, clave: &str) -> Option<Valor> {
        let i = self.0.iter().position(|(k, _)| k == clave)?;
        Some(self.0.remove(i).1)
    }

    pub fn iter(&self) -> impl Iterator<Item = (&String, &Valor)> {
        self.0.iter().map(|(k, v)| (k, v))
    }

    pub fn claves(&self) -> impl Iterator<Item = &String> {
        self.0.iter().map(|(k, _)| k)
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    /// `{**self, **otro}`
    pub fn fusion(&self, otro: &Mapa) -> Mapa {
        let mut m = self.clone();
        for (k, v) in otro.iter() {
            m.poner(k.clone(), v.clone());
        }
        m
    }

    /// `d.get(clave)`: `Nulo` si no está
    pub fn valor(&self, clave: &str) -> &Valor {
        self.get(clave).unwrap_or(&NULO)
    }

    /// `d.get(clave)` como número (`None` si falta o no es un número)
    pub fn num(&self, clave: &str) -> Option<f64> {
        self.get(clave).and_then(Valor::num)
    }

    /// `d.get(clave, defecto)` como número
    pub fn num_o(&self, clave: &str, defecto: f64) -> f64 {
        match self.get(clave) {
            None => defecto,
            Some(v) => v.num().unwrap_or(f64::NAN),
        }
    }

    /// `bool(d.get(clave))`
    pub fn verdad(&self, clave: &str) -> bool {
        self.get(clave).is_some_and(Valor::verdad)
    }

    /// `d.get(clave)` como texto, si lo es
    pub fn texto(&self, clave: &str) -> Option<&str> {
        match self.get(clave) {
            Some(Valor::Texto(t)) => Some(t),
            _ => None,
        }
    }

    pub fn mapa(&self, clave: &str) -> Option<&Mapa> {
        match self.get(clave) {
            Some(Valor::Mapa(m)) => Some(m),
            _ => None,
        }
    }

    pub fn lista(&self, clave: &str) -> Option<&[Valor]> {
        match self.get(clave) {
            Some(Valor::Lista(l)) => Some(l),
            _ => None,
        }
    }
}

static NULO: Valor = Valor::Nulo;

/// Igualdad de Python: un diccionario es igual a otro con las mismas claves y valores, en cualquier orden
impl PartialEq for Mapa {
    fn eq(&self, otro: &Mapa) -> bool {
        self.len() == otro.len() && self.iter().all(|(k, v)| otro.get(k) == Some(v))
    }
}

/// Igualdad de Python: `1 == 1.0 == True`
impl PartialEq for Valor {
    fn eq(&self, otro: &Valor) -> bool {
        use Valor::*;
        match (self, otro) {
            (Nulo, Nulo) => true,
            (Texto(a), Texto(b)) => a == b,
            (Lista(a), Lista(b)) => a == b,
            (Mapa(a), Mapa(b)) => a == b,
            (Entero(a), Entero(b)) => a == b,
            _ => match (self.num(), otro.num()) {
                (Some(a), Some(b)) => a == b,
                _ => false,
            },
        }
    }
}

impl Valor {
    /// El número que es (los booleanos cuentan como 0 y 1, como en Python)
    pub fn num(&self) -> Option<f64> {
        match self {
            Valor::Bool(b) => Some(*b as i32 as f64),
            Valor::Entero(n) => Some(*n as f64),
            Valor::Real(x) => Some(*x),
            _ => None,
        }
    }

    /// `bool(v)`
    pub fn verdad(&self) -> bool {
        match self {
            Valor::Nulo => false,
            Valor::Bool(b) => *b,
            Valor::Entero(n) => *n != 0,
            Valor::Real(x) => *x != 0.0,
            Valor::Texto(t) => !t.is_empty(),
            Valor::Lista(l) => !l.is_empty(),
            Valor::Mapa(m) => !m.is_empty(),
        }
    }

    pub fn es_nulo(&self) -> bool {
        matches!(self, Valor::Nulo)
    }

    /// `int(v)`: `None` donde Python lanzaría TypeError o ValueError
    pub fn entero(&self) -> Option<i128> {
        match self {
            Valor::Bool(b) => Some(*b as i128),
            Valor::Entero(n) => Some(*n),
            Valor::Real(x) if x.is_finite() => Some(x.trunc() as i128),
            Valor::Texto(t) => entero_de_texto(t),
            _ => None,
        }
    }

    /// `float(v)`
    pub fn real(&self) -> Option<f64> {
        match self {
            Valor::Texto(t) => real_de_texto(t),
            v => v.num(),
        }
    }

    /// `str(v)`
    pub fn texto_py(&self) -> String {
        match self {
            Valor::Texto(t) => t.clone(),
            v => v.repr_py(),
        }
    }

    /// `repr(v)`
    /// `str(v)` de Python: el texto tal cual; lo demás, su repr
    pub fn texto_o_repr(&self) -> String {
        match self {
            Valor::Texto(t) => t.clone(),
            otro => otro.repr_py(),
        }
    }

    pub fn repr_py(&self) -> String {
        match self {
            Valor::Nulo => "None".into(),
            Valor::Bool(true) => "True".into(),
            Valor::Bool(false) => "False".into(),
            Valor::Entero(n) => n.to_string(),
            Valor::Real(x) => repr_real(*x),
            Valor::Texto(t) => repr_texto(t),
            Valor::Lista(l) => format!("[{}]", l.iter().map(Valor::repr_py).collect::<Vec<_>>().join(", ")),
            Valor::Mapa(m) => format!(
                "{{{}}}",
                m.iter().map(|(k, v)| format!("{}: {}", repr_texto(k), v.repr_py())).collect::<Vec<_>>().join(", ")
            ),
        }
    }
}

/// `repr` de un texto de Python (comillas simples salvo que las tenga y no tenga dobles)
fn repr_texto(t: &str) -> String {
    let comilla = if t.contains('\'') && !t.contains('"') { '"' } else { '\'' };
    let mut s = String::with_capacity(t.len() + 2);
    s.push(comilla);
    for c in t.chars() {
        match c {
            '\\' => s.push_str("\\\\"),
            '\n' => s.push_str("\\n"),
            '\r' => s.push_str("\\r"),
            '\t' => s.push_str("\\t"),
            c if c == comilla => {
                s.push('\\');
                s.push(c)
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => {
                let _ = write!(s, "\\x{:02x}", c as u32);
            }
            c => s.push(c),
        }
    }
    s.push(comilla);
    s
}

/// `int(texto)` en base 10: espacios alrededor, signo y «_» entre cifras
pub fn entero_de_texto(t: &str) -> Option<i128> {
    let t = t.trim();
    let (negativo, cifras) = match t.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, t.strip_prefix('+').unwrap_or(t)),
    };
    if cifras.is_empty() || cifras.starts_with('_') || cifras.ends_with('_') || cifras.contains("__") {
        return None;
    }
    let limpio: String = cifras.chars().filter(|&c| c != '_').collect();
    if !limpio.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let n: i128 = limpio.parse().ok()?;
    Some(if negativo { -n } else { n })
}

/// `float(texto)`
pub fn real_de_texto(t: &str) -> Option<f64> {
    let t = t.trim();
    if t.contains("__") || t.starts_with('_') || t.ends_with('_') {
        return None;
    }
    let mut limpio = String::with_capacity(t.len());
    let c: Vec<char> = t.chars().collect();
    for (i, &x) in c.iter().enumerate() {
        if x == '_' {
            // solo entre dos cifras
            let antes = i > 0 && c[i - 1].is_ascii_digit();
            let despues = i + 1 < c.len() && c[i + 1].is_ascii_digit();
            if !(antes && despues) {
                return None;
            }
            continue;
        }
        limpio.push(x);
    }
    limpio.parse().ok()
}

/// `repr(x)` de un float de Python: el número más corto que vuelve a dar el mismo valor, en notación fija entre
/// 1e-4 y 1e16 (con «.0» si es entero) y científica fuera (`1e+16`, `1.5e-05`)
pub fn repr_real(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    let e = format!("{x:e}"); // el más corto que vuelve al mismo valor, como Python
    let (mantisa, exp) = e.split_once('e').unwrap_or((&e, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let (signo, mantisa) = match mantisa.strip_prefix('-') {
        Some(m) => ("-", m),
        None => ("", mantisa),
    };
    let cifras: String = mantisa.chars().filter(|c| *c != '.').collect();
    let n = cifras.len() as i32;
    if (-4..16).contains(&exp) {
        if exp >= 0 {
            let enteros = (exp + 1) as usize;
            if n <= exp + 1 {
                format!("{signo}{cifras}{}.0", "0".repeat(enteros - n as usize))
            } else {
                format!("{signo}{}.{}", &cifras[..enteros], &cifras[enteros..])
            }
        } else {
            format!("{signo}0.{}{cifras}", "0".repeat((-exp - 1) as usize))
        }
    } else {
        let m = if n > 1 { format!("{}.{}", &cifras[..1], &cifras[1..]) } else { cifras };
        format!("{signo}{m}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs())
    }
}

/// `round(x, n)` de Python: redondea el valor decimal exacto, con los empates al par (`{:.n}` hace lo mismo)
pub fn redondear(x: f64, decimales: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.decimales$}").parse().unwrap_or(x)
}

/// `round(x)` de Python: un entero, con los empates al par
pub fn redondear_entero(x: f64) -> i128 {
    x.round_ties_even() as i128
}

/// `f"{x:.nf}"`
pub fn fijo(x: f64, decimales: usize) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    format!("{x:.decimales$}")
}

impl From<bool> for Valor {
    fn from(b: bool) -> Valor {
        Valor::Bool(b)
    }
}
impl From<i64> for Valor {
    fn from(n: i64) -> Valor {
        Valor::Entero(n as i128)
    }
}
impl From<i128> for Valor {
    fn from(n: i128) -> Valor {
        Valor::Entero(n)
    }
}
impl From<i32> for Valor {
    fn from(n: i32) -> Valor {
        Valor::Entero(n as i128)
    }
}
impl From<u32> for Valor {
    fn from(n: u32) -> Valor {
        Valor::Entero(n as i128)
    }
}
impl From<u64> for Valor {
    fn from(n: u64) -> Valor {
        Valor::Entero(n as i128)
    }
}
impl From<usize> for Valor {
    fn from(n: usize) -> Valor {
        Valor::Entero(n as i128)
    }
}
impl From<f64> for Valor {
    fn from(x: f64) -> Valor {
        Valor::Real(x)
    }
}
impl From<&str> for Valor {
    fn from(t: &str) -> Valor {
        Valor::Texto(t.to_string())
    }
}
impl From<String> for Valor {
    fn from(t: String) -> Valor {
        Valor::Texto(t)
    }
}
impl From<&String> for Valor {
    fn from(t: &String) -> Valor {
        Valor::Texto(t.clone())
    }
}
impl From<Mapa> for Valor {
    fn from(m: Mapa) -> Valor {
        Valor::Mapa(m)
    }
}
impl From<Vec<Valor>> for Valor {
    fn from(l: Vec<Valor>) -> Valor {
        Valor::Lista(l)
    }
}
impl<T: Into<Valor>> From<Option<T>> for Valor {
    fn from(o: Option<T>) -> Valor {
        o.map(Into::into).unwrap_or(Valor::Nulo)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repr_como_python() {
        for (x, esperado) in [
            (4.85, "4.85"),
            (5.0, "5.0"),
            (-0.0, "-0.0"),
            (0.1 + 0.2, "0.30000000000000004"),
            (1e16, "1e+16"),
            (1.5e-5, "1.5e-05"),
            (0.0001, "0.0001"),
            (123456789012345.6, "123456789012345.6"),
            (1e15, "1000000000000000.0"),
            (6141.0 * 1048576.0, "6439305216.0"),
        ] {
            assert_eq!(repr_real(x), esperado, "{x}");
        }
    }

    #[test]
    fn enteros_como_python() {
        assert_eq!(entero_de_texto(" 2 "), Some(2));
        assert_eq!(entero_de_texto("+3"), Some(3));
        assert_eq!(entero_de_texto("1_000"), Some(1000));
        assert_eq!(entero_de_texto("2.0"), None);
        assert_eq!(entero_de_texto("x"), None);
        assert_eq!(entero_de_texto("1__0"), None);
    }

    #[test]
    fn mapa_conserva_el_orden() {
        let mut m = Mapa::new().con("b", 1).con("a", 2);
        m.poner("b", 3);
        assert_eq!(m.claves().cloned().collect::<Vec<_>>(), ["b", "a"]);
        assert_eq!(m.valor("b"), &Valor::Entero(3));
    }
}
