//! El conocimiento de la biblioteca (`prig_biblioteca::conocimiento`): el estado del índice, indexar en segundo plano
//! y buscar (con las reformulaciones del modelo si la bandera `query_expansion` está puesta).

use axum::{
    body::Bytes,
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_biblioteca::conocimiento::{self as k, Conocimiento};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

pub fn servicio(state: &AppState) -> Result<&'static Conocimiento, String> {
    k::global(|| crate::routes::libros::pdfium(state))
}

async fn en_hilo<F: FnOnce() -> Result<Valor, String> + Send + 'static>(f: F) -> Response {
    match tokio::task::spawn_blocking(f).await {
        Ok(Ok(v)) => json_py(StatusCode::OK, &v),
        _ => error_500(),
    }
}

/// `_context_budget`: ~45 % de la ventana configurada (al menos 400), o lo pedido si es menos
pub fn presupuesto(pedido: Option<i64>) -> i64 {
    let n = match prig_ia::motor::config_ia().get("num_ctx") {
        None => 4096,
        Some(Valor::Entero(n)) => *n as i64,
        Some(Valor::Real(r)) if r.is_finite() => r.trunc() as i64,
        Some(Valor::Bool(b)) => *b as i64,
        Some(Valor::Texto(t)) => py::strip(t).parse().unwrap_or(4096),
        Some(_) => 4096,
    };
    let b = 400.max((n as f64 * 0.45) as i64);
    match pedido.filter(|p| *p != 0) {
        Some(p) => p.min(b),
        None => b,
    }
}

/// `AIEngine.expand_query`: hasta 3 reformulaciones con la terminología técnica de un libro
pub fn reformular(state: &AppState, q: &str, modelo: &str) -> Vec<String> {
    let banderas = prig_plataforma::banderas::Banderas::new(std::path::PathBuf::from(py::expanduser("~/.prig_flags.json")));
    if !banderas.activa("query_expansion") {
        return Vec::new();
    }
    let sistema = "Reescribe la consulta del usuario en variantes de búsqueda con la TERMINOLOGÍA TÉCNICA equivalente que aparecería en un libro. Devuelve ÚNICAMENTE las variantes, una por línea, sin numerar, sin comillas y sin explicaciones. Máximo 3 líneas.";
    let p = prig_ia::generar::PedidoGenerar {
        prompt: format!("Consulta: {q}"),
        modelo: modelo.into(),
        sistema: sistema.into(),
        opciones: Some(Mapa::new().con("temperature", 0.2)),
        gobernador: true,
        ..Default::default()
    };
    let mut crudo = String::new();
    let cancelar = prig_ia::vivo::Cancelar::default();
    prig_ia::generar::generar(&state.base_dir, &p, &cancelar, &mut |e: Mapa| {
        if e.get("t") == Some(&Valor::Texto("texto".into())) {
            crudo.push_str(&e.valor("v").texto_py());
        }
    });
    let mut v = Vec::new();
    for l in prig_recursos::servidor::lineas_como_python(&crudo) {
        let x = py::strip(l).trim_start_matches(|c: char| "-*0123456789.) ".contains(c));
        let x = py::strip(x).trim_matches('"').to_string();
        if !x.is_empty() && x.to_lowercase() != q.to_lowercase() && x.chars().count() > 3 {
            v.push(x);
        }
    }
    v.truncate(3);
    v
}

/// `GET /api/knowledge/status`
pub async fn estado(State(state): State<AppState>) -> Response {
    en_hilo(move || Ok(Valor::Mapa(servicio(&state)?.estado()?))).await
}

/// `POST /api/knowledge/index` (`force`): en segundo plano; el progreso, en `status`
pub async fn indexar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("force", &Tipo::Booleano, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || Ok(Valor::Mapa(servicio(&state)?.indexar_en_segundo_plano(c.verdad("force"))))).await
}

const ENTERO_OPC: Tipo = Tipo::Opcional(&Tipo::Entero);

/// `POST /api/knowledge/search` (`query`, `top_k`, `expand`, `model`, `max_context_tokens`): sin modelo que responda
pub async fn buscar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(
            &m,
            &[("query", &Tipo::Texto, true), ("top_k", &Tipo::Entero, false), ("expand", &Tipo::Booleano, false), ("model", &Tipo::Texto, false), ("max_context_tokens", &ENTERO_OPC, false)],
        )
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        let q = c.valor("query").texto_py();
        let top_k = c.get("top_k").and_then(Valor::num).map(|n| n as i64).unwrap_or(8);
        let expandir = c.get("expand").map(Valor::verdad).unwrap_or(true);
        let modelo = c.get("model").map(Valor::texto_py).unwrap_or_else(|| "qwen2.5-coder:7b".into());
        let tope = presupuesto(c.get("max_context_tokens").and_then(Valor::num).map(|n| n as i64));
        let exp = if expandir { reformular(&state, &q, &modelo) } else { Vec::new() };
        Ok(Valor::Mapa(servicio(&state)?.buscar(&q, top_k.max(0) as usize, tope, &exp)?))
    })
    .await
}

const LIBRARY_TUTOR_PROMPT: &str = "Eres el TUTOR de Prig IDE respondiendo a partir de la BIBLIOTECA PERSONAL del alumno.\n\nREGLAS ESTRICTAS:\n1. Responde APOYÁNDOTE en los fragmentos proporcionados. Son la fuente de verdad.\n2. Cita el fragmento que respalda cada afirmación con su marca [1], [2]...\n3. Si los fragmentos NO contienen la respuesta, dilo con claridad y explica qué falta. Es preferible admitirlo a inventar: el alumno debe poder confiar en las citas.\n4. Distingue explícitamente lo que viene de la biblioteca de lo que añades por tu cuenta.\n5. Responde en español, en Markdown limpio, sin saludos ni relleno.";

/// `POST /api/knowledge/ask` (`query`, `model`, `top_k`, `expand`, `max_context_tokens`): primero las fuentes y
/// después la respuesta del tutor, en NDJSON
pub async fn preguntar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(
            &m,
            &[("query", &Tipo::Texto, true), ("model", &Tipo::Texto, false), ("top_k", &Tipo::Entero, false), ("expand", &Tipo::Booleano, false), ("max_context_tokens", &ENTERO_OPC, false)],
        )
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let q = c.valor("query").texto_py();
    let modelo = c.get("model").map(Valor::texto_py).unwrap_or_else(|| "qwen2.5-coder:7b".into());
    let top_k = c.get("top_k").and_then(Valor::num).map(|n| n as i64).unwrap_or(6);
    let expandir = c.get("expand").map(Valor::verdad).unwrap_or(true);
    let pedido = c.get("max_context_tokens").and_then(Valor::num).map(|n| n as i64);
    // Lo previo a la respuesta (contexto, búsqueda, lecturas) se hace antes de abrir el flujo, como Python
    let st = state.clone();
    let (q2, m2) = (q.clone(), modelo.clone());
    let previo = tokio::task::spawn_blocking(move || -> Result<(Mapa, String), String> {
        let presupuesto = presupuesto(pedido);
        let destilado = crate::routes::kb::contexto_destilado(&q2, presupuesto);
        let exp = if expandir { reformular(&st, &q2, &m2) } else { Vec::new() };
        let tope = if destilado.is_some() { presupuesto.div_euclid(3) } else { presupuesto };
        let r = servicio(&st)?.buscar(&q2, top_k.max(0) as usize, tope, &exp)?;
        let encontrado = r.verdad("found");
        let mut contexto = match &destilado {
            Some(d) if encontrado => format!("{}\n\n--- FRAGMENTOS ADICIONALES ---\n{}", d.valor("texto").texto_py(), r.valor("context_prompt").texto_py()),
            Some(d) => d.valor("texto").texto_py(),
            None => r.valor("context_prompt").texto_py(),
        };
        let (bloque, refs) = prig_biblioteca::referencias_ml::bloque_para_prompt(&st.base_dir, &q2, 5);
        if !bloque.is_empty() {
            contexto = format!("{contexto}\n\n--- LECTURAS RECOMENDADAS (catálogo) ---\n{bloque}");
        }
        let trozos: Vec<Valor> = r
            .lista("chunks")
            .unwrap_or(&[])
            .iter()
            .enumerate()
            .filter_map(|(i, c)| {
                let Valor::Mapa(c) = c else { return None };
                Some(Valor::Mapa(
                    Mapa::new()
                        .con("n", (i + 1) as i64)
                        .con("chunk_id", c.valor("chunk_id").clone())
                        .con("source_id", c.valor("source_id").clone())
                        .con("source_title", c.get("source_title").cloned().unwrap_or_else(|| c.valor("source_id").clone()))
                        .con("page", c.valor("page").clone())
                        .con("content_type", c.valor("content_type").clone())
                        .con("preview", c.valor("content").texto_py().chars().take(220).collect::<String>()),
                ))
            })
            .collect();
        let fuentes = Mapa::new()
            .con("type", "sources")
            .con("found", encontrado || destilado.is_some())
            .con("evidence", r.get("evidence").cloned().unwrap_or(Valor::Nulo))
            .con("verificado", destilado.is_some())
            .con("conceptos", destilado.as_ref().and_then(|d| d.get("conceptos").cloned()).unwrap_or(Valor::Lista(vec![])))
            .con("citas", destilado.as_ref().and_then(|d| d.get("fuentes").cloned()).unwrap_or(Valor::Lista(vec![])))
            .con("chunks", Valor::Lista(trozos))
            .con("stats", r.get("stats").cloned().unwrap_or(Valor::Nulo))
            .con("referencias", Valor::Lista(refs.iter().map(|x| Valor::Mapa(prig_biblioteca::referencias_ml::resumen_publico(x))).collect()));
        Ok((fuentes, contexto))
    })
    .await;
    let Ok(Ok((fuentes, contexto))) = previo else { return error_500() };
    let raiz = state.base_dir.clone();
    crate::routes::asistente::flujo_con_tipo("application/x-ndjson", move |cancelar, enviar| {
        let linea = |m: Mapa| prig_plataforma::json::escribir_linea(&Valor::Mapa(m)) + "\n";
        enviar(linea(fuentes));
        let token = |t: &str| linea(Mapa::new().con("type", "token").con("text", t));
        if py::strip(&contexto).is_empty() {
            enviar(token("No encontré nada en tu biblioteca relacionado con esa consulta. Comprueba que el material esté indexado en la sección de Biblioteca."));
        } else {
            let nivel = prig_ia::motor::config_ia().get("depth_level").map(Valor::texto_py).unwrap_or_else(|| "intermediate".into());
            let p = prig_ia::generar::PedidoGenerar {
                prompt: format!("{contexto}\n\n---\nPREGUNTA DEL ALUMNO: {q}"),
                modelo,
                sistema: format!("{LIBRARY_TUTOR_PROMPT}\n\nNivel del alumno: {nivel}."),
                gobernador: true,
                ..Default::default()
            };
            prig_ia::generar::generar(&raiz, &p, cancelar, &mut |e: Mapa| {
                if e.get("t") == Some(&Valor::Texto("texto".into())) {
                    enviar(token(&e.valor("v").texto_py()));
                }
            });
        }
        enviar(linea(Mapa::new().con("type", "done")));
    })
}
