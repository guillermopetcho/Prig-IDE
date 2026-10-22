//! Kaggle por la red (`kaggle_lector.py` y `kaggle_explorar.py`, sin el modelo): buscar notebooks, datasets y
//! competiciones, sus fichas (con caché en memoria, como Python), abrir un notebook (guardado una semana en disco),
//! importarlo al proyecto con las rutas de datos cambiadas, qué datos usa y su contexto, y descargar datos al proyecto.

use crate::kaggle::{self, pedir, ErrorKaggle, Fallo};
use crate::kaggle_datos::{self, CARPETA_DATOS};
use prig_plataforma::py;
use prig_plataforma::valor::{redondear, Mapa, Valor};
use regex::Regex;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

fn error<T>(t: &str) -> Result<T, Fallo> {
    Err(Fallo::Usuario(ErrorKaggle(t.into())))
}

// ---------------------------------------------------------------------------------------------- caché

static CACHE: LazyLock<Mutex<HashMap<String, (Instant, Valor)>>> = LazyLock::new(|| Mutex::new(HashMap::new()));

/// `_cacheado(clave, segundos, fn)`
fn cacheado(clave: &str, segundos: u64, f: impl FnOnce() -> Result<Valor, Fallo>) -> Result<Valor, Fallo> {
    if let Some((t, v)) = CACHE.lock().unwrap().get(clave) {
        if t.elapsed() < Duration::from_secs(segundos) {
            return Ok(v.clone());
        }
    }
    let v = f()?;
    CACHE.lock().unwrap().insert(clave.to_string(), (Instant::now(), v.clone()));
    Ok(v)
}

/// La clave de caché de Python: `json.dumps(params, sort_keys=True)`
fn clave(prefijo: &str, params: &[(&str, String)]) -> String {
    let mut p: Vec<&(&str, String)> = params.iter().collect();
    p.sort_by_key(|x| x.0);
    format!("{prefijo}{}", p.iter().map(|(k, v)| format!("{k}={v}")).collect::<Vec<_>>().join("&"))
}

// ---------------------------------------------------------------------------------------------- utilidades de Python

fn get(v: &Valor, k: &str) -> Result<Valor, Fallo> {
    match v {
        Valor::Mapa(m) => Ok(m.get(k).cloned().unwrap_or(Valor::Nulo)),
        _ => Err(Fallo::Interno),
    }
}

/// `x or y`
fn o(v: Valor, y: Valor) -> Valor {
    if v.verdad() { v } else { y }
}

/// `x or []` como lista (Err si no lo es)
fn lista(v: Valor) -> Result<Vec<Valor>, Fallo> {
    match v {
        Valor::Lista(l) => Ok(l),
        v if !v.verdad() => Ok(Vec::new()),
        _ => Err(Fallo::Interno),
    }
}

/// `str(x)` de Python dentro de un f-string
fn s(v: &Valor) -> String {
    v.texto_py()
}

/// `str.splitlines(keepends=True)`
pub fn splitlines(t: &str) -> Vec<String> {
    let mut v = Vec::new();
    let mut actual = String::new();
    let mut it = t.chars().peekable();
    while let Some(c) = it.next() {
        actual.push(c);
        let corta = matches!(c, '\n' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}');
        if c == '\r' {
            if it.peek() == Some(&'\n') {
                actual.push('\n');
                it.next();
            }
            v.push(std::mem::take(&mut actual));
        } else if corta {
            v.push(std::mem::take(&mut actual));
        }
    }
    if !actual.is_empty() {
        v.push(actual);
    }
    v
}

// ---------------------------------------------------------------------------------------------- referencias

static ENLACE_NOTEBOOK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"kaggle\.com/(?:code/|kernels/)?([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-.]+)").unwrap());
static COLA_NOTEBOOK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"/(?:notebook|edit|log|comments|input|output|data)$").unwrap());
static ENLACE_DATASET: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"kaggle\.com/datasets/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-.]+)").unwrap());
static COLA_DATASET: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"/(?:data|code|discussion|versions/\d+|suggestions)$").unwrap());

/// `ref_desde`: «usuario/slug» de un notebook
pub fn ref_desde(texto: &str) -> Result<String, Fallo> {
    let t = py::strip(texto);
    let r = match ENLACE_NOTEBOOK.captures(t) {
        Some(c) => format!("{}/{}", &c[1], &c[2]),
        None => t.trim_matches('/').to_string(),
    };
    let r = COLA_NOTEBOOK.replace(&r, "").into_owned();
    if !kaggle::REF_VALIDA.is_match(&r) || r.contains("..") {
        return error("Eso no es un notebook de Kaggle: pega un enlace como kaggle.com/code/usuario/nombre.");
    }
    Ok(r)
}

/// `ref_dataset`
pub fn ref_dataset(texto: &str) -> Result<String, Fallo> {
    let t = py::strip(texto);
    let r = match ENLACE_DATASET.captures(t) {
        Some(c) => format!("{}/{}", &c[1], &c[2]),
        None => t.trim_matches('/').to_string(),
    };
    let r = COLA_DATASET.replace(&r, "").into_owned();
    if !kaggle::REF_VALIDA.is_match(&r) || r.contains("..") {
        return error("Eso no es un dataset de Kaggle: pega un enlace como kaggle.com/datasets/usuario/nombre.");
    }
    Ok(r)
}

// ---------------------------------------------------------------------------------------------- notebooks

const ORDENES: [(&str, &str); 7] = [
    ("relevancia", "relevance"),
    ("votos", "voteCount"),
    ("populares", "hotness"),
    ("recientes", "dateRun"),
    ("comentados", "commentCount"),
    ("vistos", "viewCount"),
    ("nuevos", "dateCreated"),
];

/// Los filtros de `buscar` (los que Kaggle no sabe aplicar se aplican aquí)
#[derive(Default)]
pub struct Busqueda {
    pub consulta: String,
    pub orden: String,
    pub pagina: i64,
    pub competicion: String,
    pub dataset: String,
    pub usuario: String,
    pub tipo: String,
    pub votos_min: i64,
    pub dias: i64,
    pub gpu: Option<bool>,
    pub padre: String,
}

/// `_fecha(texto)`: marca de tiempo de una fecha ISO (0 si no se lee)
fn marca(v: &Valor) -> f64 {
    static ISO: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?(Z|[+-]\d{2}:\d{2})?$").unwrap());
    let t = s(v);
    let Some(c) = ISO.captures(&t) else { return 0.0 };
    let n = |i: usize| c.get(i).map(|m| m.as_str().parse::<i64>().unwrap_or(0)).unwrap_or(0);
    // SAFETY: mktime/timegm con una estructura propia
    unsafe {
        let mut tm: libc::tm = std::mem::zeroed();
        tm.tm_year = (n(1) - 1900) as i32;
        tm.tm_mon = (n(2) - 1) as i32;
        tm.tm_mday = n(3) as i32;
        tm.tm_hour = n(4) as i32;
        tm.tm_min = n(5) as i32;
        tm.tm_sec = n(6) as i32;
        tm.tm_isdst = -1;
        match c.get(8).map(|m| m.as_str()) {
            None => libc::mktime(&mut tm) as f64,
            Some(z) => {
                let base = libc::timegm(&mut tm) as f64;
                if z == "Z" {
                    base
                } else {
                    let signo = if z.starts_with('-') { -1.0 } else { 1.0 };
                    let h: f64 = z[1..3].parse().unwrap_or(0.0);
                    let m: f64 = z[4..6].parse().unwrap_or(0.0);
                    base - signo * (h * 3600.0 + m * 60.0)
                }
            }
        }
    }
}

/// `_normalizar(k)`
fn normalizar(k: &Valor) -> Result<Mapa, Fallo> {
    let mut datos = lista(get(k, "competitionDataSources")?)?;
    datos.extend(lista(get(k, "datasetDataSources")?)?);
    Ok(Mapa::new()
        .con("ref", get(k, "ref")?)
        .con("titulo", get(k, "title")?)
        .con("autor", get(k, "author")?)
        .con("votos", get(k, "totalVotes")?)
        .con("ejecutado", get(k, "lastRunTime")?)
        .con("lenguaje", get(k, "language")?)
        .con("tipo", get(k, "kernelType")?)
        .con("gpu", get(k, "enableGpu")?.verdad())
        .con("datos", Valor::Lista(datos))
        .con("url", format!("https://www.kaggle.com/code/{}", s(&get(k, "ref")?))))
}

/// `buscar(...)`: notebooks de la comunidad
pub fn buscar(b: &Busqueda) -> Result<Mapa, Fallo> {
    let locales = matches!(b.tipo.as_str(), "notebook" | "script") || b.votos_min != 0 || b.dias != 0 || b.gpu.is_some();
    let pagina = b.pagina.max(1);
    let por_pagina = if locales { 50 } else { 20 };
    let mut orden = ORDENES.iter().find(|o| o.0 == b.orden).map(|o| o.1).unwrap_or("hotness").to_string();
    let mut params: Vec<(&str, String)> = vec![("page", pagina.to_string()), ("pageSize", por_pagina.to_string())];
    let consulta = py::strip(&b.consulta);
    let mut extra: Vec<(&str, String)> = Vec::new();
    if !consulta.is_empty() {
        extra.push(("search", consulta.chars().take(100).collect()));
    } else if orden == "relevance" {
        orden = "hotness".into();
    }
    params.push(("sortBy", orden));
    params.extend(extra);
    for (k, v) in [("competition", &b.competicion), ("dataset", &b.dataset), ("user", &b.usuario)] {
        let v = py::strip(v);
        if !v.is_empty() {
            params.push((k, v.to_string()));
        }
    }
    if !py::strip(&b.padre).is_empty() {
        params.push(("parentKernel", ref_desde(&b.padre)?));
    }
    let lista_k = cacheado(&clave("kl:", &params), 600, || {
        let datos = pedir("kernels/list", &params, None, true)?;
        Ok(match datos {
            Valor::Lista(l) => Valor::Lista(l),
            Valor::Mapa(m) => Valor::Lista(lista(o(m.get("kernels").cloned().unwrap_or(Valor::Nulo), Valor::Nulo))?),
            _ => return Err(Fallo::Interno),
        })
    })?;
    let Valor::Lista(lista_k) = lista_k else { return Err(Fallo::Interno) };
    let mut notebooks = Vec::new();
    for k in &lista_k {
        let lenguaje = o(get(k, "language")?, Valor::Texto("python".into()));
        if get(k, "ref")?.verdad() && s(&lenguaje).to_lowercase() == "python" {
            notebooks.push(normalizar(k)?);
        }
    }
    let antes = notebooks.len();
    if matches!(b.tipo.as_str(), "notebook" | "script") {
        notebooks.retain(|n| s(&o(n.valor("tipo").clone(), Valor::Texto("notebook".into()))) == b.tipo);
    }
    if b.votos_min != 0 {
        notebooks.retain(|n| o(n.valor("votos").clone(), Valor::Entero(0)).num().unwrap_or(0.0) >= b.votos_min as f64);
    }
    if b.dias != 0 {
        let limite = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0) - b.dias as f64 * 86400.0;
        notebooks.retain(|n| marca(n.valor("ejecutado")) >= limite);
    }
    if let Some(g) = b.gpu {
        notebooks.retain(|n| n.verdad("gpu") == g);
    }
    let ocultos = antes - notebooks.len();
    Ok(Mapa::new()
        .con("notebooks", Valor::Lista(notebooks.into_iter().map(Valor::Mapa).collect()))
        .con("pagina", pagina as i128)
        .con("hay_mas", lista_k.len() >= por_pagina)
        .con("ocultos", ocultos as i128))
}

/// `_texto_de(fuente)`
fn texto_de(f: &Valor) -> Result<String, Fallo> {
    match f {
        Valor::Lista(l) => l.iter().map(|x| if let Valor::Texto(t) = x { Ok(t.clone()) } else { Err(Fallo::Interno) }).collect(),
        v if !v.verdad() => Ok(String::new()),
        v => Ok(s(v)),
    }
}

/// `_salidas_texto(celda)`
fn salidas_texto(celda: &Valor) -> Result<String, Fallo> {
    let mut partes = Vec::new();
    for x in lista(get(celda, "outputs")?)? {
        let tipo = get(&x, "output_type")?;
        let data = get(&x, "data")?;
        if tipo == Valor::Texto("stream".into()) {
            partes.push(texto_de(&get(&x, "text")?)?);
        } else if matches!(&x, Valor::Mapa(m) if m.contiene("data")) && matches!(&o(data.clone(), Valor::Mapa(Mapa::new())), Valor::Mapa(d) if d.contiene("text/plain")) {
            partes.push(texto_de(&get(&data, "text/plain")?)?);
        } else if tipo == Valor::Texto("error".into()) {
            partes.push(format!("{}: {}", s(&get(&x, "ename")?), s(&get(&x, "evalue")?)));
        }
    }
    let t = partes.into_iter().filter(|p| !py::strip(p).is_empty()).collect::<Vec<_>>().join("\n");
    Ok(t.chars().take(3000).collect())
}

fn ruta_notebook(r: &str) -> PathBuf {
    kaggle::carpeta().join("notebooks").join(format!("{}.json", r.replace('/', "__")))
}

fn ahora_s() -> String {
    py::ahora_iso().chars().take(19).collect()
}

/// `abrir(texto, refrescar)`: el notebook con sus celdas (guardado una semana en disco)
pub fn abrir(texto: &str, refrescar: bool) -> Result<Mapa, Fallo> {
    let r = ref_desde(texto)?;
    let ruta = ruta_notebook(&r);
    if !refrescar {
        if let Ok(m) = std::fs::metadata(&ruta) {
            if m.modified().ok().and_then(|t| t.elapsed().ok()).is_some_and(|e| e.as_secs_f64() < 7.0 * 86400.0) {
                if let Some(g) = kaggle::leer_objeto(&ruta).filter(|g| !g.is_empty()) {
                    return Ok(g);
                }
            }
        }
    }
    let (usuario, slug) = r.split_once('/').unwrap_or((&r, ""));
    let datos = pedir("kernels/pull", &[("userName", usuario.to_string()), ("kernelSlug", slug.to_string())], None, false)?;
    let meta = o(get(&datos, "metadata")?, Valor::Mapa(Mapa::new()));
    let blob = o(get(&datos, "blob")?, Valor::Mapa(Mapa::new()));
    let fuente = o(get(&blob, "source")?, Valor::Texto(String::new()));
    let script = Valor::Texto("script".into());
    let (celdas, ipynb) = if get(&meta, "kernelType")? == script || get(&blob, "kernelType")? == script {
        (vec![Mapa::new().con("tipo", "code").con("fuente", fuente).con("salida", "")], Valor::Nulo)
    } else {
        let Ok(ipynb) = prig_plataforma::json::leer(&s(&fuente)) else { return error("El notebook descargado no se pudo leer.") };
        let mut celdas = Vec::new();
        for c in lista(get(&ipynb, "cells")?)? {
            let tipo = match get(&c, "cell_type")? {
                Valor::Nulo => Valor::Texto("code".into()),
                v => v,
            };
            if matches!(&get(&c, "cell_type")?, Valor::Texto(t) if t == "code" || t == "markdown") {
                celdas.push(Mapa::new().con("tipo", tipo).con("fuente", texto_de(&get(&c, "source")?)?).con("salida", salidas_texto(&c)?));
            }
        }
        (celdas, ipynb)
    };
    let celdas: Vec<Valor> = celdas.into_iter().enumerate().map(|(i, c)| Valor::Mapa(c.con("indice", i as i128))).collect();
    let ref_meta = o(get(&meta, "ref")?, Valor::Texto(r.clone()));
    let nb = Mapa::new()
        .con("ref", ref_meta.clone())
        .con("titulo", o(get(&meta, "title")?, Valor::Texto(slug.into())))
        .con("autor", get(&meta, "author")?)
        .con("votos", get(&meta, "totalVotes")?)
        .con("version", get(&meta, "currentVersionNumber")?)
        .con("lenguaje", get(&meta, "language")?)
        .con("tipo", get(&meta, "kernelType")?)
        .con("ejecutado", get(&meta, "lastRunTime")?)
        .con("gpu", get(&meta, "enableGpu")?)
        .con("competiciones", o(get(&meta, "competitionDataSources")?, Valor::Lista(vec![])))
        .con("datasets", o(get(&meta, "datasetDataSources")?, Valor::Lista(vec![])))
        .con("notebooks_fuente", o(get(&meta, "kernelDataSources")?, Valor::Lista(vec![])))
        .con("url", format!("https://www.kaggle.com/code/{}", s(&ref_meta)))
        .con("celdas", Valor::Lista(celdas))
        .con("ipynb", ipynb)
        .con("descargado", ahora_s())
        .con("licencia", "Los notebooks públicos de Kaggle se publican por defecto con licencia Apache 2.0 salvo que el autor indique otra.");
    if let Some(p) = ruta.parent() {
        std::fs::create_dir_all(p).map_err(|_| Fallo::Interno)?;
    }
    let tmp = PathBuf::from(format!("{}.tmp", ruta.display()));
    std::fs::write(&tmp, prig_plataforma::json::escribir_linea(&Valor::Mapa(nb.clone()))).map_err(|_| Fallo::Interno)?;
    std::fs::rename(&tmp, &ruta).map_err(|_| Fallo::Interno)?;
    Ok(nb)
}

/// `lectura(ref)`
fn lectura(r: &str) -> Valor {
    match kaggle::leer_objeto(&kaggle::carpeta().join("lecturas.json")).unwrap_or_default().get(r) {
        Some(v) if v.verdad() => v.clone(),
        _ => Valor::Mapa(Mapa::new().con("leidas", Valor::Lista(vec![])).con("total", 0)),
    }
}

/// `GET /api/kaggle/notebook`: la vista (sin el .ipynb), las explicaciones guardadas, los datos y su contexto
pub fn notebook(r: &str, refrescar: bool, espacio: &Path) -> Result<Mapa, Fallo> {
    let nb = abrir(r, refrescar)?;
    let mut v = Mapa::new();
    for (k, x) in nb.iter() {
        if k != "ipynb" {
            v.poner(k.clone(), x.clone());
        }
    }
    let r = s(nb.valor("ref"));
    v.poner("lectura", lectura(&r));
    let expl = kaggle::leer_objeto(&kaggle::carpeta().join("explicaciones").join(format!("{}.json", r.replace('/', "__")))).unwrap_or_default();
    v.poner("explicaciones", expl);
    v.poner("datos", Valor::Lista(datos_del_notebook(&nb, espacio)?.into_iter().map(Valor::Mapa).collect()));
    let resumen = contexto_datos(&nb, espacio, 5).unwrap_or_else(|_| Mapa::new().con("fuentes", Valor::Lista(vec![])).con("contexto_texto", ""));
    v.poner("resumen_datos", resumen);
    Ok(v)
}

// ---------------------------------------------------------------------------------------------- datos de un notebook

static RUTA_RELATIVA: LazyLock<fancy_regex::Regex> = LazyLock::new(|| fancy_regex::Regex::new(r"(?<![\w/])\.\./input/").unwrap());
static FUENTE_EN_CODIGO: LazyLock<fancy_regex::Regex> = LazyLock::new(|| {
    fancy_regex::Regex::new(r#"(?:/kaggle/input/|(?<![\w/])\.\./input/)([A-Za-z0-9_\-.]+(?:/[A-Za-z0-9_\-.]+)?)(?:/|['"]|\s|$)"#).unwrap()
});

/// `reescribir_rutas`: /kaggle/input/… y ../input/… → <proyecto>/kaggle_datos/…
pub fn reescribir_rutas(fuente: &str, espacio: &Path) -> String {
    let local = format!("{}/", espacio.join(CARPETA_DATOS).to_string_lossy().replace('\\', "/"));
    let f = fuente.replace("/kaggle/input/", &local);
    RUTA_RELATIVA.replace_all(&f, fancy_regex::NoExpand(&local)).into_owned()
}

const EXTS_DATOS: [&str; 13] = [".csv", ".tsv", ".txt", ".json", ".parquet", ".zip", ".h5", ".feather", ".pt", ".pkl", ".npy", ".tab", ".data"];

/// `detectar_fuentes_en_codigo`: /kaggle/input/<slug> o ../input/<slug> en las celdas de código
fn fuentes_en_codigo(nb: &Mapa) -> Result<Vec<(String, String)>, Fallo> {
    let mut encontrados = std::collections::BTreeSet::new();
    let termina = |t: &str| EXTS_DATOS.iter().any(|e| t.to_lowercase().ends_with(e));
    for c in lista(nb.get("celdas").cloned().unwrap_or(Valor::Nulo))? {
        if get(&c, "tipo")? != Valor::Texto("code".into()) {
            continue;
        }
        let fuente = s(&o(get(&c, "fuente")?, Valor::Texto(String::new())));
        for m in FUENTE_EN_CODIGO.captures_iter(&fuente).flatten() {
            let raw = py::strip(m.get(1).map(|x| x.as_str()).unwrap_or("")).trim_matches('/').trim_matches('\\').to_string();
            if raw.is_empty() || raw == "." || raw == ".." {
                continue;
            }
            let slug = match raw.split_once('/') {
                Some((prim, seg)) if termina(seg) => prim.to_string(),
                _ => raw.clone(),
            };
            if !slug.is_empty() && !termina(&slug) {
                encontrados.insert(slug);
            }
        }
    }
    let mut ya = std::collections::HashSet::new();
    for c in lista(nb.get("competiciones").cloned().unwrap_or(Valor::Nulo))? {
        ya.insert(s(&o(c, Valor::Texto(String::new()))).to_lowercase());
    }
    for d in lista(nb.get("datasets").cloned().unwrap_or(Valor::Nulo))? {
        let d = s(&o(d, Valor::Texto(String::new())));
        ya.insert(d.to_lowercase());
        ya.insert(d.rsplit('/').next().unwrap_or("").to_lowercase());
    }
    Ok(encontrados
        .into_iter()
        .filter(|sl| !ya.contains(&sl.to_lowercase()))
        .map(|sl| (if sl.contains('/') { "dataset" } else { "competicion" }.to_string(), sl))
        .collect())
}

/// Las fuentes de un notebook: las declaradas y las que aparecen en el código, sin repetir
fn fuentes(nb: &Mapa) -> Result<Vec<(String, String)>, Fallo> {
    let mut base: Vec<(String, String)> = Vec::new();
    for c in lista(nb.get("competiciones").cloned().unwrap_or(Valor::Nulo))? {
        base.push(("competicion".into(), s(&c)));
    }
    for d in lista(nb.get("datasets").cloned().unwrap_or(Valor::Nulo))? {
        base.push(("dataset".into(), s(&d)));
    }
    base.extend(fuentes_en_codigo(nb)?);
    let mut vistos = std::collections::HashSet::new();
    Ok(base.into_iter().filter(|(t, r)| vistos.insert((t.clone(), r.to_lowercase()))).collect())
}

/// `datos_del_notebook`: cada fuente de datos y si ya está en el proyecto
pub fn datos_del_notebook(nb: &Mapa, espacio: &Path) -> Result<Vec<Mapa>, Fallo> {
    fuentes(nb)?
        .into_iter()
        .map(|(t, r)| Ok(Mapa::new().con("tipo", t).con("ref", r.clone()).con("descargado", kaggle_datos::local(&r, espacio)?.is_some())))
        .collect()
}

/// `str(x)` de un número de las estadísticas (int o float de Python)
fn numero_py(v: &Valor) -> String {
    s(v)
}

/// `obtener_contexto_datasets_notebook`: tablas, columnas y estadísticas de cada fuente (lo descargado o, si no, los
/// metadatos de Kaggle), para la interfaz y para el modelo
pub fn contexto_datos(nb: &Mapa, espacio: &Path, max_filas: usize) -> Result<Mapa, Fallo> {
    let mut resumen = Vec::new();
    let mut bloques = Vec::new();
    for (tipo, r) in fuentes(nb)? {
        let slug = kaggle_datos::nombre_local(&r);
        let info = kaggle_datos::local(&r, espacio)?;
        let descargado = info.is_some();
        let mut fuente = Mapa::new().con("tipo", tipo.clone()).con("ref", r.clone()).con("slug", slug).con("descargado", descargado).con("tablas", Valor::Lista(vec![]));
        let mut tablas: Vec<Mapa> = Vec::new();
        if let Some(info) = &info {
            fuente.poner("carpeta", info.valor("carpeta").clone());
            let archivos: Vec<Mapa> = info
                .lista("archivos")
                .unwrap_or(&[])
                .iter()
                .filter_map(|a| if let Valor::Mapa(a) = a { Some(a.clone()) } else { None })
                .filter(|a| {
                    let rel = a.texto("relativa").unwrap_or("").to_lowercase();
                    [".csv", ".tsv", ".parquet", ".json", ".txt"].iter().any(|e| rel.ends_with(e))
                })
                .take(6)
                .collect();
            for a in archivos {
                if let Ok(mut prev) = kaggle_datos::vista_previa(a.texto("ruta").unwrap_or(""), espacio, max_filas) {
                    prev.poner("relativa", a.valor("relativa").clone());
                    tablas.push(prev);
                }
            }
        }
        if tablas.is_empty() {
            let ficha = if tipo == "dataset" { dataset(&r, Some(espacio)) } else { competicion(&r, Some(espacio)) };
            if let Ok(ficha) = ficha {
                for a in ficha.lista("archivos").unwrap_or(&[]).iter().take(6) {
                    let Valor::Mapa(a) = a else { continue };
                    let nombre = a.get("nombre").cloned().unwrap_or(Valor::Nulo);
                    let n = s(&o(nombre.clone(), Valor::Texto(String::new())));
                    let ext = if n.contains('.') { n.rsplit('.').next().unwrap_or("").to_lowercase() } else { String::new() };
                    tablas.push(
                        Mapa::new()
                            .con("nombre", nombre)
                            .con("bytes", a.get("bytes").cloned().unwrap_or(Valor::Nulo))
                            .con("tipo", ext)
                            .con("columnas", o(a.get("columnas").cloned().unwrap_or(Valor::Nulo), Valor::Lista(vec![])))
                            .con("primeras", Valor::Lista(vec![]))
                            .con("total_filas", Valor::Nulo)
                            .con("metadatos_solo", true),
                    );
                }
            }
        }
        // el texto para el modelo
        let mut lineas = vec![format!(
            "### FUENTE DE DATOS: [{}] «{r}» ({})",
            tipo.to_uppercase(),
            if descargado { "Descargado localmente" } else { "Metadatos de Kaggle" }
        )];
        if tablas.is_empty() {
            lineas.push("- Archivos en Kaggle (descarga al proyecto para ver muestras exactas).".into());
        }
        for tab in &tablas {
            let nombre = s(&o(tab.get("nombre").cloned().unwrap_or(Valor::Nulo), Valor::Texto("tabla".into())));
            let filas = match tab.get("total_filas") {
                Some(v) if !v.es_nulo() => format!("{} filas, ", s(v)),
                _ => String::new(),
            };
            let cols = lista(o(tab.get("columnas").cloned().unwrap_or(Valor::Nulo), Valor::Nulo))?;
            lineas.push(format!("- Archivo `{nombre}` ({filas}{} columnas):", cols.len()));
            for c in cols.iter().take(35) {
                let nombre_col = s(&o(get(c, "nombre")?, Valor::Texto(String::new())));
                let tipo_col = s(&o(get(c, "tipo")?, Valor::Texto("desconocido".into())));
                let mut detalles = Vec::new();
                let pct = get(c, "faltan_pct")?;
                if !pct.es_nulo() && pct.num().unwrap_or(0.0) > 0.0 {
                    detalles.push(format!("{}% nulos", numero_py(&pct)));
                }
                let distintos = get(c, "distintos")?;
                if !distintos.es_nulo() {
                    detalles.push(format!("{} valores distintos", s(&distintos)));
                }
                let media = get(c, "media")?;
                let frecuentes = get(c, "frecuentes")?;
                if !media.es_nulo() {
                    detalles.push(format!("media {}", numero_py(&media)));
                } else if frecuentes.verdad() {
                    let vals: Vec<String> = lista(frecuentes)?
                        .iter()
                        .take(3)
                        .filter_map(|f| get(f, "valor").ok().filter(|v| !v.es_nulo()).map(|v| s(&v)))
                        .collect();
                    if !vals.is_empty() {
                        detalles.push(format!("frecuentes: {}", vals.join(", ")));
                    }
                }
                let det = if detalles.is_empty() { String::new() } else { format!(" ({})", detalles.join(", ")) };
                lineas.push(format!("    · `{nombre_col}` [{tipo_col}]{det}"));
            }
            // «primeras»: la vista previa las llama «filas», así que solo salen en los metadatos (vacías); se conserva
            let primeras = lista(o(tab.get("primeras").cloned().unwrap_or(Valor::Nulo), Valor::Nulo))?;
            if !primeras.is_empty() {
                lineas.push("    Muestras de filas:".into());
                for f in primeras.iter().take(3) {
                    let vals: Vec<String> = lista(f.clone())?.iter().take(10).map(s).collect();
                    lineas.push(format!("      {}", vals.join(", ")));
                }
            }
        }
        fuente.poner("tablas", Valor::Lista(tablas.into_iter().map(Valor::Mapa).collect()));
        resumen.push(fuente);
        bloques.push(lineas.join("\n"));
    }
    let todos = !resumen.is_empty() && resumen.iter().all(|f| f.verdad("descargado"));
    Ok(Mapa::new()
        .con("total_fuentes_tmp", Valor::Nulo)
        .con("fuentes", Valor::Lista(resumen.iter().cloned().map(Valor::Mapa).collect()))
        .con("contexto_texto", bloques.join("\n\n"))
        .con("descargados_todos", todos)
        .con("total_fuentes", resumen.len() as i128))
    .map(|mut m| {
        m.quitar("total_fuentes_tmp");
        m
    })
}

/// `guardar_en_workspace`: el notebook en kaggle_notebooks/ del proyecto, con las rutas de datos del proyecto
pub fn importar(texto: &str, espacio: &Path) -> Result<Mapa, Fallo> {
    let nb = abrir(texto, false)?;
    let dir = espacio.join("kaggle_notebooks");
    std::fs::create_dir_all(&dir).map_err(|_| Fallo::Interno)?;
    let r = s(nb.valor("ref"));
    let ipynb = nb.get("ipynb").cloned().unwrap_or(Valor::Nulo);
    let nombre = format!("{}{}", r.split('/').nth(1).ok_or(Fallo::Interno)?, if ipynb.es_nulo() { ".py" } else { ".ipynb" });
    let destino = dir.join(&nombre);
    let mut cambiadas = 0i128;
    let contenido = if !ipynb.es_nulo() {
        let mut doc = ipynb.clone();
        if let Valor::Mapa(m) = &mut doc {
            if let Some(Valor::Lista(celdas)) = m.get_mut("cells") {
                for c in celdas.iter_mut() {
                    let Valor::Mapa(c) = c else { return Err(Fallo::Interno) };
                    if c.get("cell_type") != Some(&Valor::Texto("code".into())) {
                        continue;
                    }
                    let antes = texto_de(c.get("source").unwrap_or(&Valor::Nulo))?;
                    let despues = reescribir_rutas(&antes, espacio);
                    if despues != antes {
                        cambiadas += 1;
                        c.poner("source", Valor::Lista(splitlines(&despues).into_iter().map(Valor::Texto).collect()));
                    }
                }
            }
        }
        prig_plataforma::json::escribir(&doc, 1)
    } else {
        let antes = match nb.lista("celdas").and_then(|l| l.first()) {
            Some(Valor::Mapa(c)) => s(c.valor("fuente")),
            _ => return Err(Fallo::Interno),
        };
        let despues = reescribir_rutas(&antes, espacio);
        cambiadas = (despues != antes) as i128;
        despues
    };
    std::fs::write(&destino, contenido).map_err(|_| Fallo::Interno)?;
    let datos = datos_del_notebook(&nb, espacio)?;
    let faltan: Vec<String> = datos.iter().filter(|d| !d.verdad("descargado")).map(|d| s(d.valor("ref"))).collect();
    Ok(Mapa::new()
        .con("ruta", destino.to_string_lossy().into_owned())
        .con("relativa", py::relpath(&destino.to_string_lossy(), &espacio.to_string_lossy()))
        .con("titulo", nb.valor("titulo").clone())
        .con("datos", Valor::Lista(datos.into_iter().map(Valor::Mapa).collect()))
        .con("celdas_con_rutas", cambiadas)
        .con(
            "aviso",
            if faltan.is_empty() {
                Valor::Nulo
            } else {
                Valor::Texto(format!("Para ejecutarlo faltan sus datos: {}. Bájalos con «Descargar al proyecto».", faltan.join(", ")))
            },
        ))
}

// ---------------------------------------------------------------------------------------------- datasets y competiciones

const ORDEN_DATASETS: [(&str, &str); 5] = [("populares", "hottest"), ("votos", "votes"), ("recientes", "updated"), ("activos", "active"), ("nuevos", "published")];
const TIPOS_ARCHIVO: [&str; 5] = ["csv", "json", "sqlite", "bigQuery", "parquet"];
const LICENCIAS: [&str; 4] = ["cc", "gpl", "odb", "other"];
const TAMANOS: [(&str, Option<i64>, Option<i64>); 4] =
    [("pequeno", None, Some(1 << 20)), ("mediano", Some(1 << 20), Some(100 << 20)), ("grande", Some(100 << 20), Some(1 << 30)), ("enorme", Some(1 << 30), None)];
const GRUPOS: [(&str, &str); 2] = [("general", "general"), ("mias", "entered")];
const CATEGORIAS: [&str; 5] = ["featured", "gettingStarted", "playground", "research", "community"];
const ORDEN_COMPETICIONES: [(&str, &str); 5] =
    [("agrupadas", "grouped"), ("premio", "prize"), ("cierre", "earliestDeadline"), ("equipos", "numberOfTeams"), ("nuevas", "recentlyCreated")];

fn etiquetas(d: &Valor) -> Result<Valor, Fallo> {
    let mut v = Vec::new();
    for t in lista(get(d, "tags")?)? {
        let n = get(&t, "name")?;
        if n.verdad() {
            v.push(n);
        }
    }
    v.truncate(12);
    Ok(Valor::Lista(v))
}

/// `_dataset_corto`
fn dataset_corto(d: &Valor) -> Result<Mapa, Fallo> {
    let usab = o(get(d, "usabilityRating")?, Valor::Entero(0));
    let usab = match &usab {
        Valor::Texto(t) => prig_plataforma::valor::real_de_texto(t).ok_or(Fallo::Interno)?,
        v => v.num().ok_or(Fallo::Interno)?,
    };
    Ok(Mapa::new()
        .con("ref", get(d, "ref")?)
        .con("titulo", get(d, "title")?)
        .con("subtitulo", o(get(d, "subtitle")?, Valor::Texto(String::new())))
        .con("autor", o(get(d, "ownerName")?, get(d, "creatorName")?))
        .con("imagen", get(d, "thumbnailImageUrl")?)
        .con("votos", get(d, "voteCount")?)
        .con("descargas", get(d, "downloadCount")?)
        .con("vistas", get(d, "viewCount")?)
        .con("bytes", get(d, "totalBytes")?)
        .con("usabilidad", Valor::Real(redondear(usab * 10.0, 1)))
        .con("actualizado", get(d, "lastUpdated")?)
        .con("licencia", get(d, "licenseName")?)
        .con("notebooks", get(d, "kernelCount")?)
        .con("etiquetas", etiquetas(d)?)
        .con("url", o(get(d, "url")?, Valor::Texto(format!("https://www.kaggle.com/datasets/{}", s(&get(d, "ref")?))))))
}

/// `buscar_datasets(...)`
pub fn buscar_datasets(consulta: &str, orden: &str, pagina: i64, tipo_archivo: &str, licencia: &str, tamano: &str, usuario: &str) -> Result<Mapa, Fallo> {
    let pagina = pagina.max(1);
    let mut params: Vec<(&str, String)> =
        vec![("page", pagina.to_string()), ("sortBy", ORDEN_DATASETS.iter().find(|o| o.0 == orden).map(|o| o.1).unwrap_or("hottest").into())];
    let c = py::strip(consulta);
    if !c.is_empty() {
        params.push(("search", c.chars().take(100).collect()));
    }
    if TIPOS_ARCHIVO.contains(&tipo_archivo) {
        params.push(("filetype", tipo_archivo.into()));
    }
    if LICENCIAS.contains(&licencia) {
        params.push(("license", licencia.into()));
    }
    if let Some((_, min, max)) = TAMANOS.iter().find(|t| t.0 == tamano) {
        if let Some(m) = min {
            params.push(("minSize", m.to_string()));
        }
        if let Some(m) = max {
            params.push(("maxSize", m.to_string()));
        }
    }
    let u = py::strip(usuario);
    if !u.is_empty() {
        params.push(("user", u.chars().take(60).collect()));
    }
    let v = cacheado(&clave("dl:", &params), 600, || {
        let datos = pedir("datasets/list", &params, None, false)?;
        let l = if let Valor::Lista(l) = &datos { l.clone() } else { Vec::new() };
        let mut ds = Vec::new();
        for d in &l {
            if get(d, "ref")?.verdad() {
                ds.push(Valor::Mapa(dataset_corto(d)?));
            }
        }
        Ok(Valor::Mapa(Mapa::new().con("datasets", Valor::Lista(ds)).con("pagina", pagina as i128).con("hay_mas", l.len() >= 20)))
    })?;
    match v {
        Valor::Mapa(m) => Ok(m),
        _ => Err(Fallo::Interno),
    }
}

fn archivos_dataset(r: &str) -> Result<Vec<Valor>, Fallo> {
    let mut archivos = Vec::new();
    let mut token: Option<String> = None;
    for _ in 0..10 {
        let params: Vec<(&str, String)> = match &token {
            Some(t) => vec![("pageToken", t.clone())],
            None => vec![],
        };
        let d = pedir(&format!("datasets/list/{r}"), &params, None, false)?;
        for f in lista(get(&d, "datasetFiles")?)? {
            let mut cols = Vec::new();
            for c in lista(get(&f, "columns")?)? {
                cols.push(Valor::Mapa(
                    Mapa::new().con("nombre", get(&c, "name")?).con("tipo", get(&c, "type")?).con("descripcion", o(get(&c, "description")?, Valor::Texto(String::new()))),
                ));
            }
            cols.truncate(80);
            archivos.push(Valor::Mapa(
                Mapa::new()
                    .con("nombre", get(&f, "name")?)
                    .con("bytes", get(&f, "totalBytes")?)
                    .con("descripcion", o(get(&f, "description")?, Valor::Texto(String::new())))
                    .con("columnas", Valor::Lista(cols)),
            ));
        }
        token = Some(get(&d, "nextPageToken")?).filter(|t| t.verdad()).map(|t| s(&t));
        if token.is_none() {
            break;
        }
    }
    Ok(archivos)
}

/// `dataset(texto, workspace)`: la ficha (una hora en caché) y lo descargado
pub fn dataset(texto: &str, espacio: Option<&Path>) -> Result<Mapa, Fallo> {
    let r = ref_dataset(texto)?;
    let ficha = cacheado(&format!("dv:{r}"), 3600, || {
        let d = pedir(&format!("datasets/view/{r}"), &[], None, false)?;
        let mut f = dataset_corto(&d)?;
        f.poner("descripcion", o(get(&d, "description")?, Valor::Texto(String::new())));
        f.poner("version", get(&d, "currentVersionNumber")?);
        f.poner("archivos", Valor::Lista(archivos_dataset(&r)?));
        let mut versiones = Vec::new();
        for v in lista(get(&d, "versions")?)?.into_iter().take(10) {
            versiones.push(Valor::Mapa(Mapa::new().con("numero", get(&v, "versionNumber")?).con("fecha", get(&v, "creationDate")?).con("notas", get(&v, "versionNotes")?)));
        }
        f.poner("versiones", Valor::Lista(versiones));
        Ok(Valor::Mapa(f))
    })?;
    let Valor::Mapa(mut f) = ficha else { return Err(Fallo::Interno) };
    f.poner("tipo", "dataset");
    f.poner("local", match espacio {
        Some(e) => kaggle_datos::local(&r, e)?.map(Valor::Mapa).unwrap_or(Valor::Nulo),
        None => Valor::Nulo,
    });
    Ok(f)
}

/// `_competicion_corta`
fn competicion_corta(c: &Valor) -> Result<Mapa, Fallo> {
    let url = s(&o(o(get(c, "url")?, get(c, "ref")?), Valor::Texto(String::new())));
    let slug = url.trim_end_matches('/').rsplit('/').next().unwrap_or("").to_string();
    let fin = get(c, "deadline")?;
    let ahora_utc = {
        // SAFETY: gmtime_r con una estructura propia
        unsafe {
            let t = libc::time(std::ptr::null_mut());
            let mut tm: libc::tm = std::mem::zeroed();
            libc::gmtime_r(&t, &mut tm);
            format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec)
        }
    };
    let abierta = match &fin {
        v if !v.verdad() => false,
        Valor::Texto(t) => t.as_str() > ahora_utc.as_str(),
        _ => return Err(Fallo::Interno),
    };
    Ok(Mapa::new()
        .con("ref", slug.clone())
        .con("titulo", get(c, "title")?)
        .con("subtitulo", o(get(c, "description")?, Valor::Texto(String::new())))
        .con("organizador", o(get(c, "organizationName")?, get(c, "hostName")?))
        .con("imagen", get(c, "thumbnailImageUrl")?)
        .con("categoria", get(c, "category")?)
        .con("premio", get(c, "reward")?)
        .con("equipos", get(c, "teamCount")?)
        .con("cierre", fin)
        .con("abierta", abierta)
        .con("metrica", get(c, "evaluationMetric")?)
        .con("max_equipo", get(c, "maxTeamSize")?)
        .con("envios_diarios", get(c, "maxDailySubmissions")?)
        .con("inscrito", get(c, "userHasEntered")?.verdad())
        .con("solo_notebooks", get(c, "isKernelsSubmissionsOnly")?.verdad())
        .con("etiquetas", etiquetas(c)?)
        .con("url", if url.is_empty() { format!("https://www.kaggle.com/competitions/{slug}") } else { url }))
}

/// `buscar_competiciones(...)`
pub fn buscar_competiciones(consulta: &str, categoria: &str, orden: &str, pagina: i64, grupo: &str) -> Result<Mapa, Fallo> {
    let pagina = pagina.max(1);
    let mut params: Vec<(&str, String)> =
        vec![("page", pagina.to_string()), ("sortBy", ORDEN_COMPETICIONES.iter().find(|o| o.0 == orden).map(|o| o.1).unwrap_or("grouped").into())];
    if let Some((_, g)) = GRUPOS.iter().find(|g| g.0 == grupo && grupo != "general") {
        params.push(("group", g.to_string()));
    }
    let c = py::strip(consulta);
    if !c.is_empty() {
        params.push(("search", c.chars().take(100).collect()));
    }
    if CATEGORIAS.contains(&categoria) {
        params.push(("category", categoria.into()));
    }
    let v = cacheado(&clave("cl:", &params), 600, || {
        let datos = pedir("competitions/list", &params, None, true)?;
        let l = if let Valor::Lista(l) = &datos { l.clone() } else { Vec::new() };
        let cs: Vec<Valor> = l.iter().map(|c| competicion_corta(c).map(Valor::Mapa)).collect::<Result<_, _>>()?;
        Ok(Valor::Mapa(Mapa::new().con("competiciones", Valor::Lista(cs)).con("pagina", pagina as i128).con("hay_mas", l.len() >= 19)))
    })?;
    match v {
        Valor::Mapa(m) => Ok(m),
        _ => Err(Fallo::Interno),
    }
}

/// `competicion(texto, workspace)`: la ficha (no hay «view» de competiciones: se busca por su nombre)
pub fn competicion(texto: &str, espacio: Option<&Path>) -> Result<Mapa, Fallo> {
    let slug = kaggle::ref_competicion(texto)?;
    let ficha = cacheado(&format!("cv:{slug}"), 3600, || {
        let buscar = |q: String| -> Result<Option<Mapa>, Fallo> {
            for c in lista(pedir("competitions/list", &[("search", q)], None, true)?)? {
                let f = competicion_corta(&c)?;
                if f.texto("ref") == Some(slug.as_str()) {
                    return Ok(Some(f));
                }
            }
            Ok(None)
        };
        let mut f = match buscar(slug.replace('-', " ").chars().take(100).collect())? {
            Some(f) => f,
            None => match buscar(slug.clone())? {
                Some(f) => f,
                None => Mapa::new()
                    .con("ref", slug.clone())
                    .con("titulo", slug.clone())
                    .con("subtitulo", "")
                    .con("url", format!("https://www.kaggle.com/competitions/{slug}"))
                    .con("etiquetas", Valor::Lista(vec![])),
            },
        };
        let d = pedir(&format!("competitions/data/list/{slug}"), &[], None, true)?;
        let archivos_api = match &d {
            Valor::Mapa(m) => m.get("files").cloned().unwrap_or(Valor::Nulo),
            otro => otro.clone(),
        };
        let mut archivos = Vec::new();
        let mut total = 0f64;
        for a in lista(archivos_api)? {
            let b = get(&a, "totalBytes")?;
            total += o(b.clone(), Valor::Entero(0)).num().unwrap_or(0.0);
            archivos.push(Valor::Mapa(
                Mapa::new().con("nombre", get(&a, "name")?).con("bytes", b).con("descripcion", o(get(&a, "description")?, Valor::Texto(String::new()))).con("columnas", Valor::Lista(vec![])),
            ));
        }
        f.poner("archivos", Valor::Lista(archivos));
        f.poner("bytes", Valor::Entero(total as i128));
        f.poner("reglas", format!("https://www.kaggle.com/competitions/{slug}/rules"));
        Ok(Valor::Mapa(f))
    })?;
    let Valor::Mapa(mut f) = ficha else { return Err(Fallo::Interno) };
    f.poner("tipo", "competicion");
    f.poner("local", match espacio {
        Some(e) => kaggle_datos::local(&slug, e)?.map(Valor::Mapa).unwrap_or(Valor::Nulo),
        None => Valor::Nulo,
    });
    Ok(f)
}

// ---------------------------------------------------------------------------------------------- descargar

/// `_tam(n)`
pub fn tam(n: f64) -> String {
    let mut n = n;
    for u in ["B", "KB", "MB", "GB"] {
        if n < 1024.0 || u == "GB" {
            return if u == "B" { format!("{n:.0} {u}") } else { format!("{n:.1} {u}") };
        }
        n /= 1024.0;
    }
    format!("{n} B")
}

/// `_descomprimir`: el zip en `destino` (nada fuera de la carpeta); un archivo que no es zip queda como «datos»
fn descomprimir(zip_ruta: &Path, destino: &Path) -> Result<(), Fallo> {
    let f = std::fs::File::open(zip_ruta).map_err(|_| Fallo::Interno)?;
    let Ok(mut z) = zip::ZipArchive::new(f) else {
        std::fs::create_dir_all(destino).map_err(|_| Fallo::Interno)?;
        std::fs::rename(zip_ruta, destino.join("datos")).map_err(|_| Fallo::Interno)?;
        return Ok(());
    };
    std::fs::create_dir_all(destino).map_err(|_| Fallo::Interno)?;
    let raiz = std::fs::canonicalize(destino).map_err(|_| Fallo::Interno)?;
    for i in 0..z.len() {
        let mut e = z.by_index(i).map_err(|_| Fallo::Interno)?;
        let nombre = e.name().to_string();
        let ruta = PathBuf::from(py::normpath(&raiz.join(&nombre).to_string_lossy()));
        if !(ruta == raiz || ruta.starts_with(&raiz)) {
            continue; // «zip slip»
        }
        if e.is_dir() {
            std::fs::create_dir_all(&ruta).map_err(|_| Fallo::Interno)?;
            continue;
        }
        if let Some(p) = ruta.parent() {
            std::fs::create_dir_all(p).map_err(|_| Fallo::Interno)?;
        }
        let mut salida = std::fs::File::create(&ruta).map_err(|_| Fallo::Interno)?;
        std::io::copy(&mut e, &mut salida).map_err(|_| Fallo::Interno)?;
    }
    Ok(())
}

/// `descargar(tipo, texto, workspace, avisar, cancelar)`: baja el zip y lo descomprime en kaggle_datos/<slug>/
pub fn descargar(tipo: &str, texto: &str, espacio: &Path, avisar: &mut dyn FnMut(Mapa) -> bool) -> Result<Mapa, Fallo> {
    let r = if tipo == "dataset" { ref_dataset(texto)? } else { kaggle::ref_competicion(texto)? };
    let cuenta = kaggle::credenciales();
    if tipo != "dataset" && cuenta.is_none() {
        return error("Para bajar los datos de una competición hace falta conectar tu cuenta de Kaggle.");
    }
    let destino = espacio.join(CARPETA_DATOS).join(kaggle_datos::nombre_local(&r));
    std::fs::create_dir_all(destino.parent().ok_or(Fallo::Interno)?).map_err(|_| Fallo::Interno)?;
    let zip_tmp = PathBuf::from(format!("{}.zip.parcial", destino.display()));
    let url = if tipo == "dataset" { format!("{}/datasets/download/{r}", kaggle::api()) } else { format!("{}/competitions/data/download-all/{r}", kaggle::api()) };
    let cliente = reqwest::blocking::Client::builder().connect_timeout(Duration::from_secs(60)).build().map_err(|_| Fallo::Interno)?;
    let mut req = cliente.get(url).header("User-Agent", "Prig-IDE (lector de notebooks; uso educativo local)");
    match &cuenta {
        Some(kaggle::Cuenta::Token { token, .. }) => req = req.bearer_auth(token),
        Some(kaggle::Cuenta::Clave { usuario, clave, .. }) => req = req.basic_auth(s(usuario), Some(clave)),
        None => {}
    }
    let Ok(mut resp) = req.send() else { return error("Sin conexión con Kaggle: comprueba internet.") };
    let estado = resp.status().as_u16();
    let fallo = |t: String| Err(Fallo::Usuario(ErrorKaggle(t)));
    if estado == 403 && tipo != "dataset" {
        return fallo(format!(
            "Kaggle pide aceptar las reglas de la competición antes de bajar sus datos: entra en kaggle.com/competitions/{r}/rules, pulsa «I Understand and Accept» y reintenta."
        ));
    }
    match estado {
        200 => {}
        401 => return error("Kaggle no aceptó tus credenciales: vuelve a conectar la cuenta."),
        404 => return error("Kaggle no encuentra esos datos (¿privados o borrados?)."),
        s => return fallo(format!("Kaggle respondió {s} al descargar.")),
    }
    let total = resp.content_length().unwrap_or(0) as f64;
    let mut bajado = 0f64;
    let mut ultimo: Option<Instant> = None;
    let r_bajar = (|| -> Result<(), Fallo> {
        use std::io::{Read, Write};
        let mut f = std::fs::File::create(&zip_tmp).map_err(|_| Fallo::Interno)?;
        let mut b = vec![0u8; 1 << 16];
        loop {
            let n = resp.read(&mut b).map_err(|_| Fallo::Usuario(ErrorKaggle("Sin conexión con Kaggle: comprueba internet.".into())))?;
            if n == 0 {
                break;
            }
            f.write_all(&b[..n]).map_err(|_| Fallo::Interno)?;
            bajado += n as f64;
            if ultimo.is_none_or(|u| u.elapsed() > Duration::from_millis(400)) {
                ultimo = Some(Instant::now());
                let m = format!("Descargando {}{}", tam(bajado), if total > 0.0 { format!(" de {}", tam(total)) } else { String::new() });
                let sigue = avisar(Mapa::new().con("tipo", "progreso").con("bytes", bajado as i128).con("total", total as i128).con("mensaje", m));
                if !sigue {
                    return error("Descarga cancelada.");
                }
            }
        }
        Ok(())
    })();
    if let Err(e) = r_bajar {
        let _ = std::fs::remove_file(&zip_tmp);
        return Err(e);
    }
    avisar(Mapa::new().con("tipo", "progreso").con("bytes", bajado as i128).con("total", total as i128).con("mensaje", "Descomprimiendo…"));
    let r_zip = descomprimir(&zip_tmp, &destino);
    let _ = std::fs::remove_file(&zip_tmp);
    r_zip?;
    // `_registrar`
    let ruta_reg = kaggle::carpeta().join("descargas.json");
    let mut reg = kaggle::leer_objeto(&ruta_reg).unwrap_or_default();
    reg.poner(destino.to_string_lossy().into_owned(), Mapa::new().con("tipo", tipo).con("ref", r.clone()).con("fecha", ahora_s()));
    std::fs::create_dir_all(kaggle::carpeta()).map_err(|_| Fallo::Interno)?;
    let tmp = PathBuf::from(format!("{}.tmp", ruta_reg.display()));
    std::fs::write(&tmp, prig_plataforma::json::escribir_linea(&Valor::Mapa(reg))).map_err(|_| Fallo::Interno)?;
    std::fs::rename(&tmp, &ruta_reg).map_err(|_| Fallo::Interno)?;
    Ok(kaggle_datos::local(&r, espacio)?.unwrap_or_default())
}
