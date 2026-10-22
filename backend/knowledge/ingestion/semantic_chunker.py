"""
Fragmentador semántico: parte un documento en trozos del tamaño que se le pide.

El tamaño del fragmento es el parámetro que más consecuencias tiene aguas abajo. Un
fragmento demasiado grande desborda la ventana del modelo que lo va a leer, o le
obliga a recortarlo en silencio; uno demasiado pequeño corta las derivaciones por la
mitad y produce afirmaciones que no se sostienen solas.

Tres cosas que este módulo hacía mal y que no daban error, solo peores resultados:

  · CONTABA PALABRAS COMO SI FUERAN TOKENS. En castellano una palabra son 1,5-1,8
    tokens, así que pedir 500 devolvía fragmentos de 800 o más.
  · NO PARTÍA UN BLOQUE GRANDE. Si un párrafo (o una página entera, que es lo
    normal cuando el PDF no separa párrafos con línea en blanco) superaba el tope,
    se convertía en un fragmento del tamaño que fuese. Se midieron fragmentos de
    1800 tokens pidiendo 500.
  · ASIGNABA TODOS LOS FRAGMENTOS A LA PRIMERA SECCIÓN DEL LIBRO, sin mirar en qué
    página estaban. El enlace con el índice quedaba inservible, y de ese enlace
    depende poder decir "esto está en el capítulo 4, páginas 181-240".
"""

from typing import Dict, Any, List
from .structure_detector import StructureDetector  # noqa: F401  (se importaba desde aquí)

# Caracteres por token. Es la misma cifra que usa el resto de Prig para presupuestar
# contexto; mantenerla igual en todas partes es lo que hace que los presupuestos
# cuadren de un extremo a otro.
CARACTERES_POR_TOKEN = 3.6

# Por debajo de esto un bloque no es un párrafo, es un número de página suelto o un
# encabezado: procesarlo gasta y no produce conocimiento.
MINIMO_BLOQUE = 20


def _rs():
    from nativo_rust import rust
    return rust().troceado


def tokens_de(texto: str) -> int:
    return _rs().tokens_de(texto)


class SemanticChunker:
    """ Fragmentador semántico que atomiza un documento en trozos enlazados.

    Párrafos, cortes, ubicación y clasificación están en Rust (backend-rust/crates/prig-biblioteca, troceado.rs),
    con el mismo resultado; los fragmentos se clasifican en paralelo. """

    @classmethod
    def chunk_document(cls, parsed_doc: Dict[str, Any], structure: Dict[str, Any],
                       source_id: str, max_chunk_tokens: int = 500
                       ) -> List[Dict[str, Any]]:
        paginas = [(p.get("page_num", 1), p.get("text") or "") for p in parsed_doc.get("pages", [])]
        secciones = [(s["_es_seccion"], s.get("start_page") or 0, s.get("end_page") or 10 ** 9,
                      s.get("section_id"), s.get("chapter_id"))
                     for s in cls._ordenar_secciones(structure)]
        return _rs().fragmentar(paginas, secciones, source_id, max_chunk_tokens)

    # ------------------------------------------------------------------

    @staticmethod
    def _parrafos(texto: str) -> List[str]:
        """ Separa en párrafos tolerando que el PDF no use líneas en blanco (sangría y mayúsculas tras punto) """
        return _rs().parrafos(texto or "")

    @staticmethod
    def _partir(texto: str, tope: int) -> List[str]:
        """ Parte un bloque que no cabe, por frases (por palabras si una frase sola no cabe) """
        return _rs().partir(texto, tope)

    # ------------------------------------------------------------------

    @staticmethod
    def _ordenar_secciones(structure: Dict[str, Any]) -> List[Dict[str, Any]]:
        """ Secciones y capítulos con página, ordenados para poder buscar por página.

        Las secciones van antes que los capítulos porque son más específicas: si un
        fragmento cae dentro de las dos, la sección dice más.
        """
        secciones = [s for s in (structure.get("sections") or []) if s.get("start_page")]
        capitulos = [c for c in (structure.get("chapters") or []) if c.get("start_page")]
        for s in secciones:
            s["_es_seccion"] = True
        for c in capitulos:
            c["_es_seccion"] = False
        todas = secciones + capitulos
        todas.sort(key=lambda x: (not x["_es_seccion"], x.get("start_page") or 0))
        return todas
