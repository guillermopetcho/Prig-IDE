//! El conocimiento de la biblioteca (`knowledge_service.py` y el paquete `knowledge`): el catálogo SQLite
//! (`.index/catalog.db`, el mismo esquema y las mismas filas que escribía Python), meter un documento (leerlo, sacar
//! capítulos y secciones de los marcadores o del texto y trocearlo), la indexación de toda la biblioteca en segundo
//! plano y la búsqueda: BM25 + TF-IDF fusionados, un empujón por capítulos que hablan del tema, el reordenado
//! explicable (que se audita en el catálogo), el contexto con presupuesto de tokens y la evidencia.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};

use prig_plataforma::py::{abspath, basename, join, relpath, splitext, strip};
use prig_recursos::valor::{redondear, Mapa, Valor};
use rusqlite::{params, Connection, OptionalExtension};

use crate::estante::Estante;
use crate::indices::{Bm25, Vectorial};
use crate::troceado::{self, Seccion};

fn ahora() -> String {
    prig_plataforma::py::ahora_iso()
}

fn json_ascii(v: &Valor) -> String {
    prig_plataforma::json::escribir_compacto(v)
}

fn lista_textos(l: &[String]) -> Valor {
    Valor::Lista(l.iter().map(|t| Valor::Texto(t.clone())).collect())
}

// =========================================================================== el catálogo

const ESQUEMA: &str = "
CREATE TABLE IF NOT EXISTS books (source_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, title TEXT NOT NULL, original_filename TEXT NOT NULL, relative_path TEXT NOT NULL, sha256 TEXT UNIQUE NOT NULL, file_size INTEGER NOT NULL, authors_json TEXT, total_pages INTEGER DEFAULT 0, document_version INTEGER DEFAULT 1, index_version INTEGER DEFAULT 1, metadata_json TEXT, created_at TEXT NOT NULL, modified_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chapters (chapter_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, chapter_num INTEGER NOT NULL, title TEXT NOT NULL, start_page INTEGER DEFAULT 1, end_page INTEGER DEFAULT 1, summary TEXT, key_topics_json TEXT, prerequisites_json TEXT, created_at TEXT NOT NULL, FOREIGN KEY (source_id) REFERENCES books(source_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS sections (section_id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL, source_id TEXT NOT NULL, section_num TEXT NOT NULL, title TEXT NOT NULL, start_page INTEGER DEFAULT 1, end_page INTEGER DEFAULT 1, summary TEXT, created_at TEXT NOT NULL, FOREIGN KEY (chapter_id) REFERENCES chapters(chapter_id) ON DELETE CASCADE, FOREIGN KEY (source_id) REFERENCES books(source_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, chapter_id TEXT, section_id TEXT, content TEXT NOT NULL, content_type TEXT NOT NULL, token_count INTEGER DEFAULT 0, previous_chunk_id TEXT, next_chunk_id TEXT, contains_equation INTEGER DEFAULT 0, contains_code INTEGER DEFAULT 0, topics_json TEXT, concepts_json TEXT, symbols_json TEXT, page_start INTEGER DEFAULT 1, page_end INTEGER DEFAULT 1, created_at TEXT NOT NULL, FOREIGN KEY (source_id) REFERENCES books(source_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS concepts (concept_id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT DEFAULT 'FOUNDATIONAL', declarative_summary TEXT, procedural_summary TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claims (claim_id TEXT PRIMARY KEY, concept_id TEXT NOT NULL, statement TEXT NOT NULL, claim_type TEXT DEFAULT 'DECLARATIVE', status TEXT DEFAULT 'PROPOSED', evidence_ids_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY (concept_id) REFERENCES concepts(concept_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS evidence (evidence_id TEXT PRIMARY KEY, claim_id TEXT, concept_id TEXT, source_id TEXT NOT NULL, source_type TEXT DEFAULT 'book', source_title TEXT NOT NULL, chapter_num INTEGER, chapter_name TEXT, pages_json TEXT, chunk_ids_json TEXT, location_summary TEXT, strength TEXT DEFAULT 'DIRECT', confidence REAL DEFAULT 1.0, created_at TEXT NOT NULL, FOREIGN KEY (source_id) REFERENCES books(source_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS relations (relation_id TEXT PRIMARY KEY, from_concept_id TEXT NOT NULL, to_concept_id TEXT NOT NULL, relation_type TEXT DEFAULT 'PREREQUISITE_OF', confidence REAL DEFAULT 1.0, status TEXT DEFAULT 'PROPOSED', created_at TEXT NOT NULL, FOREIGN KEY (from_concept_id) REFERENCES concepts(concept_id) ON DELETE CASCADE, FOREIGN KEY (to_concept_id) REFERENCES concepts(concept_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS conflicts (conflict_id TEXT PRIMARY KEY, source_a_id TEXT NOT NULL, source_b_id TEXT NOT NULL, topic TEXT NOT NULL, context_a TEXT NOT NULL, context_b TEXT NOT NULL, resolution_status TEXT DEFAULT 'LOGGED', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retrieval_runs (run_id TEXT PRIMARY KEY, query TEXT NOT NULL, query_type TEXT NOT NULL, candidate_count INTEGER DEFAULT 0, final_count INTEGER DEFAULT 0, retriever_version TEXT DEFAULT 'v3.0', embedding_model TEXT DEFAULT 'tfidf-hybrid', reranker_version TEXT DEFAULT 'explicable-v1', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retrieval_results (result_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, chunk_id TEXT NOT NULL, bm25_score REAL DEFAULT 0.0, vector_score REAL DEFAULT 0.0, structure_score REAL DEFAULT 0.0, topic_score REAL DEFAULT 0.0, context_score REAL DEFAULT 0.0, reranker_score REAL DEFAULT 0.0, final_score REAL DEFAULT 0.0, rank INTEGER NOT NULL, reasons_json TEXT, FOREIGN KEY (run_id) REFERENCES retrieval_runs(run_id) ON DELETE CASCADE, FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_books_sha256 ON books(sha256);
CREATE INDEX IF NOT EXISTS idx_chapters_source ON chapters(source_id);
CREATE INDEX IF NOT EXISTS idx_sections_chapter ON sections(chapter_id);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(content_type);
";

const TABLAS: [&str; 11] = ["books", "chapters", "sections", "chunks", "concepts", "claims", "evidence", "relations", "conflicts", "retrieval_runs", "retrieval_results"];

/// `DBCatalog`: el catálogo SQLite de la biblioteca
pub struct Catalogo {
    pub ruta: String,
}

/// Un valor de una fila como lo da `sqlite3.Row` en Python
fn de_sql(v: rusqlite::types::ValueRef<'_>) -> Valor {
    use rusqlite::types::ValueRef as V;
    match v {
        V::Null => Valor::Nulo,
        V::Integer(n) => Valor::Entero(n as i128),
        V::Real(r) => Valor::Real(r),
        V::Text(t) => Valor::Texto(String::from_utf8_lossy(t).into_owned()),
        V::Blob(b) => Valor::Texto(String::from_utf8_lossy(b).into_owned()),
    }
}

fn filas(c: &Connection, sql: &str, p: &[&dyn rusqlite::ToSql]) -> rusqlite::Result<Vec<Mapa>> {
    let mut st = c.prepare(sql)?;
    let nombres: Vec<String> = st.column_names().iter().map(|s| s.to_string()).collect();
    let filas = st.query_map(p, |f| {
        let mut m = Mapa::new();
        for (i, n) in nombres.iter().enumerate() {
            m.poner(n.clone(), de_sql(f.get_ref(i)?));
        }
        Ok(m)
    })?;
    filas.collect()
}

impl Catalogo {
    pub fn new(ruta: &str) -> Result<Catalogo, String> {
        let ruta = abspath(ruta);
        if let Some(d) = Path::new(&ruta).parent() {
            let _ = std::fs::create_dir_all(d);
        }
        let c = Catalogo { ruta };
        c.conexion()?.execute_batch(ESQUEMA).map_err(|e| e.to_string())?;
        Ok(c)
    }

    pub fn conexion(&self) -> Result<Connection, String> {
        let c = Connection::open(&self.ruta).map_err(|e| e.to_string())?;
        c.busy_timeout(std::time::Duration::from_secs(5)).map_err(|e| e.to_string())?;
        c.execute_batch("PRAGMA foreign_keys = ON;").map_err(|e| e.to_string())?;
        Ok(c)
    }

    pub fn libro_por_sha(&self, sha: &str) -> Result<Option<Mapa>, String> {
        Ok(filas(&self.conexion()?, "SELECT * FROM books WHERE sha256 = ?;", &[&sha.to_lowercase()]).map_err(|e| e.to_string())?.into_iter().next())
    }

    pub fn libro(&self, source_id: &str) -> Result<Option<Mapa>, String> {
        Ok(filas(&self.conexion()?, "SELECT * FROM books WHERE source_id = ?;", &[&source_id]).map_err(|e| e.to_string())?.into_iter().next())
    }

    /// `list_books`: con su número de fragmentos, los más recientes primero
    pub fn libros(&self) -> Result<Vec<Mapa>, String> {
        filas(
            &self.conexion()?,
            "SELECT b.*, (SELECT COUNT(*) FROM chunks c WHERE c.source_id = b.source_id) AS chunks_count FROM books b ORDER BY b.modified_at DESC;",
            &[],
        )
        .map_err(|e| e.to_string())
    }

    pub fn shas(&self) -> Result<HashSet<String>, String> {
        let c = self.conexion()?;
        let mut st = c.prepare("SELECT sha256 FROM books;").map_err(|e| e.to_string())?;
        let r = st.query_map([], |f| f.get::<_, String>(0)).map_err(|e| e.to_string())?;
        Ok(r.flatten().collect())
    }

    pub fn borrar_libro(&self, source_id: &str) -> Result<bool, String> {
        let c = self.conexion()?;
        let hay: Option<i64> = c.query_row("SELECT 1 FROM books WHERE source_id = ?;", [source_id], |f| f.get(0)).optional().map_err(|e| e.to_string())?;
        if hay.is_none() {
            return Ok(false);
        }
        for t in ["chunks", "sections", "chapters"] {
            c.execute(&format!("DELETE FROM {t} WHERE source_id = ?;"), [source_id]).map_err(|e| e.to_string())?;
        }
        c.execute("DELETE FROM books WHERE source_id = ?;", [source_id]).map_err(|e| e.to_string())?;
        Ok(true)
    }

    pub fn fragmentos_de(&self, source_id: &str) -> Result<usize, String> {
        let c = self.conexion()?;
        c.query_row("SELECT COUNT(*) FROM chunks WHERE source_id = ?;", [source_id], |f| f.get::<_, i64>(0)).map(|n| n as usize).map_err(|e| e.to_string())
    }

    pub fn contar(&self) -> Result<Mapa, String> {
        let c = self.conexion()?;
        let mut m = Mapa::new();
        for t in TABLAS {
            let n: i64 = c.query_row(&format!("SELECT COUNT(*) FROM {t};"), [], |f| f.get(0)).map_err(|e| e.to_string())?;
            m.poner(t, n);
        }
        Ok(m)
    }

    /// La huella del contenido buscable: cambia cuando entra o sale un libro o un fragmento (lo escriba quien lo
    /// escriba: este servidor o el backend de Python)
    fn huella(&self) -> Result<(i64, i64, i64, String), String> {
        let c = self.conexion()?;
        c.query_row(
            "SELECT (SELECT COUNT(*) FROM chunks), (SELECT IFNULL(MAX(rowid), 0) FROM chunks), (SELECT COUNT(*) FROM books), (SELECT IFNULL(MAX(modified_at), '') FROM books);",
            [],
            |f| Ok((f.get(0)?, f.get(1)?, f.get(2)?, f.get(3)?)),
        )
        .map_err(|e| e.to_string())
    }
}

// =========================================================================== leer un documento

/// `PDFParser.parse_document`
pub struct Documento {
    pub abs_path: String,
    pub nombre: String,
    pub ext: String,
    pub sha256: String,
    pub tamano: u64,
    pub paginas: Vec<(i64, String)>,
    pub marcadores: Vec<(String, usize, Option<usize>)>,
}

pub fn sha256_de(ruta: &str) -> std::io::Result<String> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut f = std::fs::File::open(ruta)?;
    let mut h = Sha256::new();
    let mut b = vec![0u8; 65536];
    loop {
        let n = f.read(&mut b)?;
        if n == 0 {
            break;
        }
        h.update(&b[..n]);
    }
    Ok(h.finalize().iter().map(|x| format!("{x:02x}")).collect())
}

/// `open(..., errors="ignore")` en modo texto
fn texto_ignorando(ruta: &str) -> std::io::Result<String> {
    let b = std::fs::read(ruta)?;
    Ok(String::from_utf8_lossy(&b).replace('\u{FFFD}', "").replace("\r\n", "\n").replace('\r', "\n"))
}

pub fn leer_documento(ruta: &str, pdf_listo: bool) -> Result<Documento, String> {
    let abs = abspath(ruta);
    if !Path::new(&abs).exists() {
        return Err(format!("El archivo no existe: {ruta}"));
    }
    let sha256 = sha256_de(&abs).map_err(|e| prig_plataforma::py::error_os(&e, &abs))?;
    let tamano = std::fs::metadata(&abs).map(|m| m.len()).unwrap_or(0);
    let nombre = basename(&abs);
    let ext = if nombre.contains('.') { nombre.rsplit('.').next().unwrap_or("").to_lowercase() } else { String::new() };
    let mut paginas: Vec<(i64, String)> = Vec::new();
    let mut marcadores = Vec::new();
    if ext == "pdf" {
        let leido = if pdf_listo { crate::pdf::paginas(&abs).and_then(|p| Ok((p, crate::pdf::marcadores(&abs)?))) } else { Err("PDFium no disponible".into()) };
        match leido {
            Ok((p, m)) => {
                paginas = p.into_iter().map(|(n, t)| (n as i64, t)).collect();
                marcadores = m;
            }
            Err(e) => {
                println!("PDFium no pudo leer {nombre} ({e}).");
                paginas.push((1, format!("Contenido PDF: {nombre}")));
            }
        }
    } else if ext == "ipynb" {
        if let Ok(Valor::Mapa(nb)) = texto_ignorando(&abs).map_err(|e| e.to_string()).and_then(|t| prig_plataforma::json::leer(&t)) {
            if let Some(Valor::Lista(celdas)) = nb.get("cells") {
                for (i, c) in celdas.iter().enumerate() {
                    let Valor::Mapa(c) = c else { break };
                    let texto = match c.get("source") {
                        None => String::new(),
                        Some(Valor::Lista(l)) => {
                            if l.iter().any(|x| !matches!(x, Valor::Texto(_))) {
                                break;
                            }
                            l.iter().map(Valor::texto_py).collect()
                        }
                        Some(v) => v.texto_py(),
                    };
                    let t = strip(&texto);
                    if !t.is_empty() {
                        let prefijo = if c.get("cell_type") == Some(&Valor::Texto("markdown".into())) { "# " } else { "" };
                        paginas.push((i as i64 + 1, format!("{prefijo}{t}")));
                    }
                }
            }
        }
        if paginas.is_empty() {
            paginas.push((1, String::new()));
        }
    } else {
        let t = texto_ignorando(&abs).unwrap_or_default();
        paginas.push((1, strip(&t).to_string()));
    }
    Ok(Documento { abs_path: abs, nombre, ext, sha256, tamano, paginas, marcadores })
}

// =========================================================================== capítulos y secciones

#[derive(Clone, Debug)]
pub struct Capitulo {
    pub id: String,
    pub num: i64,
    pub titulo: String,
    pub inicio: i64,
    pub fin: i64,
    pub resumen: String,
    pub temas: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct Apartado {
    /// El nivel del marcador (solo en las que salen de los marcadores del PDF)
    pub nivel: Option<usize>,
    pub id: String,
    pub capitulo: Option<String>,
    pub num: String,
    pub titulo: String,
    pub inicio: i64,
    pub fin: i64,
    pub resumen: String,
}

pub struct Estructura {
    pub capitulos: Vec<Capitulo>,
    pub secciones: Vec<Apartado>,
    pub origen: Option<&'static str>,
}

/// `TOCExtractor._desde_marcadores`
fn desde_marcadores(entradas: &[(String, usize, usize)], sid: &str, total: i64) -> Option<Estructura> {
    if entradas.len() < 3 {
        return None;
    }
    let (mut caps, mut secs) = (Vec::<Capitulo>::new(), Vec::<Apartado>::new());
    let (mut n_cap, mut n_sec) = (0i64, 0i64);
    for (i, (titulo, nivel, pagina)) in entradas.iter().enumerate() {
        let pagina = *pagina as i64;
        let mut fin = if total != 0 { total } else { pagina };
        for (_, nv, pg) in &entradas[i + 1..] {
            if nv <= nivel {
                fin = pagina.max(*pg as i64 - 1);
                break;
            }
        }
        if *nivel == 0 {
            n_cap += 1;
            caps.push(Capitulo { id: format!("chp_{sid}_{n_cap:02}"), num: n_cap, titulo: titulo.clone(), inicio: pagina, fin, resumen: titulo.clone(), temas: vec![titulo.clone()] });
        } else {
            n_sec += 1;
            secs.push(Apartado {
                nivel: Some(*nivel),
                id: format!("sec_{sid}_{n_sec:03}"),
                capitulo: caps.last().map(|c| c.id.clone()),
                num: format!("{n_cap}.{n_sec}"),
                titulo: titulo.clone(),
                inicio: pagina,
                fin,
                resumen: titulo.clone(),
            });
        }
    }
    if caps.is_empty() && !secs.is_empty() {
        let planos: Vec<(String, usize, usize)> = entradas.iter().map(|(t, _, p)| (t.clone(), 0, *p)).collect();
        return desde_marcadores(&planos, sid, total);
    }
    Some(Estructura { capitulos: caps, secciones: secs, origen: Some("marcadores_pdf") })
}

/// `TOCExtractor.extract_structure`: de los marcadores del PDF si los hay; si no, «Capítulo N» y «N.M» en el texto
pub fn estructura(doc: &Documento, sid: &str) -> Estructura {
    let entradas: Vec<(String, usize, usize)> = doc.marcadores.iter().filter_map(|(t, n, p)| p.filter(|p| *p != 0).map(|p| (t.clone(), *n, p))).collect();
    let total = doc.paginas.len() as i64;
    if let Some(e) = desde_marcadores(&entradas, sid, total) {
        return e;
    }
    static R: OnceLock<(regex::Regex, regex::Regex)> = OnceLock::new();
    let (re_cap, re_sec) = R.get_or_init(|| (regex::Regex::new(r"(?i)^(?:Capítulo|Chapter)\s+(\d+)[:\.\s]+(.+)$").unwrap(), regex::Regex::new(r"^(\d+\.\d+)\s+(.+)$").unwrap()));
    let (mut caps, mut secs) = (Vec::<Capitulo>::new(), Vec::<Apartado>::new());
    let (mut cap_actual, mut sec_actual): (Option<usize>, Option<usize>) = (None, None);
    for (pagina, texto) in &doc.paginas {
        for linea in texto.split('\n') {
            let l = strip(linea);
            if l.is_empty() {
                continue;
            }
            if let Some(m) = re_cap.captures(l) {
                let Ok(num) = m[1].parse::<i64>() else { continue };
                let titulo = strip(&m[2]).to_string();
                caps.push(Capitulo {
                    id: format!("chp_{sid}_{num:02}"),
                    num,
                    titulo: titulo.clone(),
                    inicio: *pagina,
                    fin: *pagina,
                    resumen: format!("Capítulo {num}: {titulo}"),
                    temas: vec![titulo],
                });
                cap_actual = Some(caps.len() - 1);
                continue;
            }
            if let (Some(m), Some(ci)) = (re_sec.captures(l), cap_actual) {
                let num = m[1].to_string();
                let titulo = strip(&m[2]).to_string();
                let c = &caps[ci];
                secs.push(Apartado {
                    nivel: None,
                    id: format!("sec_{sid}_{:02}_{}", c.num, num.replace('.', "_")),
                    capitulo: Some(c.id.clone()),
                    num: num.clone(),
                    titulo: titulo.clone(),
                    inicio: *pagina,
                    fin: *pagina,
                    resumen: format!("Sección {num}: {titulo}"),
                });
                sec_actual = Some(secs.len() - 1);
                continue;
            }
            if let Some(ci) = cap_actual {
                caps[ci].fin = *pagina;
            }
            if let Some(si) = sec_actual {
                secs[si].fin = *pagina;
            }
        }
    }
    if caps.is_empty() {
        let id = format!("chp_{sid}_01");
        caps.push(Capitulo { id: id.clone(), num: 1, titulo: doc.nombre.clone(), inicio: 1, fin: total, resumen: format!("Contenido completo de {}", doc.nombre), temas: vec![doc.nombre.clone()] });
        secs.push(Apartado { nivel: None, id: format!("sec_{sid}_01_1"), capitulo: Some(id), num: "1.0".into(), titulo: "Sección General".into(), inicio: 1, fin: total, resumen: "Sección única del documento".into() });
    }
    Estructura { capitulos: caps, secciones: secs, origen: None }
}

impl Estructura {
    /// Los capítulos como los dicts de Python (con `_es_seccion`, que les pone el troceador)
    pub fn capitulos_json(&self, sid: &str) -> Vec<Valor> {
        let marcas = self.origen.is_some();
        self.capitulos
            .iter()
            .map(|c| {
                let temas = Valor::Lista(c.temas.iter().map(|t| Valor::Texto(t.clone())).collect());
                let m = if marcas {
                    Mapa::new()
                        .con("source_id", sid)
                        .con("title", c.titulo.as_str())
                        .con("start_page", c.inicio)
                        .con("end_page", c.fin)
                        .con("key_topics", temas)
                        .con("prerequisites", Valor::Lista(vec![]))
                        .con("created_at", "")
                        .con("chapter_id", c.id.as_str())
                        .con("chapter_num", c.num)
                        .con("summary", c.resumen.as_str())
                } else {
                    Mapa::new()
                        .con("chapter_id", c.id.as_str())
                        .con("source_id", sid)
                        .con("chapter_num", c.num)
                        .con("title", c.titulo.as_str())
                        .con("start_page", c.inicio)
                        .con("end_page", c.fin)
                        .con("summary", c.resumen.as_str())
                        .con("key_topics", temas)
                        .con("prerequisites", Valor::Lista(vec![]))
                        .con("created_at", "")
                };
                Valor::Mapa(if c.inicio != 0 { m.con("_es_seccion", false) } else { m })
            })
            .collect()
    }

    pub fn secciones_json(&self, sid: &str) -> Vec<Valor> {
        self.secciones
            .iter()
            .map(|s| {
                let cap = s.capitulo.clone().map(Valor::Texto).unwrap_or(Valor::Nulo);
                let m = match s.nivel {
                    Some(n) => Mapa::new()
                        .con("source_id", sid)
                        .con("title", s.titulo.as_str())
                        .con("start_page", s.inicio)
                        .con("end_page", s.fin)
                        .con("key_topics", Valor::Lista(vec![Valor::Texto(s.titulo.clone())]))
                        .con("prerequisites", Valor::Lista(vec![]))
                        .con("created_at", "")
                        .con("section_id", s.id.as_str())
                        .con("chapter_id", cap)
                        .con("section_num", s.num.as_str())
                        .con("level", n as i64)
                        .con("summary", s.resumen.as_str()),
                    None => Mapa::new()
                        .con("section_id", s.id.as_str())
                        .con("chapter_id", cap)
                        .con("source_id", sid)
                        .con("section_num", s.num.as_str())
                        .con("title", s.titulo.as_str())
                        .con("start_page", s.inicio)
                        .con("end_page", s.fin)
                        .con("summary", s.resumen.as_str())
                        .con("created_at", ""),
                };
                Valor::Mapa(if s.inicio != 0 { m.con("_es_seccion", true) } else { m })
            })
            .collect()
    }
}

/// `SemanticChunker._ordenar_secciones`: secciones antes que capítulos, por página
pub fn secciones_para_trocear(e: &Estructura) -> Vec<Seccion> {
    let mut v: Vec<(bool, i64, Seccion)> = Vec::new();
    for s in e.secciones.iter().filter(|s| s.inicio != 0) {
        v.push((true, s.inicio, Seccion { es_seccion: true, inicio: s.inicio, fin: if s.fin != 0 { s.fin } else { 1_000_000_000 }, section_id: Some(s.id.clone()), chapter_id: s.capitulo.clone() }));
    }
    for c in e.capitulos.iter().filter(|c| c.inicio != 0) {
        v.push((false, c.inicio, Seccion { es_seccion: false, inicio: c.inicio, fin: if c.fin != 0 { c.fin } else { 1_000_000_000 }, section_id: None, chapter_id: Some(c.id.clone()) }));
    }
    v.sort_by_key(|(s, p, _)| (!*s, *p));
    v.into_iter().map(|(_, _, s)| s).collect()
}

/// `BookIngestor.ingest_document`: (estado, source_id, fragmentos)
pub fn meter(cat: &Catalogo, ruta: &str, tipo: &str, pdf_listo: bool) -> Result<(&'static str, String, usize), String> {
    let doc = leer_documento(ruta, pdf_listo)?;
    if let Some(b) = cat.libro_por_sha(&doc.sha256)? {
        let sid = b.valor("source_id").texto_py();
        let n = cat.fragmentos_de(&sid)?;
        return Ok(("ALREADY_EXISTS", sid, n));
    }
    let sid = format!("{tipo}_{}", &doc.sha256[..16]);
    let e = estructura(&doc, &sid);
    let frags = troceado::fragmentar(&doc.paginas, &secciones_para_trocear(&e), 500);
    let ahora_s = ahora();
    let mut c = cat.conexion()?;
    let t = c.transaction().map_err(|e| e.to_string())?;
    let meta = Valor::Mapa(Mapa::new().con("ext", doc.ext.as_str()).con("abs_path", doc.abs_path.as_str()));
    t.execute(
        "INSERT OR REPLACE INTO books (source_id, source_type, title, original_filename, relative_path, sha256, file_size, authors_json, total_pages, document_version, index_version, metadata_json, created_at, modified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        params![sid, tipo, doc.nombre, doc.nombre, format!("{}/{}", tipo.to_uppercase(), doc.nombre), doc.sha256.to_lowercase(), doc.tamano as i64, "[]", doc.paginas.len() as i64, 1, 1, json_ascii(&meta), ahora_s, ahora_s],
    )
    .map_err(|e| e.to_string())?;
    for ch in &e.capitulos {
        t.execute(
            "INSERT OR REPLACE INTO chapters (chapter_id, source_id, chapter_num, title, start_page, end_page, summary, key_topics_json, prerequisites_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            params![ch.id, sid, ch.num, ch.titulo, ch.inicio, ch.fin, ch.resumen, json_ascii(&lista_textos(&ch.temas)), "[]", ahora_s],
        )
        .map_err(|e| e.to_string())?;
    }
    for s in &e.secciones {
        t.execute(
            "INSERT OR REPLACE INTO sections (section_id, chapter_id, source_id, section_num, title, start_page, end_page, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            params![s.id, s.capitulo, sid, s.num, s.titulo, s.inicio, s.fin, s.resumen, ahora_s],
        )
        .map_err(|e| e.to_string())?;
    }
    let ids: Vec<String> = frags.iter().map(|f| format!("chk_{sid}_{:04}", f.numero)).collect();
    for (i, f) in frags.iter().enumerate() {
        t.execute(
            "INSERT OR REPLACE INTO chunks (chunk_id, source_id, chapter_id, section_id, content, content_type, token_count, previous_chunk_id, next_chunk_id, contains_equation, contains_code, topics_json, concepts_json, symbols_json, page_start, page_end, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            params![
                ids[i],
                sid,
                f.chapter_id,
                f.section_id,
                f.texto,
                f.clase.tipo,
                f.tokens,
                if i > 0 { Some(&ids[i - 1]) } else { None },
                ids.get(i + 1),
                f.clase.ecuacion as i64,
                f.clase.codigo as i64,
                "[]",
                "[]",
                json_ascii(&lista_textos(&f.clase.simbolos)),
                f.pagina_inicio,
                f.pagina_fin,
                ahora(),
            ],
        )
        .map_err(|e| e.to_string())?;
    }
    t.commit().map_err(|e| e.to_string())?;
    Ok(("INGESTED", sid, frags.len()))
}

// =========================================================================== buscar

/// `QueryAnalyzer.analyze_query`
pub fn analizar_consulta(q: &str) -> Mapa {
    static R: OnceLock<[regex::Regex; 5]> = OnceLock::new();
    let r = R.get_or_init(|| {
        [
            regex::Regex::new(r"(derivad|gradiente|ecuaci|fórmula|pérdida|loss|matemátic|matriz|tensor|integral|optimiza)").unwrap(),
            regex::Regex::new(r"(código|implementa|pytorch|tensorflow|python|función|class|import|notebook|script)").unwrap(),
            regex::Regex::new(r"(cómo|paso a paso|pasos|procedimiento|guía|instrucciones)").unwrap(),
            regex::Regex::new(r"(diferencia|compar|difiere|versus|vs|frente a)").unwrap(),
            regex::Regex::new(r"(qué es|defina|concepto de|significado)").unwrap(),
        ]
    });
    let b = q.to_lowercase();
    let si: Vec<bool> = r.iter().map(|x| x.is_match(&b)).collect();
    let nombres = ["MATHEMATICAL", "CODE", "PROCEDURAL", "COMPARISON", "DEFINITION"];
    let mut activos: Vec<&str> = nombres.iter().zip(&si).filter(|(_, s)| **s).map(|(n, _)| *n).collect();
    if activos.len() > 1 {
        activos.push("MULTI_HOP");
    } else if activos.is_empty() {
        activos.push("CONCEPTUAL");
    }
    Mapa::new()
        .con("query", q)
        .con("primary_type", activos[0])
        .con("active_types", Valor::Lista(activos.iter().map(|a| Valor::Texto(a.to_string())).collect()))
        .con("is_math_required", si[0])
        .con("is_code_required", si[1])
        .con("is_procedural_required", si[2])
}

/// Los índices de búsqueda de un catálogo (se rehacen cuando cambia su contenido)
pub struct Motor {
    corpus: Vec<Mapa>,
    bm25: Option<Bm25>,
    vectorial: Option<Vectorial>,
}

impl Motor {
    fn new(cat: &Catalogo) -> Result<Motor, String> {
        let corpus = filas(&cat.conexion()?, "SELECT chunk_id, source_id, chapter_id, section_id, content, content_type, page_start FROM chunks;", &[]).map_err(|e| e.to_string())?;
        let textos: Vec<String> = corpus.iter().map(|d| d.valor("content").texto_py()).collect();
        let (bm25, vectorial) = if corpus.is_empty() { (None, None) } else { (Some(Bm25::new(&textos, 1.5, 0.75)), Some(Vectorial::new(&textos))) };
        Ok(Motor { corpus, bm25, vectorial })
    }
}

/// `MacroRetriever.filter_candidate_sources`: los libros (hasta 5) cuyos capítulos nombran palabras de la consulta
fn fuentes_macro(cat: &Catalogo, q: &str) -> Result<HashSet<String>, String> {
    static R: OnceLock<regex::Regex> = OnceLock::new();
    let palabras: HashSet<String> = R.get_or_init(|| regex::Regex::new(r"\w+").unwrap()).find_iter(&q.to_lowercase()).map(|m| m.as_str().to_string()).collect();
    if palabras.is_empty() {
        return Ok(HashSet::new());
    }
    let c = cat.conexion()?;
    let mut st = c.prepare("SELECT source_id, title, key_topics_json, summary FROM chapters;").map_err(|e| e.to_string())?;
    let filas = st
        .query_map([], |f| Ok((f.get::<_, String>(0)?, de_sql(f.get_ref(1)?).texto_py(), de_sql(f.get_ref(2)?).texto_py(), de_sql(f.get_ref(3)?).texto_py())))
        .map_err(|e| e.to_string())?;
    let mut puntos: Vec<(String, f64)> = Vec::new();
    for (sid, titulo, temas, resumen) in filas.flatten() {
        let texto = format!("{titulo} {resumen} {temas}").to_lowercase();
        let n = palabras.iter().filter(|w| texto.contains(w.as_str())).count();
        if n > 0 {
            match puntos.iter_mut().find(|(s, _)| *s == sid) {
                Some(p) => p.1 += n as f64,
                None => puntos.push((sid, n as f64)),
            }
        }
    }
    puntos.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    Ok(puntos.into_iter().take(5).map(|(s, _)| s).collect())
}

/// `HybridRetriever.retrieve`: BM25 (0,55) y TF-IDF (0,45) normalizados por su máximo, +0,05 a los libros del tema
fn recuperar(cat: &Catalogo, m: &Motor, q: &str, top_k: usize) -> Vec<Mapa> {
    let analisis = analizar_consulta(q);
    let pool = (top_k * 3).max(60);
    let bm25 = m.bm25.as_ref().map(|i| i.buscar(q, pool)).unwrap_or_default();
    let vec = m.vectorial.as_ref().map(|i| i.buscar(q, pool)).unwrap_or_default();
    let macro_ = fuentes_macro(cat, q).unwrap_or_default();
    let maximo = |l: &[(usize, f64)]| {
        let x = l.iter().map(|(_, s)| *s).fold(f64::NEG_INFINITY, f64::max);
        if l.is_empty() || x == 0.0 { 1.0 } else { x }
    };
    let (mb, mv) = (maximo(&bm25), maximo(&vec));
    let pb: HashMap<usize, f64> = bm25.iter().cloned().collect();
    let pv: HashMap<usize, f64> = vec.iter().cloned().collect();
    let mut orden: Vec<usize> = bm25.iter().map(|(i, _)| *i).collect();
    for (i, _) in &vec {
        if !pb.contains_key(i) {
            orden.push(*i);
        }
    }
    let mut cands: Vec<Mapa> = orden
        .into_iter()
        .map(|i| {
            let doc = &m.corpus[i];
            let nb = (pb.get(&i).copied().unwrap_or(0.0) / mb).min(1.0);
            let nv = (pv.get(&i).copied().unwrap_or(0.0) / mv).min(1.0);
            let mut f = nb * 0.55 + nv * 0.45;
            if macro_.contains(&doc.valor("source_id").texto_py()) {
                f += 0.05;
            }
            Mapa::new()
                .con("chunk", doc.clone())
                .con("chunk_id", doc.valor("chunk_id").clone())
                .con("bm25_score", redondear(nb, 4))
                .con("vector_score", redondear(nv, 4))
                .con("fused_score", redondear(f.min(1.0), 4))
                .con("query_analysis", analisis.clone())
        })
        .collect();
    cands.sort_by(|a, b| b.num_o("fused_score", 0.0).partial_cmp(&a.num_o("fused_score", 0.0)).unwrap_or(std::cmp::Ordering::Equal));
    cands.truncate(top_k);
    cands
}

/// `ExplicableReranker.rerank` (con su auditoría en `retrieval_runs`/`retrieval_results`)
fn reordenar(cat: &Catalogo, cands: &[Mapa], q: &str, top_k: usize) -> Vec<Mapa> {
    if cands.is_empty() {
        return Vec::new();
    }
    let a = cands[0].mapa("query_analysis").cloned().unwrap_or_default();
    let (mat, cod, pro) = (a.verdad("is_math_required"), a.verdad("is_code_required"), a.verdad("is_procedural_required"));
    let mut salida: Vec<Mapa> = cands
        .iter()
        .map(|c| {
            let doc = c.mapa("chunk").cloned().unwrap_or_default();
            let (b, v) = (c.num_o("bm25_score", 0.0), c.num_o("vector_score", 0.0));
            let tipo = doc.get("content_type").map(Valor::texto_py).unwrap_or_else(|| "TEXT".into());
            let mut s = 0.5;
            let mut razones = Vec::new();
            if mat && (tipo == "MATHEMATICS" || tipo == "PROOF") {
                s += 0.4;
                razones.push("Contiene ecuaciones y fórmulas matemáticas relevantes");
            }
            if cod && tipo == "CODE" {
                s += 0.4;
                razones.push("Contiene bloques de código Python ejecutables");
            }
            if pro && (tipo == "ALGORITHM" || tipo == "DEFINITION") {
                s += 0.3;
                razones.push("Contiene definición o pasos procedimentales del algoritmo");
            }
            if razones.is_empty() {
                razones.push("Coincidencia textual y semántica con la consulta");
            }
            let s = f64::min(1.0, s);
            let tema = redondear((b + v) / 2.0, 4);
            let ctx = if doc.get("section_id").is_some_and(Valor::verdad) { 0.8 } else { 0.5 };
            let r = redondear(b * 0.3 + v * 0.35 + s * 0.25 + ctx * 0.10, 4);
            let fin = redondear(r * 0.85 + tema * 0.15, 4);
            Mapa::new()
                .con("chunk_id", doc.valor("chunk_id").clone())
                .con("source_id", doc.valor("source_id").clone())
                .con("chapter_id", doc.get("chapter_id").cloned().unwrap_or(Valor::Nulo))
                .con("section_id", doc.get("section_id").cloned().unwrap_or(Valor::Nulo))
                .con("content", doc.valor("content").clone())
                .con("content_type", tipo)
                .con("page_start", doc.get("page_start").cloned().unwrap_or(Valor::Entero(1)))
                .con("bm25_score", b)
                .con("vector_score", v)
                .con("structure_score", redondear(s, 4))
                .con("topic_score", tema)
                .con("context_score", ctx)
                .con("reranker_score", r)
                .con("final_score", fin)
                .con("reasons", Valor::Lista(razones.iter().map(|x| Valor::Texto(x.to_string())).collect()))
        })
        .collect();
    salida.sort_by(|a, b| b.num_o("final_score", 0.0).partial_cmp(&a.num_o("final_score", 0.0)).unwrap_or(std::cmp::Ordering::Equal));
    salida.truncate(top_k);
    for (i, m) in salida.iter_mut().enumerate() {
        m.poner("rank", (i + 1) as i64);
    }
    let run = format!("run_{}", &uuid::Uuid::new_v4().simple().to_string()[..8]);
    let auditar = || -> Result<(), String> {
        let mut c = cat.conexion()?;
        let t = c.transaction().map_err(|e| e.to_string())?;
        t.execute(
            "INSERT INTO retrieval_runs (run_id, query, query_type, candidate_count, final_count, retriever_version, embedding_model, reranker_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            params![run, q, a.get("primary_type").map(Valor::texto_py).unwrap_or_else(|| "CONCEPTUAL".into()), cands.len() as i64, salida.len() as i64, "v3.0", "tfidf-hybrid", "explicable-v1", ahora()],
        )
        .map_err(|e| e.to_string())?;
        for r in &salida {
            let n = r.num_o("rank", 0.0) as i64;
            t.execute(
                "INSERT INTO retrieval_results (result_id, run_id, chunk_id, bm25_score, vector_score, structure_score, topic_score, context_score, reranker_score, final_score, rank, reasons_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                params![
                    format!("{run}_{n}"),
                    run,
                    r.valor("chunk_id").texto_py(),
                    r.num_o("bm25_score", 0.0),
                    r.num_o("vector_score", 0.0),
                    r.num_o("structure_score", 0.0),
                    r.num_o("topic_score", 0.0),
                    r.num_o("context_score", 0.0),
                    r.num_o("reranker_score", 0.0),
                    r.num_o("final_score", 0.0),
                    n,
                    json_ascii(r.get("reasons").unwrap_or(&Valor::Lista(vec![]))),
                ],
            )
            .map_err(|e| e.to_string())?;
        }
        t.commit().map_err(|e| e.to_string())
    };
    if let Err(e) = auditar() {
        println!("Advertencia al auditar retrieval run: {e}");
    }
    salida
}

/// `ContextDistiller.distill_context`: los fragmentos que caben en el presupuesto (~3,5 caracteres por token)
fn destilar(reord: &[Mapa], q: &str, max_tokens: i64) -> Mapa {
    let estimar = |t: &str| (t.chars().count() as f64 / 3.5) as i64 + 1;
    let (mut usados, mut fuera) = (0i64, 0i64);
    let mut dest: Vec<Mapa> = Vec::new();
    for c in reord.iter().take(15) {
        let mut contenido = c.valor("content").texto_py();
        let mut coste = estimar(&contenido);
        if usados + coste > max_tokens {
            let resto = max_tokens - usados;
            if resto > 120 && dest.is_empty() {
                contenido = contenido.chars().take((resto as f64 * 3.5) as usize).collect::<String>() + " […]";
                coste = estimar(&contenido);
            } else {
                fuera += 1;
                continue;
            }
        }
        dest.push(
            Mapa::new()
                .con("chunk_id", c.valor("chunk_id").clone())
                .con("source_id", c.valor("source_id").clone())
                .con("content_type", c.valor("content_type").clone())
                .con("page", c.valor("page_start").clone())
                .con("content", contenido)
                .con("score", c.get("final_score").cloned().unwrap_or(Valor::Nulo))
                .con("reasons", c.get("reasons").cloned().unwrap_or(Valor::Lista(vec![]))),
        );
        usados += coste;
    }
    let mut p = format!("CONTEXTO EXTRAÍDO Y VERIFICADO DE LA BIBLIOTECA ({} fragmentos destilados):\n\n", dest.len());
    for (i, d) in dest.iter().enumerate() {
        p.push_str(&format!(
            "--- FRAGMENTO [{}] ({} | Tipo: {} | Pág: {}) ---\n{}\n\n",
            i + 1,
            d.valor("chunk_id").texto_py(),
            d.valor("content_type").texto_py(),
            d.valor("page").texto_py(),
            d.valor("content").texto_py()
        ));
    }
    Mapa::new()
        .con("query", q)
        .con("total_chunks_distilled", dest.len() as i64)
        .con("chunks_dropped_by_budget", fuera)
        .con("estimated_tokens", usados)
        .con("token_budget", max_tokens)
        .con("formatted_context_prompt", strip(&p).to_string())
        .con("distilled_chunks", Valor::Lista(dest.into_iter().map(Valor::Mapa).collect()))
}

/// `list(set(enteros))` en CPython: el orden de la tabla hash (pocos enteros: tabla de 8 con sondeo lineal)
pub fn orden_de_set(v: &[i128]) -> Vec<i128> {
    let mut tabla: Vec<Option<i128>> = vec![None; 8];
    for x in v {
        if tabla.contains(&Some(*x)) {
            continue;
        }
        let h = if *x == -1 { -2 } else { *x };
        let mut i = (h as u64 & 7) as usize;
        while tabla[i].is_some() {
            i = (i + 1) & 7;
        }
        tabla[i] = Some(*x);
    }
    tabla.into_iter().flatten().collect()
}

/// `EvidenceBuilder.build_evidence`
fn evidencia(cat: &Catalogo, reord: &[Mapa], concepto: &str) -> Valor {
    let Some(top) = reord.first() else {
        return Valor::Mapa(
            Mapa::new()
                .con("concept_name", concepto)
                .con("has_evidence", false)
                .con("evidence_strength", "INSUFFICIENT_EVIDENCE")
                .con("summary", "No se encontraron fragmentos con suficiente solidez en la biblioteca."),
        );
    };
    let ids: Vec<Valor> = reord.iter().take(3).map(|c| c.valor("chunk_id").clone()).collect();
    let paginas = orden_de_set(&reord.iter().take(3).map(|c| c.num_o("page_start", 0.0) as i128).collect::<Vec<_>>());
    let sid = top.get("source_id").map(Valor::texto_py).unwrap_or_default();
    let info = cat.libro(&sid).ok().flatten().unwrap_or_default();
    let titulo = info.get("title").filter(|t| t.verdad()).map(Valor::texto_py).unwrap_or_else(|| if sid.is_empty() { "Biblioteca".into() } else { sid.clone() });
    let texto_pags = paginas.iter().map(|p| p.to_string()).collect::<Vec<_>>().join(", ");
    Valor::Mapa(
        Mapa::new()
            .con("evidence_id", format!("ev_{}", &uuid::Uuid::new_v4().simple().to_string()[..8]))
            .con("concept_name", concepto)
            .con("has_evidence", true)
            .con("evidence_strength", if reord.len() > 1 { "MULTI_SOURCE" } else { "DIRECT" })
            .con(
                "level_1_source",
                Mapa::new()
                    .con("source_id", top.valor("source_id").clone())
                    .con("source_title", titulo.as_str())
                    .con("source_path", info.get("relative_path").cloned().unwrap_or(Valor::Texto(String::new())))
                    .con("original_filename", info.get("original_filename").cloned().unwrap_or(Valor::Texto(String::new())))
                    .con("chapter_num", top.get("chapter_id").cloned().unwrap_or(Valor::Nulo))
                    .con("pages", Valor::Lista(paginas.iter().map(|p| Valor::Entero(*p)).collect()))
                    .con("chunk_ids", Valor::Lista(ids))
                    .con("location_summary", format!("Libro: {titulo} (Páginas {texto_pags})")),
            )
            .con("level_2_dependencies", Valor::Lista(vec![Valor::Texto("Prerrequisitos conceptuales del capítulo".into()), Valor::Texto("Matemáticas y código enlazado".into())]))
            .con("level_3_pedagogical_reason", format!("Ubicado en el plan de estudio porque {concepto} requiere la fundamentación extraída en los fragmentos de la biblioteca."))
            .con("top_reasons", top.get("reasons").cloned().unwrap_or(Valor::Lista(vec![])))
            .con("confidence", top.get("final_score").cloned().unwrap_or(Valor::Real(0.95))),
    )
}

// =========================================================================== el servicio

const INDEXABLES: [(&str, &str); 8] =
    [(".pdf", "book"), (".md", "documentation"), (".txt", "documentation"), (".rst", "documentation"), (".ipynb", "notebook"), (".py", "code"), (".js", "code"), (".sql", "code")];
const INFRAESTRUCTURA: [&str; 6] = ["metadata", ".index", "citas", "jobs", "librerias", "packs"];
const MAX_BYTES: u64 = 80 * 1024 * 1024;

fn tipo_de(ext: &str) -> Option<&'static str> {
    INDEXABLES.iter().find(|(e, _)| *e == ext).map(|(_, t)| *t)
}

/// `KnowledgeService`: la biblioteca, su catálogo, los índices en memoria y el trabajo de indexación
pub struct Conocimiento {
    pub raiz: String,
    pub catalogo: Catalogo,
    pub pdf_listo: bool,
    motor: Mutex<Option<((i64, i64, i64, String, Option<std::time::SystemTime>), Arc<Motor>)>>,
    shas: Mutex<HashMap<String, (std::time::SystemTime, u64, String)>>,
    trabajo: Mutex<Mapa>,
    parar: std::sync::atomic::AtomicBool,
}

fn trabajo_inicial() -> Mapa {
    Mapa::new()
        .con("running", false)
        .con("started_at", Valor::Nulo)
        .con("finished_at", Valor::Nulo)
        .con("total", 0)
        .con("processed", 0)
        .con("indexed", 0)
        .con("skipped", 0)
        .con("failed", 0)
        .con("current_file", Valor::Nulo)
        .con("errors", Valor::Lista(vec![]))
        .con("replaced", 0)
}

impl Conocimiento {
    pub fn new(raiz: &str, pdf_listo: bool) -> Result<Conocimiento, String> {
        let raiz = abspath(raiz);
        let _ = std::fs::create_dir_all(Path::new(&raiz).join(".index"));
        let catalogo = Catalogo::new(&join(&join(&raiz, ".index"), "catalog.db"))?;
        Ok(Conocimiento { raiz, catalogo, pdf_listo, motor: Mutex::new(None), shas: Mutex::new(HashMap::new()), trabajo: Mutex::new(trabajo_inicial()), parar: Default::default() })
    }

    fn generacion(&self) -> Option<std::time::SystemTime> {
        std::fs::metadata(Path::new(&self.raiz).join(".index").join("generacion")).and_then(|m| m.modified()).ok()
    }

    fn motor(&self) -> Result<Arc<Motor>, String> {
        let (a, b, c, d) = self.catalogo.huella()?;
        let clave = (a, b, c, d, self.generacion());
        let mut g = self.motor.lock().unwrap_or_else(|e| e.into_inner());
        if let Some((k, m)) = g.as_ref() {
            if *k == clave {
                return Ok(m.clone());
            }
        }
        let m = Arc::new(Motor::new(&self.catalogo)?);
        *g = Some((clave, m.clone()));
        Ok(m)
    }

    /// `file_sha256`, con caché por fecha y tamaño
    pub fn sha(&self, ruta: &str) -> Option<String> {
        let m = std::fs::metadata(ruta).ok()?;
        let (fecha, tam) = (m.modified().ok()?, m.len());
        let clave = abspath(ruta);
        if let Some((f, t, s)) = self.shas.lock().ok()?.get(&clave) {
            if *f == fecha && *t == tam {
                return Some(s.clone());
            }
        }
        let s = sha256_de(ruta).ok()?;
        self.shas.lock().ok()?.insert(clave, (fecha, tam, s.clone()));
        Some(s)
    }

    /// `discover_files`: lo indexable de la biblioteca (sin lo quitado ni las carpetas de Prig)
    pub fn descubrir(&self) -> Vec<Mapa> {
        let ocultos = Estante::new(&self.raiz).rutas_ocultas();
        let mut salida = Vec::new();
        self.recorrer(Path::new(&self.raiz), &ocultos, &mut salida);
        salida
    }

    fn recorrer(&self, dir: &Path, ocultos: &[String], salida: &mut Vec<Mapa>) {
        let Ok(l) = std::fs::read_dir(dir) else { return };
        let es_raiz = dir.to_string_lossy() == self.raiz;
        let (mut dirs, mut archivos) = (Vec::new(), Vec::new());
        for e in l.flatten() {
            let n = e.file_name().to_string_lossy().to_string();
            if std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false) {
                if n != "metadata" && !n.starts_with('.') && !(es_raiz && INFRAESTRUCTURA.contains(&n.as_str())) {
                    dirs.push((n, e.file_type().map(|t| t.is_symlink()).unwrap_or(false)));
                }
            } else {
                archivos.push(n);
            }
        }
        archivos.sort();
        for n in archivos {
            let ext = splitext(&n).1.to_lowercase();
            let Some(tipo) = tipo_de(&ext) else { continue };
            let ruta = join(&dir.to_string_lossy(), &n);
            if Estante::oculto(&abspath(&ruta), ocultos) {
                continue;
            }
            let rel = relpath(&ruta, &self.raiz);
            let categoria = if rel.contains('/') { rel.split('/').next().unwrap_or("").to_string() } else { tipo.to_string() };
            salida.push(Mapa::new().con("path", ruta).con("relative_path", rel).con("filename", n).con("category", categoria).con("source_type", tipo));
        }
        for (d, enlace) in dirs {
            if !enlace {
                self.recorrer(&dir.join(d), ocultos, salida);
            }
        }
    }

    fn ruta_de_libro(&self, b: &Mapa) -> String {
        let abs = b.get("metadata_json").and_then(|m| prig_plataforma::json::leer(&m.texto_py()).ok()).and_then(|m| match m {
            Valor::Mapa(m) => m.get("abs_path").filter(|a| a.verdad()).map(Valor::texto_py),
            _ => None,
        });
        abspath(&abs.unwrap_or_else(|| join(&self.raiz, &b.valor("relative_path").texto_py())))
    }

    /// `_purge_stale_version`: si el archivo cambió, fuera su versión anterior
    fn purgar_viejo(&self, ruta: &str, sha: Option<&str>, mapa: &HashMap<String, (String, String)>) -> bool {
        let Some(sha) = sha else { return false };
        match mapa.get(&abspath(ruta)) {
            Some((sid, viejo)) if viejo != sha => self.catalogo.borrar_libro(sid).unwrap_or(false),
            _ => false,
        }
    }

    fn mapa_por_ruta(&self) -> HashMap<String, (String, String)> {
        self.catalogo
            .libros()
            .unwrap_or_default()
            .iter()
            .map(|b| (self.ruta_de_libro(b), (b.valor("source_id").texto_py(), b.valor("sha256").texto_py())))
            .collect()
    }

    fn con_trabajo<R>(&self, f: impl FnOnce(&mut Mapa) -> R) -> R {
        f(&mut self.trabajo.lock().unwrap_or_else(|e| e.into_inner()))
    }

    /// `index_library`: todo lo indexable, saltando lo que no cambió
    pub fn indexar(&self, forzar: bool) {
        self.parar.store(false, std::sync::atomic::Ordering::SeqCst);
        let archivos = self.descubrir();
        let conocidos = if forzar { HashSet::new() } else { self.catalogo.shas().unwrap_or_default() };
        let _ = conocidos;
        let mapa = self.mapa_por_ruta();
        let mut reemplazados = 0i64;
        self.con_trabajo(|t| {
            let inicio = t.get("started_at").filter(|v| v.verdad()).cloned().unwrap_or_else(|| Valor::Texto(ahora()));
            t.poner("running", true);
            t.poner("started_at", inicio);
            t.poner("finished_at", Valor::Nulo);
            t.poner("total", archivos.len() as i64);
            for k in ["processed", "indexed", "skipped", "failed"] {
                t.poner(k, 0);
            }
            t.poner("current_file", Valor::Nulo);
            t.poner("errors", Valor::Lista(vec![]));
        });
        let sumar = |t: &mut Mapa, k: &str| {
            let n = t.num_o(k, 0.0) as i64 + 1;
            t.poner(k, n);
        };
        let error = |t: &mut Mapa, e: String| {
            let mut l = t.lista("errors").map(<[Valor]>::to_vec).unwrap_or_default();
            l.push(Valor::Texto(e));
            t.poner("errors", Valor::Lista(l));
        };
        for item in &archivos {
            if self.parar.load(std::sync::atomic::Ordering::SeqCst) {
                self.con_trabajo(|t| error(t, "Indexación detenida.".into()));
                break;
            }
            let rel = item.valor("relative_path").texto_py();
            let ruta = item.valor("path").texto_py();
            self.con_trabajo(|t| t.poner("current_file", rel.as_str()));
            let r: Result<bool, String> = (|| {
                if std::fs::metadata(&ruta).map_err(|e| prig_plataforma::py::error_os(&e, &ruta))?.len() > MAX_BYTES {
                    self.con_trabajo(|t| {
                        sumar(t, "skipped");
                        error(t, format!("{rel}: demasiado grande, omitido"));
                    });
                    return Ok(false);
                }
                if self.purgar_viejo(&ruta, self.sha(&ruta).as_deref(), &mapa) {
                    reemplazados += 1;
                }
                let (estado, _, _) = meter(&self.catalogo, &ruta, &item.valor("source_type").texto_py(), self.pdf_listo)?;
                self.con_trabajo(|t| sumar(t, if estado == "INGESTED" { "indexed" } else { "skipped" }));
                Ok(true)
            })();
            self.con_trabajo(|t| {
                if let Err(e) = r {
                    sumar(t, "failed");
                    error(t, format!("{rel}: {e}"));
                }
                sumar(t, "processed");
            });
        }
        self.con_trabajo(|t| {
            t.poner("running", false);
            t.poner("current_file", Valor::Nulo);
            t.poner("finished_at", ahora());
            t.poner("replaced", reemplazados);
        });
        // el backend de Python rehace sus índices en memoria cuando cambia `.index/generacion`
        let marca = Path::new(&self.raiz).join(".index").join("generacion");
        let _ = std::fs::write(&marca, ahora());
    }

    /// `index_single`: un archivo recién importado, sin recorrer la biblioteca. (estado, fragmentos)
    pub fn indexar_uno(&self, ruta: &str, tipo: &str) -> Result<(&'static str, usize), String> {
        self.purgar_viejo(ruta, self.sha(ruta).as_deref(), &self.mapa_por_ruta());
        let (estado, _, n) = meter(&self.catalogo, ruta, tipo, self.pdf_listo)?;
        if estado == "INGESTED" {
            // el backend de Python rehace sus índices en memoria cuando cambia `.index/generacion`
            let _ = std::fs::write(Path::new(&self.raiz).join(".index").join("generacion"), ahora());
        }
        Ok((estado, n))
    }

    /// `index_library_async`: en marcha ANTES de lanzar el hilo (así el estado no dice «terminado» por un instante)
    pub fn indexar_en_segundo_plano(self: &'static Self, forzar: bool) -> Mapa {
        let ya = self.con_trabajo(|t| t.verdad("running"));
        if ya {
            return Mapa::new().con("status", "already_running").con("job", self.con_trabajo(|t| t.clone()));
        }
        let job = self.con_trabajo(|t| {
            t.poner("running", true);
            t.poner("started_at", ahora());
            t.poner("finished_at", Valor::Nulo);
            for k in ["total", "processed", "indexed", "skipped", "failed"] {
                t.poner(k, 0);
            }
            t.poner("current_file", Valor::Nulo);
            t.poner("errors", Valor::Lista(vec![]));
            t.clone()
        });
        std::thread::spawn(move || self.indexar(forzar));
        Mapa::new().con("status", "started").con("job", job)
    }

    pub fn detener(&self) {
        self.parar.store(true, std::sync::atomic::Ordering::SeqCst);
    }

    /// `get_status`
    pub fn estado(&self) -> Result<Mapa, String> {
        let job = self.con_trabajo(|t| t.clone());
        let cuentas = self.catalogo.contar()?;
        let libros = self.catalogo.libros()?;
        let descubiertos = self.descubrir();
        let shas = self.catalogo.shas()?;
        let pendientes = descubiertos.iter().filter(|d| self.sha(&d.valor("path").texto_py()).is_none_or(|s| !shas.contains(&s))).count();
        let indexados: Vec<Valor> = libros
            .iter()
            .map(|b| {
                let mut m = Mapa::new();
                for k in ["source_id", "title", "source_type", "relative_path", "total_pages", "chunks_count", "file_size", "modified_at"] {
                    m.poner(k, b.get(k).cloned().unwrap_or(Valor::Nulo));
                }
                Valor::Mapa(m)
            })
            .collect();
        Ok(Mapa::new()
            .con("books_dir", self.raiz.as_str())
            .con("db_path", self.catalogo.ruta.as_str())
            .con("counts", cuentas)
            .con("files_discovered", descubiertos.len() as i64)
            .con("files_pending", pendientes as i64)
            .con("indexed_books", Valor::Lista(indexados))
            .con("job", job))
    }

    /// `search`: con las reformulaciones (`expansiones`) del modelo si las hay
    pub fn buscar(&self, q: &str, top_k: usize, max_tokens: i64, expansiones: &[String]) -> Result<Mapa, String> {
        let m = self.motor()?;
        let mut consultas = vec![q.to_string()];
        consultas.extend(expansiones.iter().filter(|e| !strip(e).is_empty()).cloned());
        let mut unidos: Vec<Mapa> = Vec::new();
        for c in &consultas {
            for cand in recuperar(&self.catalogo, &m, c, top_k * 4) {
                let id = cand.valor("chunk_id").clone();
                match unidos.iter_mut().find(|x| x.get("chunk_id") == Some(&id)) {
                    Some(p) if cand.num_o("fused_score", 0.0) > p.num_o("fused_score", 0.0) => *p = cand,
                    Some(_) => {}
                    None => unidos.push(cand),
                }
            }
        }
        unidos.sort_by(|a, b| b.num_o("fused_score", 0.0).partial_cmp(&a.num_o("fused_score", 0.0)).unwrap_or(std::cmp::Ordering::Equal));
        unidos.truncate(top_k * 4);
        if unidos.is_empty() {
            return Ok(Mapa::new()
                .con("query", q)
                .con("found", false)
                .con("chunks", Valor::Lista(vec![]))
                .con("evidence", Valor::Nulo)
                .con("context_prompt", "")
                .con("stats", Mapa::new().con("candidates", 0).con("returned", 0)));
        }
        let reord = reordenar(&self.catalogo, &unidos, q, top_k);
        let dest = destilar(&reord, q, max_tokens);
        let ev = evidencia(&self.catalogo, &reord, q);
        let mut titulos: HashMap<String, Valor> = HashMap::new();
        let trozos: Vec<Valor> = dest
            .lista("distilled_chunks")
            .unwrap_or(&[])
            .iter()
            .map(|c| {
                let Valor::Mapa(c) = c else { return c.clone() };
                let sid = c.valor("source_id").texto_py();
                let t = titulos
                    .entry(sid.clone())
                    .or_insert_with(|| self.catalogo.libro(&sid).ok().flatten().and_then(|b| b.get("title").filter(|t| t.verdad()).cloned()).unwrap_or(Valor::Texto(sid.clone())))
                    .clone();
                Valor::Mapa(c.clone().con("source_title", t))
            })
            .collect();
        Ok(Mapa::new()
            .con("query", q)
            .con("expansions_used", Valor::Lista(consultas[1..].iter().map(|c| Valor::Texto(c.clone())).collect()))
            .con("found", true)
            .con("chunks", Valor::Lista(trozos))
            .con("evidence", ev)
            .con("context_prompt", dest.valor("formatted_context_prompt").clone())
            .con(
                "stats",
                Mapa::new()
                    .con("candidates", unidos.len() as i64)
                    .con("returned", reord.len() as i64)
                    .con("estimated_tokens", dest.valor("estimated_tokens").clone())
                    .con("token_budget", dest.valor("token_budget").clone())
                    .con("chunks_dropped_by_budget", dest.valor("chunks_dropped_by_budget").clone()),
            ))
    }
}

/// El de la biblioteca de siempre (`PRIG_BOOKS_DIR` o `~/.prig_books`), uno por proceso
pub fn global(pdf_listo: impl FnOnce() -> bool) -> Result<&'static Conocimiento, String> {
    static C: OnceLock<Result<Conocimiento, String>> = OnceLock::new();
    C.get_or_init(|| Conocimiento::new(&Estante::por_defecto().raiz, pdf_listo())).as_ref().map_err(|e| e.clone())
}

pub fn ruta_raiz() -> PathBuf {
    PathBuf::from(Estante::por_defecto().raiz)
}
