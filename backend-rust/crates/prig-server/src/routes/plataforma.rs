//! Lo básico del editor: leer, escribir, crear y borrar archivos, servirlos en crudo (imágenes), abrir el espacio de
//! trabajo y la segunda carpeta (también con el diálogo nativo), los proyectos guardados, y lo que faltaba del IDE
//! (reemplazar, renombrar, duplicar, mostrar en el sistema, problemas, olvidar recientes, acerca de). Con las mismas
//! funciones que usaba el backend de Python (`prig_plataforma::{archivos, espacio, ide}`).
//!
//! El espacio de trabajo se guarda en ~/.prig_config.json (`last_workspace`, `segunda_carpeta`): el backend de Python
//! lo relee cuando cambia, igual que este servidor.

#![allow(clippy::result_large_err)]

use std::collections::HashMap;
use std::path::Path;

use axum::{
    body::{Body, Bytes},
    extract::{Query, State},
    http::{Request, StatusCode},
    response::{IntoResponse, Response},
};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py::{self, ErrorPy};
use prig_plataforma::valor::{Mapa, Valor};
use prig_plataforma::{archivos, espacio, ide};
use tower::ServiceExt;

use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn ok(m: Mapa) -> Response {
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

async fn bloque<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| error_500())
}

/// El espacio de trabajo y las raíces donde se puede leer y escribir: el espacio, la biblioteca de libros, tus
/// repositorios de Prig Hub (los que sigues, no) y la segunda carpeta
pub async fn espacio_y_raices(state: &AppState) -> (String, Vec<String>) {
    let base = espacio_de_trabajo(state).await.to_string_lossy().into_owned();
    let segunda = state.file_mgr.read().await.segunda_dir.clone();
    let hub = std::env::var("PRIG_HUB_DIR").ok().filter(|v| !v.is_empty()).unwrap_or_else(|| py::expanduser("~/.prig_hub"));
    let mut raices = vec![base.clone(), py::abspath(&py::expanduser("~/.prig_books")), py::abspath(&py::join(&hub, "propios"))];
    if let Some(s) = segunda {
        raices.push(s.to_string_lossy().into_owned());
    }
    (base, raices)
}

fn configuracion(state: &AppState) -> String {
    state.config_path.to_string_lossy().into_owned()
}

/// `{"error": …}` → 400 con su detalle; si no, la respuesta tal cual
fn o_400(m: Mapa) -> Response {
    match m.get("error") {
        Some(e) => detalle(StatusCode::BAD_REQUEST, e.texto_py()),
        None => ok(m),
    }
}

/// `_ide`: PermissionError → 403; ErrorIDE y OSError → 400
fn error_ide(e: ErrorPy) -> Response {
    let estado = if matches!(e, ErrorPy::Permiso(_)) { StatusCode::FORBIDDEN } else { StatusCode::BAD_REQUEST };
    detalle(estado, e.texto())
}

fn de_ide(r: Result<Mapa, ErrorPy>) -> Response {
    match r {
        Ok(m) => ok(m),
        Err(e) => error_ide(e),
    }
}

fn consulta(q: &HashMap<String, String>, campo: &str) -> Result<String, Response> {
    q.get(campo).cloned().ok_or_else(|| {
        cuerpo::respuesta(vec![cuerpo::Error {
            tipo: "missing",
            loc: vec!["query".into(), campo.into()],
            msg: "Field required".into(),
            entrada: Valor::Nulo,
            ctx: None,
        }])
    })
}

fn campos(b: &Bytes, c: &[(&str, &Tipo, bool)]) -> Result<Mapa, Response> {
    let m = cuerpo::modelo(b)?;
    cuerpo::tipados(&m, c)
}

fn texto(c: &Mapa, k: &str) -> String {
    c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py).unwrap_or_default()
}

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const LISTA_OPC: Tipo = Tipo::Opcional(&Tipo::Lista(&Tipo::Texto));

// =========================================================================== archivos

/// `GET /api/file?path=`
pub async fn leer(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let ruta = match consulta(&q, "path") {
        Ok(r) => r,
        Err(r) => return r,
    };
    let (base, raices) = espacio_y_raices(&state).await;
    bloque(move || o_400(archivos::leer(&ruta, &base, &raices))).await
}

/// `POST /api/file` (`path`, `content`). La memoria del director (`director.rs`) anota lo guardado.
pub async fn escribir(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("path", &Tipo::Texto, true), ("content", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (base, raices) = espacio_y_raices(&state).await;
    let prig = state.base_dir.clone();
    bloque(move || {
        let (ruta, contenido) = (texto(&c, "path"), texto(&c, "content"));
        let r = archivos::escribir(&ruta, &contenido, &base, &raices);
        if !r.contiene("error") {
            std::thread::spawn(move || crate::routes::director::archivo_guardado(&prig, &ruta, &contenido));
        }
        o_400(r)
    })
    .await
}

/// `DELETE /api/file?path=`
pub async fn borrar(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let ruta = match consulta(&q, "path") {
        Ok(r) => r,
        Err(r) => return r,
    };
    let (base, raices) = espacio_y_raices(&state).await;
    bloque(move || o_400(archivos::borrar(&ruta, &base, &raices))).await
}

/// `POST /api/create` (`path`, `is_dir`)
pub async fn crear(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("path", &Tipo::Texto, true), ("is_dir", &Tipo::Booleano, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (base, raices) = espacio_y_raices(&state).await;
    bloque(move || o_400(archivos::crear(&texto(&c, "path"), c.verdad("is_dir"), &base, &raices))).await
}

/// `GET /api/raw-file?path=` y `GET /api/file/raw?path=`: el archivo tal cual (las imágenes del editor)
pub async fn crudo(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let ruta = match consulta(&q, "path") {
        Ok(r) => r,
        Err(r) => return r,
    };
    let (base, raices) = espacio_y_raices(&state).await;
    let abs = match archivos::resolver(&ruta, &base, &raices) {
        Ok(a) => a,
        Err(e) => return detalle(StatusCode::FORBIDDEN, e),
    };
    if !Path::new(&abs).is_file() {
        return detalle(StatusCode::NOT_FOUND, "Archivo no encontrado");
    }
    let pedido = Request::builder().uri("/").body(Body::empty()).unwrap_or_default();
    match tower_http::services::ServeFile::new(&abs).oneshot(pedido).await {
        Ok(r) => r.into_response(),
        Err(_) => error_500(),
    }
}

// =========================================================================== espacio de trabajo

/// `set_base_dir`: la carpeta (si existe) pasa a ser el espacio de trabajo y se guarda en la configuración
fn abrir_espacio(cfg: &str, ruta: &str) -> Mapa {
    match espacio::carpeta(ruta) {
        Ok((abs, r)) => {
            espacio::guardar_clave(cfg, "last_workspace", Some(&abs));
            let _ = ide::anotar_reciente(cfg, &Valor::Texto(abs));
            r
        }
        Err(e) => e,
    }
}

/// `POST /api/workspace/open` (`path`)
pub async fn abrir(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("path", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let cfg = configuracion(&state);
    let r = tokio::task::spawn_blocking(move || abrir_espacio(&cfg, &texto(&c, "path"))).await.unwrap_or_default();
    espacio_de_trabajo(&state).await; // que este servidor lo tome ya
    o_400(r)
}

/// `POST /api/workspace/browse`: el diálogo nativo para elegir el espacio de trabajo
pub async fn elegir(State(state): State<AppState>) -> Response {
    let cfg = configuracion(&state);
    let r = tokio::task::spawn_blocking(move || match espacio::elegir_con_zenity("Seleccionar Carpeta de Proyecto - Prig IDE") {
        Some(c) => abrir_espacio(&cfg, &c),
        None => Mapa::new().con("error", "No se pudo abrir el diálogo nativo de carpetas"),
    })
    .await
    .unwrap_or_default();
    espacio_de_trabajo(&state).await;
    o_400(r)
}

/// `set_segunda_dir`: la segunda carpeta del explorador (o ninguna)
fn poner_segunda(cfg: &str, ruta: Option<&str>) -> Mapa {
    let abs = match ruta.filter(|r| !r.is_empty()) {
        Some(r) => match espacio::carpeta(r) {
            Ok((abs, _)) => Some(abs),
            Err(e) => return e,
        },
        None => None,
    };
    espacio::guardar_clave(cfg, "segunda_carpeta", abs.as_deref());
    espacio::respuesta_segunda(abs.as_deref())
}

/// `POST /api/workspace/segunda` (`path`, opcional: sin él, se quita)
pub async fn segunda(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("path", &TEXTO_OPC, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let cfg = configuracion(&state);
    let r = tokio::task::spawn_blocking(move || poner_segunda(&cfg, c.get("path").filter(|v| !v.es_nulo()).map(Valor::texto_py).as_deref()))
        .await
        .unwrap_or_default();
    espacio_de_trabajo(&state).await;
    o_400(r)
}

/// `POST /api/workspace/segunda/browse`
pub async fn segunda_elegir(State(state): State<AppState>) -> Response {
    let cfg = configuracion(&state);
    let r = tokio::task::spawn_blocking(move || match espacio::elegir_con_zenity("Seleccionar segunda carpeta - Prig IDE") {
        Some(c) => Ok(poner_segunda(&cfg, Some(&c))),
        None => Err(()),
    })
    .await
    .unwrap_or(Err(()));
    espacio_de_trabajo(&state).await;
    match r {
        Ok(m) => ok(m),
        Err(()) => detalle(StatusCode::BAD_REQUEST, "No se eligió ninguna carpeta"),
    }
}

/// `POST /api/workspace/projects/save` (`path`, `name`, `source`)
pub async fn guardar_proyecto(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("path", &Tipo::Texto, true), ("name", &TEXTO_OPC, false), ("source", &TEXTO_OPC, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let cfg = configuracion(&state);
    bloque(move || {
        let nombre = c.get("name").filter(|v| !v.es_nulo()).map(Valor::texto_py);
        let origen = c.get("source").cloned().unwrap_or_else(|| Valor::Texto("biblioteca".into()));
        de_ide(ide::guardar_proyecto(&cfg, &texto(&c, "path"), nombre.as_deref(), &origen))
    })
    .await
}

/// `POST /api/workspace/projects/remove` (`path`)
pub async fn quitar_proyecto(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("path", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let cfg = configuracion(&state);
    bloque(move || de_ide(ide::eliminar_proyecto(&cfg, &texto(&c, "path")))).await
}

// =========================================================================== IDE

/// `POST /api/ide/reemplazar`: como buscar, con `reemplazo` (y `solo`: los archivos elegidos)
pub async fn reemplazar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(
        &b,
        &[
            ("consulta", &Tipo::Texto, true),
            ("reemplazo", &TEXTO_OPC, false),
            ("regex", &Tipo::Booleano, false),
            ("mayusculas", &Tipo::Booleano, false),
            ("palabra", &Tipo::Booleano, false),
            ("incluir", &Tipo::Texto, false),
            ("excluir", &Tipo::Texto, false),
            ("solo", &LISTA_OPC, false),
        ],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let Some(reemplazo) = c.get("reemplazo").filter(|v| !v.es_nulo()).map(Valor::texto_py) else {
        return detalle(StatusCode::BAD_REQUEST, "Falta el texto de reemplazo.");
    };
    let (base, raices) = espacio_y_raices(&state).await;
    bloque(move || {
        let solo: Option<Vec<String>> = match c.get("solo") {
            Some(Valor::Lista(l)) => Some(l.iter().map(Valor::texto_py).collect()),
            _ => None,
        };
        de_ide(ide::reemplazar(
            &base,
            &raices,
            &texto(&c, "consulta"),
            &reemplazo,
            c.verdad("regex"),
            c.verdad("mayusculas"),
            c.verdad("palabra"),
            &texto(&c, "incluir"),
            &texto(&c, "excluir"),
            solo.as_deref(),
        ))
    })
    .await
}

/// `POST /api/ide/renombrar` (`path`, `destino`)
pub async fn renombrar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("path", &Tipo::Texto, true), ("destino", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (base, raices) = espacio_y_raices(&state).await;
    bloque(move || de_ide(ide::renombrar(&texto(&c, "path"), &texto(&c, "destino"), &base, &raices))).await
}

/// `POST /api/ide/duplicar` (`path`)
pub async fn duplicar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("path", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (base, raices) = espacio_y_raices(&state).await;
    bloque(move || de_ide(ide::duplicar(&texto(&c, "path"), &base, &raices))).await
}

/// `POST /api/ide/mostrar-en-sistema` (`path`)
pub async fn mostrar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("path", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (base, raices) = espacio_y_raices(&state).await;
    bloque(move || de_ide(ide::mostrar_en_sistema(&texto(&c, "path"), &base, &raices))).await
}

/// Lo que comprueba los problemas de un archivo de Python: su propio compilador, con el `python3` del sistema (Python
/// sigue como herramienta para el código del usuario). Errores de sintaxis e indentación, y avisos de tabuladores.
const PROBLEMAS_PY: &str = r#"
import ast, io, json, sys, tokenize
codigo = sys.stdin.read()
problemas = []
try:
    ast.parse(codigo)
except SyntaxError as e:
    linea = e.lineno or 1
    col = e.offset or 1
    fin_col = getattr(e, "end_offset", None) or col + 1
    fin_linea = getattr(e, "end_lineno", None) or linea
    if fin_linea == linea and fin_col <= col:
        fin_col = col + 1
    problemas.append({"linea": linea, "col": col, "fin_linea": fin_linea, "fin_col": fin_col, "gravedad": "error",
                      "mensaje": f"{type(e).__name__}: {e.msg}"})
except ValueError as e:
    problemas.append({"linea": 1, "col": 1, "fin_linea": 1, "fin_col": 2, "gravedad": "error", "mensaje": str(e)})
else:
    try:
        list(tokenize.generate_tokens(io.StringIO(codigo).readline))
    except (tokenize.TokenError, IndentationError) as e:
        problemas.append({"linea": 1, "col": 1, "fin_linea": 1, "fin_col": 2, "gravedad": "aviso", "mensaje": str(e)})
sys.stdout.write(json.dumps(problemas, ensure_ascii=False))
"#;

fn python_del_sistema(raiz: &Path) -> std::path::PathBuf {
    let venv = raiz.join(".venv/bin/python");
    if venv.exists() { venv } else { "python3".into() }
}

fn problemas_python(raiz: &Path, codigo: &str) -> Vec<Valor> {
    use std::io::Write;
    let hijo = std::process::Command::new(python_del_sistema(raiz))
        .args(["-I", "-c", PROBLEMAS_PY])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn();
    let Ok(mut hijo) = hijo else { return Vec::new() };
    if let Some(mut entrada) = hijo.stdin.take() {
        let codigo = codigo.to_string();
        std::thread::spawn(move || {
            let _ = entrada.write_all(codigo.as_bytes());
        });
    }
    match hijo.wait_with_output() {
        Ok(s) => match prig_plataforma::json::leer(&String::from_utf8_lossy(&s.stdout)) {
            Ok(Valor::Lista(l)) => l,
            _ => Vec::new(),
        },
        Err(_) => Vec::new(),
    }
}

/// `POST /api/ide/problemas` (`lenguaje`, `codigo`)
pub async fn problemas(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match campos(&b, &[("lenguaje", &Tipo::Texto, true), ("codigo", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let l = if texto(&c, "lenguaje") == "python" { problemas_python(&raiz, &texto(&c, "codigo")) } else { Vec::new() };
        ok(Mapa::new().con("problemas", Valor::Lista(l)))
    })
    .await
}

/// `DELETE /api/ide/recientes`
pub async fn olvidar_recientes(State(state): State<AppState>) -> Response {
    let cfg = configuracion(&state);
    bloque(move || match ide::olvidar_recientes(&cfg) {
        Ok(()) => ok(Mapa::new().con("ok", true)),
        Err(e) => error_ide(e),
    })
    .await
}

/// `GET /api/ide/acerca`: versiones y carpetas
pub async fn acerca(State(state): State<AppState>) -> Response {
    let ws = espacio_de_trabajo(&state).await.to_string_lossy().into_owned();
    let raiz = state.base_dir.clone();
    bloque(move || {
        let python = std::process::Command::new(python_del_sistema(&raiz))
            .args(["-I", "-c", "import platform;print(platform.python_version())"])
            .output()
            .ok()
            .map(|s| String::from_utf8_lossy(&s.stdout).trim().to_string())
            .unwrap_or_default();
        let (so, version, _) = prig_recursos::detector::uname_publico();
        let ollama = prig_ia::ollama::version_texto(&raiz);
        ok(Mapa::new()
            .con("prig", "Prig IDE")
            .con("python", python)
            .con("sistema", format!("{so} {version}"))
            .con("ollama", ollama)
            .con("workspace", ws)
            .con("backend", raiz.join("backend").to_string_lossy().into_owned()))
    })
    .await
}
