//! El profesor de los notebooks de Kaggle (`kaggle_lector.py`): el esquema del notebook, los prompts para explicar
//! una celda, la guía de lectura, la ruta de estudio y las preguntas, las explicaciones guardadas y lo leído. Los
//! prompts salen byte a byte iguales que en Python; generar lo hace quien llama (prig_ia::tutor::flujo).

use crate::kaggle::{carpeta, leer_objeto};
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use sha1::{Digest, Sha1};
use std::path::PathBuf;
use std::sync::{LazyLock, Mutex};

pub const NIVELES: [(&str, &str); 3] = [
    ("principiante", "El alumno está empezando: explica cada término técnico la primera vez que aparece y ve línea por línea."),
    ("intermedio", "El alumno conoce Python y pandas básico: explica las decisiones y lo que no es obvio, no la sintaxis."),
    ("avanzado", "El alumno es avanzado: céntrate en por qué se hace así, alternativas, riesgos (fugas de datos, validación) y buenas prácticas."),
];

pub fn es_nivel(n: &str) -> bool {
    NIVELES.iter().any(|(k, _)| *k == n)
}

fn nivel(n: &str) -> &'static str {
    NIVELES.iter().find(|(k, _)| *k == n).map(|(_, v)| *v).unwrap_or(NIVELES[1].1)
}

pub const SISTEMA_CELDA: &str = "Eres un científico de datos senior que lee un notebook de Kaggle JUNTO al alumno, celda
a celda, como un profesor al lado. Explica en español lo que hace ESTA celda en el contexto del notebook.

Estructura (encabezados «### »):
### Qué hace
Una o dos frases.
### Paso a paso
Las partes importantes del código explicadas en orden; cita el fragmento entre `comillas de código`.
### Datos y Columnas (solo si la celda lee, transforma, filtra o grafica datos)
Si la celda interactúa con columnas o archivos de datos, explica qué columnas concretas del dataset real se están usando, qué significan, cómo se están tratando los tipos o nulos y qué impacto tiene en los datos.
### Por qué aquí
Qué papel cumple en el flujo del notebook (usa el esquema y las celdas anteriores).
### Conceptos
Los conceptos de Python, pandas, estadística o ML que aparecen, en una línea cada uno.
### Diagrama del Algoritmo (solo si la celda entrena, define o transforma modelos de ML/DL o pipelines)
Si la celda involucra modelos o pipelines (ej. XGBoost, LightGBM, CatBoost, Random Forest, SVM, k-Means, PCA, CNN, ResNet, Transformer, etc.), incluye un diagrama de flujo modular en bloque de código ```mermaid ... ``` conectando sus 4 bloques: [Entrada] -> [Transformación/División/Atención] -> [Pérdida/Optimización] -> [Inferencia/Métrica].
### Para pensar
Una pregunta o mini-reto para comprobar que se entendió.

No inventes resultados: si la celda muestra datos, di QUÉ mostraría, no valores concretos.";

pub const SISTEMA_MARKDOWN: &str = "Eres un científico de datos senior que lee un notebook de Kaggle junto al alumno. Esta
celda es TEXTO del autor. En español y en pocas líneas: resume la idea, explica los términos
técnicos que use y di qué conviene tener presente para las celdas de código que siguen.";

pub const SISTEMA_GUIA: &str = "Eres un científico de datos senior. Antes de leer un notebook de Kaggle con el alumno, le
das una guía de lectura en español, basada en el esquema, las celdas y la estructura de los datos disponibles.

Secciones (encabezados «## »):
## De qué trata
Objetivo del notebook y qué datos usa (menciona los datasets, tablas y columnas principales).
## El recorrido
Las etapas (por ejemplo: carga, exploración, limpieza, variables, modelo, evaluación) con los
números de celda donde empieza cada una: `celdas 3–7`. Si el notebook entrena modelos, incluye un diagrama de flujo general del pipeline en un bloque ```mermaid ... ```.
## Qué vas a aprender
Técnicas y conceptos concretos que aparecen.
## Antes de empezar
Lo que conviene saber para seguirlo, y cómo leerlo (qué celdas son clave y cuáles se pueden hojear).";

pub const SISTEMA_ESTUDIO_OPTIMO: &str = "Eres un mentor y científico de datos senior especializado en aprendizaje activo de Machine Learning y Ciencia de Datos a través de proyectos reales de Kaggle.

Diseña una RUTA ÓPTIMA DE ESTUDIO personalizada para este notebook y sus datasets reales, diseñada para que el estudiante comprenda el flujo de trabajo completo, domine la teoría subyacente y sepa reutilizar el código en sus propios proyectos.

Estructura obligatoria con encabezados («## » y «### »):
## 1. Mapeo del Problema y los Datos
- Tipo de problema (clasificación, regresión, series temporales, NLP, visión, etc.) y métrica de evaluación (ROC-AUC, RMSE, F1, LogLoss, etc.).
- Relación de los datasets reales con el objetivo: qué representa cada fila, cuál es la variable objetivo (target) y qué variables predictoras son clave.

## 2. Flujo de Trabajo y Celdas Clave
Organiza el estudio en fases lógicas indicando los rangos de celdas a revisar:
- Fase A: Carga, Inspección y Calidad de Datos (celdas X-Y).
- Fase B: Análisis Exploratorio (EDA) e Hipótesis (celdas X-Y).
- Fase C: Ingeniería de Características y Preprocesamiento (celdas X-Y).
- Fase D: Modelado, Validación Cruzada y Tuning (celdas X-Y).
- Fase E: Inferencia, Post-procesamiento y Conclusiones (celdas X-Y).
(Si el notebook entrena modelos, incluye un diagrama de flujo modular en bloque ```mermaid ... ``` resumiendo la arquitectura de datos y modelado).

## 3. Patrones de Código Reutilizables
Identifica 2 a 4 técnicas o patrones de código excelentes que se usan en este notebook y que el estudiante debería guardar en su caja de herramientas (ej. imputación específica, encoding, optimización de memoria, cross-validation estratificado, pipeline de scikit-learn/PyTorch, etc.), con breve explicación de por qué son buenas prácticas.

## 4. Preguntas Socráticas y Retos de Aprendizaje
3 retos prácticos ordenados por dificultad:
- Nivel Básico: Modificar un hiperparámetro o preprocesamiento en una celda específica.
- Nivel Intermedio: Crear una nueva feature o manejar valores nulos de forma alternativa.
- Nivel Avanzado: Diseñar una estrategia de validación diferente o mitigar un riesgo de fuga de datos (data leakage).

## 5. Próximos Pasos para Practicar en Prig IDE
Cómo transferir este código a tu editor local con el botón «Al editor», cómo ejecutarlo con datos en `kaggle_datos/` y qué experimento ejecutar primero.";

pub const SISTEMA_PREGUNTAR: &str = "Eres un científico de datos senior que lee con el alumno un notebook de Kaggle. Responde en español, claro y breve (menos de 200 palabras), apoyándote en el código del notebook y en la estructura de los datos reales. Si la pregunta es sobre algo que no está en el notebook ni en sus datos, dilo. Puedes mostrar fragmentos cortos de código.";

/// Un pedido al modelo: (prompt, sistema, temperatura, pensar)
pub struct Pedido {
    pub prompt: String,
    pub sistema: String,
    pub temperatura: f64,
    pub pensar: bool,
}

fn celdas(nb: &Mapa) -> Vec<Mapa> {
    nb.lista("celdas").unwrap_or(&[]).iter().filter_map(|c| if let Valor::Mapa(c) = c { Some(c.clone()) } else { None }).collect()
}

fn t(m: &Mapa, k: &str) -> String {
    m.get(k).map(Valor::texto_py).unwrap_or_default()
}

fn primeros(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

/// `nb.get('autor')` en un f-string (None si falta)
fn autor(nb: &Mapa) -> String {
    nb.get("autor").cloned().unwrap_or(Valor::Nulo).texto_py()
}

/// `', '.join(nb['competiciones'] + nb['datasets']) or 'sin indicar'`
fn datos_de(nb: &Mapa) -> String {
    let mut l: Vec<String> = nb.lista("competiciones").unwrap_or(&[]).iter().map(Valor::texto_py).collect();
    l.extend(nb.lista("datasets").unwrap_or(&[]).iter().map(Valor::texto_py));
    let s = l.join(", ");
    if s.is_empty() { "sin indicar".into() } else { s }
}

static DEFINE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?m)^\s*(?:def|class)\s+(\w+)|^\s*(\w+)\s*=").unwrap());

/// El notebook resumido en una línea por celda: títulos de markdown e inicio del código
pub fn esquema(nb: &Mapa, hasta: Option<usize>) -> String {
    let cs = celdas(nb);
    let n = hasta.unwrap_or(cs.len()).min(cs.len());
    let mut lineas = Vec::new();
    for c in &cs[..n] {
        let fuente = t(c, "fuente");
        let primera = crate::kaggle_red::splitlines(&fuente).iter().map(|l| py::strip(l).to_string()).find(|l| !l.is_empty()).unwrap_or_default();
        let indice = c.valor("indice").texto_py();
        if t(c, "tipo") == "markdown" {
            if primera.starts_with('#') {
                lineas.push(format!("[{indice}] {}", primeros(&primera, 100)));
            }
        } else {
            let nombres: Vec<String> = DEFINE
                .captures_iter(&fuente)
                .map(|m| m.get(1).or(m.get(2)).map(|x| x.as_str().to_string()).unwrap_or_default())
                .take(5)
                .collect();
            let define = if nombres.is_empty() { String::new() } else { format!("  (define: {})", nombres.join(", ")) };
            lineas.push(format!("[{indice}] código: {}{define}", primeros(&primera, 80)));
        }
    }
    primeros(&lineas.join("\n"), 6000)
}

fn bloque_datos(etiqueta: &str, contexto_datos: Option<&str>) -> String {
    match contexto_datos.map(str::trim).filter(|c| !c.is_empty()) {
        Some(c) => format!("\n\n{etiqueta}:\n{c}"),
        None => String::new(),
    }
}

fn contexto(nb: &Mapa, indice: usize, contexto_datos: Option<&str>) -> String {
    let cs = celdas(nb);
    let c = &cs[indice];
    let previas: Vec<String> = cs[indice.saturating_sub(3)..indice]
        .iter()
        .map(|p| format!("--- celda {} ({}) ---\n{}", p.valor("indice").texto_py(), t(p, "tipo"), primeros(&t(p, "fuente"), 1500)))
        .collect();
    let previas = if previas.is_empty() { "(ninguna)".to_string() } else { previas.join("\n") };
    let salida = match c.get("salida").filter(|s| s.verdad()) {
        Some(s) => format!("\n\nSALIDA GUARDADA:\n{}", s.texto_py()),
        None => String::new(),
    };
    format!(
        "NOTEBOOK: «{}» de {} · datos: {}\n\nESQUEMA:\n{}\n\nCELDAS ANTERIORES:\n{previas}\n\nCELDA {indice} A EXPLICAR ({}):\n{}{salida}{}",
        t(nb, "titulo"),
        autor(nb),
        datos_de(nb),
        esquema(nb, None),
        t(c, "tipo"),
        primeros(&t(c, "fuente"), 5000),
        bloque_datos("ESTRUCTURA DE LOS DATASETS DISPONIBLES", contexto_datos),
    )
}

/// Explicar una celda. `Ok(None)`: la celda está vacía (se responde «Celda vacía.» sin modelo).
pub fn explicar(nb: &Mapa, indice: i64, nivel_: &str, contexto_datos: Option<&str>) -> Result<Option<Pedido>, String> {
    let cs = celdas(nb);
    if indice < 0 || indice as usize >= cs.len() {
        return Err("Esa celda no existe.".into());
    }
    let c = &cs[indice as usize];
    if py::strip(&t(c, "fuente")).is_empty() {
        return Ok(None);
    }
    let base = if t(c, "tipo") == "markdown" { SISTEMA_MARKDOWN } else { SISTEMA_CELDA };
    Ok(Some(Pedido {
        prompt: contexto(nb, indice as usize, contexto_datos),
        sistema: format!("{base}\n\n{}", nivel(nivel_)),
        temperatura: 0.3,
        pensar: false,
    }))
}

fn cabecera(nb: &Mapa) -> String {
    format!("NOTEBOOK: «{}» de {} · {} celdas · datos: {}", t(nb, "titulo"), autor(nb), celdas(nb).len(), datos_de(nb))
}

fn muestra(nb: &Mapa, n: usize, largo: usize) -> String {
    celdas(nb)
        .iter()
        .take(n)
        .map(|c| format!("--- celda {} ({}) ---\n{}", c.valor("indice").texto_py(), t(c, "tipo"), primeros(&t(c, "fuente"), largo)))
        .collect::<Vec<_>>()
        .join("\n")
}

pub fn guia(nb: &Mapa, contexto_datos: Option<&str>) -> Pedido {
    let prompt = format!(
        "{}\n\nESQUEMA:\n{}\n\nPRIMERAS CELDAS:\n{}{}",
        cabecera(nb),
        esquema(nb, None),
        muestra(nb, 6, 800),
        bloque_datos("DATASETS Y ESQUEMAS DISPONIBLES", contexto_datos)
    );
    Pedido { prompt, sistema: SISTEMA_GUIA.into(), temperatura: 0.3, pensar: true }
}

pub fn estudio_optimo(nb: &Mapa, contexto_datos: Option<&str>) -> Pedido {
    let prompt = format!(
        "{}\n\nESQUEMA COMPLETO:\n{}\n\nMUESTRA DE CELDAS:\n{}{}",
        cabecera(nb),
        esquema(nb, None),
        muestra(nb, 8, 600),
        bloque_datos("ESTRUCTURA Y ESTADÍSTICAS DE LOS DATASETS REALES", contexto_datos)
    );
    Pedido { prompt, sistema: SISTEMA_ESTUDIO_OPTIMO.into(), temperatura: 0.3, pensar: true }
}

/// Una pregunta del alumno; `mensajes`: `[{rol, texto}]` (los 10 últimos)
pub fn preguntar(nb: &Mapa, indice: Option<i64>, mensajes: &[Valor], contexto_datos: Option<&str>) -> Pedido {
    let n = celdas(nb).len() as i64;
    let ctx = match indice.filter(|i| (0..n).contains(i)) {
        Some(i) => contexto(nb, i as usize, contexto_datos),
        None => format!("NOTEBOOK: «{}»\n\nESQUEMA:\n{}{}", t(nb, "titulo"), esquema(nb, None), bloque_datos("DATASETS", contexto_datos)),
    };
    let ultimos = &mensajes[mensajes.len().saturating_sub(10)..];
    let historial = ultimos
        .iter()
        .map(|m| {
            let m = match m {
                Valor::Mapa(m) => m.clone(),
                _ => Mapa::new(),
            };
            let quien = if m.get("rol") == Some(&Valor::Texto("usuario".into())) { "Alumno" } else { "Profesor" };
            format!("{quien}: {}", primeros(&m.get("texto").cloned().unwrap_or(Valor::Nulo).texto_py(), 1500))
        })
        .collect::<Vec<_>>()
        .join("\n");
    Pedido { prompt: format!("{ctx}\n\nCONVERSACIÓN:\n{historial}\nProfesor:"), sistema: SISTEMA_PREGUNTAR.into(), temperatura: 0.4, pensar: false }
}

// ---------------------------------------------------------------------------------------------- guardadas

static CERROJO: Mutex<()> = Mutex::new(());

fn ruta_explicaciones(r: &str) -> PathBuf {
    carpeta().join("explicaciones").join(format!("{}.json", r.replace('/', "__")))
}

fn clave(nb: &Mapa, indice: Option<i64>, nivel_: &str, modelo: &str) -> String {
    match indice {
        None => format!("{}:{modelo}", if nivel_ == "estudio" { "estudio" } else { "guia" }),
        Some(i) => {
            let fuente = celdas(nb).get(i as usize).map(|c| t(c, "fuente")).unwrap_or_default();
            let h = Sha1::digest(fuente.as_bytes());
            let hex: String = h.iter().map(|b| format!("{b:02x}")).collect();
            format!("{i}:{nivel_}:{modelo}:{}", &hex[..10])
        }
    }
}

pub fn explicacion_guardada(nb: &Mapa, indice: Option<i64>, nivel_: &str, modelo: &str) -> Option<String> {
    let datos = leer_objeto(&ruta_explicaciones(&t(nb, "ref"))).unwrap_or_default();
    match datos.get(&clave(nb, indice, nivel_, modelo)) {
        Some(Valor::Mapa(e)) => e.get("texto").filter(|x| x.verdad()).map(Valor::texto_py),
        _ => None,
    }
}

fn escribir(ruta: &PathBuf, v: &Valor) {
    if let Some(p) = ruta.parent() {
        let _ = std::fs::create_dir_all(p);
    }
    let mut tmp = ruta.clone().into_os_string();
    tmp.push(".tmp");
    if std::fs::write(&tmp, prig_plataforma::json::escribir_linea(v)).is_ok() {
        let _ = std::fs::rename(&tmp, ruta);
    }
}

pub fn guardar_explicacion(nb: &Mapa, indice: Option<i64>, nivel_: &str, modelo: &str, texto: &str) {
    {
        let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
        let ruta = ruta_explicaciones(&t(nb, "ref"));
        let mut datos = leer_objeto(&ruta).unwrap_or_default();
        let fecha: String = py::ahora_iso().chars().take(19).collect();
        datos.poner(
            clave(nb, indice, nivel_, modelo),
            Mapa::new().con("texto", texto).con("fecha", fecha).con("indice", indice.map(Valor::from).unwrap_or(Valor::Nulo)),
        );
        escribir(&ruta, &Valor::Mapa(datos));
    }
    if let Some(i) = indice {
        marcar_leida(nb, i);
    }
}

/// Apunta la celda como leída (para el Perfil)
pub fn marcar_leida(nb: &Mapa, indice: i64) {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let ruta = carpeta().join("lecturas.json");
    let mut datos = leer_objeto(&ruta).unwrap_or_default();
    let r = t(nb, "ref");
    let ahora: String = py::ahora_iso().chars().take(19).collect();
    let total = celdas(nb).len();
    let mut l = match datos.get(&r) {
        Some(Valor::Mapa(l)) => l.clone(),
        _ => Mapa::new()
            .con("titulo", nb.get("titulo").cloned().unwrap_or(Valor::Nulo))
            .con("leidas", Valor::Lista(vec![]))
            .con("total", total)
            .con("empezado", ahora.as_str()),
    };
    let mut leidas: Vec<i64> = l.lista("leidas").unwrap_or(&[]).iter().filter_map(|v| v.num()).map(|n| n as i64).collect();
    if !leidas.contains(&indice) {
        leidas.push(indice);
        leidas.sort_unstable();
        leidas.dedup();
        l.poner("leidas", Valor::Lista(leidas.into_iter().map(Valor::from).collect()));
    }
    l.poner("total", total);
    l.poner("titulo", nb.get("titulo").cloned().unwrap_or(Valor::Nulo));
    l.poner("ultima", ahora);
    l.poner("ultima_celda", indice);
    datos.poner(r, l);
    escribir(&ruta, &Valor::Mapa(datos));
}

// ---------------------------------------------------------------------------------------------- los datos

pub const SISTEMA_DATOS: &str = "Eres un científico de datos senior que presenta un conjunto de datos de Kaggle a un
alumno antes de trabajar con él. En español, claro y concreto, apoyándote SOLO en la
información que se te da (descripción, archivos, columnas, estadísticas y filas de ejemplo).
Usa exactamente estas secciones en markdown:

## Qué contiene
Qué representa cada fila y de dónde vienen los datos.
## Las columnas que importan
Las más relevantes, qué significan y de qué tipo son. Si hay una variable objetivo evidente, dila.
## Calidad de los datos
Valores faltantes, columnas raras, desequilibrios o cosas a limpiar, citando las cifras.
## Qué se puede hacer con ellos
3-5 ideas concretas de análisis o modelos, de la más sencilla a la más ambiciosa.
## Por dónde empezar
Un bloque corto de código Python (pandas) para cargarlo y echar el primer vistazo,
con la ruta que se te indica.

No inventes columnas ni cifras que no aparezcan.";

static IMAGEN_MD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"!\[[^\]]*\]\([^)]*\)").unwrap());

fn str_py(v: Option<&Valor>) -> String {
    v.cloned().unwrap_or(Valor::Nulo).texto_py()
}

fn mapas(v: Option<&Valor>) -> Vec<Mapa> {
    match v {
        Some(Valor::Lista(l)) => l.iter().filter_map(|x| if let Valor::Mapa(m) = x { Some(m.clone()) } else { None }).collect(),
        _ => Vec::new(),
    }
}

/// El dataset o la competición para el modelo: datos, descripción, archivos y las tablas descargadas
pub fn contexto_datos(ficha: &Mapa, previas: &[Mapa]) -> String {
    let etiquetas: Vec<String> = ficha.lista("etiquetas").unwrap_or(&[]).iter().map(Valor::texto_py).collect();
    let mut partes = vec![
        format!("{}: «{}»", if t(ficha, "tipo") == "dataset" { "DATASET" } else { "COMPETICIÓN" }, str_py(ficha.get("titulo"))),
        format!("Subtítulo: {}", ficha.get("subtitulo").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| "-".into())),
        format!("Etiquetas: {}", if etiquetas.is_empty() { "-".to_string() } else { etiquetas.join(", ") }),
    ];
    if let Some(m) = ficha.get("metrica").filter(|v| v.verdad()) {
        partes.push(format!("Métrica de evaluación: {}", m.texto_py()));
    }
    if let Some(d) = ficha.get("descripcion").filter(|v| v.verdad()) {
        partes.push(format!("DESCRIPCIÓN:\n{}", primeros(&IMAGEN_MD.replace_all(&d.texto_py(), ""), 3500)));
    }
    let archivos: Vec<String> = mapas(ficha.get("archivos"))
        .iter()
        .take(30)
        .map(|a| {
            let b = a.get("bytes").filter(|v| v.verdad()).and_then(Valor::num).unwrap_or(0.0);
            format!("- {} ({})", t(a, "nombre"), crate::kaggle_red::tam(b))
        })
        .collect();
    partes.push(format!("ARCHIVOS:\n{}", archivos.join("\n")));
    for p in previas.iter().take(3) {
        let columnas = mapas(p.get("columnas"));
        let cols: Vec<String> = columnas
            .iter()
            .take(40)
            .map(|c| {
                let mut l = format!(
                    "  · {} [{}] faltan {}% · distintos {}",
                    str_py(c.get("nombre")),
                    str_py(c.get("tipo")),
                    str_py(c.get("faltan_pct")),
                    str_py(c.get("distintos"))
                );
                if t(c, "tipo") == "número" {
                    l.push_str(&format!(" · min {} máx {} media {}", str_py(c.get("min")), str_py(c.get("max")), str_py(c.get("media"))));
                }
                let frecuentes = mapas(c.get("frecuentes"));
                if !frecuentes.is_empty() {
                    let f: Vec<String> = frecuentes.iter().take(4).map(|f| str_py(f.get("valor"))).collect();
                    l.push_str(&format!(" · frecuentes: {}", f.join(", ")));
                }
                l
            })
            .collect();
        let filas: Vec<String> = p
            .lista("filas")
            .unwrap_or(&[])
            .iter()
            .take(5)
            .map(|f| match f {
                Valor::Lista(x) => x.iter().map(Valor::texto_py).collect::<Vec<_>>().join(","),
                otro => otro.texto_py(),
            })
            .collect();
        let ruta = p.get("ruta_relativa").cloned().unwrap_or_else(|| p.get("nombre").cloned().unwrap_or(Valor::Nulo)).texto_py();
        partes.push(format!(
            "TABLA {} — {} filas, {} columnas (ruta en el proyecto: {ruta})\n{}\nPRIMERAS FILAS:\n{}",
            str_py(p.get("nombre")),
            str_py(p.get("total_filas")),
            columnas.len(),
            cols.join("\n"),
            filas.join("\n")
        ));
    }
    primeros(&partes.join("\n\n"), 14000)
}

/// Resumen de las tablas descargadas (las 3 mayores), si las hay
pub fn previas_para_modelo(ficha: &Mapa, espacio: &std::path::Path) -> Vec<Mapa> {
    let local = ficha.mapa("local").cloned().unwrap_or_default();
    let mut tablas: Vec<Mapa> = mapas(local.get("archivos"))
        .into_iter()
        .filter(|a| {
            let r = t(a, "relativa").to_lowercase();
            r.ends_with(".csv") || r.ends_with(".tsv")
        })
        .collect();
    let bytes = |a: &Mapa| a.get("bytes").and_then(Valor::num).unwrap_or(0.0);
    tablas.sort_by(|a, b| bytes(b).partial_cmp(&bytes(a)).unwrap_or(std::cmp::Ordering::Equal));
    let esp = espacio.to_string_lossy().to_string();
    tablas
        .iter()
        .take(3)
        .filter_map(|a| {
            let ruta = t(a, "ruta");
            crate::kaggle_datos::vista_previa(&ruta, espacio, 5).ok().map(|p| p.con("ruta_relativa", py::relpath(&ruta, &esp)))
        })
        .collect()
}

/// Cambia si se bajan los datos: la explicación con estadísticas reales es otra
pub fn huella(ficha: &Mapa) -> String {
    let local = ficha.mapa("local").cloned().unwrap_or_default();
    let texto = format!(
        "{}:{}:{}",
        str_py(ficha.get("version")),
        if local.is_empty() { "False" } else { "True" },
        str_py(local.get("bytes"))
    );
    let h = Sha1::digest(texto.as_bytes());
    h.iter().map(|b| format!("{b:02x}")).collect::<String>()[..10].to_string()
}

fn ruta_datos(tipo: &str, r: &str) -> PathBuf {
    carpeta().join("explicaciones").join(format!("datos__{tipo}__{}.json", r.replace('/', "__")))
}

pub fn explicacion_datos(tipo: &str, r: &str, modelo: &str, huella: &str) -> Option<String> {
    match leer_objeto(&ruta_datos(tipo, r)).unwrap_or_default().get(&format!("{modelo}:{huella}")) {
        Some(Valor::Mapa(e)) => e.get("texto").filter(|x| x.verdad()).map(Valor::texto_py),
        _ => None,
    }
}

pub fn guardar_explicacion_datos(tipo: &str, r: &str, modelo: &str, huella: &str, texto: &str) {
    let _g = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let ruta = ruta_datos(tipo, r);
    let mut datos = leer_objeto(&ruta).unwrap_or_default();
    let fecha: String = py::ahora_iso().chars().take(19).collect();
    datos.poner(format!("{modelo}:{huella}"), Mapa::new().con("texto", texto).con("fecha", fecha));
    escribir(&ruta, &Valor::Mapa(datos));
}
