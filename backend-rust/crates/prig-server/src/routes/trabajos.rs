//! El trabajo de extracción para la GPU externa (`prig_biblioteca::trabajos`): los libros que se pueden mandar con
//! el campo que se les propone, prepararlo (de una vez o informando libro a libro) y los trabajos ya preparados.

use axum::{
    body::Bytes,
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_biblioteca::{dominios, trabajos};
use prig_plataforma::explorador::{Ambito, EXTENSIONES};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

pub fn carpeta_trabajos() -> String {
    py::join(&py::expanduser("~/.prig_books"), "jobs")
}

/// `GET /api/job/books`: los libros, el campo propuesto por el nombre y los repetidos
pub async fn libros() -> Response {
    let r = tokio::task::spawn_blocking(|| {
        let mut vistos: Vec<((u64, String), String)> = Vec::new();
        let mut salida = Vec::new();
        for b in trabajos::libros_disponibles(&prig_biblioteca::estante::Estante::por_defecto().raiz) {
            let ruta = b.valor("path").texto_py();
            let Ok(m) = std::fs::metadata(&ruta) else { continue };
            let clave = (m.len(), py::basename(&ruta));
            let p = dominios::sugerir_con_confianza("", &b.valor("name").texto_py());
            let previo = vistos.iter().find(|(k, _)| *k == clave).map(|(_, v)| v.clone());
            salida.push(Valor::Mapa(
                b.con("domain", p.valor("dominio").clone())
                    .con("revisar", !p.verdad("seguro"))
                    .con("motivo", p.valor("motivo").clone())
                    .con("duplicado", previo.is_some())
                    .con("duplicado_de", previo.map(Valor::Texto).unwrap_or(Valor::Nulo)),
            ));
            if !vistos.iter().any(|(k, _)| *k == clave) {
                vistos.push((clave, ruta));
            }
        }
        let mut doms = Mapa::new();
        for (k, v) in dominios::dominios().iter() {
            let Valor::Mapa(v) = v else { continue };
            doms.poner(k.clone(), Mapa::new().con("nombre", v.valor("name").clone()).con("icono", v.get("icon").cloned().unwrap_or(Valor::Texto(String::new()))));
        }
        Mapa::new().con("libros", Valor::Lista(salida)).con("dominios", doms).con("carpeta_trabajos", carpeta_trabajos())
    })
    .await;
    match r {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

/// `_libro_aceptable`: por qué no se puede meter este archivo en un trabajo
fn por_que_no(ruta: Option<&str>, ambito: &Ambito) -> Option<String> {
    let ruta = ruta.filter(|r| !r.is_empty())?;
    let completa = py::abspath(&py::expanduser(ruta));
    let p = std::path::Path::new(&completa);
    if !p.exists() {
        return Some("el archivo ya no está ahí".into());
    }
    if !p.is_file() {
        return Some("no es un archivo".into());
    }
    let ext = py::splitext(&completa).1.to_lowercase();
    if !EXTENSIONES.iter().any(|(e, _)| *e == ext) {
        let mut todas: Vec<&str> = EXTENSIONES.iter().map(|(e, _)| *e).collect();
        todas.sort();
        return Some(format!("no es un libro ({}); se admiten {}", if ext.is_empty() { "sin extensión" } else { &ext }, todas.join(", ")));
    }
    if !ambito.permitida(&completa) {
        return Some("está fuera de tu carpeta personal. Cópialo dentro, o ábrelo desde Buscar libros".into());
    }
    None
}

/// `_preparar_trabajo`: valida la selección y trocea lo válido; `Err((estado, detalle))`
fn preparar(libros: &[Valor], max_tokens: i64, ws: &str, pdf_listo: bool, avisar: &mut dyn FnMut(Mapa)) -> Result<Mapa, (StatusCode, String)> {
    let casa = py::expanduser("~");
    let ambito = Ambito { raiz: &casa, workspace: Some(ws) };
    let (mut aceptados, mut rechazados) = (Vec::new(), Vec::new());
    for l in libros {
        let Valor::Mapa(l) = l else { continue };
        let ruta_v = l.get("path").filter(|v| v.verdad()).or_else(|| l.get("ruta")).cloned().unwrap_or(Valor::Nulo);
        let ruta = if ruta_v.es_nulo() { None } else { Some(ruta_v.texto_py()) };
        match if ruta.as_deref().is_none_or(str::is_empty) { Some("ruta vacía".to_string()) } else { por_que_no(ruta.as_deref(), &ambito) } {
            Some(motivo) => rechazados.push(Mapa::new().con("ruta", ruta_v.clone()).con("nombre", py::basename(ruta.as_deref().unwrap_or(""))).con("motivo", motivo)),
            None => aceptados.push(
                Mapa::new()
                    .con("path", py::abspath(&py::expanduser(ruta.as_deref().unwrap_or(""))))
                    .con("domain", l.get("domain").cloned().unwrap_or(Valor::Nulo))
                    .con("ajustes", l.get("ajustes").filter(|a| a.verdad()).cloned().unwrap_or(Valor::Mapa(Mapa::new()))),
            ),
        }
    }
    if aceptados.is_empty() {
        let d: Vec<String> = rechazados
            .iter()
            .take(4)
            .map(|r| {
                let n = r.valor("nombre").texto_py();
                format!("{}: {}", if n.is_empty() { r.valor("ruta").texto_py() } else { n }, r.valor("motivo").texto_py())
            })
            .collect();
        let d = if d.is_empty() { "no has elegido ningún libro".to_string() } else { d.join("; ") };
        return Err((StatusCode::BAD_REQUEST, format!("No se puede preparar nada. {d}")));
    }
    let dir = carpeta_trabajos();
    let _ = std::fs::create_dir_all(&dir);
    let a = py::ahora_iso();
    let sello = format!("{}{}{}_{}{}{}", &a[0..4], &a[5..7], &a[8..10], &a[11..13], &a[14..16], &a[17..19]);
    let destino = py::join(&dir, &format!("prig_job_{sello}"));
    let manifest = trabajos::preparar(&aceptados, &destino, max_tokens, 120, pdf_listo, avisar).map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, format!("No se pudo preparar: {e}")))?;
    let manifest = manifest.con("rechazados", Valor::Lista(rechazados.into_iter().map(Valor::Mapa).collect()));
    if !manifest.verdad("total_books") {
        let motivos: Vec<String> = manifest.lista("failed").unwrap_or(&[]).iter().take(3).map(|f| if let Valor::Mapa(f) = f { f.valor("motivo").texto_py() } else { String::new() }).collect();
        let m = if motivos.is_empty() { "Revisa que no estén escaneados.".to_string() } else { motivos.join("; ") };
        return Err((StatusCode::BAD_REQUEST, format!("Ningún libro se pudo trocear. {m}")));
    }
    Ok(manifest)
}

const LISTA_DICTS: Tipo = Tipo::Lista(&Tipo::Dict(&Tipo::Cualquiera));

fn pedido(b: &Bytes) -> Result<(Vec<Valor>, i64), Response> {
    let c = cuerpo::modelo(b).and_then(|m| cuerpo::tipados(&m, &[("libros", &LISTA_DICTS, true), ("max_chunk_tokens", &Tipo::Entero, false)]))?;
    let l = c.lista("libros").map(<[Valor]>::to_vec).unwrap_or_default();
    if l.is_empty() {
        return Err(detalle(StatusCode::BAD_REQUEST, "No has elegido ningún libro"));
    }
    Ok((l, c.get("max_chunk_tokens").and_then(Valor::num).map(|n| n as i64).unwrap_or(500)))
}

/// `POST /api/job/prepare` (y `/api/sondeo/preparar`): trocea y deja la carpeta lista para subir
pub async fn preparar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let (libros, max) = match pedido(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    let ws = crate::routes::workspace::espacio_de_trabajo(&state).await.to_string_lossy().to_string();
    let r = tokio::task::spawn_blocking(move || preparar(&libros, max, &ws, crate::routes::libros::pdfium(&state), &mut |_| {})).await;
    match r {
        Ok(Ok(m)) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Ok(Err((e, d))) => detalle(e, d),
        Err(_) => error_500(),
    }
}

/// `POST /api/job/prepare-stream`: lo mismo, libro a libro, en NDJSON
pub async fn preparar_flujo(State(state): State<AppState>, b: Bytes) -> Response {
    let (libros, max) = match pedido(&b) {
        Ok(p) => p,
        Err(r) => return r,
    };
    let ws = crate::routes::workspace::espacio_de_trabajo(&state).await.to_string_lossy().to_string();
    crate::routes::asistente::flujo_con_tipo("application/x-ndjson", move |_cancelar, enviar| {
        let linea = |m: Mapa, ascii: bool| {
            let v = Valor::Mapa(m);
            (if ascii { prig_plataforma::json::escribir_compacto(&v) } else { prig_plataforma::json::escribir_linea(&v) }) + "\n"
        };
        enviar(linea(Mapa::new().con("tipo", "inicio").con("total", libros.len() as i64), true));
        let pdf = crate::routes::libros::pdfium(&state);
        let r = preparar(&libros, max, &ws, pdf, &mut |e| enviar(linea(e, false)));
        enviar(match r {
            Ok(m) => linea(Mapa::new().con("tipo", "fin").con("manifest", m), false),
            Err((_, d)) => linea(Mapa::new().con("tipo", "error").con("mensaje", d), false),
        });
    })
}

/// `GET /api/job/list`
pub async fn listar() -> Response {
    let r = tokio::task::spawn_blocking(|| {
        let dir = carpeta_trabajos();
        Mapa::new().con("trabajos", Valor::Lista(trabajos::listar(&dir))).con("carpeta", dir)
    })
    .await;
    match r {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

// =========================================================================== sondeo

use prig_biblioteca::sondeo;
use prig_plataforma::py::ErrorPy;

const LISTA_TEXTOS: Tipo = Tipo::Lista(&Tipo::Texto);
const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);

/// `SondeoLibro.sondear`: medir, clasificar con el modelo (si se pide y tiene sentido) y recomendar
fn sondear(state: &AppState, ruta: &str, modelo: &str, con_modelo: bool, cancelar: &prig_ia::vivo::Cancelar) -> Result<Mapa, String> {
    let (medicion, muestra) = sondeo::medir(ruta, crate::routes::libros::pdfium(state))?;
    let muestra: String = muestra.chars().take(6000).collect();
    let mut clasificacion = Mapa::new();
    if con_modelo && !modelo.is_empty() && !medicion.verdad("escaneado") && !medicion.get("error").is_some_and(Valor::verdad) {
        let (prompt, sistema) = sondeo::prompt_clasificar(&medicion, &muestra);
        let p = prig_ia::generar::PedidoGenerar {
            prompt,
            modelo: modelo.into(),
            sistema: sistema.into(),
            opciones: Some(Mapa::new().con("temperature", 0.1).con("num_predict", 700)),
            gobernador: true,
            ..Default::default()
        };
        let mut r = String::new();
        prig_ia::generar::generar(&state.base_dir, &p, cancelar, &mut |e: Mapa| {
            if e.get("t") == Some(&Valor::Texto("texto".into())) {
                r.push_str(&e.valor("v").texto_py());
            }
        });
        clasificacion = sondeo::leer_clasificacion(&r);
    }
    let rec = sondeo::recomendar(&medicion, &clasificacion);
    Ok(Mapa::new().con("medicion", medicion).con("clasificacion", clasificacion).con("recomendacion", rec))
}

/// `POST /api/sondeo` (`rutas`, `carpeta`, `con_modelo`, `modelo`, `tope`): libro a libro, en NDJSON
pub async fn sondeo_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(&m, &[("rutas", &LISTA_TEXTOS, false), ("carpeta", &TEXTO_OPC, false), ("con_modelo", &Tipo::Booleano, false), ("modelo", &TEXTO_OPC, false), ("tope", &Tipo::Entero, false)])
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let ws = crate::routes::workspace::espacio_de_trabajo(&state).await.to_string_lossy().to_string();
    let previo = tokio::task::spawn_blocking(move || -> Result<(Vec<String>, Mapa), Response> {
        let casa = py::expanduser("~");
        let ambito = Ambito { raiz: &casa, workspace: Some(&ws) };
        let mut rutas: Vec<String> = c.lista("rutas").unwrap_or(&[]).iter().map(Valor::texto_py).collect();
        if let Some(carpeta) = c.get("carpeta").filter(|v| v.verdad()).map(Valor::texto_py) {
            match ambito.listar(Some(&carpeta), true) {
                Ok(l) => rutas.extend(l.lista("libros").unwrap_or(&[]).iter().filter_map(|x| if let Valor::Mapa(x) = x { Some(x.valor("ruta").texto_py()) } else { None })),
                Err(e @ ErrorPy::Permiso(_)) => return Err(detalle(StatusCode::FORBIDDEN, e.texto())),
                Err(e @ ErrorPy::NoEsCarpeta(_)) | Err(e @ ErrorPy::Os { errno: 2 | 20, .. }) => return Err(detalle(StatusCode::NOT_FOUND, e.texto())),
                Err(_) => return Err(error_500()),
            }
        }
        let tope = c.get("tope").and_then(Valor::num).map(|n| n as i64).unwrap_or(40);
        let mut unicas: Vec<String> = Vec::new();
        for r in rutas {
            if !unicas.contains(&r) {
                unicas.push(r);
            }
        }
        let n = unicas.len() as i64;
        // `lista[:tope]` de Python (un tope negativo cuenta desde el final)
        let fin = if tope >= 0 { tope.min(n) } else { (n + tope).max(0) };
        let elegidas: Vec<String> = unicas.into_iter().filter(|r| ambito.permitida(r)).collect();
        let fin = fin.min(elegidas.len() as i64).max(0) as usize;
        let _ = fin;
        Ok((elegidas, c))
    })
    .await;
    let (rutas, c) = match previo {
        Ok(Ok(x)) => x,
        Ok(Err(r)) => return r,
        Err(_) => return error_500(),
    };
    let tope = c.get("tope").and_then(Valor::num).map(|n| n as i64).unwrap_or(40);
    let n = rutas.len() as i64;
    let fin = if tope >= 0 { tope.min(n) } else { (n + tope).max(0) } as usize;
    let rutas: Vec<String> = rutas.into_iter().take(fin).collect();
    if rutas.is_empty() {
        return detalle(StatusCode::BAD_REQUEST, "No hay ningún libro que sondear en esa selección");
    }
    let modelo = c.get("modelo").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_else(|| {
        prig_ia::motor::config_ia().get("agent1_model").map(Valor::texto_py).unwrap_or_else(|| "qwen2.5-coder:7b".into())
    });
    let con_modelo = c.get("con_modelo").map(Valor::verdad).unwrap_or(true);
    crate::routes::asistente::flujo_con_tipo("application/x-ndjson", move |cancelar, enviar| {
        let linea = |m: Mapa, ascii: bool| {
            let v = Valor::Mapa(m);
            (if ascii { prig_plataforma::json::escribir_compacto(&v) } else { prig_plataforma::json::escribir_linea(&v) }) + "\n"
        };
        let total = rutas.len() as i64;
        enviar(linea(Mapa::new().con("tipo", "inicio").con("total", total), true));
        for (i, ruta) in rutas.iter().enumerate() {
            let n = i as i64 + 1;
            enviar(linea(Mapa::new().con("tipo", "sondeando").con("n", n).con("total", total).con("nombre", py::basename(ruta)), false));
            let r = match sondear(&state, ruta, &modelo, con_modelo, cancelar) {
                Ok(m) => m.con("tipo", "resultado").con("n", n),
                Err(e) => Mapa::new().con("tipo", "fallo").con("n", n).con("ruta", ruta.as_str()).con("nombre", py::basename(ruta)).con("mensaje", e),
            };
            enviar(linea(r, false));
        }
        enviar(linea(Mapa::new().con("tipo", "fin"), true));
    })
}
