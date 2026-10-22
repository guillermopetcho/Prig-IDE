//! La base de conocimiento destilada (`knowledge_base.py`): un SQLite con FTS5 (`.index/knowledge.db`) con los
//! conceptos canónicos (todos sus nombres llevan al mismo), las afirmaciones con su cita, las relaciones entre
//! conceptos, los símbolos, la estructura de cada libro y los dosieres ya reunidos. Mismo esquema y mismas
//! consultas que Python.

use std::collections::HashSet;
use std::sync::OnceLock;

use prig_recursos::valor::{redondear, Mapa, Valor};
use rusqlite::Connection;
use unicode_general_category::{get_general_category, GeneralCategory};
use unicode_normalization::UnicodeNormalization;

pub const VERSION_ESQUEMA: &str = "3.1";

const ARTICULOS: [&str; 14] = ["el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "the", "a", "an", "of"];

const VACIAS: [&str; 46] = [
    "que", "como", "cual", "cuales", "para", "por", "con", "sin", "sobre", "entre", "este", "esta", "esto", "esos", "esas", "cuando", "donde", "porque",
    "pero", "mas", "muy", "son", "ser", "estar", "hay", "tiene", "hace", "puede", "debe", "explicame", "explica", "explicar", "dime", "quiero",
    "necesito", "saber", "funciona", "significa", "diferencia", "ejemplo", "ayuda", "ayudame", "and", "for", "with", "what",
];
const VACIAS_2: [&str; 6] = ["how", "why", "does", "can", "should", "explain"];

/// ¿Es una de `PALABRAS_VACIAS`?
pub fn es_vacia(p: &str) -> bool {
    vacia(p)
}

fn vacia(p: &str) -> bool {
    ARTICULOS.contains(&p) || VACIAS.contains(&p) || VACIAS_2.contains(&p)
}

/// `lower()` + NFD sin las marcas no espaciadoras (categoría Mn)
fn sin_marcas(t: &str) -> String {
    t.to_lowercase().nfd().filter(|c| get_general_category(*c) != GeneralCategory::NonspacingMark).collect()
}

/// `_raiz`: la misma raíz para singular y plural («redes» → «red», «gradientes» → «gradient»)
pub fn raiz(p: &str) -> String {
    let n = p.chars().count();
    if n <= 3 {
        return p.to_string();
    }
    let mut s: Vec<char> = p.chars().collect();
    if p.ends_with("es") && n > 4 {
        s.truncate(n - 2);
    } else if p.ends_with('s') && n > 3 {
        s.truncate(n - 1);
    }
    if s.last() == Some(&'e') && s.len() > 3 {
        s.pop();
    }
    s.into_iter().collect()
}

/// `palabras_contenido`: las palabras de una consulta que discriminan (sin vacías, una por raíz)
pub fn palabras_contenido(texto: &str) -> Vec<String> {
    static R: OnceLock<regex::Regex> = OnceLock::new();
    let t = sin_marcas(texto);
    let mut vistas = HashSet::new();
    let mut salida = Vec::new();
    for m in R.get_or_init(|| regex::Regex::new(r"[a-z0-9_+#]{3,}").unwrap()).find_iter(&t) {
        let p = m.as_str();
        if vacia(p) {
            continue;
        }
        if vistas.insert(raiz(p)) {
            salida.push(p.to_string());
        }
    }
    salida
}

/// `normalizar_nombre`: sin acentos, artículos, plurales ni signos
pub fn normalizar_nombre(nombre: &str) -> String {
    let t: String = sin_marcas(nombre).chars().map(|c| if c.is_ascii_lowercase() || c.is_ascii_digit() || c.is_whitespace() { c } else { ' ' }).collect();
    t.split_whitespace().filter(|p| !ARTICULOS.contains(p)).map(raiz).collect::<Vec<_>>().join(" ")
}

const ESQUEMA: &str = "
CREATE TABLE IF NOT EXISTS books (source_id TEXT PRIMARY KEY, title TEXT, domain TEXT, sha256 TEXT, pages INTEGER, model_used TEXT, claims_verified INTEGER DEFAULT 0, imported_at TEXT);
CREATE TABLE IF NOT EXISTS concepts (concept_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, norm TEXT NOT NULL, domains TEXT, is_bridge INTEGER DEFAULT 0, mentions INTEGER DEFAULT 0, books INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_concepts_norm ON concepts(norm);
CREATE INDEX IF NOT EXISTS idx_concepts_bridge ON concepts(is_bridge);
CREATE TABLE IF NOT EXISTS aliases (norm TEXT NOT NULL, concept_id TEXT NOT NULL, surface TEXT, source_id TEXT NOT NULL DEFAULT '', is_primary INTEGER DEFAULT 0, PRIMARY KEY (norm, concept_id, source_id));
CREATE INDEX IF NOT EXISTS idx_alias_norm ON aliases(norm);
CREATE TABLE IF NOT EXISTS claims (claim_id TEXT PRIMARY KEY, concept_id TEXT, source_id TEXT, domain TEXT, type TEXT, text TEXT, quote TEXT, page INTEGER, confidence REAL, code_language TEXT, latex TEXT, bridges_to TEXT);
CREATE INDEX IF NOT EXISTS idx_claims_concept ON claims(concept_id);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(type);
CREATE INDEX IF NOT EXISTS idx_claims_domain ON claims(domain);
CREATE INDEX IF NOT EXISTS idx_claims_lang ON claims(code_language);
CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(claim_id UNINDEXED, text, quote, concept_names, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS relations (source_concept TEXT, target_concept TEXT, type TEXT, quote TEXT, source_id TEXT, page INTEGER, cross_domain INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source_concept);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target_concept);
CREATE INDEX IF NOT EXISTS idx_rel_cross ON relations(cross_domain);
CREATE TABLE IF NOT EXISTS symbols (symbol TEXT, meaning TEXT, concept_id TEXT, source_id TEXT, domain TEXT, page INTEGER);
CREATE INDEX IF NOT EXISTS idx_sym_symbol ON symbols(symbol);
CREATE TABLE IF NOT EXISTS sections (section_id TEXT PRIMARY KEY, source_id TEXT, chapter_id TEXT, numero TEXT, titulo TEXT, pagina_inicio INTEGER, pagina_fin INTEGER, es_capitulo INTEGER DEFAULT 0, temas TEXT, resumen TEXT, prerrequisitos TEXT);
CREATE INDEX IF NOT EXISTS idx_sec_libro ON sections(source_id);
CREATE INDEX IF NOT EXISTS idx_sec_pagina ON sections(pagina_inicio);
CREATE TABLE IF NOT EXISTS figures (source_id TEXT, label TEXT, caption TEXT, tipo TEXT, page INTEGER);
CREATE INDEX IF NOT EXISTS idx_fig_libro ON figures(source_id);
CREATE TABLE IF NOT EXISTS questions (source_id TEXT, texto TEXT, page INTEGER, concept_id TEXT);
CREATE INDEX IF NOT EXISTS idx_preg_libro ON questions(source_id);
CREATE TABLE IF NOT EXISTS book_profiles (source_id TEXT PRIMARY KEY, json TEXT, built_at TEXT, modelos TEXT);
CREATE TABLE IF NOT EXISTS dossiers (concept_id TEXT PRIMARY KEY, json TEXT, built_at TEXT);
CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
";

fn de_sql(v: rusqlite::types::ValueRef<'_>) -> Valor {
    use rusqlite::types::ValueRef as V;
    match v {
        V::Null => Valor::Nulo,
        V::Integer(n) => Valor::Entero(n as i128),
        V::Real(r) => Valor::Real(r),
        V::Text(t) | V::Blob(t) => Valor::Texto(String::from_utf8_lossy(t).into_owned()),
    }
}

/// Las filas de una consulta como dicts (`sqlite3.Row`)
pub fn filas(c: &Connection, sql: &str, p: &[rusqlite::types::Value]) -> Result<Vec<Mapa>, String> {
    let mut st = c.prepare(sql).map_err(|e| e.to_string())?;
    let nombres: Vec<String> = st.column_names().iter().map(|s| s.to_string()).collect();
    let r = st
        .query_map(rusqlite::params_from_iter(p.iter()), |f| {
            let mut m = Mapa::new();
            for (i, n) in nombres.iter().enumerate() {
                m.poner(n.clone(), de_sql(f.get_ref(i)?));
            }
            Ok(m)
        })
        .map_err(|e| e.to_string())?;
    r.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
}

fn texto(t: &str) -> rusqlite::types::Value {
    rusqlite::types::Value::Text(t.to_string())
}

/// `domains` de JSON a lista
fn con_dominios(mut d: Mapa) -> Mapa {
    let l = d.get("domains").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| "[]".into());
    d.poner("domains", prig_plataforma::json::leer(&l).unwrap_or(Valor::Lista(vec![])));
    d
}

pub struct BaseKb {
    pub ruta: String,
}

impl BaseKb {
    /// `~/.prig_books/.index/knowledge.db` (la de siempre: no mira `PRIG_BOOKS_DIR`, como Python)
    pub fn por_defecto() -> Result<BaseKb, String> {
        let base = prig_plataforma::py::expanduser("~/.prig_books/.index");
        let _ = std::fs::create_dir_all(&base);
        BaseKb::new(&prig_plataforma::py::join(&base, "knowledge.db"))
    }

    pub fn new(ruta: &str) -> Result<BaseKb, String> {
        let b = BaseKb { ruta: prig_plataforma::py::abspath(ruta) };
        let c = b.conectar()?;
        c.execute_batch(ESQUEMA).map_err(|e| e.to_string())?;
        migrar_alias(&c)?;
        c.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", [VERSION_ESQUEMA]).map_err(|e| e.to_string())?;
        Ok(b)
    }

    pub fn conectar(&self) -> Result<Connection, String> {
        let c = Connection::open(&self.ruta).map_err(|e| e.to_string())?;
        c.busy_timeout(std::time::Duration::from_secs(5)).map_err(|e| e.to_string())?;
        c.query_row("PRAGMA journal_mode = WAL;", [], |_| Ok(())).map_err(|e| e.to_string())?;
        c.execute_batch("PRAGMA synchronous = NORMAL;").map_err(|e| e.to_string())?;
        Ok(c)
    }

    /// `resolver`: de cualquier nombre o alias al concepto canónico
    pub fn resolver(&self, nombre: &str) -> Result<Option<Mapa>, String> {
        let norm = normalizar_nombre(nombre);
        if norm.is_empty() {
            return Ok(None);
        }
        let c = self.conectar()?;
        let mut f = filas(&c, "SELECT co.* FROM concepts co JOIN aliases a ON a.concept_id = co.concept_id WHERE a.norm = ? LIMIT 1;", &[texto(&norm)])?;
        if f.is_empty() {
            f = filas(&c, "SELECT * FROM concepts WHERE norm = ? LIMIT 1;", &[texto(&norm)])?;
        }
        if f.is_empty() {
            f = filas(&c, "SELECT * FROM concepts WHERE norm LIKE ? ORDER BY LENGTH(norm) LIMIT 1;", &[texto(&format!("{norm}%"))])?;
        }
        Ok(f.into_iter().next().map(con_dominios))
    }

    /// `buscar`: texto completo (FTS5, `rank` es su BM25) con filtros opcionales
    pub fn buscar(&self, consulta: &str, limite: i64, dominios: &[String], tipos: &[String], lenguaje: Option<&str>) -> Result<Vec<Mapa>, String> {
        let contenido = palabras_contenido(consulta);
        if contenido.is_empty() {
            return Ok(Vec::new());
        }
        let terminos = contenido.iter().map(|t| format!("\"{t}\"")).collect::<Vec<_>>().join(" OR ");
        let mut sql = String::from("SELECT c.*, bm25(claims_fts) AS rank\n                 FROM claims_fts JOIN claims c ON c.claim_id = claims_fts.claim_id\n                 WHERE claims_fts MATCH ?");
        let mut p = vec![texto(&terminos)];
        let marcas = |n: usize| vec!["?"; n].join(",");
        if !dominios.is_empty() {
            sql += &format!(" AND c.domain IN ({})", marcas(dominios.len()));
            p.extend(dominios.iter().map(|d| texto(d)));
        }
        if !tipos.is_empty() {
            sql += &format!(" AND c.type IN ({})", marcas(tipos.len()));
            p.extend(tipos.iter().map(|d| texto(d)));
        }
        if let Some(l) = lenguaje.filter(|l| !l.is_empty()) {
            sql += " AND c.code_language = ?";
            p.push(texto(l));
        }
        sql += " ORDER BY rank LIMIT ?";
        p.push(rusqlite::types::Value::Integer(limite as i64));
        filas(&self.conectar()?, &sql, &p)
    }

    /// `afirmaciones_de`: las de un concepto, las más seguras primero
    pub fn afirmaciones_de(&self, concepto: &str, tipos: &[String], limite: i64) -> Result<Vec<Mapa>, String> {
        let mut sql = String::from("SELECT * FROM claims WHERE concept_id = ?");
        let mut p = vec![texto(concepto)];
        if !tipos.is_empty() {
            sql += &format!(" AND type IN ({})", vec!["?"; tipos.len()].join(","));
            p.extend(tipos.iter().map(|t| texto(t)));
        }
        sql += " ORDER BY confidence DESC LIMIT ?";
        p.push(rusqlite::types::Value::Integer(limite as i64));
        filas(&self.conectar()?, &sql, &p)
    }

    /// `prerrequisitos`: el cierre de lo que hay que saber antes (REQUIRES, PART_OF), de la base a la cima
    pub fn prerrequisitos(&self, concepto: &str, profundidad: usize) -> Result<Vec<Mapa>, String> {
        let c = self.conectar()?;
        let mut vistos: HashSet<String> = HashSet::from([concepto.to_string()]);
        let mut capas: Vec<Vec<String>> = Vec::new();
        let mut frontera = vec![concepto.to_string()];
        for _ in 0..profundidad {
            if frontera.is_empty() {
                break;
            }
            let sql = format!(
                "SELECT DISTINCT target_concept FROM relations WHERE source_concept IN ({}) AND type IN ('REQUIRES','PART_OF');",
                vec!["?"; frontera.len()].join(",")
            );
            let p: Vec<_> = frontera.iter().map(|f| texto(f)).collect();
            let nuevos: Vec<String> = filas(&c, &sql, &p)?
                .into_iter()
                .filter_map(|f| f.get("target_concept").filter(|v| v.verdad()).map(Valor::texto_py))
                .filter(|t| !vistos.contains(t))
                .collect();
            if nuevos.is_empty() {
                break;
            }
            vistos.extend(nuevos.iter().cloned());
            capas.push(nuevos.clone());
            frontera = nuevos;
        }
        let mut salida = Vec::new();
        for (nivel, grupo) in capas.iter().rev().enumerate() {
            for cid in grupo {
                if let Some(f) = filas(&c, "SELECT * FROM concepts WHERE concept_id = ?;", &[texto(cid)])?.into_iter().next() {
                    salida.push(con_dominios(f).con("nivel", (nivel + 1) as i64));
                }
            }
        }
        Ok(salida)
    }

    /// `puentes`: conceptos de más de un campo
    pub fn puentes(&self, limite: i64) -> Result<Vec<Mapa>, String> {
        Ok(filas(&self.conectar()?, "SELECT * FROM concepts WHERE is_bridge = 1\n                                 ORDER BY books DESC, mentions DESC LIMIT ?;", &[rusqlite::types::Value::Integer(limite as i64)])?
            .into_iter()
            .map(con_dominios)
            .collect())
    }

    pub fn estadisticas(&self) -> Result<Mapa, String> {
        let c = self.conectar()?;
        let n = |sql: &str| c.query_row(sql, [], |f| f.get::<_, i64>(0)).map_err(|e| e.to_string());
        let mut por_dominio = Mapa::new();
        for f in filas(&c, "SELECT domain, COUNT(*) n FROM books GROUP BY domain;", &[])? {
            por_dominio.poner(f.get("domain").map(|d| if d.es_nulo() { "null".to_string() } else { d.texto_py() }).unwrap_or_default(), f.valor("n").clone());
        }
        let tam = std::fs::metadata(&self.ruta).map(|m| redondear(m.len() as f64 / (1024.0 * 1024.0), 2)).map(Valor::Real).unwrap_or(Valor::Entero(0));
        Ok(Mapa::new()
            .con("ruta", self.ruta.as_str())
            .con("libros", n("SELECT COUNT(*) FROM books;")?)
            .con("conceptos", n("SELECT COUNT(*) FROM concepts;")?)
            .con("afirmaciones", n("SELECT COUNT(*) FROM claims;")?)
            .con("relaciones", n("SELECT COUNT(*) FROM relations;")?)
            .con("simbolos", n("SELECT COUNT(*) FROM symbols;")?)
            .con("alias", n("SELECT COUNT(*) FROM aliases;")?)
            .con("dosieres", n("SELECT COUNT(*) FROM dossiers;")?)
            .con("puentes", n("SELECT COUNT(*) FROM concepts WHERE is_bridge=1;")?)
            .con("relaciones_cruzadas", n("SELECT COUNT(*) FROM relations WHERE cross_domain=1;")?)
            .con("libros_por_dominio", por_dominio)
            .con("tamano_mb", tam))
    }

    pub fn libros_dentro(&self) -> Result<HashSet<String>, String> {
        Ok(filas(&self.conectar()?, "SELECT source_id FROM books;", &[])?.into_iter().map(|f| f.valor("source_id").texto_py()).collect())
    }
}

/// `_migrar_aliases`: las bases antiguas al esquema actual de `aliases` (otra clave primaria)
fn migrar_alias(c: &Connection) -> Result<(), String> {
    let info = filas(c, "PRAGMA table_info(aliases);", &[])?;
    if info.is_empty() {
        return Ok(());
    }
    let columnas: HashSet<String> = info.iter().map(|f| f.valor("name").texto_py()).collect();
    let clave: Vec<String> = info.iter().filter(|f| f.valor("pk").verdad()).map(|f| f.valor("name").texto_py()).collect();
    if columnas.contains("is_primary") && clave == ["norm", "concept_id", "source_id"] {
        return Ok(());
    }
    let primaria = if columnas.contains("is_primary") { "is_primary" } else { "0" };
    c.execute_batch(&format!(
        "CREATE TABLE IF NOT EXISTS aliases_nueva (norm TEXT NOT NULL, concept_id TEXT NOT NULL, surface TEXT, source_id TEXT NOT NULL DEFAULT '', is_primary INTEGER DEFAULT 0, PRIMARY KEY (norm, concept_id, source_id));
         INSERT OR REPLACE INTO aliases_nueva SELECT norm, concept_id, surface, COALESCE(source_id,''), {primaria} FROM aliases;
         DROP TABLE aliases;
         ALTER TABLE aliases_nueva RENAME TO aliases;
         CREATE INDEX IF NOT EXISTS idx_alias_norm ON aliases(norm);"
    ))
    .map_err(|e| e.to_string())
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn nombres_y_palabras() {
        assert_eq!(normalizar_nombre("La Regularización L2"), "regularizacion l2");
        assert_eq!(normalizar_nombre("regularizaciones L2"), "regularizacion l2");
        assert_eq!(raiz("redes"), "red");
        assert_eq!(raiz("gradientes"), "gradient");
        assert_eq!(raiz("capas"), "capa");
        assert_eq!(palabras_contenido("¿Cómo funcionan los gradientes y el gradiente de una red?"), vec!["funcionan", "gradientes", "red"]);
    }
}
