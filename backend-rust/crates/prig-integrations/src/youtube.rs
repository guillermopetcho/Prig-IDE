//! YouTube sin el modelo (`youtube_buscador.py` y la transcripción de `youtube_analisis.py`): buscar cursos y listas
//! (InnerTube y, si falla, el HTML), con el ranking didáctico; las sugerencias; abrir un enlace en el navegador; y la
//! transcripción con tiempos (pistas de subtítulos, XML, párrafos y traducción en lotes), con caché en disco.

use prig_plataforma::html::unescape;
use prig_plataforma::valor::{redondear, Mapa, Valor};
use regex::Regex;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

fn entorno(v: &str, defecto: &str) -> String {
    std::env::var(v).ok().filter(|x| !x.is_empty()).unwrap_or_else(|| defecto.into())
}
fn youtube() -> String {
    entorno("PRIG_YOUTUBE_URL", "https://www.youtube.com")
}
fn sugerencias_url() -> String {
    entorno("PRIG_YOUTUBE_SUGERENCIAS", "https://suggestqueries.google.com")
}
fn traductor() -> String {
    entorno("PRIG_TRADUCTOR", "https://translate.googleapis.com")
}

const UA_CHROME: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
const UA_CHROME_120: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
const UA_ANDROID: &str = "com.google.android.youtube/20.10.38";

/// `urllib.parse.quote(t)`: todo salvo letras, cifras, «_.-~» y «/»
pub fn citar(t: &str) -> String {
    let mut o = String::new();
    for b in t.as_bytes() {
        if b.is_ascii_alphanumeric() || b"_.-~/".contains(b) {
            o.push(*b as char);
        } else {
            o.push_str(&format!("%{b:02X}"));
        }
    }
    o
}

/// GET o POST como `red_http.urlopen`: el cuerpo en texto si respondió 2xx (None si no, o sin red)
fn pedir(url: &str, cuerpo: Option<&str>, cab: &[(&str, &str)], segundos: f64) -> Option<(u16, String)> {
    let c = reqwest::blocking::Client::builder().timeout(Duration::from_secs_f64(segundos)).build().ok()?;
    let mut r = match cuerpo {
        Some(b) => c.post(url).body(b.to_string()),
        None => c.get(url),
    };
    for (k, v) in cab {
        r = r.header(*k, *v);
    }
    let resp = r.send().ok()?;
    let estado = resp.status().as_u16();
    if !(200..300).contains(&estado) {
        return None;
    }
    let b = resp.bytes().ok()?;
    Some((estado, String::from_utf8_lossy(&b).into_owned()))
}

/// `decode("utf-8", errors="ignore")`: lo que no es UTF-8 se quita (la cadena ya viene con U+FFFD; se borran)
fn sin_reemplazo(t: String) -> String {
    if t.contains('\u{FFFD}') { t.replace('\u{FFFD}', "") } else { t }
}

// ---------------------------------------------------------------------------------------------- palabras y canales

struct Palabra {
    slug: &'static str,
    palabra: &'static str,
    emoji: &'static str,
    descripcion: &'static str,
    tags: &'static [&'static str],
    color: &'static str,
    queries: &'static [&'static str],
}

const PALABRAS: [Palabra; 4] = [
    Palabra {
        slug: "deep_learning",
        palabra: "Deep Learning",
        emoji: "🧠",
        descripcion: "Redes neuronales, PyTorch, Transformers, LLMs, Visión Artificial y NLP.",
        tags: &["Deep Learning", "PyTorch", "Redes Neuronales", "Transformers", "IA"],
        color: "#8b5cf6",
        queries: &["deep learning curso completo", "deep learning pytorch full course university", "mit deep learning 6.s191", "neural networks 3blue1brown"],
    },
    Palabra {
        slug: "machine_learning",
        palabra: "Machine Learning",
        emoji: "🤖",
        descripcion: "Aprendizaje supervisado y no supervisado, Scikit-Learn, algoritmos y matemáticas.",
        tags: &["Machine Learning", "Scikit-Learn", "Data Science", "Python"],
        color: "#3b82f6",
        queries: &["curso machine learning completo español", "machine learning full course stanford andrew ng", "machine learning python scikit-learn tutorial"],
    },
    Palabra {
        slug: "python",
        palabra: "Python",
        emoji: "🐍",
        descripcion: "Fundamentos, programación orientada a objetos, proyectos, automatización y backend.",
        tags: &["Python", "Programación", "POO", "Backend", "Principiantes"],
        color: "#10b981",
        queries: &["curso python desde cero completo", "python full course for beginners freecodecamp", "python proyectos completos programacion"],
    },
    Palabra {
        slug: "cpp",
        palabra: "C++",
        emoji: "⚡",
        descripcion: "C++ moderno (C++17/C++20), memoria y punteros, STL, algoritmos y sistemas de alto rendimiento.",
        tags: &["C++", "Sistemas", "Estructuras de Datos", "Algoritmos", "Modern C++"],
        color: "#f59e0b",
        queries: &["curso c++ completo desde cero", "c++ programming full course university", "c++ estructuras de datos algoritmos"],
    },
];

fn palabra_mapa(p: &Palabra) -> Mapa {
    let l = |x: &[&str]| Valor::Lista(x.iter().map(|t| Valor::Texto(t.to_string())).collect());
    Mapa::new()
        .con("slug", p.slug)
        .con("palabra", p.palabra)
        .con("emoji", p.emoji)
        .con("descripcion", p.descripcion)
        .con("tags", l(p.tags))
        .con("color", p.color)
        .con("queries_expansion", l(p.queries))
}

/// `obtener_palabras_registradas()`
pub fn palabras_registradas() -> Vec<Valor> {
    PALABRAS.iter().map(|p| Valor::Mapa(palabra_mapa(p))).collect()
}

const CANALES: [(&str, f64); 37] = [
    ("harvard", 50.0), ("david j. malan", 50.0), ("cs50", 50.0), ("mit opencourseware", 50.0), ("mit", 48.0), ("stanford online", 50.0),
    ("stanford university", 50.0), ("stanford", 48.0), ("cmu", 48.0), ("carnegie mellon", 48.0), ("uc berkeley", 48.0), ("berkeley", 45.0),
    ("oxford", 45.0), ("cornell", 45.0), ("freecodecamp", 48.0), ("freecodecamp español", 48.0), ("3blue1brown", 48.0),
    ("statquest with josh starmer", 46.0), ("statquest", 46.0), ("andrej karpathy", 50.0), ("adrian cancino", 42.0), ("mouredev", 42.0),
    ("mouredev by brais moure", 42.0), ("dot csv", 42.0), ("fazt code", 40.0), ("fazt", 38.0), ("midudev", 40.0), ("corey schafer", 42.0),
    ("sentdex", 42.0), ("trevtutor", 42.0), ("neetcode", 40.0), ("computerphile", 42.0), ("programming with mosh", 38.0), ("edureka!", 36.0),
    ("simplilearn", 36.0), ("pildorasinformaticas", 38.0), ("mit", 48.0),
];

const CLAVE_DIDACTICAS: [&str; 15] = [
    "curso completo", "full course", "desde cero", "masterclass", "bootcamp", "universidad", "tutorial completo", "guia completa", "from scratch",
    "lecture", "computer science", "fundamentos", "paso a paso", "estructuras de datos", "algoritmos",
];

// ---------------------------------------------------------------------------------------------- sugerencias

static PARENTESIS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\((.*)\)").unwrap());

/// `obtener_sugerencias_youtube(q, max)`: el autocompletado de YouTube
pub fn sugerencias(q: &str, max: i64) -> Vec<Valor> {
    let c = prig_plataforma::py::strip(q);
    if c.is_empty() {
        return Vec::new();
    }
    let url = format!("{}/complete/search?client=youtube&ds=yt&q={}", sugerencias_url(), citar(c));
    let Some((_, t)) = pedir(&url, None, &[("User-Agent", UA_CHROME), ("Accept-Language", "es-419,es;q=0.9,en;q=0.8")], 3.5) else { return Vec::new() };
    let t = sin_reemplazo(t);
    let Some(m) = PARENTESIS.captures(&t) else { return Vec::new() };
    let Ok(Valor::Lista(d)) = prig_plataforma::json::leer(&m[1]) else { return Vec::new() };
    let Some(Valor::Lista(l)) = d.get(1) else { return Vec::new() };
    let mut v = Vec::new();
    for it in l {
        match it {
            Valor::Lista(x) if !x.is_empty() => v.push(Valor::Texto(x[0].texto_py())),
            Valor::Texto(x) if !x.is_empty() => v.push(Valor::Texto(x.chars().next().unwrap().to_string())),
            Valor::Mapa(_) | Valor::Lista(_) | Valor::Texto(_) | Valor::Nulo => {}
            _ => return Vec::new(),
        }
    }
    let n = if max < 0 { (v.len() as i64 + max).max(0) as usize } else { max as usize };
    v.truncate(n);
    v
}

// ---------------------------------------------------------------------------------------------- extraer resultados

fn g(v: &Valor, k: &str) -> Valor {
    match v {
        Valor::Mapa(m) => m.get(k).cloned().unwrap_or(Valor::Nulo),
        _ => Valor::Nulo,
    }
}

/// `_limpiar_texto(obj)`: el texto de `runs` o `simpleText`
fn limpiar(obj: &Valor) -> String {
    match obj {
        v if !v.verdad() => String::new(),
        Valor::Texto(t) => unescape(prig_plataforma::py::strip(t)),
        Valor::Mapa(m) => {
            if let Some(s) = m.get("simpleText") {
                return unescape(prig_plataforma::py::strip(&s.texto_py()));
            }
            if let Some(Valor::Lista(runs)) = m.get("runs") {
                let partes: String = runs
                    .iter()
                    .filter_map(|r| match r {
                        Valor::Mapa(x) => Some(unescape(&x.get("text").map(|t| t.texto_py()).unwrap_or_default())),
                        _ => None,
                    })
                    .collect();
                return prig_plataforma::py::strip(&partes).to_string();
            }
            String::new()
        }
        _ => String::new(),
    }
}

/// `_parsear_duracion_a_segundos`
fn duracion_s(d: &str) -> i64 {
    let p: Vec<&str> = prig_plataforma::py::strip(d).split(':').collect();
    let n = |x: &str| prig_plataforma::valor::entero_de_texto(x).map(|v| v as i64);
    match p.len() {
        2 => match (n(p[0]), n(p[1])) {
            (Some(a), Some(b)) => a * 60 + b,
            _ => 0,
        },
        3 => match (n(p[0]), n(p[1]), n(p[2])) {
            (Some(a), Some(b), Some(c)) => a * 3600 + b * 60 + c,
            _ => 0,
        },
        _ => 0,
    }
}

static VISTAS: LazyLock<fancy_regex::Regex> = LazyLock::new(|| fancy_regex::Regex::new(r"(\d[\d.,]*)\s*(mil millones|mil|mill\.?|millones|m|k|b)?\b").unwrap());

/// `_parsear_vistas_a_numero`
fn vistas_n(v: &str) -> i64 {
    if v.is_empty() {
        return 0;
    }
    let s = v.to_lowercase().replace('\u{a0}', " ");
    let Ok(Some(m)) = VISTAS.captures(&s) else { return 0 };
    let numero = m.get(1).map(|x| x.as_str()).unwrap_or("");
    let sufijo = m.get(2).map(|x| x.as_str()).unwrap_or("").trim_end_matches('.');
    let mult = match sufijo {
        "k" | "mil" => 1e3,
        "m" | "mill" | "millones" => 1e6,
        "b" | "mil millones" => 1e9,
        _ => 1.0,
    };
    if mult == 1.0 {
        let limpio: String = numero.chars().filter(|c| *c != '.' && *c != ',').collect();
        return limpio.parse().unwrap_or(0);
    }
    prig_plataforma::valor::real_de_texto(&numero.replace(',', ".")).map(|x| (x * mult) as i64).unwrap_or(0)
}

static ANTIGUEDAD: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(\d+)\s+(segundo|second|minuto|minute|hora|hour|día|dia|day|semana|week|mes|month|año|ano|year)").unwrap());

/// `_antiguedad_segundos`
fn antiguedad(p: &str) -> Option<i64> {
    let bajo = p.to_lowercase();
    let c = ANTIGUEDAD.captures(&bajo)?;
    let u = match &c[2] {
        "segundo" | "second" => 1,
        "minuto" | "minute" => 60,
        "hora" | "hour" => 3600,
        "día" | "dia" | "day" => 86400,
        "semana" | "week" => 604800,
        "mes" | "month" => 2592000,
        _ => 31536000,
    };
    c[1].parse::<i64>().ok().map(|n| n * u)
}

const PALABRAS_ES: [&str; 30] = [
    "de", "la", "el", "en", "los", "las", "del", "para", "con", "que", "como", "una", "un", "por", "curso", "desde", "cero", "aprende", "aprender",
    "programación", "programacion", "completo", "español", "principiantes", "introducción", "introduccion", "clase", "qué", "cómo", "redes",
];
const PALABRAS_EN: [&str; 25] = [
    "the", "and", "for", "with", "how", "to", "of", "in", "is", "what", "your", "you", "course", "full", "beginners", "from", "scratch", "learn",
    "learning", "programming", "introduction", "lecture", "guide", "explained", "build",
];
static TOKENS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[a-záéíóúñü]+").unwrap());

/// `_detectar_idioma_heuristico(titulo, descripcion, por_defecto)`
fn idioma(titulo: &str, desc: &str, defecto: &str) -> String {
    let t = format!("{titulo} {desc}").to_lowercase();
    let toks: Vec<&str> = TOKENS.find_iter(&t).map(|m| m.as_str()).collect();
    let es = toks.iter().filter(|x| PALABRAS_ES.contains(x)).count() + 2 * t.chars().filter(|c| "ñ¿¡áéíóú".contains(*c)).count();
    let en = toks.iter().filter(|x| PALABRAS_EN.contains(x)).count();
    if es > en {
        "es".into()
    } else if en > es {
        "en".into()
    } else {
        defecto.into()
    }
}

fn s_txt(m: &Mapa, k: &str) -> String {
    m.get(k).map(|v| v.texto_py()).unwrap_or_default()
}

/// `calcular_score_educativo(item, query, idioma)`
fn score(it: &Mapa, q: &str, idioma_pref: &str) -> f64 {
    let mut s = 50.0;
    let titulo = s_txt(it, "titulo").to_lowercase();
    let canal = s_txt(it, "canal").to_lowercase();
    let ql = q.to_lowercase();
    let toks: Vec<&str> = ql.split_whitespace().filter(|t| t.chars().count() > 2).collect();
    if titulo.contains(&ql) {
        s += 35.0;
    } else {
        s += toks.iter().filter(|t| titulo.contains(**t)).count() as f64 * 12.0;
    }
    s += CANALES.iter().filter(|(c, _)| canal.contains(c)).map(|(_, p)| *p).fold(0.0, f64::max);
    let dur = it.get("duracion_segundos").and_then(|v| v.num()).unwrap_or(0.0);
    if it.verdad("es_playlist") {
        s += 45.0;
    } else if dur < 240.0 {
        s -= 40.0;
    } else if dur < 900.0 {
        s += 10.0;
    } else if dur < 3600.0 {
        s += 25.0;
    } else if dur < 10800.0 {
        s += 45.0;
    } else {
        s += 55.0;
    }
    if CLAVE_DIDACTICAS.iter().any(|p| titulo.contains(p)) {
        s += 25.0;
    }
    let idi = it.get("idioma").map(|v| v.texto_py()).unwrap_or_else(|| "es".into());
    if idioma_pref != "todos" {
        s += if idioma_pref == idi { 20.0 } else { -15.0 };
    }
    s.max(0.0)
}

fn video(vr: &Valor) -> Option<Mapa> {
    let vid = g(vr, "videoId");
    if !vid.verdad() {
        return None;
    }
    let vid = vid.texto_py();
    let titulo = limpiar(&g(vr, "title"));
    let canal = limpiar(&{
        let o = g(vr, "ownerText");
        if o.verdad() { o } else { g(vr, "shortBylineText") }
    });
    let duracion = limpiar(&g(vr, "lengthText"));
    let vistas = limpiar(&g(vr, "viewCountText"));
    let publicado = limpiar(&g(vr, "publishedTimeText"));
    let snippets = g(vr, "detailedMetadataSnippets");
    let desc = if snippets.verdad() {
        match &snippets {
            Valor::Lista(l) => limpiar(&g(&l[0], "snippetText")),
            _ => String::new(),
        }
    } else if g(vr, "descriptionSnippet").verdad() {
        limpiar(&g(vr, "descriptionSnippet"))
    } else {
        String::new()
    };
    let thumbs = match g(&g(vr, "thumbnail"), "thumbnails") {
        Valor::Lista(l) => l,
        _ => Vec::new(),
    };
    let mut miniatura = match thumbs.last() {
        Some(t) => g(t, "url").texto_py(),
        None => format!("https://i.ytimg.com/vi/{vid}/hqdefault.jpg"),
    };
    if miniatura.starts_with("//") {
        miniatura = format!("https:{miniatura}");
    }
    let o = |t: &str, d: &str| if t.is_empty() { d.to_string() } else { t.to_string() };
    Some(
        Mapa::new()
            .con("id", vid.clone())
            .con("tipo", "video")
            .con("titulo", o(&titulo, "Video de YouTube"))
            .con("canal", o(&canal, "Canal YouTube"))
            .con("duracion", o(&duracion, "Video"))
            .con("duracion_segundos", duracion_s(&duracion) as i128)
            .con("vistas", vistas.clone())
            .con("vistas_numero", vistas_n(&vistas) as i128)
            .con("publicado", publicado)
            .con("descripcion", desc.clone())
            .con("miniatura", miniatura)
            .con("url", format!("https://www.youtube.com/watch?v={vid}"))
            .con("es_playlist", false)
            .con("idioma", idioma(&titulo, &desc, "es")),
    )
}

fn playlist(pr: &Valor) -> Option<Mapa> {
    let pid = g(pr, "playlistId");
    if !pid.verdad() {
        return None;
    }
    let pid = pid.texto_py();
    let titulo = limpiar(&g(pr, "title"));
    let canal = limpiar(&{
        let o = g(pr, "shortBylineText");
        if o.verdad() { o } else { g(pr, "ownerText") }
    });
    let mut conteo = limpiar(&g(pr, "videoCount"));
    if conteo.is_empty() && matches!(pr, Valor::Mapa(m) if m.contiene("videoCountText")) {
        conteo = limpiar(&g(pr, "videoCountText"));
    }
    let thumbs = if g(pr, "thumbnails").verdad() {
        match g(pr, "thumbnails") {
            Valor::Lista(l) => match g(&l[0], "thumbnails") {
                Valor::Lista(x) => x,
                _ => Vec::new(),
            },
            _ => Vec::new(),
        }
    } else {
        Vec::new()
    };
    let mut miniatura = thumbs.last().map(|t| g(t, "url").texto_py()).unwrap_or_default();
    if miniatura.starts_with("//") {
        miniatura = format!("https:{miniatura}");
    }
    let nav = g(&g(pr, "navigationEndpoint"), "watchEndpoint");
    let primer = match &nav {
        Valor::Mapa(m) if !m.is_empty() && m.contiene("videoId") => m.valor("videoId").texto_py(),
        _ => String::new(),
    };
    let desc = if conteo.is_empty() { format!("Lista de reproducción sobre {titulo}") } else { format!("Lista de reproducción con {conteo} sobre {titulo}") };
    Some(fila_playlist(&pid, &titulo, &canal, &conteo, &desc, miniatura, &primer))
}

fn fila_playlist(pid: &str, titulo: &str, canal: &str, conteo: &str, desc: &str, miniatura: String, primer: &str) -> Mapa {
    let o = |t: &str, d: &str| if t.is_empty() { d.to_string() } else { t.to_string() };
    let mini = if !miniatura.is_empty() {
        miniatura
    } else if !primer.is_empty() {
        format!("https://i.ytimg.com/vi/{primer}/hqdefault.jpg")
    } else {
        String::new()
    };
    Mapa::new()
        .con("id", pid)
        .con("tipo", "playlist")
        .con("titulo", o(titulo, "Lista de reproducción"))
        .con("canal", o(canal, "Canal YouTube"))
        .con("duracion", o(conteo, "Playlist"))
        .con("duracion_segundos", 0)
        .con("vistas", "")
        .con("vistas_numero", 0)
        .con("publicado", "")
        .con("descripcion", desc)
        .con("miniatura", mini)
        .con("url", format!("https://www.youtube.com/playlist?list={pid}"))
        .con("es_playlist", true)
        .con("video_inicial_id", primer)
        .con("conteo_videos", conteo)
        .con("idioma", idioma(titulo, "", "es"))
}

/// `_textos_de(nodo, clave)`: los valores de `clave` (texto u objeto) bajo `nodo`, en orden de aparición
fn textos_de(nodo: &Valor, clave: &str) -> Vec<Valor> {
    let mut salida = Vec::new();
    let mut pila: std::collections::VecDeque<Valor> = std::collections::VecDeque::from([nodo.clone()]);
    while let Some(n) = pila.pop_front() {
        match n {
            Valor::Mapa(m) => {
                for (k, v) in m.iter() {
                    if k == clave && matches!(v, Valor::Texto(_) | Valor::Mapa(_)) {
                        salida.push(v.clone());
                    } else {
                        pila.push_back(v.clone());
                    }
                }
            }
            Valor::Lista(l) => {
                for x in l.into_iter().rev() {
                    pila.push_front(x);
                }
            }
            _ => {}
        }
    }
    salida
}

static VI: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"/vi/([\w-]{11})/").unwrap());

/// `_item_de_lockup(lk)`: las listas en el formato nuevo (lockupViewModel)
fn lockup(lk: &Valor) -> Option<Mapa> {
    let o = |v: Valor| if v.verdad() { v.texto_py() } else { String::new() };
    let cid = o(g(lk, "contentId"));
    let tipo = o(g(lk, "contentType"));
    if cid.is_empty() || cid.chars().count() == 11 || (!tipo.is_empty() && !tipo.contains("PLAYLIST") && !tipo.contains("PODCAST")) {
        return None;
    }
    let meta = g(&g(lk, "metadata"), "lockupMetadataViewModel");
    let titulo = unescape(prig_plataforma::py::strip(&o(g(&g(&meta, "title"), "content"))));
    let filas = match g(&g(&g(&meta, "metadata"), "contentMetadataViewModel"), "metadataRows") {
        Valor::Lista(l) => l,
        _ => Vec::new(),
    };
    let mut canal = String::new();
    'filas: for f in &filas {
        if let Valor::Lista(partes) = g(f, "metadataParts") {
            for p in partes {
                canal = prig_plataforma::py::strip(&o(g(&g(&p, "text"), "content"))).to_string();
                if !canal.is_empty() {
                    break 'filas;
                }
            }
        }
    }
    let imagen = g(lk, "contentImage");
    let fuentes: Vec<String> = textos_de(&imagen, "url").into_iter().filter_map(|f| if let Valor::Texto(t) = f { Some(t) } else { None }).filter(|t| t.starts_with("http") || t.starts_with("//")).collect();
    let mut miniatura = fuentes.last().cloned().unwrap_or_default();
    if miniatura.starts_with("//") {
        miniatura = format!("https:{miniatura}");
    }
    let conteo = textos_de(&imagen, "thumbnailBadgeViewModel").into_iter().find_map(|t| match &t {
        Valor::Mapa(m) if m.verdad("text") => Some(m.valor("text").texto_py()),
        _ => None,
    }).unwrap_or_default();
    let base = if g(lk, "itemPlayback").verdad() { g(lk, "itemPlayback") } else { lk.clone() };
    let mut primer = textos_de(&base, "watchEndpoint").into_iter().find_map(|w| match &w {
        Valor::Mapa(m) if m.verdad("videoId") => Some(m.valor("videoId").texto_py()),
        _ => None,
    }).unwrap_or_default();
    if primer.is_empty() {
        primer = VI.captures(&miniatura).map(|c| c[1].to_string()).unwrap_or_default();
    }
    let desc = if conteo.is_empty() { format!("Lista de reproducción sobre {titulo}") } else { format!("Lista de reproducción con {conteo} sobre {titulo}") };
    Some(fila_playlist(&cid, &titulo, &canal, &conteo, &desc, miniatura, &primer))
}

/// `_extraer_items_de_yt_data(data)`
fn extraer_items(data: &Valor) -> Vec<Mapa> {
    let mut items = Vec::new();
    fn recorrer(n: &Valor, items: &mut Vec<Mapa>) {
        match n {
            Valor::Mapa(m) => {
                if let Some(vr) = m.get("videoRenderer") {
                    if let Some(x) = video(vr) {
                        items.push(x);
                    }
                } else if let Some(pr) = m.get("playlistRenderer") {
                    if let Some(x) = playlist(pr) {
                        items.push(x);
                    }
                } else if let Some(lk) = m.get("lockupViewModel") {
                    if let Some(x) = lockup(lk) {
                        items.push(x);
                    }
                } else {
                    for (_, v) in m.iter() {
                        recorrer(v, items);
                    }
                }
            }
            Valor::Lista(l) => {
                for x in l {
                    recorrer(x, items);
                }
            }
            _ => {}
        }
    }
    recorrer(data, &mut items);
    items
}

// ---------------------------------------------------------------------------------------------- buscar

/// `_params_busqueda(tipo, duracion)`: el filtro nativo de YouTube (protobuf en base64)
fn params_busqueda(tipo: &str, dur: &str) -> String {
    use base64::Engine;
    let mut campos: Vec<u8> = Vec::new();
    if dur == "playlists" || tipo == "playlist" {
        campos.extend([0x10, 0x03]);
    } else if tipo == "video" || ["cortos", "clases", "cursos"].contains(&dur) {
        campos.extend([0x10, 0x01]);
        if dur == "clases" || dur == "cursos" {
            campos.extend([0x18, 0x02]);
        }
    }
    if campos.is_empty() {
        return String::new();
    }
    let mut b = vec![0x12, campos.len() as u8];
    b.extend(campos);
    base64::engine::general_purpose::STANDARD.encode(b)
}

fn idioma_cliente(i: &str) -> (&'static str, &'static str, &'static str) {
    if i == "en" { ("en", "US", "en-US,en;q=0.9") } else { ("es-419", "US", "es-419,es;q=0.9,en;q=0.8") }
}

fn innertube(q: &str, params: &str, idi: &str) -> Option<Vec<Mapa>> {
    let (hl, gl, aceptar) = idioma_cliente(idi);
    let mut cliente = Mapa::new().con("clientName", "WEB").con("clientVersion", "2.20240401.00.00").con("hl", hl).con("gl", gl);
    let _ = &mut cliente;
    let mut cuerpo = Mapa::new().con("context", Mapa::new().con("client", cliente)).con("query", q);
    if !params.is_empty() {
        cuerpo.poner("params", params);
    }
    let (estado, t) = pedir(
        &format!("{}/youtubei/v1/search", youtube()),
        Some(&prig_plataforma::json::escribir_compacto(&Valor::Mapa(cuerpo))),
        &[("Content-Type", "application/json"), ("User-Agent", UA_CHROME), ("Accept-Language", aceptar)],
        6.5,
    )?;
    if estado != 200 {
        return None;
    }
    prig_plataforma::json::leer(&t).ok().map(|v| extraer_items(&v))
}

static INITIAL_DATA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"ytInitialData\s*=\s*(\{.+?\});").unwrap());

fn scraper(q: &str, params: &str, idi: &str) -> Option<Vec<Mapa>> {
    let (hl, _, aceptar) = idioma_cliente(idi);
    let mut url = format!("{}/results?search_query={}&hl={hl}", youtube(), citar(q));
    if !params.is_empty() {
        url += &format!("&sp={}", citar(params));
    }
    let (_, t) = pedir(&url, None, &[("User-Agent", UA_CHROME), ("Accept-Language", aceptar), ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")], 7.5)?;
    let t = sin_reemplazo(t);
    match INITIAL_DATA.captures(&t) {
        Some(c) => prig_plataforma::json::leer(&c[1]).ok().map(|v| extraer_items(&v)),
        None => None,
    }
}

static CACHE: LazyLock<Mutex<Vec<(String, f64, Vec<Mapa>)>>> = LazyLock::new(|| Mutex::new(Vec::new()));
const CACHE_TTL: f64 = 7200.0;

fn ahora() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

/// Los filtros de `buscar_cursos_youtube`
pub struct Busqueda {
    pub q: String,
    pub tipo: String,
    pub max: i64,
    pub educativo: bool,
    pub idioma: String,
    pub duracion: String,
    pub orden: String,
    pub forzar: bool,
}

fn palabra(slug: &Option<&Palabra>) -> Valor {
    slug.map(|p| Valor::Mapa(palabra_mapa(p))).unwrap_or(Valor::Nulo)
}

fn rebanar<T: Clone>(v: &[T], n: i64) -> Vec<T> {
    let n = if n < 0 { (v.len() as i64 + n).max(0) as usize } else { (n as usize).min(v.len()) };
    v[..n].to_vec()
}

/// `buscar_cursos_youtube(...)`
pub fn buscar(b: &Busqueda, carpeta_cache: &Path) -> Mapa {
    let q = prig_plataforma::py::strip(&b.q).to_string();
    if q.is_empty() {
        return Mapa::new().con("query", "").con("total", 0).con("resultados", Valor::Lista(vec![])).con("palabra_registrada", Valor::Nulo);
    }
    let ql = q.to_lowercase();
    let registrada = PALABRAS.iter().find(|p| ql == p.palabra.to_lowercase() || ql == p.slug);
    let bool_py = |x: bool| if x { "True" } else { "False" };
    let clave = format!("{ql}::tipo={}::max={}::edu={}::idm={}::dur={}::ord={}", b.tipo, b.max, bool_py(b.educativo), b.idioma, b.duracion, b.orden);
    let t = ahora();
    if !b.forzar {
        if let Some((_, ts, items)) = CACHE.lock().unwrap().iter().find(|x| x.0 == clave) {
            if t - ts < CACHE_TTL {
                return Mapa::new()
                    .con("query", q.clone())
                    .con("total", items.len() as i128)
                    .con("resultados", Valor::Lista(items.iter().cloned().map(Valor::Mapa).collect()))
                    .con("desde_cache", true)
                    .con("palabra_registrada", palabra(&registrada));
            }
        }
    }
    let consulta_yt = match registrada {
        Some(p) if b.educativo => format!("{} curso completo tutorial", p.palabra),
        _ => q.clone(),
    };
    let params = params_busqueda(&b.tipo, &b.duracion);
    let mut crudos = innertube(&consulta_yt, &params, &b.idioma);
    let mut motor = "innertube";
    if crudos.as_ref().is_none_or(|c| c.is_empty()) {
        let respaldo = scraper(&consulta_yt, &params, &b.idioma);
        if respaldo.is_some() || crudos.is_none() {
            crudos = respaldo;
            motor = "html_scraper";
        }
    }
    let Some(crudos) = crudos else {
        if let Some((_, _, items)) = CACHE.lock().unwrap().iter().find(|x| x.0 == clave) {
            return Mapa::new()
                .con("query", q.clone())
                .con("total", items.len() as i128)
                .con("resultados", Valor::Lista(items.iter().cloned().map(Valor::Mapa).collect()))
                .con("desde_cache", true)
                .con("degradado", true)
                .con("palabra_registrada", palabra(&registrada));
        }
        return Mapa::new()
            .con("query", q)
            .con("total", 0)
            .con("resultados", Valor::Lista(vec![]))
            .con("error", "No se pudo conectar con YouTube.")
            .con("palabra_registrada", Valor::Nulo);
    };
    if crudos.is_empty() {
        return Mapa::new()
            .con("query", q)
            .con("total", 0)
            .con("resultados", Valor::Lista(vec![]))
            .con("desde_cache", false)
            .con("motor", motor)
            .con("aviso", "YouTube no devolvió resultados para esta búsqueda.")
            .con("palabra_registrada", palabra(&registrada));
    }
    let filtrados: Vec<Mapa> = match b.tipo.as_str() {
        "video" => crudos.into_iter().filter(|i| !i.verdad("es_playlist")).collect(),
        "playlist" => crudos.into_iter().filter(|i| i.verdad("es_playlist")).collect(),
        _ => crudos,
    };
    let mut vistos = Vec::new();
    let mut unicos = Vec::new();
    for it in filtrados {
        let id = it.get("id").cloned().unwrap_or(Valor::Nulo);
        if id.verdad() && !vistos.contains(&id) {
            vistos.push(id);
            unicos.push(it);
        }
    }
    let mut candidatos = Vec::new();
    for it in &unicos {
        let mut it = it.clone();
        if b.idioma != "todos" {
            if idioma(&s_txt(&it, "titulo"), &s_txt(&it, "descripcion"), &b.idioma) != b.idioma {
                continue;
            }
            it.poner("idioma", b.idioma.clone());
        }
        let dur = it.get("duracion_segundos").and_then(|v| v.num()).unwrap_or(0.0);
        let pl = it.verdad("es_playlist");
        let fuera = match b.duracion.as_str() {
            "cortos" => dur > 1800.0 || pl,
            "clases" => dur < 1800.0 || dur > 7200.0 || pl,
            "cursos" => dur < 7200.0 || pl,
            "playlists" => !pl,
            _ => false,
        };
        if !fuera {
            candidatos.push(it);
        }
    }
    let aviso = if candidatos.is_empty() && !unicos.is_empty() {
        Valor::Texto("Ningún resultado de YouTube cumple los filtros elegidos. Prueba con menos filtros u otra búsqueda.".into())
    } else {
        Valor::Nulo
    };
    for it in &mut candidatos {
        let s = score(it, &q, &b.idioma);
        it.poner("score_educativo", Valor::Real(s));
        let canal = s_txt(it, "canal").to_lowercase();
        it.poner("es_canal_verificado", CANALES.iter().any(|(c, _)| canal.contains(c)));
    }
    let num = |m: &Mapa, k: &str| m.get(k).and_then(|v| v.num()).unwrap_or(0.0);
    let desc = |a: f64, b: f64| b.partial_cmp(&a).unwrap_or(std::cmp::Ordering::Equal);
    match b.orden.as_str() {
        "duracion" => candidatos.sort_by(|x, y| desc(num(x, "duracion_segundos"), num(y, "duracion_segundos"))),
        "vistas" => candidatos.sort_by(|x, y| desc(num(x, "vistas_numero"), num(y, "vistas_numero"))),
        "recientes" => candidatos.sort_by_key(|x| {
            let a = antiguedad(&s_txt(x, "publicado"));
            (a.is_none(), a.unwrap_or(0))
        }),
        _ => candidatos.sort_by(|x, y| {
            desc(num(x, "score_educativo"), num(y, "score_educativo")).then(desc(num(x, "duracion_segundos"), num(y, "duracion_segundos")))
        }),
    }
    let finales = rebanar(&candidatos, b.max);
    if !finales.is_empty() {
        let mut c = CACHE.lock().unwrap();
        c.retain(|x| x.0 != clave);
        c.push((clave, t, finales.clone()));
    }
    guardar_cache(carpeta_cache);
    Mapa::new()
        .con("query", q)
        .con("total", finales.len() as i128)
        .con("resultados", Valor::Lista(finales.into_iter().map(Valor::Mapa).collect()))
        .con("desde_cache", false)
        .con("motor", motor)
        .con("aviso", aviso)
        .con("palabra_registrada", palabra(&registrada))
}

/// `_guardar_cache_disco`: las últimas 250 búsquedas vigentes (`backend/data/youtube_cache.json`)
fn guardar_cache(carpeta: &Path) {
    let t = ahora();
    let mut doc = Mapa::new();
    {
        let c = CACHE.lock().unwrap();
        let ini = c.len().saturating_sub(250);
        for (k, ts, items) in &c[ini..] {
            if t - ts < CACHE_TTL {
                doc.poner(k.clone(), Mapa::new().con("ts", Valor::Real(*ts)).con("items", Valor::Lista(items.iter().cloned().map(Valor::Mapa).collect())));
            }
        }
    }
    let ruta = carpeta.join("youtube_cache.json");
    let _ = std::fs::create_dir_all(carpeta);
    let tmp = PathBuf::from(format!("{}.tmp", ruta.display()));
    if std::fs::write(&tmp, prig_plataforma::json::escribir(&Valor::Mapa(doc), 1)).is_ok() {
        let _ = std::fs::rename(&tmp, &ruta);
    }
}

/// Al arrancar: la caché de búsquedas del disco (lo vigente)
pub fn cargar_cache(carpeta: &Path) {
    let Some(Valor::Mapa(d)) = std::fs::read_to_string(carpeta.join("youtube_cache.json")).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) else { return };
    let t = ahora();
    let mut c = CACHE.lock().unwrap();
    for (k, v) in d.iter() {
        let ts = g(v, "ts").num().unwrap_or(0.0);
        if t - ts < CACHE_TTL {
            let items = match g(v, "items") {
                Valor::Lista(l) => l.into_iter().filter_map(|x| if let Valor::Mapa(m) = x { Some(m) } else { None }).collect(),
                _ => Vec::new(),
            };
            c.push((k.clone(), ts, items));
        }
    }
}

// ---------------------------------------------------------------------------------------------- abrir en el navegador

/// `_lanzar_navegador_sistema(url)`: el navegador del sistema, en un proceso suelto
pub fn abrir_en_navegador(url: &str) -> bool {
    let mut candidatos: Vec<String> = std::env::var("BROWSER").ok().map(|b| b.split(':').map(String::from).collect()).unwrap_or_default();
    candidatos.extend(
        ["google-chrome", "google-chrome-stable", "/opt/google/chrome/google-chrome", "chromium", "chromium-browser", "firefox", "sensible-browser", "x-www-browser", "gnome-www-browser", "xdg-open"]
            .iter()
            .map(|s| s.to_string()),
    );
    let en_path = |c: &str| -> Option<PathBuf> {
        if c.contains('/') {
            let p = PathBuf::from(c);
            return p.is_file().then_some(p);
        }
        std::env::var_os("PATH").and_then(|p| std::env::split_paths(&p).map(|d| d.join(c)).find(|x| x.is_file()))
    };
    for c in candidatos {
        let c = c.trim();
        if c.is_empty() {
            continue;
        }
        let Some(ruta) = en_path(c) else { continue };
        if ruta.file_name().is_some_and(|n| n.to_string_lossy().to_lowercase().contains("firefox")) {
            // el Firefox de snap sin instalar responde con instrucciones: no sirve
            let Ok(o) = std::process::Command::new(&ruta).arg("--version").output() else { continue };
            let todo = format!("{}{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr));
            if todo.contains("snap install firefox") {
                continue;
            }
        }
        use std::os::unix::process::CommandExt;
        let mut cmd = std::process::Command::new(&ruta);
        cmd.arg(url).stdin(std::process::Stdio::null()).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null());
        // SAFETY: setsid en el hijo antes de exec (como start_new_session)
        unsafe {
            cmd.pre_exec(|| {
                libc::setsid();
                Ok(())
            });
        }
        return cmd.spawn().is_ok();
    }
    false
}

// ---------------------------------------------------------------------------------------------- transcripción

const API_KEY: &str = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8";
const VERSION: i64 = 2;

/// `formatear_segundos_hms`
pub fn hms(s: f64) -> String {
    let t = s.max(0.0) as i64;
    let (m, s) = (t / 60, t % 60);
    let (h, m) = (m / 60, m % 60);
    if h > 0 { format!("{h}:{m:02}:{s:02}") } else { format!("{m:02}:{s:02}") }
}

/// `_extraer_nombre_track(c)`
fn nombre_track(c: &Valor) -> String {
    match g(c, "name") {
        Valor::Mapa(n) => {
            if n.verdad("simpleText") {
                return n.valor("simpleText").texto_py();
            }
            if let Some(Valor::Lista(r)) = n.get("runs") {
                if let Some(Valor::Mapa(x)) = r.first() {
                    return x.get("text").map(|t| t.texto_py()).unwrap_or_default();
                }
            }
            match g(c, "languageCode") {
                Valor::Nulo => "Desconocido".into(),
                v => v.texto_py(),
            }
        }
        Valor::Texto(t) => t,
        v if !v.verdad() => match g(c, "languageCode") {
            Valor::Nulo => "Desconocido".into(),
            v => v.texto_py(),
        },
        _ => match g(c, "languageCode") {
            Valor::Nulo => "Desconocido".into(),
            v => v.texto_py(),
        },
    }
}

/// `data.get("captions", {}).get(...).get("captionTracks", [])`
fn pistas_de(d: &Valor) -> Option<Vec<Valor>> {
    let c = match d {
        Valor::Mapa(m) => m.get("captions").cloned().unwrap_or(Valor::Mapa(Mapa::new())),
        _ => return None,
    };
    let r = match c {
        Valor::Mapa(m) => m.get("playerCaptionsTracklistRenderer").cloned().unwrap_or(Valor::Mapa(Mapa::new())),
        _ => return None,
    };
    match r {
        Valor::Mapa(m) => match m.get("captionTracks").cloned().unwrap_or(Valor::Lista(vec![])) {
            Valor::Lista(l) => Some(l),
            v if !v.verdad() => Some(Vec::new()),
            _ => None,
        },
        _ => None,
    }
}

fn cuerpo_android(video: &str) -> String {
    let c = Mapa::new().con("clientName", "ANDROID").con("clientVersion", "20.10.38").con("hl", "es").con("gl", "ES");
    prig_plataforma::json::escribir_compacto(&Valor::Mapa(Mapa::new().con("context", Mapa::new().con("client", c)).con("videoId", video)))
}

static CLAVE_API: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#""INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)""#).unwrap());
static PLAYER: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"ytInitialPlayerResponse\s*=\s*(\{.+?\});").unwrap());

/// `_obtener_caption_tracks(video_id)`: cliente Android de InnerTube; si no, la página; si no, el cliente web
fn pistas(video: &str) -> Vec<Valor> {
    let base = youtube();
    let android = |clave: &str| -> Option<Vec<Valor>> {
        let (_, t) = pedir(&format!("{base}/youtubei/v1/player?key={clave}"), Some(&cuerpo_android(video)), &[("Content-Type", "application/json"), ("User-Agent", UA_ANDROID)], 5.0)?;
        pistas_de(&prig_plataforma::json::leer(&sin_reemplazo(t)).ok()?)
    };
    if let Some(p) = android(API_KEY).filter(|p| !p.is_empty()) {
        return p;
    }
    if let Some((_, html)) = pedir(&format!("{base}/watch?v={video}"), None, &[("User-Agent", UA_CHROME_120), ("Accept-Language", "es,en;q=0.9")], 5.0) {
        let html = sin_reemplazo(html);
        let clave = CLAVE_API.captures(&html).map(|c| c[1].to_string()).unwrap_or_default();
        let mut fallo = false;
        if !clave.is_empty() && clave != API_KEY {
            match android(&clave) {
                Some(p) if !p.is_empty() => return p,
                Some(_) => {}
                None => fallo = true,
            }
        }
        if !fallo {
            if let Some(c) = PLAYER.captures(&html) {
                if let Some(p) = prig_plataforma::json::leer(&c[1]).ok().and_then(|d| pistas_de(&d)).filter(|p| !p.is_empty()) {
                    return p;
                }
            }
        }
    }
    let c = Mapa::new().con("hl", "es").con("gl", "ES").con("clientName", "WEB").con("clientVersion", "2.20240101.01.00");
    let cuerpo = prig_plataforma::json::escribir_compacto(&Valor::Mapa(Mapa::new().con("context", Mapa::new().con("client", c)).con("videoId", video)));
    if let Some((_, t)) = pedir(&format!("{base}/youtubei/v1/player"), Some(&cuerpo), &[("Content-Type", "application/json"), ("User-Agent", UA_CHROME_120)], 5.0) {
        if let Some(p) = prig_plataforma::json::leer(&sin_reemplazo(t)).ok().and_then(|d| pistas_de(&d)).filter(|p| !p.is_empty()) {
            return p;
        }
    }
    Vec::new()
}

/// `_descargar_xml_timedtext(url)`
fn xml(url: &str) -> String {
    if url.is_empty() {
        return String::new();
    }
    for ua in [UA_ANDROID, UA_CHROME_120] {
        if let Some((_, t)) = pedir(url, None, &[("User-Agent", ua), ("Accept-Language", "es,en;q=0.9")], 5.0) {
            return sin_reemplazo(t);
        }
    }
    String::new()
}

static FORMATO1: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#"(?s)<text start="([\d\.]+)"(?:\s+dur="([\d\.]+)")?[^>]*>(.*?)</text>"#).unwrap());
static FORMATO3: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#"(?s)<p t="(\d+)"(?:\s+d="(\d+)")?[^>]*>(.*?)</p>"#).unwrap());
static ETIQUETA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").unwrap());

#[derive(Clone)]
struct Entrada {
    start: f64,
    dur: f64,
    end: f64,
    texto: String,
}

/// `_parsear_fragmentos_subtitulos(xml)`: formato 1 (`<text>`) o 3 (`<p>`), sin solapes
fn fragmentos(x: &str) -> Vec<Entrada> {
    let limpio = |t: &str| prig_plataforma::py::strip(&unescape(&ETIQUETA.replace_all(t, "")).replace('\n', " ")).to_string();
    let mut e = Vec::new();
    for c in FORMATO1.captures_iter(x) {
        let Some(start) = prig_plataforma::valor::real_de_texto(&c[1]) else { continue };
        let dur = match c.get(2) {
            Some(d) if !d.as_str().is_empty() => match prig_plataforma::valor::real_de_texto(d.as_str()) {
                Some(v) => v,
                None => continue,
            },
            _ => 3.0,
        };
        let t = limpio(&c[3]);
        if !t.is_empty() {
            e.push(Entrada { start: redondear(start, 2), dur: redondear(dur, 2), end: redondear(start + dur, 2), texto: t });
        }
    }
    if e.is_empty() {
        for c in FORMATO3.captures_iter(x) {
            let Ok(t0) = c[1].parse::<i64>() else { continue };
            let start = redondear(t0 as f64 / 1000.0, 2);
            let dur = match c.get(2) {
                Some(d) if !d.as_str().is_empty() => match d.as_str().parse::<i64>() {
                    Ok(v) => redondear(v as f64 / 1000.0, 2),
                    Err(_) => continue,
                },
                _ => 3.0,
            };
            let t = limpio(&c[3]);
            if !t.is_empty() {
                e.push(Entrada { start, dur, end: redondear(start + dur, 2), texto: t });
            }
        }
    }
    e.sort_by(|a, b| a.start.partial_cmp(&b.start).unwrap_or(std::cmp::Ordering::Equal));
    for i in 0..e.len().saturating_sub(1) {
        let sig = e[i + 1].start;
        if e[i].end > sig {
            e[i].end = e[i].start.max(sig);
            e[i].dur = redondear(e[i].end - e[i].start, 2);
        }
    }
    e
}

/// Una petición al traductor: el texto traducido (None si falla)
fn traducir(texto: &str, destino: &str, segundos: f64) -> Option<String> {
    let url = format!("{}/translate_a/single?client=gtx&sl=auto&tl={destino}&dt=t&q={}", traductor(), citar(texto));
    let (_, t) = pedir(&url, None, &[("User-Agent", "Mozilla/5.0")], segundos)?;
    let Valor::Lista(d) = prig_plataforma::json::leer(&sin_reemplazo(t)).ok()? else { return None };
    let Some(Valor::Lista(partes)) = d.first() else { return None };
    let mut s = String::new();
    for it in partes {
        match it {
            Valor::Lista(x) if !x.is_empty() => {
                if x[0].verdad() {
                    s += &x[0].texto_py();
                }
            }
            v if !v.verdad() => {}
            _ => return None,
        }
    }
    Some(s)
}

/// `_traducir_lote_parrafos(textos, destino)`: en bloques de ~2 200 caracteres con un separador, en paralelo
fn traducir_lote(textos: &[String], destino: &str) -> Vec<String> {
    const SEP: &str = " \n|||\n ";
    let mut bloques: Vec<Vec<String>> = Vec::new();
    let mut actual: Vec<String> = Vec::new();
    let mut largo = 0usize;
    for t in textos {
        let t = prig_plataforma::py::strip(t).to_string();
        if t.is_empty() {
            actual.push(String::new());
            continue;
        }
        let n = t.chars().count();
        if largo + n > 2200 && !actual.is_empty() {
            bloques.push(std::mem::take(&mut actual));
            actual.push(t);
            largo = n;
        } else {
            actual.push(t);
            largo += n + SEP.chars().count();
        }
    }
    if !actual.is_empty() {
        bloques.push(actual);
    }
    let un_bloque = |items: Vec<String>| -> Vec<String> {
        let validos: Vec<&String> = items.iter().filter(|x| !x.is_empty()).collect();
        if validos.is_empty() {
            return items;
        }
        let unido = validos.iter().map(|x| x.as_str()).collect::<Vec<_>>().join(SEP);
        let Some(res) = traducir(&unido, destino, 6.0) else { return items };
        let partes: Vec<&str> = res.split("|||").collect();
        if partes.len() == validos.len() {
            let mut i = 0;
            return items
                .iter()
                .map(|o| {
                    if o.is_empty() {
                        String::new()
                    } else {
                        let p = prig_plataforma::py::strip(partes[i]).to_string();
                        i += 1;
                        p
                    }
                })
                .collect();
        }
        if partes.len() > 1 {
            let mut i = 0;
            return items
                .iter()
                .map(|o| {
                    if !o.is_empty() && i < partes.len() {
                        let p = prig_plataforma::py::strip(partes[i]).to_string();
                        i += 1;
                        p
                    } else {
                        o.clone()
                    }
                })
                .collect();
        }
        items
    };
    let resultados: Vec<String> = std::thread::scope(|sc| {
        let hilos: Vec<_> = bloques.into_iter().map(|b| sc.spawn(|| un_bloque(b))).collect();
        hilos.into_iter().flat_map(|h| h.join().unwrap_or_default()).collect()
    });
    if resultados.len() == textos.len() { resultados } else { textos.to_vec() }
}

fn carpeta_transcripciones(raiz: &Path) -> PathBuf {
    std::env::var("PRIG_CACHE_TRANSCRIPCIONES").ok().filter(|v| !v.is_empty()).map(PathBuf::from).unwrap_or_else(|| raiz.join("data/cache_transcripciones"))
}

fn error_t(e: &str) -> Mapa {
    Mapa::new().con("ok", false).con("error", e).con("segmentos", Valor::Lista(vec![]))
}

/// `extraer_transcripcion_estructurada(video_id, idioma_destino, forzar)`: párrafos con sus tiempos (y traducidos al
/// español si hace falta), con caché en disco
pub fn transcripcion(raiz: &Path, video: &str, destino: &str, forzar: bool) -> Mapa {
    if video.is_empty() {
        return error_t("ID de video vacío");
    }
    let dir = carpeta_transcripciones(raiz);
    let _ = std::fs::create_dir_all(&dir);
    let cache = dir.join(format!("{video}_{destino}.json"));
    if !forzar && cache.exists() {
        if let Some(Valor::Mapa(d)) = std::fs::read_to_string(&cache).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) {
            if d.verdad("ok") && d.verdad("segmentos") && d.get("version") == Some(&Valor::Entero(VERSION as i128)) {
                return d;
            }
        }
    }
    let captions = pistas(video);
    if captions.is_empty() {
        return Mapa::new()
            .con("ok", false)
            .con("error", "Este video no tiene subtítulos disponibles en YouTube.")
            .con("segmentos", Valor::Lista(vec![]))
            .con("idiomas_disponibles", Valor::Lista(vec![]));
    }
    let disponibles: Vec<Valor> = captions
        .iter()
        .map(|c| {
            Valor::Mapa(
                Mapa::new()
                    .con("codigo", g(c, "languageCode"))
                    .con("nombre", nombre_track(c))
                    .con("es_traducible", match c {
                        Valor::Mapa(m) => m.get("isTranslatable").cloned().unwrap_or(Valor::Bool(true)),
                        _ => Valor::Bool(true),
                    }),
            )
        })
        .collect();
    let codigo = |c: &Valor| {
        let v = g(c, "languageCode");
        if v.verdad() { v.texto_py() } else { String::new() }
    };
    let track_es = captions.iter().find(|c| codigo(c).starts_with("es"));
    let track_orig = captions.iter().find(|c| codigo(c).starts_with("en")).unwrap_or(&captions[0]);
    let lang_o = |c: &Valor, d: &str| match g(c, "languageCode") {
        Valor::Nulo => d.to_string(),
        v => v.texto_py(),
    };
    let url_de = |c: &Valor| match g(c, "baseUrl") {
        Valor::Nulo => String::new(),
        v => v.texto_py(),
    };
    let es_es = ["es", "es-419", "es-ES"].contains(&destino);
    let mut idioma_origen = lang_o(track_orig, "en");
    let nombre_origen = nombre_track(track_orig);
    let (xml_origen, mut xml_traducido, mut usado, mut nombre);
    if es_es {
        if let Some(te) = track_es {
            xml_traducido = xml(&url_de(te));
            xml_origen = xml_traducido.clone();
            usado = "es".to_string();
            let n = nombre_track(te);
            nombre = if n == "Español" {
                "Español (oficial de YouTube)".to_string()
            } else if n.to_lowercase().starts_with("español") {
                n
            } else {
                format!("Español ({n})")
            };
            idioma_origen = lang_o(te, "es");
        } else {
            xml_origen = xml(&url_de(track_orig));
            xml_traducido = xml_origen.clone();
            usado = idioma_origen.clone();
            nombre = format!("{nombre_origen} (disponible en YouTube)");
        }
    } else {
        let sel = captions.iter().find(|c| g(c, "languageCode") == Valor::Texto(destino.into())).unwrap_or(&captions[0]);
        xml_traducido = xml(&url_de(sel));
        xml_origen = xml_traducido.clone();
        usado = lang_o(sel, destino);
        nombre = nombre_track(sel);
    }
    let _ = idioma_origen;
    if xml_traducido.is_empty() && !xml_origen.is_empty() {
        xml_traducido = xml_origen.clone();
    }
    let orig = fragmentos(&xml_origen);
    let trad = fragmentos(&xml_traducido);
    let base = if !trad.is_empty() { trad.clone() } else { orig.clone() };
    if base.is_empty() {
        return error_t("No se pudieron decodificar subtítulos para este video.");
    }
    let misma = xml_origen == xml_traducido;
    let inicios: Vec<f64> = orig.iter().map(|e| e.start).collect();
    struct Trozo {
        start: f64,
        end: f64,
        trad: Vec<String>,
        orig: Vec<String>,
    }
    let mut segmentos: Vec<Mapa> = Vec::new();
    let cerrar = |t: &Trozo, segmentos: &mut Vec<Mapa>| {
        let (s, e) = (hms(t.start), hms(t.end));
        segmentos.push(
            Mapa::new()
                .con("id", format!("seg_{}", segmentos.len()))
                .con("start", Valor::Real(redondear(t.start, 2)))
                .con("end", Valor::Real(redondear(t.end, 2)))
                .con("dur", Valor::Real(redondear(t.end - t.start, 2)))
                .con("intervalo", format!("{s} - {e}"))
                .con("texto", prig_plataforma::py::strip(&t.trad.join(" ")).to_string())
                .con("texto_original", prig_plataforma::py::strip(&t.orig.join(" ")).to_string()),
        );
    };
    let mut actual: Option<Trozo> = None;
    for (n, ent) in base.iter().enumerate() {
        let o = if misma && n < orig.len() {
            Some(&orig[n])
        } else if !orig.is_empty() {
            let k = inicios.partition_point(|x| *x < ent.start);
            let vecinas: Vec<&Entrada> = [k.checked_sub(1), Some(k)].into_iter().flatten().filter(|x| *x < orig.len()).map(|x| &orig[x]).collect();
            let mut mejor = vecinas[0];
            for v in &vecinas[1..] {
                if (v.start - ent.start).abs() < (mejor.start - ent.start).abs() {
                    mejor = v;
                }
            }
            Some(mejor)
        } else {
            None
        };
        let t_orig = o.map(|x| x.texto.clone()).unwrap_or_else(|| ent.texto.clone());
        match &mut actual {
            None => actual = Some(Trozo { start: ent.start, end: ent.end, trad: vec![ent.texto.clone()], orig: vec![t_orig] }),
            Some(t) => {
                let dur = ent.end - t.start;
                let largo: usize = t.trad.iter().map(|x| x.chars().count()).sum();
                let fin = t.trad.last().map(|x| x.trim_end()).is_some_and(|x| x.ends_with('.') || x.ends_with('!') || x.ends_with('?'));
                if dur >= 25.0 || (dur >= 12.0 && fin) || largo >= 220 {
                    cerrar(t, &mut segmentos);
                    *t = Trozo { start: ent.start, end: ent.end, trad: vec![ent.texto.clone()], orig: vec![t_orig] };
                } else {
                    t.end = ent.end;
                    t.trad.push(ent.texto.clone());
                    t.orig.push(t_orig);
                }
            }
        }
    }
    if let Some(t) = &actual {
        cerrar(t, &mut segmentos);
    }
    if es_es && usado != "es" {
        let textos: Vec<String> = segmentos.iter().map(|s| s.texto("texto").unwrap_or("").to_string()).collect();
        let traducidos = traducir_lote(&textos, "es");
        let mut cambiados = 0;
        for (i, tr) in traducidos.iter().enumerate() {
            if !tr.is_empty() && Some(tr.as_str()) != segmentos[i].texto("texto") {
                segmentos[i].poner("texto", tr.clone());
                cambiados += 1;
            }
        }
        if cambiados > 0 {
            usado = "es".into();
            nombre = format!("Español (traducido desde {nombre_origen})");
            if cambiados < segmentos.len() {
                nombre += &format!(" · {} párrafos sin traducir", segmentos.len() - cambiados);
            }
        }
    }
    let r = Mapa::new()
        .con("ok", true)
        .con("version", VERSION as i128)
        .con("video_id", video)
        .con("idioma_destino", destino)
        .con("idioma_usado", usado.clone())
        .con("idioma_nombre", nombre)
        .con("idiomas_disponibles", Valor::Lista(disponibles))
        .con("total_segmentos", segmentos.len() as i128)
        .con("segmentos", Valor::Lista(segmentos.into_iter().map(Valor::Mapa).collect()));
    if !(es_es && usado != "es") {
        let _ = std::fs::write(&cache, prig_plataforma::json::escribir(&Valor::Mapa(r.clone()), 2));
    }
    r
}
