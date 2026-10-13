//! El banco del proyecto (banco_proyecto.BancoProyecto): el mismo SQLite (esquema 6), las mismas consultas y el
//! mismo orden de escritura, para que un banco hecho por Python lo lea Rust y al revés, y los ids coincidan.

pub mod busqueda;
pub mod contexto;
pub mod grafo;
pub mod herramientas;
pub mod memoria;
pub mod sincronizar;
pub mod vectores;

use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use rusqlite::types::ValueRef;
use rusqlite::{params, Connection, OpenFlags};
use serde_json::{Map, Value};

use crate::py::ruta::{basename, join, normpath};
use crate::re::Re;
use crate::texto::VERSION_ESQUEMA;

pub type Resultado<T> = Result<T, String>;

pub fn error<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}

/// `carpeta_bancos()`: $PRIG_BANCOS o ~/.prig_bancos.
pub fn carpeta_bancos() -> String {
    match std::env::var("PRIG_BANCOS") {
        Ok(v) if !v.is_empty() => v,
        _ => {
            let casa = std::env::var("HOME").unwrap_or_else(|_| "/".to_string());
            join(&casa, ".prig_bancos")
        }
    }
}

/// `os.path.abspath`.
pub fn abspath(p: &str) -> String {
    if p.starts_with('/') {
        normpath(p)
    } else {
        let cwd = std::env::current_dir().map(|d| d.to_string_lossy().to_string()).unwrap_or_else(|_| "/".to_string());
        normpath(&join(&cwd, p))
    }
}

/// La carpeta por defecto del banco de una raíz: «nombre-sha1[:10]».
pub fn carpeta_de(raiz: &str) -> String {
    let clave = &crate::texto::sha(raiz)[..10];
    let base = basename(raiz);
    let base = if base.is_empty() { "raiz" } else { base };
    static NO_PALABRA: std::sync::LazyLock<Re> = std::sync::LazyLock::new(|| Re::nuevo(r"[^\w.-]+", ""));
    let nombre = NO_PALABRA.sub("_", base).into_owned();
    join(&carpeta_bancos(), &format!("{nombre}-{clave}"))
}

const ESQUEMA: &str = "
            CREATE TABLE IF NOT EXISTS archivos (
                ruta TEXT PRIMARY KEY, sha TEXT, mtime REAL, tamano INTEGER, lenguaje TEXT,
                lineas INTEGER, tokens INTEGER, resumen TEXT, resumen_ia TEXT, analizado_sha TEXT,
                contenido BLOB, version INTEGER);
            CREATE TABLE IF NOT EXISTS simbolos (
                id INTEGER PRIMARY KEY, ruta TEXT, nombre TEXT, corto TEXT, tipo TEXT, firma TEXT,
                doc TEXT, ini INTEGER, fin INTEGER, padre TEXT, sha TEXT);
            CREATE INDEX IF NOT EXISTS idx_sim_ruta ON simbolos(ruta);
            CREATE INDEX IF NOT EXISTS idx_sim_corto ON simbolos(corto);
            CREATE TABLE IF NOT EXISTS fragmentos (
                id INTEGER PRIMARY KEY, ruta TEXT, simbolo TEXT, tipo TEXT, ini INTEGER, fin INTEGER,
                texto TEXT, sha TEXT, tokens INTEGER);
            CREATE INDEX IF NOT EXISTS idx_frag_ruta ON fragmentos(ruta);
            CREATE INDEX IF NOT EXISTS idx_frag_sha ON fragmentos(sha);
            CREATE VIRTUAL TABLE IF NOT EXISTS fragmentos_fts USING fts5(ruta, simbolo, terminos);
            CREATE TABLE IF NOT EXISTS usos (ruta TEXT, nombre TEXT, linea INTEGER, dentro TEXT, receptor TEXT);
            CREATE TABLE IF NOT EXISTS alias (ruta TEXT, nombre TEXT, destino TEXT);
            CREATE INDEX IF NOT EXISTS idx_alias_ruta ON alias(ruta);
            CREATE TABLE IF NOT EXISTS llamadas (
                ruta TEXT, desde TEXT, a_ruta TEXT, a_nombre TEXT, linea INTEGER, confianza TEXT);
            CREATE INDEX IF NOT EXISTS idx_llam_desde ON llamadas(ruta, desde);
            CREATE INDEX IF NOT EXISTS idx_llam_a ON llamadas(a_ruta, a_nombre);
            CREATE INDEX IF NOT EXISTS idx_llam_nombre ON llamadas(a_nombre);
            CREATE INDEX IF NOT EXISTS idx_usos_nombre ON usos(nombre);
            CREATE INDEX IF NOT EXISTS idx_usos_ruta ON usos(ruta);
            CREATE TABLE IF NOT EXISTS importaciones (ruta TEXT, destino TEXT);
            CREATE INDEX IF NOT EXISTS idx_imp_destino ON importaciones(destino);
            CREATE INDEX IF NOT EXISTS idx_imp_ruta ON importaciones(ruta);
            CREATE TABLE IF NOT EXISTS cambios (
                id INTEGER PRIMARY KEY, version INTEGER, ruta TEXT, tipo TEXT, cuando TEXT,
                simbolos TEXT, diff TEXT, mas INTEGER, menos INTEGER);
            CREATE INDEX IF NOT EXISTS idx_cambios_version ON cambios(version);
            CREATE TABLE IF NOT EXISTS conocimiento (
                id INTEGER PRIMARY KEY, tipo TEXT, titulo TEXT, texto TEXT, rutas TEXT, origen TEXT,
                creado TEXT, actualizado TEXT, revisar INTEGER DEFAULT 0, version INTEGER);
            CREATE VIRTUAL TABLE IF NOT EXISTS conocimiento_fts USING fts5(titulo, terminos);
            CREATE TABLE IF NOT EXISTS resoluciones (
                id INTEGER PRIMARY KEY, pregunta TEXT, resumen TEXT, respuesta BLOB, rutas TEXT,
                modelo TEXT, cuando TEXT, version INTEGER);
            CREATE VIRTUAL TABLE IF NOT EXISTS resoluciones_fts USING fts5(pregunta, terminos);
            CREATE TABLE IF NOT EXISTS vectores (clave TEXT PRIMARY KEY, vector BLOB, modelo TEXT);
            CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
            CREATE TABLE IF NOT EXISTS hechos (
                s TEXT, r TEXT, o TEXT, ruta TEXT, linea INTEGER, origen TEXT, version INTEGER);
            CREATE INDEX IF NOT EXISTS idx_hechos_s ON hechos(s);
            CREATE INDEX IF NOT EXISTS idx_hechos_o ON hechos(o);
            CREATE INDEX IF NOT EXISTS idx_hechos_r ON hechos(r);
            CREATE INDEX IF NOT EXISTS idx_hechos_ruta ON hechos(ruta);
            DROP VIEW IF EXISTS grafo;
            CREATE VIEW grafo AS
                SELECT s, r, o, ruta, linea FROM hechos
                UNION ALL SELECT desde, 'llama', a_nombre, ruta, linea FROM llamadas
                UNION ALL SELECT ruta, 'importa', destino, ruta, 0 FROM importaciones
                UNION ALL SELECT ruta, 'define', nombre, ruta, ini FROM simbolos;
            CREATE TABLE IF NOT EXISTS trabajo (nombre TEXT PRIMARY KEY, valor TEXT, cuando TEXT);
            CREATE TABLE IF NOT EXISTS unidades (
                orden INTEGER PRIMARY KEY, nombre TEXT, tokens INTEGER, rutas TEXT, piezas TEXT,
                simbolos TEXT, vecinas TEXT, cambios_git INTEGER, version INTEGER, creado TEXT);
            CREATE TABLE IF NOT EXISTS resumenes (
                nivel TEXT, clave TEXT, texto TEXT, sha_fuente TEXT, modelo TEXT, cuando TEXT,
                PRIMARY KEY (nivel, clave));
            ";

/// El banco de un proyecto.
pub struct Banco {
    pub raiz: String,
    pub carpeta: String,
    pub ruta_db: String,
    pub modelo_vectores: String,
    /// `self._lock` de Python: una sincronización a la vez
    pub cerrojo: Mutex<()>,
    /// `self._vectores`: los vectores cargados (se invalidan al cambiar)
    vectores: Mutex<Option<Arc<HashMap<String, Vec<f32>>>>>,
}

/// `datetime.now().isoformat(timespec="seconds")`.
pub fn ahora() -> String {
    chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()
}

/// Una fila como dict de Python (`dict(sqlite3.Row)`): columnas en orden y tipos de SQLite.
pub fn fila_a_valor(fila: &rusqlite::Row) -> rusqlite::Result<Value> {
    let st = fila.as_ref();
    let mut m = Map::new();
    for i in 0..st.column_count() {
        let nombre = st.column_name(i)?.to_string();
        m.insert(nombre, valor_de(fila.get_ref(i)?));
    }
    Ok(Value::Object(m))
}

pub fn valor_de(v: ValueRef) -> Value {
    match v {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(i) => Value::from(i),
        ValueRef::Real(f) => serde_json::Number::from_f64(f).map(Value::Number).unwrap_or(Value::Null),
        ValueRef::Text(t) => Value::String(String::from_utf8_lossy(t).into_owned()),
        ValueRef::Blob(b) => Value::String(format!("<{} bytes>", b.len())),
    }
}

/// Todas las filas de una consulta como dicts.
pub fn filas(c: &Connection, sql: &str, args: &[&dyn rusqlite::ToSql]) -> Resultado<Vec<Value>> {
    let mut st = c.prepare_cached(sql).map_err(error)?;
    let iter = st.query_map(args, fila_a_valor).map_err(error)?;
    iter.collect::<rusqlite::Result<Vec<_>>>().map_err(error)
}

/// Texto de una columna (None si es NULL).
pub fn texto_de(fila: &rusqlite::Row, i: usize) -> rusqlite::Result<Option<String>> {
    match fila.get_ref(i)? {
        ValueRef::Null => Ok(None),
        ValueRef::Text(t) => Ok(Some(String::from_utf8_lossy(t).into_owned())),
        ValueRef::Integer(n) => Ok(Some(n.to_string())),
        ValueRef::Real(f) => Ok(Some(crate::py::numero::repr_float(f))),
        ValueRef::Blob(b) => Ok(Some(String::from_utf8_lossy(b).into_owned())),
    }
}

/// `zlib.decompress(blob).decode("utf-8", "replace")`.
pub fn descomprimir(blob: &[u8]) -> String {
    use std::io::Read;
    let mut d = flate2::read::ZlibDecoder::new(blob);
    let mut bytes = Vec::new();
    let _ = d.read_to_end(&mut bytes);
    String::from_utf8_lossy(&bytes).into_owned()
}

/// `zlib.compress(texto.encode(), 6)`.
pub fn comprimir(texto: &str) -> Vec<u8> {
    use std::io::Write;
    let mut e = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::new(6));
    let _ = e.write_all(texto.as_bytes());
    e.finish().unwrap_or_default()
}

impl Banco {
    /// `BancoProyecto(raiz, carpeta)`: crea la carpeta y el esquema si hace falta.
    pub fn abrir(raiz: &str, carpeta: Option<&str>, modelo_vectores: &str) -> Resultado<Banco> {
        let raiz = abspath(raiz);
        let carpeta = match carpeta {
            Some(c) if !c.is_empty() => c.to_string(),
            _ => carpeta_de(&raiz),
        };
        std::fs::create_dir_all(&carpeta).map_err(error)?;
        let ruta_db = join(&carpeta, "banco.db");
        let b = Banco {
            raiz,
            carpeta,
            ruta_db,
            modelo_vectores: modelo_vectores.to_string(),
            cerrojo: Mutex::new(()),
            vectores: Mutex::new(None),
        };
        b.crear()?;
        b.guardar_meta("raiz", &b.raiz)?;
        Ok(b)
    }

    /// Una conexión nueva (como `conectar()`: una por operación, timeout de 30 s).
    pub fn conectar(&self) -> Resultado<Connection> {
        let c = Connection::open_with_flags(&self.ruta_db, OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_CREATE | OpenFlags::SQLITE_OPEN_NO_MUTEX | OpenFlags::SQLITE_OPEN_URI)
            .map_err(error)?;
        c.busy_timeout(Duration::from_secs(30)).map_err(error)?;
        Ok(c)
    }

    /// Una conexión de solo lectura (la consola aislada).
    pub fn conectar_lectura(ruta_db: &str) -> Resultado<Connection> {
        let c = Connection::open_with_flags(ruta_db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX | OpenFlags::SQLITE_OPEN_URI).map_err(error)?;
        c.busy_timeout(Duration::from_secs(30)).map_err(error)?;
        Ok(c)
    }

    fn crear(&self) -> Resultado<()> {
        let c = self.conectar()?;
        c.query_row("PRAGMA journal_mode=WAL;", [], |_| Ok(())).map_err(error)?;
        c.execute_batch(ESQUEMA).map_err(error)?;
        let tiene_receptor = {
            let mut st = c.prepare("PRAGMA table_info(usos)").map_err(error)?;
            let nombres: Vec<String> = st.query_map([], |f| f.get::<_, String>(1)).map_err(error)?.filter_map(|x| x.ok()).collect();
            nombres.iter().any(|n| n == "receptor")
        };
        if !tiene_receptor {
            c.execute("ALTER TABLE usos ADD COLUMN receptor TEXT", []).map_err(error)?;
        }
        let previo: Option<String> = c.query_row("SELECT valor FROM meta WHERE clave = 'esquema'", [], |f| f.get(0)).ok();
        if let Some(p) = previo {
            if p.trim().parse::<i64>().unwrap_or(0) < VERSION_ESQUEMA {
                c.execute("INSERT OR REPLACE INTO meta VALUES ('reindexar', '1')", []).map_err(error)?;
            }
        }
        c.execute("INSERT OR REPLACE INTO meta VALUES ('esquema', ?)", params![VERSION_ESQUEMA.to_string()]).map_err(error)?;
        c.execute("INSERT OR IGNORE INTO meta VALUES ('version', '0')", []).map_err(error)?;
        Ok(())
    }

    pub fn meta(&self, clave: &str) -> Resultado<Option<String>> {
        let c = self.conectar()?;
        Self::meta_en(&c, clave)
    }

    pub fn meta_en(c: &Connection, clave: &str) -> Resultado<Option<String>> {
        let mut st = c.prepare_cached("SELECT valor FROM meta WHERE clave = ?").map_err(error)?;
        let mut filas = st.query(params![clave]).map_err(error)?;
        match filas.next().map_err(error)? {
            Some(f) => texto_de(f, 0).map_err(error),
            None => Ok(None),
        }
    }

    pub fn guardar_meta(&self, clave: &str, valor: &str) -> Resultado<()> {
        let c = self.conectar()?;
        Self::guardar_meta_en(&c, clave, valor)
    }

    pub fn guardar_meta_en(c: &Connection, clave: &str, valor: &str) -> Resultado<()> {
        c.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", params![clave, valor]).map_err(error)?;
        Ok(())
    }

    /// `int(self._meta("version", "0") or 0)`.
    pub fn version(&self) -> Resultado<i64> {
        Ok(self.meta("version")?.and_then(|v| v.trim().parse::<i64>().ok()).unwrap_or(0))
    }

    pub fn version_en(c: &Connection) -> Resultado<i64> {
        Ok(Self::meta_en(c, "version")?.and_then(|v| v.trim().parse::<i64>().ok()).unwrap_or(0))
    }

    pub fn invalidar_vectores(&self) {
        *self.vectores.lock().unwrap() = None;
    }

    /// `_cargar_vectores`: clave → vector (float32).
    pub fn cargar_vectores(&self) -> Resultado<Arc<HashMap<String, Vec<f32>>>> {
        let mut guardia = self.vectores.lock().unwrap();
        if let Some(v) = guardia.as_ref() {
            return Ok(v.clone());
        }
        let c = self.conectar()?;
        let mut st = c.prepare("SELECT clave, vector FROM vectores").map_err(error)?;
        let mut mapa = HashMap::new();
        let mut filas = st.query([]).map_err(error)?;
        while let Some(f) = filas.next().map_err(error)? {
            let clave: String = f.get(0).map_err(error)?;
            let blob: Vec<u8> = f.get(1).unwrap_or_default();
            let v: Vec<f32> = blob.chunks_exact(4).map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]])).collect();
            mapa.insert(clave, v);
        }
        let arc = Arc::new(mapa);
        *guardia = Some(arc.clone());
        Ok(arc)
    }

    /// Las rutas de los archivos (en el orden de la tabla).
    pub fn rutas(c: &Connection) -> Resultado<Vec<String>> {
        let mut st = c.prepare_cached("SELECT ruta FROM archivos").map_err(error)?;
        let v = st.query_map([], |f| f.get::<_, String>(0)).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
        Ok(v)
    }

    pub fn existe_db(&self) -> bool {
        Path::new(&self.ruta_db).exists()
    }
}
