//! La telemetría de aprendizaje (`learning_telemetry.py`): los resultados reales de ejecutar el código del alumno, en
//! el SQLite `<espacio>/.prig_dataset/learning.db`, y las métricas que salen de ellos. SQLite coordina los procesos:
//! Python y Rust pueden escribir la misma base mientras convivan.

use prig_plataforma::valor::{Mapa, Valor};
use rusqlite::{params, Connection};
use std::path::{Path, PathBuf};

pub fn ruta_base(espacio: &Path) -> PathBuf {
    espacio.join(".prig_dataset").join("learning.db")
}

/// Abre la base (crea la carpeta y las tablas si faltan, como `__init__` y `_init_tables`)
pub fn abrir(espacio: &Path) -> rusqlite::Result<Connection> {
    let _ = std::fs::create_dir_all(espacio.join(".prig_dataset"));
    let c = Connection::open(ruta_base(espacio))?;
    c.busy_timeout(std::time::Duration::from_secs(5))?;
    c.execute_batch(
        "CREATE TABLE IF NOT EXISTS exercise_events (
            event_id     TEXT PRIMARY KEY,
            exercise_id  TEXT NOT NULL,
            concept      TEXT NOT NULL,
            event_type   TEXT NOT NULL,
            passed       INTEGER,
            attempt_num  INTEGER DEFAULT 1,
            hints_used   INTEGER DEFAULT 0,
            error_kind   TEXT,
            elapsed      REAL DEFAULT 0,
            created_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ev_concept ON exercise_events(concept);
        CREATE INDEX IF NOT EXISTS idx_ev_exercise ON exercise_events(exercise_id);
        CREATE INDEX IF NOT EXISTS idx_ev_created ON exercise_events(created_at);",
    )?;
    Ok(c)
}

/// `classify_error(stderr)`: la taxonomía mínima de errores
pub fn clasificar_error(stderr: &str) -> &'static str {
    if stderr.is_empty() {
        return "none";
    }
    const TABLA: [(&str, &str); 12] = [
        ("AssertionError", "logica_incorrecta"),
        ("SyntaxError", "sintaxis"),
        ("IndentationError", "indentacion"),
        ("NameError", "nombre_no_definido"),
        ("TypeError", "tipos"),
        ("ValueError", "valor_invalido"),
        ("IndexError", "indice_fuera_de_rango"),
        ("KeyError", "clave_inexistente"),
        ("AttributeError", "atributo_inexistente"),
        ("ZeroDivisionError", "division_por_cero"),
        ("RecursionError", "recursion_infinita"),
        ("Tiempo límite", "bucle_infinito"),
    ];
    TABLA.iter().find(|(aguja, _)| stderr.contains(aguja)).map_or("otro", |(_, k)| k)
}

/// `attempt_number(exercise_id)`: los envíos que ya hay más uno
pub fn numero_intento(c: &Connection, ejercicio: &str) -> rusqlite::Result<i64> {
    let n: i64 = c.query_row(
        "SELECT COUNT(*) FROM exercise_events WHERE exercise_id = ? AND event_type = 'submission';",
        [ejercicio],
        |r| r.get(0),
    )?;
    Ok(n + 1)
}

pub struct Evento<'a> {
    pub ejercicio: &'a str,
    pub concepto: &'a str,
    pub tipo: &'a str,
    pub aprobado: Option<bool>,
    pub intento: i64,
    pub pistas: i64,
    pub stderr: &'a str,
    pub segundos: f64,
}

/// `record(...)`: el id del evento
pub fn registrar(c: &Connection, e: &Evento) -> rusqlite::Result<String> {
    let id = format!("ev_{}", &uuid::Uuid::new_v4().simple().to_string()[..10]);
    let tipo_error = if e.aprobado == Some(false) { clasificar_error(e.stderr) } else { "none" };
    c.execute(
        "INSERT INTO exercise_events (event_id, exercise_id, concept, event_type, passed, attempt_num, hints_used, error_kind, elapsed, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        params![id, e.ejercicio, e.concepto, e.tipo, e.aprobado.map(|b| b as i64), e.intento, e.pistas, tipo_error, e.segundos, prig_plataforma::py::ahora_iso()],
    )?;
    Ok(id)
}

/// `sum()` de Python 3.12 (suma compensada de Neumaier)
fn suma(xs: &[f64]) -> f64 {
    let (mut f, mut comp) = (0.0f64, 0.0f64);
    for &x in xs {
        let t = f + x;
        if f.abs() >= x.abs() {
            comp += (f - t) + x;
        } else {
            comp += (x - t) + f;
        }
        f = t;
    }
    if comp != 0.0 && comp.is_finite() { f + comp } else { f }
}

/// `round(x, 1)` de Python (redondeo correcto del valor binario, empates a par)
fn redondear1(x: f64) -> f64 {
    format!("{x:.1}").parse().unwrap_or(x)
}

/// `datetime.fromisoformat` de los formatos que escribe Prig: segundos (con fracción opcional)
pub(crate) fn segundos_iso(t: &str) -> Option<f64> {
    let (fecha, hora) = t.split_once('T')?;
    let mut f = fecha.split('-').map(|x| x.parse::<i64>());
    let (y, m, d) = (f.next()?.ok()?, f.next()?.ok()?, f.next()?.ok()?);
    let (hms, frac) = hora.split_once('.').map_or((hora, "0"), |(a, b)| (a, b));
    let mut h = hms.split(':').map(|x| x.parse::<i64>());
    let (hh, mm, ss) = (h.next()?.ok()?, h.next()?.ok()?, h.next().unwrap_or(Ok(0)).ok()?);
    // días desde 1970 (algoritmo civil de Howard Hinnant)
    let y2 = if m <= 2 { y - 1 } else { y };
    let era = y2.div_euclid(400);
    let yoe = y2 - era * 400;
    let doy = (153 * (m + if m > 2 { -3 } else { 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let dias = era * 146097 + doe - 719468;
    let micro: f64 = format!("0.{frac}").parse().unwrap_or(0.0);
    Some((dias * 86400 + hh * 3600 + mm * 60 + ss) as f64 + micro)
}

/// `metrics(days)`
pub fn metricas(c: &Connection, dias: i64) -> rusqlite::Result<Mapa> {
    // `(datetime.now() - timedelta(days=days)).isoformat()`
    let desde = {
        let ahora = prig_plataforma::py::ahora_iso();
        restar_dias(&ahora, dias)
    };
    let mut st = c.prepare(
        "SELECT exercise_id, concept, passed, hints_used, error_kind, created_at FROM exercise_events
         WHERE event_type='submission' AND created_at >= ? ORDER BY created_at ASC;",
    )?;
    struct Envio {
        ejercicio: String,
        concepto: String,
        aprobado: Option<i64>,
        pistas: Option<i64>,
        error: Option<String>,
        fecha: String,
    }
    let envios: Vec<Envio> = st
        .query_map([&desde], |r| {
            Ok(Envio { ejercicio: r.get(0)?, concepto: r.get(1)?, aprobado: r.get(2)?, pistas: r.get(3)?, error: r.get(4)?, fecha: r.get(5)? })
        })?
        .collect::<Result<_, _>>()?;
    if envios.is_empty() {
        return Ok(Mapa::new()
            .con("window_days", Valor::Entero(dias as i128))
            .con("submissions", Valor::Entero(0))
            .con("exercises_attempted", Valor::Entero(0))
            .con("first_try_pass_rate", Valor::Nulo)
            .con("solve_rate", Valor::Nulo)
            .con("median_attempts_to_pass", Valor::Nulo)
            .con("avg_seconds_to_green", Valor::Nulo)
            .con("error_profile", Mapa::new())
            .con("weak_concepts", Valor::Lista(Vec::new()))
            .con("repeat_error_rate", Valor::Nulo)
            .con("note", "Sin datos todavía: resuelve algún ejercicio para empezar a medir."));
    }
    // por ejercicio, en orden de primera aparición
    let mut por_ejercicio: Vec<(String, Vec<&Envio>)> = Vec::new();
    for e in &envios {
        match por_ejercicio.iter_mut().find(|(k, _)| *k == e.ejercicio) {
            Some((_, v)) => v.push(e),
            None => por_ejercicio.push((e.ejercicio.clone(), vec![e])),
        }
    }
    let primera = por_ejercicio.iter().filter(|(_, v)| v[0].aprobado == Some(1) && v[0].pistas == Some(0)).count();
    let resueltos = por_ejercicio.iter().filter(|(_, v)| v.iter().any(|e| e.aprobado == Some(1))).count();
    let mut intentos: Vec<i64> = Vec::new();
    let mut segundos: Vec<f64> = Vec::new();
    for (_, v) in &por_ejercicio {
        if let Some((i, e)) = v.iter().enumerate().find(|(_, e)| e.aprobado == Some(1)) {
            intentos.push(i as i64 + 1);
            if let (Some(a), Some(b)) = (segundos_iso(&e.fecha), segundos_iso(&v[0].fecha)) {
                segundos.push(a - b);
            }
        }
    }
    let clave_error = |e: &Envio| e.error.clone().unwrap_or_else(|| "null".into());
    let mut perfil: Vec<(String, i128)> = Vec::new();
    let mut fallos_concepto: Vec<(String, i128)> = Vec::new();
    let mut dias_concepto: Vec<(String, Vec<String>)> = Vec::new();
    for e in envios.iter().filter(|e| e.aprobado == Some(0)) {
        let k = clave_error(e);
        match perfil.iter_mut().find(|(x, _)| *x == k) {
            Some(p) => p.1 += 1,
            None => perfil.push((k, 1)),
        }
        match fallos_concepto.iter_mut().find(|(x, _)| *x == e.concepto) {
            Some(p) => p.1 += 1,
            None => fallos_concepto.push((e.concepto.clone(), 1)),
        }
        let dia: String = e.fecha.chars().take(10).collect();
        match dias_concepto.iter_mut().find(|(x, _)| *x == e.concepto) {
            Some(p) => {
                if !p.1.contains(&dia) {
                    p.1.push(dia)
                }
            }
            None => dias_concepto.push((e.concepto.clone(), vec![dia])),
        }
    }
    let reincidentes: Vec<Valor> = dias_concepto.iter().filter(|(_, d)| d.len() > 1).map(|(c, _)| Valor::Texto(c.clone())).collect();
    // sorted(..., key=-n): estable
    perfil.sort_by_key(|p| std::cmp::Reverse(p.1));
    fallos_concepto.sort_by_key(|p| std::cmp::Reverse(p.1));
    let mediana = if intentos.is_empty() {
        Valor::Nulo
    } else {
        let mut o = intentos.clone();
        o.sort_unstable();
        Valor::Entero(o[o.len() / 2] as i128)
    };
    let total = por_ejercicio.len() as f64;
    let mut perfil_m = Mapa::new();
    for (k, n) in perfil {
        perfil_m.poner(k, Valor::Entero(n));
    }
    Ok(Mapa::new()
        .con("window_days", Valor::Entero(dias as i128))
        .con("submissions", Valor::Entero(envios.len() as i128))
        .con("exercises_attempted", Valor::Entero(por_ejercicio.len() as i128))
        .con("first_try_pass_rate", Valor::Real(redondear1(primera as f64 / total * 100.0)))
        .con("solve_rate", Valor::Real(redondear1(resueltos as f64 / total * 100.0)))
        .con("median_attempts_to_pass", mediana)
        .con(
            "avg_seconds_to_green",
            if segundos.is_empty() { Valor::Nulo } else { Valor::Real(redondear1(suma(&segundos) / segundos.len() as f64)) },
        )
        .con("error_profile", perfil_m)
        .con(
            "weak_concepts",
            Valor::Lista(
                fallos_concepto
                    .into_iter()
                    .take(8)
                    .map(|(c, n)| Valor::Mapa(Mapa::new().con("concept", c).con("failures", Valor::Entero(n))))
                    .collect(),
            ),
        )
        .con("repeat_error_rate", Valor::Real(redondear1(reincidentes.len() as f64 / (dias_concepto.len().max(1)) as f64 * 100.0)))
        .con("repeated_concepts", Valor::Lista(reincidentes.into_iter().take(8).collect())))
}

/// Una fecha `isoformat()` menos `dias` días, en el mismo formato
fn restar_dias(iso: &str, dias: i64) -> String {
    let Some(t) = segundos_iso(iso) else { return iso.to_string() };
    let resto = iso.split_once('.').map(|(_, f)| format!(".{f}")).unwrap_or_default();
    let s = (t.floor() as i64) - dias * 86400;
    let (d, r) = (s.div_euclid(86400), s.rem_euclid(86400));
    // de días desde 1970 a fecha civil (Hinnant)
    let z = d + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let dia = doy - (153 * mp + 2) / 5 + 1;
    let mes = if mp < 10 { mp + 3 } else { mp - 9 };
    let anio = yoe + era * 400 + if mes <= 2 { 1 } else { 0 };
    format!("{anio:04}-{mes:02}-{dia:02}T{:02}:{:02}:{:02}{resto}", r / 3600, r % 3600 / 60, r % 60)
}

/// `Hub().marcar(clave, estado, origen, version)`: un evento más en `<hub>/progreso.jsonl` (anexar es atómico entre
/// procesos, así que Python y Rust pueden anotar a la vez)
pub fn marcar_hub(base: &Path, clave: &str, estado: &str, origen: &str, version: &str) -> std::io::Result<Mapa> {
    use std::io::Write;
    let evento = Mapa::new()
        .con("ts", crate::desafios::ahora())
        .con("clave", clave)
        .con("estado", estado)
        .con("origen", origen.chars().take(200).collect::<String>())
        .con("version", version.chars().take(30).collect::<String>());
    std::fs::create_dir_all(base)?;
    let mut f = std::fs::OpenOptions::new().create(true).append(true).open(base.join("progreso.jsonl"))?;
    f.write_all(format!("{}\n", prig_plataforma::json::escribir_linea(&Valor::Mapa(evento.clone()))).as_bytes())?;
    Ok(evento)
}

/// `_registrar_telemetria(d, "submission", ...)` de app.py, si la bandera `learning_telemetry` está encendida
pub fn registrar_envio(espacio: &Path, d: &Mapa, aprobado: bool, pistas: i64, stderr: &str, segundos: f64) -> rusqlite::Result<()> {
    let conceptos: Vec<String> = match d.get("conceptos") {
        Some(Valor::Lista(l)) => l.iter().filter_map(|v| if let Valor::Texto(t) = v { Some(t.clone()) } else { None }).collect(),
        _ => Vec::new(),
    };
    let concepto = if conceptos.is_empty() { d.texto("titulo").unwrap_or_default().to_string() } else { conceptos.join(", ") };
    let id = d.texto("id").unwrap_or_default().to_string();
    let c = abrir(espacio)?;
    let intento = numero_intento(&c, &id)?;
    registrar(&c, &Evento { ejercicio: &id, concepto: &concepto, tipo: "submission", aprobado: Some(aprobado), intento, pistas, stderr, segundos })?;
    Ok(())
}
