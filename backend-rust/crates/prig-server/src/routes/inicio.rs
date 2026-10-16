//! La pantalla de Inicio y el estado de la máquina: `/api/system/stats` (CPU, RAM y GPU para la barra de estado),
//! `/api/system/health` (¿puede este equipo con el modelo elegido?) y `/api/inicio` (todo lo de Inicio en una
//! petición; cada bloque falla por separado), con el perfil editable.

#![allow(clippy::result_large_err)]

use std::path::Path;
use std::sync::Mutex;

use axum::{
    body::Bytes,
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use prig_ia::{gemini, motor, ollama, vivo};
use prig_plataforma::modelo::Tipo;
use prig_plataforma::valor::{redondear, Mapa, Valor};
use prig_plataforma::{ide, inicio};

use crate::routes::{cuerpo, json_py};
use crate::state::AppState;

fn error_500() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn ok(m: Mapa) -> Response {
    json_py(StatusCode::OK, &Valor::Mapa(m))
}

// =========================================================================== la máquina

/// `psutil.cpu_percent(interval=None)`: el uso desde la llamada anterior (0.0 la primera vez)
fn uso_cpu() -> f64 {
    static PREVIO: Mutex<Option<(u64, u64)>> = Mutex::new(None);
    let texto = std::fs::read_to_string("/proc/stat").unwrap_or_default();
    let Some(linea) = texto.lines().find(|l| l.starts_with("cpu ")) else { return 0.0 };
    let v: Vec<u64> = linea.split_whitespace().skip(1).filter_map(|x| x.parse().ok()).collect();
    if v.len() < 8 {
        return 0.0;
    }
    // como psutil en Linux: el total sin «guest» (ya contado en «user»), y ocupado = total − idle − iowait
    let guest = v.get(8).copied().unwrap_or(0) + v.get(9).copied().unwrap_or(0);
    let total: u64 = v.iter().sum::<u64>() - guest;
    let ocupado = total - v[3] - v[4];
    let mut p = PREVIO.lock().unwrap_or_else(|e| e.into_inner());
    let r = match *p {
        Some((t0, o0)) if total > t0 => redondear(100.0 * (ocupado.saturating_sub(o0)) as f64 / (total - t0) as f64, 1),
        _ => 0.0,
    };
    *p = Some((total, ocupado));
    r
}

/// `psutil.virtual_memory()`: (porcentaje, usada en GB, total en GB)
fn memoria() -> (f64, f64, f64) {
    let texto = std::fs::read_to_string("/proc/meminfo").unwrap_or_default();
    let kb = |clave: &str| -> f64 {
        texto
            .lines()
            .find_map(|l| l.strip_prefix(clave).and_then(|r| r.strip_prefix(':')))
            .and_then(|v| v.split_whitespace().next())
            .and_then(|v| v.parse::<f64>().ok())
            .unwrap_or(0.0)
            * 1024.0
    };
    let (total, libre, disponible) = (kb("MemTotal"), kb("MemFree"), kb("MemAvailable"));
    let mut usada = total - libre - kb("Buffers") - kb("Cached") - kb("SReclaimable");
    if usada < 0.0 {
        usada = total - libre;
    }
    let pct = if total > 0.0 { redondear((total - disponible) / total * 100.0, 1) } else { 0.0 };
    let gb = 1024f64.powi(3);
    (pct, redondear(usada / gb, 1), redondear(total / gb, 1))
}

/// `get_system_stats()`: CPU, RAM y la GPU (por NVML; si no, nvidia-smi)
pub fn estadisticas() -> Mapa {
    let cpu = uso_cpu();
    let (ram_pct, usada, total) = memoria();
    let base = Mapa::new().con("cpu_pct", cpu).con("ram_pct", ram_pct).con("ram_used_gb", usada).con("ram_total_gb", total);
    if let Some(g) = prig_recursos::nvml::lectura().and_then(|l| l.into_iter().next()) {
        // `g["uso_pct"] or 0`: el real de NVML, o el entero 0
        let real = |x: Option<f64>| x.filter(|v| *v != 0.0).map(Valor::Real).unwrap_or(Valor::Entero(0));
        let entero = |x: Option<u64>| Valor::Entero(x.unwrap_or(0) as i128);
        return base.con(
            "gpu",
            Mapa::new()
                .con("has_gpu", true)
                .con("gpu_pct", real(g.uso_pct))
                .con("vram_used_mb", entero(g.vram_usada_mb))
                .con("vram_total_mb", entero(g.vram_total_mb)),
        );
    }
    let mut gpu = Mapa::new().con("has_gpu", false).con("gpu_pct", 0).con("vram_used_mb", 0).con("vram_total_mb", 0);
    let salida = std::process::Command::new("nvidia-smi")
        .args(["--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"])
        .output();
    if let Ok(s) = salida {
        let t = String::from_utf8_lossy(&s.stdout).trim().to_string();
        let partes: Vec<i64> = t.lines().next().unwrap_or("").split(',').filter_map(|p| p.trim().parse().ok()).collect();
        if s.status.success() && partes.len() >= 3 {
            gpu = Mapa::new().con("has_gpu", true).con("gpu_pct", partes[0]).con("vram_used_mb", partes[1]).con("vram_total_mb", partes[2]);
        }
    }
    base.con("gpu", gpu)
}

/// `GET /api/system/stats`
pub async fn stats() -> Response {
    tokio::task::spawn_blocking(|| ok(estadisticas())).await.unwrap_or_else(|_| error_500())
}

/// `GET /api/system/health`: ¿puede este equipo con el modelo elegido?
pub async fn salud(State(state): State<AppState>) -> Response {
    let raiz = state.base_dir.clone();
    tokio::task::spawn_blocking(move || {
        let stats = estadisticas();
        let gpu = stats.mapa("gpu").cloned().unwrap_or_default();
        let total = gpu.num_o("vram_total_mb", 0.0);
        let libre = (total - gpu.num_o("vram_used_mb", 0.0)).max(0.0);
        let detalle = ollama::modelos_detallados(&raiz);
        let online = detalle.verdad("online");
        let activo = motor::config_ia().get("agent1_model").cloned().unwrap_or(Valor::Nulo);
        let mut evaluados: Vec<Mapa> = if online { detalle.lista("models").unwrap_or(&[]).to_vec() } else { Vec::new() }
            .into_iter()
            .filter_map(|m| if let Valor::Mapa(m) = m { Some(m) } else { None })
            .map(|m| {
                // regla práctica: un modelo necesita algo más de VRAM que su tamaño en disco
                let necesita = (m.num_o("size_gb", 0.0) * 1024.0 * 1.2).trunc() as i64;
                Mapa::new()
                    .con("name", m.get("name").cloned().unwrap_or(Valor::Nulo))
                    .con("size_gb", m.get("size_gb").cloned().unwrap_or(Valor::Nulo))
                    .con("estimated_vram_mb", necesita)
                    .con("fits_in_gpu", total != 0.0 && necesita as f64 <= total)
                    .con("fits_now", libre != 0.0 && necesita as f64 <= libre)
                    .con("is_active", m.get("name") == Some(&activo))
            })
            .collect();
        let mut avisos = Vec::new();
        if !online {
            avisos.push("Ollama no responde: el tutor y los ejercicios no funcionarán.".to_string());
        }
        if !gpu.verdad("has_gpu") {
            avisos.push("Sin GPU detectada: la inferencia irá por CPU y será notablemente más lenta.".to_string());
        }
        if let Some(a) = evaluados.iter().find(|m| m.verdad("is_active")) {
            if !a.verdad("fits_in_gpu") {
                avisos.push(format!(
                    "El modelo activo ({}) necesita ~{} MB y la GPU tiene {} MB: se descargará parcialmente a RAM.",
                    a.valor("name").texto_py(),
                    a.valor("estimated_vram_mb").texto_py(),
                    gpu.get("vram_total_mb").cloned().unwrap_or(Valor::Entero(0)).texto_py()
                ));
            }
        }
        evaluados.sort_by_key(|m| !m.verdad("fits_now")); // sorted(key=not fits_now): estable
        let libre_v = match gpu.get("vram_total_mb") {
            Some(Valor::Real(_)) => Valor::Real(libre),
            _ => Valor::Entero(libre as i128),
        };
        ok(Mapa::new()
            .con("ollama_online", online)
            .con("cpu_pct", stats.get("cpu_pct").cloned().unwrap_or(Valor::Nulo))
            .con("ram_total_gb", stats.get("ram_total_gb").cloned().unwrap_or(Valor::Nulo))
            .con("gpu", gpu)
            .con("vram_free_mb", libre_v)
            .con("active_model", activo)
            .con("models", Valor::Lista(evaluados.into_iter().map(Valor::Mapa).collect()))
            .con("warnings", Valor::Lista(avisos.into_iter().map(Valor::from).collect())))
    })
    .await
    .unwrap_or_else(|_| error_500())
}

// =========================================================================== Inicio

fn ahora_local() -> (i64, String) {
    let iso = prig_plataforma::py::ahora_iso();
    let hora = iso.get(11..13).and_then(|h| h.parse().ok()).unwrap_or(0);
    (hora, iso.chars().take(19).collect())
}

/// Un bloque de Inicio: su valor, o el vacío y su error apuntado (`_bloque`)
fn bloque(errores: &mut Mapa, nombre: &str, vacio: Valor, r: Result<Valor, String>) -> Valor {
    match r {
        Ok(v) => v,
        Err(e) => {
            errores.poner(nombre, e.chars().take(300).collect::<String>());
            vacio
        }
    }
}

/// `x or vacio`
fn o(v: Valor, vacio: Valor) -> Valor {
    if v.verdad() { v } else { vacio }
}

fn lista_de(v: Vec<Mapa>) -> Valor {
    Valor::Lista(v.into_iter().map(Valor::Mapa).collect())
}

fn fallo<E: std::fmt::Debug>(e: E) -> String {
    format!("{e:?}")
}

fn temperaturas(raiz: &Path) -> Valor {
    let r = vivo::recursos(raiz);
    let lectura = match r.monitor().lectura(3.0) {
        Valor::Mapa(m) => m,
        _ => Mapa::new(),
    };
    let de = |tipo: &str| {
        lectura
            .lista("componentes")
            .unwrap_or(&[])
            .iter()
            .find_map(|c| match c {
                Valor::Mapa(c) if c.texto("tipo") == Some(tipo) => Some(c.get("temp").cloned().unwrap_or(Valor::Nulo)),
                _ => None,
            })
            .unwrap_or(Valor::Nulo)
    };
    let (limite, _) = r.limite_y_reanudar();
    let pausa = r.gob.lock().map(|g| g.pausa.is_some()).unwrap_or(false);
    Valor::Mapa(Mapa::new().con("gpu", de("gpu")).con("cpu", de("cpu")).con("limite", limite).con("pausa", pausa))
}

/// `GET /api/inicio`: todo lo de la pantalla de Inicio en una petición; cada bloque falla por separado
pub async fn resumen(State(state): State<AppState>) -> Response {
    let espacio = crate::routes::workspace::espacio_de_trabajo(&state).await;
    let (raiz, cfg) = (state.base_dir.clone(), state.config_path.to_string_lossy().into_owned());
    tokio::task::spawn_blocking(move || {
        let perfil = match inicio::perfil() {
            Ok(p) => p,
            Err(_) => return error_500(),
        };
        let mut errores = Mapa::new();
        let dir = crate::routes::desafios::carpeta_base().join("desafios");
        let lecturas_r = prig_integrations::kaggle::resumen_lecturas().map(lista_de).map_err(fallo);
        let progreso = {
            let lecturas = prig_integrations::kaggle::resumen_lecturas().unwrap_or_default();
            let r = prig_aprendizaje::progreso::resumen(&dir, Some(&espacio), 120, lecturas).map(Valor::Mapa).map_err(|_| "progreso".to_string());
            o(bloque(&mut errores, "progreso", Valor::Mapa(Mapa::new()), r), Valor::Mapa(Mapa::new()))
        };
        let historial = {
            let r = prig_aprendizaje::desafios::historial(&dir, None, None, None, 30).map(lista_de).map_err(|_| "historial".to_string());
            o(bloque(&mut errores, "historial", Valor::Lista(vec![]), r), Valor::Lista(vec![]))
        };
        let lecturas = o(bloque(&mut errores, "lecturas", Valor::Lista(vec![]), lecturas_r), Valor::Lista(vec![]));
        let guardado = {
            let r = prig_integrations::kaggle::recientes(12).map(lista_de).map_err(fallo);
            o(bloque(&mut errores, "colecciones_recientes", Valor::Lista(vec![]), r), Valor::Lista(vec![]))
        };
        let descargas = {
            let r = prig_integrations::kaggle_datos::mis_datos(&espacio).map(lista_de).map_err(fallo);
            o(bloque(&mut errores, "descargas", Valor::Lista(vec![]), r), Valor::Lista(vec![]))
        };
        let ejercicios = o(lista_de(prig_aprendizaje::telemetria::recientes(&espacio, 12)), Valor::Lista(vec![]));
        let prog = match &progreso {
            Valor::Mapa(m) => m.clone(),
            _ => Mapa::new(),
        };
        let mut sub = Mapa::new();
        for k in ["desafios", "actividades", "racha", "conceptos", "fuertes", "flojos", "siguientes", "rutas"] {
            sub.poner(k, prog.get(k).cloned().unwrap_or(Valor::Nulo));
        }
        let actividad_dia = o(prog.get("actividad").cloned().unwrap_or(Valor::Nulo), Valor::Mapa(Mapa::new()));
        let semana = inicio::semana(&actividad_dia, 7).map(Valor::Lista).unwrap_or(Valor::Lista(vec![]));
        let actividad = inicio::actividad(&historial, &lecturas, &guardado, &descargas, &ejercicios, 14).map(Valor::Lista).unwrap_or(Valor::Lista(vec![]));
        let gestor = prig_modelos::gestion::Gestor { base: ollama::base_url() };
        let modelos = bloque(&mut errores, "modelos", Valor::Lista(vec![]), gestor.instalados().map(Valor::Lista).map_err(fallo));
        let cargados = bloque(&mut errores, "cargados", Valor::Lista(vec![]), gestor.cargados().map(Valor::Lista).map_err(fallo));
        let modelo_tutor = motor::config_ia().get("agent1_model").cloned().unwrap_or(Valor::Nulo);
        let base = espacio.to_string_lossy().into_owned();
        let nombre = std::path::Path::new(&base).file_name().map(|n| n.to_string_lossy().into_owned()).filter(|n| !n.is_empty()).unwrap_or_else(|| base.clone());
        let recientes = bloque(&mut errores, "recientes", Valor::Lista(vec![]), ide::recientes(&cfg, &base).map(Valor::Lista).map_err(|e| e.texto()));
        let colecciones = {
            let r = prig_integrations::kaggle::listado().map(|m| m.get("colecciones").cloned().unwrap_or(Valor::Lista(vec![]))).map_err(fallo);
            o(bloque(&mut errores, "colecciones", Valor::Lista(vec![]), r), Valor::Lista(vec![]))
        };
        let primeros = |v: &Valor, n: usize| match v {
            Valor::Lista(l) => Valor::Lista(l.iter().take(n).cloned().collect()),
            otro => otro.clone(),
        };
        let (hora, generado) = ahora_local();
        ok(Mapa::new()
            .con("perfil", perfil)
            .con("hora", hora)
            .con("progreso", sub)
            .con("semana", semana)
            .con("actividad", actividad)
            .con("modelos", modelos)
            .con("cargados", cargados)
            .con("modelo_tutor", modelo_tutor)
            .con("gemini", gemini::estado())
            .con("sistema", estadisticas())
            .con("temperaturas", temperaturas(&raiz))
            .con("proyecto", Mapa::new().con("path", base.as_str()).con("name", nombre))
            .con("recientes", recientes)
            .con(
                "kaggle",
                Mapa::new()
                    .con("lecturas", primeros(&lecturas, 4))
                    .con("colecciones", primeros(&colecciones, 6))
                    .con("recientes", guardado)
                    .con("cuenta", prig_integrations::kaggle::estado()),
            )
            .con("errores", errores)
            .con("generado", generado))
    })
    .await
    .unwrap_or_else(|_| error_500())
}

/// `GET /api/inicio/perfil`
pub async fn perfil() -> Response {
    tokio::task::spawn_blocking(|| match inicio::perfil() {
        Ok(p) => ok(p),
        Err(_) => error_500(),
    })
    .await
    .unwrap_or_else(|_| error_500())
}

const TEXTO_OPC: Tipo = Tipo::Opcional(&Tipo::Texto);
const BOOL_OPC: Tipo = Tipo::Opcional(&Tipo::Booleano);
const LISTA_OPC: Tipo = Tipo::Opcional(&Tipo::Lista(&Tipo::Texto));

/// `PATCH /api/inicio/perfil`: lo enviado que no sea null
pub async fn guardar_perfil(b: Bytes) -> Response {
    let m = match cuerpo::modelo(&b) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let campos: [(&str, &Tipo, bool); 5] =
        [("nombre", &TEXTO_OPC, false), ("objetivo", &TEXTO_OPC, false), ("nivel", &TEXTO_OPC, false), ("mostrar_al_abrir", &BOOL_OPC, false), ("favoritas", &LISTA_OPC, false)];
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
    tokio::task::spawn_blocking(move || match inicio::guardar_perfil(&cambios) {
        Ok(p) => ok(p),
        Err(_) => error_500(),
    })
    .await
    .unwrap_or_else(|_| error_500())
}
