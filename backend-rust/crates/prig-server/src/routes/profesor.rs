//! Los profesores que leen con el alumno (los de app.py que generan con el modelo): explicar un notebook de Kaggle
//! (celda, guía, ruta de estudio, preguntas), sus datos, y un repositorio de GitHub. Los prompts están en
//! `prig_integrations`; generar, en `prig_ia::tutor::flujo`. Responden en NDJSON: los eventos del modelo
//! (`{"tipo": "texto", "delta"}`, `{"tipo": "pensando"}`) y al final `{"tipo": "fin", "resultado"}` o
//! `{"tipo": "error", "mensaje"}`.

#![allow(clippy::result_large_err)]

use std::path::{Path, PathBuf};
use std::sync::Arc;

use axum::{
    body::{Body, Bytes},
    extract::State,
    http::{header, StatusCode},
    response::{IntoResponse, Response},
};
use prig_ia::tutor::{self, Motor};
use prig_ia::vivo::Cancelar;
use prig_integrations::kaggle::Fallo;
use prig_integrations::{kaggle_profesor as kp, kaggle_red};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, detalle};
use crate::state::AppState;

/// `_ndjson_en_hilo`: `trabajo(cancelar, avisar)` en un hilo; sus eventos y al final `fin` o `error`. Si quien
/// pregunta se va, se cancela (el modelo deja de generar).
pub fn ndjson_trabajo<F>(trabajo: F) -> Response
where
    F: FnOnce(&Cancelar, &mut dyn FnMut(Mapa)) -> Result<Valor, String> + Send + 'static,
{
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(256);
    let cancelar = Arc::new(Cancelar::default());
    struct AlSoltar(Arc<Cancelar>);
    impl Drop for AlSoltar {
        fn drop(&mut self) {
            self.0.poner();
        }
    }
    let guarda = AlSoltar(cancelar.clone());
    crate::routes::asistente::apuntar(&cancelar);
    std::thread::spawn(move || {
        let linea = |v: Valor| Bytes::from(prig_plataforma::json::escribir_linea(&v) + "\n");
        let mut avisar = |e: Mapa| {
            if tx.blocking_send(Ok(linea(Valor::Mapa(e)))).is_err() {
                cancelar.poner();
            }
        };
        let fin = match trabajo(&cancelar, &mut avisar) {
            Ok(r) => Mapa::new().con("tipo", "fin").con("resultado", r),
            Err(m) => Mapa::new().con("tipo", "error").con("mensaje", m),
        };
        let _ = tx.blocking_send(Ok(linea(Valor::Mapa(fin))));
    });
    let flujo = futures_util::stream::unfold((rx, guarda), |(mut rx, g)| async move { rx.recv().await.map(|x| (x, (rx, g))) });
    ([(header::CONTENT_TYPE, "application/x-ndjson")], Body::from_stream(flujo)).into_response()
}

fn de_kaggle(e: Fallo) -> Response {
    match e {
        Fallo::Usuario(e) => detalle(StatusCode::BAD_REQUEST, e.0),
        Fallo::Interno => (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response(),
    }
}

/// `_mensajes_con_referencias`: las referencias de ML relacionadas delante del último mensaje del alumno
pub fn mensajes_con_referencias(raiz: &Path, mensajes: &[Valor]) -> Vec<Valor> {
    let mut copia: Vec<Valor> = mensajes.to_vec();
    for m in copia.iter_mut().rev() {
        if let Valor::Mapa(m) = m {
            if m.get("role") == Some(&Valor::Texto("user".into())) && m.get("content").is_some_and(Valor::verdad) {
                let c = m.valor("content").texto_py();
                m.poner("content", prig_biblioteca::referencias_ml::con_referencias(raiz, &c, &c).0);
                break;
            }
        }
    }
    copia
}

// =========================================================================== Kaggle

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const BOOL_OPC: Tipo = Tipo::Opcional(&Tipo::Booleano);
const ENTERO_OPC: Tipo = Tipo::Opcional(&Tipo::Entero);
const MENSAJES: Tipo = Tipo::Lista(&Tipo::Dict(&Tipo::Texto));

const CAMPOS_REF: [(&str, &Tipo, bool); 4] =
    [("ref", &Tipo::Texto, true), ("modelo", &TEXTO_OPC, false), ("regenerar", &Tipo::Booleano, false), ("incluir_datos", &BOOL_OPC, false)];

fn pedido(b: &Bytes, extra: &[(&'static str, &'static Tipo, bool)]) -> Result<Mapa, Response> {
    let m = cuerpo::modelo(b)?;
    let mut campos: Vec<(&str, &Tipo, bool)> = CAMPOS_REF.to_vec();
    campos.extend_from_slice(extra);
    cuerpo::tipados(&m, &campos)
}

fn opcional(c: &Mapa, k: &str) -> Option<String> {
    c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py)
}

/// Lo que sale del pedido antes de generar: el notebook, el motor, el modelo y el contexto de sus datos
struct Notebook {
    nb: Mapa,
    motor: Motor,
    nombre: String,
    modelo: String,
    datos: Option<String>,
}

fn preparar_notebook(c: &Mapa, espacio: &Path) -> Result<Notebook, Response> {
    let nb = kaggle_red::abrir(&c.valor("ref").texto_py(), false).map_err(de_kaggle)?;
    let pedido = opcional(c, "modelo");
    let (motor, nombre) = tutor::motor_desafios(pedido.as_deref(), Some("explicar")).map_err(|e| detalle(StatusCode::BAD_REQUEST, e))?;
    let modelo = tutor::modelo_desafios(pedido.as_deref(), Some("explicar"));
    // `getattr(req, "incluir_datos", True)`: si viene null, no se incluyen
    let datos = if c.get("incluir_datos").is_none_or(Valor::verdad) {
        kaggle_red::contexto_datos(&nb, espacio, 5).ok().and_then(|r| r.get("contexto_texto").filter(|t| !t.es_nulo()).map(Valor::texto_py))
    } else {
        None
    };
    Ok(Notebook { nb, motor, nombre, modelo, datos })
}

/// `_kaggle_con_cache`: la explicación guardada si ya existe; si no, se pide al modelo y se guarda.
/// `pedido`: None si no hace falta el modelo (una celda vacía).
fn con_cache(raiz: PathBuf, n: Notebook, indice: Option<i64>, nivel: String, regenerar: bool, pedido: Option<kp::Pedido>) -> Response {
    let guardada = if regenerar { None } else { kp::explicacion_guardada(&n.nb, indice, &nivel, &n.modelo) };
    if let Some(texto) = guardada {
        if let Some(i) = indice {
            kp::marcar_leida(&n.nb, i);
        }
        return ndjson_trabajo(move |_, _| Ok(Valor::Mapa(Mapa::new().con("texto", texto).con("guardada", true))));
    }
    ndjson_trabajo(move |cancelar, avisar| {
        let texto = match &pedido {
            None => "Celda vacía.".to_string(),
            Some(p) => tutor::flujo(&raiz, &n.motor, &n.nombre, &p.prompt, &p.sistema, p.temperatura, p.pensar, cancelar, avisar)?,
        };
        if texto.trim().is_empty() {
            return Err("El modelo no devolvió nada. Prueba otra vez u otro modelo.".into());
        }
        kp::guardar_explicacion(&n.nb, indice, &nivel, &n.modelo, &texto);
        Ok(Valor::Mapa(Mapa::new().con("texto", texto).con("guardada", false)))
    })
}

async fn en_hilo<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response())
}

/// `POST /api/kaggle/explicar` (`ref`, `indice`, `nivel`, `modelo`, `regenerar`, `incluir_datos`): una celda
pub async fn kaggle_explicar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("indice", &Tipo::Entero, true), ("nivel", &Tipo::Texto, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        let n = match preparar_notebook(&c, &espacio) {
            Ok(n) => n,
            Err(r) => return r,
        };
        let nivel = opcional(&c, "nivel").filter(|x| kp::es_nivel(x)).unwrap_or_else(|| "intermedio".into());
        let indice = c.get("indice").and_then(Valor::num).unwrap_or(0.0) as i64;
        let pedido = match kp::explicar(&n.nb, indice, &nivel, n.datos.as_deref()) {
            Ok(p) => p,
            Err(e) => return detalle(StatusCode::BAD_REQUEST, e),
        };
        con_cache(raiz, n, Some(indice), nivel, c.verdad("regenerar"), pedido)
    })
    .await
}

/// `POST /api/kaggle/guia`: la guía de lectura del notebook
pub async fn kaggle_guia(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(&b, &[]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        let n = match preparar_notebook(&c, &espacio) {
            Ok(n) => n,
            Err(r) => return r,
        };
        let p = kp::guia(&n.nb, n.datos.as_deref());
        con_cache(raiz, n, None, String::new(), c.verdad("regenerar"), Some(p))
    })
    .await
}

/// `POST /api/kaggle/notebook/estudio_optimo`: la ruta de estudio del notebook
pub async fn kaggle_estudio(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(&b, &[]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        let n = match preparar_notebook(&c, &espacio) {
            Ok(n) => n,
            Err(r) => return r,
        };
        let p = kp::estudio_optimo(&n.nb, n.datos.as_deref());
        con_cache(raiz, n, None, "estudio".into(), c.verdad("regenerar"), Some(p))
    })
    .await
}

/// `POST /api/kaggle/preguntar` (`ref`, `indice`, `mensajes`): una pregunta sobre el notebook
pub async fn kaggle_preguntar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("indice", &ENTERO_OPC, false), ("mensajes", &MENSAJES, true)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    if c.lista("mensajes").is_none_or(|l| l.is_empty()) {
        return detalle(StatusCode::BAD_REQUEST, "Escribe una pregunta.");
    }
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        let n = match preparar_notebook(&c, &espacio) {
            Ok(n) => n,
            Err(r) => return r,
        };
        let mensajes = mensajes_con_referencias(&raiz, c.lista("mensajes").unwrap_or(&[]));
        let indice = c.get("indice").filter(|v| !v.es_nulo()).and_then(Valor::num).map(|i| i as i64);
        let p = kp::preguntar(&n.nb, indice, &mensajes, n.datos.as_deref());
        ndjson_trabajo(move |cancelar, avisar| {
            let texto = tutor::flujo(&raiz, &n.motor, &n.nombre, &p.prompt, &p.sistema, p.temperatura, p.pensar, cancelar, avisar)?;
            Ok(Valor::Mapa(Mapa::new().con("texto", texto)))
        })
    })
    .await
}

// =========================================================================== GitHub

use prig_integrations::github;

const CAMPOS_GITHUB: [(&str, &Tipo, bool); 7] = [
    ("ref", &Tipo::Texto, true),
    ("ruta", &TEXTO_OPC, false),
    ("nivel", &Tipo::Texto, false),
    ("modelo", &TEXTO_OPC, false),
    ("regenerar", &Tipo::Booleano, false),
    ("nota", &TEXTO_OPC, false),
    ("mensajes", &MENSAJES_OPC, false),
];
const MENSAJES_OPC: Tipo = Tipo::Opcional(&MENSAJES);

/// `POST /api/github/explicar` (`ref`, `ruta`, `nivel`, `modelo`, `regenerar`): sin ruta, el repositorio; con ella, ese
/// archivo
pub async fn github_explicar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &CAMPOS_GITHUB)) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        let info = match github::abrir(&c.valor("ref").texto_py(), false) {
            Ok(i) => i,
            Err(e) => return de_kaggle(e),
        };
        let pedido = opcional(&c, "modelo");
        let (motor, nombre) = match tutor::motor_desafios(pedido.as_deref(), Some("explicar")) {
            Ok(x) => x,
            Err(e) => return detalle(StatusCode::BAD_REQUEST, e),
        };
        let modelo = tutor::modelo_desafios(pedido.as_deref(), Some("explicar"));
        let nivel = opcional(&c, "nivel").filter(|n| github::es_nivel(n)).unwrap_or_else(|| "intermedio".into());
        let ruta = opcional(&c, "ruta").filter(|r| !r.is_empty());
        if let Some(r) = &ruta {
            let esta = info.lista("archivos").unwrap_or(&[]).iter().any(|a| matches!(a, Valor::Mapa(a) if a.get("ruta") == Some(&Valor::Texto(r.clone()))));
            if !esta {
                return detalle(StatusCode::BAD_REQUEST, "Ese archivo no está en el repositorio.");
            }
        }
        let nivel = if ruta.is_some() { nivel } else { String::new() };
        if !c.verdad("regenerar") {
            if let Some(texto) = github::explicacion_guardada(&info, ruta.as_deref(), &nivel, &modelo) {
                return ndjson_trabajo(move |_, _| Ok(Valor::Mapa(Mapa::new().con("texto", texto).con("guardada", true))));
            }
        }
        ndjson_trabajo(move |cancelar, avisar| {
            let texto = match &ruta {
                Some(r) => {
                    let (prompt, sistema) = github::pedido_archivo(&info, r, &nivel).map_err(|e| match e {
                        Fallo::Usuario(e) => e.0,
                        Fallo::Interno => "Error interno".into(),
                    })?;
                    tutor::flujo(&raiz, &motor, &nombre, &prompt, &sistema, 0.3, false, cancelar, avisar)?
                }
                None => tutor::flujo(&raiz, &motor, &nombre, &github::contexto_repo(&info, 14000), github::SISTEMA_REPO, 0.3, true, cancelar, avisar)?,
            };
            if texto.trim().is_empty() {
                return Err("El modelo no devolvió nada. Prueba otra vez u otro modelo.".into());
            }
            let _ = github::guardar_explicacion(&info, ruta.as_deref(), &nivel, &modelo, &texto);
            Ok(Valor::Mapa(Mapa::new().con("texto", texto).con("guardada", false)))
        })
    })
    .await
}

/// `POST /api/github/preguntar` (`ref`, `ruta`, `mensajes`, `modelo`)
pub async fn github_preguntar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &CAMPOS_GITHUB)) {
        Ok(c) => c,
        Err(r) => return r,
    };
    if c.lista("mensajes").is_none_or(|l| l.is_empty()) {
        return detalle(StatusCode::BAD_REQUEST, "Escribe una pregunta.");
    }
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        let info = match github::abrir(&c.valor("ref").texto_py(), false) {
            Ok(i) => i,
            Err(e) => return de_kaggle(e),
        };
        let (motor, nombre) = match tutor::motor_desafios(opcional(&c, "modelo").as_deref(), Some("explicar")) {
            Ok(x) => x,
            Err(e) => return detalle(StatusCode::BAD_REQUEST, e),
        };
        let mensajes = mensajes_con_referencias(&raiz, c.lista("mensajes").unwrap_or(&[]));
        let ruta = opcional(&c, "ruta");
        ndjson_trabajo(move |cancelar, avisar| {
            let prompt = github::pedido_pregunta(&info, ruta.as_deref(), &mensajes, &nombre);
            let texto = tutor::flujo(&raiz, &motor, &nombre, &prompt, github::SISTEMA_PREGUNTAR, 0.4, false, cancelar, avisar)?;
            Ok(Valor::Mapa(Mapa::new().con("texto", texto)))
        })
    })
    .await
}

/// `POST /api/kaggle/explicar_datos` (`tipo`: dataset | competicion, `ref`, `modelo`, `regenerar`)
pub async fn kaggle_explicar_datos(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(&m, &[("tipo", &Tipo::Texto, true), ("ref", &Tipo::Texto, true), ("modelo", &TEXTO_OPC, false), ("regenerar", &Tipo::Booleano, false)])
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        let tipo = c.valor("tipo").texto_py();
        let r = c.valor("ref").texto_py();
        let ficha = match tipo.as_str() {
            "dataset" => kaggle_red::dataset(&r, Some(&espacio)),
            "competicion" => kaggle_red::competicion(&r, Some(&espacio)),
            _ => return detalle(StatusCode::BAD_REQUEST, "Tipo desconocido: dataset o competicion."),
        };
        let ficha = match ficha {
            Ok(f) => f,
            Err(e) => return de_kaggle(e),
        };
        let pedido = opcional(&c, "modelo");
        let (motor, nombre) = match tutor::motor_desafios(pedido.as_deref(), Some("explicar")) {
            Ok(x) => x,
            Err(e) => return detalle(StatusCode::BAD_REQUEST, e),
        };
        let modelo = tutor::modelo_desafios(pedido.as_deref(), Some("explicar"));
        let huella = kp::huella(&ficha);
        let ref_ficha = ficha.get("ref").map(Valor::texto_py).unwrap_or_default();
        if !c.verdad("regenerar") {
            if let Some(texto) = kp::explicacion_datos(&tipo, &ref_ficha, &modelo, &huella) {
                return ndjson_trabajo(move |_, _| Ok(Valor::Mapa(Mapa::new().con("texto", texto).con("guardada", true))));
            }
        }
        ndjson_trabajo(move |cancelar, avisar| {
            let prompt = kp::contexto_datos(&ficha, &kp::previas_para_modelo(&ficha, &espacio));
            let texto = tutor::flujo(&raiz, &motor, &nombre, &prompt, kp::SISTEMA_DATOS, 0.3, false, cancelar, avisar)?;
            if texto.trim().is_empty() {
                return Err("El modelo no devolvió nada. Prueba otra vez u otro modelo.".into());
            }
            kp::guardar_explicacion_datos(&tipo, &ref_ficha, &modelo, &huella, &texto);
            Ok(Valor::Mapa(Mapa::new().con("texto", texto).con("guardada", false)))
        })
    })
    .await
}

// =========================================================================== YouTube

use prig_integrations::youtube_profesor as yp;

/// `"".join(motor.generate_response(...))`: toda la respuesta, sin razonar
fn respuesta_entera(raiz: &Path, motor: &Motor, nombre: &str, prompt: &str, sistema: &str, temperatura: f64, cancelar: &Cancelar) -> String {
    let mut texto = String::new();
    tutor::generar_con(raiz, motor, nombre, prompt, sistema, Some(false), Mapa::new().con("temperature", temperatura), false, Some("tutor"), cancelar, &mut |e| {
        if e.texto("t") == Some("texto") {
            texto.push_str(&e.valor("v").texto_py());
        }
    });
    texto
}

/// `POST /api/youtube/analizar`: resumen estructurado, objetivos didácticos o ambos
pub async fn youtube_analizar(State(state): State<AppState>, b: Bytes) -> Response {
    let campos: [(&str, &Tipo, bool); 11] = [
        ("video_id", &Tipo::Texto, true),
        ("titulo", &Tipo::Texto, true),
        ("canal", &TEXTO_OPC, false),
        ("duracion", &TEXTO_OPC, false),
        ("descripcion", &TEXTO_OPC, false),
        ("categoria", &TEXTO_OPC, false),
        ("nivel", &TEXTO_OPC, false),
        ("texto_usuario", &TEXTO_OPC, false),
        ("notas_usuario", &TEXTO_OPC, false),
        ("modo", &TEXTO_OPC, false),
        ("modelo", &TEXTO_OPC, false),
    ];
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &campos)) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        let (motor, nombre) = match tutor::motor_desafios(opcional(&c, "modelo").as_deref(), Some("tutor")) {
            Ok(x) => x,
            Err(e) => return detalle(StatusCode::BAD_REQUEST, e),
        };
        // `req.x or defecto`: un campo ausente toma el valor por defecto del modelo; null o vacío, el de la llamada
        let o = |k: &str, defecto_modelo: &str, defecto: &str| -> String {
            match c.get(k) {
                None => if defecto_modelo.is_empty() { defecto.to_string() } else { defecto_modelo.to_string() },
                Some(v) if v.verdad() => v.texto_py(),
                Some(_) => defecto.to_string(),
            }
        };
        let titulo = c.valor("titulo").texto_py();
        let (canal, duracion) = (o("canal", "YouTube", "YouTube"), o("duracion", "", ""));
        let ctx = yp::preparar_contexto(
            &raiz,
            &c.valor("video_id").texto_py(),
            &titulo,
            &canal,
            &duracion,
            &o("descripcion", "", ""),
            &o("texto_usuario", "", ""),
            &o("notas_usuario", "", ""),
        );
        let contexto = ctx.valor("texto").texto_py();
        let mut resultado = Mapa::new()
            .con("fuente", ctx.valor("fuente").clone())
            .con("transcripcion_completa", ctx.valor("transcripcion_completa").clone());
        let modo = match c.get("modo") {
            None => "ambos".to_string(),
            Some(v) => v.texto_py(),
        };
        let categoria = o("categoria", "", "");
        let cancelar = Cancelar::default();
        if modo == "resumen" || modo == "ambos" {
            let r = respuesta_entera(&raiz, &motor, &nombre, &yp::prompt_resumen(&titulo, &canal, &duracion, &contexto, &categoria), yp::SISTEMA_RESUMEN, 0.25, &cancelar);
            if let Some(e) = yp::error_del_motor(&r) {
                return detalle(StatusCode::BAD_GATEWAY, e);
            }
            resultado.poner("resumen", yp::resumen_de(&r, &titulo));
        }
        if modo == "objetivos" || modo == "ambos" {
            let nivel = o("nivel", "intermedio", "intermedio");
            let r = respuesta_entera(&raiz, &motor, &nombre, &yp::prompt_objetivos(&titulo, &canal, &duracion, &contexto, &nivel, &categoria), yp::SISTEMA_OBJETIVOS, 0.3, &cancelar);
            if let Some(e) = yp::error_del_motor(&r) {
                return detalle(StatusCode::BAD_GATEWAY, e);
            }
            let duracion_s = ctx.get("duracion_segundos").and_then(Valor::num).unwrap_or(0.0) as i64;
            match yp::objetivos_de(&r, duracion_s) {
                Ok(l) => resultado.poner("objetivos", Valor::Lista(l)),
                Err(e) => return detalle(StatusCode::BAD_GATEWAY, e),
            }
        }
        crate::routes::json_py(StatusCode::OK, &Valor::Mapa(resultado))
    })
    .await
}

/// `POST /api/youtube/traducir_texto` (`texto`, `modelo`): traduce y explica un fragmento de la clase
pub async fn youtube_traducir(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(&m, &[("texto", &Tipo::Texto, true), ("de", &TEXTO_OPC, false), ("a", &TEXTO_OPC, false), ("modelo", &TEXTO_OPC, false)])
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let texto = c.valor("texto").texto_py();
    if prig_plataforma::py::strip(&texto).is_empty() {
        return detalle(StatusCode::BAD_REQUEST, "El texto a traducir está vacío");
    }
    let raiz = state.base_dir.clone();
    en_hilo(move || {
        let modelo = tutor::modelo_desafios(opcional(&c, "modelo").as_deref(), Some("tutor"));
        let (motor, nombre) = match tutor::motor_desafios(Some(&modelo), None) {
            Ok(x) => x,
            Err(e) => return detalle(StatusCode::BAD_REQUEST, e),
        };
        let r = respuesta_entera(&raiz, &motor, &nombre, &yp::prompt_traducir(&texto), "", 0.2, &Cancelar::default());
        let traduccion = yp::sin_pensamiento(prig_plataforma::py::strip(&r));
        let respuesta = if yp::error_del_motor(&traduccion).is_some() || traduccion.is_empty() {
            Mapa::new()
                .con("ok", false)
                .con("error", if traduccion.is_empty() { "El modelo no devolvió texto.".to_string() } else { traduccion })
                .con("original", texto.as_str())
        } else {
            Mapa::new().con("ok", true).con("traduccion", traduccion).con("original", texto.as_str())
        };
        crate::routes::json_py(StatusCode::OK, &Valor::Mapa(respuesta))
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn referencias_solo_en_el_ultimo_mensaje_del_alumno() {
        let raiz = Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/../../.."));
        let m = |rol: &str, t: &str| Valor::Mapa(Mapa::new().con("role", rol).con("content", t));
        let mensajes = vec![m("user", "¿qué es XGBoost?"), m("assistant", "…"), m("user", "resume el paper de XGBoost")];
        let nuevos = mensajes_con_referencias(raiz, &mensajes);
        let contenido = |v: &Valor| match v {
            Valor::Mapa(x) => x.valor("content").texto_py(),
            _ => String::new(),
        };
        assert!(contenido(&nuevos[2]).contains("arxiv.org/abs/1603.02754"));
        assert_eq!(contenido(&nuevos[0]), "¿qué es XGBoost?");
        assert_eq!(contenido(&mensajes[2]), "resume el paper de XGBoost");
    }
}
