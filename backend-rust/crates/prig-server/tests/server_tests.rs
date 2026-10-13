//! Tests del servidor. Todo en carpetas temporales: configuración, espacio de trabajo y bancos (PRIG_BANCOS). El
//! backend de Python es un servidor falso local (`python_falso`) que repite lo que recibe, para probar el proxy de
//! verdad: métodos, cuerpo, cabeceras, espera mientras arranca y WebSocket.

use axum::{
    body::Body,
    extract::{ws::WebSocketUpgrade, Request as AxumRequest},
    http::{header, Request, StatusCode},
    response::{IntoResponse, Response},
    routing::any,
    Router,
};
use futures_util::{SinkExt, StreamExt};
use http_body_util::BodyExt;
use prig_server::{create_app, resolve_project_root, AppState};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::time::Duration;
use tower::ServiceExt;

struct Prueba {
    dir: PathBuf,
    ws: PathBuf,
    config: PathBuf,
}

impl Drop for Prueba {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn carpeta_temporal(nombre: &str) -> PathBuf {
    let nanos = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
    let dir = std::env::temp_dir().join(format!("prig_server_{nombre}_{nanos}_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn escribir(raiz: &Path, rel: &str, texto: &str) {
    let p = raiz.join(rel);
    std::fs::create_dir_all(p.parent().unwrap()).unwrap();
    std::fs::write(p, texto).unwrap();
}

/// Un espacio de trabajo temporal, con su `.prig_config.json` apuntándole (como lo deja Python)
fn prueba(nombre: &str) -> Prueba {
    let dir = carpeta_temporal(nombre);
    let ws = dir.join("proyecto");
    std::fs::create_dir_all(&ws).unwrap();
    let config = dir.join(".prig_config.json");
    std::fs::write(&config, json!({"last_workspace": ws}).to_string()).unwrap();
    Prueba { dir, ws, config }
}

fn app(p: &Prueba, respaldo: &str, plazo: Duration) -> (Router, AppState) {
    let raiz = resolve_project_root();
    let assets = Some(raiz.join("assets")).filter(|a| a.exists());
    let mut state = AppState::con_config(raiz.clone(), raiz.join("frontend"), assets, respaldo.to_string(), p.config.clone());
    state.plazo_respaldo = plazo;
    (create_app(state.clone()), state)
}

async fn pedir(app: &Router, req: Request<Body>) -> (StatusCode, axum::http::HeaderMap, Vec<u8>) {
    let r = app.clone().oneshot(req).await.unwrap();
    let (estado, cabeceras) = (r.status(), r.headers().clone());
    (estado, cabeceras, r.into_body().collect().await.unwrap().to_bytes().to_vec())
}

async fn json_de(app: &Router, req: Request<Body>) -> (StatusCode, Value) {
    let (estado, _, cuerpo) = pedir(app, req).await;
    (estado, serde_json::from_slice(&cuerpo).unwrap_or(Value::Null))
}

fn get(uri: &str) -> Request<Body> {
    Request::builder().uri(uri).body(Body::empty()).unwrap()
}

fn con_json(metodo: &str, uri: &str, cuerpo: Value) -> Request<Body> {
    Request::builder()
        .method(metodo)
        .uri(uri)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(cuerpo.to_string()))
        .unwrap()
}

/// El backend de Python falso: repite método, ruta, consulta, cuerpo y algunas cabeceras; pone dos `set-cookie` y
/// un `access-control-allow-origin` (que el proxy no tiene que reenviar); y `/ws/*` es un eco por WebSocket.
async fn python_falso_en(listener: tokio::net::TcpListener) {
    async fn eco(req: AxumRequest) -> Response {
        let metodo = req.method().to_string();
        let uri = req.uri().to_string();
        let origen = req.headers().get(header::ORIGIN).and_then(|v| v.to_str().ok()).unwrap_or("").to_string();
        let cuerpo = String::from_utf8_lossy(&req.into_body().collect().await.unwrap().to_bytes()).to_string();
        Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, "application/json")
            .header(header::SET_COOKIE, "a=1")
            .header(header::SET_COOKIE, "b=2")
            .header("access-control-allow-origin", "*")
            .body(Body::from(json!({"python": true, "metodo": metodo, "uri": uri, "origen": origen, "cuerpo": cuerpo}).to_string()))
            .unwrap()
    }
    async fn ws_eco(ws: WebSocketUpgrade) -> impl IntoResponse {
        ws.on_upgrade(|mut s| async move {
            while let Some(Ok(m)) = s.recv().await {
                if let axum::extract::ws::Message::Text(t) = m {
                    if s.send(axum::extract::ws::Message::Text(format!("python:{t}"))).await.is_err() {
                        break;
                    }
                }
            }
        })
    }
    let rutas = Router::new().route("/ws/*resto", any(ws_eco)).fallback(eco);
    axum::serve(listener, rutas).await.unwrap();
}

async fn python_falso() -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    tokio::spawn(python_falso_en(listener));
    url
}

/// Un puerto libre (sin nadie escuchando)
async fn puerto_libre() -> u16 {
    let l = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    l.local_addr().unwrap().port()
}

// =========================================================================

#[tokio::test]
async fn test_index_sin_cache() {
    let p = prueba("index");
    let (app, _) = app(&p, "http://127.0.0.1:9", Duration::ZERO);
    let (estado, cabeceras, cuerpo) = pedir(&app, get("/")).await;
    assert_eq!(estado, StatusCode::OK);
    assert_eq!(cabeceras.get(header::CACHE_CONTROL).unwrap(), "no-cache");
    assert!(String::from_utf8_lossy(&cuerpo).contains("Prig"));
    let (estado, _, _) = pedir(&app, get("/static/index.html")).await;
    assert_eq!(estado, StatusCode::OK);
}

#[tokio::test]
async fn test_cors_solo_origenes_locales() {
    let p = prueba("cors");
    let (app, _) = app(&p, "http://127.0.0.1:9", Duration::ZERO);
    let preflight = |origen: &str| {
        Request::builder()
            .method("OPTIONS")
            .uri("/api/file")
            .header(header::ORIGIN, origen)
            .header(header::ACCESS_CONTROL_REQUEST_METHOD, "POST")
            .header(header::ACCESS_CONTROL_REQUEST_HEADERS, "content-type")
            .body(Body::empty())
            .unwrap()
    };
    let (_, cab, _) = pedir(&app, preflight("http://127.0.0.1:8000")).await;
    assert_eq!(cab.get(header::ACCESS_CONTROL_ALLOW_ORIGIN).unwrap(), "http://127.0.0.1:8000");
    let (_, cab, _) = pedir(&app, preflight("https://sitio-malicioso.example")).await;
    assert!(cab.get(header::ACCESS_CONTROL_ALLOW_ORIGIN).is_none(), "una web ajena no puede usar la API local");
}

#[tokio::test]
async fn test_workspace_sigue_a_python() {
    let p = prueba("ws");
    let (app, _) = app(&p, "http://127.0.0.1:9", Duration::ZERO);
    let (_, v) = json_de(&app, get("/api/workspace")).await;
    assert_eq!(v["path"], p.ws.to_string_lossy().as_ref());
    assert_eq!(v["name"], "proyecto");
    // Python abre otra carpeta y la guarda en la configuración: Rust la sigue
    let otra = p.dir.join("otra");
    std::fs::create_dir_all(&otra).unwrap();
    std::thread::sleep(Duration::from_millis(20));
    std::fs::write(&p.config, json!({"last_workspace": otra}).to_string()).unwrap();
    let (_, v) = json_de(&app, get("/api/workspace")).await;
    assert_eq!(v["path"], otra.to_string_lossy().as_ref());
    // Una configuración a medio escribir no cambia nada
    std::thread::sleep(Duration::from_millis(20));
    std::fs::write(&p.config, "{\"last_works").unwrap();
    let (_, v) = json_de(&app, get("/api/workspace")).await;
    assert_eq!(v["path"], otra.to_string_lossy().as_ref());
}

#[tokio::test]
async fn test_arbol_como_python() {
    let p = prueba("arbol");
    escribir(&p.ws, "b.py", "x = 1\n");
    escribir(&p.ws, "A/dentro.py", "y = 2\n");
    escribir(&p.ws, ".oculto", "no\n");
    escribir(&p.ws, ".gitignore", "*.log\n");
    escribir(&p.ws, "target/debug/x", "no\n");
    let (app, _) = app(&p, "http://127.0.0.1:9", Duration::ZERO);
    let (estado, v) = json_de(&app, get("/api/tree")).await;
    assert_eq!(estado, StatusCode::OK);
    let nombres: Vec<&str> = v.as_array().unwrap().iter().map(|n| n["name"].as_str().unwrap()).collect();
    assert_eq!(nombres, vec!["A", ".gitignore", "b.py"], "carpetas primero; sin ocultos ni target");
    let archivo = v.as_array().unwrap().iter().find(|n| n["name"] == "b.py").unwrap();
    assert!(archivo.get("children").unwrap().is_null(), "Python manda \"children\": null en los archivos");
}

#[tokio::test]
async fn test_ide_archivos_y_buscar_como_python() {
    let p = prueba("ide");
    escribir(&p.ws, "src/a.py", "def f( x):\n    return f( 1)\r\nvalor_42 = gf( 2)\n");
    escribir(&p.ws, "src/b.txt", "ruta C:\\temp\\x\nF( \n");
    escribir(&p.ws, "src/bin.dat", "a\0b");
    escribir(&p.ws, "web/app.min.js", "f( 1)\n");
    escribir(&p.ws, "zz.py", "f( 3)\n");
    std::os::unix::fs::symlink(p.ws.join("src"), p.ws.join("enlace")).unwrap();
    let (app, _) = app(&p, "http://127.0.0.1:9", Duration::ZERO);

    // Ir a archivo: orden de os.walk (archivos de la carpeta y después sus subcarpetas) y sin entrar en enlaces
    let (_, v) = json_de(&app, get("/api/ide/archivos")).await;
    let rels: Vec<&str> = v["archivos"].as_array().unwrap().iter().map(|a| a["rel"].as_str().unwrap()).collect();
    assert_eq!(rels, vec!["zz.py", "src/a.py", "src/b.txt", "src/bin.dat", "web/app.min.js"]);

    // Palabra completa como Python ((?<!\w)…(?!\w)): «f(» casa en «f( 1)» pero no en «gf( 2)»; sin distinguir mayúsculas
    let (_, v) = json_de(&app, con_json("POST", "/api/ide/buscar", json!({"consulta": "f(", "palabra": true}))).await;
    assert_eq!(v["total"], 5, "{v}");
    let primero = &v["resultados"][0];
    assert_eq!(primero["rel"], "zz.py");
    // splitlines de Python: \r\n es un solo salto
    let a = v["resultados"].as_array().unwrap().iter().find(|r| r["rel"] == "src/a.py").unwrap();
    let lineas: Vec<i64> = a["coincidencias"].as_array().unwrap().iter().map(|c| c["linea"].as_i64().unwrap()).collect();
    assert_eq!(lineas, vec![1, 2]);
    assert_eq!(a["coincidencias"][1]["col"], 12);
    // Sintaxis de Python y mayúsculas
    let (_, v) = json_de(&app, con_json("POST", "/api/ide/buscar", json!({"consulta": r"valor_\d+", "regex": true, "mayusculas": true}))).await;
    assert_eq!(v["total"], 1);
    // Texto literal con barras invertidas
    let (_, v) = json_de(&app, con_json("POST", "/api/ide/buscar", json!({"consulta": "C:\\temp\\x"}))).await;
    assert_eq!(v["total"], 1);
    // Incluir y excluir (fnmatch)
    let (_, v) = json_de(&app, con_json("POST", "/api/ide/buscar", json!({"consulta": "f(", "incluir": "*.py", "excluir": "src"}))).await;
    assert_eq!(v["archivos"], 1);
    // Expresión inválida: 400 con «detail», como Python
    let (estado, v) = json_de(&app, con_json("POST", "/api/ide/buscar", json!({"consulta": "(", "regex": true}))).await;
    assert_eq!(estado, StatusCode::BAD_REQUEST);
    assert!(v["detail"].as_str().unwrap().starts_with("Expresión regular no válida"));
}

#[tokio::test]
async fn test_proxy_reenvia_lo_que_no_atiende_rust() {
    let p = prueba("proxy");
    let respaldo = python_falso().await;
    let (app, _) = app(&p, &respaldo, Duration::from_secs(5));

    // Antes 405: Rust tenía la ruta con otro método y no la pasaba a Python
    for (metodo, uri) in [
        ("POST", "/api/descargas"),
        ("POST", "/api/flags"),
        ("DELETE", "/api/modelos/parciales"),
        ("POST", "/api/recursos/servidor"),
        ("POST", "/api/workspace/open"),
        ("POST", "/api/workspace"),
        ("POST", "/api/ai/chat"),
    ] {
        let (estado, v) = json_de(&app, con_json(metodo, uri, json!({"x": 1}))).await;
        assert_eq!(estado, StatusCode::OK, "{metodo} {uri}");
        assert_eq!(v["python"], true, "{metodo} {uri} tenía que llegar a Python");
        assert_eq!(v["metodo"], metodo);
        assert_eq!(v["cuerpo"], "{\"x\":1}");
    }
    // Consulta, Origin y cabeceras repetidas; las de CORS de Python no se reenvían
    let req = Request::builder()
        .uri("/api/ai/config?a=1&b=dos")
        .header(header::ORIGIN, "http://127.0.0.1:8000")
        .body(Body::empty())
        .unwrap();
    let (estado, cab, cuerpo) = pedir(&app, req).await;
    assert_eq!(estado, StatusCode::OK);
    let v: Value = serde_json::from_slice(&cuerpo).unwrap();
    assert_eq!(v["uri"], "/api/ai/config?a=1&b=dos");
    assert_eq!(v["origen"], "http://127.0.0.1:8000");
    assert_eq!(cab.get_all(header::SET_COOKIE).iter().count(), 2);
    assert_eq!(cab.get(header::ACCESS_CONTROL_ALLOW_ORIGIN).unwrap(), "http://127.0.0.1:8000", "solo la de Rust");
}

#[tokio::test]
async fn test_proxy_sin_python() {
    let p = prueba("caido");
    let puerto = puerto_libre().await;
    let (app, _) = app(&p, &format!("http://127.0.0.1:{puerto}"), Duration::ZERO);
    let (estado, v) = json_de(&app, get("/api/inicio")).await;
    assert_eq!(estado, StatusCode::BAD_GATEWAY);
    assert_eq!(v["ok"], false);
    assert!(v["detail"].as_str().unwrap().contains("Python"));
    let (_, v) = json_de(&app, get("/api/health")).await;
    assert_eq!(v["status"], "ok");
    assert_eq!(v["respaldo"]["activo"], false);
}

#[tokio::test]
async fn test_proxy_espera_a_que_python_arranque() {
    let p = prueba("espera");
    let puerto = puerto_libre().await;
    let (app, _) = app(&p, &format!("http://127.0.0.1:{puerto}"), Duration::from_secs(10));
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(600)).await;
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", puerto)).await.unwrap();
        python_falso_en(listener).await;
    });
    let inicio = std::time::Instant::now();
    let (estado, v) = json_de(&app, get("/api/inicio")).await;
    assert_eq!(estado, StatusCode::OK);
    assert_eq!(v["python"], true);
    assert!(inicio.elapsed() >= Duration::from_millis(500));
}

#[tokio::test]
async fn test_websocket_pasa_a_python() {
    let p = prueba("websocket");
    let respaldo = python_falso().await;
    let (app, _) = app(&p, &respaldo, Duration::from_secs(5));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let direccion = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let (mut ws, _) = tokio_tungstenite::connect_async(format!("ws://{direccion}/ws/audio_reactivo")).await.unwrap();
    ws.send(tokio_tungstenite::tungstenite::Message::Text("hola".into())).await.unwrap();
    let respuesta = tokio::time::timeout(Duration::from_secs(5), ws.next()).await.unwrap().unwrap().unwrap();
    assert_eq!(respuesta.into_text().unwrap(), "python:hola");
}

#[tokio::test]
async fn test_banco_consultas_de_solo_lectura() {
    let p = prueba("banco");
    std::env::set_var("PRIG_BANCOS", p.dir.join("bancos"));
    escribir(&p.ws, "motor.py", "def calientes(n):\n    return n\n\ndef lanzar():\n    return calientes(2)\n");
    let raiz = p.ws.to_string_lossy().to_string();
    let banco = banco_core::banco::Banco::abrir(&raiz, None, "bge-m3").unwrap();
    banco.sincronizar(false).unwrap();
    let (app, _) = app(&p, "http://127.0.0.1:9", Duration::ZERO);
    let (estado, v) = json_de(&app, get("/api/banco/simbolos?nombre=calientes")).await;
    assert_eq!(estado, StatusCode::OK, "{v}");
    assert_eq!(v["simbolos"][0]["nombre"], "calientes");
    let (estado, v) = json_de(&app, get("/api/banco/ficha?nombre=calientes")).await;
    assert_eq!(estado, StatusCode::OK, "{v}");
    let (_, v) = json_de(&app, get("/api/banco/grafo?s=lanzar")).await;
    assert!(v["hechos"].is_array());
}

#[tokio::test]
async fn test_hardware() {
    let p = prueba("hardware");
    let (app, _) = app(&p, "http://127.0.0.1:9", Duration::ZERO);
    let (estado, v) = json_de(&app, get("/api/hardware")).await;
    assert_eq!(estado, StatusCode::OK);
    assert!(v.get("thermal_zones").is_some());
}

/// Python muere con una conexión del pool abierta y vuelve en el mismo puerto: la petición espera y llega
#[tokio::test]
async fn test_proxy_espera_si_python_se_reinicia() {
    let p = prueba("reinicio");
    let puerto = puerto_libre().await;
    let (app, _) = app(&p, &format!("http://127.0.0.1:{puerto}"), Duration::from_secs(10));
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", puerto)).await.unwrap();
    let python = tokio::spawn(python_falso_en(listener));
    let (estado, _) = json_de(&app, get("/api/inicio")).await;
    assert_eq!(estado, StatusCode::OK);
    // «Python» se cae (la conexión del pool queda apuntando a nadie) y vuelve medio segundo después
    python.abort();
    let _ = python.await;
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(500)).await;
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", puerto)).await.unwrap();
        python_falso_en(listener).await;
    });
    let (estado, v) = json_de(&app, get("/api/inicio")).await;
    assert_eq!(estado, StatusCode::OK, "{v}");
    assert_eq!(v["python"], true);
}
