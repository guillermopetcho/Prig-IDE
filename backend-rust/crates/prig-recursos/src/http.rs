//! Peticiones HTTP con espera (las de `requests` en el Python de recursos): JSON de ida y de vuelta con el mismo
//! lector y escritor que Python (`json.rs`), así las claves llegan en su orden.

use crate::json;
use crate::valor::Valor;
use std::time::Duration;

fn cliente(segundos: f64) -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs_f64(segundos))
        .build()
        .map_err(|e| e.to_string())
}

fn respuesta(r: reqwest::blocking::Response) -> Result<Valor, String> {
    let texto = r.text().map_err(|e| e.to_string())?;
    json::leer(&texto)
}

/// GET que devuelve JSON (como `requests.get(url, timeout).json()`: no mira el código de estado)
pub fn get_json(url: &str, segundos: f64) -> Result<Valor, String> {
    let r = cliente(segundos)?.get(url).send().map_err(|e| e.to_string())?;
    respuesta(r)
}

/// GET que devuelve JSON y falla si la respuesta no es 2xx (como `urllib.request.urlopen`)
pub fn get_json_ok(url: &str, segundos: f64) -> Result<Valor, String> {
    let r = cliente(segundos)?.get(url).send().map_err(|e| e.to_string())?;
    if !r.status().is_success() {
        return Err(format!("HTTP Error {}", r.status().as_u16()));
    }
    respuesta(r)
}

/// POST con un cuerpo JSON que devuelve JSON (como `requests.post(url, json=cuerpo, timeout).json()`)
pub fn post_json(url: &str, cuerpo: &Valor, segundos: f64) -> Result<Valor, String> {
    let r = cliente(segundos)?
        .post(url)
        .header("Content-Type", "application/json")
        .body(json::escribir_compacto(cuerpo))
        .send()
        .map_err(|e| e.to_string())?;
    respuesta(r)
}
