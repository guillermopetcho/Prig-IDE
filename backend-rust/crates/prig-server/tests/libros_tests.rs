//! Leer y anotar la biblioteca por el router (las pruebas de `BookService` de `test_citas_diagramas.py`,
//! `test_proyectos_biblioteca.py` y `test_datos_usuario.py`): citas de un libro (crear, ordenar, buscar para el chat,
//! exportar, borrar), corregir una página de un PDF, el resumen de un proyecto y no salir de la biblioteca. Con una
//! biblioteca temporal (`PRIG_BOOKS_DIR`) y PDFium de `lib/pdfium`.

use axum::{body::Body, http::Request, Router};
use http_body_util::BodyExt;
use prig_server::{create_app, resolve_project_root, AppState};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};
use tower::ServiceExt;

/// De una en una: cambian `PRIG_BOOKS_DIR`
fn turno() -> MutexGuard<'static, ()> {
    static T: Mutex<()> = Mutex::new(());
    T.lock().unwrap_or_else(|e| e.into_inner())
}

fn carpeta(nombre: &str) -> PathBuf {
    let c = std::env::temp_dir().join(format!("prig-libros-{nombre}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&c);
    for d in ["libros/books", "libros/citas/ediciones", "libros/metadata", "ws"] {
        std::fs::create_dir_all(c.join(d)).unwrap();
    }
    std::env::set_var("PRIG_BOOKS_DIR", c.join("libros"));
    c
}

fn app(c: &Path) -> Router {
    let raiz = resolve_project_root();
    let cfg = c.join(".prig_config.json");
    std::fs::write(&cfg, json!({"last_workspace": c.join("ws"), "saved_projects": [{"path": c.join("proyecto"), "name": "P"}]}).to_string()).unwrap();
    create_app(AppState::con_config(raiz.clone(), raiz.join("frontend"), None, "http://127.0.0.1:9".into(), cfg))
}

async fn pedir(app: &Router, metodo: &str, uri: &str, cuerpo: Option<Value>) -> (u16, Value) {
    let b = Request::builder().method(metodo).uri(uri).header("content-type", "application/json");
    let req = b.body(cuerpo.map(|c| Body::from(c.to_string())).unwrap_or_else(Body::empty)).unwrap();
    let r = app.clone().oneshot(req).await.unwrap();
    let estado = r.status().as_u16();
    (estado, serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap_or(Value::Null))
}

/// Un PDF de verdad hecho a mano: una página por texto (Helvetica)
fn pdf_minimo(paginas: &[&str]) -> Vec<u8> {
    let mut objs: Vec<Vec<u8>> = vec![b"<< /Type /Catalog /Pages 2 0 R >>".to_vec(), Vec::new(), b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>".to_vec()];
    let mut hijos = Vec::new();
    for t in paginas {
        let flujo = format!("BT /F1 14 Tf 20 150 Td ({t}) Tj ET");
        objs.push(format!("<< /Length {} >>\nstream\n{flujo}\nendstream", flujo.len()).into_bytes());
        objs.push(format!("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] /Contents {} 0 R /Resources << /Font << /F1 3 0 R >> >> >>", objs.len()).into_bytes());
        hijos.push(format!("{} 0 R", objs.len()));
    }
    objs[1] = format!("<< /Type /Pages /Kids [{}] /Count {} >>", hijos.join(" "), paginas.len()).into_bytes();
    let mut s = b"%PDF-1.4\n".to_vec();
    let mut offs = Vec::new();
    for (i, o) in objs.iter().enumerate() {
        offs.push(s.len());
        s.extend(format!("{} 0 obj\n", i + 1).bytes());
        s.extend(o);
        s.extend(b"\nendobj\n");
    }
    let xref = s.len();
    s.extend(format!("xref\n0 {}\n0000000000 65535 f \n", objs.len() + 1).bytes());
    for o in offs {
        s.extend(format!("{o:010} 00000 n \n").bytes());
    }
    s.extend(format!("trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n", objs.len() + 1).bytes());
    s
}

#[tokio::test(flavor = "multi_thread")]
async fn citas_de_un_libro() {
    let _t = turno();
    let c = carpeta("citas");
    let app = app(&c);
    let libro = "deep_learning_goodfellow.pdf";
    let (_, v) = pedir(&app, "GET", &format!("/api/books/citations?id={libro}"), None).await;
    assert_eq!((v["libro"].as_str(), v["citas"].as_array().map(Vec::len)), (Some(libro), Some(0)));

    let guardar = |cita: Value| pedir(&app, "POST", "/api/books/citations/save", Some(json!({"book_id": libro, "citation": cita})));
    let (_, r1) = guardar(json!({"pagina": 42, "capitulo": "Cap 4", "texto": "El descenso de gradiente converge.", "tags": ["gradiente"]})).await;
    let (_, r2) = guardar(json!({"pagina": 15, "texto": "Un escalar es un único número.", "nota": " tensores ", "tags": "álgebra, tensores"})).await;
    assert_eq!(r1["ok"], true);
    let (c42, c15) = (r1["cita"]["id"].as_str().unwrap().to_string(), r2["cita"]["id"].as_str().unwrap().to_string());
    assert_eq!(r2["cita"]["nota"], "tensores");
    assert_eq!(r2["cita"]["tags"], json!(["álgebra", "tensores"]));

    // en el archivo, ordenadas por página
    let archivo = c.join("libros/citas/deep_learning_goodfellow.json");
    let d: Value = serde_json::from_str(&std::fs::read_to_string(&archivo).unwrap()).unwrap();
    assert_eq!(d["citas"].as_array().unwrap().iter().map(|x| x["pagina"].as_i64().unwrap()).collect::<Vec<_>>(), vec![15, 42]);
    assert_eq!(d["total_citas"], 2);

    let (_, chat) = pedir(&app, "GET", "/api/books/all-citations?query=gradiente", None).await;
    assert_eq!(chat.as_array().unwrap().len(), 1);
    assert_eq!(chat[0]["id"], c42.as_str());

    let (_, e) = pedir(&app, "POST", "/api/books/citations/export", Some(json!({"book_id": libro}))).await;
    assert_eq!(e["ok"], true);
    assert!(c.join("ws/deep_learning_goodfellow.json").is_file());

    let (_, b) = pedir(&app, "POST", "/api/books/citations/delete", Some(json!({"book_id": libro, "citation_id": c15}))).await;
    assert_eq!(b["total_citas"], 1);
    let (estado, _) = pedir(&app, "POST", "/api/books/citations/delete", Some(json!({"book_id": libro, "citation_id": c15}))).await;
    assert_eq!(estado, 400);
    let _ = std::fs::remove_dir_all(c);
}

#[tokio::test(flavor = "multi_thread")]
async fn corregir_una_pagina_y_buscar() {
    let _t = turno();
    let c = carpeta("pdf");
    let app = app(&c);
    std::fs::write(c.join("libros/books/matematicas_ml.pdf"), pdf_minimo(&["uno", "dos con gradiente", "tres", "cuatro", "cinco"])).unwrap();
    let (_, r) = pedir(&app, "POST", "/api/books/pdf-page-save", Some(json!({"book_id": "matematicas_ml.pdf", "page": 3, "text": "E = mc^2"}))).await;
    assert_eq!(r["ok"], true);
    let (_, p) = pedir(&app, "GET", "/api/books/pdf-pages?id=matematicas_ml.pdf&page=3&search=GRADIENTE", None).await;
    assert_eq!((p["current_page"].as_i64(), p["total_pages"].as_i64(), p["has_edit"].as_bool()), (Some(3), Some(5), Some(true)));
    assert_eq!(p["page_text"], "E = mc^2");
    assert_eq!(p["search_matches"][0]["page"], 2);
    let (_, p) = pedir(&app, "GET", "/api/books/pdf-pages?id=matematicas_ml.pdf&page=99", None).await;
    assert_eq!((p["current_page"].as_i64(), p["page_text"].as_str()), (Some(5), Some("cinco")));
    let _ = std::fs::remove_dir_all(c);
}

#[tokio::test(flavor = "multi_thread")]
async fn un_proyecto_y_no_salir_de_la_biblioteca() {
    let _t = turno();
    let c = carpeta("proyecto");
    std::fs::create_dir_all(c.join("proyecto/src")).unwrap();
    std::fs::write(c.join("proyecto/main.py"), "print(1)").unwrap();
    std::fs::write(c.join("proyecto/src/util.py"), "x = 1").unwrap();
    std::fs::create_dir_all(c.join("proyecto/.git")).unwrap();
    let app = app(&c);
    let (_, v) = pedir(&app, "GET", &format!("/api/books/read?id={}", c.join("proyecto").display()), None).await;
    assert_eq!((v["type"].as_str(), v["is_project"].as_bool()), (Some("project"), Some(true)));
    assert_eq!((v["files_count"].as_i64(), v["dirs_count"].as_i64()), (Some(2), Some(1)));
    assert!(v["sample_files"].as_array().unwrap().iter().any(|s| s == "main.py"));

    let fuera = c.join("secreto.txt");
    std::fs::write(&fuera, "privado").unwrap();
    let (_, v) = pedir(&app, "GET", &format!("/api/books/read?id={}", fuera.display()), None).await;
    assert!(v["error"].is_string());
    let (_, v) = pedir(&app, "GET", "/api/books/pdf-pages?id=../secreto.txt", None).await;
    assert!(v["detail"].as_str().unwrap().contains("no encontrado"));
    let _ = std::fs::remove_dir_all(c);
}
