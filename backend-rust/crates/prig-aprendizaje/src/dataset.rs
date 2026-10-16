//! El dataset de aprendizaje del usuario (`learner_dataset.py`): recorridos (planes de estudio) y seguimientos con lo
//! completado, el hexágono de competencias, el mapa de calor de actividad, los temas dominados y las competencias
//! adquiridas. Se reconstruye entero desde los planes y seguimientos del espacio de trabajo y se guarda en
//! `<espacio>/.prig_dataset/user_learning_dataset.json` (el mismo archivo y los mismos bytes que Python).
//!
//! Del original se conserva también un fallo: los recorridos suman por `approved_steps`, un campo que `StudyPlanState`
//! no tiene, así que esos pasos nunca puntúan (anotado en la bitácora para corregirlo aparte).

use crate::planes;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::path::Path;
use std::sync::LazyLock;

/// Las palabras clave de cada eje del hexágono (`HEXAGON_KEYWORDS`)
const EJES: &[(&str, &str, &[&str])] = &[
    ("matematicas", "Matemáticas", &[
        "math", "matematica", "matemática", "algebra", "cálculo", "calculo", "estadistica", "estadística", "probabilidad", "logica", "lógica",
        "vector", "matriz", "matrices", "geometria", "optimizacion", "optimizó", "derivad",
    ]),
    ("programacion", "Programación", &[
        "programacion", "programación", "python", "javascript", "js", "cpp", "c++", "poo", "oop", "funcion", "función", "variable", "clase",
        "algoritmo", "codigo", "código", "sintaxis", "script", "git", "refactor", "bucle", "loop",
    ]),
    ("machine_learning", "Machine Learning", &[
        "machine_learning", "machine learning", "ml", "regresion", "regresión", "clasificacion", "clasificación", "scikit-learn", "sklearn",
        "clustering", "random forest", "svm", "supervisado", "no supervisado", "arbol", "decision", "fit", "predict",
    ]),
    ("deep_learning", "Deep Learning", &[
        "deep_learning", "deep learning", "dl", "redes neuronales", "red neuronal", "pytorch", "tensorflow", "keras", "cnn", "rnn", "transformer",
        "llm", "atencion", "atención", "backpropagation", "capa", "neurona", "loss", "optimizer",
    ]),
    ("base_de_datos", "Base de Datos", &[
        "base_de_datos", "base de datos", "sql", "database", "pandas", "dataframe", "numpy", "etl", "postgres", "sqlite", "nosql", "consulta",
        "query", "tabla", "dataset",
    ]),
    ("teoria_computacional", "Teoría Computacional", &[
        "teoria", "teoría", "computacion", "computación", "complejidad", "big o", "arquitectura", "sistema operativo", "redes", "patron", "patrón",
        "compilador", "memoria", "hilo", "concurrencia", "estructura de datos", "arbol", "grafo",
    ]),
];

static PATRONES: LazyLock<Vec<(&'static str, Vec<Regex>)>> = LazyLock::new(|| {
    EJES.iter()
        .map(|(id, _, palabras)| (*id, palabras.iter().map(|p| Regex::new(&format!(r"\b{}\b", regex::escape(p))).expect("patrón")).collect()))
        .collect()
});

/// `_classify_item`: los ejes cuyas palabras aparecen (como palabra entera); si ninguno, programación
pub fn clasificar(texto: &str) -> Vec<&'static str> {
    let t = texto.to_lowercase();
    let mut v: Vec<&'static str> = PATRONES.iter().filter(|(_, ps)| ps.iter().any(|p| p.is_match(&t))).map(|(id, _)| *id).collect();
    if v.is_empty() {
        v.push("programacion");
    }
    v
}

fn bisiesto(a: i64) -> bool {
    (a % 4 == 0 && a % 100 != 0) || a % 400 == 0
}

static ISO: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2})(?::(\d{2})(?::(\d{2})(?:[.,]\d{1,6})?)?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?)?$").expect("iso")
});

/// `datetime.fromisoformat(v).strftime("%Y-%m-%d")` (None si no es una fecha ISO válida)
pub fn dia_iso(v: &str) -> Option<String> {
    let c = ISO.captures(v)?;
    let n = |i: usize| c.get(i).map(|m| m.as_str().parse::<i64>().unwrap_or(-1));
    let (a, m, d) = (n(1)?, n(2)?, n(3)?);
    let dias = [31, if bisiesto(a) { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if !(1..=12).contains(&m) || d < 1 || d > dias[(m - 1) as usize] {
        return None;
    }
    if n(4).is_some_and(|h| h > 23) || n(5).is_some_and(|x| x > 59) || n(6).is_some_and(|x| x > 59) {
        return None;
    }
    Some(format!("{a:04}-{m:02}-{d:02}"))
}

fn hoy() -> String {
    prig_plataforma::py::ahora_iso()[..10].to_string()
}

fn texto(m: &Mapa, k: &str, defecto: &str) -> String {
    match m.get(k) {
        Some(Valor::Texto(t)) => t.clone(),
        Some(v) => v.texto_py(),
        None => defecto.to_string(),
    }
}

/// `build_and_save_dataset`: reconstruye el dataset desde los planes y seguimientos del espacio y lo guarda
pub fn construir(espacio: &Path) -> Result<Mapa, String> {
    let dir = espacio.join(".prig_dataset");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(espacio.join(".prig_plans")).map_err(|e| e.to_string())?;

    // 1. Los recorridos y seguimientos completos
    let mut recorridos = Vec::new();
    for p in planes::listar_planes(espacio) {
        match p.get("plan_id") {
            Some(Valor::Texto(id)) if !id.is_empty() => {
                // uno dañado se salta (antes tumbaba el dataset entero y, con él, guardar cualquier progreso)
                match planes::cargar_plan(espacio, id) {
                    Ok(Some(plan)) => recorridos.push(plan),
                    Ok(None) => {}
                    Err(e) => eprintln!("⚠️ Plan {id} omitido del dataset: {e}"),
                }
            }
            None | Some(Valor::Nulo) => {}
            Some(v) if !v.verdad() => {}
            Some(_) => return Err("plan_id no es texto".into()),
        }
    }
    let mut seguimientos = Vec::new();
    for s in planes::listar_seguimientos(espacio) {
        match s.get("id") {
            Some(Valor::Texto(id)) if !id.is_empty() => {
                match planes::cargar_seguimiento(espacio, id) {
                    Ok(Some(seg)) => seguimientos.push(seg),
                    Ok(None) => {}
                    Err(e) => eprintln!("⚠️ Seguimiento {id} omitido del dataset: {e}"),
                }
            }
            None | Some(Valor::Nulo) => {}
            Some(v) if !v.verdad() => {}
            Some(_) => return Err("id de seguimiento no es texto".into()),
        }
    }

    // 2. El hexágono
    let mut puntos: Vec<(i64, i64)> = vec![(0, 0); EJES.len()];
    let sumar = |puntos: &mut Vec<(i64, i64)>, ejes: &[&str], n: i64| {
        for e in ejes {
            if let Some(i) = EJES.iter().position(|x| x.0 == *e) {
                puntos[i].0 += n;
                puntos[i].1 += 1;
            }
        }
    };
    let mut calor = Mapa::new();
    let actividad = |calor: &mut Mapa, dia: String| {
        let n = calor.get(&dia).and_then(|v| v.entero()).unwrap_or(0) + 1;
        calor.poner(dia, n);
    };
    let dia = |v: Option<&Valor>| -> String {
        match v {
            Some(Valor::Texto(t)) if !t.is_empty() => dia_iso(t).unwrap_or_else(hoy),
            _ => hoy(),
        }
    };
    let mut dominados = Vec::new();
    let mut competencias = Vec::new();
    let (total_rec, total_seg) = (recorridos.len(), seguimientos.len());
    let (mut comp_rec, mut comp_seg, mut bloques_hechos, mut temas_dominados) = (0usize, 0usize, 0i64, 0i64);

    for r in &recorridos {
        let objetivo = texto(r, "user_goal", "Recorrido de Estudio");
        let dia_plan = dia(r.get("updated_at").filter(|v| v.verdad()).or(r.get("created_at")));
        if r.texto("status") == Some("APPROVED") {
            comp_rec += 1;
            actividad(&mut calor, dia_plan.clone());
        }
        // `approved_steps`: StudyPlanState no lo tiene (siempre vacío; se conserva el comportamiento)
        let mut cuadernos: Vec<String> = Vec::new();
        for c in r.lista("completed_notebooks").unwrap_or(&[]) {
            let c = c.texto_py();
            if !cuadernos.contains(&c) {
                cuadernos.push(c);
            }
        }
        for nb in cuadernos {
            sumar(&mut puntos, &clasificar(&format!("{objetivo} {nb}")), 20);
            actividad(&mut calor, dia_plan.clone());
        }
    }

    for s in &seguimientos {
        let objetivo = texto(s, "goal", "Seguimiento de Aprendizaje");
        let bloques = s.lista("blocks").unwrap_or(&[]);
        let mut hechos: Vec<String> = Vec::new();
        for b in s.lista("completed_blocks").unwrap_or(&[]) {
            let b = b.texto_py();
            if !hechos.contains(&b) {
                hechos.push(b);
            }
        }
        let fechas = s.mapa("completion_dates").cloned().unwrap_or_default();
        let dia_base = dia(s.get("created_at"));
        if !bloques.is_empty() && hechos.len() == bloques.len() {
            comp_seg += 1;
        }
        for b in bloques {
            let Valor::Mapa(b) = b else { continue };
            let id = b.get("block_id").map(|v| v.texto_py()).unwrap_or_default();
            if !hechos.contains(&id) {
                continue;
            }
            let titulo = texto(b, "title", "");
            let desc = texto(b, "description", "");
            let obj = texto(b, "learning_objective", "");
            let check = texto(b, "validation_check", "");
            let temas: Vec<String> = b.lista("topics").unwrap_or(&[]).iter().map(|t| t.texto_py()).collect();
            bloques_hechos += 1;
            temas_dominados += temas.len() as i64;
            let ejes = clasificar(&format!("{objetivo} {titulo} {desc} {obj} {check} {}", temas.join(" ")));
            sumar(&mut puntos, &ejes, 15);
            let d = match fechas.get(&id) {
                Some(v) if v.verdad() => dia(Some(v)),
                _ => dia_base.clone(),
            };
            actividad(&mut calor, d);
            let lista_ejes = Valor::Lista(ejes.iter().map(|e| Valor::Texto(e.to_string())).collect());
            for t in &temas {
                dominados.push(Valor::Mapa(
                    Mapa::new()
                        .con("topic", t.clone())
                        .con("source_goal", objetivo.clone())
                        .con("block_title", titulo.clone())
                        .con("categories", lista_ejes.clone())
                        .con("type", "seguimiento"),
                ));
            }
            if !obj.is_empty() || !check.is_empty() {
                competencias.push(Valor::Mapa(
                    Mapa::new()
                        .con("title", titulo.clone())
                        .con("objective", obj.clone())
                        .con("check", check.clone())
                        .con("source_goal", objetivo.clone())
                        .con("categories", lista_ejes.clone()),
                ));
            }
        }
    }

    // 3. Niveles (nivel = puntos // 100 + 1) y la escala
    let mut hexagono = Mapa::new();
    for (i, (id, nombre, _)) in EJES.iter().enumerate() {
        let (p, n) = puntos[i];
        hexagono.poner(
            *id,
            Mapa::new()
                .con("category_id", *id)
                .con("label", *nombre)
                .con("score", p as i128)
                .con("level", (p / 100 + 1) as i128)
                .con("max_scale", (p + 50).max(100) as i128)
                .con("completed_items_count", n as i128),
        );
    }
    let (total, hechos) = (total_rec + total_seg, comp_rec + comp_seg);
    let pct = if total > 0 { hechos as f64 / total as f64 * 100.0 } else { 0.0 };
    let metricas = Mapa::new()
        .con("total_recorridos", total_rec as i128)
        .con("total_seguimientos", total_seg as i128)
        .con("completed_recorridos", comp_rec as i128)
        .con("completed_seguimientos", comp_seg as i128)
        .con("total_blocks_completed", bloques_hechos as i128)
        .con("total_topics_mastered", temas_dominados as i128)
        .con("overall_progress_pct", Valor::Real(prig_plataforma::valor::redondear(pct, 1)))
        .con("last_activity", prig_plataforma::py::ahora_iso());
    let ahora = prig_plataforma::py::ahora_iso();
    let dataset = Mapa::new()
        .con("schema_version", planes::version_actual("dataset").unwrap_or(2))
        .con("version", "2.0")
        .con("created_at", ahora.clone())
        .con("updated_at", prig_plataforma::py::ahora_iso())
        .con("metrics", metricas)
        .con("hexagon", hexagono)
        .con("activity_heatmap", calor)
        .con("mastered_topics", Valor::Lista(dominados))
        .con("acquired_competencies", Valor::Lista(competencias))
        .con("recorridos", Valor::Lista(recorridos.into_iter().map(Valor::Mapa).collect()))
        .con("seguimientos", Valor::Lista(seguimientos.into_iter().map(Valor::Mapa).collect()));
    planes::escribir_modelo(&dir.join("user_learning_dataset.json"), &dataset).map_err(|e| e.to_string())?;
    Ok(dataset)
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn clasificar_y_fechas() {
        assert_eq!(clasificar("Aprender pandas y SQL"), ["base_de_datos"]);
        assert_eq!(clasificar("redes neuronales con pytorch"), ["deep_learning", "teoria_computacional"]);
        assert_eq!(clasificar("nada que ver"), ["programacion"]);
        assert_eq!(clasificar("c++ moderno"), ["programacion"]);
        assert_eq!(dia_iso("2026-10-03T10:00:00"), Some("2026-10-03".into()));
        assert_eq!(dia_iso("2026-10-03"), Some("2026-10-03".into()));
        assert_eq!(dia_iso("2026-02-30"), None);
        assert_eq!(dia_iso("ayer"), None);
    }
}
