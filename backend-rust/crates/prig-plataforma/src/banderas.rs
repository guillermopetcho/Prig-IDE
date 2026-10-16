//! Banderas de funcionalidad (`feature_flags.py`). Prioridad: variable de entorno (`PRIG_FLAG_<NOMBRE>`) > archivo
//! (`~/.prig_flags.json`) > valor por defecto.

use crate::valor::{Mapa, Valor};
use std::path::PathBuf;

/// Toda bandera nueva se declara aquí: (nombre, valor por defecto, para qué sirve)
pub const BANDERAS: &[(&str, bool, &str)] = &[
    ("knowledge_chat", true, "Respuestas del tutor fundamentadas en la biblioteca, con citas"),
    ("library_indexing", true, "Indexar la biblioteca para que el tutor pueda consultarla"),
    ("query_expansion", true, "Reformular la consulta con el modelo antes de buscar (compensa el índice léxico)"),
    ("exercises_api", true, "Generar y corregir ejercicios verificados por ejecución"),
    ("exercises_ui", false, "Pantalla del alumno para resolver ejercicios (aún sin construir)"),
    ("kaggle_window", false, "Ventana nativa de Kaggle con lectura de página (suspendida)"),
    ("learning_telemetry", true, "Registrar intentos de ejercicios para medir el aprendizaje"),
];

fn por_defecto(nombre: &str) -> Option<bool> {
    BANDERAS.iter().find(|(n, _, _)| *n == nombre).map(|(_, d, _)| *d)
}

/// `{nombre: {"default": ..., "description": ...}}`, como `DEFAULT_FLAGS`
pub fn declaradas() -> Mapa {
    let mut m = Mapa::new();
    for (n, d, desc) in BANDERAS {
        m.poner(*n, Mapa::new().con("default", *d).con("description", *desc));
    }
    m
}

pub struct Banderas {
    pub ruta: PathBuf,
    /// Lo guardado en el archivo, en su orden (un `dict` de Python)
    cambios: Vec<(String, bool)>,
    /// Los avisos que Python imprimía (no se pudo leer o guardar el archivo)
    pub avisos: Vec<String>,
    /// Fecha y tamaño del archivo cuando se leyó: si cambian, otro proceso (el servidor de Rust o el backend de
    /// Python) guardó banderas y hay que volver a leerlas
    sello: Option<(std::time::SystemTime, u64)>,
}

impl Banderas {
    pub fn new(ruta: PathBuf) -> Banderas {
        let mut b = Banderas { ruta, cambios: Vec::new(), avisos: Vec::new(), sello: None };
        b.cargar();
        b
    }

    fn sello_actual(&self) -> Option<(std::time::SystemTime, u64)> {
        let m = std::fs::metadata(&self.ruta).ok()?;
        Some((m.modified().ok()?, m.len()))
    }

    /// Vuelve a leer el archivo si otro proceso lo cambió desde la última lectura o escritura
    pub fn refrescar(&mut self) {
        let actual = self.sello_actual();
        if actual != self.sello {
            self.cambios.clear();
            self.cargar();
        }
    }

    fn cargar(&mut self) {
        self.sello = self.sello_actual();
        if !self.ruta.exists() {
            return;
        }
        match crate::leer_json(&self.ruta) {
            Ok(Valor::Mapa(m)) => {
                self.cambios = m.iter().filter(|(k, _)| por_defecto(k).is_some()).map(|(k, v)| (k.clone(), v.verdad())).collect();
            }
            Ok(_) => {
                // `saved.items()` sobre algo que no es un dict
                self.avisos.push("⚠️ No se pudieron leer las banderas (no es un objeto); se usan los valores por defecto.".into());
                self.cambios.clear();
            }
            Err(e) => {
                self.avisos.push(format!("⚠️ No se pudieron leer las banderas ({e}); se usan los valores por defecto."));
                self.cambios.clear();
            }
        }
    }

    fn guardar(&mut self) {
        let mut m = Mapa::new();
        for (k, v) in &self.cambios {
            m.poner(k.clone(), *v);
        }
        if let Err(e) = crate::escribir_json(&self.ruta, &Valor::Mapa(m), 2) {
            self.avisos.push(format!("⚠️ No se pudieron guardar las banderas: {e}"));
        }
        self.sello = self.sello_actual();
    }

    fn de_entorno(nombre: &str) -> Option<bool> {
        let crudo = std::env::var(format!("PRIG_FLAG_{}", nombre.to_uppercase())).ok()?;
        Some(matches!(crudo.trim().to_lowercase().as_str(), "1" | "true" | "yes" | "on" | "si" | "sí"))
    }

    fn cambio(&self, nombre: &str) -> Option<bool> {
        self.cambios.iter().find(|(k, _)| k == nombre).map(|(_, v)| *v)
    }

    pub fn activa(&self, nombre: &str) -> bool {
        let Some(defecto) = por_defecto(nombre) else { return false };
        if let Some(e) = Self::de_entorno(nombre) {
            return e;
        }
        self.cambio(nombre).unwrap_or(defecto)
    }

    /// Err si la bandera no existe (KeyError en Python)
    pub fn poner(&mut self, nombre: &str, valor: bool) -> Result<bool, String> {
        if por_defecto(nombre).is_none() {
            return Err(format!("Bandera desconocida: {nombre}"));
        }
        match self.cambios.iter_mut().find(|(k, _)| k == nombre) {
            Some(c) => c.1 = valor,
            None => self.cambios.push((nombre.to_string(), valor)),
        }
        self.guardar();
        Ok(self.activa(nombre))
    }

    pub fn reiniciar(&mut self, nombre: &str) -> bool {
        self.cambios.retain(|(k, _)| k != nombre);
        self.guardar();
        self.activa(nombre)
    }

    pub fn todas(&self) -> Mapa {
        let mut m = Mapa::new();
        for (n, d, desc) in BANDERAS {
            let fuente = if Self::de_entorno(n).is_some() {
                "entorno"
            } else if self.cambio(n).is_some() {
                "configuración"
            } else {
                "por defecto"
            };
            m.poner(
                *n,
                Mapa::new().con("enabled", self.activa(n)).con("default", *d).con("description", *desc).con("source", fuente),
            );
        }
        m
    }
}
