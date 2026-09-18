"""
Pruebas del ensamblador de contexto.

El fallo que se protege aquí es el peor posible en un tutor: preguntar por una
paella y recibir material del libro de cálculo presentado como si lo respaldara.
FTS5 siempre devuelve algo si una sola palabra coincide, así que hace falta exigir
solapamiento léxico real antes de afirmar que la biblioteca cubre el tema.
"""

import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge_base import KnowledgeBase, palabras_contenido
from pack_importer import PackImporter
from knowledge_context import ContextAssembler, tokens
from tests.test_pack_importer import hacer_pack


class PruebaContexto(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        packs = os.path.join(cls.tmp, "packs")
        os.makedirs(packs)
        hacer_pack(packs, "bk_math", "Calculo", "math",
                   claims=[("DEFINITION", "gradiente", "Vector de derivadas parciales.",
                            "el vector de las derivadas parciales", 10),
                           ("THEOREM", "gradiente", "Apunta al maximo crecimiento.",
                            "direccion de maxima variacion", 12),
                           ("DEFINITION", "regla de la cadena", "Derivada de una composicion.",
                            "(f o g)' = f'(g) g'", 20)],
                   concepts=[("gradiente", ["grad"]), ("regla de la cadena", ["chain rule"])],
                   relations=[("gradiente", "regla de la cadena", "REQUIRES", "se usan juntas")])
        hacer_pack(packs, "bk_dl", "Deep Learning", "deep_learning",
                   claims=[("DEFINITION", "gradiente",
                            "Derivada de la perdida respecto de cada parametro.",
                            "derivada de la perdida respecto de los parametros", 78),
                           ("INTUITION", "gradiente", "Cuanto cambia la perdida por peso.",
                            "gradiente de la perdida", 80),
                           ("CODE_PATTERN", "gradiente", "loss.backward() acumula gradientes.",
                            "loss.backward()", 85)],
                   concepts=[("gradiente", ["gradientes"])])
        cls.kb = KnowledgeBase(os.path.join(cls.tmp, "k.db"))
        PackImporter(cls.kb).procesar(packs)
        cls.ca = ContextAssembler(cls.kb)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- reconocimiento de conceptos ----------------------------------

    def test_palabras_contenido_descarta_el_relleno(self):
        p = palabras_contenido("explicame que es el gradiente por favor")
        self.assertIn("gradiente", p)
        for vacía in ("que", "explicame", "por"):
            self.assertNotIn(vacía, p)

    def test_prefiere_la_frase_larga_sobre_sus_partes(self):
        cs = self.ca.conceptos_de_pregunta("hablame de la regla de la cadena")
        self.assertEqual(cs[0]["canonical_name"], "regla de la cadena")

    def test_encuentra_el_concepto_por_un_alias(self):
        cs = self.ca.conceptos_de_pregunta("para que sirve grad")
        self.assertEqual(cs[0]["canonical_name"], "gradiente")

    # -- el caso de la paella -----------------------------------------

    def test_pregunta_ajena_no_devuelve_contexto(self):
        for pregunta in ("como se cocina una paella",
                         "dame la receta del gazpacho",
                         "que tiempo hace hoy en madrid",
                         "hola"):
            r = self.ca.ensamblar(pregunta)
            self.assertTrue(r["vacio"], f"'{pregunta}' devolvió contexto: {r['conceptos']}")

    def test_sin_contexto_el_prompt_avisa_de_que_no_hay_respaldo(self):
        p = self.ca.prompt_tutor("como se cocina una paella")
        self.assertIn("NO está respaldada", p["sistema"])

    def test_con_contexto_el_prompt_exige_citar(self):
        """ El formato denso lo dice con otras palabras; lo que importa es que en
        ambos se le pida al modelo que diga de dónde sale cada cosa. """
        for compilado in (False, True):
            p = self.ca.prompt_tutor("que es el gradiente", compilado=compilado)
            self.assertIn("MATERIAL DE LA BIBLIOTECA", p["sistema"])
            self.assertRegex(p["sistema"], r"(?i)(cita|di el libro).{0,40}p[áa]gina")

    # -- presupuesto --------------------------------------------------

    def test_respeta_el_presupuesto(self):
        for presupuesto in (120, 250, 500, 1500):
            r = self.ca.ensamblar("explicame el gradiente y la regla de la cadena",
                                  presupuesto_tokens=presupuesto)
            self.assertLessEqual(r["tokens"], presupuesto,
                                 f"se pasó del presupuesto {presupuesto}")

    def test_con_poco_presupuesto_conserva_la_definicion(self):
        """ Con el presupuesto justo, la definición es lo último que se recorta.
        En el formato denso la marca es «=» y en el anterior «[DEFINITION]». """
        for compilado, marca in ((False, "[DEFINITION]"), (True, "\n= ")):
            r = self.ca.ensamblar("que es el gradiente", presupuesto_tokens=130,
                                  compilado=compilado)
            self.assertFalse(r["vacio"])
            self.assertIn(marca, r["texto"])

    # -- material -----------------------------------------------------

    def test_toda_afirmacion_lleva_libro_y_pagina(self):
        r = self.ca.ensamblar("que es el gradiente", presupuesto_tokens=1500)
        self.assertTrue(r["fuentes"])
        for f in r["fuentes"]:
            self.assertTrue(f["libro"], "una cita sin libro no es citable")
            self.assertTrue(f["cita"], "una cita sin texto literal no es verificable")

    def test_reune_lo_que_dicen_varios_libros(self):
        r = self.ca.ensamblar("que es el gradiente", presupuesto_tokens=1500)
        self.assertEqual({f["libro"] for f in r["fuentes"] if f["concepto"] == "gradiente"},
                         {"Calculo", "Deep Learning"})

    def test_el_puente_trae_la_analogia_del_otro_campo(self):
        """ Un concepto que vive en dos campos tiene que llegar marcado como tal:
        es lo que permite anclarlo en el que el alumno ya conoce. """
        anterior = self.ca.ensamblar("que es el gradiente", presupuesto_tokens=1500,
                                     compilado=False)
        self.assertIn("[DESDE ", anterior["texto"])
        denso = self.ca.ensamblar("que es el gradiente", presupuesto_tokens=1500,
                                  compilado=True)
        cabecera = next(l for l in denso["texto"].splitlines() if l.startswith("@gradiente"))
        self.assertTrue(cabecera.endswith("*"), "debe ir marcado como puente")
        self.assertIn("|", cabecera, "debe declarar los dos campos")

    def test_el_nivel_cambia_el_orden(self):
        """ Al avanzado el teorema le sirve antes que la intuición. Vale para los
        dos formatos: el denso marca el teorema con «T». """
        for compilado, marca in ((False, "[THEOREM]"), (True, "\nT ")):
            principiante = self.ca.ensamblar("que es el gradiente", presupuesto_tokens=200,
                                             nivel="principiante", compilado=compilado)["texto"]
            avanzado = self.ca.ensamblar("que es el gradiente", presupuesto_tokens=200,
                                         nivel="avanzado", compilado=compilado)["texto"]
            self.assertNotEqual(principiante, avanzado)
            self.assertIn(marca, avanzado)
            if compilado:
                cuerpo = [l for l in avanzado.splitlines() if l and l[0] in "=~T"]
                self.assertTrue(cuerpo[0].startswith("T"),
                                "al avanzado, el teorema primero")

    def test_arrastra_los_prerrequisitos(self):
        r = self.ca.ensamblar("explicame el gradiente", presupuesto_tokens=2000)
        self.assertIn("regla de la cadena", r["conceptos"])

    def test_el_dominio_preferido_manda(self):
        """ A igualdad de tipo, gana el libro del campo que estudia el alumno.

        Los dos libros definen el gradiente; el que estudia deep learning debe ver
        primero la definición de su campo, y el de matemáticas la suya.
        """
        def primer_libro(dominio):
            r = self.ca.ensamblar("que es el gradiente", presupuesto_tokens=200,
                                  dominio_preferido=dominio)
            return next(f for f in r["fuentes"] if f["concepto"] == "gradiente")["libro"]
        self.assertEqual(primer_libro("deep_learning"), "Deep Learning")
        self.assertEqual(primer_libro("math"), "Calculo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
