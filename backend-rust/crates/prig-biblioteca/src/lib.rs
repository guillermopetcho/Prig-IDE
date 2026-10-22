//! La biblioteca, el conocimiento y los PDF (F5 de docs/plan-prig-rust.md): `pdf` (leer libros con PDFium).

pub mod base_kb;
pub mod conocimiento;
pub mod dominios;
pub mod contexto_kb;
pub mod estante;
pub mod paquetes;
pub mod perfil;
pub mod indices;
pub mod pdf;
pub mod referencias;
pub mod referencias_ml;
pub mod sondeo;
pub mod trabajos;
pub mod troceado;
pub mod vectores;

pub use prig_recursos::{json, valor};

/// `str.strip()` de Python, con dueño
pub(crate) fn base_kb_strip(t: &str) -> String {
    prig_plataforma::py::strip(t).to_string()
}
