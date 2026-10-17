//! El trabajo de extracción para la GPU externa (`job_exporter.py`): trocear los libros en local y dejar una carpeta
//! lista para subir (`manifest.json`, `chunks.jsonl` y `outline.json`), con cada libro que no se pudo leer anotado sin
//! tumbar el lote; los libros que se pueden mandar y los trabajos ya preparados.

use std::collections::HashMap;
use std::io::Write;
use std::path::Path;

use prig_plataforma::py;
use prig_recursos::valor::{redondear, Mapa, Valor};

use crate::conocimiento::{estructura, leer_documento, secciones_para_trocear, sha256_de};
use crate::{dominios, troceado};

fn ev(pares: Vec<(&str, Valor)>) -> Mapa {
    let mut m = Mapa::new();
    for (k, v) in pares {
        m.poner(k, v);
    }
    m
}

fn t(s: &str) -> Valor {
    Valor::Texto(s.to_string())
}

/// `JobExporter.preparar`: `libros` son `{path, domain, ajustes}`; `avisar` recibe el progreso
pub fn preparar(libros: &[Mapa], destino: &str, max_tokens: i64, min_chars: usize, pdf_listo: bool, avisar: &mut dyn FnMut(Mapa)) -> Result<Mapa, String> {
    let job_id = format!("job_{}", &uuid::Uuid::new_v4().simple().to_string()[..10]);
    let destino = py::abspath(&py::expanduser(destino));
    std::fs::create_dir_all(&destino).map_err(|e| py::error_os(&e, &destino))?;
    let ruta_chunks = py::join(&destino, "chunks.jsonl");
    let mut salida = std::fs::File::create(&ruta_chunks).map_err(|e| py::error_os(&e, &ruta_chunks))?;
    let (mut libros_ok, mut outlines) = (Vec::new(), Mapa::new());
    let (mut total, mut descartados) = (0i64, 0i64);
    let mut vistos: HashMap<String, String> = HashMap::new();
    let (mut repetidos, mut fallidos): (Vec<Valor>, Vec<Valor>) = (Vec::new(), Vec::new());
    for (numero, item) in libros.iter().enumerate() {
        let ruta = item.get("path").filter(|v| v.verdad()).or_else(|| item.get("ruta")).map(Valor::texto_py).unwrap_or_else(|| "None".into());
        let dominio_pedido = item.get("domain").filter(|v| v.verdad()).or_else(|| item.get("dominio")).filter(|v| v.verdad()).map(Valor::texto_py);
        let ajustes = item.mapa("ajustes").cloned().unwrap_or_default();
        let tope = ajustes.get("max_chunk_tokens").filter(|v| v.verdad()).and_then(Valor::num).map(|n| n as i64).unwrap_or(max_tokens);
        let nombre = py::basename(&ruta);
        avisar(ev(vec![("tipo", t("libro")), ("n", Valor::Entero(numero as i128 + 1)), ("total", Valor::Entero(libros.len() as i128)), ("nombre", t(&nombre))]));
        let abs = py::abspath(&py::expanduser(&ruta));
        if !Path::new(&abs).is_file() {
            fallidos.push(Valor::Mapa(Mapa::new().con("ruta", ruta.as_str()).con("motivo", "no existe")));
            avisar(ev(vec![("tipo", t("fallo")), ("nombre", t(&nombre)), ("motivo", t("no existe"))]));
            continue;
        }
        let doc = match leer_documento(&abs, pdf_listo) {
            Ok(d) => d,
            Err(e) => {
                fallidos.push(Valor::Mapa(Mapa::new().con("ruta", ruta.as_str()).con("motivo", format!("no se pudo leer: {e}"))));
                avisar(ev(vec![("tipo", t("fallo")), ("nombre", t(&nombre)), ("motivo", t(&e.chars().take(160).collect::<String>()))]));
                continue;
            }
        };
        let paginas = doc.paginas.len();
        let con_texto = doc.paginas.iter().filter(|(_, x)| x.chars().count() > 120).count();
        if paginas > 5 && (con_texto as f64) < paginas as f64 * 0.3 {
            fallidos.push(Valor::Mapa(Mapa::new().con("ruta", ruta.as_str()).con("motivo", "parece escaneado: casi no tiene texto extraíble. Necesita OCR.")));
            avisar(ev(vec![("tipo", t("fallo")), ("nombre", t(&nombre)), ("motivo", t("parece escaneado, necesita OCR"))]));
            continue;
        }
        let dominio = match dominio_pedido.filter(|d| dominios::es_dominio(d)) {
            Some(d) => d,
            None => {
                let muestra = doc.paginas.iter().take(4).map(|(_, x)| x.as_str()).collect::<Vec<_>>().join(" ");
                dominios::sugerir(&muestra, &doc.nombre)
            }
        };
        let sid = format!("book_{}", &doc.sha256[..16]);
        if let Some(antes) = vistos.get(&sid) {
            repetidos.push(t(&py::basename(&abs)));
            avisar(ev(vec![("tipo", t("repetido")), ("nombre", t(&py::basename(&abs))), ("ya_como", t(&py::basename(antes)))]));
            continue;
        }
        vistos.insert(sid.clone(), abs.clone());
        let e = estructura(&doc, &sid);
        let frags = troceado::fragmentar(&doc.paginas, &secciones_para_trocear(&e), tope);
        let mut escritos = 0i64;
        for f in &frags {
            let texto = py::strip(&f.texto).to_string();
            if texto.chars().count() < min_chars {
                descartados += 1;
                continue;
            }
            let fila = Mapa::new()
                .con("chunk_id", format!("chk_{sid}_{:04}", f.numero))
                .con("source_id", sid.as_str())
                .con("book_title", doc.nombre.as_str())
                .con("domain", dominio.as_str())
                .con("page", f.pagina_inicio)
                .con("page_end", f.pagina_fin)
                .con("content_type", f.clase.tipo)
                .con("section_id", f.section_id.clone().map(Valor::Texto).unwrap_or(Valor::Nulo))
                .con("chapter_id", f.chapter_id.clone().map(Valor::Texto).unwrap_or(Valor::Nulo))
                .con("text", texto);
            writeln!(salida, "{}", prig_plataforma::json::escribir_linea(&Valor::Mapa(fila))).map_err(|e| e.to_string())?;
            escritos += 1;
        }
        let caps = e.capitulos_json(&sid);
        libros_ok.push(Valor::Mapa(
            Mapa::new()
                .con("source_id", sid.as_str())
                .con("title", doc.nombre.as_str())
                .con("domain", dominio.as_str())
                .con("sha256", doc.sha256.as_str())
                .con("pages", paginas as i64)
                .con("file_size", doc.tamano as i64)
                .con("chunks", escritos)
                .con("max_chunk_tokens", tope)
                .con("indice", e.origen.unwrap_or("heuristica_texto"))
                .con("capitulos", caps.len() as i64),
        ));
        outlines.poner(sid.clone(), Mapa::new().con("chapters", Valor::Lista(caps.clone())).con("sections", Valor::Lista(e.secciones_json(&sid))));
        total += escritos;
        avisar(ev(vec![
            ("tipo", t("listo")),
            ("nombre", t(&doc.nombre)),
            ("dominio", t(&dominio)),
            ("fragmentos", Valor::Entero(escritos as i128)),
            ("paginas", Valor::Entero(paginas as i128)),
            ("capitulos", Valor::Entero(caps.len() as i128)),
        ]));
    }
    drop(salida);
    std::fs::write(py::join(&destino, "outline.json"), prig_plataforma::json::escribir(&Valor::Mapa(outlines), 2)).map_err(|e| e.to_string())?;
    let mut doms: Vec<String> = libros_ok.iter().filter_map(|b| if let Valor::Mapa(b) = b { Some(b.valor("domain").texto_py()) } else { None }).collect();
    doms.sort();
    doms.dedup();
    let n_libros = libros_ok.len() as i64;
    let manifest = Mapa::new()
        .con("job_id", job_id)
        .con("schema_version", "3.1")
        .con("created_at", py::ahora_iso())
        .con("books", Valor::Lista(libros_ok))
        .con("total_books", n_libros)
        .con("total_chunks", total)
        .con("domains", Valor::Lista(doms.into_iter().map(Valor::Texto).collect()))
        .con("discarded_short_chunks", descartados)
        .con("duplicates_skipped", Valor::Lista(repetidos))
        .con("failed", Valor::Lista(fallidos))
        .con("max_chunk_tokens", max_tokens)
        .con("chunks_sha256", sha256_de(&ruta_chunks).map_err(|e| e.to_string())?);
    std::fs::write(py::join(&destino, "manifest.json"), prig_plataforma::json::escribir(&Valor::Mapa(manifest.clone()), 2)).map_err(|e| e.to_string())?;
    let mb = std::fs::metadata(&ruta_chunks).map(|m| m.len()).unwrap_or(0) as f64 / (1024.0 * 1024.0);
    Ok(manifest.con("output_dir", destino.as_str()).con("estimated_mb", redondear(mb, 2)))
}

/// `libros_disponibles`: PDF y documentos de la biblioteca que se pueden mandar a extraer
pub fn libros_disponibles(raiz: &str) -> Vec<Mapa> {
    let mut salida = Vec::new();
    recorrer(Path::new(raiz), &mut salida);
    salida
}

fn recorrer(dir: &Path, salida: &mut Vec<Mapa>) {
    let Ok(l) = std::fs::read_dir(dir) else { return };
    let (mut dirs, mut archivos) = (Vec::new(), Vec::new());
    for e in l.flatten() {
        let n = e.file_name().to_string_lossy().to_string();
        if std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false) {
            if n != ".index" && n != "metadata" && !n.starts_with('.') {
                dirs.push((n, e.file_type().map(|t| t.is_symlink()).unwrap_or(false)));
            }
        } else {
            archivos.push(n);
        }
    }
    archivos.sort();
    for n in archivos {
        let ext = py::splitext(&n).1.to_lowercase();
        if ![".pdf", ".md", ".txt", ".rst"].contains(&ext.as_str()) {
            continue;
        }
        let ruta = py::join(&dir.to_string_lossy(), &n);
        let mb = std::fs::metadata(&ruta).map(|m| m.len()).unwrap_or(0) as f64 / (1024.0 * 1024.0);
        salida.push(Mapa::new().con("path", ruta).con("name", n).con("size_mb", redondear(mb, 2)));
    }
    for (d, enlace) in dirs {
        if !enlace {
            recorrer(&dir.join(d), salida);
        }
    }
}

/// `job_list`: los trabajos ya preparados (los más recientes primero)
pub fn listar(dir: &str) -> Vec<Valor> {
    let _ = std::fs::create_dir_all(dir);
    let mut nombres: Vec<String> = std::fs::read_dir(dir).map(|l| l.flatten().map(|e| e.file_name().to_string_lossy().to_string()).collect()).unwrap_or_default();
    nombres.sort();
    nombres.reverse();
    let mut salida = Vec::new();
    for n in nombres {
        let ruta = py::join(dir, &n);
        let man = py::join(&ruta, "manifest.json");
        if !Path::new(&man).is_file() {
            continue;
        }
        let Some(Valor::Mapa(m)) = std::fs::read_to_string(&man).ok().and_then(|t| prig_plataforma::json::leer(&t).ok()) else { continue };
        let bytes: u64 = std::fs::read_dir(&ruta).map(|l| l.flatten().filter_map(|e| std::fs::metadata(e.path()).ok()).map(|m| m.len()).sum()).unwrap_or(0);
        let g = |k: &str| m.get(k).cloned().unwrap_or(Valor::Nulo);
        salida.push(Valor::Mapa(
            Mapa::new()
                .con("nombre", n.as_str())
                .con("ruta", ruta.as_str())
                .con("job_id", g("job_id"))
                .con("creado", g("created_at"))
                .con("libros", g("total_books"))
                .con("fragmentos", g("total_chunks"))
                .con("dominios", m.get("domains").cloned().unwrap_or(Valor::Lista(vec![])))
                .con("mb", redondear(bytes as f64 / (1024.0 * 1024.0), 2)),
        ));
    }
    salida
}

#[cfg(test)]
mod pruebas {
    //! Las de `PruebaPreparacionDelTrabajo` (`test_kaggle_chain.py`)

    use super::*;

    fn libro(dir: &Path, nombre: &str, texto: &str) -> String {
        std::fs::create_dir_all(dir).unwrap();
        let r = dir.join(nombre);
        std::fs::write(&r, texto).unwrap();
        r.to_string_lossy().to_string()
    }

    fn item(r: &str) -> Mapa {
        Mapa::new().con("path", r)
    }

    #[test]
    fn la_virgulilla_y_los_repetidos() {
        let casa = py::expanduser("~");
        let tmp = Path::new(&casa).join(".prig_pruebas").join(format!("trabajos-{}", std::process::id()));
        // «~/x.md» se lee igual que la ruta absoluta
        let r = libro(&tmp, "libro.md", &"Contenido de prueba. ".repeat(40));
        let tilde = format!("~{}", &r[casa.len()..]);
        let destino = format!("~{}", &tmp.join("job").to_string_lossy()[casa.len()..]);
        let m = preparar(&[item(&tilde)], &destino, 500, 120, false, &mut |_| {}).unwrap();
        assert_eq!(m.num_o("total_books", 0.0), 1.0, "una ruta con ~ debe leerse igual que la absoluta");
        // el mismo libro en dos carpetas se procesa una vez
        let texto = "Un texto identico guardado en dos carpetas. ".repeat(40);
        let a = libro(&tmp.join("a"), "libro.md", &texto);
        let b = libro(&tmp.join("documentation"), "libro.md", &texto);
        let m = preparar(&[item(&a), item(&b)], &tmp.join("job2").to_string_lossy(), 500, 120, false, &mut |_| {}).unwrap();
        assert_eq!(m.num_o("total_books", 0.0), 1.0);
        assert_eq!(m.lista("duplicates_skipped").unwrap().len(), 1);
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
