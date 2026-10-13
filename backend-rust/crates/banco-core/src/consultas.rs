//! La consola del modelo sobre el banco (memoria_consulta.API, la parte de datos) y los hechos de una pregunta
//! (terminos_de, _hechos_de, _asignaciones_de, _claves_sospechosas, _codigo_en_revision, _trampas,
//! hechos_de_la_pregunta). Lo que ejecuta código (P.cargar, revisar, «cómo probarla») queda en Python.
//! Los errores llevan el tipo de Python delante («KeyError: …») para que la fachada los levante igual.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::{Arc, LazyLock, Mutex};

use indexmap::IndexMap;
use rusqlite::types::ToSql;
use rusqlite::{params, Connection};
use serde_json::{json, Map, Value};

use crate::banco::{descomprimir, error, fila_a_valor, Banco, Resultado};
use crate::extraer::{endpoint_de, ruta_http_canonica};
use crate::py::cadena::{es_mayuscula, largo, primeros, rstrip, rstrip_de, splitlines, split_espacios, strip, strip_de};
use crate::py::json::loads;
use crate::py::ruta::{basename, splitext};
use crate::pyast::unparse::unparse;
use crate::pyast::{con_pila, cota_de_profundidad, Arbol, Id, K};
use crate::re::{Re, ReInicio};

pub const FAMILIA_JS: [&str; 7] = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue", ".html"];
pub const MODULOS_PERMITIDOS: [&str; 16] =
    ["re", "math", "json", "collections", "itertools", "functools", "statistics", "difflib", "ast", "textwrap", "heapq", "bisect", "operator", "string", "fnmatch", "datetime"];

fn s(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::String(x) => x.clone(),
        otro => otro.to_string(),
    }
}

fn clave_err(msg: String) -> String {
    format!("KeyError: {msg}")
}

/// `_es_test` de la consola (más simple que el del banco).
pub fn es_test(ruta: &str) -> bool {
    let base = basename(ruta);
    let r = format!("/{ruta}");
    r.contains("/tests/") || r.contains("/test/") || base.starts_with("test_")
        || ["_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"].iter().any(|e| base.ends_with(e))
}

static CADENA: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"(["'])(?:\\.|(?!\1).)*\1"#, ""));
static IMPORT_PY: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^\s*(?:from\s+[\w.]+\s+)?import\s+(.+)$", ""));
static IMPORT_JS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"^\s*import\s+(.+?)\s+from\s|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(", ""));
static IDENT_JS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"[A-Za-z_$][\w$]*", ""));
static PARENS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"[(){}\\]", ""));
static INSTANCIA: LazyLock<Re> = LazyLock::new(|| {
    Re::nuevo(concat!(r"^\s*([A-Za-z_]\w*)\s*(?::\s*[\w.\[\]]+\s*)?=\s*(?:new\s+)?([A-Z]\w*)\s*\(", r"|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*new\s+([A-Z]\w*)\s*\("), "")
});

/// `_nombres_importados`.
pub fn nombres_importados(lineas: &[String]) -> HashSet<String> {
    let mut nombres = HashSet::new();
    let mut abierto = false;
    for linea in lineas {
        let codigo = linea.split('#').next().unwrap_or("");
        let trozo: String;
        if abierto {
            trozo = codigo.to_string();
            abierto = !codigo.contains(')');
        } else if let Some(m) = IMPORT_PY.coincide(codigo) {
            trozo = m.g(1).to_string();
            abierto = trozo.contains('(') && !trozo.contains(')');
        } else {
            if let Some(j) = IMPORT_JS.buscar(codigo) {
                match j.grupo(2).filter(|x| !x.is_empty()) {
                    Some(n) => {
                        nombres.insert(n.to_string());
                    }
                    None => {
                        for n in IDENT_JS.findall0(j.g(1)) {
                            nombres.insert(n.to_string());
                        }
                    }
                }
            }
            continue;
        }
        let limpio = PARENS.sub(" ", &trozo);
        for parte in limpio.split(',') {
            let palabras = split_espacios(parte);
            if palabras.is_empty() {
                continue;
            }
            let nombre = if palabras.len() >= 3 && palabras[1] == "as" {
                palabras[2]
            } else if palabras[0] == "*" {
                continue;
            } else {
                palabras[0]
            };
            nombres.insert(nombre.split('.').next().unwrap_or("").to_string());
        }
    }
    nombres
}

/// `_modulo_de_alias`.
pub fn modulo_de_alias(lineas: &[String], alias: &str) -> Option<String> {
    for linea in lineas {
        if !linea.contains(alias) {
            continue;
        }
        let Some(m) = IMPORT_PY.coincide(linea.split('#').next().unwrap_or("")) else { continue };
        let limpio = PARENS.sub(" ", m.g(1));
        for parte in limpio.split(',') {
            let palabras = split_espacios(parte);
            if palabras.is_empty() {
                continue;
            }
            if palabras.len() >= 3 && palabras[1] == "as" && palabras[2] == alias {
                return Some(palabras[0].rsplit('.').next().unwrap_or("").to_string());
            }
            if palabras[0] == alias || palabras[0].split('.').next() == Some(alias) {
                return Some(alias.to_string());
            }
        }
    }
    None
}

/// `_instancias_de`: variable → clase de la primera asignación con constructor.
pub fn instancias_de(lineas: &[String]) -> HashMap<String, String> {
    let mut salida = HashMap::new();
    for linea in lineas {
        if let Some(m) = INSTANCIA.buscar(linea) {
            let (n, c) = if m.grupo(1).map(|x| !x.is_empty()).unwrap_or(false) { (m.g(1), m.g(2)) } else { (m.g(3), m.g(4)) };
            salida.entry(n.to_string()).or_insert_with(|| c.to_string());
        }
    }
    salida
}

/// `_patrones_de_clave`: (lee, escribe, en un diccionario literal).
pub fn patrones_de_clave(clave: &str) -> (Re, Re, Re) {
    let k = format!(r#"["']{}["']"#, Re::escapar(clave));
    (
        Re::cache(&format!(r"\.get\(\s*{k}|\[\s*{k}\s*\](?!\s*=(?!=))"), ""),
        Re::cache(&format!(r"\[\s*{k}\s*\]\s*=(?!=)|\.setdefault\(\s*{k}"), ""),
        Re::cache(&format!(r"{k}\s*:"), ""),
    )
}


/// `_CADENA_NOMBRE.finditer(linea)` (`(["'])([A-Za-z_]\w{3,60})\1`) sin retroceso: una comilla, un nombre de 4 a
/// 61 caracteres de palabra y la misma comilla. Si la tira de caracteres de palabra pasa de 61, la expresión no
/// casa ahí (no puede cortarla antes de una letra); al fallar se sigue en el carácter siguiente, al casar después
/// de la comilla de cierre.
pub fn cadenas_nombre(linea: &str) -> Vec<&str> {
    let cs: Vec<(usize, char)> = linea.char_indices().collect();
    let mut salida = vec![];
    let mut i = 0;
    while i < cs.len() {
        let q = cs[i].1;
        if q == '"' || q == '\'' {
            if let Some(&(_, c0)) = cs.get(i + 1) {
                if c0.is_ascii_alphabetic() || c0 == '_' {
                    let mut j = i + 2;
                    while j < cs.len() && j - (i + 2) < 61 && crate::py::cadena::es_palabra(cs[j].1) {
                        j += 1;
                    }
                    let resto = j - (i + 2);
                    if (3..=60).contains(&resto) && cs.get(j).map(|x| x.1) == Some(q) {
                        let ini = cs[i + 1].0;
                        let fin = cs[j].0;
                        salida.push(&linea[ini..fin]);
                        i = j + 1;
                        continue;
                    }
                }
            }
        }
        i += 1;
    }
    salida
}

/// `_un_cambio`: ¿difieren en exactamente una letra?
pub fn un_cambio(a: &str, b: &str) -> bool {
    let (va, vb): (Vec<char>, Vec<char>) = (a.chars().collect(), b.chars().collect());
    if a == b || (va.len() as i64 - vb.len() as i64).abs() > 1 {
        return false;
    }
    if va.len() == vb.len() {
        return va.iter().zip(vb.iter()).filter(|(x, y)| x != y).count() == 1;
    }
    let (corta, larga) = if va.len() < vb.len() { (&va, &vb) } else { (&vb, &va) };
    let mut i = 0;
    while i < corta.len() && corta[i] == larga[i] {
        i += 1;
    }
    corta[i..] == larga[i + 1..]
}

/// Las líneas de cada archivo, compartidas entre todas las consolas del proceso (cada pregunta abre una): por banco y
/// ruta, válidas mientras el sha del archivo sea el mismo. Con tope de memoria: al pasarlo se vacía (se rellena sola).
#[derive(Default)]
struct LineasCompartidas {
    mapa: HashMap<(String, String), (String, Arc<Vec<String>>, usize)>,
    bytes: usize,
}

const TOPE_LINEAS_COMPARTIDAS: usize = 256 * 1024 * 1024;

static LINEAS_COMPARTIDAS: LazyLock<Mutex<LineasCompartidas>> = LazyLock::new(|| Mutex::new(LineasCompartidas::default()));

/// La consola sobre un banco (de solo lectura).
pub struct Consulta {
    pub raiz: String,
    pub ruta_db: String,
    c: Mutex<Connection>,
    contenido: Mutex<IndexMap<String, Arc<Vec<String>>>>,
}

fn ok_vacio<T>(r: Resultado<T>) -> Option<T> {
    r.ok()
}

impl Consulta {
    pub fn abrir(ruta_db: &str, raiz: &str) -> Resultado<Consulta> {
        let c = Banco::conectar_lectura(ruta_db)?;
        Ok(Consulta { raiz: raiz.to_string(), ruta_db: ruta_db.to_string(), c: Mutex::new(c), contenido: Mutex::new(IndexMap::new()) })
    }

    /// `_filas`.
    pub fn filas(&self, sql: &str, args: &[&dyn ToSql]) -> Resultado<Vec<Value>> {
        let c = self.c.lock().unwrap();
        let mut st = c.prepare_cached(sql).map_err(error)?;
        let v = st.query_map(args, fila_a_valor).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
        Ok(v)
    }

    fn uno(&self, sql: &str, args: &[&dyn ToSql]) -> Resultado<Option<Value>> {
        Ok(self.filas(sql, args)?.into_iter().next())
    }

    fn rutas_ordenadas(&self) -> Resultado<Vec<String>> {
        Ok(self.filas("SELECT ruta FROM archivos ORDER BY ruta", &[])?.iter().map(|f| s(&f["ruta"])).collect())
    }

    /// `_ruta`.
    pub fn ruta(&self, ruta: &str) -> Resultado<String> {
        let ruta = crate::py::cadena::lstrip_de(strip(ruta), "./").to_string();
        let existe = {
            let c = self.c.lock().unwrap();
            let mut st = c.prepare_cached("SELECT 1 FROM archivos WHERE ruta = ?").map_err(error)?;
            st.exists(params![ruta]).map_err(error)?
        };
        if existe {
            return Ok(ruta);
        }
        let como = format!("%{ruta}");
        let cands: Vec<String> = self.filas("SELECT ruta FROM archivos WHERE ruta LIKE ?", &[&como])?.iter().map(|f| s(&f["ruta"])).collect();
        if cands.len() == 1 {
            return Ok(cands[0].clone());
        }
        let mut m = format!("No está en el banco: {ruta}");
        if !cands.is_empty() {
            m.push_str(&format!(" (¿{}?)", cands.iter().take(6).cloned().collect::<Vec<_>>().join(", ")));
        }
        Err(clave_err(m))
    }

    /// `lineas`: el archivo sin numerar (caché de 400 archivos, el más viejo afuera).
    pub fn lineas(&self, ruta: &str) -> Resultado<Vec<String>> {
        Ok(self.lineas_arc(ruta)?.as_ref().clone())
    }

    /// Las líneas compartidas (sin copiar el archivo en cada consulta). Además de la caché de la consulta (como
    /// `_contenido` en Python), una del proceso por (banco, ruta, sha): cada pregunta abre una consulta nueva y antes
    /// descomprimía de nuevo todo el proyecto; el sha cambia si cambia el archivo, así que nunca da texto viejo.
    pub fn lineas_arc(&self, ruta: &str) -> Resultado<Arc<Vec<String>>> {
        let ruta = self.ruta(ruta)?;
        {
            let cache = self.contenido.lock().unwrap();
            if let Some(l) = cache.get(&ruta) {
                return Ok(l.clone());
            }
        }
        let sha: Option<String> = {
            let c = self.c.lock().unwrap();
            let mut st = c.prepare_cached("SELECT sha FROM archivos WHERE ruta = ?").map_err(error)?;
            st.query_row(params![ruta], |f| f.get::<_, Option<String>>(0)).ok().flatten()
        };
        let clave = (self.ruta_db.clone(), ruta.clone());
        let compartida = sha.as_ref().and_then(|s| {
            LINEAS_COMPARTIDAS.lock().unwrap().mapa.get(&clave).filter(|(sh, _, _)| sh == s).map(|(_, l, _)| l.clone())
        });
        let lineas = match compartida {
            Some(l) => l,
            None => {
                let blob: Option<Vec<u8>> = {
                    let c = self.c.lock().unwrap();
                    c.query_row("SELECT contenido FROM archivos WHERE ruta = ?", params![ruta], |f| f.get(0)).ok().flatten()
                };
                let texto = blob.map(|b| descomprimir(&b)).unwrap_or_default();
                let l: Arc<Vec<String>> = Arc::new(splitlines(&texto).into_iter().map(|x| x.to_string()).collect());
                if let Some(s) = sha {
                    // ~ el texto más lo que ocupa cada String
                    let tamano = l.iter().map(|x| x.len() + 24).sum::<usize>() + 64;
                    let mut g = LINEAS_COMPARTIDAS.lock().unwrap();
                    if let Some((_, _, viejo)) = g.mapa.remove(&clave) {
                        g.bytes -= viejo;
                    }
                    if g.bytes + tamano > TOPE_LINEAS_COMPARTIDAS {
                        g.mapa.clear();
                        g.bytes = 0;
                    }
                    g.bytes += tamano;
                    g.mapa.insert(clave, (s, l.clone(), tamano));
                }
                l
            }
        };
        let mut cache = self.contenido.lock().unwrap();
        cache.insert(ruta.clone(), lineas.clone());
        if cache.len() > 400 {
            cache.shift_remove_index(0);
        }
        Ok(lineas)
    }

    /// `leer(ruta, desde, hasta)` con desde y hasta ya normalizados (hasta = None → desde + 199).
    pub fn leer(&self, ruta: &str, desde: i64, hasta: Option<i64>) -> Resultado<String> {
        let lineas = self.lineas_arc(ruta)?;
        let desde = desde.max(1);
        let hasta = (lineas.len() as i64).min(hasta.unwrap_or(desde + 199));
        let mut salida = vec![];
        for n in desde..=hasta {
            salida.push(format!("{:>5}  {}", n, lineas[(n - 1) as usize]));
        }
        Ok(salida.join("\n"))
    }

    pub fn simbolos(&self, nombre: Option<&str>, ruta: Option<&str>, tipo: Option<&str>) -> Resultado<Vec<Value>> {
        let mut sql = "SELECT ruta, nombre, tipo, firma, doc, ini, fin FROM simbolos WHERE 1=1".to_string();
        let mut args: Vec<String> = vec![];
        if let Some(n) = nombre.filter(|x| !x.is_empty()) {
            sql.push_str(" AND (nombre LIKE ? OR corto LIKE ?)");
            args.push(n.to_string());
            args.push(n.to_string());
        }
        if let Some(r) = ruta.filter(|x| !x.is_empty()) {
            sql.push_str(" AND ruta = ?");
            args.push(self.ruta(r)?);
        }
        if let Some(t) = tipo.filter(|x| !x.is_empty()) {
            sql.push_str(" AND tipo = ?");
            args.push(t.to_string());
        }
        sql.push_str(" ORDER BY ruta, ini LIMIT 2000");
        let a: Vec<&dyn ToSql> = args.iter().map(|x| x as &dyn ToSql).collect();
        self.filas(&sql, &a)
    }

    pub fn codigo(&self, nombre: &str) -> Resultado<String> {
        let corto = nombre.rsplit('.').next().unwrap_or(nombre).to_string();
        let filas = self.filas("SELECT ruta, nombre, ini, fin FROM simbolos WHERE nombre = ? OR corto = ? ORDER BY (nombre = ?) DESC LIMIT 5", &[&nombre, &corto, &nombre])?;
        if filas.is_empty() {
            return Err(clave_err(format!("No hay ningún símbolo llamado «{nombre}»")));
        }
        let mut partes = vec![];
        for x in &filas {
            let ruta = s(&x["ruta"]);
            let cuerpo = self.leer(&ruta, x["ini"].as_i64().unwrap_or(1), Some(x["fin"].as_i64().unwrap_or(1)))?;
            partes.push(format!("# {}:{}-{} {}\n{}", ruta, s(&x["ini"]), s(&x["fin"]), s(&x["nombre"]), cuerpo));
        }
        Ok(partes.join("\n\n"))
    }

    /// `_simbolo_en`.
    pub fn simbolo_en(&self, ruta: &str, linea: i64) -> Resultado<Option<String>> {
        Ok(self
            .uno("SELECT nombre FROM simbolos WHERE ruta = ? AND ini <= ? AND fin >= ? ORDER BY fin - ini LIMIT 1", &[&ruta, &linea, &linea])?
            .map(|f| s(&f["nombre"])))
    }

    /// `hechos(s, r, o, limite)` (los valores ya como texto o None) con las lecturas literales de la clave.
    pub fn hechos(&self, sj: Option<&str>, r: Option<&str>, o: Option<&str>, limite: i64) -> Resultado<Vec<Value>> {
        let mut sql = "SELECT s, r, o, ruta, linea FROM grafo WHERE 1=1".to_string();
        let mut args: Vec<Value> = vec![];
        for (campo, valor) in [("s", sj), ("r", r), ("o", o)] {
            if let Some(v) = valor.filter(|x| !x.is_empty()) {
                sql.push_str(&format!(" AND {campo} LIKE ?"));
                args.push(Value::from(v));
            }
        }
        sql.push_str(" LIMIT ?");
        let textos: Vec<String> = args.iter().map(s).collect();
        let mut a: Vec<&dyn ToSql> = textos.iter().map(|x| x as &dyn ToSql).collect();
        a.push(&limite);
        let mut filas = self.filas(&sql, &a)?;
        if let (Some(r), Some(o)) = (r, o) {
            if (r == "lee_config" || r == "lee_entorno") && !o.is_empty() && !o.contains('%') && sj.map(|x| x.is_empty()).unwrap_or(true) {
                let ya: HashSet<(String, i64)> = filas.iter().map(|f| (s(&f["ruta"]), f["linea"].as_i64().unwrap_or(0))).collect();
                let (lee, escribe, _) = patrones_de_clave(o);
                let literal = Re::cache(&format!(r#"["'`]{}["'`]"#, Re::escapar(o)), "");
                for ruta in self.rutas_ordenadas()? {
                    if es_test(&ruta) {
                        continue;
                    }
                    for (k, linea) in self.lineas_arc(&ruta)?.iter().enumerate() {
                        let n = (k + 1) as i64;
                        if !linea.contains(o) || ya.contains(&(ruta.clone(), n)) || !literal.hay(linea) || escribe.hay(linea) || !lee.hay(linea) {
                            continue;
                        }
                        filas.push(json!({"s": self.simbolo_en(&ruta, n)?.unwrap_or_else(|| "(nivel de módulo)".into()), "r": r, "o": o,
                                          "ruta": ruta, "linea": n, "confianza": "texto: lectura literal de la clave"}));
                    }
                }
            }
        }
        filas.truncate(limite.max(0) as usize);
        Ok(filas)
    }

    /// `_nodos`: símbolos que casan con un nombre (completo, corto o «ruta:nombre»).
    pub fn nodos(&self, nombre: &str) -> Resultado<Vec<(String, String)>> {
        let par = |f: &Value| (s(&f["ruta"]), s(&f["nombre"]));
        if nombre.contains(':') && !nombre.starts_with('/') {
            let (ruta, n) = nombre.split_once(':').unwrap();
            let como = format!("%{ruta}");
            return Ok(self.filas("SELECT ruta, nombre FROM simbolos WHERE ruta LIKE ? AND (nombre = ? OR corto = ?)", &[&como, &n, &n])?.iter().map(par).collect());
        }
        let filas: Vec<(String, String)> = self.filas("SELECT ruta, nombre FROM simbolos WHERE nombre = ?", &[&nombre])?.iter().map(par).collect();
        if !filas.is_empty() {
            return Ok(filas);
        }
        let corto = nombre.rsplit('.').next().unwrap_or(nombre).to_string();
        Ok(self.filas("SELECT ruta, nombre FROM simbolos WHERE corto = ?", &[&corto])?.iter().map(par).collect())
    }

    fn ubicacion(&self, nodo: &(String, String)) -> Resultado<String> {
        Ok(match self.uno("SELECT ini FROM simbolos WHERE ruta = ? AND nombre = ?", &[&nodo.0, &nodo.1])? {
            Some(f) => format!("{}:{}", nodo.0, s(&f["ini"])),
            None => nodo.0.clone(),
        })
    }

    fn salientes(&self, nodo: &(String, String)) -> Resultado<Vec<(String, String)>> {
        Ok(self
            .filas("SELECT DISTINCT a_ruta, a_nombre FROM llamadas WHERE ruta = ? AND desde = ? ORDER BY linea", &[&nodo.0, &nodo.1])?
            .iter()
            .map(|f| (s(&f["a_ruta"]), s(&f["a_nombre"])))
            .collect())
    }

    fn entrantes(&self, nodo: &(String, String)) -> Resultado<Vec<Value>> {
        self.filas("SELECT ruta, desde, linea, confianza FROM llamadas WHERE a_ruta = ? AND a_nombre = ? ORDER BY ruta, linea", &[&nodo.0, &nodo.1])
    }

    /// `llamadores`: aristas resueltas y, marcadas «texto: …», las llamadas que el grafo no resuelve.
    pub fn llamadores(&self, nombre: &str) -> Resultado<Vec<Value>> {
        let nodos = self.nodos(nombre)?;
        let mut resueltos = vec![];
        for n in &nodos {
            for f in self.entrantes(n)? {
                resueltos.push(json!({"s": f["desde"], "ruta": f["ruta"], "linea": f["linea"], "confianza": f["confianza"], "a": n.1}));
            }
        }
        let por_texto = self.llamadores_por_texto(nombre, &nodos, &resueltos, 30)?;
        resueltos.extend(por_texto);
        Ok(resueltos)
    }

    fn llamadores_por_texto(&self, nombre: &str, nodos: &[(String, String)], resueltos: &[Value], maximo: usize) -> Resultado<Vec<Value>> {
        let corto = nombre.rsplit('.').next().unwrap_or("").rsplit(':').next().unwrap_or("").to_string();
        static NOMBRE: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^[A-Za-z_]\w*$", ""));
        if largo(&corto) < 4 || !NOMBRE.hay(&corto) {
            return Ok(vec![]);
        }
        let e = Re::escapar(&corto);
        let calificada = Re::cache(&format!(r"[\w)\]]\s*\.\s*{e}\s*\("), "");
        let como_valor = Re::cache(&format!(r"(?:[(,=:\[]|^)\s*(?:[A-Za-z_]\w*\s*\.\s*)+{e}\s*[,)\]]"), "");
        let como_valor_suelto = Re::cache(&format!(r"[(,=\[]\s*{e}\s*[,)\]]"), "");
        let raiz_valor = Re::cache(&format!(r"(?<![\w.])([A-Za-z_]\w*)\s*\.(?:\s*[A-Za-z_]\w*\s*\.)*\s*{e}\s*[,)\]]"), "");
        let receptor = Re::cache(&format!(r"(?<![\w.])([A-Za-z_]\w*)\s*\.\s*{e}\s*\("), "");
        let fabrica = Re::cache(&format!(r"(?<![\w.])([A-Za-z_]\w*)\s*\(\s*\)\s*\.\s*{e}\s*\("), "");
        let definidas: HashSet<&str> = nodos.iter().map(|n| n.0.as_str()).collect();
        let modulos: HashSet<String> = definidas.iter().map(|r| splitext(basename(r)).0.to_string()).collect();
        let clases_propias: HashSet<String> = nodos.iter().filter(|n| n.1.contains('.')).map(|n| n.1.rsplit_once('.').unwrap().0.to_string()).collect();
        let suelta = Re::cache(&format!(r"(?<![\w.]){e}\s*\("), "");
        let definicion = Re::cache(&format!(r"^\s*(?:async\s+)?(?:def|function|class)\s+{e}\b|\b{e}\s*[:=]\s*(?:async\s+)?(?:function|\()"), "");
        static T_RET: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"->\s*['"]?([A-Z]\w*)"#, ""));
        let ya: HashSet<(String, i64)> = resueltos.iter().map(|r| (s(&r["ruta"]), r["linea"].as_i64().unwrap_or(0))).collect();
        let distintos: HashSet<&(String, String)> = nodos.iter().collect();
        let homonimas = distintos.len() > 1 || {
            let n: i64 = self.uno("SELECT COUNT(*) n FROM simbolos WHERE corto = ?", &[&corto])?.and_then(|f| f["n"].as_i64()).unwrap_or(0);
            n > 1
        };
        let mut extensiones: HashSet<&str> = HashSet::new();
        for n in nodos {
            let ext = splitext(&n.0).1;
            match ext {
                ".py" => {
                    extensiones.insert(".py");
                }
                ".js" | ".jsx" | ".ts" | ".tsx" | ".mjs" | ".vue" => extensiones.extend(FAMILIA_JS),
                _ => {}
            }
        }
        let mut salida = vec![];
        for ruta in self.rutas_ordenadas()? {
            if !extensiones.is_empty() && !extensiones.iter().any(|e| ruta.ends_with(e)) {
                continue;
            }
            let Some(lineas) = ok_vacio(self.lineas_arc(&ruta)) else { continue };
            let mut importados: Option<HashSet<String>> = None;
            let mut instancias: Option<HashMap<String, String>> = None;
            for (k, linea) in lineas.iter().enumerate() {
                let n = (k + 1) as i64;
                if !linea.contains(corto.as_str()) || ya.contains(&(ruta.clone(), n)) || definicion.hay(linea) {
                    continue;
                }
                let codigo = if ruta.ends_with(".py") { linea.split('#').next().unwrap_or("") } else { linea.as_str() };
                let codigo = CADENA.sub("\"\"", codigo).into_owned();
                let (mut resuelta, mut raiz) = (false, String::new());
                let tipo: String;
                if calificada.hay(&codigo) {
                    let mut t = "llamada por atributo".to_string();
                    let m = receptor.buscar(&codigo);
                    raiz = m.as_ref().map(|m| m.g(1).to_string()).unwrap_or_default();
                    let fab = if m.is_some() { None } else { fabrica.buscar(&codigo) };
                    if let Some(fab) = fab {
                        let f1 = fab.g(1).to_string();
                        let firma = self.uno("SELECT firma FROM simbolos WHERE nombre = ? LIMIT 1", &[&f1])?;
                        let texto_firma = firma.map(|f| f["firma"].as_str().unwrap_or("").to_string()).unwrap_or_default();
                        if let Some(tr) = T_RET.buscar(&texto_firma) {
                            let clase = tr.g(1).to_string();
                            if clases_propias.contains(&clase) {
                                t = format!("llamada por atributo (instancia de {clase})");
                                resuelta = true;
                            } else if self.uno("SELECT 1 FROM simbolos WHERE nombre = ?", &[&format!("{clase}.{corto}")])?.is_some() {
                                continue;
                            }
                        }
                    }
                    if let Some(m) = &m {
                        let g1 = m.g(1).to_string();
                        if !["self", "cls", "this", "super"].contains(&g1.as_str()) {
                            if instancias.is_none() {
                                instancias = Some(instancias_de(&lineas));
                            }
                            let clase = instancias.as_ref().unwrap().get(&g1).cloned();
                            match clase {
                                Some(c) if clases_propias.contains(&c) => {
                                    t = format!("llamada por atributo (instancia de {c})");
                                    resuelta = true;
                                }
                                Some(c) if !c.is_empty() => {
                                    if self.uno("SELECT 1 FROM simbolos WHERE nombre = ?", &[&format!("{c}.{corto}")])?.is_some() {
                                        continue;
                                    }
                                }
                                _ => {
                                    if !modulos.contains(&g1) {
                                        let (p1, p2) = (format!("%/{g1}.%"), format!("{g1}.%"));
                                        let otras: Vec<(String, String)> = self
                                            .filas("SELECT ruta, nombre FROM simbolos WHERE corto = ? AND nombre = ? AND (ruta LIKE ? OR ruta LIKE ?)", &[&corto, &corto, &p1, &p2])?
                                            .iter()
                                            .map(|x| (s(&x["ruta"]), s(&x["nombre"])))
                                            .collect();
                                        if !otras.is_empty() && !otras.iter().any(|o| nodos.contains(o)) {
                                            continue;
                                        }
                                    }
                                }
                            }
                        }
                    }
                    tipo = t;
                } else if como_valor.hay(&codigo) {
                    let m = raiz_valor.buscar(&codigo);
                    raiz = m.map(|m| m.g(1).to_string()).unwrap_or_default();
                    let primera_mayus = raiz.chars().next().map(|c| es_mayuscula(&c.to_string())).unwrap_or(false);
                    if !raiz.is_empty() && !(primera_mayus || modulos.contains(&raiz) || (["self", "cls", "this"].contains(&raiz.as_str()) && definidas.contains(ruta.as_str()))) {
                        if importados.is_none() {
                            importados = Some(nombres_importados(&lineas));
                        }
                        if !importados.as_ref().unwrap().contains(&raiz) {
                            continue;
                        }
                    }
                    tipo = "pasada como valor".into();
                } else if definidas.contains(ruta.as_str()) && como_valor_suelto.hay(&codigo) {
                    tipo = "pasada como valor".into();
                } else if resueltos.is_empty() && suelta.hay(&codigo) {
                    tipo = "llamada directa".into();
                } else {
                    continue;
                }
                let del_modulo = !raiz.is_empty() && (modulos.contains(&raiz) || modulo_de_alias(&lineas, &raiz).map(|m| modulos.contains(&m)).unwrap_or(false));
                let hom = homonimas && !resuelta;
                salida.push(json!({
                    "s": self.simbolo_en(&ruta, n)?.unwrap_or_else(|| "(nivel de módulo)".into()), "ruta": ruta, "linea": n,
                    "confianza": format!("texto: {tipo}, sin resolver{}", if hom { " (hay homónimas: puede ser otra)" } else { "" }),
                    "a": corto, "codigo": primeros(strip(linea), 140), "homonimas": hom, "del_modulo": del_modulo,
                }));
                if salida.len() >= maximo {
                    return Ok(salida);
                }
            }
        }
        Ok(salida)
    }

    pub fn llamados(&self, simbolo: &str) -> Resultado<Vec<Value>> {
        let mut salida = vec![];
        for n in self.nodos(simbolo)? {
            for d in self.salientes(&n)? {
                salida.push(json!({"o": d.1, "ruta": d.0}));
            }
        }
        Ok(salida)
    }

    fn camino_nodos(&self, desde: &str, hasta: &str, maximo: i64) -> Resultado<Option<Vec<(String, String)>>> {
        let destinos: HashSet<(String, String)> = self.nodos(hasta)?.into_iter().collect();
        let mut previo: IndexMap<(String, String), Option<(String, String)>> = IndexMap::new();
        for n in self.nodos(desde)? {
            previo.insert(n, None);
        }
        let mut frontera: Vec<(String, String)> = previo.keys().cloned().collect();
        for _ in 0..maximo.max(0) {
            let mut nueva = vec![];
            for nodo in &frontera {
                for sig in self.salientes(nodo)? {
                    if previo.contains_key(&sig) {
                        continue;
                    }
                    previo.insert(sig.clone(), Some(nodo.clone()));
                    if destinos.contains(&sig) {
                        let mut cadena = vec![sig.clone()];
                        while let Some(Some(p)) = previo.get(cadena.last().unwrap()) {
                            cadena.push(p.clone());
                        }
                        cadena.reverse();
                        return Ok(Some(cadena));
                    }
                    nueva.push(sig);
                }
            }
            frontera = nueva;
        }
        Ok(None)
    }

    pub fn camino(&self, desde: &str, hasta: &str, maximo: i64) -> Resultado<Option<Vec<String>>> {
        match self.camino_nodos(desde, hasta, maximo)? {
            Some(c) if !c.is_empty() => Ok(Some(c.iter().map(|n| Ok(format!("{} ({})", n.1, self.ubicacion(n)?))).collect::<Resultado<Vec<_>>>()?)),
            _ => Ok(None),
        }
    }

    pub fn camino_con_llamadas(&self, desde: &str, hasta: &str, maximo: i64) -> Resultado<Option<Vec<Value>>> {
        let Some(cadena) = self.camino_nodos(desde, hasta, maximo)?.filter(|c| !c.is_empty()) else { return Ok(None) };
        let mut saltos = vec![json!({"simbolo": cadena[0].1, "en": self.ubicacion(&cadena[0])?, "nodo": [cadena[0].0, cadena[0].1]})];
        for par in cadena.windows(2) {
            let (previo, nodo) = (&par[0], &par[1]);
            let f = self.uno(
                "SELECT linea FROM llamadas WHERE ruta = ? AND desde = ? AND a_ruta = ? AND a_nombre = ? ORDER BY linea LIMIT 1",
                &[&previo.0, &previo.1, &nodo.0, &nodo.1],
            )?;
            let mut salto = json!({"simbolo": nodo.1, "en": self.ubicacion(nodo)?, "nodo": [nodo.0, nodo.1]});
            if let Some(f) = f {
                let linea = f["linea"].as_i64().unwrap_or(0);
                let codigo = match self.lineas_arc(&previo.0) {
                    Ok(l) if linea >= 1 && (linea as usize) <= l.len() => strip(&l[(linea - 1) as usize]).to_string(),
                    Ok(l) if linea <= 0 && !l.is_empty() => {
                        // índice negativo de Python: desde el final
                        let i = l.len() as i64 + linea - 1;
                        if i >= 0 { strip(&l[i as usize]).to_string() } else { String::new() }
                    }
                    _ => String::new(),
                };
                let o = salto.as_object_mut().unwrap();
                o.insert("llamada".into(), Value::from(format!("{}:{}", previo.0, linea)));
                o.insert("linea".into(), Value::from(linea));
                o.insert("codigo".into(), Value::from(primeros(&codigo, 160)));
            }
            saltos.push(salto);
        }
        Ok(Some(saltos))
    }

    /// `codigo_del_salto`: la función intermedia, entera si es corta; si no, firma y la línea de la llamada.
    pub fn codigo_del_salto(&self, nodo: &(String, String), linea_llamada: Option<i64>, maximo: i64) -> Resultado<String> {
        let Some(f) = self.uno("SELECT ini, fin FROM simbolos WHERE ruta = ? AND nombre = ?", &[&nodo.0, &nodo.1])? else { return Ok(String::new()) };
        let Some(lineas) = ok_vacio(self.lineas_arc(&nodo.0)) else { return Ok(String::new()) };
        let ini = f["ini"].as_i64().unwrap_or(1);
        let fin = f["fin"].as_i64().unwrap_or(1).min(lineas.len() as i64);
        let elegidas: Vec<i64> = match linea_llamada.filter(|x| *x != 0) {
            Some(ll) if fin - ini + 1 > maximo => {
                let mut c: BTreeSet<i64> = (ini.max(ll - 1)..=fin.min(ll + 1)).collect();
                c.insert(ini);
                c.into_iter().collect()
            }
            _ => (ini..=fin.min(ini + maximo - 1)).collect(),
        };
        let mut salida = vec![];
        let mut anterior: Option<i64> = None;
        for n in elegidas {
            if let Some(a) = anterior {
                if n > a + 1 {
                    salida.push("      …".to_string());
                }
            }
            let l = if n >= 1 { lineas.get((n - 1) as usize).map(|x| rstrip(x).to_string()).unwrap_or_default() } else { String::new() };
            salida.push(format!("{:>6}  {}", n, l));
            anterior = Some(n);
        }
        Ok(salida.join("\n"))
    }

    pub fn ficha(&self, nombre: &str) -> Resultado<Value> {
        let nodos = self.nodos(nombre)?;
        let Some(nodo) = nodos.first() else { return Err(clave_err(format!("No hay ningún símbolo llamado «{nombre}»"))) };
        let x = self.uno("SELECT ruta, nombre, tipo, firma, doc, ini, fin FROM simbolos WHERE ruta = ? AND nombre = ?", &[&nodo.0, &nodo.1])?.unwrap_or(Value::Null);
        let ruta = s(&x["ruta"]);
        let archivo = self.uno("SELECT COALESCE(resumen_ia, resumen) r FROM archivos WHERE ruta = ?", &[&ruta])?;
        let llamado_por: Vec<String> = self
            .entrantes(nodo)?
            .iter()
            .map(|f| format!("{} ({}:{}){}", s(&f["desde"]), s(&f["ruta"]), s(&f["linea"]), if f["confianza"].as_str() == Some("exacta") { "" } else { " ?" }))
            .take(40)
            .collect();
        let llama_a: Vec<String> = self.salientes(nodo)?.iter().map(|d| format!("{} ({})", d.1, d.0)).take(40).collect();
        let nombre_s = s(&x["nombre"]);
        let hechos: Vec<String> = self.filas("SELECT r, o FROM hechos WHERE s = ? AND ruta = ? LIMIT 60", &[&nombre_s, &ruta])?.iter().map(|h| format!("{} {}", s(&h["r"]), s(&h["o"]))).collect();
        let como = format!("%\"{ruta}\"%");
        let notas: Vec<String> = self
            .filas("SELECT tipo, titulo, texto FROM conocimiento WHERE rutas LIKE ? LIMIT 8", &[&como])?
            .iter()
            .map(|f| format!("({}) {}: {}", s(&f["tipo"]), s(&f["titulo"]), primeros(&s(&f["texto"]), 200)))
            .collect();
        let doc = x["doc"].as_str().unwrap_or("").to_string();
        Ok(json!({
            "simbolo": format!("{} ({}) {}:{}-{}", nombre_s, s(&x["tipo"]), ruta, s(&x["ini"]), s(&x["fin"])),
            "firma": x["firma"], "doc": primeros(&doc, 400),
            "otros_con_ese_nombre": nodos.iter().skip(1).take(7).map(|n| format!("{}:{}", n.0, n.1)).collect::<Vec<_>>(),
            "llamado_por": llamado_por, "llama_a": llama_a, "hechos": hechos,
            "archivo": archivo.map(|a| a["r"].clone()).unwrap_or(Value::from("")),
            "notas": notas,
        }))
    }

    fn inicio(&self, inicio: &str) -> Resultado<Vec<(String, String)>> {
        if inicio.contains("/api") || inicio.starts_with('/') {
            let ruta = ruta_http_canonica(crate::py::cadena::tras_primero(inicio, " "));
            let como = format!("% {ruta}");
            return Ok(self.filas("SELECT s, ruta FROM hechos WHERE r = 'expone' AND o LIKE ?", &[&como])?.iter().map(|h| (s(&h["ruta"]), s(&h["s"]))).collect());
        }
        Ok(self.nodos(inicio)?.into_iter().take(1).collect())
    }

    pub fn recorrido(&self, inicio: &str, profundidad: i64, maximo: usize) -> Resultado<String> {
        let mut lineas: Vec<String> = vec![];
        let mut vistos: HashSet<(String, String)> = HashSet::new();
        fn bajar(c: &Consulta, nodo: &(String, String), nivel: i64, profundidad: i64, maximo: usize, lineas: &mut Vec<String>, vistos: &mut HashSet<(String, String)>) -> Resultado<()> {
            if lineas.len() >= maximo {
                return Ok(());
            }
            let repetido = vistos.contains(nodo);
            lineas.push(format!("{}{}  {}{}", "  ".repeat(nivel as usize), nodo.1, c.ubicacion(nodo)?, if repetido { "  (ya visto)" } else { "" }));
            if repetido || nivel >= profundidad {
                return Ok(());
            }
            vistos.insert(nodo.clone());
            for sig in c.salientes(nodo)? {
                bajar(c, &sig, nivel + 1, profundidad, maximo, lineas, vistos)?;
            }
            Ok(())
        }
        let inicios = self.inicio(inicio)?;
        if inicios.is_empty() {
            return Err(clave_err(format!("No encontré «{inicio}» (ni como símbolo ni como endpoint)")));
        }
        for nodo in &inicios {
            bajar(self, nodo, 0, profundidad, maximo, &mut lineas, &mut vistos)?;
        }
        Ok(lineas.join("\n") + if lineas.len() >= maximo { "\n[… recortado]" } else { "" })
    }

    pub fn impacto(&self, nombre: &str, profundidad: i64) -> Resultado<Value> {
        let mut afectados: IndexMap<(String, String), i64> = IndexMap::new();
        let mut frontera: Vec<(String, String)> = self.nodos(nombre)?.into_iter().take(1).collect();
        for nivel in 1..=profundidad.max(0) {
            let mut nueva = vec![];
            for nodo in &frontera {
                for f in self.entrantes(nodo)? {
                    let clave = (s(&f["ruta"]), s(&f["desde"]));
                    if !afectados.contains_key(&clave) {
                        afectados.insert(clave.clone(), nivel);
                        nueva.push(clave);
                    }
                }
            }
            frontera = nueva;
        }
        let mut todos: Vec<(String, String)> = afectados.keys().cloned().collect();
        todos.extend(self.nodos(nombre)?.into_iter().take(1));
        let mut endpoints: BTreeSet<String> = BTreeSet::new();
        for (r, sj) in &todos {
            for h in self.filas("SELECT o FROM hechos WHERE r = 'expone' AND s = ? AND ruta = ?", &[sj, r])? {
                endpoints.insert(s(&h["o"]));
            }
        }
        let mut consumidores: BTreeSet<String> = BTreeSet::new();
        for e in &endpoints {
            let ruta = crate::py::cadena::split1(e, " ").get(1).map(|x| x.to_string()).unwrap_or_default();
            for h in self.filas("SELECT s, ruta FROM hechos WHERE r = 'llama_api' AND o = ?", &[&ruta])? {
                consumidores.insert(format!("{} ({})", s(&h["s"]), s(&h["ruta"])));
            }
        }
        let es_t = |r: &str| r.contains("/tests/") || basename(r).starts_with("test_");
        let mut orden: Vec<(String, String)> = afectados.keys().cloned().collect();
        orden.sort_by(|a, b| (afectados[a], a).cmp(&(afectados[b], b)));
        let endpoints: Vec<String> = endpoints.into_iter().collect();
        let por_texto: Vec<Value> = match self.alcance_por_texto(nombre, 3, 15) {
            Ok(v) => v.into_iter().filter(|x| !endpoints.contains(&s(&x["endpoint"]))).collect(),
            Err(_) => vec![],
        };
        let tests: BTreeSet<String> = afectados.keys().filter(|n| es_t(&n.0)).map(|n| n.1.clone()).collect();
        Ok(json!({
            "llamadores": orden.iter().filter(|n| !es_t(&n.0)).map(|n| format!("{} ({}) nivel {}", n.1, n.0, afectados[n])).take(80).collect::<Vec<_>>(),
            "tests": tests.into_iter().take(40).collect::<Vec<_>>(),
            "total": afectados.len(), "endpoints": endpoints,
            "frontend": consumidores.into_iter().collect::<Vec<_>>(),
            "endpoints_por_texto": por_texto.iter().map(|x| format!("{} (vía {})", s(&x["endpoint"]), x["via"].as_array().map(|v| v.iter().map(s).collect::<Vec<_>>().join(" → ")).unwrap_or_default())).collect::<Vec<_>>(),
        }))
    }

    pub fn alcance_por_texto(&self, nombre: &str, profundidad: i64, maximo: i64) -> Resultado<Vec<Value>> {
        let mut visto: HashSet<(String, String)> = self.nodos(nombre)?.into_iter().take(3).collect();
        // set(...) de Python: el orden de la frontera inicial es el de los nodos (sin repetir)
        let mut iniciales: Vec<(String, String)> = vec![];
        for n in self.nodos(nombre)?.into_iter().take(3) {
            if !iniciales.contains(&n) {
                iniciales.push(n);
            }
        }
        let mut frontera: Vec<((String, String), Vec<String>)> = iniciales.into_iter().map(|n| (n, vec![])).collect();
        let mut salida: BTreeMap<String, Vec<String>> = BTreeMap::new();
        let mut buscados = 0;
        for _ in 0..profundidad.max(0) {
            let mut nueva = vec![];
            for (nodo, via) in &frontera {
                if buscados >= maximo {
                    break;
                }
                buscados += 1;
                for c in self.llamadores(&format!("{}:{}", nodo.0, nodo.1))? {
                    let sig = (s(&c["ruta"]), s(&c["s"]));
                    if visto.contains(&sig) || sig.1 == "(nivel de módulo)" || es_test(&sig.0) {
                        continue;
                    }
                    if c.get("homonimas").and_then(|v| v.as_bool()).unwrap_or(false) && !c.get("del_modulo").and_then(|v| v.as_bool()).unwrap_or(false) {
                        continue;
                    }
                    visto.insert(sig.clone());
                    let mut camino = via.clone();
                    camino.push(sig.1.clone());
                    for h in self.filas("SELECT o FROM hechos WHERE r = 'expone' AND s = ? AND ruta = ?", &[&sig.1, &sig.0])? {
                        salida.entry(s(&h["o"])).or_insert_with(|| camino.clone());
                    }
                    nueva.push((sig, camino));
                }
            }
            frontera = nueva;
        }
        Ok(salida.into_iter().map(|(e, v)| json!({"endpoint": e, "via": v})).collect())
    }

    pub fn donde(&self, x: &str, maximo: usize) -> Resultado<Value> {
        let x = strip_de(strip(x), "`").to_string();
        let mut salida = Map::new();
        salida.insert("x".into(), Value::from(x.clone()));
        static METODO: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^(GET|POST|PUT|DELETE|PATCH) /", ""));
        if x.starts_with('/') || METODO.hay(&x) {
            salida.insert("endpoint".into(), self.api(crate::py::cadena::tras_primero(&x, " "))?);
        }
        let mut por_relacion: IndexMap<String, Vec<String>> = IndexMap::new();
        let como = format!("% {x}");
        for h in self.filas("SELECT s, r, o, ruta, linea FROM hechos WHERE o = ? OR o LIKE ? LIMIT 400", &[&x, &como])? {
            por_relacion.entry(s(&h["r"])).or_default().push(format!("{} ({}:{})", s(&h["s"]), s(&h["ruta"]), s(&h["linea"])));
        }
        if !por_relacion.is_empty() {
            let m: Map<String, Value> = por_relacion.into_iter().map(|(r, v)| (r, Value::from(v.into_iter().take(maximo).collect::<Vec<_>>()))).collect();
            salida.insert("hechos".into(), Value::Object(m));
        }
        let corto = x.rsplit('.').next().unwrap_or(&x).to_string();
        let simbolos = self.filas("SELECT ruta, nombre, tipo, ini FROM simbolos WHERE nombre = ? OR corto = ? LIMIT 10", &[&x, &corto])?;
        if !simbolos.is_empty() {
            salida.insert("simbolos".into(), Value::from(simbolos.iter().map(|y| format!("{} ({}) {}:{}", s(&y["nombre"]), s(&y["tipo"]), s(&y["ruta"]), s(&y["ini"]))).collect::<Vec<_>>()));
        }
        let literal = Re::cache(&format!(r#"["'`]{}["'`/]"#, Re::escapar(&x)), "");
        let mut apariciones = vec![];
        'archivos: for ruta in self.rutas_ordenadas()? {
            for (k, linea) in self.lineas_arc(&ruta)?.iter().enumerate() {
                if linea.contains(x.as_str()) && literal.hay(linea) {
                    apariciones.push(format!("{}:{}: {}", ruta, k + 1, primeros(strip(linea), 160)));
                    if apariciones.len() >= maximo {
                        break;
                    }
                }
            }
            if apariciones.len() >= maximo {
                break 'archivos;
            }
        }
        if !apariciones.is_empty() {
            salida.insert("como_texto".into(), Value::from(apariciones));
        }
        Ok(Value::Object(salida))
    }

    pub fn api(&self, ruta_http: &str) -> Resultado<Value> {
        let (metodo, _, resto) = crate::py::cadena::partition(strip(ruta_http), " ");
        let es_metodo = !resto.is_empty() && crate::py::cadena::es_alfabetico(metodo) && es_mayuscula(metodo);
        let (ruta, patron) = if es_metodo {
            let r = ruta_http_canonica(strip(resto));
            (r.clone(), format!("{metodo} {r}"))
        } else {
            let r = ruta_http_canonica(ruta_http);
            (r.clone(), format!("% {r}"))
        };
        let mut expone = self.filas("SELECT s, o, ruta, linea FROM grafo WHERE r = 'expone' AND o LIKE ?", &[&patron])?;
        let mut consume = self.filas("SELECT s, o, ruta, linea FROM grafo WHERE r = 'llama_api' AND o = ?", &[&ruta])?;
        if expone.is_empty() {
            let todas = self.filas("SELECT s, o, ruta, linea FROM grafo WHERE r = 'expone'", &[])?;
            let expuestas: HashSet<String> = todas.iter().map(|f| crate::py::cadena::tras_primero(&s(&f["o"]), " ").to_string()).collect();
            let e = endpoint_de(&ruta, expuestas.iter().map(|x| x.as_str()));
            expone = todas
                .into_iter()
                .filter(|f| {
                    let o = s(&f["o"]);
                    e.as_deref().map(|e| crate::py::cadena::split1(&o, " ").get(1).copied() == Some(e)).unwrap_or(false)
                        && (!patron.starts_with('%') && o.starts_with(&format!("{metodo} ")) || patron.starts_with('%'))
                })
                .collect();
        }
        if consume.is_empty() {
            let como = format!("%{ruta}");
            consume = self
                .filas("SELECT s, o, ruta, linea FROM grafo WHERE r = 'llama_api' AND o LIKE ?", &[&como])?
                .into_iter()
                .filter(|f| endpoint_de(&s(&f["o"]), [ruta.as_str()]).as_deref() == Some(ruta.as_str()))
                .collect();
        }
        Ok(json!({"expone": expone, "consume": consume}))
    }

    pub fn cambios(&self, desde_version: Option<i64>) -> Resultado<Vec<Value>> {
        let desde = match desde_version {
            Some(v) => v,
            None => self.uno("SELECT valor FROM meta WHERE clave = 'version'", &[])?.and_then(|v| s(&v["valor"]).trim().parse::<i64>().ok()).map(|v| (v - 20).max(0)).unwrap_or(0),
        };
        let mut filas = self.filas("SELECT version, ruta, tipo, cuando, simbolos, mas, menos FROM cambios WHERE version > ? ORDER BY id DESC LIMIT 300", &[&desde])?;
        for f in filas.iter_mut() {
            let sim = loads(f["simbolos"].as_str().filter(|x| !x.is_empty()).unwrap_or("{}")).unwrap_or(Value::Object(Map::new()));
            f.as_object_mut().unwrap().insert("simbolos".into(), sim);
        }
        Ok(filas)
    }

    pub fn diff(&self, ruta: &str) -> Resultado<String> {
        let ruta = self.ruta(ruta)?;
        let filas = self.filas("SELECT cuando, diff FROM cambios WHERE ruta = ? AND diff != '' ORDER BY id DESC LIMIT 3", &[&ruta])?;
        let t = filas.iter().map(|f| format!("# {}\n{}", s(&f["cuando"]), s(&f["diff"]))).collect::<Vec<_>>().join("\n\n");
        Ok(if t.is_empty() { "Sin diffs registrados.".into() } else { t })
    }

    pub fn memoria_toda(&self) -> Resultado<Vec<Value>> {
        self.filas("SELECT id, tipo, titulo, texto, rutas, origen, revisar FROM conocimiento ORDER BY actualizado DESC LIMIT 200", &[])
    }

    pub fn resoluciones_todas(&self) -> Resultado<Vec<Value>> {
        self.filas("SELECT id, pregunta, resumen, rutas, cuando FROM resoluciones ORDER BY id DESC LIMIT 50", &[])
    }

    pub fn resumenes(&self, nivel: Option<&str>) -> Resultado<Vec<Value>> {
        match nivel.filter(|n| !n.is_empty()) {
            Some(n) => self.filas("SELECT nivel, clave, texto FROM resumenes WHERE nivel = ? ORDER BY clave", &[&n]),
            None => self.filas("SELECT nivel, clave, texto FROM resumenes ORDER BY nivel, clave", &[]),
        }
    }

    // ------------------------------------------------------------------ hechos de una pregunta

    /// `_asignaciones_de`: dónde se asigna `nombre` a nivel de módulo (primero en los archivos nombrados).
    pub fn asignaciones_de(&self, nombre: &str, rutas: &[String], maximo: usize) -> Resultado<Vec<String>> {
        static NOMBRE: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^[A-Za-z_$][\w$]*$", ""));
        if !NOMBRE.hay(nombre) {
            return Ok(vec![]);
        }
        let e = Re::escapar(nombre);
        let patron = Re::cache(&format!(r"^{e}\s*(?::[^=]+)?=(?!=)|^\s*(?:export\s+)?(?:const|let|var)\s+{e}\s*="), "");
        let todas: Vec<String> = self.rutas_ordenadas()?.into_iter().filter(|r| !es_test(r)).collect();
        let propias: Vec<String> = todas.iter().filter(|r| !rutas.is_empty() && rutas.iter().any(|x| *r == x || r.ends_with(&format!("/{x}")))).cloned().collect();
        let mut grupos = vec![];
        if !propias.is_empty() {
            grupos.push(propias);
        }
        grupos.push(todas);
        for grupo in grupos {
            let mut salida = vec![];
            for ruta in &grupo {
                let Some(lineas) = ok_vacio(self.lineas_arc(ruta)) else { continue };
                for (k, linea) in lineas.iter().enumerate() {
                    if linea.contains(nombre) && patron.hay(linea) {
                        salida.push(format!("{}:{}: {}", ruta, k + 1, primeros(strip(linea), 120)));
                        if salida.len() >= maximo {
                            return Ok(salida);
                        }
                    }
                }
            }
            if !salida.is_empty() {
                return Ok(salida);
            }
        }
        Ok(vec![])
    }

    fn cadenas_del_codigo(&self, extensiones: &[&str]) -> Resultado<IndexMap<String, Vec<String>>> {
        let mut salida: IndexMap<String, Vec<String>> = IndexMap::new();
        for ruta in self.rutas_ordenadas()? {
            if !extensiones.iter().any(|e| ruta.ends_with(e)) || es_test(&ruta) {
                continue;
            }
            let Some(lineas) = ok_vacio(self.lineas_arc(&ruta)) else { continue };
            for (k, linea) in lineas.iter().enumerate() {
                if !linea.contains('"') && !linea.contains('\'') {
                    continue;
                }
                for nombre in cadenas_nombre(linea) {
                    let lugar = format!("{}:{}", ruta, k + 1);
                    let lugares = salida.entry(nombre.to_string()).or_default();
                    if lugares.last() != Some(&lugar) {
                        lugares.push(lugar);
                    }
                }
            }
        }
        Ok(salida)
    }

    /// `_claves_sospechosas`: una clave leída que aparece una sola vez y difiere en una letra de otra que aparece
    /// en varios lugares.
    pub fn claves_sospechosas(&self, claves: &[String], por_familia: &mut HashMap<Vec<String>, IndexMap<String, Vec<String>>>) -> Resultado<Vec<String>> {
        let mut vistas = HashSet::new();
        let claves: Vec<&String> = claves.iter().filter(|k| vistas.insert(k.as_str())).filter(|k| largo(k) >= 6).collect();
        let mut salida = vec![];
        for k in claves {
            let fila = self.uno("SELECT ruta FROM hechos WHERE r IN ('lee_config', 'lee_entorno') AND o = ? LIMIT 1", &[k])?;
            let ext = match &fila {
                Some(f) => splitext(&s(&f["ruta"])).1.to_string(),
                None => ".py".to_string(),
            };
            let familia: Vec<String> = if FAMILIA_JS.contains(&ext.as_str()) { FAMILIA_JS.iter().map(|x| x.to_string()).collect() } else { vec![ext] };
            if !por_familia.contains_key(&familia) {
                let refs: Vec<&str> = familia.iter().map(|x| x.as_str()).collect();
                let c = self.cadenas_del_codigo(&refs)?;
                por_familia.insert(familia.clone(), c);
            }
            let cadenas = &por_familia[&familia];
            let a = cadenas.get(k.as_str()).cloned().unwrap_or_default();
            if a.len() > 1 {
                continue;
            }
            let mut ordenadas: Vec<(&String, &Vec<String>)> = cadenas.iter().collect();
            ordenadas.sort_by_key(|x| std::cmp::Reverse(x.1.len()));
            for (o, b) in ordenadas {
                if b.len() >= 2 && un_cambio(k, o) {
                    salida.push(format!(
                        "possible misspelled key: `{k}` appears only at {}, while `{o}` (one letter apart) appears in {} places ({}{})",
                        a.first().cloned().unwrap_or_else(|| "?".into()),
                        b.len(),
                        b.iter().take(4).cloned().collect::<Vec<_>>().join(", "),
                        if b.len() > 4 { ", …" } else { "" }
                    ));
                    break;
                }
            }
        }
        Ok(salida)
    }

    /// `_funcion_ast`: (ruta, nombre completo, árbol y nodo) de una función o método de Python.
    /// También la cota de profundidad del archivo, para recorrer el árbol con `con_pila`.
    pub fn funcion_ast(&self, nombre: &str, rutas: &[String]) -> Resultado<Option<(String, String, Arbol, Id, usize)>> {
        let corto = nombre.rsplit('.').next().unwrap_or(nombre).to_string();
        let filas: Vec<Value> = self
            .filas("SELECT ruta, nombre FROM simbolos WHERE (nombre = ? OR corto = ?) AND ruta LIKE '%.py'", &[&nombre, &corto])?
            .into_iter()
            .filter(|f| rutas.is_empty() || rutas.iter().any(|r| s(&f["ruta"]) == *r || s(&f["ruta"]).ends_with(&format!("/{r}"))))
            .collect();
        let Some(f) = filas.first() else { return Ok(None) };
        let (ruta, completo) = (s(&f["ruta"]), s(&f["nombre"]));
        let texto = self.lineas_arc(&ruta)?.join("\n");
        let Some(niveles) = cota_de_profundidad(&texto) else { return Err("SyntaxError: no se pudo analizar".into()) };
        let Some(arbol) = Arbol::analizar(&texto) else { return Err("SyntaxError: no se pudo analizar".into()) };
        let partes: Vec<&str> = completo.split('.').collect();
        for n in arbol.recorrer(arbol.modulo) {
            match arbol.k(n) {
                K::ClassDef { name, body, .. } if partes.len() == 2 && name == partes[0] => {
                    for m in body {
                        if let K::FunctionDef { is_async: false, name, .. } = arbol.k(*m) {
                            if name == partes[1] {
                                let m = *m;
                                return Ok(Some((ruta, completo, arbol, m, niveles)));
                            }
                        }
                    }
                }
                K::FunctionDef { is_async: false, name, .. } if partes.len() == 1 && name == partes[0] => {
                    return Ok(Some((ruta, completo, arbol, n, niveles)));
                }
                _ => {}
            }
        }
        Ok(None)
    }

    /// `_codigo_en_revision`.
    pub fn codigo_en_revision(&self, nombre: &str, rutas: &[String], maximo: i64) -> Resultado<String> {
        let corto = nombre.rsplit('.').next().unwrap_or(nombre).to_string();
        let filas: Vec<Value> = self
            .filas("SELECT ruta, nombre, ini, fin FROM simbolos WHERE nombre = ? OR corto = ?", &[&nombre, &corto])?
            .into_iter()
            .filter(|f| rutas.is_empty() || rutas.iter().any(|r| s(&f["ruta"]) == *r || s(&f["ruta"]).ends_with(&format!("/{r}"))))
            .collect();
        if filas.len() != 1 || filas[0]["fin"].as_i64().unwrap_or(0) - filas[0]["ini"].as_i64().unwrap_or(0) + 1 > maximo {
            return Ok(String::new());
        }
        let f = &filas[0];
        let ruta = s(&f["ruta"]);
        let lineas = self.lineas_arc(&ruta)?;
        let (ini, fin) = (f["ini"].as_i64().unwrap_or(1), f["fin"].as_i64().unwrap_or(1));
        let cuerpo: Vec<String> = (ini..=fin.min(lineas.len() as i64)).map(|n| format!("{:>5}  {}", n, lineas[(n - 1) as usize])).collect();
        Ok(format!(
            "· code under review, literal from the project ({}:{}-{}; quote THIS code, not from memory):\n```\n{}\n```",
            ruta,
            ini,
            fin,
            cuerpo.join("\n")
        ))
    }

    /// `_trampas`: errores conocidos que el modelo no reconocía leyendo.
    pub fn trampas(&self, nombre: &str, rutas: &[String]) -> Resultado<String> {
        let Some((ruta, completo, a, funcion, niveles)) = self.funcion_ast(nombre, rutas)? else { return Ok(String::new()) };
        // Recorre el árbol con unparse: con la pila que pida el archivo (pyast::con_pila)
        Ok(con_pila(niveles, || trampas_de(&ruta, &completo, &a, funcion)).unwrap_or_default())
    }
}

static EN_COMILLAS: LazyLock<Re> = LazyLock::new(|| Re::nuevo("`([^`\n]{2,100})`", ""));
static RUTA_HTTP: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"\b(?:GET|POST|PUT|DELETE|PATCH)\s+/[^\s`'"),?]*|(?<![\w/.])/api/[^\s`'"),?]*"#, ""));
static IDENTIFICADOR: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"\b(?:[A-Za-z_]\w*\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*|[a-z][a-z0-9]*_[a-z0-9_]+|[A-Z][A-Z0-9]*_[A-Z0-9_]+)\b", ""));
static ARCHIVO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"\.(?:py|js|jsx|ts|tsx|json|md|html|css|c|cpp|h|sh|txt|toml|yml|yaml)$", ""));
static ES_ENDPOINT: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^(?:GET|POST|PUT|DELETE|PATCH) /", ""));
static ES_ENDPOINT_OPCIONAL: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^(?:(?:GET|POST|PUT|DELETE|PATCH) )?/", ""));
pub static REVISION: LazyLock<Re> = LazyLock::new(|| {
    Re::nuevo(r"(?:tiene|hay)\s+(?:alg[uú]n|un|alg[uú]n otro)\s+(?:error|bug|fallo)|\brevis[ae]r?\b|errores? de programaci[oó]n|\bbugs?\b", "i")
});

/// `terminos_de`: rutas HTTP, lo que va entre `comillas` e identificadores con forma de código.
pub fn terminos_de(pregunta: &str, maximo: usize) -> Vec<String> {
    let mut vistos: HashSet<String> = HashSet::new();
    let mut salida: Vec<String> = vec![];
    let mut agregar = |t: &str| {
        let t = rstrip_de(strip_de(strip(t), "`"), "?.,:;").to_string();
        if largo(&t) < 3 || vistos.contains(&t) || ARCHIVO.hay(&t) || (t.contains('/') && !ES_ENDPOINT_OPCIONAL.hay(&t)) {
            return;
        }
        vistos.insert(t.clone());
        salida.push(t);
    };
    for m in RUTA_HTTP.todos(pregunta) {
        agregar(m.todo());
    }
    for m in EN_COMILLAS.todos(pregunta) {
        agregar(m.g(1));
    }
    for m in IDENTIFICADOR.todos(pregunta) {
        agregar(m.todo());
    }
    salida.truncate(maximo);
    salida
}

/// Las rutas de archivo que nombra la pregunta entre comillas.
pub fn rutas_de(pregunta: &str) -> Vec<String> {
    EN_COMILLAS.findall1(pregunta).into_iter().map(|m| strip(m).to_string()).filter(|m| ARCHIVO.hay(m)).collect()
}

fn lista(xs: &[String], n: usize) -> String {
    let mut t = xs.iter().take(n).cloned().collect::<Vec<_>>().join("; ");
    if xs.len() > n {
        t.push_str(&format!(" (+{})", xs.len() - n));
    }
    t
}

static LUGAR: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^(.+?):(\d+): (.*)$", ""));

/// `_hechos_de`: lo que el banco sabe de un término de la pregunta.
pub fn hechos_de(api: &Consulta, t: &str, rutas: &[String], n: usize, familias: &mut HashMap<Vec<String>, IndexMap<String, Vec<String>>>) -> Resultado<String> {
    let mut lineas: Vec<String> = vec![];
    if t.starts_with('/') || ES_ENDPOINT.hay(t) {
        let a = api.api(t)?;
        let expone: Vec<String> = a["expone"].as_array().unwrap().iter().map(|f| format!("{} → {} ({}:{})", s(&f["o"]), s(&f["s"]), s(&f["ruta"]), s(&f["linea"]))).collect();
        if !expone.is_empty() {
            lineas.push(format!("exposed by: {}", lista(&expone, n)));
        }
        let consume: Vec<String> = a["consume"].as_array().unwrap().iter().map(|f| format!("{} ({}:{})", s(&f["s"]), s(&f["ruta"]), s(&f["linea"]))).collect();
        if !consume.is_empty() {
            lineas.push(format!("called from: {}", lista(&consume, n)));
        }
    } else {
        let mut d = api.donde(t, n)?;
        if let Some(h) = d.get("hechos").and_then(|h| h.as_object()) {
            for (r, v) in h {
                let xs: Vec<String> = v.as_array().unwrap().iter().map(s).collect();
                lineas.push(format!("{r}: {}", lista(&xs, n)));
            }
        }
        let tiene_simbolos = d.get("simbolos").and_then(|x| x.as_array()).map(|x| !x.is_empty()).unwrap_or(false);
        if !tiene_simbolos {
            let asignaciones = api.asignaciones_de(t, rutas, 8)?;
            if !asignaciones.is_empty() {
                lineas.push(format!("assigned at module level: {}", lista(&asignaciones, n)));
            }
        }
        let (mut objetivo, mut de_ruta) = (t.to_string(), None::<String>);
        if !rutas.is_empty() && tiene_simbolos {
            for r in rutas {
                let propias: Vec<Value> = d["simbolos"].as_array().unwrap().iter().filter(|x| s(x).contains(&format!(" {r}:"))).cloned().collect();
                if !propias.is_empty() {
                    d.as_object_mut().unwrap().insert("simbolos".into(), Value::from(propias));
                    objetivo = format!("{r}:{t}");
                    de_ruta = Some(r.clone());
                    break;
                }
            }
        }
        if tiene_simbolos {
            let simbolos: Vec<String> = d["simbolos"].as_array().unwrap().iter().map(s).collect();
            lineas.push(format!("defined: {}", lista(&simbolos, n)));
            let corto = t.rsplit('.').next().unwrap_or(t).to_string();
            let como = format!("%.{corto}");
            let expone: Vec<String> = api
                .filas("SELECT o, ruta, linea FROM hechos WHERE r = 'expone' AND (s = ? OR s = ? OR s LIKE ?)", &[&t, &corto, &como])?
                .iter()
                .filter(|e| de_ruta.as_ref().map(|r| s(&e["ruta"]) == *r).unwrap_or(true))
                .map(|e| format!("{} ({}:{})", s(&e["o"]), s(&e["ruta"]), s(&e["linea"])))
                .collect();
            if !expone.is_empty() {
                lineas.push(format!("exposes: {}", lista(&expone, n)));
            }
            let llamadores = api.llamadores(&objetivo)?;
            let (en_tests, propios): (Vec<&Value>, Vec<&Value>) = llamadores.iter().partition(|x| es_test(&s(&x["ruta"])));
            let del_grafo: Vec<String> = propios.iter().filter(|x| !s(&x["confianza"]).starts_with("texto")).map(|x| format!("{} ({}:{})", s(&x["s"]), s(&x["ruta"]), s(&x["linea"]))).collect();
            let de_texto: Vec<String> = propios
                .iter()
                .filter(|x| s(&x["confianza"]).starts_with("texto"))
                .map(|x| {
                    let conf = s(&x["confianza"]);
                    let instancia = if conf.contains("instancia de ") {
                        format!(", instance of {}", conf.split("instancia de ").nth(1).unwrap_or("").split(')').next().unwrap_or(""))
                    } else {
                        String::new()
                    };
                    format!("{} ({}:{}{}: {})", s(&x["s"]), s(&x["ruta"]), s(&x["linea"]), instancia, primeros(x.get("codigo").and_then(|c| c.as_str()).unwrap_or(""), 70))
                })
                .collect();
            if !del_grafo.is_empty() {
                lineas.push(format!("callers (graph): {}", lista(&del_grafo, n)));
            }
            if !de_texto.is_empty() {
                lineas.push(format!("possible callers found by text, unresolved: {}", lista(&de_texto, n)));
            }
            if !en_tests.is_empty() {
                let archivos: BTreeSet<String> = en_tests.iter().map(|x| basename(&s(&x["ruta"])).to_string()).collect();
                let archivos: Vec<String> = archivos.into_iter().collect();
                lineas.push(format!(
                    "callers in tests: {} ({}{})",
                    en_tests.len(),
                    archivos.iter().take(4).cloned().collect::<Vec<_>>().join(", "),
                    if archivos.len() > 4 { ", …" } else { "" }
                ));
            }
            if propios.is_empty() {
                lineas.push(if en_tests.is_empty() { "callers: none found (graph and text)".into() } else { "callers outside tests: none found (graph and text)".into() });
            }
            let leidas: Vec<Value> = if t.contains('.') {
                api.filas("SELECT r, o, ruta, linea FROM hechos WHERE r IN ('lee_config', 'lee_entorno') AND s = ?", &[&t])?
            } else {
                let como_t = format!("%.{t}");
                api.filas("SELECT r, o, ruta, linea FROM hechos WHERE r IN ('lee_config', 'lee_entorno') AND (s = ? OR s LIKE ?)", &[&t, &como_t])?
            };
            let leidas: Vec<Value> = leidas.into_iter().filter(|h| de_ruta.as_ref().map(|r| s(&h["ruta"]) == *r).unwrap_or(true)).collect();
            for (r, nombre) in [("lee_config", "reads config keys"), ("lee_entorno", "reads environment variables")] {
                let propias: Vec<String> = leidas.iter().filter(|h| s(&h["r"]) == r).map(|h| format!("{} ({}:{})", s(&h["o"]), s(&h["ruta"]), s(&h["linea"]))).collect();
                if !propias.is_empty() {
                    lineas.push(format!("{nombre}: {}", lista(&propias, n)));
                }
            }
            let claves: Vec<String> = leidas.iter().filter(|h| s(&h["r"]) == "lee_config").map(|h| s(&h["o"])).collect();
            lineas.extend(api.claves_sospechosas(&claves, familias)?);
            let imp = api.impacto(&objetivo, 4).unwrap_or(Value::Object(Map::new()));
            let lst = |k: &str| -> Vec<String> { imp.get(k).and_then(|x| x.as_array()).map(|x| x.iter().map(s).collect()).unwrap_or_default() };
            if !lst("endpoints").is_empty() {
                lineas.push(format!("endpoints reached through the graph: {}", lista(&lst("endpoints"), n)));
            }
            if !lst("endpoints_por_texto").is_empty() {
                lineas.push(format!("endpoints reached through the unresolved callers too (up to 3 calls away): {}", lista(&lst("endpoints_por_texto"), n)));
            }
        }
        if let Some(como_texto) = d.get("como_texto").and_then(|x| x.as_array()).filter(|x| !x.is_empty()) {
            let (mut leen, mut escriben, mut literales, mut otras, mut en_tests, mut como_antes) = (vec![], vec![], vec![], vec![], 0, vec![]);
            let (lee, escribe, en_dict) = patrones_de_clave(t);
            for x in como_texto.iter().map(s) {
                let m = LUGAR.coincide(&x);
                let simbolo = match &m {
                    Some(m) => api.simbolo_en(m.g(1), m.g(2).parse().unwrap_or(0))?,
                    None => None,
                };
                let texto = m.as_ref().map(|m| m.g(3).to_string()).unwrap_or_else(|| x.clone());
                como_antes.push(match (&m, &simbolo) {
                    (Some(m), Some(sim)) => format!("{}:{} in {}: {}", m.g(1), m.g(2), sim, texto),
                    _ => x.clone(),
                });
                if let Some(m) = &m {
                    if es_test(m.g(1)) {
                        en_tests += 1;
                        continue;
                    }
                }
                let item = match (&m, &simbolo) {
                    (Some(m), Some(sim)) => format!("{} ({}:{}: {})", sim, m.g(1), m.g(2), primeros(&texto, 90)),
                    _ => x.clone(),
                };
                if escribe.hay(&texto) {
                    escriben.push(item);
                } else if lee.hay(&texto) {
                    leen.push(item);
                } else if en_dict.hay(&texto) {
                    literales.push(item);
                } else {
                    otras.push(item);
                }
            }
            if tiene_simbolos || (leen.is_empty() && escriben.is_empty() && literales.is_empty()) {
                lineas.push(format!("as literal text: {}", lista(&como_antes, n)));
            } else {
                for (nombre, xs) in [
                    ("reads the key (x.get / x[...])", &leen),
                    ("writes the key (x[...] = …)", &escriben),
                    ("only as a key in a dict literal (a default or a returned value, not a read)", &literales),
                    ("other literal text", &otras),
                ] {
                    if !xs.is_empty() {
                        lineas.push(format!("{nombre}: {}", lista(xs, n)));
                    }
                }
                if en_tests > 0 {
                    lineas.push(format!("in tests: {en_tests} more"));
                }
                let lee_config = d.get("hechos").and_then(|h| h.get("lee_config")).is_some();
                if lee_config || !leen.is_empty() {
                    lineas.extend(api.claves_sospechosas(&[t.to_string()], familias)?);
                }
            }
        }
    }
    Ok(if lineas.is_empty() { String::new() } else { format!("· `{t}`\n  {}", lineas.join("\n  ")) })
}

/// `hechos_de_la_pregunta` en partes: los bloques de revisión por término (código y trampas; «cómo probarla» lo
/// agrega Python en su lugar) y los demás bloques. Python arma el texto y lo recorta.
pub fn hechos_de_la_pregunta(api: &Consulta, pregunta: &str) -> Resultado<Value> {
    let terminos = terminos_de(pregunta, 4);
    if terminos.is_empty() {
        return Ok(json!({"terminos": [], "simbolos": [], "revision": [], "bloques": [], "rutas": []}));
    }
    let rutas = rutas_de(pregunta);
    let mut familias: HashMap<Vec<String>, IndexMap<String, Vec<String>>> = HashMap::new();
    let mut simbolos = vec![];
    for t in &terminos {
        if simbolos.len() >= 3 {
            break;
        }
        if t.starts_with('/') || ES_ENDPOINT.hay(t) {
            continue;
        }
        if !api.nodos(t)?.is_empty() {
            simbolos.push(t.clone());
        }
    }
    let mut bloques: Vec<String> = vec![];
    let mut caminos = vec![];
    for (i, a) in simbolos.iter().enumerate() {
        for b in &simbolos[i + 1..] {
            let saltos = match api.camino_con_llamadas(a, b, 10) {
                Ok(Some(x)) => Some(x),
                Ok(None) => api.camino_con_llamadas(b, a, 10).ok().flatten(),
                Err(_) => None,
            };
            let Some(saltos) = saltos.filter(|x| !x.is_empty()) else { continue };
            let nombres: Vec<String> = saltos.iter().map(|x| s(&x["simbolo"])).collect();
            let mut texto = format!("call path (graph): {}\n    {} ({})", nombres.join(" → "), s(&saltos[0]["simbolo"]), s(&saltos[0]["en"]));
            for x in &saltos[1..] {
                texto.push_str(&format!("\n    → calls {} ({})", s(&x["simbolo"]), s(&x["en"])));
                if x.get("llamada").is_some() {
                    texto.push_str(&format!(" at {}: {}", s(&x["llamada"]), s(&x["codigo"])));
                }
            }
            let mut medio = vec![];
            for par in saltos.windows(2).skip(1) {
                let (x, siguiente) = (&par[0], &par[1]);
                let nodo = (s(&x["nodo"][0]), s(&x["nodo"][1]));
                let codigo = api.codigo_del_salto(&nodo, siguiente.get("linea").and_then(|l| l.as_i64()), 14)?;
                if !codigo.is_empty() {
                    medio.push(format!("    {} ({}):\n{}", s(&x["simbolo"]), s(&x["en"]), codigo));
                }
            }
            if !medio.is_empty() {
                texto.push_str(&format!("\n    code of the functions in the middle (line numbers on the left):\n{}", medio.join("\n")));
            }
            caminos.push(texto);
        }
    }
    if !caminos.is_empty() {
        bloques.push(format!(
            "· call path between the names in the question: when the first one runs, execution reaches the last one through these calls — indirectly, through the functions in the middle, which is what such a question asks for. Each call is written in the code at the line shown (some sit inside an argument or a dict literal: they still run). To deny it, quote the line that contradicts it.\n  {}",
            caminos.join("\n  ")
        ));
    }
    for t in &terminos {
        if let Ok(b) = hechos_de(api, t, &rutas, 8, &mut familias) {
            if !b.is_empty() {
                bloques.push(b);
            }
        }
    }
    let mut revision: Vec<Value> = vec![];
    if REVISION.hay(pregunta) {
        for t in simbolos.iter().take(2) {
            let codigo = api.codigo_en_revision(t, &rutas, 60).unwrap_or_default();
            let trampas = api.trampas(t, &rutas).unwrap_or_default();
            revision.push(json!({"termino": t, "codigo": codigo, "trampas": trampas}));
        }
    }
    Ok(json!({"terminos": terminos, "simbolos": simbolos, "revision": revision, "bloques": bloques, "rutas": rutas}))
}

/// Puntos del enrutador de unidades (lectura_unidades.elegir_unidad), sin la parte que mira el motor (vigente):
/// las unidades entran como [(orden, nombre, rutas, piezas)].
pub fn elegir_unidad(banco: &Banco, unidades: &[(i64, String, Vec<String>, Vec<(String, i64, i64)>)], pregunta: &str, minimo: f64, vector: Option<&[f64]>) -> Resultado<Value> {
    let unidad_de = |ruta: &str, linea: i64| -> Option<i64> {
        for (orden, _, _, piezas) in unidades {
            for (r, ini, fin) in piezas {
                if r == ruta && *ini <= linea && linea <= *fin {
                    return Some(*orden);
                }
            }
        }
        None
    };
    let mut puntos: IndexMap<i64, f64> = IndexMap::new();
    let mut sumar = |orden: Option<i64>, p: f64| {
        if let Some(o) = orden {
            let x = puntos.get(&o).copied().unwrap_or(0.0);
            puntos.insert(o, x + p);
        }
    };
    let c = banco.conectar()?;
    let rutas = crate::banco::busqueda::rutas_mencionadas(&c, pregunta)?;
    static SEPARA: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"[/.]", ""));
    let partes: HashSet<String> = rutas.iter().flat_map(|r| SEPARA.sub("\u{0}", r).split('\u{0}').filter(|p| !p.is_empty()).map(|p| p.to_string()).collect::<Vec<_>>()).collect();
    static CONSTANTE: LazyLock<ReInicio> = LazyLock::new(|| ReInicio::nuevo(r"^[A-Z][A-Z0-9_]{2,}$", ""));
    let mut consulta: Option<Consulta> = None;
    for nombre in crate::texto::identificadores_nombrados(pregunta).into_iter().filter(|n| !partes.contains(n)) {
        let corto = nombre.rsplit('.').next().unwrap_or(&nombre).to_string();
        let filas: Vec<(String, i64)> = {
            let mut st = c.prepare("SELECT ruta, ini FROM simbolos WHERE nombre = ? OR corto = ?").map_err(error)?;
            let v = st
                .query_map(params![nombre, corto], |f| Ok((f.get::<_, Option<String>>(0)?.unwrap_or_default(), f.get::<_, Option<i64>>(1)?.unwrap_or(0))))
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            v
        };
        for (r, ini) in &filas {
            sumar(unidad_de(r, *ini), 3.0);
        }
        let como = format!("% {nombre}");
        {
            let mut st = c.prepare("SELECT ruta, linea FROM hechos WHERE o = ? OR o LIKE ?").map_err(error)?;
            let v = st
                .query_map(params![nombre, como], |f| Ok((f.get::<_, Option<String>>(0)?.unwrap_or_default(), f.get::<_, Option<i64>>(1)?.unwrap_or(0))))
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            for (r, l) in v {
                sumar(unidad_de(&r, l), 1.5);
            }
        }
        if filas.is_empty() && CONSTANTE.hay(&nombre) {
            if consulta.is_none() {
                consulta = Some(Consulta::abrir(&banco.ruta_db, &banco.raiz)?);
            }
            for lugar in consulta.as_ref().unwrap().asignaciones_de(&nombre, &rutas, 3)? {
                let partes: Vec<&str> = lugar.split(':').collect();
                if partes.len() >= 2 {
                    if let Ok(l) = partes[1].parse::<i64>() {
                        sumar(unidad_de(partes[0], l), 3.0);
                    }
                }
            }
        }
    }
    for ruta in &rutas {
        for (orden, _, rutas_u, piezas) in unidades {
            if rutas_u.contains(ruta) {
                let n = piezas.iter().filter(|p| &p.0 == ruta).count().max(1);
                sumar(Some(*orden), 2.0 / n as f64);
            }
        }
    }
    drop(c);
    for (rango, f) in banco.buscar(pregunta, 12, vector)?.iter().enumerate() {
        sumar(unidad_de(&f.ruta, f.ini), 1.0 / (1.0 + rango as f64 * 0.5));
    }
    if puntos.is_empty() {
        return Ok(json!({"orden": null, "motivo": "ninguna unidad coincide"}));
    }
    let mut orden_puntos: Vec<(i64, f64)> = puntos.iter().map(|(a, b)| (*a, *b)).collect();
    orden_puntos.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    let total = crate::py::numero::suma(puntos.values().copied());
    let (mejor, p1) = orden_puntos[0];
    let p2 = orden_puntos.get(1).map(|x| x.1).unwrap_or(0.0);
    let cuota = p1 / total;
    let nombre_de = |o: i64| unidades.iter().find(|u| u.0 == o).map(|u| u.1.clone()).unwrap_or_default();
    let alternativas: Vec<Value> = orden_puntos
        .iter()
        .take(4)
        .map(|(o, p)| json!({"orden": o, "nombre": nombre_de(*o), "puntos": crate::banco::busqueda::numero(crate::py::numero::round(*p, 2))}))
        .collect();
    if cuota < minimo || p1 < 1.5 * p2 {
        return Ok(json!({"orden": null, "motivo": format!("repartida entre unidades (la mejor tiene {})", crate::py::numero::porciento(cuota, 0)), "alternativas": alternativas}));
    }
    Ok(json!({"orden": mejor, "nombre": nombre_de(mejor), "cuota": crate::banco::busqueda::numero(crate::py::numero::round(cuota, 2)), "alternativas": alternativas}))
}

/// El cuerpo de `trampas`, sobre el árbol del archivo.
fn trampas_de(ruta: &str, completo: &str, a: &Arbol, funcion: Id) -> String {
    let mut avisos: Vec<String> = vec![];
    let todo = a.recorrer(funcion);
    for &manejador in &todo {
        let K::ExceptHandler { type_: Some(t), body, .. } = a.k(manejador) else { continue };
        if !unparse(&a, *t).contains("TimeoutExpired") {
            continue;
        }
        let mut matados: HashSet<String> = HashSet::new();
        for nodo in body {
            for x in a.recorrer(*nodo) {
                let K::Call { func, args, .. } = a.k(x) else { continue };
                let K::Attribute { value, attr, .. } = a.k(*func) else { continue };
                let quien = unparse(&a, *value);
                if attr == "kill" || attr == "terminate" || attr == "killpg" {
                    matados.insert(quien);
                    for arg in args {
                        matados.insert(unparse(&a, *arg));
                    }
                } else if attr == "communicate" && !matados.contains(&quien) && !matados.iter().any(|m| m.contains(quien.as_str())) {
                    avisos.push(format!(
                        "line {}: in the `except TimeoutExpired` handler, `{quien}.communicate()` runs without `{quien}.kill()` first. The child was not killed, so communicate() waits for it to finish: a hang (Python docs, subprocess.Popen.communicate: «The child process is not killed if the timeout expires… kill the child process and finish communication»)",
                        a.linea(x)
                    ));
                }
            }
        }
    }
    // max()/min() de una lista filtrada sin default ni comprobación
    let nombres_en = |n: Id| -> HashSet<String> { a.recorrer(n).into_iter().filter_map(|x| a.nombre(x).map(|s| s.to_string())).collect() };
    let mut filtradas: HashMap<String, (u32, HashSet<String>)> = HashMap::new();
    for &nodo in &todo {
        let K::Assign { targets, value } = a.k(nodo) else { continue };
        if targets.len() != 1 {
            continue;
        }
        let Some(objetivo) = a.nombre(targets[0]) else { continue };
        let generators = match a.k(*value) {
            K::ListComp { generators, .. } | K::GeneratorExp { generators, .. } => generators,
            _ => continue,
        };
        if !generators.iter().any(|g| matches!(a.k(*g), K::Comprehension { ifs, .. } if !ifs.is_empty())) {
            continue;
        }
        let mut objetivos: HashSet<String> = HashSet::new();
        for g in generators {
            if let K::Comprehension { target, .. } = a.k(*g) {
                objetivos.extend(nombres_en(*target));
            }
        }
        let usados: HashSet<String> = nombres_en(*value).difference(&objetivos).cloned().collect();
        filtradas.insert(objetivo.to_string(), (a.linea(nodo), usados));
    }
    if !filtradas.is_empty() {
        let mut protegidas: HashSet<String> = HashSet::new();
        for &nodo in &todo {
            match a.k(nodo) {
                K::If { test, .. } | K::IfExp { test, .. } | K::While { test, .. } | K::Assert { test, .. } => protegidas.extend(nombres_en(*test)),
                K::BoolOp { values, .. } => {
                    for v in &values[..values.len().saturating_sub(1)] {
                        protegidas.extend(nombres_en(*v));
                    }
                }
                _ => {}
            }
        }
        for &llamada in &todo {
            let K::Call { func, args, keywords } = a.k(llamada) else { continue };
            let Some(f) = a.nombre(*func) else { continue };
            if (f != "max" && f != "min") || args.len() != 1 {
                continue;
            }
            let Some(lista) = a.nombre(args[0]) else { continue };
            let Some((linea_f, usados)) = filtradas.get(lista) else { continue };
            if protegidas.contains(lista) || usados.iter().any(|u| protegidas.contains(u)) {
                continue;
            }
            if keywords.iter().any(|k| matches!(a.k(*k), K::Keyword { arg: Some(x), .. } if x == "default")) {
                continue;
            }
            avisos.push(format!(
                "line {}: `{f}({lista})` — `{lista}` is a filtered list (line {linea_f}) and can be empty; {f}() of an empty sequence raises ValueError, and there is no default= nor a check before it",
                a.linea(llamada)
            ));
        }
    }
    // @contextmanager con el yield fuera de try/finally
    let decoradores = match a.k(funcion) {
        K::FunctionDef { decorators, .. } => decorators.clone(),
        _ => vec![],
    };
    let es_cm = decoradores.iter().any(|d| matches!(a.k(*d), K::Name { id, .. } if id == "contextmanager") || matches!(a.k(*d), K::Attribute { attr, .. } if attr == "contextmanager"));
    if es_cm {
        let mut cubiertos: HashSet<Id> = HashSet::new();
        for &nodo in &todo {
            let cuerpo: Option<&Vec<Id>> = match a.k(nodo) {
                K::Try { is_star: false, body, finalbody, .. } if !finalbody.is_empty() => Some(body),
                K::With { is_async: false, body, .. } => Some(body),
                _ => None,
            };
            if let Some(cuerpo) = cuerpo {
                for m in cuerpo {
                    cubiertos.extend(a.recorrer(*m));
                }
            }
        }
        let sueltos: Vec<Id> = todo.iter().copied().filter(|y| matches!(a.k(*y), K::Yield { .. } | K::YieldFrom { .. }) && !cubiertos.contains(y)).collect();
        if let Some(y) = sueltos.first() {
            let cierra = todo.iter().any(|c| matches!(a.k(*c), K::Call { func, .. } if matches!(a.k(*func), K::Attribute { attr, .. } if attr == "close" || attr == "release")));
            avisos.push(format!(
                "line {}: in this @contextmanager the `yield` is not inside try/finally: if the body of the `with` raises, nothing after the yield runs{} (Python docs, contextlib.contextmanager)",
                a.linea(*y),
                if cierra { "" } else { ", and nothing ever closes what it opened (no .close())" }
            ));
        }
    }
    // startswith como prueba de contención de rutas
    static NO_ALNUM: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"[^A-Za-z0-9]+|_", ""));
    let de_ruta: HashSet<&str> = ["path", "ruta", "root", "raiz", "dir", "base", "carpeta", "folder", "directorio", "workspace"].into_iter().collect();
    for &c in &todo {
        let K::Call { func, args, .. } = a.k(c) else { continue };
        let K::Attribute { value, attr, .. } = a.k(*func) else { continue };
        if attr != "startswith" || args.len() != 1 || !matches!(a.k(args[0]), K::Name { .. } | K::Attribute { .. }) {
            continue;
        }
        let (quien, prefijo) = (unparse(&a, *value), unparse(&a, args[0]));
        let texto = format!("{quien} {prefijo}");
        let partes: HashSet<String> = NO_ALNUM.sub("\u{0}", &texto).split('\u{0}').filter(|x| !x.is_empty()).map(|x| x.to_lowercase()).collect();
        if partes.iter().any(|p| de_ruta.contains(p.as_str())) {
            avisos.push(format!(
                "line {}: `{quien}.startswith({prefijo})` as a path containment check: '/ws-other' starts with '/ws'. Compare with `{prefijo} + os.sep` (or os.path.commonpath)",
                a.linea(c)
            ));
        }
    }
    if avisos.is_empty() { String::new() } else { format!("· known pitfalls in `{completo}` ({ruta}):\n  {}", avisos.join("\n  ")) }
}
