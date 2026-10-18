//! Ollama y la configuración de IA (`prig_ia::ollama`, `prig_ia::motor::config_ia`): estado, recargar, la lista de
//! modelos, borrar y descargar modelos, la configuración; y lo que pide el backend de Python mientras conviven
//! (`/api/ollama/asegurar` y `/api/ollama/detener`: el `ollama serve` que arranca Prig es de este servidor).

#![allow(clippy::result_large_err)]

use axum::{
    body::{Body, Bytes},
    extract::State,
    http::{header, StatusCode},
    response::{IntoResponse, Response},
};
use prig_ia::{motor, ollama};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::{cuerpo, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

async fn bloque<F: FnOnce() -> Mapa + Send + 'static>(f: F) -> Response {
    match tokio::task::spawn_blocking(f).await {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(_) => error_500(),
    }
}

/// `GET /api/ai/status`
pub async fn estado(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || ollama::estado(&raiz)).await
}

/// `GET/POST /api/ai/reload`: reinicia Ollama y da su estado
pub async fn recargar(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || {
        ollama::asegurar(&raiz, true);
        ollama::estado(&raiz)
    })
    .await
}

/// `GET /api/ai/models`
pub async fn modelos(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || Mapa::new().con("models", ollama::estado(&raiz).get("models").cloned().unwrap_or(Valor::Lista(vec![])))).await
}

/// `GET /api/ai/models/detailed`
pub async fn modelos_detallados(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || ollama::modelos_detallados(&raiz)).await
}

/// `POST /api/ai/models/delete` (`model`)
pub async fn borrar_modelo(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let modelo = c.texto("model", None).texto_py();
    if let Err(r) = c.fin() {
        return r;
    }
    bloque(move || {
        let ok = ollama::borrar_modelo(&modelo);
        Mapa::new().con("status", if ok { "success" } else { "error" }).con("model", modelo)
    })
    .await
}

/// `POST /api/ai/pull` (`model`): el progreso en texto, línea a línea
pub async fn descargar_modelo(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let mut c = cuerpo::Campos::new(&m);
    let modelo = c.texto("model", Some(Valor::Texto("qwen2.5-coder:7b".into())));
    if let Err(r) = c.fin() {
        return r;
    }
    let modelo = if modelo.es_nulo() { "qwen2.5-coder:7b".to_string() } else { modelo.texto_py() };
    let raiz = state.base_dir.clone();
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(64);
    std::thread::spawn(move || {
        let mut enviar = |t: String| tx.blocking_send(Ok(Bytes::from(t))).is_ok();
        ollama::descargar_modelo(&raiz, &modelo, &mut enviar);
    });
    let flujo = futures_util::stream::unfold(rx, |mut rx| async move { rx.recv().await.map(|x| (x, rx)) });
    ([(header::CONTENT_TYPE, "text/plain; charset=utf-8")], Body::from_stream(flujo)).into_response()
}

/// `GET /api/ai/config`
pub async fn config() -> Response {
    bloque(motor::config_ia).await
}

const STR: Tipo = Tipo::Opcional(&Tipo::Texto);
const REAL: Tipo = Tipo::Opcional(&Tipo::Real);
const ENTERO: Tipo = Tipo::Opcional(&Tipo::Entero);
const BOOL: Tipo = Tipo::Opcional(&Tipo::Booleano);

/// Los campos de `AIConfigUpdateRequest`
const CAMPOS: [(&str, &Tipo); 22] = [
    ("ollama_url", &STR),
    ("agent1_model", &STR),
    ("agent2_model", &STR),
    ("agent3_model", &STR),
    ("designer_model", &STR),
    ("modelo_codigo", &STR),
    ("modelo_explicar", &STR),
    ("modelo_autocompletar", &STR),
    ("depth_level", &STR),
    ("temperature", &REAL),
    ("num_ctx", &ENTERO),
    ("num_gpu", &ENTERO),
    ("num_thread", &ENTERO),
    ("num_predict", &ENTERO),
    ("low_vram", &BOOL),
    ("f16_kv", &BOOL),
    ("muestreo_del_modelo", &BOOL),
    ("keep_alive", &STR),
    ("top_k", &ENTERO),
    ("top_p", &REAL),
    ("repeat_penalty", &REAL),
    ("exec_timeout", &ENTERO),
];

/// `POST /api/ai/config`: solo lo enviado (`exclude_unset`), con los tipos de pydantic
pub async fn guardar_config(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let campos: Vec<(&str, &Tipo, bool)> = CAMPOS.iter().map(|(k, t)| (*k, *t, false)).collect();
    let cambios = match cuerpo::tipados(&m, &campos) {
        Ok(c) => c,
        Err(r) => return r,
    };
    match tokio::task::spawn_blocking(move || motor::guardar_config_ia(&cambios)).await {
        Ok(Ok(c)) => json_py(StatusCode::OK, &Valor::Mapa(c)),
        _ => error_500(),
    }
}

/// `POST /api/ollama/asegurar` (`forzar`): para el backend de Python (arrancar Ollama si hace falta)
pub async fn asegurar(State(state): State<AppState>, b: Bytes) -> Response {
    let forzar = match prig_plataforma::json::leer(&String::from_utf8_lossy(&b)) {
        Ok(Valor::Mapa(m)) => m.verdad("forzar"),
        _ => false,
    };
    let raiz = state.base_dir.clone();
    bloque(move || Mapa::new().con("ok", ollama::asegurar(&raiz, forzar))).await
}

/// `POST /api/ollama/detener`: para el `ollama serve` que arrancó Prig
pub async fn detener() -> Response {
    bloque(|| {
        ollama::detener_propio();
        Mapa::new().con("ok", true)
    })
    .await
}

// =========================================================================== generar (para el backend de Python)

use prig_ia::generar::{self, Herramientas, PedidoChat, PedidoGenerar, PedidoPausas};
use prig_ia::vivo::Cancelar;
use std::sync::Arc;

fn texto_de(m: &Mapa, k: &str) -> String {
    m.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py).unwrap_or_default()
}

fn opcional_texto(m: &Mapa, k: &str) -> Option<String> {
    m.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py)
}

fn opcional_bool(m: &Mapa, k: &str) -> Option<bool> {
    m.get(k).filter(|v| !v.es_nulo()).map(Valor::verdad)
}

/// Un flujo NDJSON de eventos que produce `trabajo` en su hilo. Si quien pregunta cierra la conexión (Detener, se
/// fue), se cancela en el acto, también en mitad de una pausa térmica.
fn flujo_de_eventos<F>(trabajo: F) -> Response
where
    F: FnOnce(&Cancelar, &mut dyn FnMut(Mapa)) + Send + 'static,
{
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(256);
    let cancelar = Arc::new(Cancelar::default());
    // Al soltar el cuerpo (terminó, o quien preguntó se fue) se cancela: así también se despierta una pausa térmica
    struct AlSoltar(Arc<Cancelar>);
    impl Drop for AlSoltar {
        fn drop(&mut self) {
            self.0.poner();
        }
    }
    let guarda = AlSoltar(cancelar.clone());
    crate::routes::asistente::apuntar(&cancelar);
    std::thread::spawn(move || {
        let mut emitir = |e: Mapa| {
            let linea = prig_plataforma::json::escribir_compacto(&Valor::Mapa(e)) + "\n";
            if tx.blocking_send(Ok(Bytes::from(linea))).is_err() {
                cancelar.poner();
            }
        };
        trabajo(&cancelar, &mut emitir);
    });
    let flujo = futures_util::stream::unfold((rx, guarda), |(mut rx, g)| async move { rx.recv().await.map(|x| (x, (rx, g))) });
    ([(header::CONTENT_TYPE, "application/x-ndjson")], Body::from_stream(flujo)).into_response()
}

fn cuerpo_mapa(b: &Bytes) -> Result<Mapa, Response> {
    match prig_plataforma::json::leer(&String::from_utf8_lossy(b)) {
        Ok(Valor::Mapa(m)) => Ok(m),
        _ => Err(crate::routes::detalle(StatusCode::BAD_REQUEST, "Pedido inválido")),
    }
}

/// `POST /api/ia/generar`: `generate_response` por eventos (texto, pensando, stats)
pub async fn ia_generar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo_mapa(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let p = PedidoGenerar {
        prompt: texto_de(&m, "prompt"),
        modelo: texto_de(&m, "model"),
        sistema: texto_de(&m, "system_prompt"),
        opciones: m.mapa("options").cloned(),
        think: opcional_bool(&m, "think"),
        con_pensamiento: m.verdad("con_pensamiento"),
        uso: opcional_texto(&m, "uso"),
        gobernador: m.verdad("gobernador"),
    };
    let raiz = state.base_dir.clone();
    flujo_de_eventos(move |c, emitir| generar::generar(&raiz, &p, c, emitir))
}

/// `POST /api/ia/pausas`: `generar_con_pausas`; los avisos como `{"t": "aviso", "v": evento}` y al final
/// `{"t": "fin", "v": respuesta}` o `{"t": "error", "v": mensaje}`
pub async fn ia_pausas(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo_mapa(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let p = PedidoPausas {
        prompt: texto_de(&m, "prompt"),
        modelo: texto_de(&m, "model"),
        sistema: texto_de(&m, "system_prompt"),
        opciones: m.mapa("options").cloned(),
        think: opcional_bool(&m, "think"),
        uso: opcional_texto(&m, "uso"),
        gobernador: m.verdad("gobernador"),
    };
    let con_avisos = m.verdad("con_avisos");
    let raiz = state.base_dir.clone();
    flujo_de_eventos(move |c, emitir| {
        let r = {
            let mut avisar = |e: Mapa| emitir(Mapa::new().con("t", "aviso").con("v", e));
            let a: Option<&mut dyn FnMut(Mapa)> = if con_avisos { Some(&mut avisar) } else { None };
            generar::generar_con_pausas(&raiz, &p, c, a)
        };
        emitir(match r {
            Ok(t) => Mapa::new().con("t", "fin").con("v", t),
            Err(e) => Mapa::new().con("t", "error").con("v", e),
        });
    })
}

/// Las herramientas de un chat del backend de Python: se le pide que ejecute cada una
struct HerramientasDePython {
    fallback: String,
    sesion: String,
    definiciones: Vec<Valor>,
}

impl Herramientas for HerramientasDePython {
    fn definiciones(&mut self) -> Option<Vec<Valor>> {
        Some(self.definiciones.clone())
    }

    fn ejecutar(&mut self, nombre: &str, argumentos: &Valor) -> String {
        let cuerpo = Mapa::new().con("sesion", self.sesion.as_str()).con("nombre", nombre).con("argumentos", argumentos.clone());
        let r = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(900))
            .build()
            .and_then(|c| {
                c.post(format!("{}/api/interno/herramienta", self.fallback))
                    .header("Content-Type", "application/json")
                    .body(prig_plataforma::json::escribir_compacto(&Valor::Mapa(cuerpo)))
                    .send()
            })
            .and_then(|r| r.text());
        match r.ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
            Some(Valor::Mapa(m)) => texto_de(&m, "resultado"),
            _ => format!("No se pudo ejecutar {nombre}."),
        }
    }
}

/// `POST /api/ia/chat`: `chat_eventos` por eventos; con `herramientas` (`{sesion, definiciones}`), las ejecuta el
/// backend de Python
pub async fn ia_chat(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo_mapa(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let p = PedidoChat {
        mensajes: m.lista("mensajes").map(<[Valor]>::to_vec).unwrap_or_default(),
        modelo: texto_de(&m, "model"),
        uso: opcional_texto(&m, "uso"),
        think: opcional_bool(&m, "think"),
        logprobs: m.get("logprobs").and_then(Valor::num).unwrap_or(0.0) as i64,
        max_rondas: m.get("max_rondas").and_then(Valor::num).map(|n| n as usize).unwrap_or(6),
        gobernador: m.verdad("gobernador"),
        extra: m.mapa("extra").cloned(),
        max_tokens: m.get("max_tokens").and_then(Valor::num).map(|n| n as i64),
    };
    let herramientas = m.mapa("herramientas").map(|h| HerramientasDePython {
        fallback: state.fallback_url.clone(),
        sesion: texto_de(h, "sesion"),
        definiciones: h.lista("definiciones").map(<[Valor]>::to_vec).unwrap_or_default(),
    });
    let raiz = state.base_dir.clone();
    flujo_de_eventos(move |c, emitir| {
        let mut h = herramientas;
        generar::chat_eventos(&raiz, &p, h.as_mut().map(|h| h as &mut dyn Herramientas), c, emitir)
    })
}

/// `GET /api/ia/capacidades?modelo=`: lo que declara el modelo (completion, tools, thinking…)
pub async fn ia_capacidades(axum::extract::Query(q): axum::extract::Query<std::collections::HashMap<String, String>>) -> Response {
    let modelo = q.get("modelo").cloned().unwrap_or_default();
    bloque(move || Mapa::new().con("capacidades", Valor::Lista(generar::capacidades(&modelo).into_iter().map(Valor::from).collect()))).await
}

/// `POST /api/ia/descargar`: suelta de Ollama los modelos que usó Prig y para el motor MoE (al cerrar o liberar VRAM)
pub async fn ia_descargar(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || {
        ollama::descargar_propios(&generar::modelos_propios());
        if let Some(m) = motor::global_si_hay() {
            m.detener();
        }
        let _ = raiz;
        Mapa::new().con("ok", true)
    })
    .await
}

// =========================================================================== Gemini

use prig_ia::gemini;

fn de_gemini(r: Result<Mapa, gemini::ErrorGemini>) -> Response {
    match r {
        Ok(m) => json_py(StatusCode::OK, &Valor::Mapa(m)),
        Err(e) => crate::routes::detalle(StatusCode::BAD_REQUEST, e.0),
    }
}

/// `GET /api/gemini/estado`: nunca devuelve la clave, solo si hay una y sus 4 primeros y últimos caracteres
pub async fn gemini_estado() -> Response {
    bloque(gemini::estado).await
}

/// `POST /api/gemini/clave` (`clave`, `acepto_aviso`): se comprueba contra Google antes de guardarla
pub async fn gemini_guardar(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(&m, &[("clave", &Tipo::Texto, true), ("acepto_aviso", &Tipo::Booleano, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (clave, acepto) = (texto_de(&c, "clave"), c.verdad("acepto_aviso"));
    tokio::task::spawn_blocking(move || de_gemini(gemini::guardar_clave(&clave, acepto))).await.unwrap_or_else(|_| error_500())
}

/// `DELETE /api/gemini/clave`
pub async fn gemini_borrar() -> Response {
    bloque(gemini::borrar_clave).await
}

/// `GET /api/gemini/modelos`
pub async fn gemini_modelos() -> Response {
    tokio::task::spawn_blocking(|| de_gemini(gemini::listar_modelos(None, true).map(|l| Mapa::new().con("modelos", Valor::Lista(l)))))
        .await
        .unwrap_or_else(|_| error_500())
}

/// `POST /api/ia/gemini`: generar con Gemini por eventos (como `/api/ia/generar`)
pub async fn ia_gemini(b: Bytes) -> Response {
    let m = match cuerpo_mapa(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let (prompt, modelo, sistema, opciones) = (texto_de(&m, "prompt"), texto_de(&m, "model"), texto_de(&m, "system_prompt"), m.mapa("options").cloned());
    flujo_de_eventos(move |c, emitir| gemini::generar(&prompt, &modelo, &sistema, opciones.as_ref(), c, emitir))
}

// =========================================================================== actualizar Ollama

const COMANDO_MANUAL: &str = "curl -fsSL https://ollama.com/install.sh | sh";

/// `GET /api/ai/ollama/version-info`: la versión de Ollama de aquí y la última publicada en GitHub
pub async fn ollama_version_info(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || {
        let actual = ollama::version_texto(&raiz);
        let ultima = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .build()
            .ok()
            .and_then(|c| c.get("https://api.github.com/repos/ollama/ollama/releases/latest").header("User-Agent", "Prig-IDE").send().ok())
            .filter(|r| r.status().as_u16() == 200)
            .and_then(|r| r.text().ok())
            .and_then(|t| prig_plataforma::json::leer(&t).ok())
            .and_then(|v| match v {
                Valor::Mapa(m) => Some(m.get("tag_name").map(Valor::texto_py).unwrap_or_default().trim_start_matches('v').to_string()),
                _ => None,
            });
        let ultima = ultima.filter(|u| !u.is_empty());
        let hay = actual != "?" && ultima.as_deref().is_some_and(|u| !crate::routes::flujos_motor::version_suficiente(&actual, u));
        Mapa::new()
            .con("current_version", actual)
            .con("latest_version", ultima.unwrap_or_else(|| "desconocida".into()))
            .con("has_update", hay)
            .con("command", COMANDO_MANUAL)
    })
    .await
}

fn evento_error(mensaje: String) -> Mapa {
    Mapa::new().con("stage", "error").con("mensaje", mensaje).con("comando_manual", COMANDO_MANUAL)
}

fn evento(stage: &str, porcentaje: i64, mensaje: String) -> Mapa {
    Mapa::new().con("stage", stage).con("porcentaje", porcentaje).con("mensaje", mensaje)
}

fn mb(bytes: u64) -> String {
    let x = (bytes as f64 / (1024.0 * 1024.0) * 10.0).round() / 10.0;
    if x.fract() == 0.0 { format!("{x:.1}") } else { format!("{x}") }
}

/// Copia `de` en `a` con permisos de ejecución (`shutil.copy2` + `chmod 755`), sin quejarse
fn copiar_ejecutable(de: &std::path::Path, a: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;
    if std::fs::copy(de, a).is_ok() {
        let _ = std::fs::set_permissions(a, std::fs::Permissions::from_mode(0o755));
    }
}

/// Descarga el paquete oficial de Ollama para Linux, lo desempaqueta en la raíz de Prig y reinicia Ollama
fn actualizar_ollama(raiz: &std::path::Path, cancelar: &Cancelar, emitir: &mut dyn FnMut(Mapa)) {
    use std::io::{Read, Write};
    emitir(evento("inicio", 5, "Iniciando proceso de actualización de Ollama...".into()));
    let sistema = match std::env::consts::OS {
        "linux" => "Linux",
        "macos" => "Darwin",
        "windows" => "Windows",
        otro => otro,
    };
    if sistema != "Linux" {
        emitir(evento_error(format!("La actualización automática directa está optimizada para Linux (detectado: {sistema}).")));
        return;
    }
    let arch = match std::env::consts::ARCH {
        "x86_64" => "amd64",
        "aarch64" => "arm64",
        otro => {
            emitir(evento_error(format!("Arquitectura del procesador no soportada para descarga directa: {otro}.")));
            return;
        }
    };
    let urls = [
        format!("https://github.com/ollama/ollama/releases/latest/download/ollama-linux-{arch}.tar.zst"),
        format!("https://ollama.com/download/ollama-linux-{arch}.tar.zst"),
        format!("https://ollama.com/download/ollama-linux-{arch}.tgz"),
    ];
    emitir(evento("info", 15, format!("Conectando con servidores oficiales de Ollama (Linux {arch})...")));
    if cancelar.puesto() {
        return;
    }
    let mut temporal: Option<std::path::PathBuf> = None;
    let trabajo = |temporal: &mut Option<std::path::PathBuf>, emitir: &mut dyn FnMut(Mapa)| -> Result<(), String> {
        let cliente = reqwest::blocking::Client::builder()
            .connect_timeout(std::time::Duration::from_secs(15))
            .timeout(None)
            .build()
            .map_err(|e| e.to_string())?;
        let respuesta = urls
            .iter()
            .find_map(|u| cliente.get(u).header("User-Agent", "Prig-IDE").send().ok().filter(|r| r.status().as_u16() == 200));
        let Some(mut respuesta) = respuesta else {
            emitir(evento_error("No se pudo conectar a los servidores de descarga de Ollama. Usa el botón de terminal oficial de abajo.".into()));
            return Ok(());
        };
        let total = respuesta
            .headers()
            .get(reqwest::header::CONTENT_LENGTH)
            .and_then(|v| v.to_str().ok())
            .filter(|v| !v.is_empty() && v.chars().all(|c| c.is_ascii_digit()))
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(0);
        let sufijo = if respuesta.url().as_str().contains(".zst") { ".tar.zst" } else { ".tgz" };
        let ruta = std::env::temp_dir().join(format!("prig-ollama-{}-{}{sufijo}", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0)));
        *temporal = Some(ruta.clone());
        let mut archivo = std::fs::File::create(&ruta).map_err(|e| e.to_string())?;
        let mut bajado: u64 = 0;
        let mut ultimo = -1i64;
        let mut trozo = vec![0u8; 1024 * 256];
        loop {
            let n = respuesta.read(&mut trozo).map_err(|e| e.to_string())?;
            if n == 0 {
                break;
            }
            archivo.write_all(&trozo[..n]).map_err(|e| e.to_string())?;
            bajado += n as u64;
            if total > 0 {
                let pct = 15 + ((bajado as f64 / total as f64) * 65.0) as i64;
                if pct != ultimo && pct % 5 == 0 {
                    ultimo = pct;
                    emitir(evento("descarga", pct, format!("Descargando paquete oficial ({} MB / {} MB - {pct}%)...", mb(bajado), mb(total))));
                    if cancelar.puesto() {
                        return Ok(());
                    }
                }
            }
        }
        drop(archivo);
        emitir(evento("extraccion", 85, "Desempaquetando binarios y bibliotecas en Prig...".into()));
        let tmp = ruta.to_string_lossy().to_string();
        let destino = raiz.to_string_lossy().to_string();
        if sufijo == ".tar.zst" {
            let ok = std::process::Command::new("tar").args(["--zstd", "-xf", &tmp, "-C", &destino]).output().is_ok_and(|o| o.status.success());
            if !ok {
                let orden = format!("zstd -d -c '{tmp}' | tar -xf - -C '{destino}'");
                let estado = std::process::Command::new("sh").args(["-c", &orden]).status().map_err(|e| e.to_string())?;
                if !estado.success() {
                    return Err(format!("Command '{orden}' returned non-zero exit status {}.", estado.code().unwrap_or(-1)));
                }
            }
        } else {
            let salida = std::process::Command::new("tar").args(["-xzf", &tmp, "-C", &destino]).output().map_err(|e| e.to_string())?;
            if !salida.status.success() {
                return Err(String::from_utf8_lossy(&salida.stderr).trim().to_string());
            }
        }
        let binario = raiz.join("bin").join("ollama");
        if binario.exists() {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&binario, std::fs::Permissions::from_mode(0o755));
            let bin_bin = raiz.join("bin").join("bin");
            if bin_bin.exists() {
                copiar_ejecutable(&binario, &bin_bin.join("ollama"));
            }
        }
        if let Some(casa) = std::env::var_os("HOME") {
            let local = std::path::Path::new(&casa).join(".local").join("bin");
            if local.exists() {
                let destino = local.join("ollama");
                if destino.symlink_metadata().is_ok() {
                    let _ = std::fs::remove_file(&destino);
                }
                copiar_ejecutable(&binario, &destino);
            }
        }
        emitir(evento("reinicio", 95, "Reiniciando el servicio de Ollama...".into()));
        if cancelar.puesto() {
            return Ok(());
        }
        ollama::asegurar(raiz, true);
        std::thread::sleep(std::time::Duration::from_secs(2));
        let nueva = ollama::version_texto(raiz);
        emitir(
            Mapa::new()
                .con("stage", "fin")
                .con("porcentaje", 100)
                .con("version", nueva.clone())
                .con("mensaje", format!("¡Ollama se ha actualizado con éxito! Versión activa: {nueva}")),
        );
        Ok(())
    };
    if let Err(e) = trabajo(&mut temporal, emitir) {
        emitir(evento_error(format!("Fallo durante la actualización: {e}")));
    }
    if let Some(t) = temporal {
        let _ = std::fs::remove_file(t);
    }
}

/// `POST /api/ai/ollama/update`: NDJSON con el avance de la actualización
pub async fn ollama_actualizar(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    flujo_de_eventos(move |cancelar, emitir| actualizar_ollama(&raiz, cancelar, emitir))
}

fn en_el_path(programa: &str) -> bool {
    std::env::var_os("PATH").is_some_and(|p| {
        std::env::split_paths(&p).any(|d| {
            use std::os::unix::fs::PermissionsExt;
            std::fs::metadata(d.join(programa)).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
        })
    })
}

/// `POST /api/ai/ollama/launch-terminal-update`: abre una terminal con el instalador oficial (para el sudo)
pub async fn ollama_terminal() -> Response {
    let orden = "echo '=================================================='; \
echo '      🚀 Actualizador Oficial de Ollama           '; \
echo '=================================================='; \
echo ''; \
echo 'Descargando e instalando con el script oficial...'; \
echo ''; \
curl -fsSL https://ollama.com/install.sh | sh; \
echo ''; \
echo '=================================================='; \
echo '✅ ¡Proceso finalizado! Ya puedes cerrar esta ventana.'; \
echo '=================================================='; \
read -p 'Presiona Enter para salir...' dummy";
    let envuelta = format!("bash -c \"{orden}\"");
    let candidatos: [Vec<&str>; 3] = [
        vec!["gnome-terminal", "--", "bash", "-c", orden],
        vec!["x-terminal-emulator", "-e", &envuelta],
        vec!["xterm", "-e", &envuelta],
    ];
    for c in candidatos.iter() {
        if en_el_path(c[0]) {
            use std::os::unix::process::CommandExt;
            let lanzado = std::process::Command::new(c[0])
                .args(&c[1..])
                .stdin(std::process::Stdio::null())
                .process_group(0)
                .spawn();
            if lanzado.is_ok() {
                return json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("status", "ok").con("message", format!("Terminal abierta con {}", c[0]))));
            }
        }
    }
    json_py(
        StatusCode::OK,
        &Valor::Mapa(Mapa::new().con("status", "error").con("message", "No se encontró un emulador de terminal compatible instalado en el sistema.")),
    )
}
