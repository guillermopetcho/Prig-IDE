//! Notebooks de Kaggle explicados, en PDF (`kaggle_pdf.py`): el código celda a celda con la explicación guardada del
//! profesor debajo. El documento es una lista de bloques que compone Typst (`prig_documentos`).

use crate::kaggle::{self, ErrorKaggle, Fallo};
use crate::kaggle_red;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use sha1::{Digest, Sha1};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

pub const CARPETA_PDF: &str = "kaggle_pdf";

fn md(t: &str) -> String {
    prig_documentos::marcado::escapar_md(t)
}

fn enlace(url: &str) -> String {
    format!("[{}](<{}>)", md(url), url.replace('<', "%3C").replace('>', "%3E"))
}

fn s(v: Option<&Valor>) -> String {
    match v {
        Some(Valor::Nulo) | None => String::new(),
        Some(v) => v.texto_py(),
    }
}

/// `x or ""`
fn o_vacio(v: Option<&Valor>) -> String {
    match v {
        Some(v) if v.verdad() => v.texto_py(),
        _ => String::new(),
    }
}

/// Las opciones del PDF
#[derive(Clone, Default)]
pub struct Opciones {
    pub nivel: Option<String>,
    pub solo_explicadas: bool,
    pub guia: bool,
    pub salidas: bool,
    pub chat: Option<Vec<Mapa>>,
}

fn celdas(nb: &Mapa) -> Vec<Mapa> {
    nb.lista("celdas").unwrap_or(&[]).iter().filter_map(|c| if let Valor::Mapa(m) = c { Some(m.clone()) } else { None }).collect()
}

/// `_clave_explicacion`
fn clave_explicacion(nb: &Mapa, indice: usize, nivel: &str, modelo: &str) -> String {
    let fuente = celdas(nb).get(indice).map(|c| s(c.get("fuente"))).unwrap_or_default();
    let huella: String = Sha1::digest(fuente.as_bytes()).iter().map(|b| format!("{b:02x}")).collect();
    format!("{indice}:{nivel}:{modelo}:{}", &huella[..10])
}

/// `elegir_explicaciones`: por celda, la explicación más reciente cuyo código coincide (con preferencia por el nivel);
/// y la guía más reciente
fn elegir(nb: &Mapa, nivel: Option<&str>) -> Result<(Vec<(usize, Mapa)>, Option<Mapa>), Fallo> {
    let r = s(nb.get("ref"));
    let guardadas = kaggle::leer_objeto(&kaggle::carpeta().join("explicaciones").join(format!("{}.json", r.replace('/', "__")))).unwrap_or_default();
    let n_celdas = celdas(nb).len();
    let mut por_celda: Vec<(usize, Mapa)> = Vec::new();
    let mut guia: Option<Mapa> = None;
    let fecha = |m: &Mapa| o_vacio(m.get("fecha"));
    for (clave, e) in guardadas.iter() {
        let Valor::Mapa(e) = e else { return Err(Fallo::Interno) };
        if let Some(modelo) = clave.strip_prefix("guia:") {
            if guia.as_ref().is_none_or(|g| fecha(e) > fecha(g)) {
                guia = Some(e.clone().con("modelo", modelo));
            }
            continue;
        }
        let partes: Vec<&str> = clave.split(':').collect();
        if partes.len() < 4 {
            continue;
        }
        let Ok(indice) = partes[0].trim().parse::<i64>() else { return Err(Fallo::Interno) };
        let (nivel_e, modelo) = (partes[1], partes[2..partes.len() - 1].join(":"));
        if indice < 0 || indice as usize >= n_celdas || clave_explicacion(nb, indice as usize, nivel_e, &modelo) != *clave {
            continue;
        }
        let i = indice as usize;
        let candidata = e.clone().con("nivel", nivel_e).con("modelo", modelo);
        let pos = por_celda.iter().position(|x| x.0 == i);
        let mejor = match pos {
            None => true,
            Some(p) => {
                let actual = &por_celda[p].1;
                let (a, b) = (Some(nivel_e) == nivel, actual.texto("nivel") == nivel);
                a > b || (a == b && fecha(e) > fecha(actual))
            }
        };
        if mejor {
            match pos {
                Some(p) => por_celda[p].1 = candidata,
                None => por_celda.push((i, candidata)),
            }
        }
    }
    Ok((por_celda, guia))
}

fn bloque(tipo: &str) -> Mapa {
    Mapa::new().con("tipo", tipo)
}

fn caja_codigo(codigo: &str, lenguaje: Option<&str>, salida: bool, max_lineas: Option<i64>) -> Mapa {
    bloque("codigo")
        .con("texto", codigo)
        .con("lenguaje", lenguaje.map(|l| Valor::Texto(l.into())).unwrap_or(Valor::Nulo))
        .con("salida", salida)
        .con("max_lineas", max_lineas.map(|n| Valor::Entero(n as i128)).unwrap_or(Valor::Nulo))
}

fn profesor(texto: &str, etiqueta: &str) -> Mapa {
    bloque("profesor").con("etiqueta", etiqueta).con("texto", texto)
}

fn portada(titulo: &Valor, subtitulo: &str, lineas: Vec<String>) -> Mapa {
    let hoy = py::ahora_iso();
    let (a, m, d) = (&hoy[..4], &hoy[5..7], &hoy[8..10]);
    bloque("portada")
        .con("etiqueta", subtitulo)
        .con("titulo", titulo.clone())
        .con("lineas", Valor::Lista(lineas.into_iter().map(Valor::Texto).collect()))
        .con("fecha", format!("Generado con Prig el {d}/{m}/{a}"))
}

fn textos(v: Option<&Valor>) -> Vec<String> {
    v.and_then(|v| if let Valor::Lista(l) = v { Some(l.iter().map(|x| x.texto_py()).collect()) } else { None }).unwrap_or_default()
}

/// `_historia_notebook`: los bloques de un notebook y cuántas celdas explicadas lleva
fn historia(nb: &Mapa, op: &Opciones, con_portada: bool) -> Result<(Vec<Mapa>, usize), Fallo> {
    let (por_celda, guia) = elegir(nb, op.nivel.as_deref())?;
    let mut fl = Vec::new();
    let mut modelos: Vec<String> = por_celda.iter().map(|(_, e)| s(e.get("modelo")).replace("gemini:", "Gemini ")).collect();
    modelos.sort();
    modelos.dedup();
    let mut fuentes = textos(nb.get("competiciones"));
    fuentes.extend(textos(nb.get("datasets")));
    let fuentes = fuentes.join(", ");
    let cs = celdas(nb);
    let url = s(nb.get("url"));
    let autor = o_vacio(nb.get("autor"));
    if con_portada {
        let mut lineas = vec![format!("de **{}** · {} celdas · {} explicadas por el profesor", md(&autor), cs.len(), por_celda.len()), enlace(&url)];
        if !fuentes.is_empty() {
            lineas.push(format!("Datos: {}", md(&fuentes)));
        }
        if !modelos.is_empty() {
            lineas.push(format!("Profesor: {}", md(&modelos.join(", "))));
        }
        fl.push(portada(nb.valor("titulo"), "NOTEBOOK DE KAGGLE EXPLICADO", lineas));
        fl.push(bloque("espacio").con("alto", 28));
        fl.push(bloque("nota").con(
            "texto",
            md(&format!(
                "{} Autoría del notebook original: {autor}. Las explicaciones las generó un modelo de IA: pueden contener errores.",
                o_vacio(nb.get("licencia"))
            )),
        ));
        fl.push(bloque("salto"));
    } else {
        fl.push(bloque("seccion").con("texto", nb.valor("titulo").clone()));
        fl.push(bloque("nota").con("texto", format!("de {} · {} de {} celdas explicadas · {}", md(&autor), por_celda.len(), cs.len(), enlace(&url))));
    }
    if let Some(g) = guia.filter(|_| op.guia) {
        fl.push(bloque("seccion").con("texto", "Guía de lectura"));
        fl.push(profesor(&s(g.get("texto")), "PROFESOR · ANTES DE EMPEZAR"));
        fl.push(bloque("espacio").con("alto", 10));
    }
    fl.push(bloque("seccion").con("texto", "El notebook, celda a celda"));
    for c in &cs {
        let indice = c.get("indice").and_then(|v| v.entero()).unwrap_or(-1);
        let exp = por_celda.iter().find(|(i, _)| *i as i128 == indice).map(|x| &x.1);
        if op.solo_explicadas && exp.is_none() {
            continue;
        }
        let fuente = s(c.get("fuente"));
        if py::strip(&fuente).is_empty() {
            continue;
        }
        let markdown = c.texto("tipo") == Some("markdown");
        fl.push(bloque("celda").con("texto", format!("CELDA {indice} · {}", if markdown { "TEXTO" } else { "CÓDIGO" })));
        if markdown {
            fl.push(bloque("markdown").con("texto", fuente).con("profesor", false));
        } else {
            fl.push(caja_codigo(&fuente, Some("python"), false, None));
            let salida = o_vacio(c.get("salida"));
            if !salida.is_empty() && op.salidas {
                fl.push(bloque("nota").con("texto", "Salida guardada"));
                fl.push(caja_codigo(&salida, None, true, Some(30)));
            }
        }
        if let Some(e) = exp {
            let nivel = o_vacio(e.get("nivel"));
            let etiqueta = format!("PROFESOR{}", if nivel.is_empty() { String::new() } else { format!(" · NIVEL {}", nivel.to_uppercase()) });
            fl.push(profesor(&s(e.get("texto")), &etiqueta));
        }
        fl.push(bloque("espacio").con("alto", 6));
    }
    let chat: Vec<&Mapa> = op.chat.iter().flatten().filter(|m| !py::strip(&o_vacio(m.get("texto"))).is_empty()).collect();
    if !chat.is_empty() {
        fl.push(bloque("salto"));
        fl.push(bloque("seccion").con("texto", "Preguntas al profesor"));
        for m in chat.into_iter().take(80) {
            let t = s(m.get("texto"));
            if m.texto("rol") == Some("usuario") {
                fl.push(bloque("alumno").con("texto", format!("Tú: {}", t.chars().take(3000).collect::<String>())));
            } else {
                fl.push(profesor(&t.chars().take(8000).collect::<String>(), "PROFESOR"));
            }
        }
    }
    Ok((fl, por_celda.len()))
}

/// `_construir`: compone el PDF y lo escribe de golpe; sus páginas
fn construir(ruta: &Path, bloques: Vec<Mapa>, titulo: &Valor) -> Result<usize, Fallo> {
    std::fs::create_dir_all(ruta.parent().ok_or(Fallo::Interno)?).map_err(|_| Fallo::Interno)?;
    let doc = Mapa::new()
        .con("titulo", titulo.clone())
        .con("asunto", "Notebook de Kaggle explicado")
        .con("estilo", "notebook")
        .con("pie", true)
        .con("bloques", Valor::Lista(bloques.into_iter().map(Valor::Mapa).collect()));
    let (datos, paginas) = prig_documentos::pdf_de_json(&prig_plataforma::json::escribir_linea(&Valor::Mapa(doc))).map_err(|_| Fallo::Interno)?;
    let tmp = PathBuf::from(format!("{}.tmp", ruta.display()));
    std::fs::write(&tmp, datos).map_err(|_| Fallo::Interno)?;
    std::fs::rename(&tmp, ruta).map_err(|_| Fallo::Interno)?;
    Ok(paginas)
}

static NO_NOMBRE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^A-Za-z0-9_\-.]+").unwrap());

/// `_nombre_archivo`
fn nombre_archivo(t: &str) -> String {
    let n: String = NO_NOMBRE.replace_all(t, "-").trim_matches('-').chars().take(90).collect();
    if n.is_empty() { "notebook".into() } else { n }
}

fn tam(ruta: &Path) -> i128 {
    std::fs::metadata(ruta).map(|m| m.len() as i128).unwrap_or(0)
}

/// `pdf_notebook`: <proyecto>/kaggle_pdf/<slug>.pdf
pub fn pdf_notebook(r: &str, espacio: &Path, op: &Opciones) -> Result<Mapa, Fallo> {
    let nb = kaggle_red::abrir(r, false)?;
    let (bloques, explicadas) = historia(&nb, op, true)?;
    if op.solo_explicadas && explicadas == 0 {
        return Err(Fallo::Usuario(ErrorKaggle(
            "Este notebook todavía no tiene celdas explicadas: pide alguna explicación o exporta el notebook completo.".into(),
        )));
    }
    let slug = s(nb.get("ref")).split('/').nth(1).map(String::from).ok_or(Fallo::Interno)?;
    let ruta = espacio.join(CARPETA_PDF).join(format!("{}.pdf", nombre_archivo(&slug)));
    let paginas = construir(&ruta, bloques, nb.valor("titulo"))?;
    Ok(Mapa::new()
        .con("ruta", ruta.to_string_lossy().into_owned())
        .con("relativa", py::relpath(&ruta.to_string_lossy(), &espacio.to_string_lossy()))
        .con("paginas", paginas as i128)
        .con("explicadas", explicadas as i128)
        .con("celdas", celdas(&nb).len() as i128)
        .con("bytes", tam(&ruta)))
}

/// `pdf_coleccion`: todos los notebooks de una colección en un PDF, con índice
pub fn pdf_coleccion(coleccion: &Mapa, espacio: &Path, op: &Opciones) -> Result<Mapa, Fallo> {
    let items: Vec<Mapa> = coleccion
        .lista("items")
        .unwrap_or(&[])
        .iter()
        .filter_map(|i| if let Valor::Mapa(m) = i { Some(m.clone()) } else { None })
        .filter(|i| i.texto("tipo") == Some("notebook"))
        .collect();
    if items.is_empty() {
        return Err(Fallo::Usuario(ErrorKaggle("Esta colección no tiene notebooks.".into())));
    }
    let mut cargados = Vec::new();
    let mut fallidos = Vec::new();
    for it in &items {
        let r = s(it.get("ref"));
        match kaggle_red::abrir(&r, false) {
            Ok(nb) => cargados.push(nb),
            Err(Fallo::Usuario(e)) => fallidos.push(format!("{r}: {e}")),
            Err(e) => return Err(e),
        }
    }
    if cargados.is_empty() {
        return Err(Fallo::Usuario(ErrorKaggle("No se pudo descargar ninguno de sus notebooks.".into())));
    }
    let nombre = coleccion.valor("nombre").clone();
    let mut bloques = vec![portada(&nombre, "COLECCIÓN DE NOTEBOOKS EXPLICADOS", vec![md(&o_vacio(coleccion.get("descripcion"))), format!("{} notebooks", cargados.len())])];
    bloques.push(bloque("salto"));
    bloques.push(bloque("seccion").con("texto", "Contenido"));
    let indice: Vec<String> =
        cargados.iter().enumerate().map(|(n, nb)| format!("{}\\. **{}** — {}  ", n + 1, md(&s(nb.get("titulo"))), md(&o_vacio(nb.get("autor"))))).collect();
    bloques.push(bloque("markdown").con("texto", indice.join("\n")));
    if !fallidos.is_empty() {
        bloques.push(bloque("nota").con("texto", format!("No incluidos: {}", md(&fallidos.join("; ")))));
    }
    let mut total = 0;
    let sin_chat = Opciones { chat: None, ..op.clone() };
    for nb in &cargados {
        bloques.push(bloque("salto"));
        let (fl, ex) = historia(nb, &sin_chat, false)?;
        bloques.extend(fl);
        total += ex;
    }
    let ruta = espacio.join(CARPETA_PDF).join(format!("coleccion-{}.pdf", nombre_archivo(&nombre.texto_py())));
    let paginas = construir(&ruta, bloques, &nombre)?;
    Ok(Mapa::new()
        .con("ruta", ruta.to_string_lossy().into_owned())
        .con("relativa", py::relpath(&ruta.to_string_lossy(), &espacio.to_string_lossy()))
        .con("paginas", paginas as i128)
        .con("notebooks", cargados.len() as i128)
        .con("explicadas", total as i128)
        .con("no_incluidos", Valor::Lista(fallidos.into_iter().map(Valor::Texto).collect()))
        .con("bytes", tam(&ruta)))
}

/// `_ruta_pdf_segura`: un PDF dentro de <proyecto>/kaggle_pdf (None si no)
pub fn ruta_segura(ruta: &str, espacio: &Path) -> Option<PathBuf> {
    let raiz = std::fs::canonicalize(espacio.join(CARPETA_PDF)).ok()?;
    let real = std::fs::canonicalize(ruta).ok()?;
    (real.starts_with(&raiz) && real != raiz && real.to_string_lossy().ends_with(".pdf") && real.is_file()).then_some(real)
}
