//! El widget de estadísticas para el perfil de GitHub (`github_stats_widget.py`): la configuración, las métricas del
//! alumno, la tarjeta en SVG y la publicación en el repositorio de perfil (`login/login`).

use crate::kaggle::{ErrorKaggle as ErrorUsuario, Fallo};
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use std::path::{Path, PathBuf};

/// (clave, nombre, fondo, borde, texto, subtexto, acentos 1..5, gradiente inicio, fin)
const TEMAS: [(&str, &str, [&str; 11]); 4] = [
    ("catppuccin", "Catppuccin Macchiato", ["#1e1e2e", "#313244", "#cdd6f4", "#a6adc8", "#fab387", "#cba6f7", "#f38ba8", "#89b4fa", "#a6e3a1", "#89b4fa", "#cba6f7"]),
    ("mocha", "Mocha Dark", ["#11111b", "#27293a", "#ffffff", "#9399b2", "#f9e2af", "#b4befe", "#eba0ac", "#74c7ec", "#94e2d5", "#a6e3a1", "#94e2d5"]),
    ("cyber", "Cyber Neon", ["#0b0f19", "#1e293b", "#f8fafc", "#94a3b8", "#00f2fe", "#4facfe", "#f72585", "#7209b7", "#10b981", "#00f2fe", "#7209b7"]),
    ("minimal", "Minimal Monocromo", ["#0d1117", "#30363d", "#e6edf3", "#7d8590", "#58a6ff", "#3fb950", "#d29922", "#bc8cff", "#3fb950", "#58a6ff", "#3fb950"]),
];

fn por_defecto() -> Mapa {
    Mapa::new()
        .con("tema", "catppuccin")
        .con("mostrar_racha", true)
        .con("mostrar_desafios", true)
        .con("mostrar_youtube", true)
        .con("mostrar_kaggle", true)
        .con("mostrar_conceptos", true)
        .con("mostrar_modelos", false)
        .con("mostrar_nivel", true)
        .con("ultimo_sync", Valor::Nulo)
}

fn archivo() -> PathBuf {
    PathBuf::from(py::expanduser("~/.prig_github_widget.json"))
}

/// Los nombres de los temas (`{clave: nombre}`)
pub fn temas() -> Mapa {
    let mut m = Mapa::new();
    for (k, n, _) in TEMAS {
        m.poner(k, n);
    }
    m
}

/// `leer_config()`: lo guardado sobre lo de por defecto
pub fn leer_config() -> Mapa {
    let mut c = por_defecto();
    if let Some(Valor::Mapa(d)) = std::fs::read_to_string(archivo()).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        for (k, v) in d.iter() {
            c.poner(k.clone(), v.clone());
        }
    }
    c
}

/// `guardar_config(cambios)`
pub fn guardar_config(cambios: &Mapa) -> Mapa {
    let mut c = leer_config();
    for (k, v) in cambios.iter() {
        c.poner(k.clone(), v.clone());
    }
    let ruta = archivo();
    let tmp = PathBuf::from(format!("{}.tmp", ruta.display()));
    if let Some(p) = ruta.parent() {
        let _ = std::fs::create_dir_all(p);
    }
    if std::fs::write(&tmp, prig_plataforma::json::escribir(&Valor::Mapa(c.clone()), 2)).is_ok() {
        let _ = std::fs::rename(&tmp, &ruta);
    }
    c
}

fn esc(t: &str) -> String {
    t.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&apos;")
}

/// `stats.get(k, defecto)` como texto de Python
fn g(m: &Mapa, k: &str, defecto: Valor) -> String {
    m.get(k).cloned().unwrap_or(defecto).texto_py()
}

/// `recolectar_estadisticas(progreso, almacen, extras)`
pub fn estadisticas(dir_desafios: &Path, extras: Option<&Mapa>) -> Mapa {
    let perfil = prig_plataforma::inicio::perfil().unwrap_or_default();
    let o = |k: &str, defecto: &str| match perfil.get(k) {
        Some(v) if v.verdad() => v.clone(),
        _ => Valor::Texto(defecto.into()),
    };
    let (mut racha, mut mejor, mut activos, mut resueltos, mut conceptos) = (Valor::Entero(0), Valor::Entero(0), Valor::Entero(0), Valor::Entero(0), 0usize);
    // `progreso.resumen(almacen)`: sin rutas, telemetría ni dataset (`por_lenguaje` no existe: Python ponía 0)
    if let Ok(r) = prig_aprendizaje::progreso::resumen(dir_desafios, None, 120, Vec::new()) {
        if let Some(rc) = r.mapa("racha") {
            racha = rc.get("actual").cloned().unwrap_or(Valor::Entero(0));
            mejor = rc.get("mejor").cloned().unwrap_or(Valor::Entero(0));
            activos = rc.get("dias_activos").cloned().unwrap_or(Valor::Entero(0));
        }
        resueltos = r.mapa("desafios").and_then(|d| d.mapa("por_estado")).and_then(|p| p.get("resuelto").cloned()).unwrap_or(Valor::Entero(0));
        conceptos = r.lista("fuertes").map(|l| l.len()).unwrap_or(0);
    }
    let (mut n_cols, mut n_notas) = (0usize, 0usize);
    if let (Ok(l), Ok(rec)) = (crate::kaggle::listado(), crate::kaggle::recientes(100)) {
        n_cols = l.lista("colecciones").map(|c| c.len()).unwrap_or(0);
        n_notas = rec.iter().filter(|it| it.verdad("nota")).count();
    }
    let vacio = Mapa::new();
    let extras = extras.unwrap_or(&vacio);
    let e = |k: &str| extras.get(k).cloned().unwrap_or(Valor::Entero(0));
    let num = |v: &Valor| v.num().unwrap_or(0.0);
    let pct_desafios = (num(&resueltos) * 5.0).min(100.0);
    let pct_racha = (num(&racha) * 10.0).min(100.0);
    let general = ((pct_desafios * 0.5 + pct_racha * 0.3 + conceptos as f64 * 4.0).round_ties_even()).clamp(10.0, 100.0) as i128;
    let hoy: String = py::ahora_iso().chars().take(10).collect();
    Mapa::new()
        .con("nombre", o("nombre", "Estudiante de Prig"))
        .con("nivel", o("nivel", "intermedio"))
        .con("objetivo", o("objetivo", "Machine Learning & Programación"))
        .con("racha_actual", racha)
        .con("racha_mejor", mejor)
        .con("dias_activos", activos)
        .con("desafios_resueltos", resueltos)
        .con("desafios_python", 0)
        .con("desafios_cpp", 0)
        .con("conceptos_dominados", conceptos as i128)
        .con("kaggle_celdas", 0)
        .con("kaggle_colecciones", n_cols as i128)
        .con("kaggle_notas", n_notas as i128)
        .con("youtube_cursos", e("yt_cursos_completados"))
        .con("youtube_horas", e("yt_horas"))
        .con("youtube_fotogramas", e("yt_fotogramas"))
        .con("youtube_notas", e("yt_notas"))
        .con("porcentaje_general", general)
        .con("modelo_local", match extras.get("modelo_local") {
            Some(v) if v.verdad() => v.clone(),
            _ => Valor::Texto("Qwen 2.5 Coder / DeepSeek".into()),
        })
        .con("fecha", hoy)
}

/// `str.capitalize()`
fn capitalizar(t: &str) -> String {
    let mut c = t.chars();
    match c.next() {
        Some(p) => p.to_uppercase().collect::<String>() + &c.as_str().to_lowercase(),
        None => String::new(),
    }
}

/// `generar_svg(stats, config)`: la tarjeta
pub fn svg(stats: &Mapa, cfg: &Mapa) -> String {
    let clave = match cfg.get("tema") {
        Some(v) if v.verdad() => v.texto_py(),
        _ => "catppuccin".into(),
    };
    let t = TEMAS.iter().find(|x| x.0 == clave).unwrap_or(&TEMAS[0]).2;
    let [fondo, borde, texto, subtexto, a1, a2, a3, a4, a5, gi, gf] = t;
    let nombre = esc(&match stats.get("nombre") {
        Some(v) if v.verdad() => v.texto_py(),
        _ => "Estudiante de Prig".into(),
    });
    let nivel = esc(&capitalizar(&match stats.get("nivel") {
        Some(v) if v.verdad() => v.texto_py(),
        _ => "intermedio".into(),
    }));
    let pct = match stats.get("porcentaje_general") {
        Some(v) if v.verdad() => v.num().unwrap_or(25.0) as i64,
        _ => 25,
    }
    .clamp(5, 100);
    let barra = (435.0 * (pct as f64 / 100.0)).round_ties_even() as i64;
    let mostrar = |k: &str, d: bool| match cfg.get(k) {
        None => d,
        Some(v) => v.verdad(),
    };
    let mut tarjetas: Vec<(&str, &str, String, String, &str)> = Vec::new();
    let z = || Valor::Entero(0);
    if mostrar("mostrar_racha", true) {
        tarjetas.push(("🔥", "Racha Activa", format!("{} días", g(stats, "racha_actual", z())), format!("Mejor: {}d · {} activos", g(stats, "racha_mejor", z()), g(stats, "dias_activos", z())), a1));
    }
    if mostrar("mostrar_desafios", true) {
        tarjetas.push(("♟️", "Desafíos", format!("{} resueltos", g(stats, "desafios_resueltos", z())), format!("{} Python · {} C++", g(stats, "desafios_python", z()), g(stats, "desafios_cpp", z())), a2));
    }
    if mostrar("mostrar_youtube", true) {
        tarjetas.push(("📺", "YouTube Study", format!("{} clases/cursos", g(stats, "youtube_cursos", z())), format!("{} notas y fotogramas", g(stats, "youtube_fotogramas", z())), a3));
    }
    if mostrar("mostrar_kaggle", true) {
        tarjetas.push(("📖", "Kaggle Learning", format!("{} celdas leídas", g(stats, "kaggle_celdas", z())), format!("{} colecciones guardadas", g(stats, "kaggle_colecciones", z())), a4));
    }
    if mostrar("mostrar_conceptos", true) {
        tarjetas.push(("🎯", "Conceptos", format!("{} dominados", g(stats, "conceptos_dominados", z())), "ML, Redes & Algoritmos".into(), a5));
    }
    if mostrar("mostrar_modelos", false) {
        let m: String = g(stats, "modelo_local", Valor::Texto("Qwen 2.5 Coder".into())).chars().take(16).collect();
        tarjetas.push(("🧠", "Modelo Local", m, "Inferencia privada local".into(), a2));
    }
    let mut items = String::new();
    for (i, (icono, titulo, valor, sub, color)) in tarjetas.iter().take(6).enumerate() {
        let (x, y) = (24 + (i % 2) as i64 * (210 + 15), 80 + (i / 2) as i64 * (56 + 10));
        items += &format!(
            r#"
        <g transform="translate({x}, {y})">
          <rect width="210" height="56" rx="8" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.07)" stroke-width="1"/>
          <text x="12" y="24" font-size="16">{}</text>
          <text x="36" y="20" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600" fill="{subtexto}">{}</text>
          <text x="36" y="36" font-family="system-ui, -apple-system, sans-serif" font-size="12.5" font-weight="700" fill="{color}">{}</text>
          <text x="36" y="48" font-family="system-ui, -apple-system, sans-serif" font-size="9" fill="{subtexto}">{}</text>
        </g>
        "#,
            esc(icono),
            esc(titulo),
            esc(valor),
            esc(sub)
        );
    }
    let fecha = g(stats, "fecha", Valor::Texto(String::new()));
    let s = format!(
        r##"<svg width="495" height="240" viewBox="0 0 495 240" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="gradienteBarra" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="{gi}"/>
      <stop offset="100%" stop-color="{gf}"/>
    </linearGradient>
    <linearGradient id="gradienteLogo" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#89b4fa"/>
      <stop offset="100%" stop-color="#cba6f7"/>
    </linearGradient>
  </defs>

  <!-- Fondo de la tarjeta -->
  <rect width="495" height="240" rx="14" fill="{fondo}" stroke="{borde}" stroke-width="1.2"/>

  <!-- Cabecera: Logo de Prig IDE, Nombre y Nivel -->
  <g transform="translate(24, 20)">
    <!-- Insignia P de Prig -->
    <rect width="32" height="32" rx="8" fill="url(#gradienteLogo)"/>
    <text x="16" y="22" font-family="'Fira Code', system-ui, monospace" font-size="18" font-weight="800" fill="#11111b" text-anchor="middle">P</text>

    <!-- Título y subtítulo -->
    <text x="42" y="16" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" fill="{texto}">{nombre}</text>
    <text x="42" y="29" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="500" fill="{subtexto}">Aprendizaje en <tspan font-weight="700" fill="{gf}">Prig IDE</tspan> · Nivel {nivel}</text>

    <!-- Badge de Estado Activo -->
    <rect x="365" y="4" width="70" height="20" rx="10" fill="rgba(166,227,161,0.14)" stroke="rgba(166,227,161,0.3)" stroke-width="1"/>
    <circle cx="377" cy="14" r="3.5" fill="#a6e3a1"/>
    <text x="385" y="17.5" font-family="system-ui, -apple-system, sans-serif" font-size="9.5" font-weight="700" fill="#a6e3a1">ACTIVO</text>
  </g>

  <!-- Cuadrícula de Métricas -->
  {items}

  <!-- Barra de Avance y Dominio -->
  <g transform="translate(24, 208)">
    <rect width="435" height="7" rx="3.5" fill="rgba(255,255,255,0.08)"/>
    <rect width="{barra}" height="7" rx="3.5" fill="url(#gradienteBarra)"/>
    <text x="0" y="-4" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600" fill="{subtexto}">Nivel de Dominio General: <tspan font-weight="700" fill="{texto}">{pct}%</tspan></text>
    <text x="435" y="-4" font-family="system-ui, -apple-system, sans-serif" font-size="8.5" fill="{subtexto}" text-anchor="end">{fecha}</text>
  </g>
</svg>"##
    );
    s.trim().to_string()
}

// ---------------------------------------------------------------------------------------------- GitHub

fn cliente() -> Option<reqwest::blocking::Client> {
    reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(25)).build().ok()
}

fn api() -> String {
    std::env::var("PRIG_GITHUB_API").ok().filter(|v| !v.is_empty()).unwrap_or_else(|| "https://api.github.com".into())
}

/// El usuario de GitHub del token (None si no hay o no se puede saber)
pub fn usuario(token: &str) -> Option<Mapa> {
    let r = cliente()?
        .get(format!("{}/user", api()))
        .header("Authorization", format!("Bearer {token}"))
        .header("Accept", "application/vnd.github.v3+json")
        .header("User-Agent", "Prig-IDE")
        .send()
        .ok()?;
    if r.status().as_u16() != 200 {
        return None;
    }
    match prig_plataforma::json::leer(&r.text().ok()?).ok()? {
        Valor::Mapa(m) => Some(m),
        _ => None,
    }
}

/// El token de GitHub guardado (o de las variables)
pub fn token() -> Option<String> {
    let ruta = std::env::var("PRIG_GITHUB_CREDENCIALES").ok().filter(|v| !v.is_empty()).unwrap_or_else(|| py::expanduser("~/.prig_github.json"));
    if let Some(Valor::Mapa(m)) = std::fs::read_to_string(ruta).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
        if m.verdad("token") {
            return Some(m.valor("token").texto_py());
        }
    }
    ["GITHUB_TOKEN", "GH_TOKEN"].iter().find_map(|v| std::env::var(v).ok().filter(|x| !x.is_empty()))
}

/// `inyectar_en_readme(contenido, login)`: pone o actualiza el bloque de Prig sin tocar lo demás
pub fn inyectar_en_readme(actual: &str, login: &str) -> String {
    let bloque = format!(
        r#"<!-- PRIG-STATS:START -->
<div align="center">
  <a href="https://github.com/guillermopetcho/Prig-IDE">
    <img src="https://raw.githubusercontent.com/{login}/{login}/main/prig-stats.svg" alt="Estadísticas de Estudio en Prig IDE" width="495"/>
  </a>
  <br/>
  <a href="https://github.com/guillermopetcho/Prig-IDE">
    <img src="https://img.shields.io/badge/Estudiando_con-Prig_IDE-cba6f7?style=flat-square&logo=visualstudiocode&logoColor=white" alt="Prig IDE Badge"/>
  </a>
</div>
<!-- PRIG-STATS:END -->"#
    );
    let re = regex::Regex::new(r"(?s)<!-- PRIG-STATS:START -->.*?<!-- PRIG-STATS:END -->").unwrap();
    if re.is_match(actual) {
        return re.replace_all(actual, regex::NoExpand(&bloque)).into_owned();
    }
    let sep = if py::strip(actual).is_empty() { "" } else { "\n\n" };
    format!("{}{sep}{bloque}\n", actual.trim_end())
}

fn fallo<T>(t: impl Into<String>) -> Result<T, Fallo> {
    Err(Fallo::Usuario(ErrorUsuario(t.into())))
}

/// `sincronizar_con_github(token, stats, config)`: sube prig-stats.svg y actualiza el README del repo de perfil.
/// Un fallo de GitHub es un 400 con el motivo (en Python era un `ValueError` sin capturar: 500)
pub fn publicar(token: &str, stats: &Mapa, cfg: &Mapa) -> Result<Mapa, Fallo> {
    use base64::Engine;
    let b64 = base64::engine::general_purpose::STANDARD;
    let c = cliente().ok_or(Fallo::Interno)?;
    let cab = |r: reqwest::blocking::RequestBuilder| {
        r.header("User-Agent", "Prig-IDE (github-stats-widget)").header("Authorization", format!("Bearer {token}")).header("Accept", "application/vnd.github+json")
    };
    let base = api();
    let json = |r: reqwest::blocking::Response| -> Option<Mapa> {
        match prig_plataforma::json::leer(&r.text().ok()?).ok()? {
            Valor::Mapa(m) => Some(m),
            _ => None,
        }
    };
    let Ok(ru) = cab(c.get(format!("{base}/user"))).send() else { return fallo("Sin conexión con GitHub.") };
    if ru.status().as_u16() != 200 {
        return fallo(format!("No se pudo acceder a tu cuenta de GitHub ({}). Verifica el token.", ru.status().as_u16()));
    }
    let login = json(ru).and_then(|m| m.texto("login").map(String::from)).ok_or(Fallo::Interno)?;
    let repo = format!("{base}/repos/{login}/{login}");
    let rr = cab(c.get(&repo)).send().or_else(|_| fallo("Sin conexión con GitHub."))?;
    if rr.status().as_u16() == 404 {
        let cuerpo = Mapa::new().con("name", login.clone()).con("description", "Mi perfil de GitHub y progreso en Prig IDE").con("private", false).con("auto_init", true);
        let rc = cab(c.post(format!("{base}/user/repos"))).header("Content-Type", "application/json").body(prig_plataforma::json::escribir_compacto(&Valor::Mapa(cuerpo))).send();
        let estado = rc.map(|r| r.status().as_u16()).unwrap_or(0);
        if estado != 200 && estado != 201 {
            return fallo(format!(
                "GitHub no permitió crear el repositorio de perfil «{login}/{login}» ({estado}). Comprueba que el token tenga permiso «Administration: write»."
            ));
        }
    }
    let subir = |ruta: &str, contenido: &str, mensaje: &str| -> Result<u16, Fallo> {
        let url = format!("{repo}/contents/{ruta}");
        let sha = cab(c.get(&url)).send().ok().filter(|r| r.status().as_u16() == 200).and_then(json).and_then(|m| m.get("sha").cloned()).filter(|v| v.verdad());
        let mut cuerpo = Mapa::new().con("message", mensaje).con("content", b64.encode(contenido.as_bytes()));
        if let Some(s) = sha {
            cuerpo.poner("sha", s);
        }
        let r = cab(c.put(&url)).header("Content-Type", "application/json").body(prig_plataforma::json::escribir_compacto(&Valor::Mapa(cuerpo))).send();
        Ok(r.map(|r| r.status().as_u16()).unwrap_or(0))
    };
    let e = subir("prig-stats.svg", &svg(stats, cfg), "chore(prig): update learning stats widget [skip ci]")?;
    if e != 200 && e != 201 {
        return fallo(format!("Error subiendo prig-stats.svg a GitHub ({e}). Comprueba que el token tenga permiso «Contents: write»."));
    }
    let mut readme = format!("# {login}\n");
    if let Some(m) = cab(c.get(format!("{repo}/contents/README.md"))).send().ok().filter(|r| r.status().as_u16() == 200).and_then(json) {
        let contenido: String = m.texto("content").unwrap_or("").chars().filter(|c| !c.is_whitespace()).collect();
        readme = b64.decode(contenido).ok().and_then(|b| String::from_utf8(b).ok()).unwrap_or_else(|| format!("# {login}\n"));
    }
    let e = subir("README.md", &inyectar_en_readme(&readme, &login), "chore(prig): sync profile learning widgets [skip ci]")?;
    if e != 200 && e != 201 {
        return fallo(format!("Error actualizando README.md en GitHub ({e})."));
    }
    guardar_config(&Mapa::new().con("ultimo_sync", py::ahora_iso()).con("ultimo_login", login.clone()));
    Ok(Mapa::new()
        .con("ok", true)
        .con("login", login.clone())
        .con("repo_url", format!("https://github.com/{login}/{login}"))
        .con("profile_url", format!("https://github.com/{login}"))
        .con("svg_url", format!("https://raw.githubusercontent.com/{login}/{login}/main/prig-stats.svg"))
        .con("mensaje", format!("¡Widget y README.md sincronizados exitosamente en {login}/{login}!")))
}
