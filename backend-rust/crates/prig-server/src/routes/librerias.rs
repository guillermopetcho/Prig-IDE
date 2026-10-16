//! El analista de librerías (`librerias_service.py`): dar de alta un repositorio, las citas técnicas de cada librería
//! (`~/.prig_books/librerias/<id>.json`), guardarlas, borrarlas, copiarlas al proyecto, pedirle al modelo una ficha de
//! una función y reunirlas para el chat. Los archivos son los mismos que escribía Python, byte a byte.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use axum::{
    body::Bytes,
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

/// Un fallo de la lógica: el mensaje (400) o un error de Python sin capturar (500)
enum Fallo {
    Mensaje(String),
    Interno,
}

fn responder(r: Result<Valor, Fallo>) -> Response {
    match r {
        Ok(v) => json_py(StatusCode::OK, &v),
        Err(Fallo::Mensaje(m)) => detalle(StatusCode::BAD_REQUEST, m),
        Err(Fallo::Interno) => error_500(),
    }
}

async fn en_hilo<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| error_500())
}

pub fn carpeta() -> PathBuf {
    crate::routes::biblioteca::libros_dir().join("librerias")
}

fn ruta_citas(lid: &str) -> PathBuf {
    carpeta().join(format!("{lid}.json"))
}

fn ahora() -> String {
    py::ahora_iso()
}

fn escribir(ruta: &Path, v: &Valor) -> Result<(), String> {
    std::fs::write(ruta, prig_plataforma::json::escribir(v, 2)).map_err(|e| py::error_os(&e, &ruta.to_string_lossy()))
}

/// `str.capitalize()`
fn capitalizar(t: &str) -> String {
    let mut c = t.chars();
    match c.next() {
        Some(p) => p.to_uppercase().chain(c.flat_map(char::to_lowercase)).collect(),
        None => String::new(),
    }
}

/// `LibreriasService.__init__`: la carpeta y las citas de muestra de NumPy y Matplotlib si aún no están
pub fn preparar() {
    let dir = carpeta();
    let _ = std::fs::create_dir_all(&dir);
    let cita = |id: &str, tema: &str, modulo: &str, funcion: &str, snippet: &str, explicacion: &str, params: &[&str], tags: &[&str]| {
        let l = |x: &[&str]| Valor::Lista(x.iter().map(|s| Valor::Texto(s.to_string())).collect());
        Valor::Mapa(
            Mapa::new()
                .con("id", id)
                .con("tema", tema)
                .con("modulo", modulo)
                .con("funcion", funcion)
                .con("snippet", snippet)
                .con("explicacion", explicacion)
                .con("parametros_clave", l(params))
                .con("tags", l(tags))
                .con("fecha", ahora()),
        )
    };
    let muestra = |lib: &str, nombre: &str, repo: &str, citas: Vec<Valor>| {
        Valor::Mapa(
            Mapa::new()
                .con("libreria", lib)
                .con("nombre", nombre)
                .con("repo", repo)
                .con("total_citas", citas.len() as i64)
                .con("fecha_actualizacion", ahora())
                .con("citas", Valor::Lista(citas)),
        )
    };
    let np = dir.join("numpy.json");
    if !np.exists() {
        let v = muestra(
            "numpy",
            "NumPy",
            "numpy/numpy",
            vec![
                cita(
                    "lib_np_1",
                    "Broadcasting y Reshape eficiente",
                    "numpy",
                    "np.broadcast_to / reshape",
                    "import numpy as np\nx = np.array([1, 2, 3])\n# Expansión de dimensiones sin duplicar memoria\ny = np.broadcast_to(x, (3, 3))\nprint(y)",
                    "El broadcasting de NumPy permite realizar operaciones vectoriales entre arrays de diferentes dimensiones sin copiar datos en memoria física.",
                    &["shape", "subok"],
                    &["broadcasting", "memoria", "rendimiento"],
                ),
                cita(
                    "lib_np_2",
                    "Operaciones Matriciales y Descomposición SVD",
                    "numpy.linalg",
                    "np.linalg.svd",
                    "U, S, Vt = np.linalg.svd(matriz_datos)\n# U: vectores singulares izquierdos, S: valores singulares",
                    "Calcula la descomposición en valores singulares (SVD) de una matriz, base de PCA y reducción de dimensionalidad.",
                    &["a", "full_matrices", "compute_uv"],
                    &["svd", "algebra-lineal", "pca"],
                ),
            ],
        );
        let _ = escribir(&np, &v);
    }
    let plt = dir.join("matplotlib.json");
    if !plt.exists() {
        let v = muestra(
            "matplotlib",
            "Matplotlib",
            "matplotlib/matplotlib",
            vec![cita(
                "lib_plt_1",
                "Creación limpia de Subplots Orientados a Objetos",
                "matplotlib.pyplot",
                "plt.subplots",
                "import matplotlib.pyplot as plt\nfig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4), sharey=True)\nax1.plot(x, y1, color='#89b4fa', label='Train Loss')\nax1.set_title('Entrenamiento')\nax2.plot(x, y2, color='#a6e3a1', label='Val Loss')\nax2.set_title('Validación')\nplt.tight_layout()\nplt.show()",
                "La API orientada a objetos de Matplotlib (usando fig y ax) es más robusta y legible que el estilo procedimental simple.",
                &["nrows", "ncols", "figsize", "sharey"],
                &["subplots", "orientado-a-objetos", "layout"],
            )],
        );
        let _ = escribir(&plt, &v);
    }
}

fn lista(state: &AppState) -> Result<Vec<Valor>, Fallo> {
    crate::routes::biblioteca::librerias(state).map_err(|_| Fallo::Interno)
}

fn meta_de(state: &AppState, id: &str) -> Result<Option<Mapa>, Fallo> {
    Ok(lista(state)?.into_iter().find_map(|l| match l {
        Valor::Mapa(m) if m.get("id") == Some(&Valor::Texto(id.to_string())) => Some(m),
        _ => None,
    }))
}

/// `get_library_citations`: lo guardado o, si no hay (o no se puede leer), uno nuevo vacío que se escribe
fn citas(state: &AppState, lib_id: &str) -> Result<Valor, Fallo> {
    let lid = py::strip(&lib_id.to_lowercase()).to_string();
    let ruta = ruta_citas(&lid);
    if ruta.exists() {
        if let Ok(v) = std::fs::read_to_string(&ruta).map_err(|_| ()).and_then(|t| prig_plataforma::json::leer(&t).map_err(|_| ())) {
            return Ok(v);
        }
    }
    let meta = meta_de(state, &lid)?;
    let (nombre, repo) = match &meta {
        Some(m) => (m.get("nombre").cloned().unwrap_or_else(|| Valor::Texto(capitalizar(&lid))), m.get("repo").cloned().unwrap_or_else(|| Valor::Texto(String::new()))),
        None => (Valor::Texto(capitalizar(&lid)), Valor::Texto(lid.clone())),
    };
    let inicial = Valor::Mapa(
        Mapa::new()
            .con("libreria", lid.as_str())
            .con("nombre", nombre)
            .con("repo", repo)
            .con("archivo_json", format!("{lid}.json"))
            .con("total_citas", 0)
            .con("fecha_actualizacion", ahora())
            .con("citas", Valor::Lista(vec![])),
    );
    let _ = escribir(&ruta, &inicial);
    Ok(inicial)
}

/// `current.get("libreria", lib_id.lower())` (lo leído tiene que ser un dict: si no, Python falla)
fn actual(state: &AppState, lib_id: &str) -> Result<(Mapa, String), Fallo> {
    let Valor::Mapa(m) = citas(state, lib_id)? else { return Err(Fallo::Interno) };
    let lid = m.get("libreria").map(Valor::texto_py).unwrap_or_else(|| lib_id.to_lowercase());
    Ok((m, lid))
}

/// `(x or defecto).strip()`: un valor que no es texto revienta en Python
fn limpio(v: Option<&Valor>, defecto: &str) -> Result<String, Fallo> {
    match v.filter(|v| v.verdad()) {
        None => Ok(py::strip(defecto).to_string()),
        Some(Valor::Texto(t)) => Ok(py::strip(t).to_string()),
        Some(_) => Err(Fallo::Interno),
    }
}

fn lista_o_comas(v: Option<&Valor>) -> Valor {
    match v {
        Some(Valor::Lista(l)) => Valor::Lista(l.clone()),
        otro => {
            let t = otro.filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default();
            Valor::Lista(t.split(',').map(py::strip).filter(|p| !p.is_empty()).map(|p| Valor::Texto(p.to_string())).collect())
        }
    }
}

fn id_nuevo() -> String {
    let s = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    format!("lib_cita_{s}_{}", &uuid::Uuid::new_v4().simple().to_string()[..4])
}

fn guardar_cita(state: &AppState, lib_id: &str, datos: &Mapa) -> Result<Valor, Fallo> {
    let (mut actual, lid) = actual(state, lib_id)?;
    let ruta = ruta_citas(&lid);
    let cid = datos.get("id").filter(|v| v.verdad()).cloned().unwrap_or_else(|| Valor::Texto(id_nuevo()));
    let funcion = datos.get("funcion").filter(|v| v.verdad()).or_else(|| datos.get("funcion_o_clase"));
    let snippet = datos.get("snippet").filter(|v| v.verdad()).or_else(|| datos.get("codigo_ejemplo"));
    let entrada = Mapa::new()
        .con("id", cid.clone())
        .con("tema", limpio(datos.get("tema"), "Uso de API")?)
        .con("modulo", limpio(datos.get("modulo"), &lid)?)
        .con("funcion", limpio(funcion, "")?)
        .con("snippet", limpio(snippet, "")?)
        .con("explicacion", limpio(datos.get("explicacion"), "")?)
        .con("parametros_clave", lista_o_comas(datos.get("parametros_clave")))
        .con("tags", lista_o_comas(datos.get("tags")))
        .con("fecha", ahora());
    let mut existentes = match actual.get("citas") {
        None => Vec::new(),
        Some(Valor::Lista(l)) => l.clone(),
        Some(_) => return Err(Fallo::Interno),
    };
    let mismo = |c: &Valor| matches!(c, Valor::Mapa(c) if c.get("id") == Some(&cid));
    match existentes.iter().position(mismo) {
        Some(i) => existentes[i] = Valor::Mapa(entrada.clone()),
        None => existentes.push(Valor::Mapa(entrada.clone())),
    }
    let n = existentes.len();
    actual.poner("citas", Valor::Lista(existentes));
    actual.poner("total_citas", n as i64);
    actual.poner("fecha_actualizacion", ahora());
    match escribir(&ruta, &Valor::Mapa(actual.clone())) {
        Ok(()) => Ok(Valor::Mapa(
            Mapa::new()
                .con("success", true)
                .con("ok", true)
                .con("cita", entrada)
                .con("library_citations", actual)
                .con("archivo_json", format!("{lid}.json")),
        )),
        Err(e) => Err(Fallo::Mensaje(format!("Error guardando {lid}.json: {e}"))),
    }
}

fn borrar_cita(state: &AppState, lib_id: &str, cita_id: &str) -> Result<Valor, Fallo> {
    let (mut actual, lid) = actual(state, lib_id)?;
    let existentes = match actual.get("citas") {
        None => Vec::new(),
        Some(Valor::Lista(l)) => l.clone(),
        Some(_) => return Err(Fallo::Interno),
    };
    let antes = existentes.len();
    let quedan: Vec<Valor> = existentes.into_iter().filter(|c| !matches!(c, Valor::Mapa(c) if c.get("id") == Some(&Valor::Texto(cita_id.to_string())))).collect();
    if quedan.len() == antes {
        return Err(Fallo::Mensaje(format!("Cita no encontrada: {cita_id}")));
    }
    let n = quedan.len();
    actual.poner("citas", Valor::Lista(quedan));
    actual.poner("total_citas", n as i64);
    actual.poner("fecha_actualizacion", ahora());
    match escribir(&ruta_citas(&lid), &Valor::Mapa(actual)) {
        Ok(()) => Ok(Valor::Mapa(Mapa::new().con("success", true).con("ok", true).con("deleted_id", cita_id).con("total_citas", n as i64))),
        Err(e) => Err(Fallo::Mensaje(format!("Error guardando cambios en {lid}.json: {e}"))),
    }
}

/// `shutil.copy2`: el contenido, los permisos y las fechas
pub fn copiar2(origen: &Path, destino: &Path) -> std::io::Result<()> {
    std::fs::copy(origen, destino)?;
    let m = std::fs::metadata(origen)?;
    let f = std::fs::File::options().write(true).open(destino)?;
    f.set_times(std::fs::FileTimes::new().set_accessed(m.accessed()?).set_modified(m.modified()?))
}

fn exportar(state: &AppState, lib_id: &str, ws: &str) -> Result<Valor, Fallo> {
    let (actual, lid) = actual(state, lib_id)?;
    let origen = ruta_citas(&lid);
    if !origen.exists() {
        return Err(Fallo::Mensaje(format!("No hay archivo de citas para la librería {lib_id}")));
    }
    let dir = py::abspath(ws);
    py::makedirs(&dir).map_err(|_| Fallo::Interno)?;
    let destino = py::join(&dir, &format!("{lid}.json"));
    match copiar2(&origen, Path::new(&destino)) {
        Ok(()) => Ok(Valor::Mapa(
            Mapa::new()
                .con("success", true)
                .con("ok", true)
                .con("exported_to", destino.as_str())
                .con("filename", format!("{lid}.json"))
                .con("total_citas", actual.get("total_citas").cloned().unwrap_or(Valor::Entero(0))),
        )),
        Err(e) => Err(Fallo::Mensaje(format!("Error exportando al proyecto: {}", py::error_os(&e, &destino)))),
    }
}

fn agregar(repo: &str, nombre: Option<String>, desc: Option<String>) -> Result<Valor, Fallo> {
    let limpio = py::strip(repo).replace("https://github.com/", "");
    let limpio = limpio.trim_matches('/').to_string();
    let Some((_, nombre_repo)) = limpio.split_once('/') else {
        return Err(Fallo::Mensaje("Formato de repositorio inválido. Usa 'usuario/repo' (ej: huggingface/datasets).".into()));
    };
    let lid = nombre_repo.to_lowercase().replace('.', "-");
    let archivo = carpeta().join("lista_librerias.json");
    let propias: Vec<Valor> = match std::fs::read_to_string(&archivo).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        Some(Valor::Lista(l)) => l,
        Some(v) if !v.verdad() => Vec::new(),
        Some(_) if archivo.exists() => return Err(Fallo::Interno),
        _ => Vec::new(),
    };
    let entrada = Mapa::new()
        .con("id", lid.as_str())
        .con("nombre", nombre.filter(|n| !n.is_empty()).unwrap_or_else(|| capitalizar(nombre_repo)))
        .con("repo", limpio.as_str())
        .con("doc_url", format!("https://github.com/{limpio}"))
        .con("descripcion", desc.filter(|d| !d.is_empty()).unwrap_or_else(|| format!("Repositorio y librería de GitHub {limpio}")))
        .con("modulos_clave", Valor::Lista(vec![Valor::Texto(nombre_repo.into())]))
        .con("color", "#cba6f7")
        .con("tags", Valor::Lista(vec![Valor::Texto("github".into()), Valor::Texto("custom-repo".into()), Valor::Texto(nombre_repo.into())]));
    let mut nuevas = Vec::new();
    for c in propias {
        match &c {
            Valor::Mapa(m) if m.get("id") == Some(&Valor::Texto(lid.clone())) => {}
            Valor::Mapa(_) => nuevas.push(c),
            _ => return Err(Fallo::Interno),
        }
    }
    nuevas.push(Valor::Mapa(entrada.clone()));
    match escribir(&archivo, &Valor::Lista(nuevas)) {
        Ok(()) => Ok(Valor::Mapa(Mapa::new().con("success", true).con("ok", true).con("library", entrada))),
        Err(e) => Err(Fallo::Mensaje(format!("Error guardando librería: {e}"))),
    }
}

/// `get_all_library_citations_for_ai`: las citas de todas las librerías (con `query`, las que encajan, por
/// coincidencias), hasta 10
fn todas_las_citas(query: Option<&str>) -> Vec<Valor> {
    let dir = carpeta();
    let Ok(entradas) = std::fs::read_dir(&dir) else { return Vec::new() };
    let terminos: Vec<String> = query.unwrap_or("").split_whitespace().map(str::to_lowercase).filter(|t| t.chars().count() > 2).collect();
    let mut salida: Vec<(i64, Mapa)> = Vec::new();
    for e in entradas.flatten() {
        let f = e.file_name().to_string_lossy().to_string();
        if !f.ends_with(".json") || f == "lista_librerias.json" {
            continue;
        }
        let Some(Valor::Mapa(datos)) = std::fs::read_to_string(dir.join(&f)).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) else { continue };
        let lnombre = datos.get("nombre").filter(|v| v.verdad()).or_else(|| datos.get("libreria").filter(|v| v.verdad())).cloned().unwrap_or_else(|| Valor::Texto(f.clone()));
        let citas = match datos.get("citas") {
            None => continue,
            Some(Valor::Lista(l)) => l.clone(),
            Some(_) => continue,
        };
        // un error de Python a mitad deja lo ya reunido y salta al archivo siguiente
        for c in citas {
            let Valor::Mapa(c) = c else { break };
            let g = |k: &str, d: Valor| c.get(k).cloned().unwrap_or(d);
            let vacio = || Valor::Texto(String::new());
            let item = Mapa::new()
                .con("tipo", "libreria")
                .con("libreria", lnombre.clone())
                .con("modulo", g("modulo", vacio()))
                .con("funcion", g("funcion", vacio()))
                .con("tema", g("tema", vacio()))
                .con("snippet", g("snippet", vacio()))
                .con("explicacion", g("explicacion", vacio()))
                .con("parametros", g("parametros_clave", Valor::Lista(vec![])))
                .con("tags", g("tags", Valor::Lista(vec![])))
                .con("id", g("id", vacio()));
            if terminos.is_empty() {
                salida.push((0, item));
                continue;
            }
            // `term in item["funcion"].lower() or ... or any(term in str(tg).lower() for tg in item["tags"])`, campo a
            // campo como Python: el primero que no es texto (o unos tags que no se pueden recorrer) corta el archivo
            let mut n = 0i64;
            let mut roto = false;
            'terminos: for t in &terminos {
                for k in ["funcion", "tema", "explicacion", "libreria"] {
                    match item.get(k) {
                        Some(Valor::Texto(x)) if x.to_lowercase().contains(t.as_str()) => {
                            n += 1;
                            continue 'terminos;
                        }
                        Some(Valor::Texto(_)) => {}
                        _ => {
                            roto = true;
                            break 'terminos;
                        }
                    }
                }
                let partes: Vec<String> = match item.get("tags") {
                    Some(Valor::Lista(l)) => l.iter().map(|x| x.texto_py().to_lowercase()).collect(),
                    Some(Valor::Texto(x)) => x.chars().map(|c| c.to_lowercase().collect()).collect(),
                    Some(Valor::Mapa(m)) => m.claves().map(|k| k.to_lowercase()).collect(),
                    _ => {
                        roto = true;
                        break 'terminos;
                    }
                };
                if partes.iter().any(|x| x.contains(t.as_str())) {
                    n += 1;
                }
            }
            if roto {
                break;
            }
            if n > 0 {
                salida.push((n, item.con("_score", n)));
            }
        }
    }
    if !terminos.is_empty() {
        salida.sort_by(|a, b| b.0.cmp(&a.0));
    }
    salida.into_iter().take(10).map(|(_, m)| Valor::Mapa(m)).collect()
}

// =========================================================================== rutas

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const DICT: Tipo = Tipo::Dict(&Tipo::Cualquiera);

fn pedido(b: &Bytes, campos: &[(&str, &Tipo, bool)]) -> Result<Mapa, Response> {
    cuerpo::modelo(b).and_then(|m| cuerpo::tipados(&m, campos))
}

fn opcional(c: &Mapa, k: &str) -> Option<String> {
    c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py)
}

/// `POST /api/librerias/add` (`repo`, `name`, `desc`)
pub async fn agregar_ruta(b: Bytes) -> Response {
    let c = match pedido(&b, &[("repo", &Tipo::Texto, true), ("name", &TEXTO_OPC, false), ("desc", &TEXTO_OPC, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        preparar();
        responder(agregar(&c.valor("repo").texto_py(), opcional(&c, "name"), opcional(&c, "desc")))
    })
    .await
}

/// `GET /api/librerias/citations?id=`
pub async fn citas_ruta(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let id = match cuerpo::texto_consulta(&q, "id") {
        Ok(i) => i,
        Err(r) => return r,
    };
    en_hilo(move || {
        preparar();
        match citas(&state, &id) {
            Ok(v) => json_py(StatusCode::OK, &v),
            Err(_) => error_500(),
        }
    })
    .await
}

/// `POST /api/librerias/citations/save` (`lib_id`, `citation`)
pub async fn guardar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("lib_id", &Tipo::Texto, true), ("citation", &DICT, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        preparar();
        responder(guardar_cita(&state, &c.valor("lib_id").texto_py(), &c.mapa("citation").cloned().unwrap_or_default()))
    })
    .await
}

/// `POST /api/librerias/citations/delete` (`lib_id`, `citation_id`)
pub async fn borrar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("lib_id", &Tipo::Texto, true), ("citation_id", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        preparar();
        responder(borrar_cita(&state, &c.valor("lib_id").texto_py(), &c.valor("citation_id").texto_py()))
    })
    .await
}

/// `POST /api/librerias/citations/export` (`lib_id`, `workspace_path`): una copia del JSON en el proyecto
pub async fn exportar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("lib_id", &Tipo::Texto, true), ("workspace_path", &TEXTO_OPC, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    en_hilo(move || {
        preparar();
        let ws = c.get("workspace_path").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| espacio.to_string_lossy().to_string());
        responder(exportar(&state, &c.valor("lib_id").texto_py(), &ws))
    })
    .await
}

/// `POST /api/librerias/analyze` (`lib_id`, `topic`, `model`): la ficha de una función, en JSON, por el modelo
pub async fn analizar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("lib_id", &Tipo::Texto, true), ("topic", &Tipo::Texto, true), ("model", &TEXTO_OPC, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        preparar();
        let lib_id = c.valor("lib_id").texto_py();
        let tema = c.valor("topic").texto_py();
        let modelo = c.get("model").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| "qwen2.5-coder:7b".into());
        let meta = match meta_de(&state, &lib_id.to_lowercase()) {
            Ok(m) => m,
            Err(_) => return error_500(),
        };
        let nombre = meta.and_then(|m| m.get("nombre").map(Valor::texto_py)).unwrap_or_else(|| lib_id.clone());
        let prompt = format!(
            "Analiza técnicamente la función, clase o módulo '{tema}' de la librería '{nombre}' (Python).\nProporciona la sintaxis moderna oficial, explicación técnica concisa, parámetros cruciales, y un snippet de código Python limpio, probado y ejecutable.\n\nDEVUELVE EXCLUSIVAMENTE UN OBJETO JSON VÁLIDO con esta estructura exacta:\n{{\n  \"tema\": \"Nombre descriptivo del caso de uso\",\n  \"modulo\": \"{lib_id}\",\n  \"funcion\": \"{tema}\",\n  \"snippet\": \"# Código Python ejecutable de ejemplo\\nimport ...\",\n  \"explicacion\": \"Explicación técnica en 2-3 frases de qué hace, por qué se usa y qué devuelve.\",\n  \"parametros_clave\": [\"param1\", \"param2\", \"param3\"],\n  \"tags\": [\"tag1\", \"tag2\", \"tag3\"]\n}}\n"
        );
        let sistema = "Eres un Desarrollador Senior y Analista de APIs de Python. Devuelve ÚNICAMENTE un objeto JSON válido sin texto ni explicaciones adicionales.";
        let p = prig_ia::generar::PedidoGenerar { prompt, modelo, sistema: sistema.into(), gobernador: true, ..Default::default() };
        let mut acumulado = String::new();
        let cancelar = prig_ia::vivo::Cancelar::default();
        prig_ia::generar::generar(&raiz, &p, &cancelar, &mut |e: Mapa| {
            if e.get("t") == Some(&Valor::Texto("texto".into())) {
                acumulado.push_str(&e.valor("v").texto_py());
            }
        });
        let mut limpio = py::strip(&acumulado).to_string();
        if limpio.contains("```") {
            if let (Some(s), Some(e)) = (limpio.find('{'), limpio.rfind('}')) {
                limpio = if e >= s { limpio[s..=e].to_string() } else { String::new() };
            }
        }
        responder(match prig_plataforma::json::leer(&limpio) {
            Ok(d) => Ok(Valor::Mapa(Mapa::new().con("success", true).con("analysis", d))),
            Err(e) => Err(Fallo::Mensaje(format!("Error analizando {tema} con IA: {e}"))),
        })
    })
    .await
}

/// `GET /api/librerias/all-citations?query=`
pub async fn todas_ruta(Query(q): Query<HashMap<String, String>>) -> Response {
    en_hilo(move || {
        preparar();
        json_py(StatusCode::OK, &Valor::Lista(todas_las_citas(q.get("query").map(String::as_str))))
    })
    .await
}
