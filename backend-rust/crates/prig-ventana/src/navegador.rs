//! Abrir una dirección en el navegador del sistema sin bloquear nunca la ventana (`lanzar_navegador_desacoplado` y
//! `obtener_navegador_ejecutable` de main.py): en un hilo, en su propia sesión y sin heredar la entrada ni la salida.

use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

fn en_path(nombre: &str) -> Option<PathBuf> {
    if nombre.contains('/') {
        let p = PathBuf::from(nombre);
        return es_ejecutable(&p).then_some(p);
    }
    std::env::var_os("PATH")?.to_str()?.split(':').map(|d| Path::new(d).join(nombre)).find(|p| es_ejecutable(p))
}

fn es_ejecutable(p: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    p.is_file() && p.metadata().map(|m| m.permissions().mode() & 0o111 != 0).unwrap_or(false)
}

/// Un navegador de verdad: $BROWSER, Chrome, Chromium, Firefox (si no es el aviso de «instálalo con snap»), y por
/// último xdg-open
pub fn ejecutable() -> Option<PathBuf> {
    let mut candidatos: Vec<String> = std::env::var("BROWSER").map(|b| b.split(':').map(String::from).collect()).unwrap_or_default();
    candidatos.extend(
        [
            "google-chrome", "google-chrome-stable", "/opt/google/chrome/google-chrome", "chromium", "chromium-browser",
            "firefox", "sensible-browser", "x-www-browser", "gnome-www-browser", "xdg-open",
        ]
        .map(String::from),
    );
    for c in candidatos.iter().map(|c| c.trim()).filter(|c| !c.is_empty()) {
        let Some(ruta) = en_path(c) else { continue };
        if ruta.file_name().is_some_and(|n| n.to_string_lossy().to_lowercase().contains("firefox")) {
            let salida = Command::new(&ruta).arg("--version").stdin(Stdio::null()).output();
            match salida {
                Ok(o) if !String::from_utf8_lossy(&o.stdout).contains("snap install firefox")
                    && !String::from_utf8_lossy(&o.stderr).contains("snap install firefox") => {}
                _ => continue,
            }
        }
        return Some(ruta);
    }
    None
}

/// Abre `url` (solo http y https) sin esperar a nada
pub fn abrir(url: &str) -> bool {
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return false;
    }
    let url = url.to_string();
    std::thread::Builder::new()
        .name("prig-navegador".into())
        .spawn(move || {
            let Some(binario) = ejecutable() else {
                eprintln!("⚠️ No hay navegador para abrir {url}");
                return;
            };
            let mut c = Command::new(binario);
            c.arg(&url).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
            // SAFETY: setsid() en el hijo antes de exec: solo lo desliga de la sesión de Prig
            unsafe {
                c.pre_exec(|| {
                    libc::setsid();
                    Ok(())
                });
            }
            if let Err(e) = c.spawn() {
                eprintln!("⚠️ Error abriendo el navegador para {url}: {e}");
            }
        })
        .is_ok()
}

/// ¿Es una dirección de la propia interfaz de Prig?
pub fn es_local(url: &str) -> bool {
    url.starts_with("http://127.0.0.1") || url.starts_with("http://localhost")
}
