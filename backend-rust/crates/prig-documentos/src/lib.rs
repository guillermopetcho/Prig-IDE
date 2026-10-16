//! Documentos PDF de Prig con Typst como biblioteca (F5 de docs/plan-prig-rust.md), en lugar de reportlab y
//! pygments: exportar el código de una carpeta, un notebook o una colección de Kaggle explicados y un repositorio de
//! GitHub explicado. Quien llama describe el documento como una lista de bloques (`bloques`); el texto nunca se
//! interpreta como Typst (`marcado`); `mundo` compila sin tocar el disco ni la red.

pub mod bloques;
pub mod marcado;
pub mod mundo;

/// Un documento (JSON de `bloques::Documento`) a PDF: los bytes y las páginas
pub fn pdf_de_json(json: &str) -> Result<(Vec<u8>, usize), String> {
    let doc: bloques::Documento = serde_json::from_str(json).map_err(|e| format!("documento mal formado: {e}"))?;
    mundo::pdf(&bloques::a_typst(&doc))
}
