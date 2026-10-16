//! Las peticiones HTTP de los módulos de modelos, como las hacía `requests`: el cuerpo JSON con el escritor de Python
//! (`json.dumps`), la respuesta leída entera o línea a línea, y los errores de red separados de los del servidor (para
//! que la fachada lance las excepciones de `requests` que espera app.py).

use prig_recursos::json;
use prig_recursos::valor::Valor;
use std::io::{BufRead, BufReader, Read};
use std::time::Duration;

#[derive(Debug)]
pub enum ErrorRed {
    /// No se pudo conectar o se cortó (requests.ConnectionError)
    Conexion(String),
    /// Se pasó el tiempo (requests.Timeout)
    Tiempo(String),
    /// La respuesta no es JSON (requests.JSONDecodeError): el mensaje y el documento
    Json(String, String),
}

impl ErrorRed {
    pub fn texto(&self) -> String {
        match self {
            ErrorRed::Conexion(t) | ErrorRed::Tiempo(t) | ErrorRed::Json(t, _) => t.clone(),
        }
    }
}

fn de_reqwest(e: reqwest::Error) -> ErrorRed {
    if e.is_timeout() {
        ErrorRed::Tiempo(e.to_string())
    } else {
        ErrorRed::Conexion(e.to_string())
    }
}

pub struct Respuesta {
    pub estado: u16,
    pub cuerpo: Vec<u8>,
    /// La cabecera `Link` (la paginación de Hugging Face)
    pub link: String,
}

impl Respuesta {
    /// `r.text`
    pub fn texto(&self) -> String {
        String::from_utf8_lossy(&self.cuerpo).into_owned()
    }

    /// `r.json()`
    pub fn json(&self) -> Result<Valor, ErrorRed> {
        let t = self.texto();
        json::leer(&t).map_err(|e| ErrorRed::Json(e, t.clone()))
    }

    /// `_error(r)` de `ollama_gestion`: el `error` (o su `message`) del JSON, o el texto, o `HTTP <código>`
    pub fn error(&self) -> String {
        let http = || format!("HTTP {}", self.estado);
        match self.json() {
            Ok(Valor::Mapa(d)) => {
                let e = d.valor("error");
                let e = match e {
                    Valor::Mapa(m) => m.valor("message").clone(),
                    otro => otro.clone(),
                };
                if e.verdad() {
                    e.texto_py()
                } else {
                    http()
                }
            }
            _ => {
                let t: String = self.texto().chars().take(300).collect();
                if t.is_empty() {
                    http()
                } else {
                    t
                }
            }
        }
    }
}

/// Los clientes ya creados, por tiempo y por si siguen redirecciones: un cliente guarda sus conexiones abiertas, así
/// que la segunda petición al mismo servidor se ahorra la conexión y el saludo TLS (~150 ms con GitHub o YouTube)
/// (tiempo en bits, redirige) → cliente
type Clientes = Vec<((Option<u64>, bool), reqwest::blocking::Client)>;
static CLIENTES: std::sync::Mutex<Clientes> = std::sync::Mutex::new(Vec::new());

pub fn cliente(segundos: Option<f64>) -> Result<reqwest::blocking::Client, ErrorRed> {
    cliente_con(segundos, true)
}

fn cliente_con(segundos: Option<f64>, redirigir: bool) -> Result<reqwest::blocking::Client, ErrorRed> {
    let clave = (segundos.map(f64::to_bits), redirigir);
    if let Some((_, c)) = CLIENTES.lock().unwrap().iter().find(|(k, _)| *k == clave) {
        return Ok(c.clone());
    }
    let politica = if redirigir { reqwest::redirect::Policy::limited(30) } else { reqwest::redirect::Policy::none() };
    // sin Referer al redirigir: ni requests ni urllib lo ponen
    let mut b = reqwest::blocking::Client::builder().redirect(politica).referer(false).pool_idle_timeout(Duration::from_secs(90));
    b = match segundos {
        Some(s) => b.timeout(Duration::from_secs_f64(s)).connect_timeout(Duration::from_secs_f64(s)),
        // sin tiempo total (una subida o una creación largas): solo el de conectar
        None => b.timeout(None).connect_timeout(Duration::from_secs(30)),
    };
    let c = b.build().map_err(de_reqwest)?;
    let mut cache = CLIENTES.lock().unwrap();
    if cache.len() >= 16 {
        cache.remove(0);
    }
    cache.push((clave, c.clone()));
    Ok(c)
}

/// Una respuesta entera, con todo lo que necesita un `requests.Response`
pub struct RespuestaCompleta {
    pub estado: u16,
    pub razon: String,
    pub cabeceras: Vec<(String, String)>,
    pub cuerpo: Vec<u8>,
    pub url: String,
}

/// Una petición ya preparada (por `requests.Request(...).prepare()` en Python: URL con sus parámetros, cabeceras y
/// cuerpo exactos) enviada por el cliente compartido
pub fn enviar(metodo: &str, url: &str, cabeceras: &[(String, String)], cuerpo: Option<Vec<u8>>, segundos: Option<f64>,
              redirigir: bool) -> Result<RespuestaCompleta, ErrorRed> {
    let c = cliente_con(segundos, redirigir)?;
    let metodo = reqwest::Method::from_bytes(metodo.as_bytes()).map_err(|e| ErrorRed::Conexion(e.to_string()))?;
    let mut rb = c.request(metodo, url);
    for (k, v) in cabeceras {
        rb = rb.header(k.as_str(), v.as_str());
    }
    if let Some(cuerpo) = cuerpo {
        rb = rb.body(cuerpo);
    }
    let r = rb.send().map_err(de_reqwest)?;
    let estado = r.status().as_u16();
    let razon = r.status().canonical_reason().unwrap_or("").to_string();
    let url = r.url().to_string();
    let cabeceras = r.headers().iter().map(|(k, v)| (k.as_str().to_string(), String::from_utf8_lossy(v.as_bytes()).into_owned())).collect();
    let cuerpo = r.bytes().map_err(de_reqwest)?.to_vec();
    Ok(RespuestaCompleta { estado, razon, cabeceras, cuerpo, url })
}

/// Una petición entera: (método, url, cuerpo JSON, cabeceras, segundos)
pub fn pedir(metodo: &str, url: &str, cuerpo: Option<&Valor>, cabeceras: &[(&str, &str)], segundos: f64) -> Result<Respuesta, ErrorRed> {
    let c = cliente(Some(segundos))?;
    let mut rb = match metodo {
        "GET" => c.get(url),
        "POST" => c.post(url),
        "DELETE" => c.delete(url),
        "HEAD" => c.head(url),
        otro => c.request(reqwest::Method::from_bytes(otro.as_bytes()).unwrap_or(reqwest::Method::GET), url),
    };
    for (k, v) in cabeceras {
        rb = rb.header(*k, *v);
    }
    if let Some(cuerpo) = cuerpo {
        rb = rb.header("Content-Type", "application/json").body(json::escribir_compacto(cuerpo));
    }
    let r = rb.send().map_err(de_reqwest)?;
    let estado = r.status().as_u16();
    let link = r.headers().get("link").and_then(|v| v.to_str().ok()).unwrap_or("").to_string();
    let cuerpo = r.bytes().map_err(de_reqwest)?.to_vec();
    Ok(Respuesta { estado, cuerpo, link })
}

/// `urllib.parse.quote_plus` (lo que hace `requests` con `params`): letras, cifras y `_.-~` tal cual, el espacio
/// como `+` y lo demás en `%XX` (UTF-8)
pub fn quote_plus(t: &str) -> String {
    let mut s = String::with_capacity(t.len());
    for b in t.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => s.push(b as char),
            b' ' => s.push('+'),
            otro => s.push_str(&format!("%{otro:02X}")),
        }
    }
    s
}

/// La URL con `params` como la arma `requests`: `clave=valor` en su orden, las listas repetidas
pub fn con_params(url: &str, params: &[(&str, String)]) -> String {
    if params.is_empty() {
        return url.to_string();
    }
    let q: Vec<String> = params.iter().map(|(k, v)| format!("{}={}", quote_plus(k), quote_plus(v))).collect();
    let sep = if url.contains('?') { "&" } else { "?" };
    format!("{url}{sep}{}", q.join("&"))
}

/// Un POST cuyo cuerpo sale de un lector (una subida grande, por trozos)
pub fn subir(url: &str, lector: impl Read + Send + 'static) -> Result<Respuesta, ErrorRed> {
    let c = cliente(None)?;
    let r = c.post(url).body(reqwest::blocking::Body::new(lector)).send().map_err(de_reqwest)?;
    let estado = r.status().as_u16();
    let cuerpo = r.bytes().map_err(de_reqwest)?.to_vec();
    Ok(Respuesta { estado, cuerpo, link: String::new() })
}

/// Una respuesta que se lee línea a línea (`r.iter_lines()`, sin las vacías)
pub struct Lineas {
    lector: BufReader<reqwest::blocking::Response>,
}

impl Lineas {
    pub fn siguiente(&mut self) -> Result<Option<String>, ErrorRed> {
        loop {
            let mut b = Vec::new();
            let n = self.lector.read_until(b'\n', &mut b).map_err(|e| ErrorRed::Conexion(e.to_string()))?;
            if n == 0 {
                return Ok(None);
            }
            while matches!(b.last(), Some(b'\n' | b'\r')) {
                b.pop();
            }
            if b.is_empty() {
                continue;
            }
            return Ok(Some(String::from_utf8_lossy(&b).into_owned()));
        }
    }
}

/// Un POST JSON cuya respuesta se lee por líneas; si el estado no es 200, la respuesta entera para el error
pub fn post_lineas(url: &str, cuerpo: &Valor) -> Result<Result<Lineas, Respuesta>, ErrorRed> {
    let c = cliente(None)?;
    let r = c
        .post(url)
        .header("Content-Type", "application/json")
        .body(json::escribir_compacto(cuerpo))
        .send()
        .map_err(de_reqwest)?;
    let estado = r.status().as_u16();
    if estado != 200 {
        let cuerpo = r.bytes().map_err(de_reqwest)?.to_vec();
        return Ok(Err(Respuesta { estado, cuerpo, link: String::new() }));
    }
    Ok(Ok(Lineas { lector: BufReader::new(r) }))
}
