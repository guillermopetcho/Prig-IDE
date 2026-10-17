//! Los modelos de `study_plan_engine.py` (planes de estudio de tres agentes y rutas de aprendizaje guiado) y las
//! migraciones de esquema de `schema_migrations.py`, con el validador de `prig_plataforma::modelo`: lo que se lee del
//! disco se valida y se vuelca igual que con `Model.model_validate(doc).model_dump()`.

use prig_plataforma::modelo::{id_al_azar, rellenar, texto, Campo, Defecto, Modelo, Tipo};
use prig_plataforma::valor::{Mapa, Valor};
use std::path::Path;

fn ahora() -> Valor {
    Valor::Texto(prig_plataforma::py::ahora_iso())
}
fn vacia() -> Valor {
    Valor::Lista(Vec::new())
}
fn vacio() -> Valor {
    Valor::Mapa(Mapa::new())
}
fn t(s: &str) -> Valor {
    Valor::Texto(s.into())
}
fn tx(d: &Mapa, k: &str, defecto: &str) -> Valor {
    Valor::Texto(texto(d.get(k), defecto))
}

/// `x or y` de Python sobre dos valores de un dict
fn o<'a>(d: &'a Mapa, a: &str, b: &str) -> Option<&'a Valor> {
    match d.get(a) {
        Some(v) if v.verdad() => Some(v),
        _ => d.get(b),
    }
}

/// `if isinstance(v, str): v = {campo: v}`
fn de_texto(v: Valor, campo: &str) -> Valor {
    match v {
        Valor::Texto(s) => Valor::Mapa(Mapa::new().con(campo, s)),
        otro => otro,
    }
}

const STR: Tipo = Tipo::Texto;
const OPT_STR: Tipo = Tipo::Opcional(&Tipo::Texto);
const LISTA_STR: Tipo = Tipo::Lista(&Tipo::Texto);
const DICT_ANY: Tipo = Tipo::Dict(&Tipo::Cualquiera);
const LISTA_DICT_ANY: Tipo = Tipo::Lista(&DICT_ANY);

const fn campo(nombre: &'static str, tipo: Tipo, defecto: Defecto) -> Campo {
    Campo { nombre, tipo, defecto }
}
const NO: Defecto = Defecto::No;

pub const ESTADOS_PLAN: &[&str] =
    &["DRAFT", "KNOWLEDGE_REVIEW", "KNOWLEDGE_APPROVED", "PRACTICAL_REVIEW", "PRACTICAL_APPROVED", "LEARNING_REVIEW", "APPROVED"];
pub const ACCIONES: &[&str] = &[
    "ADD_PREREQUISITE", "REMOVE_PREREQUISITE", "ADD_TOPIC", "REMOVE_TOPIC", "REDUCE_DEPTH", "INCREASE_DEPTH", "SWAP_NOTEBOOK", "CUSTOM_CORRECTION",
    "ADD_CONCEPT", "REMOVE_CONCEPT", "MODIFY_OBJECTIVE", "ADD_PRACTICAL_MODULE",
];
const TIPOS_CONCEPTO: &[&str] = &["FOUNDATIONAL", "PRACTICAL", "ADVANCED"];
const ACCIONES_CUADERNO_ENUM: &[&str] = &["CREATED_FROM_SCRATCH", "COPIED_AND_EXPLAINED"];

// ---------------------------------------------------------------------------------------------- mapa de conocimiento

pub static EVIDENCIA: Modelo = Modelo {
    nombre: "EvidenceSource",
    campos: &[
        campo("source_id", STR, NO),
        campo("source_type", STR, Defecto::Valor(|| t("book"))),
        campo("title", STR, NO),
        campo("location", OPT_STR, Defecto::Valor(|| t(""))),
        campo("confidence", STR, Defecto::Valor(|| t("HIGH"))),
    ],
    antes: Some(|v| {
        let v = rellenar(
            de_texto(v, "source_id"),
            &[("source_id", &|d| tx(d, "title", "biblioteca")), ("title", &|d| tx(d, "source_id", "Fuente de la biblioteca"))],
        );
        match v {
            Valor::Mapa(mut m) if !m.verdad("location") => {
                // «locator» y «quote» son nombres que el modelo usa a menudo por su cuenta
                let l = texto(o(&m, "locator", "quote"), "");
                m.poner("location", l);
                Valor::Mapa(m)
            }
            otro => otro,
        }
    }),
};

pub static CONCEPTO: Modelo = Modelo {
    nombre: "Concept",
    campos: &[
        campo("concept_id", STR, NO),
        campo("name", STR, NO),
        campo("type", Tipo::Enum(TIPOS_CONCEPTO), Defecto::Valor(|| t("FOUNDATIONAL"))),
        campo("characteristics", LISTA_STR, Defecto::Valor(vacia)),
        campo("specifications", OPT_STR, Defecto::Valor(|| t(""))),
        campo("dependencies", LISTA_STR, Defecto::Valor(vacia)),
        campo("evidence", Tipo::Lista(&Tipo::Modelo(&EVIDENCIA)), Defecto::Valor(vacia)),
    ],
    antes: Some(|v| {
        rellenar(
            de_texto(v, "name"),
            &[("name", &|d| tx(d, "concept_id", "Concepto")), ("concept_id", &|_| Valor::Texto(id_al_azar("conc", 6)))],
        )
    }),
};

pub static TEMA: Modelo = Modelo {
    nombre: "Topic",
    campos: &[campo("topic_id", STR, NO), campo("name", STR, NO), campo("concepts", Tipo::Lista(&Tipo::Modelo(&CONCEPTO)), Defecto::Valor(vacia))],
    antes: Some(|v| {
        rellenar(de_texto(v, "name"), &[("name", &|d| tx(d, "topic_id", "Tema")), ("topic_id", &|_| Valor::Texto(id_al_azar("top", 6)))])
    }),
};

pub static DOMINIO: Modelo = Modelo {
    nombre: "Domain",
    campos: &[campo("domain_id", STR, NO), campo("name", STR, NO), campo("topics", Tipo::Lista(&Tipo::Modelo(&TEMA)), Defecto::Valor(vacia))],
    antes: Some(|v| {
        rellenar(de_texto(v, "name"), &[("name", &|d| tx(d, "domain_id", "Dominio")), ("domain_id", &|_| Valor::Texto(id_al_azar("dom", 6)))])
    }),
};

pub static PRERREQUISITO: Modelo = Modelo {
    nombre: "Prerequisite",
    campos: &[campo("name", STR, NO), campo("reason", STR, NO), campo("required", Tipo::Booleano, Defecto::Valor(|| Valor::Bool(true)))],
    antes: Some(|v| rellenar(de_texto(v, "name"), &[("name", &|_| t("Prerrequisito")), ("reason", &|_| t("Necesario para seguir la ruta."))])),
};

pub static RELACION: Modelo = Modelo {
    nombre: "Relationship",
    campos: &[
        campo("source_concept_id", STR, NO),
        campo("target_concept_id", STR, NO),
        campo("relation_type", STR, Defecto::Valor(|| t("PREREQUISITE_FOR"))),
    ],
    antes: Some(|v| {
        rellenar(
            v,
            &[
                ("source_concept_id", &|d| Valor::Texto(texto(o(d, "from", "source"), ""))),
                ("target_concept_id", &|d| Valor::Texto(texto(o(d, "to", "target"), ""))),
            ],
        )
    }),
};

pub static MAPA: Modelo = Modelo {
    nombre: "KnowledgeMap",
    campos: &[
        campo("goal", STR, NO),
        campo("prerequisites", Tipo::Lista(&Tipo::Modelo(&PRERREQUISITO)), Defecto::Valor(vacia)),
        campo("domains", Tipo::Lista(&Tipo::Modelo(&DOMINIO)), Defecto::Valor(vacia)),
        campo("relationships", Tipo::Lista(&Tipo::Modelo(&RELACION)), Defecto::Valor(vacia)),
        campo("exceptions", LISTA_STR, Defecto::Valor(vacia)),
        campo("terminology", Tipo::Dict(&Tipo::Texto), Defecto::Valor(vacio)),
        campo("recommended_order", LISTA_STR, Defecto::Valor(vacia)),
        campo("evidence_summary", DICT_ANY, Defecto::Valor(vacio)),
    ],
    antes: Some(|v| {
        let v = rellenar(v, &[("goal", &|_| t("Ruta de aprendizaje"))]);
        match v {
            // una relación sin extremos no aporta nada y sí puede romper la validación
            Valor::Mapa(mut m) => {
                if let Some(Valor::Lista(rs)) = m.get("relationships").cloned() {
                    let quedan: Vec<Valor> = rs
                        .into_iter()
                        .filter(|r| match r {
                            Valor::Mapa(x) => ["source_concept_id", "from", "source"].iter().any(|k| x.verdad(k)),
                            _ => true,
                        })
                        .collect();
                    m.poner("relationships", Valor::Lista(quedan));
                }
                Valor::Mapa(m)
            }
            otro => otro,
        }
    }),
};

// ---------------------------------------------------------------------------------------------- currículo práctico

pub static MODULO_PRACTICO: Modelo = Modelo {
    nombre: "PracticalModule",
    campos: &[
        campo("module_id", STR, NO),
        campo("name", STR, NO),
        campo("objective", STR, NO),
        campo("topics", LISTA_STR, Defecto::Valor(vacia)),
        campo("concepts", LISTA_STR, Defecto::Valor(vacia)),
        campo("practical_tasks", LISTA_STR, Defecto::Valor(vacia)),
        campo("prerequisites", LISTA_STR, Defecto::Valor(vacia)),
        campo("validation_criteria", LISTA_STR, Defecto::Valor(vacia)),
    ],
    antes: Some(|v| {
        rellenar(
            de_texto(v, "name"),
            &[
                ("module_id", &|_| Valor::Texto(id_al_azar("mod", 6))),
                ("name", &|d| tx(d, "module_id", "Módulo práctico")),
                ("objective", &|d| Valor::Texto(format!("Practicar {}.", texto(d.get("name"), "los conceptos del módulo")))),
            ],
        )
    }),
};

pub static DEPENDENCIA: Modelo = Modelo {
    nombre: "ModuleDependency",
    campos: &[campo("module_id", STR, NO), campo("depends_on", LISTA_STR, Defecto::Valor(vacia))],
    antes: Some(|v| rellenar(v, &[("module_id", &|_| Valor::Texto(id_al_azar("mod", 6)))])),
};

pub static CURRICULO: Modelo = Modelo {
    nombre: "PracticalCurriculum",
    campos: &[
        campo("curriculum_id", STR, NO),
        campo("knowledge_map_version", Tipo::Entero, Defecto::Valor(|| Valor::Entero(1))),
        campo("objectives", LISTA_STR, Defecto::Valor(vacia)),
        campo("modules", Tipo::Lista(&Tipo::Modelo(&MODULO_PRACTICO)), Defecto::Valor(vacia)),
        campo("learning_dependencies", Tipo::Lista(&Tipo::Modelo(&DEPENDENCIA)), Defecto::Valor(vacia)),
        campo("progression", LISTA_STR, Defecto::Valor(vacia)),
        campo("validation_criteria_summary", OPT_STR, Defecto::Valor(|| t(""))),
    ],
    antes: Some(|v| rellenar(v, &[("curriculum_id", &|_| Valor::Texto(id_al_azar("curr", 8)))])),
};

// ---------------------------------------------------------------------------------------------- plan ejecutable

/// `ACCIONES_CUADERNO`: lo que escribe un modelo pequeño en lugar del valor exacto
fn accion_cuaderno(clave: &str) -> Option<&'static str> {
    match clave {
        "create" | "created" | "create_from_scratch" | "created_from_scratch" | "new" | "scratch" => Some("CREATED_FROM_SCRATCH"),
        "copy" | "copied" | "copy_and_explain" | "copied_and_explained" | "reuse" => Some("COPIED_AND_EXPLAINED"),
        _ => None,
    }
}

pub static CUADERNO: Modelo = Modelo {
    nombre: "ExecutableNotebook",
    campos: &[
        campo("notebook_id", STR, NO),
        campo("title", STR, NO),
        campo("action", Tipo::Enum(ACCIONES_CUADERNO_ENUM), Defecto::Valor(|| t("COPIED_AND_EXPLAINED"))),
        campo("source_library_notebook", OPT_STR, Defecto::Valor(|| t(""))),
        campo("executable_path", STR, NO),
        campo("is_original_protected", Tipo::Booleano, Defecto::Valor(|| Valor::Bool(true))),
        campo("associated_datasets", LISTA_STR, Defecto::Valor(vacia)),
        campo("topics_covered", LISTA_STR, Defecto::Valor(vacia)),
        campo("line_by_line_explanations_added", Tipo::Booleano, Defecto::Valor(|| Valor::Bool(true))),
        campo("validation_tests_included", Tipo::Booleano, Defecto::Valor(|| Valor::Bool(true))),
    ],
    antes: Some(|v| {
        let v = rellenar(
            v,
            &[
                ("notebook_id", &|_| Valor::Texto(id_al_azar("nb", 6))),
                ("title", &|d| tx(d, "notebook_id", "Cuaderno de práctica")),
                ("executable_path", &|_| t("")),
            ],
        );
        match v {
            Valor::Mapa(mut m) => {
                if let Some(a) = m.get("action").filter(|a| !a.es_nulo()) {
                    let clave = prig_plataforma::py::strip(&a.texto_o_repr()).to_lowercase();
                    if let Some(x) = accion_cuaderno(&clave) {
                        m.poner("action", x);
                    } else if !ACCIONES_CUADERNO_ENUM.iter().any(|e| e.to_lowercase() == clave) {
                        let x = if m.verdad("source_library_notebook") { "COPIED_AND_EXPLAINED" } else { "CREATED_FROM_SCRATCH" };
                        m.poner("action", x);
                    }
                }
                Valor::Mapa(m)
            }
            otro => otro,
        }
    }),
};

pub static MODULO_EJECUTABLE: Modelo = Modelo {
    nombre: "ExecutableModule",
    campos: &[campo("module_id", STR, NO), campo("module_name", STR, NO), campo("notebooks", Tipo::Lista(&Tipo::Modelo(&CUADERNO)), Defecto::Valor(vacia))],
    antes: Some(|v| {
        rellenar(v, &[("module_id", &|_| Valor::Texto(id_al_azar("mod", 6))), ("module_name", &|d| tx(d, "module_id", "Módulo"))])
    }),
};

pub static PLAN_EJECUTABLE: Modelo = Modelo {
    nombre: "ExecutableLearningPlan",
    campos: &[
        campo("plan_id", STR, NO),
        campo("curriculum_version", Tipo::Entero, Defecto::Valor(|| Valor::Entero(1))),
        campo("modules_notebooks", Tipo::Lista(&Tipo::Modelo(&MODULO_EJECUTABLE)), Defecto::Valor(vacia)),
        campo("total_notebooks_created", Tipo::Entero, Defecto::Valor(|| Valor::Entero(0))),
        campo("total_notebooks_copied_and_edited", Tipo::Entero, Defecto::Valor(|| Valor::Entero(0))),
        campo("total_datasets_linked", Tipo::Entero, Defecto::Valor(|| Valor::Entero(0))),
        campo("status", STR, Defecto::Valor(|| t("READY_FOR_APPROVAL"))),
    ],
    antes: Some(|v| rellenar(v, &[("plan_id", &|_| Valor::Texto(id_al_azar("exec", 8)))])),
};

// ---------------------------------------------------------------------------------------------- trazas y revisiones

pub static PETICION_CAMBIO: Modelo = Modelo {
    nombre: "ChangeRequest",
    campos: &[
        campo("request_id", STR, Defecto::Valor(|| Valor::Texto(id_al_azar("cr", 8)))),
        campo("target_agent", STR, NO),
        campo("action", Tipo::Enum(ACCIONES), NO),
        campo("target", STR, NO),
        campo("parameter", OPT_STR, Defecto::Valor(|| t(""))),
        campo("user_prompt", STR, NO),
        campo("reason", OPT_STR, Defecto::Valor(|| t("Solicitud explícita de corrección por el usuario"))),
    ],
    antes: None,
};

pub static PASO_TRAZA: Modelo = Modelo {
    nombre: "TraceStep",
    campos: &[
        campo("step", STR, NO),
        campo("message", STR, NO),
        campo("status", STR, Defecto::Valor(|| t("DONE"))),
        campo("details", OPT_STR, Defecto::Valor(|| t(""))),
        campo("timestamp", STR, Defecto::Valor(ahora)),
    ],
    antes: None,
};

pub static TRAZA: Modelo = Modelo {
    nombre: "DecisionTrace",
    campos: &[
        campo("agent_name", STR, NO),
        campo("status", STR, Defecto::Valor(|| t("COMPLETED"))),
        campo("steps", Tipo::Lista(&Tipo::Modelo(&PASO_TRAZA)), Defecto::Valor(vacia)),
        campo("stats", DICT_ANY, Defecto::Valor(vacio)),
    ],
    antes: None,
};

pub static REVISION: Modelo = Modelo {
    nombre: "PlanRevision",
    campos: &[
        campo("version", Tipo::Entero, NO),
        campo("timestamp", STR, NO),
        campo("modified_by", STR, NO),
        campo("change_request", Tipo::Opcional(&Tipo::Modelo(&PETICION_CAMBIO)), Defecto::Valor(|| Valor::Nulo)),
        campo("summary", STR, NO),
    ],
    antes: None,
};

/// `StudyPlanState`
pub static PLAN: Modelo = Modelo {
    nombre: "StudyPlanState",
    campos: &[
        campo("schema_version", Tipo::Entero, Defecto::Valor(|| Valor::Entero(2))),
        campo("plan_id", STR, Defecto::Valor(|| Valor::Texto(id_al_azar("plan", 8)))),
        campo("version", Tipo::Entero, Defecto::Valor(|| Valor::Entero(1))),
        campo("status", Tipo::Enum(ESTADOS_PLAN), Defecto::Valor(|| t("DRAFT"))),
        campo("user_goal", STR, NO),
        campo("knowledge_map", Tipo::Opcional(&Tipo::Modelo(&MAPA)), Defecto::Valor(|| Valor::Nulo)),
        campo("practical_curriculum", Tipo::Opcional(&Tipo::Modelo(&CURRICULO)), Defecto::Valor(|| Valor::Nulo)),
        campo("executable_learning_plan", Tipo::Opcional(&Tipo::Modelo(&PLAN_EJECUTABLE)), Defecto::Valor(|| Valor::Nulo)),
        campo("decision_traces", Tipo::Lista(&Tipo::Modelo(&TRAZA)), Defecto::Valor(vacia)),
        campo("revisions", Tipo::Lista(&Tipo::Modelo(&REVISION)), Defecto::Valor(vacia)),
        campo("completed_validation_criteria", Tipo::Dict(&LISTA_STR), Defecto::Valor(vacio)),
        campo("completed_notebooks", LISTA_STR, Defecto::Valor(vacia)),
        campo("progress_percentage", Tipo::Real, Defecto::Valor(|| Valor::Real(0.0))),
        campo("created_at", STR, Defecto::Valor(ahora)),
        campo("updated_at", STR, Defecto::Valor(ahora)),
    ],
    antes: None,
};

// ---------------------------------------------------------------------------------------------- aprendizaje guiado

pub static BLOQUE: Modelo = Modelo {
    nombre: "SeguimientoBlock",
    campos: &[
        campo("block_id", STR, Defecto::Valor(|| Valor::Texto(id_al_azar("blk", 6)))),
        campo("title", STR, NO),
        campo("description", STR, NO),
        campo("learning_objective", STR, Defecto::Valor(|| t(""))),
        campo("validation_check", STR, Defecto::Valor(|| t(""))),
        campo("topics", LISTA_STR, NO),
        campo("type", STR, Defecto::Valor(|| t("theory"))),
        campo("estimated_time", STR, Defecto::Valor(|| t("N/A"))),
    ],
    antes: Some(|v| {
        let v = rellenar(
            de_texto(v, "title"),
            &[("title", &|_| t("Bloque de estudio")), ("description", &|d| tx(d, "learning_objective", "Estudio del bloque."))],
        );
        match v {
            Valor::Mapa(mut m) => {
                match m.get("topics") {
                    Some(Valor::Texto(s)) => {
                        let temas: Vec<Valor> = s
                            .split(',')
                            .map(prig_plataforma::py::strip)
                            .filter(|x| !x.is_empty())
                            .map(|x| Valor::Texto(x.to_string()))
                            .collect();
                        m.poner("topics", Valor::Lista(temas));
                    }
                    Some(x) if x.verdad() => {}
                    _ => {
                        let titulo = texto(m.get("title"), "Tema general");
                        m.poner("topics", Valor::Lista(vec![Valor::Texto(titulo)]));
                    }
                }
                Valor::Mapa(m)
            }
            otro => otro,
        }
    }),
};

/// `SeguimientoPath`: una ruta de aprendizaje guiado
pub static RUTA: Modelo = Modelo {
    nombre: "SeguimientoPath",
    campos: &[
        campo("schema_version", Tipo::Entero, Defecto::Valor(|| Valor::Entero(3))),
        campo("id", STR, Defecto::Valor(|| Valor::Texto(id_al_azar("seg", 8)))),
        campo("goal", STR, NO),
        campo("source", STR, Defecto::Valor(|| t("rapido"))),
        campo("level", STR, Defecto::Valor(|| t("Intermedio"))),
        campo("focus", STR, Defecto::Valor(|| t("Práctico"))),
        campo("origin_plan_id", OPT_STR, Defecto::Valor(|| Valor::Nulo)),
        campo("knowledge_map", Tipo::Opcional(&DICT_ANY), Defecto::Valor(|| Valor::Nulo)),
        campo("decision_traces", LISTA_DICT_ANY, Defecto::Valor(vacia)),
        campo("notebooks", LISTA_DICT_ANY, Defecto::Valor(vacia)),
        campo("topics_raw", STR, Defecto::Valor(|| t(""))),
        campo("blocks", Tipo::Lista(&Tipo::Modelo(&BLOQUE)), Defecto::Valor(vacia)),
        campo("rationale", STR, Defecto::Valor(|| t(""))),
        campo("completed_blocks", LISTA_STR, Defecto::Valor(vacia)),
        campo("completion_dates", Tipo::Dict(&Tipo::Texto), Defecto::Valor(vacio)),
        campo("created_at", STR, Defecto::Valor(ahora)),
    ],
    antes: None,
};

// ---------------------------------------------------------------------------------------------- migraciones

/// `CURRENT_VERSIONS`
pub fn version_actual(tipo: &str) -> Option<i128> {
    match tipo {
        "study_plan" => Some(2),
        "seguimiento" => Some(3),
        "dataset" => Some(2),
        _ => None,
    }
}

/// `detect_version`: la declarada; sin marca (o ilegible), v1
fn version_de(doc: &Mapa) -> i128 {
    let n = match doc.get("schema_version") {
        None => Some(1),
        Some(Valor::Entero(n)) => Some(*n),
        Some(Valor::Bool(b)) => Some(*b as i128),
        Some(Valor::Real(x)) if x.is_finite() => Some(x.trunc() as i128),
        Some(Valor::Texto(s)) => s.trim().parse::<i128>().ok(),
        _ => None,
    };
    n.unwrap_or(1).max(1)
}

fn por_defecto(doc: &mut Mapa, k: &str, v: Valor) {
    if !doc.contiene(k) {
        doc.poner(k, v);
    }
}

fn migrar_paso(tipo: &str, de: i128, doc: &mut Mapa) -> Result<(), String> {
    match (tipo, de) {
        ("seguimiento", 1) => {
            por_defecto(doc, "completion_dates", vacio());
            if let Some(creado) = doc.get("created_at").filter(|c| c.verdad()).cloned() {
                let hechos = match doc.get("completed_blocks") {
                    Some(Valor::Lista(l)) => l.clone(),
                    _ => Vec::new(),
                };
                if let Some(Valor::Mapa(fechas)) = doc.get_mut("completion_dates") {
                    for b in hechos {
                        let k = b.texto_o_repr();
                        if !fechas.contiene(&k) {
                            fechas.poner(k, creado.clone());
                        }
                    }
                }
            }
        }
        ("seguimiento", 2) => {
            por_defecto(doc, "source", t("rapido"));
            por_defecto(doc, "level", t("Intermedio"));
            por_defecto(doc, "focus", t("Práctico"));
            por_defecto(doc, "origin_plan_id", Valor::Nulo);
            por_defecto(doc, "knowledge_map", Valor::Nulo);
            por_defecto(doc, "decision_traces", vacia());
            por_defecto(doc, "notebooks", vacia());
        }
        ("study_plan", 1) => {
            por_defecto(doc, "completed_validation_criteria", vacio());
            por_defecto(doc, "completed_notebooks", vacia());
            por_defecto(doc, "decision_traces", vacia());
            por_defecto(doc, "revisions", vacia());
        }
        ("dataset", 1) => {
            por_defecto(doc, "activity_heatmap", vacio());
            por_defecto(doc, "acquired_competencies", vacia());
            por_defecto(doc, "mastered_topics", vacia());
        }
        _ => return Err(format!("Falta la migración de {tipo} v{de} a v{}", de + 1)),
    }
    Ok(())
}

/// `migrate(kind, doc)`: (documento en la versión actual, ¿cambió?)
pub fn migrar(tipo: &str, mut doc: Mapa) -> Result<(Mapa, bool), String> {
    let objetivo = version_actual(tipo).ok_or_else(|| format!("Tipo de documento desconocido: {tipo}"))?;
    let mut v = version_de(&doc);
    if v > objetivo {
        return Err(format!(
            "El documento usa el esquema v{v}, más nuevo que el soportado (v{objetivo}). Actualiza Prig para abrirlo sin perder datos."
        ));
    }
    let mut cambio = false;
    while v < objetivo {
        migrar_paso(tipo, v, &mut doc)?;
        v += 1;
        cambio = true;
    }
    doc.poner("schema_version", Valor::Entero(objetivo));
    Ok((doc, cambio))
}

/// `load_migrated(path, kind)`: el JSON migrado; si migró, una copia `.v<N>.bak` del original (si no la había)
pub fn cargar_migrado(ruta: &Path, tipo: &str) -> Result<Mapa, String> {
    let texto = std::fs::read_to_string(ruta).map_err(|e| e.to_string())?;
    let Valor::Mapa(doc) = prig_plataforma::json::leer(&texto)? else { return Err("el documento no es un objeto".into()) };
    let original = version_de(&doc);
    let (doc, cambio) = migrar(tipo, doc)?;
    if cambio {
        let bak = ruta.with_file_name(format!("{}.v{original}.bak", ruta.file_name().unwrap_or_default().to_string_lossy()));
        if !bak.exists() {
            if let Err(e) = std::fs::copy(ruta, &bak) {
                tracing_aviso(&format!("⚠️ No se pudo respaldar {}: {e}", ruta.display()));
            } else if let Ok(m) = std::fs::metadata(ruta).and_then(|m| m.modified()) {
                // copy2: también la fecha
                if let Ok(f) = std::fs::File::options().write(true).open(&bak) {
                    let _ = f.set_modified(m);
                }
            }
        }
    }
    Ok(doc)
}

fn tracing_aviso(t: &str) {
    eprintln!("{t}");
}

#[cfg(test)]
mod pruebas {
    use super::*;
    use prig_plataforma::modelo::validar;

    #[test]
    fn ruta_como_pydantic() {
        let doc = prig_plataforma::json::leer(r#"{"id":"seg_1","goal":"g","created_at":"2026-01-01","blocks":["Intro",{"block_id":"b1","learning_objective":" obj ","topics":"a, b,,c"},{"block_id":"b2","title":"T","topics":[]}],"completed_blocks":["b1"],"extra":1}"#).unwrap();
        let mut m = validar(&RUTA, doc).unwrap();
        if let Some(Valor::Lista(b)) = m.get_mut("blocks") {
            if let Valor::Mapa(x) = &mut b[0] {
                assert!(x.texto("block_id").unwrap().starts_with("blk_"));
                x.poner("block_id", "blk_871a8a");
            }
        }
        let esperado = r#"{"schema_version": 3, "id": "seg_1", "goal": "g", "source": "rapido", "level": "Intermedio", "focus": "Pr\u00e1ctico", "origin_plan_id": null, "knowledge_map": null, "decision_traces": [], "notebooks": [], "topics_raw": "", "blocks": [{"block_id": "blk_871a8a", "title": "Intro", "description": "Estudio del bloque.", "learning_objective": "", "validation_check": "", "topics": ["Intro"], "type": "theory", "estimated_time": "N/A"}, {"block_id": "b1", "title": "Bloque de estudio", "description": "obj", "learning_objective": " obj ", "validation_check": "", "topics": ["a", "b", "c"], "type": "theory", "estimated_time": "N/A"}, {"block_id": "b2", "title": "T", "description": "Estudio del bloque.", "learning_objective": "", "validation_check": "", "topics": ["T"], "type": "theory", "estimated_time": "N/A"}], "rationale": "", "completed_blocks": ["b1"], "completion_dates": {}, "created_at": "2026-01-01"}"#;
        assert_eq!(prig_plataforma::json::escribir_compacto(&Valor::Mapa(m)), esperado);
    }

    #[test]
    fn migra_seguimiento() {
        let Valor::Mapa(d) = prig_plataforma::json::leer(r#"{"id":"s","created_at":"c","completed_blocks":["a"]}"#).unwrap() else { panic!() };
        let (d, cambio) = migrar("seguimiento", d).unwrap();
        assert!(cambio);
        assert_eq!(d.valor("schema_version"), &Valor::Entero(3));
        assert_eq!(prig_plataforma::json::escribir_compacto(d.valor("completion_dates")), r#"{"a": "c"}"#);
        let Valor::Mapa(n) = prig_plataforma::json::leer(r#"{"schema_version":9}"#).unwrap() else { panic!() };
        assert!(migrar("seguimiento", n).is_err());
    }
}

// ---------------------------------------------------------------------------------------------- repositorios

/// `leer` un JSON (None si falta o está roto)
fn leer_doc(ruta: &Path) -> Option<Valor> {
    prig_plataforma::json::leer(&std::fs::read_to_string(ruta).ok()?).ok()
}

/// `len(x)` de Python para lo que sale de un JSON (None si no tiene longitud)
fn largo(v: &Valor) -> Option<usize> {
    match v {
        Valor::Lista(l) => Some(l.len()),
        Valor::Mapa(m) => Some(m.len()),
        Valor::Texto(t) => Some(t.chars().count()),
        _ => None,
    }
}

/// Los JSON de una carpeta, en el orden de `os.listdir`
pub fn jsons(dir: &Path) -> Vec<std::path::PathBuf> {
    match std::fs::read_dir(dir) {
        Ok(l) => l.flatten().filter(|e| e.file_name().to_str().is_some_and(|n| n.ends_with(".json"))).map(|e| e.path()).collect(),
        Err(_) => Vec::new(),
    }
}

/// `sort(key=x.get(clave) or "", reverse=True)` (estable; lo que no es texto ordena como "")
pub fn ordenar_desc(v: &mut [Mapa], clave: &str) {
    v.sort_by_key(|m| std::cmp::Reverse(m.texto(clave).unwrap_or_default().to_string()));
}

/// Un JSON con la forma de `model_dump_json(indent=2)` (comprobado: los mismos bytes)
pub fn escribir_modelo(ruta: &Path, m: &Mapa) -> std::io::Result<()> {
    std::fs::write(ruta, prig_plataforma::json::escribir(&Valor::Mapa(m.clone()), 2))
}

fn dir_seguimientos(espacio: &Path) -> std::path::PathBuf {
    espacio.join(".prig_seguimientos")
}

/// `SeguimientoRepository.list_all()`: el resumen de cada seguimiento (los rotos se saltan)
pub fn listar_seguimientos(espacio: &Path) -> Vec<Mapa> {
    let mut items = Vec::new();
    for ruta in jsons(&dir_seguimientos(espacio)) {
        let Some(Valor::Mapa(d)) = leer_doc(&ruta) else { continue };
        let vacia = Valor::Lista(Vec::new());
        let (Some(hechos), Some(bloques)) = (largo(d.get("completed_blocks").unwrap_or(&vacia)), largo(d.get("blocks").unwrap_or(&vacia))) else {
            continue;
        };
        // round() de Python: a entero, empates a par
        let progreso = ((hechos as f64 / bloques.max(1) as f64) * 100.0).round_ties_even() as i128;
        items.push(
            Mapa::new()
                .con("id", d.get("id").cloned().unwrap_or(Valor::Nulo))
                .con("goal", d.get("goal").cloned().unwrap_or(Valor::Nulo))
                .con("created_at", d.get("created_at").cloned().unwrap_or(Valor::Nulo))
                .con("progress", Valor::Entero(progreso)),
        );
    }
    ordenar_desc(&mut items, "created_at");
    items
}

/// `SeguimientoRepository.load(id)`: None si no existe; Err si no se puede migrar o validar
pub fn cargar_seguimiento(espacio: &Path, id: &str) -> Result<Option<Mapa>, String> {
    let ruta = dir_seguimientos(espacio).join(format!("{id}.json"));
    if !ruta.exists() {
        return Ok(None);
    }
    let doc = cargar_migrado(&ruta, "seguimiento")?;
    prig_plataforma::modelo::validar(&RUTA, Valor::Mapa(doc)).map(Some).map_err(|f| format!("{} en {}", f.tipo, f.donde))
}

/// `SeguimientoRepository.save(path)`
pub fn guardar_seguimiento(espacio: &Path, s: &Mapa) -> std::io::Result<()> {
    let id = s.get("id").map(|v| v.texto_py()).unwrap_or_default();
    escribir_modelo(&dir_seguimientos(espacio).join(format!("{id}.json")), s)
}

/// Marca los bloques hechos de un seguimiento con la fecha en que se marcó cada uno (los que se desmarcan pierden la
/// suya), como `guided_progress` y `update_seguimiento_progress`
pub fn marcar_bloques(s: &mut Mapa, hechos: &[String]) {
    let antes: Vec<String> = s.lista("completed_blocks").unwrap_or(&[]).iter().map(|v| v.texto_py()).collect();
    let ahora = prig_plataforma::py::ahora_iso();
    let mut fechas = s.mapa("completion_dates").cloned().unwrap_or_default();
    let mut vistos = std::collections::HashSet::new();
    for b in hechos {
        if !antes.contains(b) && vistos.insert(b.clone()) {
            fechas.poner(b.clone(), ahora.clone());
        }
    }
    for b in &antes {
        if !hechos.contains(b) {
            fechas.quitar(b);
        }
    }
    s.poner("completion_dates", Valor::Mapa(fechas));
    s.poner("completed_blocks", Valor::Lista(hechos.iter().cloned().map(Valor::Texto).collect()));
}

fn dir_planes(espacio: &Path) -> std::path::PathBuf {
    espacio.join(".prig_plans")
}

/// `StudyPlanRepository.list_plans()`: los manifiestos de las carpetas y los planes antiguos de un archivo
pub fn listar_planes(espacio: &Path) -> Vec<Mapa> {
    let dir = dir_planes(espacio);
    let Ok(lectura) = std::fs::read_dir(&dir) else { return Vec::new() };
    let mut planes = Vec::new();
    for e in lectura.flatten() {
        let ruta = e.path();
        let nombre = e.file_name().to_string_lossy().into_owned();
        if ruta.is_dir() {
            let manifiesto = ruta.join("manifest.json");
            if manifiesto.exists() {
                if let Some(Valor::Mapa(m)) = leer_doc(&manifiesto) {
                    planes.push(m);
                }
            }
        } else if nombre.ends_with(".json") {
            let Some(Valor::Mapa(d)) = leer_doc(&ruta) else { continue };
            planes.push(
                Mapa::new()
                    .con("plan_id", d.get("plan_id").cloned().unwrap_or(Valor::Nulo))
                    .con("user_goal", d.get("user_goal").cloned().unwrap_or(Valor::Nulo))
                    .con("current_version", d.get("version").cloned().unwrap_or(Valor::Entero(1)))
                    .con("status", d.get("status").cloned().unwrap_or(Valor::Texto("DRAFT".into())))
                    .con("updated_at", d.get("updated_at").cloned().unwrap_or(Valor::Texto(String::new()))),
            );
        }
    }
    ordenar_desc(&mut planes, "updated_at");
    planes
}

/// `StudyPlanRepository.load_state(plan_id)`: el `current.json` de su carpeta o el archivo antiguo
pub fn cargar_plan(espacio: &Path, id: &str) -> Result<Option<Mapa>, String> {
    let dir = dir_planes(espacio).join(id);
    let ruta = if dir.exists() {
        dir.join("current.json")
    } else {
        dir_planes(espacio).join(format!("{id}.json"))
    };
    if !ruta.exists() {
        return Ok(None);
    }
    let doc = cargar_migrado(&ruta, "study_plan")?;
    prig_plataforma::modelo::validar(&PLAN, Valor::Mapa(doc)).map(Some).map_err(|f| format!("{} en {}", f.tipo, f.donde))
}

/// `StudyPlanRepository.save_state`: versión inmutable `v{N}.json`, `current.json` y el manifiesto
pub fn guardar_plan(espacio: &Path, plan: &mut Mapa) -> std::io::Result<()> {
    plan.poner("updated_at", prig_plataforma::py::ahora_iso());
    let id = plan.get("plan_id").map(|v| v.texto_py()).unwrap_or_default();
    let dir = dir_planes(espacio).join(&id);
    std::fs::create_dir_all(&dir)?;
    let version = plan.get("version").cloned().unwrap_or(Valor::Entero(1));
    escribir_modelo(&dir.join(format!("v{}.json", version.texto_o_repr())), plan)?;
    escribir_modelo(&dir.join("current.json"), plan)?;
    let manifiesto = Mapa::new()
        .con("plan_id", id)
        .con("user_goal", plan.valor("user_goal").clone())
        .con("current_version", version.clone())
        .con("status", plan.valor("status").clone())
        .con("created_at", plan.valor("created_at").clone())
        .con("updated_at", plan.valor("updated_at").clone())
        .con("versions_count", version)
        .con("revisions", plan.get("revisions").cloned().unwrap_or(Valor::Lista(Vec::new())));
    escribir_modelo(&dir.join("manifest.json"), &manifiesto)
}

/// `StudyPlanState.update_progress_percentage`
pub fn actualizar_progreso(plan: &mut Mapa) {
    let mut total = 0usize;
    let mut hechos = 0usize;
    let criterios = plan.mapa("completed_validation_criteria").cloned().unwrap_or_default();
    if let Some(curr) = plan.mapa("practical_curriculum") {
        for m in curr.lista("modules").unwrap_or(&[]) {
            let Valor::Mapa(m) = m else { continue };
            let lista = m.lista("validation_criteria").unwrap_or(&[]);
            total += lista.len();
            let del_modulo = criterios.get(m.texto("module_id").unwrap_or("")).and_then(|v| if let Valor::Lista(l) = v { Some(l.clone()) } else { None }).unwrap_or_default();
            hechos += lista.iter().filter(|c| del_modulo.contains(c)).count();
        }
    }
    let cuadernos = plan.lista("completed_notebooks").map(|l| l.to_vec()).unwrap_or_default();
    if let Some(ej) = plan.mapa("executable_learning_plan") {
        for m in ej.lista("modules_notebooks").unwrap_or(&[]) {
            let Valor::Mapa(m) = m else { continue };
            for nb in m.lista("notebooks").unwrap_or(&[]) {
                let Valor::Mapa(nb) = nb else { continue };
                total += 1;
                if cuadernos.contains(nb.valor("notebook_id")) {
                    hechos += 1;
                }
            }
        }
    }
    let p = if total == 0 { 0.0 } else { prig_plataforma::valor::redondear(hechos as f64 / total as f64 * 100.0, 1) };
    plan.poner("progress_percentage", Valor::Real(p));
}

/// `toggle_validation_criterion`: marca o desmarca un criterio de un módulo
pub fn alternar_criterio(plan: &mut Mapa, modulo: &str, criterio: &str) {
    let mut todos = plan.mapa("completed_validation_criteria").cloned().unwrap_or_default();
    let mut l = match todos.get(modulo) {
        Some(Valor::Lista(l)) => l.clone(),
        _ => Vec::new(),
    };
    let c = Valor::Texto(criterio.into());
    match l.iter().position(|x| *x == c) {
        Some(i) => {
            l.remove(i);
        }
        None => l.push(c),
    }
    todos.poner(modulo, Valor::Lista(l));
    plan.poner("completed_validation_criteria", Valor::Mapa(todos));
    actualizar_progreso(plan);
}

/// `toggle_notebook_completion`: marca o desmarca un cuaderno
pub fn alternar_cuaderno(plan: &mut Mapa, cuaderno: &str) {
    let mut l = plan.lista("completed_notebooks").map(|l| l.to_vec()).unwrap_or_default();
    let c = Valor::Texto(cuaderno.into());
    match l.iter().position(|x| *x == c) {
        Some(i) => {
            l.remove(i);
        }
        None => l.push(c),
    }
    plan.poner("completed_notebooks", Valor::Lista(l));
    actualizar_progreso(plan);
}

// ---------------------------------------------------------------------------------------------- el motor del plan

/// `StudyPlanRepository.load_state(plan_id, version)`: con `version` (si no es 0), su `v{N}.json`; el archivo antiguo
/// de un plan sin carpeta se carga aunque se pida una versión
pub fn cargar_plan_version(espacio: &Path, id: &str, version: Option<i128>) -> Result<Option<Mapa>, String> {
    let dir = dir_planes(espacio).join(id);
    let ruta = match version {
        Some(v) if v != 0 && dir.exists() => dir.join(format!("v{v}.json")),
        _ => return cargar_plan(espacio, id),
    };
    if !ruta.exists() {
        return Ok(None);
    }
    let doc = cargar_migrado(&ruta, "study_plan")?;
    prig_plataforma::modelo::validar(&PLAN, Valor::Mapa(doc)).map(Some).map_err(|f| fallo_py(&PLAN, &f))
}

/// Un error de validación con la cabecera de `str(ValidationError)` de pydantic
pub fn fallo_py(m: &Modelo, f: &prig_plataforma::modelo::Fallo) -> String {
    format!("1 validation error for {}\n{}\n  [type={}]", m.nombre, f.donde, f.tipo)
}

/// Valida contra un modelo (`Model.model_validate`), con el error como texto
pub fn validar_modelo(m: &Modelo, v: Valor) -> Result<Mapa, String> {
    prig_plataforma::modelo::validar(m, v).map_err(|f| fallo_py(m, &f))
}

/// `StudyPlanEngine.create_new_plan`
pub fn nuevo_plan(espacio: &Path, objetivo: &str) -> Result<Mapa, String> {
    let mut p = validar_modelo(&PLAN, Valor::Mapa(Mapa::new().con("user_goal", objetivo).con("status", "DRAFT")))?;
    guardar_plan(espacio, &mut p).map_err(|e| e.to_string())?;
    Ok(p)
}

/// `PlanValidator.VALID_TRANSITIONS`
fn transiciones(estado: &str) -> &'static [&'static str] {
    match estado {
        "DRAFT" => &["KNOWLEDGE_REVIEW"],
        "KNOWLEDGE_REVIEW" => &["KNOWLEDGE_REVIEW", "KNOWLEDGE_APPROVED"],
        "KNOWLEDGE_APPROVED" => &["PRACTICAL_REVIEW"],
        "PRACTICAL_REVIEW" => &["PRACTICAL_REVIEW", "PRACTICAL_APPROVED"],
        "PRACTICAL_APPROVED" => &["LEARNING_REVIEW"],
        "LEARNING_REVIEW" => &["LEARNING_REVIEW", "APPROVED"],
        _ => &[],
    }
}

/// `PlanValidator.validate_state_transition`
pub fn validar_transicion(actual: &str, siguiente: &str) -> Result<(), String> {
    let permitidas = transiciones(actual);
    if permitidas.contains(&siguiente) {
        return Ok(());
    }
    let lista: Vec<String> = permitidas.iter().map(|s| format!("'{s}'")).collect();
    Err(format!("❌ Transición de estado no válida: {actual} ➔ {siguiente}. Permitidas: [{}]", lista.join(", ")))
}

fn revision(version: Valor, por: &str, cambio: Valor, resumen: String) -> Valor {
    let r = Mapa::new()
        .con("version", version)
        .con("timestamp", prig_plataforma::py::ahora_iso())
        .con("modified_by", por)
        .con("change_request", cambio)
        .con("summary", resumen);
    validar_modelo(&REVISION, Valor::Mapa(r)).map(Valor::Mapa).unwrap_or(Valor::Nulo)
}

fn anadir(m: &mut Mapa, clave: &str, v: Valor) {
    let mut l = m.lista(clave).map(|l| l.to_vec()).unwrap_or_default();
    l.push(v);
    m.poner(clave, Valor::Lista(l));
}

/// `approve_knowledge_step`, `approve_practical_step` y `approve_learning_step`; Err es el `ValueError` (un 400)
pub fn aprobar(espacio: &Path, id: &str, paso: &str) -> Result<Mapa, String> {
    let (clave, falta, siguiente, resumen) = match paso {
        "knowledge" => ("knowledge_map", "No existe un KnowledgeMap válido para aprobar en este plan.", "KNOWLEDGE_APPROVED", "Aprobación del Módulo 1 (Ciclo Básico - KnowledgeMap)"),
        "practical" => ("practical_curriculum", "No existe un PracticalCurriculum válido para aprobar.", "PRACTICAL_APPROVED", "Aprobación del Módulo 2 (Ciclo Práctico - PracticalCurriculum)"),
        _ => ("executable_learning_plan", "No existe un ExecutableLearningPlan para aprobar.", "APPROVED", "✨ PLAN APROBADO COMPLETAMENTE PARA COMENZAR"),
    };
    let mut p = match cargar_plan(espacio, id)? {
        Some(p) if matches!(p.get(clave), Some(Valor::Mapa(_))) => p,
        _ => return Err(falta.into()),
    };
    validar_transicion(p.texto("status").unwrap_or(""), siguiente)?;
    p.poner("status", siguiente);
    let r = revision(p.valor("version").clone(), "USER", Valor::Nulo, resumen.into());
    anadir(&mut p, "revisions", r);
    guardar_plan(espacio, &mut p).map_err(|e| e.to_string())?;
    Ok(p)
}

fn minus(t: &str) -> String {
    t.to_lowercase()
}

/// `apply_change_request`: aplica la orden de cambio (ya validada como `ChangeRequest`) en una versión nueva del plan
pub fn aplicar_cambio(espacio: &Path, id: &str, cambio: &Mapa) -> Result<Mapa, String> {
    let Some(mut p) = cargar_plan(espacio, id)? else { return Err(format!("Plan no encontrado: {id}")) };
    let version = match p.valor("version") {
        Valor::Entero(n) => n + 1,
        _ => 2,
    };
    p.poner("version", Valor::Entero(version));
    let accion = cambio.texto("action").unwrap_or("").to_string();
    let objetivo = cambio.texto("target").unwrap_or("").to_string();
    let razon = cambio.get("reason").filter(|r| r.verdad()).map(|r| r.texto_py());
    let o = minus(&objetivo);
    let mut km = p.mapa("knowledge_map").cloned();
    let mut curr = p.mapa("practical_curriculum").cloned();
    match (accion.as_str(), km.as_mut(), curr.as_mut()) {
        ("ADD_PREREQUISITE", Some(k), _) => {
            let pr = Mapa::new()
                .con("name", objetivo.clone())
                .con("reason", razon.clone().unwrap_or_else(|| "Añadido por solicitud del usuario".into()))
                .con("required", true);
            anadir(k, "prerequisites", Valor::Mapa(validar_modelo(&PRERREQUISITO, Valor::Mapa(pr))?));
        }
        ("REMOVE_PREREQUISITE", Some(k), _) => {
            let quedan: Vec<Valor> = k
                .lista("prerequisites")
                .unwrap_or(&[])
                .iter()
                .filter(|x| matches!(x, Valor::Mapa(m) if !minus(m.texto("name").unwrap_or("")).contains(&o)))
                .cloned()
                .collect();
            k.poner("prerequisites", Valor::Lista(quedan));
        }
        ("ADD_CONCEPT", Some(k), _) => {
            let mut doms = k.lista("domains").map(|l| l.to_vec()).unwrap_or_default();
            if let Some(Valor::Mapa(d)) = doms.first_mut() {
                let mut temas = d.lista("topics").map(|l| l.to_vec()).unwrap_or_default();
                if let Some(Valor::Mapa(t)) = temas.first_mut() {
                    let c = Mapa::new()
                        .con("concept_id", id_al_azar("conc", 6))
                        .con("name", objetivo.clone())
                        .con("specifications", razon.clone().unwrap_or_else(|| "Añadido manualmente".into()));
                    anadir(t, "concepts", Valor::Mapa(validar_modelo(&CONCEPTO, Valor::Mapa(c))?));
                    d.poner("topics", Valor::Lista(temas));
                    k.poner("domains", Valor::Lista(doms));
                }
            }
        }
        ("REMOVE_CONCEPT", Some(k), _) => {
            let mut doms = k.lista("domains").map(|l| l.to_vec()).unwrap_or_default();
            for d in doms.iter_mut() {
                let Valor::Mapa(d) = d else { continue };
                let mut temas = d.lista("topics").map(|l| l.to_vec()).unwrap_or_default();
                for t in temas.iter_mut() {
                    let Valor::Mapa(t) = t else { continue };
                    let quedan: Vec<Valor> = t
                        .lista("concepts")
                        .unwrap_or(&[])
                        .iter()
                        .filter(|c| matches!(c, Valor::Mapa(c) if !minus(c.texto("name").unwrap_or("")).contains(&o) && c.texto("concept_id") != Some(objetivo.as_str())))
                        .cloned()
                        .collect();
                    t.poner("concepts", Valor::Lista(quedan));
                }
                d.poner("topics", Valor::Lista(temas));
            }
            k.poner("domains", Valor::Lista(doms));
        }
        ("ADD_TOPIC", Some(k), _) => {
            let mut doms = k.lista("domains").map(|l| l.to_vec()).unwrap_or_default();
            if let Some(Valor::Mapa(d)) = doms.first_mut() {
                let c = Mapa::new().con("concept_id", id_al_azar("conc", 6)).con("name", format!("Concepto {objetivo}"));
                let t = Mapa::new()
                    .con("topic_id", id_al_azar("top", 6))
                    .con("name", objetivo.clone())
                    .con("concepts", Valor::Lista(vec![Valor::Mapa(c)]));
                anadir(d, "topics", Valor::Mapa(validar_modelo(&TEMA, Valor::Mapa(t))?));
                k.poner("domains", Valor::Lista(doms));
            }
        }
        ("MODIFY_OBJECTIVE", Some(k), _) => k.poner("goal", objetivo.clone()),
        ("ADD_PRACTICAL_MODULE", _, Some(c)) => {
            let n = c.lista("modules").map(|l| l.len()).unwrap_or(0) + 1;
            let m = Mapa::new()
                .con("module_id", format!("mod_{n:02}"))
                .con("name", objetivo.clone())
                .con("objective", razon.clone().unwrap_or_else(|| format!("Practicar {objetivo}")))
                .con("validation_criteria", Valor::Lista(vec![Valor::Texto(format!("✓ Implementar {objetivo}"))]));
            anadir(c, "modules", Valor::Mapa(validar_modelo(&MODULO_PRACTICO, Valor::Mapa(m))?));
        }
        _ => {}
    }
    if let Some(k) = km {
        p.poner("knowledge_map", Valor::Mapa(k));
    }
    if let Some(c) = curr {
        p.poner("practical_curriculum", Valor::Mapa(c));
    }
    let r = revision(
        Valor::Entero(version),
        "USER_ASSISTANT",
        Valor::Mapa(cambio.clone()),
        format!("Versión {version}: Corrección aplicada ({accion} -> {objetivo})"),
    );
    anadir(&mut p, "revisions", r);
    guardar_plan(espacio, &mut p).map_err(|e| e.to_string())?;
    Ok(p)
}

fn ids_de_conceptos(km: &Mapa) -> Vec<Valor> {
    let mut v = Vec::new();
    for d in km.lista("domains").unwrap_or(&[]) {
        let Valor::Mapa(d) = d else { continue };
        for t in d.lista("topics").unwrap_or(&[]) {
            let Valor::Mapa(t) = t else { continue };
            for c in t.lista("concepts").unwrap_or(&[]) {
                if let Valor::Mapa(c) = c {
                    v.push(c.valor("concept_id").clone());
                }
            }
        }
    }
    v
}

/// `PlanValidator.validate_knowledge_map`
pub fn avisos_mapa(km: &Mapa) -> Vec<String> {
    let mut avisos = Vec::new();
    let mut vistos: Vec<Valor> = Vec::new();
    for id in ids_de_conceptos(km) {
        if vistos.contains(&id) {
            avisos.push(format!("ID de concepto duplicado detectado: {}", id.texto_py()));
        }
        vistos.push(id);
    }
    for r in km.lista("relationships").unwrap_or(&[]) {
        let Valor::Mapa(r) = r else { continue };
        for k in ["source_concept_id", "target_concept_id"] {
            if !vistos.contains(r.valor(k)) {
                avisos.push(format!("Relación referencia a concept_id inexistente: {}", r.valor(k).texto_py()));
            }
        }
    }
    avisos
}

/// `PlanValidator.validate_practical_curriculum`
pub fn avisos_curriculo(curr: &Mapa, km: &Mapa) -> Vec<String> {
    let ids = ids_de_conceptos(km);
    let mut avisos = Vec::new();
    for m in curr.lista("modules").unwrap_or(&[]) {
        let Valor::Mapa(m) = m else { continue };
        for c in m.lista("concepts").unwrap_or(&[]) {
            if !ids.is_empty() && !ids.contains(c) {
                avisos.push(format!(
                    "Módulo práctico '{}' hace referencia a concept_id no encontrado en KnowledgeMap: {}",
                    m.valor("module_id").texto_py(),
                    c.texto_py()
                ));
            }
        }
    }
    avisos
}

/// `PlanValidator.validate_executable_plan`
pub fn avisos_ejecutable(ej: &Mapa, curr: &Mapa) -> Vec<String> {
    let ids: Vec<Valor> = curr.lista("modules").unwrap_or(&[]).iter().filter_map(|m| match m { Valor::Mapa(m) => Some(m.valor("module_id").clone()), _ => None }).collect();
    let mut avisos = Vec::new();
    for m in ej.lista("modules_notebooks").unwrap_or(&[]) {
        let Valor::Mapa(m) = m else { continue };
        if !ids.is_empty() && !ids.contains(m.valor("module_id")) {
            avisos.push(format!("ExecutableModule hace referencia a module_id no existente en Curriculum: {}", m.valor("module_id").texto_py()));
        }
    }
    avisos
}

/// `NotebookSafetyLayer.generate_explained_notebook_content`: el `.ipynb` con la cabecera, la teoría y el código
pub fn cuaderno_explicado(nombre: &str, objetivo: &str, criterios: &[Valor], codigo: &str) -> Valor {
    let criterios_md = if criterios.is_empty() {
        "- [ ] Práctica completada con éxito".to_string()
    } else {
        criterios.iter().map(|c| format!("- [ ] {}", c.texto_py())).collect::<Vec<_>>().join("\n")
    };
    let cabecera = format!(
        "# 📓 {nombre}\n\n### 🎯 Objetivo de Aprendizaje:\n{objetivo}\n\n### 📋 Criterios de Validación de Aprendizaje (validation_criteria):\n{criterios_md}\n\n---\n*Cuaderno generado automáticamente por el **Notebook & Learning Manager** de Prig IDE.*"
    );
    let teoria = "## 💡 Explicación Teórica & Conceptos Base\n\nEn este cuaderno pondremos en práctica los conceptos del módulo.\nRevisa el código a continuación, ejecuta las celdas secuencialmente (`Shift + Enter`) y verifica cada criterio de validación.";
    let bloque = if codigo.is_empty() {
        "# Importaciones principales\nimport sys\nimport numpy as np\n\n# Imprimir entorno\nprint('✨ Cuaderno de práctica activo')\n".to_string()
    } else {
        prig_plataforma::py::strip(codigo).to_string()
    };
    let md = |t: String| Valor::Mapa(Mapa::new().con("cell_type", "markdown").con("metadata", Valor::Mapa(Mapa::new())).con("source", Valor::Lista(vec![Valor::Texto(t)])));
    let celdas = vec![
        md(cabecera),
        md(teoria.to_string()),
        Valor::Mapa(
            Mapa::new()
                .con("cell_type", "code")
                .con("execution_count", Valor::Nulo)
                .con("metadata", Valor::Mapa(Mapa::new()))
                .con("outputs", Valor::Lista(Vec::new()))
                .con("source", Valor::Lista(vec![Valor::Texto(bloque)])),
        ),
    ];
    Valor::Mapa(
        Mapa::new()
            .con("cells", Valor::Lista(celdas))
            .con("metadata", Valor::Mapa(Mapa::new().con("language_info", Valor::Mapa(Mapa::new().con("name", "python")))))
            .con("nbformat", Valor::Entero(4))
            .con("nbformat_minor", Valor::Entero(2)),
    )
}

/// `NotebookSafetyLayer.is_path_in_library`: por componentes (una carpeta hermana como `.prig_books_backup` no lo es)
pub fn en_biblioteca(ruta: &str, biblioteca: &Path) -> bool {
    let r = prig_plataforma::py::abspath(ruta);
    let b = prig_plataforma::py::abspath(&biblioteca.to_string_lossy());
    Path::new(&r).starts_with(Path::new(&b))
}

/// `NotebookSafetyLayer.write_executable_notebook`: la ruta absoluta escrita, o el error (nunca dentro de la biblioteca)
pub fn escribir_cuaderno(destino: &Path, contenido: &Valor, biblioteca: &Path) -> Result<String, String> {
    let abs = prig_plataforma::py::abspath(&destino.to_string_lossy());
    if en_biblioteca(&abs, biblioteca) {
        return Err(format!("🔒 PROTECCIÓN FÍSICA VIOLADA: Intento de escritura en archivo protegido de la Biblioteca ({abs})."));
    }
    if let Some(p) = Path::new(&abs).parent() {
        std::fs::create_dir_all(p).map_err(|e| e.to_string())?;
    }
    std::fs::write(&abs, prig_plataforma::json::escribir(contenido, 2)).map_err(|e| e.to_string())?;
    Ok(abs)
}

#[cfg(test)]
mod pruebas_motor {
    use super::*;

    #[test]
    fn transiciones_como_python() {
        assert!(validar_transicion("DRAFT", "KNOWLEDGE_REVIEW").is_ok());
        assert_eq!(
            validar_transicion("APPROVED", "APPROVED").unwrap_err(),
            "❌ Transición de estado no válida: APPROVED ➔ APPROVED. Permitidas: []"
        );
        assert_eq!(
            validar_transicion("KNOWLEDGE_REVIEW", "APPROVED").unwrap_err(),
            "❌ Transición de estado no válida: KNOWLEDGE_REVIEW ➔ APPROVED. Permitidas: ['KNOWLEDGE_REVIEW', 'KNOWLEDGE_APPROVED']"
        );
    }

    #[test]
    fn cambios_sobre_el_mapa() {
        let tmp = std::env::temp_dir().join(format!("prig_plan_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        let mut p = nuevo_plan(&tmp, "SQL").unwrap();
        let km = r#"{"goal":"g","prerequisites":[{"name":"Álgebra","reason":"r"}],"domains":[{"domain_id":"d","name":"D","topics":[{"topic_id":"t","name":"T","concepts":[{"concept_id":"c1","name":"Joins"}]}]}]}"#;
        p.poner("knowledge_map", Valor::Mapa(validar_modelo(&MAPA, prig_plataforma::json::leer(km).unwrap()).unwrap()));
        guardar_plan(&tmp, &mut p).unwrap();
        let id = p.texto("plan_id").unwrap().to_string();
        let orden = |a: &str, t: &str| {
            validar_modelo(&PETICION_CAMBIO, Valor::Mapa(Mapa::new().con("target_agent", "K").con("action", a).con("target", t).con("user_prompt", "u"))).unwrap()
        };
        aplicar_cambio(&tmp, &id, &orden("REMOVE_PREREQUISITE", "álgebra")).unwrap();
        aplicar_cambio(&tmp, &id, &orden("REMOVE_CONCEPT", "JOIN")).unwrap();
        let p = aplicar_cambio(&tmp, &id, &orden("ADD_PRACTICAL_MODULE", "x")).unwrap();
        assert_eq!(p.valor("version"), &Valor::Entero(4));
        let km = p.mapa("knowledge_map").unwrap();
        assert_eq!(km.lista("prerequisites").unwrap().len(), 0);
        assert!(prig_plataforma::json::escribir_compacto(km.valor("domains")).contains(r#""concepts": []"#));
        assert!(cargar_plan_version(&tmp, &id, Some(2)).unwrap().is_some());
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn el_cuaderno_no_se_escribe_en_la_biblioteca() {
        let bib = Path::new("/tmp/prig_bib_prueba");
        assert!(en_biblioteca("/tmp/prig_bib_prueba/a/b.ipynb", bib));
        assert!(!en_biblioteca("/tmp/prig_bib_prueba_copia/b.ipynb", bib));
        assert!(escribir_cuaderno(&bib.join("x.ipynb"), &Valor::Nulo, bib).is_err());
        let nb = prig_plataforma::json::escribir_compacto(&cuaderno_explicado("M", "O", &[], ""));
        assert!(nb.contains("Pr\\u00e1ctica completada con \\u00e9xito"));
    }
}
