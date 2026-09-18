"""
Pruebas del troceado y de la preparación del trabajo.

Todo lo que se protege aquí venía de fallos reales que no daban error, solo
resultados peores:

  · el troceador contaba PALABRAS como si fueran tokens, y nunca partía un bloque
    demasiado grande: pidiendo 500 devolvía fragmentos de hasta 1800;
  · asignaba TODOS los fragmentos a la primera sección del libro, sin mirar la
    página, dejando inservible el enlace con el índice;
  · el extractor de índice solo buscaba "Capítulo N" en el texto e ignoraba los
    marcadores del PDF: en un libro con 172 marcadores detectaba un capítulo;
  · preparar un libro del Escritorio respondía «Ruta no permitida», porque el
    explorador navega la carpeta personal y el preparador solo aceptaba el espacio
    de trabajo.
"""

import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge.ingestion.semantic_chunker import SemanticChunker, tokens_de
from knowledge.ingestion.toc_extractor import TOCExtractor


def doc(paginas, outline=None):
    return {"pages": [{"page_num": i + 1, "text": t} for i, t in enumerate(paginas)],
            "total_pages": len(paginas), "outline": outline or []}


PARRAFO = ("La regularizacion penaliza la norma de los pesos para limitar su "
           "magnitud durante el entrenamiento del modelo. ")


class PruebaTopeDeFragmento(unittest.TestCase):
    """ El tope es el parámetro con más consecuencias aguas abajo: si no se
    respeta, el modelo que lo lea recorta el fragmento sin avisar. """

    def trocear(self, texto, tope=500, paginas=None):
        return SemanticChunker.chunk_document(
            doc(paginas or [texto]), {}, "bk", max_chunk_tokens=tope)

    def test_ningun_fragmento_se_pasa_del_tope(self):
        for tope in (200, 350, 500, 800):
            fragmentos = self.trocear(PARRAFO * 400, tope)
            self.assertTrue(fragmentos)
            excedidos = [f for f in fragmentos if f["token_count"] > tope]
            self.assertEqual(excedidos, [],
                             f"{len(excedidos)} fragmentos superan el tope de {tope}")

    def test_parte_un_parrafo_enorme(self):
        """ Antes un bloque grande se convertía en un fragmento del tamaño que
        fuese: no había ninguna partición. """
        fragmentos = self.trocear(PARRAFO * 200, 300)
        self.assertGreater(len(fragmentos), 5)
        self.assertLessEqual(max(f["token_count"] for f in fragmentos), 300)

    def test_parte_por_final_de_frase(self):
        """ Cortar a mitad de una derivación da afirmaciones que no se pueden
        verificar contra el texto porque les falta la mitad. """
        fragmentos = self.trocear(PARRAFO * 60, 200)
        interiores = fragmentos[:-1]
        terminan_bien = sum(1 for f in interiores
                            if f["content"].rstrip().endswith((".", ":", "?", "!")))
        self.assertGreaterEqual(terminan_bien, len(interiores) * 0.8,
                                "la mayoría de los cortes deben caer en final de frase")

    def test_una_frase_sin_puntuacion_tambien_se_parte(self):
        fragmentos = self.trocear("palabra " * 3000, 250)
        self.assertLessEqual(max(f["token_count"] for f in fragmentos), 250)

    def test_cuenta_tokens_no_palabras(self):
        """ En castellano una palabra son 1,5-1,8 tokens. """
        texto = "a" * 3600
        self.assertGreaterEqual(tokens_de(texto), 900)

    def test_no_pierde_texto_al_trocear(self):
        original = PARRAFO * 80
        junto = " ".join(f["content"] for f in self.trocear(original, 300))
        # Se comparan las palabras: el troceado reagrupa espacios y saltos
        self.assertEqual(len(junto.split()), len(original.split()))

    def test_un_documento_vacio_no_da_fragmentos(self):
        self.assertEqual(self.trocear("", 500), [])

    def test_enlaza_los_fragmentos_entre_si(self):
        f = self.trocear(PARRAFO * 100, 250)
        self.assertIsNone(f[0]["previous_chunk_id"])
        self.assertEqual(f[0]["next_chunk_id"], f[1]["chunk_id"])
        self.assertIsNone(f[-1]["next_chunk_id"])


class PruebaParrafosSinLineasEnBlanco(unittest.TestCase):
    """ Muchos PDF devuelven un salto de línea por renglón y ninguno en blanco
    entre párrafos: partir solo por '\\n\\n' dejaba la página entera como un bloque. """

    def test_detecta_parrafos_por_mayuscula_tras_punto(self):
        pagina = ("Primera frase del primer parrafo que es bastante larga.\n"
                  "Segunda frase que continua el mismo parrafo sin cortar.\n"
                  "Otro parrafo distinto empieza aqui con mayuscula despues de punto.\n"
                  "Y sigue con su segunda linea correspondiente del mismo bloque.")
        fragmentos = SemanticChunker.chunk_document(doc([pagina]), {}, "bk",
                                                    max_chunk_tokens=40)
        self.assertGreater(len(fragmentos), 1,
                           "una página sin líneas en blanco debe partirse igual")

    def test_descarta_los_bloques_minusculos(self):
        """ Un número de página suelto no es un párrafo. """
        fragmentos = SemanticChunker.chunk_document(doc(["12"]), {}, "bk")
        self.assertEqual(fragmentos, [])


class PruebaUbicacionEnElIndice(unittest.TestCase):
    """ De este enlace depende poder decir «esto está en el capítulo 4, p.181-240». """

    ESTRUCTURA = {
        "chapters": [
            {"chapter_id": "c1", "start_page": 1, "end_page": 10, "title": "Uno"},
            {"chapter_id": "c2", "start_page": 11, "end_page": 30, "title": "Dos"},
        ],
        "sections": [
            {"section_id": "s1", "chapter_id": "c1", "start_page": 1, "end_page": 5},
            {"section_id": "s2", "chapter_id": "c2", "start_page": 11, "end_page": 20},
        ],
    }

    def test_cada_fragmento_va_a_la_seccion_de_su_pagina(self):
        paginas = [PARRAFO * 4] * 25
        fragmentos = SemanticChunker.chunk_document(
            doc(paginas), self.ESTRUCTURA, "bk", max_chunk_tokens=200)
        del_principio = [f for f in fragmentos if f["page_start"] <= 5]
        del_medio = [f for f in fragmentos if 11 <= f["page_start"] <= 20]
        self.assertTrue(all(f["section_id"] == "s1" for f in del_principio))
        self.assertTrue(all(f["section_id"] == "s2" for f in del_medio))

    def test_reparte_entre_varias_secciones(self):
        """ Antes TODOS iban a sections[0], hubiera las que hubiera. """
        fragmentos = SemanticChunker.chunk_document(
            doc([PARRAFO * 4] * 25), self.ESTRUCTURA, "bk", max_chunk_tokens=200)
        distintas = {f["section_id"] for f in fragmentos if f["section_id"]}
        self.assertGreaterEqual(len(distintas), 2)

    def test_una_pagina_fuera_de_toda_seccion_no_inventa_una(self):
        fragmentos = SemanticChunker.chunk_document(
            doc([""] * 40 + [PARRAFO * 4]), self.ESTRUCTURA, "bk", max_chunk_tokens=200)
        self.assertTrue(fragmentos)
        self.assertIsNone(fragmentos[-1]["section_id"])

    def test_sin_estructura_no_falla(self):
        self.assertTrue(SemanticChunker.chunk_document(doc([PARRAFO * 10]), {}, "bk"))


class PruebaIndiceDesdeMarcadores(unittest.TestCase):
    """ Los marcadores del PDF son el índice de verdad cuando existen. """

    MARCADORES = [
        {"title": "Introducción", "level": 0, "page": 1},
        {"title": "Qué es esto", "level": 1, "page": 2},
        {"title": "Regularización", "level": 0, "page": 20},
        {"title": "Norma L2", "level": 1, "page": 22},
        {"title": "Dropout", "level": 1, "page": 28},
        {"title": "Optimización", "level": 0, "page": 40},
    ]

    def test_construye_capitulos_y_secciones(self):
        e = TOCExtractor.extract_structure(doc([""] * 60, self.MARCADORES), "bk")
        self.assertEqual(e["origen"], "marcadores_pdf")
        self.assertEqual(len(e["chapters"]), 3)
        self.assertEqual(len(e["sections"]), 3)

    def test_calcula_la_pagina_de_fin(self):
        """ Sin página de fin no se puede decir «lee de la 20 a la 39». """
        e = TOCExtractor.extract_structure(doc([""] * 60, self.MARCADORES), "bk")
        reg = next(c for c in e["chapters"] if c["title"] == "Regularización")
        self.assertEqual((reg["start_page"], reg["end_page"]), (20, 39))

    def test_la_ultima_llega_al_final_del_libro(self):
        e = TOCExtractor.extract_structure(doc([""] * 60, self.MARCADORES), "bk")
        self.assertEqual(e["chapters"][-1]["end_page"], 60)

    def test_las_secciones_cuelgan_de_su_capitulo(self):
        e = TOCExtractor.extract_structure(doc([""] * 60, self.MARCADORES), "bk")
        norma = next(s for s in e["sections"] if s["title"] == "Norma L2")
        reg = next(c for c in e["chapters"] if c["title"] == "Regularización")
        self.assertEqual(norma["chapter_id"], reg["chapter_id"])

    def test_dos_marcadores_no_son_un_indice(self):
        """ Un libro con un marcador tiene una portada marcada, no un índice. """
        e = TOCExtractor.extract_structure(
            doc(["Capítulo 1: Algo"], [{"title": "Portada", "level": 0, "page": 1}]), "bk")
        self.assertNotEqual(e.get("origen"), "marcadores_pdf")

    def test_sin_marcadores_recurre_al_texto(self):
        e = TOCExtractor.extract_structure(doc(["Capítulo 1: Introducción"]), "bk")
        self.assertNotEqual(e.get("origen"), "marcadores_pdf")

    def test_todo_al_mismo_nivel_son_capitulos(self):
        planos = [{"title": f"Tema {i}", "level": 2, "page": i * 10 + 1} for i in range(4)]
        e = TOCExtractor.extract_structure(doc([""] * 50, planos), "bk")
        self.assertEqual(len(e["chapters"]), 4)


class PruebaPermisoDeLibros(unittest.TestCase):
    """ El fallo que se veía como «Ruta no permitida» al preparar un libro del
    Escritorio: el explorador navega la carpeta personal, pero el preparador
    comprobaba contra el espacio de trabajo. """

    def setUp(self):
        import app
        self.app = app
        self.tmp = os.path.join(os.path.expanduser("~"), ".prig_pruebas_permiso")
        os.makedirs(self.tmp, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def crear(self, nombre):
        ruta = os.path.join(self.tmp, nombre)
        with open(ruta, "w") as f:
            f.write("contenido")
        return ruta

    def test_acepta_un_libro_de_la_carpeta_personal(self):
        self.assertIsNone(self.app._libro_aceptable(self.crear("libro.pdf")))

    def test_rechaza_lo_que_esta_fuera(self):
        motivo = self.app._libro_aceptable("/etc/hostname")
        self.assertIsNotNone(motivo)

    def test_rechaza_lo_que_no_es_un_libro(self):
        motivo = self.app._libro_aceptable(self.crear("programa.sh"))
        self.assertIn("no es un libro", motivo)

    def test_dice_que_pasa_cuando_el_archivo_ya_no_esta(self):
        motivo = self.app._libro_aceptable(os.path.join(self.tmp, "fantasma.pdf"))
        self.assertIn("ya no está", motivo)

    def test_el_motivo_explica_qué_hacer(self):
        """ «Ruta no permitida» no decía ni qué ruta ni qué hacer con ella. """
        motivo = self.app._libro_aceptable(self.crear("cosa.sh"))
        self.assertIn("se admiten", motivo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
