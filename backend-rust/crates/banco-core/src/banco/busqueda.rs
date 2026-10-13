//! Búsqueda (BancoProyecto._consulta_fts, buscar, _rutas_mencionadas, vecinos, buscar_conocimiento,
//! buscar_resoluciones, cambios_desde, texto_busqueda): mismas consultas, mismas sumas de puntos en el mismo
//! orden y los mismos desempates (orden estable por puntos, inserción en el orden de las listas).

use std::collections::{BTreeSet, HashSet};
use std::sync::LazyLock;

use indexmap::IndexMap;
use rusqlite::types::ToSql;
use rusqlite::{params, Connection};
use serde_json::{Map, Value};

use super::{error, filas, Banco, Resultado};
use crate::extraer::ES_TEST;
use crate::py::cadena::{es_alfabetico, largo, primeros, splitlines, strip_de};
use crate::py::json::loads;
use crate::py::numero::suma;
use crate::re::Re;
use crate::texto::{identificadores_nombrados, terminos_consulta, RRF_K};

/// `_consulta_fts`: cada término y, para las palabras largas, su raíz como prefijo.
pub fn consulta_fts(terms: &[String]) -> Option<String> {
    let mut partes: Vec<String> = vec![];
    for t in terms {
        let t = t.replace('"', "");
        if t.is_empty() {
            continue;
        }
        partes.push(format!("\"{t}\""));
        let n = largo(&t);
        if n >= 6 && es_alfabetico(&t) {
            partes.push(format!("\"{}\"*", primeros(&t, 4.max(n - 3))));
        }
    }
    if partes.is_empty() {
        return None;
    }
    let mut vistos = HashSet::new();
    let unicas: Vec<String> = partes.into_iter().filter(|p| vistos.insert(p.clone())).collect();
    Some(unicas.join(" OR "))
}

/// `_coseno`: suma de productos (vectores ya normalizados), con la suma de Python 3.12.
pub fn coseno(a: &[f64], b: &[f32]) -> f64 {
    suma(a.iter().zip(b.iter()).map(|(x, y)| x * (*y as f64)))
}

static RUTA_MENCIONADA: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"[\w./-]+\.[A-Za-z]{1,6}\b", ""));
static HABLA_DE_TESTS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"\b(tests?|pruebas?|unittest|pytest|spec)\b", "i"));

/// `_rutas_mencionadas` (en Python un set; aquí ordenadas).
pub fn rutas_mencionadas(c: &Connection, texto: &str) -> Resultado<Vec<String>> {
    let candidatos: BTreeSet<&str> = RUTA_MENCIONADA.findall0(texto).into_iter().collect();
    if candidatos.is_empty() {
        return Ok(vec![]);
    }
    let rutas = Banco::rutas(c)?;
    let mut salida: BTreeSet<String> = BTreeSet::new();
    for cand in candidatos {
        // Recortada como en Python y, además, tal cual: strip("./") le quitaba el punto a un archivo oculto
        for x in [strip_de(cand, "./"), cand] {
            let sufijo = format!("/{x}");
            for r in &rutas {
                if r == x || r.ends_with(&sufijo) {
                    salida.insert(r.clone());
                }
            }
        }
    }
    Ok(salida.into_iter().collect())
}

/// Un fragmento encontrado (el dict de `buscar`).
#[derive(Clone, Debug)]
pub struct Encontrado {
    pub id: i64,
    pub ruta: String,
    pub simbolo: Option<String>,
    pub tipo: Option<String>,
    pub ini: i64,
    pub fin: i64,
    pub texto: String,
    pub tokens: i64,
    pub puntos: f64,
}

pub fn numero(x: f64) -> Value {
    serde_json::Number::from_f64(x).map(Value::Number).unwrap_or(Value::Null)
}

impl Encontrado {
    pub fn a_valor(&self) -> Value {
        let mut m = Map::new();
        m.insert("id".into(), Value::from(self.id));
        m.insert("ruta".into(), Value::from(self.ruta.clone()));
        m.insert("simbolo".into(), self.simbolo.clone().map(Value::from).unwrap_or(Value::Null));
        m.insert("tipo".into(), self.tipo.clone().map(Value::from).unwrap_or(Value::Null));
        m.insert("ini".into(), Value::from(self.ini));
        m.insert("fin".into(), Value::from(self.fin));
        m.insert("texto".into(), Value::from(self.texto.clone()));
        m.insert("tokens".into(), Value::from(self.tokens));
        m.insert("puntos".into(), numero(self.puntos));
        Value::Object(m)
    }
}

pub fn marcas(n: usize) -> String {
    vec!["?"; n].join(",")
}

fn ids_de(c: &Connection, sql: &str, args: &[&dyn ToSql]) -> Resultado<Vec<i64>> {
    let mut st = c.prepare(sql).map_err(error)?;
    let v = st.query_map(args, |f| f.get::<_, i64>(0)).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
    Ok(v)
}


/// Los fragmentos de los símbolos que nombra la pregunta, como la consulta de Python
///   SELECT fr.id FROM fragmentos fr JOIN simbolos s ON s.ruta = fr.ruta AND fr.simbolo = s.nombre
///   WHERE s.corto IN (…) OR s.nombre IN (…) ORDER BY fr.ini
/// pero sin recorrer todos los fragmentos (≈190 ms en Prig: `simbolos.nombre` no tiene índice): por el índice de
/// `corto` (un nombre completo termina en su nombre corto) y ordenado como lo deja SQLite, por (fr.ini, fr.id, s.id)
/// —el orden del recorrido, estable—, con una fila por cada par (fragmento, símbolo).
pub fn ids_nombrados(c: &Connection, nombrados: &[String]) -> Resultado<Vec<i64>> {
    let conjunto: HashSet<&str> = nombrados.iter().map(|x| x.as_str()).collect();
    let mut cortos: BTreeSet<&str> = conjunto.iter().copied().collect();
    for n in nombrados {
        cortos.insert(n.rsplit('.').next().unwrap_or(n));
    }
    let lista: Vec<&str> = cortos.into_iter().collect();
    let sql = format!("SELECT id, ruta, nombre, corto FROM simbolos WHERE corto IN ({})", marcas(lista.len()));
    let args: Vec<&dyn ToSql> = lista.iter().map(|x| x as &dyn ToSql).collect();
    let mut simbolos: Vec<(i64, String, String)> = vec![];
    {
        let mut st = c.prepare(&sql).map_err(error)?;
        let mut fs = st.query(args.as_slice()).map_err(error)?;
        while let Some(f) = fs.next().map_err(error)? {
            let id: i64 = f.get(0).map_err(error)?;
            let ruta: Option<String> = f.get(1).map_err(error)?;
            let nombre: Option<String> = f.get(2).map_err(error)?;
            let corto: Option<String> = f.get(3).map_err(error)?;
            let entra = corto.as_deref().map(|x| conjunto.contains(x)).unwrap_or(false) || nombre.as_deref().map(|x| conjunto.contains(x)).unwrap_or(false);
            if let (true, Some(r), Some(n)) = (entra, ruta, nombre) {
                simbolos.push((id, r, n));
            }
        }
    }
    let mut pares: Vec<(i64, i64, i64)> = vec![];
    let mut st = c.prepare_cached("SELECT id, ini FROM fragmentos WHERE ruta = ? AND simbolo = ?").map_err(error)?;
    for (sid, ruta, nombre) in &simbolos {
        let mut fs = st.query(params![ruta, nombre]).map_err(error)?;
        while let Some(f) = fs.next().map_err(error)? {
            let fid: i64 = f.get(0).map_err(error)?;
            let ini: Option<i64> = f.get(1).map_err(error)?;
            pares.push((ini.unwrap_or(i64::MIN), fid, *sid));
        }
    }
    pares.sort();
    Ok(pares.into_iter().map(|(_, fid, _)| fid).collect())
}

/// La consulta original de Python, para verificar `ids_nombrados`.
pub fn ids_nombrados_sql(c: &Connection, nombrados: &[String]) -> Resultado<Vec<i64>> {
    let m = marcas(nombrados.len());
    let sql = format!(
        "SELECT fr.id FROM fragmentos fr JOIN simbolos s
                        ON s.ruta = fr.ruta AND fr.simbolo = s.nombre
                        WHERE s.corto IN ({m}) OR s.nombre IN ({m}) ORDER BY fr.ini"
    );
    let args: Vec<&dyn ToSql> = nombrados.iter().chain(nombrados.iter()).map(|x| x as &dyn ToSql).collect();
    ids_de(c, &sql, &args)
}

fn sumar(puntos: &mut IndexMap<i64, f64>, i: i64, x: f64) {
    let previo = puntos.get(&i).copied().unwrap_or(0.0);
    puntos.insert(i, previo + x);
}

fn ordenar_por_puntos(v: &mut [Value]) {
    v.sort_by(|a, b| b["puntos"].as_f64().partial_cmp(&a["puntos"].as_f64()).unwrap_or(std::cmp::Ordering::Equal));
}

fn lista_json(texto: Option<&str>) -> Vec<String> {
    match loads(texto.filter(|s| !s.is_empty()).unwrap_or("[]")) {
        Some(Value::Array(xs)) => xs.into_iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect(),
        _ => vec![],
    }
}

impl Banco {
    /// `buscar(consulta, k, vector)`: `vector` es el de la consulta ya calculado (None: sin vectores).
    pub fn buscar(&self, consulta: &str, k: usize, vector: Option<&[f64]>) -> Resultado<Vec<Encontrado>> {
        let c = self.conectar()?;
        self.buscar_en(&c, consulta, k, vector)
    }

    pub fn buscar_en(&self, c: &Connection, consulta: &str, k: usize, vector: Option<&[f64]>) -> Resultado<Vec<Encontrado>> {
        let mut listas: Vec<(Vec<i64>, f64)> = vec![];
        let terms = terminos_consulta(consulta);
        if let Some(q) = consulta_fts(&terms) {
            if let Ok(ids) = ids_de(c, "SELECT rowid FROM fragmentos_fts WHERE fragmentos_fts MATCH ? ORDER BY bm25(fragmentos_fts, 2.0, 4.0, 1.0) LIMIT 80", &[&q]) {
                listas.push((ids, 1.0));
            }
        }
        let nombrados = identificadores_nombrados(consulta);
        if !nombrados.is_empty() {
            let ids = ids_nombrados(c, &nombrados)?;
            if !ids.is_empty() {
                listas.push((ids.into_iter().take(30).collect(), 2.0));
            }
        }
        let rutas = rutas_mencionadas(c, consulta)?;
        if !rutas.is_empty() {
            let sql = format!("SELECT id FROM fragmentos WHERE ruta IN ({}) ORDER BY ini LIMIT 40", marcas(rutas.len()));
            let args: Vec<&dyn ToSql> = rutas.iter().map(|x| x as &dyn ToSql).collect();
            listas.push((ids_de(c, &sql, &args)?, 1.5));
        }
        if let Some(qv) = vector {
            let vectores = self.cargar_vectores()?;
            let mut por_sha: IndexMap<String, Vec<i64>> = IndexMap::new();
            {
                let mut st = c.prepare("SELECT id, sha FROM fragmentos").map_err(error)?;
                let mut fs = st.query([]).map_err(error)?;
                while let Some(f) = fs.next().map_err(error)? {
                    let id: i64 = f.get(0).map_err(error)?;
                    let sha: Option<String> = f.get(1).map_err(error)?;
                    por_sha.entry(sha.unwrap_or_else(|| "None".into())).or_default().push(id);
                }
            }
            let mut puntuados: Vec<(f64, i64)> = vec![];
            for (sha, ids_sha) in &por_sha {
                if let Some(v) = vectores.get(&format!("f:{sha}")) {
                    puntuados.push((coseno(qv, v), ids_sha[0]));
                }
            }
            puntuados.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
            if let Some(primero) = puntuados.first() {
                let piso = 0.25f64.max(primero.0 - 0.2);
                listas.push((puntuados.iter().take(80).filter(|(s, _)| *s >= piso).map(|(_, i)| *i).collect(), 1.2));
            }
        }
        let version = Banco::version_en(c)?;
        let recientes: Vec<String> = {
            let mut st = c.prepare("SELECT DISTINCT ruta FROM cambios WHERE version > ? ORDER BY id DESC LIMIT 20").map_err(error)?;
            let v = st.query_map(params![0.max(version - 5)], |f| f.get::<_, Option<String>>(0)).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
            v.into_iter().map(|x| x.unwrap_or_else(|| "None".into())).collect()
        };
        let mut puntos: IndexMap<i64, f64> = IndexMap::new();
        for (ids, peso) in &listas {
            for (rango, i) in ids.iter().enumerate() {
                sumar(&mut puntos, *i, peso / (RRF_K + rango as f64 + 1.0));
            }
        }
        if puntos.is_empty() {
            return Ok(vec![]);
        }
        let mut mejores: Vec<(i64, f64)> = puntos.into_iter().collect();
        mejores.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        mejores.truncate((k * 2).max(40));
        let corte = mejores[0].1 * 0.25;
        mejores.retain(|(_, p)| *p >= corte);
        let sql = format!("SELECT id, ruta, simbolo, tipo, ini, fin, texto, tokens FROM fragmentos WHERE id IN ({})", marcas(mejores.len()));
        let ids: Vec<i64> = mejores.iter().map(|(i, _)| *i).collect();
        let args: Vec<&dyn ToSql> = ids.iter().map(|x| x as &dyn ToSql).collect();
        let mut por_id: std::collections::HashMap<i64, Encontrado> = std::collections::HashMap::new();
        {
            let mut st = c.prepare(&sql).map_err(error)?;
            let mut fs = st.query(args.as_slice()).map_err(error)?;
            while let Some(f) = fs.next().map_err(error)? {
                let e = Encontrado {
                    id: f.get(0).map_err(error)?,
                    ruta: f.get::<_, Option<String>>(1).map_err(error)?.unwrap_or_default(),
                    simbolo: f.get(2).map_err(error)?,
                    tipo: f.get(3).map_err(error)?,
                    ini: f.get::<_, Option<i64>>(4).map_err(error)?.unwrap_or(0),
                    fin: f.get::<_, Option<i64>>(5).map_err(error)?.unwrap_or(0),
                    texto: f.get::<_, Option<String>>(6).map_err(error)?.unwrap_or_default(),
                    tokens: f.get::<_, Option<i64>>(7).map_err(error)?.unwrap_or(0),
                    puntos: 0.0,
                };
                por_id.insert(e.id, e);
            }
        }
        let habla_de_tests = HABLA_DE_TESTS.hay(consulta);
        let mut salida = vec![];
        for (i, mut p) in mejores {
            let Some(mut f) = por_id.remove(&i) else { continue };
            if recientes.contains(&f.ruta) {
                p *= 1.1;
            }
            if f.tipo.as_deref() == Some("bloque") && [".json", ".yaml", ".yml", ".csv", ".toml"].iter().any(|e| f.ruta.ends_with(e)) {
                p *= 0.7;
            }
            if !habla_de_tests && ES_TEST.hay(&f.ruta) {
                p *= 0.5;
            }
            f.puntos = p;
            salida.push(f);
        }
        salida.sort_by(|a, b| b.puntos.partial_cmp(&a.puntos).unwrap_or(std::cmp::Ordering::Equal));
        salida.truncate(k);
        Ok(salida)
    }

    /// `vecinos`: lo que llaman los fragmentos elegidos y quién los llama (1 salto, aristas resueltas).
    pub fn vecinos(&self, fragmentos: &[Encontrado], limite: usize) -> Resultado<Vec<Value>> {
        let mut ya: HashSet<(String, String)> = fragmentos.iter().map(|f| (f.ruta.clone(), f.simbolo.clone().unwrap_or_else(|| "\0None".into()))).collect();
        let mut salida: Vec<Value> = vec![];
        let c = self.conectar()?;
        for f in fragmentos.iter().take(6) {
            let Some(simbolo) = f.simbolo.as_deref().filter(|s| !s.is_empty()) else { continue };
            let llamados = filas(
                &c,
                "SELECT DISTINCT s.ruta, s.nombre, s.firma, s.doc, s.ini, s.fin
                                      FROM llamadas l JOIN simbolos s ON s.ruta = l.a_ruta AND s.nombre = l.a_nombre
                                      WHERE l.ruta = ? AND l.desde = ? ORDER BY l.linea LIMIT 20",
                &[&f.ruta, &simbolo],
            )?;
            for mut s in llamados {
                let clave = (s["ruta"].as_str().unwrap_or("").to_string(), s["nombre"].as_str().unwrap_or("").to_string());
                if ya.insert(clave) {
                    s.as_object_mut().unwrap().insert("relacion".into(), Value::from(format!("llamada desde {simbolo}")));
                    salida.push(s);
                }
            }
            let llaman = filas(
                &c,
                "SELECT DISTINCT s.ruta, s.nombre, s.firma, s.doc, s.ini, s.fin
                                      FROM llamadas l JOIN simbolos s ON s.ruta = l.ruta AND s.nombre = l.desde
                                      WHERE l.a_ruta = ? AND l.a_nombre = ? LIMIT 8",
                &[&f.ruta, &simbolo],
            )?;
            let corto = simbolo.rsplit('.').next().unwrap_or(simbolo);
            for mut u in llaman {
                let clave = (u["ruta"].as_str().unwrap_or("").to_string(), u["nombre"].as_str().unwrap_or("").to_string());
                if ya.insert(clave) {
                    u.as_object_mut().unwrap().insert("relacion".into(), Value::from(format!("llama a {corto}")));
                    salida.push(u);
                }
            }
        }
        salida.truncate(limite);
        Ok(salida)
    }

    /// `buscar_conocimiento`: por texto (RRF), vectores y rutas propias.
    pub fn buscar_conocimiento(&self, consulta: &str, k: usize, vector: Option<&[f64]>, rutas: Option<&HashSet<String>>) -> Resultado<Vec<Value>> {
        let c = self.conectar()?;
        let mut puntos: IndexMap<i64, f64> = IndexMap::new();
        if let Some(q) = consulta_fts(&terminos_consulta(consulta)) {
            if let Ok(ids) = ids_de(&c, "SELECT rowid FROM conocimiento_fts WHERE conocimiento_fts MATCH ? ORDER BY bm25(conocimiento_fts, 3.0, 1.0) LIMIT 30", &[&q]) {
                for (rango, i) in ids.into_iter().enumerate() {
                    sumar(&mut puntos, i, 1.0 / (RRF_K + rango as f64 + 1.0));
                }
            }
        }
        if let Some(v) = vector {
            let vectores = self.cargar_vectores()?;
            let mut sims: Vec<(f64, i64)> = vectores
                .iter()
                .filter(|(cl, _)| cl.starts_with("c:"))
                .filter_map(|(cl, x)| cl[2..].parse::<i64>().ok().map(|i| (coseno(v, x), i)))
                .collect();
            sims.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
            for (rango, (sim, i)) in sims.into_iter().take(30).enumerate() {
                if sim >= 0.45 {
                    sumar(&mut puntos, i, 1.2 / (RRF_K + rango as f64 + 1.0));
                }
            }
        }
        let hay_rutas = rutas.map(|r| !r.is_empty()).unwrap_or(false);
        let todas = if !puntos.is_empty() || hay_rutas { filas(&c, "SELECT * FROM conocimiento", &[])? } else { vec![] };
        let mut salida = vec![];
        for mut f in todas {
            let id = f["id"].as_i64().unwrap_or(0);
            let mut p = puntos.get(&id).copied().unwrap_or(0.0);
            let suyas: BTreeSet<String> = lista_json(f["rutas"].as_str()).into_iter().collect();
            if let Some(r) = rutas {
                if !r.is_empty() && suyas.iter().any(|s| r.contains(s)) {
                    p += 0.5 / RRF_K;
                }
            }
            if p > 0.0 {
                let o = f.as_object_mut().unwrap();
                o.insert("puntos".into(), numero(p));
                o.insert("rutas".into(), Value::from(suyas.into_iter().collect::<Vec<_>>()));
                salida.push(f);
            }
        }
        ordenar_por_puntos(&mut salida);
        salida.truncate(k);
        Ok(salida)
    }

    /// `buscar_resoluciones`: parecidas de verdad (por significado o compartiendo bastantes palabras).
    pub fn buscar_resoluciones(&self, consulta: &str, k: usize, vector: Option<&[f64]>) -> Resultado<Vec<Value>> {
        let c = self.conectar()?;
        let mut puntos: IndexMap<i64, f64> = IndexMap::new();
        let mut coincide_texto: HashSet<i64> = HashSet::new();
        let terms = terminos_consulta(consulta);
        if let Some(q) = consulta_fts(&terms) {
            if let Ok(ids) = ids_de(&c, "SELECT rowid, bm25(resoluciones_fts, 3.0, 1.0) b FROM resoluciones_fts WHERE resoluciones_fts MATCH ? ORDER BY b LIMIT 20", &[&q]) {
                for (rango, i) in ids.into_iter().enumerate() {
                    sumar(&mut puntos, i, 1.0 / (RRF_K + rango as f64 + 1.0));
                    coincide_texto.insert(i);
                }
            }
        }
        let mut sims: std::collections::HashMap<i64, f64> = std::collections::HashMap::new();
        if let Some(v) = vector {
            let vectores = self.cargar_vectores()?;
            let mut orden: Vec<(f64, i64)> = vectores
                .iter()
                .filter(|(cl, _)| cl.starts_with("r:"))
                .filter_map(|(cl, x)| cl[2..].parse::<i64>().ok().map(|i| (coseno(v, x), i)))
                .collect();
            orden.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
            for (rango, (sim, i)) in orden.into_iter().take(20).enumerate() {
                sims.insert(i, sim);
                if sim >= 0.55 {
                    sumar(&mut puntos, i, 1.5 / (RRF_K + rango as f64 + 1.0));
                }
            }
        }
        let elegidos: Vec<i64> = puntos.keys().copied().collect();
        if elegidos.is_empty() {
            return Ok(vec![]);
        }
        let sql = format!("SELECT id, pregunta, resumen, rutas, modelo, cuando, version FROM resoluciones WHERE id IN ({})", marcas(elegidos.len()));
        let args: Vec<&dyn ToSql> = elegidos.iter().map(|x| x as &dyn ToSql).collect();
        let todas = filas(&c, &sql, &args)?;
        let terms_set: HashSet<&String> = terms.iter().collect();
        let mut salida = vec![];
        for mut f in todas {
            let id = f["id"].as_i64().unwrap_or(0);
            let parecida = if sims.get(&id).copied().unwrap_or(0.0) >= 0.55 {
                true
            } else {
                let texto = format!("{} {}", f["pregunta"].as_str().unwrap_or("None"), f["resumen"].as_str().unwrap_or("None"));
                let propios: HashSet<String> = terminos_consulta(&texto).into_iter().collect();
                let comunes = propios.iter().filter(|t| terms_set.contains(t)).count();
                coincide_texto.contains(&id) && comunes >= 2usize.max(terms_set.len() / 3)
            };
            if !parecida {
                continue;
            }
            let rutas = lista_json(f["rutas"].as_str());
            let version = f["version"].as_i64().unwrap_or(0);
            let cambiaron: Vec<String> = if rutas.is_empty() {
                vec![]
            } else {
                let sql = format!("SELECT DISTINCT ruta FROM cambios WHERE version > ? AND ruta IN ({})", marcas(rutas.len()));
                let mut args: Vec<&dyn ToSql> = vec![&version];
                args.extend(rutas.iter().map(|x| x as &dyn ToSql));
                let mut st = c.prepare(&sql).map_err(error)?;
                let v = st.query_map(args.as_slice(), |r| r.get::<_, Option<String>>(0)).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
                v.into_iter().map(|x| x.unwrap_or_else(|| "None".into())).collect()
            };
            let o = f.as_object_mut().unwrap();
            o.insert("rutas".into(), Value::from(rutas));
            o.insert("puntos".into(), numero(puntos.get(&id).copied().unwrap_or(0.0)));
            o.insert("cambiaron_despues".into(), Value::from(cambiaron));
            salida.push(f);
        }
        ordenar_por_puntos(&mut salida);
        salida.truncate(k);
        Ok(salida)
    }

    /// `cambios_desde`: el último estado de cada archivo, con los símbolos acumulados.
    pub fn cambios_desde(&self, version: i64, limite: i64) -> Resultado<Vec<Value>> {
        let c = self.conectar()?;
        let lista = filas(&c, "SELECT * FROM cambios WHERE version > ? ORDER BY id DESC LIMIT ?", &[&version, &limite])?;
        let mut por_ruta: IndexMap<String, Value> = IndexMap::new();
        for mut f in lista {
            let simbolos = loads(f["simbolos"].as_str().filter(|s| !s.is_empty()).unwrap_or("{}")).unwrap_or(Value::Object(Map::new()));
            f.as_object_mut().unwrap().insert("simbolos".into(), simbolos);
            let ruta = f["ruta"].as_str().unwrap_or("None").to_string();
            match por_ruta.get_mut(&ruta) {
                None => {
                    por_ruta.insert(ruta, f);
                }
                Some(previo) => {
                    let mas = previo["mas"].as_i64().unwrap_or(0) + f["mas"].as_i64().unwrap_or(0);
                    let menos = previo["menos"].as_i64().unwrap_or(0) + f["menos"].as_i64().unwrap_or(0);
                    let po = previo.as_object_mut().unwrap();
                    po.insert("mas".into(), Value::from(mas));
                    po.insert("menos".into(), Value::from(menos));
                    for clave in ["nuevos", "borrados", "modificados"] {
                        let mut union: BTreeSet<String> = BTreeSet::new();
                        for fuente in [po.get("simbolos"), f.get("simbolos")] {
                            if let Some(Value::Array(xs)) = fuente.and_then(|s| s.get(clave)) {
                                union.extend(xs.iter().filter_map(|x| x.as_str().map(|s| s.to_string())));
                            }
                        }
                        if let Some(Value::Object(s)) = po.get_mut("simbolos") {
                            s.insert(clave.into(), Value::from(union.into_iter().collect::<Vec<_>>()));
                        }
                    }
                    if f["tipo"].as_str() == Some("nuevo") {
                        po.insert("tipo".into(), Value::from("nuevo"));
                    }
                }
            }
        }
        Ok(por_ruta.into_values().collect())
    }

    /// `texto_busqueda`.
    pub fn texto_busqueda(&self, consulta: &str, k: usize, vector: Option<&[f64]>) -> Resultado<String> {
        let lista = self.buscar(consulta, k, vector)?;
        if lista.is_empty() {
            return Ok("Sin resultados en el banco del proyecto.".to_string());
        }
        let partes: Vec<String> = lista
            .iter()
            .map(|f| {
                let primeras = splitlines(&f.texto).into_iter().take(6).collect::<Vec<_>>().join("\n");
                format!("### {}:{}-{} {}\n{}", f.ruta, f.ini, f.fin, f.simbolo.clone().unwrap_or_default(), primeras)
            })
            .collect();
        Ok(partes.join("\n\n"))
    }
}
