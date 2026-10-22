//! El analista de librerías por el router (las pruebas de `LibreriasService` de `test_citas_diagramas.py`): la lista
//! con las de serie y las propias, las citas de muestra, dar de alta un repositorio, guardar, exportar y borrar
//! citas, y reunirlas para el chat. Con una carpeta de libros temporal (`PRIG_BOOKS_DIR`).

use axum::{body::Body, http::Request, Router};
use http_body_util::BodyExt;
use prig_server::{create_app, resolve_project_root, AppState};
use serde_json::{json, Value};
use std::path::PathBuf;
use tower::ServiceExt;

fn carpeta() -> PathBuf {
    let c = std::env::temp_dir().join(format!("prig-librerias-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&c);
    std::fs::create_dir_all(c.join("ws")).unwrap();
    std::env::set_var("PRIG_BOOKS_DIR", c.join("libros"));
    c
}

fn app(c: &std::path::Path) -> Router {
    let raiz = resolve_project_root();
    let cfg = c.join(".prig_config.json");
    std::fs::write(&cfg, json!({"last_workspace": c.join("ws")}).to_string()).unwrap();
    create_app(AppState::con_config(raiz.clone(), raiz.join("frontend"), None, "http://127.0.0.1:9".into(), cfg))
}

async fn pedir(app: &Router, metodo: &str, uri: &str, cuerpo: Option<Value>) -> (u16, Value) {
    let b = Request::builder().method(metodo).uri(uri).header("content-type", "application/json");
    let req = b.body(cuerpo.map(|c| Body::from(c.to_string())).unwrap_or_else(Body::empty)).unwrap();
    let r = app.clone().oneshot(req).await.unwrap();
    let estado = r.status().as_u16();
    (estado, serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap_or(Value::Null))
}

fn ids(v: &Value) -> Vec<String> {
    v.as_array().unwrap().iter().map(|l| l["id"].as_str().unwrap().to_string()).collect()
}

#[tokio::test]
async fn de_serie_propias_y_citas() {
    let c = carpeta();
    let app = app(&c);
    let (_, libs) = pedir(&app, "GET", "/api/librerias/list", None).await;
    for id in ["numpy", "matplotlib", "pytorch", "scikit-learn"] {
        assert!(ids(&libs).contains(&id.to_string()), "falta {id}");
    }
    let (_, np) = pedir(&app, "GET", "/api/librerias/citations?id=numpy", None).await;
    assert_eq!(np["libreria"], "numpy");
    assert!(!np["citas"].as_array().unwrap().is_empty());

    let (estado, alta) = pedir(&app, "POST", "/api/librerias/add", Some(json!({"repo": "optuna/optuna", "name": "optuna", "desc": "hiperparámetros"}))).await;
    assert_eq!((estado, alta["ok"].clone()), (200, json!(true)));
    let (_, libs) = pedir(&app, "GET", "/api/librerias/list", None).await;
    assert!(ids(&libs).contains(&"optuna".to_string()));

    let cita = json!({"tema": "study.optimize", "funcion_o_clase": "optuna.create_study", "explicacion": "Crea un estudio.",
        "codigo_ejemplo": "study = optuna.create_study()", "tags": ["optuna", "tpe"]});
    let (_, g) = pedir(&app, "POST", "/api/librerias/citations/save", Some(json!({"lib_id": "optuna", "citation": cita}))).await;
    assert_eq!(g["ok"], true);
    assert_eq!(g["cita"]["funcion"], "optuna.create_study");
    let cid = g["cita"]["id"].as_str().unwrap().to_string();
    assert!(cid.starts_with("lib_cita_"));
    assert!(c.join("libros/librerias/optuna.json").is_file());

    let (_, e) = pedir(&app, "POST", "/api/librerias/citations/export", Some(json!({"lib_id": "optuna"}))).await;
    assert_eq!(e["ok"], true);
    assert!(c.join("ws/optuna.json").is_file());

    let (_, todas) = pedir(&app, "GET", "/api/librerias/all-citations?query=optuna%20estudio", None).await;
    assert_eq!(todas[0]["funcion"], "optuna.create_study");
    assert_eq!(todas[0]["_score"], 2);

    let (_, b) = pedir(&app, "POST", "/api/librerias/citations/delete", Some(json!({"lib_id": "optuna", "citation_id": cid}))).await;
    assert_eq!(b["ok"], true);
    let (_, o) = pedir(&app, "GET", "/api/librerias/citations?id=optuna", None).await;
    assert_eq!(o["citas"], json!([]));
    let (estado, _) = pedir(&app, "POST", "/api/librerias/citations/delete", Some(json!({"lib_id": "optuna", "citation_id": cid}))).await;
    assert_eq!(estado, 400);
    let _ = std::fs::remove_dir_all(c);
}
