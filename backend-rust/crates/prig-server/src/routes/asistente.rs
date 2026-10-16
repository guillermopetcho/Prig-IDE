//! El asistente del editor y lo suelto de la IA: el catálogo de modelos de Prig cruzado con lo instalado, la búsqueda
//! web para el chat, el autocompletado (rellenar al medio si el modelo sabe, si no completar la línea), las
//! instrucciones `Prig//:` dentro del código y detener todo lo que se esté generando.

#![allow(clippy::result_large_err)]

use std::sync::{Arc, Mutex, OnceLock, Weak};

use axum::{
    body::Bytes,
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_ia::generar::{self, PedidoGenerar};
use prig_ia::vivo::Cancelar;
use prig_ia::{motor, ollama, tutor};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn ok(m: Mapa) -> Response {
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

// =========================================================================== lo que se está generando

/// Las generaciones en curso de este servidor: «Detener» las corta todas
fn en_curso() -> &'static Mutex<Vec<Weak<Cancelar>>> {
    static E: OnceLock<Mutex<Vec<Weak<Cancelar>>>> = OnceLock::new();
    E.get_or_init(Default::default)
}

/// Apunta una generación (mientras viva su `Cancelar`)
pub fn apuntar(c: &Arc<Cancelar>) {
    let mut e = en_curso().lock().unwrap_or_else(|x| x.into_inner());
    e.retain(|w| w.strong_count() > 0);
    e.push(Arc::downgrade(c));
}

/// `StreamingResponse(_flujo_cancelable(...), media_type="text/plain; charset=utf-8")`: `trabajo(cancelar, enviar)`
/// en un hilo, cada trozo tal cual. Si quien pregunta se va o pulsa «Detener», se cancela (el modelo deja de generar).
pub fn flujo_de_texto<F>(trabajo: F) -> Response
where
    F: FnOnce(&Cancelar, &mut dyn FnMut(String)) + Send + 'static,
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
    apuntar(&cancelar);
    std::thread::spawn(move || {
        let mut enviar = |t: String| {
            if !t.is_empty() && tx.blocking_send(Ok(Bytes::from(t))).is_err() {
                cancelar.poner();
            }
        };
        trabajo(&cancelar, &mut enviar);
    });
    let flujo = futures_util::stream::unfold((rx, guarda), |(mut rx, g)| async move { rx.recv().await.map(|x| (x, (rx, g))) });
    ([(axum::http::header::CONTENT_TYPE, "text/plain; charset=utf-8")], axum::body::Body::from_stream(flujo)).into_response()
}

/// `POST /api/ai/cancel`: detiene todo lo que se esté generando (aquí y en el backend de Python)
pub async fn cancelar(State(state): State<AppState>) -> Response {
    let mut n = 0usize;
    {
        let mut e = en_curso().lock().unwrap_or_else(|x| x.into_inner());
        for w in e.drain(..) {
            if let Some(c) = w.upgrade() {
                if !c.puesto() {
                    c.poner();
                    n += 1;
                }
            }
        }
    }
    let fallback = state.fallback_url.clone();
    let de_python = tokio::task::spawn_blocking(move || {
        reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .build()
            .ok()?
            .post(format!("{fallback}/api/interno/cancelar"))
            .send()
            .ok()?
            .text()
            .ok()
            .and_then(|t| prig_plataforma::json::leer(&t).ok())
            .and_then(|v| match v {
                Valor::Mapa(m) => m.get("active_requests_cancelled").and_then(Valor::num),
                _ => None,
            })
    })
    .await
    .ok()
    .flatten()
    .unwrap_or(0.0);
    ok(Mapa::new().con("status", "cancelled").con("active_requests_cancelled", n + de_python as usize))
}

// =========================================================================== catálogo

/// `GET /api/ai/catalog`: los modelos que Prig conoce, con lo instalado en Ollama
pub async fn catalogo(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    tokio::task::spawn_blocking(move || {
        let detalle = ollama::modelos_detallados(&raiz);
        let mut tamanos = Mapa::new();
        for m in detalle.lista("models").unwrap_or(&[]) {
            if let Valor::Mapa(m) = m {
                let t = m.get("size_gb").filter(|v| v.verdad()).cloned().unwrap_or(Valor::Entero(0));
                tamanos.poner(m.valor("name").texto_py(), t);
            }
        }
        let modelos = prig_recursos::json::leer(include_str!("../../../prig-ia/src/catalogo_modelos.json"))
            .ok()
            .and_then(|v| if let Valor::Mapa(m) = v { m.mapa("modelos").cloned() } else { None })
            .unwrap_or_default();
        let lista: Vec<Valor> = modelos
            .iter()
            .map(|(nombre, info)| {
                let info = match info {
                    Valor::Mapa(i) => i.clone(),
                    _ => Mapa::new(),
                };
                let latest = format!("{nombre}:latest");
                let instalado = tamanos.contiene(nombre) || tamanos.contiene(&latest);
                let g = |k: &str, d: Valor| info.get(k).cloned().unwrap_or(d);
                let tam = [tamanos.get(nombre), tamanos.get(&latest)]
                    .into_iter()
                    .flatten()
                    .find(|v| v.verdad())
                    .cloned()
                    .unwrap_or_else(|| g("vram_gb", Valor::Entero(0)));
                Valor::Mapa(
                    Mapa::new()
                        .con("name", nombre.as_str())
                        .con("familia", g("familia", Valor::Texto(String::new())))
                        .con("vram_gb", g("vram_gb", Valor::Entero(0)))
                        .con("razona", g("razona", Valor::Entero(0)))
                        .con("piensa", g("piensa", Valor::Texto("no".into())))
                        .con("fuerte_en", g("fuerte_en", Valor::Lista(vec![])))
                        .con("nota", g("nota", Valor::Texto(String::new())))
                        .con("instalado", instalado)
                        .con("size_gb", tam),
                )
            })
            .collect();
        ok(Mapa::new().con("catalog", Valor::Lista(lista)))
    })
    .await
    .unwrap_or_else(|_| error_500())
}

// =========================================================================== búsqueda web

/// `POST /api/ai/search` (`query`)
pub async fn buscar(b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("query", &Tipo::Texto, true)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let consulta = c.valor("query").texto_py();
    tokio::task::spawn_blocking(move || {
        let (contexto, fuentes) = prig_ia::web::contexto_web(&consulta);
        ok(Mapa::new().con("context", contexto).con("sources", fuentes))
    })
    .await
    .unwrap_or_else(|_| error_500())
}

// =========================================================================== autocompletado

/// Un modelo que sabe rellenar al medio: el pedido si sabe; si no, el más pequeño instalado que sepa
fn modelo_que_rellena(pedido: Option<&str>) -> Option<String> {
    if let Some(p) = pedido.filter(|p| generar::capacidades(p).iter().any(|c| c == "insert")) {
        return Some(p.to_string());
    }
    let tags = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .ok()?
        .get(format!("{}/api/tags", ollama::base_url()))
        .send()
        .ok()?
        .text()
        .ok()?;
    let Valor::Mapa(t) = prig_plataforma::json::leer(&tags).ok()? else { return None };
    let mut candidatos: Vec<(f64, String)> = t
        .lista("models")
        .unwrap_or(&[])
        .iter()
        .filter_map(|m| if let Valor::Mapa(m) = m { Some(m.clone()) } else { None })
        .filter_map(|m| {
            let nombre = m.valor("name").texto_py();
            generar::capacidades(&nombre).iter().any(|c| c == "insert").then(|| (m.num_o("size", 0.0), nombre))
        })
        .collect();
    candidatos.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    candidatos.into_iter().next().map(|(_, n)| n)
}

fn ultimos(t: &str, n: usize) -> String {
    let c: Vec<char> = t.chars().collect();
    c[c.len().saturating_sub(n)..].iter().collect()
}

fn primeros(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

/// `POST /api/ai/inline-complete` (`code_prefix`, `code_suffix`, `model`)
pub async fn completar(State(state): State<AppState>, b: Bytes) -> Response {
    let tipo_opc = Tipo::Opcional(&Tipo::Texto);
    let c = match cuerpo::modelo(&b)
        .and_then(|m| cuerpo::tipados(&m, &[("code_prefix", &Tipo::Texto, true), ("code_suffix", &Tipo::Texto, false), ("model", &tipo_opc, false)]))
    {
        Ok(c) => c,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    tokio::task::spawn_blocking(move || {
        let prefijo = c.valor("code_prefix").texto_py();
        let sufijo = c.get("code_suffix").map(Valor::texto_py).unwrap_or_default();
        let pedido = c.get("model").filter(|v| !v.es_nulo()).map(Valor::texto_py).map(|s| s.trim().to_string()).filter(|s| !s.is_empty());
        let elegido = pedido.or_else(|| tutor::modelo_para("autocompletar"));
        // El elegido no sabe rellenar al medio: se respeta la elección y completa la línea
        let fim = match &elegido {
            Some(e) if !generar::capacidades(e).iter().any(|c| c == "insert") => None,
            _ => modelo_que_rellena(elegido.as_deref()),
        };
        if let Some(m) = fim {
            let opc = Mapa::new()
                .con("num_predict", 64)
                .con("temperature", 0.2)
                .con("stop", Valor::Lista(vec![Valor::Texto("\n\n".into())]));
            let mut payload = Mapa::new()
                .con("model", m.as_str())
                .con("prompt", ultimos(&prefijo, 4000))
                .con("suffix", primeros(&sufijo, 2000))
                .con("stream", false)
                .con("options", generar::opciones(Some(&opc), &m, Some("autocompletado"), &raiz));
            let _ = generar::completar_payload(&mut payload, &m, Some("autocompletado"), Some(false), "");
            let r = reqwest::blocking::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .ok()
                .and_then(|cl| {
                    cl.post(format!("{}/api/generate", ollama::base_url()))
                        .header("Content-Type", "application/json")
                        .body(prig_plataforma::json::escribir_compacto(&Valor::Mapa(payload)))
                        .send()
                        .ok()
                });
            let Some(r) = r else { return ok(Mapa::new().con("completion", "")) };
            let estado = r.status().as_u16();
            let texto = r.text().ok().and_then(|t| prig_plataforma::json::leer(&t).ok());
            let Some(texto) = texto else { return ok(Mapa::new().con("completion", "")) };
            let respuesta = match (estado, texto) {
                (200, Valor::Mapa(d)) => d.get("response").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default(),
                _ => String::new(),
            };
            return ok(Mapa::new().con("completion", respuesta.trim_end()).con("modelo", m).con("relleno_al_medio", true));
        }
        let prompt = format!("Completa la siguiente línea de código de forma exacta y concisa:\n```python\n{}", ultimos(&prefijo, 600));
        let sistema = "Eres un motor de autocompletado de código en tiempo real. Devuelve ÚNICAMENTE la sintaxis faltante de la siguiente línea de código sin explicaciones, formato markdown ni intros.";
        let p = PedidoGenerar {
            prompt,
            modelo: elegido.unwrap_or_else(|| "qwen2.5-coder:7b".into()),
            sistema: sistema.into(),
            uso: Some("autocompletado".into()),
            gobernador: true,
            ..Default::default()
        };
        let cancelar = Cancelar::default();
        let mut partes = String::new();
        generar::generar(&raiz, &p, &cancelar, &mut |e| {
            if e.texto("t") == Some("texto") && !cancelar.puesto() {
                partes.push_str(&e.valor("v").texto_py());
                if partes.chars().count() > 100 {
                    cancelar.poner();
                }
            }
        });
        let crudo = partes.trim().replace("```python", "").replace("```", "");
        let linea = crudo.split('\n').next().unwrap_or("").to_string();
        ok(Mapa::new().con("completion", linea))
    })
    .await
    .unwrap_or_else(|_| error_500())
}

// =========================================================================== Prig//:

/// `POST /api/ai/inline-prompt`: una instrucción `Prig//: …` escrita en el código; devuelve el código para esa posición
pub async fn instruccion(State(state): State<AppState>, b: Bytes) -> Response {
    let opc = Tipo::Opcional(&Tipo::Texto);
    let ent = Tipo::Opcional(&Tipo::Entero);
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(
            &m,
            &[
                ("prompt", &Tipo::Texto, true),
                ("file_path", &opc, false),
                ("file_content", &opc, false),
                ("prefix_code", &opc, false),
                ("suffix_code", &opc, false),
                ("line_number", &ent, false),
                ("language", &Tipo::Texto, false),
                ("model", &opc, false),
            ],
        )
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let instruccion = c.valor("prompt").texto_py();
    if instruccion.trim().is_empty() {
        return detalle(StatusCode::BAD_REQUEST, "Debes escribir una instrucción después de 'Prig//: '");
    }
    let raiz = state.base_dir.clone();
    tokio::task::spawn_blocking(move || {
        let texto = |k: &str| c.get(k).filter(|v| v.verdad()).map(Valor::texto_py);
        let linea = match c.get("line_number") {
            None => 1,
            Some(v) => v.num().map(|n| n as i64).filter(|n| *n != 0).unwrap_or(1),
        };
        let mut sangria = String::new();
        let (antes, despues) = if let Some(contenido) = texto("file_content") {
            let lineas = prig_recursos::servidor::lineas_como_python(&contenido).into_iter().map(String::from).collect::<Vec<_>>();
            let i = if lineas.is_empty() { 0 } else { (linea - 1).clamp(0, lineas.len() as i64 - 1) as usize };
            let actual = lineas.get(i).cloned().unwrap_or_default();
            sangria = actual.chars().take_while(|c| c.is_whitespace()).collect();
            let ini = i.saturating_sub(40);
            let fin = (i + 40).min(lineas.len());
            (lineas[ini..i.min(lineas.len())].join("\n"), lineas.get(i + 1..fin).map(|l| l.join("\n")).unwrap_or_default())
        } else {
            let antes = texto("prefix_code").unwrap_or_default();
            if let Some(l) = prig_recursos::servidor::lineas_como_python(&antes).into_iter().map(String::from).collect::<Vec<_>>().iter().rev().find(|l| !l.trim().is_empty()) {
                sangria = l.chars().take_while(|c| c.is_whitespace()).collect();
            }
            (antes, texto("suffix_code").unwrap_or_default())
        };
        let lang = c.get("language").map(Valor::texto_py).unwrap_or_else(|| "python".into());
        let archivo = texto("file_path").unwrap_or_else(|| format!("archivo.{lang}"));
        let sistema = format!(
            "Eres Prig AI, un asistente experto de programación integrado directamente en el editor de código.\n\
             El usuario ha escrito una instrucción en un comentario 'Prig//: ' en el archivo '{archivo}'.\n\
             Tu tarea es generar ÚNICAMENTE el código en {lang} que cumple la instrucción para insertarse en esa posición.\n\
             REGLAS CRÍTICAS:\n\
             1. Devuelve SOLAMENTE el código fuente válido en {lang}.\n\
             2. NO devuelvas explicaciones, texto introductorio ni conclusiones en prosa.\n\
             3. Si usas bloques markdown de código (```), asegúrate de que solo contengan el código solicitado.\n\
             4. Mantén la coherencia con las variables, funciones e importaciones del código circundante.\n\
             5. Ajusta la indentación para que encaje de forma natural en el archivo."
        );
        let prompt = format!(
            "Archivo: {archivo} (Lenguaje: {lang})\n\n--- Código previo a la instrucción ---\n{antes}\n\n--- INSTRUCCIÓN DEL USUARIO ---\n{instruccion}\n\n--- Código posterior a la instrucción ---\n{despues}\n\nGenera el código correspondiente para cumplir la instrucción en esa posición:"
        );
        // El modelo de «código» (o el del tutor); si no está instalado, uno de código que sí lo esté
        let pedido = c.get("model").filter(|v| v.verdad()).map(Valor::texto_py).map(|s| s.trim().to_string()).filter(|s| !s.is_empty());
        let cfg = motor::config_ia();
        let crudo = pedido
            .or_else(|| tutor::modelo_para("codigo"))
            .or_else(|| cfg.get("agent1_model").filter(|v| v.verdad()).map(Valor::texto_py))
            .unwrap_or_else(|| "qwen2.5-coder:7b".into());
        let mut modelo = crudo.split(" (").next().unwrap_or("").trim().to_string();
        let instalados: Option<Vec<String>> = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(2))
            .build()
            .ok()
            .and_then(|cl| cl.get(format!("{}/api/tags", ollama::base_url())).send().ok())
            .filter(|r| r.status().as_u16() == 200)
            .and_then(|r| r.text().ok())
            .and_then(|t| prig_plataforma::json::leer(&t).ok())
            .map(|v| match v {
                Valor::Mapa(m) => m
                    .lista("models")
                    .unwrap_or(&[])
                    .iter()
                    .map(|x| if let Valor::Mapa(x) = x { x.get("name").cloned().unwrap_or(Valor::Nulo).texto_py() } else { String::new() })
                    .collect(),
                _ => Vec::new(),
            });
        if let Some(instalados) = instalados.filter(|l| !l.is_empty()) {
            if !instalados.iter().any(|m| m.contains(&modelo) || modelo.contains(m.as_str())) {
                let codigo = instalados.iter().find(|m| m.contains("coder") || m.contains("code") || m.contains("qwen"));
                modelo = codigo.unwrap_or(&instalados[0]).clone();
            }
        }
        let p = PedidoGenerar { prompt, modelo: modelo.clone(), sistema, uso: Some("programador".into()), gobernador: true, ..Default::default() };
        let mut partes = String::new();
        generar::generar(&raiz, &p, &Cancelar::default(), &mut |e| {
            if e.texto("t") == Some("texto") {
                partes.push_str(&e.valor("v").texto_py());
            }
        });
        let mut codigo = partes.trim().to_string();
        if codigo.starts_with("[Error Ollama:") || codigo.starts_with("[Error:") {
            if codigo.contains("Connection refused") || codigo.contains("Failed to establish a new connection") {
                return detalle(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "Ollama no está en marcha o no responde en el puerto 11434. Inicia Ollama ('ollama serve') para usar el autocompletado con IA.",
                );
            }
            return detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("Error al generar código: {codigo}"));
        }
        // Lo de dentro de un bloque ``` si lo hay
        if codigo.contains("```") {
            let re = regex::Regex::new(r"(?s)```(?:\w+)?\n?(.*?)\n?```").expect("regex");
            codigo = match re.captures(&codigo) {
                Some(m) => m[1].trim().to_string(),
                None => codigo.replace("```", "").trim().to_string(),
            };
        }
        let ajustadas: Vec<String> = prig_recursos::servidor::lineas_como_python(&codigo).into_iter().map(String::from).collect::<Vec<_>>()
            .into_iter()
            .map(|l| {
                if l.trim().is_empty() {
                    String::new()
                } else if !l.starts_with(&sangria) {
                    format!("{sangria}{l}")
                } else {
                    l
                }
            })
            .collect();
        ok(Mapa::new()
            .con("status", "ok")
            .con("code", ajustadas.join("\n"))
            .con("prompt", instruccion.as_str())
            .con("line_number", linea)
            .con("model_used", modelo))
    })
    .await
    .unwrap_or_else(|_| error_500())
}
