//! El asistente del editor contra una Ollama falsa (las pruebas de `test_modelos_por_tarea.py` de Python): qué modelo
//! autocompleta (el elegido si sabe rellenar al medio; si no, se respeta y completa la línea; en automático, el más
//! pequeño que rellena) y con qué modelo responde una instrucción `Prig//:` (el de «código»).

use axum::{body::Body, http::Request, Router};
use http_body_util::BodyExt;
use prig_server::{create_app, resolve_project_root, AppState};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard, OnceLock};
use tower::ServiceExt;

/// De una en una: cambian el entorno del proceso (HOME)
fn turno() -> MutexGuard<'static, ()> {
    static T: Mutex<()> = Mutex::new(());
    T.lock().unwrap_or_else(|e| e.into_inner())
}

fn casa() -> &'static PathBuf {
    static C: OnceLock<PathBuf> = OnceLock::new();
    C.get_or_init(|| {
        let c = std::env::temp_dir().join(format!("prig-asistente-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&c);
        std::fs::create_dir_all(c.join("proyecto")).unwrap();
        std::env::set_var("HOME", &c);
        std::env::set_var("PRIG_SIN_MOTOR_SUAVE", "1");
        std::env::set_var("PRIG_SIN_AUTOARRANQUE_OLLAMA", "1");
        c
    })
}

/// Una Ollama falsa: capacidades por modelo, modelos instalados (nombre, tamaño) y lo que se le pidió
struct Falsa {
    pedidos: Arc<Mutex<Vec<(String, Value)>>>,
}

fn falsa(caps: &[(&str, &[&str])], tags: &[(&str, f64)], config: Value) -> Falsa {
    let l = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", l.local_addr().unwrap());
    let caps: HashMap<String, Vec<String>> = caps.iter().map(|(m, c)| (m.to_string(), c.iter().map(|x| x.to_string()).collect())).collect();
    let tags: Vec<Value> = tags.iter().map(|(n, s)| json!({"name": n, "size": s})).collect();
    let pedidos: Arc<Mutex<Vec<(String, Value)>>> = Arc::default();
    let p = pedidos.clone();
    std::thread::spawn(move || {
        for s in l.incoming().flatten() {
            let mut r = BufReader::new(s.try_clone().unwrap());
            let mut primera = String::new();
            let _ = r.read_line(&mut primera);
            let ruta = primera.split_whitespace().nth(1).unwrap_or("").to_string();
            let mut largo = 0usize;
            loop {
                let mut h = String::new();
                if r.read_line(&mut h).is_err() || h.trim().is_empty() {
                    break;
                }
                if let Some(v) = h.to_lowercase().strip_prefix("content-length:") {
                    largo = v.trim().parse().unwrap_or(0);
                }
            }
            let mut cuerpo = vec![0u8; largo];
            let _ = r.read_exact(&mut cuerpo);
            let pedido: Value = serde_json::from_slice(&cuerpo).unwrap_or(Value::Null);
            let texto = match ruta.as_str() {
                "/api/show" => {
                    let m = pedido["model"].as_str().unwrap_or("");
                    json!({"capabilities": caps.get(m).cloned().unwrap_or_default()}).to_string()
                }
                "/api/tags" => json!({"models": tags}).to_string(),
                "/api/ps" => json!({"models": []}).to_string(),
                "/api/generate" | "/api/chat" => {
                    p.lock().unwrap().push((ruta.clone(), pedido.clone()));
                    if pedido["stream"] == json!(false) {
                        json!({"response": "return a + b", "done": true}).to_string()
                    } else {
                        let msg = |t: &str| if ruta == "/api/chat" { json!({"message": {"content": t}}) } else { json!({"response": t}) };
                        let mut fin = msg("");
                        fin["done"] = json!(true);
                        format!("{}\n{}\n", msg("b)"), fin)
                    }
                }
                _ => "{}".into(),
            };
            let mut s = s;
            let _ = write!(s, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{texto}", texto.len());
        }
    });
    let c = casa();
    let mut cfg = config;
    cfg["ollama_url"] = json!(url);
    std::fs::write(c.join(".prig_ai_config.json"), cfg.to_string()).unwrap();
    std::fs::write(c.join(".prig_recursos.json"), r#"{"version": 1, "frio": {"activo": false}}"#).unwrap();
    Falsa { pedidos }
}

fn app() -> Router {
    let raiz = resolve_project_root();
    let cfg = casa().join(".prig_config.json");
    std::fs::write(&cfg, json!({"last_workspace": casa().join("proyecto")}).to_string()).unwrap();
    create_app(AppState::con_config(raiz.clone(), raiz.join("frontend"), None, "http://127.0.0.1:9".into(), cfg))
}

async fn post(app: &Router, uri: &str, cuerpo: Value) -> Value {
    let req = Request::builder().method("POST").uri(uri).header("content-type", "application/json").body(Body::from(cuerpo.to_string())).unwrap();
    let r = app.clone().oneshot(req).await.unwrap();
    serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap_or(Value::Null)
}

#[tokio::test(flavor = "multi_thread")]
async fn el_elegido_que_rellena_al_medio() {
    let _t = turno();
    let f = falsa(&[("chico:1.5b", &["completion", "insert"])], &[("chico:1.5b", 1e9)], json!({"modelo_autocompletar": "chico:1.5b"}));
    let r = post(&app(), "/api/ai/inline-complete", json!({"code_prefix": "def f(a, b):\n    ", "code_suffix": "\n"})).await;
    assert_eq!((r["modelo"].as_str(), r["relleno_al_medio"].as_bool(), r["completion"].as_str()), (Some("chico:1.5b"), Some(true), Some("return a + b")));
    let p = f.pedidos.lock().unwrap().clone();
    assert_eq!(p[0].1["model"], json!("chico:1.5b"));
    assert!(p[0].1.get("suffix").is_some());
}

#[tokio::test(flavor = "multi_thread")]
async fn el_elegido_sin_insert_se_respeta() {
    let _t = turno();
    let f = falsa(
        &[("charla:8b", &["completion"]), ("chico:1.5b", &["insert"])],
        &[("charla:8b", 5e9), ("chico:1.5b", 1e9)],
        json!({"modelo_autocompletar": "charla:8b"}),
    );
    let r = post(&app(), "/api/ai/inline-complete", json!({"code_prefix": "print(a, "})).await;
    assert_eq!(r["completion"], json!("b)"));
    let p = f.pedidos.lock().unwrap().clone();
    assert!(p.iter().all(|(_, x)| x["model"] == json!("charla:8b"))); // no se cambia en silencio por otro
    assert!(p.iter().all(|(_, x)| x["stream"] != json!(false)));
}

#[tokio::test(flavor = "multi_thread")]
async fn en_automatico_el_mas_pequeno_que_rellena() {
    let _t = turno();
    let f = falsa(
        &[("grande:14b", &["insert"]), ("chico:1.5b", &["insert"]), ("medio:7b", &["completion"])],
        &[("grande:14b", 9e9), ("chico:1.5b", 1e9), ("medio:7b", 4e9)],
        json!({}),
    );
    let r = post(&app(), "/api/ai/inline-complete", json!({"code_prefix": "x = "})).await;
    assert_eq!(r["modelo"], json!("chico:1.5b"));
    assert_eq!(f.pedidos.lock().unwrap()[0].1["model"], json!("chico:1.5b"));
}

#[tokio::test(flavor = "multi_thread")]
async fn prig_usa_el_modelo_de_codigo() {
    let _t = turno();
    let f = falsa(&[("codigo:7b", &["completion"])], &[("codigo:7b", 4e9), ("qwen2.5-coder:7b", 4e9)], json!({"modelo_codigo": "codigo:7b"}));
    let r = post(&app(), "/api/ai/inline-prompt", json!({"prompt": "suma", "prefix_code": "def f():\n    x = 1\n"})).await;
    assert_eq!((r["status"].as_str(), r["model_used"].as_str()), (Some("ok"), Some("codigo:7b")));
    assert_eq!(r["code"], json!("    b)")); // con la sangría del código de alrededor
    assert_eq!(f.pedidos.lock().unwrap()[0].1["model"], json!("codigo:7b"));
}
