"""
Contrato de extracción: qué se saca de cada fragmento de libro.

Este archivo es la ÚNICA definición de la forma de los datos, y viaja con el
trabajador a la plataforma que lo ejecute. Prig lo lee al importar el paquete, así
que si cambia aquí cambia en los dos lados a la vez.

Principio de diseño: cada dato extraído lleva su CITA TEXTUAL. Una afirmación cuya
cita no aparece literalmente en el fragmento es una alucinación y se descarta antes
de llegar al paquete. Es una comprobación de subcadena: cuesta nada y elimina la
mayor fuente de basura.
"""

SCHEMA_VERSION = "3.1"

# ---------------------------------------------------------------------------
# Tipos de afirmación
# ---------------------------------------------------------------------------

CLAIM_TYPES = {
    "DEFINITION":  "Qué es algo. La frase que lo define.",
    "FORMULA":     "Expresión matemática con el significado de sus símbolos.",
    "PROCEDURE":   "Pasos para hacer algo, en orden.",
    "EXAMPLE":     "Caso concreto que ilustra un concepto.",
    "CAVEAT":      "Cuándo NO aplica, límites, errores frecuentes.",
    "COMPARISON":  "En qué se diferencian dos cosas.",
    "RESULT":      "Hecho empírico, cifra o conclusión de un experimento.",
    "INTUITION":   "Explicación informal de por qué algo funciona.",
    "NOTATION":    "Convención de notación que el libro introduce.",
}

RELATION_TYPES = {
    "REQUIRES":      "A necesita entender B antes",
    "PART_OF":       "A es parte de B",
    "CONTRASTS_WITH":"A se contrapone a B",
    "CAUSES":        "A produce B",
    "EXAMPLE_OF":    "A es un caso de B",
    "GENERALIZES":   "A generaliza B",
    "EQUIVALENT_TO": "A y B son lo mismo con otro nombre",
}

DIFFICULTY = ["BASICO", "INTERMEDIO", "AVANZADO"]


# ---------------------------------------------------------------------------
# Lo que el modelo devuelve POR FRAGMENTO
# ---------------------------------------------------------------------------

CHUNK_EXTRACTION_SCHEMA = {
    "summary": "str — de qué trata el fragmento, en una o dos frases",
    "difficulty": f"str — uno de {DIFFICULTY}",
    "keywords": "list[str] — términos técnicos que aparecen",
    "concepts": [{
        "name": "str — nombre del concepto tal y como lo llama el libro",
        "aliases": "list[str] — otras formas de nombrarlo en el texto",
        "is_defined_here": "bool — si el fragmento lo define o solo lo menciona",
        "also_known_in": "list[str] — campos donde el concepto se usa con otro nombre",
    }],
    "claims": [{
        "type": f"str — uno de {list(CLAIM_TYPES)}",
        "text": "str — la afirmación redactada de forma autónoma",
        "quote": "str — FRAGMENTO LITERAL del texto que la respalda",
        "concepts": "list[str] — conceptos a los que se refiere",
        "confidence": "float — 0 a 1",
        # Añadidos en v3.1: retrofitarlos costaría repetir toda la extracción
        "code_language": "str — python, cpp, pseudocode, math o none",
        "latex": "str — la expresión en LaTeX si la afirmación es una fórmula",
        "bridges_to": "list[str] — otros campos que esta afirmación conecta",
    }],
    "relations": [{
        "source": "str — nombre del concepto origen",
        "target": "str — nombre del concepto destino",
        "type": f"str — uno de {list(RELATION_TYPES)}",
        "quote": "str — fragmento literal que justifica la relación",
    }],
    "symbols": [{
        "symbol": "str — el símbolo o notación, ej. λ, ∇θ, W",
        "meaning": "str — qué representa",
        "quote": "str — fragmento literal donde se introduce",
    }],
    "figures": [{
        "label": "str — ej. 'Figura 7.3' o 'Tabla 2'",
        "caption": "str — el pie tal como aparece",
        "shows": "str — qué muestra, según el texto que la referencia",
    }],
    "questions": "list[str] — preguntas de comprensión que el fragmento permite responder",
}


# ---------------------------------------------------------------------------
# Prompt del extractor
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres un EXTRACTOR DE CONOCIMIENTO de libros técnicos.

Recibes un fragmento de un libro y devuelves ÚNICAMENTE un objeto JSON válido, sin
markdown ni texto alrededor.

REGLA INVIOLABLE — LA CITA:
Cada afirmación, relación y símbolo lleva un campo "quote" que debe ser una copia
LITERAL Y EXACTA de una parte del fragmento, carácter por carácter. No la reescribas,
no la resumas, no corrijas su ortografía. Si no puedes citar literalmente, NO incluyas
ese elemento. Las citas se comprueban automáticamente contra el texto original y lo
que no cuadre se descarta.

QUÉ EXTRAER (todo lo que el fragmento permita, sin inventar nada):
- summary: de qué trata, en 1-2 frases.
- difficulty: BASICO, INTERMEDIO o AVANZADO.
- keywords: términos técnicos presentes.
- concepts: los conceptos tratados, con los otros nombres que el texto les da.
- claims: hechos concretos, cada uno con su tipo y su cita.
- relations: dependencias entre conceptos que el texto afirme.
- symbols: notación matemática que el fragmento introduzca, con su significado.
- figures: figuras o tablas referenciadas, con su pie.
- questions: preguntas de comprensión que este fragmento permita responder.

TIPOS DE AFIRMACIÓN: %s

TIPOS DE RELACIÓN: %s

CAMPOS TRANSVERSALES (son la clave del sistema):
- code_language: si la afirmación muestra código, di en qué lenguaje (python, cpp);
  si es una expresión matemática pon "math"; si no hay código, "none".
- latex: si la afirmación contiene una fórmula, escríbela también en LaTeX.
- bridges_to: si la afirmación conecta este campo con OTRO de esta lista
  [math, physics, cpp, python, machine_learning, deep_learning], nómbralos.
  Ejemplo: una afirmación sobre la regla de la cadena en un libro de deep learning
  lleva bridges_to ["math"]. Estas conexiones son lo que permite explicar un tema
  apoyándose en lo que el alumno ya sabe de otra disciplina.
- also_known_in: si el concepto se llama distinto en otro campo, indícalo.

Si el fragmento es índice, bibliografía, portada o no tiene contenido técnico,
devuelve listas vacías y un summary que lo diga. Es una respuesta correcta y
preferible a inventar contenido.""" % (
    ", ".join(CLAIM_TYPES), ", ".join(RELATION_TYPES)
)

USER_TEMPLATE = """Libro: {book_title}
Campo del libro: {domain}
Página aproximada: {page}
{section_hint}
--- FRAGMENTO ---
{text}
--- FIN DEL FRAGMENTO ---

Devuelve el JSON con esta forma exacta:
{{
  "summary": "...",
  "difficulty": "INTERMEDIO",
  "keywords": ["..."],
  "concepts": [{{"name": "...", "aliases": ["..."], "is_defined_here": true, "also_known_in": []}}],
  "claims": [{{"type": "DEFINITION", "text": "...", "quote": "cita literal del fragmento", "concepts": ["..."], "confidence": 0.9, "code_language": "none", "latex": "", "bridges_to": []}}],
  "relations": [{{"source": "...", "target": "...", "type": "REQUIRES", "quote": "cita literal"}}],
  "symbols": [{{"symbol": "λ", "meaning": "...", "quote": "cita literal"}}],
  "figures": [{{"label": "Figura 1.2", "caption": "...", "shows": "..."}}],
  "questions": ["..."]
}}"""
