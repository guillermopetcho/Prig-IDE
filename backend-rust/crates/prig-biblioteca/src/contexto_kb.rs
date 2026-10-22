//! De la base de conocimiento al contexto del tutor (`contexto_modelo.py`, `indice_semantico.py` y
//! `knowledge_context.py`): el compilador deja cada concepto en una forma densa (signos con leyenda, sujeto elidido,
//! lo que dicen varios libros fundido y códigos cortos de libro), el índice semántico descarta conceptos que no
//! vienen a cuento (opcional: con el embebedor de Ollama) y el ensamblador elige qué entra en el presupuesto.

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

use prig_plataforma::regex_py::{escapar, ExpresionPy};
use prig_recursos::valor::{redondear, Mapa, Valor};
use unicode_general_category::{get_general_category, GeneralCategory};
use unicode_normalization::UnicodeNormalization;

use crate::base_kb::{filas, normalizar_nombre, palabras_contenido, BaseKb};

pub fn tokens(t: &str) -> i64 {
    (t.chars().count() as f64 / 3.6) as i64 + 1
}

fn sin_acentos(t: &str) -> String {
    t.to_lowercase().nfd().filter(|c| get_general_category(*c) != GeneralCategory::NonspacingMark).collect()
}

fn texto(t: &str) -> rusqlite::types::Value {
    rusqlite::types::Value::Text(t.to_string())
}

fn tx(m: &Mapa, k: &str) -> String {
    m.get(k).map(Valor::texto_py).unwrap_or_default()
}

/// `str.isupper()`
fn es_mayusculas(t: &str) -> bool {
    let mut hay = false;
    for c in t.chars() {
        if c.is_lowercase() {
            return false;
        }
        if c.is_uppercase() {
            hay = true;
        }
    }
    hay
}

/// `str.capitalize()`
fn capitalizar(t: &str) -> String {
    let mut c = t.chars();
    match c.next() {
        Some(p) => p.to_uppercase().chain(c.flat_map(char::to_lowercase)).collect(),
        None => String::new(),
    }
}

/// `t[n:]` por caracteres
fn desde(t: &str, n: usize) -> String {
    t.chars().skip(n).collect()
}

/// El final de un `re.match` en caracteres (las posiciones del motor son bytes)
fn fin_en_caracteres(t: &str, fin_bytes: usize) -> usize {
    t[..fin_bytes].chars().count()
}

pub const SIGNOS: [(&str, &str, &str); 14] = [
    ("DEFINITION", "=", "definición"),
    ("INTUITION", "~", "intuición"),
    ("FORMULA", "f", "fórmula"),
    ("RESULT", ">", "resultado"),
    ("PROCEDURE", "@", "procedimiento"),
    ("PROPERTY", "p", "propiedad"),
    ("THEOREM", "T", "teorema"),
    ("ALGORITHM", "A", "algoritmo"),
    ("CODE_PATTERN", "c", "código"),
    ("EXAMPLE", "e", "ejemplo"),
    ("COMPARISON", "/", "contraste"),
    ("CAVEAT", "!", "error típico"),
    ("PITFALL", "!", "error típico"),
    ("NOTATION", "n", "notación"),
];

fn signo_de(tipo: &str) -> &'static str {
    SIGNOS.iter().rev().find(|(t, _, _)| *t == tipo).map(|(_, s, _)| *s).unwrap_or("-")
}

fn orden_tipo(tipo: &str) -> i64 {
    SIGNOS.iter().position(|(t, _, _)| *t == tipo).map(|i| i as i64).unwrap_or(99)
}

const COPULAS: &str = r"(es|son|se\s+define\s+como|se\s+conoce\s+como|consiste\s+en|significa|es\s+una?|es\s+el|es\s+la|se\s+llama|se\s+denomina)";

struct Expresiones {
    relleno: Vec<ExpresionPy>,
    formula: ExpresionPy,
    calificador: ExpresionPy,
    error_tipico: ExpresionPy,
    huella: regex::Regex,
}

fn expresiones() -> &'static Expresiones {
    static E: OnceLock<Expresiones> = OnceLock::new();
    E.get_or_init(|| Expresiones {
        relleno: [
            r"^(se\s+)?(dice|define|establece|afirma|observa|tiene|puede\s+decirse)\s+que\s+",
            r"^(es|son)\s+(decir|un\s+hecho\s+que)\s+",
            r"^(en\s+este\s+caso|por\s+tanto|as[ií]\s+pues|de\s+este\s+modo|de\s+hecho)[,\s]+",
            r"^(conviene|cabe|hay\s+que)\s+(observar|notar|se[nñ]alar|destacar)\s+que\s+",
            r"^(it\s+)?(is|can\s+be)\s+(said|defined|noted|observed)\s+that\s+",
        ]
        .iter()
        .map(|p| ExpresionPy::compilar(p, false).unwrap())
        .collect(),
        formula: ExpresionPy::compilar(r"([A-Za-zΑ-Ωα-ω∇∂][^\s]*\s*[=≈≤≥<>]\s*.+)$", true).unwrap(),
        calificador: ExpresionPy::anclada(r"^(en|para|con|bajo|dentro\s+de)\s+([^,]{3,45}),\s*", false).unwrap(),
        error_tipico: ExpresionPy::compilar(r"^(un\s+)?error\s+(frecuente|com[uú]n|habitual|t[ií]pico)\s+(es|consiste\s+en)\s+", false).unwrap(),
        huella: regex::Regex::new(r"[a-z0-9áéíóúñ]{4,}").unwrap(),
    })
}

/// `re.match(patron, t, re.I)`: el final del acierto (en bytes), si casa al principio
fn casa_al_principio(patron: &str, t: &str) -> Option<usize> {
    let e = ExpresionPy::anclada(patron, false).ok()?;
    e.aciertos(t).into_iter().next().filter(|(i, _)| *i == 0).map(|(_, f)| f)
}

/// `_solo_formula`: de «La solución ridge es w = …» a la fórmula sola
fn solo_formula(t: &str) -> String {
    match expresiones().formula.buscar(t).and_then(|g| g.get(1).cloned().flatten()) {
        Some(f) if f.chars().count() > 6 => crate::base_kb_strip(&f),
        _ => t.to_string(),
    }
}

/// `_elidir`: sin muletillas ni el sujeto que repite la cabecera (con el calificador «En X,» conservado)
pub fn elidir(texto_: &str, nombres: &[String], tipo: &str) -> String {
    let e = expresiones();
    let mut t = crate::base_kb_strip(texto_);
    for r in &e.relleno {
        t = r.sustituir(&t, "");
    }
    if tipo == "FORMULA" {
        t = solo_formula(&t);
    }
    let mut prefijo = String::new();
    if let Some((0, fin)) = e.calificador.aciertos(&t).into_iter().next() {
        let grupos = e.calificador.buscar(&t).unwrap_or_default();
        let candidato = t[fin..].to_string();
        let alts: Vec<String> = nombres.iter().filter(|n| !n.is_empty()).map(|n| escapar(&sin_acentos(n))).collect();
        let patron = format!(r"^(el|la|los|las|un|una)?\s*({})\s", alts.join("|"));
        if casa_al_principio(&patron, &sin_acentos(&candidato)).is_some() {
            prefijo = format!("[{}] ", crate::base_kb_strip(grupos.get(2).cloned().flatten().as_deref().unwrap_or("")));
            t = crate::base_kb_strip(&candidato);
        }
    }
    let mut plano = sin_acentos(&t);
    let mut unicos: Vec<&String> = Vec::new();
    for n in nombres.iter().filter(|n| !n.is_empty()) {
        if !unicos.contains(&n) {
            unicos.push(n);
        }
    }
    unicos.sort_by_key(|n| std::cmp::Reverse(n.chars().count()));
    'nombres: for n in unicos {
        let esc = escapar(&sin_acentos(n));
        for patron in [format!(r"^(el|la|los|las|un|una|lo)?\s*{esc}\s+{COPULAS}\s+"), format!(r"^(el|la|los|las|un|una|lo)?\s*{esc}\s+")] {
            if let Some(fin) = casa_al_principio(&patron, &plano) {
                let fin_c = fin_en_caracteres(&plano, fin);
                if t.chars().count() as i64 - fin_c as i64 > 12 {
                    t = crate::base_kb_strip(&desde(&t, fin_c));
                    plano = sin_acentos(&t);
                    break 'nombres;
                }
            }
        }
    }
    let _ = plano;
    if tipo == "CAVEAT" || tipo == "PITFALL" {
        t = e.error_tipico.sustituir(&t, "");
    }
    let t = crate::base_kb_strip(crate::base_kb_strip(&(prefijo + &t)).trim_end_matches('.'));
    if ["FORMULA", "NOTATION", "CODE_PATTERN"].contains(&tipo) {
        return t;
    }
    let tres: String = t.chars().take(3).collect();
    match t.chars().next() {
        Some(c) if c.is_uppercase() && !es_mayusculas(&tres) => c.to_lowercase().chain(t.chars().skip(1)).collect(),
        _ => t,
    }
}

fn huella(t: &str) -> HashSet<String> {
    expresiones().huella.find_iter(&sin_acentos(t)).map(|m| m.as_str().to_string()).collect()
}

fn misma_idea(a: &str, b: &str) -> bool {
    let (ha, hb) = (huella(a), huella(b));
    if ha.is_empty() || hb.is_empty() {
        return false;
    }
    ha.intersection(&hb).count() as f64 / ha.len().min(hb.len()) as f64 >= 0.62
}

// =========================================================================== el compilador

pub struct Compilador<'a> {
    pub kb: &'a BaseKb,
}

fn lista_texto(l: &[String]) -> Valor {
    Valor::Lista(l.iter().map(|s| Valor::Texto(s.clone())).collect())
}

impl Compilador<'_> {
    /// `codigos_de_libros`: un código corto por libro (el apellido entre paréntesis si lo hay)
    pub fn codigos(&self) -> Result<Vec<(String, Mapa)>, String> {
        let c = self.kb.conectar()?;
        let libros = filas(&c, "SELECT source_id, title, domain FROM books ORDER BY source_id;", &[])?;
        static R: OnceLock<(ExpresionPy, ExpresionPy)> = OnceLock::new();
        let (no_letra, parentesis) = R.get_or_init(|| (ExpresionPy::compilar(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", true).unwrap(), ExpresionPy::compilar(r"\(([^)]+)\)", true).unwrap()));
        let mut usados: HashSet<String> = HashSet::new();
        let mut salida = Vec::new();
        for b in libros {
            let sid = tx(&b, "source_id");
            let titulo = b.get("title").filter(|t| t.verdad()).map(Valor::texto_py);
            let base = no_letra.sustituir(titulo.as_deref().unwrap_or(&sid), " ");
            let m = parentesis.buscar(titulo.as_deref().unwrap_or("")).and_then(|g| g.get(1).cloned().flatten());
            let fuente = m.unwrap_or(base);
            let palabra = crate::base_kb_strip(&fuente).split_whitespace().next().map(String::from).unwrap_or_else(|| sid.clone());
            let mut codigo = capitalizar(&sin_acentos(&palabra).chars().take(3).collect::<String>());
            if codigo.is_empty() {
                codigo = "Lib".into();
            }
            let mut n = 2;
            while usados.contains(&codigo) {
                codigo = format!("{}{n}", codigo.chars().take(3).collect::<String>());
                n += 1;
            }
            usados.insert(codigo.clone());
            salida.push((sid, Mapa::new().con("codigo", codigo).con("titulo", b.get("title").cloned().unwrap_or(Valor::Nulo)).con("dominio", b.get("domain").cloned().unwrap_or(Valor::Nulo))));
        }
        Ok(salida)
    }

    /// `compilar_concepto`
    pub fn compilar_concepto(&self, cid: &str, codigos: Option<&[(String, Mapa)]>) -> Result<Option<Mapa>, String> {
        let propios;
        let codigos = match codigos {
            Some(c) => c,
            None => {
                propios = self.codigos()?;
                &propios
            }
        };
        let c = self.kb.conectar()?;
        let Some(con) = filas(&c, "SELECT * FROM concepts WHERE concept_id = ?;", &[texto(cid)])?.into_iter().next() else { return Ok(None) };
        let afirmaciones = filas(
            &c,
            "SELECT claim_id, type, text, page, source_id, latex, code_language,\n                          confidence\n                   FROM claims WHERE concept_id = ? ORDER BY confidence DESC;",
            &[texto(cid)],
        )?;
        let alias: Vec<String> = filas(&c, "SELECT DISTINCT surface FROM aliases\n                   WHERE concept_id = ? AND surface IS NOT NULL;", &[texto(cid)])?.iter().map(|f| tx(f, "surface")).collect();
        let requiere = filas(
            &c,
            "SELECT DISTINCT co.canonical_name AS n, r.type\n                   FROM relations r JOIN concepts co ON co.concept_id = r.target_concept\n                   WHERE r.source_concept = ? LIMIT 10;",
            &[texto(cid)],
        )?;
        let habilita = filas(
            &c,
            "SELECT DISTINCT co.canonical_name AS n, r.type\n                   FROM relations r JOIN concepts co ON co.concept_id = r.source_concept\n                   WHERE r.target_concept = ? LIMIT 10;",
            &[texto(cid)],
        )?;
        let nombre = tx(&con, "canonical_name");
        let mut nombres = vec![nombre.clone()];
        nombres.extend(alias.iter().filter(|a| !a.is_empty()).cloned());
        let mut vistos: HashSet<String> = HashSet::from([normalizar_nombre(&nombre)]);
        let mut otros = Vec::new();
        for a in &alias {
            let na = normalizar_nombre(a);
            if !na.is_empty() && vistos.insert(na) {
                otros.push(a.clone());
            }
        }
        let mut lineas: Vec<Mapa> = Vec::new();
        for a in &afirmaciones {
            let tipo = tx(a, "type");
            let lleno = |k: &str| a.get(k).filter(|v| v.verdad()).map(Valor::texto_py);
            let crudo = if tipo == "FORMULA" { lleno("latex").or_else(|| lleno("text")) } else { lleno("text") }.unwrap_or_default();
            let t = elidir(&crudo, &nombres, &tipo);
            if t.is_empty() {
                continue;
            }
            let codigo = codigos.iter().find(|(s, _)| *s == tx(a, "source_id")).map(|(_, m)| tx(m, "codigo")).unwrap_or_else(|| "?".into());
            let fuente = Valor::Mapa(Mapa::new().con("codigo", codigo).con("pagina", a.get("page").cloned().unwrap_or(Valor::Nulo)).con("claim_id", a.get("claim_id").cloned().unwrap_or(Valor::Nulo)));
            match lineas.iter_mut().find(|p| tx(p, "tipo") == tipo && misma_idea(&tx(p, "texto"), &t)) {
                Some(p) => {
                    let mut f = p.lista("fuentes").map(<[Valor]>::to_vec).unwrap_or_default();
                    f.push(fuente);
                    p.poner("fuentes", Valor::Lista(f));
                    if t.chars().count() < tx(p, "texto").chars().count() {
                        p.poner("texto", t);
                    }
                }
                None => lineas.push(Mapa::new().con("tipo", tipo.as_str()).con("texto", t).con("fuentes", Valor::Lista(vec![fuente])).con("lenguaje", a.get("code_language").cloned().unwrap_or(Valor::Nulo))),
            }
        }
        lineas.sort_by_key(|l| (orden_tipo(&tx(l, "tipo")), -(l.lista("fuentes").map(|f| f.len()).unwrap_or(0) as i64)));
        let dominios = prig_plataforma::json::leer(&con.get("domains").filter(|d| d.verdad()).map(Valor::texto_py).unwrap_or_else(|| "[]".into())).unwrap_or(Valor::Lista(vec![]));
        let nombres_de = |l: &[Mapa], tipos: &[&str]| lista_texto(&l.iter().filter(|r| tipos.contains(&tx(r, "type").as_str())).map(|r| tx(r, "n")).collect::<Vec<_>>());
        Ok(Some(
            Mapa::new()
                .con("concept_id", cid)
                .con("nombre", nombre.as_str())
                .con("alias", lista_texto(&otros))
                .con("dominios", dominios)
                .con("es_puente", con.get("is_bridge").is_some_and(Valor::verdad))
                .con("lineas", Valor::Lista(lineas.into_iter().map(Valor::Mapa).collect()))
                .con("requiere", nombres_de(&requiere, &["REQUIRES", "PART_OF"]))
                .con("generaliza", nombres_de(&requiere, &["GENERALIZES"]))
                .con("habilita", nombres_de(&habilita, &["REQUIRES", "PART_OF"]))
                .con("contrasta", nombres_de(&requiere, &["CONTRASTS_WITH"]))
                .con("resuelve", nombres_de(&requiere, &["SOLVES", "CAUSES"])),
        ))
    }

    /// `leyenda_de`: solo los signos que aparecen
    pub fn leyenda(usados: &HashSet<String>) -> String {
        let mut vistos = HashSet::new();
        let mut partes = Vec::new();
        for (_, s, n) in SIGNOS {
            if usados.contains(s) && vistos.insert(s) {
                partes.push(format!("{s}{n}"));
            }
        }
        for (s, n) in [("<", "requiere"), (">", "habilita"), ("≠", "contrasta"), ("→", "resuelve")] {
            if usados.contains(s) {
                partes.push(format!("{s}{n}"));
            }
        }
        if partes.is_empty() { String::new() } else { format!("· {}", partes.join("  ")) }
    }

    /// `ordenar_lineas`: según el nivel y el campo preferido
    pub fn ordenar_lineas(lineas: &[Valor], nivel: &str, dominio: Option<&str>, dominio_de_libro: &HashMap<String, Valor>) -> Vec<Mapa> {
        let primero: &[&str] = match nivel {
            "principiante" => &["INTUITION", "EXAMPLE", "DEFINITION", "CAVEAT"],
            "avanzado" => &["THEOREM", "FORMULA", "PROPERTY", "RESULT"],
            _ => &[],
        };
        let mut v: Vec<Mapa> = lineas.iter().filter_map(|l| if let Valor::Mapa(m) = l { Some(m.clone()) } else { None }).collect();
        v.sort_by_key(|l| {
            let tipo = tx(l, "tipo");
            let p = primero.iter().position(|x| *x == tipo).map(|i| i as i64).unwrap_or(primero.len() as i64 + orden_tipo(&tipo));
            let fuentes = l.lista("fuentes").unwrap_or(&[]);
            let del_campo = match dominio {
                Some(d) => {
                    let campos: Vec<Option<&Valor>> = fuentes.iter().map(|f| if let Valor::Mapa(f) = f { dominio_de_libro.get(&tx(f, "codigo")) } else { None }).collect();
                    if campos.iter().any(|c| *c == Some(&Valor::Texto(d.to_string()))) { 0 } else { 1 }
                }
                None => 1,
            };
            (del_campo, p, -(fuentes.len() as i64))
        });
        v
    }

    /// `render_concepto`
    pub fn render(&self, bloque: &Mapa, tope: i64, nivel: &str, dominio: Option<&str>, dominio_de_libro: &HashMap<String, Valor>) -> String {
        let mut cab = format!("@{}", tx(bloque, "nombre"));
        let alias: Vec<String> = bloque.lista("alias").unwrap_or(&[]).iter().map(Valor::texto_py).collect();
        if !alias.is_empty() {
            cab += &format!(" ≡{}", alias.iter().take(4).cloned().collect::<Vec<_>>().join("≡"));
        }
        let dominios = bloque.lista("dominios").unwrap_or(&[]);
        if !dominios.is_empty() {
            let d: Vec<String> = dominios.iter().map(|d| if d.verdad() { d.texto_py().chars().take(2).collect::<String>().to_uppercase() } else { String::new() }).collect();
            cab += &format!("  [{}]", d.join("|"));
        }
        if bloque.verdad("es_puente") {
            cab += "*";
        }
        let mut lineas = vec![cab];
        let todas = bloque.lista("lineas").unwrap_or(&[]);
        let ordenadas: Vec<Mapa> = if nivel != "intermedio" || dominio.is_some() {
            Self::ordenar_lineas(todas, nivel, dominio, dominio_de_libro)
        } else {
            todas.iter().filter_map(|l| if let Valor::Mapa(m) = l { Some(m.clone()) } else { None }).collect()
        };
        for l in ordenadas {
            let fuentes: Vec<String> = l
                .lista("fuentes")
                .unwrap_or(&[])
                .iter()
                .take(3)
                .map(|f| {
                    let Valor::Mapa(f) = f else { return String::new() };
                    let p = f.get("pagina").filter(|p| p.verdad()).map(Valor::texto_py).unwrap_or_default();
                    format!("{}{p}", tx(f, "codigo"))
                })
                .collect();
            let linea = format!("{} {} {{{}}}", signo_de(&tx(&l, "tipo")), tx(&l, "texto"), fuentes.join(","));
            if tope != 0 && tokens(&(lineas.join("\n") + &linea)) > tope {
                break;
            }
            lineas.push(linea);
        }
        for (e, k) in [("<", "requiere"), (">", "habilita"), ("≠", "contrasta"), ("→", "resuelve")] {
            let v: Vec<String> = bloque.lista(k).unwrap_or(&[]).iter().take(5).map(Valor::texto_py).collect();
            if !v.is_empty() {
                lineas.push(format!("{e} {}", v.join(", ")));
            }
        }
        lineas.join("\n")
    }

    fn tokens_sin_compilar(&self, cid: &str) -> Result<i64, String> {
        let f = filas(
            &self.kb.conectar()?,
            "SELECT cl.type, cl.text, cl.quote, cl.page, b.title\n                   FROM claims cl LEFT JOIN books b ON b.source_id = cl.source_id\n                   WHERE cl.concept_id = ?;",
            &[texto(cid)],
        )?;
        let partes: Vec<String> = f.iter().map(|f| format!("- [{}] {}\n  «{}» — {}, p.{}", tx(f, "type"), tx(f, "text"), tx(f, "quote"), tx(f, "title"), tx(f, "page"))).collect();
        Ok(tokens(&partes.join("\n")))
    }

    /// `precompilar`: el bloque de cada concepto, compilado y guardado
    pub fn precompilar(&self) -> Result<Mapa, String> {
        let codigos = self.codigos()?;
        let ids: Vec<String> = {
            let c = self.kb.conectar()?;
            c.execute_batch(
                "CREATE TABLE IF NOT EXISTS contexto_modelo (concept_id TEXT PRIMARY KEY, bloque TEXT, texto TEXT, tokens INTEGER, tokens_origen INTEGER, compilado_en TEXT, version TEXT);
                 CREATE TABLE IF NOT EXISTS contexto_libros (source_id TEXT PRIMARY KEY, codigo TEXT, titulo TEXT, dominio TEXT);
                 DELETE FROM contexto_libros;",
            )
            .map_err(|e| e.to_string())?;
            for (sid, i) in &codigos {
                let v = |k: &str| match i.get(k) {
                    Some(Valor::Texto(t)) => rusqlite::types::Value::Text(t.clone()),
                    _ => rusqlite::types::Value::Null,
                };
                c.execute("INSERT OR REPLACE INTO contexto_libros VALUES (?,?,?,?);", rusqlite::params_from_iter([texto(sid), v("codigo"), v("titulo"), v("dominio")])).map_err(|e| e.to_string())?;
            }
            filas(&c, "SELECT concept_id FROM concepts WHERE mentions > 0;", &[])?.iter().map(|f| tx(f, "concept_id")).collect()
        };
        let (mut hechos, mut ahorro, mut original) = (0i64, 0i64, 0i64);
        for cid in ids {
            let Some(b) = self.compilar_concepto(&cid, Some(&codigos))? else { continue };
            if b.lista("lineas").map(|l| l.is_empty()).unwrap_or(true) {
                continue;
            }
            let t = self.render(&b, 0, "intermedio", None, &HashMap::new());
            let origen = self.tokens_sin_compilar(&cid)?;
            original += origen;
            ahorro += origen - tokens(&t);
            self.kb
                .conectar()?
                .execute(
                    "INSERT OR REPLACE INTO contexto_modelo VALUES (?,?,?,?,?,?,?);",
                    rusqlite::params![cid, prig_plataforma::json::escribir_linea(&Valor::Mapa(b)), t, tokens(&t), origen, prig_plataforma::py::ahora_iso(), "1.0"],
                )
                .map_err(|e| e.to_string())?;
            hechos += 1;
        }
        Ok(Mapa::new()
            .con("conceptos", hechos)
            .con("tokens_antes", original)
            .con("tokens_despues", original - ahorro)
            .con("reduccion", if original != 0 { Valor::Real(redondear(ahorro as f64 / original as f64 * 100.0, 1)) } else { Valor::Entero(0) }))
    }

    fn guardado(&self, cid: &str, col: &str) -> Option<String> {
        let c = self.kb.conectar().ok()?;
        c.query_row(&format!("SELECT {col} FROM contexto_modelo WHERE concept_id = ?;"), [cid], |f| f.get::<_, Option<String>>(0)).ok().flatten()
    }

    pub fn bloque_json(&self, cid: &str) -> Option<Mapa> {
        match prig_plataforma::json::leer(&self.guardado(cid, "bloque")?).ok()? {
            Valor::Mapa(m) => Some(m),
            _ => None,
        }
    }

    pub fn bloque(&self, cid: &str) -> Option<String> {
        self.guardado(cid, "texto")
    }

    fn libros_compilados(&self) -> Vec<Mapa> {
        self.kb.conectar().ok().and_then(|c| filas(&c, "SELECT source_id, codigo, titulo, dominio FROM contexto_libros;", &[]).ok()).unwrap_or_default()
    }

    /// `cabecera`: la leyenda y los libros que aparecen
    pub fn cabecera(&self, codigos: &HashSet<String>, signos: &HashSet<String>) -> String {
        let libros: Vec<String> = self
            .libros_compilados()
            .iter()
            .filter(|f| codigos.contains(&tx(f, "codigo")))
            .map(|f| {
                let d = f.get("dominio").filter(|d| d.verdad()).map(|d| format!("[{}]", d.texto_py().chars().take(2).collect::<String>().to_uppercase())).unwrap_or_default();
                format!("{}={}{d}", tx(f, "codigo"), tx(f, "titulo"))
            })
            .collect();
        let leyenda = Self::leyenda(signos);
        let libros = libros.join("  ");
        let mut partes = Vec::new();
        if !leyenda.is_empty() {
            partes.push(leyenda);
        }
        if !libros.is_empty() {
            partes.push(format!("· {libros}"));
        }
        partes.join("\n")
    }

    /// `compilar_para`: varios conceptos en un presupuesto, con la cabecera de lo que aparece
    pub fn compilar_para(&self, ids: &[String], presupuesto: i64, nivel: &str, dominio: Option<&str>) -> Result<Mapa, String> {
        let a_medida = nivel != "intermedio" || dominio.is_some();
        let mut dominio_de_libro: HashMap<String, Valor> = HashMap::new();
        if a_medida {
            dominio_de_libro = self.libros_compilados().iter().map(|f| (tx(f, "codigo"), f.get("dominio").cloned().unwrap_or(Valor::Nulo))).collect();
            if dominio_de_libro.is_empty() {
                dominio_de_libro = self.codigos()?.iter().map(|(_, m)| (tx(m, "codigo"), m.get("dominio").cloned().unwrap_or(Valor::Nulo))).collect();
            }
        }
        let (mut bloques, mut usados, mut gastado) = (Vec::new(), Vec::new(), 40i64);
        let mut orden_claims: Vec<Valor> = Vec::new();
        for cid in ids {
            let mut compilado: Option<Mapa> = None;
            let mut t = if a_medida { None } else { self.bloque(cid).filter(|t| !t.is_empty()) };
            if t.is_none() {
                compilado = match self.bloque_json(cid) {
                    Some(b) => Some(b),
                    None => self.compilar_concepto(cid, None)?,
                };
                t = compilado.as_ref().map(|b| self.render(b, 0, nivel, dominio, &dominio_de_libro));
            }
            let Some(t) = t.filter(|t| !t.is_empty()) else { continue };
            if compilado.is_none() {
                compilado = self.bloque_json(cid);
            }
            if let Some(b) = &compilado {
                for l in Self::ordenar_lineas(b.lista("lineas").unwrap_or(&[]), nivel, dominio, &dominio_de_libro) {
                    for f in l.lista("fuentes").unwrap_or(&[]) {
                        if let Valor::Mapa(f) = f {
                            orden_claims.push(f.get("claim_id").cloned().unwrap_or(Valor::Nulo));
                        }
                    }
                }
            }
            let coste = tokens(&t);
            if gastado + coste > presupuesto {
                continue;
            }
            bloques.push(t);
            usados.push(cid.clone());
            gastado += coste;
        }
        if bloques.is_empty() {
            return Ok(Mapa::new().con("texto", "").con("tokens", 0).con("conceptos", Valor::Lista(vec![])).con("vacio", true));
        }
        let cuerpo = bloques.join("\n\n");
        let signos: HashSet<String> = prig_recursos::servidor::lineas_como_python(&cuerpo).iter().filter(|l| !l.is_empty() && !l.starts_with('@')).filter_map(|l| l.chars().next().map(String::from)).collect();
        static R: OnceLock<(regex::Regex, regex::Regex)> = OnceLock::new();
        let (llaves, letras) = R.get_or_init(|| (regex::Regex::new(r"\{([^}]+)\}").unwrap(), regex::Regex::new(r"^[A-Za-z]+").unwrap()));
        let mut codigos = HashSet::new();
        for g in llaves.captures_iter(&cuerpo) {
            for r in g[1].split(',') {
                if let Some(m) = letras.find(crate::base_kb_strip(r).as_str()) {
                    codigos.insert(m.as_str().to_string());
                }
            }
        }
        let cab = self.cabecera(&codigos, &signos);
        let t = if cab.is_empty() { cuerpo } else { format!("{cab}\n\n{cuerpo}") };
        Ok(Mapa::new()
            .con("texto", t.as_str())
            .con("tokens", tokens(&t))
            .con("conceptos", lista_texto(&usados))
            .con("orden_claims", Valor::Lista(orden_claims))
            .con("vacio", false))
    }

    /// `citas_de`: las citas literales de un concepto
    pub fn citas_de(&self, cid: &str) -> Result<Vec<Mapa>, String> {
        filas(
            &self.kb.conectar()?,
            "SELECT cl.claim_id, cl.type, cl.text, cl.quote, cl.page,\n                          b.title AS libro\n                   FROM claims cl LEFT JOIN books b ON b.source_id = cl.source_id\n                   WHERE cl.concept_id = ? ORDER BY cl.confidence DESC;",
            &[texto(cid)],
        )
    }
}

// =========================================================================== el índice semántico

/// Quien convierte textos en vectores (el embebedor de Ollama), o error
pub type Embeber<'a> = &'a dyn Fn(&[String]) -> Result<Vec<Vec<f64>>, String>;

pub struct Indice<'a> {
    pub kb: &'a BaseKb,
    pub embeber: Embeber<'a>,
}

impl Indice<'_> {
    fn vectores(&self) -> crate::vectores::Vectores {
        let c = self.kb.conectar();
        let filas: Vec<(String, Vec<f64>)> = c
            .ok()
            .and_then(|c| {
                c.execute_batch("CREATE TABLE IF NOT EXISTS vectores (concept_id TEXT PRIMARY KEY, vector BLOB, dimension INTEGER, modelo TEXT, indexado_en TEXT);").ok()?;
                let mut st = c.prepare("SELECT concept_id, vector FROM vectores;").ok()?;
                let r = st.query_map([], |f| Ok((f.get::<_, String>(0)?, f.get::<_, Vec<u8>>(1)?))).ok()?;
                Some(r.flatten().map(|(id, b)| (id, crate::vectores::desempaquetar(&b))).collect())
            })
            .unwrap_or_default();
        crate::vectores::Vectores::new(filas)
    }

    pub fn hay_indice(&self) -> bool {
        !self.vectores().is_empty()
    }

    /// `puntuar`: (parecido, concept_id) de más a menos
    pub fn puntuar(&self, pregunta: &str, ids: Option<&[String]>) -> Vec<(f64, String)> {
        let v = self.vectores();
        if v.is_empty() {
            return Vec::new();
        }
        if let Some(ids) = ids.filter(|i| !i.is_empty()) {
            if !ids.iter().any(|i| v.contiene(i)) {
                return Vec::new();
            }
        }
        let Ok(qv) = (self.embeber)(&[pregunta.to_string()]) else { return Vec::new() };
        let Some(q) = qv.into_iter().next() else { return Vec::new() };
        let candidatos = v.candidatos(ids.filter(|i| !i.is_empty()));
        v.puntuar(&q, &candidatos)
    }

    /// `filtrar`: de los candidatos, los que vienen a cuento (None si no se puede decidir)
    pub fn filtrar(&self, pregunta: &str, ids: &[String]) -> Option<Vec<String>> {
        if ids.len() <= 1 {
            return None;
        }
        let p = self.puntuar(pregunta, Some(ids));
        let mejor = p.first()?.0;
        if mejor <= 0.0 {
            return None;
        }
        let e: Vec<String> = p.iter().filter(|(s, _)| *s >= mejor * 0.95).take(5).map(|(_, c)| c.clone()).collect();
        Some(if e.is_empty() { vec![p[0].1.clone()] } else { e })
    }

    /// `buscar`: conceptos parecidos a la pregunta, sin candidatos
    pub fn buscar(&self, pregunta: &str, limite: usize) -> Vec<Mapa> {
        let p = self.puntuar(pregunta, None);
        let Some(mejor) = p.first().map(|x| x.0) else { return Vec::new() };
        let Ok(c) = self.kb.conectar() else { return Vec::new() };
        let mut salida = Vec::new();
        for (s, cid) in p.iter().take(limite) {
            if *s < mejor * 0.95 {
                break;
            }
            if let Ok(Some(f)) = filas(&c, "SELECT * FROM concepts WHERE concept_id = ?;", &[texto(cid)]).map(|v| v.into_iter().next()) {
                salida.push(f.con("parecido", redondear(*s, 3)));
            }
        }
        salida
    }
}

// =========================================================================== el ensamblador

const ORDEN_PEDAGOGICO: [(&str, usize); 9] =
    [("DEFINITION", 2), ("INTUITION", 2), ("FORMULA", 2), ("THEOREM", 1), ("ALGORITHM", 1), ("CODE_PATTERN", 2), ("EXAMPLE", 1), ("PROPERTY", 1), ("PITFALL", 2)];

pub struct Ensamblador<'a> {
    pub kb: &'a BaseKb,
    pub compilador: Compilador<'a>,
    pub indice: Indice<'a>,
}

impl<'a> Ensamblador<'a> {
    pub fn new(kb: &'a BaseKb, embeber: Embeber<'a>) -> Ensamblador<'a> {
        Ensamblador { kb, compilador: Compilador { kb }, indice: Indice { kb, embeber } }
    }

    fn concepto(&self, cid: &str) -> Option<Mapa> {
        filas(&self.kb.conectar().ok()?, "SELECT * FROM concepts WHERE concept_id = ?;", &[texto(cid)]).ok()?.into_iter().next()
    }

    pub fn dosier(&self, cid: &str) -> Result<Option<Valor>, String> {
        let c = self.kb.conectar()?;
        let f = filas(&c, "SELECT json FROM dossiers WHERE concept_id = ?;", &[texto(cid)])?;
        Ok(f.first().map(|f| prig_plataforma::json::leer(&tx(f, "json")).unwrap_or(Valor::Nulo)))
    }

    /// `conceptos_de_pregunta`: los conceptos que nombra (secuencias largas primero), si no por texto, si no
    /// por parecido
    pub fn conceptos_de_pregunta(&self, pregunta: &str, maximo: usize) -> Result<Vec<Mapa>, String> {
        static R: OnceLock<regex::Regex> = OnceLock::new();
        let limpia = R.get_or_init(|| regex::Regex::new(r"[^\wáéíóúüñ\s]").unwrap()).replace_all(&pregunta.to_lowercase(), " ").into_owned();
        let palabras: Vec<&str> = limpia.split_whitespace().filter(|p| !crate::base_kb::es_vacia(p)).collect();
        let mut encontrados: Vec<Mapa> = Vec::new();
        let mut cubiertas: HashSet<usize> = HashSet::new();
        for n in (1..=palabras.len().min(5)).rev() {
            for i in 0..=(palabras.len() - n) {
                if (i..i + n).any(|j| cubiertas.contains(&j)) {
                    continue;
                }
                if let Some(c) = self.kb.resolver(&palabras[i..i + n].join(" "))? {
                    let id = c.get("concept_id").cloned();
                    if !encontrados.iter().any(|e| e.get("concept_id").cloned() == id) {
                        encontrados.push(c);
                        cubiertas.extend(i..i + n);
                    }
                }
            }
        }
        let mut orden = encontrados;
        orden.sort_by_key(|c| -(c.get("mentions").filter(|m| m.verdad()).and_then(Valor::num).unwrap_or(0.0) as i64));
        if !orden.is_empty() {
            orden.truncate(maximo);
            return Ok(self.afinar(pregunta, orden));
        }
        let por_texto = self.por_texto(pregunta, maximo)?;
        if !por_texto.is_empty() {
            return Ok(self.afinar(pregunta, por_texto));
        }
        if self.indice.hay_indice() {
            return Ok(self.indice.buscar(pregunta, maximo));
        }
        Ok(Vec::new())
    }

    fn afinar(&self, pregunta: &str, conceptos: Vec<Mapa>) -> Vec<Mapa> {
        if conceptos.len() <= 1 || !self.indice.hay_indice() {
            return conceptos;
        }
        let ids: Vec<String> = conceptos.iter().map(|c| tx(c, "concept_id")).collect();
        let Some(elegidos) = self.indice.filtrar(pregunta, &ids).filter(|e| !e.is_empty()) else { return conceptos };
        let r: Vec<Mapa> = elegidos.iter().filter_map(|id| conceptos.iter().find(|c| tx(c, "concept_id") == *id).cloned()).collect();
        if r.is_empty() { conceptos } else { r }
    }

    fn por_texto(&self, pregunta: &str, maximo: usize) -> Result<Vec<Mapa>, String> {
        let raices: HashSet<String> = palabras_contenido(pregunta).iter().map(|p| normalizar_nombre(p)).filter(|r| !r.is_empty()).collect();
        if raices.is_empty() {
            return Ok(Vec::new());
        }
        let mut vistos = HashSet::new();
        let mut salida = Vec::new();
        for f in self.kb.buscar(pregunta, 12, &[], &[], None)? {
            let Some(cid) = f.get("concept_id").filter(|c| c.verdad()).map(Valor::texto_py) else { continue };
            if vistos.contains(&cid) {
                continue;
            }
            let norm = normalizar_nombre(&format!("{} {}", tx(&f, "text"), tx(&f, "quote")));
            if !norm.split_whitespace().any(|w| raices.contains(w)) {
                continue;
            }
            vistos.insert(cid.clone());
            if let Some(c) = self.concepto(&cid) {
                salida.push(c);
            }
            if salida.len() >= maximo {
                break;
            }
        }
        Ok(salida)
    }

    /// `ensamblar`: el contexto para el prompt del tutor (compilado si se puede)
    pub fn ensamblar(&self, pregunta: &str, presupuesto: i64, dominio: Option<&str>, nivel: &str, compilado: bool) -> Result<Mapa, String> {
        let conceptos = self.conceptos_de_pregunta(pregunta, 4)?;
        if compilado && !conceptos.is_empty() {
            if let Some(d) = self.ensamblar_compilado(&conceptos, presupuesto, nivel, dominio)? {
                return Ok(d);
            }
        }
        if conceptos.is_empty() {
            return Ok(Mapa::new()
                .con("texto", "")
                .con("tokens", 0)
                .con("conceptos", Valor::Lista(vec![]))
                .con("fuentes", Valor::Lista(vec![]))
                .con("vacio", true)
                .con("motivo", "Ningún concepto de la biblioteca coincide con la pregunta"));
        }
        let principal = &conceptos[0];
        let apoyos: Vec<Mapa> = self.kb.prerrequisitos(&tx(principal, "concept_id"), 1)?.into_iter().take(2).collect();
        let ids: HashSet<String> = conceptos.iter().map(|c| tx(c, "concept_id")).collect();
        let mut cola: Vec<Mapa> = conceptos.clone();
        cola.extend(apoyos.into_iter().filter(|a| !ids.contains(&tx(a, "concept_id"))));
        let (mut gastado, mut bloques, mut fuentes, mut usados) = (0i64, Vec::new(), Vec::new(), Vec::new());
        for (pos, con) in cola.iter().enumerate() {
            let Some(Valor::Mapa(dos)) = self.dosier(&tx(con, "concept_id"))? else { continue };
            let reserva = if pos == 0 { presupuesto.div_euclid(2) } else { 200.max((presupuesto - gastado).div_euclid(1.max(cola.len() as i64 - pos as i64))) };
            let (bloque, coste, citas) = self.bloque(&dos, reserva.min(presupuesto - gastado), dominio, nivel, pos == 0);
            if bloque.is_empty() || coste > presupuesto - gastado {
                continue;
            }
            bloques.push(bloque);
            fuentes.extend(citas);
            usados.push(dos.get("nombre").cloned().unwrap_or(Valor::Nulo));
            gastado += coste;
            if gastado as f64 >= presupuesto as f64 * 0.95 {
                break;
            }
        }
        let t = bloques.join("\n\n");
        Ok(Mapa::new()
            .con("texto", t.as_str())
            .con("tokens", tokens(&t))
            .con("presupuesto", presupuesto)
            .con("conceptos", Valor::Lista(usados))
            .con("concepto_principal", principal.get("canonical_name").cloned().unwrap_or(Valor::Nulo))
            .con("fuentes", Valor::Lista(fuentes.into_iter().map(Valor::Mapa).collect()))
            .con("vacio", t.is_empty()))
    }

    fn ensamblar_compilado(&self, conceptos: &[Mapa], presupuesto: i64, nivel: &str, dominio: Option<&str>) -> Result<Option<Mapa>, String> {
        let mut ids: Vec<String> = conceptos.iter().map(|c| tx(c, "concept_id")).collect();
        for a in self.kb.prerrequisitos(&ids[0], 1)?.into_iter().take(2) {
            let id = tx(&a, "concept_id");
            if !ids.contains(&id) {
                ids.push(id);
            }
        }
        let r = self.compilador.compilar_para(&ids, presupuesto, nivel, dominio)?;
        if r.verdad("vacio") {
            return Ok(None);
        }
        let mut fuentes: Vec<Mapa> = Vec::new();
        let mut nombres: Vec<Valor> = Vec::new();
        for cid in r.lista("conceptos").unwrap_or(&[]).iter().map(Valor::texto_py) {
            let con = self.concepto(&cid);
            let nombre = con.as_ref().map(|c| c.get("canonical_name").cloned().unwrap_or(Valor::Nulo)).unwrap_or(Valor::Texto(cid.clone()));
            if con.is_some() {
                nombres.push(nombre.clone());
            }
            for cita in self.compilador.citas_de(&cid)?.into_iter().take(6) {
                fuentes.push(
                    Mapa::new()
                        .con("libro", cita.get("libro").cloned().unwrap_or(Valor::Nulo))
                        .con("pagina", cita.get("page").cloned().unwrap_or(Valor::Nulo))
                        .con("cita", cita.get("quote").cloned().unwrap_or(Valor::Nulo))
                        .con("tipo", cita.get("type").cloned().unwrap_or(Valor::Nulo))
                        .con("concepto", nombre.clone())
                        .con("concept_id", cid.as_str())
                        .con("claim_id", cita.get("claim_id").cloned().unwrap_or(Valor::Nulo)),
                );
            }
        }
        let orden = r.lista("orden_claims").unwrap_or(&[]);
        let posicion = |f: &Mapa| -> usize {
            let id = f.get("claim_id");
            // `{cid: i for i, cid in enumerate(...)}`: si se repite, cuenta la última vez
            orden.iter().rposition(|x| Some(x) == id).unwrap_or(1_000_000)
        };
        fuentes.sort_by_key(posicion);
        Ok(Some(
            Mapa::new()
                .con("texto", r.valor("texto").clone())
                .con("tokens", r.valor("tokens").clone())
                .con("presupuesto", presupuesto)
                .con("conceptos", Valor::Lista(nombres.clone()))
                .con("concepto_principal", nombres.first().cloned().unwrap_or(Valor::Nulo))
                .con("fuentes", Valor::Lista(fuentes.into_iter().map(Valor::Mapa).collect()))
                .con("vacio", false)
                .con("formato", "compilado"),
        ))
    }

    /// `_bloque`: un concepto en texto citable, dentro de su tope
    fn bloque(&self, dos: &Mapa, tope: i64, dominio: Option<&str>, nivel: &str, principal: bool) -> (String, i64, Vec<Mapa>) {
        let nombre = tx(dos, "nombre");
        let mut cab = format!("### {nombre}");
        let otros: Vec<String> = dos.lista("alias").unwrap_or(&[]).iter().map(Valor::texto_py).filter(|a| a.to_lowercase() != nombre.to_lowercase()).take(4).collect();
        if !otros.is_empty() {
            cab += &format!("  (también: {})", otros.join(", "));
        }
        if dos.verdad("es_puente") {
            let d: Vec<String> = dos.lista("dominios").unwrap_or(&[]).iter().map(Valor::texto_py).collect();
            cab += &format!("\n[concepto puente entre {}]", d.join(", "));
        }
        let mut gastado = tokens(&cab);
        let mut lineas = vec![cab];
        let mut citas = Vec::new();
        let mut orden: Vec<(&str, usize)> = ORDEN_PEDAGOGICO.to_vec();
        if nivel == "principiante" {
            orden.sort_by_key(|t| if ["INTUITION", "EXAMPLE", "DEFINITION"].contains(&t.0) { 0 } else { 1 });
        } else if nivel == "avanzado" {
            orden.sort_by_key(|t| if ["THEOREM", "FORMULA", "PROPERTY"].contains(&t.0) { 0 } else { 1 });
        }
        let por_tipo = dos.mapa("por_tipo").cloned().unwrap_or_default();
        for (tipo, maximo) in orden {
            let mut items: Vec<Mapa> = por_tipo.lista(tipo).unwrap_or(&[]).iter().filter_map(|i| if let Valor::Mapa(m) = i { Some(m.clone()) } else { None }).collect();
            if let Some(d) = dominio {
                items.sort_by_key(|a| a.get("domain") != Some(&Valor::Texto(d.to_string())));
            }
            for it in items.iter().take(if principal { maximo } else { 1 }) {
                let mut linea = format!("- [{tipo}] {}", tx(it, "text"));
                if it.get("latex").is_some_and(Valor::verdad) {
                    linea += &format!("\n  {}", tx(it, "latex"));
                }
                if it.get("quote").is_some_and(Valor::verdad) {
                    let q: String = tx(it, "quote").chars().take(220).collect();
                    let p = it.get("page").filter(|p| p.verdad()).map(Valor::texto_py).unwrap_or_else(|| "?".into());
                    linea += &format!("\n  «{q}» — {}, p.{p}", tx(it, "book"));
                }
                let coste = tokens(&linea);
                if gastado + coste > tope {
                    break;
                }
                lineas.push(linea);
                gastado += coste;
                citas.push(
                    Mapa::new()
                        .con("libro", it.get("book").cloned().unwrap_or(Valor::Nulo))
                        .con("pagina", it.get("page").cloned().unwrap_or(Valor::Nulo))
                        .con("cita", it.get("quote").cloned().unwrap_or(Valor::Nulo))
                        .con("tipo", tipo)
                        .con("concepto", nombre.as_str())
                        .con("source_id", it.get("source_id").cloned().unwrap_or(Valor::Nulo)),
                );
            }
        }
        if principal {
            if let Some(pre) = dos.lista("prerrequisitos").filter(|p| !p.is_empty()) {
                let previos: Vec<String> = pre.iter().take(5).map(|p| if let Valor::Mapa(p) = p { tx(p, "nombre") } else { String::new() }).collect();
                let linea = format!("- [REQUIERE] Antes conviene dominar: {}", previos.join(", "));
                if gastado + tokens(&linea) <= tope {
                    gastado += tokens(&linea);
                    lineas.push(linea);
                }
            }
        }
        for a in dos.lista("analogias").unwrap_or(&[]).iter().take(2) {
            let Valor::Mapa(a) = a else { continue };
            if dominio.is_some_and(|d| tx(a, "dominio") == d) {
                continue;
            }
            let linea = format!("- [DESDE {}] {} ({})", tx(a, "dominio").to_uppercase(), tx(a, "texto"), tx(a, "libro"));
            if gastado + tokens(&linea) > tope {
                break;
            }
            gastado += tokens(&linea);
            lineas.push(linea);
        }
        (if lineas.len() > 1 { lineas.join("\n") } else { String::new() }, gastado, citas)
    }

    /// `prompt_tutor`: el mensaje de sistema con su contexto y sus reglas de cita
    pub fn prompt_tutor(&self, pregunta: &str, presupuesto: i64, dominio: Option<&str>, nivel: &str) -> Result<Mapa, String> {
        let ctx = self.ensamblar(pregunta, presupuesto, dominio, nivel, true)?;
        if ctx.verdad("vacio") {
            return Ok(ctx.con("sistema", "Responde con lo que sepas y avisa al alumno de que esta respuesta NO está respaldada por su biblioteca de libros."));
        }
        let denso = ctx.get("formato") == Some(&Valor::Texto("compilado".into()));
        let intro = "Eres un tutor que explica apoyándose EXCLUSIVAMENTE en los libros del alumno. El material de abajo está extraído de ellos.\n\n";
        let (formato, citar, extra) = if denso {
            (
                "El material va comprimido: la primera línea dice qué significa cada signo y qué libro es cada código. Está así para que gastes el esfuerzo en razonar y no en leer. Responde en prosa normal, nunca con estos signos.\n\n",
                "1. Cada dato lleva su fuente entre llaves: {Goo228} es la página 228 del libro con código Goo, declarado arriba. Al afirmar algo del material, di el libro y la página en palabras: «(Goodfellow, p.228)».\n",
                "3. Las líneas < y > son dependencias: lo que hace falta saber antes y lo que esto permite después. Úsalas para ordenar la explicación.\n4. Un concepto con * aparece en varios campos: ánclalo en el que el alumno ya conozca.\n",
            )
        } else {
            (
                "Cada punto lleva su cita textual con libro y página.\n\n",
                "1. Cita el libro y la página cada vez que afirmes algo del material.\n",
                "3. Si hay un bloque [DESDE OTRO CAMPO], úsalo para conectar el tema con algo que el alumno ya conoce.\n",
            )
        };
        let sistema = format!(
            "{intro}{formato}Reglas:\n{citar}2. Si algo no está en el material, dilo explícitamente en lugar de rellenarlo de memoria.\n{extra}5. Empieza por la idea y deja la formalización para después.\n\n--- MATERIAL DE LA BIBLIOTECA ---\n{}\n--- FIN ---",
            tx(&ctx, "texto")
        );
        let n = tokens(&sistema);
        Ok(ctx.con("sistema", sistema).con("tokens_sistema", n))
    }
}
