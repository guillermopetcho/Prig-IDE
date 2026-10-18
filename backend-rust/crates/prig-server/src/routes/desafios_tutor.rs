//! El tutor de los desafíos (`desafios/tutor.py` y sus rutas de app.py): la caja de razonamiento, revisar el plan,
//! las pistas, la reflexión, traducir, el chat, analizar una propuesta y evaluar una solución con su salida. Los
//! prompts, tal cual los de Python. Responden en NDJSON como los profesores (`profesor::ndjson_trabajo`): los
//! eventos del modelo y al final `{"tipo": "fin", "resultado"}` o `{"tipo": "error", "mensaje"}`; evaluar la
//! salida, en JSON.

use axum::{
    body::Bytes,
    extract::{Path as Ruta, State},
    http::StatusCode,
    response::Response,
};
use prig_aprendizaje::desafios::{self as d, ErrorObtener};
use prig_ia::tutor::{self, Motor};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::sync::OnceLock;

use crate::routes::desafios::{carpeta_base, comprobar, error_500, error_obtener, mapa_de};
use crate::routes::profesor::{mensajes_con_referencias, ndjson_trabajo};
use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

// =========================================================================== el texto de los prompts

fn corta(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

/// `f"{d.get(k)}"`
fn campo(d: &Mapa, k: &str) -> String {
    d.get(k).map(Valor::texto_py).unwrap_or_else(|| "None".into())
}

/// `x or y`: el primero que no sea falso
fn o<'a>(a: Option<&'a Valor>, b: &'a Valor) -> &'a Valor {
    match a {
        Some(v) if v.verdad() => v,
        _ => b,
    }
}

/// `_paginas_texto`: cada página con su nombre (y su descripción), recortado a `limite` caracteres
fn paginas_texto(paginas: &[Valor], limite: usize) -> Result<String, String> {
    let mut partes = Vec::new();
    for p in paginas {
        let Valor::Mapa(p) = p else { return Err("list indices must be integers or slices, not str".into()) };
        let nombre = p.get("nombre").ok_or("'nombre'")?.texto_py();
        let desc = match p.get("descripcion") {
            Some(Valor::Texto(t)) if !t.is_empty() => format!(" ({t})"),
            Some(v) if v.verdad() => return Err(format!("can only concatenate str (not \"{}\") to str", py::tipo(v))),
            _ => String::new(),
        };
        let contenido = match p.get("contenido") {
            Some(v) if v.verdad() => v.texto_py(),
            _ => String::new(),
        };
        partes.push(format!("--- página {nombre}{desc} ---\n{contenido}"));
    }
    let texto = partes.join("\n");
    Ok(if texto.chars().count() <= limite { texto } else { corta(&texto, limite) + "\n…(recortado)" })
}

fn lista<'a>(v: Option<&'a Valor>) -> &'a [Valor] {
    match v {
        Some(Valor::Lista(l)) => l,
        _ => &[],
    }
}

/// `(d.get("privado") or {}).get("referencia") or []`
fn referencia(d: &Mapa) -> Vec<Valor> {
    lista(mapa_de(d.get("privado")).get("referencia")).to_vec()
}

/// `_enunciado`: el traducido si lo hay, hasta 6000 caracteres
fn enunciado(d: &Mapa) -> String {
    let vacio = Valor::Texto(String::new());
    corta(&o(d.get("enunciado_es"), o(d.get("enunciado"), &vacio)).texto_py(), 6000)
}

// =========================================================================== los prompts

const SISTEMA_RAZONAR: &str = "Eres un profesor de RESOLUCIÓN DE PROBLEMAS. Enseñas CÓMO PENSAR un desafío de
programación antes de escribir código. NO lo resuelves.

PROHIBIDO escribir código en cualquier lenguaje (ni Python, ni pseudocódigo con sintaxis de
programación). Usa frases en español, listas y, si ayuda, tablas pequeñas.

Escribe EXACTAMENTE estas seis secciones, con estos encabezados:
## 1. Qué me piden
Reformula el problema con otras palabras: datos de entrada, resultado esperado y restricciones.
## 2. Ejemplos a mano y casos límite
Resuelve a mano un ejemplo pequeño mostrando cada paso, y lista los casos límite que hay que cuidar.
## 3. Descomponer el problema
Divide el problema en subproblemas pequeños. Si hay varias páginas, qué responsabilidad tiene cada una.
## 4. Qué estrategia usar y por qué
Qué patrón o técnica encaja (recorrido, acumulador, dos punteros, recursión, diccionario de
conteo, ordenar primero, divide y vencerás…), por qué, y qué alternativa descartas y por qué.
## 5. El algoritmo paso a paso
Pasos numerados en lenguaje natural, sin sintaxis de programación.
## 6. Cómo comprobarlo y cuánto cuesta
Cómo verificar que funciona (qué probar) y su coste en tiempo y memoria explicado con palabras.

Empieza cada sección con una o dos PREGUNTAS que el alumno debería hacerse, en cursiva.";

const SISTEMA_PLAN: &str = "Eres un tutor socrático. El alumno escribió CÓMO piensa resolver un desafío antes de programar. \
Valóralo en español, en menos de 160 palabras y con esta estructura:\n\
**Bien pensado:** lo que está bien.\n**Falta considerar:** el caso o paso que se le escapa, en forma de pregunta.\n\
**Siguiente paso:** una acción concreta.\n\
Sin código. No reveles la solución aunque la conozcas; si el plan es incorrecto, guíale con preguntas.";

const NIVELES_PISTA: [(&str, &str); 3] = [
    ("Pista conceptual", "Da UNA pista CONCEPTUAL: qué idea o estructura resuelve esto. Sin código. Máximo 2 frases."),
    ("Pista de estructura", "Describe los PASOS en una lista breve, en lenguaje natural, sin escribir Python. Máximo 5 líneas."),
    (
        "Pista concreta",
        "Señala en el código del alumno la línea o parte que falla o falta, y muestra SOLO la expresión clave \
que le falta con una frase de explicación. No entregues la solución completa.",
    ),
];

const SISTEMA_REFLEXION: &str = "Eres un mentor de programación. El alumno YA resolvió el desafío. Haz una revisión breve en español \
(menos de 250 palabras) con estas secciones:\n\
**Lo que hiciste bien**\n**Coste**: tiempo y memoria de SU solución, explicado.\n\
**Una mejora**: legibilidad o eficiencia, con un fragmento corto si ayuda.\n\
**Otra forma de pensarlo**: una estrategia distinta (compárala con la de referencia si es otra), sin el código completo.";

const SISTEMA_TRADUCIR: &str = "Traduce al español el texto en markdown que te da el usuario. Conserva EXACTAMENTE: bloques de código, \
nombres de funciones, variables y archivos, fórmulas entre $ y enlaces. Devuelve solo la traducción.";

const SISTEMA_CHAT_DESAFIO: &str = "Eres el tutor de un desafío de programación en Python. Responde dudas en español, breve (menos de 150 \
palabras): explica conceptos, interpreta errores y guía con preguntas. NUNCA des la solución completa \
ni reescribas la función entera; como mucho una línea o expresión si el alumno ya lo intentó.";

const SISTEMA_CHAT: &str = "Eres el entrenador de desafíos de Prig. Ayudas al alumno a decidir QUÉ practicar. Conversa en español, breve \
(menos de 120 palabras). Si no sabes su nivel o el tema, pregúntalo. Propón 2 o 3 ideas de desafío concretas \
(qué habría que construir, no cómo). Cuando esté decidido, dile que pulse «Crear desafío» o «Buscar en \
internet». No escribas soluciones.";

const SISTEMA_EVALUAR_SALIDA: &str = "Eres un TUTOR Y EVALUADOR EXPERTO DE PROGRAMACIÓN.
Tu misión es evaluar la solución del alumno para un desafío de programación.
Debes analizar detalladamente:
1. El CÓDIGO que programó el alumno.
2. La SALIDA que produjo al ejecutarse (código de salida, stdout, stderr).
3. El resultado de las pruebas automatizadas (si las hay).

Devuelve ÚNICAMENTE un objeto JSON válido (sin markdown ni bloques ```json alrededor) con este formato exacto:
{
  \"aprobado\": true o false,
  \"calificacion\": número entero del 1 al 10,
  \"estado\": \"aprobado\" | \"parcial\" | \"error\",
  \"resumen\": \"Resumen conciso en 1 o 2 oraciones del veredicto.\",
  \"analisis_salida\": \"Qué imprimió el programa y por qué cumple o no con lo que pide el enunciado.\",
  \"analisis_codigo\": \"Calidad, lógica, buenas prácticas, legibilidad y posibles casos límite.\",
  \"consejos\": [\"Consejo 1...\", \"Consejo 2...\"]
}

REGLAS DE EVALUACIÓN:
1. 'aprobado' es true SOLO si el código corre limpiamente (exit_code 0 y sin excepciones no controladas) Y la salida/lógica cumple satisfactoriamente con el objetivo del desafío.
2. Si el proceso falló con errores de sintaxis, excepciones (Traceback) o la salida no cumple lo pedido, 'aprobado' debe ser false y 'estado' debe ser 'error'.
3. Si el alumno casi lo logra pero le faltó un caso o tuvo un fallo menor, califica con 6-7, 'aprobado' es false y 'estado' es 'parcial'.
4. Si la solución es excelente, califica con 9-10 y 'aprobado' es true.
5. Sé pedagógico, motivador y claro en español.";

fn sistema_propuesta(lenguaje: &str, nivel: &str) -> String {
    let es_cpp = lenguaje.to_lowercase() == "cpp";
    let etiqueta = if es_cpp { "C++ (C++20)" } else { "Python 3" };
    format!(
        "Eres un ingeniero senior y especialista en algoritmia y estructuras de datos para {etiqueta}.\n\
El usuario te presenta una propuesta técnica o tema a nivel {nivel}.\n\
Tu objetivo es analizar su propuesta y devolver exactamente lo que el usuario pide o necesita en Markdown conciso y estructurado:\n\n\
1. **Evaluación de la Propuesta**: Viabilidad técnica, pertinencia algorítmica y enfoque general.\n\
2. **Complejidad y Rendimiento**: Cota asintótica Big-O esperada de tiempo y espacio (O(N), O(log N), etc.) y cómo optimizarla.\n\
3. **Casos Críticos y de Borde**: Casos extremos que deben considerarse.\n\
4. **Recomendaciones de Implementación**: Estructuras de datos óptimas y mejores prácticas idiomáticas para {}.\n\n\
Responde en español de forma directa, sin introducciones innecesarias.",
        if es_cpp { "C++20 (STL, semántica de movimiento, gestión de memoria RAII)" } else { "Python 3 (estructuras estándar, generadores, legibilidad)" }
    )
}

// =========================================================================== la caja de razonamiento

fn re_codigo() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?s)```[\w+-]*\n(.*?)```").expect("regex"))
}

fn re_parece_codigo() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| {
        Regex::new(r"(?m)(^|\n)\s*(def |class |import |from \w+ import|return\b|for \w+ in |while .+:|print\(|\w+\s*=\s*\[|#include|std::|template\s*<|cout\s*<<|int\s+main\s*\()")
            .expect("regex")
    })
}

/// `_sin_codigo`: lo que parezca código se retira de la caja de razonamiento
fn sin_codigo(texto: &str) -> String {
    re_codigo()
        .replace_all(texto, |c: &regex::Captures| {
            if re_parece_codigo().is_match(&c[1]) {
                "*(Aquí iba código: la caja de razonamiento no da la solución.)*".to_string()
            } else {
                c[0].to_string()
            }
        })
        .into_owned()
}

/// `separar_pasos`: las secciones «## » del texto; con menos de tres, todo en una
fn separar_pasos(texto: &str) -> Vec<Mapa> {
    static ENCABEZADO: OnceLock<Regex> = OnceLock::new();
    static NUMERO: OnceLock<Regex> = OnceLock::new();
    let encabezado = ENCABEZADO.get_or_init(|| Regex::new(r"(?m)^##\s+").expect("regex"));
    let numero = NUMERO.get_or_init(|| Regex::new(r"^\d+[.)]\s*").expect("regex"));
    let texto = sin_codigo(&tutor::pensamiento().replace_all(texto, ""));
    let mut pasos = Vec::new();
    for t in encabezado.split(&texto).skip(1) {
        let (titulo, cuerpo) = t.split_once('\n').unwrap_or((t, ""));
        let titulo = numero.replace(py::strip(titulo), "").trim_matches(|c| c == '#' || c == ' ').to_string();
        if !py::strip(cuerpo).is_empty() {
            let titulo = if titulo.is_empty() { format!("Paso {}", pasos.len() + 1) } else { titulo };
            pasos.push(Mapa::new().con("titulo", titulo).con("contenido", py::strip(cuerpo)));
        }
    }
    if pasos.len() < 3 {
        let t = py::strip(&texto);
        return if t.is_empty() { Vec::new() } else { vec![Mapa::new().con("titulo", "Cómo pensar este desafío").con("contenido", t)] };
    }
    pasos
}

// =========================================================================== lo común de las rutas

pub(crate) const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const PAGINAS: Tipo = Tipo::Lista(&Tipo::Dict(&Tipo::Cualquiera));
const MENSAJES: Tipo = Tipo::Lista(&Tipo::Dict(&Tipo::Texto));

pub(crate) fn pedido(b: &Bytes, campos: &[(&str, &Tipo, bool)]) -> Result<Mapa, Response> {
    let m = cuerpo::modelo(b)?;
    cuerpo::tipados(&m, campos)
}

/// `req.modelo` (None si no vino o vino null)
pub(crate) fn opcional(c: &Mapa, k: &str) -> Option<String> {
    c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py)
}

/// `_desafio(desafios_almacen.obtener, id_)`
async fn obtener(id: String) -> Result<Mapa, Response> {
    let dir = carpeta_base().join("desafios");
    match tokio::task::spawn_blocking(move || d::obtener(&dir, &id)).await {
        Ok(Ok(Valor::Mapa(m))) => Ok(m),
        Ok(Err(e)) => Err(error_obtener(e)),
        _ => Err(error_500()),
    }
}

/// `_motor_desafios`: Gemini sin conectar es un 400
pub(crate) fn motor(modelo: Option<&str>, rol: Option<&str>) -> Result<(Motor, String), Response> {
    tutor::motor_desafios(modelo, rol).map_err(|e| detalle(StatusCode::BAD_REQUEST, e))
}

/// `desafios_almacen.modificar`, fuera del hilo de la petición
async fn modificar(id: String, cambio: impl FnOnce(&mut Mapa) -> Result<(), ErrorObtener> + Send + 'static) -> Result<Mapa, Response> {
    let base = carpeta_base();
    match tokio::task::spawn_blocking(move || d::modificar(&base, &id, cambio)).await {
        Ok(Ok(m)) => Ok(m),
        Ok(Err(e)) => Err(error_obtener(e)),
        Err(_) => Err(error_500()),
    }
}

/// `x["progreso"]`: si no es un dict, el KeyError/TypeError de Python (un 500)
fn progreso_de(x: &mut Mapa) -> Result<&mut Mapa, ErrorObtener> {
    match x.get_mut("progreso") {
        Some(Valor::Mapa(p)) => Ok(p),
        _ => Err(ErrorObtener::Otro("progreso".into())),
    }
}

/// Las páginas del pedido (validadas) o las del alumno, o las del desafío
fn paginas_de(c: &Mapa, des: &Mapa) -> Result<Vec<Valor>, Response> {
    let pedidas = lista(c.get("paginas"));
    if !pedidas.is_empty() {
        return d::validar_paginas(pedidas, false)
            .map(|l| l.into_iter().map(Valor::Mapa).collect())
            .map_err(|t| detalle(StatusCode::BAD_REQUEST, t));
    }
    Ok(lista(Some(o(des.get("paginas_usuario"), des.valor("paginas")))).to_vec())
}

fn texto(t: String) -> Valor {
    Valor::Mapa(Mapa::new().con("texto", t))
}

// =========================================================================== las rutas

/// `POST /api/desafios/{id_}/razonamiento` (`modelo`, `regenerar`): se genera una vez y se guarda
pub async fn razonamiento(State(state): State<AppState>, Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("modelo", &TEXTO_OPC, false), ("paginas", &PAGINAS, false), ("regenerar", &Tipo::Booleano, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let des = match obtener(id.clone()).await {
        Ok(x) => x,
        Err(r) => return r,
    };
    if des.verdad("razonamiento") && !c.verdad("regenerar") {
        let guardado = des.valor("razonamiento").clone();
        return ndjson_trabajo(move |_, _| Ok(guardado));
    }
    let modelo = tutor::modelo_desafios(opcional(&c, "modelo").as_deref(), None);
    let (m, nombre) = match motor(Some(&modelo), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let lineas: Vec<String> = lista(des.get("paginas"))
            .iter()
            .map(|p| {
                let p = mapa_de(Some(p));
                let desc = match p.get("descripcion") {
                    Some(v) if v.verdad() => v.texto_py(),
                    _ => String::new(),
                };
                format!("- {}: {desc}", p.valor("nombre").texto_py())
            })
            .collect();
        let prompt = format!(
            "DESAFÍO: {}\nNivel: {}\n\nENUNCIADO:\n{}\n\nPÁGINAS DE CÓDIGO:\n{}\n\nCÓDIGO DE PARTIDA (solo firmas):\n{}\n\n\
Explica cómo razonar este desafío en las seis secciones.",
            campo(&des, "titulo"),
            campo(&des, "nivel"),
            enunciado(&des),
            lineas.join("\n"),
            paginas_texto(lista(des.get("paginas")), 3000)?
        );
        let t = tutor::flujo(&raiz, &m, &nombre, &prompt, SISTEMA_RAZONAR, 0.3, false, cancelar, avisar)?;
        let pasos = separar_pasos(&t);
        if pasos.is_empty() {
            return Err("El modelo no devolvió el razonamiento. Prueba otra vez u otro modelo.".into());
        }
        let r = Mapa::new().con("pasos", Valor::Lista(pasos.into_iter().map(Valor::Mapa).collect())).con("modelo", modelo.as_str());
        let guardar = r.clone();
        d::modificar(&carpeta_base(), &id, move |x| {
            x.poner("razonamiento", guardar);
            Ok(())
        })
        .map_err(|e| match e {
            ErrorObtener::Desafio(t) | ErrorObtener::Otro(t) => t,
        })?;
        Ok(Valor::Mapa(r))
    })
}

/// `POST /api/desafios/{id_}/plan` (`plan`, `modelo`): se guarda el plan del alumno y el tutor lo valora
pub async fn plan(State(state): State<AppState>, Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("plan", &Tipo::Texto, true), ("modelo", &TEXTO_OPC, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let des = match obtener(id.clone()).await {
        Ok(x) => x,
        Err(r) => return r,
    };
    let (m, nombre) = match motor(opcional(&c, "modelo").as_deref(), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let plan = c.valor("plan").texto_py();
    let guardado = corta(&plan, 5000);
    if let Err(r) = modificar(id, move |x| {
        progreso_de(x)?.poner("plan", guardado);
        d::empezar(x);
        Ok(())
    })
    .await
    {
        return r;
    }
    let raiz = state.base_dir.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        if py::strip(&plan).is_empty() {
            return Err("Escribe primero tu plan.".into());
        }
        let r = paginas_texto(&referencia(&des), 3000)?;
        let prompt = format!(
            "DESAFÍO: {}\n{}\n\nPLAN DEL ALUMNO:\n{}\n\n{}",
            campo(&des, "titulo"),
            enunciado(&des),
            corta(&plan, 3000),
            if r.is_empty() { String::new() } else { format!("(Solución de referencia, SOLO para que juzgues; NO la muestres:\n{r})") }
        );
        Ok(texto(tutor::flujo(&raiz, &m, &nombre, &prompt, SISTEMA_PLAN, 0.3, false, cancelar, avisar)?))
    })
}

/// `POST /api/desafios/{id_}/pista` (`nivel`, `modelo`, `paginas`): 0, las pistas del ejercicio original; 1-3,
/// pistas graduadas del modelo
pub async fn pista(State(state): State<AppState>, Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("nivel", &Tipo::Entero, false), ("modelo", &TEXTO_OPC, false), ("paginas", &PAGINAS, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let nivel = c.get("nivel").and_then(Valor::entero).unwrap_or(1);
    let des = match obtener(id.clone()).await {
        Ok(x) => x,
        Err(r) => return r,
    };
    let contar = move |x: &mut Mapa| {
        let p = progreso_de(x)?;
        let previo = p.get("pistas").and_then(Valor::entero).unwrap_or(0);
        p.poner("pistas", Valor::Entero(previo.max(if nivel != 0 { nivel } else { 1 })));
        d::empezar(x);
        Ok(())
    };
    if nivel == 0 {
        let propias = mapa_de(des.get("privado")).get("pistas_fuente").cloned().filter(Valor::verdad);
        let Some(t) = propias else { return detalle(StatusCode::NOT_FOUND, "Este desafío no trae pistas propias.") };
        if let Err(r) = modificar(id, contar).await {
            return r;
        }
        return json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("titulo", "Pistas del ejercicio original").con("texto", t)));
    }
    let (m, nombre) = match motor(opcional(&c, "modelo").as_deref(), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let paginas = match paginas_de(&c, &des) {
        Ok(p) => p,
        Err(r) => return r,
    };
    if let Err(r) = modificar(id, contar).await {
        return r;
    }
    let raiz = state.base_dir.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let n = nivel.clamp(1, 3);
        let (titulo, instruccion) = NIVELES_PISTA[(n - 1) as usize];
        let sistema = format!("Eres un tutor que guía sin resolver. {instruccion}\nResponde en español, directo, sin saludos. Nunca entregues la solución completa.");
        let resultado = des.get("ultima_comprobacion").filter(|v| v.verdad()).map(|v| mapa_de(Some(v))).unwrap_or_default();
        let fallos: Vec<String> = lista(resultado.get("fallos"))
            .iter()
            .take(4)
            .map(|f| {
                let f = mapa_de(Some(f));
                format!("- {}: {}", campo(&f, "nombre"), campo(&f, "mensaje"))
            })
            .collect();
        let prompt = format!(
            "DESAFÍO: {}\n{}\n\nCÓDIGO ACTUAL DEL ALUMNO:\n{}\n\n{}(Referencia interna, NO revelar:\n{})",
            campo(&des, "titulo"),
            enunciado(&des),
            paginas_texto(&paginas, 6000)?,
            if fallos.is_empty() { String::new() } else { format!("PRUEBAS QUE FALLAN:\n{}\n\n", fallos.join("\n")) },
            paginas_texto(&referencia(&des), 3000)?
        );
        avisar(Mapa::new().con("tipo", "titulo").con("texto", format!("{titulo} {n}/3")));
        Ok(texto(tutor::flujo(&raiz, &m, &nombre, &prompt, &sistema, 0.3, false, cancelar, avisar)?))
    })
}

/// `POST /api/desafios/{id_}/reflexion` (`modelo`, `paginas`): la revisión de la solución, una vez resuelto
pub async fn reflexion(State(state): State<AppState>, Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("modelo", &TEXTO_OPC, false), ("paginas", &PAGINAS, false), ("regenerar", &Tipo::Booleano, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let des = match obtener(id).await {
        Ok(x) => x,
        Err(r) => return r,
    };
    if mapa_de(des.get("progreso")).texto("estado") != Some("resuelto") {
        return detalle(StatusCode::CONFLICT, "La reflexión se abre al resolver el desafío.");
    }
    let (m, nombre) = match motor(opcional(&c, "modelo").as_deref(), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let paginas = match paginas_de(&c, &des) {
        Ok(p) => p,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let r = paginas_texto(&referencia(&des), 3000)?;
        let prompt = format!(
            "DESAFÍO: {}\n{}\n\nSOLUCIÓN DEL ALUMNO (aprobada):\n{}\n\n{}",
            campo(&des, "titulo"),
            corta(&enunciado(&des), 3000),
            paginas_texto(&paginas, 6000)?,
            if r.is_empty() { String::new() } else { format!("SOLUCIÓN DE REFERENCIA:\n{r}") }
        );
        Ok(texto(tutor::flujo(&raiz, &m, &nombre, &prompt, SISTEMA_REFLEXION, 0.4, false, cancelar, avisar)?))
    })
}

/// `POST /api/desafios/{id_}/traducir` (`modelo`, `regenerar`): el enunciado (y la teoría) al español; se guarda
pub async fn traducir(State(state): State<AppState>, Ruta(id): Ruta<String>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("modelo", &TEXTO_OPC, false), ("paginas", &PAGINAS, false), ("regenerar", &Tipo::Booleano, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let des = match obtener(id.clone()).await {
        Ok(x) => x,
        Err(r) => return r,
    };
    if des.verdad("enunciado_es") && !c.verdad("regenerar") {
        let guardado = Mapa::new()
            .con("enunciado_es", des.valor("enunciado_es").clone())
            .con("teoria_es", des.get("teoria_es").cloned().unwrap_or(Valor::Texto(String::new())));
        return ndjson_trabajo(move |_, _| Ok(Valor::Mapa(guardado)));
    }
    let (m, nombre) = match motor(opcional(&c, "modelo").as_deref(), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let vacio = Valor::Texto(String::new());
        let original = corta(&o(des.get("enunciado"), &vacio).texto_py(), 8000);
        let enunciado = tutor::flujo(&raiz, &m, &nombre, &original, SISTEMA_TRADUCIR, 0.1, false, cancelar, avisar)?;
        let mut teoria = String::new();
        if des.verdad("teoria") {
            avisar(Mapa::new().con("tipo", "progreso").con("mensaje", "Traduciendo la teoría…"));
            let t = corta(&des.valor("teoria").texto_py(), 8000);
            teoria = tutor::flujo(&raiz, &m, &nombre, &t, SISTEMA_TRADUCIR, 0.1, false, cancelar, &mut |_| {})?;
        }
        let (e2, t2) = (enunciado.clone(), teoria.clone());
        d::modificar(&carpeta_base(), &id, move |x| {
            x.poner("enunciado_es", e2);
            x.poner("teoria_es", t2);
            Ok(())
        })
        .map_err(|e| match e {
            ErrorObtener::Desafio(t) | ErrorObtener::Otro(t) => t,
        })?;
        Ok(Valor::Mapa(Mapa::new().con("enunciado_es", enunciado).con("teoria_es", teoria)))
    })
}

/// `POST /api/desafios/chat` (`mensajes`, `modelo`, `desafio_id`, `paginas`): las dudas de un desafío, o qué
/// practicar si no hay desafío
pub async fn chat(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(
        &b,
        &[("mensajes", &MENSAJES, true), ("modelo", &TEXTO_OPC, false), ("desafio_id", &TEXTO_OPC, false), ("paginas", &PAGINAS, false)],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let mensajes = lista(c.get("mensajes")).to_vec();
    if mensajes.is_empty() {
        return detalle(StatusCode::BAD_REQUEST, "Escribe un mensaje.");
    }
    let des = match opcional(&c, "desafio_id").filter(|t| !t.is_empty()) {
        Some(id) => match obtener(id).await {
            Ok(x) => Some(x),
            Err(r) => return r,
        },
        None => None,
    };
    let pedidas = lista(c.get("paginas")).to_vec();
    let paginas = if !pedidas.is_empty() {
        pedidas
    } else {
        des.as_ref().map(|x| lista(Some(o(x.get("paginas_usuario"), x.valor("paginas")))).to_vec()).unwrap_or_default()
    };
    let (m, nombre) = match motor(opcional(&c, "modelo").as_deref(), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let mensajes = mensajes_con_referencias(&raiz, &mensajes);
        let (sistema, contexto) = match &des {
            Some(x) => {
                let resultado = x.get("ultima_comprobacion").filter(|v| v.verdad()).map(|v| mapa_de(Some(v)));
                let ultima = match resultado {
                    Some(r) => {
                        let fallos: Vec<String> = lista(r.get("fallos"))
                            .iter()
                            .take(3)
                            .map(|f| {
                                let f = mapa_de(Some(f));
                                format!("{}: {}", campo(&f, "nombre"), campo(&f, "mensaje"))
                            })
                            .collect();
                        format!("\nÚLTIMA COMPROBACIÓN: {}/{} pruebas; {}", campo(&r, "pasados"), campo(&r, "total"), fallos.join("; "))
                    }
                    None => String::new(),
                };
                let contexto = format!(
                    "DESAFÍO: {}\n{}\n\nCÓDIGO ACTUAL:\n{}\n{ultima}",
                    campo(x, "titulo"),
                    corta(&enunciado(x), 3000),
                    paginas_texto(&paginas, 4000)?
                );
                (SISTEMA_CHAT_DESAFIO, contexto)
            }
            None => (SISTEMA_CHAT, String::new()),
        };
        let inicio = mensajes.len().saturating_sub(12);
        let historial: Vec<String> = mensajes[inicio..]
            .iter()
            .map(|m| {
                let m = mapa_de(Some(m));
                let quien = if m.texto("rol") == Some("usuario") { "Alumno" } else { "Tutor" };
                format!("{quien}: {}", corta(&campo(&m, "texto"), 1500))
            })
            .collect();
        let prompt = format!("{}CONVERSACIÓN:\n{}\nTutor:", if contexto.is_empty() { String::new() } else { contexto + "\n\n" }, historial.join("\n"));
        Ok(texto(tutor::flujo(&raiz, &m, &nombre, &prompt, sistema, 0.5, false, cancelar, avisar)?))
    })
}

/// `POST /api/desafios/analizar-propuesta` (`propuesta`, `lenguaje`, `nivel`, `modelo`): evaluación técnica de una
/// idea o planteo
pub async fn analizar_propuesta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(
        &b,
        &[("propuesta", &Tipo::Texto, true), ("lenguaje", &TEXTO_OPC, false), ("nivel", &TEXTO_OPC, false), ("modelo", &TEXTO_OPC, false)],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let propuesta = c.valor("propuesta").texto_py();
    if py::strip(&propuesta).is_empty() {
        return detalle(StatusCode::BAD_REQUEST, "Escribe tu propuesta o planteo.");
    }
    let (m, nombre) = match motor(opcional(&c, "modelo").as_deref(), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let o_defecto = |k: &str, defecto: &str| opcional(&c, k).filter(|t| !t.is_empty()).unwrap_or_else(|| defecto.into());
    let (lenguaje, nivel) = (o_defecto("lenguaje", "python"), o_defecto("nivel", "intermedio"));
    let raiz = state.base_dir.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let etiqueta = if lenguaje.to_lowercase() == "cpp" { "C++ (C++20)" } else { "Python 3" };
        let prompt = format!("LENGUAJE: {etiqueta}\nNIVEL: {nivel}\n\nPROPUESTA O SOLICITUD:\n{}", corta(py::strip(&propuesta), 4000));
        Ok(texto(tutor::flujo(&raiz, &m, &nombre, &prompt, &sistema_propuesta(&lenguaje, &nivel), 0.3, false, cancelar, avisar)?))
    })
}

/// `evaluar_con_salida`: el veredicto del modelo (o uno de reserva si no devuelve el JSON pedido)
#[allow(clippy::too_many_arguments)]
fn evaluar_con_salida(
    state: &AppState,
    m: &Motor,
    nombre: &str,
    des: &Mapa,
    paginas: &[Valor],
    salida: &str,
    stderr: &str,
    exit_code: i128,
    pruebas: Option<&Mapa>,
) -> Result<Mapa, String> {
    let lenguaje = o(des.get("lenguaje"), &Valor::Texto("python".into())).texto_py();
    let titulo = o(des.get("titulo"), &Valor::Texto("Desafío de programación".into())).texto_py();
    let codigo = paginas_texto(paginas, 6000)?;
    let mut info = String::new();
    if let Some(r) = pruebas {
        let de = |k: &str, defecto: Valor| r.get(k).cloned().unwrap_or(defecto).texto_py();
        info = format!(
            "\nPRUEBAS AUTOMATIZADAS:\n- Total: {}\n- Pasadas: {}\n- Aprobado: {}\n",
            de("total", Valor::Entero(0)),
            de("pasados", Valor::Entero(0)),
            de("aprobado", Valor::Bool(false))
        );
        let fallos = lista(r.get("fallos"));
        if !fallos.is_empty() {
            let lineas: Vec<String> = fallos
                .iter()
                .take(4)
                .map(|f| {
                    let f = mapa_de(Some(f));
                    let v = |k: &str| f.get(k).cloned().unwrap_or(Valor::Texto(String::new())).texto_py();
                    format!("  * {}: {}", v("nombre"), v("mensaje"))
                })
                .collect();
            info += &format!("- Fallos detectados:\n{}", lineas.join("\n"));
        }
    }
    let prompt = format!(
        "LENGUAJE: {lenguaje}\nDESAFÍO: {titulo}\nNIVEL: {}\n\nENUNCIADO Y REQUISITOS:\n{}\n\nCÓDIGO DEL ALUMNO:\n{codigo}\n\n\
RESULTADO DE LA EJECUCIÓN DEL ALUMNO:\n- Código de salida (Exit Code): {exit_code}\n- STDOUT:\n{}\n- STDERR:\n{}\n{info}\n\
Evalúa la solución y responde ÚNICAMENTE con el JSON solicitado.",
        des.get("nivel").cloned().unwrap_or(Valor::Texto("intermedio".into())).texto_py(),
        corta(&enunciado(des), 4000),
        if salida.is_empty() { "(vacío)".to_string() } else { corta(salida, 4000) },
        if stderr.is_empty() { "(vacío)".to_string() } else { corta(stderr, 2000) },
    );
    let cancelar = prig_ia::vivo::Cancelar::default();
    let respuesta = tutor::generar_texto(&state.base_dir, m, nombre, &prompt, SISTEMA_EVALUAR_SALIDA, 0.2, None, &cancelar, None)?;
    let datos = prig_ia::json_modelo::reparar(&respuesta).unwrap_or_default();
    if datos.verdad("resumen") {
        return Ok(datos);
    }
    let minusculas = respuesta.to_lowercase();
    let aprobado = exit_code == 0 && stderr.is_empty() && (minusculas.contains("aprobado") || minusculas.contains("correcto"));
    let resumen = py::strip(&corta(&respuesta, 250)).to_string();
    let resumen = if !resumen.is_empty() {
        resumen
    } else if aprobado {
        "Solución evaluada.".into()
    } else {
        "La ejecución tuvo observaciones.".into()
    };
    Ok(Mapa::new()
        .con("aprobado", aprobado)
        .con("calificacion", Valor::Entero(if aprobado { 8 } else { 4 }))
        .con("estado", if aprobado { "aprobado" } else { "error" })
        .con("resumen", resumen)
        .con("analisis_salida", format!("Salida observada (exit code {exit_code})."))
        .con("analisis_codigo", "Revisa la lógica y los casos de prueba.")
        .con("consejos", Valor::Lista(vec![Valor::Texto("Comprueba los casos borde y optimiza la eficiencia.".into())])))
}

/// `POST /api/desafios/evaluar-salida`: el modelo evalúa la solución mirando el código y la salida de ejecutarlo;
/// si es un desafío guardado y la aprueba, queda resuelto
pub async fn evaluar_salida(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(
        &b,
        &[
            ("id", &TEXTO_OPC, false),
            ("titulo", &TEXTO_OPC, false),
            ("enunciado", &TEXTO_OPC, false),
            ("lenguaje", &TEXTO_OPC, false),
            ("codigo", &Tipo::Texto, false),
            ("nombre_archivo", &TEXTO_OPC, false),
            ("salida", &Tipo::Texto, false),
            ("stderr", &TEXTO_OPC, false),
            ("exit_code", &Tipo::Entero, false),
            ("modelo", &TEXTO_OPC, false),
        ],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let crudo = opcional(&c, "id");
    let id = crudo.clone().filter(|t| !t.is_empty());
    let texto_de = |k: &str, defecto: &str| opcional(&c, k).filter(|t| !t.is_empty()).unwrap_or_else(|| defecto.into());
    let codigo = c.get("codigo").map(Valor::texto_py).unwrap_or_default();
    let nombre_archivo = texto_de("nombre_archivo", "solucion.py");
    let guardado = match &id {
        Some(i) => obtener(i.clone()).await.ok(),
        None => None,
    };
    let des = guardado.clone().unwrap_or_else(|| {
        Mapa::new()
            .con("id", id.clone().unwrap_or_else(|| "desafio_editor".into()))
            .con("titulo", texto_de("titulo", "Desafío de programación"))
            .con("enunciado", texto_de("enunciado", "Desafío resuelto en el editor de código."))
            .con("nivel", "intermedio")
            .con("lenguaje", texto_de("lenguaje", "python"))
            .con("paginas", Valor::Lista(vec![Valor::Mapa(Mapa::new().con("nombre", nombre_archivo.as_str()).con("contenido", codigo.as_str()))]))
    });
    let pagina = Mapa::new().con("nombre", nombre_archivo.as_str()).con("contenido", codigo.as_str());
    let modelo = tutor::modelo_desafios(opcional(&c, "modelo").as_deref(), Some("codigo"));
    let salida = c.get("salida").map(Valor::texto_py).unwrap_or_default();
    let stderr = texto_de("stderr", "");
    let exit_code = c.get("exit_code").and_then(Valor::entero).unwrap_or(0);
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let r = tokio::task::spawn_blocking(move || -> Result<Mapa, Response> {
        // si el desafío tiene pruebas internas, la comprobación automática enriquece la evaluación (opcional)
        let privado = mapa_de(des.get("privado"));
        let pruebas = if privado.verdad("pruebas") {
            match comprobar(&state, std::slice::from_ref(&pagina), &privado, &format!("eval_{}", campo(&des, "id"))) {
                Ok(r) => Some(r),
                Err(e) => {
                    let t = match e {
                        ErrorObtener::Desafio(t) | ErrorObtener::Otro(t) => t,
                    };
                    tracing::warn!("Comprobación automática opcional no pudo ejecutarse: {t}");
                    None
                }
            }
        } else {
            None
        };
        let (m, nombre) = motor(Some(&modelo), None)?;
        let paginas = vec![Valor::Mapa(pagina.clone())];
        let resultado = evaluar_con_salida(&state, &m, &nombre, &des, &paginas, &salida, &stderr, exit_code, pruebas.as_ref()).map_err(|_| error_500())?;
        if let (Some(i), Some(_)) = (&id, &guardado) {
            if resultado.verdad("aprobado") {
                let usuario = paginas.clone();
                let r = d::modificar(&carpeta_base(), i, move |x| {
                    x.poner("paginas_usuario", Valor::Lista(usuario));
                    if let Some(Valor::Mapa(p)) = x.get_mut("progreso") {
                        p.poner("estado", "resuelto");
                        let n = p.get("intentos").and_then(Valor::entero).unwrap_or(0);
                        p.poner("intentos", Valor::Entero(n + 1));
                    }
                    Ok(())
                });
                match r {
                    Ok(_) => {
                        let banderas = prig_plataforma::banderas::Banderas::new(std::path::PathBuf::from(py::expanduser("~/.prig_flags.json")));
                        if banderas.activa("learning_telemetry") {
                            if let Err(e) = prig_aprendizaje::telemetria::registrar_envio(&espacio, &des, true, 0, &stderr, 0.0) {
                                tracing::warn!("⚠️ Telemetría de desafíos: {e}");
                            }
                        }
                    }
                    Err(_) => tracing::warn!("No se pudo actualizar estado en almacén"),
                }
            }
        }
        Ok(Mapa::new()
            .con("ok", true)
            .con("evaluacion", resultado)
            .con("desafio_id", crudo.map(Valor::Texto).unwrap_or(Valor::Nulo))
            .con("pruebas_automatizadas", pruebas.map(Valor::Mapa).unwrap_or(Valor::Nulo)))
    })
    .await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(r)) => r,
        Err(_) => error_500(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn la_caja_no_da_codigo() {
        let t = "## 1. Qué me piden\nx\n## 2. Ejemplos\n```python\ndef f():\n    pass\n```\n## 3. Partes\nz\n";
        let p = separar_pasos(t);
        assert_eq!(p.len(), 3);
        assert_eq!(p[0].texto("titulo"), Some("Qué me piden"));
        assert!(p[1].texto("contenido").unwrap().contains("Aquí iba código"));
        assert_eq!(separar_pasos("solo texto")[0].texto("titulo"), Some("Cómo pensar este desafío"));
        assert!(separar_pasos("  ").is_empty());
    }

    #[test]
    fn paginas_recortadas() {
        let p = vec![Valor::Mapa(Mapa::new().con("nombre", "a.py").con("descripcion", "d").con("contenido", "xyz"))];
        assert_eq!(paginas_texto(&p, 100).unwrap(), "--- página a.py (d) ---\nxyz");
        assert_eq!(paginas_texto(&p, 5).unwrap(), "--- p\n…(recortado)");
        assert_eq!(paginas_texto(&[Valor::Mapa(Mapa::new())], 9).unwrap_err(), "'nombre'");
    }
}

// =========================================================================== el análisis del avance

const SISTEMA_ANALISIS: &str = r#"Eres el tutor que revisa el AVANCE de un alumno de programación en Python.

Te dan datos MEDIDOS (desafíos resueltos ejecutando pruebas, intentos, pistas, dominio por
concepto, bloques del plan). Analízalos sin inventar nada: si algo no está en los datos, no lo
digas. Habla en español, en segunda persona, directo y sin halagos vacíos.

Escribe estas secciones con encabezados «## »:
## Dónde estás
Dos o tres frases con lo que los datos muestran (volumen, constancia, qué ya resuelve solo).
## Lo que se te resiste
Los conceptos con menor dominio y POR QUÉ lo parecen (muchas pistas, rendirse, varios intentos).
## Cómo estás aprendiendo
Hábitos que se ven en los datos: si usa la caja de razonamiento, si escribe el plan antes de
programar, si reintenta o se rinde. Di qué hábito le conviene cambiar y por qué.
## Plan para las próximas tres sesiones
Tres puntos, uno por sesión: `- **tema concreto** — qué hacer y por qué ese tema ahora`.
## Cómo sabrás que avanzaste
Una señal observable y comprobable (por ejemplo: resolver X sin pistas).

Termina con un bloque ```json {"temas": ["tema 1", "tema 2", "tema 3"]} ``` con los temas del
plan, tal como los pondrías en el buscador de desafíos. Nada de código en el resto del texto."#;

/// `POST /api/progreso/analisis` (`modelo`, `regenerar`): el modelo lee el avance medido y propone los próximos
/// pasos; si ya hay uno de los mismos desafíos y no se pide regenerar, ese
pub async fn progreso_analisis(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(&b, &[("modelo", &TEXTO_OPC, false), ("regenerar", &Tipo::Booleano, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let base = carpeta_base();
    let (guardado, filas) = {
        let base = base.clone();
        match tokio::task::spawn_blocking(move || {
            let g = d::leer_json(&base.join("analisis.json")).filter(|g| matches!(g, Valor::Mapa(_)));
            (g, d::historial(&base.join("desafios"), None, None, None, prig_aprendizaje::progreso::MAX_HISTORIAL))
        })
        .await
        {
            Ok((g, Ok(f))) => (g, f),
            _ => return error_500(),
        }
    };
    if let Some(Valor::Mapa(g)) = &guardado {
        if !c.verdad("regenerar") && g.num("desafios") == Some(filas.len() as f64) {
            let g = Valor::Mapa(g.clone());
            return ndjson_trabajo(move |_, _| Ok(g));
        }
    }
    if filas.is_empty() {
        return detalle(StatusCode::CONFLICT, "Todavía no hay desafíos que analizar: empieza uno en la sección Desafíos.");
    }
    let pedido_modelo = opcional(&c, "modelo");
    let (m, nombre) = match motor(pedido_modelo.as_deref(), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let raiz = state.base_dir.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let lecturas = prig_integrations::kaggle::resumen_lecturas().unwrap_or_default();
        let r = prig_aprendizaje::progreso::resumen(&base.join("desafios"), Some(&espacio), 120, lecturas).map_err(|_| "No se pudo leer el progreso.".to_string())?;
        let contexto = prig_aprendizaje::progreso::contexto_para_modelo(&r, &filas, 25);
        let prompt = format!("DATOS DEL ALUMNO:\n{}\n\nAnaliza su avance.", corta(&contexto, 12000));
        let texto = tutor::flujo(&raiz, &m, &nombre, &prompt, SISTEMA_ANALISIS, 0.3, true, cancelar, avisar)?;
        if py::strip(&texto).is_empty() {
            return Err("El modelo no devolvió nada. Prueba otra vez o con otro modelo.".into());
        }
        let modelo = tutor::modelo_desafios(pedido_modelo.as_deref(), None);
        Ok(Valor::Mapa(prig_aprendizaje::progreso::guardar_analisis(&base, &texto, &modelo, filas.len())?))
    })
}
