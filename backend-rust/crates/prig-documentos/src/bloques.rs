//! Un documento de Prig como una lista de bloques (lo que antes eran los «flowables» de reportlab): portada,
//! secciones, Markdown, código resaltado, la caja del profesor... Se escribe en Typst con el preámbulo de estilos
//! de abajo (los colores, tamaños y márgenes de `kaggle_pdf.py` y `pdf_exporter.py`) y se compila a PDF.

use crate::marcado::{cadena, markdown, texto};
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(tag = "tipo", rename_all = "snake_case")]
pub enum Bloque {
    /// Portada centrada: la etiqueta («NOTEBOOK DE KAGGLE EXPLICADO»), el título, líneas en Markdown y la fecha
    Portada { etiqueta: String, titulo: String, #[serde(default)] lineas: Vec<String>, #[serde(default)] fecha: String },
    /// Cabecera de una exportación de código: título y subtítulo, centrados, con una raya debajo
    Titulo { texto: String, #[serde(default)] sub: String },
    Salto,
    Espacio { alto: f64 },
    Raya,
    Seccion { texto: String },
    /// Cabecera pequeña de una celda: nunca se queda sola al pie de una página
    Celda { texto: String },
    /// Banda de color con el nombre de un archivo
    Banner { texto: String },
    Markdown { texto: String, #[serde(default)] profesor: bool },
    Nota { texto: String },
    Alumno { texto: String },
    /// Código en su caja; `lenguaje` None: sin resaltar. `salida`: el estilo de la salida guardada de una celda
    Codigo { texto: String, #[serde(default)] lenguaje: Option<String>, #[serde(default)] salida: bool, #[serde(default)] max_lineas: Option<usize> },
    Profesor { etiqueta: String, texto: String },
}

#[derive(Deserialize, Default, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Estilo {
    #[default]
    Notebook,
    Codigo,
}

#[derive(Deserialize)]
pub struct Documento {
    pub titulo: String,
    #[serde(default)]
    pub asunto: String,
    #[serde(default)]
    pub estilo: Estilo,
    /// El pie con el título y el número de página, desde la segunda
    #[serde(default)]
    pub pie: bool,
    pub bloques: Vec<Bloque>,
}

const PREAMBULO: &str = r##"
#let azul = rgb("#0a7bb0")
#let morado = rgb("#7c3aed")
#let gris = rgb("#6b7280")
#set text(font: ("DejaVu Sans", "Libertinus Serif"), size: 9.6pt, lang: "es", hyphenate: false)
#set par(leading: 0.42em, spacing: 0.75em)
#show raw: set text(font: "DejaVu Sans Mono")
#set raw(tab-size: 4)
#let h1(c) = block(above: 0.9em, below: 0.5em, sticky: true, text(weight: "bold", size: 14pt, c))
#let h2(c) = block(above: 0.8em, below: 0.45em, sticky: true, text(weight: "bold", size: 12pt, c))
#let h3(c) = block(above: 0.7em, below: 0.4em, sticky: true, text(weight: "bold", size: 10.5pt, c))
#let h3p(c) = block(above: 0.7em, below: 0.4em, sticky: true, text(weight: "bold", size: 10pt, fill: morado, c))
#let cita(c) = pad(left: 12pt, text(style: "italic", fill: gris, c))
#let enlace(url, c) = link(url, underline(text(fill: azul, c)))
#let codigo-linea(t) = text(font: "DejaVu Sans Mono", size: 8.4pt, fill: rgb("#b4235a"), t)
#let caja-codigo(r, fondo: rgb("#f5f6f8"), tam: 7.8pt, color: black) = block(width: 100%, fill: fondo,
  stroke: 0.5pt + rgb("#e5e7eb"), inset: (x: 7pt, y: 5pt), breakable: true, above: 0.5em, below: 0.6em,
  text(size: tam, fill: color, r))
#let tabla(n, ..c) = block(text(size: 8pt, table(columns: n, stroke: 0.4pt + rgb("#d1d5db"), inset: 4pt,
  fill: (x, y) => if y == 0 { rgb("#eef2f7") }, ..c.pos())))
#let raya() = line(length: 100%, stroke: 0.5pt + rgb("#d1d5db"))
#let profesor(etiqueta, c) = block(width: 100%, fill: rgb("#f6f2ff"), stroke: (left: 2.2pt + morado),
  inset: (left: 9pt, right: 8pt, y: 6pt), breakable: true, above: 0.5em, below: 0.6em)[
  #text(size: 8pt, weight: "bold", fill: morado, etiqueta)
  #c
]
#let seccion(c) = block(above: 0.7em, below: 0.8em, sticky: true, text(weight: "bold", size: 15pt, fill: azul, c))
#let celda(c) = block(above: 1em, below: 0.35em, sticky: true, text(weight: "bold", size: 8pt, fill: gris, c))
#let nota(c) = text(size: 8pt, fill: gris, c)
#let banner(c) = block(width: 100%, fill: rgb("#0969da"), inset: 8pt, above: 1em, below: 0.6em, sticky: true,
  text(weight: "bold", size: 14pt, fill: white, c))
"##;

fn pie(titulo: &str) -> String {
    format!(
        r##"#set page(footer: context {{
  let n = counter(page).get().first()
  if n > 1 {{
    line(length: 100%, stroke: 0.5pt + rgb("#e5e7eb"))
    v(-4pt)
    text(size: 7.5pt, fill: gris)[{} #h(1fr) Página #n]
  }}
}})
"##,
        texto(&titulo.chars().take(95).collect::<String>())
    )
}

/// Las primeras `n` líneas de un texto y si se recortó
fn recortar(t: &str, n: Option<usize>) -> (String, bool) {
    let lineas: Vec<&str> = t.trim_end_matches('\n').split('\n').collect();
    match n {
        Some(n) if lineas.len() > n => (lineas[..n].join("\n"), true),
        _ => (lineas.join("\n"), false),
    }
}

pub fn a_typst(doc: &Documento) -> String {
    let mut s = String::with_capacity(16 * 1024);
    s.push_str(&format!("#set document(title: {}, author: \"Prig\"", cadena(&doc.titulo)));
    if !doc.asunto.is_empty() {
        s.push_str(&format!(", description: {}", cadena(&doc.asunto)));
    }
    s.push_str(")\n");
    let margen = match doc.estilo {
        Estilo::Notebook => "(left: 2cm, right: 2cm, top: 1.8cm, bottom: 2cm)",
        Estilo::Codigo => "0.5in",
    };
    s.push_str(&format!("#set page(paper: \"a4\", margin: {margen})\n"));
    s.push_str(PREAMBULO);
    if doc.estilo == Estilo::Codigo {
        // la exportación de una carpeta es sobre todo código: más grande que en un notebook explicado
        s.push_str("#let caja-codigo = caja-codigo.with(tam: 9pt)\n");
    }
    if doc.pie {
        s.push_str(&pie(&doc.titulo));
    }
    for b in &doc.bloques {
        match b {
            Bloque::Portada { etiqueta, titulo, lineas, fecha } => {
                s.push_str("#v(5cm)\n#align(center)[\n");
                s.push_str(&format!("#text(size: 10pt, fill: azul)[{}]\n\n", texto(etiqueta)));
                s.push_str(&format!("#text(size: 24pt, weight: \"bold\")[{}]\n\n", texto(titulo)));
                for l in lineas {
                    s.push_str(&format!("#text(size: 11pt, fill: gris)[{}]\n\n", markdown(l, false).trim_end()));
                }
                s.push_str("#v(1.5cm)\n#line(length: 40%, stroke: 1pt + azul)\n#v(0.4cm)\n");
                if !fecha.is_empty() {
                    s.push_str(&format!("#text(size: 11pt, fill: gris)[{}]\n", texto(fecha)));
                }
                s.push_str("]\n");
            }
            Bloque::Titulo { texto: t, sub } => {
                s.push_str("#v(20pt)\n#align(center)[\n");
                s.push_str(&format!("#text(size: 24pt, weight: \"bold\", fill: rgb(\"#0969da\"))[{}]\n\n", texto(t)));
                if !sub.is_empty() {
                    s.push_str(&format!("#text(size: 13pt, fill: rgb(\"#555555\"))[{}]\n", texto(sub)));
                }
                s.push_str("]\n#v(12pt)\n#line(length: 100%, stroke: 1pt + rgb(\"#e1e4e8\"))\n#v(14pt)\n");
            }
            Bloque::Salto => s.push_str("#pagebreak(weak: true)\n"),
            Bloque::Espacio { alto } => s.push_str(&format!("#v({}pt)\n", alto.clamp(0.0, 2000.0))),
            Bloque::Raya => s.push_str("#raya()\n"),
            Bloque::Seccion { texto: t } => s.push_str(&format!("#seccion[{}]\n", texto(t))),
            Bloque::Celda { texto: t } => s.push_str(&format!("#celda[{}]\n", texto(t))),
            Bloque::Banner { texto: t } => s.push_str(&format!("#banner[{}]\n", texto(t))),
            Bloque::Markdown { texto: t, profesor } => {
                s.push_str(&markdown(t, *profesor));
                s.push('\n');
            }
            Bloque::Nota { texto: t } => s.push_str(&format!("#nota[{}]\n\n", markdown(t, false).trim_end())),
            Bloque::Alumno { texto: t } => {
                s.push_str(&format!("#block(above: 1em)[#text(weight: \"bold\", fill: azul)[{}]]\n", markdown(t, false).trim_end()))
            }
            Bloque::Codigo { texto: t, lenguaje, salida, max_lineas } => {
                let (cuerpo, recortado) = recortar(t, *max_lineas);
                let lang = lenguaje.as_deref().map(|l| format!("lang: {}, ", cadena(l))).unwrap_or_default();
                let estilo = if *salida { ", fondo: rgb(\"#fbfbfb\"), tam: 7.4pt, color: rgb(\"#374151\")" } else { "" };
                s.push_str(&format!("#caja-codigo(raw(block: true, {lang}{}){estilo})\n", cadena(&cuerpo)));
                if recortado {
                    s.push_str("#nota[… (salida recortada)]\n\n");
                }
            }
            Bloque::Profesor { etiqueta, texto: t } => {
                s.push_str(&format!("#profesor({})[\n{}]\n", cadena(etiqueta), markdown(t, true)));
            }
        }
    }
    s
}
