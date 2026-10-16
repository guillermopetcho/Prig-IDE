"""
Servicio SQL para Prig IDE (Compatibilidad y fallback Python / motor SQLite con dialecto MySQL)
Equivalente y respaldo del módulo Rust en backend-rust/crates/prig-server/src/routes/sql.rs
"""

import os
import re
import time
import sqlite3
from typing import Dict, Any, List, Optional

def obtener_directorio_sql() -> str:
    local = os.path.abspath(".prig_sql")
    try:
        os.makedirs(local, exist_ok=True)
        return local
    except Exception:
        tmp = os.path.join("/tmp", ".prig_sql")
        os.makedirs(tmp, exist_ok=True)
        return tmp

def ruta_db(nombre_db: str) -> str:
    limpia = "".join(c for c in (nombre_db or "") if c.isalnum() or c in ("_", "-"))
    if not limpia:
        limpia = "mysql_prig"
    return os.path.join(obtener_directorio_sql(), f"{limpia}.db")

def formato_tamano(bytes_cant: int) -> str:
    if bytes_cant < 1024:
        return f"{bytes_cant} B"
    elif bytes_cant < 1024 * 1024:
        return f"{bytes_cant / 1024.0:.1f} KB"
    else:
        return f"{bytes_cant / (1024.0 * 1024.0):.1f} MB"

def listar_bases_datos() -> List[Dict[str, Any]]:
    directorio = obtener_directorio_sql()
    # Asegurar base por defecto
    ruta_default = ruta_db("mysql_prig")
    if not os.path.exists(ruta_default):
        conn = sqlite3.connect(ruta_default)
        conn.close()

    dbs = []
    if os.path.exists(directorio):
        for f in os.listdir(directorio):
            if f.endswith(".db"):
                stem = f[:-3]
                path = os.path.join(directorio, f)
                tamano = os.path.getsize(path) if os.path.exists(path) else 0
                num_tablas = 0
                try:
                    conn = sqlite3.connect(path)
                    cur = conn.cursor()
                    cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                    row = cur.fetchone()
                    if row:
                        num_tablas = row[0]
                    conn.close()
                except Exception:
                    pass
                dbs.append({
                    "nombre": stem,
                    "tablas_count": num_tablas,
                    "tamano_bytes": tamano,
                    "tamano_formato": formato_tamano(tamano)
                })
    dbs.sort(key=lambda x: x["nombre"])
    return dbs

def crear_base_datos(nombre: str) -> Dict[str, Any]:
    limpia = "".join(c for c in (nombre or "") if c.isalnum() or c in ("_", "-"))
    if not limpia:
        raise ValueError("Nombre de base de datos inválido")
    ruta = ruta_db(limpia)
    if os.path.exists(ruta):
        return {"success": True, "created": False, "nombre": limpia, "message": f"Database '{limpia}' already exists"}
    conn = sqlite3.connect(ruta)
    conn.close()
    return {"success": True, "created": True, "nombre": limpia, "message": f"Database '{limpia}' created successfully"}

def listar_tablas(db: str) -> List[Dict[str, Any]]:
    ruta = ruta_db(db)
    if not os.path.exists(ruta):
        raise ValueError(f"Unknown database '{db}'")
    conn = sqlite3.connect(ruta)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_prig_%' ORDER BY name ASC")
    tablas_names = [row[0] for row in cur.fetchall()]
    tablas = []
    for t in tablas_names:
        filas = 0
        try:
            t_escaped = t.replace('"', '""')
            cur.execute(f'SELECT count(*) FROM "{t_escaped}"')
            r = cur.fetchone()
            if r:
                filas = r[0]
        except Exception:
            pass
        tablas.append({
            "nombre": t,
            "filas": filas,
            "tamano_bytes": filas * 64,
            "motor": "InnoDB",
            "cotejamiento": "utf8mb4_unicode_ci"
        })
    conn.close()
    return tablas

def obtener_esquema(db: str, tabla: str) -> Dict[str, Any]:
    ruta = ruta_db(db)
    if not os.path.exists(ruta):
        raise ValueError(f"Unknown database '{db}'")
    conn = sqlite3.connect(ruta)
    cur = conn.cursor()
    tabla_escaped = tabla.replace('"', '""')
    pragma = f'PRAGMA table_info("{tabla_escaped}")'
    cur.execute(pragma)
    cols = cur.fetchall()
    columnas = []
    for row in cols:
        name = row[1]
        tipo = row[2] or "VARCHAR(255)"
        notnull = row[3]
        default_val = row[4]
        pk = row[5]
        columnas.append({
            "campo": name,
            "tipo": tipo,
            "nulo": "NO" if notnull else "YES",
            "clave": "PRI" if pk > 0 else "",
            "defecto": default_val,
            "extra": "auto_increment" if pk == 1 and "INT" in tipo.upper() else ""
        })
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tabla,))
    create_sql = cur.fetchone()
    conn.close()
    return {
        "success": True,
        "database": db,
        "table": tabla,
        "columns": columnas,
        "create_table_sql": create_sql[0] if create_sql else ""
    }

def adaptar_mysql_a_sqlite(sql: str) -> str:
    s = sql
    s = re.sub(r'(?i)\bAUTO_INCREMENT\b', 'AUTOINCREMENT', s)
    s = re.sub(r'(?i)\bENGINE\s*=\s*[a-zA-Z0-9_]+', '', s)
    s = re.sub(r'(?i)\bDEFAULT\s+CHARSET\s*=\s*[a-zA-Z0-9_]+', '', s)
    s = re.sub(r'(?i)\bCOLLATE\s*=\s*[a-zA-Z0-9_]+', '', s)
    s = re.sub(r'(?i)\bUNSIGNED\b', '', s)
    s = re.sub(r'(?i)\bNOW\(\)', 'CURRENT_TIMESTAMP', s)
    return s

def ejecutar_consulta(db: str, sql: str) -> Dict[str, Any]:
    inicio = time.time()
    db_nombre = db or "mysql_prig"
    sql_raw = (sql or "").strip()
    if not sql_raw:
        return {
            "success": False,
            "database": db_nombre,
            "query": "",
            "columns": [],
            "column_types": [],
            "rows": [],
            "total_rows": 0,
            "affected_rows": 0,
            "execution_time_ms": 0.0,
            "message": "Consulta vacía.",
            "error": "Consulta SQL vacía"
        }

    ruta = ruta_db(db_nombre)
    sql_upper = sql_raw.upper().rstrip(";").strip()

    # SHOW DATABASES
    if sql_upper in ("SHOW DATABASES", "SHOW SCHEMAS"):
        dbs = [[d["nombre"]] for d in listar_bases_datos()]
        dur = (time.time() - inicio) * 1000.0
        return {
            "success": True,
            "database": db_nombre,
            "query": sql_raw,
            "columns": ["Database"],
            "column_types": ["VARCHAR(64)"],
            "rows": dbs,
            "total_rows": len(dbs),
            "affected_rows": 0,
            "execution_time_ms": dur,
            "message": f"{len(dbs)} rows in set ({dur / 1000.0:.3f} sec)",
            "error": None
        }

    # SHOW TABLES
    if sql_upper == "SHOW TABLES" or sql_upper.startswith("SHOW TABLES FROM "):
        tablas = [[t["nombre"]] for t in listar_tablas(db_nombre)]
        dur = (time.time() - inicio) * 1000.0
        return {
            "success": True,
            "database": db_nombre,
            "query": sql_raw,
            "columns": [f"Tables_in_{db_nombre}"],
            "column_types": ["VARCHAR(64)"],
            "rows": tablas,
            "total_rows": len(tablas),
            "affected_rows": 0,
            "execution_time_ms": dur,
            "message": f"{len(tablas)} rows in set ({dur / 1000.0:.3f} sec)",
            "error": None
        }

    # DESCRIBE <table>
    if sql_upper.startswith("DESCRIBE ") or sql_upper.startswith("DESC "):
        parts = sql_upper.split()
        if len(parts) >= 2:
            tbl = parts[1].strip("`\"'")
            esq = obtener_esquema(db_nombre, tbl)
            rows = [
                [c["campo"], c["tipo"], c["nulo"], c["clave"], c["defecto"], c["extra"]]
                for c in esq["columns"]
            ]
            dur = (time.time() - inicio) * 1000.0
            return {
                "success": True,
                "database": db_nombre,
                "query": sql_raw,
                "columns": ["Field", "Type", "Null", "Key", "Default", "Extra"],
                "column_types": ["VARCHAR(64)", "VARCHAR(64)", "VARCHAR(3)", "VARCHAR(3)", "VARCHAR(64)", "VARCHAR(32)"],
                "rows": rows,
                "total_rows": len(rows),
                "affected_rows": 0,
                "execution_time_ms": dur,
                "message": f"{len(rows)} rows in set ({dur / 1000.0:.3f} sec)",
                "error": None
            }

    sql_adaptado = adaptar_mysql_a_sqlite(sql_raw)
    es_select = (
        sql_upper.startswith("SELECT")
        or sql_upper.startswith("PRAGMA")
        or sql_upper.startswith("EXPLAIN")
        or sql_upper.startswith("WITH")
    )

    try:
        conn = sqlite3.connect(ruta)
        cur = conn.cursor()
        if es_select:
            cur.execute(sql_adaptado)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
            # Convert python tuples to JSON serializable lists
            processed_rows = [list(r) for r in rows]
            conn.close()
            dur = (time.time() - inicio) * 1000.0
            return {
                "success": True,
                "database": db_nombre,
                "query": sql_raw,
                "columns": columns,
                "column_types": ["TEXT"] * len(columns),
                "rows": processed_rows,
                "total_rows": len(processed_rows),
                "affected_rows": 0,
                "execution_time_ms": dur,
                "message": f"{len(processed_rows)} rows in set ({dur / 1000.0:.3f} sec)",
                "error": None
            }
        else:
            cur.executescript(sql_adaptado)
            affected = cur.rowcount if cur.rowcount >= 0 else 0
            conn.commit()
            conn.close()
            dur = (time.time() - inicio) * 1000.0
            return {
                "success": True,
                "database": db_nombre,
                "query": sql_raw,
                "columns": [],
                "column_types": [],
                "rows": [],
                "total_rows": 0,
                "affected_rows": affected,
                "execution_time_ms": dur,
                "message": f"Query OK, {affected} row(s) affected ({dur / 1000.0:.3f} sec)",
                "error": None
            }
    except Exception as e:
        dur = (time.time() - inicio) * 1000.0
        return {
            "success": False,
            "database": db_nombre,
            "query": sql_raw,
            "columns": [],
            "column_types": [],
            "rows": [],
            "total_rows": 0,
            "affected_rows": 0,
            "execution_time_ms": dur,
            "message": f"ERROR 1064 (42000): {e}",
            "error": str(e)
        }

def sembrar_datos_ejemplo(db: str) -> Dict[str, Any]:
    db_nombre = db or "mysql_prig"
    ruta = ruta_db(db_nombre)
    conn = sqlite3.connect(ruta)
    script = """
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
        estado VARCHAR(30) DEFAULT 'completado',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS metricas_ia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        modelo VARCHAR(50) NOT NULL,
        tokens_prompt INTEGER NOT NULL,
        tokens_salida INTEGER NOT NULL,
        latencia_ms REAL NOT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS logs_actividad (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario VARCHAR(50) NOT NULL,
        accion VARCHAR(100) NOT NULL,
        ip VARCHAR(45) NOT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    INSERT OR IGNORE INTO usuarios (id, username, email, rol, activo) VALUES
        (1, 'admin', 'admin@prig.local', 'administrador', 1),
        (2, 'alex_mercer', 'alex@prig.dev', 'desarrollador', 1),
        (3, 'sarah_connor', 'sarah@skynet.shield', 'seguridad', 1),
        (4, 'ada_lovelace', 'ada@analitica.org', 'cientifico_datos', 1),
        (5, 'linus_torvalds', 'linus@kernel.org', 'kernel_dev', 0);

    INSERT OR IGNORE INTO productos (id, sku, nombre, categoria, precio, stock, estado) VALUES
        (1, 'PRIG-BOOK-01', 'Libro: Dominando Rust y Sistemas Distribuidos', 'Libros', 49.99, 120, 'disponible'),
        (2, 'PRIG-KEY-RGB', 'Teclado Mecánico Custom 75% Gateron Oil King', 'Hardware', 189.50, 42, 'disponible'),
        (3, 'PRIG-MON-4K', 'Monitor OLED 32 pulgadas 240Hz 4K', 'Monitores', 899.00, 15, 'disponible'),
        (4, 'PRIG-POD-PRO', 'Micrófono Shure MV7 USB/XLR Podcast', 'Audio', 249.00, 8, 'bajo_stock'),
        (5, 'PRIG-MAT-XXL', 'Mousepad Desk Mat Prig Dark Edition 90x40', 'Accesorios', 29.99, 310, 'disponible');

    INSERT OR IGNORE INTO pedidos (id, usuario_id, total, estado) VALUES
        (1, 2, 239.49, 'completado'),
        (2, 4, 899.00, 'en_camino'),
        (3, 1, 49.99, 'completado'),
        (4, 3, 219.49, 'pendiente'),
        (5, 2, 29.99, 'completado');

    INSERT OR IGNORE INTO metricas_ia (id, modelo, tokens_prompt, tokens_salida, latencia_ms) VALUES
        (1, 'qwen2.5-coder:7b', 1250, 420, 185.4),
        (2, 'qwen2.5-coder:7b', 840, 190, 94.2),
        (3, 'deepseek-r1:8b', 2048, 512, 340.1),
        (4, 'llama3.2:3b', 800, 240, 89.0);

    INSERT OR IGNORE INTO logs_actividad (id, usuario, accion, ip) VALUES
        (1, 'admin', 'LOGIN_EXITOSO', '192.168.1.10'),
        (2, 'alex_mercer', 'DESAFIO_COMPLETADO_PYTHON', '127.0.0.1'),
        (3, 'sarah_connor', 'AUDITORIA_SEGURIDAD_MODULOS', '10.0.0.5'),
        (4, 'ada_lovelace', 'PIPELINE_DESPLIEGUE_RUST', '172.16.0.4');
    """
    cur = conn.cursor()
    cur.executescript(script)
    conn.commit()
    conn.close()
    return {
        "success": True,
        "message": "Tablas de ejemplo MySQL (usuarios, productos, pedidos, logs_actividad, metricas_ia) sembradas exitosamente.",
        "database": db_nombre
    }
