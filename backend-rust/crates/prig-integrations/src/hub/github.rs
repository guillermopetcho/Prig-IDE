//! Lo que Prig Hub necesita de GitHub (`hub/github.py`), sobre el mismo cliente que la sección GitHub (su token y su
//! URL de API, que las pruebas cambian):
//!
//!   · usuario, repo, crear_repo y temas: para publicar (necesitan token);
//!   · es_hub: ¿tiene prig.yaml? Se lee el archivo en crudo, que no gasta cuota de la API;
//!   · descubrir: repositorios con el topic prig-perfil o prig-pack.

use super::enlaces;
use crate::github as gl;
use crate::kaggle::Fallo;
use prig_plataforma::valor::{Mapa, Valor};
use regex::Regex;
use std::sync::LazyLock;
use std::time::Duration;

/// `ErrorGitHubHub` (un 400 con su mensaje), o un fallo interno
#[derive(Debug)]
pub enum ErrorGitHubHub {
    Usuario(String),
    Interno,
}

fn error<T>(t: impl Into<String>) -> Result<T, ErrorGitHubHub> {
    Err(ErrorGitHubHub::Usuario(t.into()))
}

fn de_fallo(f: Fallo) -> ErrorGitHubHub {
    match f {
        Fallo::Usuario(e) => ErrorGitHubHub::Usuario(e.0),
        Fallo::Interno => ErrorGitHubHub::Interno,
    }
}

static NO_TEMA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^a-z0-9-]+").unwrap());
static DIRECTO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"github\.com[/:]([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)").unwrap());
static DUENO_REPO: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$").unwrap());

/// Una respuesta de GitHub: estado y cuerpo
pub struct Respuesta {
    pub estado: u16,
    pub cuerpo: String,
}

impl Respuesta {
    pub fn json(&self) -> Valor {
        prig_plataforma::json::leer(&self.cuerpo).unwrap_or(Valor::Nulo)
    }
}

/// Operaciones con la cuenta del usuario: necesitan token
pub struct Cuenta {
    pub token: String,
}

impl Cuenta {
    fn pedir(&self, metodo: &str, ruta: &str, cuerpo: Option<&Valor>) -> Result<Respuesta, ErrorGitHubHub> {
        let c = reqwest::blocking::Client::builder().timeout(Duration::from_secs(30)).build().map_err(|_| ErrorGitHubHub::Interno)?;
        let m = reqwest::Method::from_bytes(metodo.as_bytes()).map_err(|_| ErrorGitHubHub::Interno)?;
        let mut r = c
            .request(m, format!("{}/{ruta}", gl::api()))
            .header("User-Agent", gl::UA)
            .header("Accept", gl::ACCEPT)
            .header("Authorization", format!("Bearer {}", self.token));
        if let Some(v) = cuerpo {
            r = r.header("Content-Type", "application/json").body(prig_plataforma::json::escribir_compacto(v));
        }
        let Ok(r) = r.send() else { return error("Sin conexión con GitHub.") };
        let estado = r.status().as_u16();
        let Ok(cuerpo) = r.text() else { return error("Sin conexión con GitHub.") };
        if estado == 401 {
            return error("GitHub no aceptó el token: vuelve a pegarlo en la sección GitHub.");
        }
        Ok(Respuesta { estado, cuerpo })
    }

    pub fn usuario(&self) -> Result<Mapa, ErrorGitHubHub> {
        let r = self.pedir("GET", "user", None)?;
        if r.estado != 200 {
            return error(format!("No se pudo leer tu cuenta de GitHub ({}).", r.estado));
        }
        let Valor::Mapa(d) = r.json() else { return Err(ErrorGitHubHub::Interno) };
        if !d.contiene("login") || !d.contiene("id") {
            return Err(ErrorGitHubHub::Interno);
        }
        Ok(Mapa::new().con("login", d.valor("login").clone()).con("id", d.valor("id").clone()))
    }

    pub fn repo(&self, login: &str, nombre: &str) -> Result<Option<Mapa>, ErrorGitHubHub> {
        let r = self.pedir("GET", &format!("repos/{login}/{nombre}"), None)?;
        if r.estado == 404 {
            return Ok(None);
        }
        if r.estado != 200 {
            return error(format!("GitHub respondió {} al buscar {login}/{nombre}.", r.estado));
        }
        match r.json() {
            Valor::Mapa(m) => Ok(Some(m)),
            _ => Err(ErrorGitHubHub::Interno),
        }
    }

    pub fn crear_repo(&self, nombre: &str, descripcion: &str) -> Result<Mapa, ErrorGitHubHub> {
        let cuerpo = Mapa::new()
            .con("name", nombre)
            .con("description", descripcion)
            .con("private", false)
            .con("has_wiki", false)
            .con("auto_init", false);
        let r = self.pedir("POST", "user/repos", Some(&Valor::Mapa(cuerpo)))?;
        if r.estado == 403 || r.estado == 404 {
            return error(format!(
                "El token no tiene permiso para crear repositorios. Crea en GitHub un repositorio vacío llamado «{nombre}» \
                 (o da al token permiso «Administration: write») y vuelve a publicar."
            ));
        }
        if r.estado == 422 {
            let msj = match r.json() {
                Valor::Mapa(m) => match m.lista("errors").filter(|l| !l.is_empty()) {
                    Some(l) => match &l[0] {
                        Valor::Mapa(e) => e.get("message").map(Valor::texto_py).unwrap_or_else(|| "nombre no válido".into()),
                        _ => return Err(ErrorGitHubHub::Interno),
                    },
                    None => "nombre no válido".into(),
                },
                _ => return Err(ErrorGitHubHub::Interno),
            };
            return error(format!("GitHub no dejó crear «{nombre}»: {msj}."));
        }
        if r.estado != 200 && r.estado != 201 {
            return error(format!("GitHub respondió {} al crear el repositorio.", r.estado));
        }
        match r.json() {
            Valor::Mapa(m) => Ok(m),
            _ => Err(ErrorGitHubHub::Interno),
        }
    }

    pub fn temas(&self, login: &str, nombre: &str, temas: &[String]) -> Result<(), ErrorGitHubHub> {
        let mut limpios: Vec<String> = Vec::new();
        for t in temas {
            let t = NO_TEMA.replace_all(&t.to_lowercase(), "-").trim_matches('-').chars().take(50).collect::<String>();
            if !t.is_empty() && !limpios.contains(&t) {
                limpios.push(t);
            }
        }
        limpios.truncate(20);
        let cuerpo = Mapa::new().con("names", Valor::Lista(limpios.into_iter().map(Valor::Texto).collect()));
        self.pedir("PUT", &format!("repos/{login}/{nombre}/topics"), Some(&Valor::Mapa(cuerpo)))?;
        Ok(())
    }
}

fn crudo(info: &Mapa, archivo: &str) -> Option<String> {
    let r = info.texto("ref")?;
    match info.texto("plataforma")? {
        "github" => Some(format!("{}/{r}/HEAD/{archivo}", gl::raw())),
        "gitlab" => Some(format!("https://gitlab.com/{r}/-/raw/HEAD/{archivo}")),
        "codeberg" => Some(format!("https://codeberg.org/{r}/raw/branch/main/{archivo}")),
        _ => None,
    }
}

/// `es_hub(url)`: ¿el repositorio tiene un prig.yaml? (en crudo: no cuenta para el límite de la API)
pub fn es_hub(url: &str) -> bool {
    let Ok(info) = enlaces::reconocer(url) else { return false };
    if info.texto("tipo") != Some("repositorio") {
        return false;
    }
    let Some(u) = crudo(&info, "prig.yaml") else { return false };
    let Ok(c) = reqwest::blocking::Client::builder().timeout(Duration::from_secs(10)).build() else { return false };
    let Ok(r) = c.get(u).header("User-Agent", gl::UA).send() else { return false };
    let estado = r.status().as_u16();
    let Ok(b) = r.bytes() else { return false };
    let texto = String::from_utf8_lossy(&b);
    estado == 200 && texto.chars().take(4000).collect::<String>().contains("tipo") && b.len() < 64 * 1024
}

fn fila(r: &Mapa) -> Result<Valor, ErrorGitHubHub> {
    let dueno = r.mapa("owner").cloned().unwrap_or_default();
    let o = |v: &Valor, y: Valor| if v.verdad() { v.clone() } else { y };
    for k in ["full_name", "html_url", "name"] {
        if !r.contiene(k) {
            return Err(ErrorGitHubHub::Interno);
        }
    }
    Ok(Valor::Mapa(
        Mapa::new()
            .con("ref", r.valor("full_name").clone())
            .con("url", r.valor("html_url").clone())
            .con("titulo", r.valor("name").clone())
            .con("descripcion", o(r.valor("description"), Valor::Texto(String::new())))
            .con("estrellas", r.get("stargazers_count").cloned().unwrap_or(Valor::Entero(0)))
            .con("actualizado", r.valor("pushed_at").clone())
            .con("temas", o(r.valor("topics"), Valor::Lista(Vec::new())))
            .con("dueno", dueno.valor("login").clone())
            .con("avatar", dueno.valor("avatar_url").clone()),
    ))
}

/// `descubrir(consulta, tipo, pagina)`
pub fn descubrir(consulta: &str, tipo: &str, pagina: i64) -> Result<Mapa, ErrorGitHubHub> {
    let c = prig_plataforma::py::strip(consulta);
    // 1. Búsqueda directa si es un dueño/repo concreto (usuario/Prig-Python o el enlace completo)
    let directo = match DIRECTO.captures(c) {
        Some(m) => Some((m[1].to_string(), m[2].to_string())),
        None if DUENO_REPO.is_match(c) => c.split_once('/').map(|(a, b)| (a.to_string(), b.to_string())),
        None => None,
    };
    if let Some((dueno, repo)) = directo {
        let repo = repo.strip_suffix(".git").unwrap_or(&repo).to_string();
        if let Ok(Valor::Mapa(r)) = gl::llamar(&format!("repos/{dueno}/{repo}"), &[]) {
            if r.contiene("name") {
                if let Ok(f) = fila(&r) {
                    return Ok(Mapa::new().con("total", 1).con("repos", Valor::Lista(vec![f])));
                }
            }
        }
    }
    // 2. Por nombre Prig- o por topics
    let tema = if tipo == "perfil" { "prig-perfil" } else { "prig-pack" };
    let bajo = c.to_lowercase();
    let q = if bajo.starts_with("prig-") || bajo == "prig" {
        format!("{c} in:name fork:true")
    } else if !c.is_empty() {
        format!("topic:{tema} {c}")
    } else {
        format!("topic:{tema}")
    };
    let buscar = |q: &str, pagina: i64| {
        gl::llamar(
            "search/repositories",
            &[("q", q.to_string()), ("sort", "stars".into()), ("per_page", "30".into()), ("page", pagina.to_string())],
        )
    };
    let mut d = match buscar(&q, pagina.max(1)).map_err(de_fallo)? {
        Valor::Mapa(m) => m,
        _ => return Err(ErrorGitHubHub::Interno),
    };
    let total = |d: &Mapa| d.get("total_count").and_then(Valor::num).unwrap_or(0.0);
    if (total(&d) == 0.0 || !d.valor("items").verdad()) && !c.is_empty() && !bajo.starts_with("prig-") {
        if let Ok(Valor::Mapa(fb)) = buscar(&format!("prig-{c} in:name fork:true"), 1) {
            if total(&fb) > 0.0 {
                d = fb;
            }
        }
    }
    let mut salida = Vec::new();
    for r in d.lista("items").unwrap_or(&[]) {
        let Valor::Mapa(r) = r else { return Err(ErrorGitHubHub::Interno) };
        salida.push(fila(r)?);
    }
    Ok(Mapa::new().con("total", d.get("total_count").cloned().unwrap_or(Valor::Entero(0))).con("repos", Valor::Lista(salida)))
}
