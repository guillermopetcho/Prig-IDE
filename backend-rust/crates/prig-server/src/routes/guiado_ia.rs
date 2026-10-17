//! Aprendizaje guiado con el modelo (`/api/guided/*` y `/api/seguimiento/*` de `app.py`, con `GuidedLearningService`
//! y los agentes de `AIEngine`): generar una ruta (rápida con el organizador de temas, profunda con los tres agentes
//! del plan de estudio; también en streaming), migrar los planes antiguos, la clase de un bloque, su quiz, su reto
//! (un ejercicio VERIFICADO, o el reto antiguo si no sale ninguno), corregir el reto y el cuaderno de la ruta. Los
//! prompts son los de Python, carácter por carácter.

#![allow(clippy::result_large_err)]

use std::path::Path;
use std::sync::Arc;

use axum::{
    body::Bytes,
    extract::{Path as Ruta, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_aprendizaje::planes;
use prig_ia::vivo::Cancelar;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::asistente::{apuntar, flujo_con_tipo, flujo_de_texto};
use crate::routes::plan_estudio as pe;
use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{cuerpo, detalle, ejercicios, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn linea(v: Valor) -> String {
    prig_plataforma::json::escribir_linea(&v) + "\n"
}

fn json_dumps(v: &Valor) -> String {
    prig_plataforma::json::escribir_linea(v)
}

const SISTEMA_ORGANIZADOR: &str = r#"Eres el AGENTE ORGANIZADOR DE TEMAS EXPERTO EN PEDAGOGÍA.
Tu trabajo es tomar una meta y una lista desordenada de temas y organizarlos en un plan de aprendizaje secuencial (estilo Roadmap.sh o Duolingo). 

PARÁMETROS DEL ESTUDIANTE:
- Nivel Objetivo: {NIVEL}
- Enfoque Pedagógico: {ENFOQUE}

REGLAS PEDAGÓGICAS:
1. "Chunking": Divide los temas en bloques pequeños y digeribles (microaprendizaje).
2. Progresión: Adapta los temas al nivel ({NIVEL}) y el enfoque ({ENFOQUE}).
3. Todo bloque debe tener un `learning_objective` claro (qué logrará el estudiante).
4. Todo bloque debe tener un `validation_check` claro (un pequeño proyecto, test o acción para probar que lo aprendió).
        
Debes devolver ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{
  "goal": "La meta a alcanzar",
  "blocks": [
    {
      "title": "Nombre del bloque",
      "description": "Qué se debe lograr aquí",
      "learning_objective": "Competencia a adquirir (Ej: Ser capaz de crear un servidor local)",
      "validation_check": "Hito práctico (Ej: Inicializa un script que devuelva 'Hola' en localhost:8080)",
      "topics": ["tema1", "tema2"],
      "type": "theory | practice | project | mixed",
      "estimated_time": "ej: 2 horas"
    }
  ],
  "rationale": "Explicación breve de por qué los organizaste así basándote en pedagogía"
}"#;

const SISTEMA_QUIZ: &str = r#"Eres un GENERADOR DE QUIZZES PEDAGÓGICOS INTERACTIVOS.
Genera un Quiz de Autoevaluación corto de 3 preguntas de opción múltiple para verificar que el estudiante comprendió este bloque.

Debes devolver ÚNICAMENTE un objeto JSON válido con este formato:
{
  "block_title": "Título del Bloque",
  "questions": [
    {
      "id": 1,
      "question": "Pregunta clara sobre el tema",
      "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
      "correct_index": 0,
      "explanation": "Explicación de por qué la respuesta correcta es esa"
    }
  ]
}"#;

const SISTEMA_CLASE: &str = r#"Eres un TUTOR DE INTELIGENCIA ARTIFICIAL EXPERTO EN PROGRAMACIÓN Y TECNOLOGÍA.
Tu objetivo es dar una clase magistral profunda y detallada sobre un bloque de temas de una ruta de aprendizaje.
Sintoniza y profundiza la clase utilizando tanto tu conocimiento como la INFORMACIÓN Y DOCUMENTACIÓN OFICIAL DE INTERNET obtenida.

REGLAS PEDAGÓGICAS PARA TU RESPUESTA:
1. Explica los conceptos de forma clara, amena y profunda. Usa ejemplos de código reales.
2. Si los temas involucran flujos, lógica, secuencias o arquitectura, genera un DIAGRAMA VISUAL en sintaxis MERMAID (usando ```mermaid ... ```).
3. Integra sintaxis y mejores prácticas oficiales del contexto de internet si corresponden.
4. Si el contexto incluye enlaces o recursos oficiales, cítalos explícitamente.
5. Tu respuesta debe estar formateada en Markdown (títulos ##, ###, bloques de código ```).
"#;

const SISTEMA_RETO: &str = r##"Eres un EVALUADOR TÉCNICO DE PROGRAMACIÓN.
Genera un RETO DE CÓDIGO PRÁCTICO en formato JSON estricto con el siguiente esquema exacto:
{
  "challenge_title": "Título del reto",
  "instructions": "Instrucciones detalladas paso a paso sobre lo que el alumno debe programar",
  "starter_code": "# Código inicial de plantilla para completar\ndef mi_funcion():\n    # TODO: Implementar aquí\n    pass",
  "expected_output_hint": "Pista del resultado esperado o prueba de ejecución"
}"##;

const SISTEMA_REVISOR: &str = r#"Eres un REVISOR DE CÓDIGO TÉCNICO Y EVALUADOR PEDAGÓGICO.
Evalúa el código del alumno para el objetivo dado y responde con un JSON estricto:
{
  "passed": true / false,
  "score": 0 a 100,
  "feedback": "Explicación detallada y constructiva sobre el código",
  "suggestions": ["Sugerencia 1", "Sugerencia 2"],
  "corrected_code": "Código corregido o mejorado (opcional si aprobó)"
}"#;

// =========================================================================== el modelo

/// `generate_response` entero, con `on_thinking` (`pensando`: también pide el razonamiento) y `on_token`
fn generar(
    state: &AppState,
    cancelar: &Cancelar,
    prompt: String,
    sistema: &str,
    modelo: &str,
    mut pensando: Option<&mut dyn FnMut(&str)>,
    mut token: Option<&mut dyn FnMut(&str)>,
) -> String {
    let p = prig_ia::generar::PedidoGenerar {
        prompt,
        modelo: modelo.into(),
        sistema: sistema.into(),
        con_pensamiento: pensando.is_some(),
        gobernador: true,
        ..Default::default()
    };
    let mut r = String::new();
    prig_ia::generar::generar(&state.base_dir, &p, cancelar, &mut |e: Mapa| match e.texto("t") {
        Some("texto") => {
            let v = e.valor("v").texto_py();
            if e.verdad("token") {
                if let Some(f) = token.as_mut() {
                    f(&v);
                }
            }
            r.push_str(&v);
        }
        Some("pensando") => {
            if let Some(f) = pensando.as_mut() {
                f(&e.valor("v").texto_py());
            }
        }
        _ => {}
    });
    r
}

/// Una generación que «Detener» corta (como las que apunta `_cancelables` en Python)
fn cancelable() -> Arc<Cancelar> {
    let c = Arc::new(Cancelar::default());
    apuntar(&c);
    c
}

/// `str(block.get(clave))`
fn campo(bloque: &Mapa, clave: &str) -> String {
    bloque.get(clave).map(Valor::texto_py).unwrap_or_else(|| "None".into())
}

/// `sep.join(block.get('topics', []))`, con el TypeError de Python si no son textos
fn temas(bloque: &Mapa, sep: &str) -> Result<String, String> {
    prig_plataforma::py::unir(sep, bloque.get("topics").unwrap_or(&Valor::Lista(Vec::new())))
}

/// Lo que avisa el organizador de temas mientras trabaja
enum Aviso<'a> {
    Etapa(&'a str, i64),
    Pensando(&'a str),
    Token(&'a str),
}

/// `AIEngine.run_topic_organizer`: los temas ordenados en bloques (sin validar todavía). `oyentes`: quien pide quiere
/// el razonamiento y los trozos (el streaming)
fn organizar_temas(
    state: &AppState,
    c: &Cancelar,
    objetivo: &str,
    temas_txt: &str,
    nivel: &str,
    enfoque: &str,
    modelo: &str,
    oyentes: bool,
    avisar: &mut dyn FnMut(Aviso),
) -> Result<Mapa, String> {
    avisar(Aviso::Etapa("Analizando temas pedagógicos y preparando directivas...", 25));
    let sistema = SISTEMA_ORGANIZADOR.replace("{NIVEL}", nivel).replace("{ENFOQUE}", enfoque);
    let prompt = format!("Meta: {objetivo}\nTemas:\n{temas_txt}\nNivel: {nivel}\nEnfoque: {enfoque}");
    let avisar = std::cell::RefCell::new(avisar);
    let mut empezado = false;
    let mut al_pensar = |t: &str| (avisar.borrow_mut())(Aviso::Pensando(t));
    let mut al_token = |t: &str| {
        if !empezado {
            empezado = true;
            (avisar.borrow_mut())(Aviso::Etapa("El modelo está deduciendo la progresión pedagógica y redactando los bloques...", 55));
        }
        if oyentes {
            (avisar.borrow_mut())(Aviso::Token(t));
        }
    };
    let pensando: Option<&mut dyn FnMut(&str)> = if oyentes { Some(&mut al_pensar) } else { None };
    let texto = generar(state, c, prompt, &sistema, modelo, pensando, Some(&mut al_token));
    (avisar.borrow_mut())(Aviso::Etapa("Estructurando bloques pedagógicos y validando formato...", 88));
    let mut d = prig_ia::json_modelo::reparar(&texto)?;
    if !matches!(d.get("blocks"), Some(Valor::Lista(_))) {
        d.poner("blocks", Valor::Lista(Vec::new()));
    }
    d.poner("goal", objetivo);
    let mut bloques = d.lista("blocks").map(|l| l.to_vec()).unwrap_or_default();
    for (i, b) in bloques.iter_mut().enumerate() {
        let Valor::Mapa(b) = b else { continue };
        if !b.verdad("title") {
            b.poner("title", format!("Bloque {}", i + 1));
        }
        if !b.verdad("description") {
            b.poner("description", format!("Estudio práctico del bloque {}.", i + 1));
        }
        match b.get("topics") {
            Some(Valor::Lista(_)) => {}
            Some(Valor::Texto(t)) => {
                let t = t.clone();
                b.poner("topics", Valor::Lista(vec![Valor::Texto(t)]));
            }
            _ => b.poner("topics", Valor::Lista(vec![Valor::Texto("Tema General".into())])),
        }
        if !matches!(b.texto("type"), Some("theory" | "practice" | "project" | "mixed")) {
            b.poner("type", "practice");
        }
    }
    d.poner("blocks", Valor::Lista(bloques));
    Ok(d)
}

// =========================================================================== generar una ruta

/// El cuerpo de `GuidedGenerateRequest`
struct Pedido {
    objetivo: String,
    temas: String,
    nivel: String,
    enfoque: String,
    modo: String,
    modelo: String,
}

fn pedido(b: &Bytes) -> Result<Pedido, Response> {
    let m = cuerpo::modelo(b)?;
    let mut c = cuerpo::Campos::new(&m);
    let objetivo = c.texto("goal", None);
    let temas = c.texto("topics", Some(Valor::Texto(String::new())));
    let nivel = c.texto("level", Some(Valor::Texto("Intermedio".into())));
    let enfoque = c.texto("focus", Some(Valor::Texto("Práctico".into())));
    let modo = c.texto("mode", Some(Valor::Texto("rapido".into())));
    let modelo = c.texto("model", Some(Valor::Texto(pe::MODELO.into())));
    c.fin()?;
    Ok(Pedido {
        objetivo: objetivo.texto_py(),
        temas: temas.texto_py(),
        nivel: nivel.texto_py(),
        enfoque: enfoque.texto_py(),
        modo: modo.texto_py(),
        modelo: modelo.texto_py(),
    })
}

/// `SeguimientoRepository.save` (la carpeta la crea el repositorio al abrirse)
fn guardar(espacio: &Path, s: &Mapa) -> Result<(), String> {
    std::fs::create_dir_all(espacio.join(".prig_seguimientos")).map_err(|e| e.to_string())?;
    planes::guardar_seguimiento(espacio, s).map_err(|e| e.to_string())
}

/// `generate_fast`: el organizador de temas, validado como ruta y guardado
fn ruta_rapida(state: &AppState, espacio: &Path, c: &Cancelar, p: &Pedido, oyentes: bool, avisar: &mut dyn FnMut(Aviso)) -> Result<Mapa, String> {
    let crudo = organizar_temas(state, c, &p.objetivo, &p.temas, &p.nivel, &p.enfoque, &p.modelo, oyentes, avisar)?;
    let mut s = planes::validar_modelo(&planes::RUTA, Valor::Mapa(crudo))?;
    s.poner("goal", p.objetivo.as_str());
    s.poner("topics_raw", p.temas.as_str());
    s.poner("source", "rapido");
    s.poner("level", p.nivel.as_str());
    s.poner("focus", p.enfoque.as_str());
    guardar(espacio, &s)?;
    Ok(s)
}

/// La traza de un agente en la ruta
fn traza(agente: &str, resumen: String, avisos: Vec<String>) -> Valor {
    Valor::Mapa(
        Mapa::new()
            .con("agent", agente)
            .con("summary", resumen)
            .con("warnings", Valor::Lista(avisos.into_iter().map(Valor::Texto).collect())),
    )
}

fn largo(m: &Mapa, k: &str) -> usize {
    m.lista(k).map_or(0, |l| l.len())
}

fn hijos<'a>(m: &'a Mapa, k: &str) -> impl Iterator<Item = &'a Mapa> {
    m.lista(k).unwrap_or(&[]).iter().filter_map(|v| if let Valor::Mapa(x) = v { Some(x) } else { None })
}

/// Un agente del plan, con la respuesta como el modelo pedido (el error, como `str(err)`)
fn agente(state: &AppState, c: &Cancelar, prompt: String, sistema: &str, modelo: &str, m: &prig_plataforma::modelo::Modelo, oyentes: &mut Option<&mut dyn FnMut(Aviso)>) -> Result<Mapa, String> {
    let texto = match oyentes {
        Some(avisar) => {
            let avisar = std::cell::RefCell::new(avisar);
            let mut al_pensar = |t: &str| (avisar.borrow_mut())(Aviso::Pensando(t));
            let mut al_token = |t: &str| (avisar.borrow_mut())(Aviso::Token(t));
            generar(state, c, prompt, sistema, modelo, Some(&mut al_pensar), Some(&mut al_token))
        }
        None => generar(state, c, prompt, sistema, modelo, None, None),
    };
    planes::validar_modelo(m, Valor::Mapa(prig_ia::json_modelo::reparar(&texto)?))
}

/// `open(ruta, encoding="utf-8", errors="ignore").read()`: sin los bytes que no son UTF-8 y con los saltos de línea
/// universales
fn leer_ignorando(ruta: &str) -> Option<String> {
    let b = std::fs::read(ruta).ok()?;
    let t: String = b.utf8_chunks().map(|c| c.valid()).collect();
    Some(t.replace("\r\n", "\n").replace('\r', "\n"))
}

/// `_materialize_notebooks`: un cuaderno explicado por cada uno del plan, en `notebooks_plan/` (nunca en la biblioteca)
fn materializar(espacio: &Path, ej: &Mapa, curr: &Mapa) -> Result<Vec<Valor>, String> {
    let destino = std::path::PathBuf::from(prig_plataforma::py::abspath(&espacio.to_string_lossy())).join("notebooks_plan");
    std::fs::create_dir_all(&destino).map_err(|e| e.to_string())?;
    let mut modulos: Vec<(Valor, &Mapa)> = Vec::new();
    for m in hijos(curr, "modules") {
        let k = m.valor("module_id").clone();
        match modulos.iter_mut().find(|(x, _)| *x == k) {
            Some(e) => e.1 = m,
            None => modulos.push((k, m)),
        }
    }
    let bib = pe::biblioteca();
    let mut creados = Vec::new();
    for m in hijos(ej, "modules_notebooks") {
        let mid = m.valor("module_id").clone();
        let base = modulos.iter().find(|(k, _)| *k == mid).map(|(_, c)| *c);
        for nb in hijos(m, "notebooks") {
            let ruta = destino.join(format!("{}_{}.ipynb", mid.texto_py(), nb.valor("notebook_id").texto_py()));
            let fuente = match nb.get("source_library_notebook") {
                Some(Valor::Texto(f)) if !f.is_empty() && Path::new(f).exists() => leer_ignorando(f).unwrap_or_default(),
                _ => String::new(),
            };
            let (nombre, objetivo, criterios) = match base {
                Some(b) => (b.valor("name").texto_py(), b.valor("objective").texto_py(), b.lista("validation_criteria").map(|l| l.to_vec()).unwrap_or_default()),
                None => (m.valor("module_name").texto_py(), "Practicar los conceptos del módulo".to_string(), Vec::new()),
            };
            let contenido = planes::cuaderno_explicado(&nombre, &objetivo, &criterios, &fuente);
            match planes::escribir_cuaderno(&ruta, &contenido, &bib) {
                Ok(escrito) => {
                    let titulo = match nb.get("title") {
                        Some(t) if t.verdad() => t.clone(),
                        _ => m.get("module_name").cloned().unwrap_or(Valor::Nulo),
                    };
                    creados.push(Valor::Mapa(Mapa::new().con("block_id", format!("blk_{}", mid.texto_py())).con("title", titulo).con("path", escrito)));
                }
                Err(e) => println!("Advertencia al generar cuaderno: {e}"),
            }
        }
    }
    Ok(creados)
}

/// `generate_deep` (y su versión en streaming, con `oyentes`): los tres agentes volcados a una ruta. `etapa` avisa del
/// paso en que va (solo en streaming)
fn ruta_profunda(
    state: &AppState,
    espacio: &Path,
    c: &Cancelar,
    p: &Pedido,
    mut oyentes: Option<&mut dyn FnMut(Aviso)>,
    etapa: &mut dyn FnMut(i64, &str, i64),
) -> Result<Mapa, String> {
    etapa(1, "Explorando biblioteca y analizando libros/documentos...", 10);
    let biblioteca = pe::libros(state);
    let mut trazas = Vec::new();

    etapa(2, "Agente 1 (Knowledge Architect): Diseñando mapa conceptual y dependencias...", 30);
    let prompt = format!("Objetivo: '{}'\nFuentes disponibles en la biblioteca: {}", p.objetivo, json_dumps(&pe::fuentes_de(&biblioteca)));
    let km = agente(state, c, prompt, pe::SISTEMA_1, &p.modelo, &planes::MAPA, &mut oyentes)?;
    trazas.push(traza(
        "Knowledge Architect",
        format!("{} dominios · {} prerrequisitos", largo(&km, "domains"), largo(&km, "prerequisites")),
        planes::avisos_mapa(&km),
    ));

    etapa(3, "Agente 2 (Practice Architect): Construyendo currículo y módulos prácticos...", 60);
    let prompt = format!("KNOWLEDGE_MAP:\n{}", json_dumps(&Valor::Mapa(km.clone())));
    let curr = agente(state, c, prompt, pe::SISTEMA_2, &p.modelo, &planes::CURRICULO, &mut oyentes)?;
    trazas.push(traza("Practice Architect", format!("{} módulos prácticos", largo(&curr, "modules")), planes::avisos_curriculo(&curr, &km)));

    etapa(4, "Agente 3 (Notebook Manager): Generando cuadernos interactivos Jupyter...", 80);
    let mut nombres: Vec<(Valor, Valor)> = Vec::new();
    for d in hijos(&km, "domains") {
        for t in hijos(d, "topics") {
            for co in hijos(t, "concepts") {
                let (id, nombre) = (co.valor("concept_id").clone(), co.valor("name").clone());
                match nombres.iter_mut().find(|(k, _)| *k == id) {
                    Some(e) => e.1 = nombre,
                    None => nombres.push((id, nombre)),
                }
            }
        }
    }
    let temas_raw = if p.temas.is_empty() {
        let todos: Vec<String> = hijos(&km, "domains")
            .flat_map(|d| hijos(d, "topics"))
            .flat_map(|t| hijos(t, "concepts"))
            .map(|co| co.valor("name").texto_py())
            .collect();
        todos.join(", ").chars().take(2000).collect()
    } else {
        p.temas.clone()
    };
    let racional = match km.get("goal") {
        Some(g) if g.verdad() => g.clone(),
        _ => Valor::Texto("Ruta generada con análisis profundo.".into()),
    };
    let mut s = planes::validar_modelo(
        &planes::RUTA,
        Valor::Mapa(
            Mapa::new()
                .con("goal", p.objetivo.as_str())
                .con("topics_raw", temas_raw)
                .con("rationale", racional)
                .con("source", "profundo")
                .con("level", p.nivel.as_str())
                .con("focus", p.enfoque.as_str())
                .con("knowledge_map", Valor::Mapa(km.clone()))
                .con("decision_traces", Valor::Lista(trazas.clone())),
        ),
    )?;
    let mut bloques = Vec::new();
    for m in hijos(&curr, "modules") {
        let temas: Vec<Valor> = m
            .lista("concepts")
            .unwrap_or(&[])
            .iter()
            .map(|cid| nombres.iter().find(|(k, _)| k == cid).map(|(_, n)| n.clone()).unwrap_or_else(|| cid.clone()))
            .collect();
        let criterios = m.lista("validation_criteria").unwrap_or(&[]);
        let objetivo = m.get("objective").filter(|o| o.verdad());
        let b = Mapa::new()
            .con("block_id", format!("blk_{}", m.valor("module_id").texto_py()))
            .con("title", m.valor("name").clone())
            .con("description", objetivo.cloned().unwrap_or_else(|| Valor::Texto(format!("Practicar {}.", m.valor("name").texto_py()))))
            .con("learning_objective", objetivo.cloned().unwrap_or(Valor::Texto(String::new())))
            .con("validation_check", criterios.first().cloned().unwrap_or(Valor::Texto("Resolver el ejercicio del bloque sin ayuda.".into())))
            .con("topics", if temas.is_empty() { Valor::Lista(vec![m.valor("name").clone()]) } else { Valor::Lista(temas) })
            .con("type", "practice");
        bloques.push(Valor::Mapa(planes::validar_modelo(&planes::BLOQUE, Valor::Mapa(b))?));
    }
    s.poner("blocks", Valor::Lista(bloques));

    // Agente 3: opcional (si falla, la ruta sigue sirviendo)
    let (_, resumen) = pe::codigo_de(biblioteca);
    let prompt = format!("CURRICULUM:\n{}\n\nCUADERNOS Y CÓDIGO DISPONIBLES EN LA BIBLIOTECA:\n{}", json_dumps(&Valor::Mapa(curr.clone())), json_dumps(&resumen));
    let tercero = agente(state, c, prompt, pe::SISTEMA_3, &p.modelo, &planes::PLAN_EJECUTABLE, &mut oyentes).and_then(|ej| {
        let cuadernos = materializar(espacio, &ej, &curr)?;
        Ok((ej, cuadernos))
    });
    match tercero {
        Ok((ej, cuadernos)) => {
            let n = cuadernos.len();
            s.poner("notebooks", Valor::Lista(cuadernos));
            trazas.push(traza("Notebook Manager", format!("{n} cuadernos generados"), planes::avisos_ejecutable(&ej, &curr)));
        }
        Err(e) => trazas.push(traza("Notebook Manager", "No se generaron cuadernos".into(), vec![e])),
    }

    etapa(5, "Finalizando y guardando ruta profunda...", 95);
    s.poner("decision_traces", Valor::Lista(trazas));
    guardar(espacio, &s)?;
    Ok(s)
}

/// `POST /api/guided/generate`: una sola puerta de entrada; la diferencia es la profundidad del análisis
pub async fn generar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let p = match pedido(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    if p.modo != "profundo" && prig_plataforma::py::strip(&p.temas).is_empty() {
        return detalle(StatusCode::BAD_REQUEST, "El modo rápido necesita una lista de temas.");
    }
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || {
        let c = cancelable();
        if p.modo == "profundo" {
            ruta_profunda(&state, &espacio, &c, &p, None, &mut |_, _, _| {})
        } else {
            ruta_rapida(&state, &espacio, &c, &p, false, &mut |_| {})
        }
    })
    .await;
    match r {
        Ok(Ok(s)) => json_py(StatusCode::OK, &Valor::Mapa(s)),
        Ok(Err(e)) => detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("No se pudo generar la ruta: {e}")),
        Err(_) => error_500(),
    }
}

fn evento_etapa(n: i64, total: i64, mensaje: &str, pct: i64) -> Valor {
    Valor::Mapa(Mapa::new().con("type", "stage").con("stage_num", n).con("total_stages", total).con("message", mensaje).con("pct", pct))
}

fn evento_texto(tipo: &str, t: &str) -> Valor {
    Valor::Mapa(Mapa::new().con("type", tipo).con("text", t))
}

fn evento_error(e: &str) -> Valor {
    Valor::Mapa(Mapa::new().con("type", "error").con("message", e))
}

/// `POST /api/guided/generate/stream`: las etapas, el razonamiento del modelo, sus trozos y la ruta, en NDJSON
pub async fn generar_ruta_flujo(State(state): State<AppState>, b: Bytes) -> Response {
    let p = match pedido(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    flujo_con_tipo("application/x-ndjson", move |c, enviar| {
        let profundo = p.modo == "profundo";
        if !profundo && prig_plataforma::py::strip(&p.temas).is_empty() {
            enviar(linea(evento_error("El modo rápido necesita una lista de temas.")));
            return;
        }
        let enviar = std::cell::RefCell::new(enviar);
        let mut avisar = |a: Aviso| {
            let ev = match a {
                Aviso::Etapa(m, pct) => evento_etapa(if pct <= 20 { 1 } else if pct <= 40 { 2 } else if pct <= 75 { 3 } else { 4 }, 4, m, pct),
                Aviso::Pensando(t) => evento_texto("thought", t),
                Aviso::Token(t) => evento_texto("token", t),
            };
            (enviar.borrow_mut())(linea(ev));
        };
        let r = if profundo {
            let mut etapa = |n: i64, m: &str, pct: i64| (enviar.borrow_mut())(linea(evento_etapa(n, 5, m, pct)));
            let mut solo_texto = |a: Aviso| match a {
                Aviso::Pensando(t) => (enviar.borrow_mut())(linea(evento_texto("thought", t))),
                Aviso::Token(t) => (enviar.borrow_mut())(linea(evento_texto("token", t))),
                Aviso::Etapa(..) => {}
            };
            ruta_profunda(&state, &espacio, c, &p, Some(&mut solo_texto), &mut etapa)
        } else {
            (enviar.borrow_mut())(linea(evento_etapa(1, 4, &format!("Conectando con Ollama y cargando modelo {}...", p.modelo), 10)));
            ruta_rapida(&state, &espacio, c, &p, true, &mut avisar)
        };
        let mut enviar = enviar.borrow_mut();
        match r {
            Err(e) => enviar(linea(evento_error(&e))),
            Ok(s) => {
                let (total, mensaje) = if profundo { (5, "¡Plan de aprendizaje profundo generado con éxito!") } else { (4, "¡Plan de aprendizaje generado con éxito!") };
                enviar(linea(evento_etapa(total, total, mensaje, 100)));
                enviar(linea(Valor::Mapa(Mapa::new().con("type", "done").con("path", Valor::Mapa(s)))));
            }
        }
    })
}

// =========================================================================== migrar los planes antiguos

/// `_plan_to_path`: un plan de estudio pasa a ser una ruta, conservando su progreso
fn plan_a_ruta(plan: &Mapa) -> Result<Mapa, String> {
    let objetivo = plan.valor("user_goal").clone();
    let km = match plan.get("knowledge_map") {
        Some(k) if k.verdad() => k.clone(),
        _ => Valor::Nulo,
    };
    let mut s = planes::validar_modelo(
        &planes::RUTA,
        Valor::Mapa(
            Mapa::new()
                .con("goal", objetivo.clone())
                .con("source", "migrado")
                .con("origin_plan_id", plan.valor("plan_id").clone())
                .con("created_at", plan.valor("created_at").clone())
                .con("rationale", "Plan de estudio migrado al sistema de Aprendizaje Guiado.")
                .con("knowledge_map", km),
        ),
    )?;
    let completados: Vec<Valor> = plan.lista("completed_notebooks").unwrap_or(&[]).to_vec();
    let criterios_hechos = plan.mapa("completed_validation_criteria").cloned().unwrap_or_default();
    let fecha = match plan.get("updated_at") {
        Some(f) if f.verdad() => f.clone(),
        _ => plan.valor("created_at").clone(),
    };
    let (mut bloques, mut hechos, mut fechas) = (Vec::new(), Vec::new(), Mapa::new());
    let curr = plan.mapa("practical_curriculum").cloned();
    for m in curr.as_ref().map(|c| hijos(c, "modules").collect::<Vec<_>>()).unwrap_or_default() {
        let mid = m.valor("module_id").texto_py();
        let bid = format!("blk_{mid}");
        let criterios = m.lista("validation_criteria").unwrap_or(&[]);
        let conceptos = m.lista("concepts").unwrap_or(&[]).to_vec();
        let objetivo_m = m.get("objective").filter(|o| o.verdad());
        let b = Mapa::new()
            .con("block_id", bid.as_str())
            .con("title", m.valor("name").clone())
            .con("description", objetivo_m.cloned().unwrap_or_else(|| Valor::Texto(format!("Practicar {}.", m.valor("name").texto_py()))))
            .con("learning_objective", objetivo_m.cloned().unwrap_or(Valor::Texto(String::new())))
            .con("validation_check", criterios.first().cloned().unwrap_or(Valor::Texto("Completar el módulo.".into())))
            .con("topics", if conceptos.is_empty() { Valor::Lista(vec![m.valor("name").clone()]) } else { Valor::Lista(conceptos) })
            .con("type", "practice");
        bloques.push(Valor::Mapa(planes::validar_modelo(&planes::BLOQUE, Valor::Mapa(b))?));
        let n_hechos = criterios_hechos.lista(&mid).map_or(0, |l| l.len());
        if (!criterios.is_empty() && n_hechos >= criterios.len()) || completados.contains(&Valor::Texto(bid.clone())) {
            hechos.push(Valor::Texto(bid.clone()));
            fechas.poner(bid, fecha.clone());
        }
    }
    if bloques.is_empty() {
        let b = Mapa::new()
            .con("block_id", "blk_meta")
            .con("title", objetivo.clone())
            .con("description", "Plan migrado sin módulos prácticos generados.")
            .con("topics", Valor::Lista(vec![objetivo]))
            .con("type", "theory");
        bloques.push(Valor::Mapa(planes::validar_modelo(&planes::BLOQUE, Valor::Mapa(b))?));
    }
    s.poner("blocks", Valor::Lista(bloques));
    s.poner("completed_blocks", Valor::Lista(hechos));
    s.poner("completion_dates", Valor::Mapa(fechas));
    Ok(s)
}

/// `POST /api/guided/migrate`: trae los planes de estudio antiguos al sistema unificado. Idempotente
pub async fn migrar(State(state): State<AppState>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, ()> {
        let _ = std::fs::create_dir_all(espacio.join(".prig_seguimientos"));
        let mut ya: Vec<Valor> = Vec::new();
        for ruta in planes::jsons(&espacio.join(".prig_seguimientos")) {
            let Ok(doc) = prig_plataforma::leer_json(&ruta) else { continue };
            // `p.get(...)` de un JSON que no es un objeto: AttributeError
            let Valor::Mapa(doc) = doc else { return Err(()) };
            if let Some(o) = doc.get("origin_plan_id").filter(|o| o.verdad()) {
                if !ya.contains(o) {
                    ya.push(o.clone());
                }
            }
        }
        let (mut migrados, mut fallidos) = (Vec::new(), Vec::new());
        for manifiesto in planes::listar_planes(&espacio) {
            let id = match manifiesto.get("plan_id") {
                Some(i) if i.verdad() && !ya.contains(i) => i.texto_py(),
                _ => continue,
            };
            let hecho = planes::cargar_plan(&espacio, &id).and_then(|p| match p {
                Some(p) => {
                    let s = plan_a_ruta(&p)?;
                    guardar(&espacio, &s)?;
                    Ok(Some(s))
                }
                None => Ok(None),
            });
            match hecho {
                Ok(Some(s)) => migrados.push(Valor::Mapa(Mapa::new().con("plan_id", id).con("path_id", s.valor("id").clone()).con("goal", s.valor("goal").clone()))),
                Ok(None) => {}
                Err(e) => fallidos.push(Valor::Mapa(Mapa::new().con("plan_id", id).con("error", e))),
            }
        }
        Ok(Mapa::new()
            .con("migrated", Valor::Lista(migrados))
            .con("failed", Valor::Lista(fallidos))
            .con("already", ya.len())
            .con("total_paths", planes::listar_seguimientos(&espacio).len()))
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        _ => error_500(),
    }
}

// =========================================================================== seguimiento (obsoleto)

/// `POST /api/seguimiento/generate`: OBSOLETO (usa `/api/guided/generate`), se mantiene por compatibilidad
pub async fn seguimiento_generar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let objetivo = c.texto("goal", None).texto_py();
    let temas = c.texto("topics", None).texto_py();
    let nivel = c.texto("level", Some(Valor::Texto("Intermedio".into()))).texto_py();
    let enfoque = c.texto("focus", Some(Valor::Texto("Práctico".into()))).texto_py();
    let modelo = c.texto("model", Some(Valor::Texto(pe::MODELO.into()))).texto_py();
    if let Err(r) = c.fin() {
        return r;
    }
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, String> {
        let c = cancelable();
        let crudo = organizar_temas(&state, &c, &objetivo, &temas, &nivel, &enfoque, &modelo, false, &mut |_| {})?;
        let mut s = planes::validar_modelo(&planes::RUTA, Valor::Mapa(crudo))?;
        s.poner("goal", objetivo.as_str());
        s.poner("topics_raw", temas.as_str());
        guardar(&espacio, &s)?;
        Ok(s)
    })
    .await;
    match r {
        Ok(Ok(s)) => json_py(StatusCode::OK, &Valor::Mapa(s)),
        Ok(Err(e)) => detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("Error al generar el seguimiento: {e}")),
        Err(_) => error_500(),
    }
}

// =========================================================================== un bloque: clase, quiz, reto y corrección

/// Los campos de las peticiones de un bloque: `goal`, `block` (un dict) y `model`, más los propios
fn pedido_bloque(b: &Bytes, extra: &[(&'static str, &'static Tipo, bool)]) -> Result<(String, Mapa, String, Mapa), Response> {
    static DICT: Tipo = Tipo::Dict(&Tipo::Cualquiera);
    let m = cuerpo::modelo(b)?;
    let mut campos: Vec<(&str, &Tipo, bool)> = vec![("goal", &Tipo::Texto, true), ("block", &DICT, true), ("model", &Tipo::Texto, false)];
    campos.extend_from_slice(extra);
    let c = cuerpo::tipados(&m, &campos)?;
    let objetivo = c.valor("goal").texto_py();
    let bloque = c.mapa("block").cloned().unwrap_or_default();
    let modelo = c.get("model").map(Valor::texto_py).unwrap_or_else(|| pe::MODELO.into());
    Ok((objetivo, bloque, modelo, c))
}

/// `POST /api/guided/explain` y `/api/seguimiento/explain` (`use_web = True`): la clase del bloque, en texto
pub async fn explicar(State(state): State<AppState>, b: Bytes) -> Response {
    let (objetivo, bloque, modelo, c) = match pedido_bloque(&b, &[("use_web", &Tipo::Booleano, false)]) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let web = c.get("use_web").map(|v| v.verdad()).unwrap_or(true);
    flujo_de_texto(move |cancelar, enviar| {
        let r = (|| -> Result<(), String> {
            let titulo = bloque.get("title").cloned().unwrap_or(Valor::Texto(String::new())).texto_py();
            let tema = format!("{titulo} {} {objetivo}", temas(&bloque, " ")?);
            let (extra, _) = prig_biblioteca::referencias_ml::con_referencias(&state.base_dir, &tema, "");
            let (contexto, fuentes) = if web { prig_ia::web::contexto_web(&format!("{titulo} {}", temas(&bloque, " ")?)) } else { (String::new(), Valor::Lista(Vec::new())) };
            let prompt = format!(
                "Meta del Alumno: {objetivo}\n\nBloque a Explicar:\n- Título: {}\n- Temas: {}\n- Objetivo: {}\n- Validación: {}\n\n{contexto}\n{extra}\n¡Por favor, dame la clase!",
                campo(&bloque, "title"),
                temas(&bloque, ", ")?,
                campo(&bloque, "learning_objective"),
                campo(&bloque, "validation_check")
            );
            let p = prig_ia::generar::PedidoGenerar { prompt, modelo: modelo.clone(), sistema: SISTEMA_CLASE.into(), gobernador: true, ..Default::default() };
            prig_ia::generar::generar(&state.base_dir, &p, cancelar, &mut |e: Mapa| {
                if e.texto("t") == Some("texto") {
                    enviar(e.valor("v").texto_py());
                }
            });
            let fuentes = match fuentes {
                Valor::Lista(l) => l,
                _ => Vec::new(),
            };
            if !fuentes.is_empty() {
                enviar("\n\n---\n**🌐 Fuentes Oficiales de Internet Consultadas:**\n".into());
                for s in fuentes {
                    let Valor::Mapa(s) = s else { continue };
                    enviar(format!("- [{}]({}) (`{}`)\n", s.valor("title").texto_py(), s.valor("url").texto_py(), s.valor("domain").texto_py()));
                }
            }
            Ok(())
        })();
        if let Err(e) = r {
            enviar(format!("\n[Error: {e}]"));
        }
    })
}

/// Una respuesta del modelo en JSON (`_extract_and_parse_json`)
fn json_del_modelo(state: &AppState, prompt: String, sistema: &str, modelo: &str) -> Result<Mapa, String> {
    let c = cancelable();
    prig_ia::json_modelo::reparar(&generar(state, &c, prompt, sistema, modelo, None, None))
}

/// El prompt del quiz y del reto antiguo
fn prompt_bloque(prefijo: &str, objetivo: &str, bloque: &Mapa) -> Result<String, String> {
    Ok(format!(
        "{prefijo}{objetivo}\nBloque: {}\nTemas: {}\nObjetivo: {}",
        campo(bloque, "title"),
        temas(bloque, ", ")?,
        campo(bloque, "learning_objective")
    ))
}

/// `POST /api/guided/quiz` y `/api/seguimiento/quiz`: tres preguntas de opción múltiple sobre el bloque
pub async fn quiz(State(state): State<AppState>, b: Bytes) -> Response {
    let (objetivo, bloque, modelo, _) = match pedido_bloque(&b, &[]) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let r = tokio::task::spawn_blocking(move || json_del_modelo(&state, prompt_bloque("Meta: ", &objetivo, &bloque)?, SISTEMA_QUIZ, &modelo)).await;
    match r {
        Ok(Ok(q)) => json_py(StatusCode::OK, &Valor::Mapa(q)),
        Ok(Err(e)) => detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("Error al generar quiz: {e}")),
        Err(_) => error_500(),
    }
}

/// `POST /api/guided/challenge` y `/api/seguimiento/challenge`: el reto del bloque como ejercicio VERIFICADO (tests
/// ocultos y comprobado ejecutándolo). Si no sale ninguno válido, el reto antiguo, avisando de que no se corrige solo
pub async fn reto(State(state): State<AppState>, b: Bytes) -> Response {
    let (objetivo, bloque, modelo, _) = match pedido_bloque(&b, &[]) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, String> {
        let unidos = match bloque.get("topics") {
            None => Ok(String::new()),
            Some(t) => prig_plataforma::py::unir(", ", t),
        };
        let concepto = unidos.map(|temas| {
            let temas = if temas.is_empty() { bloque.get("title").cloned().unwrap_or(Valor::Texto(String::new())).texto_py() } else { temas };
            let titulo = bloque.get("title").cloned().unwrap_or(Valor::Texto(String::new())).texto_py();
            prig_plataforma::py::strip(&format!("{titulo} ({temas})")).to_string()
        });
        if let Ok(concepto) = &concepto {
            if let Some((Some(mut e), _)) = ejercicios::generar_verificado(&state, concepto, &modelo, "intermedio", 3) {
                ejercicios::guardar_y_anotar(&espacio, &mut e, concepto);
                let f = |k: &str| e.get(k).cloned().unwrap_or(Valor::Texto(String::new()));
                return Ok(Mapa::new()
                    .con("verified", true)
                    .con("exercise_id", e.valor("exercise_id").clone())
                    .con("challenge_title", f("title"))
                    .con("instructions", f("statement"))
                    .con("starter_code", f("starter_code"))
                    .con("function_name", f("function_name"))
                    .con("expected_output_hint", format!("Debe definir {} y pasar los tests ocultos.", f("function_name").texto_py())));
            }
        } else if let Err(e) = &concepto {
            return Err(e.clone());
        }
        let mut r = json_del_modelo(&state, prompt_bloque("Meta del Alumno: ", &objetivo, &bloque)?, SISTEMA_RETO, &modelo)?;
        r.poner("verified", false);
        Ok(r)
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e)) => detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("Error al generar reto: {e}")),
        Err(_) => error_500(),
    }
}

/// `POST /api/guided/verify-solution` y `/api/seguimiento/verify-solution`: si el reto es un ejercicio verificado, se
/// EJECUTA el código contra sus tests; si no, solo queda la valoración del modelo, y se dice
pub async fn verificar(State(state): State<AppState>, b: Bytes) -> Response {
    static OPT: Tipo = Tipo::Opcional(&Tipo::Texto);
    let (objetivo, bloque, modelo, c) = match pedido_bloque(&b, &[("user_code", &Tipo::Texto, true), ("exercise_id", &OPT, false)]) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let codigo = c.valor("user_code").texto_py();
    let id = c.get("exercise_id").filter(|v| v.verdad()).map(Valor::texto_py);
    if let Some(id) = id {
        let (espacio, ejercicio) = ejercicios::uno(&state, id.clone()).await;
        if let Some(e) = ejercicio.filter(|e| !e.is_empty()) {
            let Some(tests) = e.get("tests").map(Valor::texto_o_repr) else { return error_500() };
            let r = tokio::task::spawn_blocking(move || {
                let v = ejercicios::corregir(&state, &codigo, &tests);
                if ejercicios::telemetria_activa() {
                    use prig_aprendizaje::telemetria as t;
                    let concepto = e.get("concept").map(Valor::texto_py).unwrap_or_default();
                    let hecho = t::abrir(&espacio).and_then(|cx| {
                        let intento = t::numero_intento(&cx, &id)?;
                        t::registrar(
                            &cx,
                            &t::Evento {
                                ejercicio: &id,
                                concepto: &concepto,
                                tipo: "submission",
                                aprobado: Some(v.verdad("passed")),
                                intento,
                                pistas: 0,
                                stderr: v.texto("stderr").unwrap_or_default(),
                                segundos: v.get("elapsed").and_then(Valor::num).unwrap_or(0.0),
                            },
                        )
                    });
                    if let Err(e) = hecho {
                        tracing::warn!("telemetría: {e}");
                    }
                }
                let aprobado = v.verdad("passed");
                Mapa::new()
                    .con("verified_by_execution", true)
                    .con("passed", aprobado)
                    .con("score", if aprobado { 100 } else { 0 })
                    .con("feedback", v.valor("reason").clone())
                    .con("stdout", v.get("stdout").cloned().unwrap_or(Valor::Texto(String::new())))
                    .con("stderr", v.get("stderr").cloned().unwrap_or(Valor::Texto(String::new())))
                    .con("suggestions", Valor::Lista(Vec::new()))
            })
            .await;
            return match r {
                Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
                Err(_) => error_500(),
            };
        }
    }
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, String> {
        let prompt = format!(
            "Meta: {objetivo}\nBloque: {}\nObjetivo: {}\nValidación Esperada: {}\n\nCÓDIGO DEL ALUMNO:\n```python\n{codigo}\n```",
            campo(&bloque, "title"),
            campo(&bloque, "learning_objective"),
            campo(&bloque, "validation_check")
        );
        let mut r = json_del_modelo(&state, prompt, SISTEMA_REVISOR, &modelo)?;
        r.poner("verified_by_execution", false);
        Ok(r)
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e)) => detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("Error al verificar solución: {e}")),
        Err(_) => error_500(),
    }
}

// =========================================================================== el cuaderno de la ruta

fn celda_md(fuente: Vec<String>) -> Valor {
    Valor::Mapa(Mapa::new().con("cell_type", "markdown").con("metadata", Valor::Mapa(Mapa::new())).con("source", Valor::Lista(fuente.into_iter().map(Valor::Texto).collect())))
}

fn celda_codigo(fuente: Vec<String>) -> Valor {
    Valor::Mapa(
        Mapa::new()
            .con("cell_type", "code")
            .con("execution_count", Valor::Nulo)
            .con("metadata", Valor::Mapa(Mapa::new()))
            .con("outputs", Valor::Lista(Vec::new()))
            .con("source", Valor::Lista(fuente.into_iter().map(Valor::Texto).collect())),
    )
}

/// `POST /api/guided/{id}/generate-notebook` y `/api/seguimiento/{id}/generate-notebook`: un cuaderno Jupyter con un
/// bloque de teoría, uno de código y un reto por cada bloque, en la carpeta de trabajo
pub async fn cuaderno(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Option<Mapa>, String> {
        let Some(s) = planes::cargar_seguimiento(&espacio, &id)? else { return Ok(None) };
        let objetivo = s.valor("goal").texto_py();
        let bloques: Vec<&Mapa> = hijos(&s, "blocks").collect();
        let mut celdas = vec![celda_md(vec![
            format!("# 📓 Cuaderno de Aprendizaje: {objetivo}\n"),
            format!("**Generado automáticamente por Prig IDE** | Total de Bloques: {}\n\n", bloques.len()),
            "---\n".into(),
        ])];
        for (i, b) in bloques.iter().enumerate() {
            let i = i + 1;
            let g = |k: &str| b.valor(k).texto_py();
            let temas = b.lista("topics").unwrap_or(&[]).iter().map(Valor::texto_py).collect::<Vec<_>>().join(", ");
            celdas.push(celda_md(vec![
                format!("## Bloque {i}: {}\n", g("title")),
                format!("**Descripción:** {}\n\n", g("description")),
                format!("🎯 **Objetivo:** {}\n\n", g("learning_objective")),
                format!("⚡ **Hito de Validación:** {}\n\n", g("validation_check")),
                format!("📌 **Temas:** {temas}\n"),
            ]));
            celdas.push(celda_codigo(vec![
                "# ==========================================\n".into(),
                format!("# BLOQUE {i}: {}\n", g("title").to_uppercase()),
                "# ==========================================\n\n".into(),
                format!("print('=== Ejecutando Bloque {i}: {} ===')\n", g("title")),
            ]));
            celdas.push(celda_codigo(vec![
                format!("# 🎯 RETO PRÁCTICO PARA BLOQUE {i}\n"),
                format!("# Hito: {}\n\n", g("validation_check")),
                format!("def resolver_reto_bloque_{i}():\n"),
                "    # TODO: Escribe tu solución de código aquí\n".into(),
                "    pass\n\n".into(),
                format!("resolver_reto_bloque_{i}()\n"),
            ]));
        }
        let cuaderno = Mapa::new()
            .con("cells", Valor::Lista(celdas))
            .con(
                "metadata",
                Mapa::new()
                    .con("kernelspec", Mapa::new().con("display_name", "Python 3 (ipykernel)").con("language", "python").con("name", "python3"))
                    .con("language_info", Mapa::new().con("name", "python").con("version", "3.10")),
            )
            .con("nbformat", 4)
            .con("nbformat_minor", 4);
        let seguro: String = objetivo.chars().take(30).map(|c| if c.is_ascii_alphanumeric() || c == '_' || c == '-' { c } else { '_' }).collect();
        let nombre = format!("Ruta_{seguro}_{}.ipynb", id.chars().take(6).collect::<String>());
        let ruta = prig_plataforma::py::join(&espacio.to_string_lossy(), &nombre);
        prig_plataforma::escribir_json(Path::new(&ruta), &Valor::Mapa(cuaderno), 2)?;
        Ok(Some(
            Mapa::new()
                .con("status", "ok")
                .con("file_path", ruta)
                .con("filename", nombre.as_str())
                .con("message", format!("Cuaderno Jupyter '{nombre}' generado exitosamente.")),
        ))
    })
    .await;
    match r {
        Ok(Ok(Some(m))) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Ok(None)) => detalle(StatusCode::NOT_FOUND, "Seguimiento no encontrado"),
        _ => error_500(),
    }
}
