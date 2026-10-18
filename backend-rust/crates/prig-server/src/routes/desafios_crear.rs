//! Crear desafíos con el modelo (`tutor.crear` y `tutor.replicar_desde_github` de `desafios/tutor.py`) y sus rutas de
//! app.py: `POST /api/desafios/crear`, `/api/desafios/github/replicar` y `/api/youtube/crear-desafio`. Un desafío
//! creado por el modelo solo se entrega si su referencia pasa las pruebas y el código de partida no; si falla, se
//! reintenta contándole al modelo por qué falló. Los prompts, tal cual los de Python. Responden en NDJSON: los
//! avisos de progreso y al final `{"tipo": "fin", "resultado"}` o `{"tipo": "error", "mensaje"}`.
//!
//! Reparar y compilar las páginas de Python lo hace `desafios/arneses/codigo.py` (los mensajes de `SyntaxError` son
//! los del propio intérprete); lo de C++, aquí.

use axum::{body::Bytes, extract::State, response::Response};
use banco_core::py::cadena;
use prig_aprendizaje::desafios::{self as d, ErrorObtener};
use prig_ia::tutor::{self, Motor};
use prig_ia::vivo::Cancelar;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::sync::LazyLock;

use crate::routes::desafios::{carpeta_base, error_500, error_obtener, mapa_de};
use crate::routes::desafios_fuentes::{codigo_py, contexto_bloque, descargar_contenido_archivo, guardar_y_registrar, iterar, validar_desafio};
use crate::routes::desafios_tutor::{motor, opcional, pedido, TEXTO_OPC};
use crate::routes::profesor::ndjson_trabajo;
use crate::routes::workspace::espacio_de_trabajo;
use crate::state::AppState;

type R<T> = Result<T, ErrorObtener>;

pub(crate) const NIVELES: [&str; 4] = ["principiante", "intermedio", "avanzado", "senior"];
const EXT_CPP: [&str; 5] = [".cpp", ".h", ".hpp", ".cc", ".cxx"];

fn falla(t: impl Into<String>) -> ErrorObtener {
    ErrorObtener::Desafio(t.into())
}

fn texto_error(e: ErrorObtener) -> String {
    match e {
        ErrorObtener::Desafio(t) | ErrorObtener::Otro(t) => t,
    }
}

fn corta(t: &str, n: usize) -> String {
    cadena::primeros(t, n).to_string()
}

fn lista(v: Option<&Valor>) -> Vec<Valor> {
    match v {
        Some(Valor::Lista(l)) => l.clone(),
        _ => Vec::new(),
    }
}

fn mapas(v: &[Valor]) -> Vec<Mapa> {
    v.iter().map(|x| mapa_de(Some(x))).collect()
}

fn contenido(p: &Mapa) -> String {
    p.texto("contenido").unwrap_or_default().to_string()
}

// =========================================================================== limpiar lo que escribe el modelo

/// `limpiar_codigo(codigo, lenguaje)`: sin cercas de markdown alrededor y, en Python, los comentarios `//` como `#`
pub(crate) fn limpiar_codigo(codigo: &str, lenguaje: &str) -> String {
    let mut texto = cadena::strip(codigo).to_string();
    if texto.starts_with("```") {
        let mut lineas: Vec<&str> = cadena::splitlines(&texto);
        if lineas.first().is_some_and(|l| cadena::strip(l).starts_with("```")) {
            lineas.remove(0);
        }
        if lineas.last().is_some_and(|l| cadena::strip(l) == "```") {
            lineas.pop();
        }
        texto = cadena::strip(&lineas.join("\n")).to_string();
    }
    if texto.ends_with("```") {
        texto = cadena::rstrip(&texto[..texto.len() - 3]).to_string();
    }
    if lenguaje == "python" {
        let lineas: Vec<String> = texto
            .split('\n')
            .map(|linea| {
                let sin = cadena::lstrip(linea);
                match sin.strip_prefix("//") {
                    Some(resto) => format!("{}#{resto}", " ".repeat(linea.chars().count() - sin.chars().count())),
                    None => linea.to_string(),
                }
            })
            .collect();
        texto = lineas.join("\n");
    }
    texto
}

/// La primera clave de `claves` que está y no es falsa
fn primera<'a>(datos: &'a Mapa, claves: &[&str]) -> Option<&'a Valor> {
    claves.iter().find_map(|k| datos.get(k).filter(|v| v.verdad()))
}

/// `_normalizar_creado(datos, lenguaje)`: el JSON del modelo con la forma de un desafío (acepta los nombres en inglés
/// y las variantes que escriben los modelos pequeños)
pub(crate) fn normalizar_creado(datos: Mapa, lenguaje: &str) -> Result<Mapa, String> {
    let mut datos = datos;
    for k in ["desafio", "challenge"] {
        if let Some(Valor::Mapa(m)) = datos.get(k) {
            datos = m.clone();
            break;
        }
    }
    let defecto = if lenguaje == "cpp" { "solucion.cpp" } else { "solucion.py" };
    let extraer = |claves: &[&str]| -> Vec<Valor> {
        match primera(&datos, claves) {
            None => Vec::new(),
            Some(Valor::Mapa(m)) => vec![Valor::Mapa(m.clone())],
            Some(Valor::Texto(t)) => vec![Valor::Mapa(Mapa::new().con("nombre", defecto).con("contenido", t.clone()))],
            Some(Valor::Lista(l)) => l
                .iter()
                .filter_map(|x| match x {
                    Valor::Mapa(m) => Some(Valor::Mapa(m.clone())),
                    Valor::Texto(t) => Some(Valor::Mapa(Mapa::new().con("nombre", defecto).con("contenido", t.clone()))),
                    _ => None,
                })
                .collect(),
            Some(_) => Vec::new(),
        }
    };
    let paginas = |l: Vec<Valor>, con_desc: bool| -> Vec<Mapa> {
        l.iter()
            .filter_map(|p| if let Valor::Mapa(p) = p { Some(p) } else { None })
            .map(|p| {
                let o = |a: &str, b: &str| primera(p, &[a, b]).map(Valor::texto_py).unwrap_or_default();
                let mut nombre = cadena::strip(&o("nombre", "name")).to_string();
                if !nombre.is_empty() && !nombre.ends_with(".py") && !EXT_CPP.iter().any(|e| nombre.ends_with(e)) {
                    nombre.push_str(if lenguaje == "cpp" { ".cpp" } else { ".py" });
                }
                let mut item = Mapa::new().con("nombre", nombre).con("contenido", limpiar_codigo(&o("contenido", "content"), lenguaje));
                if con_desc {
                    item.poner("descripcion", primera(p, &["descripcion"]).map(Valor::texto_py).unwrap_or_default());
                }
                item
            })
            .collect()
    };
    let mut pags = paginas(
        extraer(&["paginas", "pages", "archivos", "files", "plantilla", "codigo_partida", "codigo_inicial", "codigo", "starter_code"]),
        true,
    );
    let mut refs = paginas(
        extraer(&["referencia", "reference", "solucion", "solution", "codigo_solucion", "soluciones", "codigo_referencia", "complete_code"]),
        false,
    );
    if !pags.is_empty() && refs.is_empty() {
        refs = pags.iter().map(|p| Mapa::new().con("nombre", p.valor("nombre").clone()).con("contenido", p.valor("contenido").clone())).collect();
    } else if !refs.is_empty() && pags.is_empty() {
        pags = refs
            .iter()
            .map(|r| Mapa::new().con("nombre", r.valor("nombre").clone()).con("contenido", r.valor("contenido").clone()).con("descripcion", "Código de partida"))
            .collect();
    }
    // Los mismos nombres en las páginas de partida y en la referencia cuando hay tantas de unas como de otras
    let nombre = |p: &Mapa| p.texto("nombre").unwrap_or_default().to_string();
    if pags.len() == 1 && refs.len() == 1 {
        if nombre(&pags[0]) != nombre(&refs[0]) {
            refs[0].poner("nombre", nombre(&pags[0]));
        }
    } else if pags.len() == refs.len() && pags.len() > 1 {
        let mut a: Vec<String> = pags.iter().map(nombre).collect();
        let mut b: Vec<String> = refs.iter().map(nombre).collect();
        a.sort();
        b.sort();
        if a != b {
            for i in 0..pags.len() {
                let n = nombre(&pags[i]);
                refs[i].poner("nombre", n);
            }
        }
    }
    let mut crudas = ["pruebas", "tests", "asserts", "test_cases", "comprobaciones", "comprobacion"].iter().find_map(|k| datos.get(k).filter(|v| v.verdad())).cloned();
    if let Some(Valor::Mapa(m)) = &crudas {
        crudas = Some(primera(m, &["asserts", "tests"]).cloned().unwrap_or(Valor::Lista(Vec::new())));
    }
    if let Some(Valor::Texto(t)) = &crudas {
        static BLOQUES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\n\s*\n").unwrap());
        crudas = Some(Valor::Lista(BLOQUES.split(t).filter(|b| !cadena::strip(b).is_empty()).map(|b| Valor::Texto(b.into())).collect()));
    }
    let mut pruebas: Vec<String> = Vec::new();
    if let Some(c) = crudas.filter(|c| c.verdad()) {
        for t in iterar(&c)? {
            let limpio = cadena::strip(&limpiar_codigo(&t.texto_py(), lenguaje)).to_string();
            if !limpio.is_empty() {
                pruebas.push(limpio);
            }
        }
    }
    if lenguaje == "python" && !pags.is_empty() {
        let mut modulos: Vec<String> = pags.iter().map(nombre).filter(|n| n.ends_with(".py")).map(|n| n[..n.len() - 3].to_string()).collect();
        modulos.sort();
        modulos.dedup();
        if modulos.len() == 1 {
            static FROM: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(\s*from\s+)([a-zA-Z0-9_]+)(\s+import\s+.*)$").unwrap());
            const COMUNES: [&str; 20] = [
                "math", "typing", "collections", "itertools", "functools", "re", "os", "sys", "random", "json", "heapq", "bisect", "unittest",
                "doctest", "string", "copy", "time", "datetime", "abc", "operator",
            ];
            let esperado = &modulos[0];
            pruebas = pruebas
                .iter()
                .map(|frag| {
                    frag.split('\n')
                        .map(|l| match FROM.captures(l) {
                            Some(m) if !modulos.contains(&m[2].to_string()) && !COMUNES.contains(&&m[2]) => format!("{}{esperado}{}", &m[1], &m[3]),
                            _ => l.to_string(),
                        })
                        .collect::<Vec<_>>()
                        .join("\n")
                })
                .collect();
        }
    }
    let nivel = primera(&datos, &["nivel"]).map(Valor::texto_py).unwrap_or_else(|| "intermedio".into()).to_lowercase();
    let conceptos: Vec<Valor> = match primera(&datos, &["conceptos"]) {
        Some(c) => iterar(c)?.iter().map(|x| Valor::Texto(x.texto_py())).take(6).collect(),
        None => Vec::new(),
    };
    let titulo = primera(&datos, &["titulo"]).map(Valor::texto_py).unwrap_or_else(|| "Desafío".into());
    Ok(Mapa::new()
        .con("titulo", corta(cadena::strip(&titulo), 120))
        .con("enunciado", cadena::strip(&primera(&datos, &["enunciado"]).map(Valor::texto_py).unwrap_or_default()))
        .con("nivel", if NIVELES.contains(&nivel.as_str()) { nivel } else { "intermedio".into() })
        .con("conceptos", Valor::Lista(conceptos))
        .con("paginas", Valor::Lista(pags.into_iter().map(Valor::Mapa).collect()))
        .con("referencia", Valor::Lista(refs.into_iter().map(Valor::Mapa).collect()))
        .con("pruebas", Valor::Lista(pruebas.into_iter().map(Valor::Texto).collect()))
        .con("lenguaje", lenguaje))
}

/// `vaciar_cuerpos_cpp(codigo)`: los cuerpos de las funciones (menos `main`) como `// TODO` y `return {};` (o nada
/// si son void), con sus firmas e includes. Recorre las coincidencias como `re.finditer` sobre el texto original.
pub(crate) fn vaciar_cuerpos_cpp(codigo: &str) -> String {
    static FUNC: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(concat!(
            r"(?m)^([ \t]*(?:template\s*<[^>]+>\s*)?",
            r"(?:(?:inline|static|constexpr|virtual|explicit|friend)\s+)*",
            r"([\w:~<>,*&]+(?:\s+[\w:~<>,*&]+)*)\s+",
            r"([a-zA-Z_]\w*(?:::[a-zA-Z_]\w*)?)\s*",
            r"\([^)]*\)\s*(?:const\b)?\s*(?:noexcept\b)?\s*(?:->\s*[\w:~<>,*&]+\s*)?",
            r")\{"
        ))
        .unwrap()
    });
    let b = codigo.as_bytes();
    let n = b.len();
    // `codigo[a:b]` de Python: vacío si a >= b
    let tramo = |a: usize, z: usize| if a < z { &codigo[a..z] } else { "" };
    let mut ultimo = 0;
    let mut res = String::new();
    for m in FUNC.captures_iter(codigo) {
        let llave = m.get(0).unwrap().end() - 1;
        let tipo = cadena::strip(&m[2]).to_string();
        let nombre = cadena::strip(&m[3]).to_string();
        if ["if", "while", "for", "switch", "catch"].contains(&nombre.as_str()) {
            continue;
        }
        let mut prof = 1;
        let mut i = llave + 1;
        let (mut cadena_, mut caracter, mut linea, mut bloque) = (false, false, false, false);
        while i < n && prof > 0 {
            let c = b[i];
            if linea {
                if c == b'\n' {
                    linea = false;
                }
            } else if bloque {
                if c == b'*' && i + 1 < n && b[i + 1] == b'/' {
                    bloque = false;
                    i += 1;
                }
            } else if cadena_ {
                if c == b'\\' {
                    i += 1;
                } else if c == b'"' {
                    cadena_ = false;
                }
            } else if caracter {
                if c == b'\\' {
                    i += 1;
                } else if c == b'\'' {
                    caracter = false;
                }
            } else if c == b'/' && i + 1 < n && b[i + 1] == b'/' {
                linea = true;
                i += 1;
            } else if c == b'/' && i + 1 < n && b[i + 1] == b'*' {
                bloque = true;
                i += 1;
            } else if c == b'"' {
                cadena_ = true;
            } else if c == b'\'' {
                caracter = true;
            } else if c == b'{' {
                prof += 1;
            } else if c == b'}' {
                prof -= 1;
            }
            i += 1;
        }
        if prof == 0 {
            res.push_str(tramo(ultimo, llave));
            let es_void = tipo == "void" || tipo.split_whitespace().any(|t| t == "void");
            let es_main = nombre == "main" || nombre.ends_with("::main");
            if es_main {
                res.push_str(tramo(llave, i));
            } else if es_void {
                res.push_str("{\n    // TODO: implementar solución\n}");
            } else {
                res.push_str("{\n    // TODO: implementar solución\n    return {};\n}");
            }
            ultimo = i;
        }
    }
    res.push_str(tramo(ultimo, n));
    if cadena::strip(&res).is_empty() {
        codigo.to_string()
    } else {
        res
    }
}

/// `_pagina_ya_resuelta(datos)`: una página de partida idéntica a la de referencia (en C++, solo las .cpp)
fn pagina_ya_resuelta(paginas: &[Mapa], referencia: &[Mapa], lenguaje: &str) -> Option<String> {
    let (minimo, solo_cpp) = if lenguaje == "cpp" { (30, true) } else { (40, false) };
    for pi in paginas {
        let nombre = pi.texto("nombre").unwrap_or_default();
        if solo_cpp && ![".cpp", ".cc", ".cxx"].iter().any(|e| nombre.ends_with(e)) {
            continue;
        }
        if let Some(pr) = referencia.iter().find(|r| r.texto("nombre") == Some(nombre)) {
            let a = contenido(pi);
            let a = cadena::strip(&a);
            if a == cadena::strip(&contenido(pr)) && a.chars().count() > minimo {
                return Some(nombre.to_string());
            }
        }
    }
    None
}

/// `extraer_contenido_cuaderno`: de un cuaderno Jupyter, las celdas de teoría y los bloques de código (el texto tal
/// cual si no se puede leer)
pub(crate) fn extraer_contenido_cuaderno(texto: &str) -> String {
    let leer = || -> Option<String> {
        let Valor::Mapa(datos) = prig_plataforma::json::leer(texto).ok()? else { return None };
        let celdas = match datos.get("cells") {
            Some(v) if v.verdad() => iterar(v).ok()?,
            _ => Vec::new(),
        };
        let mut partes = Vec::new();
        for c in celdas {
            let Valor::Mapa(c) = c else { return None };
            let src = match c.get("source") {
                Some(v) if v.verdad() => {
                    let trozos = iterar(v).ok()?;
                    let mut s = String::new();
                    for t in trozos {
                        let Valor::Texto(t) = t else { return None };
                        s.push_str(&t);
                    }
                    s
                }
                _ => String::new(),
            };
            let src = cadena::strip(&src);
            if src.is_empty() {
                continue;
            }
            match c.texto("cell_type") {
                Some("markdown") => partes.push(format!("# [Instrucciones / Explicación]\n{src}\n")),
                Some("code") => partes.push(format!("```\n{src}\n```\n")),
                _ => {}
            }
        }
        Some(if partes.is_empty() { texto.to_string() } else { partes.join("\n\n") })
    };
    leer().unwrap_or_else(|| texto.to_string())
}

/// `conversacion_como_contexto(mensajes)`: los últimos diez mensajes como texto
fn conversacion_como_contexto(mensajes: &[Valor]) -> String {
    let desde = mensajes.len().saturating_sub(10);
    mensajes[desde..]
        .iter()
        .map(|m| {
            let m = mapa_de(Some(m));
            let quien = if m.texto("rol") == Some("usuario") { "Alumno" } else { "Tutor" };
            format!("{quien}: {}", corta(&m.get("texto").map(Valor::texto_py).unwrap_or_else(|| "None".into()), 800))
        })
        .collect::<Vec<_>>()
        .join("\n")
}

// =========================================================================== crear y replicar

static ROTULO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)^\s*(markdown( en español)?|enunciado)\s*:\s*").unwrap());

const FALLO_JSON: &str = "La respuesta no tuvo un formato JSON válido o se cortó antes de cerrar las llaves. \
Devuelve ÚNICAMENTE el objeto JSON completo con las llaves, cerrando todas las comillas.";

struct Generado {
    paginas: Vec<Mapa>,
    referencia: Vec<Mapa>,
    pruebas: Vec<Valor>,
    datos: Mapa,
}

enum Paso {
    /// El texto del modelo no se pudo leer como JSON (el motivo)
    Json(String),
    /// Descartado, con el motivo para el modelo
    Descartado(String),
    Listo(Generado),
}

/// Lee el JSON del modelo y prepara las páginas: el enunciado sin rótulo, las páginas de Python reparadas y
/// compiladas (las de C++, limpias y, al replicar, vaciadas si traen la solución)
fn preparar(state: &AppState, texto: &str, lenguaje: &str, replicar: bool) -> R<Paso> {
    let datos = match prig_ia::json_modelo::reparar(texto).and_then(|m| normalizar_creado(m, lenguaje)) {
        Ok(d) => d,
        Err(e) => return Ok(Paso::Json(e)),
    };
    let mut datos = datos;
    let enunciado = ROTULO.replacen(datos.texto("enunciado").unwrap_or_default(), 1, "").into_owned();
    datos.poner("enunciado", enunciado);
    let mut paginas = mapas(datos.lista("paginas").unwrap_or(&[]));
    let mut referencia = mapas(datos.lista("referencia").unwrap_or(&[]));
    let pruebas = datos.lista("pruebas").unwrap_or(&[]).to_vec();
    let (rota, pruebas_rotas) = if lenguaje == "cpp" {
        for p in paginas.iter_mut() {
            if replicar {
                let c = contenido(p);
                let nombre = p.texto("nombre").unwrap_or_default().to_string();
                let pr = referencia.iter().find(|r| r.texto("nombre") == Some(nombre.as_str())).map(contenido);
                if let Some(pr) = pr {
                    let c_ = cadena::strip(&c);
                    if c_ == cadena::strip(&pr) && [".cpp", ".cc", ".cxx"].iter().any(|e| nombre.ends_with(e)) && c_.chars().count() > 30 {
                        let vaciado = vaciar_cuerpos_cpp(&c);
                        if cadena::strip(&vaciado) != cadena::strip(&pr) {
                            p.poner("contenido", vaciado);
                        }
                    }
                }
            }
            let c = limpiar_codigo(&contenido(p), "cpp");
            p.poner("contenido", c);
        }
        for p in referencia.iter_mut() {
            let c = limpiar_codigo(&contenido(p), "cpp");
            p.poner("contenido", c);
        }
        (None, None)
    } else {
        let lista = |v: &[Mapa]| Valor::Lista(v.iter().cloned().map(Valor::Mapa).collect());
        let r = codigo_py(
            state,
            Mapa::new()
                .con("operacion", "preparar")
                .con("lenguaje", lenguaje)
                .con("modo", if replicar { "replicar" } else { "crear" })
                .con("paginas", lista(&paginas))
                .con("referencia", lista(&referencia))
                .con("pruebas", Valor::Lista(pruebas.clone())),
        )?;
        let r = mapa_de(Some(&r));
        paginas = mapas(r.lista("paginas").unwrap_or(&[]));
        referencia = mapas(r.lista("referencia").unwrap_or(&[]));
        let t = |k: &str| r.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py);
        (t("rota"), t("pruebas_rotas"))
    };
    if let Some(rota) = rota {
        return Ok(Paso::Descartado(format!("el código no compila: {rota}. Pon pass en los cuerpos sin implementar")));
    }
    if let Some(rotas) = pruebas_rotas {
        return Ok(Paso::Descartado(format!("las pruebas no compilan: {rotas}. Corrige la sintaxis de los asserts")));
    }
    if let Some(resuelta) = pagina_ya_resuelta(&paginas, &referencia, lenguaje) {
        return Ok(Paso::Descartado(format!("la página {resuelta} del código de partida ya trae la solución: deja su lógica sin implementar")));
    }
    Ok(Paso::Listo(Generado { paginas, referencia, pruebas, datos }))
}

fn progreso(mensaje: String, n: i64) -> Mapa {
    Mapa::new().con("tipo", "progreso").con("mensaje", mensaje).con("intento", n)
}

fn descartado(mensaje: String, n: i64) -> Mapa {
    progreso(mensaje, n).con("descartado", true)
}

fn historial(n: i64, motivo: &str) -> Valor {
    Valor::Mapa(Mapa::new().con("intento", n).con("motivo", motivo))
}

/// Comprueba el desafío generado (referencia pasa, partida no) y, si vale, lo arma
fn comprobar_generado(state: &AppState, g: &Generado, lenguaje: &str, minimo: i128, n: i64, hist: &mut Vec<Valor>) -> R<Result<(Mapa, Mapa), String>> {
    let tipo = if lenguaje == "cpp" { "cpp_asserts" } else { "asserts" };
    let refs = Valor::Lista(g.referencia.iter().cloned().map(Valor::Mapa).collect());
    let privado = Mapa::new().con("comprobacion", Mapa::new().con("tipo", tipo).con("asserts", Valor::Lista(g.pruebas.clone()))).con("referencia", refs.clone());
    let pags: Vec<Valor> = g.paginas.iter().cloned().map(Valor::Mapa).collect();
    let v = validar_desafio(state, &pags, &lista(Some(&refs)), &privado, minimo)?;
    hist.push(Valor::Mapa(Mapa::new().con("intento", n).con("valido", v.valor("valido").clone()).con("motivo", v.valor("motivo").clone())));
    if !v.verdad("valido") {
        return Ok(Err(v.valor("motivo").texto_py()));
    }
    let comprobacion = Mapa::new().con("tipo", tipo).con("pruebas", v.valor("pruebas").clone()).con("pruebas_visibles", false);
    Ok(Ok((comprobacion, privado)))
}

fn conceptos_o(g: &Generado, defecto: &str) -> Valor {
    match g.datos.get("conceptos") {
        Some(v) if v.verdad() => v.clone(),
        _ => Valor::Lista(vec![Valor::Texto(defecto.into())]),
    }
}

/// `tutor.crear`: pide el desafío al modelo y lo comprueba ejecutándolo; reintenta contando qué falló
#[allow(clippy::too_many_arguments)]
fn crear(state: &AppState, m: &Motor, modelo: &str, tema: &str, nivel: &str, contexto: &str, lenguaje: &str, c: &Cancelar, avisar: &mut dyn FnMut(Mapa)) -> R<Mapa> {
    const INTENTOS: i64 = 4;
    if cadena::strip(if tema.is_empty() { contexto } else { tema }).is_empty() {
        return Err(falla("Di qué quieres practicar."));
    }
    let nivel = if NIVELES.contains(&nivel) { nivel } else { "intermedio" };
    let sistema = if lenguaje == "cpp" { SISTEMA_CREAR_CPP } else { SISTEMA_CREAR };
    let mut fallo = String::new();
    let mut hist: Vec<Valor> = Vec::new();
    for n in 1..=INTENTOS {
        avisar(progreso(format!("Intento {n} de {INTENTOS}: el modelo escribe el desafío en {}…", lenguaje.to_uppercase()), n));
        let mut prompt = format!("Tema a practicar: {}\nLenguaje: {lenguaje}\nNivel del alumno: {nivel}\n", if tema.is_empty() { "(ver conversación)" } else { tema });
        if !contexto.is_empty() {
            prompt += &format!("\nContexto:\n{}\n", corta(contexto, 4000));
        }
        if !fallo.is_empty() {
            prompt += &format!("\nEl intento anterior no sirvió porque: {fallo}\nCorrígelo.\n");
        }
        prompt += "\nCrea el desafío.";
        let texto = tutor::generar_texto(&state.base_dir, m, modelo, &prompt, sistema, 0.4, Some("json"), c, None).map_err(falla)?;
        let g = match preparar(state, &texto, lenguaje, false)? {
            Paso::Json(e) => {
                fallo = FALLO_JSON.into();
                hist.push(historial(n, &corta(&e, 120)));
                continue;
            }
            Paso::Descartado(motivo) => {
                fallo = motivo;
                hist.push(historial(n, &fallo));
                avisar(descartado(format!("Intento {n} descartado: {fallo}"), n));
                continue;
            }
            Paso::Listo(g) => g,
        };
        if g.pruebas.len() < 3 {
            fallo = "hacen falta al menos 4 pruebas".into();
            hist.push(historial(n, &fallo));
            continue;
        }
        avisar(progreso(format!("Intento {n}: comprobando que la solución pasa las pruebas y el código de partida no…"), n));
        match comprobar_generado(state, &g, lenguaje, 3, n, &mut hist)? {
            Ok((comprobacion, privado)) => {
                return Ok(Mapa::new()
                    .con("titulo", g.datos.valor("titulo").clone())
                    .con("enunciado", g.datos.valor("enunciado").clone())
                    .con("idioma", "es")
                    .con("teoria", "")
                    .con("nivel", g.datos.valor("nivel").clone())
                    .con("conceptos", conceptos_o(&g, tema))
                    .con("lenguaje", lenguaje)
                    .con("paginas", Valor::Lista(g.paginas.iter().cloned().map(con_descripcion).collect()))
                    .con("comprobacion", comprobacion)
                    .con("privado", privado)
                    .con("intentos_creacion", Valor::Lista(hist)));
            }
            Err(motivo) => {
                avisar(descartado(format!("Intento {n} descartado: {}", corta(&motivo, 160)), n));
                fallo = motivo;
            }
        }
    }
    Err(falla(format!(
        "El modelo no consiguió un desafío que se pueda comprobar en {INTENTOS} intentos (último motivo: {}). \
Prueba con un modelo más capaz o con un tema más concreto.",
        corta(&fallo, 200)
    )))
}

/// `{**p, "descripcion": p.get("descripcion", "")}`
fn con_descripcion(mut p: Mapa) -> Valor {
    let d = p.get("descripcion").cloned().unwrap_or(Valor::Texto(String::new()));
    p.poner("descripcion", d);
    Valor::Mapa(p)
}

/// `tutor.replicar_desde_github`: convierte un archivo de GitHub en un desafío interactivo evaluable
#[allow(clippy::too_many_arguments)]
fn replicar(
    state: &AppState,
    m: &Motor,
    modelo: &str,
    r: &str,
    ruta: &str,
    contenido_: &str,
    lenguaje: &str,
    tema: &str,
    nivel: &str,
    c: &Cancelar,
    avisar: &mut dyn FnMut(Mapa),
) -> R<Mapa> {
    const INTENTOS: i64 = 3;
    if cadena::strip(if contenido_.is_empty() { ruta } else { contenido_ }).is_empty() {
        return Err(falla("El archivo de GitHub está vacío o no es válido."));
    }
    let sistema = if lenguaje == "cpp" { SISTEMA_REPLICAR_CPP } else { SISTEMA_REPLICAR };
    let mut fallo = String::new();
    let mut hist: Vec<Valor> = Vec::new();
    let reintento = |f: &str, n: i64| descartado(format!("Intento {n} descartado: {}… Reintentando con correcciones…", corta(f, 120)), n);
    for n in 1..=INTENTOS {
        avisar(progreso(format!("Intento {n} de {INTENTOS}: el modelo analiza y adapta el desafío desde {r}/{ruta}…"), n));
        let mut prompt = format!(
            "Repositorio de origen: {r}\nArchivo de origen: {ruta}\nLenguaje objetivo: {lenguaje}\nNivel sugerido: {nivel}\nTema/Contexto: {}\n\n\
Contenido original del archivo en GitHub (recortado):\n```\n{}\n```\n",
            if tema.is_empty() { ruta } else { tema },
            corta(contenido_, 3500)
        );
        if !fallo.is_empty() {
            prompt += &format!("\nEl intento anterior falló porque: {fallo}\nCorrige este problema.\n");
        }
        prompt += "\nIMPORTANTE: El código en 'paginas' DEBE ser didáctico e incompleto (solo firmas con pass o return dummy / TODOs). \
NUNCA pongas la solución resuelta en 'paginas'. La solución completa va ÚNICAMENTE en 'referencia'.";
        prompt += "\nGenera el desafío didáctico interactivo. Responde ÚNICAMENTE con el objeto JSON válido.";
        let mut tokens: i64 = 0;
        let mut ultimo = std::time::Instant::now();
        let texto = {
            let mut al_token = |_: &str| {
                tokens += 1;
                if ultimo.elapsed().as_secs_f64() >= 2.0 {
                    ultimo = std::time::Instant::now();
                    avisar(progreso(format!("Intento {n} de {INTENTOS}: redactando desafío… ({tokens} tokens)"), n).con("tokens", tokens));
                }
            };
            tutor::generar_texto(&state.base_dir, m, modelo, &prompt, sistema, 0.3, Some("json"), c, Some(&mut al_token)).map_err(falla)?
        };
        let g = match preparar(state, &texto, lenguaje, true)? {
            Paso::Json(e) => {
                fallo = FALLO_JSON.into();
                hist.push(historial(n, &corta(&e, 120)));
                avisar(descartado(format!("Intento {n} descartado: formato no válido ({}). Reintentando con estructura corregida…", corta(&e, 80)), n));
                continue;
            }
            Paso::Descartado(motivo) => {
                fallo = motivo;
                hist.push(historial(n, &fallo));
                avisar(reintento(&fallo, n));
                continue;
            }
            Paso::Listo(g) => g,
        };
        if g.pruebas.len() < 2 {
            fallo = "hacen falta al menos 3 pruebas".into();
            hist.push(historial(n, &fallo));
            avisar(reintento(&fallo, n));
            continue;
        }
        avisar(progreso(format!("Intento {n}: comprobando que la solución pasa las pruebas y el código de partida no…"), n));
        match comprobar_generado(state, &g, lenguaje, 2, n, &mut hist)? {
            Ok((comprobacion, privado)) => {
                return Ok(Mapa::new()
                    .con("titulo", g.datos.valor("titulo").clone())
                    .con("enunciado", g.datos.valor("enunciado").clone())
                    .con("idioma", "es")
                    .con("teoria", format!("Replicado y adaptado automáticamente a partir de `{r}/{ruta}` en GitHub."))
                    .con("nivel", g.datos.valor("nivel").clone())
                    .con("conceptos", conceptos_o(&g, if tema.is_empty() { "algoritmos" } else { tema }))
                    .con("lenguaje", lenguaje)
                    .con("paginas", Valor::Lista(g.paginas.iter().cloned().map(con_descripcion).collect()))
                    .con("comprobacion", comprobacion)
                    .con("privado", privado)
                    .con("intentos_creacion", Valor::Lista(hist))
                    .con(
                        "origen",
                        Mapa::new()
                            .con("tipo", "github")
                            .con("nombre", format!("GitHub · {r}"))
                            .con("ref", format!("{r}/{ruta}"))
                            .con("url", format!("https://github.com/{r}/blob/master/{ruta}"))
                            .con("licencia", "Open Source")
                            .con("lenguaje", lenguaje),
                    ));
            }
            Err(motivo) => {
                avisar(descartado(format!("Intento {n} descartado: {}", corta(&motivo, 160)), n));
                fallo = motivo;
            }
        }
    }
    Err(falla(format!("No se pudo replicar automáticamente el archivo como desafío evaluable tras {INTENTOS} intentos: {}", corta(&fallo, 200))))
}

/// Guarda el desafío creado, registra la telemetría (con el número de intentos) y devuelve su vista pública
fn entregar(espacio: &std::path::Path, mut des: Mapa, evento: &str) -> Result<Valor, String> {
    let intentos = match des.get("intentos_creacion") {
        Some(Valor::Lista(l)) if !l.is_empty() => l.len() as i64,
        _ => 1,
    };
    guardar_y_registrar(espacio, &mut des, evento, intentos).map_err(texto_error)?;
    Ok(Valor::Mapa(d::publico(&des)))
}

fn es_gemini(modelo: &str) -> bool {
    modelo.starts_with(prig_ia::gemini::PREFIJO)
}

// =========================================================================== rutas

/// `Optional[str] = defecto` del cuerpo: el valor (None si vino null) o el defecto si no vino
fn con_defecto(c: &Mapa, k: &str, defecto: &str) -> Option<String> {
    if c.contiene(k) {
        opcional(c, k)
    } else {
        Some(defecto.into())
    }
}

/// `POST /api/desafios/crear`: el modelo crea el desafío; solo se entrega si se comprueba ejecutándolo (NDJSON)
pub async fn crear_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    const MENSAJES: Tipo = Tipo::Lista(&Tipo::Dict(&Tipo::Texto));
    let c = match pedido(
        &b,
        &[
            ("tema", &Tipo::Texto, false),
            ("nivel", &Tipo::Texto, false),
            ("lenguaje", &Tipo::Texto, false),
            ("modelo", &TEXTO_OPC, false),
            ("conversacion", &MENSAJES, false),
            ("ruta_id", &TEXTO_OPC, false),
            ("bloque_id", &TEXTO_OPC, false),
            ("basado_en", &TEXTO_OPC, false),
            ("ajuste", &TEXTO_OPC, false),
        ],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let modelo = tutor::modelo_desafios(opcional(&c, "modelo").as_deref().filter(|m| !m.is_empty()), Some("codigo"));
    let (m, nombre) = match motor(Some(&modelo), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    let (ruta_id, bloque_id) = (opcional(&c, "ruta_id"), opcional(&c, "bloque_id"));
    let e2 = espacio.clone();
    let bloque = match tokio::task::spawn_blocking(move || contexto_bloque(&e2, ruta_id.as_deref(), bloque_id.as_deref())).await {
        Ok(Ok(b)) => b,
        Ok(Err(r)) => return r,
        Err(_) => return error_500(),
    };
    let lenguaje = c.texto("lenguaje").unwrap_or("python").to_string();
    let mut partes: Vec<String> = Vec::new();
    let mut tema = cadena::strip(c.texto("tema").unwrap_or_default()).to_string();
    let mut nivel = c.texto("nivel").unwrap_or("intermedio").to_string();
    if !bloque.is_empty() {
        partes.push(format!("Ruta de aprendizaje: {}", bloque.get("meta").map(Valor::texto_py).unwrap_or_else(|| "None".into())));
        if bloque.verdad("bloque") {
            let temas = match bloque.get("temas") {
                Some(v) if v.verdad() => iterar(v).unwrap_or_default().iter().map(Valor::texto_py).collect::<Vec<_>>().join(", "),
                _ => String::new(),
            };
            let o = |k: &str| match bloque.get(k) {
                Some(v) if v.verdad() => v.texto_py(),
                _ => String::new(),
            };
            let nombre_bloque = bloque.valor("bloque").texto_py();
            partes.push(format!(
                "Bloque: {nombre_bloque}. Temas: {temas}. Objetivo: {}. Cómo se comprueba que lo aprendió: {}",
                o("objetivo"),
                o("validacion")
            ));
            if tema.is_empty() {
                tema = format!("{nombre_bloque} ({temas})");
            }
        }
    }
    let conversacion = lista(c.get("conversacion"));
    if !conversacion.is_empty() {
        partes.push(format!("Conversación con el alumno sobre qué quiere practicar:\n{}", conversacion_como_contexto(&conversacion)));
    }
    let basado_en = opcional(&c, "basado_en").filter(|b| !b.is_empty());
    if let Some(id) = &basado_en {
        let dir = carpeta_base().join("desafios");
        let id2 = id.clone();
        let previo = match tokio::task::spawn_blocking(move || d::obtener(&dir, &id2)).await {
            Ok(Ok(Valor::Mapa(p))) => p,
            Ok(Err(e)) => return error_obtener(e),
            _ => return error_500(),
        };
        if tema.is_empty() {
            let conceptos = match previo.get("conceptos") {
                Some(v) if v.verdad() => iterar(v).unwrap_or_default().iter().map(Valor::texto_py).collect::<Vec<_>>().join(", "),
                _ => String::new(),
            };
            tema = if conceptos.is_empty() { previo.get("titulo").map(Valor::texto_py).unwrap_or_default() } else { conceptos };
        }
        let ajuste = opcional(&c, "ajuste").unwrap_or_default();
        let orden = match ajuste.as_str() {
            "mas_dificil" => "más difícil",
            "mas_facil" => "más fácil",
            _ => "parecido en dificultad",
        };
        let campo = |k: &str| previo.get(k).map(Valor::texto_py).unwrap_or_else(|| "None".into());
        partes.push(format!(
            "El alumno acaba de trabajar el desafío «{}» (nivel {}). Crea uno DISTINTO sobre los mismos conceptos, {orden}.",
            campo("titulo"),
            campo("nivel")
        ));
        let previo_nivel = previo.texto("nivel").filter(|n| NIVELES.contains(n));
        if let (true, Some(pn)) = (ajuste == "mas_dificil" || ajuste == "mas_facil", previo_nivel) {
            let i = NIVELES.iter().position(|x| *x == pn).unwrap() as i64 + if ajuste == "mas_dificil" { 1 } else { -1 };
            nivel = NIVELES[i.clamp(0, NIVELES.len() as i64 - 1) as usize].to_string();
        } else if let Some(v) = previo.get("nivel").filter(|v| v.verdad()) {
            nivel = v.texto_py();
        }
    }
    let contexto = partes.join("\n\n");
    let st = state.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let mut des = crear(&st, &m, &nombre, &tema, &nivel, &contexto, &lenguaje, cancelar, avisar).map_err(texto_error)?;
        let nube = es_gemini(&modelo);
        des.poner("lenguaje", lenguaje.clone());
        let mut origen = Mapa::new()
            .con("tipo", if bloque.is_empty() { "modelo" } else { "plan" })
            .con("nombre", format!("{}{}", if bloque.is_empty() { "Modelo" } else { "Plan de estudios" }, if nube { " · Google Gemini" } else { "" }))
            .con("modelo", modelo.clone())
            .con("motor", if nube { "gemini" } else { "ollama" })
            .con("tema", tema.clone())
            .con("lenguaje", lenguaje.clone());
        for (k, v) in bloque.iter() {
            origen.poner(k.clone(), v.clone());
        }
        if let Some(b) = &basado_en {
            origen.poner("basado_en", b.clone());
        }
        des.poner("origen", origen);
        entregar(&espacio, des, "generated")
    })
}

/// `POST /api/desafios/github/replicar`: replica un archivo o ejercicio de GitHub como desafío evaluable (NDJSON)
pub async fn replicar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido(
        &b,
        &[
            ("ref", &Tipo::Texto, true),
            ("ruta", &Tipo::Texto, true),
            ("contenido", &TEXTO_OPC, false),
            ("lenguaje", &TEXTO_OPC, false),
            ("tema", &TEXTO_OPC, false),
            ("nivel", &TEXTO_OPC, false),
            ("modelo", &TEXTO_OPC, false),
        ],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let modelo = tutor::modelo_desafios(opcional(&c, "modelo").as_deref().filter(|m| !m.is_empty()), Some("codigo"));
    let (m, nombre) = match motor(Some(&modelo), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let r = c.texto("ref").unwrap_or_default().to_string();
    let ruta = c.texto("ruta").unwrap_or_default().to_string();
    let lenguaje = con_defecto(&c, "lenguaje", "python").filter(|l| !l.is_empty()).unwrap_or_else(|| {
        if [".cpp", ".cc", ".cxx", ".h", ".hpp"].iter().any(|e| ruta.ends_with(e)) { "cpp".into() } else { "python".into() }
    });
    let tema = opcional(&c, "tema").unwrap_or_default();
    let nivel = con_defecto(&c, "nivel", "intermedio").filter(|n| !n.is_empty()).unwrap_or_else(|| "intermedio".into());
    let dado = opcional(&c, "contenido").unwrap_or_default();
    let espacio = espacio_de_trabajo(&state).await;
    let st = state.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let mut contenido = dado;
        if contenido.is_empty() {
            avisar(Mapa::new().con("tipo", "progreso").con("mensaje", format!("Descargando archivo desde GitHub ({r}/{ruta})…")));
            contenido = descargar_contenido_archivo(&r, &ruta);
            if contenido.is_empty() {
                contenido = match prig_integrations::github::leer_archivo(&r, &ruta) {
                    Ok(info) => match info.get("contenido") {
                        Some(v) if v.verdad() => v.texto_py(),
                        _ => String::new(),
                    },
                    Err(_) => String::new(),
                };
            }
        }
        if cadena::strip(&contenido).is_empty() {
            return Err(format!(
                "No se pudo obtener el contenido del archivo '{ruta}' de '{r}'. Verifica que el archivo exista y que haya conexión con GitHub."
            ));
        }
        let bajo = ruta.to_lowercase();
        if bajo.ends_with(".ipynb") || bajo.ends_with(".json") {
            avisar(Mapa::new().con("tipo", "progreso").con("mensaje", "Extrayendo celdas de teoría y código del cuaderno Jupyter…"));
            contenido = extraer_contenido_cuaderno(&contenido);
        }
        let des = replicar(&st, &m, &nombre, &r, &ruta, &contenido, &lenguaje, &tema, &nivel, cancelar, avisar).map_err(texto_error)?;
        entregar(&espacio, des, "replicated_from_github")
    })
}

/// `POST /api/youtube/crear-desafio`: un desafío a partir de un objetivo o tema del video (NDJSON)
pub async fn youtube_crear(State(state): State<AppState>, b: Bytes) -> Response {
    const TEXTOS_OPC: Tipo = Tipo::Opcional(&Tipo::Lista(&Tipo::Texto));
    let c = match pedido(
        &b,
        &[
            ("video_id", &Tipo::Texto, true),
            ("titulo_video", &Tipo::Texto, true),
            ("objetivo_id", &TEXTO_OPC, false),
            ("objetivo_titulo", &TEXTO_OPC, false),
            ("objetivo_descripcion", &TEXTO_OPC, false),
            ("conceptos", &TEXTOS_OPC, false),
            ("nivel", &TEXTO_OPC, false),
            ("lenguaje", &TEXTO_OPC, false),
            ("modelo", &TEXTO_OPC, false),
        ],
    ) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let modelo = tutor::modelo_desafios(opcional(&c, "modelo").as_deref().filter(|m| !m.is_empty()), Some("codigo"));
    let (m, nombre) = match motor(Some(&modelo), None) {
        Ok(x) => x,
        Err(r) => return r,
    };
    let titulo_video = c.texto("titulo_video").unwrap_or_default().to_string();
    let video_id = c.texto("video_id").unwrap_or_default().to_string();
    let objetivo_titulo = con_defecto(&c, "objetivo_titulo", "").unwrap_or_default();
    let tema = if objetivo_titulo.is_empty() { titulo_video.clone() } else { objetivo_titulo };
    let conceptos: Vec<String> = lista(c.get("conceptos")).iter().map(Valor::texto_py).collect();
    let conceptos = if conceptos.is_empty() { "conceptos vistos en la clase".to_string() } else { conceptos.join(", ") };
    let descripcion = con_defecto(&c, "objetivo_descripcion", "").filter(|d| !d.is_empty()).unwrap_or_else(|| "Demostrar dominio práctico resolviendo el problema".into());
    let lenguaje = con_defecto(&c, "lenguaje", "python").filter(|l| !l.is_empty()).unwrap_or_else(|| "python".into());
    let nivel = con_defecto(&c, "nivel", "intermedio").filter(|n| !n.is_empty()).unwrap_or_else(|| "intermedio".into());
    let contexto = format!(
        "El alumno está estudiando el curso de YouTube: «{titulo_video}» en Prig IDE.\nObjetivo de aprendizaje a dominar: «{tema}».\n\
Detalles didácticos: {descripcion}.\nConceptos clave: {conceptos}.\nCrea un desafío didáctico e interactivo en {lenguaje} con pruebas unitarias que verifiquen \
estos conceptos específicos y un esqueleto limpio con comentarios TODO."
    );
    let objetivo_id = c.get("objetivo_id").cloned().unwrap_or(Valor::Nulo);
    let espacio = espacio_de_trabajo(&state).await;
    let st = state.clone();
    ndjson_trabajo(move |cancelar, avisar| {
        let mut des = crear(&st, &m, &nombre, &tema, &nivel, &contexto, &lenguaje, cancelar, avisar).map_err(texto_error)?;
        let nube = es_gemini(&modelo);
        des.poner("lenguaje", lenguaje.clone());
        des.poner(
            "origen",
            Mapa::new()
                .con("tipo", "youtube")
                .con("nombre", format!("YouTube · {titulo_video}{}", if nube { " · Google Gemini" } else { "" }))
                .con("modelo", modelo.clone())
                .con("motor", if nube { "gemini" } else { "ollama" })
                .con("video_id", video_id.clone())
                .con("tema", tema.clone())
                .con("objetivo_id", objetivo_id.clone())
                .con("lenguaje", lenguaje.clone()),
        );
        entregar(&espacio, des, "generated")
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn limpia_el_codigo_del_modelo() {
        assert_eq!(limpiar_codigo("```python\ndef f():\n  // hola\n  pass\n```", "python"), "def f():\n  # hola\n  pass");
        assert_eq!(limpiar_codigo("int x; // ok\n```", "cpp"), "int x; // ok");
    }

    #[test]
    fn normaliza_lo_que_escribe_el_modelo() {
        let datos = prig_ia::json_modelo::reparar(
            r#"{"challenge": {"titulo": "Suma", "nivel": "AVANZADO", "starter_code": "def suma(a, b):\n    pass",
            "solution": "def suma(a, b):\n    return a + b", "tests": "from mod import suma\nassert suma(1, 2) == 3\n\nfrom math import pi\nassert pi"}}"#,
        )
        .unwrap();
        let d = normalizar_creado(datos, "python").unwrap();
        assert_eq!(d.valor("nivel").texto_py(), "avanzado");
        let pags = mapas(d.lista("paginas").unwrap());
        assert_eq!(pags[0].texto("nombre"), Some("solucion.py"));
        assert_eq!(pags[0].texto("descripcion"), Some(""));
        let pruebas: Vec<String> = d.lista("pruebas").unwrap().iter().map(Valor::texto_py).collect();
        assert_eq!(pruebas, ["from solucion import suma\nassert suma(1, 2) == 3", "from math import pi\nassert pi"]);
    }

    #[test]
    fn vacia_cuerpos_de_cpp() {
        let c = "#include <x>\nint suma(int a, int b) {\n    if (a) { return a; }\n    return a + b; // }\n}\nvoid nada() { int x = '}'; }\nint main() {\n    return suma(1, 2);\n}\n";
        assert_eq!(
            vaciar_cuerpos_cpp(c),
            "#include <x>\nint suma(int a, int b) {\n    // TODO: implementar solución\n    return {};\n}\nvoid nada() {\n    // TODO: implementar solución\n}\nint main() {\n    return suma(1, 2);\n}\n"
        );
    }

    #[test]
    fn cuaderno_en_texto() {
        let nb = r##"{"cells": [{"cell_type": "markdown", "source": ["# Hola\n", "mundo"]}, {"cell_type": "code", "source": "x = 1"}, {"cell_type": "raw", "source": ["y"]}]}"##;
        assert_eq!(extraer_contenido_cuaderno(nb), "# [Instrucciones / Explicación]\n# Hola\nmundo\n\n\n```\nx = 1\n```\n");
        assert_eq!(extraer_contenido_cuaderno("no es json"), "no es json");
    }
}

// =========================================================================== los prompts (los de tutor.py)

const SISTEMA_CREAR: &str = r##"Eres un CREADOR DE DESAFÍOS DE PROGRAMACIÓN en Python para aprender razonando.

Devuelve ÚNICAMENTE un objeto JSON válido (sin bloques markdown ni ``` alrededor ni dentro de los campos) con esta forma:
{
  "titulo": "Título breve",
  "enunciado": "Contexto del problema, qué hay que construir, reglas y 2 o 3 ejemplos de entrada → salida (en markdown)",
  "nivel": "principiante | intermedio | avanzado | senior",
  "conceptos": ["concepto 1", "concepto 2"],
  "paginas": [
    {"nombre": "archivo.py", "descripcion": "para qué sirve esta página", "contenido": "código de partida"}
  ],
  "referencia": [
    {"nombre": "archivo.py", "contenido": "solución completa de esa página"}
  ],
  "pruebas": [
    "from archivo import funcion\nassert funcion(2) == 4",
    "from archivo import funcion\nassert funcion(0) == 0"
  ]
}

REGLAS:
1. PÁGINAS: usa UNA página si el problema es una función o una clase. Usa 2 o 3 páginas solo
   cuando el diseño lo pide de verdad (por ejemplo: modelo de datos, lógica, programa
   principal). Las páginas se usan entre sí con import: `from inventario import Producto`
   (el nombre del módulo es el de la página sin .py). Nombres de página: minúsculas, _ y .py.
2. El código de partida tiene firmas, docstrings y `pass` o `raise NotImplementedError`,
   con comentarios TODO que orienten. NUNCA la solución: CADA página con funciones o clases
   debe tener algo por implementar. SIEMPRE incluye `pass` en cuerpos incompletos para que
   el código compile limpiamente.
3. "referencia" tiene exactamente las mismas páginas que "paginas", completas y correctas.
4. "pruebas": entre 4 y 8 fragmentos INDEPENDIENTES; cada uno importa lo que usa y termina en
   assert. Incluye casos normales y casos límite (vacío, cero, negativos, repetidos…).
   Deben PASAR con la referencia y FALLAR con el código de partida.
5. Si el nivel es 'senior', incluye en el enunciado las cotas asintóticas requeridas (tiempo y espacio O(...))
   y prueba casos exigentes y límites de escala.
6. Solo biblioteca estándar. Nada de input(), red, archivos ni aleatoriedad sin semilla.
7. Usa \n para los saltos de línea dentro de las cadenas JSON. NUNCA envuelvas el valor de "contenido" en cercas ```."##;

const SISTEMA_CREAR_CPP: &str = r##"Eres un CREADOR DE DESAFÍOS DE PROGRAMACIÓN en C++ (estándar C++20) para aprender razonando.

Devuelve ÚNICAMENTE un objeto JSON válido (sin bloques markdown ni ``` alrededor ni dentro de los campos) con esta forma:
{
  "titulo": "Título breve",
  "enunciado": "Contexto del problema, qué hay que construir, firmas de funciones o clases, reglas y 2 o 3 ejemplos de entrada → salida (en markdown)",
  "nivel": "principiante | intermedio | avanzado | senior",
  "conceptos": ["concepto 1", "concepto 2"],
  "paginas": [
    {"nombre": "solucion.h", "descripcion": "declaraciones de la clase o funciones", "contenido": "código de cabecera con comentarios"},
    {"nombre": "solucion.cpp", "descripcion": "implementación a completar", "contenido": "esqueleto con TODOs y valores por defecto"}
  ],
  "referencia": [
    {"nombre": "solucion.h", "contenido": "cabecera completa"},
    {"nombre": "solucion.cpp", "contenido": "implementación correcta y completa"}
  ],
  "pruebas": [
    "REQUIRE(funcion(2) == 4);",
    "REQUIRE(funcion(0) == 0);"
  ]
}

REGLAS:
1. PÁGINAS: define una cabecera (.h) con las declaraciones e interfaces, y una implementación (.cpp) con el esqueleto. Nombres en minúsculas y guiones bajos (solucion.h, solucion.cpp).
2. El código de partida DEBE compilar limpiamente pero FALLAR las pruebas (devuelve 0, false, "", etc., con comentarios // TODO). NUNCA dejes la solución completa en las páginas de partida.
3. "referencia" tiene exactamente las mismas páginas que "paginas", con la solución completa, eficiente y correcta.
4. "pruebas": entre 4 y 8 aserciones con REQUIRE(...) de Catch2 (no incluyas TEST_CASE, solo la línea con REQUIRE o bloque).
5. Si el nivel es 'senior', especifica complejidades O(...) en el enunciado, aprovecha características de C++20 (ranges, concepts, move semantics si aplica) y garantiza eficiencia sin copias innecesarias.
6. Solo biblioteca estándar C++ (STL). Nada de librerías externas ni entrada interactiva std::cin.
7. Usa \n para los saltos de línea dentro de las cadenas JSON. NUNCA envuelvas el valor de "contenido" en cercas ```."##;

const SISTEMA_REPLICAR: &str = r##"Eres un EXPERTO EN EDUCACIÓN DE PROGRAMACIÓN. Tu tarea es tomar código, un ejercicio, algoritmo o problema de un repositorio de GitHub y convertirlo en un DESAFÍO DIDÁCTICO interactivo para Prig IDE en Python.

Devuelve ÚNICAMENTE un objeto JSON válido (sin bloques markdown ni ``` alrededor ni dentro de los campos) con esta forma:
{
  "titulo": "Título breve y descriptivo en español",
  "enunciado": "Explicación clara del problema en español, requisitos, reglas y 2 o 3 ejemplos de entrada → salida (en markdown)",
  "nivel": "principiante | intermedio | avanzado | senior",
  "conceptos": ["concepto 1", "concepto 2"],
  "paginas": [
    {"nombre": "modulo.py", "descripcion": "Descripción del módulo", "contenido": "código de partida con firmas y pass/TODOs"}
  ],
  "referencia": [
    {"nombre": "modulo.py", "contenido": "solución completa, óptima y limpia"}
  ],
  "pruebas": [
    "from modulo import funcion\nassert funcion(2) == 4",
    "from modulo import funcion\nassert funcion(0) == 0"
  ]
}

REGLAS:
1. El código de partida ("paginas") NO debe contener la solución: incluye las firmas de funciones/clases, docstrings explicativos y comentarios # TODO con pass o retorno neutro. CADA función, método o clase sin implementar DEBE tener `pass` para que el código compile sin errores de sintaxis pero falle las pruebas.
2. "referencia" debe implementar la solución correcta, eficiente y completa.
3. "pruebas": de 3 a 6 aserciones independientes con assert, importando el módulo de las páginas.
4. Si es de nivel 'senior' o algoritmo complejo, incluye en el enunciado las cotas de complejidad esperadas.
5. Solo biblioteca estándar de Python.
6. Usa \n para saltos de línea dentro de cadenas JSON. NUNCA envuelvas el valor de "contenido" en cercas ```."##;

const SISTEMA_REPLICAR_CPP: &str = r##"Eres un EXPERTO EN EDUCACIÓN DE PROGRAMACIÓN. Tu tarea es tomar código, un ejercicio, algoritmo o problema de un repositorio de GitHub y convertirlo en un DESAFÍO DIDÁCTICO interactivo para Prig IDE en C++ (estándar C++20).

Devuelve ÚNICAMENTE un objeto JSON válido (sin bloques markdown ni ``` alrededor ni dentro de los campos) con esta forma:
{
  "titulo": "Título breve y descriptivo en español",
  "enunciado": "Explicación clara del problema en español, firmas de funciones o clases, requisitos y 2 o 3 ejemplos de entrada → salida (en markdown)",
  "nivel": "principiante | intermedio | avanzado | senior",
  "conceptos": ["concepto 1", "concepto 2"],
  "paginas": [
    {"nombre": "solucion.h", "descripcion": "declaraciones de clases o funciones", "contenido": "#ifndef SOLUCION_H\n#define SOLUCION_H\n...\n#endif"},
    {"nombre": "solucion.cpp", "descripcion": "esqueleto de implementación", "contenido": "#include \"solucion.h\"\n... con valores dummy y // TODO"}
  ],
  "referencia": [
    {"nombre": "solucion.h", "contenido": "cabecera completa"},
    {"nombre": "solucion.cpp", "contenido": "implementación correcta y completa"}
  ],
  "pruebas": [
    "REQUIRE(funcion(2) == 4);",
    "REQUIRE(funcion(0) == 0);"
  ]
}

REGLAS:
1. "paginas": define cabecera (.h) e implementación (.cpp) con esqueleto que compila pero falla las pruebas (devuelve 0, false, \"\", etc., con // TODO).
2. "referencia" contiene la solución completa, eficiente y óptima en C++20.
3. "pruebas": de 3 a 6 aserciones con REQUIRE(...) de Catch2 (no incluyas TEST_CASE).
4. Si es de nivel 'senior', detalla requerimientos de complejidad y asegura el uso óptimo de memoria y STL.
5. Solo biblioteca estándar C++ (STL).
6. Usa \n para saltos de línea dentro de cadenas JSON. NUNCA envuelvas el valor de "contenido" en cercas ```."##;
