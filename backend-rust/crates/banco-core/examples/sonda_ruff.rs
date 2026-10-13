use ruff_python_ast::{Expr, Stmt};
use ruff_python_parser::{parse, Mode, ParseOptions};
use ruff_python_ast::PythonVersion;
use ruff_text_size::Ranged;

fn linea(src: &str, off: usize) -> usize {
    let b = src.as_bytes();
    let mut l = 1;
    let mut i = 0;
    while i < off && i < b.len() {
        if b[i] == b'\n' { l += 1; } else if b[i] == b'\r' { if i + 1 < b.len() && b[i + 1] == b'\n' { i += 1; } l += 1; }
        i += 1;
    }
    l
}

fn probar(nombre: &str, src: &str) {
    let opciones = ParseOptions::from(Mode::Module).with_target_version(PythonVersion::PY312);
    match parse(src, opciones) {
        Ok(p) => {
            let errs = p.errors().len();
            let unsup = p.unsupported_syntax_errors().len();
            let m = p.into_syntax();
            let modulo = m.as_module().unwrap();
            let mut desc = vec![];
            for s in &modulo.body {
                let r = s.range();
                let mut d = format!("{} {}-{}", tipo(s), linea(src, r.start().to_usize()), linea(src, r.end().to_usize()));
                if let Stmt::FunctionDef(f) = s { d += &format!(" nombre@{} decos@{:?}", linea(src, f.name.range.start().to_usize()), f.decorator_list.iter().map(|x| linea(src, x.expression.range().start().to_usize())).collect::<Vec<_>>()); }
                if let Stmt::Expr(e) = s { d += &format!(" expr@{}:{}", linea(src, e.value.range().start().to_usize()), e.value.range().start().to_usize()); if let Expr::Call(c) = e.value.as_ref() { d += &format!(" func@{}", c.func.range().start().to_usize()); } if let Expr::Attribute(a) = e.value.as_ref() { d += &format!(" attrvalue@{}", a.value.range().start().to_usize()); } }
                desc.push(d);
            }
            println!("{nombre}: ok errs={errs} unsup={unsup} {:?}", desc);
        }
        Err(e) => println!("{nombre}: ERROR {e}"),
    }
}
fn tipo(s: &Stmt) -> &'static str { match s { Stmt::FunctionDef(_) => "def", Stmt::Expr(_) => "expr", Stmt::Assign(_) => "assign", _ => "otro" } }

fn main() {
    probar("bom", "\u{feff}x = 1\ny = 2");
    probar("cr", "x = 1\ry = 2\r\nz = 3");
    probar("ff", "x = 1\n\x0cy = 2");
    probar("nul", "x = 1\0");
    probar("deco", "@a\n@b(1)\ndef f():\n    pass\n");
    probar("call", "(f)(x)\n(a.\nb)(y)\n(a).b\n");
    probar("py313", "def f[T = int](): pass\n");
    probar("lazy", "lazy import os\n");
    probar("feff_medio", "x = 1\ny = \u{feff}2\n");
    probar("fstring312", "f\"{x['a']}\"\nf'{\"b\"}'\n");
}
