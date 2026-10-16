//! Modelos de Ollama: todo lo configurable (solo lo verificado). El catálogo de opciones, la lista, la ficha, las capas
//! de configuración (global, modelo, uso, modelo y uso) y sus plantillas, probar una petición, crear variantes, copiar,
//! borrar, importar un GGUF, actualizaciones, cargar y soltar, descargas a medias y el registro del servidor
//! (`prig_modelos::{gestion, opciones}`). Los embeddings siguen en Python con el índice semántico.

#![allow(clippy::result_large_err)]

use std::collections::HashMap;
use std::path::Path;

use axum::{
    body::{Body, Bytes},
    extract::{Query, State},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
};
use prig_ia::{generar, gestor, motor, ollama};
use prig_modelos::gestion::{self, ErrorG, Gestor};
use prig_modelos::opciones;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py::ErrorPy;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn ok(v: Valor) -> Response {
    json_py(StatusCode::OK, &v)
}

/// `_modelos`: ErrorGestion y ErrorConfig → 400; Ollama que no responde → 503; lo demás, 500
fn de_error(e: ErrorG) -> Response {
    match e {
        ErrorG::Gestion(t) | ErrorG::Py(ErrorPy::Propia(t)) => detalle(StatusCode::BAD_REQUEST, t),
        ErrorG::Red(r) => detalle(StatusCode::SERVICE_UNAVAILABLE, format!("Ollama no responde: {}", r.texto())),
        ErrorG::Py(_) => error_500(),
    }
}

fn de_config(e: ErrorPy) -> Response {
    de_error(ErrorG::Py(e))
}

fn gestor_ollama() -> Gestor {
    Gestor { base: ollama::base_url() }
}

async fn bloque<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| error_500())
}

fn opcional_texto(c: &Mapa, k: &str) -> Option<String> {
    c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py)
}

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const BOOL_OPC: Tipo = Tipo::Opcional(&Tipo::Booleano);
const DICT: Tipo = Tipo::Dict(&Tipo::Cualquiera);

/// `GET /api/modelos/catalogo`: las opciones de Ollama con lo que se verificó de cada una
pub async fn catalogo(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || {
        let n = gestor::gestor(&raiz).radiografia(false).ok().and_then(|r| r.lista("gpus").map(<[Valor]>::len)).unwrap_or(0);
        ok(Valor::Mapa(opciones::catalogo(n.max(1) as i64)))
    })
    .await
}

/// `GET /api/modelos`: los de Ollama, el disco y los «propios» (el motor MoE, que sirve Prig sin Ollama)
pub async fn lista(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || {
        let g = gestor_ollama();
        let modelos = match g.instalados() {
            Ok(m) => m,
            Err(e) => return de_error(e),
        };
        let disco = match g.uso_disco() {
            Ok(d) => d,
            Err(e) => return de_error(e),
        };
        let caps: Vec<Valor> = motor::CAPACIDADES.iter().map(|c| Valor::from(*c)).collect();
        let propios = ollama::modelos_propios(&raiz)
            .into_iter()
            .filter_map(|m| match m {
                Valor::Mapa(m) => Some(Valor::Mapa(
                    Mapa::new()
                        .con("nombre", m.get("name").cloned().unwrap_or(Valor::Nulo))
                        .con("capacidades", Valor::Lista(caps.clone()))
                        .con("motor", m.get("motor").cloned().unwrap_or(Valor::Nulo)),
                )),
                _ => None,
            })
            .collect();
        ok(Valor::Mapa(Mapa::new().con("modelos", Valor::Lista(modelos)).con("disco", disco).con("propios", Valor::Lista(propios))))
    })
    .await
}

fn consulta_obligatoria(q: &HashMap<String, String>, campo: &str) -> Result<String, Response> {
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

/// `GET /api/modelos/ficha?modelo=`
pub async fn ficha(Query(q): Query<HashMap<String, String>>) -> Response {
    let modelo = match consulta_obligatoria(&q, "modelo") {
        Ok(m) => m,
        Err(r) => return r,
    };
    bloque(move || match gestor_ollama().ficha(&modelo) {
        Ok(f) => ok(Valor::Mapa(f)),
        Err(e) => de_error(e),
    })
    .await
}

/// `GET /api/modelos/config?modelo=&uso=`: las capas, lo efectivo, lo que trae el modelo y lo que sigue mandando la
/// configuración global de IA
pub async fn config(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let modelo = q.get("modelo").cloned().filter(|m| !m.is_empty());
    let uso = q.get("uso").cloned().filter(|u| !u.is_empty());
    let raiz = state.base_dir.clone();
    bloque(move || {
        let cfg = opciones::config();
        let mut capas = Mapa::new();
        match cfg.capa("global", None, None) {
            Ok(c) => capas.poner("global", c),
            Err(e) => return de_config(e),
        }
        if let Some(m) = &modelo {
            match cfg.capa("modelo", Some(m), None) {
                Ok(c) => capas.poner("modelo", c),
                Err(e) => return de_config(e),
            }
        }
        if let Some(u) = &uso {
            match cfg.capa("uso", None, Some(u)) {
                Ok(c) => capas.poner("uso", c),
                Err(e) => return de_config(e),
            }
            if let Some(m) = &modelo {
                match cfg.capa("modelo_uso", Some(m), Some(u)) {
                    Ok(c) => capas.poner("modelo_uso", c),
                    Err(e) => return de_config(e),
                }
            }
        }
        let del_modelo = modelo
            .as_ref()
            .and_then(|m| gestor_ollama().ficha(m).ok())
            .and_then(|f| f.get("parametros").cloned())
            .unwrap_or_else(|| Valor::Mapa(Mapa::new()));
        // Lo que la configuración global de IA sigue enviando (contexto, tope, hilos…)
        let mut globales = generar::opciones(None, "", None, &raiz);
        for k in cfg.resolver(None, None).mapa("opciones").map(|o| o.claves().cloned().collect::<Vec<_>>()).unwrap_or_default() {
            globales.quitar(&k);
        }
        ok(Valor::Mapa(
            Mapa::new()
                .con("capas", capas)
                .con("efectivo", cfg.resolver(modelo.as_deref(), uso.as_deref()))
                .con("del_modelo", del_modelo)
                .con("configuracion_ia", globales),
        ))
    })
    .await
}

/// `POST /api/modelos/config` (`capa`, `modelo`, `uso`, `valores`, `reemplazar`)
pub async fn config_fijar(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(
        &m,
        &[("capa", &Tipo::Texto, true), ("modelo", &TEXTO_OPC, false), ("uso", &TEXTO_OPC, false), ("valores", &DICT, false), ("reemplazar", &Tipo::Booleano, false)],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    bloque(move || {
        let valores = c.mapa("valores").cloned().unwrap_or_default();
        let (modelo, uso) = (opcional_texto(&c, "modelo"), opcional_texto(&c, "uso"));
        match opciones::config().fijar(&c.valor("capa").texto_py(), &valores, modelo.as_deref(), uso.as_deref(), c.verdad("reemplazar")) {
            Ok(r) => ok(Valor::Mapa(Mapa::new().con("capa", r))),
            Err(e) => de_config(e),
        }
    })
    .await
}

const MUESTREO: [&str; 9] =
    ["temperature", "top_k", "top_p", "min_p", "seed", "repeat_penalty", "repeat_last_n", "presence_penalty", "frequency_penalty"];

/// `POST /api/modelos/plantilla` (`capa`, `plantilla`, `modelo`, `uso`): cambia el muestreo de la capa por el de la
/// plantilla, sin tocar lo demás
pub async fn plantilla(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(
        &m,
        &[("capa", &Tipo::Texto, true), ("plantilla", &Tipo::Texto, true), ("modelo", &TEXTO_OPC, false), ("uso", &TEXTO_OPC, false)],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    bloque(move || {
        let nombre = c.valor("plantilla").texto_py();
        let Some(p) = opciones::catalogo_base().mapa("PLANTILLAS").and_then(|ps| ps.mapa(&nombre)).filter(|p| !p.is_empty()).cloned() else {
            return detalle(StatusCode::BAD_REQUEST, "Plantilla desconocida");
        };
        let cfg = opciones::config();
        let (capa, modelo, uso) = (c.valor("capa").texto_py(), opcional_texto(&c, "modelo"), opcional_texto(&c, "uso"));
        let actual = match cfg.capa(&capa, modelo.as_deref(), uso.as_deref()) {
            Ok(a) => a,
            Err(e) => return de_config(e),
        };
        let mut nuevo = Mapa::new();
        for (k, v) in actual.iter().filter(|(k, _)| !MUESTREO.contains(&k.as_str())) {
            nuevo.poner(k.clone(), v.clone());
        }
        for (k, v) in p.mapa("valores").cloned().unwrap_or_default().iter() {
            nuevo.poner(k.clone(), v.clone());
        }
        match cfg.fijar(&capa, &nuevo, modelo.as_deref(), uso.as_deref(), true) {
            Ok(r) => ok(Valor::Mapa(Mapa::new().con("capa", r))),
            Err(e) => de_config(e),
        }
    })
    .await
}

/// `POST /api/modelos/probar`: una petición de prueba con las opciones de las capas y lo que se pida
pub async fn probar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(
        &m,
        &[
            ("modelo", &Tipo::Texto, true),
            ("prompt", &Tipo::Texto, false),
            ("uso", &TEXTO_OPC, false),
            ("system", &TEXTO_OPC, false),
            ("opciones", &DICT, false),
            ("think", &BOOL_OPC, false),
            ("format", &Tipo::Cualquiera, false),
            ("logprobs", &Tipo::Entero, false),
            ("raw", &Tipo::Booleano, false),
            ("template", &TEXTO_OPC, false),
            ("suffix", &TEXTO_OPC, false),
        ],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let modelo = c.valor("modelo").texto_py();
        let uso = opcional_texto(&c, "uso");
        let valores = match opciones::validar(&Valor::Mapa(c.mapa("opciones").cloned().unwrap_or_default())) {
            Ok(v) => v,
            Err(e) => return de_config(e),
        };
        let (op_motor, campos) = opciones::separar(&valores);
        let mut payload = Mapa::new()
            .con("model", modelo.as_str())
            .con("prompt", c.get("prompt").map(Valor::texto_py).unwrap_or_default())
            .con("options", generar::opciones(Some(&op_motor), &modelo, uso.as_deref(), &raiz));
        let think = match c.get("think").filter(|t| !t.es_nulo()) {
            Some(t) => Some(t.verdad()),
            None => campos.get("think").filter(|t| !t.es_nulo()).map(Valor::verdad),
        };
        let sistema = generar::completar_payload(&mut payload, &modelo, uso.as_deref(), think, &opcional_texto(&c, "system").unwrap_or_default());
        for clave in ["keep_alive", "truncate", "shift"] {
            if let Some(v) = campos.get(clave) {
                payload.poner(clave, v.clone());
            }
        }
        if !sistema.is_empty() {
            payload.poner("system", sistema.as_str());
        }
        match c.get("format") {
            None | Some(Valor::Nulo) => {}
            Some(Valor::Texto(t)) if t.is_empty() => {}
            Some(Valor::Texto(t)) if t != "json" => match prig_plataforma::json::leer(t) {
                Ok(esquema) => payload.poner("format", esquema),
                Err(_) => return detalle(StatusCode::BAD_REQUEST, "El esquema JSON no es válido"),
            },
            Some(f) => payload.poner("format", f.clone()),
        }
        let logprobs = c.get("logprobs").and_then(Valor::num).unwrap_or(0.0) as i64;
        if logprobs != 0 {
            payload.poner("logprobs", true);
            payload.poner("top_logprobs", logprobs.clamp(1, 5));
        }
        if c.verdad("raw") {
            payload.poner("raw", true);
        }
        if let Some(t) = opcional_texto(&c, "template").filter(|t| !t.is_empty()) {
            payload.poner("template", t);
        }
        if let Some(s) = opcional_texto(&c, "suffix").filter(|s| !s.is_empty()) {
            if !generar::capacidades(&modelo).iter().any(|c| c == "insert") {
                return detalle(StatusCode::BAD_REQUEST, format!("{modelo} no admite rellenar al medio (suffix)"));
            }
            payload.poner("suffix", s);
        }
        let datos = match gestor_ollama().probar(&payload, 900.0) {
            Ok(Valor::Mapa(d)) => d,
            Ok(_) => Mapa::new(),
            Err(e) => return de_error(e),
        };
        let num_ctx = payload.mapa("options").and_then(|o| o.get("num_ctx")).cloned();
        let probabilidades: Vec<Valor> = datos
            .lista("logprobs")
            .unwrap_or(&[])
            .iter()
            .take(4000)
            .map(|p| {
                let p = match p {
                    Valor::Mapa(p) => p.clone(),
                    _ => Mapa::new(),
                };
                let alternativas = p
                    .lista("top_logprobs")
                    .unwrap_or(&[])
                    .iter()
                    .map(|a| {
                        let a = match a {
                            Valor::Mapa(a) => a.clone(),
                            _ => Mapa::new(),
                        };
                        Valor::Mapa(
                            Mapa::new()
                                .con("token", a.get("token").cloned().unwrap_or(Valor::Nulo))
                                .con("logprob", a.get("logprob").cloned().unwrap_or(Valor::Nulo)),
                        )
                    })
                    .collect();
                Valor::Mapa(
                    Mapa::new()
                        .con("token", p.get("token").cloned().unwrap_or(Valor::Nulo))
                        .con("logprob", p.get("logprob").cloned().unwrap_or(Valor::Nulo))
                        .con("alternativas", Valor::Lista(alternativas)),
                )
            })
            .collect();
        let mut peticion = Mapa::new();
        for (k, v) in payload.iter().filter(|(k, _)| k.as_str() != "prompt") {
            peticion.poner(k.clone(), v.clone());
        }
        ok(Valor::Mapa(
            Mapa::new()
                .con("respuesta", datos.get("response").cloned().unwrap_or_else(|| Valor::Texto(String::new())))
                .con("pensamiento", datos.get("thinking").cloned().unwrap_or_else(|| Valor::Texto(String::new())))
                .con("metricas", generar::metricas(&datos, num_ctx.as_ref()))
                .con("logprobs", Valor::Lista(probabilidades))
                .con("peticion", peticion),
        ))
    })
    .await
}

/// Los pasos de un flujo largo como NDJSON, con `{"fase": "fin"}` o `{"fase": "error", "mensaje"}` al final. Si
/// quien pregunta se va, se deja de pedir.
fn ndjson(mut pasos: gestion::Pasos) -> Response {
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(32);
    std::thread::spawn(move || {
        let enviar = |v: Valor| tx.blocking_send(Ok(Bytes::from(prig_plataforma::json::escribir_compacto(&v) + "\n"))).is_ok();
        loop {
            match pasos.siguiente() {
                Ok(Some(e)) => {
                    if !enviar(e) {
                        return;
                    }
                }
                Ok(None) => {
                    enviar(Valor::Mapa(Mapa::new().con("fase", "fin")));
                    return;
                }
                Err(ErrorG::Gestion(t)) | Err(ErrorG::Py(ErrorPy::Propia(t))) => {
                    enviar(Valor::Mapa(Mapa::new().con("fase", "error").con("mensaje", t)));
                    return;
                }
                Err(ErrorG::Red(r)) => {
                    enviar(Valor::Mapa(Mapa::new().con("fase", "error").con("mensaje", r.texto())));
                    return;
                }
                Err(ErrorG::Py(_)) => return, // en Python, otra excepción cortaba el flujo
            }
        }
    });
    let flujo = futures_util::stream::unfold(rx, |mut rx| async move { rx.recv().await.map(|x| (x, rx)) });
    ([(header::CONTENT_TYPE, "application/x-ndjson")], Body::from_stream(flujo)).into_response()
}

const PARAMETROS_VARIANTE: [&str; 13] = [
    "temperature", "top_k", "top_p", "min_p", "seed", "repeat_penalty", "repeat_last_n", "presence_penalty", "frequency_penalty",
    "num_predict", "stop", "num_ctx", "num_keep",
];

const LISTA_DICTS: Tipo = Tipo::Lista(&Tipo::Dict(&Tipo::Texto));

/// `POST /api/modelos/crear`: una variante (sistema, parámetros, mensajes, licencia) en NDJSON
pub async fn crear(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(
        &m,
        &[
            ("nombre", &Tipo::Texto, true),
            ("desde", &Tipo::Texto, true),
            ("system", &Tipo::Texto, false),
            ("parametros", &DICT, false),
            ("mensajes", &LISTA_DICTS, false),
            ("licencia", &Tipo::Texto, false),
        ],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let parametros = c.mapa("parametros").cloned().unwrap_or_default();
    let mut fuera: Vec<&String> = parametros.claves().filter(|k| !PARAMETROS_VARIANTE.contains(&k.as_str())).collect();
    if !fuera.is_empty() {
        fuera.sort();
        let lista: Vec<&str> = fuera.iter().map(|s| s.as_str()).collect();
        return detalle(StatusCode::BAD_REQUEST, format!("No se pueden guardar en una variante: {}", lista.join(", ")));
    }
    let texto = |k: &str| c.get(k).map(Valor::texto_py).unwrap_or_default();
    let pasos = gestor_ollama().crear_variante(
        texto("nombre"),
        texto("desde"),
        texto("system"),
        Some(Valor::Mapa(parametros)),
        Some(c.get("mensajes").cloned().unwrap_or(Valor::Lista(vec![]))),
        texto("licencia"),
    );
    ndjson(pasos)
}

/// `POST /api/modelos/copiar` (`origen`, `destino`, `copiar_config`): su configuración viaja con él
pub async fn copiar(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(&m, &[("origen", &Tipo::Texto, true), ("destino", &Tipo::Texto, true), ("copiar_config", &Tipo::Booleano, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    bloque(move || {
        let origen = c.valor("origen").texto_py();
        let r = match gestor_ollama().copiar(&origen, &c.valor("destino").texto_py()) {
            Ok(r) => r,
            Err(e) => return de_error(e),
        };
        if c.get("copiar_config").is_none_or(Valor::verdad) {
            let _ = opciones::config().renombrar_modelo(&origen, &r.valor("modelo").texto_py());
        }
        ok(Valor::Mapa(r))
    })
    .await
}

fn nombre_y_uso(b: &Bytes) -> Result<(String, Option<String>), Response> {
    let m = cuerpo::modelo(b)?;
    let c = cuerpo::tipados(&m, &[("modelo", &Tipo::Texto, true), ("uso", &TEXTO_OPC, false)])?;
    Ok((c.valor("modelo").texto_py(), opcional_texto(&c, "uso")))
}

/// `POST /api/modelos/borrar`
pub async fn borrar(b: Bytes) -> Response {
    let (modelo, _) = match nombre_y_uso(&b) {
        Ok(x) => x,
        Err(r) => return r,
    };
    bloque(move || match gestor_ollama().borrar(&modelo) {
        Ok(r) => ok(Valor::Mapa(r)),
        Err(e) => de_error(e),
    })
    .await
}

/// `POST /api/modelos/importar` (`ruta`, `nombre`): solo un .gguf de la carpeta personal, en NDJSON
pub async fn importar(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(&m, &[("ruta", &Tipo::Texto, true), ("nombre", &Tipo::Texto, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let ruta = prig_plataforma::py::realpath(&prig_plataforma::py::expanduser(&c.valor("ruta").texto_py()));
    let casa = prig_plataforma::py::realpath(&prig_plataforma::py::expanduser("~"));
    if !format!("{ruta}/").starts_with(&format!("{casa}/")) {
        return detalle(StatusCode::FORBIDDEN, "Solo se importan archivos de tu carpeta personal");
    }
    if !ruta.to_lowercase().ends_with(".gguf") {
        return detalle(StatusCode::BAD_REQUEST, "El archivo debe ser .gguf");
    }
    ndjson(gestor_ollama().importar_gguf(ruta, c.valor("nombre").texto_py(), None))
}

/// `GET /api/modelos/actualizaciones`
pub async fn actualizaciones() -> Response {
    bloque(|| match gestor_ollama().actualizaciones(gestion::REGISTRO) {
        Ok(l) => ok(Valor::Mapa(Mapa::new().con("modelos", Valor::Lista(l)))),
        Err(e) => de_error(e),
    })
    .await
}

/// `GET /api/modelos/cargados`
pub async fn cargados() -> Response {
    bloque(|| match gestor_ollama().cargados() {
        Ok(l) => ok(Valor::Mapa(Mapa::new().con("modelos", Valor::Lista(l)))),
        Err(e) => de_error(e),
    })
    .await
}

/// `POST /api/modelos/precargar` (`modelo`, `uso`): con las opciones de carga de sus capas
pub async fn precargar(State(state): State<AppState>, b: Bytes) -> Response {
    let (modelo, uso) = match nombre_y_uso(&b) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let campos = generar::campos(&modelo, uso.as_deref());
        let todas = generar::opciones(None, &modelo, uso.as_deref(), &raiz);
        let mut opc = Mapa::new();
        for (k, v) in todas.iter() {
            if ["num_ctx", "num_gpu", "num_batch", "num_thread", "use_mmap", "main_gpu"].contains(&k.as_str()) {
                opc.poner(k.clone(), v.clone());
            }
        }
        let keep_alive = match campos.get("keep_alive") {
            Some(v) => v.clone(),
            None => motor::config_ia().get("keep_alive").cloned().unwrap_or(Valor::Nulo),
        };
        let ka = if keep_alive.es_nulo() { None } else { Some(&keep_alive) };
        match gestor_ollama().precargar(&modelo, &Valor::Mapa(opc), ka) {
            Ok(r) => ok(Valor::Mapa(r)),
            Err(e) => de_error(e),
        }
    })
    .await
}

/// `POST /api/modelos/descargar`: suelta el modelo de la memoria
pub async fn descargar(b: Bytes) -> Response {
    let (modelo, _) = match nombre_y_uso(&b) {
        Ok(x) => x,
        Err(r) => return r,
    };
    bloque(move || match gestor_ollama().descargar(&modelo) {
        Ok(r) => ok(Valor::Mapa(r)),
        Err(e) => de_error(e),
    })
    .await
}

/// La carpeta de modelos del servidor de Ollama (`OLLAMA_MODELS`), si la fija su entorno
fn carpeta_servidor(raiz: &Path) -> Option<String> {
    let estado = crate::routes::recursos::estado_servidor_publico(raiz);
    estado.mapa("entorno").and_then(|e| e.get("OLLAMA_MODELS")).filter(|v| !v.es_nulo()).map(Valor::texto_py)
}

/// `GET /api/modelos/parciales`: descargas a medias
pub async fn parciales(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || ok(Valor::Mapa(gestion::parciales(carpeta_servidor(&raiz).as_deref())))).await
}

/// `DELETE /api/modelos/parciales`
pub async fn borrar_parciales(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || ok(Valor::Mapa(gestion::borrar_parciales(carpeta_servidor(&raiz).as_deref())))).await
}

/// `GET /api/modelos/registro?lineas=400`: el registro del `ollama serve`
pub async fn registro(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let lineas = match cuerpo::entero_consulta(&q, "lineas", 400, i64::MIN, i64::MAX) {
        Ok(l) => l,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let estado = crate::routes::recursos::estado_servidor_publico(&raiz);
        let dueno = estado.get("dueno").filter(|d| !d.es_nulo()).map(Valor::texto_py);
        let ruta = std::env::var_os("HOME").map(std::path::PathBuf::from).unwrap_or_default().join(".prig_ollama.log");
        ok(Valor::Mapa(prig_recursos::servidor::leer_registro(lineas, dueno.as_deref(), &ruta.to_string_lossy())))
    })
    .await
}
