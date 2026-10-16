//! Leer PDF con PDFium (el motor de PDF de Chrome) en lugar de pypdf: el texto de cada página, los marcadores (el
//! índice real del libro) y el número de páginas. Medido con un libro de 864 páginas: 1,7 s (pypdf ~14 s en serie),
//! con el 99,5 % de las palabras iguales y ninguna página perdida; donde difieren, PDFium acierta más (pypdf pegaba
//! palabras: «Y ou», «TokyoBeijing»).
//!
//! PDFium no se puede usar desde dos hilos a la vez: la biblioteca se carga una vez y cada llamada la toma entera.

use pdfium_render::prelude::*;
use std::sync::{Mutex, OnceLock};

static PDFIUM: OnceLock<Result<Mutex<Pdfium>, String>> = OnceLock::new();

/// Carga PDFium de `ruta` (la primera vez; después devuelve si quedó cargada)
pub fn cargar(ruta: &str) -> Result<(), String> {
    let r = PDFIUM.get_or_init(|| {
        Pdfium::bind_to_library(ruta).map(|b| Mutex::new(Pdfium::new(b))).map_err(|e| format!("PDFium no se pudo cargar de {ruta}: {e}"))
    });
    r.as_ref().map(|_| ()).map_err(|e| e.clone())
}

fn con<T>(f: impl FnOnce(&Pdfium) -> Result<T, String>) -> Result<T, String> {
    match PDFIUM.get() {
        Some(Ok(p)) => f(&p.lock().unwrap()),
        Some(Err(e)) => Err(e.clone()),
        None => Err("PDFium no está cargado".into()),
    }
}

fn abrir<'a>(p: &'a Pdfium, ruta: &str) -> Result<PdfDocument<'a>, String> {
    p.load_pdf_from_file(ruta, None).map_err(|e| format!("{e:?}"))
}

/// El texto de una página como lo usa Prig: saltos `\n` (PDFium da `\r\n`)
fn texto(pagina: &PdfPage) -> String {
    pagina.text().map(|t| t.all()).unwrap_or_default().replace("\r\n", "\n").replace('\r', "\n")
}

pub fn num_paginas(ruta: &str) -> Result<usize, String> {
    con(|p| Ok(abrir(p, ruta)?.pages().len() as usize))
}

/// El texto de todas las páginas (`(número desde 1, texto)`), sin blancos alrededor
pub fn paginas(ruta: &str) -> Result<Vec<(usize, String)>, String> {
    con(|p| {
        let doc = abrir(p, ruta)?;
        Ok(doc.pages().iter().enumerate().map(|(i, pg)| (i + 1, prig_plataforma::py::strip(&texto(&pg)).to_string())).collect())
    })
}

/// El texto ya extraído de las páginas de los últimos libros abiertos: el lector pasa de página y busca sin
/// volver a extraer nada. Un libro se reconoce por ruta, fecha de modificación y tamaño (si cambia, se relee).
type Clave = (String, std::time::SystemTime, u64);
static CACHE: Mutex<Vec<(Clave, Vec<Option<String>>)>> = Mutex::new(Vec::new());
const LIBROS_EN_CACHE: usize = 3;

fn clave(ruta: &str) -> Result<Clave, String> {
    let m = std::fs::metadata(ruta).map_err(|e| e.to_string())?;
    Ok((ruta.to_string(), m.modified().map_err(|e| e.to_string())?, m.len()))
}

/// El texto crudo de las páginas `indices` (desde 0), de la caché o extraído ahora
fn textos(ruta: &str, indices: &[usize]) -> Result<Vec<String>, String> {
    let k = clave(ruta)?;
    let faltan: Vec<usize> = {
        let cache = CACHE.lock().unwrap();
        match cache.iter().find(|(c, _)| *c == k) {
            Some((_, v)) => indices.iter().copied().filter(|&i| v.get(i).is_none_or(|t| t.is_none())).collect(),
            None => indices.to_vec(),
        }
    };
    let nuevos: Vec<(usize, String)> = if faltan.is_empty() {
        Vec::new()
    } else {
        con(|p| {
            let doc = abrir(p, ruta)?;
            let paginas = doc.pages();
            Ok(faltan.iter().map(|&i| (i, paginas.get(i as u16).map(|pg| texto(&pg)).unwrap_or_default())).collect())
        })?
    };
    let mut cache = CACHE.lock().unwrap();
    let pos = match cache.iter().position(|(c, _)| *c == k) {
        Some(i) => i,
        None => {
            cache.retain(|(c, _)| c.0 != k.0);
            if cache.len() >= LIBROS_EN_CACHE {
                cache.remove(0);
            }
            cache.push((k, Vec::new()));
            cache.len() - 1
        }
    };
    let v = &mut cache[pos].1;
    for (i, t) in nuevos {
        if v.len() <= i {
            v.resize(i + 1, None);
        }
        v[i] = Some(t);
    }
    Ok(indices.iter().map(|&i| v.get(i).cloned().flatten().unwrap_or_default()).collect())
}

/// El texto crudo de una página (desde 0), o de las primeras `n`
pub fn pagina(ruta: &str, indice: usize) -> Result<String, String> {
    if indice >= num_paginas(ruta)? {
        return Err(format!("la página {indice} no existe"));
    }
    Ok(textos(ruta, &[indice])?.remove(0))
}

pub fn primeras(ruta: &str, n: usize) -> Result<Vec<String>, String> {
    let n = n.min(num_paginas(ruta)?);
    textos(ruta, &(0..n).collect::<Vec<_>>())
}

/// Busca en las primeras `n` páginas como `BookService.get_pdf_pages`: `(página desde 1, «...trozo...»)` por cada
/// página donde aparece la consulta (sin mayúsculas), con 40 caracteres alrededor de la primera aparición
pub fn buscar(ruta: &str, consulta: &str, n: usize) -> Result<Vec<(usize, String)>, String> {
    let sq: Vec<char> = consulta.to_lowercase().chars().collect();
    Ok(primeras(ruta, n)?
        .iter()
        .enumerate()
        .filter_map(|(i, t)| {
            let bajo: Vec<char> = t.to_lowercase().chars().collect();
            let pos = if sq.is_empty() { 0 } else { bajo.windows(sq.len()).position(|w| w == sq.as_slice())? };
            let original: Vec<char> = t.chars().collect();
            let ini = pos.saturating_sub(40).min(original.len());
            let fin = (pos + sq.len() + 40).min(original.len()).max(ini);
            let trozo: String = original[ini..fin].iter().map(|&c| if c == '\n' { ' ' } else { c }).collect();
            Some((i + 1, format!("...{trozo}...")))
        })
        .collect())
}

/// Los marcadores del PDF: (título, nivel desde 0, página desde 1 si apunta a una)
pub fn marcadores(ruta: &str) -> Result<Vec<(String, usize, Option<usize>)>, String> {
    con(|p| {
        let doc = abrir(p, ruta)?;
        let mut salida = Vec::new();
        fn recorrer(b: PdfBookmark, nivel: usize, salida: &mut Vec<(String, usize, Option<usize>)>) {
            let titulo = b.title().map(|t| prig_plataforma::py::strip(&t).to_string()).unwrap_or_default();
            let pagina = b.destination().and_then(|d| d.page_index().ok()).map(|i| i as usize + 1);
            if !titulo.is_empty() {
                salida.push((titulo, nivel, pagina));
            }
            let mut hijo = b.first_child();
            while let Some(h) = hijo {
                let siguiente = h.next_sibling();
                recorrer(h, nivel + 1, salida);
                hijo = siguiente;
            }
        }
        let mut b = doc.bookmarks().root();
        while let Some(x) = b {
            let siguiente = x.next_sibling();
            recorrer(x, 0, &mut salida);
            b = siguiente;
        }
        Ok(salida)
    })
}

/// Lo que necesita el sondeo de un libro (`sondeo_libro._medir_pdf`), abriéndolo una sola vez
pub struct Sondeo {
    pub total: usize,
    /// Las páginas muestreadas (desde 0) y su texto crudo
    pub muestra: Vec<(usize, String)>,
    /// Imágenes de las páginas muestreadas (objetos imagen de la página, también dentro de formularios)
    pub imagenes: usize,
    /// Todos los marcadores, también los de título vacío: (título sin blancos, nivel)
    pub marcadores: Vec<(String, usize)>,
    /// Title, Author, Subject y Producer, los que tenga
    pub metadatos: Vec<(&'static str, String)>,
}

/// Las páginas que se muestrean: `n` repartidas por el libro, saltándose la portada (como `_medir_pdf`, con el
/// redondeo a par de `round()` de Python)
pub fn indices_muestra(total: usize, n: usize) -> Vec<usize> {
    let arranque = ((total as f64 * 0.05) as i64 + 1).min(12);
    let mut v: Vec<i64> = (0..n)
        .map(|i| (arranque as f64 + i as f64 * (total as i64 - arranque - 1) as f64 / (n as i64 - 1).max(1) as f64).round_ties_even() as i64)
        .collect();
    v.sort_unstable();
    v.dedup();
    v.into_iter().filter(|&i| i >= 0 && (i as usize) < total).map(|i| i as usize).collect()
}

fn imagenes_de<'a>(objetos: impl Iterator<Item = PdfPageObject<'a>>) -> usize {
    objetos
        .map(|o| match &o {
            PdfPageObject::Image(_) => 1,
            PdfPageObject::XObjectForm(f) => imagenes_de(f.iter()),
            _ => 0,
        })
        .sum()
}

pub fn sondeo(ruta: &str, n_muestra: usize) -> Result<Sondeo, String> {
    con(|p| {
        let doc = abrir(p, ruta)?;
        let total = doc.pages().len() as usize;
        let mut muestra = Vec::new();
        let mut imagenes = 0;
        for i in indices_muestra(total, n_muestra) {
            let Ok(pg) = doc.pages().get(i as u16) else {
                muestra.push((i, String::new()));
                continue;
            };
            muestra.push((i, texto(&pg)));
            imagenes += imagenes_de(pg.objects().iter());
        }
        let mut marcadores = Vec::new();
        fn recorrer(b: PdfBookmark, nivel: usize, salida: &mut Vec<(String, usize)>) {
            salida.push((b.title().map(|t| prig_plataforma::py::strip(&t).to_string()).unwrap_or_default(), nivel));
            let mut hijo = b.first_child();
            while let Some(h) = hijo {
                let siguiente = h.next_sibling();
                recorrer(h, nivel + 1, salida);
                hijo = siguiente;
            }
        }
        let mut b = doc.bookmarks().root();
        while let Some(x) = b {
            let siguiente = x.next_sibling();
            recorrer(x, 0, &mut marcadores);
            b = siguiente;
        }
        let meta = doc.metadata();
        let metadatos = [
            ("Title", PdfDocumentMetadataTagType::Title),
            ("Author", PdfDocumentMetadataTagType::Author),
            ("Subject", PdfDocumentMetadataTagType::Subject),
            ("Producer", PdfDocumentMetadataTagType::Producer),
        ]
        .into_iter()
        .filter_map(|(nombre, tipo)| meta.get(tipo).map(|t| (nombre, t.value().chars().take(200).collect())))
        .collect();
        Ok(Sondeo { total, muestra, imagenes, marcadores, metadatos })
    })
}

/// Si el error de abrir un PDF es que pide contraseña
pub fn es_de_contrasena(error: &str) -> bool {
    error.contains("PasswordError") || error.contains("Password")
}

#[cfg(test)]
mod pruebas {
    use super::indices_muestra;

    #[test]
    fn indices_como_python() {
        // repr() de Python de las listas de `_medir_pdf` para 0..3000 páginas (24 muestras) y 0..300 (1 y 7)
        let mut r = String::from("[");
        let mut primero = true;
        for (n, hasta) in [(24, 3000), (1, 300), (7, 300)] {
            for t in 0..hasta {
                if !primero {
                    r.push_str(", ");
                }
                primero = false;
                let v: Vec<String> = indices_muestra(t, n).iter().map(|i| i.to_string()).collect();
                r.push_str(&format!("[{}]", v.join(", ")));
            }
        }
        r.push(']');
        use md5::{Digest, Md5};
        let h: String = Md5::digest(r.as_bytes()).iter().map(|b| format!("{b:02x}")).collect();
        assert_eq!(h, "7f649af8c24c6158f9e93790a2153531");
    }
}
