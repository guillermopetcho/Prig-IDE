"""
Pruebas del índice semántico.

Existe porque el solapamiento de palabras no es relevancia. A la pregunta «¿cómo sé
hacia dónde mover los pesos para bajar el error?», BM25 puntúa MEJOR a
«regularización L2» (-5,25) que a «gradiente» (-3,37), porque la palabra «pesos»
aparece más veces en las afirmaciones sobre regularización. Un umbral sobre BM25 se
quedaría con el concepto equivocado.

Medido con bge-m3 sobre la base de pruebas: la precisión sube del 62 % al 89 % y el
ruido en el contexto baja del 38 % al 22 %, con 52 ms por pregunta.

Estas pruebas NO necesitan el embebedor descargado: se le inyecta uno simulado. Lo
que más importa comprobar es el repliegue — esto mejora el resultado y no puede
convertirse en un punto de fallo.
"""

import os
import sys
import json
import math
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge_base import KnowledgeBase
from indice_semantico import IndiceSemantico, _empaquetar, _desempaquetar, _coseno


class EmbebedorSimulado:
    """ Vectores deterministas: cada texto se proyecta sobre unas pocas palabras
    clave, de modo que los que comparten tema salen parecidos. """

    EJES = ["regulariza", "peso", "gradiente", "derivada", "sobreajuste", "dropout"]

    def __init__(self):
        self.llamadas = 0
        self.rompe = False

    def __call__(self, textos, timeout=None):
        self.llamadas += 1
        if self.rompe:
            raise RuntimeError("el embebedor no responde")
        salida = []
        for t in textos:
            bajo = (t or "").lower()
            v = [float(bajo.count(e)) for e in self.EJES]
            if not any(v):
                v = [0.01] * len(self.EJES)
            salida.append(v)
        return salida


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Ajustes de embeddings aislados: nunca los del usuario
        from unittest import mock
        self._env = mock.patch.dict(os.environ, {"PRIG_MODELOS_ARCHIVO": os.path.join(self.tmp, "modelos.json")})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.kb = KnowledgeBase(os.path.join(self.tmp, "k.db"))
        self._poblar()
        self.emb = EmbebedorSimulado()
        self.idx = IndiceSemantico(self.kb)
        self.idx.embeber = self.emb
        self.idx.disponible = lambda: True

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _poblar(self):
        CONCEPTOS = [
            ("c:reg", "regularizacion L2", "regulariza el peso regulariza peso"),
            ("c:grad", "gradiente", "gradiente derivada gradiente derivada"),
            ("c:sobre", "sobreajuste", "sobreajuste sobreajuste"),
            ("c:drop", "dropout", "dropout dropout"),
        ]
        with self.kb.conectar() as c:
            for cid, nombre, texto in CONCEPTOS:
                c.execute("INSERT OR REPLACE INTO concepts VALUES (?,?,?,?,?,?,?);",
                          (cid, nombre, nombre.lower(), json.dumps(["x"]), 0, 3, 1))
                c.execute("""INSERT OR REPLACE INTO claims VALUES
                             (?,?,?,?,?,?,?,?,?,?,?,?);""",
                          (f"cl_{cid}", cid, "bk", "x", "DEFINITION", texto,
                           "cita", 1, 0.9, "none", "", "[]"))
            c.commit()

    class CompiladorFalso:
        def __init__(self, kb):
            self.kb = kb

        def bloque(self, cid):
            with self.kb.conectar() as c:
                f = c.execute("SELECT text FROM claims WHERE concept_id=?;",
                              (cid,)).fetchone()
            return f["text"] if f else None

        def compilar_concepto(self, cid):
            return None

        def render_concepto(self, b):
            return ""

    def indexar(self):
        return self.idx.indexar(self.CompiladorFalso(self.kb))


class PruebaIndexado(Base):

    def test_indexa_todos_los_conceptos(self):
        r = self.indexar()
        self.assertTrue(r["ok"])
        self.assertEqual(r["conceptos"], 4)
        self.assertTrue(self.idx.hay_indice())

    def test_sin_embebedor_no_rompe_nada(self):
        self.idx.disponible = lambda: False
        r = self.indexar()
        self.assertFalse(r["ok"])
        self.assertIn("ollama pull", r["motivo"])

    def test_el_indice_sobrevive_a_reabrir(self):
        self.indexar()
        otro = IndiceSemantico(KnowledgeBase(os.path.join(self.tmp, "k.db")))
        self.assertTrue(otro.hay_indice())

    def test_reindexar_reemplaza_en_vez_de_acumular(self):
        self.indexar()
        self.indexar()
        with self.kb.conectar() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM vectores;").fetchone()[0], 4)

    def test_el_embebedor_va_en_cpu_por_defecto(self):
        """ En 6 GB no caben generador y embebedor: en CPU no compiten. """
        self.assertTrue(IndiceSemantico(self.kb).en_cpu)


class PruebaFiltrado(Base):

    def test_descarta_los_que_no_vienen_a_cuento(self):
        self.indexar()
        elegidos = self.idx.filtrar("gradiente derivada",
                                    ["c:reg", "c:grad", "c:sobre", "c:drop"])
        self.assertEqual(elegidos, ["c:grad"])

    def test_conserva_varios_cuando_varios_encajan(self):
        self.indexar()
        elegidos = self.idx.filtrar("regulariza peso", ["c:reg", "c:grad"])
        self.assertIn("c:reg", elegidos)

    def test_con_un_solo_candidato_no_decide_nada(self):
        self.indexar()
        self.assertIsNone(self.idx.filtrar("lo que sea", ["c:reg"]))

    def test_sin_indice_no_decide_nada(self):
        """ Devolver None deja que quien llama siga con su lista. """
        self.assertIsNone(self.idx.filtrar("gradiente", ["c:reg", "c:grad"]))

    def test_si_el_embebedor_falla_no_decide_nada(self):
        """ Una mejora opcional no puede convertirse en un punto de fallo. """
        self.indexar()
        self.emb.rompe = True
        self.assertIsNone(self.idx.filtrar("gradiente", ["c:reg", "c:grad"]))

    def test_nunca_devuelve_la_lista_vacia(self):
        self.indexar()
        elegidos = self.idx.filtrar("palabra que no aparece en ningun sitio",
                                    ["c:reg", "c:grad"])
        self.assertTrue(elegidos is None or len(elegidos) >= 1)

    def test_respeta_el_maximo(self):
        self.indexar()
        elegidos = self.idx.filtrar("regulariza peso gradiente derivada sobreajuste dropout",
                                    ["c:reg", "c:grad", "c:sobre", "c:drop"], maximo=2)
        self.assertLessEqual(len(elegidos or []), 2)


class PruebaBusqueda(Base):

    def test_encuentra_sin_partir_de_candidatos(self):
        self.indexar()
        r = self.idx.buscar("gradiente derivada", limite=3)
        self.assertEqual(r[0]["canonical_name"], "gradiente")
        self.assertIn("parecido", r[0])

    def test_sin_indice_devuelve_vacio(self):
        self.assertEqual(self.idx.buscar("gradiente"), [])


class PruebaRepliegueEnElEnsamblador(Base):
    """ Lo más importante: con o sin índice, el contexto se sigue armando. """

    def test_sin_indice_el_ensamblador_funciona_igual(self):
        from knowledge_context import ContextAssembler
        ca = ContextAssembler(self.kb)
        ca.indice = self.idx           # índice vacío
        cs = ca.conceptos_de_pregunta("regularizacion L2")
        self.assertTrue(cs)

    def test_con_el_embebedor_roto_el_ensamblador_funciona_igual(self):
        from knowledge_context import ContextAssembler
        self.indexar()
        ca = ContextAssembler(self.kb)
        ca.indice = self.idx
        self.emb.rompe = True
        self.assertTrue(ca.conceptos_de_pregunta("regularizacion L2"))


class PruebaVectores(unittest.TestCase):

    def test_ida_y_vuelta_en_binario(self):
        """ En binario son cuatro bytes por número en vez de los veinte que
        ocuparía escrito en JSON. """
        v = [0.1, -0.5, 3.25, 0.0]
        recuperado = _desempaquetar(_empaquetar(v))
        for a, b in zip(v, recuperado):
            self.assertAlmostEqual(a, b, places=5)

    def test_el_binario_ocupa_menos_que_el_texto(self):
        v = [0.123456] * 1024
        self.assertLess(len(_empaquetar(v)), len(json.dumps(v)) / 2)

    def test_coseno(self):
        self.assertAlmostEqual(_coseno([1, 0], [1, 0]), 1.0, places=5)
        self.assertAlmostEqual(_coseno([1, 0], [0, 1]), 0.0, places=5)

    def test_coseno_tolera_lo_raro(self):
        self.assertEqual(_coseno([], [1]), 0.0)
        self.assertEqual(_coseno([0, 0], [0, 0]), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
