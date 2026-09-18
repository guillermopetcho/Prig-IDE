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

import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from .structure_detector import StructureDetector

# Caracteres por token. Es la misma cifra que usa el resto de Prig para presupuestar
# contexto; mantenerla igual en todas partes es lo que hace que los presupuestos
# cuadren de un extremo a otro.
CARACTERES_POR_TOKEN = 3.6

# Por debajo de esto un bloque no es un párrafo, es un número de página suelto o un
# encabezado: procesarlo gasta y no produce conocimiento.
MINIMO_BLOQUE = 20


def tokens_de(texto: str) -> int:
    return int(len(texto) / CARACTERES_POR_TOKEN) + 1


class SemanticChunker:
    """ Fragmentador semántico que atomiza un documento en trozos enlazados """

    @classmethod
    def chunk_document(cls, parsed_doc: Dict[str, Any], structure: Dict[str, Any],
                       source_id: str, max_chunk_tokens: int = 500
                       ) -> List[Dict[str, Any]]:
        bloques = cls._bloques(parsed_doc.get("pages", []), max_chunk_tokens)
        if not bloques:
            return []

        secciones = cls._ordenar_secciones(structure)
        fragmentos: List[Dict[str, Any]] = []

        actual: List[str] = []
        tokens_actual = 0
        pagina_inicio = bloques[0]["page"]
        pagina_fin = bloques[0]["page"]

        for bloque in bloques:
            t = bloque["tokens"]
            if actual and tokens_actual + t > max_chunk_tokens:
                fragmentos.append(cls._crear(
                    "\n\n".join(actual), source_id, len(fragmentos) + 1,
                    pagina_inicio, pagina_fin, secciones))
                actual, tokens_actual = [], 0
                pagina_inicio = bloque["page"]
            actual.append(bloque["text"])
            tokens_actual += t
            pagina_fin = bloque["page"]

        if actual:
            fragmentos.append(cls._crear(
                "\n\n".join(actual), source_id, len(fragmentos) + 1,
                pagina_inicio, pagina_fin, secciones))

        # Enlaces adyacentes: permiten recuperar el fragmento de al lado cuando una
        # afirmación depende de lo que venía justo antes.
        for i, f in enumerate(fragmentos):
            if i:
                f["previous_chunk_id"] = fragmentos[i - 1]["chunk_id"]
            if i < len(fragmentos) - 1:
                f["next_chunk_id"] = fragmentos[i + 1]["chunk_id"]
        return fragmentos

    # ------------------------------------------------------------------

    @classmethod
    def _bloques(cls, paginas: List[Dict[str, Any]], tope: int) -> List[Dict[str, Any]]:
        """ Párrafos de todas las páginas, ya partidos si eran demasiado largos """
        salida: List[Dict[str, Any]] = []
        for p in paginas:
            numero = p.get("page_num", 1)
            for parrafo in cls._parrafos(p.get("text") or ""):
                for trozo in cls._partir(parrafo, tope):
                    salida.append({"page": numero, "text": trozo,
                                   "tokens": tokens_de(trozo)})
        return salida

    @staticmethod
    def _parrafos(texto: str) -> List[str]:
        """ Separa en párrafos tolerando que el PDF no use líneas en blanco.

        Muchos PDF devuelven el texto con un salto de línea por renglón y ninguno
        en blanco entre párrafos: partir solo por '\\n\\n' dejaba la página entera
        como un único bloque. Cuando no hay líneas en blanco se recurre a la
        sangría y a las mayúsculas tras punto final.
        """
        texto = (texto or "").replace("\r\n", "\n")
        partes = [p.strip() for p in texto.split("\n\n")]
        partes = [p for p in partes if len(p) > MINIMO_BLOQUE]
        if partes:
            return partes

        lineas = [l for l in texto.split("\n") if l.strip()]
        if not lineas:
            return []
        parrafos, actual = [], []
        for linea in lineas:
            nuevo = bool(re.match(r"\s{2,}\S", linea)) or (
                actual and actual[-1].rstrip().endswith((".", ":", "?", "!"))
                and re.match(r"\s*[A-ZÁÉÍÓÚÑ0-9]", linea))
            if nuevo and actual:
                parrafos.append(" ".join(actual))
                actual = []
            actual.append(linea.strip())
        if actual:
            parrafos.append(" ".join(actual))
        return [p for p in parrafos if len(p) > MINIMO_BLOQUE]

    @staticmethod
    def _partir(texto: str, tope: int) -> List[str]:
        """ Parte un bloque que no cabe, por frases y sin dejar cabos sueltos.

        Se corta por final de frase siempre que se pueda: cortar a mitad de una
        derivación produce una afirmación que no se puede verificar contra el texto
        porque le falta la mitad.
        """
        if tokens_de(texto) <= tope:
            return [texto]

        limite = int(tope * CARACTERES_POR_TOKEN)
        frases = re.split(r"(?<=[.!?:])\s+", texto)
        trozos, actual = [], ""
        for frase in frases:
            if len(frase) > limite:
                # Una sola frase enorme (una tabla, una fórmula larga): se parte
                # por palabras, que es lo menos malo que queda.
                if actual:
                    trozos.append(actual.strip())
                    actual = ""
                palabras, linea = frase.split(), ""
                for w in palabras:
                    if len(linea) + len(w) + 1 > limite:
                        trozos.append(linea.strip())
                        linea = ""
                    linea += w + " "
                if linea.strip():
                    actual = linea
                continue
            if actual and len(actual) + len(frase) + 1 > limite:
                trozos.append(actual.strip())
                actual = ""
            actual += frase + " "
        if actual.strip():
            trozos.append(actual.strip())
        return [t for t in trozos if len(t) > MINIMO_BLOQUE]

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

    @staticmethod
    def _ubicar(pagina: int, secciones: List[Dict[str, Any]]) -> tuple:
        """ En qué sección y capítulo cae una página """
        sec_id = chp_id = None
        for s in secciones:
            inicio = s.get("start_page") or 0
            fin = s.get("end_page") or 10 ** 9
            if inicio <= pagina <= fin:
                if s["_es_seccion"] and sec_id is None:
                    sec_id = s.get("section_id")
                    chp_id = chp_id or s.get("chapter_id")
                elif not s["_es_seccion"] and chp_id is None:
                    chp_id = s.get("chapter_id")
            if sec_id and chp_id:
                break
        return sec_id, chp_id

    @classmethod
    def _crear(cls, texto: str, source_id: str, numero: int,
               pagina_inicio: int, pagina_fin: int,
               secciones: List[Dict[str, Any]]) -> Dict[str, Any]:
        detectado = StructureDetector.detect_structure(texto)
        sec_id, chp_id = cls._ubicar(pagina_inicio, secciones)
        return {
            "chunk_id": f"chk_{source_id}_{numero:04d}",
            "source_id": source_id,
            "section_id": sec_id,
            "chapter_id": chp_id,
            "content": texto,
            "content_type": detectado["content_type"],
            "token_count": tokens_de(texto),
            "previous_chunk_id": None,
            "next_chunk_id": None,
            "contains_equation": detectado["contains_equation"],
            "contains_code": detectado["contains_code"],
            "topics": [],
            "concepts": [],
            "symbols": detectado["symbols"],
            "page_start": pagina_inicio,
            "page_end": pagina_fin,
            "created_at": datetime.now().isoformat(),
        }
