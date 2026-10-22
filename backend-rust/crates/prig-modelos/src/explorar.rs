//! El buscador de modelos con todo junto (la fachada de `buscador_modelos.py`): las tres plataformas a la vez (si una
//! falla, las demás siguen), las variantes comprobadas en el registro, las novedades, si lo instalado tiene versión
//! nueva, encontrar un modelo concreto por nombre o enlace, y los modelos que el usuario sigue
//! (~/.prig_buscador.json o PRIG_BUSCADOR_ARCHIVO).

use crate::buscador::{self as b, Bases, Cache, ErrorB};
use prig_recursos::valor::{Mapa, Valor};
use std::sync::{Mutex, OnceLock};

pub const OLLAMA: &str = "https://ollama.com";
pub const HUGGINGFACE: &str = "https://huggingface.co";
pub const MODELSCOPE: &str = "https://modelscope.cn";
const PROVEEDORES: [&str; 3] = ["ollama", "huggingface", "modelscope"];

pub fn cache() -> &'static Cache {
    static C: OnceLock<Cache> = OnceLock::new();
    C.get_or_init(Cache::default)
}

/// `str(e)` de la excepción de Python
pub fn texto_error(e: &ErrorB) -> String {
    match e {
        ErrorB::Buscador(t) => t.clone(),
        ErrorB::Red(r) => r.texto(),
        ErrorB::Py(p) => p.texto(),
    }
}

/// ErrorBuscador (un 400 en las rutas) o, si no, un fallo de red (503)
pub fn es_del_buscador(e: &ErrorB) -> bool {
    matches!(e, ErrorB::Buscador(_) | ErrorB::Py(prig_plataforma::py::ErrorPy::Propia(_)))
}

pub fn fuentes() -> Mapa {
    let f = |n: &str, w: &str| Mapa::new().con("nombre", n).con("web", w);
    Mapa::new()
        .con("ollama", f("Ollama", "https://ollama.com"))
        .con("huggingface", f("Hugging Face", "https://huggingface.co"))
        .con("modelscope", f("ModelScope", "https://modelscope.cn"))
}

pub fn ordenes() -> Mapa {
    Mapa::new()
        .con("ollama", Mapa::new().con("relevancia", Valor::Nulo).con("recientes", "newest"))
        .con(
            "huggingface",
            Mapa::new()
                .con("relevancia", "downloads")
                .con("descargas", "downloads")
                .con("tendencia", "trendingScore")
                .con("me_gusta", "likes")
                .con("actualizados", "lastModified")
                .con("recientes", "createdAt"),
        )
        .con("modelscope", Mapa::new().con("relevancia", "Default").con("descargas", "DownloadsCount").con("actualizados", "GmtModified"))
}

/// Una búsqueda en una plataforma. `pagina`: la de esa plataforma (número, o la marca de Hugging Face)
pub fn buscar_en(fuente: &str, consulta: &str, orden: &str, capacidad: Option<&str>, pagina: Option<&Valor>, limite: Option<i64>) -> Result<Valor, ErrorB> {
    let numero = || pagina.filter(|p| p.verdad()).and_then(Valor::num).map(|n| n as i64).unwrap_or(1);
    match fuente {
        "ollama" => b::ollama_buscar(OLLAMA, consulta, orden, capacidad, numero(), cache()),
        "huggingface" => {
            let marca = pagina.filter(|p| p.verdad()).map(Valor::texto_py);
            b::hf_buscar(HUGGINGFACE, consulta, orden, marca.as_deref(), limite.unwrap_or(30), cache())
        }
        _ => b::ms_buscar(MODELSCOPE, consulta, orden, numero(), limite.unwrap_or(30), cache()),
    }
}

/// `buscar(consulta, fuentes, orden, capacidad, paginas)`: en varias plataformas a la vez
pub fn buscar(consulta: &str, fuentes: &[String], orden: &str, capacidad: Option<&str>, paginas: &Mapa) -> Mapa {
    let mut elegidas: Vec<&str> = fuentes.iter().map(String::as_str).filter(|f| PROVEEDORES.contains(f)).collect();
    if elegidas.is_empty() {
        elegidas = PROVEEDORES.to_vec();
    }
    let resultados: Vec<(String, Valor, Valor)> = std::thread::scope(|s| {
        let hilos: Vec<_> = elegidas
            .iter()
            .map(|f| {
                let f = f.to_string();
                s.spawn(move || match buscar_en(&f, consulta, orden, capacidad, paginas.get(&f), None) {
                    Ok(r) => (f, r, Valor::Nulo),
                    Err(e) => (f, Valor::Mapa(Mapa::new().con("modelos", Valor::Lista(vec![])).con("siguiente", Valor::Nulo)), Valor::Texto(texto_error(&e))),
                })
            })
            .collect();
        hilos.into_iter().filter_map(|h| h.join().ok()).collect()
    });
    let mut por_fuente = Mapa::new();
    for (f, r, e) in resultados {
        let mut m = match r {
            Valor::Mapa(m) => m,
            _ => Mapa::new(),
        };
        m.poner("error", e);
        por_fuente.poner(f, m);
    }
    Mapa::new().con("fuentes", por_fuente)
}

/// `comprobar(ref)`: ¿se puede descargar? (el manifiesto en su registro)
pub fn comprobar(r: &str) -> Result<Valor, ErrorB> {
    let (a, b2, c) = prig_recursos::ficha::registro_de(r.trim());
    b::comprobar(r, (&a, &b2, &c), cache(), 30.0)
}

fn variantes_de(fuente: &str, id: &str) -> Result<Valor, ErrorB> {
    match fuente {
        "ollama" => b::ollama_variantes(OLLAMA, id, cache()),
        "huggingface" => b::hf_variantes(HUGGINGFACE, id, cache()),
        "modelscope" => b::ms_variantes(MODELSCOPE, id, cache()),
        _ => Err(ErrorB::Buscador("Fuente desconocida".into())),
    }
}

/// `variantes(fuente, id)`: con cada una comprobada en el registro (hasta 60, de 8 en 8)
pub fn variantes(fuente: &str, id: &str) -> Result<Mapa, ErrorB> {
    if !PROVEEDORES.contains(&fuente) {
        return Err(ErrorB::Buscador("Fuente desconocida".into()));
    }
    let mut datos = match variantes_de(fuente, id)? {
        Valor::Mapa(m) => m,
        _ => Mapa::new(),
    };
    let mut lista: Vec<Mapa> = datos.lista("variantes").unwrap_or(&[]).iter().filter_map(|v| if let Valor::Mapa(m) = v { Some(m.clone()) } else { None }).collect();
    let pendientes: Vec<usize> = (0..lista.len()).filter(|i| lista[*i].get("descargable").is_none_or(Valor::es_nulo)).take(60).collect();
    for tanda in pendientes.chunks(8) {
        let comprobados: Vec<(usize, Option<Valor>)> = std::thread::scope(|s| {
            let hilos: Vec<_> = tanda
                .iter()
                .map(|&i| {
                    let r = lista[i].get("ref").map(Valor::texto_py).unwrap_or_default();
                    s.spawn(move || (i, comprobar(&r).ok()))
                })
                .collect();
            hilos.into_iter().filter_map(|h| h.join().ok()).collect()
        });
        for (i, c) in comprobados {
            let Some(Valor::Mapa(c)) = c else { continue };
            let v = &mut lista[i];
            v.poner("descargable", c.get("descargable").cloned().unwrap_or(Valor::Nulo));
            if c.verdad("descargable") {
                v.poner("bytes", c.get("bytes").cloned().unwrap_or(Valor::Nulo));
                v.poner("vision", c.get("vision").cloned().unwrap_or(Valor::Nulo));
            } else {
                v.poner("nota", c.get("motivo").cloned().unwrap_or(Valor::Nulo));
            }
        }
    }
    datos.poner("variantes", Valor::Lista(lista.into_iter().map(Valor::Mapa).collect()));
    Ok(datos)
}

/// Lo último de cada plataforma
pub fn novedades() -> Mapa {
    let trabajos: [(&str, &str, &str, Option<i64>); 3] = [
        ("ollama_nuevos", "ollama", "recientes", None),
        ("huggingface_tendencia", "huggingface", "tendencia", Some(20)),
        ("modelscope_actualizados", "modelscope", "actualizados", Some(20)),
    ];
    let r: Vec<(String, Valor, Valor)> = std::thread::scope(|s| {
        let hilos: Vec<_> = trabajos
            .iter()
            .map(|(n, f, o, l)| {
                s.spawn(move || match buscar_en(f, "", o, None, None, *l) {
                    Ok(Valor::Mapa(m)) => (n.to_string(), m.get("modelos").cloned().unwrap_or(Valor::Lista(vec![])), Valor::Nulo),
                    Ok(_) => (n.to_string(), Valor::Lista(vec![]), Valor::Nulo),
                    Err(e) => (n.to_string(), Valor::Lista(vec![]), Valor::Texto(texto_error(&e))),
                })
            })
            .collect();
        hilos.into_iter().filter_map(|h| h.join().ok()).collect()
    });
    let mut m = Mapa::new();
    for (n, modelos, e) in r {
        m.poner(n, Mapa::new().con("modelos", modelos).con("error", e));
    }
    m
}

/// Cada modelo instalado comparado con su registro de origen (el digest de /api/tags es el del manifiesto)
pub fn actualizaciones_instalados(instalados: &[Mapa]) -> Vec<Valor> {
    let revisar = |m: &Mapa| -> Valor {
        let r = m.get("name").map(Valor::texto_py).unwrap_or_default();
        let base = Mapa::new().con("modelo", r.as_str()).con("fuente", b::fuente_de_ref(&r));
        let c = match comprobar(&r) {
            Ok(Valor::Mapa(c)) => c,
            Ok(_) => Mapa::new(),
            Err(e) => return Valor::Mapa(base.con("estado", "error").con("detalle", texto_error(&e))),
        };
        if !c.verdad("descargable") {
            let codigo = c.get("codigo").and_then(Valor::num).map(|n| n as i64);
            let local = matches!(codigo, Some(404) | Some(400));
            let detalle = if local {
                Valor::Texto("No está en ningún registro (creado o importado aquí)".into())
            } else {
                c.get("motivo").cloned().unwrap_or(Valor::Nulo)
            };
            return Valor::Mapa(base.con("estado", if local { "local" } else { "error" }).con("detalle", detalle));
        }
        let remoto = c.get("digest").map(Valor::texto_py).unwrap_or_default();
        let local = m.get("digest").filter(|d| d.verdad()).map(Valor::texto_py).unwrap_or_default();
        let estado = if Some(&Valor::Texto(remoto.clone())) == m.get("digest") { "al_dia" } else { "actualizable" };
        Valor::Mapa(
            base.con("estado", estado)
                .con("bytes", c.get("bytes").cloned().unwrap_or(Valor::Nulo))
                .con("local", local.chars().take(12).collect::<String>())
                .con("remoto", remoto.chars().take(12).collect::<String>()),
        )
    };
    let mut salida = Vec::new();
    for tanda in instalados.chunks(6) {
        let r: Vec<Valor> = std::thread::scope(|s| {
            let hilos: Vec<_> = tanda.iter().map(|m| s.spawn(move || revisar(m))).collect();
            hilos.into_iter().filter_map(|h| h.join().ok()).collect()
        });
        salida.extend(r);
    }
    salida
}

fn ficha_segura(fuente: &str, id: &str) -> (Option<Mapa>, Option<String>) {
    let bases = Bases { ollama: OLLAMA, huggingface: HUGGINGFACE, modelscope: MODELSCOPE };
    match b::ficha_repo(fuente, id, &bases, cache()) {
        Ok(f) => (f, None),
        Err(e) => (None, Some(texto_error(&e))),
    }
}

/// Encuentra un modelo concreto: con un enlace va directo; con «propietario/repo» mira en las tres; con un nombre
/// busca en las tres y separa lo exacto de lo parecido
pub fn localizar(texto: &str) -> Result<Mapa, ErrorB> {
    let q = b::interpretar(texto)?;
    let tipo = q.get("tipo").map(Valor::texto_py).unwrap_or_default();
    let (mut exactos, mut parecidos): (Vec<Mapa>, Vec<Mapa>) = (Vec::new(), Vec::new());
    let mut errores = Mapa::new();
    let buscar_nombre;
    if tipo == "enlace" || tipo == "repo" {
        let id = q.get("id").map(Valor::texto_py).unwrap_or_default();
        let fuentes: Vec<String> = match q.get("fuente").filter(|f| f.verdad()) {
            Some(f) => vec![f.texto_py()],
            None => PROVEEDORES.iter().map(|s| s.to_string()).collect(),
        };
        let r: Vec<(String, Option<Mapa>, Option<String>)> = std::thread::scope(|s| {
            let hilos: Vec<_> = fuentes
                .iter()
                .map(|f| {
                    let id = id.clone();
                    s.spawn(move || {
                        let (a, e) = ficha_segura(f, &id);
                        (f.clone(), a, e)
                    })
                })
                .collect();
            hilos.into_iter().filter_map(|h| h.join().ok()).collect()
        });
        for (f, ficha, e) in r {
            match (ficha, e) {
                (Some(x), _) => exactos.push(x),
                (None, Some(e)) => errores.poner(f, e),
                _ => {}
            }
        }
        buscar_nombre = exactos.is_empty() || exactos.iter().all(|m| m.verdad("sin_gguf"));
    } else {
        buscar_nombre = true;
    }
    if buscar_nombre {
        let consulta = q.get("consulta").map(Valor::texto_py).unwrap_or_default();
        let directo_id = if tipo == "nombre" { b::clave_ollama(&consulta) } else { None };
        let todas: Vec<String> = PROVEEDORES.iter().map(|s| s.to_string()).collect();
        let (directo, r) = std::thread::scope(|s| {
            let h = directo_id.as_ref().map(|id| s.spawn(move || ficha_segura("ollama", id)));
            let r = buscar(&consulta, &todas, "relevancia", None, &Mapa::new());
            (h.and_then(|h| h.join().ok()), r)
        });
        if let Some((Some(f), _)) = directo {
            exactos.push(f);
        }
        let mut vistos: Vec<(String, String)> = exactos
            .iter()
            .map(|m| (m.get("fuente").map(Valor::texto_py).unwrap_or_default(), m.get("id").map(Valor::texto_py).unwrap_or_default().to_lowercase()))
            .collect();
        let objetivo = b::clave(&consulta);
        let mut mismos = Vec::new();
        for (fuente, datos) in r.mapa("fuentes").cloned().unwrap_or_default().iter() {
            let Valor::Mapa(datos) = datos else { continue };
            if let Some(e) = datos.get("error").filter(|e| e.verdad()) {
                if !errores.contiene(fuente) {
                    errores.poner(fuente.clone(), e.clone());
                }
            }
            let mut n = 0;
            for m in datos.lista("modelos").unwrap_or(&[]) {
                let Valor::Mapa(m) = m else { continue };
                let id = m.get("id").map(Valor::texto_py).unwrap_or_default();
                let clave_v = (fuente.clone(), id.to_lowercase());
                if vistos.contains(&clave_v) {
                    continue;
                }
                if b::clave(&id) == objetivo {
                    if tipo == "nombre" { exactos.push(m.clone()) } else { mismos.push(m.clone()) }
                    vistos.push(clave_v);
                } else if b::parecido(&consulta, &id) && n < 6 {
                    parecidos.push(m.clone());
                    vistos.push(clave_v);
                    n += 1;
                }
            }
        }
        mismos.extend(parecidos);
        parecidos = mismos;
        // Lo comprobado directamente va primero; lo que salió de buscar, por descargas
        let (mut directos, mut de_busqueda): (Vec<Mapa>, Vec<Mapa>) = exactos.into_iter().partition(|m| m.get("sin_gguf").is_some_and(|v| !v.es_nulo()));
        de_busqueda.sort_by(|a, b| {
            let d = |m: &Mapa| -m.get("descargas").filter(|v| v.verdad()).and_then(Valor::num).unwrap_or(0.0);
            d(a).partial_cmp(&d(b)).unwrap_or(std::cmp::Ordering::Equal)
        });
        directos.extend(de_busqueda);
        exactos = directos;
    }
    let etiqueta = q.get("etiqueta").cloned().unwrap_or(Valor::Nulo);
    for m in exactos.iter_mut() {
        m.poner("destacar", etiqueta.clone());
    }
    Ok(Mapa::new()
        .con("interpretado", q)
        .con("exactos", Valor::Lista(exactos.into_iter().map(Valor::Mapa).collect()))
        .con("parecidos", Valor::Lista(parecidos.into_iter().map(Valor::Mapa).collect()))
        .con("errores", errores))
}

// =========================================================================== seguidos

pub fn ruta_estado() -> String {
    std::env::var("PRIG_BUSCADOR_ARCHIVO").ok().filter(|r| !r.is_empty()).unwrap_or_else(|| prig_plataforma::py::expanduser("~/.prig_buscador.json"))
}

fn cerrojo() -> std::sync::MutexGuard<'static, ()> {
    static C: Mutex<()> = Mutex::new(());
    C.lock().unwrap_or_else(|e| e.into_inner())
}

fn leer() -> Mapa {
    let mut d = match std::fs::read_to_string(ruta_estado()).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    };
    if !d.contiene("seguidos") {
        d.poner("seguidos", Mapa::new());
    }
    if !d.contiene("actualizaciones") {
        d.poner("actualizaciones", Valor::Nulo);
    }
    d
}

fn guardar(d: &Mapa) {
    let ruta = ruta_estado();
    let tmp = format!("{ruta}.tmp");
    if std::fs::write(&tmp, prig_plataforma::json::escribir(&Valor::Mapa(d.clone()), 1)).is_ok() {
        let _ = std::fs::rename(&tmp, &ruta);
    }
}

fn ahora() -> String {
    prig_plataforma::py::ahora_iso().chars().take(19).collect()
}

fn instantanea(variantes: &[Valor]) -> Mapa {
    let mut m = Mapa::new();
    for v in variantes {
        if let Valor::Mapa(v) = v {
            m.poner(
                v.get("etiqueta").map(Valor::texto_py).unwrap_or_default(),
                Mapa::new().con("bytes", v.get("bytes").cloned().unwrap_or(Valor::Nulo)).con("digest", v.get("digest").cloned().unwrap_or(Valor::Nulo)),
            );
        }
    }
    m
}

fn variantes_sin_comprobar(fuente: &str, id: &str) -> Result<Vec<Valor>, ErrorB> {
    match variantes_de(fuente, id)? {
        Valor::Mapa(m) => Ok(m.lista("variantes").map(<[Valor]>::to_vec).unwrap_or_default()),
        _ => Ok(Vec::new()),
    }
}

/// Seguir un modelo: guarda cómo están sus variantes
pub fn seguir(fuente: &str, id: &str, titulo: Option<&str>) -> Result<Mapa, ErrorB> {
    if !PROVEEDORES.contains(&fuente) {
        return Err(ErrorB::Buscador("Fuente desconocida".into()));
    }
    let variantes = variantes_sin_comprobar(fuente, id)?;
    let _g = cerrojo();
    let mut d = leer();
    let s = Mapa::new()
        .con("fuente", fuente)
        .con("id", id)
        .con("titulo", titulo.filter(|t| !t.is_empty()).unwrap_or(id))
        .con("desde", ahora())
        .con("instantanea", instantanea(&variantes))
        .con("cambios", Valor::Nulo)
        .con("revisado", ahora());
    let mut seguidos = d.mapa("seguidos").cloned().unwrap_or_default();
    seguidos.poner(format!("{fuente}:{id}"), s.clone());
    d.poner("seguidos", seguidos);
    guardar(&d);
    Ok(s)
}

pub fn dejar(fuente: &str, id: &str) {
    let _g = cerrojo();
    let mut d = leer();
    let mut seguidos = d.mapa("seguidos").cloned().unwrap_or_default();
    seguidos.quitar(&format!("{fuente}:{id}"));
    d.poner("seguidos", seguidos);
    guardar(&d);
}

pub fn lista() -> Vec<Valor> {
    let _g = cerrojo();
    leer()
        .mapa("seguidos")
        .cloned()
        .unwrap_or_default()
        .iter()
        .filter_map(|(_, s)| match s {
            Valor::Mapa(s) => {
                let mut m = Mapa::new();
                for (k, v) in s.iter().filter(|(k, _)| k.as_str() != "instantanea") {
                    m.poner(k.clone(), v.clone());
                }
                Some(Valor::Mapa(m))
            }
            _ => None,
        })
        .collect()
}

fn ordenadas(c: impl Iterator<Item = String>) -> Valor {
    let mut v: Vec<String> = c.collect();
    v.sort();
    Valor::Lista(v.into_iter().map(Valor::Texto).collect())
}

/// Revisa los seguidos: variantes nuevas, retiradas o cambiadas (otro tamaño o digest)
pub fn revisar() -> Vec<Valor> {
    let seguidos: Vec<Mapa> = {
        let _g = cerrojo();
        leer().mapa("seguidos").cloned().unwrap_or_default().iter().filter_map(|(_, s)| if let Valor::Mapa(s) = s { Some(s.clone()) } else { None }).collect()
    };
    let mut resultados: Vec<(String, Option<Mapa>, Option<String>)> = Vec::new();
    for tanda in seguidos.chunks(4) {
        let r: Vec<_> = std::thread::scope(|s| {
            let hilos: Vec<_> = tanda
                .iter()
                .map(|seg| {
                    s.spawn(move || {
                        let (f, id) = (seg.get("fuente").map(Valor::texto_py).unwrap_or_default(), seg.get("id").map(Valor::texto_py).unwrap_or_default());
                        let clave = format!("{f}:{id}");
                        match variantes_sin_comprobar(&f, &id) {
                            Err(e) => (clave, None, Some(texto_error(&e))),
                            Ok(v) => {
                                let ahora = instantanea(&v);
                                let antes = seg.mapa("instantanea").cloned().unwrap_or_default();
                                let nuevas = ordenadas(ahora.claves().filter(|k| !antes.contiene(k)).cloned());
                                let retiradas = ordenadas(antes.claves().filter(|k| !ahora.contiene(k)).cloned());
                                let cambiadas = ordenadas(
                                    ahora
                                        .iter()
                                        .filter(|(k, _)| antes.contiene(k))
                                        .filter(|(k, a)| {
                                            let (Valor::Mapa(a), Some(Valor::Mapa(b))) = (a, antes.get(k)) else { return false };
                                            let distinto = |c: &str| a.get(c).is_some_and(|x| x.verdad()) && b.get(c).is_some_and(|x| x.verdad()) && a.get(c) != b.get(c);
                                            distinto("digest") || distinto("bytes")
                                        })
                                        .map(|(k, _)| k.clone()),
                                );
                                let cambios = Mapa::new().con("nuevas", nuevas).con("retiradas", retiradas).con("cambiadas", cambiadas);
                                (clave, Some(cambios), None)
                            }
                        }
                    })
                })
                .collect();
            hilos.into_iter().filter_map(|h| h.join().ok()).collect()
        });
        resultados.extend(r);
    }
    {
        let _g = cerrojo();
        let mut d = leer();
        let mut seguidos = d.mapa("seguidos").cloned().unwrap_or_default();
        for (clave, cambios, error) in resultados {
            let Some(Valor::Mapa(mut s)) = seguidos.get(&clave).cloned() else { continue };
            s.poner("revisado", ahora());
            s.poner("error", error.map(Valor::Texto).unwrap_or(Valor::Nulo));
            if let Some(c) = cambios {
                let hay = c.iter().any(|(_, v)| v.verdad());
                s.poner("cambios", if hay { Valor::Mapa(c) } else { Valor::Nulo });
            }
            seguidos.poner(clave, s);
        }
        d.poner("seguidos", seguidos);
        guardar(&d);
    }
    lista()
}

/// Acepta el estado actual como el nuevo punto de comparación
pub fn marcar_visto(fuente: &str, id: &str) -> Result<Mapa, ErrorB> {
    let titulo = {
        let _g = cerrojo();
        leer().mapa("seguidos").and_then(|s| s.mapa(&format!("{fuente}:{id}")).cloned()).and_then(|s| s.get("titulo").map(Valor::texto_py))
    };
    seguir(fuente, id, titulo.as_deref())
}

/// Tras descargar `ref`, lo guardado deja de decir que tiene versión nueva
pub fn marcar_actualizado(r: &str) {
    let _g = cerrojo();
    let mut d = leer();
    let Some(Valor::Mapa(mut g)) = d.get("actualizaciones").filter(|v| v.verdad()).cloned() else { return };
    let mut modelos = g.lista("modelos").map(<[Valor]>::to_vec).unwrap_or_default();
    let latest = format!("{r}:latest");
    for m in modelos.iter_mut() {
        if let Valor::Mapa(m) = m {
            let nombre = m.get("modelo").map(Valor::texto_py).unwrap_or_default();
            if (nombre == r || nombre == latest) && m.get("estado") == Some(&Valor::Texto("actualizable".into())) {
                m.poner("estado", "al_dia");
            }
        }
    }
    let n = modelos.iter().filter(|m| matches!(m, Valor::Mapa(m) if m.get("estado") == Some(&Valor::Texto("actualizable".into())))).count();
    g.poner("modelos", Valor::Lista(modelos));
    g.poner("actualizables", n);
    d.poner("actualizaciones", g);
    guardar(&d);
}

/// Si lo instalado tiene versión nueva: lo guardado si tiene menos de `max_edad` segundos; si no, se recalcula
pub fn actualizaciones(instalados: impl FnOnce() -> Vec<Mapa>, max_edad: f64, forzar: bool) -> Mapa {
    let guardado = {
        let _g = cerrojo();
        leer().get("actualizaciones").filter(|v| v.verdad()).cloned()
    };
    let ahora_s = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    if let Some(Valor::Mapa(g)) = guardado {
        if !forzar && ahora_s - g.num_o("marca", 0.0) < max_edad {
            return g.con("de_cache", true);
        }
    }
    let resultados = actualizaciones_instalados(&instalados());
    let n = resultados.iter().filter(|m| matches!(m, Valor::Mapa(m) if m.get("estado") == Some(&Valor::Texto("actualizable".into())))).count();
    let nuevo = Mapa::new().con("marca", ahora_s).con("fecha", ahora()).con("modelos", Valor::Lista(resultados)).con("actualizables", n);
    {
        let _g = cerrojo();
        let mut d = leer();
        d.poner("actualizaciones", nuevo.clone());
        guardar(&d);
    }
    nuevo.con("de_cache", false)
}
