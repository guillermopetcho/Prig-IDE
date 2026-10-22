//! La ficha de un libro (`perfil_libro.py`): lo que la base guarda de él convertido en los trozos de texto que lee
//! el flujo de agentes, la ficha montada en código con lo que devolvió cada paso, el contexto resumido para el
//! planificador y el material con el que montar un ejercicio sobre un concepto.

use prig_recursos::valor::{Mapa, Valor};
use rusqlite::types::Value as V;

use crate::base_kb::{filas, BaseKb};

const TIPOS_UTILES: [&str; 9] = ["DEFINITION", "INTUITION", "FORMULA", "PROCEDURE", "EXAMPLE", "CAVEAT", "COMPARISON", "RESULT", "NOTATION"];

fn t(s: &str) -> V {
    V::Text(s.to_string())
}

fn tx(m: &Mapa, k: &str) -> String {
    m.get(k).map(Valor::texto_py).unwrap_or_default()
}

/// `x or '?'`
fn o_interrogacion(v: Option<&Valor>) -> String {
    v.filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| "?".into())
}

fn trozo(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

/// `_cabe`: recortado a `tope` tokens (3,6 caracteres cada uno), diciendo cuánto se quitó
fn cabe(texto: &str, tope: i64) -> String {
    let tope = (tope as f64 * 3.6) as usize;
    let n = texto.chars().count();
    if n <= tope {
        return texto.to_string();
    }
    format!("{}\n[… {} caracteres más, recortados …]", trozo(texto, tope), n - tope)
}

fn lista_json(v: Option<&Valor>) -> Vec<Valor> {
    match prig_plataforma::json::leer(&v.filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| "[]".into())) {
        Ok(Valor::Lista(l)) => l,
        _ => Vec::new(),
    }
}

/// `datos`: todo lo guardado del libro, en crudo
pub fn datos(kb: &BaseKb, sid: &str) -> Result<Option<Mapa>, String> {
    let c = kb.conectar()?;
    let Some(mut libro) = filas(&c, "SELECT * FROM books WHERE source_id = ?;", &[t(sid)])?.into_iter().next() else { return Ok(None) };
    let lista = |sql: &str| -> Result<Valor, String> { Ok(Valor::Lista(filas(&c, sql, &[t(sid)])?.into_iter().map(Valor::Mapa).collect())) };
    libro.poner("secciones", lista("SELECT * FROM sections WHERE source_id = ?\n                   ORDER BY es_capitulo DESC, pagina_inicio;")?);
    libro.poner(
        "conceptos",
        lista("SELECT co.canonical_name AS nombre, co.concept_id, co.is_bridge,\n                          co.domains, COUNT(*) AS veces,\n                          MIN(cl.page) AS primera_pagina\n                   FROM claims cl JOIN concepts co ON co.concept_id = cl.concept_id\n                   WHERE cl.source_id = ?\n                   GROUP BY co.concept_id ORDER BY veces DESC;")?,
    );
    let mut por_tipo = Mapa::new();
    for f in filas(&c, "SELECT type, COUNT(*) n FROM claims WHERE source_id = ?\n                   GROUP BY type;", &[t(sid)])? {
        por_tipo.poner(f.get("type").map(|x| if x.es_nulo() { "null".to_string() } else { x.texto_py() }).unwrap_or_default(), f.valor("n").clone());
    }
    libro.poner("por_tipo", por_tipo);
    libro.poner("simbolos", lista("SELECT DISTINCT symbol, meaning, page FROM symbols\n                   WHERE source_id = ? ORDER BY page;")?);
    libro.poner("figuras", lista("SELECT label, caption, tipo, page FROM figures WHERE source_id = ? ORDER BY page;")?);
    libro.poner("preguntas", Valor::Lista(filas(&c, "SELECT texto FROM questions WHERE source_id = ?;", &[t(sid)])?.into_iter().map(|f| f.valor("texto").clone()).collect()));
    libro.poner(
        "relaciones",
        lista("SELECT a.canonical_name AS origen, b.canonical_name AS destino, r.type\n                   FROM relations r\n                   JOIN concepts a ON a.concept_id = r.source_concept\n                   JOIN concepts b ON b.concept_id = r.target_concept\n                   WHERE r.source_id = ? LIMIT 120;")?,
    );
    Ok(Some(libro))
}

fn mapas(d: &Mapa, k: &str) -> Vec<Mapa> {
    d.lista(k).unwrap_or(&[]).iter().filter_map(|x| if let Valor::Mapa(m) = x { Some(m.clone()) } else { None }).collect()
}

fn indice(d: &Mapa) -> String {
    let secciones = mapas(d, "secciones");
    if secciones.is_empty() {
        return "(este libro no trae índice detectado; dedúcelo de los conceptos y sus páginas)".into();
    }
    let mut lineas = Vec::new();
    for s in &secciones {
        let sangria = if s.verdad("es_capitulo") { "" } else { "   " };
        let paginas = if s.get("pagina_inicio").is_some_and(Valor::verdad) { format!(" [p.{}-{}]", tx(s, "pagina_inicio"), tx(s, "pagina_fin")) } else { String::new() };
        let temas: Vec<String> = lista_json(s.get("temas")).iter().take(6).map(Valor::texto_py).collect();
        let mut l = format!("{sangria}{} {}{paginas}", tx(s, "numero"), tx(s, "titulo"));
        if !temas.is_empty() {
            l += &format!("  · temas: {}", temas.join(", "));
        }
        lineas.push(l);
        if s.get("resumen").is_some_and(Valor::verdad) {
            lineas.push(format!("{sangria}   {}", trozo(&tx(s, "resumen"), 160)));
        }
    }
    cabe(&lineas.join("\n"), 1200)
}

fn conceptos(d: &Mapa) -> String {
    let cs = mapas(d, "conceptos");
    if cs.is_empty() {
        return "(sin conceptos extraídos todavía)".into();
    }
    let l: Vec<String> = cs
        .iter()
        .map(|c| {
            let puente = if c.verdad("is_bridge") {
                format!(" ⟷{}", lista_json(c.get("domains")).iter().map(Valor::texto_py).collect::<Vec<_>>().join("/"))
            } else {
                String::new()
            };
            format!("{} ({}×, desde p.{}){puente}", tx(c, "nombre"), tx(c, "veces"), o_interrogacion(c.get("primera_pagina")))
        })
        .collect();
    cabe(&l.join(" · "), 500)
}

fn muestra(kb: &BaseKb, sid: &str) -> Result<String, String> {
    let c = kb.conectar()?;
    let mut lineas = Vec::new();
    for tipo in TIPOS_UTILES {
        let f = filas(&c, "SELECT text, quote, page FROM claims\n                       WHERE source_id = ? AND type = ? ORDER BY page;", &[t(sid), t(tipo)])?;
        if f.is_empty() {
            continue;
        }
        let paso = (f.len() / 4).max(1);
        lineas.push(format!("[{tipo}]"));
        for i in f.iter().step_by(paso).take(4) {
            let texto = i.get("text").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default();
            lineas.push(format!("  p.{} · {}", o_interrogacion(i.get("page")), trozo(&texto, 190)));
        }
    }
    let r = cabe(&lineas.join("\n"), 1400);
    Ok(if r.is_empty() { "(sin afirmaciones)".into() } else { r })
}

fn simbolos(d: &Mapa) -> String {
    let ss = mapas(d, "simbolos");
    if ss.is_empty() {
        return "(no se detectó notación)".into();
    }
    cabe(&ss.iter().map(|s| format!("{} = {} (p.{})", tx(s, "symbol"), tx(s, "meaning"), o_interrogacion(s.get("page")))).collect::<Vec<_>>().join(" · "), 250)
}

fn figuras(d: &Mapa) -> String {
    let fs = mapas(d, "figuras");
    if fs.is_empty() {
        return "(no se detectaron figuras)".into();
    }
    let l: Vec<String> = fs
        .iter()
        .map(|f| {
            let pie = f.get("caption").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default();
            format!("p.{} {}: {}", o_interrogacion(f.get("page")), tx(f, "label"), trozo(&pie, 110))
        })
        .collect();
    cabe(&l.join("\n"), 250)
}

fn preguntas(d: &Mapa) -> String {
    let ps = d.lista("preguntas").unwrap_or(&[]);
    if ps.is_empty() {
        return "(el extractor no guardó preguntas de este libro)".into();
    }
    cabe(&ps.iter().map(|p| format!("- {}", p.texto_py())).collect::<Vec<_>>().join("\n"), 300)
}

fn relaciones(d: &Mapa) -> String {
    let rs = mapas(d, "relaciones");
    if rs.is_empty() {
        return "(sin relaciones entre conceptos)".into();
    }
    cabe(&rs.iter().map(|r| format!("{} —{}→ {}", tx(r, "origen"), tx(r, "type"), tx(r, "destino"))).collect::<Vec<_>>().join(" · "), 500)
}

fn datos_sueltos(d: &Mapa) -> String {
    let mut tipos: Vec<(String, f64)> = d.mapa("por_tipo").map(|m| m.iter().map(|(k, v)| (k.clone(), v.num().unwrap_or(0.0))).collect()).unwrap_or_default();
    tipos.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    let tipos = tipos.iter().map(|(k, v)| format!("{k}: {}", *v as i64)).collect::<Vec<_>>().join(", ");
    let capitulos = mapas(d, "secciones").iter().filter(|s| s.verdad("es_capitulo")).count();
    format!(
        "Título: {}\nCampo: {}\nPáginas: {}\nAfirmaciones extraídas: {} ({tipos})\nConceptos: {}\nCapítulos detectados: {capitulos}\nFiguras: {} · Símbolos: {}",
        tx(d, "title"),
        tx(d, "domain"),
        o_interrogacion(d.get("pages")),
        d.get("claims_verified").map(Valor::texto_py).unwrap_or_else(|| "0".into()),
        d.lista("conceptos").map(|l| l.len()).unwrap_or(0),
        d.lista("figuras").map(|l| l.len()).unwrap_or(0),
        d.lista("simbolos").map(|l| l.len()).unwrap_or(0),
    )
}

/// `variables`: el libro en trozos de texto que caben en un prompt (cada paso pide solo los suyos)
pub fn variables(kb: &BaseKb, sid: &str) -> Result<Option<Mapa>, String> {
    let Some(d) = datos(kb, sid)? else { return Ok(None) };
    let titulo = d.get("title").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| sid.to_string());
    Ok(Some(
        Mapa::new()
            .con("libro:titulo", titulo)
            .con("libro:indice", indice(&d))
            .con("libro:conceptos", conceptos(&d))
            .con("libro:muestra", muestra(kb, sid)?)
            .con("libro:simbolos", simbolos(&d))
            .con("libro:figuras", figuras(&d))
            .con("libro:preguntas", preguntas(&d))
            .con("libro:datos", datos_sueltos(&d))
            .con("libro:relaciones", relaciones(&d)),
    ))
}

/// `listar`: los libros, con cuánto material hay de cada uno y si ya tienen ficha
pub fn listar(kb: &BaseKb) -> Result<Vec<Mapa>, String> {
    filas(
        &kb.conectar()?,
        "\n                SELECT b.source_id, b.title, b.domain, b.pages, b.claims_verified,\n                       (SELECT COUNT(*) FROM sections s WHERE s.source_id = b.source_id\n                        AND s.es_capitulo = 1) AS capitulos,\n                       (SELECT COUNT(DISTINCT concept_id) FROM claims cl\n                        WHERE cl.source_id = b.source_id) AS conceptos,\n                       (SELECT COUNT(*) FROM figures f WHERE f.source_id = b.source_id) AS figuras,\n                       (SELECT built_at FROM book_profiles p\n                        WHERE p.source_id = b.source_id) AS ficha_hecha\n                FROM books b ORDER BY b.title;",
        &[],
    )
}

/// `obtener`: la ficha guardada
pub fn obtener(kb: &BaseKb, sid: &str) -> Result<Option<Valor>, String> {
    let f = filas(&kb.conectar()?, "SELECT json FROM book_profiles WHERE source_id = ?;", &[t(sid)])?;
    Ok(f.first().map(|f| prig_plataforma::json::leer(&tx(f, "json")).unwrap_or(Valor::Nulo)))
}

/// `guardar`
pub fn guardar(kb: &BaseKb, sid: &str, ficha: &Mapa) -> Result<(), String> {
    let modelos = ficha.get("modelos").filter(|v| v.verdad()).cloned().unwrap_or(Valor::Lista(vec![]));
    kb.conectar()?
        .execute(
            "INSERT OR REPLACE INTO book_profiles VALUES (?,?,?,?);",
            rusqlite::params![sid, prig_plataforma::json::escribir_linea(&Valor::Mapa(ficha.clone())), prig_plataforma::py::ahora_iso(), prig_plataforma::json::escribir_linea(&modelos)],
        )
        .map(|_| ())
        .map_err(|e| e.to_string())
}

/// `_json_suelto`: el primer objeto (o lista) JSON de un texto
pub fn json_suelto(texto: &str) -> Option<Valor> {
    for (abre, cierra) in [('{', '}'), ('[', ']')] {
        let Some(i) = texto.find(abre) else { continue };
        let (mut prof, mut cad, mut esc) = (0i64, false, false);
        for (k, ch) in texto[i..].char_indices() {
            if esc {
                esc = false;
                continue;
            }
            if ch == '\\' {
                esc = true;
                continue;
            }
            if ch == '"' {
                cad = !cad;
                continue;
            }
            if cad {
                continue;
            }
            if ch == abre {
                prof += 1;
            } else if ch == cierra {
                prof -= 1;
                if prof == 0 {
                    match prig_plataforma::json::leer(&texto[i..i + k + 1]) {
                        Ok(v) => return Some(v),
                        Err(_) => break,
                    }
                }
            }
        }
    }
    None
}

/// `montar_ficha`: en código, con lo que devolvió cada paso (si uno falló, el resto sirve)
pub fn montar_ficha(kb: &BaseKb, sid: &str, salidas: &Mapa, modelos: &[Valor]) -> Result<Mapa, String> {
    let d = datos(kb, sid)?.unwrap_or_default();
    let mut ficha = Mapa::new()
        .con("source_id", sid)
        .con("titulo", d.get("title").filter(|v| v.verdad()).cloned().unwrap_or(Valor::Texto(sid.into())))
        .con("campo", d.get("domain").cloned().unwrap_or(Valor::Nulo))
        .con("paginas", d.get("pages").cloned().unwrap_or(Valor::Nulo))
        .con("construida", prig_plataforma::py::ahora_iso())
        .con("modelos", Valor::Lista(modelos.to_vec()));
    for (clave, paso) in [("temario", "temario"), ("notacion", "notacion"), ("asume", "prerrequisitos"), ("identidad", "identidad"), ("ejercicios", "ejercicios"), ("lagunas", "lagunas")] {
        let mut valor = salidas.get(paso).cloned().unwrap_or(Valor::Nulo);
        if let Valor::Texto(s) = &valor {
            if let Some(j) = json_suelto(s).filter(|j| j.verdad()) {
                valor = j;
            }
        }
        if let Valor::Mapa(m) = &valor {
            if m.len() == 1 && m.contiene(clave) {
                valor = m.valor(clave).clone();
            }
        }
        if valor.verdad() {
            ficha.poner(clave, valor);
        }
    }
    let cs = mapas(&d, "conceptos");
    ficha.poner(
        "medido",
        Mapa::new()
            .con("conceptos", cs.len() as i64)
            .con("afirmaciones", d.get("claims_verified").cloned().unwrap_or(Valor::Entero(0)))
            .con("por_tipo", d.get("por_tipo").cloned().unwrap_or(Valor::Mapa(Mapa::new())))
            .con("capitulos", mapas(&d, "secciones").iter().filter(|s| s.verdad("es_capitulo")).count() as i64)
            .con("figuras", d.lista("figuras").map(|l| l.len()).unwrap_or(0) as i64)
            .con("simbolos", d.lista("simbolos").map(|l| l.len()).unwrap_or(0) as i64)
            .con("preguntas", d.lista("preguntas").map(|l| l.len()).unwrap_or(0) as i64)
            .con("conceptos_con_material", Valor::Lista(cs.iter().filter(|c| c.valor("veces").num().unwrap_or(0.0) >= 3.0).take(40).map(|c| c.valor("nombre").clone()).collect())),
    );
    Ok(ficha)
}

// =========================================================================== planificador y ejercicios

const CLAVES_NOMBRE: [&str; 6] = ["tema", "nombre", "concepto", "titulo", "texto", "que"];

/// `_nombrar`: un elemento de la ficha, como texto
fn nombrar(x: &Valor) -> String {
    match x {
        Valor::Texto(s) => s.clone(),
        Valor::Mapa(m) => {
            for k in CLAVES_NOMBRE {
                if let Some(Valor::Texto(s)) = m.get(k) {
                    if !prig_plataforma::py::strip(s).is_empty() {
                        let matiz = m.get("gravedad").filter(|v| v.verdad()).or_else(|| m.get("como_de_necesario"));
                        return match matiz {
                            Some(Valor::Texto(mt)) => format!("{s} ({mt})"),
                            _ => s.clone(),
                        };
                    }
                }
            }
            m.iter().filter(|(_, v)| matches!(v, Valor::Texto(_) | Valor::Entero(_) | Valor::Bool(_))).map(|(_, v)| trozo(&v.texto_py(), 40)).collect::<Vec<_>>().join(", ")
        }
        otro => otro.texto_py(),
    }
}

/// `_aplanar`: de la forma que sea a una lista de cosas nombrables
fn aplanar(v: &Valor) -> Vec<Valor> {
    match v {
        Valor::Lista(l) => {
            let mut s = Vec::new();
            for x in l {
                if matches!(x, Valor::Lista(_) | Valor::Mapa(_)) && nombrar(x).is_empty() {
                    s.extend(aplanar(x));
                } else {
                    s.push(x.clone());
                }
            }
            s
        }
        Valor::Mapa(m) => {
            let listas: Vec<&Vec<Valor>> = m.iter().filter_map(|(_, x)| if let Valor::Lista(l) = x { Some(l) } else { None }).collect();
            if !listas.is_empty() {
                return listas.into_iter().flatten().cloned().collect();
            }
            if CLAVES_NOMBRE.iter().any(|k| m.contiene(k)) {
                return vec![v.clone()];
            }
            m.iter().filter(|(_, x)| matches!(x, Valor::Texto(_))).map(|(_, x)| x.clone()).collect()
        }
        x if x.verdad() => vec![x.clone()],
        _ => Vec::new(),
    }
}

fn lista_corta(v: &Valor) -> String {
    aplanar(v).iter().take(8).map(nombrar).filter(|n| !n.is_empty()).collect::<Vec<_>>().join(", ")
}

/// `contexto_para_plan`: las fichas resumidas (hasta 4 libros), para que el plan proponga lo que hay
pub fn contexto_para_plan(kb: &BaseKb) -> Result<String, String> {
    let mut trozos = Vec::new();
    for libro in listar(kb)?.into_iter().take(4) {
        let sid = tx(&libro, "source_id");
        let Some(Valor::Mapa(ficha)) = obtener(kb, &sid)? else {
            trozos.push(format!("### {} [{}] — sin analizar. {} conceptos, {} capítulos.", tx(&libro, "title"), tx(&libro, "domain"), tx(&libro, "conceptos"), tx(&libro, "capitulos")));
            continue;
        };
        let mut partes = vec![format!("### {} [{}]", tx(&ficha, "titulo"), ficha.get("campo").map(Valor::texto_py).unwrap_or_else(|| "None".into()))];
        if let Some(Valor::Mapa(ident)) = ficha.get("identidad") {
            if ident.get("nivel").is_some_and(Valor::verdad) {
                partes.push(format!("Nivel: {}", tx(ident, "nivel")));
            }
            if ident.get("que_cubre").is_some_and(Valor::verdad) {
                partes.push(format!("Cubre: {}", tx(ident, "que_cubre")));
            }
        }
        if let Some(a) = ficha.get("asume").filter(|a| a.verdad()) {
            partes.push(format!("Da por sabido: {}", lista_corta(a)));
        }
        let mut temario = ficha.get("temario").cloned().unwrap_or(Valor::Nulo);
        if let Valor::Mapa(m) = &temario {
            temario = m.get("capitulos").filter(|v| v.verdad()).or_else(|| m.get("temario")).cloned().unwrap_or(Valor::Nulo);
        }
        if let Valor::Lista(caps) = &temario {
            for cap in caps.iter().take(12) {
                let Valor::Mapa(cap) = cap else { continue };
                let pag = cap.get("paginas").filter(|v| v.verdad()).or_else(|| cap.get("pagina")).filter(|v| v.verdad());
                let mut l = format!("  cap {}: {}", cap.get("capitulo").map(Valor::texto_py).unwrap_or_else(|| "?".into()), cap.get("titulo").map(Valor::texto_py).unwrap_or_default());
                if let Some(p) = pag {
                    l += &format!(" (p.{})", p.texto_py());
                }
                if let Some(d) = cap.get("dificultad").filter(|v| v.verdad()) {
                    l += &format!(" · dificultad {}/5", d.texto_py());
                }
                partes.push(l);
            }
        }
        if let Some(l) = ficha.get("lagunas").filter(|a| a.verdad()) {
            partes.push(format!("NO cubre: {}", lista_corta(l)));
        }
        trozos.push(partes.join("\n"));
    }
    Ok(trozos.join("\n\n"))
}

/// `material_para_ejercicio`: de qué libro sale el concepto, en qué páginas, ejemplos y preguntas del texto
pub fn material_para_ejercicio(kb: &BaseKb, concepto: &str) -> Result<Mapa, String> {
    let Some(con) = kb.resolver(concepto)? else { return Ok(Mapa::new().con("encontrado", false).con("concepto", concepto)) };
    let cid = tx(&con, "concept_id");
    let c = kb.conectar()?;
    let afirmaciones = filas(
        &c,
        "SELECT cl.type, cl.text, cl.quote, cl.page, cl.source_id, cl.latex,\n                          cl.code_language, b.title\n                   FROM claims cl LEFT JOIN books b ON b.source_id = cl.source_id\n                   WHERE cl.concept_id = ? ORDER BY cl.confidence DESC LIMIT 30;",
        &[t(&cid)],
    )?;
    let mut libros: Vec<String> = afirmaciones.iter().map(|a| tx(a, "source_id")).collect();
    libros.sort();
    libros.dedup();
    let mut secciones = Vec::new();
    for sid in &libros {
        let paginas: Vec<f64> = afirmaciones.iter().filter(|a| tx(a, "source_id") == *sid).filter_map(|a| a.get("page").filter(|p| p.verdad()).and_then(Valor::num)).collect();
        if paginas.is_empty() {
            continue;
        }
        let max = paginas.iter().cloned().fold(f64::NEG_INFINITY, f64::max) as i64;
        let min = paginas.iter().cloned().fold(f64::INFINITY, f64::min) as i64;
        secciones.extend(
            filas(
                &c,
                "SELECT numero, titulo, pagina_inicio, pagina_fin, source_id\n                       FROM sections WHERE source_id = ?\n                         AND pagina_inicio <= ? AND COALESCE(pagina_fin, 99999) >= ?\n                       LIMIT 3;",
                &[t(sid), V::Integer(max), V::Integer(min)],
            )?
            .into_iter()
            .map(Valor::Mapa),
        );
    }
    let preguntas: Vec<Valor> = if libros.is_empty() {
        Vec::new()
    } else {
        let sql = format!("SELECT texto FROM questions WHERE source_id IN ({}) LIMIT 12;", vec!["?"; libros.len()].join(","));
        filas(&c, &sql, &libros.iter().map(|l| t(l)).collect::<Vec<_>>())?.into_iter().map(|f| f.valor("texto").clone()).collect()
    };
    let mut por_tipo: Vec<(String, Vec<Valor>)> = Vec::new();
    for a in &afirmaciones {
        let k = a.get("type").map(|x| if x.es_nulo() { "null".to_string() } else { x.texto_py() }).unwrap_or_default();
        match por_tipo.iter_mut().find(|(t, _)| *t == k) {
            Some(l) => l.1.push(Valor::Mapa(a.clone())),
            None => por_tipo.push((k, vec![Valor::Mapa(a.clone())])),
        }
    }
    let de = |k: &str| Valor::Lista(por_tipo.iter().find(|(t, _)| t == k).map(|(_, l)| l.clone()).unwrap_or_default());
    let suficiente = ["PROCEDURE", "EXAMPLE", "FORMULA"].iter().any(|k| por_tipo.iter().any(|(t, l)| t == k && !l.is_empty()));
    let mut pt = Mapa::new();
    for (k, l) in &por_tipo {
        pt.poner(k.clone(), Valor::Lista(l.clone()));
    }
    Ok(Mapa::new()
        .con("encontrado", true)
        .con("concepto", con.valor("canonical_name").clone())
        .con("dominios", con.get("domains").cloned().unwrap_or(Valor::Nulo))
        .con("es_puente", con.verdad("is_bridge"))
        .con("por_tipo", pt)
        .con("ejemplos_resueltos", de("EXAMPLE"))
        .con("errores_tipicos", de("CAVEAT"))
        .con("formulas", de("FORMULA"))
        .con("procedimientos", de("PROCEDURE"))
        .con("secciones", Valor::Lista(secciones))
        .con("preguntas_del_libro", Valor::Lista(preguntas))
        .con("prerrequisitos", Valor::Lista(kb.prerrequisitos(&cid, 2)?.into_iter().map(Valor::Mapa).collect()))
        .con("suficiente_para_ejercicio", suficiente))
}
