//! La memoria del banco (BancoProyecto: anotar, olvidar_conocimiento, listar_conocimiento, afirmar,
//! guardar_trabajo, guardar_particion, unidades, particion, guardar_resumen, registrar_resolucion con
//! resumir_respuesta, listar_resoluciones, resolucion, olvidar_resolucion, pendientes_de_analisis,
//! _contenido_de_carpetas, trabajo_pendiente).

use std::collections::{BTreeSet, HashSet};
use std::sync::LazyLock;

use indexmap::IndexMap;
use rusqlite::params;
use serde_json::{json, Map, Value};

use super::{ahora, comprimir, descomprimir, error, filas, Banco, Resultado};
use crate::py::cadena::{largo, primeros, rfind_car, rstrip, splitlines, strip, strip_de};
use crate::py::json::{dumps, loads};
use crate::py::ruta::{basename, dirname};
use crate::re::Re;
use crate::texto::{sha, terminos, TIPOS_CONOCIMIENTO};

static BLOQUE_CODIGO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"```.*?(```|$)", "s"));
static PENSAMIENTO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"<think>.*?</think>", "s"));
static ESPACIOS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"\s+", ""));
static DESTINO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"###\s*Archivo:\s*(\S+)", ""));
static BLOQUES: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"```[\w+-]*\n(.*?)```", "s"));
static DEFINIDOS: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"^\s*(?:async\s+)?(?:def|class|function|fn|func)\s+([A-Za-z_]\w*)", "m"));
static RUTA_EN_TEXTO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"[\w./-]+\.[A-Za-z]{1,6}\b", ""));

/// `resumir_respuesta`: la prosa inicial sin código, más qué código dejó.
pub fn resumir_respuesta(respuesta: &str, maximo: usize) -> String {
    let sin_codigo = BLOQUE_CODIGO.sub(" ", respuesta);
    let sin_codigo = PENSAMIENTO.sub(" ", &sin_codigo);
    let prosa: Vec<String> = splitlines(&sin_codigo).into_iter().filter(|l| !strip(l).is_empty()).map(|l| strip(strip_de(l, "#>*- ")).to_string()).collect();
    let prosa = prosa.join(" ");
    let prosa = ESPACIOS.sub(" ", &prosa);
    let mut prosa = strip(&prosa).to_string();
    let destinos = DESTINO.findall1(respuesta);
    let bloques = BLOQUES.findall1(respuesta);
    let mut definidos: Vec<&str> = vec![];
    for b in &bloques {
        definidos.extend(DEFINIDOS.findall1(b));
    }
    let unicos = |xs: Vec<&str>| -> Vec<String> {
        let mut vistos = HashSet::new();
        xs.into_iter().filter(|x| vistos.insert(*x)).map(|x| x.to_string()).collect()
    };
    let mut extra: Vec<String> = vec![];
    if !destinos.is_empty() {
        extra.push(format!("Archivos: {}", unicos(destinos).join(", ")));
    }
    if !definidos.is_empty() {
        extra.push(format!("Código: {}", unicos(definidos).into_iter().take(10).collect::<Vec<_>>().join(", ")));
    } else if !bloques.is_empty() {
        extra.push(format!("{} bloque(s) de código", bloques.len()));
    }
    let cola = if extra.is_empty() { String::new() } else { format!(" {}.", extra.join(". ")) };
    let espacio = 120usize.max(maximo.saturating_sub(largo(&cola)));
    if largo(&prosa) > espacio {
        let corte = primeros(&prosa, espacio).to_string();
        let punto = rfind_car(&corte, ". ");
        prosa = if punto as f64 > espacio as f64 * 0.5 { primeros(&corte, (punto + 1) as usize).to_string() } else { format!("{}…", rstrip(&corte)) };
    }
    strip(&format!("{prosa}{cola}")).to_string()
}

fn lista_json(texto: Option<&str>) -> Value {
    loads(texto.filter(|s| !s.is_empty()).unwrap_or("[]")).unwrap_or(Value::Array(vec![]))
}

impl Banco {
    /// `anotar`: guarda (o actualiza, mismo título y tipo) una nota de conocimiento.
    pub fn anotar(&self, tipo: &str, titulo: &str, texto: &str, rutas: &[String], origen: &str) -> Resultado<Value> {
        let tipo = if TIPOS_CONOCIMIENTO.contains(&tipo) { tipo } else { "nota" };
        let titulo = primeros(strip(titulo), 200).to_string();
        let texto = primeros(strip(texto), 4000).to_string();
        if titulo.is_empty() || texto.is_empty() {
            return Err("ValueError: Hacen falta un título y un texto.".into());
        }
        let version = self.version()?;
        let mut c = self.conectar()?;
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(error)?;
        let validas: HashSet<String> = Banco::rutas(&tx)?.into_iter().collect();
        let rutas_ok: Vec<String> = rutas
            .iter()
            .filter(|r| !r.is_empty())
            // La ruta tal cual primero: strip("./") de Python le quitaba el punto a un archivo oculto (`.env`)
            .map(|r| if validas.contains(r.as_str()) { r.to_string() } else { strip_de(r, "./").to_string() })
            .filter(|r| validas.contains(r))
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        let momento = ahora();
        let rutas_json = dumps(&json!(rutas_ok), true);
        let previa: Option<i64> = tx
            .query_row("SELECT id FROM conocimiento WHERE lower(titulo) = lower(?) AND tipo = ?", params![titulo, tipo], |f| f.get(0))
            .ok();
        let i = match previa {
            Some(i) => {
                tx.execute(
                    "UPDATE conocimiento SET texto = ?, rutas = ?, origen = ?, actualizado = ?, revisar = 0, version = ? WHERE id = ?",
                    params![texto, rutas_json, origen, momento, version, i],
                )
                .map_err(error)?;
                tx.execute("DELETE FROM conocimiento_fts WHERE rowid = ?", params![i]).map_err(error)?;
                tx.execute("DELETE FROM vectores WHERE clave = ?", params![format!("c:{i}")]).map_err(error)?;
                i
            }
            None => {
                tx.execute(
                    "INSERT INTO conocimiento (tipo, titulo, texto, rutas, origen, creado, actualizado, version) VALUES (?,?,?,?,?,?,?,?)",
                    params![tipo, titulo, texto, rutas_json, origen, momento, momento, version],
                )
                .map_err(error)?;
                tx.last_insert_rowid()
            }
        };
        tx.execute(
            "INSERT INTO conocimiento_fts (rowid, titulo, terminos) VALUES (?,?,?)",
            params![i, terminos(&titulo, 4000).join(" "), terminos(&texto, 4000).join(" ")],
        )
        .map_err(error)?;
        tx.commit().map_err(error)?;
        self.invalidar_vectores();
        Ok(json!({"id": i, "tipo": tipo, "titulo": titulo, "rutas": rutas_ok, "actualizado": previa.is_some()}))
    }

    pub fn olvidar_conocimiento(&self, i: i64) -> Resultado<bool> {
        let mut c = self.conectar()?;
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(error)?;
        let n = tx.execute("DELETE FROM conocimiento WHERE id = ?", params![i]).map_err(error)?;
        tx.execute("DELETE FROM conocimiento_fts WHERE rowid = ?", params![i]).map_err(error)?;
        tx.execute("DELETE FROM vectores WHERE clave = ?", params![format!("c:{i}")]).map_err(error)?;
        tx.commit().map_err(error)?;
        self.invalidar_vectores();
        Ok(n > 0)
    }

    pub fn listar_conocimiento(&self, limite: i64) -> Resultado<Vec<Value>> {
        let c = self.conectar()?;
        let mut v = filas(&c, "SELECT * FROM conocimiento ORDER BY actualizado DESC LIMIT ?", &[&limite])?;
        for f in v.iter_mut() {
            let r = lista_json(f["rutas"].as_str());
            f.as_object_mut().unwrap().insert("rutas".into(), r);
        }
        Ok(v)
    }

    /// `afirmar` (s, r, o ya convertidos a texto por quien llama: `str(x or "")`).
    pub fn afirmar(&self, s: &str, r: &str, o: &str, ruta: &str, origen: &str) -> Resultado<()> {
        let (s, r, o) = (primeros(strip(s), 300).to_string(), primeros(strip(r), 300).to_string(), primeros(strip(o), 300).to_string());
        if s.is_empty() || r.is_empty() || o.is_empty() {
            return Err("ValueError: Un hecho necesita sujeto, relación y objeto.".into());
        }
        let version = self.version()?;
        let c = self.conectar()?;
        let existe = c.query_row("SELECT 1 FROM hechos WHERE s = ? AND r = ? AND o = ?", params![s, r, o], |_| Ok(())).is_ok();
        if !existe {
            c.execute("INSERT INTO hechos (s, r, o, ruta, linea, origen, version) VALUES (?,?,?,?,0,?,?)", params![s, r, o, ruta, origen, version]).map_err(error)?;
        }
        Ok(())
    }

    /// `guardar_trabajo` con el valor ya serializado (json.dumps(valor, ensure_ascii=False, default=str)).
    pub fn guardar_trabajo(&self, nombre: &str, texto: &str) -> Resultado<()> {
        let nombre = primeros(strip(nombre), 120).to_string();
        if nombre.is_empty() {
            return Err("ValueError: Hace falta un nombre.".into());
        }
        if largo(texto) > 2_000_000 {
            return Err("ValueError: Demasiado grande para guardar (más de 2 MB).".into());
        }
        let c = self.conectar()?;
        c.execute("INSERT OR REPLACE INTO trabajo VALUES (?,?,?)", params![nombre, texto, ahora()]).map_err(error)?;
        Ok(())
    }

    /// `guardar_particion`: las unidades y el resumen (version y creado se agregan aquí).
    pub fn guardar_particion(&self, unidades: &[Value], resumen: &Map<String, Value>) -> Resultado<()> {
        let momento = ahora();
        let version = self.version()?;
        let mut c = self.conectar()?;
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(error)?;
        tx.execute("DELETE FROM unidades", []).map_err(error)?;
        {
            let mut ins = tx.prepare("INSERT INTO unidades VALUES (?,?,?,?,?,?,?,?,?,?)").map_err(error)?;
            for u in unidades {
                ins.execute(params![
                    u["orden"].as_i64(),
                    u["nombre"].as_str(),
                    u["tokens"].as_i64(),
                    dumps(&u["rutas"], true),
                    dumps(&u["piezas"], true),
                    dumps(&u["simbolos"], true),
                    dumps(&u["vecinas"], true),
                    u["cambios_git"].as_i64(),
                    version,
                    momento
                ])
                .map_err(error)?;
            }
        }
        let mut meta = resumen.clone();
        meta.insert("version".into(), Value::from(version));
        meta.insert("creado".into(), Value::from(momento));
        Banco::guardar_meta_en(&tx, "particion", &dumps(&Value::Object(meta), true))?;
        tx.commit().map_err(error)?;
        Ok(())
    }

    pub fn unidades(&self) -> Resultado<Vec<Value>> {
        let c = self.conectar()?;
        let mut v = filas(&c, "SELECT * FROM unidades ORDER BY orden", &[])?;
        for f in v.iter_mut() {
            for k in ["rutas", "piezas", "simbolos", "vecinas"] {
                let x = lista_json(f[k].as_str());
                f.as_object_mut().unwrap().insert(k.into(), x);
            }
        }
        Ok(v)
    }

    pub fn particion(&self) -> Resultado<Option<Value>> {
        Ok(self.meta("particion")?.filter(|v| !v.is_empty()).and_then(|v| loads(&v)))
    }

    pub fn guardar_resumen(&self, nivel: &str, clave: &str, texto: &str, sha_fuente: &str, modelo: &str) -> Resultado<()> {
        let c = self.conectar()?;
        c.execute("INSERT OR REPLACE INTO resumenes VALUES (?,?,?,?,?,?)", params![nivel, clave, texto, sha_fuente, modelo, ahora()]).map_err(error)?;
        Ok(())
    }

    /// `registrar_resolucion`: la pregunta respondida, su resumen y los archivos que nombra.
    pub fn registrar_resolucion(&self, pregunta: &str, respuesta: &str, modelo: &str, rutas: &[String]) -> Resultado<Option<i64>> {
        let pregunta = strip(pregunta).to_string();
        let respuesta = strip(respuesta).to_string();
        if pregunta.is_empty() || respuesta.is_empty() {
            return Ok(None);
        }
        let version = self.version()?;
        let mut c = self.conectar()?;
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(error)?;
        let todas = Banco::rutas(&tx)?;
        let validas: HashSet<String> = todas.iter().cloned().collect();
        let mut mencionadas: BTreeSet<String> = rutas.iter().filter(|r| validas.contains(*r)).cloned().collect();
        let mut por_nombre: IndexMap<String, Vec<String>> = IndexMap::new();
        for r in &todas {
            por_nombre.entry(basename(r).to_string()).or_default().push(r.clone());
        }
        for cand in RUTA_EN_TEXTO.findall0(&respuesta) {
            let cand = if validas.contains(cand) { cand } else { strip_de(cand, "./") };
            if validas.contains(cand) {
                mencionadas.insert(cand.to_string());
            } else if let Some(l) = por_nombre.get(basename(cand)).filter(|l| l.len() == 1) {
                mencionadas.insert(l[0].clone());
            }
        }
        let resumen = resumir_respuesta(&respuesta, 600);
        let lista: Vec<String> = mencionadas.into_iter().collect();
        tx.execute(
            "INSERT INTO resoluciones (pregunta, resumen, respuesta, rutas, modelo, cuando, version) VALUES (?,?,?,?,?,?,?)",
            params![primeros(&pregunta, 4000), resumen, comprimir(&respuesta), dumps(&json!(lista), true), modelo, ahora(), version],
        )
        .map_err(error)?;
        let i = tx.last_insert_rowid();
        tx.execute(
            "INSERT INTO resoluciones_fts (rowid, pregunta, terminos) VALUES (?,?,?)",
            params![i, terminos(&pregunta, 4000).join(" "), terminos(&resumen, 4000).join(" ")],
        )
        .map_err(error)?;
        Banco::guardar_meta_en(&tx, "version_vista", &version.to_string())?;
        tx.commit().map_err(error)?;
        self.invalidar_vectores();
        Ok(Some(i))
    }

    pub fn listar_resoluciones(&self, limite: i64) -> Resultado<Vec<Value>> {
        let c = self.conectar()?;
        let mut v = filas(&c, "SELECT id, pregunta, resumen, rutas, modelo, cuando, version FROM resoluciones ORDER BY id DESC LIMIT ?", &[&limite])?;
        for f in v.iter_mut() {
            let r = lista_json(f["rutas"].as_str());
            f.as_object_mut().unwrap().insert("rutas".into(), r);
        }
        Ok(v)
    }

    pub fn resolucion(&self, i: i64) -> Resultado<Option<Value>> {
        let c = self.conectar()?;
        let mut v = filas(&c, "SELECT * FROM resoluciones WHERE id = ?", &[&i])?;
        let Some(mut d) = v.pop() else { return Ok(None) };
        let blob: Option<Vec<u8>> = c.query_row("SELECT respuesta FROM resoluciones WHERE id = ?", params![i], |f| f.get(0)).ok().flatten();
        let o = d.as_object_mut().unwrap();
        o.insert("respuesta".into(), Value::from(blob.map(|b| descomprimir(&b)).unwrap_or_default()));
        let r = lista_json(o.get("rutas").and_then(|x| x.as_str()));
        o.insert("rutas".into(), r);
        Ok(Some(d))
    }

    pub fn olvidar_resolucion(&self, i: i64) -> Resultado<bool> {
        let mut c = self.conectar()?;
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(error)?;
        let n = tx.execute("DELETE FROM resoluciones WHERE id = ?", params![i]).map_err(error)?;
        tx.execute("DELETE FROM resoluciones_fts WHERE rowid = ?", params![i]).map_err(error)?;
        tx.execute("DELETE FROM vectores WHERE clave = ?", params![format!("r:{i}")]).map_err(error)?;
        tx.commit().map_err(error)?;
        self.invalidar_vectores();
        Ok(n > 0)
    }

    pub fn pendientes_de_analisis(&self) -> Resultado<Vec<String>> {
        let c = self.conectar()?;
        let mut st = c
            .prepare("SELECT ruta FROM archivos WHERE (analizado_sha IS NULL OR analizado_sha != sha) AND lenguaje NOT IN ('datos', 'texto') ORDER BY ruta")
            .map_err(error)?;
        let v = st.query_map([], |f| f.get::<_, String>(0)).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
        Ok(v)
    }

    /// `_contenido_de_carpetas`: para cada carpeta, «nombre — resumen» de sus archivos y subcarpetas.
    pub fn contenido_de_carpetas(&self) -> Resultado<IndexMap<String, Vec<String>>> {
        let c = self.conectar()?;
        let archivos: Vec<(String, Option<String>)> = {
            let mut st = c.prepare("SELECT ruta, COALESCE(resumen_ia, resumen) resumen FROM archivos ORDER BY ruta").map_err(error)?;
            let v = st.query_map([], |f| Ok((f.get::<_, String>(0)?, f.get::<_, Option<String>>(1)?))).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
            v
        };
        let previos: std::collections::HashMap<(String, String), String> = {
            let mut st = c.prepare("SELECT nivel, clave, texto FROM resumenes").map_err(error)?;
            let v = st
                .query_map([], |f| {
                    Ok(((f.get::<_, Option<String>>(0)?.unwrap_or_default(), f.get::<_, Option<String>>(1)?.unwrap_or_default()), f.get::<_, Option<String>>(2)?.unwrap_or_else(|| "None".into())))
                })
                .map_err(error)?
                .collect::<rusqlite::Result<std::collections::HashMap<_, _>>>()
                .map_err(error)?;
            v
        };
        let mut carpetas: IndexMap<String, Vec<String>> = IndexMap::new();
        for (ruta, resumen) in &archivos {
            let d = if dirname(ruta).is_empty() { ".".to_string() } else { dirname(ruta).to_string() };
            let r = resumen.clone().filter(|x| !x.is_empty()).unwrap_or_else(|| "(sin resumen)".to_string());
            carpetas.entry(d.clone()).or_default().push(format!("{} — {}", basename(ruta), r));
            let partes: Vec<&str> = if d != "." { d.split('/').collect() } else { vec![] };
            for k in (0..partes.len()).rev() {
                let p = partes[..k].join("/");
                carpetas.entry(if p.is_empty() { ".".to_string() } else { p }).or_default();
            }
        }
        let claves: Vec<String> = carpetas.keys().cloned().collect();
        for d in &claves {
            let mut hijas: Vec<&String> = claves
                .iter()
                .filter(|h| *h != d && h.as_str() != "." && (if dirname(h).is_empty() { "." } else { dirname(h) }) == d.as_str())
                .collect();
            hijas.sort();
            let lineas: Vec<String> = hijas
                .iter()
                .map(|h| format!("{}/ — {}", basename(h), previos.get(&("carpeta".to_string(), h.to_string())).cloned().unwrap_or_else(|| "(carpeta sin resumir)".to_string())))
                .collect();
            carpetas.get_mut(d).unwrap().extend(lineas);
        }
        Ok(carpetas)
    }

    /// `trabajo_pendiente`: archivos sin analizar y carpetas cuyo contenido cambió.
    pub fn trabajo_pendiente(&self) -> Resultado<Value> {
        let carpetas = self.contenido_de_carpetas()?;
        let c = self.conectar()?;
        let previos: std::collections::HashMap<String, Option<String>> = {
            let mut st = c.prepare("SELECT clave, sha_fuente FROM resumenes WHERE nivel = 'carpeta'").map_err(error)?;
            let v = st
                .query_map([], |f| Ok((f.get::<_, Option<String>>(0)?.unwrap_or_default(), f.get::<_, Option<String>>(1)?)))
                .map_err(error)?
                .collect::<rusqlite::Result<std::collections::HashMap<_, _>>>()
                .map_err(error)?;
            v
        };
        let sucias = carpetas
            .iter()
            .filter(|(d, lineas)| d.as_str() != "." && !lineas.is_empty() && previos.get(*d).cloned().flatten() != Some(sha(&lineas.iter().take(150).cloned().collect::<Vec<_>>().join("\n"))))
            .count();
        Ok(json!({"archivos": self.pendientes_de_analisis()?.len(), "carpetas": sucias}))
    }
}

/// Los pasos de datos del análisis con IA (BancoProyecto.analizar y sintetizar): el bucle que llama al modelo queda
/// en Python, lo que lee y escribe en el banco está aquí.
impl Banco {
    /// (sha, texto) de un archivo para analizarlo (el texto de un cuaderno, como lo veía Python).
    pub fn para_analizar(&self, rel: &str) -> Resultado<Option<(String, String)>> {
        let c = self.conectar()?;
        let f: Option<(Option<String>, Option<Vec<u8>>, Option<String>)> = c
            .query_row("SELECT sha, contenido, lenguaje FROM archivos WHERE ruta = ?", params![rel], |f| Ok((f.get(0)?, f.get(1)?, f.get(2)?)))
            .ok();
        let Some((sha, contenido, lenguaje)) = f else { return Ok(None) };
        let mut texto = descomprimir(&contenido.unwrap_or_default());
        if lenguaje.as_deref() == Some("cuaderno") {
            texto = super::sincronizar::texto_de_cuaderno(&texto);
        }
        Ok(Some((sha.unwrap_or_else(|| "None".into()), texto)))
    }

    pub fn guardar_analisis(&self, rel: &str, resumen: &str, sha: &str) -> Resultado<()> {
        let c = self.conectar()?;
        c.execute("UPDATE archivos SET resumen_ia = ?, analizado_sha = ? WHERE ruta = ?", params![resumen, sha, rel]).map_err(error)?;
        Ok(())
    }

    /// Las notas que dejó un análisis anterior del archivo.
    pub fn notas_de_analisis(&self, rel: &str) -> Resultado<Vec<i64>> {
        let c = self.conectar()?;
        let rutas = dumps(&json!([rel]), true);
        let mut st = c.prepare("SELECT id FROM conocimiento WHERE origen = 'analisis' AND rutas = ?").map_err(error)?;
        let v = st.query_map(params![rutas], |f| f.get(0)).map_err(error)?.collect::<rusqlite::Result<Vec<i64>>>().map_err(error)?;
        Ok(v)
    }

    /// clave → sha de la fuente de los resúmenes de un nivel.
    pub fn shas_de_resumenes(&self, nivel: &str) -> Resultado<IndexMap<String, Option<String>>> {
        let c = self.conectar()?;
        let mut st = c.prepare("SELECT clave, sha_fuente FROM resumenes WHERE nivel = ?").map_err(error)?;
        let v = st
            .query_map(params![nivel], |f| Ok((f.get::<_, Option<String>>(0)?.unwrap_or_default(), f.get::<_, Option<String>>(1)?)))
            .map_err(error)?
            .collect::<rusqlite::Result<IndexMap<_, _>>>()
            .map_err(error)?;
        Ok(v)
    }

    /// (el README, hasta 6.000 caracteres; el sha del resumen del proyecto, si hay).
    pub fn readme_y_previo(&self) -> Resultado<(String, Option<Option<String>>)> {
        let c = self.conectar()?;
        let blob: Option<Option<Vec<u8>>> = c
            .query_row("SELECT contenido FROM archivos WHERE lower(ruta) IN ('readme.md','readme','readme.rst') LIMIT 1", [], |f| f.get(0))
            .ok();
        let readme = match blob {
            Some(Some(b)) => primeros(&descomprimir(&b), 6000).to_string(),
            _ => String::new(),
        };
        let previo: Option<Option<String>> = c.query_row("SELECT sha_fuente FROM resumenes WHERE nivel = 'proyecto'", [], |f| f.get(0)).ok();
        Ok((readme, previo))
    }
}
