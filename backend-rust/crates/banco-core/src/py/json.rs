//! `json.dumps` / `json.loads` de Python con su formato por defecto: separadores ", " y ": ", claves en el
//! orden de inserción, `ensure_ascii` (\uXXXX con pares sustitutos) y floats con `repr`. Las tablas del banco
//! guardan JSON así (unidades, cambios, conocimiento): el texto tiene que ser el mismo, no solo el valor.

use serde_json::Value;

use super::numero::repr_float;

/// `json.dumps(v)` con `ensure_ascii` elegible y sin sangría.
pub fn dumps(v: &Value, ensure_ascii: bool) -> String {
    let mut salida = String::new();
    escribir(&mut salida, v, ensure_ascii, None, 0);
    salida
}

/// `json.dumps(v, ensure_ascii=False, indent=n)`.
pub fn dumps_sangrado(v: &Value, ensure_ascii: bool, sangria: usize) -> String {
    let mut salida = String::new();
    escribir(&mut salida, v, ensure_ascii, Some(sangria), 0);
    salida
}

fn escribir(salida: &mut String, v: &Value, ascii: bool, sangria: Option<usize>, nivel: usize) {
    match v {
        Value::Null => salida.push_str("null"),
        Value::Bool(b) => salida.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                salida.push_str(&i.to_string());
            } else if let Some(u) = n.as_u64() {
                salida.push_str(&u.to_string());
            } else {
                let f = n.as_f64().unwrap_or(0.0);
                if f.is_nan() {
                    salida.push_str("NaN");
                } else if f.is_infinite() {
                    salida.push_str(if f > 0.0 { "Infinity" } else { "-Infinity" });
                } else {
                    salida.push_str(&repr_float(f));
                }
            }
        }
        Value::String(s) => cadena(salida, s, ascii),
        Value::Array(xs) => {
            if xs.is_empty() {
                salida.push_str("[]");
                return;
            }
            salida.push('[');
            for (i, x) in xs.iter().enumerate() {
                separador(salida, i, sangria, nivel + 1);
                escribir(salida, x, ascii, sangria, nivel + 1);
            }
            cierre(salida, sangria, nivel);
            salida.push(']');
        }
        Value::Object(m) => {
            if m.is_empty() {
                salida.push_str("{}");
                return;
            }
            salida.push('{');
            for (i, (k, x)) in m.iter().enumerate() {
                separador(salida, i, sangria, nivel + 1);
                cadena(salida, k, ascii);
                salida.push_str(": ");
                escribir(salida, x, ascii, sangria, nivel + 1);
            }
            cierre(salida, sangria, nivel);
            salida.push('}');
        }
    }
}

fn separador(salida: &mut String, i: usize, sangria: Option<usize>, nivel: usize) {
    match sangria {
        None => {
            if i > 0 {
                salida.push_str(", ");
            }
        }
        Some(n) => {
            if i > 0 {
                salida.push(',');
            }
            salida.push('\n');
            salida.push_str(&" ".repeat(n * nivel));
        }
    }
}

fn cierre(salida: &mut String, sangria: Option<usize>, nivel: usize) {
    if let Some(n) = sangria {
        salida.push('\n');
        salida.push_str(&" ".repeat(n * nivel));
    }
}

/// Una cadena JSON como la escribe Python.
pub fn cadena(salida: &mut String, s: &str, ascii: bool) {
    salida.push('"');
    for c in s.chars() {
        match c {
            '"' => salida.push_str("\\\""),
            '\\' => salida.push_str("\\\\"),
            '\n' => salida.push_str("\\n"),
            '\r' => salida.push_str("\\r"),
            '\t' => salida.push_str("\\t"),
            '\u{08}' => salida.push_str("\\b"),
            '\u{0c}' => salida.push_str("\\f"),
            _ if (c as u32) < 0x20 => salida.push_str(&format!("\\u{:04x}", c as u32)),
            _ if ascii && !(' '..='~').contains(&c) => {
                let n = c as u32;
                if n > 0xffff {
                    let v = n - 0x10000;
                    let alto = 0xd800 | ((v >> 10) & 0x3ff);
                    let bajo = 0xdc00 | (v & 0x3ff);
                    salida.push_str(&format!("\\u{:04x}\\u{:04x}", alto, bajo));
                } else {
                    salida.push_str(&format!("\\u{:04x}", n));
                }
            }
            _ => salida.push(c),
        }
    }
    salida.push('"');
}

/// `json.loads` (orden de claves conservado). Acepta NaN e Infinity como Python.
pub fn loads(texto: &str) -> Option<Value> {
    match serde_json::from_str::<Value>(texto) {
        Ok(v) => Some(v),
        Err(_) => {
            if texto.contains("NaN") || texto.contains("Infinity") {
                let arreglado = texto.replace("-Infinity", "-1e999").replace("Infinity", "1e999").replace("NaN", "null");
                serde_json::from_str::<Value>(&arreglado).ok()
            } else {
                None
            }
        }
    }
}

/// Una lista de cadenas como JSON de Python (`json.dumps(lista)`).
pub fn lista_cadenas(xs: &[String], ascii: bool) -> String {
    dumps(&Value::Array(xs.iter().map(|x| Value::String(x.clone())).collect()), ascii)
}

/// Lee una lista de cadenas guardada como JSON («[]» si no se puede).
pub fn leer_lista_cadenas(texto: Option<&str>) -> Vec<String> {
    match texto.and_then(loads) {
        Some(Value::Array(xs)) => xs
            .into_iter()
            .map(|x| match x {
                Value::String(s) => s,
                otro => otro.to_string(),
            })
            .collect(),
        _ => Vec::new(),
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;
    use serde_json::json;

    #[test]
    fn como_python() {
        assert_eq!(dumps(&json!(["a", "ñ", 1, 2.5, null]), true), "[\"a\", \"\\u00f1\", 1, 2.5, null]");
        assert_eq!(dumps(&json!({"b": 1, "a": [1.0]}), false), "{\"b\": 1, \"a\": [1.0]}");
        assert_eq!(dumps(&json!("😀"), true), "\"\\ud83d\\ude00\"");
    }
}
