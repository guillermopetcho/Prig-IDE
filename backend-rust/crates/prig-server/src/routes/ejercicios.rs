//! Ejercicios sin modelo (`exercise_store.py` y la corrección de `exercise_engine.py`): los recientes, la vista
//! pública, la solución (anotada en la telemetría) y corregir una entrega ejecutándola contra los tests ocultos en
//! una sesión de Python desechable; generar uno YA VERIFICADO (su solución pasa sus tests y el código de partida no) y
//! las pistas graduadas, con el modelo.
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
pub(crate) fn ejercicios(espacio: &Path) -> Mapa {
    match prig_aprendizaje::desafios::leer_json(&espacio.join(".prig_dataset").join("exercises.json")) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    }
}

fn texto_o(m: &Mapa, k: &str) -> Valor {
    m.get(k).cloned().unwrap_or(Valor::Texto(String::new()))
}

pub(crate) fn telemetria_activa() -> bool {
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

pub(crate) async fn uno(state: &AppState, id: String) -> (PathBuf, Option<Mapa>) {
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
pub(crate) fn corregir(state: &AppState, codigo: &str, tests: &str) -> Mapa {
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

// =========================================================================== generar y pistas

const SISTEMA_GENERAR: &str = "Eres un GENERADOR DE EJERCICIOS DE PROGRAMACIÓN en Python.

Devuelve ÚNICAMENTE un objeto JSON válido, sin markdown ni texto alrededor, con esta forma exacta:
{
  \"title\": \"Título breve del ejercicio\",
  \"statement\": \"Enunciado claro de lo que debe implementar el alumno\",
  \"function_name\": \"nombre_de_la_funcion\",
  \"starter_code\": \"def nombre_de_la_funcion(parametros):\\n    pass\",
  \"reference_solution\": \"def nombre_de_la_funcion(parametros):\\n    return resultado\",
  \"tests\": \"assert nombre_de_la_funcion(1) == 2\\nassert nombre_de_la_funcion(0) == 0\"
}

REGLAS OBLIGATORIAS:
1. starter_code y reference_solution definen EL MISMO símbolo, con la misma firma.
   Puede ser una función (`def nombre(...)`) o una clase (`class Nombre:`); en ese
   caso \"function_name\" contiene el nombre de la clase.
2. starter_code tiene el cuerpo sin implementar (`pass`), nunca la solución.
3. tests son sentencias `assert` que llaman a esa función. Mínimo 3.
4. Los tests deben FALLAR con el starter_code y PASAR con reference_solution.
5. Nada de `assert True`, `input()`, red, ficheros ni bibliotecas externas.
6. Usa \\n para los saltos de línea dentro de las cadenas JSON.";

const CAMPOS: [&str; 5] = ["statement", "function_name", "starter_code", "reference_solution", "tests"];

fn generar_texto(state: &AppState, prompt: String, sistema: &str, modelo: &str, temperatura: f64) -> String {
    let p = prig_ia::generar::PedidoGenerar {
        prompt,
        modelo: modelo.into(),
        sistema: sistema.into(),
        opciones: Some(Mapa::new().con("temperature", temperatura)),
        gobernador: true,
        ..Default::default()
    };
    let mut r = String::new();
    let c = prig_ia::vivo::Cancelar::default();
    prig_ia::generar::generar(&state.base_dir, &p, &c, &mut |e: Mapa| {
        if e.get("t") == Some(&Valor::Texto("texto".into())) {
            r.push_str(&e.valor("v").texto_py());
        }
    });
    r
}

/// `ExerciseEngine.generate`: el ejercicio que propone el modelo (sin comprobar todavía)
fn generar_uno(state: &AppState, concepto: &str, modelo: &str, nivel: &str) -> Result<Mapa, String> {
    let prompt = format!("Concepto a practicar: {concepto}\nNivel del alumno: {nivel}\nGenera un ejercicio corto y autocontenido sobre ese concepto.");
    let mut d = prig_ia::json_modelo::reparar(&generar_texto(state, prompt, SISTEMA_GENERAR, modelo, 0.4))?;
    let faltan: Vec<&str> = CAMPOS.iter().filter(|f| prig_plataforma::py::strip(&d.get(f).map(Valor::texto_py).unwrap_or_default()).is_empty()).copied().collect();
    if !faltan.is_empty() {
        return Err(format!("Faltan campos en el JSON: {}", faltan.join(", ")));
    }
    d.poner("concept", concepto);
    d.poner("exercise_id", format!("ex_{}", &uuid::Uuid::new_v4().simple().to_string()[..8]));
    Ok(d)
}

/// Ejecutar en una sesión propia y desechable
fn ejecutar_aislado(state: &AppState, codigo: &str) -> Mapa {
    let sesion = format!("__eval_{}__", &uuid::Uuid::new_v4().simple().to_string()[..10]);
    let r = state.ejecutor.ejecutar_celda(codigo, None, Some(&sesion), Some(15));
    state.ejecutor.sesiones.reiniciar(Some(&sesion));
    r
}

/// `ExerciseEngine.validate`: comprobarlo EJECUTÁNDOLO; None si Python fallaría (un campo que no es texto)
fn validar(state: &AppState, e: &Mapa) -> Option<Mapa> {
    let texto = |k: &str| -> Option<String> {
        match e.get(k) {
            None => Some(String::new()),
            Some(Valor::Texto(t)) => Some(t.clone()),
            Some(_) => None,
        }
    };
    let (fun, sol, ini, tests) = (texto("function_name")?, texto("reference_solution")?, texto("starter_code")?, texto("tests")?);
    let patron = regex::Regex::new(&format!(r"(?:def|class)\s+{}\s*[\(:]", regex::escape(&fun))).ok()?;
    let arnes = |codigo: &str| format!("{codigo}\n\n{tests}\n\nprint('{MARCA_OK}')\n");
    let pasa = |r: &Mapa| r.verdad("success") && r.texto("stdout").unwrap_or_default().contains(MARCA_OK);
    let rf = ejecutar_aislado(state, &arnes(&sol));
    let stub = ejecutar_aislado(state, &arnes(&ini));
    let err = prig_plataforma::py::strip(rf.texto("stderr").unwrap_or_default()).to_string();
    let n = err.chars().count();
    let checks = Mapa::new()
        .con("function_in_solution", patron.is_match(&sol))
        .con("function_in_starter", patron.is_match(&ini))
        .con("reference_passes", pasa(&rf))
        .con("reference_stderr", err.chars().skip(n.saturating_sub(400)).collect::<String>())
        .con("tests_discriminate", !pasa(&stub))
        .con("tests_call_function", !fun.is_empty() && tests.contains(&fun));
    let v = |k: &str| checks.verdad(k);
    let valido = ["function_in_solution", "function_in_starter", "reference_passes", "tests_discriminate", "tests_call_function"].iter().all(|k| v(k));
    let motivo = if valido {
        "OK"
    } else if !v("reference_passes") {
        "La solución de referencia no pasa sus propios tests"
    } else if !v("tests_discriminate") {
        "Los tests pasan también con el código sin implementar: no comprueban nada"
    } else if !(v("function_in_solution") && v("function_in_starter")) {
        "La función declarada no aparece en el código de partida o en la solución"
    } else {
        "Los tests no invocan al símbolo declarado"
    };
    Some(Mapa::new().con("valid", valido).con("reason", motivo).con("checks", checks))
}

/// `ExerciseStore.save`: con su fecha, como mucho 500 (se van los más antiguos), escritura atómica
pub(crate) fn guardar_ejercicio(espacio: &Path, e: &mut Mapa) -> std::io::Result<()> {
    if !e.contiene("created_at") {
        e.poner("created_at", prig_plataforma::py::ahora_iso());
    }
    let mut todos = ejercicios(espacio);
    todos.poner(e.valor("exercise_id").texto_py(), e.clone());
    if todos.len() > 500 {
        let mut orden: Vec<(String, String)> = todos.iter().map(|(k, v)| (if let Valor::Mapa(m) = v { m.get("created_at").map(Valor::texto_py).unwrap_or_default() } else { String::new() }, k.clone())).collect();
        orden.sort_by(|a, b| a.0.cmp(&b.0));
        for (_, k) in orden.iter().take(todos.len() - 500) {
            todos.quitar(k);
        }
    }
    let dir = espacio.join(".prig_dataset");
    std::fs::create_dir_all(&dir)?;
    let ruta = dir.join("exercises.json");
    let tmp = dir.join("exercises.json.tmp");
    std::fs::write(&tmp, prig_plataforma::json::escribir(&Valor::Mapa(todos), 2))?;
    std::fs::rename(tmp, ruta)
}

/// `POST /api/exercise/generate` (`concept`, `model`, `level`, `attempts`): uno ya verificado, o un 422
pub async fn generar(State(state): State<AppState>, b: Bytes) -> Response {
    use prig_plataforma::modelo::Tipo;
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("concept", &Tipo::Texto, true), ("model", &Tipo::Texto, false), ("level", &Tipo::Texto, false), ("attempts", &Tipo::Entero, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Option<Response> {
        let concepto = c.valor("concept").texto_py();
        let modelo = c.get("model").map(Valor::texto_py).unwrap_or_else(|| "qwen2.5-coder:7b".into());
        let nivel = c.get("level").map(Valor::texto_py).unwrap_or_else(|| "intermedio".into());
        let intentos = c.get("attempts").and_then(Valor::num).map(|n| n as i64).unwrap_or(3).clamp(1, 5);
        let (hecho, historia) = generar_verificado(&state, &concepto, &modelo, &nivel, intentos)?;
        let Some(mut e) = hecho else {
            return Some(detalle(StatusCode::UNPROCESSABLE_ENTITY, format!("No se pudo generar un ejercicio verificable sobre '{concepto}'. Prueba otro modelo o reformula el concepto.")));
        };
        guardar_y_anotar(&espacio, &mut e, &concepto);
        let n = e.valor("attempts_used").clone();
        let publico = Mapa::new()
            .con("exercise_id", e.valor("exercise_id").clone())
            .con("concept", texto_o(&e, "concept"))
            .con("title", texto_o(&e, "title"))
            .con("statement", texto_o(&e, "statement"))
            .con("function_name", texto_o(&e, "function_name"))
            .con("starter_code", texto_o(&e, "starter_code"))
            .con("attempts_used", n)
            .con("generation_history", Valor::Lista(historia));
        Some(json_py(StatusCode::OK, &Valor::Mapa(publico)))
    })
    .await;
    match r {
        Ok(Some(r)) => r,
        _ => error_500(),
    }
}

/// `ExerciseEngine.generate_validated`: genera hasta tener uno que supere la verificación (con `validation` y
/// `attempts_used`), con la historia de los intentos. None si Python fallaría al validarlo (un campo que no es texto)
pub(crate) fn generar_verificado(state: &AppState, concepto: &str, modelo: &str, nivel: &str, intentos: i64) -> Option<(Option<Mapa>, Vec<Valor>)> {
    let mut historia = Vec::new();
    for n in 1..=intentos {
        let mut e = match generar_uno(state, concepto, modelo, nivel) {
            Ok(e) => e,
            Err(err) => {
                historia.push(Valor::Mapa(Mapa::new().con("attempt", n).con("stage", "generation").con("error", err)));
                continue;
            }
        };
        let v = validar(state, &e)?;
        historia.push(Valor::Mapa(Mapa::new().con("attempt", n).con("stage", "validation").con("valid", v.valor("valid").clone()).con("reason", v.valor("reason").clone())));
        if v.verdad("valid") {
            e.poner("validation", v);
            e.poner("attempts_used", n);
            return Some((Some(e), historia));
        }
    }
    Some((None, historia))
}

/// `exercise_store.save(exercise)` y, con la telemetría activa, el evento «generated»
pub(crate) fn guardar_y_anotar(espacio: &Path, e: &mut Mapa, concepto: &str) {
    if guardar_ejercicio(espacio, e).is_err() {
        tracing::warn!("No se pudieron guardar los ejercicios");
    }
    let id = e.valor("exercise_id").texto_py();
    let n = e.get("attempts_used").and_then(Valor::num).map(|n| n as i64).unwrap_or(1);
    if telemetria_activa() {
        use prig_aprendizaje::telemetria as t;
        let r = t::abrir(espacio).and_then(|cx| {
            t::registrar(&cx, &t::Evento { ejercicio: &id, concepto, tipo: "generated", aprobado: None, intento: n, pistas: 0, stderr: "", segundos: 0.0 })
        });
        if let Err(e) = r {
            tracing::warn!("telemetría: {e}");
        }
    }
}

const NIVELES_PISTA: [(&str, &str); 3] = [
    ("Pista conceptual", "Da UNA pista CONCEPTUAL: qué idea o estructura de Python resuelve esto. NO escribas código ni nombres de funciones concretas. Máximo 2 frases."),
    ("Pista de estructura", "Describe los PASOS en pseudocódigo o en una lista breve, sin escribir Python real. El alumno debe seguir teniendo que traducirlo a código. Máximo 4 líneas."),
    ("Pista concreta", "Muestra SOLO la línea o expresión clave que le falta, con una frase de explicación. No entregues la función completa."),
];

/// `POST /api/exercise/{id}/hint` (`level`, `model`): pista graduada, sin resolver
pub async fn pista(State(state): State<AppState>, Ruta(id): Ruta<String>, b: Bytes) -> Response {
    use prig_plataforma::modelo::Tipo;
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("level", &Tipo::Entero, false), ("model", &Tipo::Texto, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (_, Some(e)) = uno(&state, id).await else { return detalle(StatusCode::NOT_FOUND, "Ejercicio no encontrado.") };
    let r = tokio::task::spawn_blocking(move || {
        let nivel = c.get("level").and_then(Valor::num).map(|n| n as i64).unwrap_or(1).clamp(1, 3);
        let modelo = c.get("model").map(Valor::texto_py).unwrap_or_else(|| "qwen2.5-coder:7b".into());
        let (titulo, instruccion) = NIVELES_PISTA[(nivel - 1) as usize];
        let sistema = format!("Eres un tutor que guía sin resolver. El alumno está atascado en un ejercicio.\n{instruccion}\nResponde en español, directo, sin saludos. Nunca entregues la solución completa aunque la conozcas.");
        let g = |k: &str| e.get(k).map(Valor::texto_py).unwrap_or_default();
        let prompt = format!(
            "Enunciado: {}\nDebe definir: {}\nCódigo de partida:\n{}\n\n(Referencia interna, NO revelar:\n{})",
            g("statement"),
            g("function_name"),
            g("starter_code"),
            g("reference_solution")
        );
        let texto = prig_plataforma::py::strip(&generar_texto(&state, prompt, &sistema, &modelo, 0.3)).to_string();
        Mapa::new().con("level", nivel).con("title", titulo).con("text", texto)
    })
    .await;
    match r {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}
