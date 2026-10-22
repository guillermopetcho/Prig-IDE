//! Perfiles de configuración del entorno (`perfiles_config.py`): perfiles, apariencia, sintaxis, motor de
//! movimiento, accesibilidad y audio reactivo, cada uno en un JSON de `.prig_dataset/`. Las rutas las da quien llama
//! (en Python son constantes del módulo, que las pruebas pueden cambiar).

use crate::valor::{Mapa, Valor};
use std::path::Path;
use std::sync::OnceLock;

/// Los perfiles de fábrica, tal cual `PERFILES_PREDETERMINADOS`
pub fn predeterminados() -> Valor {
    static P: OnceLock<Valor> = OnceLock::new();
    P.get_or_init(|| crate::json::leer(include_str!("perfiles_predeterminados.json")).expect("perfiles de fábrica"))
        .clone()
}

/// Lo que Python imprimía al fallar una lectura o una escritura
pub type Avisos = Vec<String>;

fn asegurar_directorio(dir: &Path) {
    if !dir.exists() {
        let _ = std::fs::create_dir_all(dir);
    }
}

/// `_cargar_json(ruta, por_defecto)`
pub fn cargar(dir: &Path, ruta: &Path, por_defecto: Valor, avisos: &mut Avisos) -> Valor {
    asegurar_directorio(dir);
    if !ruta.is_file() {
        return por_defecto;
    }
    match crate::leer_json(ruta) {
        Ok(v) => v,
        Err(e) => {
            avisos.push(format!("Error cargando JSON de {}: {e}", ruta.display()));
            por_defecto
        }
    }
}

/// `_guardar_json(ruta, datos)`
pub fn guardar(dir: &Path, ruta: &Path, datos: &Valor, avisos: &mut Avisos) -> bool {
    asegurar_directorio(dir);
    match crate::escribir_json(ruta, datos, 2) {
        Ok(()) => true,
        Err(e) => {
            avisos.push(format!("Error guardando JSON en {}: {e}", ruta.display()));
            false
        }
    }
}

fn iniciales() -> Valor {
    Valor::Mapa(Mapa::new().con("perfil_activo", "catppuccin_equilibrado").con("perfiles", predeterminados()))
}

/// `cargar_perfiles()`: si no hay archivo se crea con los de fábrica; si está roto se devuelven los de fábrica
pub fn cargar_perfiles(dir: &Path, ruta: &Path, avisos: &mut Avisos) -> Valor {
    asegurar_directorio(dir);
    if !ruta.is_file() {
        let datos = iniciales();
        guardar(dir, ruta, &datos, avisos);
        return datos;
    }
    match crate::leer_json(ruta) {
        Ok(Valor::Mapa(m)) if m.contiene("perfiles") => Valor::Mapa(m),
        _ => iniciales(),
    }
}

/// Las secciones de `guardar_estado_completo`, en su orden
pub const SECCIONES: [&str; 6] = ["apariencia", "sintaxis", "motor_movimiento", "audio_reactivo", "accesibilidad", "perfiles"];
