//! Ir a archivo (`GET /api/ide/archivos`) y buscar en archivos (`POST /api/ide/buscar`): lo mismo que
//! `ide_servicios.ServiciosIDE.listar` y `.buscar` de Python, y más rápido en proyectos grandes. Lo demás del IDE
//! (reemplazar, renombrar, duplicar, problemas, recientes…) lo atiende Python por el proxy.

use axum::{extract::State, http::StatusCode, response::Json};
use banco_core::py::cadena::splitlines;
use banco_core::re::Re;
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

use crate::routes::workspace::espacio_de_trabajo;
use crate::state::AppState;

/// `ide_servicios.IGNORADAS` (con `target`, que también ignora Python: las compilaciones de Rust tienen miles de
/// archivos)
const IGNORADAS: &[&str] = &[
    "__pycache__", "node_modules", "venv", ".venv", "env", ".git", ".github", ".ipynb_checkpoints", "dist", "build",
    ".cache", "site-packages", ".idea", ".vscode", ".gemini", ".mypy_cache", ".pytest_cache", ".tox", "target",
];
const MAX_ARCHIVOS: usize = 20_000;
const MAX_BYTES_BUSQUEDA: u64 = 2 * 1024 * 1024;
const MAX_COINCIDENCIAS: usize = 5_000;

/// `_recorrer(raiz)`: `os.walk` de arriba abajo, sin seguir enlaces a carpetas (aparecen como carpetas pero no se
/// entra), carpetas y archivos en orden, sin ocultos salvo `.gitignore` y `.env.example`. `visitar` devuelve false
/// para cortar.
fn recorrer(carpeta: &Path, visitar: &mut dyn FnMut(PathBuf) -> bool) -> bool {
    let Ok(lectura) = fs::read_dir(carpeta) else {
        return true;
    };
    let mut subcarpetas: Vec<(String, PathBuf, bool)> = Vec::new();
    let mut archivos: Vec<(String, PathBuf)> = Vec::new();
    for entrada in lectura.flatten() {
        let nombre = entrada.file_name().to_string_lossy().to_string();
        let ruta = entrada.path();
        let Ok(tipo) = entrada.file_type() else { continue };
        // os.walk clasifica con is_dir() siguiendo enlaces, pero solo entra en carpetas que no son enlaces
        let es_enlace = tipo.is_symlink();
        let es_carpeta = if es_enlace { ruta.is_dir() } else { tipo.is_dir() };
        if es_carpeta {
            subcarpetas.push((nombre, ruta, es_enlace));
        } else {
            archivos.push((nombre, ruta));
        }
    }
    subcarpetas.retain(|(n, _, _)| !IGNORADAS.contains(&n.as_str()) && !n.starts_with('.'));
    subcarpetas.sort_by(|a, b| a.0.cmp(&b.0));
    archivos.sort_by(|a, b| a.0.cmp(&b.0));
    for (nombre, ruta) in archivos {
        if nombre.starts_with('.') && nombre != ".gitignore" && nombre != ".env.example" {
            continue;
        }
        if !visitar(ruta) {
            return false;
        }
    }
    for (_, ruta, es_enlace) in subcarpetas {
        if !es_enlace && !recorrer(&ruta, visitar) {
            return false;
        }
    }
    true
}

fn relativa(ruta: &Path, raiz: &Path) -> String {
    ruta.strip_prefix(raiz).unwrap_or(ruta).to_string_lossy().replace('\\', "/")
}

/// `fnmatch.translate` (POSIX: distingue mayúsculas): `*`, `?` y `[...]` / `[!...]`.
fn fnmatch_regex(patron: &str) -> String {
    let c: Vec<char> = patron.chars().collect();
    let mut salida = String::from("^(?s:");
    let mut i = 0;
    while i < c.len() {
        let ch = c[i];
        i += 1;
        match ch {
            '*' => {
                while i < c.len() && c[i] == '*' {
                    i += 1;
                }
                salida.push_str(".*");
            }
            '?' => salida.push('.'),
            '[' => {
                let mut j = i;
                if j < c.len() && c[j] == '!' {
                    j += 1;
                }
                if j < c.len() && c[j] == ']' {
                    j += 1;
                }
                while j < c.len() && c[j] != ']' {
                    j += 1;
                }
                if j >= c.len() {
                    salida.push_str("\\[");
                } else {
                    let dentro: String = c[i..j].iter().collect();
                    i = j + 1;
                    let mut clase = String::new();
                    for (k, x) in dentro.chars().enumerate() {
                        if k == 0 && x == '!' {
                            clase.push('^');
                        } else if k == 0 && x == '^' {
                            clase.push_str("\\^");
                        } else if matches!(x, '\\' | '[' | '&' | '~') {
                            clase.push('\\');
                            clase.push(x);
                        } else {
                            clase.push(x);
                        }
                    }
                    salida.push('[');
                    salida.push_str(&clase);
                    salida.push(']');
                }
            }
            otro => salida.push_str(&regex::escape(&otro.to_string())),
        }
    }
    salida.push_str(")$");
    salida
}

fn fnmatch(nombre: &str, patron: &str) -> bool {
    regex::Regex::new(&fnmatch_regex(patron)).map(|r| r.is_match(nombre)).unwrap_or(false)
}

/// `_coincide_patrones`
fn coincide_patrones(relativa: &str, incluir: &[String], excluir: &[String]) -> bool {
    let casa = |patron: &String| -> bool {
        let patron = patron.trim();
        if patron.is_empty() {
            return false;
        }
        if !patron.contains('/') && !patron.chars().any(|c| matches!(c, '*' | '?' | '[')) {
            return relativa.split('/').any(|s| s == patron);
        }
        let base = relativa.rsplit('/').next().unwrap_or(relativa);
        fnmatch(relativa, patron)
            || fnmatch(base, patron)
            || fnmatch(relativa, &format!("*/{patron}"))
            || relativa.starts_with(&format!("{}/", patron.trim_end_matches('/')))
    };
    if !incluir.is_empty() && !incluir.iter().any(casa) {
        return false;
    }
    !excluir.iter().any(casa)
}

/// `_patrones`
fn patrones(texto: &str) -> Vec<String> {
    texto.split(',').map(|p| p.trim().to_string()).filter(|p| !p.is_empty()).collect()
}

// =========================================================================
// GET /api/ide/archivos
// =========================================================================

pub async fn ide_archivos(State(state): State<AppState>) -> Json<Value> {
    let raiz = espacio_de_trabajo(&state).await;
    let respuesta = tokio::task::spawn_blocking(move || {
        let mut salida: Vec<Value> = Vec::new();
        let mut truncado = false;
        recorrer(&raiz, &mut |ruta| {
            if salida.len() >= MAX_ARCHIVOS {
                truncado = true;
                return false;
            }
            salida.push(json!({"path": ruta.to_string_lossy(), "rel": relativa(&ruta, &raiz)}));
            true
        });
        json!({"raiz": raiz.to_string_lossy(), "archivos": salida, "truncado": truncado})
    })
    .await
    .unwrap_or_else(|_| json!({"raiz": "", "archivos": [], "truncado": false}));
    Json(respuesta)
}

// =========================================================================
// POST /api/ide/buscar
// =========================================================================

#[derive(Deserialize)]
pub struct IdeBuscarRequest {
    pub consulta: String,
    #[serde(default)]
    pub regex: bool,
    #[serde(default)]
    pub mayusculas: bool,
    #[serde(default)]
    pub palabra: bool,
    #[serde(default)]
    pub incluir: String,
    #[serde(default)]
    pub excluir: String,
}

/// `_expresion`: la consulta con la sintaxis de `re` de Python (la traduce `banco_core::re`), palabra completa como
/// `(?<!\w)…(?!\w)` y sin distinguir mayúsculas salvo que se pida.
fn expresion(consulta: &str, es_regex: bool, mayusculas: bool, palabra: bool) -> Result<Re, String> {
    if consulta.is_empty() {
        return Err("Escribe qué buscar.".to_string());
    }
    let mut patron = if es_regex { consulta.to_string() } else { regex::escape(consulta) };
    if palabra {
        patron = format!(r"(?<!\w){patron}(?!\w)");
    }
    Re::intentar(&patron, if mayusculas { "" } else { "i" }).map_err(|e| format!("Expresión regular no válida: {e}"))
}

/// El texto de un archivo como lo busca Python: archivo regular de hasta 2 MB, sin bytes nulos en los primeros 8 KB
/// y UTF-8 válido. (Python también abría FIFOs y otros especiales, y con uno se quedaba esperando: aquí se saltan.)
fn texto_buscable(ruta: &Path) -> Option<String> {
    let meta = fs::metadata(ruta).ok()?;
    if !meta.is_file() || meta.len() > MAX_BYTES_BUSQUEDA {
        return None;
    }
    let datos = fs::read(ruta).ok()?;
    if datos[..datos.len().min(8192)].contains(&0) {
        return None;
    }
    String::from_utf8(datos).ok()
}

fn buscar(raiz: &Path, expr: &Re, incluir: &[String], excluir: &[String]) -> Value {
    let mut resultados: Vec<Value> = Vec::new();
    let (mut total, mut truncado, mut revisados) = (0usize, false, 0usize);
    recorrer(raiz, &mut |ruta| {
        let rel = relativa(&ruta, raiz);
        if !coincide_patrones(&rel, incluir, excluir) {
            return true;
        }
        let Some(texto) = texto_buscable(&ruta) else { return true };
        revisados += 1;
        let mut coincidencias: Vec<Value> = Vec::new();
        'lineas: for (n, linea) in splitlines(&texto).into_iter().enumerate() {
            for m in expr.todos(linea) {
                if m.inicio == m.fin {
                    continue;
                }
                coincidencias.push(json!({
                    "linea": n + 1,
                    "col": linea[..m.inicio].chars().count() + 1,
                    "fin": linea[..m.fin].chars().count() + 1,
                    "texto": linea.chars().take(400).collect::<String>(),
                    "trozo": m.todo().chars().take(200).collect::<String>(),
                }));
                total += 1;
                if total >= MAX_COINCIDENCIAS {
                    truncado = true;
                    break 'lineas;
                }
            }
        }
        if !coincidencias.is_empty() {
            resultados.push(json!({"path": ruta.to_string_lossy(), "rel": rel, "coincidencias": coincidencias}));
        }
        !truncado
    });
    let archivos = resultados.len();
    json!({"resultados": resultados, "total": total, "archivos": archivos, "revisados": revisados, "truncado": truncado})
}

pub async fn ide_buscar(
    State(state): State<AppState>,
    Json(req): Json<IdeBuscarRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let expr = expresion(&req.consulta, req.regex, req.mayusculas, req.palabra)
        .map_err(|e| (StatusCode::BAD_REQUEST, Json(json!({"detail": e}))))?;
    let raiz = espacio_de_trabajo(&state).await;
    let (inc, exc) = (patrones(&req.incluir), patrones(&req.excluir));
    let respuesta = tokio::task::spawn_blocking(move || buscar(&raiz, &expr, &inc, &exc))
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"detail": e.to_string()}))))?;
    Ok(Json(respuesta))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fnmatch_como_python() {
        assert!(fnmatch("src/a.py", "*.py"));
        assert!(fnmatch("a.py", "?.py"));
        assert!(!fnmatch("A.PY", "*.py"), "en Linux fnmatch distingue mayúsculas");
        assert!(fnmatch("b.py", "[ab].py"));
        assert!(!fnmatch("c.py", "[ab].py"));
        assert!(fnmatch("c.py", "[!ab].py"));
        assert!(fnmatch("[x", "[x"), "un corchete sin cerrar es literal");
        assert!(fnmatch("a+b", "a+b"));
    }

    #[test]
    fn patrones_como_python() {
        let inc = vec!["src".to_string()];
        assert!(coincide_patrones("src/a.py", &inc, &[]));
        assert!(!coincide_patrones("otro/a.py", &inc, &[]));
        assert!(coincide_patrones("x/src/a.py", &inc, &[]), "un nombre suelto casa con cualquier segmento");
        let exc = vec!["*.min.js".to_string()];
        assert!(!coincide_patrones("web/app.min.js", &[], &exc));
        assert!(coincide_patrones("web/app.js", &[], &exc));
    }

    #[test]
    fn palabra_completa_como_python() {
        // Casos donde Python ((?<!\w)…(?!\w)) y \b difieren (comprobados con re de Python)
        let e = expresion("f(", false, false, true).unwrap();
        assert!(e.hay("x = f( 1)"));
        assert!(!e.hay("x = f(1)"));
        assert!(!e.hay("gf( 1)"));
        let e = expresion("x.", false, false, true).unwrap();
        assert!(e.hay("a = x. y"));
        assert!(!e.hay("a = x.y"));
        let r = expresion(r"\bdef\s+(\w+)", true, true, false).unwrap();
        assert!(r.hay("def nombre():"));
        assert!(!r.hay("DEF nombre():"), "con mayusculas=true distingue");
    }
}
