//! Calculadora (backend/recursos/calculadora.py): cuánta memoria ocupará un modelo, dónde irá y a qué velocidad.
//!
//! Las fórmulas están calibradas contra mediciones reales, no contra hojas de datos. Sobre una RTX 4050 portátil
//! de 6 GB, con qwen2.5-coder:7b, qwen3:14b y qwen3:30b-a3b a contextos de 2048, 4096 y 8192: memoria total con un
//! error medio del 0,3 % (máximo 0,5 %), reparto GPU/CPU exacto a un punto, velocidad con un error medio del 11 %
//! (máximo 24 %).
//!
//! MEMORIA. Total = pesos + caché KV + búfer de cómputo. El búfer resultó casi constante: −0,15 GB cuando el modelo
//! cabe entero y +0,25 GB cuando se reparte entre GPU y CPU.
//!
//! HASTA DÓNDE LLENA OLLAMA LA GPU. Nunca pasó de 4,85 GB en una tarjeta de 6,1. Forzar más capas a mano no aceleró
//! nada y con 24 reventó por falta de memoria: esta calculadora predice el reparto automático de Ollama.
//!
//! VELOCIDAD. Generar un token obliga a leer los parámetros activos una vez, lo de la GPU al ancho de la VRAM y lo
//! de la RAM al de la RAM:
//!     t_token = fracción_gpu × activos / ancho_gpu + (1 − fracción_gpu) × activos / ancho_cpu
//!
//! Los textos y los números redondeados salen idénticos a los de Python (comprobado con miles de casos al azar).

use crate::ficha::kv_bytes;
use crate::perfiles::{self, Pensar, Perfil};
use crate::valor::{fijo, redondear, redondear_entero, repr_real, Mapa, Valor};
use std::cmp::Ordering;

pub const GB: f64 = 1e9;

// Valores medidos en la máquina de referencia. Solo se usan hasta que la calibración de la máquina del usuario los
// sustituye por los suyos.
pub const OVERHEAD_ENTERO: f64 = -0.15 * GB;
pub const OVERHEAD_PARCIAL: f64 = 0.25 * GB;
pub const MARGEN_RAM: f64 = 3.0 * GB; // lo que se deja al sistema antes de hablar de swap
pub const FACTOR_BANCO_RAM: f64 = 3.75; // medida en Python puro → ancho efectivo en inferencia

/// Ancho de banda de memoria de GPUs conocidas, en GB/s. El efectivo en inferencia resultó ser un 93 % del nominal
/// (RTX 4050 portátil: 192 nominal, 178 medido).
pub const ANCHO_GPU: &[(&str, i64)] = &[
    ("rtx 4050", 192),
    ("rtx 4060 laptop", 192),
    ("rtx 4060 ti", 288),
    ("rtx 4060", 272),
    ("rtx 4070 laptop", 256),
    ("rtx 4070 ti", 504),
    ("rtx 4070", 504),
    ("rtx 4080", 717),
    ("rtx 4090", 1008),
    ("rtx 3050", 224),
    ("rtx 3060 laptop", 336),
    ("rtx 3060", 360),
    ("rtx 3070", 448),
    ("rtx 3080", 760),
    ("rtx 3090", 936),
    ("rtx 2060", 336),
    ("rtx 2070", 448),
    ("rtx 2080", 448),
    ("gtx 1660", 192),
    ("gtx 1650", 128),
    ("rtx 5060", 448),
    ("rtx 5070", 672),
    ("rtx 5080", 960),
    ("rtx 5090", 1792),
    ("rx 7900", 800),
    ("rx 7800", 576),
    ("rx 7600", 288),
    ("rx 6700", 360),
    ("m1 max", 400),
    ("m1 pro", 200),
    ("m1", 68),
    ("m2 max", 400),
    ("m2 pro", 200),
    ("m2", 100),
    ("m3 max", 400),
    ("m3 pro", 150),
    ("m3", 100),
    ("m4 max", 546),
    ("m4 pro", 273),
    ("m4", 120),
];
pub const EFICIENCIA_GPU: f64 = 0.93;

/// Coste fijo por capa y token (lanzar núcleos, enrutar expertos, sincronizar). Sin él, en una GPU grande donde
/// leer pesos ya no es el cuello de botella, un MoE salía a 440 tok/s cuando rinde en torno a 200.
pub const LATENCIA_CAPA_S: f64 = 0.04e-3;
/// Medido: dos peticiones simultáneas rinden 1,32 veces lo que una, no el doble
pub const GANANCIA_RANURA: f64 = 0.32;

pub const VEREDICTOS: &[(&str, &str)] = &[
    ("entero", "Entero en GPU"),
    ("ajustando", "Entero ajustando"),
    ("parcial", "Repartido GPU + RAM"),
    ("lento", "Cabe, pero lento para esto"),
    ("solo_cpu", "Solo CPU"),
    ("no_viable", "No viable"),
    ("embeddings", "Embeddings en CPU"),
];

fn etiqueta(veredicto: &str) -> &'static str {
    VEREDICTOS.iter().find(|(k, _)| *k == veredicto).map(|(_, e)| *e).unwrap_or("")
}

/// `min(a, b)` y `max(a, b)` de Python: ante un empate, el primero
fn min_py(a: f64, b: f64) -> f64 {
    if b < a {
        b
    } else {
        a
    }
}

fn max_py(a: f64, b: f64) -> f64 {
    if b > a {
        b
    } else {
        a
    }
}

// =========================================================================== servidor

/// Lo que el servidor de Ollama aplica de verdad. Son ajustes del SERVIDOR, no de cada petición: un único Ollama no
/// puede tener la caché en q8_0 para el tutor y en f16 para la extracción a la vez.
#[derive(Debug, Clone, PartialEq)]
pub struct Servidor {
    pub kv: String,
    pub paralelo: i64,
    pub flash_attention: bool,
    pub max_modelos: Option<i64>,
}

impl Servidor {
    pub fn mapa(&self) -> Mapa {
        Mapa::new()
            .con("kv", self.kv.clone())
            .con("paralelo", self.paralelo)
            .con("flash_attention", self.flash_attention)
            .con("max_modelos", self.max_modelos)
    }
}

/// `servidor_efectivo` de Python: rellena los valores por defecto
pub fn servidor_efectivo(entorno: &Mapa) -> Servidor {
    let entero = |clave: &str, defecto: i64| match entorno.get(clave).and_then(Valor::entero) {
        Some(n) => n.clamp(1, i64::MAX as i128) as i64,
        None => defecto,
    };
    let kv = match entorno.get("OLLAMA_KV_CACHE_TYPE") {
        Some(v) if v.verdad() => v.texto_py().to_lowercase(),
        _ => "f16".into(),
    };
    let flash = match entorno.get("OLLAMA_FLASH_ATTENTION") {
        Some(v) => matches!(v.texto_py().to_lowercase().as_str(), "1" | "true" | "yes"),
        None => false,
    };
    let max_modelos = entero("OLLAMA_MAX_LOADED_MODELS", 0);
    Servidor {
        kv,
        paralelo: entero("OLLAMA_NUM_PARALLEL", 1),
        flash_attention: flash,
        max_modelos: if max_modelos == 0 { None } else { Some(max_modelos) },
    }
}

// =========================================================================== máquina

/// Lo que la calculadora necesita saber de la máquina, ya destilado: la radiografía del detector con lo calibrado.
/// Cada valor recuerda si sale de una medida («medido») o de lo previo («previo»).
#[derive(Debug, Clone)]
pub struct Maquina {
    pub radiografia: Mapa,
    pub hay_gpu: bool,
    pub gpu_nombre: String,
    pub unificada: bool,
    pub vram_total: f64,
    pub vram_libre: f64,
    pub ram_disponible: f64,
    pub ram_total: f64,
    pub nucleos: Valor,
    pub flash_attention: bool,
    pub presupuesto_gpu: f64,
    pub origen_presupuesto: &'static str,
    pub vram_parcial: f64,
    pub ancho_gpu: f64,
    pub origen_ancho_gpu: &'static str,
    pub ancho_cpu: f64,
    pub origen_ancho_cpu: &'static str,
    pub overhead_entero: f64,
    pub overhead_parcial: f64,
    pub servidor: Servidor,
}

impl Maquina {
    pub fn new(radiografia: &Mapa, calibracion: Option<&Mapa>) -> Maquina {
        let vacio = Mapa::new();
        let cal = calibracion.unwrap_or(&vacio);
        let gpus = radiografia.lista("gpus").unwrap_or(&[]);
        // `g is not None` y `if g` no son lo mismo en Python: una GPU sin datos ({}) cuenta como GPU, pero sin nada
        let g = gpus.first();
        let gv = match g {
            Some(Valor::Mapa(m)) if !m.is_empty() => Some(m),
            _ => None,
        };
        let mem = radiografia.mapa("memoria").cloned().unwrap_or_default();

        let hay_gpu = g.is_some_and(|v| !v.es_nulo());
        let gpu_nombre = gv.and_then(|g| g.texto("nombre")).unwrap_or("").to_string();
        let unificada = gv.is_some_and(|g| g.verdad("memoria_unificada"));
        let vram_total = match gv {
            Some(g) => match g.get("vram_total_mb") {
                Some(v) if v.verdad() => v.num().unwrap_or(0.0) * 1_048_576.0,
                _ => 0.0,
            },
            None => 0.0,
        };
        let procesos = gv.and_then(|g| g.lista("otros_procesos")).unwrap_or(&[]);
        let ajena: f64 = procesos
            .iter()
            .map(|p| match p {
                Valor::Mapa(p) => p.num_o("mb", 0.0),
                _ => 0.0,
            })
            .sum::<f64>()
            * 1_048_576.0;
        let vram_libre = max_py(0.0, vram_total - ajena);
        let flash_attention = gv.is_some_and(|g| g.verdad("flash_attention"));

        let (presupuesto_gpu, origen_presupuesto) = if cal.contiene("presupuesto_gpu") {
            (cal.num_o("presupuesto_gpu", 0.0), "medido")
        } else {
            let reserva = min_py(1.6 * GB, max_py(0.6 * GB, 0.245 * vram_total));
            (max_py(0.0, vram_libre - reserva), "previo")
        };
        let vram_parcial = cal.num_o("vram_parcial", presupuesto_gpu - 0.1 * GB);

        let (ancho_gpu, origen_ancho_gpu) = if cal.contiene("ancho_gpu") {
            (cal.num_o("ancho_gpu", 0.0), "medido")
        } else {
            (ancho_gpu_previo(&gpu_nombre), "previo")
        };
        let (ancho_cpu, origen_ancho_cpu) = if cal.contiene("ancho_cpu") {
            (cal.num_o("ancho_cpu", 0.0), "medido")
        } else {
            let banco = match radiografia.get("ancho_banda_ram_gbps") {
                Some(v) if v.verdad() => v.num().unwrap_or(10.0),
                _ => 10.0,
            };
            (max_py(10.0, min_py(120.0, banco * FACTOR_BANCO_RAM)), "previo")
        };

        let entorno = radiografia
            .mapa("ollama")
            .and_then(|o| match o.get("entorno") {
                Some(Valor::Mapa(m)) => Some(m.clone()),
                _ => None,
            })
            .unwrap_or_default();

        Maquina {
            radiografia: radiografia.clone(),
            hay_gpu,
            gpu_nombre,
            unificada,
            vram_total,
            vram_libre,
            ram_disponible: mem.num_o("ram_disponible", 0.0),
            ram_total: mem.num_o("ram_total", 0.0),
            nucleos: radiografia.mapa("cpu").and_then(|c| c.get("nucleos_fisicos").cloned()).unwrap_or(Valor::Entero(1)),
            flash_attention,
            presupuesto_gpu,
            origen_presupuesto,
            vram_parcial,
            ancho_gpu,
            origen_ancho_gpu,
            ancho_cpu,
            origen_ancho_cpu,
            overhead_entero: cal.num_o("overhead_entero", OVERHEAD_ENTERO),
            overhead_parcial: cal.num_o("overhead_parcial", OVERHEAD_PARCIAL),
            servidor: servidor_efectivo(&entorno),
        }
    }

    pub fn calibrada(&self) -> bool {
        [self.origen_presupuesto, self.origen_ancho_gpu, self.origen_ancho_cpu].contains(&"medido")
    }

    pub fn resumen(&self) -> Mapa {
        Mapa::new()
            .con("gpu", if self.gpu_nombre.is_empty() { "sin GPU" } else { &self.gpu_nombre })
            .con("vram_total_gb", redondear(self.vram_total / GB, 2))
            .con("vram_libre_gb", redondear(self.vram_libre / GB, 2))
            .con("presupuesto_gpu_gb", redondear(self.presupuesto_gpu / GB, 2))
            .con("ram_disponible_gb", redondear(self.ram_disponible / GB, 1))
            .con("ancho_gpu_gbps", redondear_entero(self.ancho_gpu))
            .con("ancho_cpu_gbps", redondear_entero(self.ancho_cpu))
            .con("memoria_unificada", self.unificada)
            .con(
                "origen",
                Mapa::new()
                    .con("presupuesto", self.origen_presupuesto)
                    .con("ancho_gpu", self.origen_ancho_gpu)
                    .con("ancho_cpu", self.origen_ancho_cpu),
            )
    }
}

/// Las claves más largas primero («rtx 4060 ti» antes que «rtx 4060»); a igual largo, en el orden de la tabla
fn ancho_gpu_previo(gpu_nombre: &str) -> f64 {
    let nombre = gpu_nombre.to_lowercase();
    let mut claves: Vec<&(&str, i64)> = ANCHO_GPU.iter().collect();
    claves.sort_by_key(|(k, _)| std::cmp::Reverse(k.chars().count()));
    for (clave, ancho) in claves {
        if nombre.contains(clave) {
            return *ancho as f64 * EFICIENCIA_GPU;
        }
    }
    200.0 * EFICIENCIA_GPU
}

// =========================================================================== estimar

/// Una configuración concreta: memoria, reparto y velocidad
#[derive(Debug, Clone, PartialEq)]
pub struct Estimacion {
    pub ctx: i64,
    pub paralelo: i64,
    pub kv: String,
    pub total_gb: f64,
    pub cache_gb: f64,
    pub en_gpu_gb: f64,
    pub en_ram_gb: f64,
    pub fraccion_gpu: f64,
    pub donde: &'static str,
    pub tok_s: f64,
    pub tok_s_rango: [f64; 2],
    pub cabe_en_ram: bool,
    pub riesgo_swap: bool,
}

impl Estimacion {
    pub fn mapa(&self) -> Mapa {
        Mapa::new()
            .con("ctx", self.ctx)
            .con("paralelo", self.paralelo)
            .con("kv", self.kv.clone())
            .con("total_gb", self.total_gb)
            .con("cache_gb", self.cache_gb)
            .con("en_gpu_gb", self.en_gpu_gb)
            .con("en_ram_gb", self.en_ram_gb)
            .con("fraccion_gpu", self.fraccion_gpu)
            .con("donde", self.donde)
            .con("tok_s", self.tok_s)
            .con("tok_s_rango", Valor::Lista(vec![self.tok_s_rango[0].into(), self.tok_s_rango[1].into()]))
            .con("cabe_en_ram", self.cabe_en_ram)
            .con("riesgo_swap", self.riesgo_swap)
    }
}

/// La atención cuesta más cuanto más contexto: ~3,5 % cada vez que se dobla
pub fn penalizacion_contexto(ctx: f64) -> f64 {
    1.0 + 0.035 * (max_py(ctx, 2048.0) / 2048.0).log2()
}

/// `estimar` de Python. La ficha tiene que traer «bytes_peso» (quien llama lo comprueba).
pub fn estimar(ficha: &Mapa, maq: &Maquina, ctx: i64, paralelo: i64, kv: &str) -> Estimacion {
    let peso = ficha.num_o("bytes_peso", 0.0);
    let cache = kv_bytes(ficha, ctx, paralelo, kv) as f64;
    let activos = peso * ficha.num_o("fraccion_activa", 1.0) / GB;

    let (total, frac, donde) = if !maq.hay_gpu {
        (peso + cache + maq.overhead_parcial, 0.0, "cpu")
    } else {
        let entero = peso + cache + maq.overhead_entero;
        if entero <= maq.presupuesto_gpu {
            (entero, 1.0, "gpu")
        } else {
            let total = peso + cache + maq.overhead_parcial;
            let frac = if maq.vram_parcial > 0.0 { min_py(1.0, max_py(0.0, maq.vram_parcial / total)) } else { 0.0 };
            (total, frac, if frac > 0.02 { "repartido" } else { "cpu" })
        }
    };

    let en_gpu = total * frac;
    let en_ram = total - en_gpu;
    // En memoria unificada, lo de la «GPU» también sale de la RAM
    let ram_necesaria = if maq.unificada { total } else { en_ram };

    let mut t = 0.0;
    if frac > 0.0 {
        t += frac * activos / maq.ancho_gpu;
    }
    if frac < 1.0 {
        t += (1.0 - frac) * activos / maq.ancho_cpu;
    }
    if t > 0.0 {
        let capas = match ficha.get("capas") {
            Some(v) if v.verdad() => v.num().unwrap_or(32.0),
            _ => 32.0,
        };
        t += capas * LATENCIA_CAPA_S;
    }
    let tok_s = if t > 0.0 { 1.0 / t / penalizacion_contexto(ctx as f64) } else { 0.0 };

    let cabe_en_ram = ram_necesaria <= max_py(0.0, maq.ram_disponible - MARGEN_RAM);
    Estimacion {
        ctx,
        paralelo,
        kv: kv.to_string(),
        total_gb: redondear(total / GB, 2),
        cache_gb: redondear(cache / GB, 2),
        en_gpu_gb: redondear(en_gpu / GB, 2),
        en_ram_gb: redondear(en_ram / GB, 2),
        fraccion_gpu: redondear(frac, 3),
        donde,
        tok_s: redondear(tok_s, 1),
        // Error medido de la fórmula: ±25 % en el peor caso
        tok_s_rango: [redondear(tok_s * 0.75, 1), redondear(tok_s * 1.25, 1)],
        cabe_en_ram,
        riesgo_swap: !cabe_en_ram,
    }
}

// =========================================================================== veredicto y recomendación

/// Combinaciones que tiene sentido probar para este perfil
fn candidatos(ficha: &Mapa, prf: &Perfil, tirador: &str, paralelo_servidor: i64) -> Vec<(i64, &'static str, i64)> {
    let ctx_max = prf.ctx_max as f64;
    let tope = match ficha.get("contexto_max") {
        Some(v) if v.verdad() => min_py(ctx_max, v.num().unwrap_or(ctx_max)),
        _ => ctx_max,
    };
    let mut contextos: Vec<i64> = [prf.ctx_min, prf.ctx_preferido, 4096, 8192, 16384, prf.ctx_max]
        .into_iter()
        .filter(|&c| prf.ctx_min <= c && (c as f64) <= tope)
        .collect();
    contextos.sort();
    contextos.dedup();
    if contextos.is_empty() {
        contextos.push(prf.ctx_min);
    }
    let mut kvs = vec!["f16"];
    if prf.kv_cuantizable && tirador != "calidad" {
        kvs.push("q8_0");
    }
    let mut paralelos = vec![1, prf.paralelo_deseado, paralelo_servidor];
    paralelos.sort();
    paralelos.dedup();
    let mut salida = Vec::new();
    for &c in &contextos {
        for &k in &kvs {
            for &p in &paralelos {
                salida.push((c, k, p));
            }
        }
    }
    salida
}

/// Tokens por segundo sumando todas las ranuras
pub fn rendimiento(tok_s: f64, paralelo: i64) -> f64 {
    tok_s * (1.0 + GANANCIA_RANURA * (paralelo - 1) as f64)
}

fn rend(e: &Estimacion) -> f64 {
    rendimiento(e.tok_s, e.paralelo)
}

/// Orden de preferencia entre combinaciones, de lo que más pesa a lo que menos. Una tupla y no una suma de puntos:
/// con pesos, un ajuste pequeño en una constante cambia la recomendación de forma imposible de prever.
fn puntuar(e: &Estimacion, prf: &Perfil, tirador: &str) -> Vec<f64> {
    let b = |x: bool| if x { 1.0 } else { 0.0 };
    let util = e.tok_s_rango[0] >= prf.tok_s_min; // con la cota baja, como veredicto
    let ctx_llega = e.ctx.min(prf.ctx_preferido) as f64 / prf.ctx_preferido as f64;
    let sin_exceso = e.ctx <= prf.ctx_preferido;
    let kv_exacta = e.kv == "f16";
    let r = rend(e);
    // Tramos de 5 tok/s: diferencias menores son ruido (error medio medido: 11 %)
    let tramo = redondear_entero(r / 5.0) as f64;
    match tirador {
        "calidad" => vec![b(util), b(kv_exacta), ctx_llega, b(sin_exceso), r],
        "velocidad" => vec![b(util), tramo, ctx_llega, b(kv_exacta), r],
        // Equilibrado: el contexto que pide la tarea, la precisión si la tarea la exige, y dentro de eso lo más
        // rápido. Si la tarea tolera cuantizar la caché, eso no cuenta como pérdida.
        _ => {
            let precision = if !prf.kv_cuantizable { kv_exacta } else { true };
            vec![b(util), ctx_llega, b(precision), tramo, b(sin_exceso), b(kv_exacta), r]
        }
    }
}

/// Comparación de tuplas de Python
fn comparar(a: &[f64], b: &[f64]) -> Ordering {
    for (x, y) in a.iter().zip(b) {
        if x != y {
            return x.partial_cmp(y).unwrap_or(Ordering::Equal);
        }
    }
    a.len().cmp(&b.len())
}

/// `max(lista, key=puntuar)`: el primero de los mejores
fn mejor<'a>(lista: &'a [Estimacion], prf: &Perfil, tirador: &str) -> Option<(usize, &'a Estimacion)> {
    let mut mejor: Option<(usize, &Estimacion, Vec<f64>)> = None;
    for (i, e) in lista.iter().enumerate() {
        let p = puntuar(e, prf, tirador);
        if mejor.as_ref().is_none_or(|(_, _, pm)| comparar(&p, pm) == Ordering::Greater) {
            mejor = Some((i, e, p));
        }
    }
    mejor.map(|(i, e, _)| (i, e))
}

fn veredicto(e: &Estimacion, todas: &[Estimacion], prf: &Perfil, maq: &Maquina) -> &'static str {
    if !maq.hay_gpu {
        return if e.tok_s_rango[0] >= prf.tok_s_min { "solo_cpu" } else { "lento" };
    }
    if e.tok_s < 1.0 {
        return "no_viable";
    }
    // Frontera de «lento» con la cota baja del error (±25 %): un 14B estimado en 8,5 tok/s para un mínimo de 8
    // midió 4,7. Prometer lo justo y quedarse corto es peor que avisar de más.
    let lento = e.tok_s_rango[0] < prf.tok_s_min;
    if e.donde == "gpu" {
        let preferida_entera =
            todas.iter().any(|x| x.donde == "gpu" && x.ctx >= prf.ctx_preferido && x.kv == "f16");
        return if preferida_entera { "entero" } else { "ajustando" };
    }
    if lento {
        return "lento";
    }
    if e.donde == "repartido" {
        "parcial"
    } else {
        "solo_cpu"
    }
}

/// Lo que se manda en cada petición. `num_gpu` NO se fija: medido que forzar capas por encima del reparto
/// automático no acelera y provoca falta de memoria. Solo se baja al recuperarse de un OOM.
fn opciones(e: &Estimacion, prf: &Perfil, ficha: &Mapa) -> Mapa {
    let mut o = Mapa::new().con("num_ctx", e.ctx).con("keep_alive", prf.keep_alive);
    if ficha.verdad("piensa") {
        match prf.pensar {
            Pensar::Si => o.poner("think", true),
            Pensar::No => o.poner("think", false),
            _ => {}
        }
    }
    o
}

fn motivo(ficha: &Mapa, e: &Estimacion, veredicto: &str, prf: &Perfil, maq: &Maquina) -> String {
    let r = repr_real;
    match veredicto {
        "entero" | "ajustando" => {
            let libre = max_py(0.0, maq.vram_total / GB - e.total_gb);
            let mut texto = format!(
                "Cabe entero en la GPU: ocupa {} GB de tus {} (quedan {} GB). Contexto de {} tokens a unos {} tok/s.",
                r(e.total_gb),
                r(redondear(maq.vram_total / GB, 1)),
                fijo(libre, 1),
                e.ctx,
                r(e.tok_s)
            );
            if veredicto == "ajustando" {
                texto += &format!(
                    " Para caber hubo que bajar a {} tokens{}.",
                    e.ctx,
                    if e.kv != "f16" { " y cuantizar la caché" } else { "" }
                );
            }
            texto
        }
        "parcial" => {
            let mut base = format!(
                "No cabe entero: {} GB van a la GPU y {} GB a la RAM ({} % en GPU). ",
                r(e.en_gpu_gb),
                r(e.en_ram_gb),
                redondear_entero(e.fraccion_gpu * 100.0)
            );
            if ficha.verdad("es_moe") {
                base += &format!(
                    "Aun así va rápido, unos {} tok/s: es una mezcla de expertos y por cada token solo lee {} B de sus \
                     {} B de parámetros.",
                    r(e.tok_s),
                    r(redondear(ficha.num_o("parametros_activos", 0.0) / 1e9, 1)),
                    r(redondear(ficha.num_o("parametros", 0.0) / 1e9, 1))
                );
            } else {
                base += &format!("Unos {} tok/s, suficiente para {}.", r(e.tok_s), prf.nombre.to_lowercase());
            }
            base
        }
        "lento" => format!(
            "Funciona, pero a unos {} tok/s y {} necesita al menos {}. Sirve para tareas cortas y puntuales.",
            r(e.tok_s),
            prf.nombre.to_lowercase(),
            r(prf.tok_s_min)
        ),
        "solo_cpu" => format!("Sin GPU útil: todo en RAM a unos {} tok/s.", r(e.tok_s)),
        _ => format!("{} no es viable en esta máquina para este uso.", ficha.valor("nombre").texto_py()),
    }
}

fn aviso_servidor(prf: &Perfil, srv: &Servidor) -> Option<String> {
    if srv.kv != "f16" && !prf.kv_cuantizable {
        return Some(format!(
            "El servidor tiene la caché en {}. Para {} eso resta exactitud (medido en extracción: citas verificadas \
             del 100 % al 79 %). Conviene volver a f16 antes de este trabajo.",
            srv.kv,
            prf.nombre.to_lowercase()
        ));
    }
    None
}

/// Qué se ganaría cambiando el servidor, y qué se perdería. Solo se propone si la mejora es clara (otro tramo de
/// velocidad, o pasar de repartido a entero). Cambiar la caché a q8_0 SIEMPRE lleva el aviso de lo que cuesta.
fn mejora_servidor(
    actual: &Estimacion,
    todas: &[Estimacion],
    prf: &Perfil,
    tirador: &str,
    maq: &Maquina,
) -> Option<Mapa> {
    let (_, mejor) = mejor(todas, prf, tirador)?;
    if mejor.kv == actual.kv && mejor.paralelo == actual.paralelo {
        return None;
    }
    let a_gpu = mejor.donde == "gpu" && actual.donde != "gpu";
    let mut gana = comparar(&puntuar(mejor, prf, tirador), &puntuar(actual, prf, tirador)) == Ordering::Greater
        && (redondear_entero(rend(mejor) / 5.0) > redondear_entero(rend(actual) / 5.0) || a_gpu);
    // Volver a una caché exacta en un uso que la necesita se propone siempre
    if actual.kv != "f16" && mejor.kv == "f16" && !prf.kv_cuantizable {
        gana = true;
    }
    if !gana {
        return None;
    }
    let mut cambios = Mapa::new();
    let mut contras: Vec<Valor> = Vec::new();
    if mejor.kv != maq.servidor.kv {
        cambios.poner("OLLAMA_KV_CACHE_TYPE", mejor.kv.clone());
        if mejor.kv != "f16" {
            contras.push(
                "Afecta a TODOS los usos: medido, la caché q8_0 bajó las citas verificadas de la extracción del \
                 100 % al 79 %."
                    .into(),
            );
        }
    }
    if mejor.paralelo != maq.servidor.paralelo {
        cambios.poner("OLLAMA_NUM_PARALLEL", mejor.paralelo.to_string());
        contras.push(
            format!(
                "Cada ranura reserva su propia caché: con {} ranuras los demás modelos tienen menos sitio en GPU.",
                mejor.paralelo
            )
            .into(),
        );
    }
    if cambios.texto("OLLAMA_KV_CACHE_TYPE") == Some("f16") {
        contras.push("El tutor pierde la caché compacta: le cabe menos contexto en GPU.".into());
    }
    Some(
        Mapa::new()
            .con("cambios", cambios)
            .con("estimacion", mejor.mapa())
            .con(
                "ganancia",
                format!(
                    "{} → {} tok/s{}",
                    repr_real(actual.tok_s),
                    repr_real(mejor.tok_s),
                    if a_gpu { ", y pasa a caber entero en la GPU" } else { "" }
                ),
            )
            .con("contras", contras)
            .con("requiere_reiniciar", true),
    )
}

fn sin_opcion(ficha: &Mapa, prf: &Perfil, tirador: &str, est: &Estimacion, motivo: String) -> Mapa {
    Mapa::new()
        .con("modelo", ficha.valor("nombre").clone())
        .con("perfil", prf.id)
        .con("tirador", tirador)
        .con("veredicto", "no_viable")
        .con("etiqueta", etiqueta("no_viable"))
        .con("opciones", Mapa::new())
        .con("estimacion", est.mapa())
        .con("motivo", motivo)
        .con("alternativas", Valor::Lista(vec![]))
        .con("fiabilidad", "estimada")
        .con("ficha_estimada", ficha.verdad("estimada"))
}

/// `recomendar` de Python. Error: el mensaje del KeyError de un perfil desconocido.
pub fn recomendar(ficha: &Mapa, maq: &Maquina, nombre_perfil: &str, tirador: &str) -> Result<Mapa, String> {
    let prf = perfiles::perfil(nombre_perfil)?;

    if ficha.verdad("embedding") {
        let sin_gpu = Maquina::new(&maq.radiografia.fusion(&Mapa::new().con("gpus", Valor::Lista(vec![]))), None);
        let est = estimar(ficha, &sin_gpu, 512, 1, "f16");
        return Ok(Mapa::new()
            .con("modelo", ficha.valor("nombre").clone())
            .con("perfil", nombre_perfil)
            .con("tirador", tirador)
            .con("veredicto", if est.cabe_en_ram { "embeddings" } else { "no_viable" })
            .con("etiqueta", etiqueta("embeddings"))
            .con("opciones", Mapa::new().con("num_gpu", 0).con("keep_alive", "30m"))
            .con("estimacion", est.mapa())
            .con(
                "motivo",
                "Un embebedor no genera texto: se deja en CPU para que el generador tenga la GPU entera. Medido: \
                 72 ms por pregunta y ninguna recarga del generador.",
            )
            .con("alternativas", Valor::Lista(vec![])));
    }

    let srv = &maq.servidor;
    let todas: Vec<Estimacion> = candidatos(ficha, prf, tirador, srv.paralelo)
        .into_iter()
        .map(|(c, k, p)| estimar(ficha, maq, c, p, k))
        .filter(|e| !e.riesgo_swap)
        .collect();

    // Lo que se puede aplicar YA, sin tocar el servidor. Las ranuras tienen que ser exactamente las del servidor:
    // Ollama reserva caché para todas aunque la petición sea una sola.
    let mut estimaciones: Vec<Estimacion> =
        todas.iter().filter(|e| e.kv == srv.kv && e.paralelo == srv.paralelo).cloned().collect();
    if estimaciones.is_empty() && !todas.is_empty() {
        // El servidor tiene una caché que este uso no admite (q8_0 para extraer): se evalúa igualmente con su
        // configuración real, y se avisa.
        let mut ctxs: Vec<i64> = todas.iter().map(|e| e.ctx).collect();
        ctxs.sort();
        ctxs.dedup();
        for ctx in ctxs {
            let est = estimar(ficha, maq, ctx, srv.paralelo, &srv.kv);
            if !est.riesgo_swap {
                estimaciones.push(est);
            }
        }
    }

    if estimaciones.is_empty() {
        let minimo = estimar(ficha, maq, prf.ctx_min, 1, "f16");
        let necesita = if !maq.unificada { minimo.en_ram_gb } else { minimo.total_gb };
        let motivo = format!(
            "Necesita {} GB de RAM y hay {} GB disponibles. Paginaría a disco y dejaría de responder.",
            repr_real(necesita),
            repr_real(redondear(maq.ram_disponible / GB, 1))
        );
        return Ok(sin_opcion(ficha, prf, tirador, &minimo, motivo));
    }

    let (indice, elegida) = mejor(&estimaciones, prf, tirador).expect("hay estimaciones");
    let veredicto = veredicto(elegida, &estimaciones, prf, maq);
    let mut alternativas: Vec<(&Estimacion, Vec<f64>)> = estimaciones
        .iter()
        .enumerate()
        .filter(|(i, _)| *i != indice)
        .map(|(_, e)| (e, puntuar(e, prf, tirador)))
        .collect();
    alternativas.sort_by(|a, b| comparar(&b.1, &a.1)); // estable, como sorted(reverse=True)
    let alternativas: Vec<Valor> = alternativas.into_iter().take(3).map(|(e, _)| e.mapa().into()).collect();

    Ok(Mapa::new()
        .con("modelo", ficha.valor("nombre").clone())
        .con("perfil", nombre_perfil)
        .con("tirador", tirador)
        .con("veredicto", veredicto)
        .con("etiqueta", etiqueta(veredicto))
        .con("opciones", opciones(elegida, prf, ficha))
        .con("estimacion", elegida.mapa())
        .con("motivo", motivo(ficha, elegida, veredicto, prf, maq))
        .con("alternativas", alternativas)
        .con("mejora_con_servidor", mejora_servidor(elegida, &todas, prf, tirador, maq))
        .con("aviso_servidor", aviso_servidor(prf, srv))
        .con("fiabilidad", if maq.calibrada() { "calibrada" } else { "estimada" })
        .con("ficha_estimada", ficha.verdad("estimada")))
}

// =========================================================================== qué modelo usar

/// Una aproximación a «cuánto sabe» un modelo, para ordenar candidatos. En un MoE se pondera 0,7 el total y 0,3
/// los activos (Qwen3-30B-A3B empata con Qwen3-14B en el informe técnico de Qwen3); las familias recientes rinden
/// más por parámetro. Es una heurística para ORDENAR; lo medido en la calibración manda.
pub fn calidad_esperada(ficha: &Mapa) -> f64 {
    let total = ficha.num_o("parametros", 0.0) / 1e9;
    let activos = ficha.num_o("parametros_activos", 0.0) / 1e9;
    let efectivo = if ficha.verdad("es_moe") { total.powf(0.7) * activos.powf(0.3) } else { total };
    let arch = match ficha.get("arquitectura") {
        Some(v) if v.verdad() => v.texto_py().to_lowercase(),
        _ => String::new(),
    };
    let generacion = if ["qwen3", "gemma3", "llama4"].iter().any(|p| arch.starts_with(p)) { 1.25 } else { 1.0 };
    efectivo * generacion
}

/// Modelos ordenados de mejor a peor para este uso (`elegir_modelo` de Python)
pub fn elegir_modelo(
    fichas: &[Mapa],
    maq: &Maquina,
    nombre_perfil: &str,
    tirador: &str,
    medidas: &Mapa,
) -> Result<Vec<Mapa>, String> {
    let prf = perfiles::perfil(nombre_perfil)?;
    let mut filas: Vec<(f64, Mapa)> = Vec::new();
    for f in fichas {
        if f.verdad("embedding") {
            continue;
        }
        let r = recomendar(f, maq, nombre_perfil, tirador)?;
        let util = matches!(r.texto("veredicto"), Some("entero" | "ajustando" | "parcial" | "solo_cpu"));
        let mut calidad = calidad_esperada(f);
        let medida = match f.get("nombre") {
            Some(Valor::Texto(n)) => medidas.mapa(n).cloned().unwrap_or_default(),
            _ => Mapa::new(),
        };
        if let Some(c) = medida.get("calidad").filter(|v| !v.es_nulo()) {
            calidad *= 0.5 + c.num().unwrap_or(f64::NAN); // 0..1 medido en el canario
        }
        let vel = r.mapa("estimacion").map(|e| e.num_o("tok_s", 0.0)).unwrap_or(0.0);
        let mut puntos = match tirador {
            "velocidad" => vel * (if util { 2.0 } else { 0.1 }) + calidad,
            "calidad" => calidad * (if util { 10.0 } else { 1.0 }) + vel * 0.1,
            _ => (calidad * 4.0 + min_py(vel, prf.tok_s_min * 3.0)) * (if util { 1.0 } else { 0.1 }),
        };
        // Pensar en voz alta ayuda a revisar y estorba a extraer
        if f.verdad("piensa") && (nombre_perfil == "revision" || nombre_perfil == "flujos") {
            puntos *= 1.15;
        }
        let puntos = redondear(puntos, 2);
        let fila = r.con("puntos", puntos).con("util", util).con("calidad_esperada", redondear(calidad, 1));
        filas.push((puntos, fila));
    }
    filas.sort_by(|a, b| (-a.0).partial_cmp(&-b.0).unwrap_or(Ordering::Equal));
    Ok(filas.into_iter().map(|(_, f)| f).collect())
}
