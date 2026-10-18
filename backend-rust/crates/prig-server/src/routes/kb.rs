//! La base de conocimiento destilada (`prig_biblioteca::base_kb`): su estado y los paquetes `.prigpack` que hay en
//! `~/.prig_books/packs`, buscar afirmaciones y los conceptos puente entre campos.

use std::collections::HashMap;

use axum::{
    body::Bytes,
    extract::Query,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_biblioteca::base_kb::BaseKb;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, json_py};

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

async fn en_hilo<F: FnOnce() -> Result<Valor, String> + Send + 'static>(f: F) -> Response {
    match tokio::task::spawn_blocking(f).await {
        Ok(Ok(v)) => json_py(StatusCode::OK, &v),
        _ => error_500(),
    }
}

pub fn carpeta_packs() -> String {
    py::join(&py::expanduser("~/.prig_books"), "packs")
}

/// El `source_id` del manifiesto de un paquete (sin descomprimir el resto)
pub fn source_id_de_pack(ruta: &str) -> Option<String> {
    let f = std::fs::File::open(ruta).ok()?;
    let mut z = zip::ZipArchive::new(f).ok()?;
    let mut m = z.by_name("manifest.json").ok()?;
    let mut t = String::new();
    std::io::Read::read_to_string(&mut m, &mut t).ok()?;
    match prig_plataforma::json::leer(&t).ok()? {
        Valor::Mapa(m) => m.get("source_id").filter(|s| s.verdad()).map(Valor::texto_py),
        _ => None,
    }
}

/// `GET /api/kb/status`: lo que hay en la base y los paquetes aún sin importar
pub async fn estado() -> Response {
    en_hilo(|| {
        let dir = carpeta_packs();
        let _ = std::fs::create_dir_all(&dir);
        let mut disponibles: Vec<String> =
            std::fs::read_dir(&dir).map(|l| l.flatten().map(|e| e.file_name().to_string_lossy().to_string()).filter(|f| f.ends_with(".prigpack")).collect()).unwrap_or_default();
        disponibles.sort();
        let lista = |l: &[String]| Valor::Lista(l.iter().map(|s| Valor::Texto(s.clone())).collect());
        let base = BaseKb::por_defecto();
        let stats = match base.as_ref().map_err(|e| e.clone()).and_then(|b| b.estadisticas()) {
            Ok(s) => s,
            Err(e) => return Ok(Valor::Mapa(Mapa::new().con("disponible", false).con("error", e).con("packs_en_carpeta", lista(&disponibles)))),
        };
        let dentro = base?.libros_dentro()?;
        let sin: Vec<String> = disponibles.iter().filter(|f| !source_id_de_pack(&py::join(&dir, f)).is_some_and(|s| dentro.contains(&s))).cloned().collect();
        let mut m = Mapa::new().con("disponible", stats.verdad("libros")).con("carpeta_packs", dir.as_str()).con("packs_en_carpeta", lista(&disponibles)).con("sin_importar", lista(&sin));
        for (k, v) in stats.iter() {
            m.poner(k.clone(), v.clone());
        }
        Ok(Valor::Mapa(m))
    })
    .await
}

const ENTERO_OPC: Tipo = Tipo::Opcional(&Tipo::Entero);

/// `POST /api/kb/search` (`query`, `top_k`): afirmaciones por texto completo
pub async fn buscar(b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(
            &m,
            &[("query", &Tipo::Texto, true), ("top_k", &Tipo::Entero, false), ("expand", &Tipo::Booleano, false), ("model", &Tipo::Texto, false), ("max_context_tokens", &ENTERO_OPC, false)],
        )
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        let n = c.get("top_k").and_then(Valor::num).map(|n| n as i64).unwrap_or(8);
        let r = BaseKb::por_defecto()?.buscar(&c.valor("query").texto_py(), if n == 0 { 20 } else { n }, &[], &[], None)?;
        Ok(Valor::Mapa(Mapa::new().con("resultados", Valor::Lista(r.into_iter().map(Valor::Mapa).collect()))))
    })
    .await
}

/// `GET /api/kb/bridges?limite=` (hasta 200)
pub async fn puentes(Query(q): Query<HashMap<String, String>>) -> Response {
    let limite = match cuerpo::entero_consulta(&q, "limite", 50, i64::MIN, 200) {
        Ok(n) => n,
        Err(r) => return r,
    };
    en_hilo(move || Ok(Valor::Mapa(Mapa::new().con("puentes", Valor::Lista(BaseKb::por_defecto()?.puentes(limite)?.into_iter().map(Valor::Mapa).collect()))))).await
}

// =========================================================================== el contexto del tutor

use prig_biblioteca::contexto_kb::{Compilador, Ensamblador, Indice};

/// Los ajustes del embebedor (Modelos → Embeddings): modelo, dimensiones y truncado
fn ajustes_embebedor() -> (String, Valor, bool) {
    let e = prig_modelos::opciones::config().embeddings();
    let modelo = e.get("modelo").filter(|m| m.verdad()).map(Valor::texto_py).unwrap_or_else(|| "bge-m3".into());
    (modelo, e.get("dimensiones").cloned().unwrap_or(Valor::Nulo), e.get("truncar").map(Valor::verdad).unwrap_or(true))
}

/// La Ollama del índice semántico: la de los recursos (`PRIG_OLLAMA_URL` o la de siempre)
fn base_ollama() -> String {
    prig_ia::gestor::url_ollama().trim_end_matches('/').to_string()
}

/// `IndiceSemantico.embeber`: en CPU (`num_gpu: 0`), para no mover el generador de la GPU
pub fn embeber(textos: &[String], segundos: u64) -> Result<Vec<Vec<f64>>, String> {
    if textos.is_empty() {
        return Ok(Vec::new());
    }
    let (modelo, dims, truncar) = ajustes_embebedor();
    let mut c = Mapa::new().con("model", modelo).con("input", Valor::Lista(textos.iter().map(|t| Valor::Texto(t.clone())).collect())).con("keep_alive", "30m");
    if dims.verdad() {
        c.poner("dimensions", dims);
    }
    if !truncar {
        c.poner("truncate", false);
    }
    c.poner("options", Mapa::new().con("num_gpu", 0));
    let r = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(segundos))
        .build()
        .map_err(|e| e.to_string())?
        .post(format!("{}/api/embed", base_ollama()))
        .header("Content-Type", "application/json")
        .body(prig_plataforma::json::escribir_compacto(&Valor::Mapa(c)))
        .send()
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?
        .text()
        .map_err(|e| e.to_string())?;
    let Ok(Valor::Mapa(m)) = prig_plataforma::json::leer(&r) else { return Err("respuesta no válida".into()) };
    Ok(m.lista("embeddings").unwrap_or(&[]).iter().map(|v| match v {
        Valor::Lista(l) => l.iter().filter_map(Valor::num).collect(),
        _ => Vec::new(),
    }).collect())
}

fn embeber_consulta(t: &[String]) -> Result<Vec<Vec<f64>>, String> {
    embeber(t, 60)
}

/// `disponible`: el modelo de embeddings está descargado
fn embebedor_descargado() -> bool {
    let modelo = ajustes_embebedor().0;
    let Ok(Ok(t)) = reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(5)).build().map(|c| c.get(format!("{}/api/tags", base_ollama())).send().and_then(|r| r.text())) else {
        return false;
    };
    let dentro = format!("{modelo}:");
    match prig_plataforma::json::leer(&t) {
        Ok(Valor::Mapa(m)) => m.lista("models").unwrap_or(&[]).iter().any(|x| matches!(x, Valor::Mapa(x) if { let n = x.valor("name").texto_py(); n == modelo || n.starts_with(&dentro) })),
        _ => false,
    }
}

fn no_encontrado(t: String) -> Response {
    crate::routes::detalle(StatusCode::NOT_FOUND, t)
}

/// `GET /api/kb/concept?nombre=`: el dosier de un concepto, por cualquiera de sus nombres
pub async fn concepto(Query(q): Query<HashMap<String, String>>) -> Response {
    let nombre = match cuerpo::texto_consulta(&q, "nombre") {
        Ok(n) => n,
        Err(r) => return r,
    };
    match tokio::task::spawn_blocking(move || -> Result<Result<Valor, String>, String> {
        let kb = BaseKb::por_defecto()?;
        let Some(c) = kb.resolver(&nombre)? else { return Ok(Err(format!("'{nombre}' no aparece en la biblioteca"))) };
        let cid = c.valor("concept_id").texto_py();
        let e = Ensamblador::new(&kb, &embeber_consulta);
        let dosier = e.dosier(&cid)?.unwrap_or(Valor::Nulo);
        let pre = kb.prerrequisitos(&cid, 3)?;
        Ok(Ok(Valor::Mapa(Mapa::new().con("concepto", c).con("dosier", dosier).con("prerrequisitos", Valor::Lista(pre.into_iter().map(Valor::Mapa).collect())))))
    })
    .await
    {
        Ok(Ok(Ok(v))) => json_py(StatusCode::OK, &v),
        Ok(Ok(Err(m))) => no_encontrado(m),
        _ => error_500(),
    }
}

/// `POST /api/kb/compilar`: recompila el contexto denso de todos los conceptos
pub async fn compilar() -> Response {
    en_hilo(|| Ok(Valor::Mapa(Compilador { kb: &BaseKb::por_defecto()? }.precompilar()?))).await
}

/// `GET /api/kb/contexto?pregunta=&presupuesto=&compilado=`: el contexto exacto que recibiría el modelo
pub async fn contexto(Query(q): Query<HashMap<String, String>>) -> Response {
    let pregunta = match cuerpo::texto_consulta(&q, "pregunta") {
        Ok(n) => n,
        Err(r) => return r,
    };
    let presupuesto = match cuerpo::entero_consulta(&q, "presupuesto", 1200, i64::MIN, i64::MAX) {
        Ok(n) => n,
        Err(r) => return r,
    };
    let compilado = match cuerpo::booleano_consulta(&q, "compilado") {
        Ok(c) => c.unwrap_or(true),
        Err(r) => return r,
    };
    en_hilo(move || {
        let kb = BaseKb::por_defecto()?;
        let r = Ensamblador::new(&kb, &embeber_consulta).ensamblar(&pregunta, presupuesto, None, "intermedio", compilado)?;
        let mut m = Mapa::new();
        for (k, v) in r.iter().filter(|(k, _)| k.as_str() != "fuentes") {
            m.poner(k.clone(), v.clone());
        }
        m.poner("citas_disponibles", r.lista("fuentes").map(|l| l.len()).unwrap_or(0) as i64);
        Ok(Valor::Mapa(m))
    })
    .await
}

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);

/// `POST /api/kb/context` (`pregunta`, `presupuesto_tokens`, `dominio`, `nivel`): el mensaje de sistema del tutor
pub async fn contexto_tutor(b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(&m, &[("pregunta", &Tipo::Texto, true), ("presupuesto_tokens", &ENTERO_OPC, false), ("dominio", &TEXTO_OPC, false), ("nivel", &Tipo::Texto, false)])
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || {
        let kb = BaseKb::por_defecto()?;
        let presupuesto = crate::routes::conocimiento::presupuesto(c.get("presupuesto_tokens").and_then(Valor::num).map(|n| n as i64));
        let dominio = c.get("dominio").filter(|d| !d.es_nulo()).map(Valor::texto_py);
        let nivel = c.get("nivel").map(Valor::texto_py).unwrap_or_else(|| "intermedio".into());
        Ok(Valor::Mapa(Ensamblador::new(&kb, &embeber_consulta).prompt_tutor(&c.valor("pregunta").texto_py(), presupuesto, dominio.as_deref(), &nivel)?))
    })
    .await
}

/// `GET /api/kb/indice`: si el índice semántico está en pie y con qué modelo
pub async fn indice() -> Response {
    en_hilo(|| {
        let kb = BaseKb::por_defecto()?;
        let c = kb.conectar()?;
        c.execute_batch("CREATE TABLE IF NOT EXISTS vectores (concept_id TEXT PRIMARY KEY, vector BLOB, dimension INTEGER, modelo TEXT, indexado_en TEXT);").map_err(|e| e.to_string())?;
        let f = prig_biblioteca::base_kb::filas(&c, "SELECT COUNT(*) n, MAX(indexado_en) cuando,\n                                           MAX(modelo) modelo, MAX(dimension) dim\n                                    FROM vectores;", &[])?;
        let f = f.into_iter().next().unwrap_or_default();
        let con = prig_biblioteca::base_kb::filas(&c, "SELECT modelo, dimension FROM vectores LIMIT 1;", &[])?.into_iter().next();
        let (modelo, dims, truncar) = ajustes_embebedor();
        let necesita = con.as_ref().is_some_and(|x| x.valor("modelo").texto_py() != modelo || (dims.verdad() && x.get("dimension") != Some(&dims)));
        Ok(Valor::Mapa(
            Mapa::new()
                .con("modelo", modelo)
                .con("dimensiones_pedidas", dims)
                .con("truncar", truncar)
                .con("indexado_con", con.map(Valor::Mapa).unwrap_or(Valor::Nulo))
                .con("necesita_reindexar", necesita)
                .con("descargado", embebedor_descargado())
                .con("en_cpu", true)
                .con("conceptos_indexados", f.get("n").cloned().unwrap_or(Valor::Entero(0)))
                .con("dimension", f.get("dim").cloned().unwrap_or(Valor::Nulo))
                .con("indexado_en", f.get("cuando").cloned().unwrap_or(Valor::Nulo)),
        ))
    })
    .await
}

/// `IndiceSemantico.indexar`: embebe el bloque compilado de cada concepto (de 64 en 64)
pub fn indexar_semantico(kb: &BaseKb) -> Result<Mapa, String> {
    if !embebedor_descargado() {
        return Ok(Mapa::new().con("ok", false).con("motivo", "'bge-m3' no está descargado. Instálalo con: ollama pull bge-m3"));
    }
    let comp = Compilador { kb };
    let c = kb.conectar()?;
    c.execute_batch("CREATE TABLE IF NOT EXISTS vectores (concept_id TEXT PRIMARY KEY, vector BLOB, dimension INTEGER, modelo TEXT, indexado_en TEXT);").map_err(|e| e.to_string())?;
    let conceptos = prig_biblioteca::base_kb::filas(&c, "SELECT concept_id, canonical_name FROM concepts WHERE mentions > 0;", &[])?;
    if conceptos.is_empty() {
        return Ok(Mapa::new().con("ok", true).con("conceptos", 0).con("segundos", 0.0));
    }
    let mut textos = Vec::new();
    let mut ids = Vec::new();
    for x in &conceptos {
        let cid = x.valor("concept_id").texto_py();
        let t = match comp.bloque(&cid).filter(|b| !b.is_empty()) {
            Some(b) => b,
            None => match comp.compilar_concepto(&cid, None)? {
                Some(b) => comp.render(&b, 0, "intermedio", None, &HashMap::new()),
                None => x.valor("canonical_name").texto_py(),
            },
        };
        textos.push(t);
        ids.push(cid);
    }
    let t0 = std::time::Instant::now();
    let mut vectores = Vec::new();
    for trozo in textos.chunks(64) {
        vectores.extend(embeber(trozo, 600)?);
    }
    if vectores.len() != ids.len() {
        return Ok(Mapa::new().con("ok", false).con("motivo", "el embebedor devolvió menos vectores de los pedidos"));
    }
    let ahora = py::ahora_iso();
    let modelo = ajustes_embebedor().0;
    c.execute("DELETE FROM vectores;", []).map_err(|e| e.to_string())?;
    for (cid, v) in ids.iter().zip(&vectores) {
        // `struct.pack(f"{n}f")`: float32 en el orden de la máquina
        let b: Vec<u8> = v.iter().flat_map(|x| (*x as f32).to_ne_bytes()).collect();
        c.execute("INSERT OR REPLACE INTO vectores VALUES (?,?,?,?,?);", rusqlite::params![cid, b, v.len() as i64, modelo, ahora]).map_err(|e| e.to_string())?;
    }
    Ok(Mapa::new()
        .con("ok", true)
        .con("conceptos", ids.len() as i64)
        .con("dimension", vectores[0].len() as i64)
        .con("segundos", prig_recursos::valor::redondear(t0.elapsed().as_secs_f64(), 1))
        .con("modelo", "bge-m3")
        .con("en_cpu", true))
}

/// `POST /api/kb/indexar`: rehace el índice semántico
pub async fn indexar() -> Response {
    match tokio::task::spawn_blocking(|| BaseKb::por_defecto().and_then(|kb| indexar_semantico(&kb))).await {
        Ok(Ok(r)) if r.verdad("ok") => json_py(StatusCode::OK, &Valor::Mapa(r)),
        Ok(Ok(r)) => crate::routes::detalle(StatusCode::BAD_REQUEST, r.get("motivo").map(Valor::texto_py).unwrap_or_else(|| "no se pudo indexar".into())),
        _ => error_500(),
    }
}

/// `_contexto_destilado`: el contexto de afirmaciones verificadas, si la base conoce el tema
pub fn contexto_destilado(pregunta: &str, presupuesto: i64) -> Option<Mapa> {
    let kb = BaseKb::por_defecto().ok()?;
    if !kb.estadisticas().ok()?.verdad("libros") {
        return None;
    }
    let ctx = Ensamblador::new(&kb, &embeber_consulta).ensamblar(pregunta, presupuesto, None, "intermedio", true).ok()?;
    if ctx.verdad("vacio") { None } else { Some(ctx) }
}

/// `context_assembler.ensamblar(consulta, presupuesto_tokens=…)` de los flujos: el texto, o "" si no hay nada o falla
pub fn contexto_texto(pregunta: &str, presupuesto: i64) -> String {
    let Ok(kb) = BaseKb::por_defecto() else { return String::new() };
    match Ensamblador::new(&kb, &embeber_consulta).ensamblar(pregunta, presupuesto, None, "intermedio", true) {
        Ok(c) if !c.verdad("vacio") => c.valor("texto").texto_py(),
        _ => String::new(),
    }
}

/// Que el índice semántico sirva para descartar: lo usa `Indice` por dentro (se exporta para las pruebas)
pub fn indice_de(kb: &BaseKb) -> Indice<'_> {
    Indice { kb, embeber: &embeber_consulta }
}

// =========================================================================== paquetes

use prig_biblioteca::paquetes::{self as paq, Fallo};

const BOOL: Tipo = Tipo::Booleano;

fn pedido_pack(b: &Bytes) -> Result<(Option<String>, bool), Response> {
    let c = cuerpo::modelo(b).and_then(|m| cuerpo::tipados(&m, &[("ruta", &TEXTO_OPC, false), ("forzar", &BOOL, false)]))?;
    Ok((c.get("ruta").filter(|r| !r.es_nulo()).map(Valor::texto_py), c.verdad("forzar")))
}

fn de_fallo(e: Fallo) -> Response {
    match e {
        Fallo::Paquete(t) => crate::routes::detalle(StatusCode::BAD_REQUEST, t),
        Fallo::Otro(_) => error_500(),
    }
}

/// `POST /api/kb/verify` (`ruta`): revisa un paquete sin tocar la base
pub async fn verificar(b: Bytes) -> Response {
    let (ruta, _) = match pedido_pack(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    let ruta = ruta.unwrap_or_default();
    let ruta = if py::isabs(&ruta) { ruta } else { py::join(&carpeta_packs(), &py::basename(&ruta)) };
    match tokio::task::spawn_blocking(move || {
        if !std::path::Path::new(&ruta).is_file() {
            return no_encontrado(format!("No existe el paquete: {ruta}"));
        }
        match paq::verificar(&ruta) {
            Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
            Err(e) => de_fallo(e),
        }
    })
    .await
    {
        Ok(r) => r,
        Err(_) => error_500(),
    }
}

/// `POST /api/kb/import` (`ruta`, `forzar`): importar (uno o la carpeta), unificar, dosieres, compilar, el índice
/// semántico y la verificación, de una vez
pub async fn importar(b: Bytes) -> Response {
    let (ruta, forzar) = match pedido_pack(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    match tokio::task::spawn_blocking(move || -> Response {
        let dir = carpeta_packs();
        let _ = std::fs::create_dir_all(&dir);
        let Ok(kb) = BaseKb::por_defecto() else { return error_500() };
        let importacion = match ruta.filter(|r| !r.is_empty()) {
            Some(r) => {
                let r = if py::isabs(&r) { r } else { py::join(&dir, &py::basename(&r)) };
                if !std::path::Path::new(&r).is_file() {
                    return no_encontrado(format!("No existe: {r}"));
                }
                match paq::importar(&kb, &r, forzar) {
                    Ok(m) => Mapa::new().con("importados", Valor::Lista(vec![Valor::Mapa(m)])).con("fallidos", Valor::Lista(vec![])).con("total", 1),
                    Err(e) => return de_fallo(e),
                }
            }
            None => match paq::importar_carpeta(&kb, &dir) {
                Ok(m) => m,
                Err(e) => return de_fallo(e),
            },
        };
        let pasos = (|| -> Result<Mapa, Fallo> {
            let u = paq::unificar(&kb)?;
            let d = paq::construir_dosieres(&kb)?;
            let comp = Compilador { kb: &kb }.precompilar().map_err(Fallo::Otro)?;
            let ind = indexar_semantico(&kb).map_err(Fallo::Otro)?;
            let v = paq::verificar_integridad(&kb)?;
            Ok(Mapa::new().con("importacion", importacion).con("unificacion", u).con("dosieres", d).con("compilacion", comp).con("indice_semantico", ind).con("verificacion", v))
        })();
        match pasos {
            Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
            Err(e) => de_fallo(e),
        }
    })
    .await
    {
        Ok(r) => r,
        Err(_) => error_500(),
    }
}

/// `GET /api/kb/books`: el informe libro a libro
pub async fn libros() -> Response {
    match tokio::task::spawn_blocking(|| BaseKb::por_defecto().map_err(Fallo::Otro).and_then(|kb| paq::verificar_integridad(&kb))).await {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err(e)) => de_fallo(e),
        Err(_) => error_500(),
    }
}

// =========================================================================== fichas de libros

use prig_biblioteca::perfil;

/// `GET /api/libros/analizables`
pub async fn libros_analizables() -> Response {
    en_hilo(|| Ok(Valor::Mapa(Mapa::new().con("libros", Valor::Lista(perfil::listar(&BaseKb::por_defecto()?)?.into_iter().map(Valor::Mapa).collect()))))).await
}

/// `GET /api/libros/ficha/{source_id}`
pub async fn libro_ficha(axum::extract::Path(sid): axum::extract::Path<String>) -> Response {
    match tokio::task::spawn_blocking(move || BaseKb::por_defecto().and_then(|kb| perfil::obtener(&kb, &sid))).await {
        Ok(Ok(Some(f))) if f.verdad() => json_py(StatusCode::OK, &f),
        Ok(Ok(_)) => no_encontrado("Ese libro todavía no tiene ficha".into()),
        _ => error_500(),
    }
}

/// `GET /api/libros/resumen/{source_id}`: lo que leería el flujo, tal cual
pub async fn libro_resumen(axum::extract::Path(sid): axum::extract::Path<String>) -> Response {
    match tokio::task::spawn_blocking(move || BaseKb::por_defecto().and_then(|kb| perfil::variables(&kb, &sid))).await {
        Ok(Ok(Some(v))) => {
            let mut tok = Mapa::new();
            for (k, x) in v.iter() {
                tok.poner(k.clone(), (x.texto_py().chars().count() as f64 / 3.6) as i64);
            }
            json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("variables", v).con("tokens", tok)))
        }
        Ok(Ok(None)) => no_encontrado("Ese libro no está en la base".into()),
        _ => error_500(),
    }
}

/// `GET /api/libros/material?concepto=`
pub async fn libro_material(Query(q): Query<HashMap<String, String>>) -> Response {
    let c = match cuerpo::texto_consulta(&q, "concepto") {
        Ok(c) => c,
        Err(r) => return r,
    };
    en_hilo(move || Ok(Valor::Mapa(perfil::material_para_ejercicio(&BaseKb::por_defecto()?, &c)?))).await
}

/// `GET /api/libros/contexto-plan?objetivo=`
pub async fn libro_contexto_plan() -> Response {
    en_hilo(|| Ok(Valor::Mapa(Mapa::new().con("contexto", perfil::contexto_para_plan(&BaseKb::por_defecto()?)?)))).await
}
