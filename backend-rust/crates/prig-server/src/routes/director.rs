//! El director de LLM del personaje ASCII (`llm_director.py`, `/api/llm/*`): el personaje del tema evalúa el código
//! del editor con un modelo local de Ollama (una «lente» de análisis distinta cada vez y sin repetir los últimos
//! consejos) o, si no hay modelo, con una evaluación propia sobre el árbol del archivo (`director_ast`). También
//! escribe la bitácora de pensamiento de una carpeta (`PENSAMIENTO_DEL_PROYECTO.md`) y lleva la memoria comprimida
//! de los archivos leídos (`<Prig>/.prig_dataset/cerebro_memoria_comprimida.json`), a la que se le puede preguntar.
//!
//! Desvíos decididos: `archivo_actual` y `lenguaje` que no son texto se toman por su `str()` (Python fallaba con un
//! AttributeError o un TypeError según dónde los usara), y una `linea_cursor` real con código da el error de índice de
//! Python siempre (Python solo fallaba si el índice no salía entero tras recortarlo).

use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex, OnceLock};
use std::time::Duration;

use axum::{
    body::{Body, Bytes},
    extract::State,
    http::{header, StatusCode},
    response::{IntoResponse, Response},
};
use banco_core::py::cadena::{primeros, splitlines};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use prig_recursos::valor::redondear;
use regex::Regex;

use crate::routes::director_ast as ast;
use crate::routes::{cuerpo, json_py};
use crate::state::AppState;

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const DICT: Tipo = Tipo::Dict(&Tipo::Cualquiera);
const PENSAMIENTO: &str = "PENSAMIENTO_DEL_PROYECTO.md";

static TEMAS: LazyLock<Mapa> = LazyLock::new(|| match prig_plataforma::json::leer(include_str!("director_temas.json")) {
    Ok(Valor::Mapa(m)) => m,
    _ => Mapa::new(),
});

fn personajes() -> &'static Mapa {
    TEMAS.mapa("personajes").expect("personajes")
}

fn lentes() -> Vec<Mapa> {
    TEMAS.lista("lentes").unwrap_or(&[]).iter().filter_map(|v| if let Valor::Mapa(m) = v { Some(m.clone()) } else { None }).collect()
}

fn mecha() -> Mapa {
    personajes().mapa("tema_mecha_patrol").cloned().unwrap_or_default()
}

fn t(m: &Mapa, k: &str) -> String {
    m.valor(k).texto_py()
}

fn ahora() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

fn mapa_de(v: &Valor) -> Mapa {
    match v {
        Valor::Mapa(m) => m.clone(),
        _ => Mapa::new(),
    }
}

// =========================================================================== estado

struct Director {
    endpoint: String,
    modelo: String,
    indice_lente: usize,
    ultimos_titulos: Vec<Valor>,
}

static DIRECTOR: LazyLock<Mutex<Director>> = LazyLock::new(|| {
    Mutex::new(Director {
        endpoint: std::env::var("OLLAMA_HOST").unwrap_or_else(|_| "http://localhost:11434".into()),
        modelo: std::env::var("PRIG_DIRECTOR_MODEL").unwrap_or_else(|_| "qwen2.5-coder:7b".into()),
        indice_lente: 0,
        ultimos_titulos: Vec::new(),
    })
});

fn director() -> std::sync::MutexGuard<'static, Director> {
    DIRECTOR.lock().unwrap_or_else(|e| e.into_inner())
}

/// `_obtener_siguiente_lente()`
fn siguiente_lente() -> Mapa {
    let l = lentes();
    let mut d = director();
    let lente = l[d.indice_lente % l.len()].clone();
    d.indice_lente += 1;
    lente
}

/// `_obtener_resumen_anti_repeticion()`
fn anti_repeticion() -> String {
    let d = director();
    if d.ultimos_titulos.is_empty() {
        return "Ninguna evaluación previa (primer escaneo del archivo).".into();
    }
    let desde = d.ultimos_titulos.len().saturating_sub(4);
    d.ultimos_titulos[desde..].iter().map(|t| format!("  - Ya evaluaste: '{}'", t.texto_py())).collect::<Vec<_>>().join("\n")
}

fn anotar_titulo(titulo: Valor) {
    let mut d = director();
    d.ultimos_titulos.push(titulo);
    if d.ultimos_titulos.len() > 20 {
        d.ultimos_titulos.remove(0);
    }
}

/// El `endpoint` y el `modelo` de una petición, o los del director
fn destino(endpoint: Option<&str>, modelo: Option<&str>) -> (String, String) {
    let d = director();
    let e = endpoint.filter(|e| !e.is_empty()).unwrap_or(&d.endpoint).trim_end_matches('/').to_string();
    (e, modelo.filter(|m| !m.is_empty()).unwrap_or(&d.modelo).to_string())
}

// =========================================================================== memoria comprimida

struct Memoria {
    ruta: PathBuf,
    archivos: Mapa,
    grafo: Mapa,
    preguntas: Vec<Valor>,
}

static MEMORIA: OnceLock<Mutex<Memoria>> = OnceLock::new();

fn memoria(base: &Path) -> std::sync::MutexGuard<'static, Memoria> {
    MEMORIA
        .get_or_init(|| {
            let ruta = base.join(".prig_dataset").join("cerebro_memoria_comprimida.json");
            let mut m = Memoria { ruta, archivos: Mapa::new(), grafo: Mapa::new(), preguntas: Vec::new() };
            if let Ok(Valor::Mapa(d)) = prig_plataforma::leer_json(&m.ruta) {
                m.archivos = mapa_de(d.get("archivos").unwrap_or(&Valor::Nulo));
                m.grafo = mapa_de(d.get("grafo_simbolos").unwrap_or(&Valor::Nulo));
                m.preguntas = d.lista("preguntas").map(<[Valor]>::to_vec).unwrap_or_default();
            }
            Mutex::new(m)
        })
        .lock()
        .unwrap_or_else(|e| e.into_inner())
}

impl Memoria {
    fn guardar(&self) {
        if let Some(dir) = self.ruta.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        let desde = self.preguntas.len().saturating_sub(50);
        let datos = Mapa::new()
            .con("archivos", self.archivos.clone())
            .con("grafo_simbolos", self.grafo.clone())
            .con("preguntas", Valor::Lista(self.preguntas[desde..].to_vec()))
            .con("ultima_actualizacion", ahora());
        let _ = prig_plataforma::escribir_json(&self.ruta, &Valor::Mapa(datos), 2);
    }

    /// `comprimir_codigo_ast`: la ficha del archivo (símbolos, dependencias, resumen) y el grafo de símbolos al día
    fn comprimir(&mut self, archivo: &str, codigo: &str, lenguaje: &str) -> Mapa {
        let lineas = splitlines(codigo).len() as i128;
        let crudos = ((codigo.chars().count() as f64 / 3.8) as i128).max(1);
        let a = ast::analizar(codigo, lenguaje);
        let simbolos: Vec<Mapa> = a.lista("simbolos").unwrap_or(&[]).iter().map(mapa_de).collect();
        for s in &simbolos {
            let nombre = s.valor("nombre");
            if !nombre.verdad() {
                continue;
            }
            let nombre = nombre.texto_py();
            let mut lista: Vec<Valor> = self.grafo.lista(&nombre).unwrap_or(&[]).iter().filter(|x| mapa_de(x).valor("archivo").texto_py() != archivo).cloned().collect();
            lista.push(Valor::Mapa(
                Mapa::new()
                    .con("archivo", archivo)
                    .con("tipo", s.get("tipo").cloned().unwrap_or("funcion".into()))
                    .con("firma", s.get("firma").cloned().unwrap_or(Valor::Texto(nombre.clone())))
                    .con("linea", s.get("linea_inicio").cloned().unwrap_or(Valor::Entero(1))),
            ));
            self.grafo.poner(nombre, Valor::Lista(lista));
        }
        let textos = |k: &str| a.lista(k).unwrap_or(&[]).iter().map(Valor::texto_py).collect::<Vec<_>>();
        let (deps, criticos) = (textos("dependencias"), textos("puntos_criticos"));
        let comp = a.valor("complejidad_max").clone();
        let resumen = format!("[{}|{lineas}L|{}syms|Comp:{}]", lenguaje.to_uppercase(), simbolos.len(), comp.texto_py());
        let mut nombres = simbolos.iter().take(8).map(|s| s.valor("nombre").texto_py()).collect::<Vec<_>>().join(", ");
        if simbolos.len() > 8 {
            nombres.push_str(&format!(" (+{} más)", simbolos.len() - 8));
        }
        let o = |s: String, d: &str| if s.is_empty() { d.to_string() } else { s };
        let digest = format!(
            "Archivo: {archivo} ({lenguaje}, {lineas} líneas). Símbolos: [{}]. Deps: [{}]. Puntos Críticos: [{}].",
            o(nombres, "script secuencial"),
            o(deps.iter().take(6).cloned().collect::<Vec<_>>().join(", "), "std"),
            o(criticos.iter().take(4).cloned().collect::<Vec<_>>().join(", "), "ninguno"),
        );
        let comprimidos = ((digest.chars().count() as f64 / 3.8) as i128).max(1);
        let ahorro = redondear((1.0 - comprimidos as f64 / crudos.max(1) as f64) * 100.0, 1);
        Mapa::new()
            .con("archivo", archivo)
            .con("lenguaje", lenguaje)
            .con("lineas_total", lineas)
            .con("simbolos", a.valor("simbolos").clone())
            .con("dependencias", a.valor("dependencias").clone())
            .con("puntos_criticos", a.valor("puntos_criticos").clone())
            .con("pasos_cfg", a.valor("pasos_cfg").clone())
            .con("complejidad_ciclomatica", comp)
            .con("calidad_score", a.valor("calidad_score").clone())
            .con("resumen_ast", resumen)
            .con("digest_texto", digest)
            .con("tokens_crudos_estimados", crudos)
            .con("tokens_comprimidos", comprimidos)
            .con("ahorro_tokens_pct", ahorro.max(0.0))
            .con("timestamp", ahora())
    }

    /// `registrar_lectura_archivo(archivo, codigo, lenguaje, ultima_decision)`
    fn registrar(&mut self, archivo: &str, codigo: &str, lenguaje: &str, decision: Option<&Mapa>) {
        if archivo.is_empty() || codigo.is_empty() {
            return;
        }
        let mut ficha = self.comprimir(archivo, codigo, lenguaje);
        let dec = decision.cloned().unwrap_or_default();
        let interna = match dec.get("decision") {
            Some(Valor::Mapa(m)) => m.clone(),
            _ => dec,
        };
        let consejo = match interna.get("consejo") {
            Some(Valor::Mapa(c)) => c.get("titulo").cloned().unwrap_or("".into()),
            _ => "".into(),
        };
        let metricas = match interna.get("metricas") {
            Some(Valor::Mapa(m)) => Valor::Mapa(m.clone()),
            _ => Valor::Mapa(Mapa::new()),
        };
        ficha.poner(
            "ultima_evaluacion",
            Mapa::new()
                .con("dialogo", interna.get("dialogo").cloned().unwrap_or("".into()))
                .con("consejo_titulo", consejo)
                .con("metricas", metricas)
                .con("timestamp", ahora()),
        );
        self.archivos.poner(archivo, ficha);
        self.guardar();
    }

    fn resumen(&self) -> Vec<Valor> {
        let mut v: Vec<Valor> = self.archivos.iter().map(|(_, x)| x.clone()).collect();
        let ts = |x: &Valor| mapa_de(x).num("timestamp").unwrap_or(0.0);
        v.sort_by(|a, b| ts(b).partial_cmp(&ts(a)).unwrap_or(std::cmp::Ordering::Equal));
        v
    }

    fn estadisticas(&self) -> Mapa {
        let suma = |k: &str| self.archivos.iter().map(|(_, x)| mapa_de(x).valor(k).entero().unwrap_or(0)).sum::<i128>();
        let (crudo, comprimido) = (suma("tokens_crudos_estimados"), suma("tokens_comprimidos"));
        let ahorro = if crudo > 0 { redondear((1.0 - comprimido as f64 / crudo.max(1) as f64) * 100.0, 1) } else { 0.0 };
        Mapa::new()
            .con("total_archivos_memorizados", self.archivos.len() as i128)
            .con("total_tokens_crudos_evitados", crudo)
            .con("total_tokens_comprimidos_usados", comprimido)
            .con("ahorro_global_porcentaje", ahorro.max(0.0))
            .con("tokens_netos_ahorrados", (crudo - comprimido).max(0))
    }
}

/// El lenguaje de un archivo por su extensión (`/api/interno/archivo-guardado` de Python)
fn lenguaje_de(ruta: &str) -> &'static str {
    match py::splitext(ruta).1.to_lowercase().as_str() {
        ".py" => "python",
        ".js" | ".jsx" => "javascript",
        ".ts" | ".tsx" => "typescript",
        ".html" => "html",
        ".css" => "css",
        ".c" | ".cpp" | ".h" => "c_cpp",
        ".rs" => "rust",
        _ => "text",
    }
}

/// El editor guardó un archivo: la memoria del director lo anota
pub fn archivo_guardado(base: &Path, ruta: &str, contenido: &str) {
    memoria(base).registrar(ruta, contenido, lenguaje_de(ruta), None);
}

// =========================================================================== Ollama

fn cliente(segundos: f64) -> Option<reqwest::blocking::Client> {
    reqwest::blocking::Client::builder().timeout(Duration::from_secs_f64(segundos)).build().ok()
}

/// Un POST de JSON a Ollama: el cuerpo de la respuesta si es 200
fn pedir_json(url: &str, cuerpo: &Valor, segundos: f64) -> Option<Mapa> {
    let r = cliente(segundos)?
        .post(url)
        .header("Content-Type", "application/json")
        .body(prig_plataforma::json::escribir_compacto(cuerpo))
        .send()
        .ok()?;
    if r.status().as_u16() != 200 {
        return None;
    }
    match prig_plataforma::json::leer(&r.text().ok()?) {
        Ok(Valor::Mapa(m)) => Some(m),
        _ => None,
    }
}

/// `_resolver_modelo_disponible`: el pedido si está instalado (o algo con su nombre), si no el primero instalado
fn modelo_disponible(endpoint: &str, deseado: &str) -> String {
    let resp = cliente(0.8).and_then(|c| c.get(format!("{endpoint}/api/tags")).send().ok()).filter(|r| r.status().as_u16() == 200);
    let datos = resp.and_then(|r| r.text().ok()).and_then(|t| prig_plataforma::json::leer(&t).ok());
    let Some(Valor::Mapa(d)) = datos else { return deseado.to_string() };
    let modelos: Vec<String> = d.lista("models").unwrap_or(&[]).iter().map(|m| mapa_de(m).get("name").map(Valor::texto_py).unwrap_or_default()).collect();
    let base = deseado.split(':').next().unwrap_or("");
    if modelos.iter().any(|m| m == deseado) || modelos.iter().any(|m| m.contains(base)) {
        return deseado.to_string();
    }
    modelos.first().cloned().unwrap_or_else(|| deseado.to_string())
}

/// `_limpiar_y_parsear_json`: el JSON de la respuesta de un modelo (sin el bloque de markdown y sin comas sobrantes)
fn limpiar_json(respuesta: &str) -> Option<Valor> {
    static COMAS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r",\s*([}\]])").expect("regex"));
    if respuesta.is_empty() {
        return None;
    }
    let mut texto = py::strip(respuesta).to_string();
    if texto.contains("```") {
        for p in texto.clone().split("```") {
            let mut p = py::strip(p);
            if let Some(r) = p.strip_prefix("json") {
                p = py::strip(r);
            }
            if p.starts_with('{') && p.ends_with('}') {
                texto = p.to_string();
                break;
            }
        }
    }
    if let (Some(i), Some(f)) = (texto.find('{'), texto.rfind('}')) {
        if f > i {
            texto = texto[i..=f].to_string();
        }
    }
    if let Ok(v) = prig_plataforma::json::leer(&texto) {
        return Some(v);
    }
    prig_plataforma::json::leer(&COMAS.replace_all(&texto, "$1")).ok()
}

/// `_llamar_ollama_o_local`
fn llamar(endpoint: &str, modelo: &str, sistema: &str, usuario: &str) -> Option<Valor> {
    let opciones = Mapa::new()
        .con("temperature", 0.48)
        .con("num_predict", 220)
        .con("top_p", 0.88)
        .con("top_k", 40)
        .con("repeat_penalty", 1.22)
        .con("repeat_last_n", 128)
        .con("presence_penalty", 0.35)
        .con("frequency_penalty", 0.30);
    let cuerpo = Mapa::new()
        .con("model", modelo)
        .con("prompt", format!("{sistema}\n\n{usuario}"))
        .con("stream", false)
        .con("format", "json")
        .con("options", opciones);
    let r = pedir_json(&format!("{endpoint}/api/generate"), &Valor::Mapa(cuerpo), 3.2)?;
    limpiar_json(&r.get("response").map(Valor::texto_py).unwrap_or_else(|| "{}".into()))
}

// =========================================================================== el contexto del editor

/// Lo que se saca del contexto del editor, como lo saca `consultar_director`
struct Contexto {
    ctx: Mapa,
    codigo: String,
    para_prompt: String,
    archivo: String,
    archivo_v: Valor,
    lenguaje: String,
    linea_cursor: Valor,
}

fn contexto(ctx: Mapa) -> Contexto {
    let completo = ctx.valor("codigo_completo");
    let codigo = if completo.verdad() { completo.texto_py() } else { ctx.get("codigo_reciente").map(Valor::texto_py).unwrap_or_default() };
    let codigo = py::strip(&codigo).to_string();
    let para_prompt = if codigo.chars().count() <= 14000 {
        codigo.clone()
    } else {
        format!("{}\n... [código truncado por longitud máxima de contexto]", primeros(&codigo, 14000))
    };
    let archivo_v = ctx.get("archivo_actual").cloned().unwrap_or("main.py".into());
    Contexto {
        codigo,
        para_prompt,
        archivo: archivo_v.texto_py(),
        archivo_v,
        lenguaje: ctx.get("lenguaje").map(Valor::texto_py).unwrap_or_else(|| "python".into()),
        linea_cursor: ctx.get("linea_cursor").cloned().unwrap_or(Valor::Entero(1)),
        ctx,
    }
}

/// `linea_cursor - 1` con la `linea_cursor` del contexto tal cual (los errores de Python)
fn menos_uno(v: &Valor) -> Result<i128, String> {
    match v {
        Valor::Entero(n) => Ok(n - 1),
        Valor::Bool(b) => Ok(*b as i128 - 1),
        Valor::Real(_) => Err("list indices must be integers or slices, not float".into()),
        otro => Err(format!("unsupported operand type(s) for -: '{}' and 'int'", py::tipo(otro))),
    }
}

/// `int(v or 1)`
fn entero_o_uno(v: Option<&Valor>) -> Result<i128, String> {
    let v = match v {
        Some(v) if v.verdad() => v,
        _ => return Ok(1),
    };
    match v {
        Valor::Entero(n) => Ok(*n),
        Valor::Bool(b) => Ok(*b as i128),
        Valor::Real(x) => Ok(x.trunc() as i128),
        Valor::Texto(s) => py::strip(s).replace('_', "").parse::<i128>().map_err(|_| format!("invalid literal for int() with base 10: {}", v.repr_py())),
        otro => Err(format!("int() argument must be a string, a bytes-like object or a real number, not '{}'", py::tipo(otro))),
    }
}

/// La línea del cursor y el bloque de alrededor (hasta 4 líneas antes y 4 después), numerado
fn ventana(c: &Contexto) -> Result<(String, usize, usize, String), String> {
    let lineas = if c.codigo.is_empty() { vec![] } else { splitlines(&c.codigo) };
    if lineas.is_empty() {
        return Ok((String::new(), 0, 0, "(archivo vacío)".into()));
    }
    let idx = (menos_uno(&c.linea_cursor)?.min(lineas.len() as i128 - 1)).max(0) as usize;
    let (ini, fin) = (idx.saturating_sub(4), lineas.len().min(idx + 5));
    let trozo = (ini..fin).map(|i| format!("{:4}: {}", i + 1, lineas[i])).collect::<Vec<_>>().join("\n");
    Ok((py::strip(lineas[idx]).to_string(), ini, fin, trozo))
}

fn info_tema(tema: &str, por_defecto_mecha: bool) -> Mapa {
    if let Some(m) = personajes().mapa(tema) {
        return m.clone();
    }
    if por_defecto_mecha {
        return mecha();
    }
    Mapa::new()
        .con("nombre", crate::routes::desafios_fuentes::title(&tema.replace('_', " ")))
        .con("personaje_id", "ANDROIDE_COMPACTO")
        .con("personaje_cat", "ROBOTS_Y_MECHAS")
        .con("nombre_personaje", "Androide Evaluador")
        .con("rol", "Evaluador de Código")
        .con("estilo_dialogo", "analista_codigo")
        .con("descripcion", format!("Personaje temático {tema}."))
        .con("tonos", Valor::Lista(vec!["perspicaz".into(), "observador".into()]))
}

fn tonos(info: &Mapa) -> Vec<String> {
    info.lista("tonos").unwrap_or(&[]).iter().map(Valor::texto_py).collect()
}

/// La cabecera común de los dos prompts del director
fn prompt_cabecera(info: &Mapa, lente: &Mapa, anti: &str) -> String {
    format!(
        "Eres '{}' ({}), el director y mentor interactivo de Prig IDE.\n\n=== CONTEXTO DEL TEMA: {} ===\nArquetipo: {}\nEstilo: {}. Tono: {}.\n\n=== ENFOQUE OBLIGATORIO DE ESTA EVALUACIÓN: [{}] ===\nMeta analítica: {}\nPregunta rectora: {}\n\n=== REGLAS ESTRICTAS DE ANTI-REPETICIÓN Y RAZONAMIENTO ===\n1. HISTORIAL RECIENTE QUE NO DEBES REPETIR:\n{anti}\n",
        t(info, "nombre_personaje"),
        t(info, "rol"),
        t(info, "nombre"),
        t(info, "descripcion"),
        t(info, "estilo_dialogo"),
        tonos(info).join(", "),
        t(lente, "nombre").to_uppercase(),
        t(lente, "meta"),
        t(lente, "pregunta_guia"),
    )
}

fn prompt_sistema(info: &Mapa, lente: &Mapa, anti: &str) -> String {
    let np = t(info, "nombre_personaje");
    let (id, tipo, cat) = (t(lente, "id"), t(lente, "tipo_relacion"), t(lente, "categoria"));
    prompt_cabecera(info, lente, anti)
        + "2. PROHIBIDO REPETIR frases genéricas como 'Función delimitada correctamente' o dar el mismo consejo de siempre.\n"
        + "3. En tu campo 'pensamiento', aplica Chain-of-Thought: analiza nombres exactos de variables, parámetros, invariantes y líneas específicas.\n"
        + "4. En tu campo 'dialogo', sé conciso, técnico, mordaz y directo al grano, citando símbolos reales del código.\n"
        + "5. En tu campo 'flujo_ascii', genera un diagrama ASCII claro que modele el flujo bajo la lente actual.\n"
        + "6. En tu campo 'flujo_grafico', genera una secuencia de 3 a 5 pasos animados de movimiento donde el personaje recorra y explique cada fase del código.\n\n"
        + "Responde ÚNICAMENTE un objeto JSON válido con este esquema exacto:\n{\n"
        + &format!("  \"personaje\": \"{np}\",\n")
        + "  \"pensamiento\": \"CoT: 1. Identificar símbolos -> 2. Evaluar invariante -> 3. Diseñar mejora concreta\",\n"
        + &format!("  \"dialogo\": \"[{id}]: Tu análisis riguroso y novedoso citando variables reales.\",\n")
        + "  \"posicion\": {\"x_ratio\": 0.88, \"y_ratio\": 0.88},\n  \"consejo\": {\n"
        + &format!("    \"tipo\": \"{tipo}\",\n    \"categoria\": \"{cat}\",\n")
        + "    \"titulo\": \"Título técnico preciso y no repetido\",\n    \"detalle\": \"Explicación concreta del porqué y cómo refactorizar.\",\n    \"linea_inicio\": 1,\n    \"linea_fin\": 6,\n    \"sugerencia_codigo\": \"código de reemplazo conciso\"\n  },\n"
        + "  \"flujo_ascii\": [\n    \"[ENTRADA] ──► [OPERACIÓN] ──► [SALIDA]\"\n  ],\n"
        + "  \"flujo_grafico\": {\n    \"activo\": true,\n    \"velocidad_ms\": 3200,\n    \"estilo\": \"spline_neon\",\n    \"pasos\": [\n"
        + "      {\n        \"paso\": 1,\n        \"etiqueta\": \"Entrada y Parámetros\",\n        \"tipo\": \"entrada\",\n        \"icono\": \"📥\",\n        \"linea_inicio\": 1,\n        \"linea_fin\": 2,\n        \"x_foco\": 0.35,\n        \"y_foco\": 0.20,\n        \"posicion_agente\": {\"x_ratio\": 0.88, \"y_ratio\": 0.86},\n        \"explicacion\": \"Recepción de argumentos y validación de tipos\",\n        \"sugerencia\": \"Validar tipos estáticos\"\n      },\n"
        + "      {\n        \"paso\": 2,\n        \"etiqueta\": \"Cláusula de Guarda\",\n        \"tipo\": \"guarda\",\n        \"icono\": \"🛡️\",\n        \"linea_inicio\": 3,\n        \"linea_fin\": 4,\n        \"x_foco\": 0.35,\n        \"y_foco\": 0.35,\n        \"posicion_agente\": {\"x_ratio\": 0.85, \"y_ratio\": 0.80},\n        \"explicacion\": \"Evaluación temprana para prevenir excepciones\",\n        \"sugerencia\": \"if not data: return\"\n      },\n"
        + "      {\n        \"paso\": 3,\n        \"etiqueta\": \"Transformación Central\",\n        \"tipo\": \"proceso\",\n        \"icono\": \"⚡\",\n        \"linea_inicio\": 5,\n        \"linea_fin\": 6,\n        \"x_foco\": 0.35,\n        \"y_foco\": 0.50,\n        \"posicion_agente\": {\"x_ratio\": 0.82, \"y_ratio\": 0.74},\n        \"explicacion\": \"Pipeline de computación y mapeo de datos\",\n        \"sugerencia\": \"Optimizar complejidad asintótica\"\n      }\n    ]\n  },\n"
        + "  \"inspeccion\": {\n    \"activo\": true,\n    \"linea\": 1,\n    \"linea_fin\": 6,\n    \"modo\": \"explicar\",\n"
        + &format!("    \"tipo_relacion\": \"{tipo}\",\n")
        + "    \"x_foco\": 0.35,\n    \"y_foco\": 0.35\n  },\n  \"metricas\": {\"complejidad\": \"O(N)\", \"calidad\": 95, \"modularidad\": 92, \"mantenibilidad\": 94},\n  \"modulo_activo\": \"main\",\n  \"tono\": \"analítico\"\n}"
}

fn prompt_sistema_flujo(info: &Mapa, lente: &Mapa, anti: &str) -> String {
    prompt_cabecera(info, lente, anti)
        + "2. PROHIBIDO REPETIR frases genéricas. Cita variables y funciones reales del código completo.\n"
        + "3. En tu campo 'pensamiento', aplica Chain-of-Thought analizando el código completo.\n"
        + "4. En tu campo 'dialogo', sé conciso y directo.\n"
        + "5. En 'flujo_grafico', define los pasos de movimiento sobre el código analizado.\n\n"
        + "Responde ÚNICAMENTE un objeto JSON válido con claves: personaje, pensamiento, dialogo, posicion, consejo, flujo_ascii, flujo_grafico, inspeccion, metricas."
}

fn prompt_usuario(c: &Contexto, lente: &Mapa, flujo: bool) -> Result<String, String> {
    let (linea, ini, fin, trozo) = ventana(c)?;
    let lc = c.linea_cursor.texto_py();
    let vacio = if flujo { "# Archivo recién abierto." } else { "# Archivo recién abierto o sin contenido aún." };
    let codigo = if c.para_prompt.is_empty() { vacio } else { &c.para_prompt };
    let cierre = if flujo {
        format!("INSTRUCCIÓN OBLIGATORIA: Tu análisis, diálogo y consejo DEBEN enfocarse en la línea activa L{lc} ('{linea}') o su bloque contenedor inmediato. Prohibido dar consejos que no tengan relación con esta línea. Aplica la lente [{}], razona paso a paso sobre este bloque y emite tu JSON:", t(lente, "nombre"))
    } else {
        format!("INSTRUCCIÓN OBLIGATORIA: Tu análisis, diálogo y consejo DEBEN estar directamente relacionados con la línea activa L{lc} ('{linea}') o su bloque contenedor inmediato. No emitas mensajes genéricos desvinculados de esta línea. Aplica la lente [{}], razona paso a paso en 'pensamiento' y emite tu JSON de evaluación:", t(lente, "nombre"))
    };
    Ok(format!(
        "Archivo: {} | Lenguaje: {} | Línea activa del cursor: L{lc}\nLínea de edición activa L{lc}: '{linea}'\n=== BLOQUE EN EDICIÓN ACTIVA (L{} a L{fin}) ===\n{trozo}\n\n=== CÓDIGO COMPLETO DEL USUARIO ===\n{codigo}\n===============================\n{cierre}",
        c.archivo,
        c.lenguaje,
        ini + 1
    ))
}

/// La decisión de un modelo si trae `dialogo`; anota su título (el `.get("consejo", {}).get("titulo", "")` de Python)
fn decision_llm(r: Option<Valor>, origen: &str, modelo: &str, tema: &str, info: &Mapa, lente: &Mapa) -> Result<Option<Mapa>, String> {
    let Some(Valor::Mapa(r)) = r else { return Ok(None) };
    if !r.contiene("dialogo") {
        return Ok(None);
    }
    let titulo = match r.get("consejo") {
        None => Valor::Texto(String::new()),
        Some(Valor::Mapa(c)) => c.get("titulo").cloned().unwrap_or_else(|| Valor::Texto(String::new())),
        Some(otro) => return Err(format!("'{}' object has no attribute 'get'", py::tipo(otro))),
    };
    if titulo.verdad() {
        anotar_titulo(titulo);
    }
    Ok(Some(
        Mapa::new()
            .con("origen", origen)
            .con("modelo", modelo)
            .con("tema", tema)
            .con("personaje_info", info.clone())
            .con("lente_aplicada", lente.valor("id").clone())
            .con("timestamp", ahora())
            .con("decision", r),
    ))
}

// =========================================================================== la evaluación propia

fn flecha(v: &[&str]) -> Valor {
    Valor::Lista(v.iter().map(|s| Valor::from(*s)).collect())
}

/// `_generar_evaluacion_procedural`: el consejo según lo que hay en la línea del cursor (import, bucle, condición,
/// excepción, función, clase, retorno o la lente) y los pasos del grafo de flujo del archivo
fn procedural(tema: &str, info: &Mapa, c: &Contexto, lente: &Mapa) -> Result<Mapa, String> {
    let lc = entero_o_uno(c.ctx.get("linea_cursor"))?;
    let total_ctx = entero_o_uno(c.ctx.get("total_lineas"))?;
    let lineas = if c.codigo.is_empty() { vec![] } else { splitlines(&c.codigo) };
    let total_l = 1i128.max(lineas.len() as i128).max(total_ctx);
    let linea_codigo = if lineas.is_empty() {
        String::new()
    } else {
        py::strip(lineas[(lc - 1).min(lineas.len() as i128 - 1).max(0) as usize]).to_string()
    };
    let a = ast::analizar(&c.codigo, &c.lenguaje);
    let simbolos: Vec<Mapa> = a.lista("simbolos").unwrap_or(&[]).iter().map(mapa_de).collect();
    let pasos_reales = a.lista("pasos_cfg").unwrap_or(&[]).to_vec();
    let complejidad = a.valor("complejidad_max").entero().unwrap_or(1);
    let calidad = a.valor("calidad_score").clone();
    let hay_funciones = simbolos.iter().any(|s| matches!(s.texto("tipo"), Some("funcion" | "metodo")));
    let ent = |s: &Mapa, k: &str| s.valor(k).entero().unwrap_or(1);
    let activo = simbolos
        .iter()
        .find(|s| ent(s, "linea_inicio") <= lc && lc <= ent(s, "linea_fin"))
        .or_else(|| simbolos.iter().min_by_key(|s| (ent(s, "linea_inicio") - lc).abs()));
    let (objetivo, lt, lft) = match activo {
        Some(s) => (s.valor("nombre").texto_py(), lc, total_l.min((lc + 2).max(s.get("linea_fin").and_then(Valor::entero).unwrap_or(lc + 2)))),
        None => {
            let base = py::basename(&c.archivo);
            let n = base.split('.').next().unwrap_or("").to_string();
            let lt = lc.min(total_l).max(1);
            (if n.is_empty() { "modulo".into() } else { n }, lt, total_l.min(lt + 3))
        }
    };
    let raw = linea_codigo.to_lowercase();
    let empieza = |ps: &[&str]| ps.iter().any(|p| raw.starts_with(p));
    let es_import = empieza(&["import ", "from "]) || raw.contains("require(") || raw.contains("#include");
    let es_funcion = empieza(&["def ", "async def "]) || raw.contains("function ") || raw.contains("fn ") || raw.contains("=>");
    let es_clase = empieza(&["class ", "struct ", "interface "]);
    let es_bucle = empieza(&["for ", "while "]) || raw.contains(".foreach") || raw.contains(".map(");
    let es_cond = empieza(&["if ", "elif ", "else:", "switch"]);
    let es_exc = empieza(&["try:", "except", "catch", "finally", "raise ", "throw "]);
    let es_ret = empieza(&["return", "yield"]);
    let ln = t(lente, "nombre").to_uppercase();
    let (dialogo, titulo, detalle, sug, flujo): (String, String, String, String, Valor) = if es_import {
        (
            format!("[{ln}]: Declaración de dependencias en L{lt}. Desacopla módulos para evitar importaciones circulares y favorecer testing modular."),
            "Gestión Modular de Dependencias".into(),
            "Agrupa módulos estándar, de terceros y locales de forma separada. Evita importar con comodín (*) para mantener la visibilidad explícita.".into(),
            "from typing import Optional, List, Dict".into(),
            flecha(&["[MÓDULOS EXTERNOS]", "   │", "   ▼", "[IMPORTS EXPLÍCITOS]", "   │", "   ▼", "[NÚCLEO DESACOPLADO]"]),
        )
    } else if es_bucle {
        (
            format!("[{ln}]: Bucle de procesamiento en L{lt}. Optimiza la complejidad temporal asintótica O(N) pre-indexando búsquedas en estructuras Hash."),
            "Optimización Asintótica O(N) ➔ O(1)".into(),
            "Evita búsquedas lineales o conversiones costosas dentro de cada ciclo del bucle. Pre-computa índices en diccionarios o sets.".into(),
            "lookup_table = {item.id: item for item in items}".into(),
            flecha(&["[COLECCIÓN ORIGEN]", "   │", "   ▼", "[PRE-INDEX HASH (O(1))]", "   │", "   ▼", "[ITERACIÓN SIN LATENCIA]"]),
        )
    } else if es_cond {
        (
            format!("[{ln}]: Ramificación condicional en L{lt}. Aplica cláusulas de guarda tempranas (Early Return) para reducir la indentación anidada."),
            "Cláusula de Guarda Temprana".into(),
            "Validar y rechazar estados no válidos al inicio del bloque simplifica la ruta principal del código y previene errores NoneType.".into(),
            "if not parametros_validos:\n    return None".into(),
            Valor::Lista(vec![format!("[ENTRADA: L{lt}]").into(), "   │".into(), "   ├── [INVÁLIDO?] ──► [RETURN]".into(), "   ▼".into(), "[FLUJO PRINCIPAL LIMPIO]".into()]),
        )
    } else if es_exc {
        (
            format!("[{ln}]: Control de fallos en L{lt}. Captura excepciones canónicas específicas en lugar de bloques genéricos que oculten bugs lógicos."),
            "Manejo Granular y Resiliente de Errores".into(),
            "Los bloques 'except Exception' genéricos pueden ocultar errores tipográficos o interrupciones de sistema. Captura únicamente excepciones esperadas.".into(),
            "except (ValueError, KeyError) as err:\n    logger.warning(f'Error controlado: {err}')".into(),
            flecha(&["[OPERACIÓN CRÍTICA]", "   │", "   ├──► [EXCEPCIÓN ESPERADA] ──► [FALLBACK]", "   ▼", "[ESTADO RESILIENTE]"]),
        )
    } else if es_funcion {
        (
            format!("[{ln}]: Firma de '{objetivo}' en L{lt}. Define contratos de entrada explícitos y anotaciones de tipo para verificación estática."),
            format!("Contratos de Tipo en '{objetivo}'"),
            format!("Documentar parámetros y tipos de retorno en '{objetivo}' previene desajustes de interfaces y asiste al autocompletado del editor."),
            format!("def {objetivo}(payload: dict) -> bool:"),
            Valor::Lista(vec![format!("[CONTRATO: {objetivo}]").into(), "   │".into(), "   ▼".into(), "[VALIDACIÓN TIPADA]".into(), "   │".into(), "   ▼".into(), "[EJECUCIÓN DETERMINISTA]".into()]),
        )
    } else if es_clase {
        (
            format!("[{ln}]: Definición de clase '{objetivo}' en L{lt}. Asegura alta cohesión interna y encapsulación de estado."),
            format!("Cohesión y Responsabilidad Única en '{objetivo}'"),
            format!("Mantén los métodos de '{objetivo}' centrados en su dominio específico, delegando responsabilidades colaterales en colaboradores dedicados."),
            format!("class {}:\n    def __init__(self, config): ...", crate::routes::desafios_fuentes::title(&objetivo)),
            Valor::Lista(vec![format!("[CLASE: {objetivo}]").into(), "   ├──► [ESTADO ENCAPSULADO]".into(), "   └──► [MÉTODOS COHESIVOS]".into(), "   ▼".into(), "[INSTANCIA ROBUSTA]".into()]),
        )
    } else if es_ret {
        (
            format!("[{ln}]: Emisión de salida en L{lt}. Preserva la inmutabilidad retornando copias o nuevos estados deterministas."),
            "Inmutabilidad de Salida y Determinismo".into(),
            "Evita mutar directamente referencias compartidas recibidas como parámetro. Retornar nuevas instancias evita efectos secundarios impredecibles.".into(),
            "return {**estado_previo, 'actualizado': True}".into(),
            flecha(&["[ESTADO INICIAL]", "   │", "   ▼", "[TRANSFORMACIÓN PURA]", "   │", "   ▼", "[ESTADO INMUTABLE]"]),
        )
    } else {
        match lente.texto("id").unwrap_or("ARQUITECTURA_Y_PATRONES") {
            "ALGORITMOS_Y_COMPLEJIDAD" => (
                format!("[{ln}]: Línea de cómputo L{lt} en '{objetivo}'. Evalúa el consumo de memoria evitando clonaciones innecesarias de buffers."),
                format!("Eficiencia de Memoria en L{lt}"),
                "Reutiliza referencias o usa iteradores generadores cuando transformes secuencias extensas para mantener el espacio auxiliar en O(1).".into(),
                format!("# Optimizar cómputo en {objetivo}"),
                flecha(&["[FLUJO DE DATOS]", "   │", "   ▼", "[BUFFER EFICIENTE O(1)]", "   │", "   ▼", "[RESULTADO]"]),
            ),
            "SEGURIDAD_Y_RESILIENCIA" => (
                format!("[{ln}]: Inspección defensiva en L{lt}. Comprueba invariantes de datos y neutraliza entradas no saneadas."),
                format!("Defensa en Profundidad en L{lt}"),
                "Asegura que los valores numéricos y cadenas cumplan con los límites esperados antes de utilizarlos en operaciones críticas.".into(),
                "assert valor is not None, 'Valor requerido'".into(),
                flecha(&["[ENTRADA]", "   │", "   ▼", "[VALIDADOR INVARIANTES]", "   │", "   ▼", "[OPERACIÓN SEGURA]"]),
            ),
            _ => (
                format!("[{ln}]: Línea activa L{lt} en '{objetivo}'. Nombres descriptivos y separación de constantes clarifican la intención del código."),
                format!("Claridad Semántica en '{objetivo}'"),
                "Extraer literales repetidos a constantes semánticas con nombre explicativo convierte el código en su propia documentación.".into(),
                "MAX_REINTENTOS = 3".into(),
                flecha(&["[LITERALES]", "   │", "   ▼", "[CONSTANTES SEMÁNTICAS]", "   │", "   ▼", "[CÓDIGO AUTO-EXPLICADO]"]),
            ),
        }
    };
    anotar_titulo(Valor::Texto(titulo.clone()));
    let tipo_rel = lente.get("tipo_relacion").cloned().unwrap_or("buenas_practicas".into());
    let consejo = Mapa::new()
        .con("tipo", tipo_rel.clone())
        .con("categoria", lente.get("categoria").cloned().unwrap_or("Clean Code".into()))
        .con("titulo", titulo)
        .con("detalle", detalle.as_str())
        .con("linea_inicio", lt)
        .con("linea_fin", lft)
        .con("sugerencia_codigo", sug.as_str());
    let foco = |l: i128| (l as f64 / total_l as f64 * 0.7 + 0.15).clamp(0.15, 0.85);
    let y = foco(lt);
    let pasos = if pasos_reales.len() >= 2 {
        Valor::Lista(pasos_reales)
    } else {
        let (ini, medio, fin) = (lt, total_l.min(lt + 1), total_l.min(lt + 3));
        let agente = |x: f64, y: f64| Mapa::new().con("x_ratio", x).con("y_ratio", y);
        Valor::Lista(vec![
            Valor::Mapa(
                Mapa::new()
                    .con("paso", 1)
                    .con("etiqueta", format!("Entrada [{objetivo}]"))
                    .con("tipo", "entrada")
                    .con("icono", "📥")
                    .con("linea_inicio", ini)
                    .con("linea_fin", medio)
                    .con("x_foco", 0.35)
                    .con("y_foco", redondear(y, 2))
                    .con("posicion_agente", agente(0.88, 0.88))
                    .con("explicacion", format!("Inspección de '{objetivo}' en línea L{lt}."))
                    .con("sugerencia", splitlines(&sug).first().copied().unwrap_or("")),
            ),
            Valor::Mapa(
                Mapa::new()
                    .con("paso", 2)
                    .con("etiqueta", "Verificación & Contrato")
                    .con("tipo", "proceso")
                    .con("icono", "⚡")
                    .con("linea_inicio", medio)
                    .con("linea_fin", fin)
                    .con("x_foco", 0.35)
                    .con("y_foco", redondear(foco(medio), 2))
                    .con("posicion_agente", agente(0.85, 0.82))
                    .con("explicacion", detalle)
                    .con("sugerencia", sug),
            ),
        ])
    };
    let ts = tonos(info);
    let nanos = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.subsec_nanos() as usize).unwrap_or(0);
    let tono = ts.get(nanos % ts.len().max(1)).cloned().unwrap_or_default();
    let decision = Mapa::new()
        .con("personaje", info.valor("nombre_personaje").clone())
        .con("pensamiento", format!("Lente [{}]: Analizando constructo '{objetivo}' en L{lt} ({}) enfocado en la edición activa.", t(lente, "nombre"), c.lenguaje))
        .con("dialogo", dialogo)
        .con("consejo", consejo)
        .con("flujo_ascii", flujo)
        .con("flujo_grafico", Mapa::new().con("activo", true).con("velocidad_ms", 3200).con("estilo", "spline_neon").con("pasos", pasos))
        .con("posicion", Mapa::new().con("x_ratio", 0.88).con("y_ratio", 0.88))
        .con(
            "inspeccion",
            Mapa::new()
                .con("activo", true)
                .con("linea", lt)
                .con("linea_fin", lft)
                .con("modo", "explicar")
                .con("tipo_relacion", tipo_rel)
                .con("x_foco", 0.35)
                .con("y_foco", redondear(y, 2)),
        )
        .con(
            "metricas",
            Mapa::new()
                .con("complejidad", if complejidad > 2 { "O(N)" } else { "O(1)" })
                .con("calidad", calidad)
                .con("modularidad", if hay_funciones { 95 } else { 88 })
                .con("mantenibilidad", if simbolos.len() > 2 { 94 } else { 91 }),
        )
        .con("modulo_activo", c.archivo_v.clone())
        .con("tono", tono);
    Ok(Mapa::new()
        .con("origen", "procedural_evaluador_lente")
        .con("tema", tema)
        .con("personaje_info", info.clone())
        .con("lente_aplicada", lente.valor("id").clone())
        .con("timestamp", ahora())
        .con("decision", decision))
}

/// `consultar_director`
fn consultar(base: &Path, tema: &str, ctx: Mapa, modelo: Option<&str>, endpoint: Option<&str>) -> Result<Mapa, String> {
    let info = info_tema(tema, false);
    let (endpoint, modelo) = destino(endpoint, modelo);
    let c = contexto(ctx);
    let lente = siguiente_lente();
    let anti = anti_repeticion();
    let sistema = prompt_sistema(&info, &lente, &anti);
    let usuario = prompt_usuario(&c, &lente, false)?;
    let efectivo = modelo_disponible(&endpoint, &modelo);
    let r = llamar(&endpoint, &efectivo, &sistema, &usuario);
    let decision = match decision_llm(r, "llm_7b", &efectivo, tema, &info, &lente)? {
        Some(d) => d,
        None => procedural(tema, &info, &c, &lente)?,
    };
    if !c.archivo.is_empty() && !c.codigo.is_empty() {
        memoria(base).registrar(&c.archivo, &c.codigo, &c.lenguaje, Some(&decision));
    }
    Ok(decision)
}

/// `consultar_director_stream`: los tokens del modelo según llegan y, al final, la decisión entera
fn consultar_flujo(base: &Path, tema: &str, ctx: Mapa, modelo: Option<&str>, endpoint: Option<&str>, enviar: &mut dyn FnMut(String)) -> Result<(), String> {
    let info = info_tema(tema, true);
    let (endpoint, modelo) = destino(endpoint, modelo);
    let c = contexto(ctx);
    let lente = siguiente_lente();
    let anti = anti_repeticion();
    let sistema = prompt_sistema_flujo(&info, &lente, &anti);
    let usuario = prompt_usuario(&c, &lente, true)?;
    let efectivo = modelo_disponible(&endpoint, &modelo);
    let opciones = Mapa::new().con("temperature", 0.48).con("num_predict", 220).con("top_p", 0.88).con("repeat_penalty", 1.22);
    let cuerpo = Mapa::new()
        .con("model", efectivo.as_str())
        .con("prompt", format!("{sistema}\n\n{usuario}"))
        .con("stream", true)
        .con("format", "json")
        .con("options", opciones);
    let mut acumulado = String::new();
    let resp = reqwest::blocking::Client::builder()
        .connect_timeout(Duration::from_secs(4))
        .timeout(Duration::from_secs(300))
        .build()
        .ok()
        .and_then(|cl| {
            cl.post(format!("{endpoint}/api/generate"))
                .header("Content-Type", "application/json")
                .body(prig_plataforma::json::escribir_compacto(&Valor::Mapa(cuerpo)))
                .send()
                .ok()
        })
        .filter(|r| r.status().as_u16() == 200);
    if let Some(r) = resp {
        use std::io::BufRead;
        for linea in std::io::BufReader::new(r).split(b'\n') {
            let Ok(linea) = linea else { break };
            if linea.is_empty() {
                continue;
            }
            let Ok(Valor::Mapa(trozo)) = prig_plataforma::json::leer(&String::from_utf8_lossy(&linea)) else { break };
            let token = trozo.get("response").cloned().unwrap_or("".into());
            if token.verdad() {
                acumulado.push_str(&token.texto_py());
                let msg = Mapa::new().con("tipo", "token").con("contenido", token);
                enviar(format!("data: {}\n\n", prig_plataforma::json::escribir_linea(&Valor::Mapa(msg))));
            }
        }
    }
    let r = limpiar_json(&acumulado);
    let decision = match decision_llm(r, "llm_7b_stream", &efectivo, tema, &info, &lente)? {
        Some(d) => d,
        None => procedural(tema, &info, &c, &lente)?,
    };
    if !c.archivo.is_empty() && !c.codigo.is_empty() {
        memoria(base).registrar(&c.archivo, &c.codigo, &c.lenguaje, Some(&decision));
    }
    let msg = Mapa::new().con("tipo", "decision_completa").con("data", decision);
    enviar(format!("data: {}\n\n", prig_plataforma::json::escribir_linea(&Valor::Mapa(msg))));
    Ok(())
}

// =========================================================================== la bitácora de pensamiento

struct Archivo {
    rel: String,
    ext: String,
    tam: i128,
    abs: String,
}

const IGNORAR: [&str; 10] = [".git", "node_modules", "__pycache__", ".venv", "target", "dist", "build", ".cache", ".idea", ".vscode"];
const EXT_CODIGO: [&str; 14] = [".py", ".rs", ".js", ".ts", ".html", ".css", ".json", ".toml", ".yaml", ".sql", ".sh", ".c", ".cpp", ".md"];

/// `os.walk(carpeta)` hasta 120 archivos, sin las carpetas ocultas ni las de dependencias o compilados
fn recorrer(raiz: &str, carpeta: &str, salida: &mut Vec<Archivo>) -> bool {
    let Ok(lectura) = std::fs::read_dir(raiz) else { return false };
    let (mut dirs, mut ficheros) = (Vec::new(), Vec::new());
    for e in lectura.flatten() {
        let nombre = e.file_name().to_string_lossy().into_owned();
        if std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false) {
            dirs.push(nombre);
        } else {
            ficheros.push(nombre);
        }
    }
    let rel_dir = py::relpath(raiz, carpeta);
    for f in ficheros {
        if f.starts_with('.') || f == PENSAMIENTO {
            continue;
        }
        let abs = py::join(raiz, &f);
        salida.push(Archivo {
            ext: py::splitext(&f).1.to_lowercase(),
            rel: if rel_dir != "." { py::normpath(&py::join(&rel_dir, &f)) } else { f.clone() },
            tam: std::fs::metadata(&abs).map(|m| m.len() as i128).unwrap_or(0),
            abs,
        });
        if salida.len() >= 120 {
            return true;
        }
    }
    for d in dirs {
        if IGNORAR.contains(&d.as_str()) || d.starts_with('.') {
            continue;
        }
        let ruta = py::join(raiz, &d);
        if std::fs::symlink_metadata(&ruta).map(|m| m.file_type().is_symlink()).unwrap_or(false) {
            continue;
        }
        if recorrer(&ruta, carpeta, salida) {
            return true;
        }
    }
    false
}

/// Las primeras 80 líneas de un archivo (`readline()` en modo texto, con `errors="replace"`)
fn primeras_lineas(ruta: &str) -> Option<String> {
    let bytes = std::fs::read(ruta).ok()?;
    let texto = String::from_utf8_lossy(&bytes).replace("\r\n", "\n").replace('\r', "\n");
    Some(texto.split_inclusive('\n').take(80).collect())
}

/// Las marcas `§nombre§` de la plantilla, de una pasada
fn rellenar(plantilla: &str, valores: &[(&str, String)]) -> String {
    let mut s = String::new();
    let mut partes = plantilla.split('§');
    s.push_str(partes.next().unwrap_or(""));
    let mut dentro = true;
    for p in partes {
        if dentro {
            s.push_str(valores.iter().find(|(k, _)| *k == p).map(|(_, v)| v.as_str()).unwrap_or(""));
        } else {
            s.push_str(p);
        }
        dentro = !dentro;
    }
    s
}

/// `ejecutar_pensamiento_en_archivo`: la bitácora del personaje sobre la carpeta (del modelo si responde con algo,
/// si no la propia), en `<carpeta>/PENSAMIENTO_DEL_PROYECTO.md`
fn pensamiento(base: &Path, carpeta: &str, tema: &str, modelo: Option<&str>, endpoint: Option<&str>) -> Result<Mapa, String> {
    let carpeta = py::strip(carpeta);
    let mut dir = py::abspath(if carpeta.is_empty() { "." } else { carpeta });
    let p = Path::new(&dir);
    if !p.exists() {
        py::makedirs(&dir)?;
    } else if p.is_file() {
        dir = py::dirname(&dir);
    }
    let info = personajes().mapa(tema).cloned().unwrap_or_else(mecha);
    let np = t(&info, "nombre_personaje");
    let mut archivos = Vec::new();
    recorrer(&dir, &dir, &mut archivos);
    let total = archivos.len();
    let mut analisis: Vec<(String, String, Vec<String>, i128)> = Vec::new();
    for a in archivos.iter().filter(|a| EXT_CODIGO.contains(&a.ext.as_str())).take(10) {
        let Some(texto) = primeras_lineas(&a.abs) else { continue };
        if a.ext == ".py" {
            let r = ast::analizar(&texto, "python");
            let fns = r.lista("simbolos").unwrap_or(&[]).iter().map(|s| mapa_de(s).valor("firma").texto_py()).take(4).collect();
            analisis.push((a.rel.clone(), "Python".into(), fns, 1));
        } else {
            let tipo = a.ext.replace('.', "").to_uppercase();
            analisis.push((a.rel.clone(), if tipo.is_empty() { "Texto".into() } else { tipo }, vec![], 1));
        }
    }
    let (endpoint, modelo) = destino(endpoint, modelo);
    let nombre_dir = {
        let b = py::basename(&dir);
        if b.is_empty() { "Proyecto".to_string() } else { b }
    };
    let sistema = format!(
        "Eres '{np}' ({}), el personaje y mentor interactivo de Prig IDE.\nArquetipo: {}. Estilo: {}. Tonos: {}.\nTu objetivo es redactar un documento Markdown exhaustivo y profesional que registre tu bitácora de pensamiento y razonamiento paso a paso al inspeccionar este proyecto. Incluye un monólogo interior con Chain-of-Thought, diagnóstico estructural, evaluación de invariantes, código refactorizado de ejemplo y un dictamen de calidad.",
        t(&info, "rol"),
        t(&info, "descripcion"),
        t(&info, "estilo_dialogo"),
        tonos(&info).join(", ")
    );
    let resumen = analisis
        .iter()
        .take(8)
        .map(|(f, tipo, fns, _)| {
            let muestra = if fns.is_empty() { "módulo".to_string() } else { fns.iter().take(2).cloned().collect::<Vec<_>>().join(", ") };
            format!("- `{f}` ({tipo}): {} funciones detectadas ({muestra})", fns.len())
        })
        .collect::<Vec<_>>()
        .join("\n");
    let resumen = if resumen.is_empty() { "- Sin archivos de código detectados en la muestra.".to_string() } else { resumen };
    let usuario = format!(
        "Carpeta del Proyecto: '{nombre_dir}' ({total} archivos detectados).\n\nMuestra de Archivos y Símbolos AST:\n{resumen}\n\nEscribe la bitácora de pensamiento completa en formato Markdown con las siguientes secciones obligatorias:\n# 🧠 Bitácora de Pensamiento: {np}\n## 1. Monólogo Interior y Escaneo Táctico (Chain-of-Thought)\n## 2. Cartografía y Arquitectura del Proyecto\n## 3. Puntos Críticos, Invariantes y Seguridad\n## 4. Propuesta de Refactorización y Código Recomendado\n## 5. Dictamen y Métricas Estimadas\nSé técnico, mordaz, minucioso y cita las funciones y rutas reales que ves aquí."
    );
    let cuerpo = Mapa::new()
        .con("model", modelo.as_str())
        .con("prompt", format!("{sistema}\n\n{usuario}"))
        .con("stream", false)
        .con("options", Mapa::new().con("temperature", 0.55).con("num_predict", 750).con("top_p", 0.90));
    let del_modelo = pedir_json(&format!("{endpoint}/api/generate"), &Valor::Mapa(cuerpo), 8.0)
        .map(|r| py::strip(&r.get("response").map(Valor::texto_py).unwrap_or_default()).to_string())
        .filter(|t| t.chars().count() > 200);
    let contenido = match del_modelo {
        Some(c) => c,
        None => {
            let lista = archivos.iter().take(15).map(|a| format!("| `{}` | `{}` | {} bytes |", a.rel, a.ext, a.tam)).collect::<Vec<_>>().join("\n");
            let lista = if lista.is_empty() { "| Ninguno | - | 0 bytes |".to_string() } else { lista };
            let mut detalles = String::new();
            for (f, tipo, fns, comp) in &analisis {
                let fns = if fns.is_empty() { "Sin funciones declaradas a nivel superior".to_string() } else { fns.iter().map(|x| format!("`{x}`")).collect::<Vec<_>>().join(", ") };
                detalles.push_str(&format!("- **`{f}`** ({tipo}):\n  - Funciones: {fns}\n  - Clases: Sin clases\n  - Complejidad: `{comp}`\n"));
            }
            if detalles.is_empty() {
                detalles = "- No se requirió parsing de árbol sintáctico para los módulos de este directorio.\n".into();
            }
            let ahora_s = ahora().floor() as libc::time_t;
            // SAFETY: localtime_r escribe en la estructura que se le da
            let fecha = unsafe {
                let mut tm: libc::tm = std::mem::zeroed();
                libc::localtime_r(&ahora_s, &mut tm);
                format!("{:04}-{:02}-{:02} {:02}:{:02}:{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec)
            };
            rellenar(
                include_str!("director_pensamiento.md"),
                &[
                    ("nombre_personaje", np.clone()),
                    ("rol", t(&info, "rol")),
                    ("nombre_tema", t(&info, "nombre")),
                    ("descripcion_personaje", t(&info, "descripcion")),
                    ("nombre_carpeta_display", nombre_dir.clone()),
                    ("carpeta_dir", dir.clone()),
                    ("fecha_str", fecha),
                    ("total_archivos", total.to_string()),
                    ("lista_md_archivos", lista),
                    ("detalles_ast_md", detalles),
                ],
            )
        }
    };
    let ruta = py::join(&dir, PENSAMIENTO);
    std::fs::write(&ruta, format!("{}\n", py::strip(&contenido))).map_err(|e| format!("No se pudo escribir {ruta}: {}", py::error_os(&e, &ruta)))?;
    let decision = Mapa::new()
        .con("personaje", np.as_str())
        .con("pensamiento", format!("Pensamiento ejecutado sobre carpeta {nombre_dir}"))
        .con("modulo_activo", PENSAMIENTO);
    memoria(base).registrar(PENSAMIENTO, &contenido, "markdown", Some(&decision));
    Ok(Mapa::new()
        .con("ok", true)
        .con("archivo", ruta)
        .con("nombre", PENSAMIENTO)
        .con("carpeta", dir)
        .con("personaje", np)
        .con("total_archivos", total as i128)
        .con("bytes", contenido.len() as i128))
}

// =========================================================================== preguntar a la memoria

/// `preguntar_al_cerebro`: con la memoria comprimida como contexto; sin modelo, lo que dice el grafo de símbolos
fn preguntar(base: &Path, pregunta: &str, modelo: Option<&str>, endpoint: Option<&str>) -> Mapa {
    if pregunta.is_empty() {
        return Mapa::new().con("ok", false).con("error", "Pregunta vacía");
    }
    let (archivos, grafo) = {
        let m = memoria(base);
        (m.archivos.clone(), m.grafo.clone())
    };
    let bloques: Vec<String> = archivos
        .iter()
        .map(|(_, info)| {
            let i = mapa_de(info);
            let ult = i.get("ultima_evaluacion").map(mapa_de).unwrap_or_default();
            format!("- {} | Última evaluación: {}", i.valor("digest_texto").texto_py(), ult.get("consejo_titulo").cloned().unwrap_or("OK".into()).texto_py())
        })
        .collect();
    let contexto = if bloques.is_empty() { "No hay archivos memorizados aún.".to_string() } else { bloques.join("\n") };
    let sistema = "Eres el CEREBRO IA DE MEMORIA INTEGRADA de Prig IDE.\nTienes acceso a la base de conocimiento semántica comprimida de los archivos que has leído y analizado en este proyecto.\nResponde de forma técnica, precisa, directa y orientada a la ingeniería de software.\nUsa los símbolos, firmas de funciones y métricas memorizadas para sustentar tus respuestas sin inventar archivos no presentes.";
    let usuario = format!("=== MEMORIA SEMÁNTICA COMPRIMIDA DE ARCHIVOS LEÍDOS ===\n{contexto}\n\nPREGUNTA DEL DESARROLLADOR: {pregunta}\nRESPUESTA ESTRUCTURADA:");
    let (endpoint, modelo) = destino(endpoint, modelo);
    let cuerpo = Mapa::new()
        .con("model", modelo.as_str())
        .con("prompt", format!("{sistema}\n\n{usuario}"))
        .con("stream", false)
        .con("options", Mapa::new().con("temperature", 0.3).con("num_predict", 250));
    let del_modelo = pedir_json(&format!("{endpoint}/api/generate"), &Valor::Mapa(cuerpo), 4.0)
        .map(|r| py::strip(&r.get("response").map(Valor::texto_py).unwrap_or_default()).to_string())
        .filter(|t| !t.is_empty());
    let nombres: Vec<String> = archivos.claves().cloned().collect();
    let respuesta = match del_modelo {
        Some(r) => r,
        None => {
            let total_simbolos: usize = archivos.iter().map(|(_, i)| mapa_de(i).lista("simbolos").map(<[Valor]>::len).unwrap_or(0)).sum();
            let bajo = pregunta.to_lowercase();
            let coincidencias: Vec<String> = grafo
                .iter()
                .filter(|(s, _)| bajo.contains(&s.to_lowercase()))
                .map(|(s, ocurrencias)| {
                    let locs: Vec<String> = match ocurrencias {
                        Valor::Lista(l) => l
                            .iter()
                            .map(|o| {
                                let o = mapa_de(o);
                                format!("{}:L{} ({})", t(&o, "archivo"), t(&o, "linea"), t(&o, "tipo"))
                            })
                            .collect(),
                        _ => vec![],
                    };
                    format!("• `{s}` definido en {}", locs.join(", "))
                })
                .collect();
            if !coincidencias.is_empty() {
                format!(
                    "**[CEREBRO IA - ÍNDICE DE SÍMBOLOS CRUZADOS]**:\nSe encontraron las siguientes referencias directas en el grafo del proyecto:\n\n{}\n\nTotal de archivos analizados: {} | Símbolos indexados: {total_simbolos}.",
                    coincidencias.join("\n"),
                    nombres.len()
                )
            } else {
                format!(
                    "**[CEREBRO IA - MEMORIA COMPRIMIDA]**:\nHe indexado {} archivos del proyecto ({}) con {total_simbolos} símbolos semánticos registrados.\nSobre tu consulta '{}': Los módulos analizados mantienen un índice libre de acoplamiento. Puedes consultar por cualquier función, clase o dependencia específica.",
                    nombres.len(),
                    nombres.iter().take(5).cloned().collect::<Vec<_>>().join(", "),
                    primeros(pregunta, 60)
                )
            }
        }
    };
    let mut m = memoria(base);
    let actuales: Vec<Valor> = m.archivos.claves().map(|k| Valor::Texto(k.clone())).collect();
    m.preguntas.push(Valor::Mapa(
        Mapa::new()
            .con("pregunta", pregunta)
            .con("respuesta", respuesta.as_str())
            .con("timestamp", ahora())
            .con("archivos_involucrados", Valor::Lista(actuales.clone())),
    ));
    m.guardar();
    let stats = m.estadisticas();
    Mapa::new()
        .con("ok", true)
        .con("respuesta", respuesta)
        .con("archivos_consultados", Valor::Lista(actuales))
        .con("tokens_ahorrados", stats.valor("tokens_netos_ahorrados").clone())
        .con("ahorro_porcentaje", stats.valor("ahorro_global_porcentaje").clone())
        .con("timestamp", ahora())
}

// =========================================================================== rutas

fn ok(v: Mapa) -> Response {
    json_py(StatusCode::OK, &Valor::Mapa(v))
}

fn fallo(e: String) -> Response {
    ok(Mapa::new().con("ok", false).con("error", e))
}

async fn bloque<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f)
        .await
        .unwrap_or_else(|_| (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response())
}

fn opcional(c: &Mapa, k: &str) -> Option<String> {
    c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py)
}

/// `LLMDirectorRequest`: `{tema_id = "tema_mecha_patrol", contexto = {}, modelo?, endpoint?}`
fn peticion(b: &Bytes) -> Result<(String, Mapa, Option<String>, Option<String>), Response> {
    let m = cuerpo::modelo(b)?;
    let c = cuerpo::tipados(&m, &[("tema_id", &Tipo::Texto, false), ("contexto", &DICT, false), ("modelo", &TEXTO_OPC, false), ("endpoint", &TEXTO_OPC, false)])?;
    Ok((
        c.get("tema_id").map(Valor::texto_py).unwrap_or_else(|| "tema_mecha_patrol".into()),
        c.get("contexto").map(mapa_de).unwrap_or_default(),
        opcional(&c, "modelo"),
        opcional(&c, "endpoint"),
    ))
}

/// `POST /api/llm/director_decision`
pub async fn decision(State(state): State<AppState>, b: Bytes) -> Response {
    let (tema, ctx, modelo, endpoint) = match peticion(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    let base = state.base_dir.clone();
    bloque(move || match consultar(&base, &tema, ctx, modelo.as_deref(), endpoint.as_deref()) {
        Ok(d) => ok(Mapa::new().con("ok", true).con("data", d)),
        Err(e) => fallo(e),
    })
    .await
}

/// `POST /api/llm/director_stream`: eventos del servidor (`data: {...}`)
pub async fn director_stream(State(state): State<AppState>, b: Bytes) -> Response {
    let (tema, ctx, modelo, endpoint) = match peticion(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    let base = state.base_dir.clone();
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(64);
    std::thread::spawn(move || {
        let mut enviar = |t: String| {
            let _ = tx.blocking_send(Ok(Bytes::from(t)));
        };
        // Un error a medio flujo corta la respuesta, como el generador de Python
        if consultar_flujo(&base, &tema, ctx, modelo.as_deref(), endpoint.as_deref(), &mut enviar).is_err() {
            let _ = tx.blocking_send(Err(std::io::Error::other("director")));
        }
    });
    let flujo = futures_util::stream::unfold(rx, |mut rx| async move { rx.recv().await.map(|x| (x, rx)) });
    ([(header::CONTENT_TYPE, "text/event-stream; charset=utf-8")], Body::from_stream(flujo)).into_response()
}

/// `GET /api/llm/memoria_archivos`
pub async fn memoria_archivos(State(state): State<AppState>) -> Response {
    let base = state.base_dir.clone();
    bloque(move || {
        let m = memoria(&base);
        ok(Mapa::new()
            .con("ok", true)
            .con("archivos", Valor::Lista(m.resumen()))
            .con("stats", m.estadisticas())
            .con("historial_preguntas", Valor::Lista(m.preguntas.clone())))
    })
    .await
}

/// `POST /api/llm/preguntar_cerebro` `{pregunta, modelo?, endpoint?}`
pub async fn preguntar_cerebro(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(&m, &[("pregunta", &Tipo::Texto, true), ("modelo", &TEXTO_OPC, false), ("endpoint", &TEXTO_OPC, false)])
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let base = state.base_dir.clone();
    bloque(move || ok(preguntar(&base, &c.valor("pregunta").texto_py(), opcional(&c, "modelo").as_deref(), opcional(&c, "endpoint").as_deref()))).await
}

/// `POST /api/llm/limpiar_memoria_cerebro`: los archivos y las preguntas (el grafo de símbolos se queda)
pub async fn limpiar_memoria(State(state): State<AppState>) -> Response {
    let base = state.base_dir.clone();
    bloque(move || {
        let mut m = memoria(&base);
        m.archivos = Mapa::new();
        m.preguntas.clear();
        m.guardar();
        ok(Mapa::new().con("ok", true).con("mensaje", "Memoria del cerebro reiniciada"))
    })
    .await
}

/// `POST /api/llm/ejecutar_pensamiento_proyecto` `{carpeta = "", tema_id = "tema_mecha_patrol", modelo?, endpoint?}`
pub async fn ejecutar_pensamiento(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(&m, &[("carpeta", &TEXTO_OPC, false), ("tema_id", &TEXTO_OPC, false), ("modelo", &TEXTO_OPC, false), ("endpoint", &TEXTO_OPC, false)])
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let base = state.base_dir.clone();
    bloque(move || {
        let carpeta = opcional(&c, "carpeta").unwrap_or_default();
        let tema = opcional(&c, "tema_id").filter(|t| !t.is_empty()).unwrap_or_else(|| "tema_mecha_patrol".into());
        match pensamiento(&base, &carpeta, &tema, opcional(&c, "modelo").as_deref(), opcional(&c, "endpoint").as_deref()) {
            Ok(m) => ok(m),
            Err(e) => fallo(e),
        }
    })
    .await
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn limpia_el_json_de_un_modelo() {
        let v = limpiar_json("Aquí va:\n```json\n{\"dialogo\": \"x\", \"l\": [1, 2,],}\n```").unwrap();
        assert_eq!(mapa_de(&v).valor("dialogo"), &Valor::Texto("x".into()));
        assert!(limpiar_json("nada").is_none());
    }

    #[test]
    fn la_plantilla_se_rellena_de_una_pasada() {
        assert_eq!(rellenar("a §x§ b §y§", &[("x", "§y§".into()), ("y", "2".into())]), "a §y§ b 2");
        assert!(!include_str!("director_pensamiento.md").contains('{') || include_str!("director_pensamiento.md").contains("{\"ok\""));
    }

    #[test]
    fn la_memoria_se_guarda_y_se_vuelve_a_leer() {
        let tmp = std::env::temp_dir().join(format!("prig_director_mem_{}", std::process::id()));
        let ruta = tmp.join(".prig_dataset").join("cerebro_memoria_comprimida.json");
        let mut m = Memoria { ruta: ruta.clone(), archivos: Mapa::new(), grafo: Mapa::new(), preguntas: Vec::new() };
        let codigo = "import math\n\nclass CalculadoraVentas:\n    def calcular_total(self, precios: List[float]) -> float:\n        return sum(precios)\n";
        m.registrar("ventas.py", codigo, "python", None);
        let r = m.resumen();
        assert_eq!(r.len(), 1);
        assert_eq!(mapa_de(&r[0]).valor("archivo"), &Valor::Texto("ventas.py".into()));
        assert_eq!(m.estadisticas().valor("total_archivos_memorizados"), &Valor::Entero(1));
        assert_eq!(m.grafo.lista("calcular_total").map(<[Valor]>::len), Some(1));
        let Ok(Valor::Mapa(d)) = prig_plataforma::leer_json(&ruta) else { panic!("sin archivo") };
        assert!(d.mapa("archivos").unwrap().contiene("ventas.py"));
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn las_lentes_rotan_sin_repetirse() {
        let ids: std::collections::HashSet<String> = (0..6).map(|_| t(&siguiente_lente(), "id")).collect();
        assert_eq!(ids.len(), 6);
    }

    #[test]
    fn escribe_la_bitacora_de_una_carpeta() {
        let tmp = std::env::temp_dir().join(format!("prig_director_pensar_{}", std::process::id()));
        std::fs::create_dir_all(tmp.join("node_modules")).unwrap();
        std::fs::write(tmp.join("modulo_test.py"), "def ejecutar_tarea(val: int) -> int:\n    return val * 2\n").unwrap();
        std::fs::write(tmp.join("node_modules/x.js"), "x\n").unwrap();
        let carpeta = tmp.to_string_lossy().into_owned();
        let r = pensamiento(&tmp, &carpeta, "tema_mecha_patrol", None, Some("http://127.0.0.1:9")).unwrap();
        assert_eq!(r.valor("nombre"), &Valor::Texto(PENSAMIENTO.into()));
        assert_eq!(r.valor("personaje"), &Valor::Texto("Titán Mecha MK-VII".into()));
        assert_eq!(r.valor("total_archivos"), &Valor::Entero(1));
        let md = std::fs::read_to_string(tmp.join(PENSAMIENTO)).unwrap();
        assert!(md.contains("Bitácora de Pensamiento") && md.contains("Chain-of-Thought"));
        assert!(md.contains("| `modulo_test.py` | `.py` | 56 bytes |"));
        assert!(md.contains("`def ejecutar_tarea(val: int) -> int:`"));
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn convierte_como_int() {
        assert_eq!(entero_o_uno(Some(&Valor::Texto(" 7 ".into()))), Ok(7));
        assert_eq!(entero_o_uno(Some(&Valor::Texto("".into()))), Ok(1));
        assert_eq!(entero_o_uno(Some(&Valor::Texto("x".into()))), Err("invalid literal for int() with base 10: 'x'".into()));
        assert_eq!(menos_uno(&Valor::Texto("3".into())), Err("unsupported operand type(s) for -: 'str' and 'int'".into()));
    }
}
