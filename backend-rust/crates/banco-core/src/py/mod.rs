//! Lo que el banco necesita de Python, con la semántica exacta de CPython 3.12 (cadenas, rutas, números,
//! JSON y conjuntos de enteros). Ver Prig/docs/plan-banco-rust.md, sección 5 («Trampas de traducción»).

pub mod cadena;
pub mod conjunto;
pub mod difflib;
pub mod json;
pub mod numero;
pub mod ruta;
