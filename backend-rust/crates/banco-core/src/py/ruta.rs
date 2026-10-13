//! `posixpath` de Python 3.12: basename, dirname, splitext, normpath, join y commonpath.

/// `os.path.basename`.
pub fn basename(p: &str) -> &str {
    match p.rfind('/') {
        Some(i) => &p[i + 1..],
        None => p,
    }
}

/// `os.path.dirname`.
pub fn dirname(p: &str) -> &str {
    let i = match p.rfind('/') {
        Some(i) => i + 1,
        None => 0,
    };
    let cabeza = &p[..i];
    if !cabeza.is_empty() && cabeza.chars().any(|c| c != '/') {
        cabeza.trim_end_matches('/')
    } else {
        cabeza
    }
}

/// `os.path.splitext`: (raíz, extensión); los puntos iniciales del nombre no cuentan.
pub fn splitext(p: &str) -> (&str, &str) {
    let sep = p.rfind('/').map(|i| i as isize).unwrap_or(-1);
    let punto = p.rfind('.').map(|i| i as isize).unwrap_or(-1);
    if punto > sep {
        let mut i = (sep + 1) as usize;
        let punto = punto as usize;
        let bytes = p.as_bytes();
        while i < punto {
            if bytes[i] != b'.' {
                return (&p[..punto], &p[punto..]);
            }
            i += 1;
        }
    }
    (p, "")
}

/// `os.path.normpath` (posix).
pub fn normpath(p: &str) -> String {
    if p.is_empty() {
        return ".".to_string();
    }
    let mut iniciales = if p.starts_with('/') { 1 } else { 0 };
    if iniciales == 1 && p.starts_with("//") && !p.starts_with("///") {
        iniciales = 2;
    }
    let mut nuevas: Vec<&str> = Vec::new();
    for parte in p.split('/') {
        if parte.is_empty() || parte == "." {
            continue;
        }
        if parte != ".." || (iniciales == 0 && nuevas.is_empty()) || nuevas.last() == Some(&"..") {
            nuevas.push(parte);
        } else if !nuevas.is_empty() {
            nuevas.pop();
        }
    }
    let mut salida = "/".repeat(iniciales);
    salida.push_str(&nuevas.join("/"));
    if salida.is_empty() {
        ".".to_string()
    } else {
        salida
    }
}

/// `os.path.join(a, b)`.
pub fn join(a: &str, b: &str) -> String {
    if b.starts_with('/') {
        return b.to_string();
    }
    if a.is_empty() || a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

/// `os.path.commonpath` (rutas relativas o absolutas, no mezcladas).
pub fn commonpath(rutas: &[&str]) -> String {
    if rutas.is_empty() {
        return String::new();
    }
    let absoluta = rutas[0].starts_with('/');
    let partidas: Vec<Vec<&str>> = rutas
        .iter()
        .map(|r| r.split('/').filter(|c| !c.is_empty() && *c != ".").collect())
        .collect();
    let s1 = partidas.iter().min().unwrap();
    let s2 = partidas.iter().max().unwrap();
    let mut comun: &[&str] = s1;
    for (i, c) in s1.iter().enumerate() {
        if s2.get(i) != Some(c) {
            comun = &s1[..i];
            break;
        }
    }
    let prefijo = if absoluta { "/" } else { "" };
    format!("{prefijo}{}", comun.join("/"))
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn como_posixpath() {
        assert_eq!(dirname("a/b/c.py"), "a/b");
        assert_eq!(dirname("c.py"), "");
        assert_eq!(dirname("/x"), "/");
        assert_eq!(splitext("a/.bashrc"), ("a/.bashrc", ""));
        assert_eq!(splitext("a/b.tar.gz"), ("a/b.tar", ".gz"));
        assert_eq!(normpath("a/./b/../c"), "a/c");
        assert_eq!(normpath("../a"), "../a");
        assert_eq!(commonpath(&["backend/a.py", "backend/b/c.py"]), "backend");
        assert_eq!(commonpath(&["a.py", "b.py"]), "");
    }
}
