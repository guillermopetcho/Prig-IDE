//! git para Prig Hub (`hub/git.py`): crear repositorios propios, seguir los de otros y publicar.
//!
//! Seguridad:
//!   · solo se clona por HTTPS (y por file:// en las pruebas, con PRIG_HUB_GIT_LOCAL=1); los transportes ext:: y file
//!     quedan prohibidos, y una URL que empieza por «-» se rechaza;
//!   · git nunca pregunta por la terminal (GIT_TERMINAL_PROMPT=0) ni usa ganchos del repo;
//!   · el token de GitHub va solo en el entorno del proceso que empuja (GIT_CONFIG_*), nunca en la línea de comandos
//!     (visible en ps) ni en .git/config;
//!   · un repositorio de más de MAX_MB se descarta: Prig Hub es texto.

use base64::Engine;
use prig_plataforma::py;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const MAX_MB: f64 = 30.0;
const TIEMPO: u64 = 120;

#[derive(Debug, Clone)]
pub struct ErrorGit(pub String);

fn error<T>(t: impl Into<String>) -> Result<T, ErrorGit> {
    Err(ErrorGit(t.into()))
}

/// `shutil.which("git")`
pub fn disponible() -> bool {
    let Some(camino) = std::env::var_os("PATH") else { return false };
    std::env::split_paths(&camino).any(|d| {
        use std::os::unix::fs::PermissionsExt;
        let p = d.join("git");
        p.is_file() && p.metadata().map(|m| m.permissions().mode() & 0o111 != 0).unwrap_or(false)
    })
}

fn local() -> bool {
    std::env::var("PRIG_HUB_GIT_LOCAL").as_deref() == Ok("1")
}

pub type Entorno = Vec<(String, String)>;

/// `correr(args, cwd, extra, tiempo)`: la salida de git, o el error ya explicado
pub fn correr_bytes(args: &[&str], cwd: Option<&Path>, extra: &Entorno, tiempo: u64) -> Result<Vec<u8>, ErrorGit> {
    if !disponible() {
        return error("git no está instalado (sudo apt install git).");
    }
    let mut c = Command::new("git");
    c.args(["-c", "protocol.ext.allow=never", "-c"])
        .arg(format!("protocol.file.allow={}", if local() { "always" } else { "never" }))
        .args(["-c", "core.hooksPath=/dev/null", "-c", "advice.detachedHead=false"])
        .args(args);
    for (k, _) in std::env::vars_os() {
        if k.to_string_lossy().starts_with("GIT_") {
            c.env_remove(k);
        }
    }
    for (k, v) in [("GIT_TERMINAL_PROMPT", "0"), ("GIT_ASKPASS", ""), ("SSH_ASKPASS", ""), ("LC_ALL", "C"), ("GIT_CONFIG_NOSYSTEM", "1")] {
        c.env(k, v);
    }
    for (k, v) in extra {
        c.env(k, v);
    }
    if let Some(d) = cwd {
        c.current_dir(d);
    }
    c.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut hijo = c.spawn().or_else(|e| error(e.to_string()))?;
    let mut so = hijo.stdout.take().unwrap();
    let mut se = hijo.stderr.take().unwrap();
    let h_out = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = so.read_to_end(&mut b);
        b
    });
    let h_err = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = se.read_to_end(&mut b);
        b
    });
    let limite = Instant::now() + Duration::from_secs(tiempo);
    let estado = loop {
        match hijo.try_wait() {
            Ok(Some(e)) => break e,
            Ok(None) if Instant::now() >= limite => {
                let _ = hijo.kill();
                let _ = hijo.wait();
                return error("git tardó demasiado (¿sin conexión?).");
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(15)),
            Err(e) => return error(e.to_string()),
        }
    };
    let salida = h_out.join().unwrap_or_default();
    let err = h_err.join().unwrap_or_default();
    if !estado.success() {
        let texto = String::from_utf8_lossy(&err);
        let ultima = py::strip(&texto).lines().last().map(String::from);
        return error(explicar(&ultima.unwrap_or_else(|| format!("git {} falló", args[0]))));
    }
    Ok(salida)
}

pub fn correr(args: &[&str], cwd: Option<&Path>, extra: &Entorno) -> Result<String, ErrorGit> {
    correr_t(args, cwd, extra, TIEMPO)
}

fn correr_t(args: &[&str], cwd: Option<&Path>, extra: &Entorno, tiempo: u64) -> Result<String, ErrorGit> {
    Ok(String::from_utf8_lossy(&correr_bytes(args, cwd, extra, tiempo)?).into_owned())
}

fn explicar(linea: &str) -> String {
    let bajo = linea.to_lowercase();
    let tiene = |t: &str| bajo.contains(t);
    if tiene("could not resolve host") || tiene("unable to access") && tiene("resolve") {
        return "Sin conexión: no se pudo llegar al servidor.".into();
    }
    if tiene("repository not found") || tiene("not found") && tiene("repository") {
        return "Ese repositorio no existe o es privado.".into();
    }
    if tiene("authentication failed") || tiene("could not read username") || tiene("403") {
        return "El servidor rechazó el acceso: revisa el token de GitHub (necesita permiso de escritura en el repositorio).".into();
    }
    if tiene("non-fast-forward") || tiene("fetch first") || tiene("rejected") {
        return "El repositorio en GitHub tiene cambios que no están aquí. Trae esos cambios antes de publicar.".into();
    }
    linea.chars().take(300).collect()
}

pub fn validar_url(url: &str) -> Result<String, ErrorGit> {
    let u = py::strip(url);
    if u.starts_with('-') || u.chars().any(|c| " \n\t\\".contains(c)) {
        return error("Enlace de repositorio no válido.");
    }
    if u.starts_with("https://") {
        return Ok(u.into());
    }
    if local() && (u.starts_with("file://") || py::isabs(u)) {
        return Ok(u.into());
    }
    error("Solo se pueden seguir repositorios por HTTPS (GitHub, GitLab, Codeberg…).")
}

pub fn autor(nombre: &str, correo: &str) -> Entorno {
    ["GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"]
        .iter()
        .enumerate()
        .map(|(i, k)| (k.to_string(), if i % 2 == 0 { nombre.to_string() } else { correo.to_string() }))
        .collect()
}

/// El token como cabecera HTTP, solo para este proceso y solo hacia github.com
pub fn auth_github(token: Option<&str>) -> Entorno {
    let Some(t) = token.filter(|t| !t.is_empty()) else { return Vec::new() };
    let basico = base64::engine::general_purpose::STANDARD.encode(format!("x-access-token:{t}"));
    vec![
        ("GIT_CONFIG_COUNT".into(), "1".into()),
        ("GIT_CONFIG_KEY_0".into(), "http.https://github.com/.extraheader".into()),
        ("GIT_CONFIG_VALUE_0".into(), format!("AUTHORIZATION: basic {basico}")),
    ]
}

// ============================================================================ repositorios propios

pub fn iniciar(carpeta: &Path) -> Result<(), ErrorGit> {
    if !carpeta.join(".git").is_dir() {
        correr(&["init", "-q", "-b", "main"], Some(carpeta), &Vec::new())?;
    }
    Ok(())
}

/// Commit de todo lo que cambió; None si no había nada que guardar
pub fn guardar(carpeta: &Path, mensaje: &str, firma: &Entorno) -> Result<Option<String>, ErrorGit> {
    correr(&["add", "-A"], Some(carpeta), &Vec::new())?;
    if py::strip(&correr(&["status", "--porcelain"], Some(carpeta), &Vec::new())?).is_empty() {
        return Ok(None);
    }
    correr(&["commit", "-q", "--no-gpg-sign", "-m", mensaje], Some(carpeta), firma)?;
    Ok(cabeza(carpeta))
}

pub fn cabeza(carpeta: &Path) -> Option<String> {
    if !carpeta.is_dir() {
        return None;
    }
    correr(&["rev-parse", "HEAD"], Some(carpeta), &Vec::new()).ok().map(|s| py::strip(&s).to_string())
}

pub fn fijar_remoto(carpeta: &Path, url: &str) -> Result<(), ErrorGit> {
    if correr(&["remote", "set-url", "origin", url], Some(carpeta), &Vec::new()).is_err() {
        correr(&["remote", "add", "origin", url], Some(carpeta), &Vec::new())?;
    }
    Ok(())
}

pub fn publicar(carpeta: &Path, token: Option<&str>) -> Result<(), ErrorGit> {
    correr_t(&["push", "-q", "origin", "HEAD:refs/heads/main"], Some(carpeta), &auth_github(token), 180).map(|_| ())
}

// ============================================================================ repositorios de otros

fn tamano_mb(carpeta: &Path) -> f64 {
    fn suma(d: &Path) -> u64 {
        let Ok(it) = std::fs::read_dir(d) else { return 0 };
        let mut total = 0;
        for e in it.flatten() {
            let p = e.path();
            match e.file_type() {
                Ok(t) if t.is_dir() => total += suma(&p),
                Ok(_) => total += std::fs::metadata(&p).map(|m| m.len()).unwrap_or(0),
                Err(_) => {}
            }
        }
        total
    }
    suma(carpeta) as f64 / 1e6
}

/// `tempfile.mkdtemp(prefix, dir)`
pub fn carpeta_temporal(prefijo: &str, dir: Option<&Path>) -> Result<PathBuf, ErrorGit> {
    use std::os::unix::fs::DirBuilderExt;
    const LETRAS: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789_";
    let base = dir.map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from(prig_plataforma::ejecucion::dir_temporal()));
    let mut semilla =
        SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(1) ^ ((std::process::id() as u64) << 32) | 1;
    for _ in 0..100 {
        let mut nombre = String::from(prefijo);
        for _ in 0..8 {
            semilla ^= semilla << 13;
            semilla ^= semilla >> 7;
            semilla ^= semilla << 17;
            nombre.push(LETRAS[(semilla % LETRAS.len() as u64) as usize] as char);
        }
        let ruta = base.join(nombre);
        match std::fs::DirBuilder::new().mode(0o700).create(&ruta) {
            Ok(()) => return Ok(ruta),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return error(py::error_os(&e, &ruta.to_string_lossy())),
        }
    }
    error("No usable temporary directory name found")
}

/// Clon superficial en una carpeta temporal y, si es válido, se mueve a `destino`
pub fn clonar(url: &str, destino: &Path) -> Result<Option<String>, ErrorGit> {
    let url = validar_url(url)?;
    let padre = destino.parent().unwrap_or(Path::new("."));
    py::makedirs(&padre.to_string_lossy()).or_else(error)?;
    let tmp = carpeta_temporal(".clon_", Some(padre))?;
    let r = (|| {
        correr_t(&["clone", "-q", "--depth", "1", "--no-tags", "--", &url, &tmp.to_string_lossy()], None, &Vec::new(), 180)?;
        let mb = tamano_mb(&tmp);
        if mb > MAX_MB {
            return error(format!("El repositorio pesa {mb:.0} MB: un repositorio de Prig Hub es texto (máximo {MAX_MB:.0} MB)."));
        }
        if destino.exists() {
            let _ = std::fs::remove_dir_all(destino);
        }
        std::fs::rename(&tmp, destino).or_else(|e| error(py::error_os(&e, &tmp.to_string_lossy())))?;
        Ok(cabeza(destino))
    })();
    if tmp.exists() {
        let _ = std::fs::remove_dir_all(&tmp);
    }
    r
}

/// Descarga lo último del remoto SIN aplicarlo; devuelve el commit traído
pub fn traer(carpeta: &Path) -> Result<String, ErrorGit> {
    correr_t(&["fetch", "-q", "--depth", "1", "--no-tags", "origin", "HEAD"], Some(carpeta), &Vec::new(), 180)?;
    Ok(py::strip(&correr(&["rev-parse", "FETCH_HEAD"], Some(carpeta), &Vec::new())?).to_string())
}

fn octal(campo: &[u8]) -> u64 {
    let t = String::from_utf8_lossy(campo);
    u64::from_str_radix(t.trim_matches(|c: char| c == '\0' || c == ' '), 8).unwrap_or(0)
}

fn cadena(campo: &[u8]) -> String {
    let fin = campo.iter().position(|&b| b == 0).unwrap_or(campo.len());
    String::from_utf8_lossy(&campo[..fin]).into_owned()
}

/// El nombre dentro de la carpeta, o None si sale de ella (el filtro «data» de tarfile no lo extrae)
fn dentro(nombre: &str) -> Option<PathBuf> {
    if nombre.starts_with('/') {
        return None;
    }
    let mut p = PathBuf::new();
    for t in nombre.split('/') {
        match t {
            "" | "." => {}
            ".." => return None,
            t => p.push(t),
        }
    }
    Some(p)
}

/// Extrae el tar de `git archive` (ustar con cabeceras pax) con las reglas del filtro «data»: nada fuera de la
/// carpeta, y un enlace solo si apunta dentro
fn extraer_tar(datos: &[u8], destino: &Path) -> Result<(), ErrorGit> {
    let mut i = 0usize;
    let mut largo_pax: Option<String> = None;
    while i + 512 <= datos.len() {
        let h = &datos[i..i + 512];
        if h.iter().all(|&b| b == 0) {
            break;
        }
        let tamano = octal(&h[124..136]) as usize;
        let tipo = h[156];
        let cuerpo = &datos[(i + 512).min(datos.len())..(i + 512 + tamano).min(datos.len())];
        i += 512 + tamano.div_ceil(512) * 512;
        let mut nombre = cadena(&h[0..100]);
        if &h[257..262] == b"ustar" {
            let prefijo = cadena(&h[345..500]);
            if !prefijo.is_empty() {
                nombre = format!("{prefijo}/{nombre}");
            }
        }
        match tipo {
            b'x' => {
                // pax: «largo clave=valor\n»
                let t = String::from_utf8_lossy(cuerpo);
                for l in t.split('\n') {
                    if let Some((_, kv)) = l.split_once(' ') {
                        if let Some(p) = kv.strip_prefix("path=") {
                            largo_pax = Some(p.to_string());
                        }
                    }
                }
                continue;
            }
            b'g' => continue,
            _ => {}
        }
        if let Some(p) = largo_pax.take() {
            nombre = p;
        }
        let Some(rel) = dentro(&nombre) else { return error(format!("Ruta fuera de la carpeta en el archivo: {nombre}")) };
        let ruta = destino.join(&rel);
        match tipo {
            b'5' => {
                std::fs::create_dir_all(&ruta).or_else(|e| error(e.to_string()))?;
            }
            b'0' | 0 | b'7' => {
                if let Some(p) = ruta.parent() {
                    std::fs::create_dir_all(p).or_else(|e| error(e.to_string()))?;
                }
                std::fs::write(&ruta, cuerpo).or_else(|e| error(e.to_string()))?;
            }
            b'2' => {
                let objetivo = cadena(&h[157..257]);
                let base = rel.parent().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default();
                let unido = if base.is_empty() { objetivo.clone() } else { format!("{base}/{objetivo}") };
                if objetivo.starts_with('/') || dentro(&py::normpath(&unido)).is_none() || py::normpath(&unido).starts_with("..") {
                    return error(format!("{nombre} es un enlace que sale de la carpeta"));
                }
                if let Some(p) = ruta.parent() {
                    std::fs::create_dir_all(p).or_else(|e| error(e.to_string()))?;
                }
                std::os::unix::fs::symlink(&objetivo, &ruta).or_else(|e| error(e.to_string()))?;
            }
            _ => {}
        }
    }
    Ok(())
}

/// El contenido de un commit en una carpeta temporal (para leerlo y compararlo sin aplicarlo)
pub fn extraer(carpeta: &Path, commit: &str) -> Result<PathBuf, ErrorGit> {
    let datos = correr_bytes(&["archive", "--format=tar", commit], Some(carpeta), &Vec::new(), 60)?;
    let destino = carpeta_temporal("prig_hub_ver_", None)?;
    if let Err(e) = extraer_tar(&datos, &destino) {
        let _ = std::fs::remove_dir_all(&destino);
        return Err(e);
    }
    Ok(destino)
}

pub fn aplicar(carpeta: &Path, commit: &str) -> Result<(), ErrorGit> {
    correr(&["reset", "-q", "--hard", commit], Some(carpeta), &Vec::new()).map(|_| ())
}
