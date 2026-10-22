//! El estudio SQL por el router (las de `test_sql_studio.py`): crear una base, sembrar los datos de ejemplo, listar
//! tablas, el esquema, consultar y el dialecto de MySQL (`SHOW TABLES`, `DESCRIBE`).

use axum::{body::Body, http::Request, Router};
use http_body_util::BodyExt;
use prig_server::{create_app, resolve_project_root, AppState};
use serde_json::{json, Value};
use tower::ServiceExt;

async fn pedir(app: &Router, metodo: &str, uri: &str, cuerpo: Option<Value>) -> Value {
    let req = Request::builder().method(metodo).uri(uri).header("content-type", "application/json").body(cuerpo.map(|c| Body::from(c.to_string())).unwrap_or_else(Body::empty)).unwrap();
    let r = app.clone().oneshot(req).await.unwrap();
    assert_eq!(r.status(), 200, "{metodo} {uri}");
    serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap()
}

#[tokio::test(flavor = "multi_thread")]
async fn estudio_sql() {
    let raiz = resolve_project_root();
    let casa = std::env::temp_dir().join(format!("prig-sql-{}", std::process::id()));
    std::fs::create_dir_all(&casa).unwrap();
    let cfg = casa.join("config.json");
    std::fs::write(&cfg, json!({"last_workspace": casa}).to_string()).unwrap();
    let app = create_app(AppState::con_config(raiz.clone(), raiz.join("frontend"), None, "http://127.0.0.1:9".into(), cfg));
    let db = format!("prueba_sql_{}", std::process::id());

    let v = pedir(&app, "GET", "/api/sql/databases", None).await;
    assert!(v["success"].as_bool().unwrap() && v["databases"].is_array());
    let v = pedir(&app, "POST", "/api/sql/databases/create", Some(json!({"nombre": db}))).await;
    assert_eq!((v["success"].as_bool(), v["nombre"].as_str()), (Some(true), Some(db.as_str())));
    assert_eq!(pedir(&app, "POST", "/api/sql/seed", Some(json!({"db": db, "sql": ""}))).await["success"], true);
    let v = pedir(&app, "GET", &format!("/api/sql/tables?db={db}"), None).await;
    let tablas: Vec<&str> = v["tables"].as_array().unwrap().iter().map(|t| t["nombre"].as_str().unwrap()).collect();
    for t in ["usuarios", "productos", "pedidos", "metricas_ia", "logs_actividad"] {
        assert!(tablas.contains(&t), "falta {t}");
    }
    let v = pedir(&app, "GET", &format!("/api/sql/schema?db={db}&table=usuarios"), None).await;
    let campos: Vec<&str> = v["columns"].as_array().unwrap().iter().map(|c| c["campo"].as_str().unwrap()).collect();
    assert!(v["table"] == "usuarios" && ["id", "username", "email"].iter().all(|c| campos.contains(c)));
    let v = pedir(&app, "POST", "/api/sql/query", Some(json!({"db": db, "sql": "SELECT id, username, rol FROM usuarios WHERE activo = 1 ORDER BY id ASC;"}))).await;
    assert_eq!(v["columns"], json!(["id", "username", "rol"]));
    assert!(!v["rows"].as_array().unwrap().is_empty());
    let v = pedir(&app, "POST", "/api/sql/query", Some(json!({"db": db, "sql": "SHOW TABLES"}))).await;
    assert!(v["columns"].as_array().unwrap().iter().any(|c| c == &json!(format!("Tables_in_{db}"))));
    let v = pedir(&app, "POST", "/api/sql/query", Some(json!({"db": db, "sql": "DESCRIBE productos"}))).await;
    assert!(v["columns"].as_array().unwrap().iter().any(|c| c == "Field"));
    let _ = std::fs::remove_file(format!(".prig_sql/{db}.db"));
    let _ = std::fs::remove_dir_all(casa);
}
