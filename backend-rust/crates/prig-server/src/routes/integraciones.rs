//! Las integraciones (GitHub y Kaggle) que no usan el modelo: el estado de las cuentas, las credenciales de Kaggle, sus
//! colecciones (enteras: crear, editar, borrar, elementos y notas) y lo leído. La lógica está en
//! `prig_integrations::kaggle`; se lee del disco en cada llamada y se escribe en los mismos archivos que Python.

use axum::{
    body::Bytes,
    extract::{Path as Ruta, Query},
    http::StatusCode,
    response::Response,
};
use std::collections::HashMap;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use std::path::PathBuf;

use crate::routes::{detalle, json_py};
use crate::routes::cuerpo;

fn entorno(var: &str) -> Option<String> {
    std::env::var(var).ok().filter(|v| !v.is_empty())
}

fn ruta_de(var: &str, defecto: &str) -> PathBuf {
    PathBuf::from(entorno(var).unwrap_or_else(|| py::expanduser(defecto)))
}

fn verdad(m: &Mapa, clave: &str) -> bool {
    m.get(clave).is_some_and(Valor::verdad)
}

fn error_500() -> Response {
    use axum::response::IntoResponse;
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

// ---------------------------------------------------------------------------------------------- GitHub

/// `github_lector.estado()`
pub async fn github_estado() -> Response {
    let guardado = match prig_aprendizaje::desafios::leer_json(&ruta_de("PRIG_GITHUB_CREDENCIALES", "~/.prig_github.json")) {
        Some(Valor::Mapa(m)) => m,
        Some(v) if v.verdad() => return error_500(), // `.get` sobre algo que no es un dict: AttributeError en Python
        _ => Mapa::new(),
    };
    let origen: Option<String> = if verdad(&guardado, "token") {
        Some("Prig".into())
    } else {
        ["GITHUB_TOKEN", "GH_TOKEN"].iter().find(|v| entorno(v).is_some()).map(|v| format!("variable {v}"))
    };
    let con = origen.is_some();
    let m = Mapa::new()
        .con("con_token", con)
        .con("origen", origen.map(Valor::Texto).unwrap_or(Valor::Nulo))
        .con("limite", if con { "5000 consultas por hora" } else { "60 consultas por hora y 10 búsquedas por minuto" })
        .con("url_token", "https://github.com/settings/tokens?type=beta");
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

// ---------------------------------------------------------------------------------------------- Kaggle

use prig_integrations::kaggle::{self, Fallo};

fn respuesta(r: Result<Result<Mapa, Fallo>, tokio::task::JoinError>) -> Response {
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(Fallo::Usuario(e))) => detalle(StatusCode::BAD_REQUEST, e.0),
        _ => error_500(),
    }
}

/// `GET /api/kaggle/estado`: si hay cuenta (nunca la clave ni el token)
pub async fn kaggle_estado() -> Response {
    match tokio::task::spawn_blocking(kaggle::estado).await {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

/// `POST /api/kaggle/credenciales` (`texto`): se comprueba con Kaggle antes de guardarla
pub async fn kaggle_credenciales(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let texto = c.texto("texto", None);
    if let Err(r) = c.fin() {
        return r;
    }
    respuesta(tokio::task::spawn_blocking(move || kaggle::guardar_credenciales(&texto.texto_py()).map_err(Fallo::from)).await)
}

/// `DELETE /api/kaggle/credenciales`
pub async fn kaggle_borrar_credenciales() -> Response {
    respuesta(tokio::task::spawn_blocking(|| Ok(kaggle::borrar_credenciales())).await)
}

/// `GET /api/kaggle/colecciones`
pub async fn kaggle_colecciones_listar() -> Response {
    respuesta(tokio::task::spawn_blocking(kaggle::listado).await)
}

/// `Optional[str]` de `KaggleColeccionRequest` (None si falta o es null)
fn opcional(v: &Valor) -> Option<String> {
    match v {
        Valor::Texto(t) => Some(t.clone()),
        _ => None,
    }
}

/// `POST /api/kaggle/colecciones` (`nombre`, `descripcion`, `color`)
pub async fn kaggle_colecciones_crear(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let (n, d, col) = (c.texto("nombre", Some(Valor::Nulo)), c.texto("descripcion", Some(Valor::Nulo)), c.texto("color", Some(Valor::Nulo)));
    if let Err(r) = c.fin() {
        return r;
    }
    respuesta(
        tokio::task::spawn_blocking(move || kaggle::crear(&opcional(&n).unwrap_or_default(), &opcional(&d).unwrap_or_default(), opcional(&col).as_deref()))
            .await,
    )
}

/// `GET /api/kaggle/colecciones/{id_}`
pub async fn kaggle_coleccion(Ruta(id): Ruta<String>) -> Response {
    respuesta(tokio::task::spawn_blocking(move || kaggle::obtener(&id)).await)
}

/// `PATCH /api/kaggle/colecciones/{id_}` (`nombre`, `descripcion`, `color`; lo que falte no se toca)
pub async fn kaggle_coleccion_editar(Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let (n, d, col) = (c.texto("nombre", Some(Valor::Nulo)), c.texto("descripcion", Some(Valor::Nulo)), c.texto("color", Some(Valor::Nulo)));
    if let Err(r) = c.fin() {
        return r;
    }
    respuesta(
        tokio::task::spawn_blocking(move || kaggle::editar(&id, opcional(&n).as_deref(), opcional(&d).as_deref(), opcional(&col).as_deref())).await,
    )
}

/// `DELETE /api/kaggle/colecciones/{id_}`
pub async fn kaggle_coleccion_borrar(Ruta(id): Ruta<String>) -> Response {
    respuesta(tokio::task::spawn_blocking(move || kaggle::borrar(&id)).await)
}

/// `KaggleItemRequest`: `tipo`, `ref` (obligatorios), `datos` (dict opcional), `nota`
fn item(b: &Bytes) -> Result<(String, String, Option<Mapa>, Option<String>), Response> {
    let m = cuerpo::modelo(b)?;
    let mut c = cuerpo::Campos::new(&m);
    let tipo = c.texto("tipo", None);
    let r = c.texto("ref", None);
    let nota = c.texto("nota", Some(Valor::Nulo));
    let datos = match m.get("datos") {
        None | Some(Valor::Nulo) => Ok(None),
        Some(Valor::Mapa(d)) => Ok(Some(d.clone())),
        Some(v) => Err(cuerpo::Error {
            tipo: "dict_type",
            loc: vec![Valor::Texto("body".into()), Valor::Texto("datos".into())],
            msg: "Input should be a valid dictionary".into(),
            entrada: v.clone(),
            ctx: None,
        }),
    };
    let fin = c.fin();
    match (fin, datos) {
        (Ok(()), Ok(d)) => Ok((tipo.texto_py(), r.texto_py(), d, opcional(&nota))),
        (Ok(()), Err(e)) => Err(cuerpo::respuesta(vec![e])),
        (Err(r), _) => Err(r),
    }
}

/// `POST /api/kaggle/colecciones/{id_}/items`
pub async fn kaggle_coleccion_anadir(Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let (tipo, r, datos, _) = match item(&b) {
        Ok(x) => x,
        Err(r) => return r,
    };
    respuesta(tokio::task::spawn_blocking(move || kaggle::anadir(&id, &tipo, &r, datos.as_ref())).await)
}

/// `PATCH /api/kaggle/colecciones/{id_}/items`: la nota de un elemento
pub async fn kaggle_coleccion_nota(Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let (tipo, r, _, nota) = match item(&b) {
        Ok(x) => x,
        Err(r) => return r,
    };
    respuesta(tokio::task::spawn_blocking(move || kaggle::anotar(&id, &tipo, &r, &nota.unwrap_or_default())).await)
}

/// `DELETE /api/kaggle/colecciones/{id_}/items?tipo=&ref=`
pub async fn kaggle_coleccion_quitar(Ruta(id): Ruta<String>, Query(q): Query<HashMap<String, String>>) -> Response {
    let faltan: Vec<cuerpo::Error> = ["tipo", "ref"]
        .iter()
        .filter(|k| !q.contains_key(**k))
        .map(|k| cuerpo::Error {
            tipo: "missing",
            loc: vec![Valor::Texto("query".into()), Valor::Texto(k.to_string())],
            msg: "Field required".into(),
            entrada: Valor::Nulo,
            ctx: None,
        })
        .collect();
    if !faltan.is_empty() {
        return cuerpo::respuesta(faltan);
    }
    let (tipo, r) = (q["tipo"].clone(), q["ref"].clone());
    respuesta(tokio::task::spawn_blocking(move || kaggle::quitar(&id, &tipo, &r)).await)
}

/// `GET /api/kaggle/lecturas`
pub async fn kaggle_lecturas() -> Response {
    respuesta(
        tokio::task::spawn_blocking(|| kaggle::resumen_lecturas().map(|l| Mapa::new().con("lecturas", Valor::Lista(l.into_iter().map(Valor::Mapa).collect()))))
            .await,
    )
}

use prig_integrations::kaggle_datos;

/// FastAPI responde 500 si el JSON lleva NaN o infinito (`allow_nan=False`)
fn con_no_finitos(v: &Valor) -> bool {
    match v {
        Valor::Real(x) => !x.is_finite(),
        Valor::Lista(l) => l.iter().any(con_no_finitos),
        Valor::Mapa(m) => m.iter().any(|(_, x)| con_no_finitos(x)),
        _ => false,
    }
}

fn respuesta_finita(r: Result<Result<Mapa, Fallo>, tokio::task::JoinError>) -> Response {
    match r {
        Ok(Ok(m)) if con_no_finitos(&Valor::Mapa(m.clone())) => error_500(),
        otro => respuesta(otro),
    }
}

/// `GET /api/kaggle/mis_datos`: lo descargado en el proyecto
pub async fn kaggle_mis_datos(axum::extract::State(state): axum::extract::State<crate::state::AppState>) -> Response {
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || {
            kaggle_datos::mis_datos(&espacio).map(|l| {
                Mapa::new().con("datos", Valor::Lista(l.into_iter().map(Valor::Mapa).collect())).con("carpeta", kaggle_datos::CARPETA_DATOS)
            })
        })
        .await,
    )
}

fn ruta_consulta(q: &HashMap<String, String>) -> Result<String, Response> {
    q.get("ruta").cloned().ok_or_else(|| {
        cuerpo::respuesta(vec![cuerpo::Error {
            tipo: "missing",
            loc: vec![Valor::Texto("query".into()), Valor::Texto("ruta".into())],
            msg: "Field required".into(),
            entrada: Valor::Nulo,
            ctx: None,
        }])
    })
}

/// `GET /api/kaggle/previa?ruta=`: primeras filas y un resumen por columna
pub async fn kaggle_previa(axum::extract::State(state): axum::extract::State<crate::state::AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let ruta = match ruta_consulta(&q) {
        Ok(r) => r,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    respuesta_finita(tokio::task::spawn_blocking(move || kaggle_datos::vista_previa(&ruta, &espacio, 15)).await)
}

/// `GET /api/kaggle/archivo?ruta=`: una imagen de los datos descargados
pub async fn kaggle_archivo(axum::extract::State(state): axum::extract::State<crate::state::AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    use axum::response::IntoResponse;
    let ruta = match ruta_consulta(&q) {
        Ok(r) => r,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || kaggle_datos::imagen(&ruta, &espacio).and_then(|p| std::fs::read(&p).ok().map(|b| (p, b)))).await;
    match r {
        Ok(Some((p, b))) => {
            let tipo = match p.extension().map(|e| e.to_string_lossy().to_lowercase()).as_deref() {
                Some("png") => "image/png",
                Some("jpg") | Some("jpeg") => "image/jpeg",
                Some("gif") => "image/gif",
                _ => "image/webp",
            };
            ([(axum::http::header::CONTENT_TYPE, tipo)], b).into_response()
        }
        Ok(None) => detalle(StatusCode::NOT_FOUND, "No encontrado."),
        Err(_) => error_500(),
    }
}

use prig_integrations::kaggle_red;

type Consulta = Query<HashMap<String, String>>;

fn q_texto(q: &HashMap<String, String>, k: &str) -> String {
    q.get(k).cloned().unwrap_or_default()
}

macro_rules! o_responder {
    ($e:expr) => {
        match $e {
            Ok(x) => x,
            Err(r) => return r,
        }
    };
}

/// `GET /api/kaggle/buscar`: notebooks de la comunidad
pub async fn kaggle_buscar(Query(q): Consulta) -> Response {
    let pagina = o_responder!(cuerpo::entero_consulta(&q, "pagina", 1, 1, 100));
    let votos_min = o_responder!(cuerpo::entero_consulta(&q, "votos_min", 0, 0, i64::MAX));
    let dias = o_responder!(cuerpo::entero_consulta(&q, "dias", 0, 0, i64::MAX));
    let gpu = o_responder!(cuerpo::booleano_consulta(&q, "gpu"));
    let b = kaggle_red::Busqueda {
        consulta: q_texto(&q, "q"),
        orden: q.get("orden").cloned().unwrap_or_else(|| "relevancia".into()),
        pagina,
        competicion: q_texto(&q, "competicion"),
        dataset: q_texto(&q, "dataset"),
        usuario: q_texto(&q, "usuario"),
        tipo: q_texto(&q, "tipo"),
        votos_min,
        dias,
        gpu,
        padre: q_texto(&q, "padre"),
    };
    respuesta(tokio::task::spawn_blocking(move || kaggle_red::buscar(&b)).await)
}

/// `GET /api/kaggle/notebook?ref=&refrescar=`
pub async fn kaggle_notebook(axum::extract::State(state): axum::extract::State<crate::state::AppState>, Query(q): Consulta) -> Response {
    let r = o_responder!(cuerpo::texto_consulta(&q, "ref"));
    let refrescar = o_responder!(cuerpo::booleano_consulta(&q, "refrescar")).unwrap_or(false);
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    respuesta_finita(tokio::task::spawn_blocking(move || kaggle_red::notebook(&r, refrescar, &espacio)).await)
}

/// `POST /api/kaggle/importar` (`ref`): el .ipynb original en kaggle_notebooks/ del proyecto
pub async fn kaggle_importar(axum::extract::State(state): axum::extract::State<crate::state::AppState>, b: Bytes) -> Response {
    let m = o_responder!(cuerpo::modelo(&b));
    let mut c = cuerpo::Campos::new(&m);
    let r = c.texto("ref", None);
    let _ = c.texto("modelo", Some(Valor::Nulo));
    let _ = c.booleano_opcional("regenerar");
    let _ = c.booleano_opcional("incluir_datos");
    o_responder!(c.fin());
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    respuesta(tokio::task::spawn_blocking(move || kaggle_red::importar(&r.texto_py(), &espacio)).await)
}

/// `GET /api/kaggle/datasets`
pub async fn kaggle_datasets(Query(q): Consulta) -> Response {
    let pagina = o_responder!(cuerpo::entero_consulta(&q, "pagina", 1, 1, 100));
    respuesta(
        tokio::task::spawn_blocking(move || {
            kaggle_red::buscar_datasets(
                &q_texto(&q, "q"),
                q.get("orden").map(String::as_str).unwrap_or("populares"),
                pagina,
                &q_texto(&q, "tipo_archivo"),
                &q_texto(&q, "licencia"),
                &q_texto(&q, "tamano"),
                &q_texto(&q, "usuario"),
            )
        })
        .await,
    )
}

/// `GET /api/kaggle/competiciones`
pub async fn kaggle_competiciones(Query(q): Consulta) -> Response {
    let pagina = o_responder!(cuerpo::entero_consulta(&q, "pagina", 1, 1, 100));
    respuesta(
        tokio::task::spawn_blocking(move || {
            kaggle_red::buscar_competiciones(&q_texto(&q, "q"), &q_texto(&q, "categoria"), q.get("orden").map(String::as_str).unwrap_or("agrupadas"), pagina, &q_texto(&q, "grupo"))
        })
        .await,
    )
}

/// `GET /api/kaggle/dataset?ref=` y `GET /api/kaggle/competicion?ref=`: la ficha con lo descargado
pub async fn kaggle_dataset(st: axum::extract::State<crate::state::AppState>, q: Consulta) -> Response {
    kaggle_ficha(st, "dataset", q).await
}

pub async fn kaggle_competicion(st: axum::extract::State<crate::state::AppState>, q: Consulta) -> Response {
    kaggle_ficha(st, "competicion", q).await
}

async fn kaggle_ficha(axum::extract::State(state): axum::extract::State<crate::state::AppState>, tipo: &'static str, Query(q): Consulta) -> Response {
    let r = o_responder!(cuerpo::texto_consulta(&q, "ref"));
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || if tipo == "dataset" { kaggle_red::dataset(&r, Some(&espacio)) } else { kaggle_red::competicion(&r, Some(&espacio)) })
            .await,
    )
}

/// `POST /api/kaggle/descargar` (`tipo`, `ref`): baja y descomprime los datos (NDJSON: progreso, y «fin» o «error»)
pub async fn kaggle_descargar(axum::extract::State(state): axum::extract::State<crate::state::AppState>, b: Bytes) -> Response {
    use axum::response::IntoResponse;
    let m = o_responder!(cuerpo::modelo(&b));
    let mut c = cuerpo::Campos::new(&m);
    let tipo = c.texto("tipo", None).texto_py();
    let r = c.texto("ref", None).texto_py();
    let _ = c.texto("modelo", Some(Valor::Nulo));
    let _ = c.booleano_opcional("regenerar");
    o_responder!(c.fin());
    if tipo != "dataset" && tipo != "competicion" {
        return detalle(StatusCode::BAD_REQUEST, "Tipo desconocido: dataset o competicion.");
    }
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<axum::body::Bytes, std::io::Error>>(64);
    std::thread::spawn(move || {
        let linea = |v: Mapa| axum::body::Bytes::from(prig_plataforma::json::escribir_linea(&Valor::Mapa(v)) + "\n");
        let mut avisar = |ev: Mapa| tx.blocking_send(Ok(linea(ev))).is_ok();
        let fin = match kaggle_red::descargar(&tipo, &r, &espacio, &mut avisar) {
            Ok(res) => Mapa::new().con("tipo", "fin").con("resultado", res),
            Err(Fallo::Usuario(e)) => Mapa::new().con("tipo", "error").con("mensaje", e.0),
            Err(Fallo::Interno) => Mapa::new().con("tipo", "error").con("mensaje", "Error interno al descargar."),
        };
        let _ = tx.blocking_send(Ok(linea(fin)));
    });
    let flujo = futures_util::stream::unfold(rx, |mut rx| async move { rx.recv().await.map(|x| (x, rx)) });
    ([(axum::http::header::CONTENT_TYPE, "application/x-ndjson")], axum::body::Body::from_stream(flujo)).into_response()
}

use prig_integrations::kaggle_pdf;

/// `POST /api/kaggle/pdf` (`ref` o `coleccion`; `nivel`, `solo_explicadas`, `guia`, `salidas`, `chat`)
pub async fn kaggle_pdf_crear(axum::extract::State(state): axum::extract::State<crate::state::AppState>, b: Bytes) -> Response {
    let m = o_responder!(cuerpo::modelo(&b));
    let mut c = cuerpo::Campos::new(&m);
    let r = c.texto("ref", Some(Valor::Nulo));
    let col = c.texto("coleccion", Some(Valor::Nulo));
    let nivel = c.texto("nivel", Some(Valor::Nulo));
    let solo = c.booleano_opcional("solo_explicadas").unwrap_or(false);
    let guia = c.booleano_opcional("guia").unwrap_or(true);
    let salidas = c.booleano_opcional("salidas").unwrap_or(true);
    let chat = match m.get("chat") {
        None | Some(Valor::Nulo) => None,
        Some(_) => Some(c.lista_de_dicts("chat").into_iter().filter_map(|v| if let Valor::Mapa(x) = v { Some(x) } else { None }).collect::<Vec<_>>()),
    };
    o_responder!(c.fin());
    let op = kaggle_pdf::Opciones { nivel: opcional(&nivel), solo_explicadas: solo, guia, salidas, chat };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || {
            if let Some(id) = opcional(&col).filter(|x| !x.is_empty()) {
                let coleccion = kaggle::obtener(&id)?;
                return kaggle_pdf::pdf_coleccion(&coleccion, &espacio, &op);
            }
            match opcional(&r).filter(|x| !x.is_empty()) {
                Some(r) => kaggle_pdf::pdf_notebook(&r, &espacio, &op),
                None => Err(Fallo::Usuario(kaggle::ErrorKaggle("Falta el notebook o la colección.".into()))),
            }
        })
        .await,
    )
}

/// `GET /api/kaggle/pdf?ruta=&descargar=`: el PDF generado (para verlo o guardarlo)
pub async fn kaggle_pdf_archivo(axum::extract::State(state): axum::extract::State<crate::state::AppState>, Query(q): Consulta) -> Response {
    use axum::response::IntoResponse;
    let ruta = o_responder!(cuerpo::texto_consulta(&q, "ruta"));
    let descargar = o_responder!(cuerpo::booleano_consulta(&q, "descargar")).unwrap_or(false);
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || kaggle_pdf::ruta_segura(&ruta, &espacio).and_then(|p| std::fs::read(&p).ok().map(|b| (p, b)))).await;
    match r {
        Ok(Some((p, b))) => {
            let nombre = p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
            let disp = format!("{}; filename=\"{nombre}\"", if descargar { "attachment" } else { "inline" });
            ([(axum::http::header::CONTENT_TYPE, "application/pdf".to_string()), (axum::http::header::CONTENT_DISPOSITION, disp)], b).into_response()
        }
        Ok(None) => detalle(StatusCode::NOT_FOUND, "Ese PDF no existe."),
        Err(_) => error_500(),
    }
}

/// `POST /api/kaggle/pdf/abrir` (`ref`: la ruta): lo abre con el visor del sistema
pub async fn kaggle_pdf_abrir(axum::extract::State(state): axum::extract::State<crate::state::AppState>, b: Bytes) -> Response {
    let m = o_responder!(cuerpo::modelo(&b));
    let mut c = cuerpo::Campos::new(&m);
    let r = c.texto("ref", None).texto_py();
    let _ = c.texto("modelo", Some(Valor::Nulo));
    let _ = c.booleano_opcional("regenerar");
    let _ = c.booleano_opcional("incluir_datos");
    o_responder!(c.fin());
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let Some(real) = kaggle_pdf::ruta_segura(&r, &espacio) else { return detalle(StatusCode::NOT_FOUND, "Ese PDF no existe.") };
    let lanzado = std::process::Command::new("xdg-open")
        .arg(&real)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
    match lanzado {
        Ok(_) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("ok", true))),
        Err(_) => detalle(StatusCode::BAD_REQUEST, "No hay un visor de PDF configurado en el sistema."),
    }
}

// ---------------------------------------------------------------------------------------------- GitHub (lector)

use prig_integrations::github;

/// `GithubRefRequest`: `ref` (obligatorio), `ruta`, `nivel`, `modelo`, `regenerar`, `nota`, `mensajes`
fn peticion_github(b: &Bytes) -> Result<(String, Option<String>), Response> {
    let m = cuerpo::modelo(b)?;
    let mut c = cuerpo::Campos::new(&m);
    let r = c.texto("ref", None);
    let _ = c.texto("ruta", Some(Valor::Nulo));
    let _ = c.texto("nivel", Some(Valor::Nulo));
    let _ = c.texto("modelo", Some(Valor::Nulo));
    let _ = c.booleano_opcional("regenerar");
    let nota = c.texto("nota", Some(Valor::Nulo));
    if m.get("mensajes").is_some_and(|v| !v.es_nulo()) {
        let _ = c.lista_de_dicts("mensajes");
    }
    c.fin()?;
    Ok((r.texto_py(), opcional(&nota)))
}

/// `POST /api/github/token` (`texto`)
pub async fn github_token(b: Bytes) -> Response {
    let m = o_responder!(cuerpo::modelo(&b));
    let mut c = cuerpo::Campos::new(&m);
    let t = c.texto("texto", None).texto_py();
    o_responder!(c.fin());
    respuesta(tokio::task::spawn_blocking(move || github::guardar_token(&t)).await)
}

/// `DELETE /api/github/token`
pub async fn github_borrar_token() -> Response {
    respuesta(tokio::task::spawn_blocking(github::borrar_token).await)
}

/// `GET /api/github/buscar`
pub async fn github_buscar(Query(q): Consulta) -> Response {
    let pagina = o_responder!(cuerpo::entero_consulta(&q, "pagina", 1, 1, 50));
    let estrellas = o_responder!(cuerpo::entero_consulta(&q, "estrellas_min", 0, 0, i64::MAX));
    respuesta(
        tokio::task::spawn_blocking(move || {
            github::buscar(&q_texto(&q, "q"), &q_texto(&q, "lenguaje"), q.get("orden").map(String::as_str).unwrap_or("estrellas"), pagina, estrellas, &q_texto(&q, "tema"))
        })
        .await,
    )
}

/// `GET /api/github/repo?ref=&refrescar=`: la ficha con lo explicado, si está guardado y lo descargado
pub async fn github_repo(axum::extract::State(state): axum::extract::State<crate::state::AppState>, Query(q): Consulta) -> Response {
    let r = o_responder!(cuerpo::texto_consulta(&q, "ref"));
    let refrescar = o_responder!(cuerpo::booleano_consulta(&q, "refrescar")).unwrap_or(false);
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || {
            let mut info = github::abrir(&r, refrescar)?;
            info.poner("explicadas", github::explicadas(&info)?);
            info.poner("guardado", github::esta_guardado(info.valor("ref"))?);
            let local = github::local(&info.valor("ref").texto_py(), &espacio)?;
            info.poner("local", local.map(Valor::Mapa).unwrap_or(Valor::Nulo));
            Ok(info)
        })
        .await,
    )
}

/// `GET /api/github/archivo?ref=&ruta=`
pub async fn github_archivo(Query(q): Consulta) -> Response {
    let r = o_responder!(cuerpo::texto_consulta(&q, "ref"));
    let ruta = o_responder!(cuerpo::texto_consulta(&q, "ruta"));
    respuesta(tokio::task::spawn_blocking(move || github::leer_archivo(&r, &ruta)).await)
}

/// `POST /api/github/guardados` (`ref`, `nota`)
pub async fn github_guardar(b: Bytes) -> Response {
    let (r, nota) = o_responder!(peticion_github(&b));
    respuesta(tokio::task::spawn_blocking(move || github::guardar(&r, &nota.unwrap_or_default()).map(|l| Mapa::new().con("repos", Valor::Lista(l)))).await)
}

/// `DELETE /api/github/guardados?ref=`
pub async fn github_quitar(Query(q): Consulta) -> Response {
    let r = o_responder!(cuerpo::texto_consulta(&q, "ref"));
    respuesta(tokio::task::spawn_blocking(move || github::quitar(&r).map(|l| Mapa::new().con("repos", Valor::Lista(l)))).await)
}

/// `POST /api/github/descargar` (`ref`): el repositorio en github_repos/ (NDJSON con el progreso)
pub async fn github_descargar(axum::extract::State(state): axum::extract::State<crate::state::AppState>, b: Bytes) -> Response {
    use axum::response::IntoResponse;
    let (r, _) = o_responder!(peticion_github(&b));
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<axum::body::Bytes, std::io::Error>>(64);
    std::thread::spawn(move || {
        let linea = |v: Mapa| axum::body::Bytes::from(prig_plataforma::json::escribir_linea(&Valor::Mapa(v)) + "\n");
        let mut avisar = |ev: Mapa| tx.blocking_send(Ok(linea(ev))).is_ok();
        let fin = match github::descargar(&r, &espacio, &mut avisar) {
            Ok(res) => Mapa::new().con("tipo", "fin").con("resultado", res),
            Err(Fallo::Usuario(e)) => Mapa::new().con("tipo", "error").con("mensaje", e.0),
            Err(Fallo::Interno) => Mapa::new().con("tipo", "error").con("mensaje", "Error interno al descargar."),
        };
        let _ = tx.blocking_send(Ok(linea(fin)));
    });
    let flujo = futures_util::stream::unfold(rx, |mut rx| async move { rx.recv().await.map(|x| (x, rx)) });
    ([(axum::http::header::CONTENT_TYPE, "application/x-ndjson")], axum::body::Body::from_stream(flujo)).into_response()
}

/// `POST /api/github/exportar` (`ref`, `nota`: «md» o «pdf»)
pub async fn github_exportar(axum::extract::State(state): axum::extract::State<crate::state::AppState>, b: Bytes) -> Response {
    let (r, nota) = o_responder!(peticion_github(&b));
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let pdf = nota.filter(|n| !n.is_empty()).unwrap_or_else(|| "pdf".into()) == "pdf";
    respuesta(tokio::task::spawn_blocking(move || if pdf { github::exportar_pdf(&r, &espacio) } else { github::exportar_markdown(&r, &espacio) }).await)
}

/// `GET /api/github/exportado?ruta=&descargar=`
pub async fn github_exportado(axum::extract::State(state): axum::extract::State<crate::state::AppState>, Query(q): Consulta) -> Response {
    use axum::response::IntoResponse;
    let ruta = o_responder!(cuerpo::texto_consulta(&q, "ruta"));
    let descargar = o_responder!(cuerpo::booleano_consulta(&q, "descargar")).unwrap_or(false);
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || github::exportado(&ruta, &espacio).and_then(|p| std::fs::read(&p).ok().map(|b| (p, b)))).await;
    match r {
        Ok(Some((p, b))) => {
            let nombre = p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
            let tipo = if nombre.ends_with(".pdf") { "application/pdf" } else { "text/markdown; charset=utf-8" };
            let disp = format!("{}; filename=\"{nombre}\"", if descargar { "attachment" } else { "inline" });
            ([(axum::http::header::CONTENT_TYPE, tipo.to_string()), (axum::http::header::CONTENT_DISPOSITION, disp)], b).into_response()
        }
        Ok(None) => detalle(StatusCode::NOT_FOUND, "No existe."),
        Err(_) => error_500(),
    }
}

use prig_integrations::github_widget as widget;

/// `{config, extras}` opcionales de las peticiones del widget
fn config_y_extras(b: &Bytes) -> Result<(Option<Mapa>, Option<Mapa>), Response> {
    let m = cuerpo::modelo(b)?;
    let dict = |k: &str| -> Result<Option<Mapa>, cuerpo::Error> {
        match m.get(k) {
            None | Some(Valor::Nulo) => Ok(None),
            Some(Valor::Mapa(x)) => Ok(Some(x.clone())),
            Some(v) => Err(cuerpo::Error {
                tipo: "dict_type",
                loc: vec![Valor::Texto("body".into()), Valor::Texto(k.into())],
                msg: "Input should be a valid dictionary".into(),
                entrada: v.clone(),
                ctx: None,
            }),
        }
    };
    let (c, e) = (dict("config"), dict("extras"));
    let errores: Vec<cuerpo::Error> = [c.as_ref().err(), e.as_ref().err()].into_iter().flatten().map(|x| cuerpo::Error { tipo: x.tipo, loc: x.loc.clone(), msg: x.msg.clone(), entrada: x.entrada.clone(), ctx: None }).collect();
    if !errores.is_empty() {
        return Err(cuerpo::respuesta(errores));
    }
    Ok((c.ok().flatten(), e.ok().flatten()))
}

fn dir_desafios() -> std::path::PathBuf {
    crate::routes::desafios::carpeta_base().join("desafios")
}

/// `GET /api/github/widget/config`
pub async fn widget_config() -> Response {
    let r = tokio::task::spawn_blocking(|| {
        let t = widget::token();
        let usuario = t.as_deref().and_then(widget::usuario).map(|d| {
            Valor::Mapa(
                Mapa::new()
                    .con("login", d.get("login").cloned().unwrap_or(Valor::Nulo))
                    .con("name", d.get("name").cloned().unwrap_or(Valor::Nulo))
                    .con("avatar_url", d.get("avatar_url").cloned().unwrap_or(Valor::Nulo))
                    .con("html_url", d.get("html_url").cloned().unwrap_or(Valor::Nulo)),
            )
        });
        Mapa::new().con("config", widget::leer_config()).con("tiene_token", t.is_some()).con("usuario", usuario.unwrap_or(Valor::Nulo)).con("temas", widget::temas())
    })
    .await;
    match r {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

/// `POST /api/github/widget/config` (`config`)
pub async fn widget_guardar(b: Bytes) -> Response {
    let m = o_responder!(cuerpo::modelo(&b));
    let cfg = match m.get("config") {
        Some(Valor::Mapa(c)) => c.clone(),
        None => return cuerpo::respuesta(vec![cuerpo::Error { tipo: "missing", loc: vec![Valor::Texto("body".into()), Valor::Texto("config".into())], msg: "Field required".into(), entrada: Valor::Mapa(m.clone()), ctx: None }]),
        Some(v) => return cuerpo::respuesta(vec![cuerpo::Error { tipo: "dict_type", loc: vec![Valor::Texto("body".into()), Valor::Texto("config".into())], msg: "Input should be a valid dictionary".into(), entrada: v.clone(), ctx: None }]),
    };
    match tokio::task::spawn_blocking(move || widget::guardar_config(&cfg)).await {
        Ok(c) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("ok", true).con("config", c))),
        Err(_) => error_500(),
    }
}

/// `POST /api/github/widget/preview` (`config`, `extras`): la tarjeta, las cifras y el Markdown para el README
pub async fn widget_preview(b: Bytes) -> Response {
    let (cfg_extra, extras) = o_responder!(config_y_extras(&b));
    let r = tokio::task::spawn_blocking(move || {
        let mut cfg = widget::leer_config();
        for (k, v) in cfg_extra.iter().flat_map(|c| c.iter()) {
            cfg.poner(k.clone(), v.clone());
        }
        let stats = widget::estadisticas(&dir_desafios(), extras.as_ref());
        let svg = widget::svg(&stats, &cfg);
        let login = widget::token().as_deref().and_then(widget::usuario).and_then(|u| u.get("login").filter(|v| v.verdad()).map(|v| v.texto_py())).unwrap_or_else(|| "username".into());
        let md = format!(
            "<!-- PRIG-STATS:START -->\n[![Prig IDE Stats](https://raw.githubusercontent.com/{login}/{login}/main/prig-stats.svg)](https://github.com/{login})\n<!-- PRIG-STATS:END -->"
        );
        Mapa::new().con("svg", svg).con("stats", stats).con("config", cfg).con("login", login).con("markdown", md)
    })
    .await;
    match r {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

/// `POST /api/github/widget/publicar` (`config`, `extras`): sube la tarjeta y actualiza el README del perfil
pub async fn widget_publicar(b: Bytes) -> Response {
    let (cfg_extra, extras) = o_responder!(config_y_extras(&b));
    let Some(t) = tokio::task::spawn_blocking(widget::token).await.ok().flatten() else {
        return detalle(StatusCode::BAD_REQUEST, "No hay token de GitHub configurado. Conéctalo desde la barra lateral o Ajustes de GitHub.");
    };
    respuesta(
        tokio::task::spawn_blocking(move || {
            let mut cfg = widget::leer_config();
            if let Some(c) = &cfg_extra {
                for (k, v) in c.iter() {
                    cfg.poner(k.clone(), v.clone());
                }
                widget::guardar_config(&cfg);
            }
            let stats = widget::estadisticas(&dir_desafios(), extras.as_ref());
            widget::publicar(&t, &stats, &cfg)
        })
        .await,
    )
}

// ---------------------------------------------------------------------------------------------- YouTube

use prig_integrations::youtube;

/// `GET /api/youtube/palabras_registradas`
pub async fn youtube_palabras() -> Response {
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("status", "ok").con("palabras", Valor::Lista(youtube::palabras_registradas()))))
}

/// `GET /api/youtube/sugerencias?q=&limite=8`
pub async fn youtube_sugerencias(Query(q): Consulta) -> Response {
    let texto = o_responder!(cuerpo::texto_consulta(&q, "q"));
    let limite = o_responder!(cuerpo::entero_consulta(&q, "limite", 8, i64::MIN, i64::MAX));
    let t = prig_plataforma::py::strip(&texto).to_string();
    if t.is_empty() {
        return json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("query", "").con("sugerencias", Valor::Lista(vec![]))));
    }
    let limite = if limite == 0 { 8 } else { limite };
    let tt = t.clone();
    match tokio::task::spawn_blocking(move || youtube::sugerencias(&tt, limite)).await {
        Ok(l) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("query", t).con("sugerencias", Valor::Lista(l)))),
        Err(_) => error_500(),
    }
}

static CACHE_YOUTUBE_CARGADA: std::sync::Once = std::sync::Once::new();

/// `GET /api/youtube/buscar`: cursos y listas, con el ranking didáctico
pub async fn youtube_buscar(axum::extract::State(state): axum::extract::State<crate::state::AppState>, Query(q): Consulta) -> Response {
    let texto = o_responder!(cuerpo::texto_consulta(&q, "q"));
    let max = o_responder!(cuerpo::entero_consulta(&q, "max_resultados", 16, i64::MIN, i64::MAX));
    let educativo = o_responder!(cuerpo::booleano_consulta(&q, "filtro_educativo")).unwrap_or(true);
    let forzar = o_responder!(cuerpo::booleano_consulta(&q, "forzar")).unwrap_or(false);
    if prig_plataforma::py::strip(&texto).is_empty() {
        return detalle(StatusCode::BAD_REQUEST, "El parámetro de búsqueda 'q' no puede estar vacío.");
    }
    let o = |k: &str, d: &str| q.get(k).filter(|v| !v.is_empty()).cloned().unwrap_or_else(|| d.into());
    let b = youtube::Busqueda {
        q: texto,
        tipo: o("tipo", "todos"),
        max: if max == 0 { 16 } else { max },
        educativo,
        idioma: o("idioma", "todos"),
        duracion: o("duracion_filtro", "todas"),
        orden: o("orden", "educativo"),
        forzar,
    };
    let carpeta = state.base_dir.join("backend/data");
    match tokio::task::spawn_blocking(move || {
        CACHE_YOUTUBE_CARGADA.call_once(|| youtube::cargar_cache(&carpeta));
        youtube::buscar(&b, &carpeta)
    })
    .await
    {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

/// `POST /api/youtube/abrir_externo` (`url`): un enlace oficial de YouTube en el navegador del sistema
pub async fn youtube_abrir(b: Bytes) -> Response {
    let datos = match prig_plataforma::json::leer(&String::from_utf8_lossy(&b)) {
        Ok(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    };
    let url = match datos.get("url") {
        Some(v) if v.verdad() => v.texto_py(),
        _ => return detalle(StatusCode::BAD_REQUEST, "Falta el parámetro 'url'"),
    };
    let oficial = ["https://www.youtube.com/", "https://youtube.com/", "https://youtu.be/", "https://www.youtube-nocookie.com/"].iter().any(|p| url.starts_with(p));
    if !oficial {
        return detalle(StatusCode::BAD_REQUEST, "Solo se permite abrir enlaces oficiales de YouTube.");
    }
    let u = url.clone();
    let abierto = tokio::task::spawn_blocking(move || youtube::abrir_en_navegador(&u)).await.unwrap_or(false);
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("ok", true).con("abierto", abierto).con("url", url)))
}

/// `GET /api/youtube/transcripcion?video_id=&idioma=es&forzar=false`
pub async fn youtube_transcripcion(axum::extract::State(state): axum::extract::State<crate::state::AppState>, Query(q): Consulta) -> Response {
    let video = o_responder!(cuerpo::texto_consulta(&q, "video_id"));
    let forzar = o_responder!(cuerpo::booleano_consulta(&q, "forzar")).unwrap_or(false);
    if video.is_empty() {
        return detalle(StatusCode::BAD_REQUEST, "Falta el parámetro 'video_id'");
    }
    let idioma = q.get("idioma").cloned().unwrap_or_else(|| "es".into());
    let raiz = state.base_dir.clone();
    match tokio::task::spawn_blocking(move || youtube::transcripcion(&raiz, &video, &idioma, forzar)).await {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}
