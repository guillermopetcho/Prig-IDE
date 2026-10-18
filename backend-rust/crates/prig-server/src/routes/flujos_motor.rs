//! Los dos motores de los flujos de agentes (`agent_flows.FlowEngine` y `agent_flows_v2.DynamicFlowEngine`), con lo
//! que necesitan: el catálogo de roles y variables, la validación, el plan de cargas de modelos, el recorte por el
//! medio, el JSON de las respuestas y el sandbox de Python de los nodos de herramienta.
//!
//! El motor clásico (v1) ejecuta los pasos en orden: cada uno ve solo las variables que pide (con el presupuesto de
//! la ventana repartido entre ellas), los pasos que deben devolver JSON se reintentan una vez señalando el fallo, y un
//! revisor puede devolver el trabajo a un paso anterior con su crítica. Genera con `generar_con_pausas` (uso «flujos»
//! y gobernador térmico) y espera entre pasos a que la GPU se enfríe.
//!
//! El motor de grafos (v2) sigue aristas: bucles de crítica con puntuación mínima, supervisores que eligen el siguiente
//! nodo, reglas de bifurcación, nodos que ejecutan el código del anterior y pausas de revisión. Emite cada token.

use prig_ia::generar::{self, PedidoGenerar, PedidoPausas};
use prig_ia::vivo::{self, Cancelar};
use prig_plataforma::json;
use prig_plataforma::py;
use prig_plataforma::valor::{redondear, Mapa, Valor};
use regex::Regex;
use std::path::Path;
use std::sync::LazyLock;
use std::time::Instant;

pub const MAX_FLUJOS: usize = 200;
pub const MAX_HISTORIAL: usize = 100;
pub const MAX_PASOS: usize = 12;
const MAX_VUELTAS_TOTALES: i64 = 6;
const CARACTERES_POR_TOKEN: f64 = 3.6;
const MAX_RECURSION_DEFECTO: i64 = 4;
const TIMEOUT_SANDBOX: u64 = 15;

// =========================================================================== el catálogo

/// Roles, variables y plantillas de `agent_flows.py` y `agent_flows_v2.py` (exportados tal cual). En las plantillas,
/// «\u0001B» es el modelo de base y «\u0001R» el que razona.
static DATOS: LazyLock<Mapa> = LazyLock::new(|| match json::leer(include_str!("flujos_datos.json")) {
    Ok(Valor::Mapa(m)) => m,
    _ => Mapa::new(),
});

fn dato(k: &str) -> &'static Mapa {
    static VACIO: LazyLock<Mapa> = LazyLock::new(Mapa::new);
    DATOS.mapa(k).unwrap_or(&VACIO)
}

pub fn roles() -> &'static Mapa {
    dato("roles")
}

pub fn roles_v2() -> &'static Mapa {
    dato("roles_v2")
}

pub fn variables() -> &'static Mapa {
    dato("variables")
}

pub fn variables_libro() -> &'static Mapa {
    dato("variables_libro")
}

/// `agent_flows.MODELOS`
pub fn modelos() -> &'static Mapa {
    &prig_ia::gestor::catalogo_partes().0
}

/// `agent_flows.MODELOS_EMBEDDING`
pub fn modelos_embedding() -> &'static Mapa {
    &prig_ia::gestor::catalogo_partes().1
}

/// `ROLE_SYSTEM_PROMPTS` de `AIEngine` (los pasos del workflow secuencial)
pub fn roles_workflow() -> &'static Mapa {
    dato("roles_workflow")
}

/// Cambia los marcadores de modelo de una plantilla
fn con_modelos(v: &Valor, base: &Valor, razona: &Valor) -> Valor {
    match v {
        Valor::Texto(t) if t == "\u{1}B" => base.clone(),
        Valor::Texto(t) if t == "\u{1}R" => razona.clone(),
        Valor::Lista(l) => Valor::Lista(l.iter().map(|x| con_modelos(x, base, razona)).collect()),
        Valor::Mapa(m) => Valor::Mapa(m.iter().fold(Mapa::new(), |acc, (k, x)| acc.con(k.clone(), con_modelos(x, base, razona)))),
        otro => otro.clone(),
    }
}

/// `agent_flows.plantillas(modelo_base, modelo_razona)`: el que razona, o el de base si no hay
pub fn plantillas(base: &Valor, razona: &Valor) -> Vec<Valor> {
    let r = if razona.verdad() { razona } else { base };
    DATOS.lista("plantillas").unwrap_or(&[]).iter().map(|p| con_modelos(p, base, r)).collect()
}

/// `agent_flows_v2.plantillas_profesionales_sota(modelo_base, modelo_razona)`
pub fn plantillas_v2(base: &Valor, razona: &Valor) -> Vec<Valor> {
    let b = if base.verdad() { base.clone() } else { Valor::Texto("qwen2.5-coder:7b".into()) };
    let r = if razona.verdad() { razona.clone() } else { Valor::Texto("qwen3:8b".into()) };
    DATOS.lista("plantillas_v2").unwrap_or(&[]).iter().map(|p| con_modelos(p, &b, &r)).collect()
}

/// `version_suficiente`: compara versiones tipo 0.5.7
pub fn version_suficiente(actual: &str, minima: &str) -> bool {
    static NUM: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\d+").unwrap());
    let partes = |v: &str| {
        let mut n: Vec<u128> = NUM.find_iter(v).take(3).map(|m| m.as_str().parse().unwrap_or(u128::MAX)).collect();
        if n.is_empty() {
            n.push(0);
        }
        n.resize(3.max(n.len()), 0);
        n
    };
    partes(actual) >= partes(minima)
}

/// `ollama_necesario`: la versión mínima de Ollama para la familia del modelo
pub fn ollama_necesario(modelo: &str) -> Option<String> {
    let familia = modelo.split(':').next().unwrap_or("");
    dato("ollama_minimo").texto(familia).map(String::from)
}

/// `detectar_vram_gb()`: la VRAM de la GPU según nvidia-smi, o 6 GB
pub fn vram_tipica() -> f64 {
    static V: LazyLock<f64> = LazyLock::new(|| {
        let salida = std::process::Command::new("nvidia-smi")
            .args(["--query-gpu=memory.total", "--format=csv,noheader,nounits"])
            .output()
            .ok()
            .map(|o| String::from_utf8_lossy(&o.stdout).into_owned());
        salida
            .and_then(|s| s.split_whitespace().filter(|x| !x.is_empty() && x.chars().all(|c| c.is_ascii_digit())).filter_map(|x| x.parse::<i64>().ok()).max())
            .map(|mb| redondear(mb as f64 / 1024.0, 1))
            .unwrap_or(6.0)
    });
    *V
}

// =========================================================================== utilidades de Python

/// `float(v)` con los mensajes de Python
fn float_py(v: &Valor) -> Result<f64, String> {
    match v {
        Valor::Texto(t) => prig_plataforma::valor::real_de_texto(t).ok_or_else(|| format!("could not convert string to float: {}", v.repr_py())),
        otro => otro.num().ok_or_else(|| format!("float() argument must be a string or a real number, not '{}'", py::tipo(otro))),
    }
}

/// `int(v)` con los mensajes de Python
fn int_py(v: &Valor) -> Result<i128, String> {
    match v {
        Valor::Real(x) if !x.is_finite() => Err("cannot convert float infinity to integer".into()),
        Valor::Texto(t) => prig_plataforma::valor::entero_de_texto(t).ok_or_else(|| format!("invalid literal for int() with base 10: {}", v.repr_py())),
        Valor::Lista(_) | Valor::Mapa(_) | Valor::Nulo => {
            Err(format!("int() argument must be a string, a bytes-like object or a real number, not '{}'", py::tipo(v)))
        }
        otro => Ok(otro.entero().unwrap_or(0)),
    }
}

/// `d.get(k, defecto)`
fn get_o<'a>(m: &'a Mapa, k: &str, defecto: &'a Valor) -> &'a Valor {
    m.get(k).unwrap_or(defecto)
}

/// `(x or "")` como texto
fn texto_o(v: Option<&Valor>) -> String {
    match v {
        Some(x) if x.verdad() => x.texto_py(),
        _ => String::new(),
    }
}

fn mapa_o(v: Option<&Valor>) -> Mapa {
    match v {
        Some(Valor::Mapa(m)) => m.clone(),
        _ => Mapa::new(),
    }
}

/// Los primeros `n` caracteres
fn primeros(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

/// Los últimos `n` caracteres
fn ultimos(t: &str, n: usize) -> String {
    let total = t.chars().count();
    t.chars().skip(total.saturating_sub(n)).collect()
}

/// `iter(v)` de lo que puede venir en «problemas»: los elementos de una lista, las letras de un texto, las claves de un
/// dict
fn elementos(v: &Valor) -> Vec<Valor> {
    match v {
        Valor::Lista(l) => l.clone(),
        Valor::Texto(t) => t.chars().map(|c| Valor::Texto(c.to_string())).collect(),
        Valor::Mapa(m) => m.claves().map(|k| Valor::Texto(k.clone())).collect(),
        _ => Vec::new(),
    }
}

/// `round(segundos, n)`
fn segundos(t0: Instant, n: usize) -> f64 {
    redondear(t0.elapsed().as_secs_f64(), n)
}

// =========================================================================== validación

static PATRON_VAR: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\{([a-zA-Z_][a-zA-Z0-9_]*(?::[a-zA-Z0-9_\-]+)?)\}").unwrap());

/// `variables_usadas(prompt)`: ordenadas y sin repetir
pub fn variables_usadas(prompt: &str) -> Vec<String> {
    let mut v: Vec<String> = PATRON_VAR.captures_iter(prompt).map(|c| c[1].to_string()).collect();
    v.sort();
    v.dedup();
    v
}

/// `validar_flujo`: los problemas de un flujo, en lenguaje de quien lo está montando
pub fn validar_flujo(flujo: &Mapa) -> Vec<String> {
    let mut problemas = Vec::new();
    let pasos: Vec<Mapa> = match flujo.get("pasos") {
        Some(Valor::Lista(l)) => l.iter().map(|p| mapa_o(Some(p))).collect(),
        _ => Vec::new(),
    };
    if pasos.is_empty() {
        return vec!["El flujo no tiene ningún paso".into()];
    }
    if pasos.len() > MAX_PASOS {
        problemas.push(format!("Demasiados pasos ({}); el máximo es {MAX_PASOS}", pasos.len()));
    }
    if py::strip(&texto_o(flujo.get("nombre"))).is_empty() {
        problemas.push("El flujo necesita un nombre".into());
    }
    let mut ids: Vec<String> = Vec::new();
    for (n, paso) in pasos.iter().enumerate() {
        let n = n + 1;
        let nombre = texto_o(paso.get("nombre"));
        let etiqueta = format!("Paso {n} ({})", if nombre.is_empty() { "sin nombre" } else { &nombre });
        let pid = py::strip(&texto_o(paso.get("id"))).to_string();
        if pid.is_empty() {
            problemas.push(format!("{etiqueta}: le falta el identificador"));
        } else if ids.contains(&pid) {
            problemas.push(format!("{etiqueta}: el identificador '{pid}' está repetido"));
        }
        ids.push(pid.clone());
        let prompt = texto_o(paso.get("prompt"));
        if py::strip(&prompt).is_empty() {
            problemas.push(format!("{etiqueta}: no tiene instrucción"));
        }
        let rol = paso.valor("rol");
        if !matches!(rol, Valor::Texto(r) if roles().contiene(r)) {
            problemas.push(format!("{etiqueta}: rol desconocido '{}'", rol.texto_py()));
        }
        if py::strip(&texto_o(paso.get("modelo"))).is_empty() {
            problemas.push(format!("{etiqueta}: no tiene modelo asignado"));
        }
        let anteriores = &ids[..ids.len() - 1];
        let usadas = variables_usadas(&prompt);
        for var in &usadas {
            if let Some(objetivo) = var.strip_prefix("paso:") {
                if !anteriores.iter().any(|i| i == objetivo) {
                    problemas.push(format!("{etiqueta}: usa {{{var}}}, pero no hay ningún paso anterior con ese identificador"));
                }
            } else if !variables().contiene(var) && !variables_libro().contiene(var) && var != "critica" {
                problemas.push(format!("{etiqueta}: la variable {{{var}}} no existe"));
            }
        }
        if n == 1 && usadas.iter().any(|v| v == "anterior") {
            problemas.push(format!("{etiqueta}: usa {{anterior}}, pero es el primer paso"));
        }
        if usadas.iter().any(|v| v == "critica") {
            let lo_revisan = pasos.iter().any(|otro| matches!(mapa_o(otro.get("si_falla")).get("volver_a"), Some(Valor::Texto(d)) if *d == pid));
            if !lo_revisan {
                problemas.push(format!(
                    "{etiqueta}: usa {{critica}}, pero ningún revisor le devuelve el trabajo, así que llegaría siempre vacía. Usa \
                     {{paso:id}} del revisor si lo que quieres es leer su informe"
                ));
            }
        }
        let vuelta = mapa_o(paso.get("si_falla"));
        if !vuelta.is_empty() {
            let destino = vuelta.valor("volver_a");
            if !matches!(destino, Valor::Texto(d) if anteriores.contains(d)) {
                problemas.push(format!("{etiqueta}: al fallar vuelve a '{}', que no es un paso anterior", destino.texto_py()));
            }
            if !matches!(rol, Valor::Texto(r) if r == "criticar" || r == "verificar") {
                problemas.push(format!("{etiqueta}: solo un revisor o un verificador puede devolver el trabajo a un paso anterior"));
            }
        }
    }
    problemas
}

/// `plan_de_modelos`: cuántas veces habrá que cargar un modelo, y qué cuesta eso
pub fn plan_de_modelos(flujo: &Mapa) -> Mapa {
    let secuencia: Vec<String> = flujo
        .lista("pasos")
        .unwrap_or(&[])
        .iter()
        .filter_map(|p| match p {
            Valor::Mapa(p) if p.verdad("modelo") => Some(p.valor("modelo").texto_py()),
            _ => None,
        })
        .collect();
    let mut cargas = 0i64;
    let mut ultimo: Option<&String> = None;
    for m in &secuencia {
        if ultimo != Some(m) {
            cargas += 1;
            ultimo = Some(m);
        }
    }
    let mut distintos = secuencia.clone();
    distintos.sort();
    distintos.dedup();
    let minimo = distintos.len() as i64;
    let mut vram = Valor::Entero(0);
    for m in &distintos {
        let v = modelos().mapa(m).and_then(|i| i.get("vram_gb")).cloned().unwrap_or(Valor::Entero(0));
        if v.num().unwrap_or(0.0) > vram.num().unwrap_or(0.0) {
            vram = v;
        }
    }
    let cabe = if vram.verdad() { vram.num().unwrap_or(0.0) <= vram_tipica() - 0.6 } else { true };
    Mapa::new()
        .con("modelos", Valor::Lista(distintos.into_iter().map(Valor::Texto).collect()))
        .con("cargas", cargas)
        .con("cargas_minimas", minimo)
        .con("recargas_evitables", (cargas - minimo).max(0))
        .con("vram_mayor_gb", vram)
        .con("cabe_en_vram", cabe)
        .con("segundos_estimados_de_carga", cargas * 8)
}

// =========================================================================== texto de los modelos

/// `_recortar`: por el medio, conservando principio y final
fn recortar(texto: &str, tope_tokens: i64, etiqueta: &str) -> String {
    let tope = (tope_tokens as f64 * CARACTERES_POR_TOKEN) as i64;
    let largo = texto.chars().count() as i64;
    if largo <= tope {
        return texto.to_string();
    }
    let mitad = tope / 2 - 60;
    let aviso = format!(
        "\n\n[… recortado{}, {} caracteres omitidos …]\n\n",
        if etiqueta.is_empty() { String::new() } else { format!(" de {etiqueta}") },
        largo - tope
    );
    let chars: Vec<char> = texto.chars().collect();
    // texto[:mitad] + aviso + texto[-mitad:], con los índices negativos de Python
    let corte = |i: i64| -> usize { (if i < 0 { (largo + i).max(0) } else { i.min(largo) }) as usize };
    let principio: String = chars[..corte(mitad)].iter().collect();
    let final_: String = if mitad == 0 { chars.iter().collect() } else { chars[corte(-mitad)..].iter().collect() };
    format!("{principio}{aviso}{final_}")
}

static PENSAMIENTO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?is)<think(?:ing)?>.*?</think(?:ing)?>\s*").unwrap());

/// `_sin_pensamiento`: sin el bloque de razonamiento que algunos modelos dejan en el texto
pub fn sin_pensamiento(texto: &str) -> String {
    let mut limpio = PENSAMIENTO.replace_all(texto, "").into_owned();
    let bajo = limpio.to_lowercase();
    if bajo.contains("<think") && !bajo.contains("</think") {
        // el índice en minúsculas vale en el original si las letras no cambian de tamaño al pasar a minúsculas
        let corte = limpio.char_indices().map(|(i, _)| i).find(|&i| limpio[i..].to_lowercase().starts_with("<think")).unwrap_or(limpio.len());
        limpio.truncate(corte);
    }
    py::strip(&limpio).to_string()
}

/// El primer objeto o lista JSON balanceado del texto (`_json_de`, y el tercer intento de `extraer_json_seguro`)
fn json_balanceado(texto: &str) -> Option<Valor> {
    let b = texto.as_bytes();
    for (abre, cierra) in [(b'{', b'}'), (b'[', b']')] {
        let Some(inicio) = b.iter().position(|&c| c == abre) else { continue };
        let (mut profundidad, mut en_cadena, mut escape) = (0i64, false, false);
        for i in inicio..b.len() {
            let c = b[i];
            if escape {
                escape = false;
                continue;
            }
            if c == b'\\' {
                escape = true;
                continue;
            }
            if c == b'"' {
                en_cadena = !en_cadena;
                continue;
            }
            if en_cadena {
                continue;
            }
            if c == abre {
                profundidad += 1;
            } else if c == cierra {
                profundidad -= 1;
                if profundidad == 0 {
                    match leer_json(&texto[inicio..=i]) {
                        Some(v) => return Some(v),
                        None => break,
                    }
                }
            }
        }
    }
    None
}

/// `json.loads`: None si no es JSON (o es `null`, que para quien pregunta es lo mismo)
fn leer_json(t: &str) -> Option<Valor> {
    json::leer(py::strip(t)).ok().filter(|v| !v.es_nulo())
}

/// `_json_de`: el primer objeto o lista JSON del texto, tolerando markdown alrededor
pub fn json_de(texto: &str) -> Option<Valor> {
    if texto.is_empty() {
        return None;
    }
    json_balanceado(texto)
}

/// `extraer_json_seguro` (v2): el texto entero, un bloque ```json o el primer objeto balanceado
pub fn extraer_json_seguro(texto: &str) -> Option<Valor> {
    if texto.is_empty() {
        return None;
    }
    let limpio = PENSAMIENTO.replace_all(texto, "");
    let limpio = py::strip(&limpio);
    if let Ok(v) = json::leer(limpio) {
        return if v.es_nulo() { None } else { Some(v) };
    }
    static BLOQUE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"```(?:json)?\s*([\{\[][\s\S]*?[\}\]])\s*```").unwrap());
    if let Some(c) = BLOQUE.captures(limpio) {
        if let Ok(v) = json::leer(&c[1]) {
            return if v.es_nulo() { None } else { Some(v) };
        }
    }
    json_balanceado(limpio)
}

/// `_texto_critica`: los problemas del revisor, en la forma en que el corrector puede usarlos
fn texto_critica(datos: &Valor) -> String {
    let Valor::Mapa(d) = datos else { return primeros(&datos.texto_py(), 1500) };
    let mut lineas = Vec::new();
    let campo = |p: &Mapa, k: &str, def: &str| p.get(k).map(Valor::texto_py).unwrap_or_else(|| def.to_string());
    if d.verdad("problemas") {
        for p in elementos(d.valor("problemas")) {
            match &p {
                Valor::Mapa(p) => lineas.push(format!(
                    "- En {}: {}. Arreglo sugerido: {}",
                    campo(p, "donde", "el texto"),
                    campo(p, "que", ""),
                    campo(p, "arreglo", "—")
                )),
                otro => lineas.push(format!("- {}", otro.texto_py())),
            }
        }
    }
    if d.verdad("incorrectas") {
        for p in elementos(d.valor("incorrectas")) {
            match &p {
                Valor::Mapa(p) => lineas.push(format!("- «{}» es incorrecta: {}", campo(p, "afirmacion", ""), campo(p, "fallo", ""))),
                otro => lineas.push(format!("- {}", otro.texto_py())),
            }
        }
    }
    let t = lineas.join("\n");
    if t.is_empty() {
        primeros(&json::escribir_linea(datos), 1500)
    } else {
        t
    }
}

// =========================================================================== motor clásico (v1)

/// Lo que comparten las ejecuciones: la carpeta de Prig, la ventana y cómo cancelar
pub struct Ejecucion<'a> {
    pub raiz: &'a Path,
    pub num_ctx: i64,
    pub cancelar: &'a Cancelar,
}

/// `int(ai_engine.config.get("num_ctx", defecto))`, o el defecto si no se puede
pub fn num_ctx(defecto: i64) -> i64 {
    match prig_ia::motor::config_ia().get("num_ctx") {
        None => defecto,
        Some(v) => int_py(v).map(|n| n as i64).unwrap_or(defecto),
    }
}

fn rol_de(paso: &Mapa) -> &'static Mapa {
    let r = match paso.get("rol") {
        Some(Valor::Texto(r)) => roles().mapa(r),
        _ => None,
    };
    r.or_else(|| roles().mapa("razonar")).expect("el rol razonar")
}

/// `FlowEngine.debe_pensar`: None para los modelos que no lo pueden cambiar
pub fn debe_pensar(paso: &Mapa) -> Option<bool> {
    let modelo = texto_o(paso.get("modelo"));
    let info = modelos().mapa(&modelo)?;
    if info.texto("piensa") != Some("conmutable") {
        return None;
    }
    if let Some(p) = paso.get("pensar").filter(|p| !p.es_nulo()) {
        return Some(p.verdad());
    }
    let sin_pensar = DATOS.lista("roles_sin_pensar").unwrap_or(&[]);
    Some(!sin_pensar.contains(paso.valor("rol")))
}

impl Ejecucion<'_> {
    /// `_llamar`: la respuesta del paso sin razonamiento (con pausas térmicas que se avisan)
    fn llamar(&self, paso: &Mapa, prompt: &str, avisar: &mut dyn FnMut(Mapa)) -> Result<String, String> {
        let rol = rol_de(paso);
        let propio = py::strip(&texto_o(paso.get("sistema"))).to_string();
        let sistema = if propio.is_empty() { rol.valor("sistema").texto_py() } else { propio };
        let temperatura = float_py(get_o(paso, "temperatura", rol.valor("temperatura")))?;
        let max_tokens = int_py(get_o(paso, "max_tokens", &Valor::Entero(1200)))?;
        let p = PedidoPausas {
            prompt: prompt.to_string(),
            modelo: paso.valor("modelo").texto_py(),
            sistema,
            opciones: Some(Mapa::new().con("temperature", temperatura).con("num_predict", Valor::Entero(max_tokens))),
            think: debe_pensar(paso),
            uso: Some("flujos".into()),
            gobernador: true,
        };
        let salida = generar::generar_con_pausas(self.raiz, &p, self.cancelar, Some(&mut *avisar))?;
        Ok(sin_pensamiento(py::strip(&salida)))
    }

    /// `_con_formato`: si pedía JSON y no lo devolvió, se reintenta una vez señalando el fallo
    fn con_formato(&self, paso: &Mapa, prompt: &str, avisar: &mut dyn FnMut(Mapa)) -> Result<(String, Option<Valor>), String> {
        let formato = match paso.get("formato") {
            Some(f) if f.verdad() => f.texto_py(),
            _ => rol_de(paso).valor("formato").texto_py(),
        };
        let salida = self.llamar(paso, prompt, avisar)?;
        if formato != "json" {
            return Ok((salida, None));
        }
        if let Some(d) = json_de(&salida) {
            return Ok((json::escribir(&d, 1), Some(d)));
        }
        let reintento = format!(
            "{prompt}\n\n---\nTu respuesta anterior no era JSON válido. Devuelve EXCLUSIVAMENTE el objeto JSON, sin texto \
             alrededor, sin ``` y sin explicaciones."
        );
        let salida = self.llamar(paso, &reintento, avisar)?;
        Ok(match json_de(&salida) {
            Some(d) => (json::escribir(&d, 1), Some(d)),
            None => (salida, None),
        })
    }

    /// `_render`: sustituye las variables repartiendo el presupuesto entre las que se usan
    fn render(plantilla: &str, valores: &Mapa, presupuesto: i64) -> String {
        let usadas = variables_usadas(plantilla).into_iter().filter(|v| valores.verdad(v)).count() as i64;
        if usadas == 0 {
            return plantilla.to_string();
        }
        let libre = 200.max(presupuesto - (plantilla.chars().count() as f64 / CARACTERES_POR_TOKEN) as i64);
        let por_variable = 150.max(libre.div_euclid(usadas));
        PATRON_VAR
            .replace_all(plantilla, |c: &regex::Captures| match valores.get(&c[1]) {
                Some(v) => recortar(&v.texto_py(), por_variable, &c[1]),
                None => c[0].to_string(),
            })
            .into_owned()
    }

    /// `FlowEngine.ejecutar`: cada paso según va ocurriendo. Error: lo que en Python saltaba fuera del bucle.
    pub fn ejecutar(&self, flujo: &Mapa, entrada: &str, consulta_contexto: &str, extra: Option<&Mapa>, emitir: &mut dyn FnMut(Mapa)) -> Result<(), String> {
        let problemas = validar_flujo(flujo);
        if !problemas.is_empty() {
            emitir(
                Mapa::new()
                    .con("tipo", "error")
                    .con("mensaje", "El flujo tiene problemas")
                    .con("problemas", Valor::Lista(problemas.into_iter().map(Valor::Texto).collect())),
            );
            return Ok(());
        }
        let pasos: Vec<Mapa> = flujo.lista("pasos").unwrap_or(&[]).iter().map(|p| mapa_o(Some(p))).collect();
        emitir(
            Mapa::new()
                .con("tipo", "inicio")
                .con("pasos", pasos.len())
                .con("plan", plan_de_modelos(flujo))
                .con("comenzado", py::ahora_iso()),
        );
        let mut salidas = Mapa::new();
        let mut datos_json = Mapa::new();
        let mut orden: Vec<String> = Vec::new();
        let mut registro: Vec<Valor> = Vec::new();
        let mut critica_pendiente = String::new();
        let mut vueltas = 0i64;
        let mut indice = 0usize;
        let mut modelo_cargado: Option<Valor> = None;
        let t_inicio = Instant::now();
        let titulo = match (flujo.get("titulo"), flujo.get("nombre")) {
            (Some(t), _) if t.verdad() => t.clone(),
            (_, Some(n)) if n.verdad() => n.clone(),
            _ => Valor::Texto(String::new()),
        };
        while indice < pasos.len() {
            if self.cancelar.puesto() {
                emitir(Mapa::new().con("tipo", "cancelado").con("mensaje", "Flujo de análisis detenido."));
                return Ok(());
            }
            let paso = &pasos[indice];
            let pid = paso.valor("id").texto_py();
            let rol = rol_de(paso);
            let presupuesto = 400.max((self.num_ctx as f64 * 0.6) as i64);
            let anterior = orden.last().map(|o| salidas.valor(o).clone()).unwrap_or(Valor::Texto(String::new()));
            let mut valores = Mapa::new()
                .con("entrada", entrada)
                .con("anterior", anterior)
                .con("titulo", titulo.clone())
                .con("critica", critica_pendiente.as_str())
                .con("contexto", "");
            for (k, v) in salidas.iter() {
                valores.poner(format!("paso:{k}"), v.clone());
            }
            for (k, v) in extra.map(|e| e.iter().collect::<Vec<_>>()).unwrap_or_default() {
                valores.poner(k.clone(), v.clone());
            }
            let plantilla = paso.valor("prompt").texto_py();
            let usadas = variables_usadas(&plantilla);
            if usadas.iter().any(|v| v == "contexto") {
                let consulta = if consulta_contexto.is_empty() { entrada } else { consulta_contexto };
                let ctx = if py::strip(consulta).is_empty() { String::new() } else { crate::routes::kb::contexto_texto(consulta, presupuesto / 2) };
                valores.poner("contexto", ctx);
            }
            let mut prompt = Self::render(&plantilla, &valores, presupuesto);
            if !critica_pendiente.is_empty() && !usadas.iter().any(|v| v == "critica") {
                prompt += "\n\n---\nTu intento anterior fue revisado y tiene estos problemas. Rehaz el trabajo corrigiéndolos; lo \
                           que no esté señalado aquí ya estaba bien y no hace falta cambiarlo.\n\n";
                prompt += &recortar(&critica_pendiente, presupuesto / 4, "la revisión");
            }
            let (ind, pid_c) = (indice, pid.clone());
            let con_paso = move |a: Mapa| a.con("indice", ind).con("id", pid_c.as_str());
            let mut avisos = Vec::new();
            let pausa = vivo::recursos(self.raiz).antes_de_trabajar(Some(self.cancelar), Some(&mut |a: Mapa| avisos.push(a)));
            for a in avisos {
                emitir(con_paso(a));
            }
            if pausa != 0.0 && self.cancelar.puesto() {
                continue;
            }
            let modelo = paso.valor("modelo").clone();
            let nombre = if paso.verdad("nombre") { paso.valor("nombre").clone() } else { Valor::Texto(pid.clone()) };
            emitir(
                Mapa::new()
                    .con("tipo", "paso_inicio")
                    .con("indice", indice)
                    .con("id", pid.as_str())
                    .con("nombre", nombre.clone())
                    .con("rol", paso.valor("rol").clone())
                    .con("modelo", modelo.clone())
                    .con("recarga_modelo", modelo_cargado.as_ref() != Some(&modelo))
                    .con("tokens_prompt", (prompt.chars().count() as f64 / CARACTERES_POR_TOKEN) as i64),
            );
            modelo_cargado = Some(modelo.clone());
            let t0 = Instant::now();
            let r = {
                let mut avisar = |a: Mapa| emitir(con_paso(a));
                self.con_formato(paso, &prompt, &mut avisar)
            };
            let (salida, datos) = match r {
                Ok(x) => x,
                Err(e) => {
                    emitir(Mapa::new().con("tipo", "paso_error").con("indice", indice).con("id", pid.as_str()).con("mensaje", e.as_str()));
                    (format!("[el paso falló: {e}]"), None)
                }
            };
            let dt = segundos(t0, 1);
            salidas.poner(pid.clone(), salida.as_str());
            if let Some(d) = &datos {
                datos_json.poner(pid.clone(), d.clone());
            }
            orden.push(pid.clone());
            registro.push(Valor::Mapa(
                Mapa::new()
                    .con("id", pid.as_str())
                    .con("nombre", nombre.clone())
                    .con("rol", paso.valor("rol").clone())
                    .con("modelo", modelo)
                    .con("segundos", dt)
                    .con("prompt", prompt.as_str())
                    .con("salida", salida.as_str())
                    .con("vuelta", vueltas),
            ));
            let formato = match paso.get("formato") {
                Some(f) if f.verdad() => f.clone(),
                _ => rol.valor("formato").clone(),
            };
            emitir(
                Mapa::new()
                    .con("tipo", "paso_fin")
                    .con("indice", indice)
                    .con("id", pid.as_str())
                    .con("nombre", nombre.clone())
                    .con("salida", salida.as_str())
                    .con("datos", datos.clone().unwrap_or(Valor::Nulo))
                    .con("segundos", dt)
                    .con("formato", formato),
            );
            if debe_volver(paso, datos.as_ref()) && vueltas < MAX_VUELTAS_TOTALES {
                let si_falla = mapa_o(paso.get("si_falla"));
                let destino = si_falla.valor("volver_a").clone();
                let tope = int_py(get_o(&si_falla, "max_vueltas", &Valor::Entero(2)))? as i64;
                let hechas = registro.iter().filter(|r| matches!(r, Valor::Mapa(r) if *r.valor("id") == destino)).count() as i64 - 1;
                if hechas < tope {
                    vueltas += 1;
                    critica_pendiente = texto_critica(datos.as_ref().unwrap_or(&Valor::Nulo));
                    emitir(
                        Mapa::new()
                            .con("tipo", "vuelta")
                            .con("desde", pid.as_str())
                            .con("hacia", destino.clone())
                            .con("vuelta", hechas + 1)
                            .con("de", tope)
                            .con("motivo", primeros(&critica_pendiente, 400)),
                    );
                    indice = pasos.iter().position(|p| *p.valor("id") == destino).ok_or("StopIteration")?;
                    continue;
                }
                emitir(Mapa::new().con("tipo", "aviso").con(
                    "mensaje",
                    format!("'{}' sigue sin aprobar tras {tope} vueltas; se continúa con lo que hay", nombre.texto_py()),
                ));
            }
            critica_pendiente.clear();
            indice += 1;
        }
        let final_ = orden.last().map(|o| salidas.valor(o).clone()).unwrap_or(Valor::Texto(String::new()));
        let mut usados: Vec<String> = pasos.iter().filter(|p| p.verdad("modelo")).map(|p| p.valor("modelo").texto_py()).collect();
        usados.sort();
        usados.dedup();
        emitir(
            Mapa::new()
                .con("tipo", "fin")
                .con("final", final_)
                .con("salidas", salidas)
                .con("datos", datos_json)
                .con("registro", Valor::Lista(registro))
                .con("segundos", segundos(t_inicio, 1))
                .con("modelos", Valor::Lista(usados.into_iter().map(Valor::Texto).collect())),
        );
        Ok(())
    }
}

/// `_debe_volver`: si el revisor devuelve el trabajo
fn debe_volver(paso: &Mapa, datos: Option<&Valor>) -> bool {
    if !mapa_o(paso.get("si_falla")).verdad("volver_a") {
        return false;
    }
    let Some(Valor::Mapa(d)) = datos else { return false };
    if matches!(d.get("aprobado"), Some(Valor::Bool(false))) {
        return true;
    }
    d.verdad("problemas") || d.verdad("incorrectas")
}

// =========================================================================== sandbox

/// `ejecutar_sandbox_python`: el código (o el bloque ```python que lo envuelve) en un proceso aparte
pub fn sandbox_python(python: &str, codigo: &str) -> Mapa {
    static BLOQUE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"```(?:python)?\s*([\s\S]*?)```").unwrap());
    let puro = match BLOQUE.captures(codigo) {
        Some(c) => py::strip(&c[1]).to_string(),
        None => py::strip(codigo).to_string(),
    };
    let resultado = |exito: bool, stdout: &str, stderr: &str, codigo: i64, s: Valor| {
        Mapa::new().con("exito", exito).con("stdout", stdout).con("stderr", stderr).con("exit_code", codigo).con("segundos", s)
    };
    if puro.is_empty() {
        return resultado(false, "", "No se proporcionó código Python ejecutable.", 1, Valor::Real(0.0));
    }
    let t0 = Instant::now();
    let hijo = std::process::Command::new(python)
        .args(["-c", &puro])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn();
    let mut hijo = match hijo {
        Ok(h) => h,
        Err(e) => {
            let msg = format!("Error del entorno de ejecución: {}", py::error_os(&e, python));
            return resultado(false, "", &msg, -1, Valor::Real(segundos(t0, 2)));
        }
    };
    // la salida se lee en hilos aparte: un proceso que escribe mucho no se bloquea esperando a que alguien lea
    let leer = |r: Option<Box<dyn std::io::Read + Send>>| {
        std::thread::spawn(move || {
            let mut v = Vec::new();
            if let Some(mut r) = r {
                let _ = r.read_to_end(&mut v);
            }
            v
        })
    };
    let h_out = leer(hijo.stdout.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>));
    let h_err = leer(hijo.stderr.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>));
    let limite = std::time::Duration::from_secs(TIMEOUT_SANDBOX);
    let estado = loop {
        match hijo.try_wait() {
            Ok(Some(e)) => break Some(e),
            Ok(None) if t0.elapsed() >= limite => {
                let _ = hijo.kill();
                let _ = hijo.wait();
                break None;
            }
            Ok(None) => std::thread::sleep(std::time::Duration::from_millis(10)),
            Err(_) => break None,
        }
    };
    let Some(estado) = estado else {
        return resultado(
            false,
            "",
            &format!("Error: La ejecución excedió el tiempo límite de {TIMEOUT_SANDBOX} segundos (Timeout)."),
            -1,
            Valor::Entero(TIMEOUT_SANDBOX as i128),
        );
    };
    let dt = segundos(t0, 2);
    let texto = |v: Vec<u8>| String::from_utf8_lossy(&v).replace("\r\n", "\n");
    let stdout = texto(h_out.join().unwrap_or_default());
    let stderr = texto(h_err.join().unwrap_or_default());
    let (stdout, stderr) = (py::strip(&stdout).to_string(), py::strip(&stderr).to_string());
    use std::os::unix::process::ExitStatusExt;
    let codigo = estado.code().map(i64::from).unwrap_or_else(|| -(estado.signal().unwrap_or(0) as i64));
    resultado(codigo == 0 && stderr.is_empty(), &primeros(&stdout, 4000), &primeros(&stderr, 4000), codigo, Valor::Real(dt))
}

// =========================================================================== motor de grafos (v2)

/// `AgentState`: la pizarra que viaja por todos los nodos
struct Estado {
    entrada: String,
    variables: Mapa,
    salidas: Mapa,
    datos: Mapa,
    iteraciones: Mapa,
    criticas: Mapa,
    ruta: Vec<Valor>,
}

impl Estado {
    fn new(entrada: &str, iniciales: Option<&Valor>) -> Estado {
        let mut variables = mapa_o(iniciales);
        variables.poner("entrada", entrada);
        Estado {
            entrada: entrada.to_string(),
            variables,
            salidas: Mapa::new(),
            datos: Mapa::new(),
            iteraciones: Mapa::new(),
            criticas: Mapa::new(),
            ruta: Vec::new(),
        }
    }

    fn iteraciones_de(&self, id: &str) -> i64 {
        self.iteraciones.get(id).and_then(Valor::entero).unwrap_or(0) as i64
    }

    fn anterior(&self) -> Valor {
        self.variables.get("anterior").cloned().unwrap_or(Valor::Texto(String::new()))
    }

    fn registrar(&mut self, id: &str, salida: &str, datos: Option<Valor>) {
        self.salidas.poner(id, salida);
        self.variables.poner(format!("paso:{id}"), salida);
        self.variables.poner("anterior", salida);
        if let Some(d) = datos {
            self.datos.poner(id, d.clone());
            self.variables.poner(format!("datos:{id}"), d);
        }
        self.ruta.push(Valor::Texto(id.to_string()));
        let n = self.iteraciones_de(id) + 1;
        self.iteraciones.poner(id, n);
    }

    fn resumen(&self) -> Mapa {
        Mapa::new()
            .con("entrada_inicial", self.entrada.as_str())
            .con("salidas_nodos", self.salidas.clone())
            .con("datos_nodos", self.datos.clone())
            .con("artefactos", Mapa::new())
            .con("iteraciones", self.iteraciones.clone())
            .con("ruta_ejecucion", Valor::Lista(self.ruta.clone()))
    }

    /// `renderizar_prompt`: {entrada}, {anterior}, {critica}, {paso:id} y las demás variables; la crítica pendiente
    /// se añade si el prompt no la pedía
    fn renderizar(&self, plantilla: &str, nodo_id: &str) -> String {
        static LLAVES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\{([^{}]+)\}").unwrap());
        let critica = self.criticas.get(nodo_id).map(Valor::texto_py).unwrap_or_default();
        let mut r = LLAVES
            .replace_all(plantilla, |c: &regex::Captures| {
                let clave = py::strip(&c[1]);
                if clave == "entrada" {
                    return self.entrada.clone();
                }
                if clave == "anterior" {
                    return self.anterior().texto_py();
                }
                if clave == "critica" {
                    return critica.clone();
                }
                if let Some(pid) = clave.strip_prefix("paso:") {
                    return self.salidas.get(pid).map(Valor::texto_py).unwrap_or_default();
                }
                match self.variables.get(clave) {
                    Some(v @ (Valor::Mapa(_) | Valor::Lista(_))) => json::escribir(v, 2),
                    Some(v) => v.texto_py(),
                    None => c[0].to_string(),
                }
            })
            .into_owned();
        if !critica.is_empty() && !plantilla.contains("{critica}") {
            r += &format!(
                "\n\n---\n⚠️ RETROALIMENTACIÓN DE LA REVISIÓN ANTERIOR:\nTu intento previo fue auditado y se detectaron los \
                 siguientes aspectos a corregir:\n{critica}\nPor favor, genera una nueva versión refinada corrigiendo estos puntos \
                 específicos."
            );
        }
        r
    }
}

/// `_siguiente_secuencial`: el nodo que va después en la lista
fn siguiente_secuencial(nodos: &[Mapa], actual: &Valor) -> Valor {
    match nodos.iter().position(|n| n.valor("id") == actual) {
        Some(i) if i + 1 < nodos.len() => nodos[i + 1].valor("id").clone(),
        _ => Valor::Nulo,
    }
}

/// El siguiente por la arista del nodo o por orden
fn siguiente_de(nodo: &Mapa, nodos: &[Mapa], actual: &Valor) -> Valor {
    match nodo.get("next_node") {
        Some(n) if n.verdad() => n.clone(),
        _ => siguiente_secuencial(nodos, actual),
    }
}

/// La clave de un nodo en el mapa (sus identificadores pueden no ser texto)
fn clave(v: &Valor) -> String {
    json::escribir_linea(v)
}

impl Ejecucion<'_> {
    /// Lo que se pide al modelo para un nodo (`_llamar_modelo_stream`)
    fn pedido_nodo(nodo: &Mapa, prompt: &str) -> Result<PedidoGenerar, String> {
        let rol = match nodo.get("rol") {
            Some(Valor::Texto(r)) => roles_v2().mapa(r),
            _ => None,
        }
        .or_else(|| roles_v2().mapa("analista"))
        .expect("el rol analista");
        let modelo = match nodo.get("modelo") {
            Some(m) if m.verdad() => m.texto_py(),
            _ => "qwen2.5-coder:7b".into(),
        };
        let propio = match (nodo.get("system_prompt"), nodo.get("sistema")) {
            (Some(s), _) if s.verdad() => s.texto_py(),
            (_, Some(s)) if s.verdad() => s.texto_py(),
            _ => String::new(),
        };
        let propio = py::strip(&propio).to_string();
        let sistema = if propio.is_empty() { rol.valor("sistema").texto_py() } else { propio };
        let defecto_t = get_o(nodo, "temperatura", rol.valor("temperatura")).clone();
        let temperatura = float_py(get_o(nodo, "temperature", &defecto_t))?;
        let max_tokens = int_py(get_o(nodo, "max_tokens", &Valor::Entero(1600)))?;
        let pensar = match nodo.get("think") {
            Some(t) => t.clone(),
            None => nodo.valor("pensar").clone(),
        };
        Ok(PedidoGenerar {
            prompt: prompt.to_string(),
            modelo,
            sistema,
            opciones: Some(Mapa::new().con("temperature", temperatura).con("num_predict", Valor::Entero(max_tokens))),
            think: (!pensar.es_nulo()).then(|| pensar.verdad()),
            con_pensamiento: false,
            uso: None,
            gobernador: true,
        })
    }

    /// `DynamicFlowEngine.ejecutar_grafo`: los eventos del grafo en vivo. Error: lo que en Python saltaba fuera.
    pub fn ejecutar_grafo(&self, grafo: &Mapa, entrada: &str, python: &str, emitir: &mut dyn FnMut(Mapa)) -> Result<(), String> {
        let lista = match (grafo.get("nodos"), grafo.get("pasos")) {
            (Some(Valor::Lista(l)), _) if !l.is_empty() => l.clone(),
            (_, Some(Valor::Lista(l))) if !l.is_empty() => l.clone(),
            _ => Vec::new(),
        };
        if lista.is_empty() {
            emitir(Mapa::new().con("tipo", "error").con("mensaje", "El grafo no contiene nodos para ejecutar."));
            return Ok(());
        }
        let mut nodos = Vec::new();
        for n in &lista {
            let Valor::Mapa(n) = n else { return Err("'id'".into()) };
            if !n.contiene("id") {
                return Err("'id'".into());
            }
            nodos.push(n.clone());
        }
        let mut mapa_nodos = std::collections::HashMap::new();
        for n in &nodos {
            mapa_nodos.insert(clave(n.valor("id")), n.clone());
        }
        let nodo_inicial = match grafo.get("nodo_inicial") {
            Some(n) if n.verdad() => n.clone(),
            _ => nodos[0].valor("id").clone(),
        };
        let mut estado = Estado::new(entrada, grafo.get("variables_iniciales"));
        let titulo = match (grafo.get("nombre"), grafo.get("titulo")) {
            (Some(t), _) if t.verdad() => t.clone(),
            (_, Some(t)) if t.verdad() => t.clone(),
            _ => Valor::Texto("Flujo de Agentes".into()),
        };
        emitir(
            Mapa::new()
                .con("tipo", "grafo_inicio")
                .con("titulo", titulo)
                .con("nodos_totales", nodos.len())
                .con("nodo_inicial", nodo_inicial.clone())
                .con("timestamp", py::ahora_iso()),
        );
        let mut actual = nodo_inicial;
        let mut pasos = 0i64;
        let t_inicio = Instant::now();
        while actual.verdad() && pasos < 40 {
            if self.cancelar.puesto() {
                emitir(Mapa::new().con("tipo", "cancelado").con("mensaje", "Ejecución cancelada por el usuario."));
                return Ok(());
            }
            let Some(nodo) = mapa_nodos.get(&clave(&actual)).cloned() else {
                emitir(Mapa::new().con("tipo", "error").con("mensaje", format!("Nodo '{}' no encontrado en el grafo.", actual.texto_py())));
                break;
            };
            let id = actual.texto_py();
            let tipo_nodo = nodo.get("tipo").cloned().unwrap_or(Valor::Texto("agent".into()));
            let es = |t: &str| matches!(&tipo_nodo, Valor::Texto(x) if x == t);
            pasos += 1;
            let iteracion = estado.iteraciones_de(&id) + 1;
            emitir(
                Mapa::new()
                    .con("tipo", "nodo_inicio")
                    .con("id", actual.clone())
                    .con("nombre", if nodo.verdad("nombre") { nodo.valor("nombre").clone() } else { actual.clone() })
                    .con("tipo_nodo", tipo_nodo.clone())
                    .con("rol", nodo.valor("rol").clone())
                    .con("modelo", nodo.valor("modelo").clone())
                    .con("iteracion", iteracion)
                    .con("segundos_acumulados", segundos(t_inicio, 1)),
            );

            // herramienta: ejecutar el código del anterior (o el del nodo)
            if es("tool") || nodo.texto("herramienta") == Some("python_sandbox") {
                let codigo = if nodo.verdad("codigo") { estado.renderizar(&nodo.valor("codigo").texto_py(), &id) } else { estado.anterior().texto_py() };
                emitir(Mapa::new().con("tipo", "tool_inicio").con("id", actual.clone()).con("herramienta", "python_sandbox"));
                let r = sandbox_python(python, &codigo);
                let mut salida = format!(
                    "--- RESULTADO DE EJECUCIÓN (Exit Code: {}, Tiempo: {}s) ---\n",
                    r.valor("exit_code").texto_py(),
                    r.valor("segundos").texto_py()
                );
                let (out, err) = (r.valor("stdout").texto_py(), r.valor("stderr").texto_py());
                if !out.is_empty() {
                    salida += &format!("STDOUT:\n{out}\n");
                }
                if !err.is_empty() {
                    salida += &format!("STDERR / TRACEBACK:\n{err}\n");
                }
                if out.is_empty() && err.is_empty() {
                    salida += "(El proceso finalizó sin salida en consola)\n";
                }
                estado.registrar(&id, &salida, Some(Valor::Mapa(r.clone())));
                emitir(
                    Mapa::new()
                        .con("tipo", "tool_fin")
                        .con("id", actual.clone())
                        .con("exito", r.valor("exito").clone())
                        .con("salida", salida.as_str())
                        .con("detalles", r),
                );
                actual = siguiente_de(&nodo, &nodos, &actual);
                continue;
            }

            // pausa de revisión: nadie la reanuda, así que se espera hasta que se cancele
            if es("checkpoint") {
                let mensaje = if nodo.verdad("mensaje") { nodo.valor("mensaje").clone() } else { Valor::Texto("Pausa para inspección humana del estado.".into()) };
                emitir(
                    Mapa::new()
                        .con("tipo", "checkpoint_pausa")
                        .con("id", actual.clone())
                        .con("mensaje", mensaje)
                        .con("estado_actual", estado.resumen()),
                );
                while !self.cancelar.puesto() {
                    std::thread::sleep(std::time::Duration::from_millis(200));
                }
                emitir(Mapa::new().con("tipo", "cancelado").con("mensaje", "Cancelado durante el checkpoint."));
                return Ok(());
            }

            // agente, supervisor o crítico
            let plantilla = match nodo.get("prompt") {
                None => "{anterior}".to_string(),
                Some(p) => texto_o(Some(p)),
            };
            let prompt = estado.renderizar(&plantilla, &id);
            emitir(Mapa::new().con("tipo", "prompt_listo").con("id", actual.clone()).con("prompt_preview", primeros(&prompt, 400)));
            let mut trozos = String::new();
            match Self::pedido_nodo(&nodo, &prompt) {
                Ok(p) => {
                    let cancelar = self.cancelar;
                    generar::generar(self.raiz, &p, cancelar, &mut |e: Mapa| {
                        if e.texto("t") == Some("texto") && !cancelar.puesto() {
                            let t = e.valor("v").texto_py();
                            trozos.push_str(&t);
                            emitir(Mapa::new().con("tipo", "node_token").con("id", actual.clone()).con("token", t));
                        }
                    });
                }
                Err(e) => {
                    trozos.push_str(&format!("\n[Error en ejecución del modelo: {e}]"));
                    emitir(Mapa::new().con("tipo", "nodo_error").con("id", actual.clone()).con("error", e));
                }
            }
            let limpia = py::strip(&PENSAMIENTO.replace_all(py::strip(&trozos), "")).to_string();
            let datos = extraer_json_seguro(&limpia);
            estado.registrar(&id, &limpia, datos.clone());
            emitir(
                Mapa::new()
                    .con("tipo", "nodo_fin")
                    .con("id", actual.clone())
                    .con("salida", limpia.as_str())
                    .con("datos_json", datos.clone().unwrap_or(Valor::Nulo))
                    .con("iteracion", iteracion),
            );

            let mut siguiente = Valor::Nulo;
            let lazo = match (nodo.get("loop"), nodo.get("si_falla")) {
                (Some(l), _) if l.verdad() => l.clone(),
                (_, Some(l)) if l.verdad() => l.clone(),
                _ => Valor::Nulo,
            };
            if let Valor::Mapa(lazo) = &lazo {
                let destino = match lazo.get("target") {
                    Some(t) if t.verdad() => t.clone(),
                    _ => lazo.valor("volver_a").clone(),
                };
                let defecto = get_o(lazo, "max_vueltas", &Valor::Entero(MAX_RECURSION_DEFECTO as i128)).clone();
                let max_iter = int_py(get_o(lazo, "max_iterations", &defecto))? as i64;
                let dest_id = destino.texto_py();
                let hechas = estado.iteraciones_de(&dest_id);
                let (mut reciclar, mut motivo) = (false, String::new());
                if let Some(Valor::Mapa(d)) = &datos {
                    if matches!(d.get("aprobado"), Some(Valor::Bool(false))) {
                        reciclar = true;
                    } else if d.get("score").is_some_and(|s| !s.es_nulo())
                        && float_py(d.valor("score"))? < float_py(get_o(lazo, "min_score", &Valor::Real(0.8)))?
                    {
                        reciclar = true;
                    } else if d.verdad("problemas") || d.verdad("incorrectas") {
                        reciclar = true;
                    }
                    let problemas = if d.verdad("problemas") {
                        elementos(d.valor("problemas"))
                    } else if d.verdad("incorrectas") {
                        elementos(d.valor("incorrectas"))
                    } else {
                        Vec::new()
                    };
                    let sugs = if d.verdad("sugerencias_mejora") { elementos(d.valor("sugerencias_mejora")) } else { Vec::new() };
                    let m = d.get("motivo").map(Valor::texto_py).unwrap_or_else(|| "Fallas detectadas".into());
                    motivo = format!("Motivo: {m}\n");
                    if !problemas.is_empty() {
                        motivo += &format!("Problemas:\n{}\n", problemas.iter().map(|p| format!("- {}", p.texto_py())).collect::<Vec<_>>().join("\n"));
                    }
                    if !sugs.is_empty() {
                        motivo += &format!("Sugerencias:\n{}", sugs.iter().map(|s| format!("- {}", s.texto_py())).collect::<Vec<_>>().join("\n"));
                    }
                } else if limpia.contains("Traceback") || limpia.contains("Error:") {
                    reciclar = true;
                    motivo = format!("Error de ejecución detectado:\n{}", ultimos(&limpia, 1000));
                }
                if reciclar && hechas < max_iter {
                    estado.criticas.poner(dest_id.clone(), motivo.as_str());
                    emitir(
                        Mapa::new()
                            .con("tipo", "vuelta_recursiva")
                            .con("desde", actual.clone())
                            .con("hacia", destino.clone())
                            .con("vuelta", hechas + 1)
                            .con("max_vueltas", max_iter)
                            .con("motivo", primeros(&motivo, 300)),
                    );
                    siguiente = destino;
                } else {
                    if reciclar {
                        emitir(
                            Mapa::new()
                                .con("tipo", "limite_recursivo_alcanzado")
                                .con("nodo", actual.clone())
                                .con("mensaje", format!("Se alcanzó el límite máximo de {max_iter} iteraciones recursivas; avanzando.")),
                        );
                    }
                    estado.criticas.quitar(&dest_id);
                }
            }
            if !siguiente.verdad() && es("router") {
                if let Some(Valor::Mapa(d)) = &datos {
                    if d.verdad("decision") {
                        let decision = py::strip(&d.valor("decision").texto_py()).to_string();
                        let v = Valor::Texto(decision);
                        if mapa_nodos.contains_key(&clave(&v)) {
                            siguiente = v.clone();
                            emitir(
                                Mapa::new()
                                    .con("tipo", "enrutamiento_dinamico")
                                    .con("supervisor", actual.clone())
                                    .con("destino", v)
                                    .con("razon", d.get("razon").cloned().unwrap_or(Valor::Texto("Decisión del supervisor".into()))),
                            );
                        }
                    }
                }
            }
            if !siguiente.verdad() {
                if let Some(Valor::Lista(reglas)) = nodo.get("routing_rules").filter(|r| r.verdad()) {
                    let aprobado = match &datos {
                        Some(Valor::Mapa(d)) => d.get("aprobado").cloned(),
                        _ => None,
                    };
                    for regla in reglas {
                        let regla = mapa_o(Some(regla));
                        let cond = regla.get("condition").cloned().unwrap_or(Valor::Texto(String::new()));
                        let objetivo = regla.valor("target").clone();
                        if !mapa_nodos.contains_key(&clave(&objetivo)) {
                            continue;
                        }
                        let c = cond.texto_py();
                        let toma = !cond.verdad()
                            || c == "default"
                            || c == "*"
                            || (c == "aprobado" && aprobado == Some(Valor::Bool(true)))
                            || (c == "rechazado" && aprobado == Some(Valor::Bool(false)))
                            || (matches!(cond, Valor::Texto(_)) && limpia.contains(&c));
                        if toma {
                            siguiente = objetivo;
                            break;
                        }
                    }
                }
            }
            if !siguiente.verdad() {
                siguiente = siguiente_de(&nodo, &nodos, &actual);
            }
            actual = siguiente;
        }
        emitir(
            Mapa::new()
                .con("tipo", "grafo_fin")
                .con("resultado_final", estado.anterior())
                .con("resumen_estado", estado.resumen())
                .con("segundos_totales", segundos(t_inicio, 1))
                .con("pasos_totales", pasos),
        );
        Ok(())
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn recorta_por_el_medio() {
        let t: String = "a".repeat(1000) + &"b".repeat(1000);
        let r = recortar(&t, 150, "x");
        assert!(r.starts_with("aaa") && r.ends_with("bbb"));
        assert!(r.contains("[… recortado de x, 1460 caracteres omitidos …]"));
        assert_eq!(recortar("corto", 150, ""), "corto");
    }

    #[test]
    fn json_tolerante() {
        assert_eq!(json_de("hola {\"a\": [1, \"}\"]} fin"), json::leer("{\"a\": [1, \"}\"]}").ok());
        assert_eq!(json_de("sin nada"), None);
        assert_eq!(extraer_json_seguro("<think>x</think>```json\n{\"b\": 2}\n```"), json::leer("{\"b\": 2}").ok());
        assert_eq!(extraer_json_seguro("42"), Some(Valor::Entero(42)));
    }

    #[test]
    fn quita_el_pensamiento() {
        assert_eq!(sin_pensamiento("<think>a</think> hola"), "hola");
        assert_eq!(sin_pensamiento("hola <THINK>sin cerrar"), "hola");
    }

    #[test]
    fn versiones() {
        assert!(version_suficiente("0.11.2", "0.6.6"));
        assert!(!version_suficiente("0.5.7", "0.6.0"));
        assert!(!version_suficiente("?", "0.6.0"));
    }

    #[test]
    fn valida_variables_y_vueltas() {
        let f = |pasos: &str| match json::leer(&format!("{{\"nombre\": \"F\", \"pasos\": {pasos}}}")) {
            Ok(Valor::Mapa(m)) => validar_flujo(&m),
            _ => unreachable!(),
        };
        assert_eq!(f("[]"), vec!["El flujo no tiene ningún paso"]);
        let p = f(r#"[{"id": "a", "rol": "razonar", "modelo": "m", "prompt": "{anterior} {nada} {critica}"}]"#);
        assert_eq!(p.len(), 3);
        assert!(p[0].contains("{nada} no existe"));
        let p = f(r#"[{"id": "a", "rol": "redactar", "modelo": "m", "prompt": "{entrada}"},
                      {"id": "b", "rol": "redactar", "modelo": "m", "prompt": "{paso:a}", "si_falla": {"volver_a": "a"}}]"#);
        assert_eq!(p, vec!["Paso 2 (sin nombre): solo un revisor o un verificador puede devolver el trabajo a un paso anterior"]);
    }

    #[test]
    fn sandbox_de_python() {
        let r = sandbox_python("python3", "```python\nprint(2 + 3)\n```");
        assert_eq!(r.valor("stdout").texto_py(), "5");
        assert!(r.verdad("exito"));
        let r = sandbox_python("python3", "raise ValueError('x')");
        assert!(r.valor("stderr").texto_py().contains("ValueError: x"));
        assert_eq!(r.valor("exit_code"), &Valor::Entero(1));
        assert_eq!(sandbox_python("python3", "  ").valor("stderr").texto_py(), "No se proporcionó código Python ejecutable.");
    }
}
