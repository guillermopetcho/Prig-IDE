//! Ficha de un modelo (backend/recursos/ficha.py): lo que hay que saber de él para decidir dónde y cómo cargarlo.
//!
//! La etiqueta del nombre no sirve para eso. «qwen3:14b-q4_k_m» no dice cuántas capas tiene, cuánta caché KV gasta
//! por token ni si es una mezcla de expertos, y esas tres cosas cambian el veredicto por completo. Medido en una
//! RTX 4050 de 6 GB: qwen3:14b (denso, 48 % en GPU) 6,3 tok/s; qwen3:30b-a3b (MoE, 25 % en GPU, 3 B activos)
//! 22-28 tok/s. El de 30B va cuatro veces más rápido porque por cada token solo lee 8 de sus 128 expertos.
//!
//! Aquí está la parte que no toca la red: construir la ficha a partir de los metadatos, la caché KV, la ficha
//! estimada del catálogo y a qué registro va cada nombre. Pedir los metadatos a Ollama o al registro sigue en
//! Python por ahora.

use crate::valor::{redondear, Mapa, Valor};

/// Bytes por elemento de la caché KV según su tipo
pub const BYTES_KV: &[(&str, f64)] = &[("f16", 2.0), ("q8_0", 1.0625), ("q4_0", 0.5625)];

pub const REGISTRO: &str = "https://registry.ollama.ai";
/// Registros compatibles con Ollama (verificado: los tres sirven manifiestos y blobs)
pub const REGISTROS_EXTERNOS: &[(&str, &str)] =
    &[("hf.co", "https://hf.co"), ("huggingface.co", "https://hf.co"), ("modelscope.cn", "https://modelscope.cn")];

pub fn bytes_kv(tipo: &str) -> f64 {
    BYTES_KV.iter().find(|(k, _)| *k == tipo).map(|(_, b)| *b).unwrap_or(2.0)
}

/// Algunos modelos dan un valor por capa (una lista): se toma el mayor, que es el que manda al reservar memoria
fn entero(v: &Valor) -> Option<i128> {
    let v = match v {
        Valor::Lista(l) => {
            let mut mayor: Option<&Valor> = None;
            for x in l.iter().filter(|x| x.num().is_some()) {
                if mayor.is_none_or(|m| x.num() > m.num()) {
                    mayor = Some(x);
                }
            }
            mayor?
        }
        v => v,
    };
    if v.es_nulo() {
        return None;
    }
    v.entero()
}

/// `a // b` de Python (redondea hacia abajo)
fn division_entera(a: i128, b: i128) -> i128 {
    let q = a / b;
    if a % b != 0 && ((a < 0) != (b < 0)) {
        q - 1
    } else {
        q
    }
}

/// `desde_metadatos` de Python: la ficha a partir de los metadatos GGUF (de Ollama o de la cabecera)
pub fn desde_metadatos(
    meta: &Mapa,
    nombre: &str,
    bytes_peso: &Valor,
    capacidades: &[String],
    plantilla: &str,
    origen: &str,
    cuantizacion: &str,
) -> Mapa {
    let arch = match meta.get("general.architecture") {
        Some(v) if v.verdad() => v.texto_py(),
        _ => String::new(),
    };
    let m = |clave: &str| meta.valor(&format!("{arch}.{clave}")).clone();
    let o = |v: Option<i128>, otro: i128| v.filter(|&x| x != 0).unwrap_or(otro);

    let capas = o(entero(&m("block_count")), 0);
    let cabezas = o(entero(&m("attention.head_count")), 0);
    let cabezas_kv = o(entero(&m("attention.head_count_kv")), cabezas);
    let embedding = o(entero(&m("embedding_length")), 0);
    let dim_k = o(entero(&m("attention.key_length")), if cabezas != 0 { division_entera(embedding, cabezas) } else { 0 });
    let dim_v = o(entero(&m("attention.value_length")), dim_k);
    let contexto = o(entero(&m("context_length")), 0);

    let expertos = o(entero(&m("expert_count")), 0);
    let usados = o(entero(&m("expert_used_count")), 0);
    let ff_experto = o(entero(&m("expert_feed_forward_length")), 0);
    let es_moe = expertos > 1 && usados > 0;

    let mut parametros = entero(meta.valor("general.parameter_count")).unwrap_or(0);
    if parametros == 0 {
        // Sin el recuento declarado, se deduce del tamaño y de los bits de la cuantización. Es una aproximación:
        // sirve para ordenar, no para medir.
        let bits = match cuantizacion.to_uppercase().as_str() {
            "Q4_K_M" => 4.85,
            "Q4_0" => 4.5,
            "Q5_K_M" => 5.7,
            "Q8_0" => 8.5,
            "F16" | "BF16" => 16.0,
            _ => 4.85,
        };
        parametros = if bytes_peso.verdad() { (bytes_peso.num().unwrap_or(0.0) * 8.0 / bits).trunc() as i128 } else { 0 };
    }

    // Parámetros que se leen por cada token. En un modelo denso, todos. En un MoE, todo menos los expertos que no
    // se usan: es lo que decide la velocidad cuando buena parte del modelo vive en la RAM.
    let mut activos = parametros;
    if es_moe && capas != 0 && embedding != 0 && ff_experto != 0 {
        let por_expertos = capas * expertos * 3 * embedding * ff_experto;
        let resto = parametros as f64 - por_expertos as f64 * (1.0 - usados as f64 / expertos as f64);
        activos = (resto.trunc() as i128).max(1);
    }

    // Caché KV por token, en f16: 2 (K y V) × capas × cabezas KV × dimensión
    let kv_por_token = capas * cabezas_kv * (dim_k + dim_v);

    let tiene = |c: &str| capacidades.iter().any(|x| x == c);
    let embedding_puro = tiene("embedding")
        || meta.get(&format!("{arch}.pooling_type")).is_some_and(|v| !v.es_nulo())
        || matches!(meta.get(&format!("{arch}.attention.causal")), Some(Valor::Bool(false)));
    let plantilla = if !plantilla.is_empty() {
        plantilla.to_string()
    } else {
        match meta.get("tokenizer.chat_template") {
            Some(v) if v.verdad() => v.texto_py(),
            _ => String::new(),
        }
    };
    let piensa = tiene("thinking") || ["<think>", "enable_thinking", "reasoning_content"].iter().any(|p| plantilla.contains(p));

    let cuant: Valor = if !cuantizacion.is_empty() {
        cuantizacion.into()
    } else {
        match meta.get("general.file_type") {
            Some(v) if v.verdad() => v.clone(),
            _ => "".into(),
        }
    };
    let bytes = if bytes_peso.verdad() { bytes_peso.entero().unwrap_or(0) } else { 0 };
    let fraccion = if parametros != 0 { redondear(activos as f64 / parametros as f64, 4) } else { 1.0 };

    Mapa::new()
        .con("nombre", nombre)
        .con("origen", origen)
        .con("arquitectura", arch.clone())
        .con("cuantizacion", cuant)
        .con("bytes_peso", bytes)
        .con("parametros", parametros)
        .con("parametros_activos", activos)
        .con("fraccion_activa", fraccion)
        .con("capas", capas)
        .con("cabezas_kv", cabezas_kv)
        .con("dim_cabeza", dim_k)
        .con("kv_bytes_token_f16", kv_por_token * 2)
        .con("contexto_max", contexto)
        .con("es_moe", es_moe)
        .con("expertos", expertos)
        .con("expertos_usados", usados)
        .con("embedding", embedding_puro)
        .con("piensa", piensa)
        .con("herramientas", tiene("tools"))
        .con("vision", tiene("vision") || meta.contiene(&format!("{arch}.vision.block_count")))
        .con("estimada", origen == "catalogo")
}

/// Caché KV para un contexto y un número de peticiones simultáneas. Cada ranura en paralelo reserva su propia
/// caché: dos ranuras de 4096 ocupan lo mismo que una de 8192. Por eso subir el paralelo no es gratis.
pub fn kv_bytes(ficha: &Mapa, contexto: i64, paralelo: i64, tipo: &str) -> i128 {
    let por_token = ficha.num_o("kv_bytes_token_f16", 0.0) / 2.0 * bytes_kv(tipo);
    (por_token * contexto as f64 * paralelo.max(1) as f64).trunc() as i128
}

/// Último recurso, sin red: la ficha estimada a partir del tamaño del catálogo. La caché KV se estima por lo alto
/// (20 KB por cada mil millones de parámetros) para que un modelo desconocido nunca salga como «cabe» cuando no
/// cabe. Error: el mensaje del ValueError de `float()`.
pub fn desde_catalogo(nombre: &str, info: &Mapa) -> Result<Mapa, String> {
    let gb = match info.get("vram_gb") {
        Some(v) if v.verdad() => {
            v.real().ok_or_else(|| format!("could not convert string to float: {}", v.repr_py()))?
        }
        _ => 0.0,
    };
    let params = (gb * 1e9 * 8.0 / 4.85).trunc() as i128;
    let piensa = matches!(info.texto("piensa"), Some("conmutable" | "siempre"));
    Ok(Mapa::new()
        .con("nombre", nombre)
        .con("origen", "catalogo")
        .con("arquitectura", info.get("familia").cloned().unwrap_or_else(|| "".into()))
        .con("cuantizacion", "Q4_K_M")
        .con("bytes_peso", (gb * 1e9).trunc() as i128)
        .con("parametros", params)
        .con("parametros_activos", params)
        .con("fraccion_activa", 1.0)
        .con("capas", 0)
        .con("cabezas_kv", 0)
        .con("dim_cabeza", 0)
        .con("kv_bytes_token_f16", (params as f64 / 1e9 * 20_000.0).trunc() as i128)
        .con("contexto_max", 32768)
        .con("es_moe", false)
        .con("expertos", 0)
        .con("expertos_usados", 0)
        .con("embedding", info.verdad("embedding"))
        .con("piensa", piensa)
        .con("herramientas", false)
        .con("vision", false)
        .con("estimada", true))
}

/// (url del registro, repo, etiqueta) para cualquier nombre que Ollama descarga: «qwen3:8b»,
/// «usuario/modelo:tag», «hf.co/org/repo:Q4_K_M», «modelscope.cn/org/repo:q4_k_m»
pub fn registro_de(nombre: &str) -> (String, String, String) {
    let (host, resto) = nombre.split_once('/').unwrap_or((nombre, ""));
    if let Some((_, url)) = REGISTROS_EXTERNOS.iter().find(|(h, _)| *h == host) {
        if !resto.is_empty() {
            let (base, tag) = resto.split_once(':').unwrap_or((resto, ""));
            return (url.to_string(), base.to_string(), if tag.is_empty() { "latest" } else { tag }.to_string());
        }
    }
    let (base, tag) = nombre.split_once(':').unwrap_or((nombre, ""));
    let repo = if base.contains('/') { base.to_string() } else { format!("library/{base}") };
    (REGISTRO.to_string(), repo, if tag.is_empty() { "latest" } else { tag }.to_string())
}

// =========================================================================== fuentes (red)

/// Un error al buscar una ficha: el LookupError de Prig (con su mensaje) o uno de la red o de la cabecera
#[derive(Debug, Clone, PartialEq)]
pub enum ErrorFicha {
    NoEncontrada(String),
    Otro(String),
}

impl std::fmt::Display for ErrorFicha {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ErrorFicha::NoEncontrada(m) | ErrorFicha::Otro(m) => f.write_str(m),
        }
    }
}

fn otro(e: impl std::fmt::Display) -> ErrorFicha {
    ErrorFicha::Otro(e.to_string())
}

fn cliente(segundos: u64) -> Result<reqwest::blocking::Client, ErrorFicha> {
    reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(segundos)).build().map_err(otro)
}

/// GET que falla si la respuesta no es 2xx (como urllib y `raise_for_status`); devuelve los bytes
fn obtener_bytes(url: &str, cabeceras: &[(&str, String)], segundos: u64) -> Result<Vec<u8>, ErrorFicha> {
    let mut p = cliente(segundos)?.get(url);
    for (k, v) in cabeceras {
        p = p.header(*k, v);
    }
    let r = p.send().map_err(otro)?;
    if !r.status().is_success() {
        let s = r.status();
        return Err(ErrorFicha::Otro(format!("HTTP Error {}: {}", s.as_u16(), s.canonical_reason().unwrap_or(""))));
    }
    Ok(r.bytes().map_err(otro)?.to_vec())
}

fn obtener_json(url: &str, cabeceras: &[(&str, String)], segundos: u64) -> Result<Valor, ErrorFicha> {
    let b = obtener_bytes(url, cabeceras, segundos)?;
    crate::json::leer(&String::from_utf8_lossy(&b)).map_err(ErrorFicha::Otro)
}

/// Nombre → {tamaño, digest, detalles} de lo que Ollama tiene descargado
pub fn instalados(ollama: &str) -> Result<Mapa, ErrorFicha> {
    let r = obtener_json(&format!("{ollama}/api/tags"), &[], 10)?;
    let mut salida = Mapa::new();
    let modelos = match &r {
        Valor::Mapa(m) => m.lista("models").unwrap_or(&[]).to_vec(),
        _ => return Err(otro("respuesta de Ollama inesperada")),
    };
    for m in modelos {
        let Valor::Mapa(m) = m else { return Err(otro("respuesta de Ollama inesperada")) };
        let nombre = m.get("name").ok_or_else(|| otro("'name'"))?.texto_py();
        salida.poner(nombre, m);
    }
    Ok(salida)
}

/// La ficha de un modelo instalado en Ollama (/api/show trae los metadatos y las capacidades declaradas)
pub fn desde_ollama(ollama: &str, nombre: &str) -> Result<Mapa, ErrorFicha> {
    let inst = instalados(ollama)?;
    let clave = if inst.contiene(nombre) { nombre.to_string() } else { format!("{nombre}:latest") };
    let Some(Valor::Mapa(info)) = inst.get(&clave) else {
        return Err(ErrorFicha::NoEncontrada(format!("'{nombre}' no está instalado")));
    };
    let cuerpo = Mapa::new().con("model", clave.as_str());
    let r = cliente(30)?
        .post(format!("{ollama}/api/show"))
        .header("Content-Type", "application/json")
        .body(crate::json::escribir_compacto(&Valor::Mapa(cuerpo)))
        .send()
        .map_err(otro)?;
    if !r.status().is_success() {
        let s = r.status();
        return Err(ErrorFicha::Otro(format!("HTTP Error {}: {}", s.as_u16(), s.canonical_reason().unwrap_or(""))));
    }
    let datos = match crate::json::leer(&r.text().map_err(otro)?).map_err(ErrorFicha::Otro)? {
        Valor::Mapa(d) => d,
        _ => return Err(otro("respuesta de Ollama inesperada")),
    };
    let o_vacio = |k: &str| match datos.get(k) {
        Some(v) if v.verdad() => v.clone(),
        _ => Valor::Nulo,
    };
    let meta = match o_vacio("model_info") {
        Valor::Mapa(m) => m,
        _ => Mapa::new(),
    };
    let caps: Vec<String> = match o_vacio("capabilities") {
        Valor::Lista(l) => l.iter().map(Valor::texto_py).collect(),
        _ => Vec::new(),
    };
    let plantilla = match o_vacio("template") {
        Valor::Nulo => String::new(),
        v => v.texto_py(),
    };
    let cuant = match o_vacio("details") {
        Valor::Mapa(d) => d.get("quantization_level").map(Valor::texto_py).unwrap_or_default(),
        _ => String::new(),
    };
    let tam = info.get("size").cloned().unwrap_or(Valor::Entero(0));
    Ok(desde_metadatos(&meta, &clave, &tam, &caps, &plantilla, "ollama", &cuant))
}

/// La cuantización que dice la etiqueta: `re.search(r"(q\d_k_[sml]|q\d_\d|f16|bf16|q8_0)", tag, re.I)`, en
/// mayúsculas
fn cuantizacion_de(tag: &str) -> Option<String> {
    let c: Vec<char> = tag.chars().map(|c| c.to_ascii_lowercase()).collect();
    let es = |i: usize, f: &dyn Fn(char) -> bool| c.get(i).is_some_and(|&x| f(x));
    for i in 0..c.len() {
        let q = es(i, &|x| x == 'q') && es(i + 1, &|x| x.is_ascii_digit()) && es(i + 2, &|x| x == '_');
        let largo = if q && es(i + 3, &|x| x == 'k') && es(i + 4, &|x| x == '_') && es(i + 5, &|x| "sml".contains(x)) {
            Some(6)
        } else if q && es(i + 3, &|x| x.is_ascii_digit()) {
            Some(4)
        } else if c[i..].starts_with(&['f', '1', '6']) {
            Some(3)
        } else if c[i..].starts_with(&['b', 'f', '1', '6']) {
            Some(4)
        } else {
            None
        };
        if let Some(n) = largo {
            return Some(tag.chars().skip(i).take(n).collect::<String>().to_uppercase());
        }
    }
    None
}

fn leer_cache(ruta: &std::path::Path) -> Mapa {
    match std::fs::read_to_string(ruta).ok().and_then(|t| crate::json::leer(&t).ok()) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    }
}

static CERROJO_CACHE: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// `json.dump(datos, f, ensure_ascii=False)` a un temporal y se renombra
fn guardar_cache(ruta: &std::path::Path, datos: &Mapa) -> Result<(), ErrorFicha> {
    let _g = CERROJO_CACHE.lock().unwrap_or_else(|e| e.into_inner());
    let mut tmp = ruta.as_os_str().to_owned();
    tmp.push(".tmp");
    std::fs::write(&tmp, crate::json::escribir_linea(&Valor::Mapa(datos.clone()))).map_err(otro)?;
    std::fs::rename(&tmp, ruta).map_err(otro)
}

/// La ficha de un modelo SIN descargarlo: solo la cabecera GGUF por rangos. Se guarda en caché por el digest de la
/// capa: un blob con el mismo digest es el mismo modelo, así que no hay que volver a leerlo nunca.
pub fn desde_registro(nombre: &str, cache: &std::path::Path) -> Result<Mapa, ErrorFicha> {
    let (registro, repo, tag) = registro_de(nombre);
    let manifiesto = obtener_json(
        &format!("{registro}/v2/{repo}/manifests/{tag}"),
        &[("Accept", "application/vnd.docker.distribution.manifest.v2+json".into())],
        20,
    )?;
    let capas: Vec<Mapa> = match &manifiesto {
        Valor::Mapa(m) => m.lista("layers").unwrap_or(&[]).iter().filter_map(|l| if let Valor::Mapa(l) = l { Some(l.clone()) } else { None }).collect(),
        _ => Vec::new(),
    };
    let tipo = |l: &Mapa, fin: &str| l.texto("mediaType").unwrap_or("").ends_with(fin);
    let Some(capa) = capas.iter().find(|l| tipo(l, "image.model")) else {
        return Err(ErrorFicha::NoEncontrada(format!("'{nombre}' no tiene capa de modelo en el registro")));
    };
    let digest = capa.get("digest").ok_or_else(|| otro("'digest'"))?.texto_py();
    let mut guardadas = leer_cache(cache);
    if let Some(Valor::Mapa(f)) = guardadas.get(&digest) {
        return Ok(f.clone().con("nombre", nombre));
    }
    let url = format!("{registro}/v2/{repo}/blobs/{digest}");
    let meta = crate::gguf::leer_con_rangos(
        |desde, hasta| obtener_bytes(&url, &[("Range", format!("bytes={desde}-{hasta}"))], 90),
        256 * 1024,
        48 * 1024 * 1024,
    )
    .map_err(|e| match e {
        crate::gguf::ErrorRangos::Pedir(e) => e,
        crate::gguf::ErrorRangos::Gguf(crate::gguf::ErrorGguf::Invalido(m)) => ErrorFicha::Otro(m),
        crate::gguf::ErrorRangos::Gguf(crate::gguf::ErrorGguf::FaltanBytes) => otro("faltan bytes"),
    })?;
    // La plantilla va en su propia capa y es pequeña: dice si el modelo piensa
    let mut plantilla = String::new();
    if let Some(t) = capas.iter().find(|l| tipo(l, "image.template")) {
        if t.num_o("size", 0.0) < 512.0 * 1024.0 {
            let d = t.valor("digest").texto_py();
            if let Ok(b) = obtener_bytes(&format!("{registro}/v2/{repo}/blobs/{d}"), &[], 30) {
                plantilla = String::from_utf8_lossy(&b).into_owned();
            }
        }
    }
    let cuant = cuantizacion_de(&tag).unwrap_or_else(|| "Q4_K_M".into());
    let tam = capa.get("size").cloned().ok_or_else(|| otro("'size'"))?;
    let ficha = desde_metadatos(&meta, nombre, &tam, &[], &plantilla, "registro", &cuant);
    guardadas.poner(digest, ficha.clone());
    guardar_cache(cache, &guardadas)?;
    Ok(ficha)
}

/// La mejor ficha disponible, probando las fuentes en orden de fiabilidad: Ollama, el registro (si hay red) y el
/// catálogo (estimada, con los avisos de lo que falló). Error: el mensaje del LookupError de Python.
pub fn obtener(ollama: &str, nombre: &str, catalogo: Option<&Mapa>, red: bool, cache: &std::path::Path) -> Result<Mapa, String> {
    let mut errores: Vec<String> = Vec::new();
    match desde_ollama(ollama, nombre) {
        Ok(f) => return Ok(f),
        Err(e) => errores.push(format!("ollama: {e}")),
    }
    if red {
        match desde_registro(nombre, cache) {
            Ok(f) => return Ok(f),
            Err(e) => errores.push(format!("registro: {e}")),
        }
    }
    if let Some(Valor::Mapa(info)) = catalogo.and_then(|c| c.get(nombre)) {
        let f = desde_catalogo(nombre, info)?;
        return Ok(f.con("avisos", Valor::Lista(errores.into_iter().map(Valor::from).collect())));
    }
    Err(format!("No hay ficha para '{nombre}': {}", errores.join("; ")))
}

#[cfg(test)]
mod tests_red {
    use super::*;

    #[test]
    fn cuantizacion_de_la_etiqueta() {
        assert_eq!(cuantizacion_de("8b-q4_K_M"), Some("Q4_K_M".into()));
        assert_eq!(cuantizacion_de("Q8_0"), Some("Q8_0".into()));
        assert_eq!(cuantizacion_de("bf16"), Some("BF16".into()));
        assert_eq!(cuantizacion_de("xf16"), Some("F16".into()));
        assert_eq!(cuantizacion_de("latest"), None);
        assert_eq!(cuantizacion_de("q5_1"), Some("Q5_1".into()));
    }
}
