//! YAML como PyYAML (`yaml.safe_load` y `yaml.safe_dump(allow_unicode=True, sort_keys=False, width=…)`), que es lo
//! que leen y escriben los repositorios de Prig Hub. Leer: el analizador de `yaml-rust` y, encima, la resolución de
//! YAML 1.1 de PyYAML (yes/no/on/off son booleanos, `0o17`… no, `017` sí es octal, `1e5` es texto, `~` es nulo…).
//! Escribir: el emisor de PyYAML portado (qué estilo lleva cada escalar, dónde se parte una línea larga).
//!
//! Desvíos escritos: una fecha (`2024-01-05`) se lee como el texto de `str(date)`, y al volver a escribirla va entre
//! comillas; las claves que no son texto pasan a texto; el número de línea de un YAML mal escrito puede no ser el de
//! PyYAML (cada analizador se da cuenta en un sitio); al leer, U+2028, U+2029 y U+0085 no son saltos de línea (YAML 1.2,
//! como `yaml-rust`), así que una comilla simple partida justo ahí se lee con un espacio de más.

use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::collections::HashMap;
use std::sync::LazyLock;
use yaml_rust::parser::{Event, MarkedEventReceiver, Parser};
use yaml_rust::scanner::{Marker, TScalarStyle, TokenType};

/// Un YAML mal escrito: la línea (desde 1) donde se vio el problema, si se sabe
#[derive(Debug, Clone)]
pub struct ErrorYaml {
    pub linea: Option<usize>,
    pub mensaje: String,
}

// ---------------------------------------------------------------------------------------------- resolver (1.1)

static BOOL: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$").unwrap());
static FLOAT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(concat!(
        r"^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?",
        r"|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?",
        r"|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*",
        r"|[-+]?\.(?:inf|Inf|INF)",
        r"|\.(?:nan|NaN|NAN))$"
    ))
    .unwrap()
});
static INT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(concat!(
        r"^(?:[-+]?0b[0-1_]+",
        r"|[-+]?0[0-7_]+",
        r"|[-+]?(?:0|[1-9][0-9_]*)",
        r"|[-+]?0x[0-9a-fA-F_]+",
        r"|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$"
    ))
    .unwrap()
});
static MERGE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(?:<<)$").unwrap());
static NULL: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(?:~|null|Null|NULL|)$").unwrap());
static TIMESTAMP: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(concat!(
        r"^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]",
        r"|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?",
        r"(?:[Tt]|[ \t]+)[0-9][0-9]?",
        r":[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?",
        r"(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$"
    ))
    .unwrap()
});
static VALUE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(?:=)$").unwrap());
static PARTES_FECHA: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(concat!(
        r"^(?P<year>[0-9][0-9][0-9][0-9])-(?P<month>[0-9][0-9]?)-(?P<day>[0-9][0-9]?)",
        r"(?:(?:[Tt]|[ \t]+)(?P<hour>[0-9][0-9]?):(?P<minute>[0-9][0-9]):(?P<second>[0-9][0-9])",
        r"(?:\.(?P<fraction>[0-9]*))?",
        r"(?:[ \t]*(?P<tz>Z|(?P<tz_sign>[-+])(?P<tz_hour>[0-9][0-9]?)(?::(?P<tz_minute>[0-9][0-9]))?))?)?$"
    ))
    .unwrap()
});

#[derive(Clone, Copy, PartialEq, Debug)]
enum Etiqueta {
    Str,
    Bool,
    Int,
    Float,
    Null,
    Merge,
    Timestamp,
    Value,
}

/// `Resolver.resolve(ScalarNode, valor, (True, False))`: la etiqueta de un escalar sin comillas
fn resolver(v: &str) -> Etiqueta {
    let primero = v.chars().next();
    let candidatos: &[(Etiqueta, &LazyLock<Regex>)] = match primero {
        None => &[(Etiqueta::Null, &NULL)],
        Some(c) => match c {
            'y' | 'Y' | 'f' | 'F' | 'o' | 'O' | 't' | 'T' => &[(Etiqueta::Bool, &BOOL)],
            'n' | 'N' => &[(Etiqueta::Bool, &BOOL), (Etiqueta::Null, &NULL)],
            '-' | '+' => &[(Etiqueta::Float, &FLOAT), (Etiqueta::Int, &INT)],
            '.' => &[(Etiqueta::Float, &FLOAT)],
            '0'..='9' => &[(Etiqueta::Float, &FLOAT), (Etiqueta::Int, &INT), (Etiqueta::Timestamp, &TIMESTAMP)],
            '<' => &[(Etiqueta::Merge, &MERGE)],
            '~' => &[(Etiqueta::Null, &NULL)],
            '=' => &[(Etiqueta::Value, &VALUE)],
            _ => &[],
        },
    };
    for (e, re) in candidatos {
        if re.is_match(v) {
            return *e;
        }
    }
    Etiqueta::Str
}

fn entero(v: &str) -> Valor {
    let mut t: String = v.replace('_', "");
    let signo: i128 = if t.starts_with('-') { -1 } else { 1 };
    if t.starts_with(['+', '-']) {
        t.remove(0);
    }
    let n: Option<i128> = if t == "0" {
        Some(0)
    } else if let Some(b) = t.strip_prefix("0b") {
        i128::from_str_radix(b, 2).ok()
    } else if let Some(x) = t.strip_prefix("0x") {
        i128::from_str_radix(x, 16).ok()
    } else if t.starts_with('0') {
        i128::from_str_radix(&t, 8).ok()
    } else if t.contains(':') {
        let mut total: i128 = 0;
        for p in t.split(':') {
            total = total * 60 + p.parse::<i128>().unwrap_or(0);
        }
        Some(total)
    } else {
        t.parse::<i128>().ok()
    };
    match n {
        Some(n) => Valor::Entero(signo * n),
        None => Valor::Texto(v.to_string()),
    }
}

fn real(v: &str) -> Valor {
    let mut t = v.replace('_', "").to_lowercase();
    let signo = if t.starts_with('-') { -1.0 } else { 1.0 };
    if t.starts_with(['+', '-']) {
        t.remove(0);
    }
    let x = if t == ".inf" {
        f64::INFINITY
    } else if t == ".nan" {
        return Valor::Real(f64::NAN);
    } else if t.contains(':') {
        let mut total = 0.0;
        for p in t.split(':') {
            total = total * 60.0 + p.parse::<f64>().unwrap_or(0.0);
        }
        total
    } else {
        let t = if t.ends_with('.') { format!("{t}0") } else { t };
        let t = if t.starts_with('.') { format!("0{t}") } else { t };
        t.parse::<f64>().unwrap_or(0.0)
    };
    Valor::Real(signo * x)
}

/// `str(date)` o `str(datetime)` de lo que construye PyYAML
fn fecha(v: &str) -> Valor {
    let Some(c) = PARTES_FECHA.captures(v) else { return Valor::Texto(v.to_string()) };
    let n = |k: &str| c.name(k).map(|m| m.as_str().parse::<i64>().unwrap_or(0));
    let (a, m, d) = (n("year").unwrap_or(0), n("month").unwrap_or(0), n("day").unwrap_or(0));
    let base = format!("{a:04}-{m:02}-{d:02}");
    let Some(h) = n("hour") else { return Valor::Texto(base) };
    let mut s = format!("{base} {h:02}:{:02}:{:02}", n("minute").unwrap_or(0), n("second").unwrap_or(0));
    if let Some(f) = c.name("fraction").map(|m| m.as_str()).filter(|f| !f.is_empty()) {
        let mut f: String = f.chars().take(6).collect();
        while f.len() < 6 {
            f.push('0');
        }
        if f != "000000" {
            s.push('.');
            s.push_str(&f);
        }
    }
    if let Some(signo) = c.name("tz_sign") {
        let (th, tm) = (n("tz_hour").unwrap_or(0), n("tz_minute").unwrap_or(0));
        s.push_str(&format!("{}{th:02}:{tm:02}", signo.as_str()));
    } else if c.name("tz").is_some() {
        s.push_str("+00:00");
    }
    Valor::Texto(s)
}

fn construir(v: String, estilo: TScalarStyle, etiqueta: Option<TokenType>) -> Valor {
    if let Some(TokenType::Tag(handle, sufijo)) = etiqueta {
        if handle == "!!" {
            return match sufijo.as_str() {
                "str" => Valor::Texto(v),
                "int" => entero(&v),
                "float" => real(&v),
                "bool" => Valor::Bool(matches!(v.to_lowercase().as_str(), "yes" | "true" | "on")),
                "null" => Valor::Nulo,
                _ => Valor::Texto(v),
            };
        }
        return Valor::Texto(v);
    }
    if estilo != TScalarStyle::Plain {
        return Valor::Texto(v);
    }
    match resolver(&v) {
        Etiqueta::Str | Etiqueta::Merge | Etiqueta::Value => Valor::Texto(v),
        Etiqueta::Bool => Valor::Bool(matches!(v.to_lowercase().as_str(), "yes" | "true" | "on")),
        Etiqueta::Int => entero(&v),
        Etiqueta::Float => real(&v),
        Etiqueta::Null => Valor::Nulo,
        Etiqueta::Timestamp => fecha(&v),
    }
}

fn clave_texto(v: &Valor) -> String {
    match v {
        Valor::Texto(t) => t.clone(),
        otro => otro.texto_py(),
    }
}

enum Abierto {
    Lista(Vec<Valor>, usize),
    Mapa(Mapa, Option<String>, usize),
}

#[derive(Default)]
struct Constructor {
    pila: Vec<Abierto>,
    documentos: Vec<Valor>,
    anclas: HashMap<usize, Valor>,
    error: Option<ErrorYaml>,
}

impl Constructor {
    fn colocar(&mut self, v: Valor) {
        match self.pila.last_mut() {
            Some(Abierto::Lista(l, _)) => l.push(v),
            Some(Abierto::Mapa(m, clave, _)) => match clave.take() {
                Some(k) => m.poner(k, v),
                None => *clave = Some(clave_texto(&v)),
            },
            None => self.documentos.push(v),
        }
    }
}

impl MarkedEventReceiver for Constructor {
    fn on_event(&mut self, ev: Event, mark: Marker) {
        match ev {
            Event::Scalar(v, estilo, ancla, etiqueta) => {
                let valor = construir(v, estilo, etiqueta);
                if ancla > 0 {
                    self.anclas.insert(ancla, valor.clone());
                }
                self.colocar(valor);
            }
            Event::SequenceStart(a) => self.pila.push(Abierto::Lista(Vec::new(), a)),
            Event::MappingStart(a) => self.pila.push(Abierto::Mapa(Mapa::new(), None, a)),
            Event::SequenceEnd | Event::MappingEnd => {
                let (v, a) = match self.pila.pop() {
                    Some(Abierto::Lista(l, a)) => (Valor::Lista(l), a),
                    Some(Abierto::Mapa(m, _, a)) => (Valor::Mapa(m), a),
                    None => return,
                };
                if a > 0 {
                    self.anclas.insert(a, v.clone());
                }
                self.colocar(v);
            }
            Event::Alias(a) => match self.anclas.get(&a).cloned() {
                Some(v) => self.colocar(v),
                None => {
                    if self.error.is_none() {
                        self.error = Some(ErrorYaml { linea: Some(mark.line()), mensaje: "found undefined alias".into() });
                    }
                    self.colocar(Valor::Nulo)
                }
            },
            _ => {}
        }
    }
}

/// `yaml.safe_load(texto)`: None si el flujo está vacío
pub fn cargar(texto: &str) -> Result<Valor, ErrorYaml> {
    let mut c = Constructor::default();
    let mut p = Parser::new(texto.chars());
    p.load(&mut c, true).map_err(|e| ErrorYaml { linea: Some(e.marker().line()), mensaje: e.to_string() })?;
    if let Some(e) = c.error {
        return Err(e);
    }
    match c.documentos.len() {
        0 => Ok(Valor::Nulo),
        1 => Ok(c.documentos.pop().unwrap_or(Valor::Nulo)),
        _ => Err(ErrorYaml { linea: None, mensaje: "expected a single document in the stream".into() }),
    }
}

// ---------------------------------------------------------------------------------------------- emisor

struct Analisis {
    vacio: bool,
    multilinea: bool,
    plano_flujo: bool,
    plano_bloque: bool,
    comilla_simple: bool,
}

fn es_espacio_o_fin(c: Option<char>) -> bool {
    matches!(c, None | Some('\0' | ' ' | '\t' | '\r' | '\n' | '\u{85}' | '\u{2028}' | '\u{2029}'))
}

fn es_salto(c: char) -> bool {
    matches!(c, '\n' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

/// `Emitter.analyze_scalar` (con `allow_unicode`)
fn analizar(s: &[char]) -> Analisis {
    if s.is_empty() {
        return Analisis { vacio: true, multilinea: false, plano_flujo: false, plano_bloque: true, comilla_simple: true };
    }
    let (mut ind_bloque, mut ind_flujo, mut saltos, mut especiales) = (false, false, false, false);
    let (mut esp_ini, mut salto_ini, mut esp_fin, mut salto_fin, mut salto_esp, mut esp_salto) = (false, false, false, false, false, false);
    let texto: String = s.iter().collect();
    if texto.starts_with("---") || texto.starts_with("...") {
        ind_bloque = true;
        ind_flujo = true;
    }
    let mut precedido = true;
    let mut seguido = s.len() == 1 || es_espacio_o_fin(s.get(1).copied());
    let (mut esp_previo, mut salto_previo) = (false, false);
    for (i, &ch) in s.iter().enumerate() {
        if i == 0 {
            if "#,[]{}&*!|>'\"%@`".contains(ch) {
                ind_flujo = true;
                ind_bloque = true;
            }
            if ch == '?' || ch == ':' {
                ind_flujo = true;
                if seguido {
                    ind_bloque = true;
                }
            }
            if ch == '-' && seguido {
                ind_flujo = true;
                ind_bloque = true;
            }
        } else {
            if ",?[]{}".contains(ch) {
                ind_flujo = true;
            }
            if ch == ':' {
                ind_flujo = true;
                if seguido {
                    ind_bloque = true;
                }
            }
            if ch == '#' && precedido {
                ind_flujo = true;
                ind_bloque = true;
            }
        }
        if es_salto(ch) {
            saltos = true;
        }
        if !(ch == '\n' || ('\x20'..='\x7E').contains(&ch)) {
            let unicode = (ch == '\u{85}' || ('\u{A0}'..='\u{D7FF}').contains(&ch) || ('\u{E000}'..='\u{FFFD}').contains(&ch) || ('\u{10000}'..'\u{10FFFF}').contains(&ch))
                && ch != '\u{FEFF}';
            if !unicode {
                especiales = true;
            }
        }
        if ch == ' ' {
            if i == 0 {
                esp_ini = true;
            }
            if i == s.len() - 1 {
                esp_fin = true;
            }
            if salto_previo {
                salto_esp = true;
            }
            esp_previo = true;
            salto_previo = false;
        } else if es_salto(ch) {
            if i == 0 {
                salto_ini = true;
            }
            if i == s.len() - 1 {
                salto_fin = true;
            }
            if esp_previo {
                esp_salto = true;
            }
            esp_previo = false;
            salto_previo = true;
        } else {
            esp_previo = false;
            salto_previo = false;
        }
        precedido = es_espacio_o_fin(Some(ch));
        seguido = i + 2 >= s.len() || es_espacio_o_fin(s.get(i + 2).copied());
    }
    let (mut plano_flujo, mut plano_bloque, mut simple) = (true, true, true);
    if esp_ini || salto_ini || esp_fin || salto_fin {
        plano_flujo = false;
        plano_bloque = false;
    }
    if salto_esp {
        plano_flujo = false;
        plano_bloque = false;
        simple = false;
    }
    if esp_salto || especiales {
        plano_flujo = false;
        plano_bloque = false;
        simple = false;
    }
    if saltos {
        plano_flujo = false;
        plano_bloque = false;
    }
    if ind_flujo {
        plano_flujo = false;
    }
    if ind_bloque {
        plano_bloque = false;
    }
    Analisis { vacio: false, multilinea: saltos, plano_flujo, plano_bloque, comilla_simple: simple }
}

#[derive(PartialEq, Clone, Copy)]
enum Estilo {
    Plano,
    Simple,
    Doble,
}

struct Emisor {
    salida: String,
    columna: usize,
    blanco: bool,
    sangrado: bool,
    sangria: Option<usize>,
    sangrias: Vec<Option<usize>>,
    flujo: usize,
    ancho: usize,
}

impl Emisor {
    fn subir(&mut self, flujo: bool, sin_sangria: bool) {
        self.sangrias.push(self.sangria);
        match self.sangria {
            None => self.sangria = Some(if flujo { 2 } else { 0 }),
            Some(n) if !sin_sangria => self.sangria = Some(n + 2),
            _ => {}
        }
    }

    fn bajar(&mut self) {
        self.sangria = self.sangrias.pop().flatten();
    }

    fn escribir(&mut self, t: &str) {
        self.columna += t.chars().count();
        self.salida.push_str(t);
    }

    fn indicador(&mut self, ind: &str, necesita_espacio: bool, blanco: bool, sangrado: bool) {
        if self.blanco || !necesita_espacio {
            self.escribir(ind);
        } else {
            self.escribir(&format!(" {ind}"));
        }
        self.blanco = blanco;
        self.sangrado = self.sangrado && sangrado;
    }

    fn salto(&mut self, t: &str) {
        self.blanco = true;
        self.sangrado = true;
        self.columna = 0;
        self.salida.push_str(t);
    }

    fn sangrar(&mut self) {
        let n = self.sangria.unwrap_or(0);
        if !self.sangrado || self.columna > n || (self.columna == n && !self.blanco) {
            self.salto("\n");
        }
        if self.columna < n {
            self.blanco = true;
            let espacios = " ".repeat(n - self.columna);
            self.salida.push_str(&espacios);
            self.columna = n;
        }
    }

    fn nodo(&mut self, v: &Valor, mapa: bool, clave_simple: bool) {
        match v {
            Valor::Lista(l) if self.flujo > 0 || l.is_empty() => {
                self.indicador("[", true, true, false);
                self.flujo += 1;
                self.subir(true, false);
                for (i, x) in l.iter().enumerate() {
                    if i > 0 {
                        self.indicador(",", false, false, false);
                    }
                    if self.columna > self.ancho {
                        self.sangrar();
                    }
                    self.nodo(x, false, false);
                }
                self.bajar();
                self.flujo -= 1;
                self.indicador("]", false, false, false);
            }
            Valor::Mapa(m) if self.flujo > 0 || m.is_empty() => {
                self.indicador("{", true, true, false);
                self.flujo += 1;
                self.subir(true, false);
                for (i, (k, x)) in m.iter().enumerate() {
                    if i > 0 {
                        self.indicador(",", false, false, false);
                    }
                    if self.columna > self.ancho {
                        self.sangrar();
                    }
                    self.nodo(&Valor::Texto(k.clone()), true, true);
                    self.indicador(":", false, false, false);
                    self.nodo(x, true, false);
                }
                self.bajar();
                self.flujo -= 1;
                self.indicador("}", false, false, false);
            }
            Valor::Lista(l) => {
                let sin_sangria = mapa && !self.sangrado;
                self.subir(false, sin_sangria);
                for x in l {
                    self.sangrar();
                    self.indicador("-", true, false, true);
                    self.nodo(x, false, false);
                }
                self.bajar();
            }
            Valor::Mapa(m) => {
                self.subir(false, false);
                for (k, x) in m.iter() {
                    self.sangrar();
                    let chars: Vec<char> = k.chars().collect();
                    let a = analizar(&chars);
                    // PyYAML cuenta también la etiqueta ya preparada («!!str», 5 caracteres)
                    let simple = chars.len() + 5 < 128 && !a.vacio && !a.multilinea;
                    if simple {
                        self.nodo(&Valor::Texto(k.clone()), true, true);
                        self.indicador(":", false, false, false);
                    } else {
                        self.indicador("?", true, false, true);
                        self.nodo(&Valor::Texto(k.clone()), true, false);
                        self.sangrar();
                        self.indicador(":", true, false, true);
                    }
                    self.nodo(x, true, false);
                }
                self.bajar();
            }
            escalar => {
                self.subir(true, false);
                self.escalar(escalar, clave_simple);
                self.bajar();
            }
        }
    }

    fn escalar(&mut self, v: &Valor, clave_simple: bool) {
        let (texto, implicito) = match v {
            Valor::Texto(t) => (t.clone(), resolver(t) == Etiqueta::Str),
            Valor::Nulo => ("null".to_string(), true),
            Valor::Bool(b) => ((if *b { "true" } else { "false" }).to_string(), true),
            Valor::Entero(n) => (n.to_string(), true),
            Valor::Real(x) => (texto_real(*x), true),
            _ => (String::new(), true),
        };
        let chars: Vec<char> = texto.chars().collect();
        let a = analizar(&chars);
        let mut estilo = Estilo::Doble;
        if implicito
            && !(clave_simple && (a.vacio || a.multilinea))
            && ((self.flujo > 0 && a.plano_flujo) || (self.flujo == 0 && a.plano_bloque))
        {
            estilo = Estilo::Plano;
        } else if a.comilla_simple && !(clave_simple && a.multilinea) {
            estilo = Estilo::Simple;
        }
        let partir = !clave_simple;
        match estilo {
            Estilo::Plano => self.plano(&chars, partir),
            Estilo::Simple => self.simple(&chars, partir),
            Estilo::Doble => self.doble(&chars, partir),
        }
    }

    fn plano(&mut self, t: &[char], partir: bool) {
        if t.is_empty() {
            return;
        }
        if !self.blanco {
            self.escribir(" ");
        }
        self.blanco = false;
        self.sangrado = false;
        let (mut espacios, mut saltos) = (false, false);
        let (mut ini, mut fin) = (0usize, 0usize);
        while fin <= t.len() {
            let ch = t.get(fin).copied();
            if espacios {
                if ch != Some(' ') {
                    if ini + 1 == fin && self.columna > self.ancho && partir {
                        self.sangrar();
                        self.blanco = false;
                        self.sangrado = false;
                    } else {
                        let d: String = t[ini..fin].iter().collect();
                        self.escribir(&d);
                    }
                    ini = fin;
                }
            } else if saltos {
                if !ch.is_some_and(es_salto) {
                    if t[ini] == '\n' {
                        self.salto("\n");
                    }
                    for &br in &t[ini..fin] {
                        self.salto(&br.to_string());
                    }
                    self.sangrar();
                    self.blanco = false;
                    self.sangrado = false;
                    ini = fin;
                }
            } else if ch.is_none_or(|c| c == ' ' || es_salto(c)) {
                let d: String = t[ini..fin].iter().collect();
                self.escribir(&d);
                ini = fin;
            }
            if let Some(c) = ch {
                espacios = c == ' ';
                saltos = es_salto(c);
            }
            fin += 1;
        }
    }

    fn simple(&mut self, t: &[char], partir: bool) {
        self.indicador("'", true, false, false);
        let (mut espacios, mut saltos) = (false, false);
        let (mut ini, mut fin) = (0usize, 0usize);
        while fin <= t.len() {
            let ch = t.get(fin).copied();
            if espacios {
                if ch != Some(' ') {
                    if ini + 1 == fin && self.columna > self.ancho && partir && ini != 0 && fin != t.len() {
                        self.sangrar();
                    } else {
                        let d: String = t[ini..fin].iter().collect();
                        self.escribir(&d);
                    }
                    ini = fin;
                }
            } else if saltos {
                if !ch.is_some_and(es_salto) {
                    if t[ini] == '\n' {
                        self.salto("\n");
                    }
                    for &br in &t[ini..fin] {
                        self.salto(&br.to_string());
                    }
                    self.sangrar();
                    ini = fin;
                }
            } else if ch.is_none_or(|c| c == ' ' || es_salto(c) || c == '\'') && ini < fin {
                let d: String = t[ini..fin].iter().collect();
                self.escribir(&d);
                ini = fin;
            }
            if ch == Some('\'') {
                self.escribir("''");
                ini = fin + 1;
            }
            if let Some(c) = ch {
                espacios = c == ' ';
                saltos = es_salto(c);
            }
            fin += 1;
        }
        self.indicador("'", false, false, false);
    }

    fn doble(&mut self, t: &[char], partir: bool) {
        self.indicador("\"", true, false, false);
        let (mut ini, mut fin) = (0usize, 0usize);
        while fin <= t.len() {
            let ch = t.get(fin).copied();
            let escapar = match ch {
                None => true,
                Some(c) => {
                    "\"\\\u{85}\u{2028}\u{2029}\u{FEFF}".contains(c)
                        || !(('\x20'..='\x7E').contains(&c) || ('\u{A0}'..='\u{D7FF}').contains(&c) || ('\u{E000}'..='\u{FFFD}').contains(&c))
                }
            };
            if escapar {
                if ini < fin {
                    let d: String = t[ini..fin].iter().collect();
                    self.escribir(&d);
                    ini = fin;
                }
                if let Some(c) = ch {
                    let d = match c {
                        '\0' => "\\0".to_string(),
                        '\x07' => "\\a".into(),
                        '\x08' => "\\b".into(),
                        '\x09' => "\\t".into(),
                        '\x0A' => "\\n".into(),
                        '\x0B' => "\\v".into(),
                        '\x0C' => "\\f".into(),
                        '\x0D' => "\\r".into(),
                        '\x1B' => "\\e".into(),
                        '"' => "\\\"".into(),
                        '\\' => "\\\\".into(),
                        '\u{85}' => "\\N".into(),
                        '\u{A0}' => "\\_".into(),
                        '\u{2028}' => "\\L".into(),
                        '\u{2029}' => "\\P".into(),
                        c if (c as u32) <= 0xFF => format!("\\x{:02X}", c as u32),
                        c if (c as u32) <= 0xFFFF => format!("\\u{:04X}", c as u32),
                        c => format!("\\U{:08X}", c as u32),
                    };
                    self.escribir(&d);
                    ini = fin + 1;
                }
            }
            if 0 < fin && fin + 1 < t.len() && (ch == Some(' ') || ini >= fin) && self.columna as isize + fin as isize - ini as isize > self.ancho as isize && partir {
                let mut d: String = if ini < fin { t[ini..fin].iter().collect() } else { String::new() };
                d.push('\\');
                if ini < fin {
                    ini = fin;
                }
                self.escribir(&d);
                self.sangrar();
                self.blanco = false;
                self.sangrado = false;
                if t[ini] == ' ' {
                    self.escribir("\\");
                }
            }
            fin += 1;
        }
        self.indicador("\"", false, false, false);
    }
}

/// `represent_float`: `repr(x).lower()`, con «.0» delante de la «e» si no lleva punto
fn texto_real(x: f64) -> String {
    if x.is_nan() {
        return ".nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { ".inf".into() } else { "-.inf".into() };
    }
    let t = Valor::Real(x).repr_py().to_lowercase();
    if !t.contains('.') && t.contains('e') {
        t.replacen('e', ".0e", 1)
    } else {
        t
    }
}

/// `yaml.safe_dump(v, allow_unicode=True, sort_keys=False, width=ancho)`
pub fn volcar(v: &Valor, ancho: usize) -> String {
    let mut e = Emisor { salida: String::new(), columna: 0, blanco: true, sangrado: true, sangria: None, sangrias: Vec::new(), flujo: 0, ancho: if ancho > 4 { ancho } else { 80 } };
    e.nodo(v, false, false);
    if matches!(v, Valor::Texto(_) | Valor::Nulo | Valor::Bool(_) | Valor::Entero(_) | Valor::Real(_)) {
        // Un escalar suelto deja el documento abierto: PyYAML cierra con «...»
        let plano = !e.salida.ends_with('\'') && !e.salida.ends_with('"');
        if plano {
            e.sangrar();
            e.indicador("...", true, false, false);
        }
    }
    e.sangrar();
    e.salida
}
