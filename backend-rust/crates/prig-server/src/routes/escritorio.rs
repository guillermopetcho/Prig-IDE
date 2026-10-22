//! Lo que toca el escritorio: el audio que suena en el sistema (las aplicaciones que reproducen, la fuente elegida
//! y el espectro en vivo por `/ws/audio_reactivo`, `prig_recursos::audio`) y la pantalla completa de la ventana
//! nativa (la registra el binario `prig`; abierto en el navegador no hay ventana que alternar).

use std::sync::OnceLock;
use std::time::Duration;

use axum::{
    body::Bytes,
    extract::ws::{Message, WebSocket, WebSocketUpgrade},
    http::StatusCode,
    response::Response,
};
use prig_plataforma::valor::{Mapa, Valor};
use prig_recursos::audio::MonitorAudio;

use crate::routes::{cuerpo, detalle, json_py};

fn monitor() -> &'static MonitorAudio {
    static M: OnceLock<MonitorAudio> = OnceLock::new();
    M.get_or_init(MonitorAudio::new)
}

/// `GET /api/audio/aplicaciones`
pub async fn aplicaciones() -> Response {
    let l = tokio::task::spawn_blocking(|| monitor().listar()).await.unwrap_or_default();
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("aplicaciones", Valor::Lista(l.into_iter().map(Valor::Mapa).collect()))))
}

/// `POST /api/audio/seleccionar_fuente` (`{fuente_id}`)
pub async fn seleccionar_fuente(b: Bytes) -> Response {
    let d = match cuerpo::dict(&b) {
        Ok(d) => d,
        Err(r) => return r,
    };
    let fuente = d.get("fuente_id").map(Valor::texto_py).unwrap_or_else(|| "sistema_global".into());
    monitor().seleccionar_fuente(Valor::Texto(fuente.clone()));
    json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("ok", true).con("fuente_actual", fuente)))
}

/// `GET /api/audio/datos_actuales`: el último análisis (energía por bandas y espectro)
pub async fn datos_actuales() -> Response {
    json_py(StatusCode::OK, &Valor::Mapa(monitor().datos()))
}

/// Un suscriptor del espectro: la captura corre mientras haya alguno
struct Suscrito;

impl Suscrito {
    fn nuevo() -> Suscrito {
        monitor().incrementar();
        Suscrito
    }
}

impl Drop for Suscrito {
    fn drop(&mut self) {
        monitor().decrementar();
    }
}

/// `/ws/audio_reactivo`: el análisis a ~50 por segundo
pub async fn ws_audio(ws: WebSocketUpgrade) -> Response {
    ws.on_upgrade(|mut s: WebSocket| async move {
        let _sub = Suscrito::nuevo();
        loop {
            let texto = prig_plataforma::json::escribir_compacto(&Valor::Mapa(monitor().datos()));
            if s.send(Message::Text(texto)).await.is_err() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
}

// =========================================================================== pantalla completa

static PANTALLA: OnceLock<Box<dyn Fn() + Send + Sync>> = OnceLock::new();

/// La ventana nativa dice cómo alternar su pantalla completa (lo llama el binario `prig` al crearla)
pub fn al_pedir_pantalla_completa(f: impl Fn() + Send + Sync + 'static) {
    let _ = PANTALLA.set(Box::new(f));
}

/// `POST /api/ide/pantalla-completa`: WebKitGTK no deja al JavaScript ponerse a pantalla completa; lo hace la ventana
pub async fn pantalla_completa() -> Response {
    match PANTALLA.get() {
        Some(f) => {
            f();
            json_py(StatusCode::OK, &Valor::Mapa(Mapa::new().con("ok", true)))
        }
        None => detalle(StatusCode::CONFLICT, "No hay ventana nativa (¿abierto en el navegador?)"),
    }
}

// =========================================================================== el bloc de notas suelto

/// El binario de la ventana: este mismo proceso si es `prig`; si no (el servidor suelto), el `prig` de al lado
fn binario_ventana() -> Result<std::path::PathBuf, String> {
    let yo = std::env::current_exe().map_err(|e| e.to_string())?;
    if yo.file_name().is_some_and(|n| n == "prig") {
        return Ok(yo);
    }
    let al_lado = yo.with_file_name("prig");
    if al_lado.is_file() {
        Ok(al_lado)
    } else {
        Err(format!("No se encuentra la ventana de Prig ({})", al_lado.display()))
    }
}

/// `POST /api/note/open-standalone`: el bloc de notas en su propia ventana (`prig --nota`)
pub async fn nota_suelta(axum::extract::State(state): axum::extract::State<crate::state::AppState>) -> Response {
    use std::os::unix::process::CommandExt;
    let url = format!("http://127.0.0.1:{}/static/note.html", state.puerto);
    let r = binario_ventana().and_then(|b| {
        std::process::Command::new(b)
            .arg("--nota")
            .arg(&url)
            .stdin(std::process::Stdio::null())
            .process_group(0)
            .spawn()
            .map_err(|e| e.to_string())
    });
    let m = match r {
        Ok(hijo) => {
            // se recoge al cerrarse (sin zombis)
            std::thread::spawn(move || {
                let mut hijo = hijo;
                let _ = hijo.wait();
            });
            Mapa::new().con("status", "success").con("message", "Ventana nativa Note lanzada como aplicación independiente.")
        }
        Err(e) => Mapa::new().con("status", "error").con("message", e),
    };
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

/// `POST /api/note/explain` (`topic`, `model`): unas 500 palabras sobre el tema, en texto continuo
pub async fn nota_explicar(axum::extract::State(state): axum::extract::State<crate::state::AppState>, b: Bytes) -> Response {
    use prig_plataforma::modelo::Tipo;
    let c = match cuerpo::modelo(&b).and_then(|m| cuerpo::tipados(&m, &[("topic", &Tipo::Texto, true), ("model", &Tipo::Texto, false)])) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let tema = c.valor("topic").texto_py();
    let modelo = c.get("model").map(Valor::texto_py).unwrap_or_else(|| "qwen2.5-coder:7b".into());
    let raiz = state.base_dir.clone();
    crate::routes::asistente::flujo_de_texto(move |cancelar, enviar| {
        let sistema = "Eres un TUTOR PEDAGÓGICO DE IA EXPERTO EN TECNOLOGÍA Y PROGRAMACIÓN.
Tu tarea es explicar el tema solicitado de forma profunda, pedagógica y clara en APROXIMADAMENTE 500 PALABRAS.

ESTRUCTURA DE LA EXPLICACIÓN:
1. Concepto Fundamental e Importancia.
2. Principios y Funcionamiento Clave (usando viñetas explicativas).
3. Ejemplo de Código Práctico o Caso de Uso.
4. Conclusión / Resumen Técnico.

Formatea la respuesta en Markdown limpio (títulos ##, ###, bloques de código ```). No agregues saludos ni intros informales.";
        let prompt = format!("Por favor, explica en detalle el siguiente tema en aproximadamente 500 palabras:\nTema: {tema}");
        let prompt = prig_biblioteca::referencias_ml::con_referencias(&raiz, &tema, &prompt).0;
        let p = prig_ia::generar::PedidoGenerar { prompt, modelo, sistema: sistema.into(), gobernador: true, ..Default::default() };
        prig_ia::generar::generar(&raiz, &p, cancelar, &mut |e: Mapa| {
            if e.get("t") == Some(&Valor::Texto("texto".into())) {
                enviar(e.valor("v").texto_py());
            }
        });
    })
}
