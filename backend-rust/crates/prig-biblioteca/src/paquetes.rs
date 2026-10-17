//! Los paquetes de conocimiento `.prigpack` (`pack_importer.py`): verificarlos sin tocar la base, importarlos (un
//! libro reimportado se reemplaza, no se duplica), unificar los conceptos de todos los libros en canónicos (Union-Find
//! sobre los nombres normalizados), reunir el dosier de cada concepto y el informe de integridad libro a libro.

use std::collections::{HashMap, HashSet};
use std::io::Read;

use prig_recursos::valor::{Mapa, Valor};
use rusqlite::{params, Connection};
use unicode_normalization::UnicodeNormalization;

use crate::base_kb::{filas, normalizar_nombre, BaseKb};
use crate::dominios;

/// Un fallo: `PackImportError` (un 400 en las rutas) u otro de Python (un 500)
#[derive(Debug)]
pub enum Fallo {
    Paquete(String),
    Otro(String),
}

impl Fallo {
    pub fn texto(&self) -> &str {
        match self {
            Fallo::Paquete(t) | Fallo::Otro(t) => t,
        }
    }
}

fn otro(e: impl std::fmt::Display) -> Fallo {
    Fallo::Otro(e.to_string())
}

const ESQUEMAS: [&str; 2] = ["3.0", "3.1"];

/// `norm_de_id`: sin el prefijo `tmp:` o `c:`
pub fn norm_de_id(cid: &str) -> &str {
    cid.strip_prefix("tmp:").or_else(|| cid.strip_prefix("c:")).unwrap_or(cid)
}

fn basename(r: &str) -> String {
    prig_plataforma::py::basename(r)
}

struct Paquete {
    archivos: HashMap<String, Vec<u8>>,
    nombres: HashSet<String>,
}

fn abrir(ruta: &str) -> Result<Paquete, Fallo> {
    let f = std::fs::File::open(ruta).map_err(otro)?;
    let Ok(mut z) = zip::ZipArchive::new(f) else { return Err(Fallo::Paquete(format!("No es un paquete válido: {}", basename(ruta)))) };
    let mut archivos = HashMap::new();
    for i in 0..z.len() {
        let mut e = z.by_index(i).map_err(otro)?;
        let mut b = Vec::new();
        e.read_to_end(&mut b).map_err(otro)?;
        archivos.insert(e.name().to_string(), b);
    }
    let nombres = archivos.keys().cloned().collect();
    Ok(Paquete { archivos, nombres })
}

impl Paquete {
    fn json(&self, n: &str) -> Result<Valor, Fallo> {
        prig_plataforma::json::leer(&String::from_utf8_lossy(&self.archivos[n])).map_err(Fallo::Otro)
    }
    /// `_leer_json`: None si falta o no se puede leer
    fn json_opcional(&self, n: &str) -> Option<Valor> {
        self.archivos.get(n).and_then(|b| prig_plataforma::json::leer(&String::from_utf8_lossy(b)).ok())
    }
    /// `_leer_jsonl`: una entrada por línea, saltando las que no son JSON
    fn jsonl(&self, n: &str) -> Result<Vec<Valor>, Fallo> {
        let Some(b) = self.archivos.get(n) else { return Ok(Vec::new()) };
        let t = std::str::from_utf8(b).map_err(|_| Fallo::Otro(format!("'utf-8' codec can't decode {n}")))?;
        Ok(prig_recursos::servidor::lineas_como_python(t).iter().map(|l| prig_plataforma::py::strip(l)).filter(|l| !l.is_empty()).filter_map(|l| prig_plataforma::json::leer(l).ok()).collect())
    }
}

fn mapa(v: &Valor) -> Mapa {
    match v {
        Valor::Mapa(m) => m.clone(),
        _ => Mapa::new(),
    }
}

fn es_entero(v: Option<&Valor>) -> bool {
    matches!(v, Some(Valor::Entero(_)) | Some(Valor::Bool(_)))
}

/// `verificar`: el paquete entero, sin escribir nada
pub fn verificar(ruta: &str) -> Result<Mapa, Fallo> {
    let p = abrir(ruta)?;
    let (m, n) = verificar_abierto(&p)?;
    let _ = n;
    Ok(m)
}

fn verificar_abierto(p: &Paquete) -> Result<(Mapa, Vec<String>), Fallo> {
    for o in ["manifest.json", "claims.jsonl", "concepts.jsonl", "checksums.json"] {
        if !p.nombres.contains(o) {
            return Err(Fallo::Paquete(format!("Falta {o} en el paquete")));
        }
    }
    let manifest = p.json("manifest.json")?;
    let man = mapa(&manifest);
    let mut problemas: Vec<String> = Vec::new();
    let version = man.get("schema_version").map(Valor::texto_py).unwrap_or_else(|| "?".into());
    if !ESQUEMAS.contains(&version.as_str()) {
        problemas.push(format!("esquema v{version} no reconocido (se esperaba 3.0 o 3.1)"));
    }
    if let Valor::Mapa(cs) = p.json("checksums.json")? {
        for (nombre, esperado) in cs.iter() {
            if nombre == "checksums.json" || !p.nombres.contains(nombre) {
                continue;
            }
            use sha2::{Digest, Sha256};
            let real: String = Sha256::digest(&p.archivos[nombre]).iter().map(|x| format!("{x:02x}")).collect();
            if Valor::Texto(real) != *esperado {
                problemas.push(format!("{nombre}: checksum no coincide"));
            }
        }
    }
    let claims = p.jsonl("claims.jsonl")?;
    let concepts = p.jsonl("concepts.jsonl")?;
    if let Some(d) = man.get("claims_verified").filter(|v| !v.es_nulo()) {
        if *d != Valor::Entero(claims.len() as i128) && *d != Valor::Real(claims.len() as f64) {
            problemas.push(format!("el manifiesto declara {} afirmaciones pero el archivo trae {}", d.texto_py(), claims.len()));
        }
    }
    if let Some(d) = man.get("domain").filter(|d| d.verdad()) {
        if !dominios::es_dominio(&d.texto_py()) {
            problemas.push(format!("dominio desconocido: {}", d.texto_py()));
        }
    }
    let (pro, esp) = (man.get("chunks_processed"), man.get("chunks_expected"));
    let incompleto = man.get("complete") == Some(&Valor::Bool(false))
        || (es_entero(pro) && es_entero(esp) && pro.and_then(Valor::num).unwrap_or(0.0) < esp.and_then(Valor::num).unwrap_or(0.0));
    if incompleto {
        let t = |v: Option<&Valor>| v.map(Valor::texto_py).unwrap_or_else(|| "None".into());
        problemas.push(format!("libro incompleto: {} de {} fragmentos (termina los repartos y vuelve a empaquetar con --pack-only)", t(pro), t(esp)));
    }
    let fallidos = man.get("chunks_failed").filter(|v| v.verdad()).and_then(Valor::num).unwrap_or(0.0);
    if let Some(e) = esp.filter(|v| v.verdad()).and_then(Valor::num) {
        if fallidos > e * 0.2 {
            problemas.push(format!(
                "{} fragmentos fallaron de {}: revisa el modelo antes de darlo por bueno",
                man.get("chunks_failed").map(Valor::texto_py).unwrap_or_default(),
                esp.map(Valor::texto_py).unwrap_or_default()
            ));
        }
    }
    let r = Mapa::new()
        .con("ok", problemas.is_empty())
        .con("problemas", Valor::Lista(problemas.iter().map(|p| Valor::Texto(p.clone())).collect()))
        .con("manifest", manifest)
        .con("claims", claims.len() as i64)
        .con("concepts", concepts.len() as i64);
    Ok((r, problemas))
}

/// `_normalizar_indice`: el índice del libro (suelto o dentro de uno por libro)
fn normalizar_indice(i: Option<Valor>, sid: &str) -> Mapa {
    let Some(Valor::Mapa(i)) = i else { return Mapa::new() };
    if i.contiene("chapters") || i.contiene("sections") {
        return i;
    }
    if let Some(Valor::Mapa(m)) = i.get(sid) {
        return m.clone();
    }
    let v: Vec<&Mapa> = i.iter().filter_map(|(_, v)| if let Valor::Mapa(m) = v { m.contiene("chapters").then_some(m) } else { None }).collect();
    if v.len() == 1 { v[0].clone() } else { Mapa::new() }
}

fn v_sql(v: Option<&Valor>) -> rusqlite::types::Value {
    use rusqlite::types::Value as V;
    match v {
        None | Some(Valor::Nulo) => V::Null,
        Some(Valor::Bool(b)) => V::Integer(*b as i64),
        Some(Valor::Entero(n)) => V::Integer(*n as i64),
        Some(Valor::Real(r)) => V::Real(*r),
        Some(Valor::Texto(t)) => V::Text(t.clone()),
        Some(otro) => V::Text(otro.texto_py()),
    }
}

fn txt(m: &Mapa, k: &str, d: &str) -> rusqlite::types::Value {
    match m.get(k) {
        None => rusqlite::types::Value::Text(d.into()),
        v => v_sql(v),
    }
}

fn lista_json(m: &Mapa, k: &str, ascii: bool) -> String {
    let v = m.get(k).filter(|v| v.verdad()).cloned().unwrap_or(Valor::Lista(vec![]));
    if ascii { prig_plataforma::json::escribir_compacto(&v) } else { prig_plataforma::json::escribir_linea(&v) }
}

fn borrar_libro(c: &Connection, sid: &str) -> rusqlite::Result<()> {
    let ids: Vec<String> = c.prepare("SELECT claim_id FROM claims WHERE source_id = ?;")?.query_map([sid], |f| f.get(0))?.flatten().collect();
    for i in ids {
        c.execute("DELETE FROM claims_fts WHERE claim_id = ?;", [i])?;
    }
    for t in ["claims", "relations", "symbols", "aliases", "sections", "figures", "questions"] {
        c.execute(&format!("DELETE FROM {t} WHERE source_id = ?;"), [sid])?;
    }
    Ok(())
}

/// `importar`: vuelca un paquete (reemplazando el libro si ya estaba)
pub fn importar(kb: &BaseKb, ruta: &str, forzar: bool) -> Result<Mapa, Fallo> {
    let p = abrir(ruta)?;
    let (verif, problemas) = verificar_abierto(&p)?;
    if !problemas.is_empty() && !forzar {
        return Err(Fallo::Paquete(format!("Paquete con problemas: {}", problemas.join("; "))));
    }
    let man = mapa(verif.valor("manifest"));
    let sid = man.get("source_id").map(Valor::texto_py).ok_or_else(|| Fallo::Otro("'source_id'".into()))?;
    let dominio = man.get("domain").filter(|d| d.verdad()).map(Valor::texto_py).unwrap_or_else(|| "machine_learning".into());
    let claims = p.jsonl("claims.jsonl")?;
    let concepts = p.jsonl("concepts.jsonl")?;
    let relations = p.jsonl("relations.jsonl")?;
    let symbols = p.jsonl("symbols.jsonl")?;
    let figuras = p.jsonl("figures.jsonl")?;
    let preguntas = match p.json_opcional("questions.json") {
        Some(Valor::Lista(l)) => l,
        _ => Vec::new(),
    };
    let indice = normalizar_indice(p.json_opcional("outline.json"), &sid);
    let mut c = kb.conectar().map_err(Fallo::Otro)?;
    let t = c.transaction().map_err(otro)?;
    let existia = t.query_row("SELECT 1 FROM books WHERE source_id = ?;", [&sid], |_| Ok(())).is_ok();
    if existia {
        borrar_libro(&t, &sid).map_err(otro)?;
    }
    t.execute(
        "INSERT OR REPLACE INTO books\n                (source_id, title, domain, sha256, pages, model_used,\n                 claims_verified, imported_at) VALUES (?,?,?,?,?,?,?,?);",
        params![sid, txt(&man, "title", &sid), dominio, v_sql(man.get("book_sha256")), v_sql(man.get("pages")), v_sql(man.get("model_used")), claims.len() as i64, prig_plataforma::py::ahora_iso()],
    )
    .map_err(otro)?;
    for cl in &claims {
        let cl = mapa(cl);
        let nombres: Vec<String> = cl.lista("concepts").filter(|_| cl.get("concepts").is_some_and(Valor::verdad)).unwrap_or(&[]).iter().map(Valor::texto_py).collect();
        let primer = nombres.first().map(|n| normalizar_nombre(n)).unwrap_or_default();
        let id = cl.get("claim_id").map(Valor::texto_py).ok_or_else(|| Fallo::Otro("'claim_id'".into()))?;
        let conf = cl.get("confidence").filter(|v| v.verdad()).and_then(Valor::num).unwrap_or(0.7);
        t.execute(
            "INSERT OR REPLACE INTO claims\n                    (claim_id, concept_id, source_id, domain, type, text, quote,\n                     page, confidence, code_language, latex, bridges_to)\n                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?);",
            params![id, format!("tmp:{primer}"), sid, dominio, txt(&cl, "type", "DEFINITION"), txt(&cl, "text", ""), txt(&cl, "quote", ""), v_sql(cl.get("page")), conf, txt(&cl, "code_language", "none"), txt(&cl, "latex", ""), lista_json(&cl, "bridges_to", true)],
        )
        .map_err(otro)?;
        t.execute("INSERT INTO claims_fts (claim_id, text, quote, concept_names)\n                             VALUES (?,?,?,?);", params![id, txt(&cl, "text", ""), txt(&cl, "quote", ""), nombres.join(" ")]).map_err(otro)?;
    }
    for co in &concepts {
        let co = mapa(co);
        let nombre = co.get("name").map(Valor::texto_py).unwrap_or_default();
        let norm = normalizar_nombre(&nombre);
        if norm.is_empty() {
            continue;
        }
        t.execute("INSERT OR REPLACE INTO aliases\n                             (norm, concept_id, surface, source_id, is_primary)\n                             VALUES (?,?,?,?,1);", params![norm, format!("tmp:{norm}"), v_sql(co.get("name")), sid]).map_err(otro)?;
        for a in co.lista("aliases").unwrap_or(&[]) {
            let na = normalizar_nombre(&a.texto_py());
            if !na.is_empty() && na != norm {
                t.execute("INSERT OR REPLACE INTO aliases\n                                     (norm, concept_id, surface, source_id, is_primary)\n                                     VALUES (?,?,?,?,0);", params![na, format!("tmp:{norm}"), v_sql(Some(a)), sid]).map_err(otro)?;
            }
        }
    }
    for r in &relations {
        let r = mapa(r);
        let ns = normalizar_nombre(&r.get("source").map(Valor::texto_py).unwrap_or_default());
        let nt = normalizar_nombre(&r.get("target").map(Valor::texto_py).unwrap_or_default());
        if ns.is_empty() || nt.is_empty() {
            continue;
        }
        t.execute(
            "INSERT INTO relations\n                    (source_concept, target_concept, type, quote, source_id, page, cross_domain)\n                    VALUES (?,?,?,?,?,?,0);",
            params![format!("tmp:{ns}"), format!("tmp:{nt}"), txt(&r, "type", "REQUIRES"), txt(&r, "quote", ""), sid, v_sql(r.get("page"))],
        )
        .map_err(otro)?;
    }
    let caps = indice.lista("chapters").filter(|_| indice.get("chapters").is_some_and(Valor::verdad)).unwrap_or(&[]).to_vec();
    let secs = indice.lista("sections").filter(|_| indice.get("sections").is_some_and(Valor::verdad)).unwrap_or(&[]).to_vec();
    for cap in &caps {
        let cap = mapa(cap);
        let id = cap.get("chapter_id").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| format!("{sid}_cap{}", cap.get("chapter_num").map(Valor::texto_py).unwrap_or_else(|| "None".into())));
        t.execute(
            "INSERT OR REPLACE INTO sections\n                    (section_id, source_id, chapter_id, numero, titulo,\n                     pagina_inicio, pagina_fin, es_capitulo, temas, resumen,\n                     prerrequisitos) VALUES (?,?,?,?,?,?,?,1,?,?,?);",
            params![id, sid, v_sql(cap.get("chapter_id")), cap.get("chapter_num").map(Valor::texto_py).unwrap_or_default(), txt(&cap, "title", ""), v_sql(cap.get("start_page")), v_sql(cap.get("end_page")), lista_json(&cap, "key_topics", false), txt(&cap, "summary", ""), lista_json(&cap, "prerequisites", false)],
        )
        .map_err(otro)?;
    }
    for sec in &secs {
        let sec = mapa(sec);
        let id = sec.get("section_id").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| format!("{sid}_sec{}", sec.get("section_num").map(Valor::texto_py).unwrap_or_else(|| "None".into())));
        t.execute(
            "INSERT OR REPLACE INTO sections\n                    (section_id, source_id, chapter_id, numero, titulo,\n                     pagina_inicio, pagina_fin, es_capitulo, temas, resumen,\n                     prerrequisitos) VALUES (?,?,?,?,?,?,?,0,?,?,?);",
            params![id, sid, v_sql(sec.get("chapter_id")), sec.get("section_num").map(Valor::texto_py).unwrap_or_default(), txt(&sec, "title", ""), v_sql(sec.get("start_page")), v_sql(sec.get("end_page")), lista_json(&sec, "key_topics", false), txt(&sec, "summary", ""), lista_json(&sec, "prerequisites", false)],
        )
        .map_err(otro)?;
    }
    for fg in &figuras {
        let fg = mapa(fg);
        let tipo = fg.get("type").filter(|v| v.verdad()).or_else(|| fg.get("tipo").filter(|v| v.verdad())).cloned().unwrap_or(Valor::Texto("figura".into()));
        t.execute("INSERT INTO figures (source_id, label, caption, tipo, page)\n                             VALUES (?,?,?,?,?);", params![sid, txt(&fg, "label", ""), txt(&fg, "caption", ""), v_sql(Some(&tipo)), v_sql(fg.get("page"))]).map_err(otro)?;
    }
    for pr in &preguntas {
        let (texto, pagina) = match pr {
            Valor::Texto(t) => (Valor::Texto(t.clone()), Valor::Nulo),
            Valor::Mapa(m) => (m.get("texto").cloned().unwrap_or(Valor::Texto(String::new())), m.get("page").cloned().unwrap_or(Valor::Nulo)),
            _ => (Valor::Texto(String::new()), Valor::Nulo),
        };
        if texto.verdad() {
            t.execute("INSERT INTO questions (source_id, texto, page, concept_id)\n                                 VALUES (?,?,?,?);", params![sid, v_sql(Some(&texto)), v_sql(Some(&pagina)), rusqlite::types::Value::Null]).map_err(otro)?;
        }
    }
    for sy in &symbols {
        let sy = mapa(sy);
        t.execute(
            "INSERT INTO symbols\n                    (symbol, meaning, concept_id, source_id, domain, page)\n                    VALUES (?,?,?,?,?,?);",
            params![txt(&sy, "symbol", ""), txt(&sy, "meaning", ""), rusqlite::types::Value::Null, sid, dominio, v_sql(sy.get("page"))],
        )
        .map_err(otro)?;
    }
    t.commit().map_err(otro)?;
    Ok(Mapa::new()
        .con("source_id", sid.as_str())
        .con("title", man.get("title").cloned().unwrap_or(Valor::Nulo))
        .con("domain", dominio.as_str())
        .con("reemplazado", existia)
        .con("claims", claims.len() as i64)
        .con("concepts", concepts.len() as i64)
        .con("relations", relations.len() as i64)
        .con("symbols", symbols.len() as i64)
        .con("figuras", figuras.len() as i64)
        .con("preguntas", preguntas.len() as i64)
        .con("capitulos", caps.len() as i64)
        .con("secciones", secs.len() as i64)
        .con("avisos", verif.valor("problemas").clone()))
}

/// `importar_carpeta`: todos los `.prigpack`, por orden; los que fallan, con su motivo
pub fn importar_carpeta(kb: &BaseKb, carpeta: &str) -> Result<Mapa, Fallo> {
    let mut packs: Vec<String> = std::fs::read_dir(carpeta).map_err(otro)?.flatten().map(|e| e.file_name().to_string_lossy().to_string()).filter(|f| f.ends_with(".prigpack")).collect();
    packs.sort();
    let (mut ok, mut mal) = (Vec::new(), Vec::new());
    for f in &packs {
        match importar(kb, &prig_plataforma::py::join(carpeta, f), false) {
            Ok(r) => ok.push(Valor::Mapa(r)),
            Err(e) => mal.push(Valor::Mapa(Mapa::new().con("pack", f.as_str()).con("error", e.texto()))),
        }
    }
    Ok(Mapa::new().con("importados", Valor::Lista(ok)).con("fallidos", Valor::Lista(mal)).con("total", packs.len() as i64))
}

// =========================================================================== unificar

/// `UnionFind`: el nombre más corto queda como raíz (con el orden de inserción de Python)
struct UnionFind {
    padre: HashMap<String, String>,
    orden: Vec<String>,
}

impl UnionFind {
    fn buscar(&mut self, x: &str) -> String {
        if !self.padre.contains_key(x) {
            self.padre.insert(x.into(), x.into());
            self.orden.push(x.into());
        }
        let mut raiz = x.to_string();
        while self.padre[&raiz] != raiz {
            raiz = self.padre[&raiz].clone();
        }
        let mut y = x.to_string();
        while self.padre[&y] != raiz {
            let siguiente = self.padre[&y].clone();
            self.padre.insert(y, raiz.clone());
            y = siguiente;
        }
        raiz
    }

    fn unir(&mut self, a: &str, b: &str) {
        let (mut ra, mut rb) = (self.buscar(a), self.buscar(b));
        if ra != rb {
            if rb.chars().count() < ra.chars().count() {
                std::mem::swap(&mut ra, &mut rb);
            }
            self.padre.insert(rb, ra);
        }
    }

    fn grupos(&mut self) -> Vec<(String, Vec<String>)> {
        let mut salida: Vec<(String, Vec<String>)> = Vec::new();
        for x in self.orden.clone() {
            let r = self.buscar(&x);
            match salida.iter_mut().find(|(k, _)| *k == r) {
                Some(g) => g.1.push(x),
                None => salida.push((r, vec![x])),
            }
        }
        salida
    }
}

/// `_nombre_canonico`: el que más libros usan como título; luego el más mencionado; luego el más corto
fn nombre_canonico(miembros: &[String], superficies: &HashMap<String, Vec<(String, [i64; 2])>>) -> String {
    let mut conteo: Vec<(String, [i64; 2])> = Vec::new();
    for m in miembros {
        for (t, [p, a]) in superficies.get(m).map(Vec::as_slice).unwrap_or(&[]) {
            match conteo.iter_mut().find(|(k, _)| k == t) {
                Some(c) => {
                    c.1[0] += p;
                    c.1[1] += a;
                }
                None => conteo.push((t.clone(), [*p, *a])),
            }
        }
    }
    if conteo.is_empty() {
        return miembros[0].clone();
    }
    conteo.sort_by_key(|(t, [p, a])| (-p, -(p + a), t.chars().count()));
    conteo[0].0.clone()
}

fn columna(c: &Connection, sql: &str) -> Result<Vec<String>, Fallo> {
    Ok(filas(c, sql, &[]).map_err(Fallo::Otro)?.iter().map(|f| f.iter().next().map(|(_, v)| if v.es_nulo() { String::new() } else { v.texto_py() }).unwrap_or_default()).collect())
}

/// `unificar`: los conceptos provisionales de cada libro, canónicos
pub fn unificar(kb: &BaseKb) -> Result<Mapa, Fallo> {
    let mut uf = UnionFind { padre: HashMap::new(), orden: Vec::new() };
    let mut superficies: HashMap<String, Vec<(String, [i64; 2])>> = HashMap::new();
    let mut c = kb.conectar().map_err(Fallo::Otro)?;
    let t = c.transaction().map_err(otro)?;
    let mut grupos_libro: Vec<(String, Vec<String>)> = Vec::new();
    for f in filas(&t, "SELECT norm, concept_id, surface, is_primary FROM aliases;", &[]).map_err(Fallo::Otro)? {
        let norm = f.valor("norm").texto_py();
        let cid = f.valor("concept_id").texto_py();
        uf.buscar(&norm);
        match grupos_libro.iter_mut().find(|(k, _)| *k == cid) {
            Some(g) => g.1.push(norm.clone()),
            None => grupos_libro.push((cid, vec![norm.clone()])),
        }
        if let Some(s) = f.get("surface").filter(|s| s.verdad()).map(Valor::texto_py) {
            let lista = superficies.entry(norm).or_default();
            let i = match lista.iter().position(|(k, _)| *k == s) {
                Some(i) => i,
                None => {
                    lista.push((s, [0, 0]));
                    lista.len() - 1
                }
            };
            lista[i].1[if f.valor("is_primary").verdad() { 0 } else { 1 }] += 1;
        }
    }
    for (_, norms) in &grupos_libro {
        for otro_ in &norms[1..] {
            uf.unir(&norms[0], otro_);
        }
    }
    for col in ["source_concept", "target_concept"] {
        for v in columna(&t, &format!("SELECT DISTINCT {col} AS v FROM relations;"))? {
            let n = norm_de_id(&v);
            if !n.is_empty() {
                uf.buscar(n);
            }
        }
    }
    let grupos = uf.grupos();
    let mut mapa_ids: HashMap<String, String> = HashMap::new();
    let mut conceptos: Vec<(String, String, String)> = Vec::new(); // (cid, norm raíz, canónico)
    for (raiz, miembros) in &grupos {
        let canonico = nombre_canonico(miembros, &superficies);
        let n = normalizar_nombre(&canonico);
        let cid = format!("c:{}", if n.is_empty() { raiz.clone() } else { n });
        for m in miembros {
            mapa_ids.insert(m.clone(), cid.clone());
        }
        match conceptos.iter_mut().find(|(k, _, _)| *k == cid) {
            Some(x) => *x = (cid.clone(), raiz.clone(), canonico),
            None => conceptos.push((cid, raiz.clone(), canonico)),
        }
    }
    t.execute("DELETE FROM concepts;", []).map_err(otro)?;
    let mut reapuntadas = 0i64;
    for f in filas(&t, "SELECT claim_id, concept_id FROM claims;", &[]).map_err(Fallo::Otro)? {
        let viejo = f.get("concept_id").filter(|v| !v.es_nulo()).map(Valor::texto_py).unwrap_or_default();
        if let Some(nuevo) = mapa_ids.get(norm_de_id(&viejo)) {
            if *nuevo != viejo {
                t.execute("UPDATE claims SET concept_id = ? WHERE claim_id = ?;", params![nuevo, f.valor("claim_id").texto_py()]).map_err(otro)?;
                reapuntadas += 1;
            }
        }
    }
    for viejo in columna(&t, "SELECT DISTINCT concept_id FROM aliases;")? {
        if let Some(nuevo) = mapa_ids.get(norm_de_id(&viejo)) {
            if *nuevo != viejo {
                t.execute("UPDATE OR REPLACE aliases SET concept_id = ?\n                                 WHERE concept_id = ?;", params![nuevo, viejo]).map_err(otro)?;
            }
        }
    }
    for col in ["source_concept", "target_concept"] {
        for viejo in columna(&t, &format!("SELECT DISTINCT {col} AS v FROM relations;"))? {
            if let Some(nuevo) = mapa_ids.get(norm_de_id(&viejo)) {
                if *nuevo != viejo {
                    t.execute(&format!("UPDATE relations SET {col} = ? WHERE {col} = ?;"), params![nuevo, viejo]).map_err(otro)?;
                }
            }
        }
    }
    let puentes_norm: HashMap<String, Vec<String>> = dominios::puentes_conocidos().into_iter().map(|(n, d)| (normalizar_nombre(&n), d)).collect();
    let mut n_puentes = 0i64;
    for (cid, raiz, canonico) in &conceptos {
        let f = filas(&t, "SELECT domain, source_id FROM claims\n                                     WHERE concept_id = ?;", &[rusqlite::types::Value::Text(cid.clone())]).map_err(Fallo::Otro)?;
        let mut doms: Vec<String> = f.iter().filter_map(|x| x.get("domain").filter(|d| d.verdad()).map(Valor::texto_py)).collect::<HashSet<_>>().into_iter().collect();
        doms.sort();
        let libros = f.iter().map(|x| x.valor("source_id").texto_py()).collect::<HashSet<_>>().len() as i64;
        let es_puente = if doms.len() >= 2 { 1 } else { 0 };
        if let Some(s) = puentes_norm.get(raiz).filter(|_| !f.is_empty()) {
            let mut todos: HashSet<String> = doms.into_iter().collect();
            todos.extend(s.iter().cloned());
            doms = todos.into_iter().collect();
            doms.sort();
        }
        n_puentes += es_puente;
        let dj = prig_plataforma::json::escribir_compacto(&Valor::Lista(doms.into_iter().map(Valor::Texto).collect()));
        t.execute(
            "INSERT OR REPLACE INTO concepts\n                    (concept_id, canonical_name, norm, domains, is_bridge, mentions, books)\n                    VALUES (?,?,?,?,?,?,?);",
            params![cid, canonico, raiz, dj, es_puente, f.len() as i64, libros],
        )
        .map_err(otro)?;
    }
    let dom_por_cid: HashMap<String, HashSet<String>> = filas(&t, "SELECT concept_id, domains FROM concepts;", &[])
        .map_err(Fallo::Otro)?
        .iter()
        .map(|r| {
            let d = match prig_plataforma::json::leer(&r.get("domains").filter(|d| d.verdad()).map(Valor::texto_py).unwrap_or_else(|| "[]".into())) {
                Ok(Valor::Lista(l)) => l.iter().map(Valor::texto_py).collect(),
                _ => HashSet::new(),
            };
            (r.valor("concept_id").texto_py(), d)
        })
        .collect();
    let mut cruzadas = 0i64;
    for f in filas(&t, "SELECT rowid, source_concept, target_concept\n                                     FROM relations;", &[]).map_err(Fallo::Otro)? {
        let vacio = HashSet::new();
        let ds = dom_por_cid.get(&f.valor("source_concept").texto_py()).unwrap_or(&vacio);
        let dt = dom_por_cid.get(&f.valor("target_concept").texto_py()).unwrap_or(&vacio);
        if !ds.is_empty() && !dt.is_empty() && ds.is_disjoint(dt) {
            t.execute("UPDATE relations SET cross_domain = 1 WHERE rowid = ?;", [v_sql(f.get("rowid"))]).map_err(otro)?;
            cruzadas += 1;
        }
    }
    let mut enganchados = 0i64;
    for f in filas(&t, "SELECT rowid, meaning FROM symbols\n                                     WHERE concept_id IS NULL;", &[]).map_err(Fallo::Otro)? {
        let m = f.get("meaning").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default();
        if let Some(cid) = mapa_ids.get(&normalizar_nombre(&m)) {
            t.execute("UPDATE symbols SET concept_id = ? WHERE rowid = ?;", params![cid, v_sql(f.get("rowid"))]).map_err(otro)?;
            enganchados += 1;
        }
    }
    t.execute("INSERT OR REPLACE INTO meta VALUES ('unified_at', ?);", [prig_plataforma::py::ahora_iso()]).map_err(otro)?;
    t.commit().map_err(otro)?;
    let fusionados = grupos.iter().filter(|(_, g)| g.len() > 1).count() as i64;
    Ok(Mapa::new()
        .con("conceptos", conceptos.len() as i64)
        .con("fusionados", fusionados)
        .con("afirmaciones_reapuntadas", reapuntadas)
        .con("puentes", n_puentes)
        .con("relaciones_cruzadas", cruzadas)
        .con("simbolos_enganchados", enganchados))
}

// =========================================================================== dosieres

/// `_grafia`: (tildes, mayúsculas) que conserva un texto
fn grafia(t: &str) -> (usize, usize) {
    use unicode_general_category::{get_general_category, GeneralCategory};
    (t.nfd().filter(|c| get_general_category(*c) == GeneralCategory::NonspacingMark).count(), t.chars().filter(|c| c.is_uppercase()).count())
}

fn analogias(dominios: &[String], por_tipo: &[(String, Vec<Mapa>)]) -> Vec<Valor> {
    if dominios.len() < 2 {
        return Vec::new();
    }
    let mut salida = Vec::new();
    for d in dominios {
        for tipo in ["INTUITION", "DEFINITION", "EXAMPLE"] {
            let cands: Vec<&Mapa> = por_tipo.iter().find(|(t, _)| t == tipo).map(|(_, l)| l.iter().filter(|a| a.get("domain") == Some(&Valor::Texto(d.clone()))).collect()).unwrap_or_default();
            if let Some(a) = cands.first() {
                salida.push(Valor::Mapa(Mapa::new().con("dominio", d.as_str()).con("tipo", tipo).con("texto", a.valor("text").clone()).con("libro", a.valor("book").clone())));
                break;
            }
        }
    }
    salida
}

/// `construir_dosieres`: por concepto, todo lo que se sabe de él, ya reunido
pub fn construir_dosieres(kb: &BaseKb) -> Result<Mapa, Fallo> {
    const PRIORIDAD: [&str; 9] = ["DEFINITION", "INTUITION", "THEOREM", "FORMULA", "PROPERTY", "ALGORITHM", "CODE_PATTERN", "EXAMPLE", "PITFALL"];
    let mut c = kb.conectar().map_err(Fallo::Otro)?;
    let t = c.transaction().map_err(otro)?;
    let huerfanos = t.execute("DELETE FROM dossiers WHERE concept_id NOT IN\n                                     (SELECT concept_id FROM concepts);", []).map_err(otro)?;
    let conceptos = filas(&t, "SELECT * FROM concepts\n                                     WHERE mentions >= ? ORDER BY mentions DESC;", &[rusqlite::types::Value::Integer(1)]).map_err(Fallo::Otro)?;
    let titulos: HashMap<String, Valor> = filas(&t, "SELECT source_id, title FROM books;", &[]).map_err(Fallo::Otro)?.into_iter().map(|r| (r.valor("source_id").texto_py(), r.valor("title").clone())).collect();
    let id = |x: &str| [rusqlite::types::Value::Text(x.to_string())];
    let mut hechos = 0i64;
    for con in &conceptos {
        let cid = con.valor("concept_id").texto_py();
        let afirmaciones = filas(
            &t,
            "SELECT type, text, quote, page, source_id, domain,\n                              code_language, latex, confidence\n                       FROM claims WHERE concept_id = ?\n                       ORDER BY confidence DESC;",
            &id(&cid),
        )
        .map_err(Fallo::Otro)?;
        let mut por_tipo: Vec<(String, Vec<Mapa>)> = Vec::new();
        for a in &afirmaciones {
            let tipo = a.get("type").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| "DEFINITION".into());
            let sid = a.valor("source_id").texto_py();
            let item = Mapa::new()
                .con("text", a.valor("text").clone())
                .con("quote", a.valor("quote").clone())
                .con("page", a.valor("page").clone())
                .con("book", titulos.get(&sid).cloned().unwrap_or_else(|| a.valor("source_id").clone()))
                .con("source_id", a.valor("source_id").clone())
                .con("domain", a.valor("domain").clone())
                .con("code_language", a.valor("code_language").clone())
                .con("latex", a.valor("latex").clone());
            match por_tipo.iter_mut().find(|(k, _)| *k == tipo) {
                Some(l) => l.1.push(item),
                None => por_tipo.push((tipo, vec![item])),
            }
        }
        let rel = |cond: &str| {
            filas(
                &t,
                &format!("SELECT co.canonical_name AS nombre, co.concept_id, r.type,\n                              r.cross_domain\n                       FROM relations r JOIN concepts co ON co.concept_id = r.target_concept\n                       WHERE r.source_concept = ? AND r.type {cond} ('REQUIRES','GENERALIZES')\n                       LIMIT 12;"),
                &id(&cid),
            )
        };
        let pre = rel("IN").map_err(Fallo::Otro)?;
        let relac = rel("NOT IN").map_err(Fallo::Otro)?;
        let simbolos = filas(&t, "SELECT symbol, meaning, domain FROM symbols WHERE concept_id = ? LIMIT 8;", &id(&cid)).map_err(Fallo::Otro)?;
        let mut mejores: Vec<(String, String)> = Vec::new();
        for r in filas(&t, "SELECT surface FROM aliases\n                                      WHERE concept_id = ? AND surface IS NOT NULL;", &id(&cid)).map_err(Fallo::Otro)? {
            let s = r.valor("surface").texto_py();
            let clave = normalizar_nombre(&s);
            match mejores.iter_mut().find(|(k, _)| *k == clave) {
                Some(p) => {
                    if grafia(&s) > grafia(&p.1) {
                        p.1 = s;
                    }
                }
                None => mejores.push((clave, s)),
            }
        }
        let canon = normalizar_nombre(&con.valor("canonical_name").texto_py());
        let alias: Vec<Valor> = mejores.into_iter().filter(|(k, _)| *k != canon).map(|(_, v)| Valor::Texto(v)).take(12).collect();
        let doms: Vec<String> = match prig_plataforma::json::leer(&con.get("domains").filter(|d| d.verdad()).map(Valor::texto_py).unwrap_or_else(|| "[]".into())) {
            Ok(Valor::Lista(l)) => l.iter().map(Valor::texto_py).collect(),
            _ => Vec::new(),
        };
        let mut pt = Mapa::new();
        for p in PRIORIDAD {
            if let Some((_, l)) = por_tipo.iter().find(|(k, _)| k == p) {
                pt.poner(p, Valor::Lista(l.iter().cloned().map(Valor::Mapa).collect()));
            }
        }
        let dosier = Mapa::new()
            .con("concept_id", cid.as_str())
            .con("nombre", con.valor("canonical_name").clone())
            .con("alias", Valor::Lista(alias))
            .con("dominios", Valor::Lista(doms.iter().map(|d| Valor::Texto(d.clone())).collect()))
            .con("es_puente", con.valor("is_bridge").verdad())
            .con("libros", con.valor("books").clone())
            .con("menciones", con.valor("mentions").clone())
            .con("por_tipo", pt)
            .con("prerrequisitos", Valor::Lista(pre.into_iter().map(Valor::Mapa).collect()))
            .con("relacionados", Valor::Lista(relac.into_iter().map(Valor::Mapa).collect()))
            .con("simbolos", Valor::Lista(simbolos.into_iter().map(Valor::Mapa).collect()))
            .con("analogias", Valor::Lista(analogias(&doms, &por_tipo)));
        t.execute("INSERT OR REPLACE INTO dossiers VALUES (?,?,?);", params![cid, prig_plataforma::json::escribir_linea(&Valor::Mapa(dosier)), prig_plataforma::py::ahora_iso()]).map_err(otro)?;
        hechos += 1;
    }
    t.commit().map_err(otro)?;
    Ok(Mapa::new().con("dosieres", hechos).con("obsoletos_borrados", huerfanos as i64))
}

// =========================================================================== integridad

/// `verificar_integridad`: lo que dice cada manifiesto contra lo que hay en la base
pub fn verificar_integridad(kb: &BaseKb) -> Result<Mapa, Fallo> {
    let c = kb.conectar().map_err(Fallo::Otro)?;
    let n = |sql: &str, sid: &str| -> Result<i64, Fallo> { c.query_row(sql, [sid], |f| f.get::<_, i64>(0)).map_err(otro) };
    let (mut libros, mut problemas) = (Vec::new(), Vec::new());
    for b in filas(&c, "SELECT * FROM books ORDER BY title;", &[]).map_err(Fallo::Otro)? {
        let sid = b.valor("source_id").texto_py();
        let n_claims = n("SELECT COUNT(*) FROM claims WHERE source_id = ?;", &sid)?;
        let n_fts = n("SELECT COUNT(*) FROM claims_fts f\n                                     JOIN claims c2 ON c2.claim_id = f.claim_id\n                                     WHERE c2.source_id = ?;", &sid)?;
        let sin_concepto = n("SELECT COUNT(*) FROM claims\n                    WHERE source_id = ? AND (concept_id IS NULL\n                          OR concept_id LIKE 'tmp:%');", &sid)?;
        let sin_cita = n("SELECT COUNT(*) FROM claims\n                    WHERE source_id = ? AND (quote IS NULL OR quote = '');", &sid)?;
        let n_conceptos = n("SELECT COUNT(DISTINCT concept_id) FROM claims\n                                           WHERE source_id = ?;", &sid)?;
        let n_rel = n("SELECT COUNT(*) FROM relations WHERE source_id = ?;", &sid)?;
        let huerfanas = n(
            "SELECT COUNT(*) FROM relations r\n                    WHERE r.source_id = ? AND (\n                        NOT EXISTS (SELECT 1 FROM concepts WHERE concept_id = r.source_concept)\n                     OR NOT EXISTS (SELECT 1 FROM concepts WHERE concept_id = r.target_concept));",
            &sid,
        )?;
        let n_sym = n("SELECT COUNT(*) FROM symbols WHERE source_id = ?;", &sid)?;
        let mut fallos: Vec<String> = Vec::new();
        if n_claims == 0 {
            fallos.push("sin afirmaciones".into());
        }
        if n_fts != n_claims {
            fallos.push(format!("índice de texto descuadrado ({n_fts}/{n_claims})"));
        }
        let verificadas = b.get("claims_verified").filter(|v| v.verdad()).and_then(Valor::num).map(|x| x as i64);
        if let Some(v) = verificadas.filter(|v| *v != n_claims) {
            fallos.push(format!("faltan {} afirmaciones", v - n_claims));
        }
        if sin_concepto != 0 {
            fallos.push(format!("{sin_concepto} sin concepto canónico (falta unificar)"));
        }
        if sin_cita != 0 {
            fallos.push(format!("{sin_cita} sin cita textual"));
        }
        if huerfanas != 0 {
            fallos.push(format!("{huerfanas} relaciones huérfanas"));
        }
        let dom = b.get("domain").filter(|d| !d.es_nulo()).map(Valor::texto_py);
        if !dom.as_deref().is_some_and(dominios::es_dominio) {
            fallos.push(format!("dominio inválido: {}", dom.unwrap_or_else(|| "None".into())));
        }
        let fl = Valor::Lista(fallos.iter().map(|f| Valor::Texto(f.clone())).collect());
        libros.push(Valor::Mapa(
            Mapa::new()
                .con("source_id", sid.as_str())
                .con("titulo", b.valor("title").clone())
                .con("dominio", b.valor("domain").clone())
                .con("paginas", b.valor("pages").clone())
                .con("modelo", b.valor("model_used").clone())
                .con("afirmaciones", n_claims)
                .con("conceptos", n_conceptos)
                .con("relaciones", n_rel)
                .con("simbolos", n_sym)
                .con("importado", b.valor("imported_at").clone())
                .con("ok", fallos.is_empty())
                .con("fallos", fl.clone()),
        ));
        if !fallos.is_empty() {
            problemas.push(Valor::Mapa(Mapa::new().con("titulo", b.valor("title").clone()).con("fallos", fl)));
        }
    }
    let total = |sql: &str| -> Result<i64, Fallo> { c.query_row(sql, [], |f| f.get::<_, i64>(0)).map_err(otro) };
    let total_claims = total("SELECT COUNT(*) FROM claims;")?;
    let total_fts = total("SELECT COUNT(*) FROM claims_fts;")?;
    let huerfanas_fts = total("SELECT COUNT(*) FROM claims_fts f\n                WHERE NOT EXISTS (SELECT 1 FROM claims c2 WHERE c2.claim_id = f.claim_id);")?;
    let unificado: Valor = c.query_row("SELECT valor FROM meta WHERE clave='unified_at';", [], |f| f.get::<_, Option<String>>(0)).ok().flatten().map(Valor::Texto).unwrap_or(Valor::Nulo);
    if libros.is_empty() {
        return Ok(Mapa::new()
            .con("libros", Valor::Lista(vec![]))
            .con("total_libros", 0)
            .con("libros_ok", 0)
            .con("problemas", Valor::Lista(vec![]))
            .con("problemas_globales", Valor::Lista(vec![]))
            .con("integro", true)
            .con("vacia", true)
            .con("unificado_en", unificado));
    }
    let mut globales = Vec::new();
    if huerfanas_fts != 0 {
        globales.push(format!("{huerfanas_fts} entradas de texto sin afirmación (basura de una reimportación)"));
    }
    if total_fts != total_claims {
        globales.push(format!("índice global descuadrado: {total_fts} vs {total_claims}"));
    }
    if unificado.es_nulo() {
        globales.push("los conceptos nunca se han unificado".into());
    }
    let ok = libros.iter().filter(|l| matches!(l, Valor::Mapa(m) if m.verdad("ok"))).count() as i64;
    let integro = problemas.is_empty() && globales.is_empty();
    let n_libros = libros.len() as i64;
    Ok(Mapa::new()
        .con("libros", Valor::Lista(libros))
        .con("total_libros", n_libros)
        .con("libros_ok", ok)
        .con("problemas", Valor::Lista(problemas))
        .con("problemas_globales", Valor::Lista(globales.into_iter().map(Valor::Texto).collect()))
        .con("integro", integro)
        .con("unificado_en", unificado))
}
