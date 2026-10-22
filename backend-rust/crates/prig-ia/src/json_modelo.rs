//! Sacar el JSON de lo que responde un modelo (`reparar_y_parsear_json` de `ai_engine_class.py`): sin el bloque de
//! razonamiento, de un bloque ```json, del primer `{` al último `}` o del texto entero, y si no se puede leer tal
//! cual, con los arreglos de siempre (comas sobrantes, comillas simples, `True`/`None` de Python, comillas internas
//! sin escapar, cierres que faltan) y por último el rescate de un desafío a medias.

use std::sync::OnceLock;

use prig_plataforma::regex_py::ExpresionPy;
use prig_recursos::json;
use prig_recursos::valor::{Mapa, Valor};

fn re(p: &str, mayus: bool) -> ExpresionPy {
    ExpresionPy::compilar(p, mayus).unwrap()
}

struct Exp {
    pensamiento: ExpresionPy,
    bloque: ExpresionPy,
    comas: ExpresionPy,
    simples: ExpresionPy,
    tru: ExpresionPy,
    fal: ExpresionPy,
    non: ExpresionPy,
    tru_j: ExpresionPy,
    fal_j: ExpresionPy,
    nul_j: ExpresionPy,
    titulo: ExpresionPy,
    enunciado: ExpresionPy,
    nivel: ExpresionPy,
    paginas: ExpresionPy,
}

fn exp() -> &'static Exp {
    static E: OnceLock<Exp> = OnceLock::new();
    E.get_or_init(|| Exp {
        pensamiento: re(r"(?s)<think(?:ing)?>.*?</think(?:ing)?>\s*", false),
        bloque: re(r"(?s)```(?:json)?\s*([\{\[].*?[\}\]])\s*```", true),
        comas: re(r",\s*([\]}])", true),
        simples: re(r"'([^'\\]*(?:\\.[^'\\]*)*)'", true),
        tru: re(r"\bTrue\b", true),
        fal: re(r"\bFalse\b", true),
        non: re(r"\bNone\b", true),
        tru_j: re(r"\btrue\b", true),
        fal_j: re(r"\bfalse\b", true),
        nul_j: re(r"\bnull\b", true),
        titulo: re(r#""titulo"\s*:\s*"([^"]+)""#, true),
        enunciado: re(r#"(?s)"enunciado"\s*:\s*"(.*?)(?="\s*,\s*"(?:nivel|conceptos|paginas))"#, true),
        nivel: re(r#""nivel"\s*:\s*"([^"]+)""#, true),
        paginas: re(r#"(?s)\{\s*"nombre"\s*:\s*"([^"]+)".*?"contenido"\s*:\s*"(.*?)(?="\s*\}\s*[,\]])"#, true),
    })
}

/// `re.sub` con la plantilla `\1`
fn sub_grupo(e: &ExpresionPy, t: &str, plantilla: &str) -> String {
    let p = prig_plataforma::regex_py::plantilla(plantilla, e).unwrap();
    e.subn(t, &prig_plataforma::regex_py::Reemplazo::Plantilla(p)).0
}

fn como_dict(v: Valor) -> Option<Mapa> {
    match v {
        Valor::Mapa(m) => Some(m),
        Valor::Lista(mut l) if !l.is_empty() && matches!(l[0], Valor::Mapa(_)) => match l.swap_remove(0) {
            Valor::Mapa(m) => Some(m),
            _ => None,
        },
        _ => None,
    }
}

fn intentar(s: &str) -> Option<Mapa> {
    let e = exp();
    if let Some(d) = json::leer(s).ok().and_then(como_dict) {
        return Some(d);
    }
    if let Some(d) = json::leer_flexible(s).ok().and_then(como_dict) {
        return Some(d);
    }
    let sin_comas = sub_grupo(&e.comas, s, r"\1");
    if let Some(d) = json::leer_flexible(&sin_comas).ok().and_then(como_dict) {
        return Some(d);
    }
    let doble = sub_grupo(&e.simples, &sin_comas, r#""\1""#);
    let doble = e.non.sustituir(&e.fal.sustituir(&e.tru.sustituir(&doble, "true"), "false"), "null");
    if let Some(d) = json::leer_flexible(&doble).ok().and_then(como_dict) {
        return Some(d);
    }
    let py = e.nul_j.sustituir(&e.fal_j.sustituir(&e.tru_j.sustituir(&sin_comas, "True"), "False"), "None");
    literal_eval(&py).ok().and_then(como_dict)
}

/// `_escapar_comillas_internas`: una `"` dentro de una cadena que no va seguida de `, : } ]` se escapa
fn escapar_comillas_internas(t: &str) -> String {
    let mut c: Vec<char> = t.chars().collect();
    let mut i = 0;
    while i < c.len() {
        if c[i] == '"' {
            let mut j = i + 1;
            while j < c.len() {
                if c[j] == '\\' {
                    j += 2;
                    continue;
                }
                if c[j] == '"' {
                    let mut k = j + 1;
                    while k < c.len() && " \t\r\n".contains(c[k]) {
                        k += 1;
                    }
                    if k < c.len() && ",:}]".contains(c[k]) {
                        break;
                    }
                    c.splice(j..j + 1, ['\\', '"']);
                    j += 2;
                    continue;
                }
                j += 1;
            }
            i = j + 1;
        } else {
            i += 1;
        }
    }
    c.into_iter().collect()
}

/// `_cerrar_incompleto`: cierra la cadena y las llaves y corchetes abiertos
fn cerrar_incompleto(t: &str) -> String {
    let (mut pila, mut en, mut esc) = (Vec::new(), false, false);
    for ch in t.chars() {
        if esc {
            esc = false;
            continue;
        }
        if ch == '\\' {
            esc = true;
            continue;
        }
        if ch == '"' {
            en = !en;
            continue;
        }
        if !en {
            match ch {
                '{' => pila.push('}'),
                '[' => pila.push(']'),
                '}' | ']' if pila.last() == Some(&ch) => {
                    pila.pop();
                }
                _ => {}
            }
        }
    }
    let mut s = t.to_string();
    if en {
        s.push('"');
    }
    while let Some(c) = pila.pop() {
        s.push(c);
    }
    s
}

/// `reparar_y_parsear_json`: el dict que hay en la respuesta; Err con el mensaje de Python
pub fn reparar(respuesta: &str) -> Result<Mapa, String> {
    if prig_plataforma::py::strip(respuesta).is_empty() {
        return Err("Respuesta vacía del modelo de IA".into());
    }
    let e = exp();
    let limpio = prig_plataforma::py::strip(&e.pensamiento.sustituir(respuesta, "")).to_string();
    let mut cands: Vec<String> = e.bloque.todos(&limpio).into_iter().filter_map(|g| g.get(1).cloned().flatten()).map(|s| prig_plataforma::py::strip(&s).to_string()).collect();
    if let (Some(a), Some(b)) = (limpio.find('{'), limpio.rfind('}')) {
        if b > a {
            let c = prig_plataforma::py::strip(&limpio[a..=b]).to_string();
            if !cands.contains(&c) {
                cands.push(c);
            }
        }
    }
    if !cands.contains(&limpio) {
        cands.push(limpio.clone());
    }
    for c in &cands {
        for intento in [c.clone(), escapar_comillas_internas(c), cerrar_incompleto(c), cerrar_incompleto(&escapar_comillas_internas(c))] {
            if let Some(d) = intentar(&intento) {
                return Ok(d);
            }
        }
    }
    if let Some(t) = e.titulo.buscar(&limpio).and_then(|g| g.get(1).cloned().flatten()) {
        let enunciado = e.enunciado.buscar(&limpio).and_then(|g| g.get(1).cloned().flatten()).map(|s| prig_plataforma::py::strip(&s).to_string()).unwrap_or_else(|| "Resuelve el desafío propuesto.".into());
        let nivel = e.nivel.buscar(&limpio).and_then(|g| g.get(1).cloned().flatten()).map(|s| prig_plataforma::py::strip(&s).to_string()).unwrap_or_else(|| "intermedio".into());
        let paginas: Vec<Valor> = e
            .paginas
            .todos(&limpio)
            .into_iter()
            .map(|g| {
                let n = g.get(1).cloned().flatten().unwrap_or_default();
                let c = g.get(2).cloned().flatten().unwrap_or_default().replace("\\n", "\n");
                Valor::Mapa(Mapa::new().con("nombre", n).con("contenido", c))
            })
            .collect();
        if !paginas.is_empty() {
            return Ok(Mapa::new()
                .con("titulo", prig_plataforma::py::strip(&t))
                .con("enunciado", enunciado)
                .con("nivel", nivel)
                .con("conceptos", Valor::Lista(vec![Valor::Texto("algoritmos".into())]))
                .con("paginas", Valor::Lista(paginas.clone()))
                .con("referencia", Valor::Lista(paginas))
                .con("pruebas", Valor::Lista(vec![Valor::Texto("assert True".into())])));
        }
    }
    Err(format!("No se pudo extraer un JSON válido de la respuesta del modelo: {}...", limpio.chars().take(160).collect::<String>()))
}

// =========================================================================== ast.literal_eval

/// `ast.literal_eval` de los literales que puede escribir un modelo: dicts, listas, tuplas, cadenas con comillas
/// simples o dobles (y sus escapes), números, `True`, `False` y `None`
pub fn literal_eval(t: &str) -> Result<Valor, String> {
    let c: Vec<char> = t.chars().collect();
    let mut p = Lit { c: &c, i: 0 };
    p.blancos();
    let v = p.valor()?;
    p.blancos();
    if p.i != c.len() {
        return Err("malformed node or string".into());
    }
    Ok(v)
}

struct Lit<'a> {
    c: &'a [char],
    i: usize,
}

impl Lit<'_> {
    fn blancos(&mut self) {
        while self.i < self.c.len() {
            match self.c[self.i] {
                ' ' | '\t' | '\n' | '\r' => self.i += 1,
                '\\' if self.c.get(self.i + 1) == Some(&'\n') => self.i += 2,
                '#' => {
                    while self.i < self.c.len() && self.c[self.i] != '\n' {
                        self.i += 1;
                    }
                }
                _ => break,
            }
        }
    }

    fn mal<T>(&self) -> Result<T, String> {
        Err("malformed node or string".into())
    }

    fn valor(&mut self) -> Result<Valor, String> {
        let Some(&ch) = self.c.get(self.i) else { return self.mal() };
        match ch {
            '{' => self.secuencia('}', true),
            '[' => self.secuencia(']', false),
            '(' => self.secuencia(')', false),
            '"' | '\'' => {
                // cadenas pegadas: 'a' 'b' es 'ab'
                let mut s = self.cadena()?;
                loop {
                    let guardado = self.i;
                    self.blancos();
                    if matches!(self.c.get(self.i), Some('"') | Some('\'')) {
                        s.push_str(&self.cadena()?);
                    } else {
                        self.i = guardado;
                        return Ok(Valor::Texto(s));
                    }
                }
            }
            '-' | '+' | '0'..='9' | '.' => self.numero(),
            _ => {
                let ini = self.i;
                while self.i < self.c.len() && (self.c[self.i].is_alphanumeric() || self.c[self.i] == '_') {
                    self.i += 1;
                }
                match self.c[ini..self.i].iter().collect::<String>().as_str() {
                    "True" => Ok(Valor::Bool(true)),
                    "False" => Ok(Valor::Bool(false)),
                    "None" => Ok(Valor::Nulo),
                    _ => self.mal(),
                }
            }
        }
    }

    fn numero(&mut self) -> Result<Valor, String> {
        let ini = self.i;
        if matches!(self.c[self.i], '-' | '+') {
            self.i += 1;
            self.blancos();
        }
        let cuerpo = self.i;
        while self.i < self.c.len() && (self.c[self.i].is_ascii_alphanumeric() || matches!(self.c[self.i], '.' | '_') || (matches!(self.c[self.i], '+' | '-') && matches!(self.c[self.i - 1], 'e' | 'E'))) {
            self.i += 1;
        }
        let neg = self.c[ini] == '-';
        let t: String = self.c[cuerpo..self.i].iter().filter(|c| **c != '_').collect();
        if let Ok(n) = t.parse::<i128>() {
            return Ok(Valor::Entero(if neg { -n } else { n }));
        }
        match t.parse::<f64>() {
            Ok(r) if !t.is_empty() => Ok(Valor::Real(if neg { -r } else { r })),
            _ => self.mal(),
        }
    }

    fn cadena(&mut self) -> Result<String, String> {
        let q = self.c[self.i];
        let triple = self.c.get(self.i + 1) == Some(&q) && self.c.get(self.i + 2) == Some(&q);
        self.i += if triple { 3 } else { 1 };
        let mut s = String::new();
        loop {
            let Some(&ch) = self.c.get(self.i) else { return self.mal() };
            if ch == q && (!triple || (self.c.get(self.i + 1) == Some(&q) && self.c.get(self.i + 2) == Some(&q))) {
                self.i += if triple { 3 } else { 1 };
                return Ok(s);
            }
            if ch == '\n' && !triple {
                return self.mal();
            }
            if ch == '\\' {
                let Some(&e) = self.c.get(self.i + 1) else { return self.mal() };
                self.i += 2;
                match e {
                    'n' => s.push('\n'),
                    't' => s.push('\t'),
                    'r' => s.push('\r'),
                    '0' => s.push('\0'),
                    'a' => s.push('\u{7}'),
                    'b' => s.push('\u{8}'),
                    'f' => s.push('\u{c}'),
                    'v' => s.push('\u{b}'),
                    '\\' | '\'' | '"' => s.push(e),
                    '\n' => {}
                    'x' | 'u' | 'U' => {
                        let n = match e {
                            'x' => 2,
                            'u' => 4,
                            _ => 8,
                        };
                        let h: String = self.c.get(self.i..self.i + n).map(|x| x.iter().collect()).unwrap_or_default();
                        let Some(ch) = u32::from_str_radix(&h, 16).ok().and_then(char::from_u32) else { return self.mal() };
                        s.push(ch);
                        self.i += n;
                    }
                    otro => {
                        s.push('\\');
                        s.push(otro);
                    }
                }
                continue;
            }
            s.push(ch);
            self.i += 1;
        }
    }

    fn secuencia(&mut self, cierre: char, dict: bool) -> Result<Valor, String> {
        self.i += 1;
        let (mut l, mut m) = (Vec::new(), Mapa::new());
        loop {
            self.blancos();
            if self.c.get(self.i) == Some(&cierre) {
                self.i += 1;
                return Ok(if dict { Valor::Mapa(m) } else { Valor::Lista(l) });
            }
            let v = self.valor()?;
            self.blancos();
            if dict {
                if self.c.get(self.i) != Some(&':') {
                    return self.mal();
                }
                self.i += 1;
                self.blancos();
                let x = self.valor()?;
                m.poner(v.texto_py(), x);
            } else {
                l.push(v);
            }
            self.blancos();
            match self.c.get(self.i) {
                Some(',') => self.i += 1,
                Some(c) if *c == cierre => {}
                _ => return self.mal(),
            }
        }
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn repara_lo_de_siempre() {
        let r = |t: &str| reparar(t).map(|m| prig_recursos::json::escribir_compacto(&Valor::Mapa(m)));
        assert_eq!(r("```json\n{\"a\": 1,}\n```").unwrap(), "{\"a\": 1}");
        assert_eq!(r("<think>x</think>{'a': True, 'b': None}").unwrap(), "{\"a\": true, \"b\": null}");
        assert_eq!(r("Aquí: {\"a\": \"dice \"hola\" y\", \"b\": 2}").unwrap(), "{\"a\": \"dice \\\"hola\\\" y\", \"b\": 2}");
        assert_eq!(r("{\"a\": [1, 2").unwrap(), "{\"a\": [1, 2]}");
        assert_eq!(r("{\"code\": \"x = 1\ny = 2\"}").unwrap(), "{\"code\": \"x = 1\\ny = 2\"}");
        assert_eq!(r("[{\"a\": 1}]").unwrap(), "{\"a\": 1}");
        assert!(r("   ").unwrap_err().contains("vacía"));
        assert!(r("nada de json").unwrap_err().starts_with("No se pudo extraer"));
        assert_eq!(literal_eval("{'a': (1, -2.5), \"b\": 'x' 'y'}").map(|v| prig_recursos::json::escribir_compacto(&v)).unwrap(), "{\"a\": [1, -2.5], \"b\": \"xy\"}");
    }
}

/// Para comparar con Python: cada línea de `PRIG_JSON_CASOS` (un JSON con el texto) reparada
#[cfg(test)]
#[test]
#[ignore]
fn reparar_casos() {
    let Ok(f) = std::env::var("PRIG_JSON_CASOS") else { return };
    for l in std::fs::read_to_string(f).unwrap().lines() {
        let t = json::leer(l).unwrap().texto_py();
        let r = match reparar(&t) {
            Ok(m) => Valor::Mapa(Mapa::new().con("ok", m)),
            Err(e) => Valor::Mapa(Mapa::new().con("error", e)),
        };
        println!("{}", json::escribir_linea(&r));
    }
}
