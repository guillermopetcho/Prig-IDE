//! Texto a Typst sin que nada del texto se interprete: el marcado de Typst con todo signo ASCII escapado, las
//! cadenas de Typst y Markdown (CommonMark con tablas, por pulldown-cmark) convertido a Typst. Lo que escribe un
//! modelo o un notebook nunca puede ejecutar código de Typst: solo llega como texto escapado o como cadena.
//!
//! Los emoji se quitan (ninguna fuente disponible los dibuja), como hacía `kaggle_pdf._texto_seguro`.

use pulldown_cmark::{CodeBlockKind, Event, Options, Parser, Tag, TagEnd};

/// Lo que ninguna fuente disponible dibuja (el `EMOJI` de kaggle_pdf)
pub fn es_emoji(c: char) -> bool {
    c as u32 >= 0x10000 || ('\u{2600}'..='\u{27BF}').contains(&c) || c == '\u{FE0F}' || c == '\u{200D}'
        // y los caracteres de control, que tampoco tienen dibujo (menos los saltos y tabuladores)
        || (c.is_control() && !matches!(c, '\n' | '\t' | '\r'))
}

/// Texto en el marcado de Typst: cada signo ASCII va escapado; los saltos de línea, como espacios
pub fn texto(t: &str) -> String {
    let mut s = String::with_capacity(t.len() + 8);
    for c in t.chars() {
        match c {
            _ if es_emoji(c) => {}
            '\r' => {}
            '\n' | '\t' => s.push(' '),
            _ if c.is_ascii_punctuation() => {
                s.push('\\');
                s.push(c);
            }
            _ => s.push(c),
        }
    }
    s
}

/// Una cadena de Typst (`"..."`)
pub fn cadena(t: &str) -> String {
    let mut s = String::with_capacity(t.len() + 2);
    s.push('"');
    for c in t.chars() {
        match c {
            _ if es_emoji(c) => {}
            '\\' => s.push_str("\\\\"),
            '"' => s.push_str("\\\""),
            '\n' => s.push_str("\\n"),
            '\r' => {}
            '\t' => s.push_str("\\t"),
            _ => s.push(c),
        }
    }
    s.push('"');
    s
}

/// Texto para meter en Markdown sin que se interprete (todo signo ASCII con barra, que CommonMark acepta)
pub fn escapar_md(t: &str) -> String {
    let mut s = String::with_capacity(t.len() + 8);
    for c in t.chars() {
        if c.is_ascii_punctuation() {
            s.push('\\');
        }
        s.push(c);
    }
    s
}

/// HTML de un notebook a texto (`kaggle_pdf._quitar_html`): fuera scripts, estilos y comentarios; saltos por
/// `<br>` y por cierres de bloque; las imágenes, por su texto alternativo; el resto de etiquetas, fuera
pub fn html_a_texto(h: &str) -> String {
    let bajo = h.to_ascii_lowercase(); // mismas posiciones en bytes que `h`
    let mut s = String::new();
    let mut i = 0;
    let b = h.as_bytes();
    while i < h.len() {
        if b[i] != b'<' {
            let fin = h[i..].find('<').map_or(h.len(), |k| i + k);
            s.push_str(&h[i..fin]);
            i = fin;
            continue;
        }
        let resto = &bajo[i..];
        let saltar_hasta = |cierre: &str| resto.find(cierre).map_or(h.len(), |k| i + k + cierre.len());
        if resto.starts_with("<!--") {
            i = saltar_hasta("-->");
        } else if resto.starts_with("<script") {
            i = saltar_hasta("</script>");
        } else if resto.starts_with("<style") {
            i = saltar_hasta("</style>");
        } else {
            let es_etiqueta = resto[1..].chars().next().is_some_and(|c| c.is_ascii_alphabetic() || c == '/');
            let fin = resto.find('>').map(|k| i + k + 1);
            match fin {
                Some(fin) if es_etiqueta => {
                    let etiqueta = &bajo[i..fin];
                    let nombre: String =
                        etiqueta.trim_start_matches(['<', '/']).chars().take_while(|c| c.is_ascii_alphanumeric()).collect();
                    if nombre == "br" || (etiqueta.starts_with("</") && ["p", "div", "li", "tr", "center", "h1", "h2", "h3", "h4", "h5", "h6"].contains(&nombre.as_str())) {
                        s.push('\n');
                    } else if nombre == "img" {
                        s.push_str(&alt_de(&h[i..fin]).map_or("[imagen]".to_string(), |a| format!("[imagen: {a}]")));
                    }
                    i = fin;
                }
                _ => {
                    s.push('<');
                    i += 1;
                }
            }
        }
    }
    desescapar_html(&s)
}

/// Fuera `<script>…</script>`, `<style>…</style>` y comentarios de todo el texto, también dentro de bloques de
/// código (como hacía `_quitar_html` antes de leer el Markdown): ese texto nunca llega al PDF
pub fn sin_scripts(t: &str) -> String {
    let bajo = t.to_ascii_lowercase();
    let mut s = String::with_capacity(t.len());
    let mut i = 0;
    while let Some(k) = bajo[i..].find('<').map(|k| i + k) {
        let resto = &bajo[k..];
        let cierre = if resto.starts_with("<!--") {
            Some("-->")
        } else if resto.starts_with("<script") {
            Some("</script>")
        } else if resto.starts_with("<style") {
            Some("</style>")
        } else {
            None
        };
        match cierre {
            Some(c) => {
                s.push_str(&t[i..k]);
                i = resto.find(c).map_or(t.len(), |f| k + f + c.len());
            }
            None => {
                s.push_str(&t[i..k + 1]);
                i = k + 1;
            }
        }
    }
    s.push_str(&t[i..]);
    s
}

fn alt_de(etiqueta: &str) -> Option<String> {
    let bajo = etiqueta.to_ascii_lowercase();
    let k = bajo.find("alt=")? + 4;
    let comilla = etiqueta[k..].chars().next().filter(|c| *c == '"' || *c == '\'')?;
    let fin = etiqueta[k + 1..].find(comilla)?;
    Some(etiqueta[k + 1..k + 1 + fin].to_string())
}

fn desescapar_html(t: &str) -> String {
    if !t.contains('&') {
        return t.to_string();
    }
    let mut s = String::with_capacity(t.len());
    let mut resto = t;
    while let Some(k) = resto.find('&') {
        s.push_str(&resto[..k]);
        resto = &resto[k..];
        let fin = resto.bytes().take(12).position(|b| b == b';');
        let entidad = fin.map(|f| &resto[1..f]);
        let c = entidad.and_then(|e| match e {
            "amp" => Some('&'),
            "lt" => Some('<'),
            "gt" => Some('>'),
            "quot" => Some('"'),
            "apos" | "#39" => Some('\''),
            "nbsp" => Some('\u{a0}'),
            _ if e.starts_with("#x") || e.starts_with("#X") => u32::from_str_radix(&e[2..], 16).ok().and_then(char::from_u32),
            _ if e.starts_with('#') => e[1..].parse().ok().and_then(char::from_u32),
            _ => None,
        });
        match (c, fin) {
            (Some(c), Some(f)) => {
                s.push(c);
                resto = &resto[f + 1..];
            }
            _ => {
                s.push('&');
                resto = &resto[1..];
            }
        }
    }
    s.push_str(resto);
    s
}

/// El lenguaje de un bloque de código para Typst: la primera palabra del bloque, si es un nombre razonable
fn lenguaje(info: &str) -> String {
    let l = info.split_whitespace().next().unwrap_or("");
    if !l.is_empty() && l.chars().all(|c| c.is_ascii_alphanumeric() || "+#-_".contains(c)) {
        l.to_ascii_lowercase()
    } else {
        "python".into()
    }
}

/// Markdown a Typst. `profesor`: los títulos van en el estilo de la caja del profesor. Las funciones a las que
/// llama (`h1`, `codigo-linea`, `caja-codigo`, `tabla`, `cita`, ...) las define el preámbulo de `bloques`.
pub fn markdown(md: &str, profesor: bool) -> String {
    let opciones = Options::ENABLE_TABLES | Options::ENABLE_STRIKETHROUGH;
    let md = sin_scripts(&md.replace("\r\n", "\n"));
    let mut s = String::new();
    let mut codigo: Option<(String, String)> = None;
    let mut en_imagen = 0usize;
    let mut enlaces: Vec<bool> = Vec::new();
    for ev in Parser::new_ext(&md, opciones) {
        if let Some((_, buf)) = codigo.as_mut() {
            match ev {
                Event::Text(t) => buf.push_str(&t),
                Event::End(TagEnd::CodeBlock) => {
                    let (lang, buf) = codigo.take().unwrap();
                    s.push_str(&format!("#caja-codigo(raw(block: true, lang: {}, {}))\n\n", cadena(&lang), cadena(buf.trim_end_matches('\n'))));
                }
                _ => {}
            }
            continue;
        }
        match ev {
            Event::Start(tag) => match tag {
                Tag::Paragraph => {}
                Tag::Heading { level, .. } => {
                    let n = level as usize;
                    let f = if profesor { "h3p" } else if n == 1 { "h1" } else if n == 2 { "h2" } else { "h3" };
                    s.push_str(&format!("#{f}["));
                }
                Tag::BlockQuote(_) => s.push_str("#cita["),
                Tag::CodeBlock(kind) => {
                    let lang = match kind {
                        CodeBlockKind::Fenced(info) => lenguaje(&info),
                        CodeBlockKind::Indented => "python".into(),
                    };
                    codigo = Some((lang, String::new()));
                }
                Tag::List(Some(inicio)) => s.push_str(&format!("#enum(start: {inicio}, ")),
                Tag::List(None) => s.push_str("#list("),
                Tag::Item => s.push('['),
                Tag::Table(columnas) => s.push_str(&format!("#tabla({}, ", columnas.len().max(1))),
                Tag::TableHead | Tag::TableRow => {}
                Tag::TableCell => s.push('['),
                Tag::Emphasis => s.push_str("#emph["),
                Tag::Strong => s.push_str("#strong["),
                Tag::Strikethrough => s.push_str("#strike["),
                Tag::Link { dest_url, .. } => {
                    let web = ["http://", "https://", "mailto:"].iter().any(|p| dest_url.starts_with(p));
                    if web {
                        s.push_str(&format!("#enlace({})[", cadena(&dest_url)));
                    }
                    enlaces.push(web);
                }
                Tag::Image { .. } => {
                    en_imagen += 1;
                    s.push_str("\\[imagen: ");
                }
                _ => {}
            },
            Event::End(fin) => match fin {
                TagEnd::Paragraph => s.push_str("\n\n"),
                TagEnd::Heading(_) | TagEnd::BlockQuote(_) => s.push_str("]\n\n"),
                TagEnd::List(_) => s.push_str(")\n\n"),
                TagEnd::Item | TagEnd::TableCell => s.push_str("], "),
                TagEnd::Table => s.push_str(")\n\n"),
                TagEnd::Emphasis | TagEnd::Strong | TagEnd::Strikethrough => s.push(']'),
                TagEnd::Link => {
                    if enlaces.pop() == Some(true) {
                        s.push(']');
                    }
                }
                TagEnd::Image => {
                    en_imagen = en_imagen.saturating_sub(1);
                    s.push_str("\\]");
                }
                _ => {}
            },
            Event::Text(t) => s.push_str(&texto(&t)),
            Event::Code(t) => s.push_str(&format!("#codigo-linea({})", cadena(&t))),
            Event::SoftBreak => s.push(' '),
            Event::HardBreak => s.push_str("#linebreak()"),
            Event::Rule => s.push_str("#raya()\n\n"),
            Event::Html(h) | Event::InlineHtml(h) => {
                let t = html_a_texto(&h);
                // los saltos que deja el HTML son saltos de línea; el texto, escapado
                let partes: Vec<String> = t.split('\n').map(texto).collect();
                s.push_str(&partes.join("#linebreak()"));
            }
            Event::InlineMath(t) | Event::DisplayMath(t) => s.push_str(&texto(&t)),
            Event::FootnoteReference(t) => s.push_str(&texto(&t)),
            Event::TaskListMarker(hecho) => s.push_str(if hecho { "☑ " } else { "☐ " }),
        }
    }
    if let Some((lang, buf)) = codigo {
        s.push_str(&format!("#caja-codigo(raw(block: true, lang: {}, {}))\n\n", cadena(&lang), cadena(&buf)));
    }
    s
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn escapa_todo() {
        assert_eq!(texto("#let x = [a] // b $c$"), "\\#let x \\= \\[a\\] \\/\\/ b \\$c\\$");
        assert_eq!(texto("hola 😀 mundo"), "hola  mundo");
        assert_eq!(cadena("a\"b\\c\n"), "\"a\\\"b\\\\c\\n\"");
    }

    #[test]
    fn html_a_texto_como_kaggle() {
        assert_eq!(html_a_texto("<b>hola</b><br>a < b &amp; c"), "hola\na < b & c");
        assert_eq!(html_a_texto("<img src=x alt=\"gato\">"), "[imagen: gato]");
        assert_eq!(html_a_texto("<script>x</script>y<!-- z -->"), "y");
    }

    #[test]
    fn sin_scripts_en_todo_el_texto() {
        assert_eq!(sin_scripts("a<SCRIPT>x</script>b<!--c-->d<style>e</style>f < g"), "abdf < g");
        assert_eq!(sin_scripts("```\n<script>x"), "```\n");
    }

    #[test]
    fn markdown_basico() {
        let t = markdown("# Título\n\nTexto **fuerte** y `x = 1`.\n\n- a\n- b\n\n```py\nprint(1)\n```\n", false);
        assert!(t.contains("#h1[Título]"));
        assert!(t.contains("#strong[fuerte]"));
        assert!(t.contains("#codigo-linea(\"x = 1\")"));
        assert!(t.contains("#list([a], [b], )"));
        assert!(t.contains("lang: \"py\""));
    }
}
