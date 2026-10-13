//! Listado, lectura, indexación y sincronización (BancoProyecto._listar … sincronizar, _indexar_archivo,
//! _fragmentar, _resumen_basico, _texto_de_cuaderno, _anotar_cambio, _marcar_revisar). El análisis de cada
//! archivo corre en paralelo; las escrituras van en el orden de Python (de él dependen los ids).

use std::collections::{BTreeSet, HashMap, HashSet};
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::process::{Command, Stdio};
use std::sync::LazyLock;
use std::time::{Duration, Instant};

use indexmap::IndexMap;
use rayon::prelude::*;
use rusqlite::{params, Connection};
use serde_json::{json, Value};

use super::{ahora, comprimir, descomprimir, error, Banco, Resultado};
use crate::extraer::generico::{importaciones_genericas, primera_linea, secciones_markdown, simbolos_genericos, sin_comentario, COMENTARIO_LINEA};
use crate::extraer::python::{alias_de, simbolos_de};
use crate::extraer::{extraer_hechos, Hecho, Simbolo};
use crate::py::cadena::{largo, primeros, splitlines, strip, strip_de};
use crate::py::difflib::unified_diff;
use crate::py::json::{dumps, loads};
use crate::py::numero::round;
use crate::py::ruta::join;
use crate::pyast::{con_pila, cota_de_profundidad, Arbol};
use crate::re::Re;
use crate::texto::{estimar_tokens, lenguaje_de, sha, terminos, EXCLUIR_NOMBRES, IGNORADAS, LINEAS_BLOQUE_SUELTO, MAX_ARCHIVOS, MAX_BYTES, MAX_BYTES_DATOS, MAX_CAMBIOS_GUARDADOS, MAX_DIFF, MAX_LINEAS_FRAGMENTO};

/// Un fragmento para el índice.
#[derive(Clone, Debug)]
pub struct Fragmento {
    pub ini: i64,
    pub fin: i64,
    pub simbolo: String,
    pub tipo: String,
    pub texto: String,
}

/// Todo lo que sale de analizar un archivo (sin tocar la base).
pub struct Analisis {
    pub lenguaje: &'static str,
    pub texto: String,
    pub lineas: usize,
    pub tokens: i64,
    pub resumen: String,
    pub simbolos: Vec<Simbolo>,
    pub shas_simbolos: Vec<String>,
    pub alias: Vec<(String, String)>,
    pub hechos: Vec<Hecho>,
    pub importados: Vec<String>,
    pub fragmentos: Vec<(Fragmento, String, i64, String, String, String)>,
    pub contenido: Vec<u8>,
}

/// `_leer`: hasta MAX_BYTES + 1, None si no se puede leer o hay un NUL en los primeros 8 KB.
pub fn leer(ruta: &str) -> Option<String> {
    let mut f = std::fs::File::open(ruta).ok()?;
    let mut datos = Vec::new();
    f.by_ref().take((MAX_BYTES + 1) as u64).read_to_end(&mut datos).ok()?;
    if datos[..datos.len().min(8192)].contains(&0) {
        return None;
    }
    Some(String::from_utf8_lossy(&datos).into_owned())
}

/// `git -C raiz ls-files -co --exclude-standard -z` (None si no es un repositorio o git falla).
fn listar_git(raiz: &str) -> Option<Vec<String>> {
    let mut hijo = Command::new("git")
        .args(["-C", raiz, "ls-files", "-co", "--exclude-standard", "-z"])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;
    let mut salida = hijo.stdout.take()?;
    let lector = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = salida.read_to_end(&mut b);
        b
    });
    let mut err = hijo.stderr.take()?;
    let lector_err = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = err.read_to_end(&mut b);
    });
    let limite = Instant::now() + Duration::from_secs(20);
    let estado = loop {
        match hijo.try_wait() {
            Ok(Some(e)) => break Some(e),
            Ok(None) => {
                if Instant::now() > limite {
                    let _ = hijo.kill();
                    let _ = hijo.wait();
                    break None;
                }
                std::thread::sleep(Duration::from_millis(5));
            }
            Err(_) => break None,
        }
    };
    let bytes = lector.join().ok()?;
    let _ = lector_err.join();
    let estado = estado?;
    if !estado.success() {
        return None;
    }
    let texto = String::from_utf8_lossy(&bytes);
    Some(texto.split('\0').filter(|p| !p.is_empty()).map(|p| p.to_string()).collect())
}

/// `_listar_disco`: os.walk ordenado, sin carpetas ignoradas ni ocultas.
fn listar_disco(raiz: &str) -> Vec<String> {
    let mut salida = vec![];
    fn caminar(raiz: &str, rel: &str, salida: &mut Vec<String>) -> bool {
        let carpeta = if rel.is_empty() { raiz.to_string() } else { join(raiz, rel) };
        let Ok(entradas) = std::fs::read_dir(&carpeta) else { return true };
        let mut dirs = vec![];
        let mut archivos = vec![];
        for e in entradas.flatten() {
            let nombre = e.file_name().to_string_lossy().to_string();
            // os.walk: is_dir sigue los enlaces; no entra en carpetas enlazadas
            let es_dir = std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false);
            if es_dir {
                let enlace = e.file_type().map(|t| t.is_symlink()).unwrap_or(false);
                dirs.push((nombre, enlace));
            } else {
                archivos.push(nombre);
            }
        }
        dirs.retain(|(d, _)| !IGNORADAS.contains(d.as_str()) && !d.starts_with('.'));
        dirs.sort();
        archivos.sort();
        for n in archivos {
            if n.starts_with('.') {
                continue;
            }
            salida.push(if rel.is_empty() { n } else { format!("{rel}/{n}") });
            if salida.len() >= MAX_ARCHIVOS * 2 {
                return false;
            }
        }
        for (d, enlace) in dirs {
            if enlace {
                continue;
            }
            let sub = if rel.is_empty() { d } else { format!("{rel}/{d}") };
            if !caminar(raiz, &sub, salida) {
                return false;
            }
        }
        true
    }
    caminar(raiz, "", &mut salida);
    salida
}

impl Banco {
    /// `_listar`: ruta → (mtime, tamaño), en el orden de git (o del disco).
    pub fn listar(&self) -> IndexMap<String, (f64, i64)> {
        let rutas = listar_git(&self.raiz).unwrap_or_else(|| listar_disco(&self.raiz));
        let mut salida: IndexMap<String, (f64, i64)> = IndexMap::new();
        for rel in rutas {
            let partes: Vec<&str> = rel.split('/').collect();
            let (carpetas, nombre) = partes.split_at(partes.len() - 1);
            if carpetas.iter().any(|p| IGNORADAS.contains(p) || p.starts_with('.')) {
                continue;
            }
            let nombre = nombre[0];
            let Some(lenguaje) = lenguaje_de(nombre) else { continue };
            if EXCLUIR_NOMBRES.hay(&nombre.to_lowercase()) {
                continue;
            }
            let ruta = join(&self.raiz, &rel);
            let Ok(st) = std::fs::metadata(&ruta) else { continue };
            let limite = if lenguaje == "datos" || lenguaje == "cuaderno" { MAX_BYTES_DATOS } else { MAX_BYTES };
            if st.size() as usize > limite || !st.is_file() {
                continue;
            }
            // st_mtime de CPython: segundos + nanosegundos · 1e-9 en doble precisión
            let mtime = st.mtime() as f64 + st.mtime_nsec() as f64 * 1e-9;
            salida.insert(rel, (mtime, st.size() as i64));
            if salida.len() >= MAX_ARCHIVOS {
                break;
            }
        }
        salida
    }
}

/// `_texto_de_cuaderno`: las celdas de un .ipynb como texto (markdown con «# »).
pub fn texto_de_cuaderno(texto: &str) -> String {
    let Some(nb) = loads(texto) else { return texto.to_string() };
    let celdas = match nb.get("cells") {
        Some(Value::Array(c)) => c.clone(),
        _ => vec![],
    };
    let mut partes = vec![];
    for celda in celdas {
        let fuente = match celda.get("source") {
            Some(Value::Array(xs)) => xs.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect::<Vec<_>>().concat(),
            Some(Value::String(s)) => s.clone(),
            _ => String::new(),
        };
        if celda.get("cell_type").and_then(|t| t.as_str()) == Some("markdown") {
            partes.push(splitlines(&fuente).iter().map(|l| format!("# {l}")).collect::<Vec<_>>().join("\n"));
        } else {
            partes.push(fuente);
        }
    }
    partes.join("\n\n")
}

/// `_resumen_basico`.
pub fn resumen_basico(lenguaje: &str, texto: &str, docmod: &str) -> String {
    if !docmod.is_empty() {
        return primera_linea(docmod, 200);
    }
    if lenguaje == "md" {
        for l in splitlines(texto) {
            if strip(l).starts_with('#') {
                return primeros(strip(strip_de(l, "# ")), 200).to_string();
            }
        }
    }
    let lineas = splitlines(texto);
    let mut cabecera: Vec<String> = vec![];
    for l in lineas.iter().take(40) {
        let s = strip(l);
        if s.is_empty() || s.starts_with("#!") || s.starts_with("# -*-") {
            if !cabecera.is_empty() {
                break;
            }
            continue;
        }
        if COMENTARIO_LINEA.hay(l) || s.starts_with("\"\"\"") || s.starts_with("'''") {
            let limpio = sin_comentario(s);
            let limpio = strip_de(&limpio, "\"' */").to_string();
            if !limpio.is_empty() {
                cabecera.push(limpio);
            }
            if cabecera.len() >= 2 {
                break;
            }
        } else if !cabecera.is_empty() || !["import", "from", "#include", "package", "using", "use "].iter().any(|p| s.starts_with(p)) {
            break;
        }
    }
    primeros(&cabecera.join(" "), 200).to_string()
}

/// `_fragmentar`.
pub fn fragmentar(lineas: &[&str], simbolos: &[Simbolo]) -> Vec<Fragmento> {
    let mut fragmentos: Vec<Fragmento> = vec![];
    let tope = simbolos.iter().map(|s| s.fin.max(0) as usize + 2).max().unwrap_or(0).max(lineas.len() + 2);
    let mut cubiertas = vec![false; tope];
    let unir = |ini: i64, fin: i64| -> String {
        let a = (ini - 1).max(0) as usize;
        let b = (fin.max(0) as usize).min(lineas.len());
        if a < b {
            lineas[a..b].join("\n")
        } else {
            String::new()
        }
    };
    let agregar = |ini: i64, fin: i64, simbolo: &str, tipo: &str, texto: String, fragmentos: &mut Vec<Fragmento>| {
        if strip(&texto).is_empty() {
            return;
        }
        fragmentos.push(Fragmento { ini, fin, simbolo: simbolo.to_string(), tipo: tipo.to_string(), texto });
    };
    for s in simbolos {
        if s.tipo == "clase" || s.tipo == "espacio" {
            let hijos: Vec<&Simbolo> = simbolos.iter().filter(|h| h.padre == s.nombre).collect();
            let mut cabecera_fin = hijos.iter().map(|h| h.ini - 1).chain(std::iter::once(s.fin)).min().unwrap();
            cabecera_fin = cabecera_fin.min(s.ini + 40);
            let mut texto = unir(s.ini, cabecera_fin);
            if !hijos.is_empty() {
                let lista: Vec<String> = hijos.iter().take(40).map(|h| format!("{} (l. {})", h.firma, h.ini)).collect();
                texto.push_str(&format!("\n    # métodos: {}", lista.join("; ")));
            }
            agregar(s.ini, cabecera_fin, &s.nombre, &s.tipo, texto, &mut fragmentos);
            let hasta = if hijos.is_empty() { s.fin } else { cabecera_fin };
            for k in s.ini..=hasta {
                if k >= 0 && (k as usize) < cubiertas.len() {
                    cubiertas[k as usize] = true;
                }
            }
        }
    }
    for s in simbolos.iter().filter(|s| s.tipo != "clase" && s.tipo != "espacio" && s.tipo != "anidada") {
        let largo_s = s.fin - s.ini + 1;
        if largo_s <= MAX_LINEAS_FRAGMENTO {
            agregar(s.ini, s.fin, &s.nombre, &s.tipo, unir(s.ini, s.fin), &mut fragmentos);
        } else {
            let mut parte = 1;
            let mut ini = s.ini;
            while ini <= s.fin {
                let fin = s.fin.min(ini + MAX_LINEAS_FRAGMENTO - 1);
                let mut texto = unir(ini, fin);
                if parte > 1 {
                    texto = format!("# {}  (continuación {})\n{}", s.firma, parte, texto);
                }
                agregar(ini, fin, &s.nombre, &s.tipo, texto, &mut fragmentos);
                parte += 1;
                ini += MAX_LINEAS_FRAGMENTO;
            }
        }
        for k in s.ini..=s.fin {
            if k >= 0 && (k as usize) < cubiertas.len() {
                cubiertas[k as usize] = true;
            }
        }
    }
    let total = lineas.len();
    let mut n = 1usize;
    while n <= total {
        if cubiertas[n] {
            n += 1;
            continue;
        }
        let ini = n;
        while n <= total && !cubiertas[n] && n - ini < LINEAS_BLOQUE_SUELTO {
            n += 1;
        }
        if (ini..n).any(|k| !strip(lineas[k - 1]).is_empty()) {
            agregar(ini as i64, (n - 1) as i64, "", "bloque", unir(ini as i64, (n - 1) as i64), &mut fragmentos);
        }
    }
    fragmentos.sort_by_key(|f| f.ini);
    fragmentos
}

/// Analiza un archivo como `_indexar_archivo` (sin escribir): símbolos, hechos, fragmentos y sus términos.
pub fn analizar(rel: &str, texto_original: &str) -> Analisis {
    let lenguaje = lenguaje_de(rel).unwrap_or("texto");
    let texto = if lenguaje == "cuaderno" { texto_de_cuaderno(texto_original) } else { texto_original.to_string() };
    if lenguaje != "python" && lenguaje != "cuaderno" {
        return analizar_texto(rel, lenguaje, texto, false);
    }
    // El árbol y todo lo que lo recorre, con la pila que pida el texto (pyast::con_pila); None: CPython lo rechaza por
    // sus topes de anidamiento y el archivo queda sin árbol, como con un error de sintaxis
    match cota_de_profundidad(&texto) {
        None => analizar_texto(rel, lenguaje, texto, false),
        Some(niveles) => match con_pila(niveles, || analizar_texto(rel, lenguaje, texto.clone(), true)) {
            Some(a) => a,
            None => analizar_texto(rel, lenguaje, texto, false),
        },
    }
}

fn analizar_texto(rel: &str, lenguaje: &'static str, texto: String, con_arbol: bool) -> Analisis {
    let lineas = splitlines(&texto);
    let mut importados: Vec<String> = vec![];
    let mut docmod = String::new();
    let mut alias = vec![];
    let arbol = if con_arbol { Arbol::analizar_aqui(&texto) } else { None };
    let simbolos = if lenguaje == "python" || lenguaje == "cuaderno" {
        match &arbol {
            Some(a) => {
                let (s, i, d) = simbolos_de(a);
                importados = i;
                docmod = d;
                alias = alias_de(a);
                s
            }
            None => vec![],
        }
    } else if lenguaje == "md" {
        secciones_markdown(&texto)
    } else {
        let s = simbolos_genericos(&texto, lenguaje);
        importados = importaciones_genericas(&texto, lenguaje);
        s
    };
    let resumen = resumen_basico(lenguaje, &texto, &docmod);
    let shas_simbolos = simbolos
        .iter()
        .map(|s| {
            let a = (s.ini - 1).max(0) as usize;
            let b = (s.fin.max(0) as usize).min(lineas.len());
            sha(&if a < b { lineas[a..b].join("\n") } else { String::new() })
        })
        .collect();
    let hechos = extraer_hechos(rel, lenguaje, &texto, &simbolos, arbol.as_ref());
    let terminos_ruta = terminos(rel, 4000).join(" ");
    let fragmentos = fragmentar(&lineas, &simbolos)
        .into_iter()
        .map(|f| {
            let sha_f = sha(&format!("{rel}\0{}", f.texto));
            let tokens = estimar_tokens(&f.texto);
            let ts = terminos(&f.simbolo, 4000).join(" ");
            let tt = terminos(&f.texto, 4000).join(" ");
            (f, sha_f, tokens, terminos_ruta.clone(), ts, tt)
        })
        .collect();
    Analisis {
        lenguaje,
        lineas: lineas.len(),
        tokens: estimar_tokens(&texto),
        resumen,
        simbolos,
        shas_simbolos,
        alias,
        hechos,
        importados,
        fragmentos,
        contenido: comprimir(&texto),
        texto,
    }
}

/// `_borrar_archivo`.
pub fn borrar_archivo(c: &Connection, rel: &str, conservar_archivo: bool) -> Resultado<()> {
    let ids: Vec<i64> = {
        let mut st = c.prepare_cached("SELECT id FROM fragmentos WHERE ruta = ?").map_err(error)?;
        let v = st.query_map(params![rel], |f| f.get(0)).map_err(error)?.collect::<rusqlite::Result<Vec<i64>>>().map_err(error)?;
        v
    };
    for i in ids {
        c.execute("DELETE FROM fragmentos_fts WHERE rowid = ?", params![i]).map_err(error)?;
    }
    for sql in [
        "DELETE FROM fragmentos WHERE ruta = ?",
        "DELETE FROM simbolos WHERE ruta = ?",
        "DELETE FROM usos WHERE ruta = ?",
        "DELETE FROM alias WHERE ruta = ?",
        "DELETE FROM importaciones WHERE ruta = ?",
        "DELETE FROM hechos WHERE ruta = ? AND origen = 'codigo'",
    ] {
        c.execute(sql, params![rel]).map_err(error)?;
    }
    if !conservar_archivo {
        c.execute("DELETE FROM archivos WHERE ruta = ?", params![rel]).map_err(error)?;
    }
    Ok(())
}

/// `_simbolos_de`: nombre → sha del cuerpo (el último gana si se repite el nombre).
pub fn simbolos_de_ruta(c: &Connection, rel: &str) -> Resultado<IndexMap<String, Option<String>>> {
    let mut st = c.prepare_cached("SELECT nombre, sha FROM simbolos WHERE ruta = ?").map_err(error)?;
    let mut filas = st.query(params![rel]).map_err(error)?;
    let mut m = IndexMap::new();
    while let Some(f) = filas.next().map_err(error)? {
        let n: String = f.get::<_, Option<String>>(0).map_err(error)?.unwrap_or_default();
        let s: Option<String> = f.get(1).map_err(error)?;
        m.insert(n, s);
    }
    Ok(m)
}

/// Escribe el análisis de un archivo (la parte de `_indexar_archivo` que toca la base).
pub fn escribir_analisis(c: &Connection, rel: &str, sha_texto: &str, mtime: f64, tamano: i64, version: i64, a: &Analisis) -> Resultado<()> {
    borrar_archivo(c, rel, true)?;
    c.execute(
        "INSERT INTO archivos (ruta, sha, mtime, tamano, lenguaje, lineas, tokens, resumen, contenido, version)
                     VALUES (?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(ruta) DO UPDATE SET sha=excluded.sha, mtime=excluded.mtime,
                       tamano=excluded.tamano, lenguaje=excluded.lenguaje, lineas=excluded.lineas,
                       tokens=excluded.tokens, resumen=excluded.resumen, contenido=excluded.contenido,
                       version=excluded.version",
        params![rel, sha_texto, mtime, tamano, a.lenguaje, a.lineas as i64, a.tokens, a.resumen, a.contenido, version],
    )
    .map_err(error)?;
    {
        let mut ins_s = c
            .prepare_cached("INSERT INTO simbolos (ruta, nombre, corto, tipo, firma, doc, ini, fin, padre, sha) VALUES (?,?,?,?,?,?,?,?,?,?)")
            .map_err(error)?;
        let mut ins_u = c.prepare_cached("INSERT INTO usos (ruta, nombre, linea, dentro, receptor) VALUES (?,?,?,?,?)").map_err(error)?;
        for (s, sh) in a.simbolos.iter().zip(a.shas_simbolos.iter()) {
            ins_s.execute(params![rel, s.nombre, s.corto, s.tipo, s.firma, s.doc, s.ini, s.fin, s.padre, sh]).map_err(error)?;
            for u in &s.usos {
                ins_u.execute(params![rel, u.nombre, u.linea, s.nombre, u.receptor]).map_err(error)?;
            }
        }
    }
    {
        let mut ins = c.prepare_cached("INSERT INTO alias VALUES (?,?,?)").map_err(error)?;
        for (al, destino) in &a.alias {
            ins.execute(params![rel, al, destino]).map_err(error)?;
        }
    }
    {
        let mut ins = c.prepare_cached("INSERT INTO hechos (s, r, o, ruta, linea, origen, version) VALUES (?,?,?,?,?,'codigo',?)").map_err(error)?;
        for h in &a.hechos {
            ins.execute(params![h.s, h.r, h.o, rel, h.linea, version]).map_err(error)?;
        }
    }
    {
        let mut ins = c.prepare_cached("INSERT INTO importaciones VALUES (?, ?)").map_err(error)?;
        for m in &a.importados {
            ins.execute(params![rel, format!("?{m}")]).map_err(error)?;
        }
    }
    {
        let mut ins_f = c.prepare_cached("INSERT INTO fragmentos (ruta, simbolo, tipo, ini, fin, texto, sha, tokens) VALUES (?,?,?,?,?,?,?,?)").map_err(error)?;
        let mut ins_t = c.prepare_cached("INSERT INTO fragmentos_fts (rowid, ruta, simbolo, terminos) VALUES (?,?,?,?)").map_err(error)?;
        for (f, sh, tokens, tr, ts, tt) in &a.fragmentos {
            ins_f.execute(params![rel, f.simbolo, f.tipo, f.ini, f.fin, f.texto, sh, tokens]).map_err(error)?;
            let id = c.last_insert_rowid();
            ins_t.execute(params![id, tr, ts, tt]).map_err(error)?;
        }
    }
    Ok(())
}

/// `_anotar_cambio`.
fn anotar_cambio(c: &Connection, version: i64, rel: &str, tipo: &str, previo: &str, nuevo: &str, viejos: &IndexMap<String, Option<String>>, nuevos: &IndexMap<String, Option<String>>) -> Resultado<()> {
    let a = splitlines(previo);
    let b = splitlines(nuevo);
    let diff_lineas = unified_diff(&a, &b, 2);
    let mas = diff_lineas.iter().filter(|l| l.starts_with('+') && !l.starts_with("+++")).count() as i64;
    let menos = diff_lineas.iter().filter(|l| l.starts_with('-') && !l.starts_with("---")).count() as i64;
    let mut diff = if tipo == "modificado" { diff_lineas.iter().skip(2).cloned().collect::<Vec<_>>().join("\n") } else { String::new() };
    if largo(&diff) > MAX_DIFF {
        diff = format!("{}\n[… diff recortado]", primeros(&diff, MAX_DIFF));
    }
    let k_viejos: BTreeSet<&String> = viejos.keys().collect();
    let k_nuevos: BTreeSet<&String> = nuevos.keys().collect();
    let simbolos = json!({
        "nuevos": k_nuevos.difference(&k_viejos).collect::<Vec<_>>(),
        "borrados": k_viejos.difference(&k_nuevos).collect::<Vec<_>>(),
        "modificados": k_viejos.intersection(&k_nuevos).filter(|n| viejos[**n] != nuevos[**n]).collect::<Vec<_>>(),
    });
    if tipo == "modificado" && mas == 0 && menos == 0 {
        return Ok(());
    }
    c.execute(
        "INSERT INTO cambios (version, ruta, tipo, cuando, simbolos, diff, mas, menos) VALUES (?,?,?,?,?,?,?,?)",
        params![version, rel, tipo, ahora(), dumps(&simbolos, false), diff, if tipo != "borrado" { mas } else { 0 }, if tipo != "nuevo" { menos } else { 0 }],
    )
    .map_err(error)?;
    Ok(())
}

static MAYUSCULA: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"[A-Z]", ""));

/// `_marcar_revisar`: las notas de los archivos que cambiaron y las que nombran un símbolo que cambió.
pub fn marcar_revisar(c: &Connection, rutas: &HashSet<String>, version: i64, simbolos: &HashSet<String>) -> Resultado<()> {
    if rutas.is_empty() {
        return Ok(());
    }
    let mut nombres: HashSet<String> = HashSet::new();
    for s in simbolos {
        for n in [s.as_str(), s.rsplit('.').next().unwrap_or(s)] {
            if largo(n) >= 4 {
                nombres.insert(n.to_string());
            }
        }
    }
    let es_codigo = |n: &str| n.contains('.') || n.contains('_') || MAYUSCULA.hay(crate::py::cadena::desde(n, 1));
    let mut de_codigo: Vec<String> = nombres.iter().filter(|n| es_codigo(n)).map(|n| Re::escapar(n)).collect();
    let mut de_texto: Vec<String> = nombres.iter().filter(|n| !es_codigo(n)).map(|n| Re::escapar(n)).collect();
    de_codigo.sort_by_key(|n| std::cmp::Reverse(n.len()));
    de_texto.sort_by_key(|n| std::cmp::Reverse(n.len()));
    let mut partes = vec![];
    if !de_codigo.is_empty() {
        partes.push(format!(r"(?<![\w.])(?:{})(?![\w])", de_codigo.join("|")));
    }
    if !de_texto.is_empty() {
        partes.push(format!(r"`(?:{t})`|(?<![\w.])(?:{t})\(", t = de_texto.join("|")));
    }
    let menciona = if partes.is_empty() { None } else { Re::intentar(&partes.join("|"), "").ok() };
    let notas: Vec<(i64, Option<String>, Option<String>, Option<String>)> = {
        let mut st = c.prepare("SELECT id, rutas, titulo, texto FROM conocimiento WHERE revisar = 0").map_err(error)?;
        let v = st.query_map([], |f| Ok((f.get(0)?, f.get(1)?, f.get(2)?, f.get(3)?))).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
        v
    };
    for (id, rutas_nota, titulo, texto) in notas {
        let suyas: HashSet<String> = match loads(rutas_nota.as_deref().filter(|s| !s.is_empty()).unwrap_or("[]")) {
            Some(Value::Array(xs)) => xs.into_iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect(),
            _ => HashSet::new(),
        };
        let toca = suyas.iter().any(|r| rutas.contains(r));
        // f"{titulo}\n{texto}" de Python: un NULL se escribe «None»
        let nombra = || menciona.as_ref().map(|m| m.hay(&format!("{}\n{}", titulo.as_deref().unwrap_or("None"), texto.as_deref().unwrap_or("None")))).unwrap_or(false);
        if toca || nombra() {
            c.execute("UPDATE conocimiento SET revisar = ? WHERE id = ?", params![version, id]).map_err(error)?;
        }
    }
    Ok(())
}

/// Lo que devuelve `sincronizar`.
pub struct Sincronizacion {
    pub inicial: bool,
    pub nuevos: usize,
    pub modificados: usize,
    pub borrados: usize,
    pub rutas: Vec<String>,
    pub version: i64,
    pub archivos: usize,
    pub segundos: f64,
}

impl Sincronizacion {
    pub fn a_valor(&self) -> Value {
        json!({"inicial": self.inicial, "nuevos": self.nuevos, "modificados": self.modificados, "borrados": self.borrados,
               "rutas": self.rutas, "version": self.version, "archivos": self.archivos, "segundos": self.segundos})
    }
}

impl Banco {
    /// `sincronizar`: relee solo lo que cambió (fecha y tamaño; luego el sha).
    pub fn sincronizar(&self, mut forzar: bool) -> Resultado<Sincronizacion> {
        let t0 = Instant::now();
        if self.meta("reindexar")?.as_deref() == Some("1") {
            forzar = true;
            self.guardar_meta("reindexar", "0")?;
        }
        let _guardia = self.cerrojo.lock().unwrap();
        let listado = self.listar();
        let conocidos: IndexMap<String, (Option<f64>, Option<i64>, Option<String>)> = {
            let c = self.conectar()?;
            let mut st = c.prepare("SELECT ruta, mtime, tamano, sha FROM archivos").map_err(error)?;
            let v = st
                .query_map([], |f| Ok((f.get::<_, String>(0)?, (f.get::<_, Option<f64>>(1)?, f.get::<_, Option<i64>>(2)?, f.get::<_, Option<String>>(3)?))))
                .map_err(error)?
                .collect::<rusqlite::Result<IndexMap<_, _>>>()
                .map_err(error)?;
            v
        };
        let inicial = conocidos.is_empty();
        let candidatos: Vec<&String> = listado
            .iter()
            .filter(|(r, (mt, tam))| match conocidos.get(*r) {
                None => true,
                Some((cmt, ctam, _)) => forzar || *cmt != Some(*mt) || *ctam != Some(*tam),
            })
            .map(|(r, _)| r)
            .collect();
        let borrados: Vec<String> = conocidos.keys().filter(|r| !listado.contains_key(*r)).cloned().collect();
        // Leer y analizar en paralelo (en el orden de los candidatos)
        let leidos: Vec<Option<(String, String)>> = candidatos
            .par_iter()
            .map(|rel| leer(&join(&self.raiz, rel)).map(|t| {
                let s = sha(&t);
                (t, s)
            }))
            .collect();
        let analisis: Vec<Option<Analisis>> = candidatos
            .par_iter()
            .zip(leidos.par_iter())
            .map(|(rel, l)| {
                let (texto, sh) = l.as_ref()?;
                if let Some((_, _, Some(csha))) = conocidos.get(*rel) {
                    if csha == sh && !forzar {
                        return None;
                    }
                }
                Some(analizar(rel, texto))
            })
            .collect();
        let mut nuevos: Vec<String> = vec![];
        let mut modificados: Vec<String> = vec![];
        let mut tocados: Vec<String> = vec![];
        let mut simbolos_cambiados: HashSet<String> = HashSet::new();
        let version = self.version()? + 1;
        let mut c = self.conectar()?;
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(error)?;
        for ((rel, l), an) in candidatos.iter().zip(leidos.iter()).zip(analisis.iter()) {
            let Some((texto, sh)) = l else { continue };
            let (mt, tam) = listado[*rel];
            let conocido = conocidos.get(*rel);
            if let Some((_, _, Some(csha))) = conocido {
                if csha == sh && !forzar {
                    tx.execute("UPDATE archivos SET mtime = ?, tamano = ? WHERE ruta = ?", params![mt, tam, rel]).map_err(error)?;
                    continue;
                }
            }
            let mut previo: Option<String> = None;
            if conocido.is_some() && !inicial {
                let f: Option<Option<Vec<u8>>> = tx.query_row("SELECT contenido FROM archivos WHERE ruta = ?", params![rel], |f| f.get(0)).ok();
                previo = Some(match f {
                    Some(Some(b)) if !b.is_empty() => descomprimir(&b),
                    _ => String::new(),
                });
            }
            let viejos = if previo.is_some() { simbolos_de_ruta(&tx, rel)? } else { IndexMap::new() };
            let an = an.as_ref().expect("analizado");
            escribir_analisis(&tx, rel, sh, mt, tam, version, an)?;
            tocados.push(rel.to_string());
            if inicial {
                continue;
            }
            match previo {
                None => {
                    nuevos.push(rel.to_string());
                    let actuales = simbolos_de_ruta(&tx, rel)?;
                    anotar_cambio(&tx, version, rel, "nuevo", "", texto, &IndexMap::new(), &actuales)?;
                }
                Some(previo) => {
                    modificados.push(rel.to_string());
                    let actuales = simbolos_de_ruta(&tx, rel)?;
                    anotar_cambio(&tx, version, rel, "modificado", &previo, texto, &viejos, &actuales)?;
                    for n in viejos.keys().chain(actuales.keys()) {
                        if viejos.get(n) != actuales.get(n) {
                            simbolos_cambiados.insert(n.clone());
                        }
                    }
                }
            }
        }
        for rel in &borrados {
            let viejos = simbolos_de_ruta(&tx, rel)?;
            simbolos_cambiados.extend(viejos.keys().cloned());
            borrar_archivo(&tx, rel, false)?;
            tocados.push(rel.clone());
            anotar_cambio(&tx, version, rel, "borrado", "", "", &viejos, &IndexMap::new())?;
        }
        let hubo = !tocados.is_empty();
        if hubo {
            Banco::guardar_meta_en(&tx, "version", &version.to_string())?;
            Banco::guardar_meta_en(&tx, "actualizado", &ahora())?;
            if !inicial {
                let rutas: HashSet<String> = modificados.iter().chain(borrados.iter()).cloned().collect();
                marcar_revisar(&tx, &rutas, version, &simbolos_cambiados)?;
            }
            tx.execute("DELETE FROM cambios WHERE id <= (SELECT MAX(id) FROM cambios) - ?", params![MAX_CAMBIOS_GUARDADOS]).map_err(error)?;
        }
        if inicial && hubo {
            Banco::guardar_meta_en(&tx, "version_vista", &version.to_string())?;
        }
        tx.commit().map_err(error)?;
        if hubo {
            self.resolver_importaciones()?;
            self.resolver_llamadas()?;
            self.invalidar_vectores();
        }
        let rutas: Vec<String> = nuevos.iter().chain(modificados.iter()).chain(borrados.iter()).take(50).cloned().collect();
        Ok(Sincronizacion {
            inicial,
            nuevos: if inicial { tocados.len() } else { nuevos.len() },
            modificados: modificados.len(),
            borrados: borrados.len(),
            rutas,
            version: self.version()?,
            archivos: listado.len(),
            segundos: round(t0.elapsed().as_secs_f64(), 3),
        })
    }

    /// Para comparar con Python: el análisis de un archivo tal como lo escribiría el banco.
    pub fn analisis_de(rel: &str, texto: &str) -> Analisis {
        analizar(rel, texto)
    }
}

/// Las columnas de un símbolo cambiado: para avisos en las notas.
pub fn hay_cambios(viejos: &HashMap<String, String>, nuevos: &HashMap<String, String>) -> bool {
    viejos != nuevos
}
