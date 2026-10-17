//! El plan de estudio de los tres agentes (`/api/study-plan/*` de `app.py` con `StudyPlanEngine`): crear, ver una
//! versión, los agentes (mapa de conocimiento, currículo práctico y cuadernos ejecutables), las aprobaciones y las
//! peticiones de cambio. Los planes son archivos del espacio de trabajo (`.prig_plans/`); las listas, el borrado y el
//! progreso están en `guiado`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use axum::{
    body::Bytes,
    extract::{Path as Ruta, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_aprendizaje::planes;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::cuerpo::{self, Campos};
use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{detalle, json_py};
use crate::state::AppState;

const MODELO: &str = "qwen2.5-coder:7b";

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn respuesta(r: Result<Result<Mapa, Response>, tokio::task::JoinError>) -> Response {
    match r {
        Ok(Ok(p)) => json_py(StatusCode::OK, &Valor::Mapa(p)),
        Ok(Err(r)) => r,
        Err(_) => error_500(),
    }
}

/// `generate_response` sin opciones, entero
fn generar(state: &AppState, prompt: String, sistema: &str, modelo: &str) -> String {
    let p = prig_ia::generar::PedidoGenerar { prompt, modelo: modelo.into(), sistema: sistema.into(), gobernador: true, ..Default::default() };
    let mut r = String::new();
    let c = prig_ia::vivo::Cancelar::default();
    prig_ia::generar::generar(&state.base_dir, &p, &c, &mut |e: Mapa| {
        if e.get("t") == Some(&Valor::Texto("texto".into())) {
            r.push_str(&e.valor("v").texto_py());
        }
    });
    r
}

fn paso(nombre: &str, mensaje: String, estado: &str) -> Valor {
    let m = Mapa::new().con("step", nombre).con("message", mensaje).con("status", estado);
    planes::validar_modelo(&planes::PASO_TRAZA, Valor::Mapa(m)).map(Valor::Mapa).unwrap_or(Valor::Nulo)
}

fn traza(agente: &str, pasos: Vec<Valor>, stats: Mapa) -> Valor {
    let m = Mapa::new().con("agent_name", agente).con("status", "COMPLETED").con("steps", Valor::Lista(pasos)).con("stats", Valor::Mapa(stats));
    planes::validar_modelo(&planes::TRAZA, Valor::Mapa(m)).map(Valor::Mapa).unwrap_or(Valor::Nulo)
}

fn anadir_traza(p: &mut Mapa, t: Valor) {
    let mut l = p.lista("decision_traces").map(|l| l.to_vec()).unwrap_or_default();
    l.push(t);
    p.poner("decision_traces", Valor::Lista(l));
}

/// El paso final del `PlanValidator`, con sus avisos o el visto bueno
fn paso_validador(avisos: &[String], prefijo: &str, bien: &str) -> Valor {
    if avisos.is_empty() {
        paso("PLAN_VALIDATOR_CHECK", bien.into(), "DONE")
    } else {
        paso("PLAN_VALIDATOR_CHECK", format!("{prefijo}{}", avisos.join("; ")), "WARNING")
    }
}

fn libros(state: &AppState) -> Vec<Mapa> {
    let guardados = crate::routes::estante::guardados(state);
    prig_biblioteca::estante::Estante::por_defecto().listar(None, &guardados).unwrap_or_default()
}

fn biblioteca() -> PathBuf {
    PathBuf::from(prig_biblioteca::estante::Estante::por_defecto().raiz)
}

/// `POST /api/study-plan/init` (`user_goal`)
pub async fn iniciar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = Campos::new(&m);
    let objetivo = c.texto("user_goal", None);
    if let Err(r) = c.fin() {
        return r;
    }
    let espacio = espacio_de_trabajo(&state).await;
    respuesta(tokio::task::spawn_blocking(move || planes::nuevo_plan(&espacio, &objetivo.texto_py()).map_err(|_| error_500())).await)
}

/// `GET /api/study-plan/state/{plan_id}?version=`
pub async fn ver(State(state): State<AppState>, Ruta(id): Ruta<String>, Query(q): Query<HashMap<String, String>>) -> Response {
    let version = match cuerpo::entero_consulta(&q, "version", 0, i64::MIN, i64::MAX) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || match planes::cargar_plan_version(&espacio, &id, Some(version as i128)) {
            Ok(Some(p)) => Ok(p),
            Ok(None) => Err(detalle(StatusCode::NOT_FOUND, "Plan de estudio no encontrado.")),
            Err(_) => Err(error_500()),
        })
        .await,
    )
}

/// El cuerpo de los agentes: `plan_id` y `model`
fn pedido_agente(b: &Bytes) -> Result<(String, String), Response> {
    let m = cuerpo::modelo(b)?;
    let mut c = Campos::new(&m);
    let id = c.texto("plan_id", None);
    let modelo = c.texto("model", Some(Valor::Texto(MODELO.into())));
    c.fin()?;
    Ok((id.texto_py(), modelo.texto_py()))
}

const SISTEMA_1: &str = r#"Eres el AGENTE 1: KNOWLEDGE ARCHITECT.
Tu tarea es descomponer el objetivo del alumno en un mapa de conocimiento jerárquico
(dominios -> temas -> conceptos) apoyándote en las fuentes de la biblioteca que recibes.

REGLAS:
1. Cada concept_id, topic_id y domain_id debe ser único y en snake_case (ej: conc_tensores).
2. Las relaciones y prerrequisitos solo pueden referenciar concept_id que existan en domains.
3. Cita en evidence el source_id de la fuente de la biblioteca que respalda cada concepto.

Devuelve ÚNICAMENTE un objeto JSON válido, sin texto ni markdown alrededor, con esta forma:
{
  "goal": "objetivo del alumno",
  "domains": [
    {
      "domain_id": "dom_01",
      "name": "Nombre del dominio",
      "topics": [
        {
          "topic_id": "top_01",
          "name": "Nombre del tema",
          "concepts": [
            {
              "concept_id": "conc_01",
              "name": "Nombre del concepto",
              "specifications": "Qué debe dominar exactamente el alumno",
              "concept_type": "THEORETICAL",
              "evidence": [{"source_id": "archivo.pdf", "title": "Título del documento", "location": "cap. 3"}]
            }
          ]
        }
      ]
    }
  ],
  "prerequisites": [{"name": "Álgebra lineal básica", "reason": "por qué hace falta", "required": true}],
  "relationships": [{"source_concept_id": "conc_01", "target_concept_id": "conc_02", "relation_type": "REQUIRES"}]
}"#;

const SISTEMA_2: &str = r#"Eres el AGENTE 2: PRACTICE & CURRICULUM ARCHITECT.
Recibes un KNOWLEDGE_MAP y lo conviertes en un currículo práctico: módulos ordenados,
cada uno con un objetivo, criterios de validación comprobables y tareas concretas.

REGLAS:
1. Los module_id siguen el formato mod_01, mod_02, ... en orden de dificultad creciente.
2. El campo concepts de cada módulo SOLO puede contener concept_id existentes en el KNOWLEDGE_MAP.
3. Cada validation_criteria debe ser verificable por el alumno ("ejecuta X y obtén Y"), no vago.

Devuelve ÚNICAMENTE un objeto JSON válido, sin texto ni markdown alrededor, con esta forma:
{
  "curriculum_id": "curr_01",
  "goal": "objetivo del alumno",
  "modules": [
    {
      "module_id": "mod_01",
      "name": "Nombre del módulo",
      "objective": "Qué sabrá hacer el alumno al terminarlo",
      "concepts": ["conc_01", "conc_02"],
      "validation_criteria": ["Criterio comprobable 1", "Criterio comprobable 2"],
      "tasks": [{"task_id": "task_01", "description": "Qué debe programar o resolver"}]
    }
  ],
  "objectives": ["Objetivo global 1", "Objetivo global 2"],
  "module_dependencies": [{"from_module_id": "mod_01", "to_module_id": "mod_02"}]
}"#;

const SISTEMA_3: &str = r#"Eres el AGENTE 3: NOTEBOOK & LEARNING MANAGER.
Recibes un currículo práctico y el listado de cuadernos y código disponibles en la
biblioteca, y planificas qué cuaderno ejecutable corresponde a cada módulo.

REGLAS:
1. Cada module_id debe existir en el currículo recibido; no inventes módulos nuevos.
2. source_library_notebook debe ser una ruta exacta del listado de la biblioteca, o null
   si el cuaderno se crea desde cero.
   action solo admite dos valores: CREATED_FROM_SCRATCH o COPIED_AND_EXPLAINED.
3. Nunca propongas escribir dentro de la biblioteca: las copias editables las genera el sistema.

Devuelve ÚNICAMENTE un objeto JSON válido, sin texto ni markdown alrededor, con esta forma:
{
  "plan_id": "exec_01",
  "goal": "objetivo del alumno",
  "modules_notebooks": [
    {
      "module_id": "mod_01",
      "module_name": "Nombre del módulo",
      "notebooks": [
        {
          "notebook_id": "nb_01",
          "title": "Título del cuaderno",
          "executable_path": "",
          "action": "CREATED_FROM_SCRATCH",
          "source_library_notebook": null,
          "description": "Qué se practica en este cuaderno"
        }
      ]
    }
  ],
  "total_notebooks_copied_and_edited": 0,
  "total_notebooks_created": 1
}"#;

const SISTEMA_CAMBIO: &str = r#"Eres el ASISTENTE DISEÑADOR DEL PLAN.
Traduces la petición en lenguaje natural del alumno a una orden de cambio estructurada
sobre el plan de estudio que está revisando.

target_agent válidos: KNOWLEDGE_ARCHITECT | PRACTICE_ARCHITECT | NOTEBOOK_MANAGER
action válidos: ADD_PREREQUISITE | REMOVE_PREREQUISITE | ADD_CONCEPT | REMOVE_CONCEPT |
                ADD_TOPIC | MODIFY_OBJECTIVE | ADD_PRACTICAL_MODULE

Devuelve ÚNICAMENTE un objeto JSON válido, sin texto ni markdown alrededor, con esta forma:
{
  "target_agent": "KNOWLEDGE_ARCHITECT",
  "action": "ADD_PREREQUISITE",
  "target": "Nombre exacto del elemento afectado",
  "parameter": "Valor adicional si aplica, o cadena vacía",
  "reason": "Por qué se aplica este cambio"
}"#;

/// La respuesta del modelo como el modelo pedido, o el 500 del agente
fn ejecutar_agente(state: &AppState, prompt: String, sistema: &str, modelo: &str, m: &prig_plataforma::modelo::Modelo, agente: &str) -> Result<Mapa, Response> {
    prig_ia::json_modelo::reparar(&generar(state, prompt, sistema, modelo))
        .and_then(|d| planes::validar_modelo(m, Valor::Mapa(d)))
        .map_err(|e| detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("Error al ejecutar {agente}: {e}")))
}

fn cargar(espacio: &Path, id: &str) -> Result<Option<Mapa>, Response> {
    planes::cargar_plan(espacio, id).map_err(|_| error_500())
}

fn guardar(espacio: &Path, p: &mut Mapa) -> Result<(), Response> {
    planes::guardar_plan(espacio, p).map_err(|_| error_500())
}

/// `POST /api/study-plan/agent1`: el Knowledge Architect
pub async fn agente1(State(state): State<AppState>, b: Bytes) -> Response {
    let (id, modelo) = match pedido_agente(&b) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || {
            let Some(mut p) = cargar(&espacio, &id)? else { return Err(detalle(StatusCode::NOT_FOUND, "Plan no encontrado.")) };
            let items = libros(&state);
            let objetivo = p.valor("user_goal").texto_py();
            let fuentes: Vec<Valor> = items
                .iter()
                .take(20)
                .map(|i| {
                    let tipo = match i.get("category_id") {
                        Some(v) if v.verdad() => v.clone(),
                        _ => i.get("ext").cloned().unwrap_or(Valor::Nulo),
                    };
                    let temas = match i.get("metadata") {
                        Some(Valor::Mapa(md)) if i.verdad("metadata") => md.get("topics").cloned().unwrap_or(Valor::Lista(Vec::new())),
                        _ => Valor::Lista(Vec::new()),
                    };
                    Valor::Mapa(
                        Mapa::new()
                            .con("source_id", i.get("id").cloned().unwrap_or(Valor::Nulo))
                            .con("title", i.get("title").cloned().unwrap_or(Valor::Nulo))
                            .con("type", tipo)
                            .con("topics", temas),
                    )
                })
                .collect();
            let prompt = format!(
                "Objetivo: '{objetivo}'\nFuentes disponibles en la biblioteca: {}",
                prig_plataforma::json::escribir_linea(&Valor::Lista(fuentes))
            );
            let km = ejecutar_agente(&state, prompt, SISTEMA_1, &modelo, &planes::MAPA, "Agente 1 (Knowledge Architect)")?;
            let avisos = planes::avisos_mapa(&km);
            let n = items.len();
            let pasos = vec![
                paso("ANALYZING_GOAL", format!("Objetivo analizado: '{objetivo}'"), "DONE"),
                paso("SCANNING_LIBRARY", format!("Fuentes escaneadas en Biblioteca: {n} ítems"), "DONE"),
                paso("EXTRACTING_CONCEPTS", "Conceptos y matriz de dependencias extraída con evidencias".into(), "DONE"),
                paso("BUILDING_KNOWLEDGE_MAP", "KNOWLEDGE_MAP construido exitosamente".into(), "DONE"),
                if avisos.is_empty() {
                    paso("PLAN_VALIDATOR_CHECK", "✅ PlanValidator: Validación cruzada de IDs 100% Correcta".into(), "DONE")
                } else {
                    paso("PLAN_VALIDATOR_CHECK", format!("⚠️ PlanValidator detectó {} advertencias de IDs: {}", avisos.len(), avisos.join("; ")), "WARNING")
                },
            ];
            let stats = Mapa::new()
                .con("sources_scanned", Valor::Entero(n as i128))
                .con("domains_count", Valor::Entero(km.lista("domains").map_or(0, |l| l.len()) as i128))
                .con("prerequisites_count", Valor::Entero(km.lista("prerequisites").map_or(0, |l| l.len()) as i128))
                .con("validator_warnings", Valor::Entero(avisos.len() as i128));
            p.poner("knowledge_map", Valor::Mapa(km));
            p.poner("status", "KNOWLEDGE_REVIEW");
            anadir_traza(&mut p, traza("Knowledge Architect", pasos, stats));
            guardar(&espacio, &mut p)?;
            Ok(p)
        })
        .await,
    )
}

/// `POST /api/study-plan/agent2`: el Practice & Curriculum Architect
pub async fn agente2(State(state): State<AppState>, b: Bytes) -> Response {
    let (id, modelo) = match pedido_agente(&b) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || {
            let (mut p, km) = match cargar(&espacio, &id)? {
                Some(p) => match p.mapa("knowledge_map").cloned() {
                    Some(km) => (p, km),
                    None => return Err(falta_paso_1()),
                },
                None => return Err(falta_paso_1()),
            };
            let prompt = format!("KNOWLEDGE_MAP:\n{}", prig_plataforma::json::escribir_linea(&Valor::Mapa(km.clone())));
            let curr = ejecutar_agente(&state, prompt, SISTEMA_2, &modelo, &planes::CURRICULO, "Agente 2 (Practice Architect)")?;
            let avisos = planes::avisos_curriculo(&curr, &km);
            let modulos = curr.lista("modules").map_or(0, |l| l.len());
            let pasos = vec![
                paso("RECEIVING_KNOWLEDGE_MAP", "KNOWLEDGE_MAP procesado".into(), "DONE"),
                paso("BUILDING_PRACTICAL_MODULES", format!("Creados {modulos} módulos de objetivos prácticos"), "DONE"),
                paso("DEFINING_VALIDATION_CRITERIA", "Criterios de validación del estudiante (validation_criteria) establecidos".into(), "DONE"),
                paso_validador(&avisos, "⚠️ PlanValidator: ", "✅ PlanValidator: Coincidencia cruzada de concept_ids 100% Correcta"),
            ];
            let stats = Mapa::new()
                .con("modules_count", Valor::Entero(modulos as i128))
                .con("objectives_count", Valor::Entero(curr.lista("objectives").map_or(0, |l| l.len()) as i128))
                .con("validator_warnings", Valor::Entero(avisos.len() as i128));
            p.poner("practical_curriculum", Valor::Mapa(curr));
            p.poner("status", "PRACTICAL_REVIEW");
            anadir_traza(&mut p, traza("Practice & Curriculum Architect", pasos, stats));
            guardar(&espacio, &mut p)?;
            Ok(p)
        })
        .await,
    )
}

fn falta_paso_1() -> Response {
    detalle(StatusCode::BAD_REQUEST, "Se requiere aprobar o ejecutar el Módulo 1 (KnowledgeMap) primero.")
}

fn falta_paso_2() -> Response {
    detalle(StatusCode::BAD_REQUEST, "Se requiere ejecutar el Módulo 2 (PracticalCurriculum) primero.")
}

/// `POST /api/study-plan/agent3`: el Notebook & Learning Manager. Escribe un cuaderno explicado por cada uno del plan
/// en `notebooks_plan/` del espacio de trabajo (nunca dentro de la biblioteca: los originales no se tocan)
pub async fn agente3(State(state): State<AppState>, b: Bytes) -> Response {
    let (id, modelo) = match pedido_agente(&b) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || {
            let (mut p, curr) = match cargar(&espacio, &id)? {
                Some(p) => match p.mapa("practical_curriculum").cloned() {
                    Some(c) => (p, c),
                    None => return Err(falta_paso_2()),
                },
                None => return Err(falta_paso_2()),
            };
            let codigo: Vec<Mapa> = libros(&state)
                .into_iter()
                .filter(|b| {
                    matches!(b.texto("category_id"), Some("code" | "notebooks")) || matches!(b.texto("ext"), Some("py" | "ipynb"))
                })
                .collect();
            let resumen: Vec<Valor> = codigo
                .iter()
                .take(15)
                .map(|i| {
                    Valor::Mapa(
                        Mapa::new()
                            .con("id", i.get("id").cloned().unwrap_or(Valor::Nulo))
                            .con("filename", i.get("filename").cloned().unwrap_or(Valor::Nulo)),
                    )
                })
                .collect();
            let prompt = format!(
                "CURRICULUM:\n{}\n\nCUADERNOS Y CÓDIGO DISPONIBLES EN LA BIBLIOTECA:\n{}",
                prig_plataforma::json::escribir_linea(&Valor::Mapa(curr.clone())),
                prig_plataforma::json::escribir_linea(&Valor::Lista(resumen))
            );
            let mut ej = ejecutar_agente(&state, prompt, SISTEMA_3, &modelo, &planes::PLAN_EJECUTABLE, "Agente 3 (Notebook Manager)")?;
            let avisos = planes::avisos_ejecutable(&ej, &curr);

            let dir = PathBuf::from(prig_plataforma::py::abspath(&espacio.to_string_lossy())).join("notebooks_plan");
            let _ = std::fs::create_dir_all(&dir);
            let mut por_id: Vec<(Valor, Mapa)> = Vec::new();
            for m in curr.lista("modules").unwrap_or(&[]) {
                if let Valor::Mapa(m) = m {
                    let k = m.valor("module_id").clone();
                    match por_id.iter_mut().find(|(x, _)| *x == k) {
                        Some(e) => e.1 = m.clone(),
                        None => por_id.push((k, m.clone())),
                    }
                }
            }
            let bib = biblioteca();
            let mut modulos = ej.lista("modules_notebooks").map(|l| l.to_vec()).unwrap_or_default();
            for m in modulos.iter_mut() {
                let Valor::Mapa(m) = m else { continue };
                let mid = m.valor("module_id").clone();
                let del_curr = por_id.iter().find(|(k, _)| *k == mid).map(|(_, c)| c);
                let nombre = del_curr.map_or_else(|| m.valor("module_name").texto_py(), |c| c.valor("name").texto_py());
                let objetivo = del_curr.map_or_else(|| "Practicar los conceptos del módulo".to_string(), |c| c.valor("objective").texto_py());
                let criterios = del_curr.and_then(|c| c.lista("validation_criteria")).map(|l| l.to_vec()).unwrap_or_default();
                let mut cuadernos = m.lista("notebooks").map(|l| l.to_vec()).unwrap_or_default();
                for nb in cuadernos.iter_mut() {
                    let Valor::Mapa(nb) = nb else { continue };
                    let destino = dir.join(format!("{}_{}.ipynb", mid.texto_py(), nb.valor("notebook_id").texto_py()));
                    let fuente = nb.texto("source_library_notebook").unwrap_or("").to_string();
                    let codigo = if !fuente.is_empty() && Path::new(&fuente).exists() {
                        std::fs::read(&fuente).map(|b| String::from_utf8_lossy(&b).into_owned()).unwrap_or_default()
                    } else {
                        String::new()
                    };
                    let contenido = planes::cuaderno_explicado(&nombre, &objetivo, &criterios, &codigo);
                    match planes::escribir_cuaderno(&destino, &contenido, &bib) {
                        Ok(ruta) => {
                            nb.poner("executable_path", ruta);
                            nb.poner("is_original_protected", true);
                            nb.poner("line_by_line_explanations_added", true);
                            nb.poner("validation_tests_included", true);
                        }
                        Err(e) => eprintln!("Advertencia en generación de cuaderno: {e}"),
                    }
                }
                m.poner("notebooks", Valor::Lista(cuadernos));
            }
            ej.poner("modules_notebooks", Valor::Lista(modulos));

            let pasos = vec![
                paso("SCANNING_LIBRARY_CODE", format!("Archivos de código analizados: {}", codigo.len()), "DONE"),
                paso("PHYSICAL_COPY_ENFORCEMENT", "🔒 Copias editables generadas fuera de ~/.prig_books/ (Originales 100% Protegidos)".into(), "DONE"),
                paso("PLAN_READY", "EXECUTABLE_LEARNING_PLAN generado exitosamente".into(), "DONE"),
                paso_validador(&avisos, "⚠️ PlanValidator: ", "✅ PlanValidator: Validación de cuadernos y módulos 100% Correcta"),
            ];
            let stats = Mapa::new()
                .con("notebooks_copied", ej.valor("total_notebooks_copied_and_edited").clone())
                .con("notebooks_created", ej.valor("total_notebooks_created").clone())
                .con("validator_warnings", Valor::Entero(avisos.len() as i128));
            p.poner("executable_learning_plan", Valor::Mapa(ej));
            p.poner("status", "LEARNING_REVIEW");
            anadir_traza(&mut p, traza("Notebook & Learning Manager", pasos, stats));
            guardar(&espacio, &mut p)?;
            Ok(p)
        })
        .await,
    )
}

/// `POST /api/study-plan/approve` (`plan_id`, `step`: knowledge | practical | learning)
pub async fn aprobar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = Campos::new(&m);
    let id = c.texto("plan_id", None);
    let paso = c.texto("step", None);
    if let Err(r) = c.fin() {
        return r;
    }
    let paso = paso.texto_py();
    if !matches!(paso.as_str(), "knowledge" | "practical" | "learning") {
        return detalle(StatusCode::BAD_REQUEST, format!("Paso de aprobación no válido: {paso}"));
    }
    let espacio = espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || planes::aprobar(&espacio, &id.texto_py(), &paso).map_err(|e| detalle(StatusCode::BAD_REQUEST, e))).await,
    )
}

/// `POST /api/study-plan/change-request` (`plan_id`, `user_prompt`, `model`): el asistente traduce la petición a una
/// orden de cambio y se aplica en una versión nueva
pub async fn cambio(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = Campos::new(&m);
    let id = c.texto("plan_id", None).texto_py();
    let peticion = c.texto("user_prompt", None).texto_py();
    let modelo = c.texto("model", Some(Valor::Texto(MODELO.into()))).texto_py();
    if let Err(r) = c.fin() {
        return r;
    }
    let espacio = espacio_de_trabajo(&state).await;
    respuesta(
        tokio::task::spawn_blocking(move || {
            let Some(p) = cargar(&espacio, &id)? else { return Err(detalle(StatusCode::NOT_FOUND, "Plan no encontrado.")) };
            let fallo = |e: String| detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("Error al procesar solicitud de cambio: {e}"));
            let prompt = format!("Etapa actual del plan: {}\nPetición del alumno: '{peticion}'", p.valor("status").texto_py());
            let crudo = prig_ia::json_modelo::reparar(&generar(&state, prompt, SISTEMA_CAMBIO, &modelo)).map_err(fallo)?;
            let de = |k: &str, d: &str| crudo.get(k).cloned().unwrap_or_else(|| Valor::Texto(d.into()));
            let orden = Mapa::new()
                .con("target_agent", de("target_agent", "KNOWLEDGE_ARCHITECT"))
                .con("action", de("action", "ADD_PREREQUISITE"))
                .con("target", de("target", "General"))
                .con("parameter", de("parameter", ""))
                .con("user_prompt", peticion.clone())
                .con("reason", de("reason", "Solicitud del usuario"));
            let orden = planes::validar_modelo(&planes::PETICION_CAMBIO, Valor::Mapa(orden)).map_err(fallo)?;
            planes::aplicar_cambio(&espacio, &id, &orden).map_err(fallo)
        })
        .await,
    )
}
