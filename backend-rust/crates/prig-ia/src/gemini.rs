//! Google Gemini como motor opcional, en la nube (`backend/gemini_motor.py`).
//!
//! Se conecta con una clave de API de Google AI Studio (aistudio.google.com/apikey), la vía oficial. No se reutiliza
//! ninguna sesión guardada por otros programas de Google: sus condiciones lo prohíben desde software de terceros.
//!
//! PRIVACIDAD: en el nivel gratuito Google puede usar lo que se le envía para mejorar sus productos, con revisión
//! humana; por eso está apagado hasta que el usuario pega su clave y acepta el aviso. La clave vive en
//! ~/.prig_gemini.json con permisos 600 (o en GEMINI_API_KEY), nunca se devuelve entera, va en la cabecera
//! x-goog-api-key (no en la URL) y se borra de cualquier mensaje de error.
//!
//! Pruebas: PRIG_GEMINI_ARCHIVO (dónde se guarda) y PRIG_GEMINI_URL (un servidor falso).

use crate::vivo::Cancelar;
use prig_recursos::json;
use prig_recursos::valor::{Mapa, Valor};
use regex::Regex;
use std::collections::HashMap;
use std::io::BufRead;
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

pub const PREFIJO: &str = "gemini:";
pub const URL_CLAVES: &str = "https://aistudio.google.com/apikey";
pub const AVISO_PRIVACIDAD: &str = "Cuando uses un modelo Gemini, Prig envía a Google el tema, el enunciado, tu plan, tu \
código y los mensajes del tutor de ese desafío. En el nivel gratuito, Google puede usar ese contenido y las respuestas \
para mejorar sus productos, y puede revisarlo una persona. No escribas datos personales. Con facturación activada (nivel \
de pago) Google no lo usa para mejorar sus productos.";

/// El ErrorGemini de Python: su mensaje, para el usuario
#[derive(Debug, Clone, PartialEq)]
pub struct ErrorGemini(pub String);

fn error(m: impl Into<String>) -> ErrorGemini {
    ErrorGemini(m.into())
}

fn base() -> String {
    std::env::var("PRIG_GEMINI_URL")
        .ok()
        .filter(|u| !u.is_empty())
        .unwrap_or_else(|| "https://generativelanguage.googleapis.com/v1beta".into())
        .trim_end_matches('/')
        .to_string()
}

pub fn ruta_config() -> PathBuf {
    match std::env::var("PRIG_GEMINI_ARCHIVO").ok().filter(|r| !r.is_empty()) {
        Some(r) => PathBuf::from(r),
        None => PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".prig_gemini.json"),
    }
}

fn leer() -> Mapa {
    match std::fs::read_to_string(ruta_config()).ok().and_then(|t| json::leer(&t).ok()) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    }
}

/// (clave, origen): primero lo guardado en Prig, después GEMINI_API_KEY
pub fn clave_actual() -> (Option<String>, Option<&'static str>) {
    if let Some(c) = leer().get("clave").filter(|c| c.verdad()) {
        return (Some(c.texto_py()), Some("prig"));
    }
    match std::env::var("GEMINI_API_KEY").ok().filter(|c| !c.is_empty()) {
        Some(c) => (Some(c), Some("entorno")),
        None => (None, None),
    }
}

pub fn enmascarar(clave: Option<&str>) -> Valor {
    let Some(c) = clave.filter(|c| !c.is_empty()) else { return Valor::Nulo };
    let letras: Vec<char> = c.chars().collect();
    if letras.len() > 12 {
        let ini: String = letras[..4].iter().collect();
        let fin: String = letras[letras.len() - 4..].iter().collect();
        Valor::Texto(format!("{ini}…{fin}"))
    } else {
        Valor::Texto("…".into())
    }
}

pub fn estado() -> Mapa {
    let (clave, origen) = clave_actual();
    let datos = leer();
    Mapa::new()
        .con("configurado", clave.is_some())
        .con("origen", origen.map(Valor::from).unwrap_or(Valor::Nulo))
        .con("clave", enmascarar(clave.as_deref()))
        .con(
            "aviso_aceptado",
            if origen == Some("prig") { datos.get("aviso_aceptado").cloned().unwrap_or(Valor::Nulo) } else { Valor::Nulo },
        )
        .con("aviso", AVISO_PRIVACIDAD)
        .con("url_claves", URL_CLAVES)
}

fn re(p: &str) -> &'static Regex {
    static CACHE: OnceLock<Mutex<HashMap<String, &'static Regex>>> = OnceLock::new();
    let mut c = CACHE.get_or_init(Default::default).lock().unwrap_or_else(|e| e.into_inner());
    c.entry(p.to_string()).or_insert_with(|| Box::leak(Box::new(Regex::new(p).expect("regex"))))
}

/// La clave tal como se usa, a partir de lo que se pegó (sola, entre comillas, `GEMINI_API_KEY=…`,
/// `export GEMINI_API_KEY="…"`, `x-goog-api-key: …` o una URL con `key=…`). Si no puede ser una clave lo dice sin
/// repetirla.
pub fn limpiar_clave(texto: &str) -> Result<String, ErrorGemini> {
    let t: String = texto.chars().filter(|c| !['\u{200b}', '\u{200c}', '\u{200d}', '\u{2060}', '\u{feff}', '\u{a0}'].contains(c)).collect();
    let mut t = t.trim().to_string();
    if let Some(m) = re(r"[?&]key=([^&\s]+)").captures(&t) {
        t = m[1].to_string();
    }
    t = re(r"^(?:export\s+)?[A-Z_]*API_KEY\s*=\s*").replace(&t, "").into_owned();
    t = re(r"(?i)^x-goog-api-key\s*:\s*").replace(&t, "").into_owned();
    let t = t.trim().trim_matches(|c| c == '"' || c == '\'' || c == '`').trim().to_string();
    if t.is_empty() {
        return Err(error("No pegaste ninguna clave."));
    }
    if re(r"\s").is_match(&t) {
        return Err(error(
            "Lo que pegaste tiene espacios o saltos de línea en medio: copia solo la clave (en AI Studio, el botón de \
             copiar junto a la clave).",
        ));
    }
    let n = t.chars().count();
    if n < 20 {
        return Err(error(format!(
            "Lo que pegaste tiene {n} caracteres y una clave de Gemini es más larga: parece que falta un trozo. Cópiala \
             de nuevo con el botón de copiar de AI Studio."
        )));
    }
    if !t.chars().all(|c| (33..=126).contains(&(c as u32))) {
        return Err(error(
            "Lo que pegaste tiene caracteres que no aparecen en las claves (acentos, símbolos especiales): cópiala de \
             nuevo desde AI Studio.",
        ));
    }
    Ok(t)
}

/// El error de Google explicado, sin la clave
pub fn explicar(codigo: u16, cuerpo: &str, clave: Option<&str>) -> String {
    let error = match json::leer(cuerpo) {
        Ok(Valor::Mapa(m)) => m.mapa("error").cloned().unwrap_or_default(),
        _ => Mapa::new(),
    };
    let motivo = error
        .lista("details")
        .unwrap_or(&[])
        .iter()
        .filter_map(|d| if let Valor::Mapa(d) = d { Some(d.get("reason").map(Valor::texto_py).unwrap_or_default()) } else { None })
        .collect::<Vec<_>>()
        .join(" ");
    let crudo = match error.get("message").filter(|m| m.verdad()) {
        Some(m) => m.texto_py(),
        None => cuerpo.to_string(),
    };
    let mut mensaje: String = crudo.chars().take(300).collect();
    if let Some(c) = clave.filter(|c| !c.is_empty()) {
        mensaje = mensaje.replace(c, "…");
    }
    if motivo.contains("API_KEY_INVALID") || mensaje.contains("API key not valid") {
        return "La clave de Gemini no es válida. Crea otra en Google AI Studio y vuelve a conectarla.".into();
    }
    if codigo == 401 || motivo.contains("ACCESS_TOKEN_TYPE_UNSUPPORTED") {
        // Medido: así responde Google a una clave «AQ.…» que no reconoce
        return "Google no reconoce esta clave. Suele pasar si se copió incompleta o si la borraste en AI Studio. \
                Cópiala de nuevo con el botón de copiar de AI Studio, o crea otra."
            .into();
    }
    if codigo == 429 || error.get("status") == Some(&Valor::Texto("RESOURCE_EXHAUSTED".into())) {
        return "Llegaste al límite gratuito de Gemini (por minuto o por día). Espera un poco o usa un modelo local \
                mientras tanto."
            .into();
    }
    if codigo == 403 {
        return format!("Google rechazó la petición: la clave no tiene permiso para usar Gemini ({mensaje}).");
    }
    if codigo == 404 {
        return "Ese modelo de Gemini no existe o tu clave no tiene acceso a él. Elige otro de la lista.".into();
    }
    if codigo >= 500 {
        return "Gemini no responde ahora mismo (error del servidor de Google). Prueba más tarde.".into();
    }
    format!("Gemini respondió {codigo}: {mensaje}")
}

fn cache() -> &'static Mutex<HashMap<String, (f64, Vec<Valor>)>> {
    static C: OnceLock<Mutex<HashMap<String, (f64, Vec<Valor>)>>> = OnceLock::new();
    C.get_or_init(Default::default)
}

fn olvidar_cache() {
    cache().lock().unwrap_or_else(|e| e.into_inner()).clear();
}

fn cliente(segundos: u64) -> Result<reqwest::blocking::Client, ErrorGemini> {
    reqwest::blocking::Client::builder()
        .connect_timeout(Duration::from_secs(15))
        .timeout(Duration::from_secs(segundos))
        .build()
        .map_err(|_| error("Sin conexión con Google: comprueba internet."))
}

/// Los modelos Gemini que la clave puede usar para generar texto (con caché de 10 min). Primero los Flash (los del
/// nivel gratuito).
pub fn listar_modelos(clave: Option<&str>, usar_cache: bool) -> Result<Vec<Valor>, ErrorGemini> {
    let clave = match clave {
        Some(c) => c.to_string(),
        None => clave_actual().0.ok_or_else(|| error("Gemini no está conectado."))?,
    };
    let ahora = crate::vivo::ahora();
    if usar_cache {
        if let Some((t, m)) = cache().lock().unwrap_or_else(|e| e.into_inner()).get(&clave) {
            if ahora - t < 600.0 {
                return Ok(m.clone());
            }
        }
    }
    let excluir = re(r"embedding|tts|image|audio|live|robotics|computer-use");
    let c = cliente(20)?;
    let (mut modelos, mut token): (Vec<Mapa>, Option<String>) = (Vec::new(), None);
    for _ in 0..10 {
        let mut url = format!("{}/models?pageSize=200", base());
        if let Some(t) = &token {
            url.push_str(&format!("&pageToken={t}"));
        }
        let r = c.get(&url).header("x-goog-api-key", &clave).send().map_err(|_| error("Sin conexión con Google: comprueba internet."))?;
        let codigo = r.status().as_u16();
        let texto = r.text().unwrap_or_default();
        if codigo != 200 {
            return Err(error(explicar(codigo, &texto, Some(&clave))));
        }
        let datos = match json::leer(&texto) {
            Ok(Valor::Mapa(m)) => m,
            _ => Mapa::new(),
        };
        for m in datos.lista("models").unwrap_or(&[]) {
            let Valor::Mapa(m) = m else { continue };
            let nombre = m.get("name").map(Valor::texto_py).unwrap_or_default().rsplit('/').next().unwrap_or("").to_string();
            let metodos = m.lista("supportedGenerationMethods").unwrap_or(&[]);
            if !metodos.contains(&Valor::Texto("generateContent".into())) || !nombre.starts_with("gemini") || excluir.is_match(&nombre) {
                continue;
            }
            let visible = m.get("displayName").filter(|v| v.verdad()).cloned().unwrap_or_else(|| Valor::Texto(nombre.clone()));
            modelos.push(
                Mapa::new()
                    .con("id", nombre.as_str())
                    .con("nombre", visible)
                    .con("piensa", m.verdad("thinking"))
                    .con("entrada", m.get("inputTokenLimit").cloned().unwrap_or(Valor::Nulo))
                    .con("salida", m.get("outputTokenLimit").cloned().unwrap_or(Valor::Nulo)),
            );
        }
        token = datos.get("nextPageToken").filter(|t| t.verdad()).map(Valor::texto_py);
        if token.is_none() {
            break;
        }
    }
    let id = |m: &Mapa| m.valor("id").texto_py();
    modelos.sort_by_key(|m| {
        let i = id(m);
        (!i.contains("flash"), i.contains("lite"), i.contains("preview"), i)
    });
    let lista: Vec<Valor> = modelos.into_iter().map(Valor::Mapa).collect();
    cache().lock().unwrap_or_else(|e| e.into_inner()).insert(clave, (ahora, lista.clone()));
    Ok(lista)
}

/// Guarda la clave (comprobada antes contra Google) con permisos 600
pub fn guardar_clave(clave: &str, acepto_aviso: bool) -> Result<Mapa, ErrorGemini> {
    if !acepto_aviso {
        return Err(error("Para conectar Gemini tienes que aceptar el aviso de privacidad."));
    }
    let clave = limpiar_clave(clave)?;
    let modelos = listar_modelos(Some(&clave), false)?;
    let ruta = ruta_config();
    let mut tmp = ruta.clone().into_os_string();
    tmp.push(".tmp");
    let tmp = PathBuf::from(tmp);
    let datos = Mapa::new().con("clave", clave.as_str()).con("aviso_aceptado", prig_recursos::almacen::ahora());
    {
        use std::io::Write;
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
        let mut f = std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .open(&tmp)
            .map_err(|e| error(e.to_string()))?;
        f.write_all(json::escribir_compacto(&Valor::Mapa(datos)).as_bytes()).map_err(|e| error(e.to_string()))?;
        let _ = std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(0o600));
    }
    std::fs::rename(&tmp, &ruta).map_err(|e| error(e.to_string()))?;
    olvidar_cache();
    Ok(estado().con("modelos", Valor::Lista(modelos)))
}

pub fn borrar_clave() -> Mapa {
    let _ = std::fs::remove_file(ruta_config());
    olvidar_cache();
    estado()
}

/// Generar con Gemini, con la forma de `generar::generar`: `{"t": "texto", "v", "token": true}`, `{"t": "pensando"}`
/// y `{"t": "stats", "v": {"motor": "gemini", …}}`. Los errores llegan como texto («[Error Gemini: …]»); cancelado
/// o con la conexión cortada a mitad, termina sin más.
pub fn generar(prompt: &str, modelo: &str, sistema: &str, opciones: Option<&Mapa>, cancelar: &Cancelar, emitir: &mut dyn FnMut(Mapa)) {
    let texto = |v: &str| Mapa::new().con("t", "texto").con("v", v).con("token", true);
    let fallo = |v: &str| Mapa::new().con("t", "texto").con("v", format!("[Error Gemini: {v}]")).con("token", false);
    let Some(clave) = clave_actual().0 else {
        emitir(fallo("Gemini no está conectado. Conéctalo o elige un modelo local."));
        return;
    };
    let mut cuerpo = Mapa::new().con(
        "contents",
        Valor::Lista(vec![Valor::Mapa(
            Mapa::new().con("role", "user").con("parts", Valor::Lista(vec![Valor::Mapa(Mapa::new().con("text", prompt))])),
        )]),
    );
    if !sistema.is_empty() {
        cuerpo.poner("systemInstruction", Mapa::new().con("parts", Valor::Lista(vec![Valor::Mapa(Mapa::new().con("text", sistema))])));
    }
    let mut config = Mapa::new();
    if let Some(t) = opciones.and_then(|o| o.get("temperature")).filter(|t| !t.es_nulo()).and_then(Valor::num) {
        config.poner("temperature", t);
    }
    if opciones.and_then(|o| o.get("format")) == Some(&Valor::Texto("json".into())) {
        config.poner("responseMimeType", "application/json");
    }
    if !config.is_empty() {
        cuerpo.poner("generationConfig", config);
    }
    let url = format!("{}/models/{modelo}:streamGenerateContent?alt=sse", base());
    let Ok(c) = cliente(300) else {
        emitir(fallo("Sin conexión con Google: comprueba internet."));
        return;
    };
    let r = match c
        .post(&url)
        .header("x-goog-api-key", &clave)
        .header("Content-Type", "application/json")
        .body(json::escribir_compacto(&Valor::Mapa(cuerpo)))
        .send()
    {
        Ok(r) => r,
        Err(_) => {
            emitir(fallo("Sin conexión con Google: comprueba internet."));
            return;
        }
    };
    let codigo = r.status().as_u16();
    if codigo != 200 {
        let t = r.text().unwrap_or_default();
        emitir(fallo(&explicar(codigo, &t, Some(&clave))));
        return;
    }
    for linea in std::io::BufReader::new(r).lines() {
        if cancelar.puesto() {
            return;
        }
        let Ok(linea) = linea else { return }; // cancelado o conexión cortada
        let Some(resto) = linea.strip_prefix("data:") else { continue };
        let Ok(Valor::Mapa(datos)) = json::leer(resto.trim()) else { continue };
        if let Some(b) = datos.mapa("promptFeedback").and_then(|p| p.get("blockReason")).filter(|b| b.verdad()) {
            emitir(fallo(&format!("Google bloqueó la petición por sus filtros ({}).", b.texto_py())));
            return;
        }
        for cand in datos.lista("candidates").unwrap_or(&[]) {
            let Valor::Mapa(cand) = cand else { continue };
            for parte in cand.mapa("content").and_then(|c| c.lista("parts")).unwrap_or(&[]) {
                let Valor::Mapa(parte) = parte else { continue };
                if parte.verdad("thought") {
                    if let Some(Valor::Texto(t)) = parte.get("text") {
                        emitir(Mapa::new().con("t", "pensando").con("v", t.as_str()));
                    }
                    continue;
                }
                if let Some(t) = parte.get("text").filter(|t| t.verdad()) {
                    emitir(texto(&t.texto_py()));
                }
            }
        }
        if let Some(Valor::Mapa(u)) = datos.get("usageMetadata").filter(|u| u.verdad()) {
            let mut s = Mapa::new().con("motor", "gemini");
            for (k, v) in u.iter() {
                s.poner(k.clone(), v.clone());
            }
            emitir(Mapa::new().con("t", "stats").con("v", s));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const AQ: &str = "AQ.Ab8RN6PRUEBA_formato.nuevo12345678";

    #[test]
    fn limpiar_lo_pegado() {
        for pegado in [
            format!("  {AQ}\n"),
            format!("\"{AQ}\""),
            format!("'{AQ}'"),
            format!("`{AQ}`"),
            format!("GEMINI_API_KEY={AQ}"),
            format!("export GEMINI_API_KEY=\"{AQ}\""),
            format!("x-goog-api-key: {AQ}"),
            format!("\u{200b}{AQ}\u{feff}"),
            format!("https://generativelanguage.googleapis.com/v1beta/models?key={AQ}&pageSize=1"),
        ] {
            assert_eq!(limpiar_clave(&pegado).unwrap(), AQ, "{pegado:?}");
        }
        for (pegado, motivo) in [
            ("", "ninguna clave"),
            ("   ", "ninguna clave"),
            ("AQ.corta", "falta un trozo"),
            ("AQ.Ab8RN6 PRUEBA_formato.nuevo123", "espacios"),
            ("AQ.Ab8RN6PRUEBAñandú_formato.nuevo", "caracteres"),
        ] {
            let e = limpiar_clave(pegado).unwrap_err().0;
            assert!(e.contains(motivo), "{pegado:?}: {e}");
            assert!(!e.contains("PRUEBA")); // nunca repite lo pegado
        }
    }

    #[test]
    fn errores_explicados_sin_la_clave() {
        let c = "AIzaSySECRETA_de_prueba_abcd";
        let m = explicar(403, &format!("{{\"error\": {{\"message\": \"clave {c} mala\"}}}}"), Some(c));
        assert!(!m.contains(c) && m.contains("no tiene permiso"));
        assert!(explicar(400, r#"{"error": {"details": [{"reason": "API_KEY_INVALID"}]}}"#, None).contains("no es válida"));
        assert!(explicar(401, "{}", None).contains("Google no reconoce esta clave"));
        assert!(explicar(429, "{}", None).contains("límite gratuito"));
        assert!(explicar(404, "{}", None).contains("no existe"));
        assert!(explicar(503, "{}", None).contains("no responde"));
    }

    #[test]
    fn enmascarada() {
        assert_eq!(enmascarar(Some("AIzaSyX_prueba_abcd")), Valor::Texto("AIza…abcd".into()));
        assert_eq!(enmascarar(Some("corta")), Valor::Texto("…".into()));
        assert_eq!(enmascarar(None), Valor::Nulo);
    }
}
