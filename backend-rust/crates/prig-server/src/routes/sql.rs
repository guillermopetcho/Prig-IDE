use axum::{
    extract::Query,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use rusqlite::{types::ValueRef, Connection};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

fn obtener_directorio_sql() -> PathBuf {
    // Si existe el directorio de trabajo local, usamos .prig_sql ahí
    let local = PathBuf::from(".prig_sql");
    if local.exists() || fs::create_dir_all(&local).is_ok() {
        return local;
    }
    // Fallback a /tmp/.prig_sql
    let tmp = std::env::temp_dir().join(".prig_sql");
    let _ = fs::create_dir_all(&tmp);
    tmp
}

fn ruta_db(nombre_db: &str) -> PathBuf {
    let limpia = nombre_db
        .chars()
        .filter(|c| c.is_alphanumeric() || *c == '_' || *c == '-')
        .collect::<String>();
    let nombre = if limpia.is_empty() {
        "mysql_prig".to_string()
    } else {
        limpia
    };
    obtener_directorio_sql().join(format!("{}.db", nombre))
}

fn abrir_conexion(nombre_db: &str) -> Result<Connection, String> {
    let ruta = ruta_db(nombre_db);
    Connection::open(&ruta).map_err(|e| format!("ERROR 1049 (42000): Unknown database '{}' (detalles: {})", nombre_db, e))
}

#[derive(Serialize)]
pub struct BaseDatosItem {
    pub nombre: String,
    pub tablas_count: usize,
    pub tamano_bytes: u64,
    pub tamano_formato: String,
}

#[derive(Serialize)]
pub struct TablaItem {
    pub nombre: String,
    pub filas: usize,
    pub tamano_bytes: u64,
    pub motor: String,
    pub cotejamiento: String,
}

#[derive(Serialize)]
pub struct ColumnaSchemaItem {
    pub campo: String,
    pub tipo: String,
    pub nulo: String,
    pub clave: String,
    pub defecto: Option<String>,
    pub extra: String,
}

#[derive(Deserialize)]
pub struct QueryRequest {
    pub db: Option<String>,
    pub sql: String,
}

#[derive(Deserialize)]
pub struct ParametrosTabla {
    pub db: Option<String>,
    pub table: Option<String>,
}

#[derive(Deserialize)]
pub struct CrearDbRequest {
    pub nombre: String,
}

#[derive(Serialize)]
pub struct QueryResult {
    pub success: bool,
    pub database: String,
    pub query: String,
    pub columns: Vec<String>,
    pub column_types: Vec<String>,
    pub rows: Vec<Vec<serde_json::Value>>,
    pub total_rows: usize,
    pub affected_rows: usize,
    pub execution_time_ms: f64,
    pub message: String,
    pub error: Option<String>,
}

/// GET /api/sql/databases
pub async fn listar_bases_datos() -> Response {
    let dir = obtener_directorio_sql();
    let mut dbs = Vec::new();

    // Asegurar que al menos existe 'mysql_prig'
    let default_db_path = dir.join("mysql_prig.db");
    if !default_db_path.exists() {
        if let Ok(conn) = Connection::open(&default_db_path) {
            let _ = inicializar_tablas_ejemplo(&conn);
        }
    }

    if let Ok(entries) = fs::read_dir(&dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) == Some("db") {
                if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                    let metadata = entry.metadata().ok();
                    let tamano = metadata.map(|m| m.len()).unwrap_or(0);
                    let mut num_tablas = 0;
                    if let Ok(conn) = Connection::open(&path) {
                        let mut stmt = conn.prepare("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").ok();
                        if let Some(ref mut s) = stmt {
                            num_tablas = s.query_row([], |r| r.get::<_, i64>(0)).unwrap_or(0) as usize;
                        }
                    }
                    dbs.push(BaseDatosItem {
                        nombre: stem.to_string(),
                        tablas_count: num_tablas,
                        tamano_bytes: tamano,
                        tamano_formato: formato_tamano(tamano),
                    });
                }
            }
        }
    }

    // Ordenar alfabéticamente
    dbs.sort_by(|a, b| a.nombre.cmp(&b.nombre));

    Json(serde_json::json!({
        "success": true,
        "databases": dbs,
        "servidor": "MySQL 8.0.35-Prig-Rust (Protocol Compatible)",
        "host": "localhost:3306"
    })).into_response()
}

/// POST /api/sql/databases/create
pub async fn crear_base_datos(Json(req): Json<CrearDbRequest>) -> Response {
    let nombre = req.nombre.trim();
    if nombre.is_empty() {
        return (StatusCode::BAD_REQUEST, Json(serde_json::json!({
            "success": false,
            "error": "El nombre de la base de datos no puede estar vacío."
        }))).into_response();
    }
    let ruta = ruta_db(nombre);
    if ruta.exists() {
        return (StatusCode::CONFLICT, Json(serde_json::json!({
            "success": false,
            "error": format!("ERROR 1007 (HY000): Can't create database '{}'; database exists", nombre)
        }))).into_response();
    }
    match Connection::open(&ruta) {
        Ok(conn) => {
            let _ = conn.execute("CREATE TABLE IF NOT EXISTS _prig_meta (creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP)", []);
            Json(serde_json::json!({
                "success": true,
                "message": format!("Query OK, 1 row affected. Base de datos '{}' creada exitosamente.", nombre),
                "database": nombre
            })).into_response()
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({
            "success": false,
            "error": format!("No se pudo inicializar la base de datos: {}", e)
        }))).into_response(),
    }
}

/// GET /api/sql/tables?db=...
pub async fn listar_tablas(Query(params): Query<ParametrosTabla>) -> Response {
    let db_nombre = params.db.unwrap_or_else(|| "mysql_prig".to_string());
    let conn = match abrir_conexion(&db_nombre) {
        Ok(c) => c,
        Err(e) => return (StatusCode::BAD_REQUEST, Json(serde_json::json!({ "success": false, "error": e }))).into_response(),
    };

    let mut stmt = match conn.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_prig_%' ORDER BY name ASC") {
        Ok(s) => s,
        Err(e) => return (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({ "success": false, "error": e.to_string() }))).into_response(),
    };

    let nombres_tablas: Vec<String> = stmt.query_map([], |row| row.get(0)).map(|iter| iter.flatten().collect()).unwrap_or_default();

    let mut tablas = Vec::new();
    for t in nombres_tablas {
        let count_query = format!("SELECT count(*) FROM \"{}\"", t.replace('"', "\"\""));
        let filas = conn.query_row(&count_query, [], |r| r.get::<_, i64>(0)).unwrap_or(0) as usize;
        tablas.push(TablaItem {
            nombre: t,
            filas,
            tamano_bytes: (filas * 64) as u64, // Estimación
            motor: "InnoDB".to_string(),
            cotejamiento: "utf8mb4_unicode_ci".to_string(),
        });
    }

    Json(serde_json::json!({
        "success": true,
        "database": db_nombre,
        "tables": tablas,
        "total": tablas.len()
    })).into_response()
}

/// GET /api/sql/schema?db=...&table=...
pub async fn obtener_esquema(Query(params): Query<ParametrosTabla>) -> Response {
    let db_nombre = params.db.unwrap_or_else(|| "mysql_prig".to_string());
    let tabla_nombre = match params.table {
        Some(t) if !t.is_empty() => t,
        _ => return (StatusCode::BAD_REQUEST, Json(serde_json::json!({ "success": false, "error": "Debe especificar el parámetro 'table'" }))).into_response(),
    };

    let conn = match abrir_conexion(&db_nombre) {
        Ok(c) => c,
        Err(e) => return (StatusCode::BAD_REQUEST, Json(serde_json::json!({ "success": false, "error": e }))).into_response(),
    };

    let pragma_sql = format!("PRAGMA table_info(\"{}\")", tabla_nombre.replace('"', "\"\""));
    let mut stmt = match conn.prepare(&pragma_sql) {
        Ok(s) => s,
        Err(e) => return (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({ "success": false, "error": e.to_string() }))).into_response(),
    };

    let mut columnas = Vec::new();
    let rows_iter = stmt.query_map([], |row| {
        let name: String = row.get(1)?;
        let mut tipo: String = row.get(2)?;
        let notnull: i32 = row.get(3)?;
        let default_val: Option<String> = row.get(4)?;
        let pk: i32 = row.get(5)?;

        if tipo.is_empty() {
            tipo = "VARCHAR(255)".to_string();
        }

        let clave = if pk > 0 { "PRI".to_string() } else { "".to_string() };
        let nulo = if notnull == 0 { "YES".to_string() } else { "NO".to_string() };
        let extra = if pk == 1 && tipo.to_uppercase().contains("INT") {
            "auto_increment".to_string()
        } else {
            "".to_string()
        };

        Ok(ColumnaSchemaItem {
            campo: name,
            tipo,
            nulo,
            clave,
            defecto: default_val,
            extra,
        })
    });

    if let Ok(iter) = rows_iter {
        for c in iter.flatten() {
            columnas.push(c);
        }
    }

    // Obtener DDL CREATE TABLE si es posible
    let create_sql: Option<String> = conn.query_row(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?1",
        [&tabla_nombre],
        |r| r.get(0),
    ).ok();

    Json(serde_json::json!({
        "success": true,
        "database": db_nombre,
        "table": tabla_nombre,
        "columns": columnas,
        "create_table_sql": create_sql.unwrap_or_default()
    })).into_response()
}

/// POST /api/sql/query
pub async fn ejecutar_consulta(Json(req): Json<QueryRequest>) -> Response {
    let inicio = Instant::now();
    let db_nombre = req.db.unwrap_or_else(|| "mysql_prig".to_string());
    let sql_raw = req.sql.trim();

    if sql_raw.is_empty() {
        return (StatusCode::BAD_REQUEST, Json(QueryResult {
            success: false,
            database: db_nombre,
            query: String::new(),
            columns: vec![],
            column_types: vec![],
            rows: vec![],
            total_rows: 0,
            affected_rows: 0,
            execution_time_ms: 0.0,
            message: "Consulta vacía.".to_string(),
            error: Some("Consulta SQL vacía".to_string()),
        })).into_response();
    }

    let conn = match abrir_conexion(&db_nombre) {
        Ok(c) => c,
        Err(e) => {
            let dur = inicio.elapsed().as_secs_f64() * 1000.0;
            return (StatusCode::BAD_REQUEST, Json(QueryResult {
                success: false,
                database: db_nombre,
                query: sql_raw.to_string(),
                columns: vec![],
                column_types: vec![],
                rows: vec![],
                total_rows: 0,
                affected_rows: 0,
                execution_time_ms: dur,
                message: e.clone(),
                error: Some(e),
            })).into_response();
        }
    };

    // Procesar comandos de ayuda estilo MySQL
    let sql_upper = sql_raw.to_uppercase();
    let sql_trim_upper = sql_upper.trim_end_matches(';').trim();

    // 1. SHOW DATABASES / SHOW SCHEMAS
    if sql_trim_upper == "SHOW DATABASES" || sql_trim_upper == "SHOW SCHEMAS" {
        let dir = obtener_directorio_sql();
        let mut dbs = Vec::new();
        if let Ok(entries) = fs::read_dir(&dir) {
            for entry in entries.flatten() {
                if let Some(stem) = entry.path().file_stem().and_then(|s| s.to_str()) {
                    dbs.push(vec![serde_json::Value::String(stem.to_string())]);
                }
            }
        }
        let total = dbs.len();
        let dur = inicio.elapsed().as_secs_f64() * 1000.0;
        return Json(QueryResult {
            success: true,
            database: db_nombre,
            query: sql_raw.to_string(),
            columns: vec!["Database".to_string()],
            column_types: vec!["VARCHAR(64)".to_string()],
            rows: dbs,
            total_rows: total,
            affected_rows: 0,
            execution_time_ms: dur,
            message: format!("{} rows in set ({:.3} sec)", total, dur / 1000.0),
            error: None,
        }).into_response();
    }

    // 2. SHOW TABLES
    if sql_trim_upper == "SHOW TABLES" || sql_trim_upper.starts_with("SHOW TABLES FROM ") {
        let mut stmt = match conn.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_prig_%' ORDER BY name ASC") {
            Ok(s) => s,
            Err(e) => return error_response(&db_nombre, sql_raw, e.to_string(), inicio),
        };
        let rows: Vec<Vec<serde_json::Value>> = stmt.query_map([], |r| {
            let n: String = r.get(0)?;
            Ok(vec![serde_json::Value::String(n)])
        }).map(|it| it.flatten().collect()).unwrap_or_default();
        let total = rows.len();
        let col_name = format!("Tables_in_{}", db_nombre);
        let dur = inicio.elapsed().as_secs_f64() * 1000.0;
        return Json(QueryResult {
            success: true,
            database: db_nombre,
            query: sql_raw.to_string(),
            columns: vec![col_name],
            column_types: vec!["VARCHAR(64)".to_string()],
            rows,
            total_rows: total,
            affected_rows: 0,
            execution_time_ms: dur,
            message: format!("{} rows in set ({:.3} sec)", total, dur / 1000.0),
            error: None,
        }).into_response();
    }

    // 3. DESCRIBE <table> / DESC <table>
    if sql_trim_upper.starts_with("DESCRIBE ") || sql_trim_upper.starts_with("DESC ") {
        let parts: Vec<&str> = sql_trim_upper.split_whitespace().collect();
        if parts.len() >= 2 {
            let tabla = parts[1].trim_matches('`').trim_matches('"');
            let pragma_sql = format!("PRAGMA table_info(\"{}\")", tabla.replace('"', "\"\""));
            let mut stmt = match conn.prepare(&pragma_sql) {
                Ok(s) => s,
                Err(e) => return error_response(&db_nombre, sql_raw, e.to_string(), inicio),
            };
            let rows: Vec<Vec<serde_json::Value>> = stmt.query_map([], |row| {
                let name: String = row.get(1)?;
                let mut tipo: String = row.get(2)?;
                let notnull: i32 = row.get(3)?;
                let default_val: Option<String> = row.get(4)?;
                let pk: i32 = row.get(5)?;
                if tipo.is_empty() { tipo = "VARCHAR(255)".to_string(); }
                let clave = if pk > 0 { "PRI" } else { "" };
                let nulo = if notnull == 0 { "YES" } else { "NO" };
                let extra = if pk == 1 && tipo.to_uppercase().contains("INT") { "auto_increment" } else { "" };
                Ok(vec![
                    serde_json::Value::String(name),
                    serde_json::Value::String(tipo),
                    serde_json::Value::String(nulo.to_string()),
                    serde_json::Value::String(clave.to_string()),
                    default_val.map(serde_json::Value::String).unwrap_or(serde_json::Value::Null),
                    serde_json::Value::String(extra.to_string()),
                ])
            }).map(|it| it.flatten().collect()).unwrap_or_default();
            let total = rows.len();
            let dur = inicio.elapsed().as_secs_f64() * 1000.0;
            return Json(QueryResult {
                success: true,
                database: db_nombre,
                query: sql_raw.to_string(),
                columns: vec!["Field".into(), "Type".into(), "Null".into(), "Key".into(), "Default".into(), "Extra".into()],
                column_types: vec!["VARCHAR(64)".into(), "VARCHAR(64)".into(), "VARCHAR(3)".into(), "VARCHAR(3)".into(), "VARCHAR(64)".into(), "VARCHAR(32)".into()],
                rows,
                total_rows: total,
                affected_rows: 0,
                execution_time_ms: dur,
                message: format!("{} rows in set ({:.3} sec)", total, dur / 1000.0),
                error: None,
            }).into_response();
        }
    }

    // 4. Adaptar SQL con compatibilidad MySQL básica
    let sql_adaptado = adaptar_mysql_a_sqlite(sql_raw);

    // Determinar si es SELECT / PRAGMA / EXPLAIN (lectura) o DDL/DML (escritura)
    let es_select = sql_trim_upper.starts_with("SELECT")
        || sql_trim_upper.starts_with("PRAGMA")
        || sql_trim_upper.starts_with("EXPLAIN")
        || sql_trim_upper.starts_with("WITH");

    if es_select {
        match conn.prepare(&sql_adaptado) {
            Ok(mut stmt) => {
                let col_names: Vec<String> = stmt.column_names().into_iter().map(|s| s.to_string()).collect();
                let col_count = col_names.len();

                let mut rows_out = Vec::new();
                let mut rows_iter = match stmt.query([]) {
                    Ok(r) => r,
                    Err(e) => return error_response(&db_nombre, sql_raw, format!("ERROR 1064 (42000): {}", e), inicio),
                };

                while let Ok(Some(row)) = rows_iter.next() {
                    let mut row_vals = Vec::with_capacity(col_count);
                    for i in 0..col_count {
                        let val = match row.get_ref(i) {
                            Ok(ValueRef::Null) => serde_json::Value::Null,
                            Ok(ValueRef::Integer(n)) => serde_json::Value::Number(serde_json::Number::from(n)),
                            Ok(ValueRef::Real(f)) => serde_json::Number::from_f64(f)
                                .map(serde_json::Value::Number)
                                .unwrap_or(serde_json::Value::Null),
                            Ok(ValueRef::Text(t)) => serde_json::Value::String(String::from_utf8_lossy(t).to_string()),
                            Ok(ValueRef::Blob(b)) => serde_json::Value::String(format!("0x{}", hex::encode(b))),
                            Err(_) => serde_json::Value::Null,
                        };
                        row_vals.push(val);
                    }
                    rows_out.push(row_vals);
                    if rows_out.len() >= 1000 {
                        // Limitar resultados en memoria a 1000 filas por seguridad
                        break;
                    }
                }

                let total = rows_out.len();
                let dur = inicio.elapsed().as_secs_f64() * 1000.0;
                let col_types = vec!["TEXT".to_string(); col_count];

                Json(QueryResult {
                    success: true,
                    database: db_nombre,
                    query: sql_raw.to_string(),
                    columns: col_names,
                    column_types: col_types,
                    rows: rows_out,
                    total_rows: total,
                    affected_rows: 0,
                    execution_time_ms: dur,
                    message: format!("{} row{} in set ({:.3} sec)", total, if total == 1 { "" } else { "s" }, dur / 1000.0),
                    error: None,
                }).into_response()
            }
            Err(e) => error_response(&db_nombre, sql_raw, format!("ERROR 1064 (42000): {}", e), inicio),
        }
    } else {
        // Ejecución de sentencias múltiples (CREATE, INSERT, UPDATE, DELETE, DROP...)
        match conn.execute_batch(&sql_adaptado) {
            Ok(_) => {
                let affected = conn.changes() as usize;
                let dur = inicio.elapsed().as_secs_f64() * 1000.0;
                Json(QueryResult {
                    success: true,
                    database: db_nombre,
                    query: sql_raw.to_string(),
                    columns: vec![],
                    column_types: vec![],
                    rows: vec![],
                    total_rows: 0,
                    affected_rows: affected,
                    execution_time_ms: dur,
                    message: format!("Query OK, {} row{} affected ({:.3} sec)", affected, if affected == 1 { "" } else { "s" }, dur / 1000.0),
                    error: None,
                }).into_response()
            }
            Err(e) => error_response(&db_nombre, sql_raw, format!("ERROR 1064 (42000): {}", e), inicio),
        }
    }
}

fn error_response(db: &str, query: &str, error_msg: String, inicio: Instant) -> Response {
    let dur = inicio.elapsed().as_secs_f64() * 1000.0;
    (StatusCode::OK, Json(QueryResult {
        success: false,
        database: db.to_string(),
        query: query.to_string(),
        columns: vec![],
        column_types: vec![],
        rows: vec![],
        total_rows: 0,
        affected_rows: 0,
        execution_time_ms: dur,
        message: error_msg.clone(),
        error: Some(error_msg),
    })).into_response()
}

/// Adapta peculiaridades de sintaxis MySQL comunes a SQLite
fn adaptar_mysql_a_sqlite(sql: &str) -> String {
    let mut s = sql.to_string();
    // Reemplazos de tipos y modificadores comunes
    s = s.replace("AUTO_INCREMENT", "AUTOINCREMENT");
    s = s.replace("auto_increment", "AUTOINCREMENT");
    s = s.replace("ENGINE=InnoDB", "");
    s = s.replace("engine=innodb", "");
    s = s.replace("DEFAULT CHARSET=utf8mb4", "");
    s = s.replace("COLLATE=utf8mb4_unicode_ci", "");
    s = s.replace("UNSIGNED", "");
    s = s.replace("unsigned", "");
    s = s.replace("NOW()", "CURRENT_TIMESTAMP");
    s = s.replace("now()", "CURRENT_TIMESTAMP");
    s
}

/// POST /api/sql/seed
pub async fn sembrar_datos_ejemplo(Json(req): Json<QueryRequest>) -> Response {
    let db_nombre = req.db.unwrap_or_else(|| "mysql_prig".to_string());
    match abrir_conexion(&db_nombre) {
        Ok(conn) => {
            if let Err(e) = inicializar_tablas_ejemplo(&conn) {
                return (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({ "success": false, "error": e }))).into_response();
            }
            Json(serde_json::json!({
                "success": true,
                "message": "Tablas de ejemplo MySQL (usuarios, productos, pedidos, logs_actividad, metricas_ia) sembradas exitosamente.",
                "database": db_nombre
            })).into_response()
        }
        Err(e) => (StatusCode::BAD_REQUEST, Json(serde_json::json!({ "success": false, "error": e }))).into_response(),
    }
}

fn inicializar_tablas_ejemplo(conn: &Connection) -> Result<(), String> {
    let script = r#"
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(50) NOT NULL UNIQUE,
        email VARCHAR(100) NOT NULL UNIQUE,
        rol VARCHAR(20) DEFAULT 'desarrollador',
        activo BOOLEAN DEFAULT 1,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku VARCHAR(30) NOT NULL UNIQUE,
        nombre VARCHAR(120) NOT NULL,
        categoria VARCHAR(50) NOT NULL,
        precio DECIMAL(10,2) NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0,
        estado VARCHAR(20) DEFAULT 'disponible'
    );

    CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        total DECIMAL(10,2) NOT NULL,
        estado VARCHAR(20) DEFAULT 'pendiente',
        fecha_pedido TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS metricas_ia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        modelo VARCHAR(50) NOT NULL,
        prompt_tokens INTEGER NOT NULL,
        completion_tokens INTEGER NOT NULL,
        latencia_ms REAL NOT NULL,
        fecha_inferencia TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS logs_actividad (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario VARCHAR(50) NOT NULL,
        accion VARCHAR(80) NOT NULL,
        ip VARCHAR(45) DEFAULT '127.0.0.1',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Insertar registros iniciales si las tablas están vacías
    INSERT OR IGNORE INTO usuarios (id, username, email, rol, activo) VALUES 
        (1, 'admin', 'admin@prig.local', 'administrador', 1),
        (2, 'alex_mercer', 'alex@cyber.org', 'desarrollador', 1),
        (3, 'sarah_connor', 'sarah@sky.net', 'seguridad', 1),
        (4, 'turing_alan', 'alan@bletchley.ac.uk', 'cientifico_datos', 1),
        (5, 'ada_lovelace', 'ada@analytical.io', 'arquitecto', 1);

    INSERT OR IGNORE INTO productos (id, sku, nombre, categoria, precio, stock, estado) VALUES
        (1, 'GPU-RTX4090', 'NVIDIA GeForce RTX 4090 24GB', 'Hardware', 1899.99, 12, 'disponible'),
        (2, 'CPU-RYZEN9', 'AMD Ryzen 9 7950X 16-Core', 'Hardware', 599.00, 24, 'disponible'),
        (3, 'RAM-DDR5-64', 'Corsair Vengeance 64GB DDR5 6000MHz', 'Memoria', 249.50, 45, 'disponible'),
        (4, 'SSD-NVME-4TB', 'Samsung 990 Pro 4TB PCIe 4.0 M.2', 'Almacenamiento', 329.99, 30, 'disponible'),
        (5, 'MOD-QWEN7B', 'Suscripción Cluster Inferencia Qwen 7B', 'Servicios IA', 49.00, 999, 'disponible');

    INSERT OR IGNORE INTO pedidos (id, usuario_id, total, estado) VALUES
        (1, 2, 2498.99, 'completado'),
        (2, 4, 329.99, 'enviado'),
        (3, 5, 2149.49, 'procesando'),
        (4, 3, 599.00, 'pendiente');

    INSERT OR IGNORE INTO metricas_ia (id, modelo, prompt_tokens, completion_tokens, latencia_ms) VALUES
        (1, 'qwen2.5-coder:7b', 1240, 312, 142.5),
        (2, 'qwen2.5-coder:7b', 450, 120, 58.2),
        (3, 'deepseek-r1:8b', 2048, 512, 340.1),
        (4, 'llama3.2:3b', 800, 240, 89.0);

    INSERT OR IGNORE INTO logs_actividad (id, usuario, accion, ip) VALUES
        (1, 'admin', 'LOGIN_EXITOSO', '192.168.1.10'),
        (2, 'alex_mercer', 'DESAFIO_COMPLETADO_PYTHON', '127.0.0.1'),
        (3, 'sarah_connor', 'AUDITORIA_SEGURIDAD_MODULOS', '10.0.0.5'),
        (4, 'ada_lovelace', 'PIPELINE_DESPLIEGUE_RUST', '172.16.0.4');
    "#;

    conn.execute_batch(script)
        .map_err(|e| format!("Error sembrando tablas de ejemplo: {}", e))
}

fn formato_tamano(bytes: u64) -> String {
    if bytes < 1024 {
        format!("{} B", bytes)
    } else if bytes < 1024 * 1024 {
        format!("{:.1} KB", bytes as f64 / 1024.0)
    } else {
        format!("{:.1} MB", bytes as f64 / (1024.0 * 1024.0))
    }
}

// Helper simple para codificar bytes a hexadecimal sin dependencias pesadas
mod hex {
    pub fn encode(data: &[u8]) -> String {
        let mut s = String::with_capacity(data.len() * 2);
        for &b in data {
            s.push_str(&format!("{:02x}", b));
        }
        s
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mysql_dialect_translation() {
        assert_eq!(adaptar_mysql_a_sqlite("INT AUTO_INCREMENT"), "INT AUTOINCREMENT");
        assert_eq!(adaptar_mysql_a_sqlite("SELECT NOW()"), "SELECT CURRENT_TIMESTAMP");
        assert_eq!(adaptar_mysql_a_sqlite("ENGINE=InnoDB").trim(), "");
    }

    #[test]
    fn test_seeding_and_query() {
        let conn = Connection::open_in_memory().unwrap();
        let seed_res = inicializar_tablas_ejemplo(&conn);
        assert!(seed_res.is_ok());

        let count: i64 = conn.query_row("SELECT count(*) FROM usuarios", [], |r| r.get(0)).unwrap();
        assert_eq!(count, 5);

        let prod_count: i64 = conn.query_row("SELECT count(*) FROM productos", [], |r| r.get(0)).unwrap();
        assert_eq!(prod_count, 5);
    }
}


