//! El estudio SQL (`sql_service.py`): bases SQLite en `.prig_sql/` con el dialecto de MySQL por encima (`SHOW
//! DATABASES`, `SHOW TABLES`, `DESCRIBE`, `AUTO_INCREMENT`…), listar bases y tablas, el esquema, consultar y sembrar
//! datos de ejemplo. Las respuestas son las de Python, clave a clave (la interfaz lee `nombre` al crear una base).

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::Instant;

use axum::{
    body::Bytes,
    extract::Query,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};
use rusqlite::{types::ValueRef, Connection};

use crate::routes::{cuerpo, detalle, json_py};

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

/// `obtener_directorio_sql`: `.prig_sql` en el directorio actual (o en /tmp si no se puede)
fn directorio() -> PathBuf {
    let local = prig_plataforma::py::abspath(".prig_sql");
    if std::fs::create_dir_all(&local).is_ok() {
        return PathBuf::from(local);
    }
    let tmp = PathBuf::from("/tmp/.prig_sql");
    let _ = std::fs::create_dir_all(&tmp);
    tmp
}

fn limpiar(n: &str) -> String {
    n.chars().filter(|c| c.is_alphanumeric() || *c == '_' || *c == '-').collect()
}

fn ruta_db(nombre: &str) -> PathBuf {
    let l = limpiar(nombre);
    directorio().join(format!("{}.db", if l.is_empty() { "mysql_prig" } else { &l }))
}

fn tamano(b: u64) -> String {
    if b < 1024 {
        format!("{b} B")
    } else if b < 1024 * 1024 {
        format!("{:.1} KB", b as f64 / 1024.0)
    } else {
        format!("{:.1} MB", b as f64 / (1024.0 * 1024.0))
    }
}

fn abrir(r: &std::path::Path) -> Result<Connection, String> {
    Connection::open(r).map_err(|e| e.to_string())
}

/// `listar_bases_datos`
fn bases() -> Result<Vec<Valor>, String> {
    let dir = directorio();
    let defecto = ruta_db("mysql_prig");
    if !defecto.exists() {
        abrir(&defecto)?;
    }
    let mut v: Vec<(String, Mapa)> = Vec::new();
    for e in std::fs::read_dir(&dir).map_err(|e| e.to_string())?.flatten() {
        let f = e.file_name().to_string_lossy().to_string();
        let Some(stem) = f.strip_suffix(".db") else { continue };
        let p = dir.join(&f);
        let t = std::fs::metadata(&p).map(|m| m.len()).unwrap_or(0);
        let n: i64 = abrir(&p).ok().and_then(|c| c.query_row("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'", [], |f| f.get(0)).ok()).unwrap_or(0);
        v.push((stem.to_string(), Mapa::new().con("nombre", stem).con("tablas_count", n).con("tamano_bytes", t as i64).con("tamano_formato", tamano(t))));
    }
    v.sort_by(|a, b| a.0.cmp(&b.0));
    Ok(v.into_iter().map(|(_, m)| Valor::Mapa(m)).collect())
}

fn tablas(db: &str) -> Result<Vec<Mapa>, String> {
    let r = ruta_db(db);
    if !r.exists() {
        return Err(format!("Unknown database '{db}'"));
    }
    let c = abrir(&r)?;
    let nombres: Vec<String> = c
        .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_prig_%' ORDER BY name ASC")
        .and_then(|mut s| s.query_map([], |f| f.get(0))?.collect())
        .map_err(|e| e.to_string())?;
    Ok(nombres
        .into_iter()
        .map(|t| {
            let filas: i64 = c.query_row(&format!("SELECT count(*) FROM \"{}\"", t.replace('"', "\"\"")), [], |f| f.get(0)).unwrap_or(0);
            Mapa::new().con("nombre", t.as_str()).con("filas", filas).con("tamano_bytes", filas * 64).con("motor", "InnoDB").con("cotejamiento", "utf8mb4_unicode_ci")
        })
        .collect())
}

fn valor(v: ValueRef<'_>) -> Result<Valor, ()> {
    Ok(match v {
        ValueRef::Null => Valor::Nulo,
        ValueRef::Integer(n) => Valor::Entero(n as i128),
        ValueRef::Real(r) => Valor::Real(r),
        ValueRef::Text(t) => Valor::Texto(String::from_utf8_lossy(t).into_owned()),
        // `bytes` no se puede pasar a JSON: en Python, un 500
        ValueRef::Blob(_) => return Err(()),
    })
}

fn esquema(db: &str, tabla: &str) -> Result<Mapa, String> {
    let r = ruta_db(db);
    if !r.exists() {
        return Err(format!("Unknown database '{db}'"));
    }
    let c = abrir(&r)?;
    let mut st = c.prepare(&format!("PRAGMA table_info(\"{}\")", tabla.replace('"', "\"\""))).map_err(|e| e.to_string())?;
    let cols: Vec<Valor> = st
        .query_map([], |f| {
            let tipo: String = f.get::<_, Option<String>>(2)?.filter(|t| !t.is_empty()).unwrap_or_else(|| "VARCHAR(255)".into());
            let pk: i64 = f.get(5)?;
            Ok(Valor::Mapa(
                Mapa::new()
                    .con("campo", f.get::<_, String>(1)?)
                    .con("tipo", tipo.as_str())
                    .con("nulo", if f.get::<_, i64>(3)? != 0 { "NO" } else { "YES" })
                    .con("clave", if pk > 0 { "PRI" } else { "" })
                    .con("defecto", valor(f.get_ref(4)?).unwrap_or(Valor::Nulo))
                    .con("extra", if pk == 1 && tipo.to_uppercase().contains("INT") { "auto_increment" } else { "" }),
            ))
        })
        .and_then(|r| r.collect())
        .map_err(|e| e.to_string())?;
    let sql: String = c.query_row("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", [tabla], |f| f.get::<_, Option<String>>(0)).ok().flatten().unwrap_or_default();
    Ok(Mapa::new().con("success", true).con("database", db).con("table", tabla).con("columns", Valor::Lista(cols)).con("create_table_sql", sql))
}

/// `adaptar_mysql_a_sqlite`
fn adaptar(sql: &str) -> String {
    static R: OnceLock<Vec<(regex::Regex, &'static str)>> = OnceLock::new();
    let r = R.get_or_init(|| {
        [
            (r"(?i)\bAUTO_INCREMENT\b", "AUTOINCREMENT"),
            (r"(?i)\bENGINE\s*=\s*[a-zA-Z0-9_]+", ""),
            (r"(?i)\bDEFAULT\s+CHARSET\s*=\s*[a-zA-Z0-9_]+", ""),
            (r"(?i)\bCOLLATE\s*=\s*[a-zA-Z0-9_]+", ""),
            (r"(?i)\bUNSIGNED\b", ""),
            (r"(?i)\bNOW\(\)", "CURRENT_TIMESTAMP"),
        ]
        .iter()
        .map(|(p, s)| (regex::Regex::new(p).unwrap(), *s))
        .collect()
    });
    let mut s = sql.to_string();
    for (re, por) in r {
        s = re.replace_all(&s, *por).into_owned();
    }
    s
}

fn respuesta(db: &str, query: &str, columnas: Vec<Valor>, tipos: Vec<Valor>, filas: Vec<Valor>, afectadas: i64, ms: f64, mensaje: String, error: Valor, ok: bool) -> Mapa {
    Mapa::new()
        .con("success", ok)
        .con("database", db)
        .con("query", query)
        .con("columns", Valor::Lista(columnas))
        .con("column_types", Valor::Lista(tipos))
        .con("total_rows", filas.len() as i64)
        .con("rows", Valor::Lista(filas))
        .con("affected_rows", afectadas)
        .con("execution_time_ms", ms)
        .con("message", mensaje)
        .con("error", error)
}

/// `rows` va antes que `total_rows` en Python
fn ordenar(m: Mapa) -> Mapa {
    let mut s = Mapa::new();
    for k in ["success", "database", "query", "columns", "column_types", "rows", "total_rows", "affected_rows", "execution_time_ms", "message", "error"] {
        s.poner(k, m.get(k).cloned().unwrap_or(Valor::Nulo));
    }
    s
}

fn textos(v: &[&str]) -> Vec<Valor> {
    v.iter().map(|t| Valor::Texto(t.to_string())).collect()
}

/// `ejecutar_consulta`; Err para lo que Python deja escapar (un 500)
fn consulta(db: Option<&str>, sql: &str) -> Result<Mapa, String> {
    let inicio = Instant::now();
    let ms = || inicio.elapsed().as_secs_f64() * 1000.0;
    let db = db.filter(|d| !d.is_empty()).unwrap_or("mysql_prig");
    let crudo = prig_plataforma::py::strip(sql).to_string();
    if crudo.is_empty() {
        return Ok(ordenar(respuesta(db, "", vec![], vec![], vec![], 0, 0.0, "Consulta vacía.".into(), Valor::Texto("Consulta SQL vacía".into()), false)));
    }
    let ruta = ruta_db(db);
    let mayus = prig_plataforma::py::strip(crudo.to_uppercase().trim_end_matches(';')).to_string();
    let en = |n: usize, d: f64| format!("{n} rows in set ({:.3} sec)", d / 1000.0);
    if mayus == "SHOW DATABASES" || mayus == "SHOW SCHEMAS" {
        let f: Vec<Valor> = bases()?.into_iter().map(|d| if let Valor::Mapa(d) = d { Valor::Lista(vec![d.valor("nombre").clone()]) } else { d }).collect();
        let d = ms();
        let n = f.len();
        return Ok(ordenar(respuesta(db, &crudo, textos(&["Database"]), textos(&["VARCHAR(64)"]), f, 0, d, en(n, d), Valor::Nulo, true)));
    }
    if mayus == "SHOW TABLES" || mayus.starts_with("SHOW TABLES FROM ") {
        let f: Vec<Valor> = tablas(db)?.into_iter().map(|t| Valor::Lista(vec![t.valor("nombre").clone()])).collect();
        let d = ms();
        let n = f.len();
        return Ok(ordenar(respuesta(db, &crudo, vec![Valor::Texto(format!("Tables_in_{db}"))], textos(&["VARCHAR(64)"]), f, 0, d, en(n, d), Valor::Nulo, true)));
    }
    if mayus.starts_with("DESCRIBE ") || mayus.starts_with("DESC ") {
        if let Some(t) = mayus.split_whitespace().nth(1) {
            let tbl = t.trim_matches(|c| c == '`' || c == '"' || c == '\'');
            let e = esquema(db, tbl)?;
            let f: Vec<Valor> = e
                .lista("columns")
                .unwrap_or(&[])
                .iter()
                .filter_map(|c| if let Valor::Mapa(c) = c { Some(Valor::Lista(["campo", "tipo", "nulo", "clave", "defecto", "extra"].iter().map(|k| c.valor(k).clone()).collect())) } else { None })
                .collect();
            let d = ms();
            let n = f.len();
            return Ok(ordenar(respuesta(
                db,
                &crudo,
                textos(&["Field", "Type", "Null", "Key", "Default", "Extra"]),
                textos(&["VARCHAR(64)", "VARCHAR(64)", "VARCHAR(3)", "VARCHAR(3)", "VARCHAR(64)", "VARCHAR(32)"]),
                f,
                0,
                d,
                en(n, d),
                Valor::Nulo,
                true,
            )));
        }
    }
    let adaptado = adaptar(&crudo);
    let es_select = ["SELECT", "PRAGMA", "EXPLAIN", "WITH"].iter().any(|p| mayus.starts_with(p));
    let r = (|| -> Result<(Vec<Valor>, Vec<Valor>), rusqlite::Error> {
        let c = Connection::open(&ruta)?;
        if es_select {
            let mut st = c.prepare(&adaptado)?;
            let cols: Vec<Valor> = st.column_names().iter().map(|n| Valor::Texto(n.to_string())).collect();
            let n = cols.len();
            let mut filas = Vec::new();
            let mut q = st.query([])?;
            while let Some(f) = q.next()? {
                let mut fila = Vec::with_capacity(n);
                for i in 0..n {
                    fila.push(valor(f.get_ref(i)?).map_err(|_| rusqlite::Error::InvalidQuery)?);
                }
                filas.push(Valor::Lista(fila));
            }
            Ok((cols, filas))
        } else {
            c.execute_batch(&adaptado)?;
            Ok((Vec::new(), Vec::new()))
        }
    })();
    let d = ms();
    Ok(ordenar(match r {
        Ok((cols, filas)) if es_select => {
            let n = filas.len();
            let tipos = vec![Valor::Texto("TEXT".into()); cols.len()];
            respuesta(db, &crudo, cols, tipos, filas, 0, d, en(n, d), Valor::Nulo, true)
        }
        Ok(_) => respuesta(db, &crudo, vec![], vec![], vec![], 0, d, format!("Query OK, 0 row(s) affected ({:.3} sec)", d / 1000.0), Valor::Nulo, true),
        Err(rusqlite::Error::InvalidQuery) => return Err("bytes".into()),
        Err(e) => {
            let t = match &e {
                // el error de sintaxis trae aparte el SQL y la posición: el mensaje de Python es solo `msg`
                rusqlite::Error::SqlInputError { msg, .. } => msg.clone(),
                // el SQLite empaquetado (más nuevo que el de Python) añade «in <sql> at offset N»
                rusqlite::Error::SqliteFailure(_, Some(m)) => match (m.find(" in "), m.rfind(" at offset ")) {
                    (Some(i), Some(j)) if j > i && m[j + 11..].chars().all(|c| c.is_ascii_digit()) => m[..i].to_string(),
                    _ => m.clone(),
                },
                otro => otro.to_string(),
            };
            respuesta(db, &crudo, vec![], vec![], vec![], 0, d, format!("ERROR 1064 (42000): {t}"), Valor::Texto(t), false)
        }
    }))
}

const SEMILLA: &str = include_str!("sql_semilla.sql");

async fn en_hilo<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| error_500())
}

/// `GET /api/sql/databases`
pub async fn listar_bases_datos() -> Response {
    en_hilo(|| match bases() {
        Ok(b) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("success", true).con("databases", Valor::Lista(b)))),
        Err(e) => detalle(StatusCode::INTERNAL_SERVER_ERROR, e),
    })
    .await
}

/// `POST /api/sql/databases/create` (`nombre`)
pub async fn crear_base_datos(b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("nombre", &Tipo::Texto, true)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        let l = limpiar(&c.valor("nombre").texto_py());
        if l.is_empty() {
            return detalle(StatusCode::BAD_REQUEST, "Nombre de base de datos inválido");
        }
        let r = ruta_db(&l);
        if r.exists() {
            return json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("success", true).con("created", false).con("nombre", l.as_str()).con("message", format!("Database '{l}' already exists"))));
        }
        match abrir(&r) {
            Ok(_) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("success", true).con("created", true).con("nombre", l.as_str()).con("message", format!("Database '{l}' created successfully")))),
            Err(e) => detalle(StatusCode::BAD_REQUEST, e),
        }
    })
    .await
}

/// `GET /api/sql/tables?db=`
pub async fn listar_tablas(Query(q): Query<HashMap<String, String>>) -> Response {
    en_hilo(move || {
        let db = q.get("db").filter(|d| !d.is_empty()).cloned().unwrap_or_else(|| "mysql_prig".into());
        match tablas(&db) {
            Ok(t) => {
                let n = t.len() as i64;
                json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("success", true).con("database", db.as_str()).con("tables", Valor::Lista(t.into_iter().map(Valor::Mapa).collect())).con("total", n)))
            }
            Err(e) => detalle(StatusCode::BAD_REQUEST, e),
        }
    })
    .await
}

/// `GET /api/sql/schema?db=&table=`
pub async fn obtener_esquema(Query(q): Query<HashMap<String, String>>) -> Response {
    en_hilo(move || {
        let Some(tabla) = q.get("table").filter(|t| !t.is_empty()).cloned() else { return detalle(StatusCode::BAD_REQUEST, "Parámetro 'table' es requerido") };
        let db = q.get("db").filter(|d| !d.is_empty()).cloned().unwrap_or_else(|| "mysql_prig".into());
        match esquema(&db, &tabla) {
            Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
            Err(e) => detalle(StatusCode::BAD_REQUEST, e),
        }
    })
    .await
}

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);

/// `POST /api/sql/query` (`db`, `sql`)
pub async fn ejecutar_consulta(b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("db", &TEXTO_OPC, false), ("sql", &Tipo::Texto, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        let db = c.get("db").filter(|d| !d.es_nulo()).map(Valor::texto_py);
        match consulta(db.as_deref(), &c.get("sql").map(Valor::texto_py).unwrap_or_default()) {
            Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
            Err(e) if e == "bytes" => error_500(),
            Err(e) => detalle(StatusCode::INTERNAL_SERVER_ERROR, e),
        }
    })
    .await
}

/// `POST /api/sql/seed` (`db`): las tablas de ejemplo
pub async fn sembrar_datos_ejemplo(b: Bytes) -> Response {
    let db = if b.iter().all(|c| c.is_ascii_whitespace()) {
        None
    } else {
        match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("db", &TEXTO_OPC, false), ("sql", &Tipo::Texto, false)])) {
            Ok(c) => c.get("db").filter(|d| d.verdad()).map(Valor::texto_py),
            Err(r) => return r,
        }
    };
    en_hilo(move || {
        let db = db.unwrap_or_else(|| "mysql_prig".into());
        match abrir(&ruta_db(&db)).and_then(|c| c.execute_batch(SEMILLA).map_err(|e| e.to_string())) {
            Ok(()) => json_py(
                StatusCode::OK,
                &Valor::Mapa(
                    Mapa::new()
                        .con("success", true)
                        .con("message", "Tablas de ejemplo MySQL (usuarios, productos, pedidos, logs_actividad, metricas_ia) sembradas exitosamente.")
                        .con("database", db.as_str()),
                ),
            ),
            Err(e) => detalle(StatusCode::INTERNAL_SERVER_ERROR, e),
        }
    })
    .await
}
