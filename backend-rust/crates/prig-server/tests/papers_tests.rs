//! Los papers seminales de ML por el router (las pruebas de `PapersService` de `test_algoritmos_ml.py`): las 21
//! monografías, buscar por concepto y por categoría, leer una y guardarla en el proyecto.

use axum::{body::Body, http::Request, Router};
use http_body_util::BodyExt;
use prig_server::{create_app, resolve_project_root, AppState};
use serde_json::{json, Value};
use tower::ServiceExt;

fn app() -> Router {
    let raiz = resolve_project_root();
    let casa = std::env::temp_dir().join(format!("prig-papers-{}", std::process::id()));
    std::fs::create_dir_all(&casa).unwrap();
    let cfg = casa.join(".prig_config.json");
    std::fs::write(&cfg, json!({"last_workspace": casa}).to_string()).unwrap();
    create_app(AppState::con_config(raiz.clone(), raiz.join("frontend"), None, "http://127.0.0.1:9".into(), cfg))
}

async fn pedir(app: &Router, req: Request<Body>) -> Value {
    let r = app.clone().oneshot(req).await.unwrap();
    serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap()
}

async fn get(app: &Router, uri: &str) -> Value {
    pedir(app, Request::builder().uri(uri).body(Body::empty()).unwrap()).await
}

fn ids(v: &Value) -> Vec<String> {
    v["papers"].as_array().unwrap().iter().map(|p| p["id"].as_str().unwrap().to_string()).collect()
}

#[tokio::test]
async fn listar_buscar_y_leer() {
    let app = app();
    assert_eq!(ids(&get(&app, "/api/papers/list").await).len(), 21);
    assert!(ids(&get(&app, "/api/papers/list?q=RoPE").await).iter().any(|i| i.contains("transformer")));
    assert!(ids(&get(&app, "/api/papers/list?q=GOSS").await).iter().any(|i| i.contains("lightgbm")));
    assert!(ids(&get(&app, "/api/papers/list?categoria=Deep%20Learning").await).len() >= 4);
    let doc = get(&app, "/api/papers/detail?id=20_transformer_y_atencion&tipo=analisis").await;
    assert_eq!(doc["success"], true);
    assert!(doc["tamano_bytes"].as_i64().unwrap() > 20000);
    assert!(doc["contenido"].as_str().unwrap().contains("Vaswani"));
}

#[tokio::test]
async fn guardar_en_el_proyecto() {
    let app = app();
    let destino = std::env::temp_dir().join(format!("prig-papers-ws-{}", std::process::id()));
    let cuerpo = json!({"paper_id": "20_transformer_y_atencion", "tipo": "analisis", "workspace_path": destino});
    let r = pedir(
        &app,
        Request::builder().method("POST").uri("/api/papers/download").header("content-type", "application/json").body(Body::from(cuerpo.to_string())).unwrap(),
    )
    .await;
    assert_eq!(r["success"], true);
    assert!(std::path::Path::new(r["saved_to"].as_str().unwrap()).is_file());
    assert!(r["bytes"].as_i64().unwrap() > 20000);
    let _ = std::fs::remove_dir_all(destino);
}
