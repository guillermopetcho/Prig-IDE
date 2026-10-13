//! Ajustes del SERVIDOR de Ollama (backend/recursos/servidor.py): los que no se pueden mandar en cada petición.
//!
//! La caché KV cuantizada, las ranuras en paralelo o FlashAttention se fijan con variables de entorno al arrancar
//! `ollama serve`. Cambiarlas exige reiniciarlo, y eso solo es seguro si el proceso es de Prig: si lo gestiona
//! systemd o alguien lo lanzó a mano, se dan las instrucciones exactas y no se toca nada. Nunca se actualiza ni se
//! sustituye el binario de Ollama del sistema.

use crate::calculadora::servidor_efectivo;
use crate::motor_suave::correr;
use crate::valor::{Mapa, Valor};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Variables que Prig gestiona. El resto (las que el usuario tenga) se respeta.
pub const GESTIONADAS: &[&str] = &[
    "OLLAMA_KV_CACHE_TYPE",
    "OLLAMA_NUM_PARALLEL",
    "OLLAMA_FLASH_ATTENTION",
    "OLLAMA_MAX_LOADED_MODELS",
    "OLLAMA_KEEP_ALIVE",
    // Verificadas una a una en un Ollama aparte (puerto 11500), midiendo el efecto
    "OLLAMA_CONTEXT_LENGTH",
    "OLLAMA_LLM_LIBRARY",
    "LLAMA_ARG_FIT_TARGET",
    "OLLAMA_LOAD_TIMEOUT",
    "OLLAMA_IGPU_ENABLE",
    "OLLAMA_MODELS",
    "OLLAMA_HOST",
    "OLLAMA_ORIGINS",
    "OLLAMA_DEBUG",
    "OLLAMA_NO_CLOUD",
];

pub const VALORES_VALIDOS: &[(&str, &[&str])] = &[
    ("OLLAMA_KV_CACHE_TYPE", &["f16", "q8_0", "q4_0"]),
    ("OLLAMA_FLASH_ATTENTION", &["0", "1"]),
    ("OLLAMA_IGPU_ENABLE", &["0", "1"]),
    ("OLLAMA_DEBUG", &["0", "1"]),
    ("OLLAMA_NO_CLOUD", &["0", "1"]),
    // Solo el puerto de siempre: Prig y el gestor de recursos hablan con el 11434
    ("OLLAMA_HOST", &["127.0.0.1:11434", "0.0.0.0:11434"]),
];

/// Qué hace cada una y cómo se comprobó, para la interfaz: (título, descripción, comprobado)
pub const DESCRIPCIONES: &[(&str, (&str, &str, &str))] = &[
    ("OLLAMA_CONTEXT_LENGTH", ("Contexto por defecto", "Tokens de contexto cuando la petición no dice nada.",
                               "Con 3072, el modelo se carga con 3072 en vez de 4096.")),
    ("OLLAMA_LLM_LIBRARY", ("Motor de cálculo", "Fuerza la biblioteca: CUDA 12, CUDA 13, Vulkan o CPU. Vacío = automático.",
                            "cuda_v12, cuda_v13 y vulkan cargan en GPU (140 tok/s con cuda_v13); cpu deja la VRAM en 0.")),
    ("LLAMA_ARG_FIT_TARGET", ("VRAM libre a reservar (MiB)", "Margen que el reparto automático deja libre en la GPU.",
                              "Con 2500 MiB el 7B pasa de 4,75 a 3,31 GB en GPU.")),
    ("OLLAMA_LOAD_TIMEOUT", ("Tiempo máximo de carga", "Cuánto puede tardar en cargar un modelo antes de darlo por fallido. Mínimo 10s.",
                             "Con un valor mínimo la carga falla con «timed out waiting for llama-server».")),
    ("OLLAMA_IGPU_ENABLE", ("Usar la gráfica integrada", "Permite usar también la GPU integrada del procesador.",
                            "Los dispositivos detectados pasan de 1 a 2 (la Intel integrada).")),
    ("OLLAMA_MODELS", ("Carpeta de modelos", "Dónde guarda Ollama los modelos (por ejemplo, otro disco).",
                       "Apuntando a una carpeta vacía, la lista de modelos queda vacía.")),
    ("OLLAMA_HOST", ("Acceso desde la red", "127.0.0.1: solo este equipo. 0.0.0.0: cualquier equipo de tu red puede usar tus modelos.",
                     "En 0.0.0.0 responde por la IP de la red local; en 127.0.0.1 la rechaza.")),
    ("OLLAMA_ORIGINS", ("Webs con permiso", "Orígenes (https://…) que pueden llamar a Ollama desde el navegador, separados por comas.",
                        "Sin permiso: 403. Con el origen en la lista: 200 y cabecera CORS.")),
    ("OLLAMA_DEBUG", ("Registro detallado", "Escribe información de depuración en el registro del servidor.",
                      "El registro pasa a incluir líneas level=DEBUG.")),
    ("OLLAMA_NO_CLOUD", ("Bloquear la nube", "Impide usar modelos remotos y la búsqueda web de ollama.com: todo queda en tu equipo.",
                         "Un modelo :cloud pasa de 401 a 403 «ollama cloud is disabled».")),
];

pub fn descripciones() -> Mapa {
    DESCRIPCIONES.iter().fold(Mapa::new(), |m, (k, (a, b, c))| {
        m.con(*k, Valor::Lista(vec![(*a).into(), (*b).into(), (*c).into()]))
    })
}

/// Motores instalados junto al binario de Ollama de Prig, más la CPU
pub fn librerias_disponibles(raiz_prig: &Path) -> Vec<String> {
    let raiz = raiz_prig.join("lib/ollama");
    let mut libs: Vec<String> = std::fs::read_dir(&raiz)
        .map(|it| it.flatten().filter(|e| e.path().is_dir()).map(|e| e.file_name().to_string_lossy().into_owned()).collect())
        .unwrap_or_default();
    libs.sort();
    libs.push("cpu".into());
    libs
}

/// `str.isdigit()` (las cifras ASCII; Python acepta también otras cifras Unicode)
fn es_numero(v: &str) -> bool {
    !v.is_empty() && v.chars().all(|c| c.is_ascii_digit())
}

/// `^(\*|https?://[a-zA-Z0-9.\-*]+(:\d+)?|app://[^,\s]+|file://[^,\s]*)$`
fn es_origen(x: &str) -> bool {
    if x == "*" {
        return true;
    }
    if let Some(r) = x.strip_prefix("app://") {
        return !r.is_empty() && !r.chars().any(|c| c == ',' || c.is_whitespace());
    }
    if let Some(r) = x.strip_prefix("file://") {
        return !r.chars().any(|c| c == ',' || c.is_whitespace());
    }
    let resto = x.strip_prefix("https://").or_else(|| x.strip_prefix("http://"));
    let Some(resto) = resto else { return false };
    let (host, puerto) = match resto.rsplit_once(':') {
        Some((h, p)) if !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()) => (h, Some(p)),
        _ => (resto, None),
    };
    let _ = puerto;
    !host.is_empty() && host.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-' || c == '*')
}

/// `os.path.abspath(os.path.expanduser(v))`
fn ruta_absoluta(v: &str) -> PathBuf {
    let v = if v == "~" || v.starts_with("~/") {
        format!("{}{}", std::env::var("HOME").unwrap_or_default(), &v[1..])
    } else {
        v.to_string()
    };
    let p = PathBuf::from(&v);
    let p = if p.is_absolute() { p } else { std::env::current_dir().unwrap_or_default().join(p) };
    // normalización léxica, como abspath
    let mut partes: Vec<std::ffi::OsString> = Vec::new();
    for c in p.components() {
        match c {
            std::path::Component::ParentDir => {
                partes.pop();
            }
            std::path::Component::Normal(n) => partes.push(n.to_os_string()),
            _ => {}
        }
    }
    let mut r = PathBuf::from("/");
    for x in partes {
        r.push(x);
    }
    r
}

fn escribible(p: &Path) -> bool {
    let Ok(c) = std::ffi::CString::new(p.as_os_str().as_encoded_bytes()) else { return false };
    // SAFETY: access solo lee la ruta
    unsafe { libc::access(c.as_ptr(), libc::W_OK) == 0 }
}

/// Comprueba y limpia los cambios. Error: el mensaje del ValueError de Python.
pub fn validar(cambios: &Mapa, raiz_prig: &Path) -> Result<Mapa, String> {
    let mut limpio = Mapa::new();
    for (k, v) in cambios.iter() {
        if !GESTIONADAS.contains(&k.as_str()) {
            return Err(format!("{k} no es un ajuste que Prig gestione"));
        }
        if v.es_nulo() || matches!(v, Valor::Texto(t) if t.is_empty()) {
            limpio.poner(k.clone(), ""); // quitarla: vuelve al valor por defecto
            continue;
        }
        let mut v = v.texto_py().trim().to_string();
        if let Some((_, validos)) = VALORES_VALIDOS.iter().find(|(c, _)| c == k) {
            if !validos.contains(&v.as_str()) {
                return Err(format!("{k}={v} no es válido"));
            }
        }
        let entre = |a: i128, b: i128| es_numero(&v) && v.parse::<i128>().is_ok_and(|n| (a..=b).contains(&n));
        match k.as_str() {
            "OLLAMA_NUM_PARALLEL" | "OLLAMA_MAX_LOADED_MODELS" if !entre(1, 8) => {
                return Err(format!("{k} debe ser un entero entre 1 y 8"));
            }
            "OLLAMA_CONTEXT_LENGTH" if !entre(512, 262144) => {
                return Err("El contexto por defecto debe estar entre 512 y 262144".into());
            }
            "LLAMA_ARG_FIT_TARGET" if !entre(0, 65536) => {
                return Err("La VRAM a reservar debe estar entre 0 y 65536 MiB".into());
            }
            "OLLAMA_LLM_LIBRARY" => {
                let libs = librerias_disponibles(raiz_prig);
                if !libs.contains(&v) {
                    return Err(format!("Motor desconocido: {v}. Hay: {}", libs.join(", ")));
                }
            }
            "OLLAMA_LOAD_TIMEOUT" => {
                let cifras: String = v.chars().take_while(|c| c.is_ascii_digit()).collect();
                let unidad = &v[cifras.len()..];
                let factor = match unidad {
                    "ms" => Some(0.001),
                    "s" => Some(1.0),
                    "m" => Some(60.0),
                    "h" => Some(3600.0),
                    _ => None,
                };
                let ok = match (cifras.parse::<f64>(), factor) {
                    (Ok(n), Some(f)) if !cifras.is_empty() => n * f >= 10.0,
                    _ => false,
                };
                if !ok {
                    return Err("El tiempo de carga debe ser de al menos 10s (ej. 90s, 5m); medido: con valores mínimos \
                                ningún modelo llega a cargar"
                        .into());
                }
            }
            "OLLAMA_MODELS" => {
                let p = ruta_absoluta(&v);
                v = p.to_string_lossy().into_owned();
                if !p.is_dir() || !escribible(&p) {
                    return Err(format!("La carpeta de modelos no existe o no se puede escribir: {v}"));
                }
            }
            "OLLAMA_ORIGINS" => {
                let partes: Vec<&str> = v.split(',').map(str::trim).filter(|x| !x.is_empty()).collect();
                let malos: Vec<&str> = partes.iter().copied().filter(|x| !es_origen(x)).collect();
                if !malos.is_empty() || partes.is_empty() {
                    let lista = if malos.is_empty() { v.clone() } else { malos.join(", ") };
                    return Err(format!("Orígenes no válidos: {lista}"));
                }
                v = partes.join(",");
            }
            _ => {}
        }
        limpio.poner(k.clone(), v);
    }
    // La caché cuantizada solo funciona con FlashAttention: sin ella, Ollama la ignora en silencio
    if matches!(limpio.texto("OLLAMA_KV_CACHE_TYPE"), Some("q8_0" | "q4_0")) {
        limpio.poner("OLLAMA_FLASH_ATTENTION", "1");
    }
    Ok(limpio)
}

/// Lo que Prig quiere, lo que tiene el servidor y lo que falta por aplicar
pub fn estado(info: &Mapa, guardado: &Mapa, raiz_prig: &Path, ruta_registro: &str) -> Mapa {
    let real = info.mapa("entorno").cloned().unwrap_or_default();
    let mut pendiente = Mapa::new();
    for (k, v) in guardado.iter() {
        let tiene = real.get(k).cloned().unwrap_or_else(|| "".into());
        if tiene != *v {
            pendiente.poner(k.clone(), v.clone());
        }
    }
    let mut entorno = Mapa::new();
    for k in GESTIONADAS {
        if let Some(v) = real.get(k).filter(|v| !v.es_nulo()) {
            entorno.poner(*k, v.clone());
        }
    }
    let dueno = info.valor("dueno").clone();
    let puede = matches!(&dueno, Valor::Nulo) || matches!(&dueno, Valor::Texto(t) if t == "prig");
    Mapa::new()
        .con("responde", info.valor("responde").clone())
        .con("version", info.valor("version").clone())
        .con("binario", info.valor("binario").clone())
        .con("dueno", dueno)
        .con("entorno", entorno)
        .con("efectivo", servidor_efectivo(&real).mapa())
        .con("guardado", guardado.clone())
        .con("pendiente", pendiente)
        .con("puede_reiniciar", puede)
        .con("descripciones", descripciones())
        .con("librerias", Valor::Lista(librerias_disponibles(raiz_prig).into_iter().map(Valor::from).collect()))
        .con("registro", ruta_registro)
        .con("modelos_cargados", info.get("modelos_cargados").cloned().unwrap_or(Valor::Lista(vec![])))
}

/// Cómo aplicar las variables a mano, según quién gestione Ollama
pub fn instrucciones(dueno: Option<&str>, entorno: &Mapa) -> String {
    let mut pares: Vec<(String, String)> = entorno.iter().map(|(k, v)| (k.clone(), v.texto_py())).collect();
    pares.sort();
    let lineas: Vec<String> = pares.into_iter().filter(|(_, v)| !v.is_empty()).map(|(k, v)| format!("{k}={v}")).collect();
    if matches!(dueno, Some("systemd" | "systemd-usuario")) {
        let usuario = if dueno == Some("systemd-usuario") { " --user" } else { "" };
        let sudo = if usuario.is_empty() { "sudo " } else { "" };
        let cuerpo = lineas.iter().map(|l| format!("Environment=\"{l}\"")).collect::<Vec<_>>().join("\n");
        return format!(
            "Ollama lo gestiona systemd, así que Prig no lo reinicia por su cuenta.\n1. {sudo}systemctl{usuario} edit ollama\n\
             2. Añade:\n[Service]\n{cuerpo}\n3. {sudo}systemctl{usuario} restart ollama"
        );
    }
    format!("Ollama se lanzó a mano. Ciérralo y vuelve a arrancarlo así:\n{} ollama serve", lineas.join(" "))
}

/// El entorno con el que Prig arranca `ollama serve`: el de base con lo guardado encima
pub fn entorno_arranque(base: &Mapa, guardado: &Mapa) -> Mapa {
    let mut env = base.clone();
    for (k, v) in guardado.iter() {
        if GESTIONADAS.contains(&k.as_str()) && !matches!(v, Valor::Texto(t) if t.is_empty()) {
            env.poner(k.clone(), v.clone());
        }
    }
    env
}

/// Rota el registro al pasar de 5 MB (antes de abrirlo para añadir)
pub fn rotar_registro(ruta: &str) {
    if std::fs::metadata(ruta).is_ok_and(|m| m.len() > 5 * 1024 * 1024) {
        let _ = std::fs::rename(ruta, format!("{ruta}.1"));
    }
}

/// Las últimas líneas del registro: el de journalctl si lo gestiona systemd, el archivo de Prig si no
pub fn leer_registro(lineas: i64, dueno: Option<&str>, ruta: &str) -> Mapa {
    let lineas = lineas.clamp(20, 5000);
    if matches!(dueno, Some("systemd" | "systemd-usuario")) {
        let mut args: Vec<String> = Vec::new();
        if dueno == Some("systemd-usuario") {
            args.push("--user".into());
        }
        args.extend(["-u".into(), "ollama".into(), "-n".into(), lineas.to_string(), "--no-pager".into()]);
        return match correr(Path::new("journalctl"), &args, Duration::from_secs(10)) {
            Ok((0, salida, _)) if !salida.trim().is_empty() => Mapa::new().con("origen", "journalctl").con("texto", salida),
            Ok((_, _, error)) => {
                let aviso = if error.trim().is_empty() { "Sin permiso para leer el registro del servicio".to_string() } else { error.trim().to_string() };
                Mapa::new().con("origen", "journalctl").con("texto", "").con("aviso", aviso)
            }
            Err(e) => Mapa::new().con("origen", "journalctl").con("texto", "").con("aviso", e.to_string()),
        };
    }
    let Ok(bytes) = std::fs::read(ruta) else {
        return Mapa::new()
            .con("origen", ruta)
            .con("texto", "")
            .con("aviso", "Todavía no hay registro: se crea cuando Prig arranca Ollama.");
    };
    let desde = bytes.len().saturating_sub(400 * lineas as usize);
    let texto = String::from_utf8_lossy(&bytes[desde..]).into_owned();
    let todas: Vec<&str> = lineas_como_python(&texto);
    let ultimas = &todas[todas.len().saturating_sub(lineas as usize)..];
    Mapa::new().con("origen", ruta).con("texto", ultimas.join("\n"))
}

/// `str.splitlines()`: también corta en \r, \v, \f, \x1c-\x1e, \x85,   y
pub fn lineas_como_python(t: &str) -> Vec<&str> {
    let mut salida = Vec::new();
    let mut inicio = 0;
    let mut it = t.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        let corte = matches!(c, '\n' | '\r' | '\u{b}' | '\u{c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}');
        if corte {
            salida.push(&t[inicio..i]);
            let mut fin = i + c.len_utf8();
            if c == '\r' {
                if let Some(&(j, '\n')) = it.peek() {
                    it.next();
                    fin = j + 1;
                }
            }
            inicio = fin;
        }
    }
    if inicio < t.len() {
        salida.push(&t[inicio..]);
    }
    salida
}

/// Para el `ollama serve` de Prig: SIGTERM, hasta 10 s esperando y SIGKILL si sigue
pub fn parar_ollama(pid: i32) {
    // SAFETY: kill solo manda señales
    let vivo = |p: i32| unsafe { libc::kill(p, 0) == 0 || *libc::__errno_location() != libc::ESRCH };
    unsafe {
        libc::kill(pid, libc::SIGTERM);
    }
    for _ in 0..40 {
        if !vivo(pid) {
            return;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    unsafe {
        libc::kill(pid, libc::SIGKILL);
    }
    std::thread::sleep(Duration::from_secs(1));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cache_cuantizada_activa_flash_attention() {
        let r = validar(&Mapa::new().con("OLLAMA_KV_CACHE_TYPE", "q8_0"), Path::new("/no"));
        assert_eq!(r.unwrap(), Mapa::new().con("OLLAMA_KV_CACHE_TYPE", "q8_0").con("OLLAMA_FLASH_ATTENTION", "1"));
    }

    #[test]
    fn rechaza() {
        for (k, v) in [
            ("OLLAMA_NOPRUNE", "1"),
            ("OLLAMA_KV_CACHE_TYPE", "q2"),
            ("OLLAMA_NUM_PARALLEL", "40"),
            ("OLLAMA_NUM_PARALLEL", "dos"),
            ("OLLAMA_LOAD_TIMEOUT", "9s"),
            ("OLLAMA_ORIGINS", "ftp://x"),
        ] {
            assert!(validar(&Mapa::new().con(k, v), Path::new("/no")).is_err(), "{k}={v}");
        }
        assert!(validar(&Mapa::new().con("OLLAMA_LOAD_TIMEOUT", "10000ms"), Path::new("/no")).is_ok());
        assert_eq!(
            validar(&Mapa::new().con("OLLAMA_ORIGINS", " https://a.b:8080 , app://x ,"), Path::new("/no")).unwrap().texto("OLLAMA_ORIGINS"),
            Some("https://a.b:8080,app://x")
        );
    }

    #[test]
    fn lineas() {
        assert_eq!(lineas_como_python("a\r\nb\rc\n"), ["a", "b", "c"]);
        assert_eq!(lineas_como_python(""), Vec::<&str>::new());
    }
}
