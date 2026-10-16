//! El «mundo» de Typst: un solo archivo fuente (el documento ya escrito en Typst), sin acceso al disco ni a la
//! red, y las fuentes de letra: las que trae Typst (Libertinus, New Computer Modern, DejaVu Sans Mono) y DejaVu
//! Sans del sistema si está (la misma que usaba reportlab). Las fuentes se cargan una vez por proceso.

use std::path::PathBuf;
use std::sync::OnceLock;
use typst::diag::{FileError, FileResult};
use typst::foundations::{Bytes, Datetime, Duration};
use typst::syntax::{FileId, Source};
use typst::text::{Font, FontBook};
use typst::utils::LazyHash;
use typst::{Library, LibraryExt, World};
use typst_layout::PagedDocument;

struct Fuentes {
    libro: LazyHash<FontBook>,
    fuentes: Vec<Font>,
}

static FUENTES: OnceLock<Fuentes> = OnceLock::new();
static BIBLIOTECA: OnceLock<LazyHash<Library>> = OnceLock::new();

/// Carpetas donde se busca DejaVu Sans (las mismas que miraba `kaggle_pdf._registrar_fuentes`)
fn carpetas_sistema() -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = Vec::new();
    if let Ok(c) = std::env::var("PRIG_FUENTES_PDF") {
        if !c.is_empty() {
            v.push(c.into());
        }
    }
    v.extend(["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/local/share/fonts"].map(PathBuf::from));
    if let Some(h) = std::env::var_os("HOME") {
        v.push(PathBuf::from(h).join(".local/share/fonts"));
    }
    v
}

fn fuentes() -> &'static Fuentes {
    FUENTES.get_or_init(|| {
        let mut fuentes: Vec<Font> = typst_assets::fonts().flat_map(|d| Font::iter(Bytes::new(d))).collect();
        let nombres = ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"];
        for carpeta in carpetas_sistema() {
            if nombres.iter().all(|n| carpeta.join(n).is_file()) {
                for n in nombres {
                    if let Ok(datos) = std::fs::read(carpeta.join(n)) {
                        fuentes.extend(Font::iter(Bytes::new(datos)));
                    }
                }
                break;
            }
        }
        let libro = FontBook::from_infos(fuentes.iter().map(|f| f.info().clone()));
        Fuentes { libro: LazyHash::new(libro), fuentes }
    })
}

/// Si DejaVu Sans está disponible (si no, el texto va en Libertinus Serif)
pub fn hay_sans() -> bool {
    fuentes().fuentes.iter().any(|f| f.info().family == "DejaVu Sans")
}

struct Mundo {
    fuente: Source,
}

impl World for Mundo {
    fn library(&self) -> &LazyHash<Library> {
        BIBLIOTECA.get_or_init(|| LazyHash::new(Library::default()))
    }

    fn book(&self) -> &LazyHash<FontBook> {
        &fuentes().libro
    }

    fn main(&self) -> FileId {
        self.fuente.id()
    }

    fn source(&self, id: FileId) -> FileResult<Source> {
        if id == self.fuente.id() {
            Ok(self.fuente.clone())
        } else {
            Err(FileError::AccessDenied)
        }
    }

    fn file(&self, id: FileId) -> FileResult<Bytes> {
        if id == self.fuente.id() {
            Ok(Bytes::from_string(self.fuente.clone()))
        } else {
            Err(FileError::AccessDenied)
        }
    }

    fn font(&self, index: usize) -> Option<Font> {
        fuentes().fuentes.get(index).cloned()
    }

    fn today(&self, _offset: Option<Duration>) -> Option<Datetime> {
        None
    }
}

/// Compila un documento Typst a PDF: los bytes y el número de páginas
pub fn pdf(fuente: &str) -> Result<(Vec<u8>, usize), String> {
    let mundo = Mundo { fuente: Source::detached(fuente) };
    let doc: PagedDocument = typst::compile(&mundo).output.map_err(|errores| {
        errores.iter().map(|e| e.message.to_string()).collect::<Vec<_>>().join("; ")
    })?;
    let bytes = typst_pdf::pdf(&doc, &typst_pdf::PdfOptions::default())
        .map_err(|errores| errores.iter().map(|e| e.message.to_string()).collect::<Vec<_>>().join("; "))?;
    Ok((bytes, doc.pages().len()))
}
