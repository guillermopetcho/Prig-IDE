//! El mapa del proyecto y el paquete de contexto de una pregunta (BancoProyecto.mapa, componer, _lenguajes):
//! los textos que lee el modelo, carácter por carácter como en Python.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::LazyLock;
use std::time::Instant;

use indexmap::IndexMap;
use rusqlite::types::ToSql;
use serde_json::{json, Value};

use super::busqueda::{marcas, Encontrado};
use super::{error, filas, Banco, Resultado};
use crate::extraer::generico::primera_linea;
use crate::py::cadena::{largo, primeros, rstrip, strip};
use crate::py::numero::round;
use crate::py::ruta::{basename, dirname};
use crate::re::Re;
use crate::texto::{bloque_lenguaje, estimar_tokens, CARACTERES_POR_TOKEN};

static MENOS_IMPORTANTE: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"(^|/)(tests?|spec|__tests__|fixtures|data|datos|assets|static|docs?|ejemplos?|examples?)(/|$)", ""));

fn carpeta_o_punto(ruta: &str) -> &str {
    let d = dirname(ruta);
    if d.is_empty() {
        "."
    } else {
        d
    }
}

/// Un texto de Python que puede ser None (f"{x}" escribe «None»).
fn s(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::String(x) => x.clone(),
        otro => otro.to_string(),
    }
}

fn verdadero(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|x| x != 0.0).unwrap_or(false),
        Value::String(x) => !x.is_empty(),
        Value::Array(x) => !x.is_empty(),
        Value::Object(x) => !x.is_empty(),
    }
}

fn lista_str(v: &Value) -> Vec<String> {
    match v {
        Value::Array(xs) => xs.iter().map(s).collect(),
        _ => vec![],
    }
}

struct Archivo {
    ruta: String,
    resumen: Option<String>,
    resumen_ia: Option<String>,
}

impl Banco {
    /// `mapa(presupuesto)`: estructura estable del proyecto, plegando lo menos importante si no cabe.
    pub fn mapa(&self, presupuesto: i64) -> Resultado<String> {
        let c = self.conectar()?;
        let archivos: Vec<Archivo> = {
            let mut st = c.prepare("SELECT ruta, lenguaje, resumen, resumen_ia FROM archivos ORDER BY ruta").map_err(error)?;
            let v = st
                .query_map([], |f| Ok(Archivo { ruta: f.get::<_, Option<String>>(0)?.unwrap_or_default(), resumen: f.get(2)?, resumen_ia: f.get(3)? }))
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            v
        };
        let mut simbolos: HashMap<String, Vec<String>> = HashMap::new();
        {
            let mut st = c
                .prepare("SELECT ruta, nombre, tipo FROM simbolos WHERE padre = '' AND tipo IN ('clase','funcion','tipo') ORDER BY ruta, ini")
                .map_err(error)?;
            let mut fs = st.query([]).map_err(error)?;
            while let Some(f) = fs.next().map_err(error)? {
                let r: String = f.get::<_, Option<String>>(0).map_err(error)?.unwrap_or_default();
                let n: String = f.get::<_, Option<String>>(1).map_err(error)?.unwrap_or_else(|| "None".into());
                simbolos.entry(r).or_default().push(n);
            }
        }
        let mut importancia: HashMap<String, i64> = HashMap::new();
        {
            let mut st = c.prepare("SELECT destino, COUNT(*) n FROM importaciones GROUP BY destino").map_err(error)?;
            let mut fs = st.query([]).map_err(error)?;
            while let Some(f) = fs.next().map_err(error)? {
                let d: String = f.get::<_, Option<String>>(0).map_err(error)?.unwrap_or_else(|| "None".into());
                let n: i64 = f.get(1).map_err(error)?;
                *importancia.entry(d).or_insert(0) += 3 * n;
            }
            let mut st = c
                .prepare("SELECT s.ruta, COUNT(*) n FROM usos u JOIN simbolos s ON s.corto = u.nombre
                                  AND s.ruta != u.ruta GROUP BY s.ruta")
                .map_err(error)?;
            let mut fs = st.query([]).map_err(error)?;
            while let Some(f) = fs.next().map_err(error)? {
                let r: String = f.get::<_, Option<String>>(0).map_err(error)?.unwrap_or_else(|| "None".into());
                let n: i64 = f.get(1).map_err(error)?;
                *importancia.entry(r).or_insert(0) += n;
            }
        }
        if archivos.is_empty() {
            return Ok(String::new());
        }
        let nombre = basename(&self.raiz);
        let mut res_carpeta: HashMap<String, String> = HashMap::new();
        {
            let mut st = c.prepare("SELECT clave, texto FROM resumenes WHERE nivel = 'carpeta'").map_err(error)?;
            let mut fs = st.query([]).map_err(error)?;
            while let Some(f) = fs.next().map_err(error)? {
                let k: String = f.get::<_, Option<String>>(0).map_err(error)?.unwrap_or_else(|| "None".into());
                let t: String = f.get::<_, Option<String>>(1).map_err(error)?.unwrap_or_else(|| "None".into());
                res_carpeta.insert(k, t);
            }
        }
        let res_proyecto: String = c
            .query_row("SELECT texto FROM resumenes WHERE nivel = 'proyecto'", [], |f| f.get::<_, Option<String>>(0))
            .ok()
            .map(|x| x.unwrap_or_else(|| "None".into()))
            .unwrap_or_default();
        let cabecera = format!(
            "MAPA DEL PROYECTO «{nombre}» ({} archivos). Estructura estable; el código relevante y los cambios recientes llegan con cada pregunta, y con las herramientas puedes consultar cualquier parte.\n{}",
            archivos.len(),
            if res_proyecto.is_empty() { String::new() } else { format!("Resumen: {res_proyecto}\n") }
        );
        let imp = |r: &str| *importancia.get(r).unwrap_or(&0);
        let mut orden: Vec<&Archivo> = archivos.iter().collect();
        orden.sort_by(|a, b| (-imp(&a.ruta), &a.ruta).cmp(&(-imp(&b.ruta), &b.ruta)));
        let mut detalle: HashMap<String, u8> = archivos.iter().map(|a| (a.ruta.clone(), 0)).collect();
        let linea = |a: &Archivo, nivel: u8| -> String {
            let mut texto = format!("  {}", basename(&a.ruta));
            if nivel >= 1 {
                let resumen = a.resumen_ia.clone().filter(|x| !x.is_empty()).or_else(|| a.resumen.clone());
                if let Some(r) = resumen.filter(|x| !x.is_empty()) {
                    texto.push_str(&format!(" — {}", primeros(&r, 140)));
                }
            }
            if nivel >= 2 {
                if let Some(lista) = simbolos.get(&a.ruta).filter(|l| !l.is_empty()) {
                    let primeros14: Vec<&str> = lista.iter().take(14).map(|x| x.as_str()).collect();
                    texto.push_str(&format!(" · {}", primeros14.join(", ")));
                    if lista.len() > 14 {
                        texto.push_str(&format!(" (+{})", lista.len() - 14));
                    }
                }
            }
            texto
        };
        let mut carpetas: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for a in &archivos {
            carpetas.entry(carpeta_o_punto(&a.ruta).to_string()).or_default().push(a.ruta.clone());
        }
        let mut subarbol: IndexMap<String, Vec<String>> = IndexMap::new();
        for a in &archivos {
            let partes: Vec<&str> = carpeta_o_punto(&a.ruta).split('/').collect();
            for k in 1..=partes.len() {
                subarbol.entry(partes[..k].join("/")).or_default().push(a.ruta.clone());
            }
        }
        let plegada = |carpeta: &str, colapsar: &HashSet<String>| -> Option<String> {
            let partes: Vec<&str> = carpeta.split('/').collect();
            for k in 1..=partes.len() {
                let p = partes[..k].join("/");
                if colapsar.contains(&p) {
                    return Some(p);
                }
            }
            None
        };
        let por_ruta: HashMap<&str, &Archivo> = archivos.iter().map(|a| (a.ruta.as_str(), a)).collect();
        let render = |colapsar: &HashSet<String>, detalle: &HashMap<String, u8>| -> String {
            let mut partes = vec![cabecera.clone()];
            let mut hechas: HashSet<String> = HashSet::new();
            for (carpeta, rutas) in &carpetas {
                if let Some(tope) = plegada(carpeta, colapsar) {
                    if !hechas.insert(tope.clone()) {
                        continue;
                    }
                    let lista = &subarbol[&tope];
                    let n_carpetas = lista.iter().map(|r| dirname(r)).collect::<HashSet<_>>().len();
                    let ejemplo: Vec<&str> = lista.iter().take(3).map(|r| basename(r)).collect();
                    let donde = if n_carpetas > 1 { format!(" en {n_carpetas} carpetas") } else { String::new() };
                    let resumen = res_carpeta.get(&tope).map(|t| format!(" — {}", primeros(t, 220))).unwrap_or_default();
                    partes.push(format!("{tope}/ ({} archivos{donde}: {}…){resumen}", lista.len(), ejemplo.join(", ")));
                    continue;
                }
                let resumen = res_carpeta.get(carpeta).map(|t| format!(" — {}", primeros(t, 220))).unwrap_or_default();
                partes.push(format!("{carpeta}/{resumen}"));
                for r in rutas {
                    partes.push(linea(por_ruta[r.as_str()], detalle[r]));
                }
            }
            partes.join("\n")
        };
        let peso = |d: &str| -> f64 {
            let lista = &subarbol[d];
            let total: i64 = lista.iter().map(|r| imp(r)).sum();
            let mut base = total as f64 / lista.len() as f64;
            if MENOS_IMPORTANTE.hay(d) {
                base *= 0.3;
            }
            base
        };
        let mut colapsar: HashSet<String> = HashSet::new();
        let mut total = estimar_tokens(&render(&colapsar, &detalle));
        let mut candidatas: Vec<&String> = subarbol.keys().filter(|d| d.as_str() != ".").collect();
        candidatas.sort_by(|a, b| {
            let (pa, pb) = (peso(a), peso(b));
            pa.partial_cmp(&pb)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| (-(subarbol[a.as_str()].len() as i64)).cmp(&-(subarbol[b.as_str()].len() as i64)))
                .then_with(|| a.cmp(b))
        });
        for d in candidatas {
            if (total as f64) <= presupuesto as f64 * 0.5 {
                break;
            }
            if plegada(d, &colapsar).is_some() || subarbol[d.as_str()].len() < 3 {
                continue;
            }
            colapsar.insert(d.clone());
            total = estimar_tokens(&render(&colapsar, &detalle));
        }
        let visibles: Vec<&Archivo> = orden.into_iter().filter(|a| !colapsar.contains(carpeta_o_punto(&a.ruta))).collect();
        for nivel in [1u8, 2u8] {
            for a in &visibles {
                let previo = detalle[&a.ruta];
                if previo >= nivel {
                    continue;
                }
                let coste = estimar_tokens(&linea(a, nivel)) - estimar_tokens(&linea(a, previo));
                if total + coste > presupuesto {
                    continue;
                }
                detalle.insert(a.ruta.clone(), nivel);
                total += coste;
            }
        }
        Ok(render(&colapsar, &detalle))
    }

    /// `_lenguajes`.
    pub fn lenguajes(&self, rutas: &[String]) -> Resultado<HashMap<String, String>> {
        if rutas.is_empty() {
            return Ok(HashMap::new());
        }
        let c = self.conectar()?;
        let sql = format!("SELECT ruta, lenguaje FROM archivos WHERE ruta IN ({})", marcas(rutas.len()));
        let args: Vec<&dyn ToSql> = rutas.iter().map(|x| x as &dyn ToSql).collect();
        let mut st = c.prepare(&sql).map_err(error)?;
        let v = st
            .query_map(args.as_slice(), |f| Ok((f.get::<_, Option<String>>(0)?.unwrap_or_default(), f.get::<_, Option<String>>(1)?.unwrap_or_default())))
            .map_err(error)?
            .collect::<rusqlite::Result<HashMap<_, _>>>()
            .map_err(error)?;
        Ok(v)
    }

    /// `componer`: lo relevante para una pregunta dentro del presupuesto. `vector`: el de la pregunta (ya
    /// calculado por quien llama; None si no hay vectores).
    pub fn componer(&self, pregunta: &str, presupuesto: i64, version_vista: Option<i64>, excluir_rutas: &HashSet<String>, usar_resoluciones: bool, vector: Option<&[f64]>) -> Resultado<Value> {
        let t0 = Instant::now();
        let vista = match version_vista {
            Some(v) => v,
            None => self.meta("version_vista")?.and_then(|v| v.trim().parse::<i64>().ok()).unwrap_or(0),
        };
        let fragmentos = self.buscar(pregunta, 40, vector)?;
        let rutas_top: HashSet<String> = fragmentos.iter().take(8).map(|f| f.ruta.clone()).collect();
        let conocimiento = self.buscar_conocimiento(pregunta, 6, vector, Some(&rutas_top))?;
        let resoluciones = if usar_resoluciones { self.buscar_resoluciones(pregunta, 3, vector)? } else { vec![] };
        let cambios = if vista < self.version()? { self.cambios_desde(vista, 40)? } else { vec![] };
        let mut secciones: Vec<String> = vec![];
        let mut usado: i64 = 0;

        // 1. Cambios desde la última respuesta (hasta un 20 %)
        if !cambios.is_empty() {
            let tope = (presupuesto as f64 * 0.2) as i64;
            let mut lineas = vec!["## Cambios en el proyecto desde tu última respuesta".to_string()];
            for ch in &cambios {
                let sim = &ch["simbolos"];
                let mut detalle = vec![];
                for (clave, etiqueta) in [("modificados", "cambió"), ("nuevos", "nuevo"), ("borrados", "borró")] {
                    let v = sim.get(clave).cloned().unwrap_or(Value::Null);
                    if verdadero(&v) {
                        let l: Vec<String> = lista_str(&v).into_iter().take(8).collect();
                        detalle.push(format!("{etiqueta}: {}", l.join(", ")));
                    }
                }
                let mut l = format!("- {}: {} (+{} −{})", s(&ch["ruta"]), s(&ch["tipo"]), s(&ch["mas"]), s(&ch["menos"]));
                if !detalle.is_empty() {
                    l.push_str(&format!(" · {}", detalle.join("; ")));
                }
                lineas.push(l);
            }
            let mut texto = lineas.join("\n");
            let mut orden: Vec<&Value> = cambios.iter().collect();
            orden.sort_by_key(|ch| (!rutas_top.contains(&s(&ch["ruta"])), -ch["id"].as_i64().unwrap_or(0)));
            for ch in orden {
                if ch["tipo"].as_str() != Some("modificado") || !verdadero(ch.get("diff").unwrap_or(&Value::Null)) {
                    continue;
                }
                let bloque = format!("\n```diff\n# {}\n{}\n```", s(&ch["ruta"]), s(&ch["diff"]));
                if estimar_tokens(&format!("{texto}{bloque}")) > tope {
                    continue;
                }
                texto.push_str(&bloque);
            }
            if estimar_tokens(&texto) > tope {
                texto = format!("{}\n[…]", primeros(&texto, (tope as f64 * CARACTERES_POR_TOKEN) as usize));
            }
            usado += estimar_tokens(&texto);
            secciones.push(texto);
        }

        // 2. Conocimiento (hasta un 15 %)
        if !conocimiento.is_empty() {
            let tope = (presupuesto as f64 * 0.15) as i64;
            let mut lineas = vec!["## Conocimiento guardado del proyecto (definiciones, teoría, decisiones)".to_string()];
            for k in &conocimiento {
                let aviso = if verdadero(&k["revisar"]) { " ⚠ puede estar desactualizado: sus archivos cambiaron" } else { "" };
                let rutas = lista_str(&k["rutas"]);
                let donde = if rutas.is_empty() { String::new() } else { format!(" [{}]", rutas.iter().take(4).cloned().collect::<Vec<_>>().join(", ")) };
                let l = format!("- ({}) **{}**: {}{donde}{aviso}", s(&k["tipo"]), s(&k["titulo"]), primeros(&s(&k["texto"]), 700));
                let mut prueba = lineas.clone();
                prueba.push(l.clone());
                if estimar_tokens(&prueba.join("\n")) > tope {
                    break;
                }
                lineas.push(l);
            }
            if lineas.len() > 1 {
                let texto = lineas.join("\n");
                usado += estimar_tokens(&texto);
                secciones.push(texto);
            }
        }

        // 3. Resoluciones anteriores parecidas (hasta un 15 %)
        if !resoluciones.is_empty() {
            let tope = (presupuesto as f64 * 0.15) as i64;
            let mut lineas = vec!["## Preguntas parecidas ya resueltas en este proyecto (respuestas anteriores, no verificadas: contrástalas con el código actual antes de repetirlas)".to_string()];
            for r in &resoluciones {
                let cambiaron = lista_str(r.get("cambiaron_despues").unwrap_or(&Value::Null));
                let despues = if cambiaron.is_empty() { String::new() } else { format!(" ⚠ después cambiaron: {}", cambiaron.iter().take(5).cloned().collect::<Vec<_>>().join(", ")) };
                let rutas = lista_str(&r["rutas"]);
                let archivos = if rutas.is_empty() { String::new() } else { format!(" Archivos: {}.", rutas.iter().take(6).cloned().collect::<Vec<_>>().join(", ")) };
                let l = format!(
                    "- ({}) «{}» → {}{archivos}{despues}",
                    primeros(&s(&r["cuando"]), 10),
                    primeros(&s(&r["pregunta"]), 200),
                    primeros(&s(&r["resumen"]), 500)
                );
                let mut prueba = lineas.clone();
                prueba.push(l.clone());
                if estimar_tokens(&prueba.join("\n")) > tope {
                    break;
                }
                lineas.push(l);
            }
            if lineas.len() > 1 {
                let texto = lineas.join("\n");
                usado += estimar_tokens(&texto);
                secciones.push(texto);
            }
        }

        // 4. Código relevante: el resto del presupuesto
        let mut restante = presupuesto - usado;
        let mut elegidos: Vec<Encontrado> = vec![];
        let mut fichas: Vec<Encontrado> = vec![];
        for f in &fragmentos {
            if excluir_rutas.contains(&f.ruta) {
                continue;
            }
            let coste = f.tokens + 20;
            if (coste as f64) <= restante as f64 * 0.9 || (elegidos.is_empty() && coste <= restante) {
                elegidos.push(f.clone());
                restante -= coste;
            } else if fichas.len() < 15 {
                fichas.push(f.clone());
            }
        }
        let vecinos: Vec<Value> = self.vecinos(&elegidos, 12)?.into_iter().filter(|v| !excluir_rutas.contains(&s(&v["ruta"]))).collect();
        if !elegidos.is_empty() {
            let mut por_archivo: IndexMap<String, Vec<Encontrado>> = IndexMap::new();
            for f in &elegidos {
                por_archivo.entry(f.ruta.clone()).or_default().push(f.clone());
            }
            let rutas: Vec<String> = por_archivo.keys().cloned().collect();
            let lenguajes = self.lenguajes(&rutas)?;
            let mut codigo = vec!["## Código relevante, literal del disco (archivo:líneas)".to_string()];
            let mut documentos = vec!["## Documentación del proyecto relacionada".to_string()];
            let mut grupos: Vec<(String, Vec<Encontrado>)> = por_archivo.into_iter().collect();
            grupos.sort_by(|a, b| {
                let ma = a.1.iter().map(|f| f.puntos).fold(f64::NEG_INFINITY, f64::max);
                let mb = b.1.iter().map(|f| f.puntos).fold(f64::NEG_INFINITY, f64::max);
                mb.partial_cmp(&ma).unwrap_or(std::cmp::Ordering::Equal)
            });
            for (ruta, mut lista) in grupos {
                lista.sort_by_key(|f| f.ini);
                let es_doc = lenguajes.get(&ruta).map(|l| l == "md").unwrap_or(false);
                for f in lista {
                    let nombre = match f.simbolo.as_deref() {
                        Some(x) if !x.is_empty() => format!(" — {x}"),
                        _ => String::new(),
                    };
                    if es_doc {
                        documentos.push(format!("### {ruta}{nombre}\n{}", strip(&f.texto)));
                    } else {
                        let lang = bloque_lenguaje(lenguajes.get(&ruta).map(|s| s.as_str()).unwrap_or(""));
                        codigo.push(format!("### {ruta}:{}-{}{nombre}\n```{lang}\n{}\n```", f.ini, f.fin, f.texto));
                    }
                }
            }
            if codigo.len() > 1 {
                secciones.push(codigo.join("\n"));
            }
            if documentos.len() > 1 {
                secciones.push(documentos.join("\n"));
            }
        }
        let mut otros: Vec<String> = vec![];
        for f in &fichas {
            let nombre = match f.simbolo.as_deref() {
                Some(x) if !x.is_empty() => x.to_string(),
                _ => "(bloque)".to_string(),
            };
            otros.push(format!("- {}:{}-{} {nombre}", f.ruta, f.ini, f.fin));
        }
        for v in &vecinos {
            let doc = if verdadero(v.get("doc").unwrap_or(&Value::Null)) { format!(" — {}", primera_linea(&s(&v["doc"]), 120)) } else { String::new() };
            otros.push(format!("- {}:{} {}{doc} ({})", s(&v["ruta"]), s(&v["ini"]), s(&v["firma"]), s(&v["relacion"])));
        }
        if !otros.is_empty() && restante > 200 {
            let mut texto = "## También relacionado (pídelo con ver_simbolo o leer_archivo si lo necesitas)\n".to_string();
            for o in &otros {
                if estimar_tokens(&format!("{texto}{o}")) > restante - 50 {
                    break;
                }
                texto.push_str(o);
                texto.push('\n');
            }
            secciones.push(rstrip(&texto).to_string());
        }
        let cuerpo = if secciones.is_empty() {
            String::new()
        } else {
            format!(
                "BANCO DEL PROYECTO «{}» — lo relevante para esta pregunta (estado actual del disco):\n\n{}",
                basename(&self.raiz),
                secciones.join("\n\n")
            )
        };
        let archivos: BTreeSet<&str> = elegidos.iter().map(|f| f.ruta.as_str()).collect();
        Ok(json!({
            "texto": cuerpo, "tokens": estimar_tokens(&cuerpo), "fragmentos": elegidos.len(),
            "archivos": archivos.into_iter().collect::<Vec<_>>(), "cambios": cambios.len(),
            "conocimiento": conocimiento.len(), "resoluciones": resoluciones.len(),
            "vectores": vector.is_some(), "version": self.version()?,
            "segundos": round(t0.elapsed().as_secs_f64(), 3),
        }))
    }
}

/// Para quien necesite el ancho en caracteres de un texto ya armado.
pub fn caracteres(texto: &str) -> usize {
    largo(texto)
}

/// Usado por las pruebas: el texto de una fila de `filas` tal como lo formatea Python.
pub fn texto_py(v: &Value) -> String {
    s(v)
}

pub fn ejecutar_filas(b: &Banco, sql: &str) -> Resultado<Vec<Value>> {
    let c = b.conectar()?;
    filas(&c, sql, &[])
}
