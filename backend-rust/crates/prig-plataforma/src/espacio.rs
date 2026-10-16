//! La carpeta de trabajo y la segunda carpeta del explorador, guardadas en `~/.prig_config.json` (`last_workspace`,
//! `segunda_carpeta`), y el selector de carpetas del sistema (zenity). Como `FileManager` de Python.

use crate::py;
use crate::valor::{Mapa, Valor};
use std::path::Path;

fn es_dir(p: &str) -> bool {
    !p.contains('\0') && Path::new(p).is_dir()
}

/// `_load_last_workspace`: la última carpeta si existe; si no, el directorio actual
pub fn cargar_ultima(config: &str) -> String {
    if Path::new(config).exists() {
        if let Ok(Valor::Mapa(m)) = crate::leer_json(Path::new(config)) {
            if let Some(Valor::Texto(d)) = m.get("last_workspace") {
                if !d.is_empty() && es_dir(d) {
                    return d.clone();
                }
            }
        }
    }
    py::getcwd()
}

/// `_leer_config`: el dict guardado, o uno vacío si no hay o no se puede leer
pub fn leer_config(config: &str) -> Mapa {
    match crate::leer_json(Path::new(config)) {
        Ok(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    }
}

/// Cambia una clave del archivo (`None` la quita) y lo escribe como `json.dump(config, f)`. Si el archivo existe y
/// no se puede leer, no se toca (así no se pierde lo demás que guarda).
pub fn guardar_clave(config: &str, clave: &str, valor: Option<&str>) {
    let mut m = if Path::new(config).exists() {
        match crate::leer_json(Path::new(config)) {
            Ok(Valor::Mapa(m)) => m,
            _ => return,
        }
    } else {
        Mapa::new()
    };
    match valor {
        Some(v) => m.poner(clave, v),
        None => {
            m.quitar(clave);
        }
    }
    let _ = std::fs::write(config, crate::json::escribir_compacto(&Valor::Mapa(m)));
}

fn nombre_de(abs: &str) -> String {
    let n = py::basename(abs);
    if n.is_empty() {
        abs.to_string()
    } else {
        n
    }
}

/// `set_base_dir`: Ok(ruta absoluta) y su respuesta, o la respuesta de error
pub fn carpeta(ruta: &str) -> Result<(String, Mapa), Mapa> {
    let abs = py::abspath(&py::expanduser(ruta));
    if es_dir(&abs) {
        let r = Mapa::new().con("success", true).con("path", abs.clone()).con("name", nombre_de(&abs));
        Ok((abs, r))
    } else {
        Err(Mapa::new().con("error", format!("El directorio no existe: {ruta}")))
    }
}

/// La respuesta de `set_segunda_dir` para una carpeta (o para quitarla, con `None`)
pub fn respuesta_segunda(abs: Option<&str>) -> Mapa {
    match abs {
        Some(a) => Mapa::new().con("success", true).con("path", a).con("name", nombre_de(a)),
        None => Mapa::new().con("success", true).con("path", Valor::Nulo).con("name", Valor::Nulo),
    }
}

/// El selector de carpetas de zenity: la carpeta elegida, si existe
pub fn elegir_con_zenity(titulo: &str) -> Option<String> {
    let salida = std::process::Command::new("zenity")
        .args(["--file-selection", "--directory", &format!("--title={titulo}")])
        .output()
        .ok()?;
    if !salida.status.success() {
        return None;
    }
    let elegida = String::from_utf8_lossy(&salida.stdout).trim().to_string();
    if !elegida.is_empty() && es_dir(&elegida) {
        Some(elegida)
    } else {
        None
    }
}
