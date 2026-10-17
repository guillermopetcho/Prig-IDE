//! Desafíos de solo lectura, con la lógica de `prig_aprendizaje` (la misma que usa `desafios/almacen.py`):
//! `GET /api/desafios`. Crear, comprobar, el tutor y lo demás lo atiende Python por el proxy.

use axum::{
    extract::{Path as Ruta, Request, State},
    http::StatusCode,
    response::Response,
};
use crate::state::AppState;
use prig_aprendizaje::desafios::{self as d, ErrorObtener};
use prig_plataforma::valor::{Mapa, Valor};
use std::path::PathBuf;

use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{detalle, json_py};

/// `almacen.carpeta_base()`: PRIG_DESAFIOS_DIR, o ~/.prig_desafios, o la carpeta temporal si no se puede crear
pub fn carpeta_base() -> PathBuf {
    if let Some(d) = std::env::var_os("PRIG_DESAFIOS_DIR").filter(|d| !d.is_empty()) {
        return PathBuf::from(d);
    }
    let casa = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"));
    let d = casa.join(".prig_desafios");
    if std::fs::create_dir_all(&d).is_ok() {
        d
    } else {
        std::env::temp_dir().join("prig_desafios")
    }
}

pub async fn desafios_lista() -> Response {
    let dir = carpeta_base().join("desafios");
    match tokio::task::spawn_blocking(move || prig_aprendizaje::desafios::lista(&dir)).await {
        Ok(Ok(filas)) => json_py(
            StatusCode::OK,
            &Valor::Mapa(Mapa::new().con("desafios", Valor::Lista(filas.into_iter().map(Valor::Mapa).collect()))),
        ),
        Ok(Err(e)) => detalle(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()),
        Err(e) => detalle(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()),
    }
}

/// `GET /api/desafios/{id_}`: la vista pública (sin pruebas ocultas ni solución). ErrorDesafio → 400. Lo que no
/// tiene forma de id (`/api/desafios/fuentes` y las demás rutas de un segmento) sigue a Python por el proxy.
pub async fn desafios_obtener(State(state): State<AppState>, Ruta(id): Ruta<String>, req: Request) -> Response {
    if !d::id_valido(&id) {
        return crate::routes::proxy::proxy_fallback(State(state), req).await;
    }
    let dir = carpeta_base().join("desafios");
    match tokio::task::spawn_blocking(move || d::obtener(&dir, &id)).await {
        Ok(Ok(Valor::Mapa(m))) => json_py(StatusCode::OK, &Valor::Mapa(d::publico(&m))),
        Ok(Err(ErrorObtener::Desafio(t))) => detalle(StatusCode::BAD_REQUEST, t),
        _ => error_500(),
    }
}

/// `GET /api/progreso/analisis`: el último análisis guardado, o null
pub async fn progreso_analisis() -> Response {
    let ruta = carpeta_base().join("analisis.json");
    let v = tokio::task::spawn_blocking(move || d::leer_json(&ruta)).await.ok().flatten().unwrap_or(Valor::Nulo);
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("analisis", v)))
}

/// `GET /api/github/guardados`: los repositorios guardados (`[]` si no hay o el archivo está roto)
pub async fn github_guardados() -> Response {
    let carpeta = std::env::var_os("PRIG_GITHUB_DIR")
        .filter(|d| !d.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(prig_plataforma::py::expanduser("~/.prig_github")));
    let ruta = carpeta.join("guardados.json");
    let v = tokio::task::spawn_blocking(move || d::leer_json(&ruta)).await.ok().flatten();
    // `_leer_json(...) or []`: lo falso (null, [], {}, "", 0) también da []
    let v = match v {
        Some(x) if x.verdad() => x,
        _ => Valor::Lista(Vec::new()),
    };
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("repos", v)))
}

pub(crate) fn error_500() -> Response {
    use axum::response::IntoResponse;
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

// ---------------------------------------------------------------------------------------------- escribir

use axum::body::Bytes;
use crate::routes::cuerpo;

pub(crate) fn error_obtener(e: ErrorObtener) -> Response {
    match e {
        ErrorObtener::Desafio(t) => detalle(StatusCode::BAD_REQUEST, t),
        ErrorObtener::Otro(_) => error_500(),
    }
}

pub(crate) fn mapa_de(v: Option<&Valor>) -> Mapa {
    match v {
        Some(Valor::Mapa(m)) => m.clone(),
        _ => Mapa::new(),
    }
}

/// `DELETE /api/desafios/{id_}`: 400 si no existe; si no, `{"borrado": true}`
pub async fn desafios_borrar(State(state): State<AppState>, Ruta(id): Ruta<String>, req: Request) -> Response {
    if !d::id_valido(&id) {
        return crate::routes::proxy::proxy_fallback(State(state), req).await;
    }
    let base = carpeta_base();
    let r = tokio::task::spawn_blocking(move || {
        d::obtener(&base.join("desafios"), &id)?;
        d::borrar(&base, &id)
    })
    .await;
    match r {
        Ok(Ok(b)) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("borrado", b))),
        Ok(Err(e)) => error_obtener(e),
        Err(_) => error_500(),
    }
}

/// `PUT /api/desafios/{id_}/paginas`: el guardado automático del trabajo del alumno
pub async fn desafios_guardar_paginas(Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let paginas = c.lista_de_dicts("paginas");
    if let Err(r) = c.fin() {
        return r;
    }
    let paginas = match d::validar_paginas(&paginas, false) {
        Ok(p) => p,
        Err(t) => return detalle(StatusCode::BAD_REQUEST, t),
    };
    let base = carpeta_base();
    let r = tokio::task::spawn_blocking(move || {
        d::modificar(&base, &id, |des| {
            // las páginas de solo lectura del desafío no las cambia el alumno
            let solo_lectura: Vec<(String, Valor)> = match des.get("paginas") {
                Some(Valor::Lista(l)) => l
                    .iter()
                    .filter_map(|p| match p {
                        Valor::Mapa(pm) if pm.verdad("solo_lectura") => {
                            Some((pm.texto("nombre").unwrap_or_default().to_string(), p.clone()))
                        }
                        _ => None,
                    })
                    .collect(),
                _ => Vec::new(),
            };
            let usuario: Vec<Valor> = paginas
                .iter()
                .map(|p| {
                    let nombre = p.texto("nombre").unwrap_or_default().to_string();
                    // {nombre: p} se queda con la última página de solo lectura de ese nombre
                    match solo_lectura.iter().rev().find(|(n, _)| *n == nombre) {
                        Some((_, v)) => v.clone(),
                        None => Valor::Mapa(
                            Mapa::new()
                                .con("nombre", nombre)
                                .con("contenido", p.valor("contenido").clone())
                                .con("descripcion", p.get("descripcion").cloned().unwrap_or(Valor::Texto(String::new()))),
                        ),
                    }
                })
                .collect();
            des.poner("paginas_usuario", Valor::Lista(usuario));
            d::empezar(des);
            Ok(())
        })
    })
    .await;
    match r {
        Ok(Ok(des)) => {
            let estado = mapa_de(des.get("progreso")).get("estado").cloned().unwrap_or(Valor::Nulo);
            json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("guardado", des.valor("actualizado").clone()).con("estado", estado)))
        }
        Ok(Err(e)) => error_obtener(e),
        Err(_) => error_500(),
    }
}

/// `POST /api/desafios/{id_}/razonamiento/visto`: cuántos pasos del razonamiento vio (0–10, nunca baja)
pub async fn desafios_pasos_vistos(Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let n = c.entero("pasos_vistos");
    if let Err(r) = c.fin() {
        return r;
    }
    let n = n.unwrap_or(0).clamp(0, 10);
    let base = carpeta_base();
    let r = tokio::task::spawn_blocking(move || {
        d::modificar(&base, &id, |des| {
            if let Some(Valor::Mapa(p)) = des.get_mut("progreso") {
                let previo = p.get("pasos_vistos").and_then(Valor::entero).unwrap_or(0);
                p.poner("pasos_vistos", Valor::Entero(previo.max(n)));
            }
            d::empezar(des);
            Ok(())
        })
    })
    .await;
    match r {
        Ok(Ok(des)) => {
            let v = mapa_de(des.get("progreso")).get("pasos_vistos").cloned().unwrap_or(Valor::Nulo);
            json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("pasos_vistos", v)))
        }
        Ok(Err(e)) => error_obtener(e),
        Err(_) => error_500(),
    }
}

/// `POST /api/desafios/{id_}/rendirse`: la solución de referencia; si no estaba resuelto, queda como rendido
pub async fn desafios_rendirse(Ruta(id): Ruta<String>) -> Response {
    let base = carpeta_base();
    let r = tokio::task::spawn_blocking(move || {
        d::modificar(&base, &id, |des| {
            if let Some(Valor::Mapa(p)) = des.get_mut("progreso") {
                if !matches!(p.get("estado"), Some(Valor::Texto(t)) if t == "resuelto") {
                    p.poner("estado", "rendido");
                    p.poner("rendido", d::ahora());
                }
            }
            Ok(())
        })
    })
    .await;
    match r {
        Ok(Ok(des)) => {
            let vacio = Valor::Mapa(Mapa::new());
            let privado = mapa_de(Some(if des.verdad("privado") { des.valor("privado") } else { &vacio }));
            let comp = mapa_de(Some(if privado.verdad("comprobacion") { privado.valor("comprobacion") } else { &vacio }));
            let tipo = comp.get("tipo").cloned().unwrap_or(Valor::Nulo);
            let campo = match &tipo {
                Valor::Texto(t) if t == "unittest" => Some("archivos"),
                Valor::Texto(t) if t == "doctest" => Some("ejemplos"),
                Valor::Texto(t) if t == "asserts" => Some("asserts"),
                _ => None,
            };
            let pruebas = campo.and_then(|c| comp.get(c).cloned()).unwrap_or(Valor::Nulo);
            let referencia = match privado.get("referencia") {
                Some(v) if v.verdad() => v.clone(),
                _ => Valor::Lista(Vec::new()),
            };
            json_py(
                StatusCode::OK,
                &Valor::Mapa(
                    Mapa::new()
                        .con("referencia", referencia)
                        .con("pruebas", pruebas)
                        .con("tipo", tipo)
                        .con("progreso", des.get("progreso").cloned().unwrap_or(Valor::Nulo)),
                ),
            )
        }
        Ok(Err(e)) => error_obtener(e),
        Err(_) => error_500(),
    }
}

// ---------------------------------------------------------------------------------------------- ejecutar

/// Los arneses que van junto a las páginas: `backend/desafios/arneses/` (los mismos que usa desafios/ejecucion.py)
fn arneses(state: &AppState) -> Result<(String, String), String> {
    let dir = state.base_dir.join("backend/desafios/arneses");
    let leer = |n: &str| std::fs::read_to_string(dir.join(n)).map_err(|e| format!("{n}: {e}"));
    Ok((leer("pytest.py")?, leer("catch.hpp")?))
}

/// `Carpeta`: una carpeta temporal `prig_desafio_*` con las páginas y los extras; se borra al terminar
struct Carpeta(std::path::PathBuf);

impl Carpeta {
    fn crear(paginas: &[Mapa], extras: &[(&str, &str)]) -> Result<Carpeta, String> {
        let base = std::env::temp_dir();
        let ruta = (0..100)
            .map(|_| base.join(format!("prig_desafio_{}", &uuid::Uuid::new_v4().simple().to_string()[..8])))
            .find(|r| std::fs::create_dir(r).is_ok())
            .ok_or("no se pudo crear la carpeta temporal")?;
        let c = Carpeta(ruta);
        for p in paginas {
            c.escribir(p.texto("nombre").unwrap_or_default(), p.texto("contenido").unwrap_or_default())?;
        }
        for (n, t) in extras {
            c.escribir(n, t)?;
        }
        Ok(c)
    }

    fn escribir(&self, nombre: &str, contenido: &str) -> Result<(), String> {
        let destino = self.0.join(nombre);
        if let Some(d) = destino.parent() {
            std::fs::create_dir_all(d).map_err(|e| e.to_string())?;
        }
        std::fs::write(destino, contenido).map_err(|e| e.to_string())
    }
}

impl Drop for Carpeta {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

const FUENTES_C: [&str; 4] = [".cpp", ".cc", ".cxx", ".c"];

/// `POST /api/desafios/{id_}/ejecutar` (`paginas`, `pagina`): ejecuta una página como script; las demás están para
/// importarlas o compilarlas. `run_id` = `desafio_<id>`, así `/detener` la para
pub async fn desafios_ejecutar(State(state): State<AppState>, Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let paginas = c.lista_de_dicts("paginas");
    let pagina = c.texto("pagina", None);
    if let Err(r) = c.fin() {
        return r;
    }
    let Valor::Texto(pagina) = pagina else { return error_500() };
    let base = carpeta_base();
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, ErrorObtener> {
        d::obtener(&base.join("desafios"), &id)?;
        let paginas = d::validar_paginas(&paginas, false).map_err(ErrorObtener::Desafio)?;
        if !paginas.iter().any(|p| p.texto("nombre") == Some(pagina.as_str())) {
            return Err(ErrorObtener::Desafio(format!("No hay ninguna página «{pagina}».")));
        }
        let (pytest, catch) = arneses(&state).map_err(ErrorObtener::Otro)?;
        let extras = [("pytest.py", pytest.as_str()), ("catch.hpp", catch.as_str()), ("test/catch.hpp", catch.as_str()), ("catch2/catch.hpp", catch.as_str())];
        let carpeta = Carpeta::crear(&paginas, &extras).map_err(ErrorObtener::Otro)?;
        let dir = carpeta.0.to_string_lossy().into_owned();
        let extra: Vec<String> = if FUENTES_C.iter().any(|e| pagina.ends_with(e)) {
            paginas
                .iter()
                .filter_map(|p| p.texto("nombre"))
                .filter(|n| *n != pagina && FUENTES_C.iter().any(|e| n.ends_with(e)))
                .map(|n| format!("{dir}/{n}"))
                .collect()
        } else {
            Vec::new()
        };
        let r = state.ejecutor.ejecutar_archivo(&format!("{dir}/{pagina}"), Some(&dir), Some(20), Some(&format!("desafio_{id}")), &extra);
        let stderr = r.texto("stderr").unwrap_or_default().replace(&format!("{dir}/"), "");
        Ok(Mapa::new()
            .con("ok", r.verdad("success"))
            .con("stdout", r.texto("stdout").unwrap_or_default().to_string())
            .con("stderr", stderr)
            .con("elapsed", r.get("elapsed").cloned().unwrap_or(Valor::Entero(0)))
            .con("cancelado", r.verdad("cancelled")))
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e)) => error_obtener(e),
        Err(_) => error_500(),
    }
}

/// `POST /api/desafios/{id_}/detener`
pub async fn desafios_detener(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    let m = tokio::task::spawn_blocking(move || state.ejecutor.cancelar(&format!("desafio_{id}"))).await.unwrap_or_default();
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

// ---------------------------------------------------------------------------------------------- comprobar

const MARCA: &str = "__PRIG_RESULTADO__";
const EXT_CPP: [&str; 6] = [".cpp", ".hpp", ".h", ".cc", ".cxx", ".c"];

fn termina(n: &str, exts: &[&str]) -> bool {
    exts.iter().any(|e| n.ends_with(e))
}

/// `str[-n:]` en caracteres
fn cola(t: &str, n: usize) -> String {
    let c = t.chars().count();
    t.chars().skip(c.saturating_sub(n)).collect()
}

/// `\bint\s+main\s*\(`
fn tiene_main(t: &str) -> bool {
    static RE: std::sync::LazyLock<regex::Regex> = std::sync::LazyLock::new(|| regex::Regex::new(r"\bint\s+main\s*\(").unwrap());
    RE.is_match(t)
}

/// `comprobar(runner, paginas, privado)` de desafios/ejecucion.py: pasa las pruebas ocultas a las páginas
pub(crate) fn comprobar(state: &AppState, paginas: &[Mapa], privado: &Mapa, run_id: &str) -> Result<Mapa, ErrorObtener> {
    let timeout = 30;
    let vacio = Valor::Mapa(Mapa::new().con("tipo", "ninguna"));
    let c = mapa_de(Some(if privado.verdad("comprobacion") { privado.valor("comprobacion") } else { &vacio }));
    let tipo = c.texto("tipo").unwrap_or_default().to_string();
    if c.get("tipo") == Some(&Valor::Texto("ninguna".into())) {
        return Ok(Mapa::new()
            .con("aprobado", false)
            .con("comprobable", false)
            .con("total", Valor::Entero(0))
            .con("pasados", Valor::Entero(0))
            .con("fallos", Valor::Lista(Vec::new()))
            .con("error", Valor::Nulo)
            .con("stdout", "")
            .con("stderr", "")
            .con("elapsed", Valor::Entero(0)));
    }
    let nombres: Vec<String> = paginas.iter().map(|p| p.texto("nombre").unwrap_or_default().to_string()).collect();
    let es_cpp = nombres.iter().any(|n| termina(n, &EXT_CPP)) || ["cpp_test", "catch2", "cpp_asserts"].contains(&tipo.as_str());
    let (pytest, catch) = arneses(state).map_err(ErrorObtener::Otro)?;
    let arnes = std::fs::read_to_string(state.base_dir.join("backend/desafios/arneses/comprobar.py")).map_err(|e| ErrorObtener::Otro(e.to_string()))?;
    let mut extras: Vec<(String, String)> = vec![
        ("pytest.py".into(), pytest),
        ("_prig_comprobar.py".into(), arnes),
        ("catch.hpp".into(), catch.clone()),
        ("test/catch.hpp".into(), catch.clone()),
        ("catch2/catch.hpp".into(), catch),
    ];
    // Un dict de Python: una clave repetida se queda en su sitio con el valor nuevo
    let poner = |extras: &mut Vec<(String, String)>, k: String, v: String| match extras.iter_mut().find(|(n, _)| *n == k) {
        Some(e) => e.1 = v,
        None => extras.push((k, v)),
    };
    let archivos_de = |c: &Mapa| -> Vec<(String, String)> {
        match c.get("archivos") {
            Some(Valor::Mapa(m)) => m.iter().map(|(k, v)| (k.clone(), v.texto_o_repr())).collect(),
            _ => Vec::new(),
        }
    };
    let ejecutar = |extras: &[(String, String)], archivo: &str, fuentes: &dyn Fn(&str) -> Vec<String>| -> Result<(Mapa, String, String, String), ErrorObtener> {
        let refs: Vec<(&str, &str)> = extras.iter().map(|(a, b)| (a.as_str(), b.as_str())).collect();
        let carpeta = Carpeta::crear(paginas, &refs).map_err(ErrorObtener::Otro)?;
        let dir = carpeta.0.to_string_lossy().into_owned();
        let extra = fuentes(&dir);
        let r = state.ejecutor.ejecutar_archivo(&format!("{dir}/{archivo}"), Some(&dir), Some(timeout), Some(run_id), &extra);
        let stdout = r.texto("stdout").unwrap_or_default().to_string();
        let stderr = r.texto("stderr").unwrap_or_default().replace(&format!("{dir}/"), "");
        Ok((r, stdout, stderr, dir))
    };

    let (r, stdout, stderr, carpeta) = if es_cpp {
        let test_file: Option<String>;
        let mut fuentes_extra: Vec<String> = Vec::new();
        let mut tiene_h = true;
        if ["cpp_test", "catch2", "unittest"].contains(&tipo.as_str()) {
            let mut archivos = archivos_de(&c);
            if archivos.is_empty() {
                if let Some(codigo) = c.get("codigo") {
                    archivos.push(("test.cpp".into(), codigo.texto_o_repr()));
                }
            }
            let choque: Vec<&str> = archivos.iter().map(|(n, _)| n.as_str()).filter(|n| nombres.iter().any(|x| x == n)).collect();
            if !choque.is_empty() {
                return Err(ErrorObtener::Desafio(format!("Una página no puede llamarse como las pruebas: {}", choque.join(", "))));
            }
            for (n, t) in &archivos {
                poner(&mut extras, n.clone(), t.clone());
            }
            let elegido = archivos
                .iter()
                .map(|(n, _)| n)
                .find(|n| termina(n, &[".cpp", ".cc", ".cxx"]))
                .or_else(|| archivos.iter().map(|(n, _)| n).find(|n| n.to_lowercase().contains("test")))
                .or_else(|| archivos.first().map(|(n, _)| n))
                .cloned();
            let Some(tf) = elegido else { return Err(ErrorObtener::Desafio("No se encontró ningún archivo de pruebas C++.".into())) };
            test_file = Some(tf.clone());
            for (n, _) in &archivos {
                if *n != tf && termina(n, &[".cpp", ".cc", ".cxx", ".c"]) {
                    fuentes_extra.push(n.clone());
                }
            }
        } else if ["cpp_asserts", "asserts"].contains(&tipo.as_str()) {
            let mut lineas_h: Vec<String> = nombres.iter().filter(|n| termina(n, &[".h", ".hpp"])).map(|n| format!("#include \"{n}\"")).collect();
            if let Some(Valor::Lista(inc)) = c.get("includes") {
                for i in inc {
                    let i = i.texto_o_repr();
                    if !lineas_h.contains(&i) {
                        lineas_h.push(i);
                    }
                }
            }
            tiene_h = !lineas_h.is_empty();
            if !tiene_h {
                let cpps: Vec<&String> = nombres.iter().filter(|n| termina(n, &[".cpp", ".cc", ".cxx", ".c"])).collect();
                for (i, cf) in cpps.iter().enumerate() {
                    lineas_h.push(format!("#define main __prig_disabled_main_{}\n#include \"{cf}\"\n#undef main", i + 1));
                }
            }
            let mut cuerpo: Vec<String> = Vec::new();
            if let Some(Valor::Lista(asserts)) = c.get("asserts") {
                for (i, f) in asserts.iter().enumerate() {
                    let mut frag = prig_plataforma::py::strip(&f.texto_o_repr()).to_string();
                    if !frag.starts_with("TEST_CASE") {
                        if !frag.contains(';') && !(frag.starts_with("REQUIRE") || frag.starts_with("CHECK")) {
                            frag = format!("REQUIRE({frag});");
                        } else if !frag.ends_with(';') && !frag.ends_with('}') {
                            frag.push(';');
                        }
                        frag = format!("TEST_CASE(\"prueba {}\", \"[test]\") {{\n    {frag}\n}}", i + 1);
                    }
                    cuerpo.push(frag);
                }
            }
            let test_cpp = format!(
                "#include \"catch.hpp\"\n#include <cassert>\n#undef assert\n#define assert(expr) REQUIRE(expr)\n{}\n\n{}\n",
                lineas_h.join("\n"),
                cuerpo.join("\n\n")
            );
            test_file = Some("_prig_comprobar.cpp".into());
            poner(&mut extras, "_prig_comprobar.cpp".into(), test_cpp);
        } else {
            return Err(ErrorObtener::Desafio(format!("Tipo de comprobación C++ desconocido: {}", c.get("tipo").map(|v| v.texto_o_repr()).unwrap_or("None".into()))));
        }
        let tf = test_file.clone().unwrap_or_default();
        let fuentes = |dir: &str| -> Vec<String> {
            let mut v: Vec<String> = if tiene_h {
                paginas
                    .iter()
                    .filter(|p| {
                        let n = p.texto("nombre").unwrap_or_default();
                        termina(n, &[".cpp", ".cc", ".cxx", ".c"]) && n != tf && !tiene_main(p.texto("contenido").unwrap_or_default())
                    })
                    .map(|p| format!("{dir}/{}", p.texto("nombre").unwrap_or_default()))
                    .collect()
            } else {
                Vec::new()
            };
            v.extend(fuentes_extra.iter().map(|s| format!("{dir}/{s}")));
            v
        };
        ejecutar(&extras, &tf, &fuentes)?
    } else {
        let mut config = Mapa::new().con("tipo", c.valor("tipo").clone());
        match tipo.as_str() {
            "unittest" => {
                let archivos = archivos_de(&c);
                let choque: Vec<&str> = archivos.iter().map(|(n, _)| n.as_str()).filter(|n| nombres.iter().any(|x| x == n)).collect();
                if !choque.is_empty() {
                    return Err(ErrorObtener::Desafio(format!("Una página no puede llamarse como las pruebas: {}", choque.join(", "))));
                }
                for (n, t) in &archivos {
                    poner(&mut extras, n.clone(), t.clone());
                }
                config.poner(
                    "modulos",
                    Valor::Lista(archivos.iter().filter(|(n, _)| n.ends_with(".py")).map(|(n, _)| Valor::Texto(n[..n.len() - 3].to_string())).collect()),
                );
            }
            "doctest" => {
                config.poner("modulo", c.get("modulo").cloned().ok_or(ErrorObtener::Otro("falta modulo".into()))?);
                config.poner("ejemplos", c.get("ejemplos").cloned().ok_or(ErrorObtener::Otro("faltan ejemplos".into()))?);
            }
            "asserts" => {
                let l = match c.get("asserts") {
                    Some(Valor::Lista(l)) => l.clone(),
                    _ => Vec::new(),
                };
                config.poner("asserts", Valor::Lista(l));
            }
            _ => {
                return Err(ErrorObtener::Desafio(format!(
                    "Tipo de comprobación desconocido: {}",
                    c.get("tipo").map(|v| v.texto_o_repr()).unwrap_or("None".into())
                )))
            }
        }
        poner(&mut extras, "_prig_config.json".into(), prig_plataforma::json::escribir_linea(&Valor::Mapa(config)));
        ejecutar(&extras, "_prig_comprobar.py", &|_| Vec::new())?
    };

    // el resultado: la última línea con la marca
    let mut datos: Option<Mapa> = stdout.rsplit_once(MARCA).and_then(|(_, resto)| {
        let linea = prig_plataforma::py::strip(resto).lines().next()?.to_string();
        match prig_plataforma::json::leer(&linea).ok()? {
            Valor::Mapa(m) => Some(m),
            _ => None,
        }
    });
    if let Some(d) = datos.as_mut() {
        let limpiar = |v: &Valor| match v {
            Valor::Texto(t) => Valor::Texto(t.replace(&format!("{carpeta}/"), "")),
            otro => otro.clone(),
        };
        let e = limpiar(d.get("error").unwrap_or(&Valor::Nulo));
        d.poner("error", e);
        if let Some(Valor::Lista(fs)) = d.get("fallos").cloned() {
            let limpios = fs
                .iter()
                .map(|f| match f {
                    Valor::Mapa(m) => {
                        let mut n = Mapa::new();
                        for (k, v) in m.iter() {
                            n.poner(k.clone(), limpiar(v));
                        }
                        Valor::Mapa(n)
                    }
                    otro => otro.clone(),
                })
                .collect();
            d.poner("fallos", Valor::Lista(limpios));
        }
    }
    let elapsed = r.get("elapsed").cloned().unwrap_or(Valor::Entero(0));
    let Some(d) = datos else {
        let codigo = r.get("exit_code").and_then(Valor::entero);
        let motivo = if stderr.contains("Tiempo límite") {
            format!("Tardó más de {timeout} s: revisa si hay un bucle que no termina.")
        } else if stderr.contains("Error de compilación") || (codigo != Some(0) && !stderr.is_empty()) {
            format!("Error de compilación:\n{}", cola(&stderr, 2000))
        } else if r.verdad("cancelled") {
            "Comprobación detenida.".into()
        } else {
            "La comprobación no terminó.".into()
        };
        return Ok(Mapa::new()
            .con("aprobado", false)
            .con("comprobable", true)
            .con("total", Valor::Entero(0))
            .con("pasados", Valor::Entero(0))
            .con("fallos", Valor::Lista(Vec::new()))
            .con("error", motivo)
            .con("stdout", cola(&stdout, 3000))
            .con("stderr", cola(&stderr, 3000))
            .con("elapsed", elapsed));
    };
    let total = d.get("total").and_then(Valor::entero).unwrap_or(0);
    let pasados = d.get("pasados").and_then(Valor::entero).unwrap_or(0);
    let error = d.get("error").cloned().unwrap_or(Valor::Nulo);
    let aprobado = error.es_nulo() && total > 0 && pasados == total;
    let fallos = match d.get("fallos") {
        Some(Valor::Lista(l)) => l.iter().take(20).cloned().collect(),
        _ => Vec::new(),
    };
    Ok(Mapa::new()
        .con("aprobado", aprobado)
        .con("comprobable", true)
        .con("total", d.valor("total").clone())
        .con("pasados", d.valor("pasados").clone())
        .con("fallos", Valor::Lista(fallos))
        .con("error", error)
        .con("stdout", d.get("stdout").cloned().unwrap_or(Valor::Texto(String::new())))
        .con("stderr", cola(&stderr, 3000))
        .con("elapsed", elapsed))
}

/// `POST /api/desafios/{id_}/comprobar`: comprueba, guarda el resultado en el desafío, anota la telemetría y, si es
/// de Prig Hub y lo aprueba, el progreso del Hub
pub async fn desafios_comprobar(State(state): State<AppState>, Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let paginas = c.lista_de_dicts("paginas");
    if let Err(r) = c.fin() {
        return r;
    }
    let espacio = espacio_de_trabajo(&state).await;
    let base = carpeta_base();
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, ErrorObtener> {
        let Valor::Mapa(des) = d::obtener(&base.join("desafios"), &id)? else { return Err(ErrorObtener::Otro("no es un objeto".into())) };
        let paginas = d::validar_paginas(&paginas, false).map_err(ErrorObtener::Desafio)?;
        let vacio = Valor::Mapa(Mapa::new());
        let privado = mapa_de(Some(if des.verdad("privado") { des.valor("privado") } else { &vacio }));
        let resultado = comprobar(&state, &paginas, &privado, &format!("desafio_{id}"))?;
        if !resultado.verdad("comprobable") {
            return Ok(resultado.con("progreso", des.get("progreso").cloned().unwrap_or(Valor::Nulo)));
        }
        let aprobado = resultado.verdad("aprobado");
        let total = resultado.get("total").and_then(Valor::entero).unwrap_or(0);
        let pasados = resultado.get("pasados").and_then(Valor::entero).unwrap_or(0);
        let r2 = resultado.clone();
        let des = d::modificar(&base, &id, move |x| {
            let usuario = paginas
                .iter()
                .map(|p| {
                    Valor::Mapa(
                        Mapa::new()
                            .con("nombre", p.valor("nombre").clone())
                            .con("contenido", p.valor("contenido").clone())
                            .con("descripcion", p.get("descripcion").cloned().unwrap_or(Valor::Texto(String::new()))),
                    )
                })
                .collect();
            x.poner("paginas_usuario", Valor::Lista(usuario));
            d::registrar_comprobacion(x, aprobado, pasados, total);
            let mut ultima = Mapa::new();
            for k in ["aprobado", "total", "pasados", "fallos", "error"] {
                ultima.poner(k, r2.valor(k).clone());
            }
            x.poner("ultima_comprobacion", ultima);
            Ok(())
        })?;
        // la telemetría, si está encendida (un fallo aquí solo se avisa, como en Python)
        let banderas = prig_plataforma::banderas::Banderas::new(std::path::PathBuf::from(prig_plataforma::py::expanduser("~/.prig_flags.json")));
        if banderas.activa("learning_telemetry") {
            let pistas = mapa_de(des.get("progreso")).get("pistas").and_then(Valor::entero).unwrap_or(0) as i64;
            let stderr = match resultado.get("error") {
                Some(Valor::Texto(t)) if !t.is_empty() => t.clone(),
                _ => resultado.texto("stderr").unwrap_or_default().to_string(),
            };
            let segundos = resultado.get("elapsed").and_then(Valor::num).unwrap_or(0.0);
            if let Err(e) = prig_aprendizaje::telemetria::registrar_envio(&espacio, &des, aprobado, pistas, &stderr, segundos) {
                tracing::warn!("⚠️ Telemetría de desafíos: {e}");
            }
        }
        let origen = mapa_de(des.get("origen"));
        if aprobado && origen.texto("tipo") == Some("prig-hub") && origen.verdad("ref") {
            let referencia = origen.texto("ref").unwrap_or_default().to_string();
            let hub = std::env::var_os("PRIG_HUB_DIR")
                .filter(|d| !d.is_empty())
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|| prig_plataforma::py::expanduser("~/.prig_hub").into());
            let version = origen.texto("version").unwrap_or_default().to_string();
            let fuente = referencia.split('#').next().unwrap_or_default().to_string();
            if let Err(e) = prig_aprendizaje::telemetria::marcar_hub(&hub, &format!("desafio:{referencia}"), "terminado", &fuente, &version) {
                tracing::warn!("⚠️ No se pudo anotar el progreso en Prig Hub: {e}");
            }
        }
        Ok(resultado.con("progreso", des.get("progreso").cloned().unwrap_or(Valor::Nulo)))
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e)) => error_obtener(e),
        Err(_) => error_500(),
    }
}

/// `GET /api/progreso/historial?estado=&concepto=&fuente=&limite=200`
pub async fn progreso_historial(axum::extract::Query(q): axum::extract::Query<std::collections::HashMap<String, String>>) -> Response {
    let limite = match cuerpo::entero_consulta(&q, "limite", 200, 1, 500) {
        Ok(n) => n,
        Err(r) => return r,
    };
    let dir = carpeta_base().join("desafios");
    let r = tokio::task::spawn_blocking(move || {
        d::historial(&dir, q.get("estado").map(String::as_str), q.get("concepto").map(String::as_str), q.get("fuente").map(String::as_str), limite)
    })
    .await;
    match r {
        Ok(Ok(filas)) => json_py(
            StatusCode::OK,
            &Valor::Mapa(Mapa::new().con("desafios", Valor::Lista(filas.into_iter().map(Valor::Mapa).collect()))),
        ),
        _ => error_500(),
    }
}

/// `GET /api/progreso/resumen?dias=120`: todo el avance en un sitio
pub async fn progreso_resumen(
    axum::extract::State(state): axum::extract::State<crate::state::AppState>,
    axum::extract::Query(q): axum::extract::Query<std::collections::HashMap<String, String>>,
) -> Response {
    let dias = match cuerpo::entero_consulta(&q, "dias", 120, 7, 365) {
        Ok(n) => n,
        Err(r) => return r,
    };
    let dir = carpeta_base().join("desafios");
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || {
        let lecturas = prig_integrations::kaggle::resumen_lecturas().unwrap_or_default();
        prig_aprendizaje::progreso::resumen(&dir, Some(&espacio), dias, lecturas)
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        _ => error_500(),
    }
}
