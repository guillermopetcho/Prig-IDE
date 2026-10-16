//! Lo común de los profesores de Prig (`desafios/tutor.py` y los ayudantes de app.py): qué modelo usar para cada
//! tarea (el pedido, el elegido para ese rol en Configuración o el del tutor), con qué motor (Ollama en local o
//! Gemini en la nube si el nombre empieza por «gemini:»), y `flujo`: los eventos de lo que escribe el modelo, sin su
//! razonamiento, con los errores del motor explicados.

use crate::gemini;
use crate::generar::{self, PedidoGenerar};
use crate::motor;
use crate::vivo::Cancelar;
use prig_recursos::valor::{Mapa, Valor};
use regex::Regex;
use std::path::Path;
use std::sync::OnceLock;

/// El campo de la configuración de IA de cada rol
pub fn campo_de_rol(rol: &str) -> &str {
    match rol {
        "codigo" => "modelo_codigo",
        "explicar" | "tutor" => "modelo_explicar",
        "autocompletar" => "modelo_autocompletar",
        otro => otro,
    }
}

/// `ai_engine.modelo_para(rol)`: el elegido para ese rol en la configuración, o None (automático)
pub fn modelo_para(rol: &str) -> Option<String> {
    motor::config_ia().get(campo_de_rol(rol)).filter(|v| !v.es_nulo()).map(Valor::texto_py).map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
}

/// `_modelo_desafios`: el pedido; si no, el del rol en Configuración; si no, el del tutor
pub fn modelo_desafios(modelo: Option<&str>, rol: Option<&str>) -> String {
    let cfg = motor::config_ia();
    let tutor = ["agent1_model", "agent2_model"]
        .iter()
        .find_map(|k| cfg.get(*k).filter(|v| v.verdad()).map(Valor::texto_py))
        .unwrap_or_else(|| "qwen2.5-coder:7b".into());
    if let Some(m) = modelo.filter(|m| !m.is_empty()) {
        return m.to_string();
    }
    match rol {
        Some(r) => modelo_para(r).unwrap_or(tutor),
        None => tutor,
    }
}

/// Con qué genera un profesor
#[derive(Debug, Clone, PartialEq)]
pub enum Motor {
    Ollama,
    Gemini,
}

/// `_motor_desafios`: (motor, nombre que se le pasa). Error: el mensaje del 400 (Gemini sin conectar)
pub fn motor_desafios(modelo: Option<&str>, rol: Option<&str>) -> Result<(Motor, String), String> {
    let nombre = modelo_desafios(modelo, rol);
    if let Some(n) = nombre.strip_prefix(gemini::PREFIJO) {
        if gemini::clave_actual().0.is_none() {
            return Err("Gemini no está conectado: conéctalo o elige un modelo local.".into());
        }
        return Ok((Motor::Gemini, n.to_string()));
    }
    Ok((Motor::Ollama, nombre))
}

/// `generate_response` del motor que toque: los eventos de `generar::generar` (texto con `token`, pensando, stats).
/// Con Ollama, siempre con el gobernador térmico (el `ai_engine.gobernador` de Python).
#[allow(clippy::too_many_arguments)]
pub fn generar_con(
    raiz: &Path,
    motor: &Motor,
    nombre: &str,
    prompt: &str,
    sistema: &str,
    think: Option<bool>,
    opciones: Mapa,
    con_pensamiento: bool,
    uso: Option<&str>,
    cancelar: &Cancelar,
    emitir: &mut dyn FnMut(Mapa),
) {
    match motor {
        Motor::Gemini => gemini::generar(prompt, nombre, sistema, Some(&opciones), cancelar, emitir),
        Motor::Ollama => {
            let p = PedidoGenerar {
                prompt: prompt.into(),
                modelo: nombre.into(),
                sistema: sistema.into(),
                opciones: Some(opciones),
                think,
                con_pensamiento,
                uso: uso.map(String::from),
                gobernador: true,
            };
            generar::generar(raiz, &p, cancelar, emitir)
        }
    }
}

/// `<think>…</think>` (o hasta el final), sin distinguir mayúsculas
pub fn pensamiento() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?is)<think(?:ing)?>.*?(?:</think(?:ing)?>|$)\s*").expect("regex"))
}

/// El mensaje para el usuario si el texto es un error del motor (`_error_de_modelo`)
pub fn error_de_modelo(texto: &str) -> Option<String> {
    let t = texto.trim();
    if let Some(r) = t.strip_prefix("[Error Gemini:") {
        return Some(r.trim_end_matches(']').trim().to_string());
    }
    if t.starts_with("[Error Ollama") || t.starts_with("[Error de conexión") {
        return Some(crate::gestor::explicar_error_motor(t).map(String::from).unwrap_or_else(|| t.trim_matches(|c| c == '[' || c == ']').to_string()));
    }
    None
}

/// `flujo`: eventos `{"tipo": "texto", "delta"}` con lo que escribe el modelo (sin su pensamiento) y
/// `{"tipo": "pensando"}` mientras piensa; devuelve el texto completo. Error: el del motor, explicado
/// (el ErrorDesafio de Python).
#[allow(clippy::too_many_arguments)]
pub fn flujo(
    raiz: &Path,
    motor: &Motor,
    nombre: &str,
    prompt: &str,
    sistema: &str,
    temperatura: f64,
    pensar: bool,
    cancelar: &Cancelar,
    emitir: &mut dyn FnMut(Mapa),
) -> Result<String, String> {
    let mut texto = String::new();
    let mut trozos = 0usize;
    let mut pensando = false;
    let (mut visible, mut emitido) = (String::new(), 0usize);
    let mut error = None;
    generar_con(
        raiz,
        motor,
        nombre,
        prompt,
        sistema,
        Some(pensar),
        Mapa::new().con("temperature", temperatura),
        true,
        Some("tutor"),
        cancelar,
        &mut |e| {
            if error.is_some() {
                return;
            }
            match e.texto("t") {
                Some("pensando") => pensando = true,
                Some("texto") => {
                    let trozo = e.valor("v").texto_py();
                    texto.push_str(&trozo);
                    trozos += 1;
                    if trozos == 1 {
                        if let Some(m) = error_de_modelo(&trozo) {
                            error = Some(m);
                            return;
                        }
                    }
                    if pensando {
                        pensando = false;
                        emitir(Mapa::new().con("tipo", "pensando"));
                    }
                    if e.verdad("token") {
                        visible.push_str(&trozo);
                        // Las etiquetas <think> pueden llegar partidas entre trozos: se limpia lo acumulado y se
                        // retiene un posible comienzo de etiqueta al final
                        let mut limpio = pensamiento().replace_all(&visible, "").into_owned();
                        if let Some(corte) = limpio.rfind('<') {
                            let cola: String = limpio[corte..].chars().take(6).collect();
                            if "<think".starts_with(&cola) && !limpio[corte..].contains('>') {
                                limpio.truncate(corte);
                            }
                        }
                        let n = limpio.chars().count();
                        if n > emitido {
                            let delta: String = limpio.chars().skip(emitido).collect();
                            emitir(Mapa::new().con("tipo", "texto").con("delta", delta));
                            emitido = n;
                        }
                    }
                }
                _ => {}
            }
        },
    );
    if let Some(m) = error {
        return Err(m);
    }
    Ok(pensamiento().replace_all(&texto, "").trim().to_string())
}

/// `tutor.generar`: el texto entero (sin razonar), con un formato opcional («json»)
#[allow(clippy::too_many_arguments)]
pub fn generar_texto(
    raiz: &Path,
    motor: &Motor,
    nombre: &str,
    prompt: &str,
    sistema: &str,
    temperatura: f64,
    formato: Option<&str>,
    cancelar: &Cancelar,
    mut on_token: Option<&mut dyn FnMut(&str)>,
) -> Result<String, String> {
    let mut opciones = Mapa::new().con("temperature", temperatura).con("num_predict", 4096);
    if let Some(f) = formato.filter(|f| !f.is_empty()) {
        opciones.poner("format", f);
    }
    let mut texto = String::new();
    generar_con(raiz, motor, nombre, prompt, sistema, Some(false), opciones, false, Some("tutor"), cancelar, &mut |e| {
        if e.texto("t") == Some("texto") {
            let v = e.valor("v").texto_py();
            if e.verdad("token") {
                if let Some(f) = on_token.as_mut() {
                    f(&v);
                }
            }
            texto.push_str(&v);
        }
    });
    if let Some(m) = error_de_modelo(&texto) {
        return Err(m);
    }
    Ok(pensamiento().replace_all(&texto, "").trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn errores_del_motor() {
        assert_eq!(error_de_modelo("[Error Gemini: sin cuota.]").as_deref(), Some("sin cuota."));
        assert_eq!(error_de_modelo("[Error Ollama: 500: x]").as_deref(), Some("Error Ollama: 500: x"));
        assert!(error_de_modelo("[Error Ollama: llama-server binary not found]").unwrap().contains("incompleto"));
        assert_eq!(error_de_modelo("hola"), None);
    }

    #[test]
    fn quita_el_pensamiento() {
        assert_eq!(pensamiento().replace_all("<think>a\nb</think>\n hola", ""), "hola");
        assert_eq!(pensamiento().replace_all("x<THINKING>sin cerrar", ""), "x");
    }
}

#[cfg(test)]
mod tests_roles {
    use super::*;

    #[test]
    fn cada_rol_su_campo() {
        // Kaggle y GitHub explican con «explicar»; los desafíos programan con «codigo»
        assert_eq!(campo_de_rol("explicar"), "modelo_explicar");
        assert_eq!(campo_de_rol("tutor"), "modelo_explicar");
        assert_eq!(campo_de_rol("codigo"), "modelo_codigo");
        assert_eq!(campo_de_rol("autocompletar"), "modelo_autocompletar");
    }
}
