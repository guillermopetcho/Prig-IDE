//! El explorador de carpetas para elegir libros (`explorador.py`). SOLO LISTA: nombres, tamaños y fechas, nunca el
//! contenido de un archivo. Navega solo dentro de la carpeta personal y del espacio de trabajo, comprobado sobre la
//! ruta real (con los enlaces resueltos), y sin nada oculto.

use crate::py::{self, abspath, ErrorPy};
use crate::valor::{redondear, Mapa, Valor};
use std::path::Path;

pub const EXTENSIONES: &[(&str, &str)] = &[
    (".pdf", "PDF"),
    (".epub", "EPUB"),
    (".djvu", "DjVu"),
    (".md", "Markdown"),
    (".txt", "Texto"),
    (".rst", "reStructuredText"),
    (".ipynb", "Cuaderno"),
    (".tex", "LaTeX"),
];

pub const IGNORADAS: &[&str] = &[
    "node_modules", "__pycache__", "site-packages", ".git", ".cache", "snap", "venv", ".venv", "env", "AppData", "Library",
    "Trash", ".local", ".config", ".mozilla", ".steam", "Papelera",
];

pub const ATAJOS: &[(&str, &str)] = &[
    ("Biblioteca de Prig", "~/.prig_books"),
    ("Descargas", "~/Descargas"),
    ("Downloads", "~/Downloads"),
    ("Documentos", "~/Documentos"),
    ("Documents", "~/Documents"),
    ("Escritorio", "~/Escritorio"),
    ("Desktop", "~/Desktop"),
    ("Carpeta personal", "~"),
];

type R<T> = Result<T, ErrorPy>;

fn tipo_de(nombre: &str) -> Option<(String, &'static str)> {
    let ext = py::extension(nombre).to_lowercase();
    EXTENSIONES.iter().find(|(e, _)| *e == ext).map(|(_, t)| (ext, *t))
}

fn es_dir(p: &str) -> bool {
    !p.contains('\0') && Path::new(p).is_dir()
}

/// Dónde se puede navegar: la carpeta personal y el espacio de trabajo (los atributos del objeto de Python)
pub struct Ambito<'a> {
    pub raiz: &'a str,
    pub workspace: Option<&'a str>,
}

impl Ambito<'_> {
    /// `permitida`: sobre la ruta real (sin eso, un enlace a / dejaría navegar el disco entero)
    pub fn permitida(&self, ruta: &str) -> bool {
        let real = py::realpath(ruta);
        std::iter::once(self.raiz).chain(self.workspace).map(py::realpath).any(|p| real == p || real.starts_with(&format!("{p}/")))
    }

    /// `atajos`
    pub fn atajos(&self) -> Vec<Valor> {
        let mut salida: Vec<(String, String)> = Vec::new();
        for (nombre, ruta) in ATAJOS {
            let completa = abspath(&py::expanduser(ruta));
            if es_dir(&completa) && !salida.iter().any(|s| s.1 == completa) {
                salida.push((nombre.to_string(), completa));
            }
        }
        if let Some(w) = self.workspace {
            if es_dir(w) {
                salida.insert(0, ("Espacio de trabajo".into(), w.to_string()));
            }
        }
        salida.into_iter().map(|(n, r)| Valor::Mapa(Mapa::new().con("nombre", n).con("ruta", r))).collect()
    }

    /// `listar`: carpetas y libros de una ruta (con `recursivo`, también los de las subcarpetas)
    pub fn listar(&self, ruta: Option<&str>, recursivo: bool) -> R<Mapa> {
        let ruta = abspath(&py::expanduser(match ruta {
            Some(r) if !r.is_empty() => r,
            _ => "~",
        }));
        if !self.permitida(&ruta) {
            return Err(ErrorPy::Permiso(format!(
                "Solo se puede navegar dentro de tu carpeta personal. '{ruta}' queda fuera."
            )));
        }
        if !es_dir(&ruta) {
            return Err(ErrorPy::NoEsCarpeta(format!("No es una carpeta: {ruta}")));
        }
        let leidas = match std::fs::read_dir(&ruta) {
            Ok(l) => l,
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                return Err(ErrorPy::Permiso(format!("Sin permiso para leer {ruta}")))
            }
            Err(e) => return Err(ErrorPy::os(&e, &ruta)),
        };
        let mut entradas: Vec<std::fs::DirEntry> = leidas.flatten().collect();
        entradas.sort_by_key(|e| e.file_name().to_string_lossy().to_lowercase());
        let mut carpetas = Vec::new();
        let mut libros = Vec::new();
        for e in entradas {
            let nombre = e.file_name().to_string_lossy().into_owned();
            if nombre.starts_with('.') || IGNORADAS.contains(&nombre.as_str()) {
                continue;
            }
            let Ok(t) = e.file_type() else { continue };
            let completa = py::join(&ruta, &nombre);
            if t.is_dir() {
                let n = contar(&completa, 200);
                carpetas.push(Valor::Mapa(Mapa::new().con("nombre", nombre).con("ruta", completa).con("libros_dentro", n)));
            } else if t.is_file() {
                let Some((ext, tipo)) = tipo_de(&nombre) else { continue };
                let Ok(m) = std::fs::metadata(&completa) else { continue };
                libros.push(Valor::Mapa(ficha_libro(nombre, completa, tipo, ext, &m)));
            }
        }
        if recursivo {
            let ya = libros.len();
            libros.extend(self.buscar_hondo(&ruta, ya, 300).into_iter().map(Valor::Mapa));
        }
        let padre = py::dirname(&ruta);
        let padre = if self.permitida(&padre) && padre != ruta { Valor::Texto(padre) } else { Valor::Nulo };
        let nombre = {
            let b = py::basename(&ruta);
            if b.is_empty() {
                ruta.clone()
            } else {
                b
            }
        };
        let total = libros.len();
        Ok(Mapa::new()
            .con("ruta", ruta.clone())
            .con("nombre", nombre)
            .con("padre", padre)
            .con("migas", Valor::Lista(self.migas(&ruta)))
            .con("carpetas", Valor::Lista(carpetas))
            .con("libros", Valor::Lista(libros))
            .con("total_libros", total))
    }

    /// `_buscar_hondo`: los libros de las subcarpetas (no los de la carpeta misma)
    fn buscar_hondo(&self, ruta: &str, ya: usize, tope: usize) -> Vec<Mapa> {
        let mut salida = Vec::new();
        let _ = walk(ruta, &mut |raiz, ficheros| {
            if raiz == ruta {
                return true;
            }
            let mut ficheros = ficheros.to_vec();
            ficheros.sort();
            for nombre in ficheros {
                let Some((ext, tipo)) = tipo_de(&nombre) else { continue };
                let completa = py::join(raiz, &nombre);
                let Ok(m) = std::fs::metadata(&completa) else { continue };
                let mut f = ficha_libro(nombre, completa, tipo, ext, &m);
                f.poner("subcarpeta", py::relpath(raiz, ruta));
                salida.push(f);
                if ya + salida.len() >= tope {
                    return false;
                }
            }
            true
        });
        salida
    }

    /// `_migas`: el camino desde la carpeta personal, para poder volver atrás
    fn migas(&self, ruta: &str) -> Vec<Valor> {
        let mut migas = Vec::new();
        let mut actual = ruta.to_string();
        while self.permitida(&actual) {
            let b = py::basename(&actual);
            let nombre = if b.is_empty() { actual.clone() } else { b };
            migas.insert(0, Valor::Mapa(Mapa::new().con("nombre", nombre).con("ruta", actual.clone())));
            let padre = py::dirname(&actual);
            if padre == actual {
                break;
            }
            actual = padre;
        }
        migas
    }

    /// `buscar`: un libro por su nombre en todo el árbol (todas las palabras, en cualquier orden)
    pub fn buscar(&self, texto: &str, desde: Option<&str>, tope: usize) -> R<Vec<Valor>> {
        let desde = abspath(&py::expanduser(match desde {
            Some(d) if !d.is_empty() => d,
            _ => "~",
        }));
        if !self.permitida(&desde) {
            return Err(ErrorPy::Permiso("Esa carpeta queda fuera de tu carpeta personal".into()));
        }
        let bajo = texto.to_lowercase();
        let agujas: Vec<&str> = bajo.split(|c: char| c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)).filter(|t| !t.is_empty()).collect();
        if agujas.is_empty() {
            return Ok(Vec::new());
        }
        let mut salida = Vec::new();
        let _ = walk(&desde, &mut |raiz, ficheros| {
            for nombre in ficheros {
                let Some((ext, tipo)) = tipo_de(nombre) else { continue };
                let n = nombre.to_lowercase();
                if !agujas.iter().all(|a| n.contains(a)) {
                    continue;
                }
                let completa = py::join(raiz, nombre);
                let Ok(m) = std::fs::metadata(&completa) else { continue };
                let carpeta = py::dirname(&completa);
                let mut f = ficha_libro(nombre.clone(), completa, tipo, ext, &m);
                f.poner("carpeta", carpeta);
                salida.push(Valor::Mapa(f));
                if salida.len() >= tope {
                    return false;
                }
            }
            true
        });
        Ok(salida)
    }
}

fn ficha_libro(nombre: String, ruta: String, tipo: &str, ext: String, m: &std::fs::Metadata) -> Mapa {
    use std::os::unix::fs::MetadataExt;
    let mtime = m.mtime() as f64 + m.mtime_nsec() as f64 / 1e9;
    Mapa::new()
        .con("nombre", nombre)
        .con("ruta", ruta)
        .con("tipo", tipo)
        .con("extension", ext)
        .con("mb", redondear(m.len() as f64 / (1024.0 * 1024.0), 2))
        .con("modificado", py::fecha_local(mtime))
}

/// `_contar`: cuántos libros hay en una carpeta (solo el primer nivel, hasta `tope`)
fn contar(carpeta: &str, tope: usize) -> usize {
    let Ok(leidas) = std::fs::read_dir(carpeta) else { return 0 };
    let mut n = 0;
    for e in leidas {
        let Ok(e) = e else { return 0 };
        let nombre = e.file_name().to_string_lossy().into_owned();
        if nombre.starts_with('.') {
            continue;
        }
        if e.file_type().map(|t| t.is_file()).unwrap_or(false) && tipo_de(&nombre).is_some() {
            n += 1;
            if n >= tope {
                break;
            }
        }
    }
    n
}

/// `os.walk(raiz)` sin seguir enlaces y sin las carpetas ocultas o ignoradas, en el orden del directorio (sin
/// ordenar, como Python): `f(carpeta, archivos)`, y `false` para parar
fn walk(raiz: &str, f: &mut dyn FnMut(&str, &[String]) -> bool) -> bool {
    let Ok(leidas) = std::fs::read_dir(raiz) else { return true };
    let mut dirs = Vec::new();
    let mut archivos = Vec::new();
    for e in leidas {
        let Ok(e) = e else { return true };
        let nombre = e.file_name().to_string_lossy().into_owned();
        let carpeta = match e.file_type() {
            Ok(t) if t.is_symlink() => std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false),
            Ok(t) => t.is_dir(),
            Err(_) => false,
        };
        if carpeta {
            dirs.push(nombre);
        } else {
            archivos.push(nombre);
        }
    }
    if !f(raiz, &archivos) {
        return false;
    }
    for d in dirs {
        if d.starts_with('.') || IGNORADAS.contains(&d.as_str()) {
            continue;
        }
        let nueva = py::join(raiz, &d);
        if std::fs::symlink_metadata(&nueva).map(|m| m.file_type().is_symlink()).unwrap_or(false) {
            continue;
        }
        if !walk(&nueva, f) {
            return false;
        }
    }
    true
}
