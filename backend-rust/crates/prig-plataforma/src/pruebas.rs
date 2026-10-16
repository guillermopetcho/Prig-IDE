//! Pruebas del núcleo con valores sacados de Python 3.12

use crate::py;
use crate::regex_py::{plantilla, ExpresionPy, Reemplazo};

#[test]
fn rutas_como_os_path() {
    assert_eq!(py::normpath("/a//b/./c/../d/"), "/a/b/d");
    assert_eq!(py::normpath("//a/b"), "//a/b");
    assert_eq!(py::normpath("///a"), "/a");
    assert_eq!(py::normpath("../x/.."), "..");
    assert_eq!(py::normpath(""), ".");
    assert_eq!(py::split("/a/b/"), ("/a/b".into(), "".into()));
    assert_eq!(py::split("//"), ("//".into(), "".into()));
    assert_eq!(py::extension("/x/.bashrc"), "");
    assert_eq!(py::extension("/x/..raro"), "");
    assert_eq!(py::extension("a.tar.gz"), ".gz");
    assert_eq!(py::relpath("/a/b/c", "/a/x"), "../b/c");
    assert_eq!(py::bajo_raiz("/a/bc", "/a/b"), Some(false));
    assert_eq!(py::bajo_raiz("/a/b/c", "/a/b"), Some(true));
    assert_eq!(py::bajo_raiz("/a/b", "/a/b/"), Some(false)); // la raíz sin normalizar no casa, como en Python
    assert_eq!(py::bajo_raiz("/a", "rel"), None);
}

#[test]
fn errores_de_decodificacion_como_python() {
    let d = crate::ejecucion::decodificar;
    assert_eq!(d(b"ok\xff").unwrap_err(), "'utf-8' codec can't decode byte 0xff in position 2: invalid start byte");
    assert_eq!(d(b"\xe2\x82").unwrap_err(), "'utf-8' codec can't decode bytes in position 0-1: unexpected end of data");
    assert_eq!(d(b"\xe2(").unwrap_err(), "'utf-8' codec can't decode byte 0xe2 in position 0: invalid continuation byte");
    assert_eq!(d(b"a\r\nb\rc").unwrap(), "a\nb\nc");
}

fn sub(patron: &str, plantilla_: &str, texto: &str) -> (String, usize) {
    let e = ExpresionPy::compilar(patron, true).unwrap();
    let p = plantilla(plantilla_, &e).unwrap();
    e.subn(texto, &Reemplazo::Plantilla(p))
}

#[test]
fn expresiones_como_re() {
    // re.subn('x*', '-', 'abxd') == ('-a-b--d-', 5)
    assert_eq!(sub("x*", "-", "abxd"), ("-a-b--d-".into(), 5));
    // re.subn('foo|', '#', 'afoo') == ('#a##', 3)
    assert_eq!(sub("foo|", "#", "afoo"), ("#a##".into(), 3));
    assert_eq!(sub(r"(\w+)=(\w+)", r"\2=\1", "a=b c=d"), ("b=a d=c".into(), 2));
    assert_eq!(sub(r"(?P<n>o)", r"[\g<n>\g<0>]", "oo"), ("[oo][oo]".into(), 2));
    assert_eq!(sub("a{2}", "X", "aaa{2}"), ("Xa{2}".into(), 1));
    assert_eq!(sub("a{", "X", "a{"), ("X".into(), 1));
    assert_eq!(sub("b$", "X", "ab\n"), ("aX\n".into(), 1));
    assert_eq!(sub("[[]", "X", "a[b"), ("aXb".into(), 1));
    assert_eq!(sub(r"\101", "X", "A"), ("X".into(), 1));
}

#[test]
fn plantillas_con_los_errores_de_python() {
    let e = ExpresionPy::compilar("(a)", true).unwrap();
    let err = |t: &str| plantilla(t, &e).err().unwrap();
    assert_eq!(err(r"\q"), "bad escape \\q at position 0");
    assert_eq!(err(r"x\2"), "invalid group reference 2 at position 2");
    assert_eq!(err(r"\g<x>"), "unknown group name 'x'");
    assert_eq!(err(r"\g<1"), "missing >, unterminated name at position 3");
    assert_eq!(err("\\"), "bad escape (end of pattern) at position 0");
    assert!(ExpresionPy::compilar("a(?i)b", true).err().unwrap().starts_with("global flags not at the start"));
}

#[test]
fn unescape_como_python() {
    let casos = crate::json::leer(include_str!("html_casos_python.json")).unwrap();
    let crate::valor::Valor::Lista(casos) = casos else { panic!() };
    let mut malos = Vec::new();
    for c in casos {
        let crate::valor::Valor::Lista(par) = c else { panic!() };
        let (e, s) = (par[0].texto_py(), par[1].texto_py());
        let r = crate::html::unescape(&e);
        if r != s {
            malos.push(format!("{e:?}: python {s:?}, rust {r:?}"));
        }
    }
    assert!(malos.is_empty(), "{}", malos.join("\n"));
}
