//! Calibración (backend/recursos/calibracion.py): medir de verdad en la máquina del usuario.
//!
//! La calculadora parte de valores previos. Una prueba corta con un modelo real da los números que los sustituyen:
//! el presupuesto de GPU (cuánto llena Ollama la tarjeta cuando un modelo no cabe), el ancho de GPU (de un modelo
//! que cabe entero) y el de CPU (de uno repartido). Cada prueba es además un CANARIO de extracción: se pide un JSON
//! con citas literales y se comprueba que existen (lo que se estropeó al cuantizar la caché, y no se ve mirando solo
//! la velocidad). Si Ollama revienta por memoria, se reintenta bajando el contexto y después las capas en GPU.
//! Antes de cada prueba se espera a que la GPU se enfríe; si llega al límite, se corta, se enfría y se repite una vez.

use crate::calculadora::{estimar, penalizacion_contexto, Maquina, GB, LATENCIA_CAPA_S};
use crate::ficha::kv_bytes;
use crate::motor_suave::{correr, ejecutable};
use crate::valor::{redondear, Mapa, Valor};
use crate::{http, json};
use std::io::BufRead;
use std::path::Path;
use std::time::Duration;

pub const ESPERA_MAX_S: f64 = 240.0;
pub const MAX_INTENTOS: i64 = 5;
/// Por debajo de esto, la calidad medida no se usa para ordenar modelos
pub const CITAS_MINIMAS: usize = 2;

pub const TEXTO_CANARIO: &str = "La regularización L2 añade a la función de pérdida la suma de los cuadrados de \
los pesos multiplicada por un coeficiente lambda. Cuanto mayor es lambda, más se \
penalizan los pesos grandes y más simple resulta el modelo. A diferencia de la \
regularización L1, la L2 no lleva los pesos exactamente a cero, sino que los \
reduce de forma proporcional. El descenso de gradiente con L2 equivale a \
multiplicar cada peso por un factor ligeramente menor que uno antes de cada \
actualización, lo que se conoce como decaimiento de pesos. En redes profundas, \
el decaimiento de pesos suele combinarse con la normalización por lotes, aunque \
la interacción entre ambas técnicas no es trivial: la normalización hace que la \
escala de los pesos sea irrelevante para la salida, y el decaimiento pasa a \
controlar sobre todo la tasa de aprendizaje efectiva. El abandono aleatorio, o \
dropout, apaga en cada paso una fracción de las neuronas con probabilidad p. \
Durante la inferencia no se apaga ninguna neurona y las activaciones se escalan \
para conservar el valor esperado. La parada temprana detiene el entrenamiento \
cuando el error de validación deja de mejorar durante un número fijo de épocas.";

pub fn prompt_canario() -> String {
    format!(
        "Extrae exactamente 3 afirmaciones del texto. Para cada una da la afirmación resumida y una cita LITERAL, \
         copiada carácter a carácter del texto, de entre 6 y 15 palabras.\n\
         Responde solo con JSON: {{\"afirmaciones\": [{{\"texto\": \"...\", \"cita\": \"...\"}}]}}\n\n\
         TEXTO:\n{TEXTO_CANARIO}"
    )
}

// =========================================================================== canario

/// `str.isspace()` de Python (como `\s` en sus expresiones)
fn espacio(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Sin espacios ni comillas a los lados, en minúsculas y con los espacios seguidos en uno
pub fn normalizar(t: &str) -> String {
    let t = t.trim_matches(espacio).trim_matches(|c| c == '"' || c == '«' || c == '»').to_lowercase();
    let mut s = String::with_capacity(t.len());
    let mut en_espacio = false;
    for c in t.chars() {
        if espacio(c) {
            if !en_espacio {
                s.push(' ');
            }
            en_espacio = true;
        } else {
            s.push(c);
            en_espacio = false;
        }
    }
    s
}

/// `re.findall(r'"cita"\s*:\s*"((?:[^"\\]|\\.)*)"', texto)`
fn citas_en(texto: &str) -> Vec<String> {
    let c: Vec<char> = texto.chars().collect();
    let patron: Vec<char> = "\"cita\"".chars().collect();
    let mut salida = Vec::new();
    let mut i = 0;
    while i + patron.len() <= c.len() {
        if c[i..i + patron.len()] != patron[..] {
            i += 1;
            continue;
        }
        let mut j = i + patron.len();
        while j < c.len() && espacio(c[j]) {
            j += 1;
        }
        if c.get(j) != Some(&':') {
            i += 1;
            continue;
        }
        j += 1;
        while j < c.len() && espacio(c[j]) {
            j += 1;
        }
        if c.get(j) != Some(&'"') {
            i += 1;
            continue;
        }
        j += 1;
        let inicio = j;
        let mut cerrada = None;
        while j < c.len() {
            match c[j] {
                '"' => {
                    cerrada = Some(j);
                    break;
                }
                '\\' if j + 1 < c.len() && c[j + 1] != '\n' => j += 2,
                '\\' => break,
                _ => j += 1,
            }
        }
        match cerrada {
            Some(fin) => {
                salida.push(c[inicio..fin].iter().collect());
                i = fin + 1;
            }
            None => i += 1,
        }
    }
    salida
}

/// 0..1: fracción de citas que están de verdad en el texto. Las citas se sacan también de un JSON cortado (la
/// prueba limita los tokens y en la primera versión todos los modelos puntuaban 0).
pub fn puntuar_canario(respuesta: Option<&str>) -> Mapa {
    let mut json_valido = true;
    let datos = respuesta.and_then(|r| json::leer(r).ok());
    let items = match &datos {
        Some(Valor::Mapa(m)) => match m.get("afirmaciones") {
            Some(Valor::Lista(l)) => Some(l.clone()),
            _ => None,
        },
        _ => None,
    };
    let citas: Vec<String> = match items {
        Some(l) => l
            .iter()
            .filter_map(|i| match i {
                Valor::Mapa(m) => Some(m.get("cita").map(Valor::texto_py).unwrap_or_default()),
                _ => None,
            })
            .collect(),
        None => {
            json_valido = false;
            citas_en(respuesta.unwrap_or(""))
                .into_iter()
                .map(|bruta| match json::leer(&format!("\"{bruta}\"")) {
                    Ok(Valor::Texto(t)) => t,
                    _ => bruta,
                })
                .collect()
        }
    };
    let fuente = normalizar(TEXTO_CANARIO);
    let buenas = citas
        .iter()
        .filter(|c| {
            let n = normalizar(c);
            n.chars().count() >= 15 && fuente.contains(&n)
        })
        .count();
    let calidad = if citas.is_empty() { 0.0 } else { buenas as f64 / citas.len() as f64 };
    Mapa::new()
        .con("json_valido", json_valido)
        .con("citas", citas.len())
        .con("citas_literales", buenas)
        .con("calidad", redondear(calidad, 2))
        .con("fiable", citas.len() >= CITAS_MINIMAS)
}

/// ¿Es un mensaje de falta de memoria de Ollama o llama.cpp?
pub fn es_oom(mensaje: &str) -> bool {
    let m = mensaje.to_lowercase();
    let literales = [
        "out of memory",
        "cudamalloc failed",
        "cuda error",
        "failed to allocate",
        "llama runner process has terminated",
        "llama-server process has terminated",
        "requires more system memory",
        "insufficient memory",
        "unable to allocate",
        "erroroutofdevicememory",
    ];
    if literales.iter().any(|l| m.contains(l)) {
        return true;
    }
    // vk::.*OutOfMemory (en la misma línea)
    m.lines().any(|l| l.find("vk::").is_some_and(|i| l[i + 4..].contains("outofmemory")))
}

// =========================================================================== decisiones

/// `a // b` y `max` de Python sobre enteros o floats
fn medio(v: &Valor) -> Valor {
    match v {
        Valor::Entero(n) => Valor::Entero(n.div_euclid(2)),
        v => Valor::Real((v.num().unwrap_or(f64::NAN) / 2.0).floor()),
    }
}

fn max_valor(a: Valor, b: Valor) -> Valor {
    match (a.num(), b.num()) {
        (Some(x), Some(y)) if y > x => b,
        _ => a,
    }
}

/// El siguiente escalón tras una falta de memoria: primero el contexto (hasta 2048), después las capas en GPU en
/// saltos de un cuarto. Con 0 capas ya no queda nada que quitar a la GPU.
pub fn reducir(ficha: &Mapa, opc: &Mapa) -> Option<Mapa> {
    let mut nueva = opc.clone();
    let ctx = opc.get("num_ctx").cloned().unwrap_or(Valor::Entero(4096));
    if ctx.num().unwrap_or(f64::NAN) > 2048.0 {
        nueva.poner("num_ctx", max_valor(Valor::Entero(2048), medio(&ctx)));
        return Some(nueva);
    }
    let capas = match ficha.get("capas") {
        Some(v) if v.verdad() => v.entero().unwrap_or(32),
        _ => 32,
    } + 1;
    let actual = opc.get("num_gpu").cloned().unwrap_or(Valor::Entero(capas));
    if actual.num().unwrap_or(f64::NAN) <= 0.0 {
        return None;
    }
    let paso = (capas.div_euclid(4)).max(1);
    let nuevo = match actual {
        Valor::Entero(a) => Valor::Entero((a - paso).max(0)),
        v => Valor::Real((v.num().unwrap_or(0.0) - paso as f64).max(0.0)),
    };
    nueva.poner("num_gpu", nuevo);
    Some(nueva)
}

fn max_py(a: f64, b: f64) -> f64 {
    if b > a {
        b
    } else {
        a
    }
}

/// Despeja lo que la prueba permite saber. Devuelve solo lo medido.
pub fn deducir(ficha: &Mapa, r: &Mapa, maq: &Maquina) -> Mapa {
    let mut datos = Mapa::new();
    if !r.verdad("ok") || !r.verdad("tok_s") || !r.verdad("total_gb") {
        return datos;
    }
    let opciones = r.mapa("opciones").cloned().unwrap_or_default();
    if opciones.contiene("num_gpu") {
        return datos; // capas forzadas por una recuperación: no es el reparto automático
    }
    let ctx = opciones.num_o("num_ctx", f64::NAN);
    let peso = ficha.num_o("bytes_peso", f64::NAN);
    let activos = peso * ficha.num_o("fraccion_activa", 1.0) / GB;
    // Segundos por token que se van en leer pesos (sin el coste fijo por capa)
    let mut t = 1.0 / (r.num_o("tok_s", f64::NAN) * penalizacion_contexto(ctx));
    let capas = match ficha.get("capas") {
        Some(v) if v.verdad() => v.num().unwrap_or(32.0),
        _ => 32.0,
    };
    t = max_py(t * 0.2, t - capas * LATENCIA_CAPA_S);
    let frac = match r.get("fraccion_gpu") {
        Some(v) if v.verdad() => v.num().unwrap_or(0.0),
        _ => 0.0,
    };
    let total = r.num_o("total_gb", f64::NAN) * GB;
    let cache = kv_bytes(ficha, ctx as i64, 1, "f16") as f64;
    let base = peso + cache;
    if !maq.hay_gpu || frac <= 0.02 {
        datos.poner("ancho_cpu", redondear(activos / t, 1));
        return datos;
    }
    if frac >= 0.99 {
        datos.poner("ancho_gpu", redondear(activos / t, 1));
        datos.poner("overhead_entero", total - base);
        datos.poner("presupuesto_minimo", total); // cabe entero: el presupuesto es al menos esto
        return datos;
    }
    datos.poner("vram_parcial", frac * total);
    datos.poner("presupuesto_gpu", frac * total + 0.1 * GB);
    datos.poner("overhead_parcial", total - base);
    let resto = t - frac * activos / maq.ancho_gpu;
    if resto > 0.0 {
        let ancho_cpu = (1.0 - frac) * activos / resto;
        if (3.0..=400.0).contains(&ancho_cpu) {
            datos.poner("ancho_cpu", redondear(ancho_cpu, 1)); // fuera de esto la medida es ruido
        }
    }
    datos
}

/// `statistics.median`: el del medio, o la media de los dos del medio
fn mediana(vs: &[Valor]) -> Valor {
    let mut v: Vec<&Valor> = vs.iter().collect();
    v.sort_by(|a, b| a.num().partial_cmp(&b.num()).unwrap_or(std::cmp::Ordering::Equal));
    let n = v.len();
    if n % 2 == 1 {
        v[n / 2].clone()
    } else {
        Valor::Real((v[n / 2 - 1].num().unwrap_or(f64::NAN) + v[n / 2].num().unwrap_or(f64::NAN)) / 2.0)
    }
}

/// Mediana de todas las muestras de cada parámetro, las viejas incluidas (las 9 últimas)
pub fn combinar(previa: Option<&Mapa>, nuevas: &[Mapa]) -> Mapa {
    let mut muestras: Vec<(String, Vec<Valor>)> = previa
        .and_then(|p| p.mapa("muestras"))
        .map(|m| m.iter().map(|(k, v)| (k.clone(), match v { Valor::Lista(l) => l.clone(), _ => Vec::new() })).collect())
        .unwrap_or_default();
    for n in nuevas {
        for (k, v) in n.iter() {
            if matches!(v, Valor::Entero(_) | Valor::Real(_) | Valor::Bool(_)) {
                let x = Valor::Real(v.num().unwrap_or(f64::NAN));
                match muestras.iter_mut().find(|(c, _)| c == k) {
                    Some((_, l)) => l.push(x),
                    None => muestras.push((k.clone(), vec![x])),
                }
            }
        }
    }
    let mut valores = Mapa::new();
    for (k, vs) in muestras.iter_mut() {
        let desde = vs.len().saturating_sub(9);
        *vs = vs[desde..].to_vec();
        valores.poner(k.clone(), mediana(vs));
    }
    // El presupuesto nunca por debajo de lo que se vio caber entero
    if valores.contiene("presupuesto_minimo") {
        let lista = &muestras.iter().find(|(k, _)| k == "presupuesto_minimo").map(|(_, l)| l.clone()).unwrap_or_default();
        let minimo = lista.iter().cloned().reduce(max_valor).unwrap_or(Valor::Nulo);
        if valores.num_o("presupuesto_gpu", 0.0) < minimo.num().unwrap_or(f64::NAN) {
            valores.poner("presupuesto_gpu", minimo.clone());
            if !valores.contiene("vram_parcial") {
                valores.poner("vram_parcial", minimo.num().unwrap_or(f64::NAN) - 0.1 * GB);
            }
        }
        valores.quitar("presupuesto_minimo");
    }
    let m = muestras.into_iter().fold(Mapa::new(), |m, (k, l)| m.con(k, Valor::Lista(l)));
    valores.poner("muestras", m);
    valores
}

/// Dos modelos instalados que den información distinta: uno que quepa entero (mide la GPU) y uno que se reparta (mide
/// el presupuesto y la RAM). De cada clase el más pequeño que sirva; sin GPU, uno pequeño basta.
pub fn elegir_modelos_prueba(fichas: &[Mapa], maq: &Maquina) -> Vec<Mapa> {
    let mut candidatos: Vec<&Mapa> =
        fichas.iter().filter(|f| !f.verdad("embedding") && !f.verdad("estimada") && f.verdad("bytes_peso")).collect();
    candidatos.sort_by(|a, b| a.num_o("bytes_peso", 0.0).partial_cmp(&b.num_o("bytes_peso", 0.0)).unwrap_or(std::cmp::Ordering::Equal));
    if !maq.hay_gpu {
        return candidatos.into_iter().take(1).cloned().collect();
    }
    let (mut enteros, mut repartidos) = (Vec::new(), Vec::new());
    for f in &candidatos {
        let e = estimar(f, maq, 4096, 1, "f16");
        if e.riesgo_swap {
            continue;
        }
        if e.donde == "gpu" {
            enteros.push(*f);
        } else if e.donde == "repartido" && (0.25..=0.9).contains(&e.fraccion_gpu) {
            repartidos.push(*f);
        }
    }
    // Para medir la GPU conviene el más grande que cabe: menos ruido fijo por token
    let mut elegidos: Vec<Mapa> = enteros.last().map(|f| (*f).clone()).into_iter().collect();
    elegidos.extend(repartidos.first().map(|f| (*f).clone()));
    if elegidos.is_empty() {
        return candidatos.into_iter().take(1).cloned().collect();
    }
    elegidos
}

// =========================================================================== Ollama y GPU

/// VRAM usada, temperatura y consumo de la GPU por nvidia-smi (None sin nvidia-smi o si algo no cuadra)
pub fn estado_gpu() -> Option<Mapa> {
    ejecutable("nvidia-smi")?;
    let args: Vec<String> = ["--query-gpu=memory.used,temperature.gpu,power.draw", "--format=csv,noheader,nounits"]
        .iter()
        .map(|s| s.to_string())
        .collect();
    let (_, salida, _) = correr(Path::new("nvidia-smi"), &args, Duration::from_secs(5)).ok()?;
    let primera = salida.lines().next()?;
    let p: Vec<&str> = primera.split(',').map(str::trim).collect();
    if p.len() != 3 {
        return None;
    }
    let real = crate::valor::real_de_texto;
    let consumo = if !p[2].is_empty() && p[2].replace('.', "").chars().all(|c| c.is_ascii_digit()) { real(p[2]) } else { None };
    Some(Mapa::new().con("vram_mb", real(p[0])?).con("temp_c", real(p[1])?).con("consumo_w", consumo))
}

/// Cómo terminó una generación en streaming
pub enum FinGenerar {
    Hecho(Mapa),
    /// La GPU llegó al límite: se cortó la conexión (eso detiene la generación)
    PorCalor,
    /// El error de Ollama (o de la conexión), con su mensaje
    Error(String),
}

/// Un error HTTP de Ollama: su campo «error» si lo trae
fn detalle_http(r: reqwest::blocking::Response) -> String {
    let codigo = r.status().as_u16();
    let texto = r.text().unwrap_or_default();
    match json::leer(&texto) {
        Ok(Valor::Mapa(m)) if m.verdad("error") => m.valor("error").texto_py(),
        _ => format!("HTTP Error {codigo}"),
    }
}

/// Genera en streaming para poder cortar si la GPU llega al límite (`parar` se mira tras cada trozo). Devuelve el
/// último mensaje (el que trae las estadísticas) con la respuesta entera.
pub fn generar_stream(url: &str, cuerpo: &Mapa, mut parar: impl FnMut() -> bool, segundos: f64) -> FinGenerar {
    let cuerpo = cuerpo.clone().con("stream", true);
    let cliente = match reqwest::blocking::Client::builder().timeout(Duration::from_secs_f64(segundos)).build() {
        Ok(c) => c,
        Err(e) => return FinGenerar::Error(e.to_string()),
    };
    let r = match cliente
        .post(format!("{url}/api/generate"))
        .header("Content-Type", "application/json")
        .body(json::escribir_compacto(&Valor::Mapa(cuerpo)))
        .send()
    {
        Ok(r) => r,
        Err(e) => return FinGenerar::Error(e.to_string()),
    };
    if !r.status().is_success() {
        return FinGenerar::Error(detalle_http(r));
    }
    let mut texto = String::new();
    for linea in std::io::BufReader::new(r).lines() {
        let linea = match linea {
            Ok(l) => l,
            Err(e) => return FinGenerar::Error(e.to_string()),
        };
        if linea.trim().is_empty() {
            continue;
        }
        let d = match json::leer(&linea) {
            Ok(Valor::Mapa(d)) => d,
            Ok(_) => return FinGenerar::Error("respuesta de Ollama inesperada".into()),
            Err(e) => return FinGenerar::Error(e),
        };
        if d.verdad("error") {
            return FinGenerar::Error(d.valor("error").texto_py());
        }
        texto.push_str(&d.get("response").map(Valor::texto_py).unwrap_or_default());
        if d.verdad("done") {
            return FinGenerar::Hecho(d.con("response", texto));
        }
        if parar() {
            return FinGenerar::PorCalor;
        }
    }
    FinGenerar::Error("Ollama cerró la respuesta sin terminar".into())
}

/// El modelo cargado en Ollama con ese nombre (de /api/ps)
pub fn ps(url: &str, modelo: &str) -> Option<Mapa> {
    let Ok(Valor::Mapa(r)) = http::get_json_ok(&format!("{url}/api/ps"), 5.0) else { return None };
    r.lista("models")?.iter().find_map(|m| match m {
        Valor::Mapa(m) if m.texto("name") == Some(modelo) || m.texto("model") == Some(modelo) => Some(m.clone()),
        _ => None,
    })
}

/// Descarga el modelo de la memoria (keep_alive 0); los fallos no importan
pub fn descargar(url: &str, modelo: &str) {
    let cuerpo = Mapa::new().con("model", modelo).con("keep_alive", 0);
    let _ = http::post_json(&format!("{url}/api/generate"), &Valor::Mapa(cuerpo), 30.0);
}

// =========================================================================== una prueba

/// Lo de fuera de una prueba: Ollama, la GPU, el reloj, los avisos, el gobernador. `Error` es el de quien lo
/// implementa (en Python, la excepción, incluida «Cancelado»): se propaga.
pub trait MundoPrueba {
    type Error;
    fn cancelado(&mut self) -> Result<bool, Self::Error>;
    /// Error «Cancelado»
    fn cancelar(&mut self) -> Self::Error;
    /// Espera `s` segundos o hasta que se cancele (true si se canceló)
    fn esperar(&mut self, s: f64) -> Result<bool, Self::Error>;
    fn dormir(&mut self, s: f64) -> Result<(), Self::Error>;
    fn ahora(&mut self) -> Result<f64, Self::Error>;
    fn estado_gpu(&mut self) -> Result<Option<Mapa>, Self::Error>;
    fn reanudar(&mut self) -> Result<f64, Self::Error>;
    fn limite(&mut self) -> Result<f64, Self::Error>;
    fn avisar(&mut self, evento: Mapa) -> Result<(), Self::Error>;
    /// Empieza a muestrear la GPU (pico de VRAM y temperatura, y si llegó al límite)
    fn muestreo_empezar(&mut self, limite: f64) -> Result<(), Self::Error>;
    /// Para el muestreo: (VRAM pico en MB, temperatura máxima)
    fn muestreo_terminar(&mut self) -> Result<(f64, f64), Self::Error>;
    fn generar(&mut self, cuerpo: &Mapa) -> Result<FinGenerar, Self::Error>;
    fn ps(&mut self, modelo: &str) -> Result<Option<Mapa>, Self::Error>;
    fn descargar(&mut self, modelo: &str) -> Result<(), Self::Error>;
    /// El error del motor explicado para el usuario (o el mismo)
    fn explicar(&mut self, error: &str) -> Result<String, Self::Error>;
}

/// Espera a que la GPU baje de `tope` (la de reanudar del gobernador si es None). false si no baja a tiempo.
pub fn esperar_temperatura<M: MundoPrueba>(mundo: &mut M, tope: Option<f64>, espera_max: f64) -> Result<bool, M::Error> {
    let tope = match tope {
        Some(t) => t,
        None => mundo.reanudar()?,
    };
    let inicio = mundo.ahora()?;
    let mut avisado = false;
    loop {
        let Some(e) = mundo.estado_gpu()? else { return Ok(true) };
        let temp = e.num_o("temp_c", f64::NAN);
        if temp <= tope {
            return Ok(true);
        }
        if !avisado {
            mundo.avisar(
                Mapa::new().con("tipo", "enfriando").con("temp_c", e.valor("temp_c").clone()).con(
                    "mensaje",
                    format!(
                        "La GPU está a {} °C; espero a que baje de {} °C antes de probar.",
                        crate::valor::fijo(temp, 0),
                        crate::valor::repr_real(tope)
                    ),
                ),
            )?;
            avisado = true;
        }
        if mundo.ahora()? - inicio > espera_max {
            return Ok(false);
        }
        if mundo.esperar(5.0)? {
            return Err(mundo.cancelar());
        }
    }
}

fn fallo(modelo: &Valor, opc: &Mapa, intentos: &[Valor], error: String) -> Mapa {
    Mapa::new()
        .con("ok", false)
        .con("modelo", modelo.clone())
        .con("opciones", opc.clone())
        .con("intentos", intentos.to_vec())
        .con("error", error)
}

fn primeros(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

/// Carga el modelo con estas opciones, genera el canario y mide. Si revienta por memoria, reintenta con menos
/// contexto y después menos capas; si la GPU llega al límite, enfría y repite una vez.
pub fn probar<M: MundoPrueba>(
    ficha: &Mapa,
    opciones: &Mapa,
    mundo: &mut M,
    num_predict: i64,
    dejar_cargado: bool,
) -> Result<Mapa, M::Error> {
    let modelo = ficha.valor("nombre").clone();
    let nombre = modelo.texto_py();
    let mut opc = Mapa::new();
    for (k, v) in opciones.iter() {
        if k == "num_ctx" || k == "num_gpu" {
            opc.poner(k.clone(), v.clone());
        }
    }
    if !opc.contiene("num_ctx") {
        opc.poner("num_ctx", 4096);
    }
    let think = opciones.get("think").cloned();
    let mut intentos: Vec<Valor> = Vec::new();
    let mut reintentos_calor = 0;

    for n in 1..=MAX_INTENTOS {
        if mundo.cancelado()? {
            return Err(mundo.cancelar());
        }
        if !esperar_temperatura(mundo, None, ESPERA_MAX_S)? {
            return Ok(fallo(&modelo, &opc, &intentos, "La GPU no se enfrió a tiempo; prueba cancelada por calor.".into()));
        }
        let capas = opc.get("num_gpu").map(|v| format!(" y {} capas en GPU", v.texto_py())).unwrap_or_default();
        mundo.avisar(
            Mapa::new()
                .con("tipo", "intento")
                .con("n", n)
                .con("modelo", modelo.clone())
                .con("opciones", opc.clone())
                .con("mensaje", format!("Probando {nombre} con {} tokens de contexto{capas}…", opc.valor("num_ctx").texto_py())),
        )?;
        let mut cuerpo = Mapa::new()
            .con("model", modelo.clone())
            .con("prompt", prompt_canario())
            .con("stream", false)
            .con("format", "json")
            .con("keep_alive", "2m")
            .con("options", opc.clone().con("num_predict", num_predict).con("temperature", 0));
        if ficha.verdad("piensa") {
            cuerpo.poner("think", think.as_ref().filter(|t| !t.es_nulo()).map(Valor::verdad).unwrap_or(false));
        }
        let limite = mundo.limite()?;
        mundo.muestreo_empezar(limite)?;
        let t0 = mundo.ahora()?;
        let fin = mundo.generar(&cuerpo);
        let (vram_pico, temp_max) = mundo.muestreo_terminar()?;
        let fin = fin?;
        let pared = mundo.ahora()? - t0;

        let d = match fin {
            FinGenerar::PorCalor => {
                // Cortar la conexión ya detuvo la generación: enfriar y repetir una vez
                if reintentos_calor >= 1 {
                    mundo.descargar(&nombre)?;
                    return Ok(Mapa::new()
                        .con("ok", false)
                        .con("modelo", modelo.clone())
                        .con("opciones", opc.clone())
                        .con("intentos", intentos.clone())
                        .con("temp_max_c", temp_max)
                        .con(
                            "error",
                            format!(
                                "La GPU volvió a llegar a {} °C; prueba cortada. Prueba con un modelo más pequeño.",
                                crate::valor::fijo(temp_max, 0)
                            ),
                        ));
                }
                reintentos_calor += 1;
                mundo.avisar(Mapa::new().con("tipo", "enfriando").con("temp_c", temp_max).con(
                    "mensaje",
                    format!("La GPU llegó a {} °C: prueba cortada; se repite al enfriar.", crate::valor::fijo(temp_max, 0)),
                ))?;
                continue;
            }
            FinGenerar::Error(e) => {
                let explicado = mundo.explicar(&e)?;
                let error = if explicado.is_empty() { e } else { explicado };
                let oom = es_oom(&error);
                intentos.push(Mapa::new().con("opciones", opc.clone()).con("error", primeros(&error, 300)).con("oom", oom).into());
                mundo.avisar(Mapa::new().con("tipo", "fallo").con("n", n).con("oom", oom).con("mensaje", primeros(&error, 300)))?;
                if !oom {
                    return Ok(fallo(&modelo, &opc, &intentos, primeros(&error, 500)));
                }
                let Some(siguiente) = reducir(ficha, &opc) else {
                    return Ok(fallo(&modelo, &opc, &intentos, "No cabe ni con el mínimo de contexto y capas en GPU.".into()));
                };
                mundo.descargar(&nombre)?;
                mundo.dormir(2.0)?;
                opc = siguiente;
                continue;
            }
            FinGenerar::Hecho(d) => d,
        };

        let cargado = mundo.ps(&nombre)?.unwrap_or_default();
        if !dejar_cargado {
            mundo.descargar(&nombre)?;
        }
        let tam = match cargado.get("size") {
            Some(v) if v.verdad() => v.num().unwrap_or(0.0),
            _ => 0.0,
        };
        let en_vram = match cargado.get("size_vram") {
            Some(v) if v.verdad() => v.num().unwrap_or(0.0),
            _ => 0.0,
        };
        let gen_s = max_py(d.num_o("eval_duration", 0.0) / 1e9, 1e-6);
        let pre_s = max_py(d.num_o("prompt_eval_duration", 0.0) / 1e9, 1e-6);
        let con_tam = |v: f64| if tam != 0.0 { Valor::Real(v) } else { Valor::Nulo };
        let canario = puntuar_canario(Some(&d.get("response").map(Valor::texto_py).unwrap_or_default()));
        let calidad = if canario.verdad("fiable") { canario.valor("calidad").clone() } else { Valor::Nulo };
        let resultado = Mapa::new()
            .con("ok", true)
            .con("modelo", modelo.clone())
            .con("opciones", opc.clone())
            .con("tok_s", redondear(d.num_o("eval_count", 0.0) / gen_s, 1))
            .con("prefill_tok_s", redondear(d.num_o("prompt_eval_count", 0.0) / pre_s, 1))
            .con("carga_s", redondear(d.num_o("load_duration", 0.0) / 1e9, 1))
            .con("tokens_generados", d.get("eval_count").cloned().unwrap_or(Valor::Entero(0)))
            .con("tokens_prompt", d.get("prompt_eval_count").cloned().unwrap_or(Valor::Entero(0)))
            .con("total_gb", con_tam(redondear(tam / GB, 2)))
            .con("vram_gb", con_tam(redondear(en_vram / GB, 2)))
            .con("fraccion_gpu", con_tam(redondear(en_vram / tam, 3)))
            .con("vram_pico_mb", if vram_pico != 0.0 { Valor::Real(vram_pico) } else { Valor::Nulo })
            .con("temp_max_c", if temp_max != 0.0 { Valor::Real(temp_max) } else { Valor::Nulo })
            .con("segundos", redondear(pared, 1))
            .con("canario", canario)
            .con("intentos", intentos.clone())
            .con("recuperado_de_oom", !intentos.is_empty())
            // Sin citas suficientes la calidad no se sabe: None, no 0 (un 0 hundiría al modelo en el ranking)
            .con("calidad", calidad);
        let mut medido = Mapa::new().con("tipo", "medido");
        for k in ["modelo", "tok_s", "prefill_tok_s", "total_gb", "fraccion_gpu", "calidad"] {
            medido.poner(k, resultado.valor(k).clone());
        }
        mundo.avisar(medido)?;
        return Ok(resultado);
    }
    Ok(fallo(&modelo, &opc, &intentos, "Demasiados intentos fallidos.".into()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canario() {
        let buena = "Cuanto mayor es lambda, más se penalizan los pesos grandes";
        let mala = "La regularización L2 siempre lleva los pesos exactamente a cero";
        let r = puntuar_canario(Some(&format!(
            "{{\"afirmaciones\": [{{\"texto\": \"x\", \"cita\": \"{buena}\"}}, {{\"texto\": \"y\", \"cita\": \"{mala}\"}}]}}"
        )));
        assert_eq!((r.valor("citas"), r.valor("citas_literales"), r.valor("calidad")), (&Valor::Entero(2), &Valor::Entero(1), &Valor::Real(0.5)));
        let cortado = "{\"afirmaciones\": [{\"texto\": \"a\", \"cita\": \"Cuanto mayor es lambda, más se penalizan los pesos grandes\"}, \
                       {\"texto\": \"b\", \"cita\": \"La parada temprana detiene el entrenamiento\"}, {\"texto\": \"c\", \"cita\": \"Durante la infer";
        let r = puntuar_canario(Some(cortado));
        assert!(!r.verdad("json_valido"));
        assert_eq!(r.valor("citas_literales"), &Valor::Entero(2));
        assert!(r.verdad("fiable"));
    }

    #[test]
    fn oom() {
        assert!(es_oom("llama runner process has terminated: cudaMalloc failed: out of memory"));
        assert!(es_oom("vk::Queue::submit: ErrorOutOfDeviceMemory"));
        assert!(es_oom("algo vk::x y OutOfMemory"));
        assert!(!es_oom("model 'x' not found"));
    }

    #[test]
    fn reducir_termina() {
        let ficha = Mapa::new().con("capas", 28);
        let mut opc = Some(Mapa::new().con("num_ctx", 8192));
        let mut pasos = 0;
        while let Some(o) = opc {
            opc = reducir(&ficha, &o);
            pasos += 1;
            assert!(pasos < 20);
        }
    }
}
