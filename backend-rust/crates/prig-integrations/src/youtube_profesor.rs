//! El profesor de los videos de YouTube (`youtube_analisis.py`): el contexto del video para el modelo (la
//! transcripción repartida por todo el video si no cabe), los prompts del resumen estructurado y de los objetivos
//! didácticos, leer el JSON que devuelve el modelo y ordenar los objetivos. Los prompts salen iguales que en Python;
//! generar lo hace quien llama.

use crate::youtube::{hms, transcripcion};
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::path::Path;
use std::sync::LazyLock;

pub const PRESUPUESTO_TRANSCRIPCION: usize = 16000;

/// La transcripción como texto «[mm:ss] párrafo»: {texto, completa, duracion_segundos, segmentos}, o None si el video
/// no tiene subtítulos. Si no entra en el presupuesto, bloques de párrafos repartidos por todo el video.
pub fn subtitulos(raiz: &Path, video: &str, presupuesto: usize) -> Option<Mapa> {
    if video.is_empty() {
        return None;
    }
    let datos = transcripcion(raiz, video, "es", false);
    let segmentos: Vec<Mapa> = if datos.verdad("ok") {
        datos.lista("segmentos").unwrap_or(&[]).iter().filter_map(|s| if let Valor::Mapa(m) = s { Some(m.clone()) } else { None }).collect()
    } else {
        Vec::new()
    };
    if segmentos.is_empty() {
        return None;
    }
    let mut lineas: Vec<String> = segmentos
        .iter()
        .map(|s| format!("[{}] {}", hms(s.num_o("start", 0.0)), prig_plataforma::py::strip(&s.get("texto").map(Valor::texto_py).unwrap_or_default())))
        .collect();
    let total: usize = lineas.iter().map(|l| l.chars().count() + 1).sum();
    let completa = total <= presupuesto;
    if !completa {
        const POR_BLOQUE: usize = 3;
        let media = total as f64 / lineas.len() as f64;
        let n_bloques = ((presupuesto as f64 / (media * POR_BLOQUE as f64)) as usize).max(1);
        let paso = lineas.len() as f64 / n_bloques as f64;
        let mut elegidas = Vec::new();
        for b in 0..n_bloques {
            let ini = (b as f64 * paso) as usize;
            elegidas.extend(lineas.iter().skip(ini).take(POR_BLOQUE).cloned());
            if b + 1 < n_bloques {
                elegidas.push("[…]".to_string());
            }
        }
        lineas = elegidas;
    }
    let ultimo = segmentos.last().cloned().unwrap_or_default();
    let fin = [ultimo.get("end"), ultimo.get("start")].into_iter().flatten().find(|v| v.verdad()).and_then(Valor::num).unwrap_or(0.0);
    Some(
        Mapa::new()
            .con("texto", lineas.join("\n"))
            .con("completa", completa)
            .con("duracion_segundos", fin.trunc() as i64)
            .con("segmentos", segmentos.len()),
    )
}

/// Todo el texto del video: {texto, fuente (transcripcion | texto_usuario | solo_metadatos), transcripcion_completa,
/// duracion_segundos}
#[allow(clippy::too_many_arguments)]
pub fn preparar_contexto(
    raiz: &Path,
    video: &str,
    titulo: &str,
    canal: &str,
    duracion: &str,
    descripcion: &str,
    texto_usuario: &str,
    notas_usuario: &str,
) -> Mapa {
    let mut partes = vec![
        format!("VIDEO: «{titulo}»"),
        format!("CANAL: {}", if canal.is_empty() { "YouTube" } else { canal }),
        format!("DURACIÓN: {}", if duracion.is_empty() { "N/A" } else { duracion }),
    ];
    let mut fuente = "solo_metadatos";
    let (mut completa, mut duracion_segundos) = (false, 0i64);
    let strip = prig_plataforma::py::strip;
    if !strip(descripcion).is_empty() {
        partes.push(format!("\nDESCRIPCIÓN / TEMARIO OFICIAL DEL CURSO:\n{}", strip(descripcion)));
    }
    if !strip(notas_usuario).is_empty() {
        partes.push(format!("\nAPUNTES Y MARCAS DE TIEMPO DEL ALUMNO:\n{}", strip(notas_usuario)));
    }
    if !strip(texto_usuario).is_empty() {
        partes.push(format!("\nTEXTO / TRANSCRIPCIÓN PROPORCIONADA POR EL USUARIO:\n{}", strip(texto_usuario)));
        if strip(texto_usuario).chars().count() >= 100 {
            fuente = "texto_usuario";
        }
    }
    if fuente != "texto_usuario" {
        if let Some(s) = subtitulos(raiz, video, PRESUPUESTO_TRANSCRIPCION) {
            fuente = "transcripcion";
            completa = s.verdad("completa");
            duracion_segundos = s.get("duracion_segundos").and_then(Valor::num).unwrap_or(0.0) as i64;
            let aviso = if completa {
                ""
            } else {
                " (EXTRACTOS repartidos por todo el video; «[…]» marca los saltos; los minutos entre corchetes son los reales)"
            };
            partes.push(format!("\nTRANSCRIPCIÓN DE SUBTÍTULOS DEL VIDEO{aviso}:\n{}", s.valor("texto").texto_py()));
        }
    }
    if fuente == "solo_metadatos" {
        partes.push(
            "\n(ATENCIÓN: este video no tiene transcripción disponible. Trabaja SOLO con el título, la descripción y los \
apuntes; no inventes contenidos, ejemplos ni minutos concretos que no estén en ese material.)"
                .into(),
        );
    }
    Mapa::new()
        .con("texto", partes.join("\n\n"))
        .con("fuente", fuente)
        .con("transcripcion_completa", completa)
        .con("duracion_segundos", duracion_segundos)
}

/// Los motores devuelven «[Error …]» como texto: eso no es un resumen ni una traducción
pub fn error_del_motor(texto: &str) -> Option<String> {
    let t = prig_plataforma::py::strip(texto);
    t.starts_with("[Error").then(|| t.to_string())
}

static PIENSA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)<think>[\s\S]*?</think>").unwrap());
static BLOQUE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)```(?:json)?\s*([\s\S]*?)\s*```").unwrap());

/// Quita los bloques `<think>` y los espacios de los extremos
pub fn sin_pensamiento(t: &str) -> String {
    prig_plataforma::py::strip(&PIENSA.replace_all(t, "")).to_string()
}

/// El primer objeto o lista JSON de la respuesta
pub fn extraer_json(texto: &str) -> Option<Valor> {
    if texto.is_empty() {
        return None;
    }
    let t = sin_pensamiento(texto);
    let leer = |s: &str| prig_plataforma::json::leer(s).ok();
    if let Some(m) = BLOQUE.captures(&t) {
        if let Some(v) = leer(prig_plataforma::py::strip(&m[1])) {
            return Some(v);
        }
    }
    if let Some(v) = leer(&t) {
        return Some(v);
    }
    for (a, b) in [('{', '}'), ('[', ']')] {
        if let (Some(i), Some(j)) = (t.find(a), t.rfind(b)) {
            if j > i {
                if let Some(v) = leer(&t[i..=j]) {
                    return Some(v);
                }
            }
        }
    }
    None
}

pub const SISTEMA_RESUMEN: &str = "Eres un DOCENTE EXPERTO EN CIENCIAS DE LA COMPUTACIÓN Y PROGRAMACIÓN de Prig IDE.
Tu misión es analizar el material de un video educativo y generar un RESUMEN TÉCNICO ESTRUCTURADO en español para programadores.

Debes responder ÚNICAMENTE con un objeto JSON válido (sin markdown fuera del JSON) con esta estructura exacta:
{
  \"resumen_ejecutivo\": \"Explicación clara, concisa y rigurosa de los conceptos esenciales...\",
  \"puntos_clave\": [\"Idea o regla 1\", \"Idea o regla 2\", \"Idea o regla 3\"],
  \"snippets_codigo\": [
    {\"titulo\": \"Uso canónico\", \"lenguaje\": \"python o cpp\", \"codigo\": \"código aquí...\", \"explicacion\": \"breve nota\"}
  ],
  \"glosario\": [
    {\"termino\": \"Concepto 1\", \"definicion\": \"Definición didáctica...\"}
  ],
  \"conclusiones\": \"Cómo aplicar lo aprendido en proyectos reales.\"
}
Todo debe salir del material dado (transcripción, descripción, apuntes): no inventes temas, código ni librerías que el video no trate. Los snippets ilustran lo que se enseña en ESTE video. Sé riguroso y pedagógico.";

pub fn prompt_resumen(titulo: &str, canal: &str, duracion: &str, contexto: &str, categoria: &str) -> String {
    format!(
        "Analiza la siguiente información de la clase «{titulo}» ({canal}, duración: {duracion}, tema: {categoria}).\n\n{contexto}\n\nGenera el JSON con el resumen estructurado, puntos clave, snippets de código y glosario en español."
    )
}

/// El resumen a partir de la respuesta: el JSON, o la respuesta tal cual en el resumen ejecutivo
pub fn resumen_de(respuesta: &str, titulo: &str) -> Valor {
    match extraer_json(respuesta) {
        Some(Valor::Mapa(m)) if !m.is_empty() => Valor::Mapa(m),
        _ => {
            let r = prig_plataforma::py::strip(respuesta);
            Valor::Mapa(
                Mapa::new()
                    .con("resumen_ejecutivo", if r.is_empty() { "No se pudo formatear el resumen estructurado." } else { r })
                    .con("puntos_clave", Valor::Lista(vec![Valor::Texto(format!("Estudio de {titulo}"))]))
                    .con("snippets_codigo", Valor::Lista(vec![]))
                    .con("glosario", Valor::Lista(vec![]))
                    .con("conclusiones", "Continúa con la práctica activa para fijar los conocimientos."),
            )
        }
    }
}

pub const SISTEMA_OBJETIVOS: &str = "Eres un DISEÑADOR CURRICULAR Y PEDAGÓGICO DE PROGRAMACIÓN de Prig IDE.
Tu misión es dividir el contenido de un video educativo en entre 3 y 6 OBJETIVOS DE APRENDIZAJE progresivos, secuenciales y prácticos (micro-metas).

Debes responder ÚNICAMENTE con un objeto JSON válido (sin texto antes ni después) con esta forma:
{
  \"objetivos\": [
    {
      \"id\": \"obj_1\",
      \"numero\": 1,
      \"titulo\": \"<verbo + tema concreto de ESTE video>\",
      \"descripcion\": \"<lo que el alumno debe saber y saber hacer, según lo que se ve en el video>\",
      \"inicio_timestamp\": \"<mm:ss o h:mm:ss donde empieza en la transcripción>\",
      \"fin_timestamp\": \"<mm:ss o h:mm:ss donde termina>\",
      \"inicio_segundos\": <segundos de inicio_timestamp>,
      \"conceptos\": [\"<concepto del video>\", \"<otro>\"],
      \"dificultad\": \"principiante | intermedio | avanzado\",
      \"criterio_evaluacion\": \"Qué debe ser capaz de implementar o responder para darlo por superado.\"
    }
  ]
}
REGLAS:
0. Todo sale del material dado (transcripción, descripción, apuntes). Nunca copies los marcadores <…> de la plantilla ni inventes temas que no estén en el video.
1. Los timestamps deben ser crecientes, dentro de la duración del video, y tomados de los minutos [mm:ss] de la transcripción.
2. Cada objetivo debe ser evaluable con un ejercicio de código o comprensión.
3. La redacción debe ser en español neutro y motivador.";

pub fn prompt_objetivos(titulo: &str, canal: &str, duracion: &str, contexto: &str, nivel: &str, categoria: &str) -> String {
    format!(
        "Divide en 3 a 6 objetivos didácticos la clase «{titulo}» ({canal}, duración: {duracion}, nivel: {nivel}, categoría: {categoria}).\n\n{contexto}\n\nDevuelve el JSON con la lista de objetivos cronometrados."
    )
}

/// «1:02:30», «12:34», «90» o 90 → segundos
fn a_segundos(ts: Option<&Valor>) -> Option<i64> {
    match ts {
        Some(Valor::Entero(n)) => return Some(*n as i64),
        Some(Valor::Real(x)) => return Some(x.trunc() as i64),
        Some(Valor::Bool(b)) => return Some(*b as i64),
        _ => {}
    }
    let texto = match ts {
        Some(v) if v.verdad() => v.texto_py(),
        _ => String::new(),
    };
    let mut total = 0i64;
    for p in prig_plataforma::py::strip(&texto).split(':') {
        let x: f64 = prig_plataforma::py::strip(p).parse().ok().filter(|x: &f64| x.is_finite())?;
        total = total * 60 + x.trunc() as i64;
    }
    Some(total)
}

/// Los objetivos de la respuesta, en orden: ids y números, segundos de inicio crecientes y dentro del video. Error:
/// el mensaje del ValueError de Python.
pub fn objetivos_de(respuesta: &str, duracion_segundos: i64) -> Result<Vec<Valor>, String> {
    let mut datos = extraer_json(respuesta);
    if let Some(Valor::Mapa(m)) = &datos {
        if let Some(Valor::Lista(l)) = m.get("objetivos") {
            datos = Some(Valor::Lista(l.clone()));
        }
    }
    let lista = match datos {
        Some(Valor::Lista(l)) if !l.is_empty() => l,
        _ => return Err("El modelo no devolvió los objetivos en JSON. Vuelve a intentarlo o elige otro modelo.".into()),
    };
    let mut salida: Vec<Valor> = Vec::new();
    let mut previo = 0i64;
    for o in lista {
        let Valor::Mapa(mut o) = o else { continue };
        let titulo = match o.get("titulo") {
            Some(v) if v.verdad() => v.texto_py(),
            _ => String::new(),
        };
        if prig_plataforma::py::strip(&titulo).is_empty() {
            continue;
        }
        let mut ini = a_segundos(o.get("inicio_timestamp"));
        if ini.is_none() {
            ini = a_segundos(o.get("inicio_segundos"));
        }
        let mut fin = a_segundos(o.get("fin_timestamp"));
        if duracion_segundos != 0 {
            ini = ini.map(|i| i.min(duracion_segundos));
            fin = fin.map(|f| f.min(duracion_segundos));
        }
        let ini = ini.unwrap_or(previo).max(previo);
        let fin = fin.filter(|f| *f >= ini);
        let n = salida.len() + 1;
        o.poner("id", format!("obj_{n}"));
        o.poner("numero", n);
        o.poner("inicio_segundos", ini);
        o.poner("inicio_timestamp", hms(ini as f64));
        o.poner("fin_timestamp", fin.map(|f| hms(f as f64)).unwrap_or_default());
        if !matches!(o.get("conceptos"), Some(Valor::Lista(_))) {
            let c = match o.get("conceptos") {
                Some(v) if v.verdad() => vec![Valor::Texto(v.texto_py())],
                _ => Vec::new(),
            };
            o.poner("conceptos", Valor::Lista(c));
        }
        salida.push(Valor::Mapa(o));
        previo = ini;
    }
    if salida.is_empty() {
        return Err("El modelo devolvió objetivos vacíos. Vuelve a intentarlo o elige otro modelo.".into());
    }
    Ok(salida)
}

/// El prompt para traducir y explicar un fragmento de la clase
pub fn prompt_traducir(texto: &str) -> String {
    format!(
        "Traduce y explica de forma clara, didáctica y rigurosa el siguiente fragmento técnico de una clase de programación al español. Mantén intactos nombres de funciones, librerías, términos en código y palabras reservadas.\n\nTEXTO ORIGINAL:\n«{}»\n\nResponde directamente con la traducción explicada, fluida y precisa:",
        prig_plataforma::py::strip(texto)
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn objetivos_crecientes_y_dentro_del_video() {
        let r = r#"```json
{"objetivos": [{"titulo": "Uno", "inicio_timestamp": "1:30", "fin_timestamp": "0:10", "conceptos": "listas"},
 {"titulo": "", "inicio_timestamp": "2:00"},
 {"titulo": "Dos", "inicio_timestamp": "0:20", "fin_timestamp": "99:00"}]}
```"#;
        let o = objetivos_de(r, 300).unwrap();
        assert_eq!(o.len(), 2);
        let (a, b) = match (&o[0], &o[1]) {
            (Valor::Mapa(a), Valor::Mapa(b)) => (a.clone(), b.clone()),
            _ => panic!(),
        };
        assert_eq!((a.valor("inicio_segundos"), a.valor("fin_timestamp")), (&Valor::Entero(90), &Valor::Texto(String::new())));
        assert_eq!(a.valor("conceptos"), &Valor::Lista(vec![Valor::Texto("listas".into())]));
        assert_eq!((b.valor("id"), b.valor("inicio_segundos"), b.valor("fin_timestamp")), (&Valor::Texto("obj_2".into()), &Valor::Entero(90), &Valor::Texto("05:00".into())));
        assert!(objetivos_de("nada", 0).is_err());
    }
}
