//! `ast.unparse` de CPython 3.12 (Lib/ast.py, `_Unparser`) para expresiones y argumentos: las firmas, los
//! receptores de las llamadas y los tipos de excepción del banco se escriben así, y las firmas llegan al texto
//! de las unidades guardadas. Traducción literal: mismas precedencias (con la tabla por nodo), mismas
//! comillas, mismos f-strings.

use std::collections::HashMap;

use super::{Arbol, Constante, Id, OpBin, OpBool, OpCmp, OpUn, K};
use crate::py::cadena::{es_imprimible, repr_bytes, repr_str, unicode_escape};
use crate::py::numero::{repr_float, repr_imaginario};

const NAMED_EXPR: u8 = 1;
const TUPLE: u8 = 2;
const YIELD: u8 = 3;
const TEST: u8 = 4;
const OR: u8 = 5;
const AND: u8 = 6;
const NOT: u8 = 7;
const CMP: u8 = 8;
const EXPR: u8 = 9;
const BOR: u8 = 9;
const BXOR: u8 = 10;
const BAND: u8 = 11;
const SHIFT: u8 = 12;
const ARITH: u8 = 13;
const TERM: u8 = 14;
const FACTOR: u8 = 15;
const POWER: u8 = 16;
const AWAIT: u8 = 17;
const ATOM: u8 = 18;

fn siguiente(p: u8) -> u8 {
    if p >= ATOM {
        ATOM
    } else {
        p + 1
    }
}

const INFSTR: &str = "1e309";
const COMILLAS: [&str; 4] = ["'", "\"", "\"\"\"", "'''"];
const TRIPLES: [&str; 2] = ["\"\"\"", "'''"];

struct Unparser<'a> {
    a: &'a Arbol,
    s: String,
    prec: HashMap<Id, u8>,
}

/// `ast.unparse(nodo)`.
pub fn unparse(a: &Arbol, id: Id) -> String {
    let mut u = Unparser { a, s: String::new(), prec: HashMap::new() };
    u.traverse(id);
    u.s
}

impl<'a> Unparser<'a> {
    fn w(&mut self, t: &str) {
        self.s.push_str(t);
    }

    fn p(&self, id: Id) -> u8 {
        *self.prec.get(&id).unwrap_or(&TEST)
    }

    fn set(&mut self, p: u8, id: Id) {
        self.prec.insert(id, p);
    }

    fn abre(&mut self, p: u8, id: Id) -> bool {
        let parens = self.p(id) > p;
        if parens {
            self.w("(");
        }
        parens
    }

    fn cierra(&mut self, parens: bool) {
        if parens {
            self.w(")");
        }
    }

    fn intercalar(&mut self, sep: &str, ids: &[Id]) {
        for (i, x) in ids.iter().enumerate() {
            if i > 0 {
                self.w(sep);
            }
            self.traverse(*x);
        }
    }

    fn items_view(&mut self, ids: &[Id]) {
        if ids.len() == 1 {
            self.traverse(ids[0]);
            self.w(",");
        } else {
            self.intercalar(", ", ids);
        }
    }

    fn constante(&mut self, c: &Constante) {
        let texto = match c {
            Constante::Flotante(f) => repr_float(*f).replace("inf", INFSTR).replace("nan", &format!("({INFSTR}-{INFSTR})")),
            Constante::Imaginario(f) => repr_imaginario(*f).replace("inf", INFSTR).replace("nan", &format!("({INFSTR}-{INFSTR})")),
            Constante::Cadena(s) => repr_str(s),
            Constante::Bytes(b) => repr_bytes(b),
            Constante::Entero(n) => n.clone(),
            Constante::Nada => "None".into(),
            Constante::Verdadero => "True".into(),
            Constante::Falso => "False".into(),
            Constante::Elipsis => "...".into(),
        };
        self.w(&texto);
    }

    fn traverse(&mut self, id: Id) {
        let a = self.a;
        match a.k(id).clone() {
            K::NamedExpr { target, value } => {
                let par = self.abre(NAMED_EXPR, id);
                self.set(ATOM, target);
                self.set(ATOM, value);
                self.traverse(target);
                self.w(" := ");
                self.traverse(value);
                self.cierra(par);
            }
            K::Await { value } => {
                let par = self.abre(AWAIT, id);
                self.w("await ");
                self.set(ATOM, value);
                self.traverse(value);
                self.cierra(par);
            }
            K::Yield { value } => {
                let par = self.abre(YIELD, id);
                self.w("yield");
                if let Some(v) = value {
                    self.w(" ");
                    self.set(ATOM, v);
                    self.traverse(v);
                }
                self.cierra(par);
            }
            K::YieldFrom { value } => {
                let par = self.abre(YIELD, id);
                self.w("yield from ");
                self.set(ATOM, value);
                self.traverse(value);
                self.cierra(par);
            }
            K::JoinedStr { .. } => self.joined_str(id),
            K::FormattedValue { .. } => self.formatted_value(id),
            K::Name { id: n, .. } => self.w(&n),
            K::Constant { value, kind_u } => match value {
                Constante::Elipsis => self.w("..."),
                v => {
                    if kind_u {
                        self.w("u");
                    }
                    self.constante(&v);
                }
            },
            K::List { elts, .. } => {
                self.w("[");
                self.intercalar(", ", &elts);
                self.w("]");
            }
            K::ListComp { elt, generators } => {
                self.w("[");
                self.traverse(elt);
                for g in generators {
                    self.traverse(g);
                }
                self.w("]");
            }
            K::GeneratorExp { elt, generators } => {
                self.w("(");
                self.traverse(elt);
                for g in generators {
                    self.traverse(g);
                }
                self.w(")");
            }
            K::SetComp { elt, generators } => {
                self.w("{");
                self.traverse(elt);
                for g in generators {
                    self.traverse(g);
                }
                self.w("}");
            }
            K::DictComp { key, value, generators } => {
                self.w("{");
                self.traverse(key);
                self.w(": ");
                self.traverse(value);
                for g in generators {
                    self.traverse(g);
                }
                self.w("}");
            }
            K::Comprehension { target, iter, ifs, is_async } => {
                self.w(if is_async { " async for " } else { " for " });
                self.set(TUPLE, target);
                self.traverse(target);
                self.w(" in ");
                self.set(siguiente(TEST), iter);
                for i in &ifs {
                    self.set(siguiente(TEST), *i);
                }
                self.traverse(iter);
                for i in ifs {
                    self.w(" if ");
                    self.traverse(i);
                }
            }
            K::IfExp { test, body, orelse } => {
                let par = self.abre(TEST, id);
                self.set(siguiente(TEST), body);
                self.set(siguiente(TEST), test);
                self.traverse(body);
                self.w(" if ");
                self.traverse(test);
                self.w(" else ");
                self.set(TEST, orelse);
                self.traverse(orelse);
                self.cierra(par);
            }
            K::Set { elts } => {
                if elts.is_empty() {
                    self.w("{*()}");
                } else {
                    self.w("{");
                    self.intercalar(", ", &elts);
                    self.w("}");
                }
            }
            K::Dict { keys, values } => {
                self.w("{");
                for (i, (k, v)) in keys.iter().zip(values.iter()).enumerate() {
                    if i > 0 {
                        self.w(", ");
                    }
                    match k {
                        None => {
                            self.w("**");
                            self.set(EXPR, *v);
                            self.traverse(*v);
                        }
                        Some(k) => {
                            self.traverse(*k);
                            self.w(": ");
                            self.traverse(*v);
                        }
                    }
                }
                self.w("}");
            }
            K::Tuple { elts, .. } => {
                let par = elts.is_empty() || self.p(id) > TUPLE;
                if par {
                    self.w("(");
                }
                self.items_view(&elts);
                if par {
                    self.w(")");
                }
            }
            K::UnaryOp { op, operand } => {
                let (texto, prec) = match op {
                    OpUn::Invert => ("~", FACTOR),
                    OpUn::Not => ("not", NOT),
                    OpUn::UAdd => ("+", FACTOR),
                    OpUn::USub => ("-", FACTOR),
                };
                let par = self.abre(prec, id);
                self.w(texto);
                if prec != FACTOR {
                    self.w(" ");
                }
                self.set(prec, operand);
                self.traverse(operand);
                self.cierra(par);
            }
            K::BinOp { left, op, right } => {
                let (texto, prec) = match op {
                    OpBin::Add => ("+", ARITH),
                    OpBin::Sub => ("-", ARITH),
                    OpBin::Mult => ("*", TERM),
                    OpBin::MatMult => ("@", TERM),
                    OpBin::Div => ("/", TERM),
                    OpBin::Mod => ("%", TERM),
                    OpBin::LShift => ("<<", SHIFT),
                    OpBin::RShift => (">>", SHIFT),
                    OpBin::BitOr => ("|", BOR),
                    OpBin::BitXor => ("^", BXOR),
                    OpBin::BitAnd => ("&", BAND),
                    OpBin::FloorDiv => ("//", TERM),
                    OpBin::Pow => ("**", POWER),
                };
                let par = self.abre(prec, id);
                let (pi, pd) = if op == OpBin::Pow { (siguiente(prec), prec) } else { (prec, siguiente(prec)) };
                self.set(pi, left);
                self.traverse(left);
                self.w(&format!(" {texto} "));
                self.set(pd, right);
                self.traverse(right);
                self.cierra(par);
            }
            K::Compare { left, ops, comparators } => {
                let par = self.abre(CMP, id);
                self.set(siguiente(CMP), left);
                for c in &comparators {
                    self.set(siguiente(CMP), *c);
                }
                self.traverse(left);
                for (o, e) in ops.iter().zip(comparators.iter()) {
                    let t = match o {
                        OpCmp::Eq => "==",
                        OpCmp::NotEq => "!=",
                        OpCmp::Lt => "<",
                        OpCmp::LtE => "<=",
                        OpCmp::Gt => ">",
                        OpCmp::GtE => ">=",
                        OpCmp::Is => "is",
                        OpCmp::IsNot => "is not",
                        OpCmp::In => "in",
                        OpCmp::NotIn => "not in",
                    };
                    self.w(&format!(" {t} "));
                    self.traverse(*e);
                }
                self.cierra(par);
            }
            K::BoolOp { op, values } => {
                let (texto, mut prec) = match op {
                    OpBool::And => ("and", AND),
                    OpBool::Or => ("or", OR),
                };
                let par = self.abre(prec, id);
                let sep = format!(" {texto} ");
                for (i, v) in values.iter().enumerate() {
                    if i > 0 {
                        self.w(&sep);
                    }
                    prec = siguiente(prec);
                    self.set(prec, *v);
                    self.traverse(*v);
                }
                self.cierra(par);
            }
            K::Attribute { value, attr, .. } => {
                self.set(ATOM, value);
                self.traverse(value);
                if let K::Constant { value: Constante::Entero(_) | Constante::Verdadero | Constante::Falso, .. } = a.k(value) {
                    self.w(" ");
                }
                self.w(".");
                self.w(&attr);
            }
            K::Call { func, args, keywords } => {
                self.set(ATOM, func);
                self.traverse(func);
                self.w("(");
                let mut coma = false;
                for e in args.iter().chain(keywords.iter()) {
                    if coma {
                        self.w(", ");
                    } else {
                        coma = true;
                    }
                    self.traverse(*e);
                }
                self.w(")");
            }
            K::Subscript { value, slice, .. } => {
                self.set(ATOM, value);
                self.traverse(value);
                self.w("[");
                match a.k(slice) {
                    K::Tuple { elts, .. } if !elts.is_empty() => {
                        let elts = elts.clone();
                        self.items_view(&elts);
                    }
                    _ => self.traverse(slice),
                }
                self.w("]");
            }
            K::Starred { value, .. } => {
                self.w("*");
                self.set(EXPR, value);
                self.traverse(value);
            }
            K::Slice { lower, upper, step } => {
                if let Some(l) = lower {
                    self.traverse(l);
                }
                self.w(":");
                if let Some(u) = upper {
                    self.traverse(u);
                }
                if let Some(s) = step {
                    self.w(":");
                    self.traverse(s);
                }
            }
            K::Arg { arg, annotation } => {
                self.w(&arg);
                if let Some(an) = annotation {
                    self.w(": ");
                    self.traverse(an);
                }
            }
            K::Arguments { posonlyargs, args, vararg, kwonlyargs, kw_defaults, kwarg, defaults } => {
                let mut primero = true;
                let todos: Vec<Id> = posonlyargs.iter().chain(args.iter()).copied().collect();
                let faltan = todos.len() - defaults.len();
                for (indice, x) in todos.iter().enumerate() {
                    if primero {
                        primero = false;
                    } else {
                        self.w(", ");
                    }
                    self.traverse(*x);
                    if indice >= faltan {
                        self.w("=");
                        self.traverse(defaults[indice - faltan]);
                    }
                    if indice + 1 == posonlyargs.len() {
                        self.w(", /");
                    }
                }
                if vararg.is_some() || !kwonlyargs.is_empty() {
                    if primero {
                        primero = false;
                    } else {
                        self.w(", ");
                    }
                    self.w("*");
                    if let Some(v) = vararg {
                        if let K::Arg { arg, annotation } = a.k(v).clone() {
                            self.w(&arg);
                            if let Some(an) = annotation {
                                self.w(": ");
                                self.traverse(an);
                            }
                        }
                    }
                }
                for (x, d) in kwonlyargs.iter().zip(kw_defaults.iter()) {
                    self.w(", ");
                    self.traverse(*x);
                    if let Some(d) = d {
                        self.w("=");
                        self.traverse(*d);
                    }
                }
                if let Some(k) = kwarg {
                    if !primero {
                        self.w(", ");
                    }
                    if let K::Arg { arg, annotation } = a.k(k).clone() {
                        self.w(&format!("**{arg}"));
                        if let Some(an) = annotation {
                            self.w(": ");
                            self.traverse(an);
                        }
                    }
                }
            }
            K::Keyword { arg, value } => {
                match arg {
                    None => self.w("**"),
                    Some(n) => {
                        self.w(&n);
                        self.w("=");
                    }
                }
                self.traverse(value);
            }
            K::Lambda { args, body } => {
                let par = self.abre(TEST, id);
                self.w("lambda");
                let previo = std::mem::take(&mut self.s);
                self.traverse(args);
                let buffer = std::mem::replace(&mut self.s, previo);
                if !buffer.is_empty() {
                    self.w(" ");
                    self.w(&buffer);
                }
                self.w(": ");
                self.set(TEST, body);
                self.traverse(body);
                self.cierra(par);
            }
            K::Alias { name, asname } => {
                self.w(&name);
                if let Some(a) = asname {
                    self.w(&format!(" as {a}"));
                }
            }
            K::WithItem { context_expr, optional_vars } => {
                self.traverse(context_expr);
                if let Some(v) = optional_vars {
                    self.w(" as ");
                    self.traverse(v);
                }
            }
            // Sentencias y patrones: el banco no los escribe (solo expresiones y argumentos)
            _ => {}
        }
    }

    /// `_str_literal_helper`: (texto escapado, comillas posibles).
    fn literal(cadena: &str, comillas: &[String], escapar_espacios: bool) -> (String, Vec<String>) {
        let mut escapado = String::with_capacity(cadena.len());
        for c in cadena.chars() {
            if !escapar_espacios && (c == '\n' || c == '\t') {
                escapado.push(c);
            } else if c == '\\' || !es_imprimible(c) {
                escapado.push_str(&unicode_escape(c));
            } else {
                escapado.push(c);
            }
        }
        let mut posibles: Vec<String> = comillas.to_vec();
        if escapado.contains('\n') {
            posibles.retain(|q| TRIPLES.contains(&q.as_str()));
        }
        posibles.retain(|q| !escapado.contains(q.as_str()));
        if posibles.is_empty() {
            let r = repr_str(cadena);
            let primera = r.chars().next().unwrap();
            let comilla = comillas.iter().find(|q| q.contains(primera)).cloned().unwrap_or_else(|| primera.to_string());
            let interior = r[1..r.len() - 1].to_string();
            return (interior, vec![comilla]);
        }
        if let Some(ultimo) = escapado.chars().last() {
            // ordenar: primero las que no empiezan con el último carácter (sort estable por un booleano)
            let (no, si): (Vec<String>, Vec<String>) = posibles.into_iter().partition(|q| !q.starts_with(ultimo));
            posibles = no.into_iter().chain(si).collect();
            if posibles[0].starts_with(ultimo) {
                escapado.pop();
                escapado.push('\\');
                escapado.push(ultimo);
            }
        }
        (escapado, posibles)
    }

    fn fstring_interior(&mut self, id: Id, es_spec: bool) {
        let a = self.a;
        match a.k(id).clone() {
            K::JoinedStr { values } => {
                for v in values {
                    self.fstring_interior(v, es_spec);
                }
            }
            K::Constant { value: Constante::Cadena(s), .. } => {
                let mut v = s.replace('{', "{{").replace('}', "}}");
                if es_spec {
                    v = v.replace('\\', "\\\\").replace('\'', "\\'").replace('"', "\\\"").replace('\n', "\\n");
                }
                self.w(&v);
            }
            K::FormattedValue { .. } => self.formatted_value(id),
            _ => {}
        }
    }

    fn formatted_value(&mut self, id: Id) {
        let K::FormattedValue { value, conversion, format_spec } = self.a.k(id).clone() else { return };
        self.w("{");
        let mut interno = Unparser { a: self.a, s: String::new(), prec: HashMap::new() };
        interno.set(siguiente(TEST), value);
        interno.traverse(value);
        let expr = interno.s;
        if expr.starts_with('{') {
            self.w(" ");
        }
        self.w(&expr);
        if conversion != -1 {
            self.w(&format!("!{}", char::from_u32(conversion as u32).unwrap_or('r')));
        }
        if let Some(spec) = format_spec {
            self.w(":");
            self.fstring_interior(spec, true);
        }
        self.w("}");
    }

    fn joined_str(&mut self, id: Id) {
        let K::JoinedStr { values } = self.a.k(id).clone() else { return };
        self.w("f");
        let mut partes: Vec<(String, bool)> = Vec::new();
        for v in &values {
            let previo = std::mem::take(&mut self.s);
            self.fstring_interior(*v, false);
            let buffer = std::mem::replace(&mut self.s, previo);
            let es_constante = matches!(self.a.k(*v), K::Constant { .. });
            partes.push((buffer, es_constante));
        }
        let mut nuevas: Vec<String> = Vec::new();
        let mut comillas: Vec<String> = COMILLAS.iter().map(|q| q.to_string()).collect();
        let mut recurrir = false;
        for (valor, es_constante) in &partes {
            if *es_constante {
                let (v, nuevas_comillas) = Self::literal(valor, &comillas, true);
                if nuevas_comillas.iter().all(|q| !comillas.contains(q)) {
                    recurrir = true;
                    break;
                }
                comillas = nuevas_comillas;
                nuevas.push(v);
            } else {
                if valor.contains('\n') {
                    comillas.retain(|q| TRIPLES.contains(&q.as_str()));
                }
                nuevas.push(valor.clone());
            }
        }
        if recurrir {
            comillas = vec!["'''".to_string()];
            nuevas.clear();
            for (valor, es_constante) in &partes {
                if *es_constante {
                    let r = repr_str(&format!("\"{valor}"));
                    nuevas.push(r[2..r.len() - 1].to_string());
                } else {
                    nuevas.push(valor.clone());
                }
            }
        }
        let comilla = comillas[0].clone();
        self.w(&comilla);
        self.w(&nuevas.concat());
        self.w(&comilla);
    }
}
