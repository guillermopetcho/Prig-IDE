//! Perfiles de uso (backend/recursos/perfiles.py): el mejor rendimiento depende de para qué se use el modelo.
//!
//! Una sola configuración «óptima» no existe, y está medido. Cuantizar la caché KV a q8_0 hizo el tutor algo más
//! rápido, y en la extracción de libros bajó las citas verificadas del 100 % al 79 %: copiar texto literal es la
//! operación más sensible a la precisión que hay. Lo que es bueno para charlar es malo para extraer.
//!
//!   · ctx_min / ctx_preferido: el contexto que la tarea usa. No se reserva más: cada token ocioso de caché es
//!     memoria que no puede ir a otra ranura o a una capa más en GPU.
//!   · kv_cuantizable: si la tarea tolera perder precisión en la caché.
//!   · tok_s_min: por debajo, el modelo «funciona» pero no sirve para esto.
//!   · pensar: si el razonamiento en voz alta aporta o estorba.

use crate::valor::{Mapa, Valor};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Pensar {
    Si,
    No,
    Auto,
    PorRol,
}

impl Pensar {
    fn valor(self) -> Valor {
        match self {
            Pensar::Si => Valor::Bool(true),
            Pensar::No => Valor::Bool(false),
            Pensar::Auto => "auto".into(),
            Pensar::PorRol => "por_rol".into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Perfil {
    pub id: &'static str,
    pub nombre: &'static str,
    pub descripcion: &'static str,
    pub ctx_min: i64,
    pub ctx_preferido: i64,
    pub ctx_max: i64,
    pub kv_cuantizable: bool,
    pub paralelo_deseado: i64,
    pub pensar: Pensar,
    pub keep_alive: &'static str,
    pub tok_s_min: f64,
    pub prioriza: &'static str,
    pub gobernador_termico: bool,
}

pub const PERFILES: &[Perfil] = &[
    Perfil {
        id: "extraccion",
        nombre: "Extracción de libros",
        descripcion: "Leer libros enteros sacando afirmaciones con su cita literal.",
        ctx_min: 3072, // ~2000 de prompt + margen; la respuesta va en num_predict
        ctx_preferido: 4096,
        ctx_max: 6144,
        kv_cuantizable: false, // medido: q8_0 bajó las citas del 100 % al 79 %
        paralelo_deseado: 2,   // medido: 2 ranuras dieron 1,32× de rendimiento
        pensar: Pensar::No,
        keep_alive: "30m",
        tok_s_min: 10.0,
        prioriza: "exactitud y rendimiento sostenido",
        gobernador_termico: true,
    },
    Perfil {
        id: "tutor",
        nombre: "Tutor y chat",
        descripcion: "Responder preguntas mientras estudias.",
        ctx_min: 4096,
        ctx_preferido: 8192,
        ctx_max: 16384,
        kv_cuantizable: true,
        paralelo_deseado: 1,
        pensar: Pensar::Auto,
        keep_alive: "30m",
        tok_s_min: 8.0, // algo más rápido de lo que se lee
        prioriza: "que la respuesta empiece rápido",
        gobernador_termico: false,
    },
    Perfil {
        id: "flujos",
        nombre: "Flujos de agentes",
        descripcion: "Cadenas de pasos: extraer, analizar, criticar, redactar.",
        ctx_min: 4096,
        ctx_preferido: 4096,
        ctx_max: 8192,
        kv_cuantizable: false, // los revisores dependen de leer bien
        paralelo_deseado: 1,
        pensar: Pensar::PorRol,
        keep_alive: "15m",
        tok_s_min: 6.0,
        prioriza: "no recargar modelos entre pasos",
        gobernador_termico: true,
    },
    Perfil {
        id: "revision",
        nombre: "Revisión final",
        descripcion: "Un único paso de calidad sobre un texto ya corto.",
        ctx_min: 4096,
        ctx_preferido: 8192,
        ctx_max: 16384,
        kv_cuantizable: false,
        paralelo_deseado: 1,
        pensar: Pensar::Si,
        keep_alive: "5m",
        tok_s_min: 2.5,
        prioriza: "calidad por encima de velocidad",
        gobernador_termico: false,
    },
];

pub const TIRADORES: &[(&str, &str)] =
    &[("calidad", "Máxima calidad"), ("equilibrado", "Equilibrado"), ("velocidad", "Máxima velocidad")];

impl Perfil {
    /// Sin el «id»: lo que hay en `PERFILES[nombre]` de Python
    pub fn mapa(&self) -> Mapa {
        Mapa::new()
            .con("nombre", self.nombre)
            .con("descripcion", self.descripcion)
            .con("ctx_min", self.ctx_min)
            .con("ctx_preferido", self.ctx_preferido)
            .con("ctx_max", self.ctx_max)
            .con("kv_cuantizable", self.kv_cuantizable)
            .con("paralelo_deseado", self.paralelo_deseado)
            .con("pensar", self.pensar.valor())
            .con("keep_alive", self.keep_alive)
            .con("tok_s_min", self.tok_s_min)
            .con("prioriza", self.prioriza)
            .con("gobernador_termico", self.gobernador_termico)
    }
}

/// `PERFILES` de Python: {id: {...}}
pub fn perfiles() -> Mapa {
    PERFILES.iter().fold(Mapa::new(), |m, p| m.con(p.id, p.mapa()))
}

/// `TIRADORES` de Python
pub fn tiradores() -> Mapa {
    TIRADORES.iter().fold(Mapa::new(), |m, (k, v)| m.con(*k, *v))
}

/// El perfil, o el mensaje del KeyError de Python
pub fn perfil(nombre: &str) -> Result<&'static Perfil, String> {
    PERFILES.iter().find(|p| p.id == nombre).ok_or_else(|| {
        format!(
            "perfil desconocido: {nombre}. Hay: {}",
            PERFILES.iter().map(|p| p.id).collect::<Vec<_>>().join(", ")
        )
    })
}

/// `perfil(nombre)` de Python: {"id": nombre, **PERFILES[nombre]}
pub fn perfil_mapa(nombre: &str) -> Result<Mapa, String> {
    let p = perfil(nombre)?;
    Ok(Mapa::new().con("id", p.id).fusion(&p.mapa()))
}
