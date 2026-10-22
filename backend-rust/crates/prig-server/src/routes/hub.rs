//! Prig Hub (`/api/hub/*`, `hub/api.py`): tus repositorios de aprendizaje en texto plano, los que sigues, tu
//! progreso, importar y exportar desafíos, publicar en GitHub y preguntar al tutor sobre un repositorio. El servicio
//! está en `prig_integrations::hub`.

use std::collections::HashMap;
use std::sync::Mutex;

use axum::{
    body::Bytes,
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_aprendizaje::desafios as d;
use prig_integrations::hub::servicio::{ErrorHub, Hub, SISTEMA_IA};
use prig_integrations::hub::{git, github as gh};
use prig_plataforma::modelo::{Campo, Defecto, Modelo, Tipo};
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::desafios::{carpeta_base, error_obtener};
use crate::routes::desafios_fuentes::{guardar_y_registrar, validar_desafio};
use crate::routes::desafios_tutor::motor;
use crate::routes::profesor::ndjson_trabajo;
use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

/// Un Hub a la vez escribe (el `RLock` del servicio de Python)
static CERROJO: Mutex<()> = Mutex::new(());

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn de_hub(e: ErrorHub) -> Response {
    match e {
        ErrorHub::Usuario(m) => detalle(StatusCode::BAD_REQUEST, m),
        ErrorHub::Interno(m) => {
            tracing::warn!("Prig Hub: {m}");
            error_500()
        }
    }
}

fn servicio(state: &AppState) -> Hub {
    Hub::new(carpeta_base().join("desafios"), state.base_dir.clone())
}

/// `autor()`: el nombre del perfil de Inicio
fn autor() -> String {
    match prig_plataforma::inicio::perfil() {
        Ok(p) if p.valor("nombre").verdad() => p.valor("nombre").texto_py(),
        _ => String::new(),
    }
}

/// `propio(destino)`: «propio:<nombre>» o el nombre; el perfil se crea si hace falta
fn propio(s: &Hub, destino: &str) -> Result<String, ErrorHub> {
    let nombre = destino.strip_prefix("propio:").unwrap_or(destino).to_string();
    if nombre == "prig" {
        s.asegurar_perfil(&autor())?;
    }
    Ok(nombre)
}

/// El trabajo del Hub fuera del hilo de la petición y bajo el cerrojo: su resultado como JSON
async fn trabajo<F>(state: &AppState, f: F) -> Response
where
    F: FnOnce(&Hub) -> Result<Valor, ErrorHub> + Send + 'static,
{
    let s = servicio(state);
    tokio::task::spawn_blocking(move || {
        let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
        match f(&s) {
            Ok(v) => json_py(StatusCode::OK, &v),
            Err(e) => de_hub(e),
        }
    })
    .await
    .unwrap_or_else(|_| error_500())
}

fn m(v: Mapa) -> Valor {
    Valor::Mapa(v)
}

fn ok_true() -> Valor {
    m(Mapa::new().con("ok", true))
}

// ---------------------------------------------------------------------------------------------- modelos

const fn campo(nombre: &'static str, tipo: Tipo, defecto: Defecto) -> Campo {
    Campo { nombre, tipo, defecto }
}
const OBLIG: Defecto = Defecto::No;
const VACIO: Defecto = Defecto::Valor(|| Valor::Texto(String::new()));
const NULO: Defecto = Defecto::Valor(|| Valor::Nulo);
const PRIG: Defecto = Defecto::Valor(|| Valor::Texto("prig".into()));
const SI: Defecto = Defecto::Valor(|| Valor::Bool(true));
const NO: Defecto = Defecto::Valor(|| Valor::Bool(false));
const TEXTOS_OPC: Tipo = Tipo::Opcional(&Tipo::Lista(&Tipo::Texto));
const DICT: Tipo = Tipo::Dict(&Tipo::Cualquiera);

macro_rules! modelo {
    ($n:ident, $nombre:expr, [$($c:expr),* $(,)?]) => {
        static $n: Modelo = Modelo { nombre: $nombre, campos: &[$($c),*], antes: None };
    };
}

modelo!(SINCRONIZAR, "SincronizarLocal", [
    campo("destino", Tipo::Texto, PRIG),
    campo("categorias_youtube", TEXTOS_OPC, NULO),
    campo("incluir_todas_youtube", Tipo::Booleano, NO),
    campo("incluir_desafios", Tipo::Booleano, SI),
    campo("desafios_ids", TEXTOS_OPC, NULO),
    campo("crear_ruta_estudio", Tipo::Booleano, SI),
]);
modelo!(TEXTO, "Texto", [campo("texto", Tipo::Texto, OBLIG)]);
modelo!(AGREGAR, "Agregar", [
    campo("destino", Tipo::Texto, PRIG),
    campo("url", Tipo::Texto, OBLIG),
    campo("titulo", Tipo::Texto, VACIO),
    campo("nota", Tipo::Texto, VACIO),
    campo("etiquetas", TEXTOS_OPC, NULO),
    campo("tipo", Tipo::Texto, VACIO),
    campo("nivel", Tipo::Texto, VACIO),
    campo("minutos", Tipo::Opcional(&Tipo::Entero), NULO),
]);
modelo!(CLAVE, "Clave", [campo("destino", Tipo::Texto, PRIG), campo("clave", Tipo::Texto, OBLIG)]);
modelo!(EDITAR, "Editar", [campo("destino", Tipo::Texto, PRIG), campo("clave", Tipo::Texto, OBLIG), campo("cambios", DICT, OBLIG)]);
modelo!(COPIAR, "Copiar", [campo("origen", Tipo::Texto, OBLIG), campo("clave", Tipo::Texto, OBLIG), campo("destino", Tipo::Texto, PRIG)]);
modelo!(MANIFIESTO, "Manifiesto", [campo("destino", Tipo::Texto, OBLIG), campo("cambios", DICT, OBLIG)]);
modelo!(PACK, "Pack", [
    campo("titulo", Tipo::Texto, OBLIG),
    campo("descripcion", Tipo::Texto, VACIO),
    campo("etiquetas", TEXTOS_OPC, NULO),
    campo("nivel", Tipo::Texto, VACIO),
]);
modelo!(PASO, "Paso", [campo("titulo", Tipo::Texto, VACIO), campo("destino", Tipo::Texto, OBLIG), campo("nota", Tipo::Texto, VACIO)]);
modelo!(RUTA, "Ruta", [
    campo("destino", Tipo::Texto, OBLIG),
    campo("id", Tipo::Texto, VACIO),
    campo("titulo", Tipo::Texto, OBLIG),
    campo("descripcion", Tipo::Texto, VACIO),
    campo("nivel", Tipo::Texto, VACIO),
    campo("etiquetas", TEXTOS_OPC, NULO),
    campo("introduccion", Tipo::Texto, VACIO),
    campo("pasos", Tipo::Lista(&Tipo::Modelo(&PASO)), OBLIG),
]);
modelo!(RUTA_BORRAR, "RutaBorrar", [campo("destino", Tipo::Texto, OBLIG), campo("id", Tipo::Texto, OBLIG)]);
modelo!(URL, "Url", [campo("url", Tipo::Texto, OBLIG)]);
modelo!(SUSCRIPCION, "Suscripcion", [campo("clave", Tipo::Texto, OBLIG)]);
modelo!(APLICAR, "Aplicar", [campo("clave", Tipo::Texto, OBLIG), campo("commit", Tipo::Texto, OBLIG)]);
modelo!(PROGRESO, "Progreso", [
    campo("clave", Tipo::Texto, OBLIG),
    campo("estado", Tipo::Texto, OBLIG),
    campo("origen", Tipo::Texto, VACIO),
    campo("version", Tipo::Texto, VACIO),
]);
modelo!(IMPORTAR, "Importar", [campo("origen", Tipo::Texto, OBLIG), campo("id", Tipo::Texto, OBLIG), campo("confirmado", Tipo::Booleano, NO)]);
modelo!(EXPORTAR, "Exportar", [campo("destino", Tipo::Texto, OBLIG), campo("id_desafio", Tipo::Texto, OBLIG)]);
modelo!(DESTINO, "Destino", [campo("destino", Tipo::Texto, OBLIG)]);
modelo!(PREGUNTAR, "Preguntar", [
    campo("origen", Tipo::Texto, OBLIG),
    campo("mensajes", Tipo::Lista(&Tipo::Dict(&Tipo::Texto)), OBLIG),
    campo("modelo", Tipo::Opcional(&Tipo::Texto), NULO),
]);
modelo!(AJUSTES, "Ajustes", [campo("publicar_resumen", Tipo::Opcional(&Tipo::Booleano), NULO)]);

/// El cuerpo validado como el modelo de pydantic (todos los errores de primer nivel juntos) y con sus valores por
/// defecto, en el orden de sus campos
fn validar(b: &Bytes, modelo: &Modelo) -> Result<Mapa, Response> {
    let entrada = cuerpo::modelo(b)?;
    let campos: Vec<(&str, &Tipo, bool)> = modelo.campos.iter().map(|c| (c.nombre, &c.tipo, matches!(c.defecto, Defecto::No))).collect();
    let validos = cuerpo::tipados(&entrada, &campos)?;
    let mut salida = Mapa::new();
    for c in modelo.campos {
        match (validos.get(c.nombre), &c.defecto) {
            (Some(v), _) => salida.poner(c.nombre, v.clone()),
            (None, Defecto::Valor(f)) => salida.poner(c.nombre, f()),
            (None, Defecto::No) => {}
        }
    }
    Ok(salida)
}

fn t(c: &Mapa, k: &str) -> String {
    c.texto(k).unwrap_or("").to_string()
}

macro_rules! cuerpo_o {
    ($b:expr, $m:expr) => {
        match validar(&$b, &$m) {
            Ok(c) => c,
            Err(r) => return r,
        }
    };
}

// ---------------------------------------------------------------------------------------------- rutas

/// `GET /api/hub/estado`
pub async fn estado(State(state): State<AppState>) -> Response {
    let s = servicio(&state);
    tokio::task::spawn_blocking(move || {
        let Ok(token) = prig_integrations::github::token() else { return error_500() };
        let e = s.estado();
        json_py(
            StatusCode::OK,
            &m(Mapa::new()
                .con("git", git::disponible())
                .con("token", token.is_some())
                .con("origen_token", token.map(|t| Valor::Texto(t.1)).unwrap_or(Valor::Nulo))
                .con("github", e.valor("github").clone())
                .con("ajustes", e.valor("ajustes").clone())
                .con("carpeta", s.base.to_string_lossy().into_owned())),
        )
    })
    .await
    .unwrap_or_else(|_| error_500())
}

/// `GET /api/hub/todo`
pub async fn todo(State(state): State<AppState>) -> Response {
    trabajo(&state, |s| {
        s.asegurar_perfil(&autor())?;
        Ok(m(s.todo()?))
    })
    .await
}

/// `GET /api/hub/repos`
pub async fn repos(State(state): State<AppState>) -> Response {
    trabajo(&state, |s| Ok(m(s.repos()?))).await
}

fn consultas(q: &HashMap<String, String>, campos: &[&str]) -> Result<Vec<String>, Response> {
    let mut errores = Vec::new();
    let mut salida = Vec::new();
    for c in campos {
        match q.get(*c) {
            Some(v) => salida.push(v.clone()),
            None => errores.push(cuerpo::Error {
                tipo: "missing",
                loc: vec![Valor::Texto("query".into()), Valor::Texto((*c).into())],
                msg: "Field required".into(),
                entrada: Valor::Nulo,
                ctx: None,
            }),
        }
    }
    if errores.is_empty() { Ok(salida) } else { Err(cuerpo::respuesta(errores)) }
}

/// `GET /api/hub/repo?origen=`
pub async fn repo(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let v = match consultas(&q, &["origen"]) {
        Ok(v) => v,
        Err(r) => return r,
    };
    trabajo(&state, move |s| Ok(m(s.leer(&v[0])?))).await
}

/// `POST /api/hub/analizar`
pub async fn analizar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, TEXTO);
    trabajo(&state, move |s| Ok(m(s.analizar(&t(&c, "texto"), &gh::es_hub)?))).await
}

/// `POST /api/hub/agregar`
pub async fn agregar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, AGREGAR);
    trabajo(&state, move |s| {
        let nombre = propio(s, &t(&c, "destino"))?;
        Ok(m(s.agregar(&nombre, &t(&c, "url"), &t(&c, "titulo"), &t(&c, "nota"), c.get("etiquetas"), &t(&c, "tipo"), &t(&c, "nivel"), c.valor("minutos"))?))
    })
    .await
}

/// `POST /api/hub/quitar`
pub async fn quitar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, CLAVE);
    trabajo(&state, move |s| {
        let nombre = propio(s, &t(&c, "destino"))?;
        Ok(m(Mapa::new().con("ok", s.quitar(&nombre, &t(&c, "clave"))?)))
    })
    .await
}

/// `POST /api/hub/editar`
pub async fn editar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, EDITAR);
    trabajo(&state, move |s| {
        let nombre = propio(s, &t(&c, "destino"))?;
        let cambios = c.mapa("cambios").cloned().unwrap_or_default();
        Ok(m(Mapa::new().con("ok", s.editar(&nombre, &t(&c, "clave"), &cambios)?)))
    })
    .await
}

/// `POST /api/hub/copiar`
pub async fn copiar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, COPIAR);
    trabajo(&state, move |s| {
        let nombre = propio(s, &t(&c, "destino"))?;
        Ok(m(s.copiar(&t(&c, "origen"), &t(&c, "clave"), &nombre)?))
    })
    .await
}

/// `POST /api/hub/manifiesto`
pub async fn manifiesto(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, MANIFIESTO);
    trabajo(&state, move |s| {
        let nombre = propio(s, &t(&c, "destino"))?;
        Ok(m(s.editar_manifiesto(&nombre, &c.mapa("cambios").cloned().unwrap_or_default())?))
    })
    .await
}

/// `POST /api/hub/packs`
pub async fn crear_pack(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, PACK);
    trabajo(&state, move |s| {
        let etiquetas = c.lista("etiquetas").map(<[Valor]>::to_vec).unwrap_or_default();
        Ok(m(Mapa::new().con("nombre", s.crear_pack(&t(&c, "titulo"), &t(&c, "descripcion"), &etiquetas, &t(&c, "nivel"), &autor())?)))
    })
    .await
}

/// `POST /api/hub/rutas`
pub async fn guardar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, RUTA);
    trabajo(&state, move |s| {
        let nombre = propio(s, &t(&c, "destino"))?;
        let pasos: Vec<Mapa> = c.lista("pasos").unwrap_or(&[]).iter().filter_map(|p| if let Valor::Mapa(p) = p { Some(p.clone()) } else { None }).collect();
        let id = s.guardar_ruta(&nombre, &t(&c, "titulo"), &pasos, &t(&c, "id"), &t(&c, "descripcion"), &t(&c, "nivel"), c.get("etiquetas"), &t(&c, "introduccion"))?;
        Ok(m(Mapa::new().con("id", id)))
    })
    .await
}

/// `POST /api/hub/rutas/borrar`
pub async fn borrar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, RUTA_BORRAR);
    trabajo(&state, move |s| {
        let nombre = propio(s, &t(&c, "destino"))?;
        s.borrar_ruta(&nombre, &t(&c, "id"))?;
        Ok(ok_true())
    })
    .await
}

/// `GET /api/hub/recursos_locales`
pub async fn recursos_locales(State(state): State<AppState>) -> Response {
    trabajo(&state, |s| Ok(m(s.recursos_locales()))).await
}

/// `POST /api/hub/sincronizar_local`
pub async fn sincronizar_local(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, SINCRONIZAR);
    trabajo(&state, move |s| {
        let nombre = propio(s, &t(&c, "destino"))?;
        Ok(m(s.sincronizar_desde_prig(&nombre, &c)?))
    })
    .await
}

/// `POST /api/hub/seguir`: acepta el enlace, «usuario/repo», un usuario suelto (su perfil) o un pack suelto tuyo
pub async fn seguir(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, URL);
    let mut texto = prig_plataforma::py::strip(&t(&c, "url")).to_string();
    let s = servicio(&state);
    if !texto.contains('/') && !texto.contains('.') {
        if texto.to_lowercase().starts_with("prig-") {
            // Un pack suelto («prig-ml»): de tu propia cuenta, si Prig ya la conoce (se guarda al publicar)
            let login = s.estado().mapa("github").and_then(|g| g.get("login").filter(|l| l.verdad()).map(Valor::texto_py));
            let Some(login) = login else {
                return detalle(
                    StatusCode::BAD_REQUEST,
                    format!("¿De quién es «{texto}»? Escribe usuario/{texto} o el enlace completo (github.com/usuario/{texto})."),
                );
            };
            texto = format!("https://github.com/{login}/{texto}");
        } else {
            texto = format!("https://github.com/{}/prig", texto.trim_start_matches('@'));
        }
    } else if texto.contains('/') && !["http://", "https://", "git@", "/", "file://"].iter().any(|p| texto.starts_with(p)) {
        texto = format!("https://github.com/{}", texto.trim_start_matches('@'));
    }
    trabajo(&state, move |s| Ok(m(s.seguir(&texto, &autor())?))).await
}

/// `POST /api/hub/dejar`
pub async fn dejar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, SUSCRIPCION);
    trabajo(&state, move |s| {
        s.dejar(&t(&c, "clave"))?;
        Ok(ok_true())
    })
    .await
}

/// `POST /api/hub/novedades`
pub async fn novedades(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, SUSCRIPCION);
    trabajo(&state, move |s| Ok(m(s.novedades(&t(&c, "clave"))?))).await
}

/// `POST /api/hub/aplicar`
pub async fn aplicar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, APLICAR);
    trabajo(&state, move |s| Ok(m(s.aplicar(&t(&c, "clave"), &t(&c, "commit"))?))).await
}

/// `POST /api/hub/descartar`
pub async fn descartar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, SUSCRIPCION);
    trabajo(&state, move |s| {
        s.descartar(&t(&c, "clave"))?;
        Ok(ok_true())
    })
    .await
}

/// `POST /api/hub/progreso`
pub async fn progreso(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, PROGRESO);
    trabajo(&state, move |s| Ok(m(s.marcar(&t(&c, "clave"), &t(&c, "estado"), &t(&c, "origen"), &t(&c, "version"))?))).await
}

/// `GET /api/hub/desafio?origen=&id=`: todo el código a la vista ANTES de importarlo (nada se ejecuta aquí)
pub async fn desafio(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let v = match consultas(&q, &["origen", "id"]) {
        Ok(v) => v,
        Err(r) => return r,
    };
    trabajo(&state, move |s| Ok(m(s.desafio(&v[0], &v[1])?))).await
}

/// `POST /api/hub/desafio/importar`: solo con el código revisado y si pasa la verificación
pub async fn importar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, IMPORTAR);
    if !c.verdad("confirmado") {
        return detalle(StatusCode::BAD_REQUEST, "Revisa el código del desafío y confirma antes de importarlo.");
    }
    let espacio = espacio_de_trabajo(&state).await;
    let s = servicio(&state);
    let st = state.clone();
    tokio::task::spawn_blocking(move || {
        let (origen, id) = (t(&c, "origen"), t(&c, "id"));
        let mut des = {
            let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
            match s.a_desafio_prig(&origen, &id) {
                Ok(x) => x,
                Err(e) => return de_hub(e),
            }
        };
        let privado = des.mapa("privado").cloned().unwrap_or_default();
        let v = match validar_desafio(&st, des.lista("paginas").unwrap_or(&[]), privado.lista("referencia").unwrap_or(&[]), &privado, 1) {
            Ok(v) => v,
            Err(e) => return error_obtener(e),
        };
        if !v.verdad("valido") {
            return detalle(StatusCode::BAD_REQUEST, format!("No pasa la verificación, así que no se importa: {}", v.valor("motivo").texto_py()));
        }
        if let Some(Valor::Mapa(c)) = des.get_mut("comprobacion") {
            c.poner("pruebas", v.valor("pruebas").clone());
        }
        if let Some(Valor::Mapa(o)) = des.get_mut("origen") {
            o.poner("verificado", true);
        }
        if let Err(e) = guardar_y_registrar(&espacio, &mut des, "generated", 1) {
            return error_obtener(e);
        }
        let version = des.mapa("origen").map(|o| if o.valor("version").verdad() { o.valor("version").texto_py() } else { String::new() }).unwrap_or_default();
        if let Err(e) = s.marcar(&Hub::clave_desafio(&origen, &id), "en_curso", &origen, &version) {
            return de_hub(e);
        }
        json_py(StatusCode::OK, &m(d::publico(&des)))
    })
    .await
    .unwrap_or_else(|_| error_500())
}

/// `POST /api/hub/desafio/exportar`: un desafío de la sección Desafíos pasa a un pack tuyo
pub async fn exportar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, EXPORTAR);
    let des = match tokio::task::spawn_blocking({
        let id = t(&c, "id_desafio");
        move || d::obtener(&carpeta_base().join("desafios"), &id)
    })
    .await
    {
        Ok(Ok(Valor::Mapa(x))) => x,
        Ok(Ok(_)) => return error_500(),
        Ok(Err(d::ErrorObtener::Desafio(e) | d::ErrorObtener::Otro(e))) => return detalle(StatusCode::NOT_FOUND, e),
        Err(_) => return error_500(),
    };
    trabajo(&state, move |s| {
        let nombre = propio(s, &t(&c, "destino"))?;
        Ok(m(Mapa::new().con("id", s.exportar_desafio(&nombre, &des)?)))
    })
    .await
}

/// `GET /api/hub/desafios_locales`: los desafíos de la sección Desafíos que se pueden compartir en un pack
pub async fn desafios_locales() -> Response {
    tokio::task::spawn_blocking(|| {
        let filas: Vec<Valor> = d::lista(&carpeta_base().join("desafios"))
            .unwrap_or_default()
            .iter()
            .map(|x| {
                let o = x.mapa("origen").cloned().unwrap_or_default();
                let origen = if o.valor("nombre").verdad() { o.valor("nombre").clone() } else { o.valor("tipo").clone() };
                m(Mapa::new()
                    .con("id", x.valor("id").clone())
                    .con("titulo", x.valor("titulo").clone())
                    .con("nivel", x.valor("nivel").clone())
                    .con("origen", origen))
            })
            .collect();
        json_py(StatusCode::OK, &m(Mapa::new().con("desafios", Valor::Lista(filas))))
    })
    .await
    .unwrap_or_else(|_| error_500())
}

/// `POST /api/hub/publicar`
pub async fn publicar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, DESTINO);
    trabajo(&state, move |s| {
        let token = prig_integrations::github::token().map_err(|_| ErrorHub::Interno("token de GitHub".into()))?.map(|t| t.0);
        let nombre = propio(s, &t(&c, "destino"))?;
        Ok(m(s.publicar(&nombre, token.as_deref())?))
    })
    .await
}

/// `GET /api/hub/descubrir?q=&tipo=pack&pagina=1`
pub async fn descubrir(Query(q): Query<HashMap<String, String>>) -> Response {
    let pagina = match cuerpo::entero_consulta(&q, "pagina", 1, i64::MIN, i64::MAX) {
        Ok(p) => p,
        Err(r) => return r,
    };
    let consulta = q.get("q").cloned().unwrap_or_default();
    let tipo = q.get("tipo").cloned().unwrap_or_else(|| "pack".into());
    tokio::task::spawn_blocking(move || match gh::descubrir(&consulta, &tipo, pagina) {
        Ok(r) => json_py(StatusCode::OK, &m(r)),
        Err(e) => de_hub(e.into()),
    })
    .await
    .unwrap_or_else(|_| error_500())
}

/// `POST /api/hub/ajustes`
pub async fn ajustes(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, AJUSTES);
    trabajo(&state, move |s| {
        let mut cambios = Mapa::new();
        if !c.valor("publicar_resumen").es_nulo() {
            cambios.poner("publicar_resumen", c.valor("publicar_resumen").clone());
        }
        s.ajustes(&cambios)
    })
    .await
}

/// `POST /api/hub/preguntar`: el tutor sobre un repositorio; su contenido va como DATOS y sin herramientas
pub async fn preguntar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = cuerpo_o!(b, PREGUNTAR);
    let mensajes = c.lista("mensajes").map(<[Valor]>::to_vec).unwrap_or_default();
    if mensajes.is_empty() {
        return detalle(StatusCode::BAD_REQUEST, "Escribe una pregunta.");
    }
    let s = servicio(&state);
    let origen = t(&c, "origen");
    let datos = match tokio::task::spawn_blocking(move || s.contexto_ia(&origen, 12000)).await {
        Ok(Ok(x)) => x,
        Ok(Err(e)) => return de_hub(e),
        Err(_) => return error_500(),
    };
    let modelo = c.get("modelo").filter(|v| !v.es_nulo()).map(Valor::texto_py);
    let (motor_ia, nombre) = match motor(modelo.as_deref(), Some("explicar")) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let desde = mensajes.len().saturating_sub(10);
    let historial: Vec<String> = mensajes[desde..]
        .iter()
        .map(|x| {
            let x = if let Valor::Mapa(x) = x { x.clone() } else { Mapa::new() };
            let quien = if x.texto("rol") == Some("usuario") { "Alumno" } else { "Tutor" };
            let texto = x.get("texto").map(Valor::texto_py).unwrap_or_else(|| "None".into());
            format!("{quien}: {}", texto.chars().take(1500).collect::<String>())
        })
        .collect();
    let prompt = format!("{datos}\n\nCONVERSACIÓN:\n{}\nTutor:", historial.join("\n"));
    let raiz = state.base_dir.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let texto = prig_ia::tutor::flujo(&raiz, &motor_ia, &nombre, &prompt, SISTEMA_IA, 0.4, false, cancelar, avisar)?;
        Ok(m(Mapa::new().con("texto", texto)))
    })
}
