//! El sondeo rápido de un libro antes de extraerlo (`sondeo_libro.py`): medir sin modelo (páginas, texto, densidad
//! de matemáticas y de código página a página, imágenes, índice, idioma), clasificar con UNA llamada corta al modelo
//! sobre una muestra, y recomendar la configuración de extracción y el flujo de análisis.

use std::sync::OnceLock;

use prig_plataforma::py;
use prig_plataforma::regex_py::ExpresionPy;
use prig_recursos::valor::{redondear, redondear_entero, Mapa, Valor};

pub const PAGINAS_MUESTRA: usize = 24;
const CHARS_PAGINA_ESCANEADO: usize = 120;
const CARACTERES_POR_TOKEN: f64 = 3.6;

const SIMBOLOS_MAT: &str = "∑∏∫∮∂∇√∞≈≠≤≥±∓×÷⊂⊆∈∉∪∩∀∃⇒⇔→←↔αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ";

const PATRONES_MAT: [&str; 10] = [
    r"\\[a-zA-Z]{2,}\{",
    r"\$[^$]{2,60}\$",
    r"\b[a-z]\s*=\s*[^=]",
    r"\^\s*[0-9{]",
    r"_\s*[0-9{i-n]",
    r"\b(teorema|lema|corolario|demostraci[oó]n|proposici[oó]n|axioma|theorem|lemma|corollary|proof|proposition)\b",
    r"\b[a-zA-Z]'\s*\(",
    r"\[\s*[a-z]\s*,\s*[a-z]\s*\]",
    r"\)\s*/\s*\(",
    r"\b(sea|sean|supongamos|entonces existe|para todo|si y s[oó]lo si|let|suppose|there exists|for all|if and only if)\b",
];

const PATRONES_CODIGO: [&str; 7] = [
    r"[;{}]\s*$",
    r"\b[a-zA-Z_]\w{2,}\s*\([^)]*\)",
    r"^\s*(#\s|//|/\*)",
    r"\b\w{2,}\.\w{2,}\(",
    r"->|=>|::|\+=|-=|\*=|==|!=",
    r"\b(import|from|def|class|return|function|const|var|let|public|void|include|namespace|print|printf)\b",
    r"^\s{4,}\w{2,}\s*[=(.]",
];

const PALABRAS_CODIGO: [&str; 40] = [
    "def", "class", "import", "return", "function", "const", "let", "var", "public", "private", "static", "void", "int", "float", "double", "struct",
    "include", "namespace", "template", "printf", "println", "console", "if", "else", "for", "while", "try", "catch", "except", "lambda", "self", "this",
    "null", "none", "true", "false", "async", "await", "", "",
];

const PISTAS: [(&str, &[&str]); 4] = [
    ("es", &["de", "la", "que", "el", "en", "los", "se", "del", "las", "por", "con", "para"]),
    ("en", &["the", "of", "and", "to", "in", "is", "that", "for", "with", "as", "this", "are"]),
    ("pt", &["de", "que", "não", "uma", "para", "com", "por", "dos", "das", "são"]),
    ("fr", &["de", "la", "le", "les", "des", "est", "une", "pour", "dans", "que"]),
];

struct Expresiones {
    mat: Vec<ExpresionPy>,
    codigo: Vec<ExpresionPy>,
    palabras: regex::Regex,
    encabezados: regex::Regex,
    imagenes_md: regex::Regex,
}

fn expresiones() -> &'static Expresiones {
    static E: OnceLock<Expresiones> = OnceLock::new();
    E.get_or_init(|| Expresiones {
        // `re.M | re.I`
        mat: PATRONES_MAT.iter().map(|p| ExpresionPy::compilar(&format!("(?m){p}"), false).unwrap()).collect(),
        // `re.M`
        codigo: PATRONES_CODIGO.iter().map(|p| ExpresionPy::compilar(&format!("(?m){p}"), true).unwrap()).collect(),
        palabras: regex::Regex::new(r"[a-zA-Z_]{2,}").unwrap(),
        encabezados: regex::Regex::new(r"(?m)^#{1,3}[ \t\n\r\f\v]+(.+)$").unwrap(),
        imagenes_md: regex::Regex::new(r"!\[[^\]]*\]\(").unwrap(),
    })
}

/// `estimar_fragmentos`
pub fn estimar_fragmentos(caracteres: i64, max_tokens: i64) -> i64 {
    if caracteres <= 0 {
        return 0;
    }
    let por = max_tokens as f64 * CARACTERES_POR_TOKEN * 0.75;
    1.max(redondear_entero(caracteres as f64 / por) as i64)
}

fn largo(t: &str) -> usize {
    t.chars().count()
}

/// `_densidades`: señales de matemáticas y de código por cada mil caracteres, y las palabras
fn densidades(t: &str) -> (f64, f64, Vec<String>) {
    let e = expresiones();
    let n = largo(t).max(1) as f64;
    let mut simbolos = t.chars().filter(|c| SIMBOLOS_MAT.contains(*c)).count();
    for r in &e.mat {
        simbolos += r.aciertos(t).len();
    }
    let bajo = t.to_lowercase();
    let palabras: Vec<String> = e.palabras.find_iter(&bajo).map(|m| m.as_str().to_string()).collect();
    let mut codigo = palabras.iter().filter(|p| PALABRAS_CODIGO.contains(&p.as_str())).count();
    for r in &e.codigo {
        codigo += r.aciertos(t).len();
    }
    (simbolos as f64 * 1000.0 / n, codigo as f64 * 1000.0 / n, palabras)
}

fn idioma(palabras: &[String]) -> String {
    if palabras.is_empty() {
        return "?".into();
    }
    let conjunto = &palabras[..palabras.len().min(4000)];
    let mut mejor: Option<(&str, usize)> = None;
    for (id, pistas) in PISTAS {
        let n = conjunto.iter().filter(|p| pistas.contains(&p.as_str())).count();
        if mejor.is_none_or(|m| n > m.1) {
            mejor = Some((id, n));
        }
    }
    let (id, n) = mejor.unwrap();
    if n as f64 > conjunto.len() as f64 * 0.01 { id.into() } else { "?".into() }
}

/// `_analizar_paginas`: página a página (lo que importa es cuántas son de código, no la media)
fn analizar_paginas(paginas: &[String]) -> Mapa {
    let paginas: Vec<&String> = paginas.iter().filter(|p| !py::strip(p).is_empty()).collect();
    if paginas.is_empty() {
        return Mapa::new()
            .con("densidad_matematicas", 0.0)
            .con("densidad_codigo", 0.0)
            .con("fraccion_paginas_matematicas", 0.0)
            .con("fraccion_paginas_codigo", 0.0)
            .con("idioma", "?")
            .con("palabras_muestra", 0);
    }
    let (mut mats, mut cods, mut todas) = (Vec::new(), Vec::new(), Vec::new());
    for p in &paginas {
        let (m, c, pal) = densidades(p);
        mats.push(m);
        cods.push(c);
        todas.extend(pal.into_iter().take(200));
    }
    let n = paginas.len() as f64;
    let suma = |v: &[f64]| prig_aprendizaje_suma(v);
    Mapa::new()
        .con("densidad_matematicas", redondear(suma(&mats) / n, 1))
        .con("densidad_codigo", redondear(suma(&cods) / n, 1))
        .con("fraccion_paginas_matematicas", redondear(mats.iter().filter(|m| **m >= 10.0).count() as f64 / n, 2))
        .con("fraccion_paginas_codigo", redondear(cods.iter().filter(|c| **c >= 15.0).count() as f64 / n, 2))
        .con("pico_matematicas", redondear(mats.iter().cloned().fold(f64::NEG_INFINITY, f64::max), 1))
        .con("pico_codigo", redondear(cods.iter().cloned().fold(f64::NEG_INFINITY, f64::max), 1))
        .con("idioma", idioma(&todas))
        .con("palabras_muestra", todas.len() as i64)
}

/// `sum()` de Python 3.12 (suma compensada), para que las medias salgan con los mismos bits
fn prig_aprendizaje_suma(v: &[f64]) -> f64 {
    crate::indices::suma_py(v)
}

fn num(m: &Mapa, k: &str) -> f64 {
    m.get(k).and_then(Valor::num).unwrap_or(0.0)
}

/// `_derivar`: lo que se deduce de las cifras
fn derivar(m: &Mapa) -> Mapa {
    let paginas = m.get("paginas").filter(|v| v.verdad()).and_then(Valor::num).unwrap_or(0.0) as i64;
    let (mat, cod, imgs) = (num(m, "fraccion_paginas_matematicas"), num(m, "fraccion_paginas_codigo"), num(m, "imagenes_por_pagina"));
    let escaneado = num(m, "fraccion_sin_texto") >= 0.5 || (paginas > 5 && num(m, "chars_por_pagina") < 200.0);
    let mut nat = Vec::new();
    if mat >= 0.35 {
        nat.push("matemático");
    } else if mat >= 0.12 {
        nat.push("con bastantes matemáticas");
    }
    if cod >= 0.30 {
        nat.push("de programación");
    } else if cod >= 0.10 {
        nat.push("con código");
    }
    if imgs >= 0.5 {
        nat.push("muy ilustrado");
    } else if imgs >= 0.2 {
        nat.push("con figuras");
    }
    if nat.is_empty() {
        nat.push("de texto corrido");
    }
    let tamano = if paginas >= 800 {
        "enorme"
    } else if paginas >= 400 {
        "largo"
    } else if paginas >= 120 {
        "normal"
    } else {
        "corto"
    };
    let chars = (num(m, "chars_por_pagina") as i64) * paginas;
    let fr = if escaneado { 0 } else { estimar_fragmentos(chars, 500) };
    Mapa::new()
        .con("escaneado", escaneado)
        .con("naturaleza", Valor::Lista(nat.into_iter().map(|n| Valor::Texto(n.into())).collect()))
        .con("tamano", tamano)
        .con("fragmentos_estimados", fr)
        .con("horas_estimadas_local", redondear(fr as f64 * 35.0 / 3600.0, 1))
}

fn medida_pdf(total: usize, textos: &[String], imagenes: usize, indice: Vec<Valor>, meta: Mapa) -> (Mapa, Vec<String>, String) {
    let muestreadas = textos.len().max(1);
    let vacias = textos.iter().filter(|t| largo(py::strip(t)) < CHARS_PAGINA_ESCANEADO).count();
    let chars: usize = textos.iter().map(|t| largo(t)).sum();
    let muestra: String = textos.iter().filter(|t| !py::strip(t).is_empty()).cloned().collect::<Vec<_>>().join("\n\n").chars().take(24000).collect();
    let m = Mapa::new()
        .con("paginas", total as i64)
        .con("paginas_muestreadas", muestreadas as i64)
        .con("chars_por_pagina", redondear_entero(chars as f64 / muestreadas as f64) as i64)
        .con("fraccion_sin_texto", redondear(vacias as f64 / muestreadas as f64, 2))
        .con("imagenes_por_pagina", redondear(imagenes as f64 / muestreadas as f64, 2))
        .con("tiene_indice", !indice.is_empty())
        .con("entradas_indice", indice.len() as i64)
        .con("indice_muestra", Valor::Lista(indice.into_iter().take(25).collect()))
        .con("metadatos", meta);
    (m, textos.to_vec(), muestra)
}

/// La medición del archivo; con (páginas de texto, muestra) aparte
fn medir_pdf(ruta: &str, pdf_listo: bool) -> (Mapa, Vec<String>, String) {
    let error = |e: &str| (Mapa::new().con("error", e).con("paginas", 0), Vec::new(), String::new());
    if !pdf_listo {
        return error("pypdf no está instalado; no se puede sondear un PDF");
    }
    match crate::pdf::sondeo(ruta, PAGINAS_MUESTRA) {
        Err(e) if crate::pdf::es_de_contrasena(&e) => {
            let (m, p, s) = error("el PDF está protegido con contraseña");
            (m.con("cifrado", true), p, s)
        }
        Err(e) => error(&format!("el PDF no se puede abrir ({e})")),
        Ok(s) if s.total == 0 => error("el PDF no tiene páginas"),
        Ok(s) => {
            let indice: Vec<Valor> = s.marcadores.iter().map(|(t, n)| Valor::Mapa(Mapa::new().con("titulo", t.as_str()).con("nivel", *n as i64))).collect();
            let mut meta = Mapa::new();
            for (k, v) in &s.metadatos {
                meta.poner(*k, v.as_str());
            }
            let textos: Vec<String> = s.muestra.iter().map(|(_, t)| t.clone()).collect();
            medida_pdf(s.total, &textos, s.imagenes, indice, meta)
        }
    }
}

fn texto_de_cuaderno(bruto: &str) -> String {
    let Ok(Valor::Mapa(nb)) = prig_plataforma::json::leer(bruto) else { return bruto.to_string() };
    let mut partes = Vec::new();
    for c in nb.lista("cells").unwrap_or(&[]) {
        let Valor::Mapa(c) = c else { continue };
        partes.push(match c.get("source") {
            Some(Valor::Lista(l)) => l.iter().map(Valor::texto_py).collect::<String>(),
            Some(v) => v.texto_py(),
            None => String::new(),
        });
    }
    partes.join("\n\n")
}

fn medir_texto(ruta: &str) -> (Mapa, Vec<String>, String) {
    let texto = match std::fs::read(ruta) {
        Ok(b) => String::from_utf8_lossy(&b).replace('\u{FFFD}', "").replace("\r\n", "\n").replace('\r', "\n"),
        Err(e) => return (Mapa::new().con("error", py::error_os(&e, ruta)).con("paginas", 0), Vec::new(), String::new()),
    };
    let texto = if ruta.to_lowercase().ends_with(".ipynb") { texto_de_cuaderno(&texto) } else { texto };
    let n = largo(&texto);
    let paginas = 1.max(redondear_entero(n as f64 / 2500.0) as i64);
    let e = expresiones();
    let encabezados: Vec<String> = e.encabezados.captures_iter(&texto).map(|c| c[1].to_string()).collect();
    let chars: Vec<char> = texto.chars().collect();
    let trozos: Vec<String> = chars.chunks(2500).take(40).map(|c| c.iter().collect()).collect();
    let m = Mapa::new()
        .con("paginas", paginas)
        .con("paginas_muestreadas", paginas)
        .con("chars_por_pagina", redondear_entero(n as f64 / paginas as f64) as i64)
        .con("fraccion_sin_texto", 0.0)
        .con("imagenes_por_pagina", redondear(e.imagenes_md.find_iter(&texto).count() as f64 / paginas as f64, 2))
        .con("tiene_indice", !encabezados.is_empty())
        .con("entradas_indice", encabezados.len() as i64)
        .con("indice_muestra", Valor::Lista(encabezados.iter().take(25).map(|h| Valor::Mapa(Mapa::new().con("titulo", py::strip(h)).con("nivel", 0))).collect()))
        .con("metadatos", Mapa::new());
    (m, trozos, chars.iter().take(24000).collect())
}

/// `medir`: la ficha del archivo sin modelo; Err si no existe
pub fn medir(ruta: &str, pdf_listo: bool) -> Result<(Mapa, String), String> {
    let ruta = py::abspath(&py::expanduser(ruta));
    if !std::path::Path::new(&ruta).is_file() {
        return Err(format!("No existe: {ruta}"));
    }
    let ext = py::splitext(&ruta).1.to_lowercase();
    let mb = std::fs::metadata(&ruta).map(|m| m.len()).unwrap_or(0) as f64 / (1024.0 * 1024.0);
    let mut base = Mapa::new().con("ruta", ruta.as_str()).con("nombre", py::basename(&ruta)).con("extension", ext.as_str()).con("mb", redondear(mb, 2)).con("medido_en", py::ahora_iso());
    let (medida, paginas, muestra) = if ext == ".pdf" { medir_pdf(&ruta, pdf_listo) } else { medir_texto(&ruta) };
    for (k, v) in medida.iter() {
        base.poner(k.clone(), v.clone());
    }
    for (k, v) in analizar_paginas(&paginas).iter() {
        base.poner(k.clone(), v.clone());
    }
    let d = derivar(&base);
    for (k, v) in d.iter() {
        base.poner(k.clone(), v.clone());
    }
    Ok((base, muestra))
}

const SISTEMA: &str = "Clasificas un libro a partir de unas páginas sueltas suyas y de unas cifras medidas sobre el archivo. No has leído el libro entero y no debes fingir que sí: si la muestra no alcanza para decidir algo, responde \"indeterminado\" en ese campo. Devuelves únicamente JSON válido.";

/// `_json_de`: el primer objeto JSON equilibrado de un texto
pub fn json_de(t: &str) -> Option<Valor> {
    let inicio = t.find('{')?;
    let (mut prof, mut cad, mut esc) = (0i64, false, false);
    for (i, c) in t[inicio..].char_indices() {
        if esc {
            esc = false;
            continue;
        }
        match c {
            '\\' => esc = true,
            '"' => cad = !cad,
            _ if cad => {}
            '{' => prof += 1,
            '}' => {
                prof -= 1;
                if prof == 0 {
                    return prig_plataforma::json::leer(&t[inicio..inicio + i + 1]).ok();
                }
            }
            _ => {}
        }
    }
    None
}

/// `clasificar`: el prompt y el sistema (el que llama genera con `temperature` 0,1 y `num_predict` 700)
pub fn prompt_clasificar(m: &Mapa, muestra_texto: &str) -> (String, &'static str) {
    let indice: Vec<String> = m
        .lista("indice_muestra")
        .unwrap_or(&[])
        .iter()
        .take(25)
        .filter_map(|e| if let Valor::Mapa(e) = e { Some(format!("{}{}", "  ".repeat(e.valor("nivel").num().unwrap_or(0.0) as usize), e.valor("titulo").texto_py())) } else { None })
        .collect();
    let indice = indice.join("\n");
    let muestra: String = muestra_texto.chars().take(5000).collect();
    let g = |k: &str| m.get(k).map(Valor::texto_py).unwrap_or_else(|| "None".into());
    let pct = |k: &str| redondear_entero(num(m, k) * 100.0);
    let mut p = format!(
        "Archivo: {}\nMedido sobre el propio archivo:\n  {} páginas · {} MB\n  {} caracteres por página\n  páginas con matemáticas: {} %\n  páginas con código: {} %\n  imágenes por página: {}\n  idioma detectado: {}\n\n",
        g("nombre"),
        g("paginas"),
        g("mb"),
        g("chars_por_pagina"),
        pct("fraccion_paginas_matematicas"),
        pct("fraccion_paginas_codigo"),
        g("imagenes_por_pagina"),
        g("idioma")
    );
    if !indice.is_empty() {
        p += &format!("Índice del archivo:\n{indice}\n\n");
    }
    p += &format!("Páginas sueltas, tomadas a lo largo del libro:\n{muestra}\n\nClasifícalo. El campo tiene que ser uno de: math, physics, cpp, python, machine_learning, deep_learning. Si es de programación pero de otro lenguaje, elige el más cercano y dilo en 'observaciones'.\n\n{{\"titulo_real\": \"el título de verdad, no el del archivo\", \"campo\": \"...\", \"campo_alternativo\": \"\" , \"nivel\": \"introductorio|intermedio|avanzado|referencia\", \"de_que_trata\": \"una frase\", \"para_quien\": \"...\", \"tipo\": \"manual|libro de texto|referencia|apuntes|paper|tutorial\", \"temas_principales\": [\"...\"], \"merece_extraccion\": true, \"observaciones\": \"\"}}");
    (p, SISTEMA)
}

/// La respuesta del modelo a la clasificación, como dict (o el error con lo que dijo)
pub fn leer_clasificacion(respuesta: &str) -> Mapa {
    match json_de(respuesta) {
        Some(Valor::Mapa(m)) => m,
        _ => Mapa::new().con("error", "el modelo no devolvió JSON válido").con("bruto", respuesta.chars().take(500).collect::<String>()),
    }
}

/// `recomendar`: qué configuración y qué flujo le convienen a ESTE libro
pub fn recomendar(m: &Mapa, clasificacion: &Mapa) -> Mapa {
    let (mut avisos, mut ajustes, mut bloqueos) = (Vec::<String>::new(), Mapa::new(), Vec::<String>::new());
    if let Some(e) = m.get("error").filter(|e| e.verdad()) {
        bloqueos.push(e.texto_py());
    }
    let escaneado = m.verdad("escaneado");
    if escaneado {
        bloqueos.push("Parece escaneado: las páginas casi no tienen texto extraíble. Hace falta pasarle OCR antes (ocrmypdf) o no habrá nada que extraer.".into());
    }
    let paginas = m.get("paginas").filter(|v| v.verdad()).and_then(Valor::num).unwrap_or(0.0) as i64;
    let (mat, cod, imgs) = (num(m, "fraccion_paginas_matematicas"), num(m, "fraccion_paginas_codigo"), num(m, "imagenes_por_pagina"));
    if mat >= 0.12 {
        ajustes.poner("pedir_latex", true);
        avisos.push(format!("El {} % de las páginas llevan matemáticas: la extracción tiene que pedir la fórmula en LaTeX, no solo el texto, o las derivaciones se pierden.", redondear_entero(mat * 100.0)));
    }
    if cod >= 0.10 {
        ajustes.poner("pedir_lenguaje_codigo", true);
        avisos.push(format!("El {} % de las páginas llevan código: hay que pedir el lenguaje de cada fragmento para poder ejecutarlo después.", redondear_entero(cod * 100.0)));
    }
    if imgs >= 0.5 {
        let cada = Valor::Real(redondear(1.0 / imgs.max(0.01), 1)).texto_py();
        avisos.push(format!("Una imagen cada {cada} páginas: parte de la explicación está en figuras que la extracción de texto no ve. Los pies de figura pasan a ser importantes."));
    }
    if !m.verdad("tiene_indice") {
        avisos.push("Sin índice en el archivo: el temario habrá que deducirlo de las páginas donde aparece cada concepto.".into());
    }
    let idioma = m.get("idioma").map(Valor::texto_py).unwrap_or_else(|| "None".into());
    if !["es", "en", "?"].contains(&idioma.as_str()) {
        avisos.push(format!("Idioma detectado '{idioma}': comprueba que el modelo lo maneja bien antes de lanzar la extracción entera."));
    }
    let tope = if mat >= 0.35 { 350 } else if paginas < 600 { 500 } else { 600 };
    ajustes.poner("max_chunk_tokens", tope);
    if paginas >= 800 {
        avisos.push(format!("{paginas} páginas: pártelo en dos o tres trabajos. Depender de una sola corrida larga es la forma más fácil de perder horas."));
    }
    let (flujo, razon) = if paginas < 80 {
        (Valor::Texto("plantilla_libro".into()), "Es corto: la ficha completa de siete pasos no tiene de dónde sacar un temario. Mejor analizar sus temas directamente.")
    } else if escaneado {
        (Valor::Nulo, "Sin OCR no hay nada que analizar.")
    } else {
        (Valor::Texto("plantilla_ficha_libro".into()), "Tiene tamaño y estructura suficientes para la ficha completa.")
    };
    let perfil = if paginas >= 600 { "core" } else { "full" };
    if perfil == "core" {
        avisos.push("Por su tamaño, conviene el perfil 'core' en la extracción: omite preguntas y figuras y ahorra un 20 % de tokens de salida.".into());
    }
    let chars = (m.get("chars_por_pagina").filter(|v| v.verdad()).and_then(Valor::num).unwrap_or(0.0) as i64) * paginas;
    let fragmentos = if escaneado || !bloqueos.is_empty() {
        0
    } else if chars != 0 {
        estimar_fragmentos(chars, tope)
    } else {
        num(m, "fragmentos_estimados") as i64
    };
    let lista = |v: &[String]| Valor::Lista(v.iter().map(|x| Valor::Texto(x.clone())).collect());
    Mapa::new()
        .con("se_puede_extraer", bloqueos.is_empty())
        .con("bloqueos", lista(&bloqueos))
        .con("avisos", lista(&avisos))
        .con("ajustes_extraccion", ajustes.con("profile", perfil))
        .con("flujo_recomendado", flujo)
        .con("razon_del_flujo", razon)
        .con("campo_sugerido", clasificacion.get("campo").cloned().unwrap_or(Valor::Nulo))
        .con(
            "coste",
            Mapa::new()
                .con("fragmentos", fragmentos)
                .con("horas_en_local", redondear(fragmentos as f64 * 35.0 / 3600.0, 1))
                .con("minutos_en_dos_T4", if fragmentos != 0 { Valor::Real(redondear(fragmentos as f64 * 2.5 / 60.0, 1)) } else { Valor::Entero(0) }),
        )
}

#[cfg(test)]
mod pruebas {
    //! Las de `test_explorador_sondeo.py`: lo que más importa es distinguir matemáticas de código (en un libro de
    //! matemáticas «f(b)» parece una llamada a función)

    use super::*;

    const MATEMATICAS: &str = "Teorema 3.2. Sea f una funcion continua en [a,b] y derivable en (a,b).\nEntonces existe c en (a,b) tal que f(b) - f(a) = f'(c)(b-a).\nDemostracion. Definimos g(x) = f(x) - f(a) - ((f(b)-f(a))/(b-a))(x-a).\nSe tiene g(a) = g(b) = 0, y por el teorema de Rolle existe c con g'(c) = 0.\nEl gradiente ∇J(θ) = ∇L(θ) + λw determina la direccion de maximo descenso.\nCorolario. Si f'(x) = 0 para todo x en (a,b), entonces f es constante.";
    const CODIGO: &str = "def entrenar(modelo, datos, epocas=10):\n    optimizador = torch.optim.Adam(modelo.parameters(), lr=1e-3)\n    for epoca in range(epocas):\n        perdida = F.cross_entropy(modelo(x), y)\n        perdida.backward()\n        optimizador.step()\n    return modelo";
    const CPP: &str = "template <typename T>\nclass Vector {\npublic:\n    Vector(size_t n) : datos_(new T[n]), tam_(n) {}\n    T& operator[](size_t i) { return datos_[i]; }\nprivate:\n    T* datos_;\n};";
    const PROSA: &str = "El algodon es una fibra natural que se obtiene de la planta del mismo nombre.\nSu cultivo requiere suelos profundos y bien drenados, con temperaturas templadas\ndurante todo el ciclo. La siembra se realiza en primavera, cuando el suelo ha\nalcanzado una temperatura estable superior a los quince grados centigrados.";
    const INGLES: &str = "The gradient of a scalar field is the vector whose components are the\npartial derivatives of the function. This vector points in the direction of the\nsteepest increase, and its magnitude is the rate of change in that direction.";

    fn veredicto(t: &str) -> String {
        let (m, c, _) = densidades(t);
        let v = format!("{}{}", if m >= 10.0 { "matemática" } else { "" }, if c >= 15.0 { "código" } else { "" });
        if v.is_empty() { "prosa".into() } else { v }
    }

    #[test]
    fn detectores() {
        let (m, c, _) = densidades(MATEMATICAS);
        assert!(m >= 10.0 && c < 15.0, "una demostración es matemáticas y no código ({m}, {c})");
        assert_eq!(veredicto(CODIGO), "código");
        assert_eq!(veredicto(CPP), "código");
        assert_eq!(veredicto(PROSA), "prosa");
        assert_eq!(veredicto(INGLES), "prosa");
        for (t, esperado) in [(PROSA, "es"), (INGLES, "en")] {
            assert_eq!(idioma(&densidades(t).2), esperado);
        }
    }

    #[test]
    fn por_pagina() {
        let mut p = vec![CODIGO.to_string()];
        p.extend(std::iter::repeat(PROSA.to_string()).take(3));
        let r = analizar_paginas(&p);
        assert!(r.num_o("fraccion_paginas_codigo", 0.0) >= 0.2);
        assert_eq!(r.num_o("fraccion_paginas_matematicas", 1.0), 0.0);
        p.extend(std::iter::repeat(PROSA.to_string()).take(2));
        let r = analizar_paginas(&p);
        assert!(r.num_o("pico_codigo", 0.0) > r.num_o("densidad_codigo", 0.0));
        let r = analizar_paginas(&[]);
        assert_eq!((r.num_o("densidad_codigo", 1.0), r.valor("idioma").texto_py()), (0.0, "?".to_string()));
    }

    fn escribir(dir: &std::path::Path, n: &str, t: &str) -> String {
        let r = dir.join(n);
        std::fs::write(&r, t).unwrap();
        r.to_string_lossy().to_string()
    }

    #[test]
    fn medir_archivos() {
        let d = std::env::temp_dir().join(format!("prig-sondeo-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        let (m, _) = medir(&escribir(&d, "libro.md", &format!("# Capítulo 1\n\n{}", PROSA.repeat(60))), false).unwrap();
        assert!(m.num_o("paginas", 0.0) > 1.0 && m.verdad("tiene_indice"));
        assert_eq!(m.valor("idioma").texto_py(), "es");
        let naturaleza = |m: &Mapa| m.lista("naturaleza").unwrap().iter().map(Valor::texto_py).collect::<Vec<_>>().join(" ");
        let (m, _) = medir(&escribir(&d, "curso.md", &format!("{CODIGO}\n\n").repeat(30)), false).unwrap();
        assert!(naturaleza(&m).contains("de programación"));
        let (m, _) = medir(&escribir(&d, "analisis.md", &format!("{MATEMATICAS}\n\n").repeat(30)), false).unwrap();
        assert!(naturaleza(&m).contains("matemático"));
        let nb = format!("{{\"cells\": [{{\"cell_type\": \"code\", \"source\": [{}]}}, {{\"cell_type\": \"markdown\", \"source\": [\"# Título\\n\", {}]}}]}}", prig_plataforma::json::escribir_compacto(&Valor::Texto(CODIGO.into())), prig_plataforma::json::escribir_compacto(&Valor::Texto(PROSA.into())));
        let (m, _) = medir(&escribir(&d, "nb.ipynb", &nb), false).unwrap();
        assert!(m.num_o("fraccion_paginas_codigo", 0.0) > 0.0);
        assert!(medir(&d.join("fantasma.pdf").to_string_lossy(), false).is_err());
        let (m, _) = medir(&escribir(&d, "largo.md", &PROSA.repeat(400)), false).unwrap();
        assert!(m.num_o("fragmentos_estimados", 0.0) > 0.0);
        let _ = std::fs::remove_dir_all(d);
    }

    fn base(cambios: &[(&str, Valor)]) -> Mapa {
        let mut m = Mapa::new()
            .con("paginas", 300)
            .con("fraccion_paginas_matematicas", 0.0)
            .con("fraccion_paginas_codigo", 0.0)
            .con("imagenes_por_pagina", 0.1)
            .con("tiene_indice", true)
            .con("idioma", "es")
            .con("escaneado", false)
            .con("fragmentos_estimados", 200)
            .con("horas_estimadas_local", 2.0);
        for (k, v) in cambios {
            m.poner(*k, v.clone());
        }
        m
    }

    #[test]
    fn recomendacion() {
        let r = |c: &[(&str, Valor)]| recomendar(&base(c), &Mapa::new());
        let e = r(&[("escaneado", Valor::Bool(true))]);
        assert!(!e.verdad("se_puede_extraer") && e.lista("bloqueos").unwrap().iter().any(|b| b.texto_py().contains("OCR")));
        assert!(r(&[("fraccion_paginas_matematicas", Valor::Real(0.4))]).mapa("ajustes_extraccion").unwrap().verdad("pedir_latex"));
        assert!(r(&[("fraccion_paginas_codigo", Valor::Real(0.25))]).mapa("ajustes_extraccion").unwrap().verdad("pedir_lenguaje_codigo"));
        let tope = |m: Mapa| m.mapa("ajustes_extraccion").unwrap().num_o("max_chunk_tokens", 0.0);
        assert!(tope(r(&[("fraccion_paginas_matematicas", Valor::Real(0.5))])) < tope(r(&[])));
        assert!(r(&[("paginas", Valor::Entero(1200))]).lista("avisos").unwrap().iter().any(|a| a.texto_py().contains("pártelo")));
        assert_eq!(r(&[("paginas", Valor::Entero(40))]).valor("flujo_recomendado").texto_py(), "plantilla_libro");
        assert_eq!(r(&[]).valor("flujo_recomendado").texto_py(), "plantilla_ficha_libro");
        assert!(r(&[("tiene_indice", Valor::Bool(false))]).lista("avisos").unwrap().iter().any(|a| a.texto_py().contains("Sin índice")));
        let c = r(&[]).mapa("coste").cloned().unwrap();
        assert!(c.num_o("horas_en_local", 0.0) > 0.0 && c.num_o("minutos_en_dos_T4", 0.0) > 0.0);
        assert!(c.num_o("minutos_en_dos_T4", 0.0) / 60.0 < c.num_o("horas_en_local", 0.0));
    }
}
