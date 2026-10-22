//! Un documento con todos los bloques y texto hostil (Typst, HTML, emoji, Markdown roto) compila a un PDF válido.

#[test]
fn todos_los_bloques() {
    let hostil = "#import \"x.typ\": * ] [ #panic(\"boom\") $x$ // no es comentario /* ni esto */ @ref <etiqueta> \\ ` 😀 \u{0}";
    let md = format!(
        "# Título {hostil}\n\nTexto **negrita** _cursiva_ `codigo {hostil}` [enlace](https://ejemplo.org) [raro](javascript:alert(1))\n\n\
         - uno\n  - dos\n1. tres\n\n> cita\n\n| a | b |\n|---|---|\n| {hostil} | 2 |\n\n```python\nprint(\"{hostil}\")\n```\n\n\
         <center>centrado</center> <img src=x alt=\"gato\"> <br> &amp; ```\nsin cerrar"
    );
    let doc = serde_json::json!({
        "titulo": hostil, "asunto": "prueba", "estilo": "notebook", "pie": true,
        "bloques": [
            {"tipo": "portada", "etiqueta": "NOTEBOOK", "titulo": hostil, "lineas": ["de **ana**", "[https://x.org](https://x.org)"], "fecha": "Generado"},
            {"tipo": "salto"},
            {"tipo": "seccion", "texto": hostil},
            {"tipo": "celda", "texto": "CELDA 1 · CÓDIGO"},
            {"tipo": "codigo", "texto": format!("def f():\n\treturn 1  # {hostil}"), "lenguaje": "python"},
            {"tipo": "codigo", "texto": (0..50).map(|i| format!("línea {i}")).collect::<Vec<_>>().join("\n"), "salida": true, "max_lineas": 30},
            {"tipo": "markdown", "texto": md},
            {"tipo": "profesor", "etiqueta": "PROFESOR · NIVEL ALTO", "texto": md},
            {"tipo": "nota", "texto": hostil},
            {"tipo": "alumno", "texto": format!("Tú: {hostil}")},
            {"tipo": "espacio", "alto": 6.0},
            {"tipo": "raya"},
            {"tipo": "banner", "texto": hostil},
            {"tipo": "titulo", "texto": "Exportación", "sub": hostil},
            {"tipo": "codigo", "texto": "x".repeat(3000), "lenguaje": "lenguaje-que-no-existe"},
        ]
    });
    let (pdf, paginas) = prig_documentos::pdf_de_json(&doc.to_string()).expect("compila");
    assert!(pdf.starts_with(b"%PDF"));
    assert!(paginas >= 3, "{paginas} páginas");
    std::fs::write(std::env::temp_dir().join("prig-documentos-prueba.pdf"), &pdf).unwrap();
}

#[test]
fn documento_mal_formado() {
    assert!(prig_documentos::pdf_de_json("{\"titulo\": 1}").is_err());
}
