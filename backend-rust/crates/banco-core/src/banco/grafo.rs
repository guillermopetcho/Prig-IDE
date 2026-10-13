//! El grafo del proyecto: importaciones resueltas a archivos y cada llamada a su símbolo exacto
//! (BancoProyecto._resolver_importaciones, _resolver_llamadas, _resolver).

use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use rusqlite::params;

use super::{error, Banco, Resultado};
use crate::py::cadena::{rsplit1, strip_de};
use crate::py::ruta::{basename, dirname, join, normpath};
use crate::re::Re;
use crate::texto::lenguaje_de;

pub static VERBOS_COMUNES: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "get", "post", "put", "delete", "patch", "run", "read", "write", "append", "extend", "update", "items",
        "keys", "values", "format", "join", "split", "strip", "open", "close", "execute", "send", "start", "stop",
        "add", "remove", "pop", "copy", "load", "dump", "loads", "dumps", "search", "match", "sub", "find",
        "replace", "lower", "upper", "encode", "decode", "sort", "index", "count", "insert", "clear", "set",
        "wait", "acquire", "release", "submit", "result", "json", "text", "exists", "mkdir", "call", "apply",
        "map", "filter", "reduce", "emit", "on", "then", "catch", "push", "slice", "splice", "forEach", "log",
        "error", "warn", "info", "debug", "parse", "stringify", "test", "exec", "render", "setdefault", "fetch",
        "flush", "readline", "readlines", "kill", "terminate", "poll", "communicate", "is_alive", "is_set",
        "setUp", "tearDown", "__init__", "__enter__", "__exit__", "main", "init", "reset", "next", "iter",
    ]
    .into_iter()
    .collect()
});

/// `r.rsplit(".", 1)[0]`.
fn sin_extension(r: &str) -> &str {
    match r.rfind('.') {
        Some(i) => &r[..i],
        None => r,
    }
}

/// `x[:e]` de Python con e posiblemente negativo.
fn hasta_py<T: Clone>(x: &[T], e: isize) -> Vec<T> {
    let n = x.len() as isize;
    let fin = if e < 0 { (n + e).max(0) } else { e.min(n) };
    x[..fin as usize].to_vec()
}

/// `_resolver`: el archivo del proyecto al que apunta un módulo importado desde `origen`.
pub fn resolver(origen: &str, modulo: &str, por_modulo: &HashMap<String, String>, por_nombre: &HashMap<String, Vec<String>>) -> Option<String> {
    let carpeta = dirname(origen);
    if modulo.starts_with("./") || modulo.starts_with("../") || modulo.contains('/') {
        let base = normpath(&join(carpeta, modulo));
        let mut cands = vec![base.clone()];
        for e in [".js", ".ts", ".tsx", ".jsx", ".mjs", ".h", ".hpp", ".cpp"] {
            cands.push(format!("{base}{e}"));
        }
        cands.push(format!("{base}/index.js"));
        cands.push(format!("{base}/index.ts"));
        for cand in cands {
            if por_nombre.get(basename(&cand)).map(|l| l.contains(&cand)).unwrap_or(false) {
                return Some(cand);
            }
        }
        let candidatos = por_nombre.get(basename(modulo));
        return match candidatos {
            Some(l) if l.len() == 1 => Some(l[0].clone()),
            _ => None,
        };
    }
    let mut modulo = modulo.to_string();
    if modulo.starts_with('.') {
        let sin_puntos = modulo.trim_start_matches('.').to_string();
        let nivel = (modulo.chars().count() - sin_puntos.chars().count()) as isize;
        let mut paquete: Vec<String> = if carpeta.is_empty() { vec![] } else { carpeta.split('/').map(|s| s.to_string()).collect() };
        if nivel > 1 {
            paquete = hasta_py(&paquete, paquete.len() as isize - (nivel - 1));
        }
        let mut partes: Vec<String> = paquete.into_iter().filter(|p| !p.is_empty()).collect();
        if !sin_puntos.is_empty() {
            partes.push(sin_puntos);
        }
        modulo = partes.join(".");
    }
    let partes: Vec<String> = modulo.replace("::", ".").split('.').map(|s| s.to_string()).collect();
    let mut prefijos: Vec<String> = vec![];
    if !carpeta.is_empty() {
        prefijos.push(carpeta.replace('/', "."));
        let trozos: Vec<&str> = carpeta.split('/').collect();
        for k in (1..trozos.len()).rev() {
            prefijos.push(trozos[..k].join("."));
        }
    }
    prefijos.push(String::new());
    for k in (1..=partes.len()).rev() {
        let nombre = partes[..k].join(".");
        for pre in &prefijos {
            let cand = if pre.is_empty() { nombre.clone() } else { format!("{pre}.{nombre}") };
            if let Some(r) = por_modulo.get(&cand) {
                return Some(r.clone());
            }
        }
    }
    None
}

#[derive(Clone)]
struct Sim {
    ruta: String,
    nombre: String,
    corto: String,
    tipo: String,
    padre: String,
    firma: String,
}

type Nodo = (String, String);

static RETORNO: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r#"->\s*['"]?([\w.]+)['"]?\s*$"#, ""));

struct Resolucion<'a> {
    primer_nivel: HashMap<String, HashMap<String, String>>,
    metodos: HashMap<(String, String), HashMap<String, String>>,
    global: HashMap<String, Vec<Nodo>>,
    clases: HashMap<String, Vec<Nodo>>,
    anidadas: HashMap<(String, String), HashMap<String, String>>,
    bases: HashMap<(String, String), Vec<Nodo>>,
    retorno: HashMap<Nodo, String>,
    _vida: std::marker::PhantomData<&'a ()>,
}

impl<'a> Resolucion<'a> {
    fn unico(&self, nombre: &str, desde: Option<&str>) -> Option<Nodo> {
        let cand = self.global.get(nombre).cloned().unwrap_or_default();
        let cand: Vec<Nodo> = match desde {
            Some(d) => {
                let familia = lenguaje_de(d);
                cand.into_iter().filter(|x| lenguaje_de(&x.0) == familia).collect()
            }
            None => cand,
        };
        if cand.len() == 1 && !VERBOS_COMUNES.contains(nombre) {
            Some(cand[0].clone())
        } else {
            None
        }
    }

    fn metodo_en(&self, ruta: &str, clase: &str, nombre: &str, profundidad: u32) -> Option<Nodo> {
        if let Some(m) = self.metodos.get(&(ruta.to_string(), clase.to_string())) {
            if let Some(n) = m.get(nombre) {
                return Some((ruta.to_string(), n.clone()));
            }
        }
        if profundidad < 4 {
            if let Some(bs) = self.bases.get(&(ruta.to_string(), clase.to_string())) {
                for b in bs {
                    if let Some(r) = self.metodo_en(&b.0, &b.1, nombre, profundidad + 1) {
                        return Some(r);
                    }
                }
            }
        }
        None
    }

    fn es_clase(&self, nombre_completo: &str) -> bool {
        let corto = nombre_completo.rsplit('.').next().unwrap_or(nombre_completo);
        self.clases.get(corto).map(|l| l.iter().any(|x| x.1 == nombre_completo)).unwrap_or(false)
    }

    fn clase_de_llamada(&self, ruta: &str, clase: &str, receptor: &str) -> Option<Nodo> {
        let base = receptor.split('(').next().unwrap_or("");
        let partes: Vec<&str> = base.split('.').collect();
        let fn_ = if partes.len() == 2 && (partes[0] == "self" || partes[0] == "cls") && !clase.is_empty() {
            self.metodo_en(ruta, clase, partes[1], 0)
        } else if partes.len() == 1 {
            match self.primer_nivel.get(ruta).and_then(|m| m.get(partes[0])) {
                Some(n) => Some((ruta.to_string(), n.clone())),
                None => self.unico(partes[0], Some(ruta)),
            }
        } else {
            return None;
        };
        if let Some(f) = &fn_ {
            if self.es_clase(&f.1) {
                return fn_;
            }
        }
        let tipo = fn_.as_ref().and_then(|f| self.retorno.get(f)).cloned().unwrap_or_default();
        match self.clases.get(&tipo) {
            Some(c) if c.len() == 1 => Some(c[0].clone()),
            _ => None,
        }
    }
}

/// `_anidada`: la función anidada visible desde `dentro`.
fn anidada(anidadas: &HashMap<(String, String), HashMap<String, String>>, ruta: &str, dentro: &str, nombre: &str) -> Option<Nodo> {
    let partes: Vec<&str> = dentro.split('.').collect();
    for k in (1..=partes.len()).rev() {
        if let Some(t) = anidadas.get(&(ruta.to_string(), partes[..k].join("."))) {
            if let Some(n) = t.get(nombre) {
                return Some((ruta.to_string(), n.clone()));
            }
        }
    }
    None
}

impl Banco {
    /// `_resolver_importaciones`.
    pub fn resolver_importaciones(&self) -> Resultado<()> {
        let mut c = self.conectar()?;
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(error)?;
        let rutas = Banco::rutas(&tx)?;
        let mut por_modulo: HashMap<String, String> = HashMap::new();
        let mut por_nombre: HashMap<String, Vec<String>> = HashMap::new();
        for r in &rutas {
            let sin_ext = sin_extension(r);
            por_modulo.insert(sin_ext.replace('/', "."), r.clone());
            if let Some(p) = sin_ext.strip_suffix("/__init__") {
                por_modulo.insert(p.replace('/', "."), r.clone());
            }
            por_nombre.entry(basename(r).to_string()).or_default().push(r.clone());
            por_nombre.entry(basename(sin_ext).to_string()).or_default().push(r.clone());
        }
        let pendientes: Vec<(i64, String, String)> = {
            let mut st = tx.prepare("SELECT rowid, ruta, destino FROM importaciones WHERE destino LIKE '?%'").map_err(error)?;
            let v = st.query_map([], |f| Ok((f.get(0)?, f.get(1)?, f.get(2)?))).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
            v
        };
        for (rowid, ruta, destino) in pendientes {
            let modulo = &destino[1..];
            match resolver(&ruta, modulo, &por_modulo, &por_nombre) {
                Some(d) if d != ruta => {
                    tx.execute("UPDATE importaciones SET destino = ? WHERE rowid = ?", params![d, rowid]).map_err(error)?;
                }
                _ => {
                    tx.execute("DELETE FROM importaciones WHERE rowid = ?", params![rowid]).map_err(error)?;
                }
            }
        }
        tx.execute("DELETE FROM importaciones WHERE rowid NOT IN (SELECT MIN(rowid) FROM importaciones GROUP BY ruta, destino)", []).map_err(error)?;
        tx.commit().map_err(error)?;
        Ok(())
    }

    /// `_resolver_llamadas`: cada uso a su símbolo exacto, por orden de confianza (se rehace entera).
    pub fn resolver_llamadas(&self) -> Resultado<()> {
        let c = self.conectar()?;
        let simbolos: Vec<Sim> = {
            let mut st = c
                .prepare("SELECT ruta, nombre, corto, tipo, padre, firma FROM simbolos WHERE tipo IN ('funcion','metodo','clase','anidada')")
                .map_err(error)?;
            let v = st
                .query_map([], |f| {
                    Ok(Sim {
                        ruta: f.get::<_, Option<String>>(0)?.unwrap_or_default(),
                        nombre: f.get::<_, Option<String>>(1)?.unwrap_or_default(),
                        corto: f.get::<_, Option<String>>(2)?.unwrap_or_default(),
                        tipo: f.get::<_, Option<String>>(3)?.unwrap_or_default(),
                        padre: f.get::<_, Option<String>>(4)?.unwrap_or_default(),
                        firma: f.get::<_, Option<String>>(5)?.unwrap_or_default(),
                    })
                })
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            v
        };
        let rutas = Banco::rutas(&c)?;
        let usos: Vec<(String, String, i64, String, Option<String>)> = {
            let mut st = c.prepare("SELECT ruta, nombre, linea, dentro, receptor FROM usos").map_err(error)?;
            let v = st
                .query_map([], |f| {
                    Ok((
                        f.get::<_, Option<String>>(0)?.unwrap_or_default(),
                        f.get::<_, Option<String>>(1)?.unwrap_or_default(),
                        f.get::<_, Option<i64>>(2)?.unwrap_or(0),
                        f.get::<_, Option<String>>(3)?.unwrap_or_default(),
                        f.get::<_, Option<String>>(4)?,
                    ))
                })
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            v
        };
        let alias: Vec<(String, String, String)> = {
            let mut st = c.prepare("SELECT ruta, nombre, destino FROM alias").map_err(error)?;
            let v = st
                .query_map([], |f| {
                    Ok((
                        f.get::<_, Option<String>>(0)?.unwrap_or_default(),
                        f.get::<_, Option<String>>(1)?.unwrap_or_default(),
                        f.get::<_, Option<String>>(2)?.unwrap_or_default(),
                    ))
                })
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            v
        };
        let bases_raw: Vec<(String, String, String)> = {
            let mut st = c.prepare("SELECT s, o, ruta FROM hechos WHERE r = 'hereda'").map_err(error)?;
            let v = st
                .query_map([], |f| {
                    Ok((
                        f.get::<_, Option<String>>(0)?.unwrap_or_default(),
                        f.get::<_, Option<String>>(1)?.unwrap_or_default(),
                        f.get::<_, Option<String>>(2)?.unwrap_or_default(),
                    ))
                })
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            v
        };
        drop(c);

        let mut r = Resolucion {
            primer_nivel: HashMap::new(),
            metodos: HashMap::new(),
            global: HashMap::new(),
            clases: HashMap::new(),
            anidadas: HashMap::new(),
            bases: HashMap::new(),
            retorno: HashMap::new(),
            _vida: std::marker::PhantomData,
        };
        for x in &simbolos {
            if x.tipo == "anidada" {
                r.anidadas.entry((x.ruta.clone(), x.padre.clone())).or_default().insert(x.corto.clone(), x.nombre.clone());
                continue;
            }
            if x.padre.is_empty() {
                r.primer_nivel.entry(x.ruta.clone()).or_default().insert(x.corto.clone(), x.nombre.clone());
            } else if x.tipo == "metodo" {
                r.metodos.entry((x.ruta.clone(), x.padre.clone())).or_default().insert(x.corto.clone(), x.nombre.clone());
            }
            r.global.entry(x.corto.clone()).or_default().push((x.ruta.clone(), x.nombre.clone()));
            if x.tipo == "clase" {
                r.clases.entry(x.corto.clone()).or_default().push((x.ruta.clone(), x.nombre.clone()));
            }
        }
        let mut por_modulo: HashMap<String, String> = HashMap::new();
        let mut por_nombre: HashMap<String, Vec<String>> = HashMap::new();
        for ruta in &rutas {
            let sin_ext = sin_extension(ruta);
            por_modulo.insert(sin_ext.replace('/', "."), ruta.clone());
            if let Some(p) = sin_ext.strip_suffix("/__init__") {
                por_modulo.insert(p.replace('/', "."), ruta.clone());
            }
            por_nombre.entry(basename(ruta).to_string()).or_default().push(ruta.clone());
        }
        // alias: (ruta, nombre) → (archivo destino, símbolo o None si es un módulo)
        let mut resueltos: HashMap<(String, String), (String, Option<String>)> = HashMap::new();
        for (ruta, nombre, destino) in &alias {
            let modulo = resolver(ruta, destino, &por_modulo, &por_nombre);
            let limpio = destino.trim_start_matches('.');
            let destino_mod = por_modulo.get(&limpio.replace('/', "."));
            let coincide = match &modulo {
                Some(m) => Some(m) == destino_mod || sin_extension(m).replace('/', ".").ends_with(limpio),
                None => false,
            };
            if coincide {
                resueltos.insert((ruta.clone(), nombre.clone()), (modulo.clone().unwrap(), None));
            } else if limpio.contains('.') {
                let partes = rsplit1(destino, ".");
                let (padre, simbolo) = (partes[0], partes[1]);
                let archivo = if !strip_de(padre, ".").is_empty() { resolver(ruta, padre, &por_modulo, &por_nombre) } else { None };
                let en_archivo = archivo.as_ref().and_then(|a| r.primer_nivel.get(a)).and_then(|m| m.get(simbolo)).cloned();
                if let (Some(a), Some(s)) = (&archivo, en_archivo) {
                    resueltos.insert((ruta.clone(), nombre.clone()), (a.clone(), Some(s)));
                } else if let Some(m) = &modulo {
                    resueltos.insert((ruta.clone(), nombre.clone()), (m.clone(), None));
                }
            }
        }
        for (s, o, ruta) in &bases_raw {
            let corto = o.rsplit('.').next().unwrap_or(o).split('[').next().unwrap_or("");
            let todas = r.clases.get(corto).cloned().unwrap_or_default();
            let mismas: Vec<Nodo> = todas.iter().filter(|x| &x.0 == ruta).cloned().collect();
            let cand = if !mismas.is_empty() { mismas } else { todas };
            if cand.len() == 1 {
                r.bases.entry((ruta.clone(), s.clone())).or_default().push(cand[0].clone());
            }
        }
        for x in &simbolos {
            if let Some(m) = RETORNO.buscar(&x.firma) {
                let t = m.g(1);
                r.retorno.insert((x.ruta.clone(), x.nombre.clone()), t.rsplit('.').next().unwrap_or(t).to_string());
            }
        }

        let mut filas: Vec<(String, String, String, String, i64, &'static str)> = vec![];
        for (ruta, n, linea, dentro, receptor) in &usos {
            let clase = match dentro.rfind('.') {
                Some(i) => &dentro[..i],
                None => "",
            };
            let mut destino: Option<Nodo> = None;
            let mut confianza = "exacta";
            match receptor.as_deref() {
                None => {
                    if let Some(m) = r.primer_nivel.get(ruta).and_then(|m| m.get(n)) {
                        destino = Some((ruta.clone(), m.clone()));
                    } else if let (true, Some(m)) = (!clase.is_empty(), if clase.is_empty() { None } else { r.metodo_en(ruta, clase, n, 0) }) {
                        destino = Some(m);
                    } else {
                        destino = r.unico(n, Some(ruta));
                        confianza = "unica";
                    }
                }
                Some("") if anidada(&r.anidadas, ruta, dentro, n).is_some() => {
                    destino = anidada(&r.anidadas, ruta, dentro, n);
                }
                Some("") => {
                    if let Some(m) = r.primer_nivel.get(ruta).and_then(|m| m.get(n)) {
                        destino = Some((ruta.clone(), m.clone()));
                    } else if let Some((archivo, simbolo)) = resueltos.get(&(ruta.clone(), n.clone())) {
                        destino = simbolo.as_ref().map(|s| (archivo.clone(), s.clone()));
                    } else {
                        destino = r.unico(n, Some(ruta));
                        confianza = "unica";
                    }
                    if let Some(d) = &destino {
                        if r.es_clase(&d.1) {
                            let init = r.metodo_en(&d.0, &d.1, "__init__", 0);
                            if init.is_some() {
                                destino = init;
                            }
                        }
                    }
                }
                Some(rec) if rec == "self" || rec == "cls" || rec == "super()" => {
                    destino = if !clase.is_empty() { r.metodo_en(ruta, clase, n, 0) } else { None };
                    if rec == "super()" && !clase.is_empty() {
                        destino = None;
                        if let Some(bs) = r.bases.get(&(ruta.clone(), clase.to_string())) {
                            for b in bs {
                                if let Some(m) = r.metodo_en(&b.0, &b.1, n, 0) {
                                    destino = Some(m);
                                    break;
                                }
                            }
                        }
                    }
                }
                Some(rec) => {
                    let clave = (ruta.clone(), rec.to_string());
                    match resueltos.get(&clave) {
                        Some((archivo, None)) => {
                            if let Some(m) = r.primer_nivel.get(archivo).and_then(|m| m.get(n)) {
                                destino = Some((archivo.clone(), m.clone()));
                            }
                        }
                        Some((archivo, Some(simbolo))) => {
                            destino = r.metodo_en(archivo, simbolo, n, 0);
                        }
                        None => {
                            if let Some(c) = r.clases.get(rec).filter(|c| c.len() == 1) {
                                destino = r.metodo_en(&c[0].0, &c[0].1, n, 0);
                            } else if rec.ends_with(')') && r.clase_de_llamada(ruta, clase, rec).is_some() {
                                let (c_ruta, c_nombre) = r.clase_de_llamada(ruta, clase, rec).unwrap();
                                destino = r.metodo_en(&c_ruta, &c_nombre, n, 0);
                            } else {
                                destino = r.unico(n, Some(ruta));
                                confianza = "aproximada";
                            }
                        }
                    }
                }
            }
            if let Some(d) = destino {
                if !(d.0 == *ruta && d.1 == *dentro) {
                    filas.push((ruta.clone(), dentro.clone(), d.0, d.1, *linea, confianza));
                }
            }
        }
        let mut c = self.conectar()?;
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(error)?;
        tx.execute("DELETE FROM llamadas", []).map_err(error)?;
        {
            let mut ins = tx.prepare("INSERT INTO llamadas VALUES (?,?,?,?,?,?)").map_err(error)?;
            for f in &filas {
                ins.execute(params![f.0, f.1, f.2, f.3, f.4, f.5]).map_err(error)?;
            }
        }
        tx.commit().map_err(error)?;
        Ok(())
    }
}
