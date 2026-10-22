//! Los archivos del usuario (`file_manager.py`): qué rutas se pueden tocar (la carpeta de trabajo, la segunda carpeta
//! del explorador y las raíces extra), el árbol del explorador, leer (también cuadernos), escribir, crear y borrar.
//! Rust no guarda estado: la carpeta de trabajo y las raíces las da quien llama, cada vez (en Python son atributos
//! del `FileManager`, que las pruebas pueden cambiar).

use crate::py::{self, abspath, bajo_raiz, error_os, get, iterar, unir};
use crate::valor::{Mapa, Valor};
use std::path::Path;

/// Las carpetas que no se muestran en el árbol
pub const IGNORADAS: &[&str] = &[
    "__pycache__", "node_modules", "venv", ".venv", "env", ".env", ".git", ".github", ".ipynb_checkpoints", "dist",
    "build", ".cache", "site-packages", ".idea", ".vscode", ".gemini", "target",
];

/// `is_path_allowed`: la ruta (absoluta, normalizada) cae dentro de alguna raíz
pub fn permitida(abs_path: &str, raices: &[String]) -> bool {
    let abs_path = abspath(abs_path);
    raices.iter().any(|r| bajo_raiz(&abs_path, r) == Some(true))
}

/// `resolve`: la ruta absoluta (relativa a la carpeta de trabajo), o el texto del PermissionError
pub fn resolver(ruta: &str, base: &str, raices: &[String]) -> Result<String, String> {
    if ruta.is_empty() {
        return Err("Ruta no especificada".into());
    }
    let abs = abspath(&if py::isabs(ruta) { ruta.to_string() } else { py::join(base, ruta) });
    if !permitida(&abs, raices) {
        return Err(format!("Acceso denegado: '{abs}' está fuera de la carpeta de trabajo."));
    }
    Ok(abs)
}

fn es_dir(p: &str) -> bool {
    !p.contains('\0') && Path::new(p).is_dir()
}

fn es_archivo(p: &str) -> bool {
    !p.contains('\0') && Path::new(p).is_file()
}

/// `get_file_tree`: los avisos (`Error leyendo dir ...`) van a `avisos`
pub fn arbol(ruta: Option<&str>, base: &str, raices: &[String], max: i64, nivel: i64, avisos: &mut Vec<String>) -> Vec<Valor> {
    let destino = match ruta {
        Some(r) if !r.is_empty() => abspath(r),
        _ => base.to_string(),
    };
    if !es_dir(&destino) || nivel >= max || !permitida(&destino, raices) {
        return Vec::new();
    }
    let mut salida = Vec::new();
    let leidas = match std::fs::read_dir(&destino) {
        Ok(l) => l,
        Err(e) => {
            avisos.push(format!("Error leyendo dir {destino}: {}", error_os(&e, &destino)));
            return salida;
        }
    };
    let mut entradas: Vec<(bool, String, String)> = Vec::new();
    for e in leidas.flatten() {
        let nombre = e.file_name().to_string_lossy().into_owned();
        let completa = py::join(&destino, &nombre);
        entradas.push((!es_dir(&completa), nombre.to_lowercase(), nombre));
    }
    entradas.sort_by(|a, b| (a.0, &a.1).cmp(&(b.0, &b.1)));
    for (_, _, nombre) in entradas {
        if (nombre.starts_with('.') && nombre != ".gitignore" && nombre != ".env.example") || IGNORADAS.contains(&nombre.as_str()) {
            continue;
        }
        let completa = py::join(&destino, &nombre);
        let carpeta = es_dir(&completa);
        let hijos = if carpeta {
            Valor::Lista(arbol(Some(&completa), base, raices, max, nivel + 1, avisos))
        } else {
            Valor::Nulo
        };
        salida.push(Valor::Mapa(
            Mapa::new().con("name", nombre).con("path", completa).con("is_dir", carpeta).con("children", hijos),
        ));
    }
    salida
}

fn error(texto: impl Into<String>) -> Mapa {
    Mapa::new().con("error", texto.into())
}

/// `read_file`
pub fn leer(ruta: &str, base: &str, raices: &[String]) -> Mapa {
    let abs = match resolver(ruta, base, raices) {
        Ok(a) => a,
        Err(e) => return error(e),
    };
    if !es_archivo(&abs) {
        return error(format!("Archivo no encontrado: {ruta}"));
    }
    let contenido = match py::leer_texto(&abs) {
        Ok(c) => c,
        Err(e) => return error(e),
    };
    let nombre = py::basename(&abs);
    if py::extension(&abs).to_lowercase() == ".ipynb" {
        let cuaderno = cuaderno(&contenido, &abs);
        return Mapa::new()
            .con("path", abs)
            .con("name", nombre)
            .con("content", contenido)
            .con("notebook_data", cuaderno)
            .con("is_notebook", true);
    }
    Mapa::new().con("path", abs).con("name", nombre).con("content", contenido).con("is_notebook", false)
}

fn unir_o_igual(v: &Valor) -> Result<Valor, String> {
    match v {
        Valor::Lista(_) => Ok(Valor::Texto(unir("", v)?)),
        otro => Ok(otro.clone()),
    }
}

/// `read_notebook_structured`: las celdas de un cuaderno ya listas para la interfaz
pub fn cuaderno(json_str: &str, ruta: &str) -> Mapa {
    match celdas(json_str) {
        Ok(c) => Mapa::new().con("path", ruta).con("name", py::basename(ruta)).con("cells", c),
        Err(e) => Mapa::new().con("error", format!("Error parseando notebook: {e}")).con("cells", Valor::Lista(vec![])),
    }
}

fn celdas(json_str: &str) -> Result<Vec<Valor>, String> {
    let datos = crate::json::leer(json_str)?;
    let crudas = get(&datos, "cells", Valor::Lista(vec![]))?;
    let mut celdas = Vec::new();
    for (i, celda) in iterar(&crudas)?.into_iter().enumerate() {
        let idx = i as i64 + 1;
        let tipo = get(&celda, "cell_type", "code".into())?;
        let fuente = get(&celda, "source", Valor::Lista(vec![]))?;
        let mut fuente = match &fuente {
            Valor::Lista(_) => unir("", &fuente)?,
            otro => otro.texto_py(),
        };

        // Adjuntos de las celdas Markdown
        let adjuntos = get(&celda, "attachments", Valor::Mapa(Mapa::new()))?;
        if adjuntos.verdad() {
            if let Valor::Mapa(adj) = &adjuntos {
                for (nombre, mimes) in py::items(adj) {
                    if let Valor::Mapa(mimes) = mimes {
                        for (mime, b64) in py::items(&mimes) {
                            let limpio = match &b64 {
                                Valor::Lista(_) => unir("", &b64)?,
                                otro => otro.texto_py(),
                            };
                            let limpio = limpio.replace(['\n', '\r'], "");
                            let limpio = limpio.trim_matches(|c: char| c.is_whitespace() || ('\x1c'..='\x1f').contains(&c));
                            fuente = fuente.replace(&format!("attachment:{nombre}"), &format!("data:{mime};base64,{limpio}"));
                        }
                    }
                }
            }
        }

        let mut salidas = Vec::new();
        for out in iterar(&get(&celda, "outputs", Valor::Lista(vec![]))?)? {
            let tipo_salida = get(&out, "output_type", "".into())?;
            let tipo_salida = match &tipo_salida {
                Valor::Texto(t) => t.as_str(),
                _ => "",
            };
            match tipo_salida {
                "stream" => {
                    let texto = unir("", &get(&out, "text", Valor::Lista(vec![]))?)?;
                    let nombre = get(&out, "name", "stdout".into())?;
                    salidas.push(Valor::Mapa(Mapa::new().con("type", "stream").con("text", texto).con("name", nombre)));
                }
                "execute_result" | "display_data" => {
                    let datos = get(&out, "data", Valor::Mapa(Mapa::new()))?;
                    if py::contiene(&datos, "text/html")? {
                        let texto = unir_o_igual(&py::item(&datos, "text/html")?)?;
                        salidas.push(Valor::Mapa(Mapa::new().con("type", "html").con("text", texto)));
                    } else {
                        let mut imagen = false;
                        for mime in ["image/png", "image/jpeg", "image/jpg", "image/svg+xml", "image/gif"] {
                            if py::contiene(&datos, mime)? {
                                let d = unir_o_igual(&py::item(&datos, mime)?)?;
                                salidas.push(Valor::Mapa(Mapa::new().con("type", "image").con("data", d).con("mime", mime)));
                                imagen = true;
                                break;
                            }
                        }
                        if !imagen && py::contiene(&datos, "text/plain")? {
                            let texto = unir_o_igual(&py::item(&datos, "text/plain")?)?;
                            salidas.push(Valor::Mapa(Mapa::new().con("type", "text").con("text", texto)));
                        }
                    }
                }
                "error" => {
                    let ename = get(&out, "ename", "".into())?;
                    let evalue = get(&out, "evalue", "".into())?;
                    let traza = unir("\n", &get(&out, "traceback", Valor::Lista(vec![]))?)?;
                    let texto = format!("{}: {}\n{traza}", ename.texto_py(), evalue.texto_py());
                    salidas.push(Valor::Mapa(Mapa::new().con("type", "error").con("text", texto)));
                }
                _ => {}
            }
        }

        celdas.push(Valor::Mapa(
            Mapa::new()
                .con("id", format!("cell_{idx}"))
                .con("index", idx)
                .con("type", tipo)
                .con("source", fuente)
                .con("execution_count", get(&celda, "execution_count", Valor::Nulo)?)
                .con("outputs", Valor::Lista(salidas)),
        ));
    }
    Ok(celdas)
}

/// `write_file`
pub fn escribir(ruta: &str, contenido: &str, base: &str, raices: &[String]) -> Mapa {
    let abs = match resolver(ruta, base, raices) {
        Ok(a) => a,
        Err(e) => return error(e),
    };
    if let Err(e) = py::makedirs(&py::dirname(&abs)).and_then(|_| py::escribir_texto(&abs, contenido)) {
        return error(e);
    }
    Mapa::new().con("success", true).con("path", abs)
}

/// `create_item`
pub fn crear(ruta: &str, carpeta: bool, base: &str, raices: &[String]) -> Mapa {
    let abs = match resolver(ruta, base, raices) {
        Ok(a) => a,
        Err(e) => return error(e),
    };
    let r = if carpeta {
        py::makedirs(&abs)
    } else {
        py::makedirs(&py::dirname(&abs)).and_then(|_| if Path::new(&abs).exists() { Ok(()) } else { py::escribir_texto(&abs, "") })
    };
    match r {
        Ok(()) => Mapa::new().con("success", true).con("path", abs),
        Err(e) => error(e),
    }
}

/// `delete_item`: nunca una raíz entera
pub fn borrar(ruta: &str, base: &str, raices: &[String]) -> Mapa {
    let abs = match resolver(ruta, base, raices) {
        Ok(a) => a,
        Err(e) => return error(e),
    };
    if raices.contains(&abs) {
        return error("No se puede eliminar la carpeta raíz del espacio de trabajo.");
    }
    let r = if es_dir(&abs) {
        borrar_arbol(&abs)
    } else if es_archivo(&abs) {
        std::fs::remove_file(&abs).map_err(|e| error_os(&e, &abs))
    } else {
        return error(format!("No existe: {ruta}"));
    };
    match r {
        Ok(()) => Mapa::new().con("success", true).con("path", abs),
        Err(e) => error(e),
    }
}

/// `shutil.rmtree`: un enlace a una carpeta no se sigue (Python da OSError «Cannot call rmtree on a symbolic link»)
fn borrar_arbol(ruta: &str) -> Result<(), String> {
    let meta = std::fs::symlink_metadata(ruta).map_err(|e| error_os(&e, ruta))?;
    if meta.file_type().is_symlink() {
        return Err("Cannot call rmtree on a symbolic link".into());
    }
    fn dentro(ruta: &str) -> Result<(), String> {
        let entradas = std::fs::read_dir(ruta).map_err(|e| error_os(&e, ruta))?;
        for e in entradas {
            let e = e.map_err(|e| error_os(&e, ruta))?;
            let hijo = py::join(ruta, &e.file_name().to_string_lossy());
            let tipo = e.file_type().map_err(|e| error_os(&e, &hijo))?;
            if tipo.is_dir() {
                dentro(&hijo)?;
            } else {
                std::fs::remove_file(&hijo).map_err(|e| error_os(&e, &hijo))?;
            }
        }
        std::fs::remove_dir(ruta).map_err(|e| error_os(&e, ruta))
    }
    dentro(ruta)
}
