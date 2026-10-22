//! Las piezas de `ai_engine/motor_moe.py` que trabajan por petición y por token: traducir una petición de Ollama
//! (/api/chat, /api/generate) a /v1/chat/completions de llama-server, leer su flujo SSE y devolverlo como los objetos
//! NDJSON de Ollama, y las estimaciones (tokens, contexto, expertos calientes, tamaños del GGUF).
//!
//! El cuerpo que recibe llama-server tiene que ser el mismo que armaba Python, con las claves en el mismo orden:
//! la plantilla del modelo lo convierte en el prompt, y las lecturas guardadas dependen de él carácter por carácter.

use prig_plataforma::py::{self, ErrorPy};
use prig_recursos::json;
use prig_recursos::valor::{Mapa, Valor};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read};
use std::sync::{Mutex, OnceLock};

pub const NOMBRE: &str = "qwen3.6-35b-moe:prig";
pub const SOLO_CODIGO: &str = "prig_solo_codigo";
pub const PERFIL: &str = "prig_perfil";
pub const CARACTERES_POR_TOKEN: f64 = 3.0;
pub const PROYECTO_MIN_CARACTERES: usize = 12000;
pub const MAX_CALIENTES: i64 = 56;
pub const MB_POR_CALIENTE: f64 = 68.65;
pub const MARGEN_MB: f64 = 250.0;
pub const RESERVA_CUDA_MB: f64 = 370.0;
pub const CONTEXTO_MAX: i64 = 262144;
pub const CONTEXTO_INICIAL: i64 = 32768;

/// contexto: (lote, MB sin MTP, MB con MTP; None = MTP no cabe)
pub const CONTEXTOS: [(i64, i64, i64, Option<i64>); 6] = [
    (8192, 2048, 1714, Some(2491)),
    (16384, 2048, 1803, Some(2580)),
    (32768, 2048, 1981, Some(2758)),
    (65536, 2048, 2689, Some(3367)),
    (131072, 2048, 3739, Some(4799)),
    (262144, 1024, 5305, None),
];

/// Las opciones de Ollama que pasan tal cual, en este orden
pub const OPCIONES: [&str; 11] = [
    "temperature", "top_k", "top_p", "min_p", "typical_p", "repeat_penalty", "repeat_last_n", "presence_penalty",
    "frequency_penalty", "seed", "stop",
];

pub const GRAMATICA_CODIGO: &str = include_str!("gramatica_codigo.gbnf");
pub const INSTRUCCION_SOLO_CODIGO: &str = include_str!("instruccion_solo_codigo.txt");

/// Perfiles de muestreo (los recomendados por Qwen para Qwen3.6; «preciso» para lo que se ciñe a datos)
pub fn muestreo(perfil: &str) -> Option<Mapa> {
    let (t, p, k) = match perfil {
        "razonar" => (0.6, 0.95, 20),
        "charla" => (0.7, 0.8, 20),
        "codigo" => (0.6, 0.95, 20),
        "preciso" => (0.3, 0.9, 20),
        _ => return None,
    };
    Some(Mapa::new().con("temperature", t).con("top_p", p).con("top_k", k).con("min_p", 0.0))
}

type R<T> = Result<T, ErrorPy>;

fn get(v: &Valor, k: &str) -> Valor {
    match v {
        Valor::Mapa(m) => m.valor(k).clone(),
        _ => Valor::Nulo,
    }
}

fn get_py(v: &Valor, k: &str) -> R<Valor> {
    py::get(v, k, Valor::Nulo).map_err(ErrorPy::Atributo)
}

fn o_vacio(v: Valor) -> Valor {
    if v.verdad() {
        v
    } else {
        Valor::Mapa(Mapa::new())
    }
}

fn o_texto_vacio(v: Valor) -> Valor {
    if v.verdad() {
        v
    } else {
        Valor::Texto(String::new())
    }
}

fn iterar(v: &Valor) -> R<Vec<Valor>> {
    if !v.verdad() {
        return Ok(vec![]);
    }
    py::iterar(v).map_err(ErrorPy::Tipo)
}

/// `int(v)` de Python
fn int_py(v: &Valor) -> R<i128> {
    match v {
        Valor::Bool(b) => Ok(*b as i128),
        Valor::Entero(n) => Ok(*n),
        Valor::Real(x) if x.is_finite() => Ok(x.trunc() as i128),
        Valor::Real(_) => Err(ErrorPy::Desborde("cannot convert float infinity to integer".into())),
        Valor::Texto(t) => prig_recursos::valor::entero_de_texto(t)
            .ok_or_else(|| ErrorPy::Valor(format!("invalid literal for int() with base 10: {}", Valor::Texto(t.clone()).repr_py()))),
        otro => Err(ErrorPy::Tipo(format!(
            "int() argument must be a string, a bytes-like object or a real number, not '{}'",
            py::tipo(otro)
        ))),
    }
}

/// `float(v)` de Python
fn float_py(v: &Valor) -> R<f64> {
    match v {
        Valor::Texto(t) => prig_recursos::valor::real_de_texto(t)
            .ok_or_else(|| ErrorPy::Valor(format!("could not convert string to float: {}", Valor::Texto(t.clone()).repr_py()))),
        otro => otro.num().ok_or_else(|| {
            ErrorPy::Tipo(format!("float() argument must be a string or a real number, not '{}'", py::tipo(otro)))
        }),
    }
}

fn largo(v: &Valor) -> usize {
    v.texto_py().chars().count()
}

// =========================================================================== estimaciones

/// `estimar_tokens(pedido)`: lo que se lee (por caracteres, prudente) más lo que se puede generar
pub fn estimar_tokens(pedido: &Valor) -> R<i128> {
    let mut caracteres = largo(&o_texto_vacio(get_py(pedido, "prompt")?)) + largo(&o_texto_vacio(get_py(pedido, "system")?));
    for m in iterar(&get_py(pedido, "messages")?)? {
        caracteres += largo(&o_texto_vacio(get_py(&m, "content")?)) + largo(&o_texto_vacio(get_py(&m, "thinking")?));
        let llamadas = get_py(&m, "tool_calls")?;
        if llamadas.verdad() {
            caracteres += json::escribir_linea(&llamadas).chars().count();
        }
    }
    let herramientas = get_py(pedido, "tools")?;
    if herramientas.verdad() {
        caracteres += json::escribir_linea(&herramientas).chars().count();
    }
    let opciones = o_vacio(get_py(pedido, "options")?);
    let np = get_py(&opciones, "num_predict")?;
    let tope = if np.verdad() { int_py(&np)? } else { 0 };
    Ok((caracteres as f64 / CARACTERES_POR_TOKEN) as i128 + if tope > 0 { tope } else { 4096 } + 512)
}

/// `prefijo_de(cuerpo)`: los mensajes hasta el primero del usuario, si es grande y la conversación sigue
pub fn prefijo_de(cuerpo: &Valor) -> R<Option<Vec<Valor>>> {
    let mensajes = iterar(&get_py(cuerpo, "messages")?)?;
    for (i, m) in mensajes.iter().enumerate() {
        if get_py(m, "role")? == Valor::Texto("user".into()) {
            if i == mensajes.len() - 1 || largo(&o_texto_vacio(get_py(m, "content")?)) < PROYECTO_MIN_CARACTERES {
                return Ok(None);
            }
            return Ok(Some(mensajes[..=i].to_vec()));
        }
    }
    Ok(None)
}

/// `lista_caliente(uso, global_)`: por capa, los expertos del más al menos usado; los empates siguen la global
pub fn lista_caliente(uso: &[Vec<i64>], global: &[Vec<i64>]) -> Option<Vec<Vec<i64>>> {
    if uso.is_empty() || !uso.iter().any(|c| c.iter().any(|x| *x != 0)) {
        return None;
    }
    let mut lista = Vec::with_capacity(uso.len());
    for (i, cuenta) in uso.iter().enumerate() {
        let mut orden: HashMap<i64, usize> = HashMap::new();
        if let Some(g) = global.get(i) {
            for (n, e) in g.iter().enumerate() {
                orden.insert(*e, n);
            }
        }
        let mut idx: Vec<i64> = (0..cuenta.len() as i64).collect();
        idx.sort_by_key(|e| (-cuenta[*e as usize], *orden.get(e).unwrap_or(&cuenta.len())));
        lista.push(idx);
    }
    Some(lista)
}

/// `contexto_para(tokens)`: el menor contexto de la tabla (desde el inicial) que los admite
pub fn contexto_para(tokens: i128) -> Option<i64> {
    CONTEXTOS.iter().map(|c| c.0).find(|&c| c >= CONTEXTO_INICIAL && c as i128 >= tokens)
}

fn fila(contexto: i64) -> (i64, i64, i64, Option<i64>) {
    *CONTEXTOS.iter().find(|c| c.0 >= contexto).unwrap_or(&CONTEXTOS[5])
}

pub fn lote_para(contexto: i64) -> i64 {
    fila(contexto).1
}

/// `base_mb(contexto, mtp)`: VRAM sin expertos calientes (None si con MTP no cabe)
pub fn base_mb(contexto: i64, mtp: bool) -> Option<f64> {
    let (_, _, sin, con) = fila(contexto);
    if mtp {
        con.map(|x| x as f64)
    } else {
        Some(sin as f64)
    }
}

pub fn cabe_mtp(libre: Option<f64>, contexto: i64) -> bool {
    match base_mb(contexto, true) {
        None => false,
        Some(b) => libre.is_none_or(|l| l - RESERVA_CUDA_MB - MARGEN_MB >= b),
    }
}

/// `calientes_para(...)`: cuántos expertos calientes por capa caben en la VRAM libre
pub fn calientes_para(libre: Option<f64>, contexto: i64, mtp: bool, mb_caliente: f64, extra_mb: f64) -> i64 {
    let Some(base) = base_mb(contexto, mtp) else { return 0 };
    let Some(libre) = libre.filter(|l| *l != 0.0) else { return 0 };
    let n = ((libre - RESERVA_CUDA_MB - base - extra_mb - MARGEN_MB) / mb_caliente).floor() as i64;
    n.clamp(0, MAX_CALIENTES)
}

/// `segundos_keep_alive(valor)`: 300, "5m", "1h", "30s", 0 (descargar ya), negativo (no descargar)
pub fn segundos_keep_alive(valor: &Valor, defecto: f64) -> f64 {
    match valor {
        Valor::Nulo => defecto,
        Valor::Texto(t) if t.is_empty() => defecto,
        Valor::Entero(_) | Valor::Real(_) | Valor::Bool(_) => valor.num().unwrap_or(defecto),
        otro => {
            let t = py::strip(&otro.texto_py()).to_lowercase();
            for (sufijo, factor) in [("ms", 0.001), ("h", 3600.0), ("m", 60.0), ("s", 1.0)] {
                if let Some(n) = t.strip_suffix(sufijo) {
                    return prig_recursos::valor::real_de_texto(n).map(|x| x * factor).unwrap_or(defecto);
                }
            }
            prig_recursos::valor::real_de_texto(&t).unwrap_or(defecto)
        }
    }
}

// =========================================================================== el GGUF

static TAMANOS: OnceLock<Mutex<HashMap<String, (i64, i64)>>> = OnceLock::new();

/// (bytes de un experto por capa en las 40 capas, bytes del núcleo en la GPU) según los tipos del GGUF
pub fn tamanos_gguf(gguf: &str) -> (i64, i64) {
    if gguf.is_empty() {
        return (0, 0);
    }
    let cache = TAMANOS.get_or_init(|| Mutex::new(HashMap::new()));
    if let Some(t) = cache.lock().unwrap().get(gguf) {
        return *t;
    }
    let t = leer_tamanos(gguf).unwrap_or((0, 0));
    cache.lock().unwrap().insert(gguf.to_string(), t);
    t
}

fn leer_tamanos(gguf: &str) -> Option<(i64, i64)> {
    let mut f = BufReader::new(std::fs::File::open(gguf).ok()?);
    let mut leer = |n: usize| -> Option<Vec<u8>> {
        let mut b = vec![0u8; n];
        f.read_exact(&mut b).ok()?;
        Some(b)
    };
    if leer(4)? != b"GGUF" {
        return None;
    }
    let u32_ = |b: Vec<u8>| u32::from_le_bytes(b.try_into().unwrap());
    let u64_ = |b: Vec<u8>| u64::from_le_bytes(b.try_into().unwrap());
    let _version = u32_(leer(4)?);
    let n_t = u64_(leer(8)?);
    let n_kv = u64_(leer(8)?);
    let tam = |t: u32| -> Option<usize> {
        Some(match t {
            0 | 1 | 7 => 1,
            2 | 3 => 2,
            4..=6 => 4,
            10..=12 => 8,
            _ => return None,
        })
    };
    let texto = |leer: &mut dyn FnMut(usize) -> Option<Vec<u8>>| -> Option<String> {
        let n = u64::from_le_bytes(leer(8)?.try_into().ok()?) as usize;
        Some(String::from_utf8_lossy(&leer(n)?).into_owned())
    };
    for _ in 0..n_kv {
        texto(&mut leer)?;
        let t = u32_(leer(4)?);
        if t == 8 {
            texto(&mut leer)?;
        } else if t == 9 {
            let et = u32_(leer(4)?);
            let n = u64_(leer(8)?);
            if et == 8 {
                for _ in 0..n {
                    texto(&mut leer)?;
                }
            } else {
                leer(tam(et)? * n as usize)?;
            }
        } else {
            leer(tam(t)?)?;
        }
    }
    let bloques = |tipo: u32| -> Option<(u64, u64)> {
        Some(match tipo {
            0 => (1, 4),
            1 => (1, 2),
            8 => (32, 34),
            10 => (256, 84),
            11 => (256, 110),
            12 => (256, 144),
            13 => (256, 176),
            14 => (256, 210),
            23 => (256, 136),
            30 => (1, 2),
            _ => return None,
        })
    };
    let (mut expertos, mut nucleo) = (0i64, 0i64);
    for _ in 0..n_t {
        let nombre = texto(&mut leer)?;
        let dims = u32_(leer(4)?);
        let mut ne = Vec::with_capacity(dims as usize);
        for _ in 0..dims {
            ne.push(u64_(leer(8)?));
        }
        let tipo = u32_(leer(4)?);
        let _offset = u64_(leer(8)?);
        let (e, b) = bloques(tipo)?;
        let elementos: u64 = ne.iter().product();
        let bytes = (elementos / e * b) as i64;
        if nombre.contains("_exps.") {
            let capa: i64 = nombre.split('.').nth(1)?.parse().ok()?;
            if capa < 40 && ne.len() == 3 {
                expertos += bytes / ne[2] as i64;
            }
        } else if nombre != "token_embd.weight" {
            nucleo += bytes;
        }
    }
    Some((expertos, nucleo))
}

// =========================================================================== Ollama → OpenAI

/// `_mensajes`: razonamiento, llamadas a herramientas (argumentos como texto, con id) y resultados (tool_name →
/// tool_call_id de la llamada correspondiente)
pub fn mensajes_openai(mensajes: &[Valor]) -> R<Vec<Valor>> {
    let mut salida = Vec::with_capacity(mensajes.len());
    let mut pendientes: Vec<(Valor, Valor)> = Vec::new();
    let mut n = 0;
    for m in mensajes {
        let rol = get_py(m, "role")?;
        let mut nuevo = Mapa::new().con("role", rol.clone()).con("content", o_texto_vacio(get_py(m, "content")?));
        if rol == Valor::Texto("assistant".into()) {
            let pensado = get_py(m, "thinking")?;
            if pensado.verdad() {
                nuevo.poner("reasoning_content", pensado);
            }
            let mut llamadas = Vec::new();
            for llamada in iterar(&get_py(m, "tool_calls")?)? {
                let funcion = o_vacio(get_py(&llamada, "function")?);
                let argumentos = get_py(&funcion, "arguments")?;
                let argumentos = match argumentos {
                    Valor::Texto(_) => argumentos,
                    otro => Valor::Texto(json::escribir_linea(&o_vacio(otro))),
                };
                n += 1;
                let id = get_py(&llamada, "id")?;
                let id = if id.verdad() { id } else { Valor::Texto(format!("llamada_{n}")) };
                let nombre = match &funcion {
                    Valor::Mapa(f) if f.contiene("name") => f.valor("name").clone(),
                    _ => Valor::Texto(String::new()),
                };
                llamadas.push(Valor::Mapa(
                    Mapa::new().con("id", id.clone()).con("type", "function").con(
                        "function",
                        Mapa::new().con("name", nombre.clone()).con("arguments", argumentos),
                    ),
                ));
                pendientes.push((id, nombre));
            }
            if !llamadas.is_empty() {
                nuevo.poner("tool_calls", Valor::Lista(llamadas));
            }
        } else if rol == Valor::Texto("tool".into()) {
            let mut nombre = get_py(m, "tool_name")?;
            if !nombre.verdad() {
                nombre = get_py(m, "name")?;
            }
            let nombre = o_texto_vacio(nombre);
            let indice = pendientes.iter().position(|(_, nom)| *nom == nombre).or(if pendientes.is_empty() { None } else { Some(0) });
            let id = get_py(m, "tool_call_id")?;
            if id.verdad() {
                nuevo.poner("tool_call_id", id);
            } else if let Some(i) = indice {
                nuevo.poner("tool_call_id", pendientes.remove(i).0);
            }
        }
        salida.push(Valor::Mapa(nuevo));
    }
    Ok(salida)
}

/// `muestreo_para(pedido)`: el perfil pedido o el que corresponde al uso
pub fn muestreo_para(pedido: &Valor) -> R<Mapa> {
    let perfil = get_py(pedido, PERFIL)?;
    if let Valor::Texto(p) = &perfil {
        if let Some(m) = muestreo(p) {
            return Ok(m);
        }
    }
    let p = if get_py(pedido, SOLO_CODIGO)?.verdad() {
        "codigo"
    } else if get_py(pedido, "format")?.verdad() {
        "preciso"
    } else if get_py(pedido, "think")?.verdad() {
        "razonar"
    } else {
        "charla"
    };
    Ok(muestreo(p).unwrap())
}

/// `a_openai(ruta, pedido)`: el cuerpo para /v1/chat/completions y los prefijos que llama-server repetirá al
/// continuar un mensaje del asistente (hay que quitarlos de la respuesta)
pub fn a_openai(ruta: &str, pedido: &Valor) -> R<(Mapa, Mapa)> {
    let mensajes: Vec<Valor> = if ruta.ends_with("/api/generate") {
        let mut m = Vec::new();
        let sistema = get_py(pedido, "system")?;
        if sistema.verdad() {
            m.push(Valor::Mapa(Mapa::new().con("role", "system").con("content", sistema)));
        }
        m.push(Valor::Mapa(Mapa::new().con("role", "user").con("content", o_texto_vacio(get_py(pedido, "prompt")?))));
        m
    } else {
        iterar(&get_py(pedido, "messages")?)?
    };
    let stream = match pedido {
        Valor::Mapa(p) => !matches!(p.get("stream"), Some(Valor::Bool(false))),
        _ => true,
    };
    let mut cuerpo = Mapa::new().con("messages", Valor::Lista(mensajes_openai(&mensajes)?)).con("stream", stream);
    let opciones = o_vacio(get_py(pedido, "options")?);
    for de in OPCIONES {
        let v = get_py(&opciones, de)?;
        if !v.es_nulo() {
            cuerpo.poner(de, v);
        }
    }
    let tope = get_py(&opciones, "num_predict")?;
    if !tope.es_nulo() && int_py(&tope)? > 0 {
        cuerpo.poner("max_tokens", Valor::Entero(int_py(&tope)?));
    }
    cuerpo.poner("chat_template_kwargs", Mapa::new().con("enable_thinking", get_py(pedido, "think")?.verdad()));
    for (k, v) in muestreo_para(pedido)?.iter() {
        if !cuerpo.contiene(k) {
            cuerpo.poner(k.clone(), v.clone());
        }
    }
    if get_py(pedido, SOLO_CODIGO)?.verdad() {
        cuerpo.poner("chat_template_kwargs", Mapa::new().con("enable_thinking", false));
        cuerpo.poner("grammar", GRAMATICA_CODIGO);
    }
    let formato = get_py(pedido, "format")?;
    if formato == Valor::Texto("json".into()) {
        cuerpo.poner("response_format", Mapa::new().con("type", "json_object"));
    } else if let Valor::Mapa(_) = &formato {
        cuerpo.poner(
            "response_format",
            Mapa::new().con("type", "json_schema").con("json_schema", Mapa::new().con("name", "respuesta").con("schema", formato.clone())),
        );
    }
    let herramientas = get_py(pedido, "tools")?;
    if herramientas.verdad() {
        cuerpo.poner("tools", herramientas);
    }
    if get_py(pedido, "logprobs")?.verdad() {
        cuerpo.poner("logprobs", true);
        let top = get_py(pedido, "top_logprobs")?;
        if top.verdad() {
            cuerpo.poner("top_logprobs", Valor::Entero(int_py(&top)?));
        }
    }
    let mut prefijos = Mapa::new().con("content", "").con("thinking", "");
    if let Some(ultimo) = mensajes.last() {
        if get_py(ultimo, "role")? == Valor::Texto("assistant".into()) {
            prefijos = Mapa::new()
                .con("content", o_texto_vacio(get_py(ultimo, "content")?))
                .con("thinking", o_texto_vacio(get_py(ultimo, "thinking")?));
        }
    }
    Ok((cuerpo, prefijos))
}

// =========================================================================== OpenAI → Ollama

/// `_Prefijo`: quita de la respuesta el texto que ya tenía el mensaje del asistente que se continúa
pub struct Prefijo {
    resto: String,
}

impl Prefijo {
    pub fn new(t: &str) -> Prefijo {
        Prefijo { resto: t.to_string() }
    }

    pub fn filtrar(&mut self, trozo: &str) -> String {
        if self.resto.is_empty() || trozo.is_empty() {
            return trozo.to_string();
        }
        if let Some(r) = trozo.strip_prefix(self.resto.as_str()) {
            let r = r.to_string();
            self.resto.clear();
            return r;
        }
        if let Some(r) = self.resto.strip_prefix(trozo) {
            self.resto = r.to_string();
            return String::new();
        }
        self.resto.clear();
        trozo.to_string()
    }
}

/// `_final(...)`: el último objeto, con las métricas de Ollama
pub fn final_(ruta: &str, motivo: Option<&str>, timings: &Valor, carga_s: f64, llamadas: Vec<Valor>, contexto: Option<i64>, proyecto: &Valor) -> R<Mapa> {
    let ms = |v: Valor| -> R<i128> {
        let x = if v.verdad() { float_py(&v)? } else { 0.0 };
        Ok((x * 1e6) as i128)
    };
    let entero = |v: Valor| -> R<i128> { if v.verdad() { int_py(&v) } else { Ok(0) } };
    let mut prompt_n = entero(get(timings, "prompt_n"))?;
    let mut prompt_ms = ms(get(timings, "prompt_ms"))?;
    let eval_ms = ms(get(timings, "predicted_ms"))?;
    let carga = (carga_s * 1e9) as i128;
    let mut datos = Mapa::new()
        .con("model", NOMBRE)
        .con("done", true)
        .con("done_reason", if motivo == Some("length") { "length" } else { "stop" })
        .con("prompt_eval_count", prompt_n)
        .con("prompt_eval_duration", prompt_ms)
        .con("eval_count", entero(get(timings, "predicted_n"))?)
        .con("eval_duration", eval_ms)
        .con("load_duration", carga);
    if proyecto.verdad() {
        let l = get(proyecto, "leidos");
        prompt_n += if l.verdad() { int_py(&l)? } else { 0 };
        let lm = get(proyecto, "lectura_ms");
        prompt_ms += ((if lm.verdad() { float_py(&lm)? } else { 0.0 }) * 1e6) as i128;
        datos.poner("prompt_eval_count", prompt_n);
        datos.poner("prompt_eval_duration", prompt_ms);
        datos.poner("proyecto", proyecto.clone());
    }
    datos.poner("total_duration", prompt_ms + eval_ms + carga);
    if let Some(c) = contexto.filter(|c| *c != 0) {
        datos.poner("contexto", c);
    }
    if ruta.ends_with("/api/generate") {
        datos.poner("response", "");
    } else {
        let mut mensaje = Mapa::new().con("role", "assistant").con("content", "");
        if !llamadas.is_empty() {
            mensaje.poner("tool_calls", Valor::Lista(llamadas));
        }
        datos.poner("message", mensaje);
    }
    Ok(datos)
}

/// Una llamada a herramienta que llega por partes
#[derive(Clone)]
pub struct Parcial {
    id: Valor,
    nombre: Option<Valor>,
    argumentos: Option<Valor>,
}

impl Default for Parcial {
    fn default() -> Parcial {
        Parcial { id: Valor::Nulo, nombre: None, argumentos: None }
    }
}

/// `_llamadas(parciales)`: los argumentos como JSON (o `{"_texto": ...}` si no lo son)
pub fn llamadas(parciales: &std::collections::BTreeMap<i128, Parcial>) -> Vec<Valor> {
    parciales
        .values()
        .map(|p| {
            let texto = p.argumentos.clone().unwrap_or(Valor::Nulo);
            let crudo = if texto.verdad() { texto.texto_py() } else { "{}".into() };
            let argumentos = json::leer(&crudo).unwrap_or_else(|_| Valor::Mapa(Mapa::new().con("_texto", texto.clone())));
            Valor::Mapa(
                Mapa::new().con("id", p.id.clone()).con(
                    "function",
                    Mapa::new().con("name", p.nombre.clone().unwrap_or(Valor::Texto(String::new()))).con("arguments", argumentos),
                ),
            )
        })
        .collect()
}

/// `_logprobs(eleccion)`
pub fn logprobs(eleccion: &Valor) -> R<Vec<Valor>> {
    let mut salida = Vec::new();
    for c in iterar(&get_py(&o_vacio(get_py(eleccion, "logprobs")?), "content")?)? {
        let mut top = Vec::new();
        for a in iterar(&get_py(&c, "top_logprobs")?)? {
            top.push(Valor::Mapa(Mapa::new().con("token", get_py(&a, "token")?).con("logprob", get_py(&a, "logprob")?)));
        }
        salida.push(Valor::Mapa(
            Mapa::new().con("token", get_py(&c, "token")?).con("logprob", get_py(&c, "logprob")?).con("top_logprobs", Valor::Lista(top)),
        ));
    }
    Ok(salida)
}

/// `a_ollama(...)`, por línea: el traductor del flujo SSE de llama-server a los objetos NDJSON de Ollama
pub struct Traductor {
    generar: bool,
    ruta: String,
    texto: Prefijo,
    razonamiento: Prefijo,
    parciales: std::collections::BTreeMap<i128, Parcial>,
    motivo: Option<String>,
    timings: Valor,
    carga_s: f64,
    contexto: Option<i64>,
    proyecto: Valor,
    terminado: bool,
}

impl Traductor {
    pub fn new(ruta: &str, prefijos: &Mapa, carga_s: f64, contexto: Option<i64>, proyecto: Valor) -> Traductor {
        Traductor {
            generar: ruta.ends_with("/api/generate"),
            ruta: ruta.to_string(),
            texto: Prefijo::new(prefijos.texto("content").unwrap_or("")),
            razonamiento: Prefijo::new(prefijos.texto("thinking").unwrap_or("")),
            parciales: Default::default(),
            motivo: None,
            timings: Valor::Mapa(Mapa::new()),
            carga_s,
            contexto,
            proyecto,
            terminado: false,
        }
    }

    /// Los objetos que salen de una línea del flujo (ninguno, uno, o el error que termina). `Fin` si era [DONE].
    pub fn linea(&mut self, linea: &str, salida: &mut Vec<Valor>) -> R<bool> {
        let Some(dato) = linea.strip_prefix("data:") else { return Ok(false) };
        let dato = py::strip(dato);
        if dato == "[DONE]" {
            return Ok(true);
        }
        let Ok(trozo) = json::leer(dato) else { return Ok(false) };
        let error = get_py(&trozo, "error")?;
        if error.verdad() {
            let texto = match &error {
                Valor::Mapa(m) => m.valor("message").clone(),
                otro => Valor::Texto(otro.texto_py()),
            };
            salida.push(Valor::Mapa(Mapa::new().con("error", texto)));
            self.terminado = true;
            return Ok(true);
        }
        let t = get_py(&trozo, "timings")?;
        if t.verdad() {
            self.timings = t;
        }
        for eleccion in iterar(&get_py(&trozo, "choices")?)? {
            let delta = o_vacio(get_py(&eleccion, "delta")?);
            let fr = get_py(&eleccion, "finish_reason")?;
            if fr.verdad() {
                self.motivo = Some(fr.texto_py());
            }
            for llamada in iterar(&get_py(&delta, "tool_calls")?)? {
                let indice = match &llamada {
                    Valor::Mapa(m) if m.contiene("index") => int_py(m.valor("index"))?,
                    _ => 0,
                };
                let p = self.parciales.entry(indice).or_default();
                let id = get_py(&llamada, "id")?;
                if id.verdad() {
                    p.id = id;
                }
                let funcion = o_vacio(get_py(&llamada, "function")?);
                let nombre = get_py(&funcion, "name")?;
                if nombre.verdad() {
                    p.nombre = Some(nombre);
                }
                let args = o_texto_vacio(get_py(&funcion, "arguments")?);
                let previo = p.argumentos.clone().map(|a| a.texto_py()).unwrap_or_default();
                p.argumentos = Some(Valor::Texto(format!("{previo}{}", args.texto_py())));
            }
            let pensado = self.razonamiento.filtrar(&o_texto_vacio(get_py(&delta, "reasoning_content")?).texto_py());
            let escrito = self.texto.filtrar(&o_texto_vacio(get_py(&delta, "content")?).texto_py());
            let probabilidades = logprobs(&eleccion)?;
            if pensado.is_empty() && escrito.is_empty() && probabilidades.is_empty() {
                continue;
            }
            let mut objeto = if self.generar {
                let mut s = Mapa::new().con("model", NOMBRE).con("response", escrito).con("done", false);
                if !pensado.is_empty() {
                    s.poner("thinking", pensado);
                }
                s
            } else {
                let mut mensaje = Mapa::new().con("role", "assistant").con("content", escrito);
                if !pensado.is_empty() {
                    mensaje.poner("thinking", pensado);
                }
                Mapa::new().con("model", NOMBRE).con("message", mensaje).con("done", false)
            };
            if !probabilidades.is_empty() {
                objeto.poner("logprobs", Valor::Lista(probabilidades));
            }
            salida.push(Valor::Mapa(objeto));
        }
        Ok(false)
    }

    /// El objeto final (salvo si terminó con un error)
    pub fn cerrar(&mut self) -> R<Option<Valor>> {
        if self.terminado {
            return Ok(None);
        }
        self.terminado = true;
        let ll = llamadas(&self.parciales);
        Ok(Some(Valor::Mapa(final_(&self.ruta, self.motivo.as_deref(), &self.timings, self.carga_s, ll, self.contexto, &self.proyecto)?)))
    }
}

/// `a_ollama_completo(...)`: una respuesta sin streaming de llama-server → la de Ollama
pub fn a_ollama_completo(ruta: &str, respuesta: &Valor, prefijos: &Mapa, carga_s: f64, contexto: Option<i64>, proyecto: &Valor) -> R<Mapa> {
    let choices = get_py(respuesta, "choices")?;
    let eleccion = if choices.verdad() {
        match &choices {
            Valor::Lista(l) => l[0].clone(),
            otro => py::iterar(otro).map_err(ErrorPy::Tipo)?.into_iter().next().unwrap_or(Valor::Nulo),
        }
    } else {
        Valor::Mapa(Mapa::new())
    };
    let mensaje = o_vacio(get_py(&eleccion, "message")?);
    let texto = Prefijo::new(prefijos.texto("content").unwrap_or("")).filtrar(&o_texto_vacio(get_py(&mensaje, "content")?).texto_py());
    let pensado =
        Prefijo::new(prefijos.texto("thinking").unwrap_or("")).filtrar(&o_texto_vacio(get_py(&mensaje, "reasoning_content")?).texto_py());
    let mut parciales = std::collections::BTreeMap::new();
    for (i, c) in iterar(&get_py(&mensaje, "tool_calls")?)?.into_iter().enumerate() {
        let f = o_vacio(get_py(&c, "function")?);
        parciales.insert(i as i128, Parcial { id: get_py(&c, "id")?, nombre: Some(get_py(&f, "name")?).filter(|v| !v.es_nulo()), argumentos: Some(get_py(&f, "arguments")?) });
    }
    // `_llamadas` usa p.get("nombre", ""): un nombre None queda None
    let ll: Vec<Valor> = llamadas(&parciales)
        .into_iter()
        .zip(parciales.values())
        .map(|(mut v, p)| {
            if p.nombre.is_none() {
                if let Valor::Mapa(m) = &mut v {
                    if let Some(Valor::Mapa(f)) = m.get_mut("function") {
                        f.poner("name", Valor::Nulo);
                    }
                }
            }
            v
        })
        .collect();
    let fr = get_py(&eleccion, "finish_reason")?;
    let fr_t = if fr.verdad() { Some(fr.texto_py()) } else { None };
    let timings = o_vacio(get_py(respuesta, "timings")?);
    let mut datos = final_(ruta, fr_t.as_deref(), &timings, carga_s, ll, contexto, proyecto)?;
    if ruta.ends_with("/api/generate") {
        datos.poner("response", texto);
        if !pensado.is_empty() {
            datos.poner("thinking", pensado);
        }
    } else if let Some(Valor::Mapa(m)) = datos.get_mut("message") {
        m.poner("content", texto);
        if !pensado.is_empty() {
            m.poner("thinking", pensado);
        }
    }
    if get_py(&eleccion, "logprobs")?.verdad() {
        datos.poner("logprobs", Valor::Lista(logprobs(&eleccion)?));
    }
    Ok(datos)
}

// =========================================================================== el flujo

/// Lo que respondió llama-server a /v1/chat/completions: el flujo (si fue 200 y en streaming), o el estado y el
/// cuerpo
pub enum Respuesta {
    Flujo(Box<dyn BufRead + Send>),
    Entera(u16, Vec<u8>),
}

/// Manda el cuerpo a llama-server (el JSON con el escritor de `requests`, claves en su orden)
pub fn pedir(url: &str, cuerpo: &Mapa, stream: bool, timeout: f64) -> Result<Respuesta, String> {
    let c = reqwest::blocking::Client::builder()
        .connect_timeout(std::time::Duration::from_secs_f64(timeout.min(30.0)))
        .timeout(if stream { None } else { Some(std::time::Duration::from_secs_f64(timeout)) })
        .build()
        .map_err(|e| e.to_string())?;
    let r = c
        .post(url)
        .header("Content-Type", "application/json")
        .body(json::escribir_compacto(&Valor::Mapa(cuerpo.clone())))
        .send()
        .map_err(|e| e.to_string())?;
    let estado = r.status().as_u16();
    if estado == 200 && stream {
        return Ok(Respuesta::Flujo(Box::new(BufReader::new(r))));
    }
    let b = r.bytes().map_err(|e| e.to_string())?.to_vec();
    Ok(Respuesta::Entera(estado, b))
}

/// El flujo de un /api/chat o /api/generate servido por el motor: lee el SSE de llama-server en su propio hilo
/// (cerrarlo corta la conexión, y llama-server deja de generar) y lo entrega traducido
pub struct Flujo {
    rx: Mutex<std::sync::mpsc::Receiver<Result<Vec<Valor>, String>>>,
    cerrado: std::sync::Arc<std::sync::atomic::AtomicBool>,
    pendientes: Mutex<std::collections::VecDeque<Valor>>,
    fin: std::sync::atomic::AtomicBool,
}

impl Flujo {
    pub fn new(mut lector: Box<dyn BufRead + Send>, mut traductor: Traductor) -> Flujo {
        let (tx, rx) = std::sync::mpsc::channel();
        let cerrado = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let c = cerrado.clone();
        std::thread::Builder::new()
            .name("moe-flujo".into())
            .spawn(move || {
                let mut b = Vec::new();
                loop {
                    if c.load(std::sync::atomic::Ordering::SeqCst) {
                        return; // al soltar el lector se cierra la conexión
                    }
                    b.clear();
                    match lector.read_until(b'\n', &mut b) {
                        Ok(0) | Err(_) => break,
                        Ok(_) => {}
                    }
                    // `iter_lines` de requests: sin el salto, y bytes no válidos como U+FFFD
                    while matches!(b.last(), Some(b'\n' | b'\r')) {
                        b.pop();
                    }
                    let linea = String::from_utf8_lossy(&b);
                    let mut salida = Vec::new();
                    match traductor.linea(&linea, &mut salida) {
                        Ok(fin) => {
                            if !salida.is_empty() && tx.send(Ok(salida)).is_err() {
                                return;
                            }
                            if fin {
                                break;
                            }
                        }
                        Err(e) => {
                            let _ = tx.send(Err(e.texto()));
                            return;
                        }
                    }
                }
                match traductor.cerrar() {
                    Ok(Some(f)) => {
                        let _ = tx.send(Ok(vec![f]));
                    }
                    Ok(None) => {}
                    Err(e) => {
                        let _ = tx.send(Err(e.texto()));
                    }
                }
            })
            .expect("hilo del flujo");
        Flujo { rx: Mutex::new(rx), cerrado, pendientes: Mutex::new(Default::default()), fin: Default::default() }
    }

    /// El siguiente objeto de Ollama (None al terminar o si se cerró)
    pub fn siguiente(&self) -> Result<Option<Valor>, String> {
        use std::sync::atomic::Ordering;
        if let Some(v) = self.pendientes.lock().unwrap().pop_front() {
            return Ok(Some(v));
        }
        if self.fin.load(Ordering::SeqCst) || self.cerrado.load(Ordering::SeqCst) {
            return Ok(None);
        }
        let r = self.rx.lock().unwrap().recv();
        match r {
            Ok(Ok(mut lote)) => {
                if self.cerrado.load(Ordering::SeqCst) {
                    return Ok(None);
                }
                let primero = lote.remove(0);
                self.pendientes.lock().unwrap().extend(lote);
                Ok(Some(primero))
            }
            Ok(Err(e)) => {
                self.fin.store(true, Ordering::SeqCst);
                Err(e)
            }
            Err(_) => {
                self.fin.store(true, Ordering::SeqCst);
                Ok(None)
            }
        }
    }

    /// Corta: el hilo suelta la conexión en cuanto llega el siguiente trozo
    pub fn cerrar(&self) {
        self.cerrado.store(true, std::sync::atomic::Ordering::SeqCst);
    }
}

#[cfg(test)]
mod pruebas {
    //! Las de la traducción Ollama ↔ llama-server (antes en backend/tests/test_motor_moe.py, contra esta misma
    //! traducción por PyO3)
    use super::*;

    fn j(t: &str) -> Valor {
        json::leer(t).unwrap()
    }
    fn c(v: &Valor) -> String {
        json::escribir_compacto(v)
    }
    fn openai(ruta: &str, pedido: &str) -> (Mapa, Mapa) {
        a_openai(ruta, &j(pedido)).unwrap()
    }

    fn sse(trozos: &[&str], timings: Option<&str>, motivo: &str) -> Vec<String> {
        let mut l: Vec<String> =
            trozos.iter().map(|t| format!("data: {{\"choices\": [{{\"index\": 0, \"finish_reason\": null, \"delta\": {t}}}]}}")).collect();
        let t = timings.map(|t| format!(", \"timings\": {t}")).unwrap_or_default();
        l.push(format!("data: {{\"choices\": [{{\"index\": 0, \"finish_reason\": \"{motivo}\", \"delta\": {{}}}}]{t}}}"));
        l.push("data: [DONE]".into());
        l
    }

    fn ollama(ruta: &str, lineas: &[String], prefijos: &str, carga_s: f64) -> Vec<Mapa> {
        let Valor::Mapa(p) = j(prefijos) else { panic!() };
        let mut t = Traductor::new(ruta, &p, carga_s, None, Valor::Nulo);
        let mut salida = Vec::new();
        for l in lineas {
            if t.linea(l, &mut salida).unwrap() {
                break;
            }
        }
        if let Some(f) = t.cerrar().unwrap() {
            salida.push(f);
        }
        salida.into_iter().map(|v| if let Valor::Mapa(m) = v { m } else { panic!() }).collect()
    }

    #[test]
    fn chat_opciones_y_think() {
        let (cuerpo, prefijos) = openai(
            "http://x/api/chat",
            r#"{"model": "qwen3.6-35b-moe:prig", "stream": true, "think": false, "format": "json",
                "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                "options": {"temperature": 0.2, "top_k": 20, "num_predict": 300, "num_ctx": 8192, "num_thread": 4, "stop": ["</fin>"]}}"#,
        );
        assert_eq!(c(cuerpo.valor("messages")), r#"[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]"#);
        assert_eq!(cuerpo.num("temperature"), Some(0.2));
        assert_eq!(cuerpo.num("top_k"), Some(20.0));
        assert_eq!(cuerpo.num("max_tokens"), Some(300.0));
        assert_eq!(c(cuerpo.valor("stop")), r#"["</fin>"]"#);
        assert!(!cuerpo.contiene("num_ctx"));
        assert_eq!(c(cuerpo.valor("chat_template_kwargs")), r#"{"enable_thinking": false}"#);
        assert_eq!(c(cuerpo.valor("response_format")), r#"{"type": "json_object"}"#);
        assert!(cuerpo.verdad("stream"));
        assert_eq!(c(&Valor::Mapa(prefijos)), r#"{"content": "", "thinking": ""}"#);
    }

    #[test]
    fn generate_y_esquema() {
        let (cuerpo, _) = openai(
            "http://x/api/generate",
            r#"{"prompt": "p", "system": "s", "stream": false, "format": {"type": "object", "properties": {"a": {"type": "integer"}}}, "options": {"num_predict": -1}}"#,
        );
        assert_eq!(c(cuerpo.valor("messages")), r#"[{"role": "system", "content": "s"}, {"role": "user", "content": "p"}]"#);
        assert!(!cuerpo.verdad("stream"));
        assert!(!cuerpo.contiene("max_tokens"));
        assert_eq!(c(cuerpo.mapa("response_format").unwrap().mapa("json_schema").unwrap().valor("schema")), r#"{"type": "object", "properties": {"a": {"type": "integer"}}}"#);
        assert_eq!(c(cuerpo.valor("chat_template_kwargs")), r#"{"enable_thinking": false}"#);
        let (cuerpo, _) = openai("http://x/api/generate", r#"{"prompt": "p", "think": true}"#);
        assert_eq!(c(cuerpo.valor("chat_template_kwargs")), r#"{"enable_thinking": true}"#);
    }

    #[test]
    fn solo_codigo() {
        let (cuerpo, _) = openai("http://x/api/chat", r#"{"messages": [{"role": "user", "content": "una función"}], "think": true, "prig_solo_codigo": true}"#);
        assert_eq!(c(cuerpo.valor("chat_template_kwargs")), r#"{"enable_thinking": false}"#);
        assert_eq!(cuerpo.texto("grammar"), Some(GRAMATICA_CODIGO));
        assert!(GRAMATICA_CODIGO.contains("root"));
        let (cuerpo, _) = openai("http://x/api/chat", r#"{"messages": [{"role": "user", "content": "x"}]}"#);
        assert!(!cuerpo.contiene("grammar"));
    }

    #[test]
    fn muestreo_segun_el_uso() {
        let pedir = |extra: &str| openai("http://x/api/chat", &format!(r#"{{"messages": [{{"role": "user", "content": "x"}}]{extra}}}"#)).0;
        assert_eq!(pedir("").num("temperature"), Some(0.7));
        assert_eq!(pedir("").num("top_p"), Some(0.8));
        assert_eq!(pedir(r#", "think": true"#).num("temperature"), Some(0.6));
        assert_eq!(pedir(r#", "prig_solo_codigo": true"#).num("temperature"), Some(0.6));
        assert_eq!(pedir(r#", "format": "json""#).num("temperature"), Some(0.3));
        assert_eq!(pedir(r#", "prig_perfil": "preciso""#).num("temperature"), Some(0.3));
        assert_eq!(pedir(r#", "options": {"temperature": 0.1}"#).num("temperature"), Some(0.1));
        assert_eq!(pedir(r#", "options": {"temperature": 0.1}"#).num("top_p"), Some(0.8));
    }

    #[test]
    fn herramientas_y_continuacion() {
        let (cuerpo, prefijos) = openai(
            "http://x/api/chat",
            r#"{"messages": [
                {"role": "user", "content": "¿clima?"},
                {"role": "assistant", "content": "", "thinking": "busco",
                 "tool_calls": [{"function": {"name": "buscar", "arguments": {"q": "clima"}}}, {"function": {"name": "leer", "arguments": {"url": "u"}}}]},
                {"role": "tool", "tool_name": "leer", "content": "r2"},
                {"role": "tool", "tool_name": "buscar", "content": "r1"},
                {"role": "assistant", "content": "Según", "thinking": "ya está"}],
              "tools": [{"type": "function", "function": {"name": "buscar"}}], "logprobs": true, "top_logprobs": 3}"#,
        );
        let msgs = cuerpo.lista("messages").unwrap();
        let Valor::Mapa(asis) = &msgs[1] else { panic!() };
        assert_eq!(asis.texto("reasoning_content"), Some("busco"));
        let llamadas = asis.lista("tool_calls").unwrap();
        let Valor::Mapa(l0) = &llamadas[0] else { panic!() };
        assert_eq!(c(l0.valor("function")), r#"{"name": "buscar", "arguments": "{\"q\": \"clima\"}"}"#);
        let id = |n: &str| {
            llamadas.iter().find_map(|x| match x {
                Valor::Mapa(m) if m.mapa("function").and_then(|f| f.texto("name")) == Some(n) => m.texto("id").map(String::from),
                _ => None,
            })
        };
        let tool_id = |i: usize| match &msgs[i] {
            Valor::Mapa(m) => m.texto("tool_call_id").map(String::from),
            _ => None,
        };
        assert_eq!(tool_id(2), id("leer"));
        assert_eq!(tool_id(3), id("buscar"));
        assert_eq!((cuerpo.verdad("logprobs"), cuerpo.num("top_logprobs")), (true, Some(3.0)));
        assert_eq!((prefijos.texto("content"), prefijos.texto("thinking")), (Some("Según"), Some("ya está")));
    }

    #[test]
    fn respuesta_en_streaming() {
        let lineas = sse(
            &[r#"{"role": "assistant", "content": null}"#, r#"{"reasoning_content": "Pien"}"#, r#"{"reasoning_content": "so."}"#, r#"{"content": "Hola"}"#, r#"{"content": " mundo"}"#],
            Some(r#"{"prompt_n": 20, "prompt_ms": 400.0, "predicted_n": 5, "predicted_ms": 200.0}"#),
            "stop",
        );
        let s = ollama("http://x/api/chat", &lineas, r#"{"content": "", "thinking": ""}"#, 2.0);
        assert_eq!(s[0].mapa("message").unwrap().texto("thinking"), Some("Pien"));
        assert_eq!(s[1].mapa("message").unwrap().texto("thinking"), Some("so."));
        let texto: String = s[..s.len() - 1].iter().map(|o| o.mapa("message").unwrap().texto("content").unwrap_or("").to_string()).collect();
        assert_eq!(texto, "Hola mundo");
        let f = s.last().unwrap();
        assert!(f.verdad("done"));
        assert_eq!(f.texto("done_reason"), Some("stop"));
        assert_eq!(f.num("prompt_eval_count"), Some(20.0));
        assert_eq!(f.num("eval_count"), Some(5.0));
        assert_eq!(f.num("eval_duration"), Some(200_000_000.0));
        assert_eq!(f.num("load_duration"), Some(2_000_000_000.0));
    }

    #[test]
    fn continuacion_quita_lo_ya_escrito() {
        let lineas = sse(
            &[r#"{"content": "El mar de Plutón, dijo Ramírez, es un"}"#, r#"{"content": " mar"}"#, r#"{"reasoning_content": "Multiplico: 17 por 3 da "}"#, r#"{"reasoning_content": "51"}"#],
            None,
            "stop",
        );
        let s = ollama("http://x/api/chat", &lineas, r#"{"content": "El mar de Plutón, dijo Ramírez, es", "thinking": "Multiplico: 17 por 3 da"}"#, 0.0);
        let cuerpo = &s[..s.len() - 1];
        let texto: String = cuerpo.iter().map(|o| o.mapa("message").unwrap().texto("content").unwrap_or("").to_string()).collect();
        let razon: String = cuerpo.iter().map(|o| o.mapa("message").unwrap().texto("thinking").unwrap_or("").to_string()).collect();
        assert_eq!(texto, " un mar");
        assert_eq!(razon, " 51");
    }

    #[test]
    fn prefijo_en_varios_trozos() {
        let mut p = Prefijo::new("abcdef");
        let v: Vec<String> = ["ab", "cd", "efgh", "ij"].iter().map(|t| p.filtrar(t)).collect();
        assert_eq!(v, ["", "", "gh", "ij"]);
        let mut p = Prefijo::new("abc");
        assert_eq!(p.filtrar("xyz"), "xyz");
    }

    #[test]
    fn herramientas_en_streaming() {
        let lineas = sse(
            &[
                r#"{"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "buscar", "arguments": "{\"q\":"}}]}"#,
                r#"{"tool_calls": [{"index": 0, "function": {"arguments": " \"x\"}"}}]}"#,
            ],
            None,
            "tool_calls",
        );
        let s = ollama("http://x/api/chat", &lineas, "{}", 0.0);
        assert_eq!(s.len(), 1);
        assert_eq!(c(s[0].mapa("message").unwrap().valor("tool_calls")), r#"[{"id": "c1", "function": {"name": "buscar", "arguments": {"q": "x"}}}]"#);
    }

    #[test]
    fn generate_en_streaming_y_largo() {
        let s = ollama("http://x/api/generate", &sse(&[r#"{"content": "uno"}"#, r#"{"reasoning_content": "r"}"#], None, "length"), "{}", 0.0);
        assert_eq!(s[0].texto("response"), Some("uno"));
        assert_eq!(s[1].texto("thinking"), Some("r"));
        assert_eq!(s.last().unwrap().texto("done_reason"), Some("length"));
        assert!(s.last().unwrap().contiene("response"));
    }

    #[test]
    fn probabilidades_y_error() {
        let linea = r#"data: {"choices": [{"index": 0, "delta": {"content": "a"}, "logprobs": {"content": [{"token": "a", "logprob": -0.1, "top_logprobs": [{"token": "a", "logprob": -0.1}, {"token": "b", "logprob": -2.0}]}]}}]}"#;
        let s = ollama("http://x/api/chat", &[linea.to_string(), "data: [DONE]".into()], "{}", 0.0);
        let Valor::Mapa(lp) = &s[0].lista("logprobs").unwrap()[0] else { panic!() };
        assert_eq!(c(&lp.lista("top_logprobs").unwrap()[1]), r#"{"token": "b", "logprob": -2.0}"#);
        let s = ollama("http://x/api/chat", &[r#"data: {"error": {"message": "contexto lleno"}}"#.to_string()], "{}", 0.0);
        assert_eq!(s.iter().map(|m| c(&Valor::Mapa(m.clone()))).collect::<Vec<_>>(), [r#"{"error": "contexto lleno"}"#]);
    }

    #[test]
    fn respuesta_completa() {
        let Valor::Mapa(p) = j(r#"{"content": "Hola,", "thinking": ""}"#) else { panic!() };
        let d = a_ollama_completo(
            "http://x/api/chat",
            &j(r#"{"choices": [{"finish_reason": "stop", "message": {"content": "Hola, sigo", "reasoning_content": "r", "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{}"}}]}}], "timings": {"predicted_n": 3, "predicted_ms": 30}}"#),
            &p,
            0.0,
            None,
            &Valor::Nulo,
        )
        .unwrap();
        let m = d.mapa("message").unwrap();
        assert_eq!(m.texto("content"), Some(" sigo"));
        assert_eq!(m.texto("thinking"), Some("r"));
        let Valor::Mapa(l) = &m.lista("tool_calls").unwrap()[0] else { panic!() };
        assert_eq!(c(l.mapa("function").unwrap().valor("arguments")), "{}");
        assert_eq!(d.num("eval_count"), Some(3.0));
    }

    #[test]
    fn estimaciones() {
        let k = |v: &str, d: f64| segundos_keep_alive(&j(v), d);
        assert_eq!(
            [k(r#""5m""#, 300.0), k(r#""1h""#, 300.0), k(r#""30s""#, 300.0), k("0", 300.0), k("-1", 300.0), k(r#""10""#, 300.0), k("null", 300.0), k(r#""raro""#, 7.0)],
            [300.0, 3600.0, 30.0, 0.0, -1.0, 10.0, 300.0, 7.0]
        );
        assert_eq!(calientes_para(None, 8192, false, MB_POR_CALIENTE, 0.0), 0);
        assert_eq!(calientes_para(Some(2000.0), 8192, false, MB_POR_CALIENTE, 0.0), 0);
        assert_eq!(calientes_para(Some(6100.0), 16384, false, MB_POR_CALIENTE, 0.0), 53);
        assert!(calientes_para(Some(5800.0), 32768, false, MB_POR_CALIENTE, 0.0) < calientes_para(Some(5800.0), 8192, false, MB_POR_CALIENTE, 0.0));
        assert_eq!(calientes_para(Some(24000.0), 8192, false, MB_POR_CALIENTE, 0.0), MAX_CALIENTES);
        assert_eq!(calientes_para(Some(6126.0), 16384, true, MB_POR_CALIENTE, 0.0), 42);
        assert_eq!(calientes_para(Some(6126.0), 131072, true, MB_POR_CALIENTE, 0.0), 10);
        assert!(!cabe_mtp(Some(6126.0), 262144));
        assert!(cabe_mtp(Some(6126.0), 131072));
        assert_eq!(contexto_para(1000), Some(32768));
        assert_eq!(contexto_para(40000), Some(65536));
        assert_eq!(contexto_para(200000), Some(262144));
        assert_eq!(contexto_para(300000), None);
        assert_eq!([16384, 32768, 65536, 131072, 262144].map(lote_para), [2048, 2048, 2048, 2048, 1024]);
        assert_eq!(base_mb(100000, false), Some(3739.0));
        assert_eq!(base_mb(100000, true), Some(4799.0));
        assert_eq!(estimar_tokens(&j(&format!(r#"{{"messages": [{{"role": "user", "content": "{}"}}], "options": {{"num_predict": 1000}}}}"#, "x".repeat(30000)))).unwrap(), 10000 + 1000 + 512);
        assert_eq!(estimar_tokens(&j(&format!(r#"{{"prompt": "{}"}}"#, "x".repeat(300)))).unwrap(), 100 + 4096 + 512);
        let global = vec![vec![2, 0, 1, 3]];
        assert_eq!(lista_caliente(&[vec![0, 7, 0, 7]], &global), Some(vec![vec![1, 3, 2, 0]]));
        assert_eq!(lista_caliente(&[vec![0, 0, 0, 0]], &global), None);
        // prefijo de un proyecto
        let grande = format!(r#"{{"role": "user", "content": "{}"}}"#, "x".repeat(PROYECTO_MIN_CARACTERES));
        let pregunta = r#"{"role": "user", "content": "¿qué hace?"}"#;
        let sistema = r#"{"role": "system", "content": "s"}"#;
        let p = |m: &str| prefijo_de(&j(&format!(r#"{{"messages": [{m}]}}"#))).unwrap().map(|v| c(&Valor::Lista(v)));
        assert_eq!(p(&format!("{sistema}, {grande}, {pregunta}")), Some(c(&j(&format!("[{sistema}, {grande}]")))));
        assert_eq!(p(&format!("{sistema}, {grande}")), None);
        assert_eq!(p(&format!("{sistema}, {pregunta}, {grande}")), None);
        assert_eq!(p(""), None);
    }
}
