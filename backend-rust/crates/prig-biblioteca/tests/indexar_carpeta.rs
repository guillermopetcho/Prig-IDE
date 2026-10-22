//! Indexa la biblioteca de `PRIG_INDEXAR_CARPETA` (para comparar el catálogo con el que deja Python). A mano:
//! `PRIG_INDEXAR_CARPETA=... cargo test -p prig-biblioteca --test indexar_carpeta -- --ignored`

#[test]
#[ignore]
fn indexar_carpeta() {
    let Ok(dir) = std::env::var("PRIG_INDEXAR_CARPETA") else { return };
    let pdf = std::env::var("PRIG_PDFIUM").map(|r| prig_biblioteca::pdf::cargar(&r).is_ok()).unwrap_or(false);
    let c = prig_biblioteca::conocimiento::Conocimiento::new(&dir, pdf).unwrap();
    c.indexar(false);
    println!("{}", prig_plataforma::json::escribir_compacto(&prig_plataforma::valor::Valor::Mapa(c.estado().unwrap())));
}

/// Busca cada línea de `PRIG_BUSCAR_CONSULTAS` en la biblioteca de `PRIG_INDEXAR_CARPETA` (sin reformulaciones)
#[test]
#[ignore]
fn buscar_en_carpeta() {
    let (Ok(dir), Ok(qs)) = (std::env::var("PRIG_INDEXAR_CARPETA"), std::env::var("PRIG_BUSCAR_CONSULTAS")) else { return };
    let c = prig_biblioteca::conocimiento::Conocimiento::new(&dir, false).unwrap();
    for q in qs.lines() {
        let r = c.buscar(q, 6, 300, &[]).unwrap();
        println!("{}", prig_plataforma::json::escribir_compacto(&prig_plataforma::valor::Valor::Mapa(r)));
    }
}

/// Prepara un trabajo con los libros de `PRIG_TRABAJO_LIBROS` (una ruta por línea) en `PRIG_TRABAJO_DESTINO`
#[test]
#[ignore]
fn preparar_trabajo() {
    let (Ok(libros), Ok(dest)) = (std::env::var("PRIG_TRABAJO_LIBROS"), std::env::var("PRIG_TRABAJO_DESTINO")) else { return };
    let pdf = std::env::var("PRIG_PDFIUM").map(|r| prig_biblioteca::pdf::cargar(&r).is_ok()).unwrap_or(false);
    use prig_plataforma::valor::{Mapa, Valor};
    let items: Vec<Mapa> = libros.lines().map(|l| {
        let (r, d) = l.split_once('|').unwrap_or((l, ""));
        let m = Mapa::new().con("path", r).con("domain", if d.is_empty() { Valor::Nulo } else { Valor::Texto(d.into()) });
        if r.ends_with(".md") { m.con("ajustes", Mapa::new().con("max_chunk_tokens", 60)) } else { m }
    }).collect();
    let mut eventos = Vec::new();
    let m = prig_biblioteca::trabajos::preparar(&items, &dest, 500, 120, pdf, &mut |e| eventos.push(Valor::Mapa(e))).unwrap();
    println!("{}", prig_plataforma::json::escribir_linea(&Valor::Mapa(m)));
    println!("{}", prig_plataforma::json::escribir_linea(&Valor::Lista(eventos)));
}

/// Sondea (sin modelo) cada archivo de `PRIG_SONDEO_ARCHIVOS` (uno por línea): la medición y la recomendación
#[test]
#[ignore]
fn sondear_archivos() {
    let Ok(a) = std::env::var("PRIG_SONDEO_ARCHIVOS") else { return };
    let pdf = std::env::var("PRIG_PDFIUM").map(|r| prig_biblioteca::pdf::cargar(&r).is_ok()).unwrap_or(false);
    use prig_plataforma::valor::{Mapa, Valor};
    for r in a.lines() {
        let (m, muestra) = prig_biblioteca::sondeo::medir(r, pdf).unwrap();
        let rec = prig_biblioteca::sondeo::recomendar(&m, &Mapa::new());
        let (p, _) = prig_biblioteca::sondeo::prompt_clasificar(&m, &muestra.chars().take(6000).collect::<String>());
        println!("{}", prig_plataforma::json::escribir_linea(&Valor::Mapa(Mapa::new().con("m", m).con("r", rec).con("p", p))));
    }
}
