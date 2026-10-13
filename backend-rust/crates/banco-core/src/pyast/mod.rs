//! El árbol de Python con la forma del módulo `ast` de CPython 3.12, construido con el analizador de Ruff.
//!
//! El banco recorre el árbol con `ast.walk` (en anchura, con los campos en el orden de `_fields`), compara
//! tipos de nodo de CPython (FunctionDef/AsyncFunctionDef, Constant, JoinedStr, If anidado por cada elif) y
//! escribe expresiones con `ast.unparse`. Ruff representa algunas cosas distinto (elif en una lista, el primer
//! operando de una comparación junto a los demás, f-strings por partes): aquí se traducen a lo de CPython para
//! que el orden de los hechos, las líneas y las firmas salgan iguales.

pub mod unparse;

use ruff_python_ast as ra;
use ruff_python_ast::token::TokenKind;
use ruff_python_ast::PythonVersion;
use ruff_python_parser::lexer::lex;
use ruff_python_parser::{parse, Mode, ParseOptions};
use ruff_text_size::{Ranged, TextRange};

use crate::py::numero::entero_decimal;

pub type Id = usize;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ctx {
    Load,
    Store,
    Del,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Constante {
    Nada,
    Verdadero,
    Falso,
    Elipsis,
    /// En decimal (los enteros de Python no tienen tope)
    Entero(String),
    Flotante(f64),
    Imaginario(f64),
    Cadena(String),
    Bytes(Vec<u8>),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OpBin {
    Add,
    Sub,
    Mult,
    MatMult,
    Div,
    Mod,
    Pow,
    LShift,
    RShift,
    BitOr,
    BitXor,
    BitAnd,
    FloorDiv,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OpUn {
    Invert,
    Not,
    UAdd,
    USub,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OpBool {
    And,
    Or,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OpCmp {
    Eq,
    NotEq,
    Lt,
    LtE,
    Gt,
    GtE,
    Is,
    IsNot,
    In,
    NotIn,
}

/// Un nodo de CPython. Los campos van en el orden de `_fields` (el de `ast.iter_child_nodes`).
#[derive(Clone, Debug)]
pub enum K {
    Module { body: Vec<Id> },
    FunctionDef { is_async: bool, name: String, args: Id, body: Vec<Id>, decorators: Vec<Id>, returns: Option<Id>, type_params: Vec<Id> },
    ClassDef { name: String, bases: Vec<Id>, keywords: Vec<Id>, body: Vec<Id>, decorators: Vec<Id>, type_params: Vec<Id> },
    Return { value: Option<Id> },
    Delete { targets: Vec<Id> },
    Assign { targets: Vec<Id>, value: Id },
    TypeAlias { name: Id, type_params: Vec<Id>, value: Id },
    AugAssign { target: Id, op: OpBin, value: Id },
    AnnAssign { target: Id, annotation: Id, value: Option<Id>, simple: bool },
    For { is_async: bool, target: Id, iter: Id, body: Vec<Id>, orelse: Vec<Id> },
    While { test: Id, body: Vec<Id>, orelse: Vec<Id> },
    If { test: Id, body: Vec<Id>, orelse: Vec<Id> },
    With { is_async: bool, items: Vec<Id>, body: Vec<Id> },
    Match { subject: Id, cases: Vec<Id> },
    Raise { exc: Option<Id>, cause: Option<Id> },
    Try { is_star: bool, body: Vec<Id>, handlers: Vec<Id>, orelse: Vec<Id>, finalbody: Vec<Id> },
    Assert { test: Id, msg: Option<Id> },
    Import { names: Vec<Id> },
    ImportFrom { module: Option<String>, names: Vec<Id>, level: u32 },
    Global { names: Vec<String> },
    Nonlocal { names: Vec<String> },
    Expr { value: Id },
    Pass,
    Break,
    Continue,
    BoolOp { op: OpBool, values: Vec<Id> },
    NamedExpr { target: Id, value: Id },
    BinOp { left: Id, op: OpBin, right: Id },
    UnaryOp { op: OpUn, operand: Id },
    Lambda { args: Id, body: Id },
    IfExp { test: Id, body: Id, orelse: Id },
    Dict { keys: Vec<Option<Id>>, values: Vec<Id> },
    Set { elts: Vec<Id> },
    ListComp { elt: Id, generators: Vec<Id> },
    SetComp { elt: Id, generators: Vec<Id> },
    DictComp { key: Id, value: Id, generators: Vec<Id> },
    GeneratorExp { elt: Id, generators: Vec<Id> },
    Await { value: Id },
    Yield { value: Option<Id> },
    YieldFrom { value: Id },
    Compare { left: Id, ops: Vec<OpCmp>, comparators: Vec<Id> },
    Call { func: Id, args: Vec<Id>, keywords: Vec<Id> },
    FormattedValue { value: Id, conversion: i32, format_spec: Option<Id> },
    JoinedStr { values: Vec<Id> },
    Constant { value: Constante, kind_u: bool },
    Attribute { value: Id, attr: String, ctx: Ctx },
    Subscript { value: Id, slice: Id, ctx: Ctx },
    Starred { value: Id, ctx: Ctx },
    Name { id: String, ctx: Ctx },
    List { elts: Vec<Id>, ctx: Ctx },
    Tuple { elts: Vec<Id>, ctx: Ctx },
    Slice { lower: Option<Id>, upper: Option<Id>, step: Option<Id> },
    Comprehension { target: Id, iter: Id, ifs: Vec<Id>, is_async: bool },
    ExceptHandler { type_: Option<Id>, name: Option<String>, body: Vec<Id> },
    Arguments { posonlyargs: Vec<Id>, args: Vec<Id>, vararg: Option<Id>, kwonlyargs: Vec<Id>, kw_defaults: Vec<Option<Id>>, kwarg: Option<Id>, defaults: Vec<Id> },
    Arg { arg: String, annotation: Option<Id> },
    Keyword { arg: Option<String>, value: Id },
    Alias { name: String, asname: Option<String> },
    WithItem { context_expr: Id, optional_vars: Option<Id> },
    MatchCase { pattern: Id, guard: Option<Id>, body: Vec<Id> },
    MatchValue { value: Id },
    MatchSingleton { value: Constante },
    MatchSequence { patterns: Vec<Id> },
    MatchMapping { keys: Vec<Id>, patterns: Vec<Id>, rest: Option<String> },
    MatchClass { cls: Id, patterns: Vec<Id>, kwd_attrs: Vec<String>, kwd_patterns: Vec<Id> },
    MatchStar { name: Option<String> },
    MatchAs { pattern: Option<Id>, name: Option<String> },
    MatchOr { patterns: Vec<Id> },
    TypeVar { name: String, bound: Option<Id> },
    ParamSpec { name: String },
    TypeVarTuple { name: String },
}

#[derive(Clone, Debug)]
pub struct Nodo {
    pub k: K,
    /// `lineno` y `end_lineno` de CPython
    pub linea: u32,
    pub linea_fin: u32,
}

/// Un módulo de Python ya analizado.
pub struct Arbol {
    pub nodos: Vec<Nodo>,
    pub modulo: Id,
}

struct NoSoportado;

struct Conversor<'a> {
    fuente: &'a str,
    inicios: Vec<usize>,
    nodos: Vec<Nodo>,
}

/// Inicios de línea como los cuenta el tokenizador de CPython: \n, \r\n y \r sueltos (no \f ni los demás
/// separadores de `splitlines`).
pub fn inicios_de_linea(fuente: &str) -> Vec<usize> {
    let b = fuente.as_bytes();
    let mut inicios = vec![0];
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'\n' => inicios.push(i + 1),
            b'\r' => {
                if i + 1 < b.len() && b[i + 1] == b'\n' {
                    i += 1;
                }
                inicios.push(i + 1);
            }
            _ => {}
        }
        i += 1;
    }
    inicios
}

impl<'a> Conversor<'a> {
    fn linea(&self, offset: usize) -> u32 {
        self.inicios.partition_point(|&s| s <= offset) as u32
    }

    fn nuevo(&mut self, k: K, rango: TextRange) -> Id {
        let linea = self.linea(rango.start().to_usize());
        let linea_fin = self.linea(rango.end().to_usize());
        self.nodos.push(Nodo { k, linea, linea_fin });
        self.nodos.len() - 1
    }

    fn nuevo_en(&mut self, k: K, linea: u32, linea_fin: u32) -> Id {
        self.nodos.push(Nodo { k, linea, linea_fin });
        self.nodos.len() - 1
    }

    fn cuerpo(&mut self, ss: &[ra::Stmt]) -> Result<Vec<Id>, NoSoportado> {
        ss.iter().map(|s| self.stmt(s)).collect()
    }

    fn exprs(&mut self, es: &[ra::Expr]) -> Result<Vec<Id>, NoSoportado> {
        es.iter().map(|e| self.expr(e)).collect()
    }

    fn opt(&mut self, e: Option<&ra::Expr>) -> Result<Option<Id>, NoSoportado> {
        match e {
            Some(e) => Ok(Some(self.expr(e)?)),
            None => Ok(None),
        }
    }

    fn ctx(c: ra::ExprContext) -> Ctx {
        match c {
            ra::ExprContext::Store => Ctx::Store,
            ra::ExprContext::Del => Ctx::Del,
            _ => Ctx::Load,
        }
    }

    fn op_bin(op: ra::Operator) -> OpBin {
        match op {
            ra::Operator::Add => OpBin::Add,
            ra::Operator::Sub => OpBin::Sub,
            ra::Operator::Mult => OpBin::Mult,
            ra::Operator::MatMult => OpBin::MatMult,
            ra::Operator::Div => OpBin::Div,
            ra::Operator::Mod => OpBin::Mod,
            ra::Operator::Pow => OpBin::Pow,
            ra::Operator::LShift => OpBin::LShift,
            ra::Operator::RShift => OpBin::RShift,
            ra::Operator::BitOr => OpBin::BitOr,
            ra::Operator::BitXor => OpBin::BitXor,
            ra::Operator::BitAnd => OpBin::BitAnd,
            ra::Operator::FloorDiv => OpBin::FloorDiv,
        }
    }

    fn op_cmp(op: ra::CmpOp) -> OpCmp {
        match op {
            ra::CmpOp::Eq => OpCmp::Eq,
            ra::CmpOp::NotEq => OpCmp::NotEq,
            ra::CmpOp::Lt => OpCmp::Lt,
            ra::CmpOp::LtE => OpCmp::LtE,
            ra::CmpOp::Gt => OpCmp::Gt,
            ra::CmpOp::GtE => OpCmp::GtE,
            ra::CmpOp::Is => OpCmp::Is,
            ra::CmpOp::IsNot => OpCmp::IsNot,
            ra::CmpOp::In => OpCmp::In,
            ra::CmpOp::NotIn => OpCmp::NotIn,
        }
    }

    fn argumentos(&mut self, p: Option<&ra::Parameters>, rango: TextRange) -> Result<Id, NoSoportado> {
        let (mut posonly, mut args, mut kwonly, mut kw_defaults, mut defaults) = (vec![], vec![], vec![], vec![], vec![]);
        let (mut vararg, mut kwarg) = (None, None);
        if let Some(p) = p {
            for x in p.posonlyargs.iter() {
                posonly.push(self.parametro(&x.parameter)?);
                if let Some(d) = &x.default {
                    defaults.push(self.expr(d)?);
                }
            }
            for x in p.args.iter() {
                args.push(self.parametro(&x.parameter)?);
                if let Some(d) = &x.default {
                    defaults.push(self.expr(d)?);
                }
            }
            if let Some(v) = &p.vararg {
                vararg = Some(self.parametro(v)?);
            }
            for x in p.kwonlyargs.iter() {
                kwonly.push(self.parametro(&x.parameter)?);
                kw_defaults.push(match &x.default {
                    Some(d) => Some(self.expr(d)?),
                    None => None,
                });
            }
            if let Some(k) = &p.kwarg {
                kwarg = Some(self.parametro(k)?);
            }
        }
        let rango = p.map(|p| p.range).unwrap_or(rango);
        Ok(self.nuevo(K::Arguments { posonlyargs: posonly, args, vararg, kwonlyargs: kwonly, kw_defaults, kwarg, defaults }, rango))
    }

    fn parametro(&mut self, p: &ra::Parameter) -> Result<Id, NoSoportado> {
        let annotation = self.opt(p.annotation.as_deref())?;
        Ok(self.nuevo(K::Arg { arg: p.name.id.as_str().to_string(), annotation }, p.range))
    }

    fn keyword(&mut self, k: &ra::Keyword) -> Result<Id, NoSoportado> {
        let value = self.expr(&k.value)?;
        Ok(self.nuevo(K::Keyword { arg: k.arg.as_ref().map(|a| a.id.as_str().to_string()), value }, k.range))
    }

    fn type_params(&mut self, tp: Option<&ra::TypeParams>) -> Result<Vec<Id>, NoSoportado> {
        let mut salida = vec![];
        if let Some(tp) = tp {
            for t in tp.type_params.iter() {
                let id = match t {
                    ra::TypeParam::TypeVar(v) => {
                        let bound = self.opt(v.bound.as_deref())?;
                        self.nuevo(K::TypeVar { name: v.name.id.as_str().to_string(), bound }, v.range)
                    }
                    ra::TypeParam::ParamSpec(v) => self.nuevo(K::ParamSpec { name: v.name.id.as_str().to_string() }, v.range),
                    ra::TypeParam::TypeVarTuple(v) => self.nuevo(K::TypeVarTuple { name: v.name.id.as_str().to_string() }, v.range),
                };
                salida.push(id);
            }
        }
        Ok(salida)
    }

    fn comprehensions(&mut self, gs: &[ra::Comprehension]) -> Result<Vec<Id>, NoSoportado> {
        let mut salida = vec![];
        for g in gs {
            let target = self.expr(&g.target)?;
            let iter = self.expr(&g.iter)?;
            let ifs = self.exprs(&g.ifs)?;
            salida.push(self.nuevo(K::Comprehension { target, iter, ifs, is_async: g.is_async }, g.range));
        }
        Ok(salida)
    }

    fn stmt(&mut self, s: &ra::Stmt) -> Result<Id, NoSoportado> {
        use ra::Stmt as S;
        let rango = s.range();
        let k = match s {
            S::FunctionDef(f) => {
                let decorators = f.decorator_list.iter().map(|d| self.expr(&d.expression)).collect::<Result<Vec<_>, _>>()?;
                let type_params = self.type_params(f.type_params.as_deref())?;
                let args = self.argumentos(Some(&f.parameters), f.parameters.range)?;
                let returns = self.opt(f.returns.as_deref())?;
                let body = self.cuerpo(&f.body)?;
                let linea = self.linea(f.name.range.start().to_usize());
                let fin = self.linea(rango.end().to_usize());
                return Ok(self.nuevo_en(
                    K::FunctionDef { is_async: f.is_async, name: f.name.id.as_str().to_string(), args, body, decorators, returns, type_params },
                    linea,
                    fin,
                ));
            }
            S::ClassDef(c) => {
                let decorators = c.decorator_list.iter().map(|d| self.expr(&d.expression)).collect::<Result<Vec<_>, _>>()?;
                let type_params = self.type_params(c.type_params.as_deref())?;
                let (mut bases, mut keywords) = (vec![], vec![]);
                if let Some(a) = &c.arguments {
                    bases = self.exprs(&a.args)?;
                    for k in a.keywords.iter() {
                        keywords.push(self.keyword(k)?);
                    }
                }
                let body = self.cuerpo(&c.body)?;
                let linea = self.linea(c.name.range.start().to_usize());
                let fin = self.linea(rango.end().to_usize());
                return Ok(self.nuevo_en(
                    K::ClassDef { name: c.name.id.as_str().to_string(), bases, keywords, body, decorators, type_params },
                    linea,
                    fin,
                ));
            }
            S::Return(r) => K::Return { value: self.opt(r.value.as_deref())? },
            S::Delete(d) => K::Delete { targets: self.exprs(&d.targets)? },
            S::TypeAlias(t) => {
                let name = self.expr(&t.name)?;
                let type_params = self.type_params(t.type_params.as_deref())?;
                let value = self.expr(&t.value)?;
                K::TypeAlias { name, type_params, value }
            }
            S::Assign(a) => {
                let targets = self.exprs(&a.targets)?;
                let value = self.expr(&a.value)?;
                K::Assign { targets, value }
            }
            S::AugAssign(a) => {
                let target = self.expr(&a.target)?;
                let value = self.expr(&a.value)?;
                K::AugAssign { target, op: Self::op_bin(a.op), value }
            }
            S::AnnAssign(a) => {
                let target = self.expr(&a.target)?;
                let annotation = self.expr(&a.annotation)?;
                let value = self.opt(a.value.as_deref())?;
                K::AnnAssign { target, annotation, value, simple: a.simple }
            }
            S::For(f) => {
                let target = self.expr(&f.target)?;
                let iter = self.expr(&f.iter)?;
                let body = self.cuerpo(&f.body)?;
                let orelse = self.cuerpo(&f.orelse)?;
                K::For { is_async: f.is_async, target, iter, body, orelse }
            }
            S::While(w) => {
                let test = self.expr(&w.test)?;
                let body = self.cuerpo(&w.body)?;
                let orelse = self.cuerpo(&w.orelse)?;
                K::While { test, body, orelse }
            }
            S::If(i) => {
                let test = self.expr(&i.test)?;
                let body = self.cuerpo(&i.body)?;
                let orelse = self.elifs(&i.elif_else_clauses)?;
                K::If { test, body, orelse }
            }
            S::With(w) => {
                let mut items = vec![];
                for it in w.items.iter() {
                    let context_expr = self.expr(&it.context_expr)?;
                    let optional_vars = self.opt(it.optional_vars.as_deref())?;
                    items.push(self.nuevo(K::WithItem { context_expr, optional_vars }, it.range));
                }
                let body = self.cuerpo(&w.body)?;
                K::With { is_async: w.is_async, items, body }
            }
            S::Match(m) => {
                let subject = self.expr(&m.subject)?;
                let mut cases = vec![];
                for c in m.cases.iter() {
                    let pattern = self.patron(&c.pattern)?;
                    let guard = self.opt(c.guard.as_deref())?;
                    let body = self.cuerpo(&c.body)?;
                    cases.push(self.nuevo(K::MatchCase { pattern, guard, body }, c.range));
                }
                K::Match { subject, cases }
            }
            S::Raise(r) => {
                let exc = self.opt(r.exc.as_deref())?;
                let cause = self.opt(r.cause.as_deref())?;
                K::Raise { exc, cause }
            }
            S::Try(t) => {
                let body = self.cuerpo(&t.body)?;
                let mut handlers = vec![];
                for h in t.handlers.iter() {
                    let ra::ExceptHandler::ExceptHandler(h) = h;
                    let type_ = self.opt(h.type_.as_deref())?;
                    let hbody = self.cuerpo(&h.body)?;
                    handlers.push(self.nuevo(K::ExceptHandler { type_, name: h.name.as_ref().map(|n| n.id.as_str().to_string()), body: hbody }, h.range));
                }
                let orelse = self.cuerpo(&t.orelse)?;
                let finalbody = self.cuerpo(&t.finalbody)?;
                K::Try { is_star: t.is_star, body, handlers, orelse, finalbody }
            }
            S::Assert(a) => {
                let test = self.expr(&a.test)?;
                let msg = self.opt(a.msg.as_deref())?;
                K::Assert { test, msg }
            }
            S::Import(i) => {
                if i.is_lazy {
                    return Err(NoSoportado);
                }
                let names = i.names.iter().map(|a| self.alias(a)).collect();
                K::Import { names }
            }
            S::ImportFrom(i) => {
                if i.is_lazy {
                    return Err(NoSoportado);
                }
                let names = i.names.iter().map(|a| self.alias(a)).collect();
                K::ImportFrom { module: i.module.as_ref().map(|m| m.id.as_str().to_string()), names, level: i.level }
            }
            S::Global(g) => K::Global { names: g.names.iter().map(|n| n.id.as_str().to_string()).collect() },
            S::Nonlocal(g) => K::Nonlocal { names: g.names.iter().map(|n| n.id.as_str().to_string()).collect() },
            S::Expr(e) => K::Expr { value: self.expr(&e.value)? },
            S::Pass(_) => K::Pass,
            S::Break(_) => K::Break,
            S::Continue(_) => K::Continue,
            S::IpyEscapeCommand(_) => return Err(NoSoportado),
        };
        Ok(self.nuevo(k, rango))
    }

    fn alias(&mut self, a: &ra::Alias) -> Id {
        self.nuevo(K::Alias { name: a.name.id.as_str().to_string(), asname: a.asname.as_ref().map(|n| n.id.as_str().to_string()) }, a.range)
    }

    /// Las cláusulas elif/else de Ruff como CPython: cada elif es un If anidado en el orelse del anterior.
    fn elifs(&mut self, clausulas: &[ra::ElifElseClause]) -> Result<Vec<Id>, NoSoportado> {
        let Some((primera, resto)) = clausulas.split_first() else {
            return Ok(vec![]);
        };
        match &primera.test {
            Some(test) => {
                let test = self.expr(test)?;
                let body = self.cuerpo(&primera.body)?;
                let orelse = self.elifs(resto)?;
                let linea = self.linea(primera.range.start().to_usize());
                let fin = match resto.last() {
                    Some(u) => self.linea(u.range.end().to_usize()),
                    None => self.linea(primera.range.end().to_usize()),
                };
                Ok(vec![self.nuevo_en(K::If { test, body, orelse }, linea, fin)])
            }
            None => self.cuerpo(&primera.body),
        }
    }

    fn patron(&mut self, p: &ra::Pattern) -> Result<Id, NoSoportado> {
        use ra::Pattern as P;
        let rango = p.range();
        let k = match p {
            P::MatchValue(v) => K::MatchValue { value: self.expr(&v.value)? },
            P::MatchSingleton(s) => K::MatchSingleton {
                value: match s.value {
                    ra::Singleton::None => Constante::Nada,
                    ra::Singleton::True => Constante::Verdadero,
                    ra::Singleton::False => Constante::Falso,
                },
            },
            P::MatchSequence(s) => K::MatchSequence { patterns: s.patterns.iter().map(|x| self.patron(x)).collect::<Result<_, _>>()? },
            P::MatchMapping(m) => {
                let keys = self.exprs(&m.keys)?;
                let patterns = m.patterns.iter().map(|x| self.patron(x)).collect::<Result<_, _>>()?;
                K::MatchMapping { keys, patterns, rest: m.rest.as_ref().map(|r| r.id.as_str().to_string()) }
            }
            P::MatchClass(c) => {
                let cls = self.expr(&c.cls)?;
                let patterns = c.arguments.patterns.iter().map(|x| self.patron(x)).collect::<Result<_, _>>()?;
                let kwd_attrs = c.arguments.keywords.iter().map(|k| k.attr.id.as_str().to_string()).collect();
                let kwd_patterns = c.arguments.keywords.iter().map(|k| self.patron(&k.pattern)).collect::<Result<_, _>>()?;
                K::MatchClass { cls, patterns, kwd_attrs, kwd_patterns }
            }
            P::MatchStar(s) => K::MatchStar { name: s.name.as_ref().map(|n| n.id.as_str().to_string()) },
            P::MatchAs(a) => {
                let pattern = match &a.pattern {
                    Some(x) => Some(self.patron(x)?),
                    None => None,
                };
                K::MatchAs { pattern, name: a.name.as_ref().map(|n| n.id.as_str().to_string()) }
            }
            P::MatchOr(o) => K::MatchOr { patterns: o.patterns.iter().map(|x| self.patron(x)).collect::<Result<_, _>>()? },
        };
        Ok(self.nuevo(k, rango))
    }

    fn constante(&mut self, value: Constante, rango: TextRange) -> Id {
        self.nuevo(K::Constant { value, kind_u: false }, rango)
    }

    /// Las partes de un f-string como los `values` de un JoinedStr: el texto contiguo junto en un Constant y
    /// el texto de depuración («x=») delante de su valor.
    fn partes_fstring<'b>(&mut self, elementos: impl Iterator<Item = &'b ra::InterpolatedStringElement>, pendiente: &mut String, valores: &mut Vec<Id>, rango: TextRange) -> Result<(), NoSoportado> {
        for el in elementos {
            match el {
                ra::InterpolatedStringElement::Literal(l) => pendiente.push_str(&l.value),
                ra::InterpolatedStringElement::Interpolation(i) => {
                    if let Some(dt) = &i.debug_text {
                        pendiente.push_str(dt.as_str());
                    }
                    if !pendiente.is_empty() {
                        let texto = std::mem::take(pendiente);
                        valores.push(self.constante(Constante::Cadena(texto), rango));
                    }
                    let value = self.expr(&i.expression)?;
                    let conversion = match i.conversion {
                        ra::ConversionFlag::None => {
                            if i.debug_text.is_some() && i.format_spec.is_none() {
                                'r' as i32
                            } else {
                                -1
                            }
                        }
                        ra::ConversionFlag::Str => 's' as i32,
                        ra::ConversionFlag::Ascii => 'a' as i32,
                        ra::ConversionFlag::Repr => 'r' as i32,
                    };
                    let format_spec = match &i.format_spec {
                        Some(spec) => {
                            let mut pend = String::new();
                            let mut vals = vec![];
                            self.partes_fstring(spec.elements.iter(), &mut pend, &mut vals, spec.range)?;
                            if !pend.is_empty() {
                                vals.push(self.constante(Constante::Cadena(pend), spec.range));
                            } else if vals.last().map(|v| matches!(self.nodos[*v].k, K::FormattedValue { .. })).unwrap_or(false) {
                                // CPython 3.12: una especificación que termina en un campo anidado ({x:{w}}) lleva un
                                // Constant('') al final
                                vals.push(self.constante(Constante::Cadena(String::new()), spec.range));
                            }
                            Some(self.nuevo(K::JoinedStr { values: vals }, spec.range))
                        }
                        None => None,
                    };
                    valores.push(self.nuevo(K::FormattedValue { value, conversion, format_spec }, i.range));
                }
            }
        }
        Ok(())
    }

    fn expr(&mut self, e: &ra::Expr) -> Result<Id, NoSoportado> {
        use ra::Expr as E;
        let rango = e.range();
        let k = match e {
            E::BoolOp(b) => K::BoolOp { op: if b.op == ra::BoolOp::And { OpBool::And } else { OpBool::Or }, values: self.exprs(&b.values)? },
            E::Named(n) => {
                let target = self.expr(&n.target)?;
                let value = self.expr(&n.value)?;
                K::NamedExpr { target, value }
            }
            E::BinOp(b) => {
                let left = self.expr(&b.left)?;
                let right = self.expr(&b.right)?;
                K::BinOp { left, op: Self::op_bin(b.op), right }
            }
            E::UnaryOp(u) => {
                let operand = self.expr(&u.operand)?;
                let op = match u.op {
                    ra::UnaryOp::Invert => OpUn::Invert,
                    ra::UnaryOp::Not => OpUn::Not,
                    ra::UnaryOp::UAdd => OpUn::UAdd,
                    ra::UnaryOp::USub => OpUn::USub,
                };
                K::UnaryOp { op, operand }
            }
            E::Lambda(l) => {
                let args = self.argumentos(l.parameters.as_deref(), rango)?;
                let body = self.expr(&l.body)?;
                K::Lambda { args, body }
            }
            E::If(i) => {
                let test = self.expr(&i.test)?;
                let body = self.expr(&i.body)?;
                let orelse = self.expr(&i.orelse)?;
                K::IfExp { test, body, orelse }
            }
            E::Dict(d) => {
                let mut keys = vec![];
                let mut values = vec![];
                for it in d.items.iter() {
                    keys.push(match &it.key {
                        Some(k) => Some(self.expr(k)?),
                        None => None,
                    });
                }
                for it in d.items.iter() {
                    values.push(self.expr(&it.value)?);
                }
                K::Dict { keys, values }
            }
            E::Set(s) => K::Set { elts: self.exprs(&s.elts)? },
            E::ListComp(c) => {
                let elt = self.expr(&c.elt)?;
                let generators = self.comprehensions(&c.generators)?;
                K::ListComp { elt, generators }
            }
            E::SetComp(c) => {
                let elt = self.expr(&c.elt)?;
                let generators = self.comprehensions(&c.generators)?;
                K::SetComp { elt, generators }
            }
            E::DictComp(c) => {
                let Some(key) = &c.key else { return Err(NoSoportado) };
                let key = self.expr(key)?;
                let value = self.expr(&c.value)?;
                let generators = self.comprehensions(&c.generators)?;
                K::DictComp { key, value, generators }
            }
            E::Generator(g) => {
                let elt = self.expr(&g.elt)?;
                let generators = self.comprehensions(&g.generators)?;
                K::GeneratorExp { elt, generators }
            }
            E::Await(a) => K::Await { value: self.expr(&a.value)? },
            E::Yield(y) => K::Yield { value: self.opt(y.value.as_deref())? },
            E::YieldFrom(y) => K::YieldFrom { value: self.expr(&y.value)? },
            E::Compare(c) => {
                let (primero, resto) = c.operands.split_first().ok_or(NoSoportado)?;
                let left = self.expr(primero)?;
                let comparators = self.exprs(resto)?;
                K::Compare { left, ops: c.ops.iter().map(|o| Self::op_cmp(*o)).collect(), comparators }
            }
            E::Call(c) => {
                let func = self.expr(&c.func)?;
                let args = self.exprs(&c.arguments.args)?;
                // f(x for x in y): CPython ubica el generador en los paréntesis de la llamada
                if args.len() == 1 && c.arguments.keywords.is_empty() {
                    if let ra::Expr::Generator(g) = &c.arguments.args[0] {
                        if !g.parenthesized {
                            let (l, f) = (self.linea(c.arguments.range.start().to_usize()), self.linea(c.arguments.range.end().to_usize()));
                            self.nodos[args[0]].linea = l;
                            self.nodos[args[0]].linea_fin = f;
                        }
                    }
                }
                let mut keywords = vec![];
                for k in c.arguments.keywords.iter() {
                    keywords.push(self.keyword(k)?);
                }
                K::Call { func, args, keywords }
            }
            E::FString(f) => {
                let mut pendiente = String::new();
                let mut valores = vec![];
                for parte in f.value.iter() {
                    match parte {
                        ra::FStringPartRef::Literal(l) => pendiente.push_str(&l.value),
                        ra::FStringPartRef::FString(fs) => self.partes_fstring(fs.elements.iter(), &mut pendiente, &mut valores, rango)?,
                    }
                }
                if !pendiente.is_empty() {
                    valores.push(self.constante(Constante::Cadena(pendiente), rango));
                }
                K::JoinedStr { values: valores }
            }
            E::TString(_) | E::IpyEscapeCommand(_) => return Err(NoSoportado),
            E::StringLiteral(s) => {
                let kind_u = s.value.iter().next().map(|p| matches!(p.flags.prefix(), ra::str_prefix::StringLiteralPrefix::Unicode)).unwrap_or(false);
                K::Constant { value: Constante::Cadena(s.value.to_str().to_string()), kind_u }
            }
            E::BytesLiteral(b) => K::Constant { value: Constante::Bytes(b.value.bytes().collect()), kind_u: false },
            E::NumberLiteral(n) => K::Constant {
                value: match &n.value {
                    ra::Number::Int(i) => Constante::Entero(entero_decimal(&i.to_string())),
                    ra::Number::Float(f) => Constante::Flotante(*f),
                    ra::Number::Complex { imag, .. } => Constante::Imaginario(*imag),
                },
                kind_u: false,
            },
            E::BooleanLiteral(b) => K::Constant { value: if b.value { Constante::Verdadero } else { Constante::Falso }, kind_u: false },
            E::NoneLiteral(_) => K::Constant { value: Constante::Nada, kind_u: false },
            E::EllipsisLiteral(_) => K::Constant { value: Constante::Elipsis, kind_u: false },
            E::Attribute(a) => {
                let value = self.expr(&a.value)?;
                K::Attribute { value, attr: a.attr.id.as_str().to_string(), ctx: Self::ctx(a.ctx) }
            }
            E::Subscript(s) => {
                let value = self.expr(&s.value)?;
                let slice = self.expr(&s.slice)?;
                K::Subscript { value, slice, ctx: Self::ctx(s.ctx) }
            }
            E::Starred(s) => K::Starred { value: self.expr(&s.value)?, ctx: Self::ctx(s.ctx) },
            E::Name(n) => K::Name { id: n.id.as_str().to_string(), ctx: Self::ctx(n.ctx) },
            E::List(l) => K::List { elts: self.exprs(&l.elts)?, ctx: Self::ctx(l.ctx) },
            E::Tuple(t) => K::Tuple { elts: self.exprs(&t.elts)?, ctx: Self::ctx(t.ctx) },
            E::Slice(s) => {
                let lower = self.opt(s.lower.as_deref())?;
                let upper = self.opt(s.upper.as_deref())?;
                let step = self.opt(s.step.as_deref())?;
                K::Slice { lower, upper, step }
            }
        };
        Ok(self.nuevo(k, rango))
    }
}

/// Los topes del tokenizador de CPython 3.12, que Ruff no tiene (medidos con ast.parse): más de 200 paréntesis,
/// corchetes o llaves abiertos a la vez («too many nested parentheses»; la llave de un f-string cuenta) o más de 99
/// niveles de sangría («too many levels of indentation»). Python daba SyntaxError y el banco dejaba el archivo sin
/// analizar; Rust lo analizaba (y con miles de niveles, la pila se desbordaba).
const MAX_PARENTESIS: usize = 200;
const MAX_SANGRIA: usize = 99;

/// Cuánta recursión puede pedir un texto de Python: una cota de la profundidad de su árbol (cada nivel de una
/// expresión necesita al menos un token de su línea lógica, y cada bloque, un nivel de sangría). None si CPython lo
/// rechazaría por sus topes (arriba).
pub fn cota_de_profundidad(texto: &str) -> Option<usize> {
    let mut lexer = lex(texto, Mode::Module);
    let (mut abiertos, mut sangria, mut sangria_max, mut en_la_linea, mut linea_max) = (0usize, 0usize, 0usize, 0usize, 0usize);
    loop {
        match lexer.next_token() {
            TokenKind::EndOfFile => break,
            TokenKind::Lpar | TokenKind::Lsqb | TokenKind::Lbrace => {
                abiertos += 1;
                if abiertos > MAX_PARENTESIS {
                    return None;
                }
            }
            TokenKind::Rpar | TokenKind::Rsqb | TokenKind::Rbrace => abiertos = abiertos.saturating_sub(1),
            TokenKind::Indent => {
                sangria += 1;
                if sangria > MAX_SANGRIA {
                    return None;
                }
                sangria_max = sangria_max.max(sangria);
            }
            TokenKind::Dedent => sangria = sangria.saturating_sub(1),
            TokenKind::Newline => {
                linea_max = linea_max.max(en_la_linea);
                en_la_linea = 0;
            }
            _ => {}
        }
        en_la_linea += 1;
    }
    Some(linea_max.max(en_la_linea) + 2 * sangria_max + 16)
}

/// Hasta esta cota, la recursión cabe en la pila de cualquier hilo (medido: ~900 B por nivel en el peor caso, la
/// firma de una función con valores por defecto anidados; ~350 B en las demás expresiones).
const NIVELES_EN_EL_HILO: usize = 1_000;
/// Pila por nivel en un hilo aparte: más de 4 veces lo medido.
const PILA_POR_NIVEL: usize = 4 * 1024;

/// Corre `f` con pila para `niveles` niveles de recursión: en el hilo que llama si caben, si no en un hilo con la pila
/// necesaria (es memoria virtual: solo se ocupa la que la recursión toca). Un archivo de 1 MB puede anidar cientos de
/// miles de niveles (`x = ------…1`): en la pila de un hilo normal, el analizador y los recorridos recursivos la
/// desbordaban y el proceso entero (Prig) moría. None si no se pudo crear el hilo o `f` entró en pánico.
pub fn con_pila<T: Send>(niveles: usize, f: impl FnOnce() -> T + Send) -> Option<T> {
    if niveles <= NIVELES_EN_EL_HILO {
        return Some(f());
    }
    let pila = (16 << 20) + niveles.saturating_mul(PILA_POR_NIVEL);
    std::thread::scope(|alcance| std::thread::Builder::new().name("prig-arbol".into()).stack_size(pila).spawn_scoped(alcance, f).ok()?.join().ok())
}

impl Arbol {
    /// `ast.parse(texto)` y `f` sobre el árbol, con la pila que pida el texto (ver `con_pila`): todo lo que recorre el
    /// árbol de forma recursiva (unparse, las firmas…) tiene que ir dentro de `f`. None si CPython 3.12 daría
    /// SyntaxError (o ValueError) o si no hubo pila.
    pub fn con_arbol<T: Send>(texto: &str, f: impl FnOnce(&Arbol) -> T + Send) -> Option<T> {
        let niveles = cota_de_profundidad(texto)?;
        con_pila(niveles, || Arbol::analizar_aqui(texto).map(|a| f(&a))).flatten()
    }

    /// El árbol, para quien lo recorre sin recursión (`recorrer`, `hijos`); con `unparse` o las firmas, `con_arbol`.
    pub fn analizar(texto: &str) -> Option<Arbol> {
        let niveles = cota_de_profundidad(texto)?;
        con_pila(niveles, || Arbol::analizar_aqui(texto)).flatten()
    }

    /// `ast.parse(texto)` en la pila de este hilo, que tiene que alcanzar (`con_pila` con `cota_de_profundidad`); sin
    /// los topes de CPython, que mira `cota_de_profundidad`.
    pub fn analizar_aqui(texto: &str) -> Option<Arbol> {
        // Python rechaza el BOM al principio de un str («invalid non-printable character U+FEFF»); Ruff lo salta
        if texto.starts_with('\u{feff}') || texto.contains('\0') {
            return None;
        }
        let opciones = ParseOptions::from(Mode::Module).with_target_version(PythonVersion::PY312);
        let parsed = parse(texto, opciones).ok()?;
        if !parsed.errors().is_empty() || !parsed.unsupported_syntax_errors().is_empty() {
            return None;
        }
        let modulo = parsed.into_syntax();
        let modulo = modulo.as_module()?;
        let mut c = Conversor { fuente: texto, inicios: inicios_de_linea(texto), nodos: Vec::new() };
        let _ = c.fuente;
        let body = c.cuerpo(&modulo.body).ok()?;
        let fin = c.inicios.len() as u32;
        let id = c.nuevo_en(K::Module { body }, 1, fin);
        Some(Arbol { nodos: c.nodos, modulo: id })
    }

    pub fn k(&self, id: Id) -> &K {
        &self.nodos[id].k
    }

    pub fn linea(&self, id: Id) -> u32 {
        self.nodos[id].linea
    }

    pub fn linea_fin(&self, id: Id) -> u32 {
        self.nodos[id].linea_fin
    }

    /// `ast.iter_child_nodes`: los hijos en el orden de `_fields` (sin los nodos hoja de operadores y
    /// contextos, que no cambian el orden relativo de los demás en un recorrido).
    pub fn hijos(&self, id: Id) -> Vec<Id> {
        let mut h = Vec::new();
        let o = |h: &mut Vec<Id>, x: &Option<Id>| {
            if let Some(x) = x {
                h.push(*x)
            }
        };
        match self.k(id) {
            K::Module { body } => h.extend(body),
            K::FunctionDef { args, body, decorators, returns, type_params, .. } => {
                h.push(*args);
                h.extend(body);
                h.extend(decorators);
                o(&mut h, returns);
                h.extend(type_params);
            }
            K::ClassDef { bases, keywords, body, decorators, type_params, .. } => {
                h.extend(bases);
                h.extend(keywords);
                h.extend(body);
                h.extend(decorators);
                h.extend(type_params);
            }
            K::Return { value } => o(&mut h, value),
            K::Delete { targets } => h.extend(targets),
            K::Assign { targets, value } => {
                h.extend(targets);
                h.push(*value);
            }
            K::TypeAlias { name, type_params, value } => {
                h.push(*name);
                h.extend(type_params);
                h.push(*value);
            }
            K::AugAssign { target, value, .. } => {
                h.push(*target);
                h.push(*value);
            }
            K::AnnAssign { target, annotation, value, .. } => {
                h.push(*target);
                h.push(*annotation);
                o(&mut h, value);
            }
            K::For { target, iter, body, orelse, .. } => {
                h.push(*target);
                h.push(*iter);
                h.extend(body);
                h.extend(orelse);
            }
            K::While { test, body, orelse } | K::If { test, body, orelse } => {
                h.push(*test);
                h.extend(body);
                h.extend(orelse);
            }
            K::With { items, body, .. } => {
                h.extend(items);
                h.extend(body);
            }
            K::Match { subject, cases } => {
                h.push(*subject);
                h.extend(cases);
            }
            K::Raise { exc, cause } => {
                o(&mut h, exc);
                o(&mut h, cause);
            }
            K::Try { body, handlers, orelse, finalbody, .. } => {
                h.extend(body);
                h.extend(handlers);
                h.extend(orelse);
                h.extend(finalbody);
            }
            K::Assert { test, msg } => {
                h.push(*test);
                o(&mut h, msg);
            }
            K::Import { names } | K::ImportFrom { names, .. } => h.extend(names),
            K::Global { .. } | K::Nonlocal { .. } | K::Pass | K::Break | K::Continue => {}
            K::Expr { value } => h.push(*value),
            K::BoolOp { values, .. } => h.extend(values),
            K::NamedExpr { target, value } => {
                h.push(*target);
                h.push(*value);
            }
            K::BinOp { left, right, .. } => {
                h.push(*left);
                h.push(*right);
            }
            K::UnaryOp { operand, .. } => h.push(*operand),
            K::Lambda { args, body } => {
                h.push(*args);
                h.push(*body);
            }
            K::IfExp { test, body, orelse } => {
                h.push(*test);
                h.push(*body);
                h.push(*orelse);
            }
            K::Dict { keys, values } => {
                h.extend(keys.iter().flatten());
                h.extend(values);
            }
            K::Set { elts } | K::List { elts, .. } | K::Tuple { elts, .. } => h.extend(elts),
            K::ListComp { elt, generators } | K::SetComp { elt, generators } | K::GeneratorExp { elt, generators } => {
                h.push(*elt);
                h.extend(generators);
            }
            K::DictComp { key, value, generators } => {
                h.push(*key);
                h.push(*value);
                h.extend(generators);
            }
            K::Await { value } | K::YieldFrom { value } => h.push(*value),
            K::Yield { value } => o(&mut h, value),
            K::Compare { left, comparators, .. } => {
                h.push(*left);
                h.extend(comparators);
            }
            K::Call { func, args, keywords } => {
                h.push(*func);
                h.extend(args);
                h.extend(keywords);
            }
            K::FormattedValue { value, format_spec, .. } => {
                h.push(*value);
                o(&mut h, format_spec);
            }
            K::JoinedStr { values } => h.extend(values),
            K::Constant { .. } | K::Name { .. } => {}
            K::Attribute { value, .. } | K::Starred { value, .. } => h.push(*value),
            K::Subscript { value, slice, .. } => {
                h.push(*value);
                h.push(*slice);
            }
            K::Slice { lower, upper, step } => {
                o(&mut h, lower);
                o(&mut h, upper);
                o(&mut h, step);
            }
            K::Comprehension { target, iter, ifs, .. } => {
                h.push(*target);
                h.push(*iter);
                h.extend(ifs);
            }
            K::ExceptHandler { type_, body, .. } => {
                o(&mut h, type_);
                h.extend(body);
            }
            K::Arguments { posonlyargs, args, vararg, kwonlyargs, kw_defaults, kwarg, defaults } => {
                h.extend(posonlyargs);
                h.extend(args);
                o(&mut h, vararg);
                h.extend(kwonlyargs);
                h.extend(kw_defaults.iter().flatten());
                o(&mut h, kwarg);
                h.extend(defaults);
            }
            K::Arg { annotation, .. } => o(&mut h, annotation),
            K::Keyword { value, .. } => h.push(*value),
            K::Alias { .. } => {}
            K::WithItem { context_expr, optional_vars } => {
                h.push(*context_expr);
                o(&mut h, optional_vars);
            }
            K::MatchCase { pattern, guard, body } => {
                h.push(*pattern);
                o(&mut h, guard);
                h.extend(body);
            }
            K::MatchValue { value } => h.push(*value),
            K::MatchSingleton { .. } | K::MatchStar { .. } => {}
            K::MatchSequence { patterns } | K::MatchOr { patterns } => h.extend(patterns),
            K::MatchMapping { keys, patterns, .. } => {
                h.extend(keys);
                h.extend(patterns);
            }
            K::MatchClass { cls, patterns, kwd_patterns, .. } => {
                h.push(*cls);
                h.extend(patterns);
                h.extend(kwd_patterns);
            }
            K::MatchAs { pattern, .. } => o(&mut h, pattern),
            K::TypeVar { bound, .. } => o(&mut h, bound),
            K::ParamSpec { .. } | K::TypeVarTuple { .. } => {}
        }
        h
    }

    /// `ast.walk(nodo)`: en anchura, como CPython.
    pub fn recorrer(&self, raiz: Id) -> Vec<Id> {
        let mut salida = Vec::new();
        let mut cola = std::collections::VecDeque::new();
        cola.push_back(raiz);
        while let Some(n) = cola.pop_front() {
            cola.extend(self.hijos(n));
            salida.push(n);
        }
        salida
    }

    /// `ast.get_docstring(nodo)` (con `inspect.cleandoc`).
    pub fn docstring(&self, id: Id) -> Option<String> {
        let body = match self.k(id) {
            K::Module { body } | K::FunctionDef { body, .. } | K::ClassDef { body, .. } => body,
            _ => return None,
        };
        let primero = *body.first()?;
        let K::Expr { value } = self.k(primero) else { return None };
        match self.k(*value) {
            K::Constant { value: Constante::Cadena(s), .. } => Some(crate::py::cadena::cleandoc(s)),
            _ => None,
        }
    }

    /// Nombre (id) si el nodo es un Name.
    pub fn nombre(&self, id: Id) -> Option<&str> {
        match self.k(id) {
            K::Name { id, .. } => Some(id),
            _ => None,
        }
    }

    /// `_constante` del banco: el valor si es una cadena constante.
    pub fn cadena(&self, id: Id) -> Option<&str> {
        match self.k(id) {
            K::Constant { value: Constante::Cadena(s), .. } => Some(s),
            _ => None,
        }
    }

    pub fn es_def(&self, id: Id) -> bool {
        matches!(self.k(id), K::FunctionDef { .. } | K::ClassDef { .. })
    }
}
