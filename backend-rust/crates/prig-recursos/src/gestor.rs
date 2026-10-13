//! Gestor (backend/recursos/gestor.py): la fachada de recursos que usa el resto de Prig. Aquí están sus decisiones
//! (qué medidas valen, el estado en vivo con sus avisos, la recomendación ajustada por lo probado); las cachés y el
//! encadenado con las demás piezas siguen en la fachada de Python mientras su anfitrión sea Python.

use crate::calculadora::GB;
use crate::valor::{fijo, redondear, Mapa, Valor};

fn texto_o_vacio(v: Option<&Valor>) -> String {
    match v {
        Some(Valor::Texto(t)) => t.clone(),
        _ => String::new(),
    }
}

/// Calidad del canario por modelo: de cada modelo, la prueba más reciente que salió bien y midió calidad
pub fn medidas(pruebas: &Mapa) -> Mapa {
    let mut por_modelo = Mapa::new();
    for (clave, p) in pruebas.iter() {
        let modelo = clave.split('|').next().unwrap_or("");
        let Valor::Mapa(p) = p else { continue };
        if !p.verdad("ok") || p.get("calidad").is_none_or(Valor::es_nulo) {
            continue;
        }
        let mejor = match por_modelo.mapa(modelo) {
            None => true,
            Some(previa) if previa.is_empty() => true,
            Some(previa) => texto_o_vacio(p.get("fecha")) > texto_o_vacio(previa.get("fecha")),
        };
        if mejor {
            por_modelo.poner(modelo, p.clone());
        }
    }
    por_modelo
}

/// Lo que se ve en vivo: GPU, estado térmico, RAM y swap, energía, Ollama, otros programas en la GPU y los avisos
pub fn estado_vivo(rad: &Mapa, limite: f64, reanudar: f64) -> Mapa {
    let vacio = Mapa::new();
    let g = match rad.lista("gpus").filter(|l| !l.is_empty()).map(|l| &l[0]) {
        Some(Valor::Mapa(g)) => g,
        _ => &vacio,
    };
    let mem = rad.mapa("memoria").cloned().unwrap_or_default();
    let temp = g.get("temperatura_c").filter(|v| !v.es_nulo()).and_then(Valor::num);
    let termico = match temp {
        None => "desconocido",
        Some(t) if t >= limite => "caliente",
        Some(t) if t >= reanudar => "templado",
        _ => "normal",
    };
    let mut avisos: Vec<Valor> = Vec::new();
    let ajenos: Vec<Valor> = match g.get("otros_procesos") {
        Some(Valor::Lista(l)) => l.clone(),
        _ => Vec::new(),
    };
    if !ajenos.is_empty() {
        let mb: f64 = ajenos.iter().map(|p| if let Valor::Mapa(p) = p { p.num_o("mb", 0.0) } else { 0.0 }).sum();
        let mut nombres: Vec<String> =
            ajenos.iter().filter_map(|p| if let Valor::Mapa(p) = p { Some(p.valor("proceso").texto_py()) } else { None }).collect();
        nombres.sort();
        nombres.dedup();
        avisos.push(
            format!(
                "Otros programas usan {} GB de la GPU ({}): queda menos sitio para los modelos.",
                fijo(mb / 1024.0, 1),
                nombres.join(", ")
            )
            .into(),
        );
    }
    let swap = mem.num_o("swap_usada", 0.0);
    if swap > GB {
        avisos.push(
            format!("El sistema está usando {} GB de swap: con un modelo repartido en RAM irá muy lento.", fijo(swap / GB, 1))
                .into(),
        );
    }
    let ener = rad.mapa("energia").cloned().unwrap_or_default();
    if ener.verdad("con_bateria") {
        avisos.push("Estás con batería: la GPU rinde menos y se agota rápido.".into());
    }
    if termico == "caliente" {
        avisos.push(
            format!(
                "La GPU está a {} °C (límite {}). Los flujos se pausan hasta que baje a {}.",
                fijo(temp.unwrap_or(f64::NAN), 0),
                fijo(limite, 0),
                fijo(reanudar, 0)
            )
            .into(),
        );
    }
    let mut gpu = Mapa::new();
    for k in ["nombre", "vram_total_mb", "vram_usada_mb", "temperatura_c", "consumo_w", "uso_pct"] {
        gpu.poner(k, g.valor(k).clone());
    }
    let ollama_rad = rad.mapa("ollama").cloned().unwrap_or_default();
    let mut ollama = Mapa::new();
    for k in ["responde", "version", "dueno", "modelos_cargados"] {
        ollama.poner(k, ollama_rad.valor(k).clone());
    }
    Mapa::new()
        .con("gpu", gpu)
        .con("termico", termico)
        .con("ram_disponible_gb", redondear(mem.num_o("ram_disponible", 0.0) / GB, 1))
        .con("swap_usada_gb", redondear(swap / GB, 1))
        .con("energia", ener)
        .con("ollama", ollama)
        .con("otros_procesos_gpu", ajenos)
        .con("avisos", avisos)
}

/// La recomendación con lo probado en esta máquina (si la prueba tuvo que bajar el contexto, se respeta) y un resumen
/// de la ficha
pub fn completar_recomendacion(mut rec: Mapa, prueba: Option<&Mapa>, ficha: &Mapa) -> Mapa {
    if let Some(p) = prueba.filter(|p| !p.is_empty()) {
        rec.poner("prueba", p.clone());
        let ctx_prueba = p.mapa("opciones").and_then(|o| o.get("num_ctx")).and_then(Valor::num).unwrap_or(1e9);
        let ctx_rec = rec.mapa("opciones").map(|o| o.num_o("num_ctx", 0.0)).unwrap_or(0.0);
        if p.verdad("ok") && ctx_prueba < ctx_rec {
            let nuevo = p.mapa("opciones").map(|o| o.valor("num_ctx").clone()).unwrap_or(Valor::Nulo);
            if let Some(Valor::Mapa(o)) = rec.get_mut("opciones") {
                o.poner("num_ctx", nuevo);
            }
            rec.poner("ajustada_por_prueba", true);
        }
    }
    let mut resumen = Mapa::new();
    for k in [
        "nombre", "origen", "arquitectura", "cuantizacion", "parametros", "parametros_activos", "es_moe", "capas",
        "contexto_max", "piensa", "vision", "herramientas", "estimada",
    ] {
        resumen.poner(k, ficha.valor(k).clone());
    }
    resumen.poner("gb", redondear(ficha.num_o("bytes_peso", 0.0) / GB, 2));
    rec.con("ficha", resumen)
}
