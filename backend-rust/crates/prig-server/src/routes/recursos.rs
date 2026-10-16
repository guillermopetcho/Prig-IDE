//! Los recursos con el programa en marcha (`prig_ia::vivo`): temperaturas y gobernador térmico, modo suave, modo
//! frío, energía (con pkexec, solo cuando el usuario lo pide) y el registro de eventos.

#![allow(clippy::result_large_err)]

use std::collections::HashMap;
use std::path::Path;

use axum::{
    body::Bytes,
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_ia::vivo;
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{Mapa, Valor};
use prig_recursos::{almacen, energia, termico};

use crate::routes::{cuerpo, detalle, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

async fn bloque<F: FnOnce() -> Response + Send + 'static>(f: F) -> Response {
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|_| error_500())
}

fn ok(m: Mapa) -> Response {
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

/// Las rutas del ayudante de energía: el instalado y sus fuentes en Prig
pub fn rutas_energia(raiz: &Path) -> energia::Rutas {
    let nativo = raiz.join("backend").join("recursos").join("nativo");
    energia::Rutas {
        ayudante: "/usr/local/libexec/prig-energia".into(),
        politica: "/usr/share/polkit-1/actions/org.prig.energia.policy".into(),
        fuente_ayudante: nativo.join("prig-energia"),
        fuente_politica: nativo.join("org.prig.energia.policy"),
    }
}

// =========================================================================== temperaturas y gobernador

/// `GET /api/recursos/temperaturas?historial=`: los componentes, el gobernador y sus umbrales
pub async fn temperaturas(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let historial = match cuerpo::booleano_consulta(&q, "historial") {
        Ok(h) => h.unwrap_or(false),
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let r = vivo::recursos(&raiz);
        let lectura = match r.monitor().lectura(3.0) {
            Valor::Mapa(m) => m,
            _ => Mapa::new(),
        };
        let gob = r.estado_gobernador();
        let (limite, reanudar) = r.limite_y_reanudar();
        let mut datos = lectura.con("gobernador", gob).con(
            "umbrales",
            Mapa::new()
                .con("gpu_limite", limite)
                .con("gpu_reanudar", reanudar)
                .con("cpu_aviso", termico::CPU_AVISO)
                .con("cpu_alto", termico::CPU_ALTO),
        );
        if historial {
            datos.poner("historial", Valor::Lista(r.monitor().historial()));
        }
        ok(datos)
    })
    .await
}

const REAL: Tipo = Tipo::Opcional(&Tipo::Real);
const BOOL: Tipo = Tipo::Opcional(&Tipo::Booleano);
const ENTERO: Tipo = Tipo::Opcional(&Tipo::Entero);

/// `POST /api/recursos/termico` (`limite_gpu`, `olvidar`)
pub async fn termico_ajustar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(&m, &[("limite_gpu", &REAL, false), ("olvidar", &Tipo::Booleano, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let r = vivo::recursos(&raiz);
        if let Some(l) = c.get("limite_gpu").and_then(Valor::num) {
            if let Err(e) = r.fijar_limite(l) {
                return detalle(StatusCode::BAD_REQUEST, e);
            }
        }
        if c.verdad("olvidar") {
            r.olvidar();
        }
        ok(r.estado_gobernador())
    })
    .await
}

// =========================================================================== modo suave

/// `GET /api/recursos/ritmo`: ajustes, fracción de trabajo ahora mismo y núcleos de eficiencia
pub async fn ritmo(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || {
        let r = vivo::recursos(&raiz);
        r.sincronizar();
        ok(r.estado_ritmo())
    })
    .await
}

/// `POST /api/recursos/ritmo`: cambia los ajustes, instala o retira el motor suave y fija los núcleos
pub async fn ritmo_ajustar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let campos = [
        ("activo", &BOOL, false),
        ("objetivo_c", &REAL, false),
        ("rampa_s", &REAL, false),
        ("ritmo_minimo", &REAL, false),
        ("tramo_s", &REAL, false),
        ("cpu_eficiente", &BOOL, false),
    ];
    let c = match cuerpo::tipados(&m, &campos) {
        Ok(c) => c,
        Err(r) => return r,
    };
    // `{k: v for k, v in req.model_dump().items() if v is not None}`, en el orden del modelo
    let mut cambios = Mapa::new();
    for (k, _, _) in campos {
        if let Some(v) = c.get(k).filter(|v| !v.es_nulo()) {
            cambios.poner(k, v.clone());
        }
    }
    let raiz = state.base_dir.clone();
    bloque(move || {
        let r = vivo::recursos(&raiz);
        if r.fijar_ritmo(&cambios).is_err() {
            return error_500();
        }
        r.aplicar_motor_suave();
        r.paso_suave();
        let (activo, eficiente) = {
            let ritmo = r.ritmo.lock().unwrap_or_else(|e| e.into_inner());
            (ritmo.activo(), ritmo.ajustes.verdad("cpu_eficiente"))
        };
        if activo && eficiente {
            r.aplicar_fijador(true);
        } else {
            r.soltar_fijador();
        }
        ok(r.estado_ritmo())
    })
    .await
}

// =========================================================================== modo frío y energía

/// `GET /api/recursos/frio`
pub async fn frio(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || ok(vivo::recursos(&raiz).estado_frio(&rutas_energia(&raiz)))).await
}

/// `POST /api/recursos/frio` (`activo`, `objetivo_c`: de 40 a 85 °C)
pub async fn frio_ajustar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(&m, &[("activo", &BOOL, false), ("objetivo_c", &REAL, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let a = almacen::global();
        let mut actual = a.seccion("frio");
        if let Some(v) = c.get("activo").filter(|v| !v.es_nulo()) {
            actual.poner("activo", v.verdad());
        }
        if let Some(o) = c.get("objetivo_c").and_then(Valor::num) {
            actual.poner("objetivo_c", 40.0_f64.max(85.0_f64.min(o)));
        }
        if a.guardar_seccion("frio", actual, Some(("frio", "Ajustes del modo frío", None))).is_err() {
            return error_500();
        }
        let r = vivo::recursos(&raiz);
        r.paso_frio();
        ok(r.estado_frio(&rutas_energia(&raiz)))
    })
    .await
}

fn error_energia(e: energia::ErrorEnergia) -> Response {
    match e {
        energia::ErrorEnergia::Energia(m) => detalle(StatusCode::BAD_REQUEST, m),
        energia::ErrorEnergia::Io(_) => error_500(),
    }
}

/// `POST /api/recursos/energia/instalar`: copia el ayudante como root (pkexec pide la contraseña)
pub async fn energia_instalar(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || {
        let rutas = rutas_energia(&raiz);
        if let Err(e) = energia::instalar(&rutas) {
            return error_energia(e);
        }
        ok(vivo::recursos(&raiz).estado_frio(&rutas))
    })
    .await
}

/// `POST /api/recursos/energia` (`frio`, `vatios`): turbo apagado y tope de potencia, o lo de antes
pub async fn energia(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(&m, &[("frio", &Tipo::Booleano, true), ("vatios", &ENTERO, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let rutas = rutas_energia(&raiz);
        let a = almacen::global();
        if c.verdad("frio") {
            // int(req.vatios or almacen.frio().get("vatios") or VATIOS_POR_DEFECTO)
            let guardados = a.seccion("frio").get("vatios").cloned().unwrap_or(Valor::Nulo);
            let vatios = [c.get("vatios").cloned().unwrap_or(Valor::Nulo), guardados]
                .into_iter()
                .find(Valor::verdad)
                .and_then(|v| v.num())
                .map(|n| n.trunc() as i64)
                .unwrap_or(energia::VATIOS_POR_DEFECTO);
            if let Err(e) = energia::frio(&rutas, Some(vatios)) {
                return error_energia(e);
            }
            let actual = a.seccion("frio").con("vatios", vatios);
            let texto = format!("Energía fría: turbo apagado, tope {vatios} W");
            if a.guardar_seccion("frio", actual, Some(("frio", &texto, None))).is_err() {
                return error_500();
            }
        } else {
            if let Err(e) = energia::normal(&rutas) {
                return error_energia(e);
            }
            if a.evento("frio", "Energía normal restaurada", None).is_err() {
                return error_500();
            }
        }
        ok(vivo::recursos(&raiz).estado_frio(&rutas))
    })
    .await
}

// =========================================================================== eventos

/// `GET /api/recursos/eventos?limite=50` (de 1 a 200)
pub async fn eventos(Query(q): Query<HashMap<String, String>>) -> Response {
    let limite = match cuerpo::entero_consulta(&q, "limite", 50, i64::MIN, i64::MAX) {
        Ok(l) => l.clamp(1, 200),
        Err(r) => return r,
    };
    bloque(move || ok(Mapa::new().con("eventos", Valor::Lista(almacen::global().eventos(limite))))).await
}

// =========================================================================== el gestor: el botón «Recomendado»

use prig_ia::gestor::{self, Fallo};
use prig_ia::motor;
use prig_recursos::{calibracion, detector, perfiles, servidor};

/// Lo que se cancela con «Cancelar» (la calibración y la prueba en curso)
fn cancelar_recursos() -> &'static std::sync::Arc<vivo::Cancelar> {
    static C: std::sync::OnceLock<std::sync::Arc<vivo::Cancelar>> = std::sync::OnceLock::new();
    C.get_or_init(vivo::Cancelar::new)
}

/// ¿Hay una generación en curso? La del motor MoE, o una de Python mientras genere él (se le pregunta)
fn gpu_ocupada(fallback: &str) -> bool {
    if vivo::Recursos::moe_generando() {
        return true;
    }
    matches!(
        prig_recursos::http::get_json(&format!("{fallback}/api/ai/ocupada"), 2.0),
        Ok(Valor::Mapa(m)) if m.verdad("ocupada")
    )
}

fn texto_de_valor(v: &Valor) -> Option<&str> {
    match v {
        Valor::Texto(t) => Some(t),
        _ => None,
    }
}

fn ruta_registro() -> String {
    std::env::var_os("HOME").map(std::path::PathBuf::from).unwrap_or_default().join(".prig_ollama.log").to_string_lossy().into_owned()
}

fn estado_servidor(raiz: &Path, info: Option<&Mapa>) -> Mapa {
    let info = match info.filter(|i| !i.is_empty()) {
        Some(i) => i.clone(),
        None => detector::ollama(&gestor::url_ollama(), &raiz.to_string_lossy()),
    };
    servidor::estado(&info, &almacen::global().seccion("entorno_servidor"), raiz, &ruta_registro())
}

/// Error 400 si el perfil o la preferencia no existen
fn perfil_valido(perfil: &str, tirador: &str) -> Result<(), Response> {
    if !perfiles::perfiles().contiene(perfil) {
        return Err(detalle(StatusCode::BAD_REQUEST, format!("Perfil desconocido: {perfil}")));
    }
    if !perfiles::tiradores().contiene(tirador) {
        return Err(detalle(StatusCode::BAD_REQUEST, format!("Preferencia desconocida: {tirador}")));
    }
    Ok(())
}

const CAMPOS_TUTOR: [&str; 4] = ["agent1_model", "num_ctx", "num_gpu", "keep_alive"];

fn config_tutor() -> Mapa {
    let cfg = motor::config_ia();
    let mut m = Mapa::new();
    for k in CAMPOS_TUTOR {
        m.poner(k, cfg.get(k).cloned().unwrap_or(Valor::Nulo));
    }
    m
}

fn propuesta_tutor(rec: &Mapa) -> Mapa {
    let opc = rec.mapa("opciones").cloned().unwrap_or_default();
    Mapa::new()
        .con("agent1_model", rec.valor("modelo").clone())
        .con("num_ctx", opc.get("num_ctx").cloned().unwrap_or(Valor::Nulo))
        // Automático: forzar capas no aceleró nada y provocó falta de memoria
        .con("num_gpu", -1)
        .con("keep_alive", opc.get("keep_alive").cloned().unwrap_or(Valor::Nulo))
}

fn diferencias(actual: &Mapa, propuesta: &Mapa) -> Valor {
    Valor::Lista(
        propuesta
            .iter()
            .filter(|(k, v)| !v.es_nulo() && actual.get(k) != Some(v))
            .map(|(k, v)| {
                Mapa::new().con("campo", k.as_str()).con("actual", actual.get(k).cloned().unwrap_or(Valor::Nulo)).con("nuevo", v.clone()).into()
            })
            .collect(),
    )
}

/// `{"modelo": previo.get("modelo"), **(previo.get("opciones") or {})}`
fn actual_de(previo: &Mapa) -> Mapa {
    let mut m = Mapa::new().con("modelo", previo.get("modelo").cloned().unwrap_or(Valor::Nulo));
    if let Some(o) = previo.mapa("opciones") {
        for (k, v) in o.iter() {
            m.poner(k.clone(), v.clone());
        }
    }
    m
}

fn sin_nulos(m: &Mapa) -> Mapa {
    let mut s = Mapa::new();
    for (k, v) in m.iter().filter(|(_, v)| !v.es_nulo()) {
        s.poner(k.clone(), v.clone());
    }
    s
}

fn aplicado(perfil: &str) -> Valor {
    almacen::global().aplicado(perfil).unwrap_or(Valor::Nulo)
}

/// `GET /api/recursos/maquina?fresca=`: la radiografía, el servidor, la calibración y el estado en vivo
pub async fn maquina(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let fresca = match cuerpo::booleano_consulta(&q, "fresca") {
        Ok(f) => f.unwrap_or(false),
        Err(r) => return r,
    };
    let raiz = state.base_dir.clone();
    bloque(move || {
        let g = gestor::gestor(&raiz);
        let maq = match g.maquina(fresca) {
            Ok(m) => m,
            Err(e) => return detalle(StatusCode::INTERNAL_SERVER_ERROR, format!("No se pudo analizar la máquina: {e}")),
        };
        let rad = &maq.radiografia;
        let cal = almacen::global().calibracion(rad.texto("huella")).map(|c| {
            let mut m = Mapa::new();
            for (k, v) in c.iter().filter(|(k, _)| k.as_str() != "muestras" && k.as_str() != "detalle") {
                m.poner(k.clone(), v.clone());
            }
            Valor::Mapa(m)
        });
        let vivo = match g.estado_vivo() {
            Ok(v) => v,
            Err(_) => return error_500(),
        };
        let campo = |k: &str| rad.get(k).cloned().unwrap_or(Valor::Nulo);
        ok(Mapa::new()
            .con("huella", campo("huella"))
            .con("sistema", campo("sistema"))
            .con("cpu", campo("cpu"))
            .con("memoria", campo("memoria"))
            .con("gpus", campo("gpus"))
            .con("disco", campo("disco"))
            .con("energia", campo("energia"))
            .con("ancho_banda_ram_gbps", campo("ancho_banda_ram_gbps"))
            .con("resumen", maq.resumen())
            .con("servidor", estado_servidor(&raiz, rad.mapa("ollama")))
            .con("calibracion", cal.unwrap_or(Valor::Nulo))
            .con("vivo", vivo))
    })
    .await
}

/// `GET /api/recursos/estado`
pub async fn estado(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || match gestor::gestor(&raiz).estado_vivo() {
        Ok(m) => ok(m),
        Err(_) => error_500(),
    })
    .await
}

/// `GET /api/recursos/perfiles`
pub async fn perfiles_lista() -> Response {
    let lista = perfiles::perfiles()
        .iter()
        .map(|(k, v)| {
            let mut m = Mapa::new().con("id", k.as_str());
            if let Valor::Mapa(p) = v {
                for (c, x) in p.iter() {
                    m.poner(c.clone(), x.clone());
                }
            }
            Valor::Mapa(m)
        })
        .collect();
    let tiradores = perfiles::tiradores().iter().map(|(k, v)| Mapa::new().con("id", k.as_str()).con("nombre", v.clone()).into()).collect();
    ok(Mapa::new().con("perfiles", Valor::Lista(lista)).con("tiradores", Valor::Lista(tiradores)))
}

/// `GET /api/recursos/modelos?perfil=tutor&tirador=equilibrado`
pub async fn modelos(State(state): State<AppState>, Query(q): Query<HashMap<String, String>>) -> Response {
    let perfil = q.get("perfil").cloned().unwrap_or_else(|| "tutor".into());
    let tirador = q.get("tirador").cloned().unwrap_or_else(|| "equilibrado".into());
    if let Err(r) = perfil_valido(&perfil, &tirador) {
        return r;
    }
    let raiz = state.base_dir.clone();
    bloque(move || match gestor::gestor(&raiz).veredictos(&perfil, &tirador) {
        Ok(m) => ok(m),
        Err(_) => error_500(),
    })
    .await
}

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);

/// `(modelo, perfil, tirador)` de un cuerpo; `modelo_obligatorio`: `modelo: str`, si no `Optional[str] = None`
fn pedido_recursos(b: &Bytes, modelo_obligatorio: bool, extra: &[(&'static str, &'static Tipo, bool)]) -> Result<Mapa, Response> {
    let m = cuerpo::modelo(b)?;
    let mut campos: Vec<(&str, &Tipo, bool)> = vec![
        ("modelo", if modelo_obligatorio { &Tipo::Texto } else { &TEXTO_OPC }, modelo_obligatorio),
        ("perfil", &Tipo::Texto, false),
        ("tirador", &Tipo::Texto, false),
    ];
    campos.extend_from_slice(extra);
    let c = cuerpo::tipados(&m, &campos)?;
    Ok(c)
}

fn texto_de(c: &Mapa, k: &str, defecto: &str) -> String {
    c.get(k).filter(|v| !v.es_nulo()).map(Valor::texto_py).unwrap_or_else(|| defecto.into())
}

/// `POST /api/recursos/recomendar`: sin modelo, elige el mejor instalado para el uso; con modelo, cómo abrirlo
pub async fn recomendar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido_recursos(&b, false, &[]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (perfil, tirador) = (texto_de(&c, "perfil", "tutor"), texto_de(&c, "tirador", "equilibrado"));
    if let Err(r) = perfil_valido(&perfil, &tirador) {
        return r;
    }
    let pedido = c.get("modelo").filter(|v| v.verdad()).map(Valor::texto_py);
    let (raiz, fallback) = (state.base_dir.clone(), state.fallback_url.clone());
    bloque(move || {
        let g = gestor::gestor(&raiz);
        let mut ranking = None;
        let modelo = match &pedido {
            Some(m) => m.clone(),
            None => {
                let filas = match g.veredictos(&perfil, &tirador) {
                    Ok(v) => v.lista("modelos").map(<[Valor]>::to_vec).unwrap_or_default(),
                    Err(_) => return error_500(),
                };
                if filas.is_empty() {
                    return detalle(StatusCode::NOT_FOUND, "No hay modelos instalados.");
                }
                let elegido = filas
                    .iter()
                    .find(|m| matches!(m, Valor::Mapa(x) if x.verdad("util")))
                    .unwrap_or(&filas[0]);
                let nombre = match elegido {
                    Valor::Mapa(x) => x.valor("modelo").texto_py(),
                    _ => String::new(),
                };
                ranking = Some(filas);
                nombre
            }
        };
        let mut rec = match g.recomendar(&modelo, &perfil, &tirador) {
            Ok(r) => r,
            Err((true, e)) => return detalle(StatusCode::NOT_FOUND, e),
            Err(_) => return error_500(),
        };
        rec.poner("elegido_automaticamente", pedido.is_none());
        if let Some(filas) = ranking {
            let resumen = filas
                .iter()
                .take(8)
                .filter_map(|m| match m {
                    Valor::Mapa(m) => {
                        let mut r = Mapa::new();
                        for k in ["modelo", "veredicto", "etiqueta", "util", "calidad_esperada", "puntos"] {
                            r.poner(k, m.get(k).cloned().unwrap_or(Valor::Nulo));
                        }
                        let tok = m.mapa("estimacion").and_then(|e| e.get("tok_s")).cloned().unwrap_or(Valor::Nulo);
                        Some(Valor::Mapa(r.con("tok_s", tok)))
                    }
                    _ => None,
                })
                .collect();
            rec.poner("ranking", Valor::Lista(resumen));
        }
        let cambios = if perfil == "tutor" {
            diferencias(&config_tutor(), &propuesta_tutor(&rec))
        } else {
            let previo = match aplicado(&perfil) {
                Valor::Mapa(p) => p,
                _ => Mapa::new(),
            };
            let nuevo = actual_de(&Mapa::new().con("modelo", rec.valor("modelo").clone()).con("opciones", rec.get("opciones").cloned().unwrap_or(Valor::Nulo)));
            diferencias(&actual_de(&previo), &nuevo)
        };
        rec.poner("cambios", cambios);
        rec.poner("aplicado", aplicado(&perfil));
        rec.poner("gpu_ocupada", gpu_ocupada(&fallback));
        ok(rec)
    })
    .await
}

/// `POST /api/recursos/aplicar`: la recomendación (recalculada aquí, nunca la del cliente), guardando lo que había
pub async fn aplicar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido_recursos(&b, true, &[]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (perfil, tirador) = (texto_de(&c, "perfil", "tutor"), texto_de(&c, "tirador", "equilibrado"));
    if let Err(r) = perfil_valido(&perfil, &tirador) {
        return r;
    }
    let modelo = texto_de(&c, "modelo", "");
    let raiz = state.base_dir.clone();
    bloque(move || {
        let rec = match gestor::gestor(&raiz).recomendar(&modelo, &perfil, &tirador) {
            Ok(r) => r,
            Err((true, e)) => return detalle(StatusCode::NOT_FOUND, e),
            Err(_) => return error_500(),
        };
        if rec.texto("veredicto") == Some("no_viable") {
            return detalle(StatusCode::CONFLICT, rec.valor("motivo").texto_py());
        }
        let a = almacen::global();
        let opciones = rec.get("opciones").cloned().unwrap_or(Valor::Nulo);
        let cambios = if perfil == "tutor" {
            let actual = config_tutor();
            let propuesta = propuesta_tutor(&rec);
            let cambios = diferencias(&actual, &propuesta);
            if a.registrar_aplicado("tutor", rec.valor("modelo"), &opciones, &Valor::Mapa(actual)).is_err()
                || motor::guardar_config_ia(&sin_nulos(&propuesta)).is_err()
            {
                return error_500();
            }
            cambios
        } else {
            let previo = match aplicado(&perfil) {
                Valor::Mapa(p) => p,
                _ => Mapa::new(),
            };
            let nuevo = actual_de(&Mapa::new().con("modelo", rec.valor("modelo").clone()).con("opciones", opciones.clone()));
            let cambios = diferencias(&actual_de(&previo), &nuevo);
            if a.registrar_aplicado(&perfil, rec.valor("modelo"), &opciones, &Valor::Mapa(Mapa::new())).is_err() {
                return error_500();
            }
            cambios
        };
        ok(Mapa::new().con("ok", true).con("cambios", cambios).con("recomendacion", rec).con("config", motor::config_ia()))
    })
    .await
}

/// `POST /api/recursos/restaurar` (`perfil`)
pub async fn restaurar(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let c = match cuerpo::tipados(&m, &[("perfil", &Tipo::Texto, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let perfil = texto_de(&c, "perfil", "tutor");
    if let Err(r) = perfil_valido(&perfil, "equilibrado") {
        return r;
    }
    bloque(move || {
        let anterior = match almacen::global().quitar_aplicado(&perfil) {
            Ok(Some(a)) => a,
            Ok(None) => return detalle(StatusCode::NOT_FOUND, "No hay nada aplicado que restaurar."),
            Err(_) => return error_500(),
        };
        if perfil == "tutor" && anterior.verdad() {
            if let Valor::Mapa(a) = &anterior {
                if motor::guardar_config_ia(&sin_nulos(a)).is_err() {
                    return error_500();
                }
            }
        }
        ok(Mapa::new().con("ok", true).con("restaurado", anterior).con("config", motor::config_ia()))
    })
    .await
}

/// Ejecuta `trabajo(avisar)` en un hilo y emite sus eventos como NDJSON, con el final (`fin` o `error`). Si el
/// cliente se va, se cancela.
fn ndjson_en_hilo<F>(trabajo: F) -> Response
where
    F: FnOnce(&mut dyn FnMut(Mapa)) -> Result<Mapa, Fallo> + Send + 'static,
{
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(64);
    std::thread::spawn(move || {
        let linea = |v: Valor| Bytes::from(prig_plataforma::json::escribir_compacto(&v) + "\n");
        let mut avisar = |e: Mapa| {
            if tx.blocking_send(Ok(linea(Valor::Mapa(e)))).is_err() {
                cancelar_recursos().poner();
            }
        };
        let fin = match trabajo(&mut avisar) {
            Ok(r) => Mapa::new().con("tipo", "fin").con("resultado", r),
            Err(f) => Mapa::new().con("tipo", "error").con("mensaje", f.mensaje()),
        };
        let _ = tx.blocking_send(Ok(linea(Valor::Mapa(fin))));
    });
    let flujo = futures_util::stream::unfold(rx, |mut rx| async move { rx.recv().await.map(|x| (x, rx)) });
    ([(axum::http::header::CONTENT_TYPE, "application/x-ndjson")], axum::body::Body::from_stream(flujo)).into_response()
}

/// `POST /api/recursos/probar`: prueba real y corta de la recomendación; guarda lo medido
pub async fn probar(State(state): State<AppState>, b: Bytes) -> Response {
    let c = match pedido_recursos(&b, true, &[("forzar", &Tipo::Booleano, false)]) {
        Ok(c) => c,
        Err(r) => return r,
    };
    let (perfil, tirador) = (texto_de(&c, "perfil", "tutor"), texto_de(&c, "tirador", "equilibrado"));
    if let Err(r) = perfil_valido(&perfil, &tirador) {
        return r;
    }
    let modelo = texto_de(&c, "modelo", "");
    let forzar = c.verdad("forzar");
    let (raiz, fallback) = (state.base_dir.clone(), state.fallback_url.clone());
    let previo = tokio::task::spawn_blocking(move || {
        if !forzar && gpu_ocupada(&fallback) {
            return Err(detalle(StatusCode::CONFLICT, "Hay una generación en curso; espera a que termine."));
        }
        let f = match gestor::gestor(&raiz).ficha(&modelo, false) {
            Ok(f) => f,
            Err(e) => return Err(detalle(StatusCode::NOT_FOUND, e)),
        };
        if f.verdad("estimada") {
            return Err(detalle(StatusCode::CONFLICT, "Descarga el modelo antes de probarlo."));
        }
        Ok((raiz, f))
    })
    .await;
    let (raiz, f) = match previo {
        Ok(Ok(x)) => x,
        Ok(Err(r)) => return r,
        Err(_) => return error_500(),
    };
    cancelar_recursos().quitar();
    ndjson_en_hilo(move |avisar| {
        let g = gestor::gestor(&raiz);
        let maq = g.maquina(true).map_err(Fallo::Error)?;
        let r = gestor::probar_recomendacion(&raiz, &f, &maq, &perfil, &tirador, avisar, cancelar_recursos())?;
        let huella = maq.radiografia.valor("huella").clone();
        let mut guardar = Mapa::new();
        for (k, v) in r.iter().filter(|(k, _)| k.as_str() != "recomendacion") {
            guardar.poner(k.clone(), v.clone());
        }
        let a = almacen::global();
        a.guardar_prueba(&huella, &f.valor("nombre").texto_py(), &perfil, &guardar).map_err(|e| Fallo::Error(e.to_string()))?;
        if let Some(Valor::Mapa(d)) = r.get("deducido").filter(|d| d.verdad()) {
            let previa = a.calibracion(texto_de_valor(&huella));
            let valores = calibracion::combinar(previa.as_ref(), std::slice::from_ref(d));
            a.guardar_calibracion(&huella, &valores, None).map_err(|e| Fallo::Error(e.to_string()))?;
        }
        Ok(guardar)
    })
}

/// `POST /api/recursos/calibrar`: mide con dos modelos instalados
pub async fn calibrar(State(state): State<AppState>) -> Response {
    let (raiz, fallback) = (state.base_dir.clone(), state.fallback_url.clone());
    let ocupada = tokio::task::spawn_blocking(move || gpu_ocupada(&fallback)).await.unwrap_or(false);
    if ocupada {
        return detalle(StatusCode::CONFLICT, "Hay una generación en curso; espera a que termine.");
    }
    cancelar_recursos().quitar();
    ndjson_en_hilo(move |avisar| {
        let g = gestor::gestor(&raiz);
        let maq = g.maquina(true).map_err(Fallo::Error)?;
        let huella = maq.radiografia.valor("huella").clone();
        let a = almacen::global();
        let previa = a.calibracion(texto_de_valor(&huella));
        let mut r = gestor::calibrar(&raiz, &g.fichas_instaladas(), maq, avisar, cancelar_recursos(), previa.as_ref())?;
        for p in r.lista("pruebas").map(<[Valor]>::to_vec).unwrap_or_default() {
            if let Valor::Mapa(p) = p {
                if p.verdad("ok") {
                    a.guardar_prueba(&huella, &p.valor("modelo").texto_py(), "calibracion", &p).map_err(|e| Fallo::Error(e.to_string()))?;
                }
            }
        }
        if r.verdad("ok") {
            let n = r.lista("pruebas").map(<[Valor]>::len).unwrap_or(0);
            let valores = r.mapa("valores").cloned().unwrap_or_default();
            a.guardar_calibracion(&huella, &valores, Some(&Valor::Mapa(Mapa::new().con("pruebas", n))))
                .map_err(|e| Fallo::Error(e.to_string()))?;
            r.poner("maquina", g.maquina(false).map_err(Fallo::Error)?.resumen());
        }
        Ok(r)
    })
}

/// `POST /api/recursos/cancelar`
pub async fn cancelar() -> Response {
    cancelar_recursos().poner();
    ok(Mapa::new().con("ok", true))
}

/// `POST /api/recursos/olvidar-calibracion`
pub async fn olvidar_calibracion() -> Response {
    bloque(|| match almacen::global().olvidar_calibracion(None) {
        Ok(()) => ok(Mapa::new().con("ok", true)),
        Err(_) => error_500(),
    })
    .await
}

/// `GET /api/recursos/servidor`
pub async fn servidor_estado(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    bloque(move || ok(estado_servidor(&raiz, None))).await
}

/// `POST /api/recursos/servidor` (`cambios`, `reiniciar`, `forzar`): guarda las variables y, si el servidor es de
/// Prig, lo reinicia con ellas
pub async fn servidor_aplicar(State(state): State<AppState>, b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    // `cambios: Dict[str, Optional[str]]`: los errores de cada valor van con su clave
    let mut errores = Vec::new();
    let cambios = match m.get("cambios") {
        None => {
            errores.push(cuerpo::Error {
                tipo: "missing",
                loc: vec!["body".into(), "cambios".into()],
                msg: "Field required".into(),
                entrada: Valor::Mapa(m.clone()),
                ctx: None,
            });
            Mapa::new()
        }
        Some(Valor::Mapa(c)) => {
            for (k, v) in c.iter() {
                if !matches!(v, Valor::Texto(_) | Valor::Nulo) {
                    errores.push(cuerpo::Error {
                        tipo: "string_type",
                        loc: vec!["body".into(), "cambios".into(), Valor::Texto(k.clone())],
                        msg: cuerpo::mensaje("string_type").into(),
                        entrada: v.clone(),
                        ctx: None,
                    });
                }
            }
            c.clone()
        }
        Some(otro) => {
            errores.push(cuerpo::Error {
                tipo: "dict_type",
                loc: vec!["body".into(), "cambios".into()],
                msg: cuerpo::mensaje("dict_type").into(),
                entrada: otro.clone(),
                ctx: None,
            });
            Mapa::new()
        }
    };
    let (banderas, mas) = cuerpo::tipados_con_errores(&m, &[("reiniciar", &Tipo::Booleano, false), ("forzar", &Tipo::Booleano, false)]);
    errores.extend(mas);
    if !errores.is_empty() {
        return cuerpo::respuesta(errores);
    }
    let reiniciar = banderas.get("reiniciar").is_none_or(Valor::verdad);
    let forzar = banderas.verdad("forzar");
    let (raiz, fallback) = (state.base_dir.clone(), state.fallback_url.clone());
    bloque(move || {
        if reiniciar && !forzar && gpu_ocupada(&fallback) {
            return detalle(StatusCode::CONFLICT, "Hay una generación en curso: reiniciar Ollama la cortaría.");
        }
        let r = match aplicar_servidor(&raiz, &cambios, reiniciar, forzar) {
            Ok(r) => r,
            Err(e) => return detalle(StatusCode::BAD_REQUEST, e),
        };
        let _ = gestor::gestor(&raiz).radiografia(true);
        ok(r)
    })
    .await
}

/// `servidor.aplicar`: Error, el mensaje del ValueError (un ajuste que no vale)
fn aplicar_servidor(raiz: &Path, cambios: &Mapa, reiniciar: bool, forzar: bool) -> Result<Mapa, String> {
    let limpio = servidor::validar(cambios, raiz)?;
    let a = almacen::global();
    let mut guardado = a.seccion("entorno_servidor");
    for (k, v) in limpio.iter() {
        guardado.poner(k.clone(), v.clone());
    }
    let guardado = {
        let mut g = Mapa::new();
        for (k, v) in guardado.iter().filter(|(_, v)| **v != Valor::Texto(String::new())) {
            g.poner(k.clone(), v.clone());
        }
        g
    };
    let _ = a.guardar_entorno_servidor(&guardado);
    let url = gestor::url_ollama();
    let info = detector::ollama(&url, &raiz.to_string_lossy());
    let dueno = info.get("dueno").cloned().unwrap_or(Valor::Nulo);
    let base = Mapa::new().con("aplicado", false).con("guardado", guardado.clone()).con("dueno", dueno.clone());
    if !(dueno.es_nulo() || dueno == Valor::Texto("prig".into())) {
        let d = texto_de_valor(&dueno).map(str::to_string);
        return Ok(base.con("instrucciones", servidor::instrucciones(d.as_deref(), &guardado)));
    }
    if !reiniciar {
        return Ok(base.con("mensaje", "Guardado. Se usará la próxima vez que Prig arranque Ollama."));
    }
    if info.get("modelos_cargados").is_some_and(Valor::verdad) && !forzar {
        return Ok(base.con("necesita_confirmar", true).con(
            "mensaje",
            "Hay modelos cargados: reiniciar corta lo que estén generando. Confirma para reiniciar igualmente.",
        ));
    }
    // reiniciar_servidor
    if let Some(pid) = info.get("pid").filter(|p| p.verdad()).and_then(Valor::num) {
        if dueno == Valor::Texto("prig".into()) {
            servidor::parar_ollama(pid as i32);
        }
    }
    let arrancado = prig_ia::ollama::asegurar(raiz, false);
    let nuevo = detector::ollama(&url, &raiz.to_string_lossy());
    let real = nuevo.mapa("entorno").cloned().unwrap_or_default();
    let mut faltan = Mapa::new();
    for (k, v) in guardado.iter() {
        if real.get(k) != Some(v) {
            faltan.poner(k.clone(), v.clone());
        }
    }
    let texto = if faltan.is_empty() {
        "Ollama reiniciado con las variables de Prig."
    } else {
        "Ollama reiniciado, pero no tomó todas las variables."
    };
    let _ = a.evento(
        "servidor_reiniciado",
        texto,
        Some(Valor::Mapa(Mapa::new().con("entorno", real.clone()).con("faltan", faltan.clone()))),
    );
    Ok(Mapa::new()
        .con("aplicado", arrancado && faltan.is_empty())
        .con("guardado", guardado)
        .con("dueno", nuevo.get("dueno").cloned().unwrap_or(Valor::Nulo))
        .con("entorno", real)
        .con("faltan", faltan)
        .con("version", nuevo.get("version").cloned().unwrap_or(Valor::Nulo)))
}
