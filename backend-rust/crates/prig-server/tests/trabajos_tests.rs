//! Qué libros se pueden mandar a extraer, por la ruta (las de `PruebaPermisoDeLibros` de `test_troceado.py`): uno de
//! la carpeta personal sí; lo de fuera, lo que no es un libro y lo que ya no está, no, diciendo por qué.

use axum::{body::Body, http::Request};
use http_body_util::BodyExt;
use prig_server::{create_app, resolve_project_root, AppState};
use serde_json::{json, Value};
use tower::ServiceExt;

#[tokio::test(flavor = "multi_thread")]
async fn que_libros_se_aceptan() {
    let casa = std::env::var("HOME").unwrap();
    let tmp = std::path::Path::new(&casa).join(format!(".prig_pruebas_permiso_{}", std::process::id()));
    std::fs::create_dir_all(&tmp).unwrap();
    let crear = |n: &str| {
        let r = tmp.join(n);
        std::fs::write(&r, "contenido").unwrap();
        r.to_string_lossy().to_string()
    };
    let raiz = resolve_project_root();
    let cfg = tmp.join("config.json");
    std::fs::write(&cfg, json!({"last_workspace": tmp}).to_string()).unwrap();
    let app = create_app(AppState::con_config(raiz.clone(), raiz.join("frontend"), None, "http://127.0.0.1:9".into(), cfg));
    // Todos rechazados: el 400 trae el motivo de cada uno
    let fuera = std::env::temp_dir().join(format!("fuera_{}.pdf", std::process::id()));
    std::fs::write(&fuera, "x").unwrap();
    let libros = json!({"libros": [{"path": fuera}, {"path": crear("programa.sh")}, {"path": tmp.join("fantasma.pdf")}]});
    let req = Request::builder().method("POST").uri("/api/job/prepare").header("content-type", "application/json").body(Body::from(libros.to_string())).unwrap();
    let r = app.clone().oneshot(req).await.unwrap();
    assert_eq!(r.status(), 400);
    let v: Value = serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap();
    let d = v["detail"].as_str().unwrap();
    assert!(d.contains(".pdf: está fuera de tu carpeta personal"), "{d}");
    assert!(d.contains("programa.sh: no es un libro") && d.contains("se admiten"), "{d}");
    assert!(d.contains("fantasma.pdf: el archivo ya no está ahí"), "{d}");
    let _ = std::fs::remove_file(fuera);
    let _ = std::fs::remove_dir_all(tmp);
}
