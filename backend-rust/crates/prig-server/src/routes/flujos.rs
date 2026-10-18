//! Los flujos de agentes (las rutas `/api/flujos…` de app.py, con `FlowStore` de agent_flows.py), la ficha de un libro
//! hecha con un flujo (`POST /api/libros/ficha`) y el workflow del editor (`POST /api/ai/workflow/run`). Los motores
//! están en `flujos_motor.rs`.
//!
//! Los flujos guardados y el historial de ejecuciones viven en `<espacio>/.prig_dataset/flujos.json` y
//! `flujos_historial.json`, escritos como los escribía Python (`indent=1`, de forma atómica). Cada petición los lee
//! del disco: Python los cargaba al arrancar y no veía lo que otro proceso escribiera después.

use axum::{
    body::Bytes,
    extract::{Path as Ruta, Query, State},
    http::StatusCode,
    response::Response,
};
use prig_ia::gestor;
use prig_plataforma::json;
use prig_plataforma::modelo::{Campo, Defecto, Modelo, Tipo};
use prig_plataforma::py;
use prig_plataforma::valor::{redondear, Mapa, Valor};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use crate::routes::asistente::flujo_con_tipo;
use crate::routes::flujos_motor::{self as fm, Ejecucion};
use crate::routes::workspace::espacio_de_trabajo;
use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    use axum::response::IntoResponse;
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn linea(m: Mapa) -> String {
    json::escribir_linea(&Valor::Mapa(m)) + "\n"
}

/// `json.dumps(m)` con lo no ASCII escapado
fn linea_ascii(m: Mapa) -> String {
    json::escribir_compacto(&Valor::Mapa(m)) + "\n"
}

async fn bloque<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| error_500())
}

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const DICT: Tipo = Tipo::Dict(&Tipo::Cualquiera);
const DICT_OPC: Tipo = Tipo::Opcional(&DICT);
const LISTA_DICTS: Tipo = Tipo::Lista(&DICT);

fn t(x: &str) -> Valor {
    Valor::Texto(x.into())
}

// =========================================================================== el almacén

/// Un escritor cada vez (los hilos de este servidor)
static CERROJO: Mutex<()> = Mutex::new(());

fn carpeta(espacio: &Path) -> PathBuf {
    espacio.join(".prig_dataset")
}

/// `FlowStore._cargar`: lo guardado, o vacío si falta o no se puede leer
fn leer(ruta: &Path) -> Option<Valor> {
    let texto = std::fs::read_to_string(ruta).ok()?;
    json::leer(&texto).ok()
}

fn flujos_guardados(espacio: &Path) -> Mapa {
    match leer(&carpeta(espacio).join("flujos.json")) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    }
}

fn historial_guardado(espacio: &Path) -> Vec<Valor> {
    match leer(&carpeta(espacio).join("flujos_historial.json")) {
        Some(Valor::Lista(l)) => l,
        _ => Vec::new(),
    }
}

/// `FlowStore._guardar`: escritura atómica
fn escribir(ruta: &Path, datos: &Valor) -> Result<(), String> {
    if let Some(d) = ruta.parent() {
        std::fs::create_dir_all(d).map_err(|e| e.to_string())?;
    }
    let tmp = PathBuf::from(format!("{}.tmp", ruta.display()));
    std::fs::write(&tmp, json::escribir(datos, 1)).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, ruta).map_err(|e| e.to_string())
}

fn ahora_ms() -> u128 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0)
}

fn actualizado(f: &Valor) -> String {
    match f {
        Valor::Mapa(m) => m.get("actualizado").map(Valor::texto_py).unwrap_or_default(),
        _ => String::new(),
    }
}

/// `FlowStore.listar`: lo más reciente primero
fn listar(espacio: &Path) -> Vec<Valor> {
    let mut v: Vec<Valor> = flujos_guardados(espacio).iter().map(|(_, f)| f.clone()).collect();
    v.sort_by_key(|f| std::cmp::Reverse(actualizado(f)));
    v
}

/// `FlowStore.obtener`
fn obtener(espacio: &Path, id: &str) -> Option<Mapa> {
    match flujos_guardados(espacio).get(id) {
        Some(Valor::Mapa(m)) => Some(m.clone()),
        _ => None,
    }
}

/// `FlowStore.guardar`: con su id, cuándo se creó y cuándo se cambió (y sin pasar de 200)
fn guardar(espacio: &Path, mut flujo: Mapa) -> Result<Mapa, String> {
    let _c = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let fid = if flujo.verdad("id") { flujo.valor("id").texto_py() } else { format!("flujo_{:x}", ahora_ms()) };
    flujo.poner("id", fid.as_str());
    if !flujo.contiene("creado") {
        flujo.poner("creado", py::ahora_iso());
    }
    flujo.poner("actualizado", py::ahora_iso());
    let mut todos = flujos_guardados(espacio);
    todos.poner(fid, flujo.clone());
    if todos.len() > fm::MAX_FLUJOS {
        let mut orden: Vec<(String, String)> = todos.iter().map(|(k, f)| (actualizado(f), k.clone())).collect();
        orden.sort_by(|a, b| a.0.cmp(&b.0));
        if let Some((_, k)) = orden.first() {
            let id = match todos.get(k) {
                Some(Valor::Mapa(f)) => f.valor("id").texto_py(),
                _ => k.clone(),
            };
            todos.quitar(&id);
        }
    }
    escribir(&carpeta(espacio).join("flujos.json"), &Valor::Mapa(todos))?;
    Ok(flujo)
}

/// `FlowStore.borrar`
fn borrar(espacio: &Path, id: &str) -> Result<bool, String> {
    let _c = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let mut todos = flujos_guardados(espacio);
    if todos.quitar(id).is_none() {
        return Ok(false);
    }
    escribir(&carpeta(espacio).join("flujos.json"), &Valor::Mapa(todos))?;
    Ok(true)
}

/// `FlowStore.anotar_ejecucion`: la ejecución con el prompt exacto de cada paso, la primera de las 100
fn anotar_ejecucion(espacio: &Path, flujo: &Mapa, entrada: &str, registro: Valor, segundos: Valor) -> Result<String, String> {
    let _c = CERROJO.lock().unwrap_or_else(|e| e.into_inner());
    let eid = format!("eje_{:x}", ahora_ms());
    let mut h = historial_guardado(espacio);
    h.insert(
        0,
        Valor::Mapa(
            Mapa::new()
                .con("id", eid.as_str())
                .con("flujo_id", flujo.valor("id").clone())
                .con("flujo_nombre", flujo.valor("nombre").clone())
                .con("cuando", py::ahora_iso())
                .con("entrada", entrada.chars().take(2000).collect::<String>())
                .con("segundos", segundos)
                .con("pasos", registro),
        ),
    );
    h.truncate(fm::MAX_HISTORIAL);
    escribir(&carpeta(espacio).join("flujos_historial.json"), &Valor::Lista(h))?;
    Ok(eid)
}

/// `lista[:n]` de Python
fn rebanada<T: Clone>(v: &[T], n: i64) -> Vec<T> {
    let largo = v.len() as i64;
    let fin = if n < 0 { (largo + n).max(0) } else { n.min(largo) };
    v[..fin as usize].to_vec()
}

// =========================================================================== los modelos

/// Lo instalado en Ollama: (nombre, tamaño en GB)
fn instalados(raiz: &Path) -> Vec<(String, Valor)> {
    prig_ia::ollama::modelos_detallados(raiz)
        .lista("models")
        .unwrap_or(&[])
        .iter()
        .filter_map(|m| match m {
            Valor::Mapa(m) => Some((
                m.valor("name").texto_py(),
                m.get("size_gb").filter(|s| s.verdad()).cloned().unwrap_or(Valor::Entero(0)),
            )),
            _ => None,
        })
        .collect()
}

/// `_modelo_que_razona()`: el mejor de razonamiento descargado que cabe, si hay alguno
fn modelo_que_razona(raiz: &Path) -> String {
    let inst: Vec<String> = instalados(raiz).into_iter().map(|(n, _)| n).collect();
    let mut mejor: Option<(f64, String)> = None;
    for (nombre, info) in fm::modelos().iter() {
        let Valor::Mapa(info) = info else { continue };
        let critica = info.lista("fuerte_en").unwrap_or(&[]).iter().any(|f| f == &t("criticar"));
        if inst.contains(nombre) && critica && info.num_o("vram_gb", 0.0) <= fm::vram_tipica() - 0.6 {
            let c = (info.num_o("razona", 0.0), nombre.clone());
            if mejor.as_ref().is_none_or(|m| c.0 > m.0 || (c.0 == m.0 && c.1 > m.1)) {
                mejor = Some(c);
            }
        }
    }
    mejor.map(|m| m.1).unwrap_or_default()
}

/// `ai_engine.config.get("agent1_model", "qwen2.5-coder:7b")`
fn modelo_base() -> Valor {
    prig_ia::motor::config_ia().get("agent1_model").cloned().unwrap_or_else(|| t("qwen2.5-coder:7b"))
}

/// `round(x, 1)`: los enteros se quedan como enteros
fn redondear_1(v: &Valor) -> Valor {
    match v {
        Valor::Real(x) => Valor::Real(redondear(*x, 1)),
        otro => otro.clone(),
    }
}

/// `_veredictos_flujos()`: la calculadora de recursos para cada modelo, en el uso «flujos»
struct Veredictos {
    maquina: Option<prig_recursos::calculadora::Maquina>,
    fichas: HashMap<String, Mapa>,
}

impl Veredictos {
    fn new(raiz: &Path) -> Veredictos {
        let g = gestor::gestor(raiz);
        match g.maquina(false) {
            Ok(m) => {
                let fichas = g.fichas_instaladas().into_iter().map(|f| (f.valor("nombre").texto_py(), f)).collect();
                Veredictos { maquina: Some(m), fichas }
            }
            Err(_) => Veredictos { maquina: None, fichas: HashMap::new() },
        }
    }

    fn calcular(&self, nombre: &str, info: &Mapa) -> Mapa {
        if info.verdad("embedding") {
            return Mapa::new()
                .con("cabe", true)
                .con("veredicto", "embeddings")
                .con("etiqueta", "Embeddings en CPU")
                .con("motivo", "Se ejecuta en la CPU.");
        }
        let Some(maq) = &self.maquina else {
            let vram = match info.get("vram_gb") {
                Some(v) if v.verdad() => v.num().unwrap_or(0.0),
                _ => 0.0,
            };
            return Mapa::new().con("cabe", vram <= fm::vram_tipica() - 0.6).con("veredicto", Valor::Nulo);
        };
        let ficha = match self.fichas.get(nombre).filter(|f| !f.is_empty()) {
            Some(f) => Ok(f.clone()),
            None => prig_recursos::ficha::desde_catalogo(nombre, info),
        };
        let r = ficha.and_then(|f| prig_recursos::calculadora::recomendar(&f, maq, "flujos", "equilibrado").map(|r| (f, r)));
        let (f, r) = match r {
            Ok(x) => x,
            Err(e) => return Mapa::new().con("cabe", false).con("veredicto", Valor::Nulo).con("motivo", e),
        };
        let v = r.valor("veredicto").texto_py();
        Mapa::new()
            .con("cabe", v == "entero" || v == "ajustando")
            .con("util", ["entero", "ajustando", "parcial", "solo_cpu"].contains(&v.as_str()))
            .con("veredicto", r.valor("veredicto").clone())
            .con("etiqueta", r.valor("etiqueta").clone())
            .con("tok_s", r.mapa("estimacion").map(|e| e.valor("tok_s").clone()).unwrap_or(Valor::Nulo))
            .con("motivo", r.valor("motivo").clone())
            .con("estimado", f.verdad("estimada"))
    }
}

/// `{**a, **b}`: lo de `b` encima (lo que ya estaba conserva su sitio)
fn fusionar(a: &mut Mapa, b: Mapa) {
    for (k, v) in b.iter() {
        a.poner(k.clone(), v.clone());
    }
}

/// `GET /api/flujos/catalogo`: modelos (cruzados con los descargados), roles y variables
pub async fn catalogo(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || {
        let inst = instalados(&raiz);
        let tamanos: HashMap<String, Valor> = inst.iter().cloned().collect();
        let nombres: Vec<String> = inst.iter().map(|(n, _)| n.clone()).collect();
        let tiene = |n: &str| nombres.iter().any(|x| x == n);
        let version = prig_ia::ollama::version_texto(&raiz);
        let veredicto = Veredictos::new(&raiz);
        let mut catalogo: Vec<Mapa> = Vec::new();
        let embedding = fm::modelos_embedding().iter().map(|(k, v)| match v {
            Valor::Mapa(m) => (k.clone(), Valor::Mapa(m.clone().con("embedding", true))),
            otro => (k.clone(), otro.clone()),
        });
        let todos: Vec<(String, Valor)> = fm::modelos().iter().map(|(k, v)| (k.clone(), v.clone())).chain(embedding).collect();
        for (nombre, info) in &todos {
            let Valor::Mapa(info) = info else { continue };
            let latest = format!("{nombre}:latest");
            let vram = [tamanos.get(nombre.as_str()), tamanos.get(latest.as_str())]
                .into_iter()
                .flatten()
                .find(|v| v.verdad())
                .cloned()
                .unwrap_or_else(|| info.valor("vram_gb").clone());
            let instalado = tiene(nombre) || tiene(&latest);
            let minima = fm::ollama_necesario(nombre);
            let bloqueado = minima.as_ref().is_some_and(|m| !fm::version_suficiente(&version, m));
            let mut m = info.clone();
            m.poner("modelo", nombre.as_str());
            m.poner("vram_gb", redondear_1(&vram));
            m.poner("instalado", instalado);
            let para = if !instalado || tiene(nombre) { nombre.clone() } else { latest.clone() };
            fusionar(&mut m, veredicto.calcular(&para, info));
            m.poner("piensa", info.get("piensa").cloned().unwrap_or_else(|| t("no")));
            m.poner("ollama_minimo", minima.map(Valor::Texto).unwrap_or(Valor::Nulo));
            m.poner("necesita_actualizar", bloqueado);
            catalogo.push(m);
        }
        let mut del_catalogo: Vec<String> = todos.iter().map(|(k, _)| k.clone()).collect();
        del_catalogo.extend(todos.iter().map(|(k, _)| format!("{k}:latest")));
        let mut fuera: Vec<&String> = nombres.iter().filter(|n| !del_catalogo.contains(n)).collect();
        fuera.sort();
        fuera.dedup();
        for nombre in fuera {
            let vram = tamanos.get(nombre).cloned().unwrap_or(Valor::Entero(0));
            let v = veredicto.calcular(nombre, &Mapa::new().con("vram_gb", vram.clone()));
            let motivo = v.get("motivo").map(Valor::texto_py).unwrap_or_default();
            let mut m = Mapa::new().con("modelo", nombre.as_str()).con("instalado", true);
            fusionar(&mut m, v);
            m.poner("vram_gb", redondear_1(&vram));
            m.poner("familia", "otro");
            m.poner("razona", 0);
            m.poner("fuerte_en", Valor::Lista(Vec::new()));
            m.poner("nota", format!("No está en el catálogo de Prig. {motivo}"));
            catalogo.push(m);
        }
        catalogo.sort_by(|a, b| {
            let clave = |m: &Mapa| (m.verdad("embedding"), m.verdad("necesita_actualizar"), !m.verdad("instalado"), !m.verdad("cabe"));
            clave(a).cmp(&clave(b)).then_with(|| {
                let r = |m: &Mapa| -m.num_o("razona", 0.0);
                r(a).partial_cmp(&r(b)).unwrap_or(std::cmp::Ordering::Equal)
            })
        });
        let mut bloqueados: Vec<String> = catalogo
            .iter()
            .filter(|m| m.verdad("necesita_actualizar"))
            .map(|m| m.valor("modelo").texto_py().split(':').next().unwrap_or("").to_string())
            .collect();
        bloqueados.sort();
        bloqueados.dedup();
        let roles: Vec<Valor> = fm::roles()
            .iter()
            .map(|(k, v)| {
                let v = match v {
                    Valor::Mapa(v) => v.clone(),
                    _ => Mapa::new(),
                };
                let mut r = Mapa::new().con("id", k.as_str());
                for x in ["nombre", "icono", "formato", "temperatura", "ayuda"] {
                    r.poner(x, v.valor(x).clone());
                }
                Valor::Mapa(r)
            })
            .collect();
        json_py(
            StatusCode::OK,
            &Valor::Mapa(
                Mapa::new()
                    .con("ollama", version)
                    .con("ollama_bloquea", Valor::Lista(bloqueados.into_iter().map(Valor::Texto).collect()))
                    .con("modelos", Valor::Lista(catalogo.into_iter().map(Valor::Mapa).collect()))
                    .con("roles", Valor::Lista(roles))
                    .con("variables", fm::variables().clone())
                    .con("variables_libro", fm::variables_libro().clone())
                    .con("vram_gb", fm::vram_tipica())
                    .con("max_pasos", fm::MAX_PASOS),
            ),
        )
    })
    .await
}

/// `_explicar_fallo`: el error de Ollama, con algo que hacer
fn explicar_fallo(raiz: &Path, mensaje: &str, modelo: &str) -> String {
    if let Some(m) = gestor::explicar_error_motor(mensaje) {
        return m.to_string();
    }
    let bajo = mensaje.to_lowercase();
    if mensaje.contains("412") || bajo.contains("newer version") {
        return format!(
            "Tu Ollama ({}) es anterior a '{modelo}' y no puede descargarlo. Actualízalo y vuelve a intentarlo:\n    curl -fsSL \
             https://ollama.com/install.sh | sh\nEn Linux eso conserva los modelos que ya tienes.",
            prig_ia::ollama::version_texto(raiz)
        );
    }
    if bajo.contains("no space") || bajo.contains("espacio") {
        return format!("No hay espacio en disco para '{modelo}'. {mensaje}");
    }
    if bajo.contains("connection") || bajo.contains("refused") {
        return "Ollama no responde. Arráncalo con 'ollama serve' y reinténtalo.".into();
    }
    mensaje.to_string()
}

/// `POST /api/flujos/descargar` (`modelo`): descarga un modelo desde el panel de flujos
pub async fn descargar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("modelo", &Tipo::Texto, true)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let modelo = c.valor("modelo").texto_py();
    let raiz = state.base_dir.clone();
    let comprobado = {
        let (raiz, modelo) = (raiz.clone(), modelo.clone());
        tokio::task::spawn_blocking(move || -> Result<(), String> {
            prig_ia::ollama::asegurar(&raiz, false);
            let version = prig_ia::ollama::version_texto(&raiz);
            if let Some(minima) = fm::ollama_necesario(&modelo).filter(|m| !fm::version_suficiente(&version, m)) {
                return Err(format!(
                    "'{modelo}' necesita Ollama {minima} o posterior y tienes la {version}. Actualiza con:  curl -fsSL \
                     https://ollama.com/install.sh | sh"
                ));
            }
            let mut conocidos: Vec<String> = fm::modelos().claves().chain(fm::modelos_embedding().claves()).cloned().collect();
            let con_latest: Vec<String> = conocidos.iter().map(|n| format!("{n}:latest")).collect();
            conocidos.extend(con_latest);
            let sin_latest: Vec<String> = conocidos.iter().map(|n| n.replace(":latest", "")).collect();
            conocidos.extend(sin_latest);
            static FORMATO: std::sync::LazyLock<regex::Regex> =
                std::sync::LazyLock::new(|| regex::Regex::new(r"^[a-zA-Z0-9_\.\-]+(/[a-zA-Z0-9_\.\-]+)?(:[a-zA-Z0-9_\.\-]+)?\n?$").unwrap());
            if !conocidos.contains(&modelo) && !FORMATO.is_match(&modelo) {
                return Err(format!("'{modelo}' no tiene un formato de modelo válido de Ollama."));
            }
            Ok(())
        })
        .await
    };
    match comprobado {
        Ok(Ok(())) => {}
        Ok(Err(e)) => return detalle(StatusCode::BAD_REQUEST, e),
        Err(_) => return error_500(),
    }
    let info = fm::modelos().mapa(&modelo).or_else(|| fm::modelos_embedding().mapa(&modelo)).cloned().unwrap_or_default();
    flujo_con_tipo("application/x-ndjson", move |cancelar, enviar| {
        enviar(linea(
            Mapa::new()
                .con("tipo", "inicio")
                .con("modelo", modelo.as_str())
                .con("gb", info.valor("vram_gb").clone())
                .con("ollama", prig_ia::ollama::version_texto(&raiz)),
        ));
        let mut fallo: Option<String> = None;
        prig_ia::ollama::descargar_modelo(&raiz, &modelo, &mut |l: String| {
            if cancelar.puesto() {
                return false;
            }
            let texto = py::strip(&l).to_string();
            if texto.to_lowercase().starts_with("error") {
                fallo = Some(texto);
                return false;
            }
            enviar(linea(Mapa::new().con("tipo", "avance").con("texto", texto)));
            true
        });
        if let Some(f) = fallo {
            enviar(linea(Mapa::new().con("tipo", "error").con("mensaje", explicar_fallo(&raiz, &f, &modelo))));
            return;
        }
        let inst: Vec<String> = instalados(&raiz).into_iter().map(|(n, _)| n).collect();
        if !inst.contains(&modelo) && !inst.contains(&format!("{modelo}:latest")) {
            enviar(linea(Mapa::new().con("tipo", "error").con(
                "mensaje",
                format!("La descarga terminó pero '{modelo}' no aparece instalado. Inténtalo de nuevo."),
            )));
            return;
        }
        enviar(linea_ascii(Mapa::new().con("tipo", "fin").con("modelo", modelo.as_str())));
    })
}

// =========================================================================== las rutas del almacén

/// `GET /api/flujos`: los guardados y las plantillas
pub async fn listar_ruta(State(state): State<AppState>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    let raiz = state.base_dir.clone();
    bloque(move || {
        let guardados = listar(&espacio);
        let sugerido = t(&modelo_que_razona(&raiz));
        let base = modelo_base();
        let v1 = fm::plantillas(&base, &sugerido);
        let v2 = fm::plantillas_v2(&base, &sugerido);
        let todas: Vec<Valor> = v2.iter().cloned().chain(v1).collect();
        json_py(
            StatusCode::OK,
            &Valor::Mapa(
                Mapa::new()
                    .con("flujos", Valor::Lista(guardados))
                    .con("plantillas", Valor::Lista(todas))
                    .con("plantillas_sota", Valor::Lista(v2))
                    .con("modelo_base", base)
                    .con("modelo_razona", sugerido),
            ),
        )
    })
    .await
}

/// `GET /api/flujos/v2/plantillas`
pub async fn plantillas_v2(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || {
        let sugerido = t(&modelo_que_razona(&raiz));
        let base = modelo_base();
        json_py(
            StatusCode::OK,
            &Valor::Mapa(
                Mapa::new()
                    .con("plantillas", Valor::Lista(fm::plantillas_v2(&base, &sugerido)))
                    .con("roles", fm::roles_v2().clone())
                    .con("modelo_base", base)
                    .con("modelo_razona", sugerido),
            ),
        )
    })
    .await
}

/// `FlujoGuardar(...).model_dump()`
fn flujo_guardar(b: &Bytes) -> Result<Mapa, Response> {
    let c = cuerpo::modelo(b).and_then(|m| {
        cuerpo::tipados(
            &m,
            &[("id", &TEXTO_OPC, false), ("nombre", &Tipo::Texto, true), ("descripcion", &Tipo::Texto, false), ("ambito", &Tipo::Texto, false), ("pasos", &LISTA_DICTS, false)],
        )
    })?;
    Ok(Mapa::new()
        .con("id", c.valor("id").clone())
        .con("nombre", c.valor("nombre").clone())
        .con("descripcion", c.get("descripcion").cloned().unwrap_or_else(|| t("")))
        .con("ambito", c.get("ambito").cloned().unwrap_or_else(|| t("libre")))
        .con("pasos", c.get("pasos").cloned().unwrap_or(Valor::Lista(Vec::new()))))
}

fn textos(v: Vec<String>) -> Valor {
    Valor::Lista(v.into_iter().map(Valor::Texto).collect())
}

/// `POST /api/flujos/validar`: los problemas y el plan de cargas
pub async fn validar(b: Bytes) -> Response {
    let flujo = match flujo_guardar(&b) {
        Ok(f) => f,
        Err(r) => return r,
    };
    json_py(
        StatusCode::OK,
        &Valor::Mapa(Mapa::new().con("problemas", textos(fm::validar_flujo(&flujo))).con("plan", fm::plan_de_modelos(&flujo))),
    )
}

/// `POST /api/flujos`: guarda un flujo válido
pub async fn guardar_ruta(State(state): State<AppState>, b: Bytes) -> Response {
    let flujo = match flujo_guardar(&b) {
        Ok(f) => f,
        Err(r) => return r,
    };
    let problemas = fm::validar_flujo(&flujo);
    if !problemas.is_empty() {
        return detalle(StatusCode::BAD_REQUEST, problemas.join("; "));
    }
    let espacio = espacio_de_trabajo(&state).await;
    bloque(move || match guardar(&espacio, flujo) {
        Ok(f) => json_py(StatusCode::OK, &Valor::Mapa(f)),
        Err(_) => error_500(),
    })
    .await
}

/// `DELETE /api/flujos/{flujo_id}`
pub async fn borrar_ruta(State(state): State<AppState>, Ruta(id): Ruta<String>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    bloque(move || match borrar(&espacio, &id) {
        Ok(true) => json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("borrado", id))),
        Ok(false) => detalle(StatusCode::NOT_FOUND, "Ese flujo no existe"),
        Err(_) => error_500(),
    })
    .await
}

/// `GET /api/flujos/historial?flujo_id=&limite=20`: sin los prompts (solo cuántos pasos)
pub async fn historial(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let limite = match cuerpo::entero_consulta(&q, "limite", 20, i64::MIN, i64::MAX) {
        Ok(n) => n,
        Err(r) => return r,
    };
    let flujo_id = q.get("flujo_id").cloned().unwrap_or_default();
    let espacio = espacio_de_trabajo(&state).await;
    bloque(move || {
        let filas: Vec<Valor> = historial_guardado(&espacio)
            .into_iter()
            .filter(|h| flujo_id.is_empty() || matches!(h, Valor::Mapa(h) if *h.valor("flujo_id") == Valor::Texto(flujo_id.clone())))
            .collect();
        let resumen: Vec<Valor> = rebanada(&filas, limite)
            .into_iter()
            .map(|h| {
                let Valor::Mapa(h) = h else { return h };
                let n = match h.get("pasos") {
                    Some(Valor::Lista(l)) => l.len(),
                    Some(Valor::Mapa(m)) => m.len(),
                    Some(Valor::Texto(t)) => t.chars().count(),
                    _ => 0,
                };
                let mut r = Mapa::new();
                for (k, v) in h.iter().filter(|(k, _)| *k != "pasos") {
                    r.poner(k.clone(), v.clone());
                }
                Valor::Mapa(r.con("n_pasos", n))
            })
            .collect();
        json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("ejecuciones", Valor::Lista(resumen))))
    })
    .await
}

/// `GET /api/flujos/ejecucion/{eid}`: una ejecución con el prompt exacto de cada paso
pub async fn ejecucion(State(state): State<AppState>, Ruta(eid): Ruta<String>) -> Response {
    let espacio = espacio_de_trabajo(&state).await;
    bloque(move || {
        let e = historial_guardado(&espacio).into_iter().find(|h| matches!(h, Valor::Mapa(h) if *h.valor("id") == Valor::Texto(eid.clone())));
        match e {
            Some(e) => json_py(StatusCode::OK, &e),
            None => detalle(StatusCode::NOT_FOUND, "Esa ejecución ya no está guardada"),
        }
    })
    .await
}

// =========================================================================== ejecutar

/// `POST /api/flujos/ejecutar`: los eventos del flujo (un grafo v2 o un flujo clásico) en NDJSON
pub async fn ejecutar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(
            &m,
            &[
                ("flujo", &DICT_OPC, false),
                ("flujo_id", &TEXTO_OPC, false),
                ("entrada", &Tipo::Texto, false),
                ("consulta_contexto", &Tipo::Texto, false),
                ("guardar_historial", &Tipo::Booleano, false),
            ],
        )
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let espacio = espacio_de_trabajo(&state).await;
    let flujo = match c.get("flujo") {
        Some(Valor::Mapa(f)) if !f.is_empty() => Some(f.clone()),
        _ => {
            let (e, id) = (espacio.clone(), c.get("flujo_id").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default());
            tokio::task::spawn_blocking(move || obtener(&e, &id)).await.ok().flatten()
        }
    };
    let Some(flujo) = flujo else { return detalle(StatusCode::NOT_FOUND, "No se encontró el flujo") };
    let entrada = c.get("entrada").map(Valor::texto_py).unwrap_or_default();
    let consulta = c.get("consulta_contexto").map(Valor::texto_py).unwrap_or_default();
    let guardar_historial = c.get("guardar_historial").is_none_or(Valor::verdad);
    let es_v2 = flujo.verdad("nodos")
        || flujo.verdad("nodo_inicial")
        || flujo.verdad("es_v2")
        || flujo.get("id").map(Valor::texto_py).unwrap_or_default().starts_with("sota_");
    let raiz = state.base_dir.clone();
    let python = state.ejecutor.python.clone();
    flujo_con_tipo("application/x-ndjson", move |cancelar, enviar| {
        let ej = Ejecucion { raiz: &raiz, num_ctx: fm::num_ctx(if es_v2 { 8192 } else { 4096 }), cancelar };
        if es_v2 {
            if let Err(e) = ej.ejecutar_grafo(&flujo, &entrada, &python, &mut |ev| enviar(linea(ev))) {
                enviar(linea(Mapa::new().con("tipo", "error").con("mensaje", e)));
            }
            return;
        }
        let (mut registro, mut segundos) = (Valor::Lista(Vec::new()), Valor::Real(0.0));
        let r = ej.ejecutar(&flujo, &entrada, &consulta, None, &mut |mut ev| {
            if ev.texto("tipo") == Some("fin") {
                registro = ev.quitar("registro").unwrap_or(Valor::Lista(Vec::new()));
                segundos = ev.get("segundos").cloned().unwrap_or(Valor::Entero(0));
            }
            enviar(linea(ev));
        });
        if let Err(e) = r {
            enviar(linea(Mapa::new().con("tipo", "error").con("mensaje", e)));
            return;
        }
        if guardar_historial && registro.verdad() {
            if let Ok(eid) = anotar_ejecucion(&espacio, &flujo, &entrada, registro, segundos) {
                enviar(linea_ascii(Mapa::new().con("tipo", "guardado").con("ejecucion", eid)));
            }
        }
    })
}

/// `POST /api/libros/ficha` (`source_id`, `flujo`, `flujo_id`): corre el flujo sobre un libro y guarda la ficha
pub async fn ficha_libro(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b)
        .and_then(|m| cuerpo::tipados(&m, &[("source_id", &Tipo::Texto, true), ("flujo", &DICT_OPC, false), ("flujo_id", &TEXTO_OPC, false)]))
    {
        Ok(c) => c,
        Err(r) => return r,
    };
    let sid = c.valor("source_id").texto_py();
    let variables = {
        let sid = sid.clone();
        tokio::task::spawn_blocking(move || prig_biblioteca::base_kb::BaseKb::por_defecto().and_then(|kb| prig_biblioteca::perfil::variables(&kb, &sid))).await
    };
    let variables = match variables {
        Ok(Ok(Some(v))) if !v.is_empty() => v,
        Ok(Ok(_)) => return detalle(StatusCode::NOT_FOUND, "Ese libro no está importado en la base de conocimiento"),
        _ => return error_500(),
    };
    let espacio = espacio_de_trabajo(&state).await;
    let raiz = state.base_dir.clone();
    let flujo = match c.get("flujo") {
        Some(Valor::Mapa(f)) if !f.is_empty() => Some(f.clone()),
        _ => {
            let (e, id) = (espacio.clone(), c.get("flujo_id").filter(|v| v.verdad()).map(Valor::texto_py).unwrap_or_default());
            tokio::task::spawn_blocking(move || obtener(&e, &id)).await.ok().flatten()
        }
    };
    flujo_con_tipo("application/x-ndjson", move |cancelar, enviar| {
        let flujo = flujo.unwrap_or_else(|| {
            let razona = t(&modelo_que_razona(&raiz));
            fm::plantillas(&modelo_base(), &razona)
                .into_iter()
                .find_map(|p| match p {
                    Valor::Mapa(p) if p.texto("id") == Some("plantilla_ficha_libro") => Some(p),
                    _ => None,
                })
                .unwrap_or_default()
        });
        let titulo = variables.get("libro:titulo").map(Valor::texto_py).unwrap_or_else(|| sid.clone());
        let ej = Ejecucion { raiz: &raiz, num_ctx: fm::num_ctx(4096), cancelar };
        let mut fin: Option<Mapa> = None;
        let r = ej.ejecutar(&flujo, &titulo, &titulo, Some(&variables), &mut |mut ev| {
            if ev.texto("tipo") == Some("fin") {
                let mut f = ev.clone();
                f.poner("registro", ev.quitar("registro").unwrap_or(Valor::Lista(Vec::new())));
                fin = Some(f);
            }
            enviar(linea(ev));
        });
        if let Err(e) = r {
            enviar(linea(Mapa::new().con("tipo", "error").con("mensaje", e)));
            return;
        }
        let fin = fin.unwrap_or_default();
        let salidas = fin.mapa("salidas").cloned().unwrap_or_default();
        let datos = fin.mapa("datos").cloned().unwrap_or_default();
        let mut piezas = Mapa::new();
        for (pid, s) in salidas.iter() {
            piezas.poner(pid.clone(), datos.get(pid).cloned().unwrap_or_else(|| s.clone()));
        }
        let modelos = fin.lista("modelos").unwrap_or(&[]).to_vec();
        let Ok(kb) = prig_biblioteca::base_kb::BaseKb::por_defecto() else { return };
        let Ok(ficha) = prig_biblioteca::perfil::montar_ficha(&kb, &sid, &piezas, &modelos) else { return };
        if prig_biblioteca::perfil::guardar(&kb, &sid, &ficha).is_err() {
            return;
        }
        let registro = fin.get("registro").cloned().unwrap_or(Valor::Lista(Vec::new()));
        if registro.verdad() {
            let segundos = fin.get("segundos").cloned().unwrap_or(Valor::Entero(0));
            let _ = anotar_ejecucion(&espacio, &flujo, &format!("ficha de {titulo}"), registro, segundos);
        }
        enviar(linea(Mapa::new().con("tipo", "ficha").con("ficha", ficha)));
    })
}

// =========================================================================== el workflow del editor

const fn campo(nombre: &'static str, tipo: Tipo, defecto: Defecto) -> Campo {
    Campo { nombre, tipo, defecto }
}

/// `WorkflowStep`
static PASO_WORKFLOW: Modelo = Modelo {
    nombre: "WorkflowStep",
    campos: &[
        campo("id", TEXTO_OPC, Defecto::Valor(|| Valor::Nulo)),
        campo("name", TEXTO_OPC, Defecto::Valor(|| t("Agente"))),
        campo("model", Tipo::Texto, Defecto::Valor(|| t("qwen2.5-coder:7b"))),
        campo("role", Tipo::Texto, Defecto::Valor(|| t("programmer"))),
        campo("prompt", Tipo::Texto, Defecto::Valor(|| t(""))),
        campo("temperature", Tipo::Opcional(&Tipo::Real), Defecto::Valor(|| Valor::Real(0.3))),
        campo("system_prompt", TEXTO_OPC, Defecto::Valor(|| t(""))),
        campo("tipo", TEXTO_OPC, Defecto::Valor(|| t("agent"))),
        campo("loop", DICT_OPC, Defecto::Valor(|| Valor::Nulo)),
        campo("routing_rules", Tipo::Opcional(&LISTA_DICTS), Defecto::Valor(|| Valor::Nulo)),
        campo("herramienta", TEXTO_OPC, Defecto::Valor(|| Valor::Nulo)),
        campo("next_node", TEXTO_OPC, Defecto::Valor(|| Valor::Nulo)),
    ],
    antes: None,
};

const PASOS_WORKFLOW: Tipo = Tipo::Opcional(&Tipo::Lista(&Tipo::Modelo(&PASO_WORKFLOW)));

/// `run_workflow_step`: el texto completo del agente
fn paso_workflow(raiz: &Path, cancelar: &prig_ia::vivo::Cancelar, prompt: &str, paso: &Mapa) -> String {
    let propio = match paso.get("system_prompt") {
        Some(s) if s.verdad() => py::strip(&s.texto_py()).to_string(),
        _ => String::new(),
    };
    let sistema = if !propio.is_empty() {
        propio
    } else {
        let r = fm::roles_workflow();
        paso.get("role").and_then(|x| r.get(&x.texto_py())).unwrap_or_else(|| r.valor("programmer")).texto_py()
    };
    let p = prig_ia::generar::PedidoGenerar {
        prompt: prompt.to_string(),
        modelo: paso.valor("model").texto_py(),
        sistema,
        opciones: Some(Mapa::new().con("temperature", paso.valor("temperature").clone())),
        gobernador: true,
        ..Default::default()
    };
    let mut partes = String::new();
    prig_ia::generar::generar(raiz, &p, cancelar, &mut |e: Mapa| {
        if e.texto("t") == Some("texto") {
            partes.push_str(&e.valor("v").texto_py());
        }
    });
    py::strip(&partes).to_string()
}

/// `POST /api/ai/workflow/run`: un grafo v2 (si hay bucles, herramientas, routers o nodos) o los pasos en cadena
pub async fn workflow(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match cuerpo::modelo(&b).and_then(|m| {
        cuerpo::tipados(
            &m,
            &[
                ("initial_input", &Tipo::Texto, true),
                ("steps", &PASOS_WORKFLOW, false),
                ("nodos", &Tipo::Opcional(&LISTA_DICTS), false),
                ("grafo", &DICT_OPC, false),
            ],
        )
    }) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let entrada = c.valor("initial_input").texto_py();
    let pasos: Vec<Mapa> = match c.get("steps") {
        Some(Valor::Lista(l)) => l.iter().filter_map(|p| if let Valor::Mapa(p) = p { Some(p.clone()) } else { None }).collect(),
        _ => Vec::new(),
    };
    let grafo = c.get("grafo").filter(|g| g.verdad()).cloned();
    let nodos = c.get("nodos").filter(|n| n.verdad()).cloned();
    let es_v2 = grafo.is_some()
        || nodos.is_some()
        || pasos.iter().any(|s| s.verdad("loop") || (s.verdad("tipo") && s.texto("tipo") != Some("agent")) || s.verdad("herramienta"));
    let raiz = state.base_dir.clone();
    let python = state.ejecutor.python.clone();
    flujo_con_tipo("application/x-ndjson", move |cancelar, enviar| {
        if es_v2 {
            let grafo = match (grafo, nodos) {
                (Some(Valor::Mapa(g)), _) => g,
                (_, Some(Valor::Lista(n))) => {
                    let inicial = match n.first() {
                        Some(Valor::Mapa(p)) => p.get("id").cloned().unwrap_or_else(|| t("step_1")),
                        _ => return,
                    };
                    Mapa::new().con("nodos", Valor::Lista(n)).con("nodo_inicial", inicial)
                }
                _ => {
                    let total = pasos.len();
                    let nodos: Vec<Valor> = pasos
                        .iter()
                        .enumerate()
                        .map(|(i, s)| {
                            let sid = if s.verdad("id") { s.valor("id").clone() } else { Valor::Texto(format!("step_{}", i + 1)) };
                            let siguiente = if s.verdad("next_node") {
                                s.valor("next_node").clone()
                            } else if i + 1 < total {
                                Valor::Texto(format!("step_{}", i + 2))
                            } else {
                                Valor::Nulo
                            };
                            let o = |k: &str, d: Valor| if s.verdad(k) { s.valor(k).clone() } else { d };
                            Valor::Mapa(
                                Mapa::new()
                                    .con("id", sid)
                                    .con("nombre", o("name", Valor::Texto(format!("Agente {}", i + 1))))
                                    .con("tipo", o("tipo", t("agent")))
                                    .con("rol", o("role", t("programmer")))
                                    .con("modelo", s.valor("model").clone())
                                    .con("prompt", s.valor("prompt").clone())
                                    .con("temperature", s.valor("temperature").clone())
                                    .con("system_prompt", s.valor("system_prompt").clone())
                                    .con("loop", s.valor("loop").clone())
                                    .con("routing_rules", s.valor("routing_rules").clone())
                                    .con("herramienta", s.valor("herramienta").clone())
                                    .con("next_node", siguiente),
                            )
                        })
                        .collect();
                    let inicial = match nodos.first() {
                        Some(Valor::Mapa(n)) => n.valor("id").clone(),
                        _ => Valor::Nulo,
                    };
                    Mapa::new().con("nodos", Valor::Lista(nodos)).con("nodo_inicial", inicial)
                }
            };
            let ej = Ejecucion { raiz: &raiz, num_ctx: fm::num_ctx(8192), cancelar };
            // en Python, lo que fallaba aquí cortaba la respuesta a medias
            let _ = ej.ejecutar_grafo(&grafo, &entrada, &python, &mut |ev| enviar(linea(ev)));
            return;
        }
        let mut contexto = entrada.clone();
        for (i, s) in pasos.iter().enumerate() {
            enviar(linea_ascii(
                Mapa::new().con("step", i).con("status", "running").con("model", s.valor("model").clone()).con("name", s.valor("name").clone()),
            ));
            let prompt = format!("{}\n\nContexto / Input Anterior:\n{contexto}", s.valor("prompt").texto_py());
            contexto = paso_workflow(&raiz, cancelar, &prompt, s);
            enviar(linea_ascii(
                Mapa::new()
                    .con("step", i)
                    .con("status", "completed")
                    .con("result", contexto.as_str())
                    .con("name", s.valor("name").clone()),
            ));
        }
        enviar(linea_ascii(Mapa::new().con("status", "finished").con("final_result", contexto)));
    })
}
