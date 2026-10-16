//! Ejercicios sin modelo (`exercise_store.py` y la corrección de `exercise_engine.py`): los recientes, la vista
//! pública, la solución (anotada en la telemetría) y corregir una entrega ejecutándola contra los tests ocultos en
//! una sesión de Python desechable. Generar y las pistas usan el modelo y siguen en Python.
//!
//! Los ejercicios viven en `<espacio>/.prig_dataset/exercises.json`; Python lo escribe entero cada vez que guarda
//! uno, así que leerlo aquí da lo mismo que su caché.

use axum::{
    body::Bytes,
    extract::{Path as Ruta, Query, State},
    http::StatusCode,
    response::Response,
};
use prig_plataforma::valor::{Mapa, Valor};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::routes::cuerpo::{self, entero_consulta};
use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{detalle, json_py};
use crate::state::AppState;

const MARCA_OK: &str = "__PRIG_EXERCISE_OK__";

fn error_500() -> Response {
    use axum::response::IntoResponse;
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

/// `ExerciseStore._load()`: el dict de ejercicios (vacío si falta, está roto o no es un objeto)
fn ejercicios(espacio: &Path) -> Mapa {
    match prig_aprendizaje::desafios::leer_json(&espacio.join(".prig_dataset").join("exercises.json")) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    }
}

fn texto_o(m: &Mapa, k: &str) -> Valor {
    m.get(k).cloned().unwrap_or(Valor::Texto(String::new()))
}

fn telemetria_activa() -> bool {
    prig_plataforma::banderas::Banderas::new(PathBuf::from(prig_plataforma::py::expanduser("~/.prig_flags.json"))).activa("learning_telemetry")
}

/// `GET /api/exercise/recent?limit=20&concept=`
pub async fn recientes(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let limite = match entero_consulta(&q, "limit", 20, 1, 100) {
        Ok(n) => n as usize,
        Err(r) => return r,
    };
    let concepto = q.get("concept").cloned().filter(|c| !c.is_empty());
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || {
        let todos = ejercicios(&espacio);
        let total = todos.len();
        let mut items: Vec<Mapa> = todos
            .iter()
            .filter_map(|(_, v)| if let Valor::Mapa(m) = v { Some(m.clone()) } else { None })
            .filter(|e| concepto.as_ref().is_none_or(|c| e.get("concept") == Some(&Valor::Texto(c.clone()))))
            .collect();
        // sort(key=created_at or "", reverse=True): estable
        items.sort_by_key(|e| std::cmp::Reverse(e.texto("created_at").unwrap_or_default().to_string()));
        let lista: Vec<Valor> = items
            .iter()
            .take(limite)
            .map(|e| {
                Valor::Mapa(
                    Mapa::new()
                        .con("exercise_id", e.get("exercise_id").cloned().unwrap_or(Valor::Nulo))
                        .con("concept", texto_o(e, "concept"))
                        .con("title", texto_o(e, "title"))
                        .con("created_at", texto_o(e, "created_at")),
                )
            })
            .collect();
        Mapa::new().con("exercises", Valor::Lista(lista)).con("total", Valor::Entero(total as i128))
    })
    .await;
    match r {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

async fn uno(state: &AppState, id: String) -> (PathBuf, Option<Mapa>) {
    let espacio = espacio_de_trabajo(state).await;
    let e = tokio::task::spawn_blocking({
        let espacio = espacio.clone();
        move || match ejercicios(&espacio).get(&id) {
            Some(Valor::Mapa(m)) => Some(m.clone()),
            _ => None,
        }
    })
    .await
    .ok()
    .flatten();
    (espacio, e)
}

/// `GET /api/exercise/{id}`: la vista pública (nunca la solución ni los tests)
pub async fn ver(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    let (_, Some(e)) = uno(&state, id).await else { return detalle(StatusCode::NOT_FOUND, "Ejercicio no encontrado.") };
    let Some(eid) = e.get("exercise_id").cloned() else { return error_500() };
    let m = Mapa::new()
        .con("exercise_id", eid)
        .con("concept", texto_o(&e, "concept"))
        .con("title", texto_o(&e, "title"))
        .con("statement", texto_o(&e, "statement"))
        .con("function_name", texto_o(&e, "function_name"))
        .con("starter_code", texto_o(&e, "starter_code"))
        .con("attempts_used", e.get("attempts_used").cloned().unwrap_or(Valor::Entero(1)));
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

/// `GET /api/exercise/{id}/solution`: pedirla es un dato pedagógico (se rindió) y va a la telemetría
pub async fn solucion(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    let (espacio, Some(e)) = uno(&state, id.clone()).await else { return detalle(StatusCode::NOT_FOUND, "Ejercicio no encontrado.") };
    let (Some(sol), Some(tests)) = (e.get("reference_solution").cloned(), e.get("tests").cloned()) else { return error_500() };
    let concepto = e.texto("concept").unwrap_or_default().to_string();
    let idc = id.clone();
    let _ = tokio::task::spawn_blocking(move || {
        if telemetria_activa() {
            use prig_aprendizaje::telemetria as t;
            let r = t::abrir(&espacio).and_then(|c| {
                t::registrar(&c, &t::Evento { ejercicio: &idc, concepto: &concepto, tipo: "solution_revealed", aprobado: None, intento: 1, pistas: 0, stderr: "", segundos: 0.0 })
            });
            if let Err(e) = r {
                tracing::warn!("telemetría: {e}");
            }
        }
    })
    .await;
    json_py(
        StatusCode::OK,
        &Valor::Mapa(Mapa::new().con("exercise_id", id).con("reference_solution", sol).con("tests", tests)),
    )
}

/// `ExerciseEngine.grade_submission`: el código del alumno con los tests ocultos, en una sesión desechable
fn corregir(state: &AppState, codigo: &str, tests: &str) -> Mapa {
    if prig_plataforma::py::strip(codigo).is_empty() {
        return Mapa::new().con("passed", false).con("reason", "No enviaste código.").con("stdout", "").con("stderr", "");
    }
    let arnes = format!("{codigo}\n\n{tests}\n\nprint('{MARCA_OK}')\n");
    let sesion = format!("__eval_{}__", &uuid::Uuid::new_v4().simple().to_string()[..10]);
    let r = state.ejecutor.ejecutar_celda(&arnes, None, Some(&sesion), Some(15));
    state.ejecutor.sesiones.reiniciar(Some(&sesion));
    let stdout = r.texto("stdout").unwrap_or_default().to_string();
    let stderr = prig_plataforma::py::strip(r.texto("stderr").unwrap_or_default()).to_string();
    let aprobado = r.verdad("success") && stdout.contains(MARCA_OK);
    let motivo = if aprobado {
        "Todos los tests pasan.".to_string()
    } else if stderr.contains("AssertionError") {
        "Tu solución no cumple uno de los casos de prueba.".into()
    } else if stderr.contains("SyntaxError") {
        "El código tiene un error de sintaxis.".into()
    } else if stderr.contains("Tiempo límite") {
        "La ejecución tardó demasiado: revisa si hay un bucle infinito.".into()
    } else if !stderr.is_empty() {
        format!("La ejecución falló: {}", prig_plataforma::py::strip(&stderr).lines().last().unwrap_or_default())
    } else {
        "La ejecución no completó los tests.".into()
    };
    Mapa::new()
        .con("passed", aprobado)
        .con("reason", motivo)
        .con("stdout", stdout.replace(&format!("{MARCA_OK}\n"), "").replace(MARCA_OK, ""))
        .con("stderr", stderr)
        .con("elapsed", r.get("elapsed").cloned().unwrap_or(Valor::Entero(0)))
}

/// `POST /api/exercise/submit` (`exercise_id`, `code`, `hints_used = 0`)
pub async fn entregar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let id = c.texto("exercise_id", None);
    let codigo = c.texto("code", None);
    let pistas = if m.contiene("hints_used") { c.entero("hints_used") } else { Some(0) };
    if let Err(r) = c.fin() {
        return r;
    }
    let (Valor::Texto(id), Valor::Texto(codigo)) = (id, codigo) else { return error_500() };
    let (espacio, Some(e)) = uno(&state, id.clone()).await else {
        return detalle(StatusCode::NOT_FOUND, "Ejercicio no encontrado. Genera uno nuevo.");
    };
    let Some(tests) = e.get("tests").map(|t| t.texto_o_repr()) else { return error_500() };
    let r = tokio::task::spawn_blocking(move || {
        let mut res = corregir(&state, &codigo, &tests);
        if telemetria_activa() {
            use prig_aprendizaje::telemetria as t;
            let concepto = e.texto("concept").unwrap_or_default().to_string();
            let hecho = t::abrir(&espacio).and_then(|c| {
                let intento = t::numero_intento(&c, &id)?;
                t::registrar(
                    &c,
                    &t::Evento {
                        ejercicio: &id,
                        concepto: &concepto,
                        tipo: "submission",
                        aprobado: Some(res.verdad("passed")),
                        intento,
                        pistas: pistas.unwrap_or(0) as i64,
                        stderr: res.texto("stderr").unwrap_or_default(),
                        segundos: res.get("elapsed").and_then(Valor::num).unwrap_or(0.0),
                    },
                )?;
                Ok(intento)
            });
            match hecho {
                Ok(n) => res.poner("attempt", Valor::Entero(n as i128)),
                Err(e) => tracing::warn!("telemetría: {e}"),
            }
        }
        res
    })
    .await;
    match r {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}
