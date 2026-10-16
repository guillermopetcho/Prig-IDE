//! El buscador de modelos (`/api/buscador/*`): buscar en Ollama, Hugging Face y ModelScope, las variantes comprobadas,
//! cómo iría una en esta máquina, las novedades, lo instalado con versión nueva y los modelos seguidos
//! (`prig_modelos::explorar`). Inspeccionar un repositorio entero de Hugging Face sigue en Python con las descargas.

use std::collections::HashMap;

use axum::{
    body::Bytes,
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_ia::{gestor, ollama};
use prig_modelos::buscador::{self as b, ErrorB};
use prig_modelos::explorar as x;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

fn ok(v: Valor) -> Response {
    json_py(StatusCode::OK, &v)
}

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

/// `_buscador`: ErrorBuscador → 400; sin red → 503
fn de_error(e: ErrorB) -> Response {
    if x::es_del_buscador(&e) {
        return detalle(StatusCode::BAD_REQUEST, x::texto_error(&e));
    }
    match e {
        ErrorB::Red(_) => detalle(StatusCode::SERVICE_UNAVAILABLE, format!("Sin conexión con la plataforma: {}", x::texto_error(&e))),
        _ => error_500(),
    }
}

async fn bloque<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| error_500())
}

/// Los `campo: str` obligatorios de la consulta, con todos los 422 juntos como FastAPI
fn obligatorios(q: &HashMap<String, String>, campos: &[&str]) -> Result<Vec<String>, Response> {
    let faltan: Vec<cuerpo::Error> = campos
        .iter()
        .filter(|c| !q.contains_key(**c))
        .map(|c| cuerpo::Error { tipo: "missing", loc: vec!["query".into(), (*c).into()], msg: "Field required".into(), entrada: Valor::Nulo, ctx: None })
        .collect();
    if !faltan.is_empty() {
        return Err(cuerpo::respuesta(faltan));
    }
    Ok(campos.iter().map(|c| q[*c].clone()).collect())
}

fn instalados_tags() -> Vec<Mapa> {
    let texto = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .ok()
        .and_then(|c| c.get(format!("{}/api/tags", ollama::base_url())).send().ok())
        .and_then(|r| r.text().ok());
    match texto.and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        Some(Valor::Mapa(m)) => m.lista("models").unwrap_or(&[]).iter().filter_map(|v| if let Valor::Mapa(v) = v { Some(v.clone()) } else { None }).collect(),
        _ => Vec::new(),
    }
}

fn nombres_instalados() -> Vec<String> {
    let mut n = Vec::new();
    for m in instalados_tags() {
        let nombre = m.valor("name").texto_py();
        if let Some(s) = nombre.strip_suffix(":latest") {
            n.push(s.to_string());
        }
        n.push(nombre);
    }
    n
}

/// `_marcar_modelos`: si el usuario lo sigue y si ya tiene alguna variante instalada
fn marcar(modelos: &mut [Valor]) {
    let seguidos: Vec<String> = x::lista()
        .iter()
        .filter_map(|s| if let Valor::Mapa(s) = s { Some(format!("{}:{}", s.valor("fuente").texto_py(), s.valor("id").texto_py())) } else { None })
        .collect();
    let instalados: Vec<String> = nombres_instalados().iter().map(|n| n.to_lowercase()).collect();
    for m in modelos.iter_mut() {
        let Valor::Mapa(m) = m else { continue };
        let (f, id) = (m.valor("fuente").texto_py(), m.valor("id").texto_py());
        m.poner("seguido", seguidos.contains(&format!("{f}:{id}")));
        let prefijo = match f.as_str() {
            "huggingface" => format!("hf.co/{id}"),
            "modelscope" => format!("modelscope.cn/{id}"),
            _ => id,
        }
        .to_lowercase();
        let dentro = format!("{prefijo}:");
        m.poner("instalado", instalados.iter().any(|n| *n == prefijo || n.starts_with(&dentro)));
    }
}

/// `GET /api/buscador/fuentes`
pub async fn fuentes() -> Response {
    ok(Valor::Mapa(
        Mapa::new()
            .con("fuentes", x::fuentes())
            .con("ordenes", x::ordenes())
            .con("capacidades_ollama", Valor::Lista(b::CAPACIDADES_OLLAMA.iter().map(|c| Valor::Texto(c.to_string())).collect())),
    ))
}

/// `GET /api/buscador/buscar?q=&fuentes=&orden=&capacidad=&pagina_*=`
pub async fn buscar(Query(q): Query<HashMap<String, String>>) -> Response {
    let mut paginas = Mapa::new();
    for f in ["ollama", "modelscope"] {
        let campo = format!("pagina_{f}");
        if q.contains_key(&campo) {
            match cuerpo::entero_consulta(&q, &campo, 0, i64::MIN, i64::MAX) {
                Ok(n) => paginas.poner(f, n),
                Err(r) => return r,
            }
        }
    }
    if let Some(p) = q.get("pagina_huggingface") {
        paginas.poner("huggingface", p.as_str());
    }
    bloque(move || {
        let consulta = q.get("q").map(|s| s.trim().to_string()).unwrap_or_default();
        let fuentes: Vec<String> =
            q.get("fuentes").map(String::as_str).unwrap_or("ollama,huggingface,modelscope").split(',').map(str::trim).filter(|f| !f.is_empty()).map(String::from).collect();
        let orden = q.get("orden").cloned().unwrap_or_else(|| "relevancia".into());
        let mut r = x::buscar(&consulta, &fuentes, &orden, q.get("capacidad").map(String::as_str), &paginas);
        // Se marcan todos de una vez (una sola lectura de seguidos y de /api/tags)
        let mut por_fuente = r.mapa("fuentes").cloned().unwrap_or_default();
        let mut todos: Vec<Valor> = Vec::new();
        let mut tamanos = Vec::new();
        for (_, d) in por_fuente.iter() {
            let l = if let Valor::Mapa(d) = d { d.lista("modelos").map(<[Valor]>::to_vec).unwrap_or_default() } else { Vec::new() };
            tamanos.push(l.len());
            todos.extend(l);
        }
        marcar(&mut todos);
        let mut it = todos.into_iter();
        let claves: Vec<String> = por_fuente.claves().cloned().collect();
        for (k, n) in claves.into_iter().zip(tamanos) {
            if let Some(Valor::Mapa(mut d)) = por_fuente.get(&k).cloned() {
                d.poner("modelos", Valor::Lista(it.by_ref().take(n).collect()));
                por_fuente.poner(k, d);
            }
        }
        r.poner("fuentes", por_fuente);
        ok(Valor::Mapa(r))
    })
    .await
}

/// `GET /api/buscador/localizar?texto=`
pub async fn localizar(Query(q): Query<HashMap<String, String>>) -> Response {
    let [texto] = match obligatorios(&q, &["texto"]) {
        Ok(v) => [v[0].clone()],
        Err(r) => return r,
    };
    bloque(move || match x::localizar(&texto) {
        Ok(mut r) => {
            let mut todos = r.lista("exactos").map(<[Valor]>::to_vec).unwrap_or_default();
            let n = todos.len();
            todos.extend(r.lista("parecidos").map(<[Valor]>::to_vec).unwrap_or_default());
            marcar(&mut todos);
            let parecidos = todos.split_off(n);
            r.poner("exactos", Valor::Lista(todos));
            r.poner("parecidos", Valor::Lista(parecidos));
            ok(Valor::Mapa(r))
        }
        Err(e) => de_error(e),
    })
    .await
}

/// `GET /api/buscador/variantes?fuente=&id=`
pub async fn variantes(Query(q): Query<HashMap<String, String>>) -> Response {
    let v = match obligatorios(&q, &["fuente", "id"]) {
        Ok(v) => v,
        Err(r) => return r,
    };
    bloque(move || match x::variantes(&v[0], &v[1]) {
        Ok(mut d) => {
            let instalados = nombres_instalados();
            let bajos: Vec<String> = instalados.iter().map(|n| n.to_lowercase()).collect();
            let mut lista = d.lista("variantes").map(<[Valor]>::to_vec).unwrap_or_default();
            for v in lista.iter_mut() {
                if let Valor::Mapa(v) = v {
                    let r = v.valor("ref").texto_py();
                    v.poner("instalado", instalados.contains(&r) || bajos.contains(&r.to_lowercase()));
                }
            }
            d.poner("variantes", Valor::Lista(lista));
            ok(Valor::Mapa(d))
        }
        Err(e) => de_error(e),
    })
    .await
}

/// `GET /api/buscador/comprobar?ref=`
pub async fn comprobar(Query(q): Query<HashMap<String, String>>) -> Response {
    let v = match obligatorios(&q, &["ref"]) {
        Ok(v) => v,
        Err(r) => return r,
    };
    bloque(move || match x::comprobar(&v[0]) {
        Ok(r) => ok(r),
        Err(e) => de_error(e),
    })
    .await
}

const CAMPOS_FICHA: [&str; 9] = ["arquitectura", "parametros", "parametros_activos", "es_moe", "capas", "contexto_max", "piensa", "embedding", "bytes_peso"];

/// `GET /api/buscador/analizar?ref=`: cómo iría en esta máquina (solo la cabecera GGUF del registro)
pub async fn analizar(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let v = match obligatorios(&q, &["ref"]) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let fallo = |e: String| detalle(StatusCode::BAD_GATEWAY, format!("No se pudo leer la cabecera del modelo: {e}"));
        let r = match b::validar_ref(&v[0]) {
            Ok(r) => r,
            Err(e) if x::es_del_buscador(&e) => return detalle(StatusCode::BAD_REQUEST, x::texto_error(&e)),
            Err(e) => return fallo(x::texto_error(&e)),
        };
        let cache = std::env::var_os("HOME").map(std::path::PathBuf::from).unwrap_or_default().join(".prig_recursos_fichas.json");
        let f = match prig_recursos::ficha::desde_registro(&r, &cache) {
            Ok(f) => f,
            Err(e) => return fallo(e.to_string()),
        };
        let mut ficha = Mapa::new();
        for k in CAMPOS_FICHA {
            ficha.poner(k, f.get(k).cloned().unwrap_or(Valor::Nulo));
        }
        let resultado = Mapa::new().con("ref", r.as_str()).con("ficha", ficha);
        if f.verdad("embedding") {
            let v = Mapa::new().con("veredicto", "embeddings").con("etiqueta", "Modelo de embeddings").con("motivo", "Se usa en CPU para el índice semántico.");
            return ok(Valor::Mapa(resultado.con("veredicto", v)));
        }
        let maq = match gestor::gestor(&raiz).maquina(false) {
            Ok(m) => m,
            Err(e) => return fallo(e),
        };
        let rec = match prig_recursos::calculadora::recomendar(&f, &maq, "tutor", "equilibrado") {
            Ok(r) => r,
            Err(e) => return fallo(e),
        };
        let est = rec.mapa("estimacion").cloned().unwrap_or_default();
        let mut v = Mapa::new();
        for k in ["veredicto", "etiqueta", "motivo"] {
            v.poner(k, rec.get(k).cloned().unwrap_or(Valor::Nulo));
        }
        v.poner("tok_s", est.get("tok_s").cloned().unwrap_or(Valor::Nulo));
        v.poner("memoria_gb", est.get("total_gb").cloned().unwrap_or(Valor::Nulo));
        ok(Valor::Mapa(resultado.con("veredicto", v)))
    })
    .await
}

/// `GET /api/buscador/novedades`
pub async fn novedades() -> Response {
    bloque(|| ok(Valor::Mapa(x::novedades()))).await
}

/// `GET /api/buscador/actualizaciones?max_edad=&forzar=`
pub async fn actualizaciones(Query(q): Query<HashMap<String, String>>) -> Response {
    let max_edad = match cuerpo::entero_consulta(&q, "max_edad", 86400, i64::MIN, i64::MAX) {
        Ok(n) => n,
        Err(r) => return r,
    };
    let forzar = match cuerpo::booleano_consulta(&q, "forzar") {
        Ok(f) => f.unwrap_or(false),
        Err(r) => return r,
    };
    bloque(move || ok(Valor::Mapa(x::actualizaciones(instalados_tags, max_edad as f64, forzar)))).await
}

/// `GET /api/buscador/seguidos?revisar=`
pub async fn seguidos(Query(q): Query<HashMap<String, String>>) -> Response {
    let revisar = match cuerpo::booleano_consulta(&q, "revisar") {
        Ok(f) => f.unwrap_or(false),
        Err(r) => return r,
    };
    bloque(move || {
        let l = if revisar { x::revisar() } else { x::lista() };
        ok(Valor::Mapa(Mapa::new().con("seguidos", Valor::Lista(l))))
    })
    .await
}

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);

/// El cuerpo `SeguirRequest`: fuente, id y titulo opcional
fn seguir_req(cuerpo_b: &Bytes) -> Result<(String, String, Option<String>), Response> {
    let m = cuerpo::modelo(cuerpo_b)?;
    let c = cuerpo::tipados(&m, &[("fuente", &Tipo::Texto, true), ("id", &Tipo::Texto, true), ("titulo", &TEXTO_OPC, false)])?;
    Ok((c.valor("fuente").texto_py(), c.valor("id").texto_py(), c.get("titulo").filter(|t| !t.es_nulo()).map(Valor::texto_py)))
}

/// `POST /api/buscador/seguidos`
pub async fn seguir(b_: Bytes) -> Response {
    let (f, id, t) = match seguir_req(&b_) {
        Ok(v) => v,
        Err(r) => return r,
    };
    bloque(move || match x::seguir(&f, &id, t.as_deref()) {
        Ok(s) => ok(Valor::Mapa(s)),
        Err(e) => de_error(e),
    })
    .await
}

/// `POST /api/buscador/seguidos/dejar`
pub async fn dejar(b_: Bytes) -> Response {
    let (f, id, _) = match seguir_req(&b_) {
        Ok(v) => v,
        Err(r) => return r,
    };
    bloque(move || {
        x::dejar(&f, &id);
        ok(Valor::Mapa(Mapa::new().con("ok", true)))
    })
    .await
}

/// `POST /api/buscador/seguidos/visto`
pub async fn visto(b_: Bytes) -> Response {
    let (f, id, _) = match seguir_req(&b_) {
        Ok(v) => v,
        Err(r) => return r,
    };
    bloque(move || match x::marcar_visto(&f, &id) {
        Ok(s) => ok(Valor::Mapa(s)),
        Err(e) => de_error(e),
    })
    .await
}
