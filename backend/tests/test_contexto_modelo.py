"""
Pruebas de la compilación del contexto para el modelo.

La idea: el material se guardaba escrito para una persona —frases completas, citas
entre comillas, etiquetas en mayúsculas— y eso es caro para un modelo. Cada token de
entrada es atención gastada, y atención gastada en reconstruir una frase es atención
que no se gasta en razonar.

Medido sobre una base con tres libros que hablan de lo mismo: el material pasa de
371 a 204 tokens (45 % menos) y el modelo responde un 31 % más rápido.

Lo que más se protege aquí no es la compresión sino que comprimir NO cambie lo que
dice el texto. Dos corrupciones reales que hubo que corregir:

  · «En regresión lineal, la regularización L2 se conoce como ridge» perdía el
    calificador al elidir el sujeto y quedaba «regresión ridge», que es falso fuera
    de la regresión lineal;
  · «J(θ) = …» se convertía en «j(θ) = …» al minusculizar la inicial, y en una
    fórmula J y j son símbolos distintos.
"""

import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge_base import KnowledgeBase
from contexto_modelo import CompiladorContexto, tokens, SIGNO_DE


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = KnowledgeBase(os.path.join(self.tmp, "k.db"))
        self.c = CompiladorContexto(self.kb)
        self._poblar()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _poblar(self):
        LIBROS = [("bk_goo", "Deep Learning (Goodfellow)", "deep_learning"),
                  ("bk_bis", "Pattern Recognition (Bishop)", "machine_learning")]
        CLAIMS = [
            ("c1", "bk_goo", "DEFINITION",
             "La regularización L2 es una técnica que penaliza la norma al cuadrado "
             "del vector de pesos.", "se anade la norma L2", 228),
            ("c2", "bk_bis", "DEFINITION",
             "En regresión lineal, la regularización L2 se conoce como regresión "
             "ridge.", "known as ridge regression", 10),
            ("c3", "bk_goo", "FORMULA",
             "La función objetivo es J(θ) = L(θ) + (λ/2)||w||².",
             "J(theta) = L(theta)", 228),
            ("c4", "bk_goo", "CAVEAT",
             "Un error frecuente es aplicar la misma lambda a todas las capas.",
             "aplicar la misma lambda", 235),
            ("c5", "bk_goo", "INTUITION",
             "La regularización L2 contrae los pesos hacia el origen.",
             "contrae los pesos", 229),
        ]
        with self.kb.conectar() as c:
            for sid, titulo, dom in LIBROS:
                c.execute("INSERT OR REPLACE INTO books VALUES (?,?,?,?,?,?,?,?);",
                          (sid, titulo, dom, "sha", 400, "m", 3, "hoy"))
            c.execute("INSERT OR REPLACE INTO concepts VALUES (?,?,?,?,?,?,?);",
                      ("c:regularizacion l2", "regularizacion L2", "regularizacion l2",
                       json.dumps(["deep_learning", "machine_learning"]), 1, 5, 2))
            c.execute("INSERT OR REPLACE INTO concepts VALUES (?,?,?,?,?,?,?);",
                      ("c:sobreajust", "sobreajuste", "sobreajust",
                       json.dumps(["machine_learning"]), 0, 1, 1))
            for norm, sup, pri in (("regularizacion l2", "regularización L2", 1),
                                   ("weight decay", "weight decay", 0),
                                   ("ridg", "ridge", 0)):
                c.execute("INSERT OR REPLACE INTO aliases VALUES (?,?,?,?,?);",
                          (norm, "c:regularizacion l2", sup, "bk_goo", pri))
            for cid, sid, tipo, texto, cita, pag in CLAIMS:
                c.execute("""INSERT OR REPLACE INTO claims VALUES
                             (?,?,?,?,?,?,?,?,?,?,?,?);""",
                          (cid, "c:regularizacion l2", sid, "deep_learning", tipo,
                           texto, cita, pag, 0.9, "none", "", "[]"))
            c.execute("""INSERT INTO relations VALUES (?,?,?,?,?,?,0);""",
                      ("c:regularizacion l2", "c:sobreajust", "SOLVES", "q", "bk_goo", 1))
            c.commit()

    def bloque(self):
        return self.c.compilar_concepto("c:regularizacion l2")


class PruebaNoCorrompeElTexto(Base):
    """ Comprimir mal es peor que no comprimir: cambia lo que dice el libro. """

    def test_conserva_el_calificador_al_elidir(self):
        """ «ridge» solo es equivalente EN REGRESIÓN LINEAL. """
        b = self.bloque()
        linea = next(l for l in b["lineas"] if "ridge" in l["texto"])
        self.assertIn("regresión lineal", linea["texto"],
                      "quitar el calificador convierte la afirmación en falsa")

    def test_no_minusculiza_una_formula(self):
        """ En una fórmula, J y j son símbolos distintos. """
        b = self.bloque()
        formula = next(l for l in b["lineas"] if l["tipo"] == "FORMULA")
        self.assertIn("J(", formula["texto"])
        self.assertNotIn("j(θ)", formula["texto"])

    def test_elide_el_sujeto_repetido(self):
        """ El concepto ya está en la cabecera del bloque. """
        b = self.bloque()
        definicion = next(l for l in b["lineas"]
                          if l["tipo"] == "DEFINITION" and "norma" in l["texto"])
        self.assertNotIn("La regularización L2 es", definicion["texto"])
        self.assertIn("penaliza la norma", definicion["texto"])

    def test_elide_aunque_cambien_las_tildes(self):
        """ El nombre canónico va sin acentos y el libro los escribe: comparando
        tal cual, no coincidían nunca y no se elidía nada. """
        b = self.bloque()
        intuicion = next(l for l in b["lineas"] if l["tipo"] == "INTUITION")
        self.assertTrue(intuicion["texto"].startswith("contrae"), intuicion["texto"])

    def test_quita_el_preambulo_del_error_tipico(self):
        """ El signo ! ya dice que es un error. """
        b = self.bloque()
        error = next(l for l in b["lineas"] if l["tipo"] == "CAVEAT")
        self.assertFalse(error["texto"].lower().startswith("un error"))
        self.assertIn("lambda", error["texto"])

    def test_no_se_pierde_ninguna_afirmacion(self):
        b = self.bloque()
        self.assertEqual(len(b["lineas"]), 5)


class PruebaCompresion(Base):

    def test_comprime_de_verdad(self):
        b = self.bloque()
        denso = tokens(self.c.render_concepto(b))
        original = self.c._tokens_sin_compilar("c:regularizacion l2")
        self.assertLess(denso, original * 0.7,
                        f"esperaba al menos un 30 % menos; {denso} contra {original}")

    def test_la_cita_literal_no_va_al_modelo(self):
        """ Su trabajo era verificar en la extracción, y ya se hizo. """
        texto = self.c.render_concepto(self.bloque())
        self.assertNotIn("«", texto)
        self.assertNotIn("known as ridge regression", texto)

    def test_pero_la_cita_sigue_recuperable(self):
        """ Desaparece del contexto, no de la base: hace falta para respaldar. """
        citas = self.c.citas_de("c:regularizacion l2")
        self.assertTrue(any("known as ridge regression" == x["quote"] for x in citas))

    def test_funde_lo_que_dicen_varios_libros(self):
        with self.kb.conectar() as c:
            c.execute("""INSERT OR REPLACE INTO claims VALUES
                         (?,?,?,?,?,?,?,?,?,?,?,?);""",
                      ("c9", "c:regularizacion l2", "bk_bis", "machine_learning",
                       "INTUITION", "La regularización L2 contrae los pesos hacia el "
                       "origen del espacio.", "cita", 12, 0.9, "none", "", "[]"))
            c.commit()
        intuiciones = [l for l in self.bloque()["lineas"] if l["tipo"] == "INTUITION"]
        self.assertEqual(len(intuiciones), 1, "dos libros diciendo lo mismo son una línea")
        self.assertEqual(len(intuiciones[0]["fuentes"]), 2, "con las dos fuentes")

    def test_no_funde_ideas_distintas(self):
        definiciones = [l for l in self.bloque()["lineas"] if l["tipo"] == "DEFINITION"]
        self.assertEqual(len(definiciones), 2)


class PruebaFormato(Base):

    def test_ordena_por_como_se_entiende_algo(self):
        """ Definición, luego intuición, luego fórmula: no el orden del libro. """
        tipos = [l["tipo"] for l in self.bloque()["lineas"]]
        self.assertLess(tipos.index("DEFINITION"), tipos.index("INTUITION"))
        self.assertLess(tipos.index("INTUITION"), tipos.index("FORMULA"))
        self.assertEqual(tipos[-1], "CAVEAT")

    def test_los_alias_van_en_la_cabecera(self):
        texto = self.c.render_concepto(self.bloque())
        self.assertIn("≡weight decay", texto)

    def test_marca_los_conceptos_puente(self):
        self.assertTrue(self.c.render_concepto(self.bloque()).splitlines()[0].endswith("*"))

    def test_incluye_las_dependencias(self):
        """ Antes no estaban en el bloque y el modelo no podía ordenarlas. """
        self.assertIn("sobreajuste", self.c.render_concepto(self.bloque()))

    def test_los_libros_se_abrevian(self):
        codigos = self.c.codigos_de_libros()
        self.assertEqual(codigos["bk_bis"]["codigo"], "Bis")
        self.assertEqual(codigos["bk_goo"]["codigo"], "Goo")

    def test_dos_libros_del_mismo_autor_no_chocan(self):
        with self.kb.conectar() as c:
            c.execute("INSERT OR REPLACE INTO books VALUES (?,?,?,?,?,?,?,?);",
                      ("bk_x", "Otro libro (Bishop)", "math", "s", 10, "m", 1, "hoy"))
            c.commit()
        codigos = [v["codigo"] for v in self.c.codigos_de_libros().values()]
        self.assertEqual(len(codigos), len(set(codigos)))


class PruebaCabeceraAMedida(Base):

    def test_solo_declara_los_signos_que_aparecen(self):
        """ Declarar los trece cuando el bloque usa cuatro se come el ahorro. """
        self.c.precompilar()
        r = self.c.compilar_para(["c:regularizacion l2"], presupuesto=2000)
        cabecera = r["texto"].split("\n\n")[0]
        self.assertIn("=definición", cabecera)
        self.assertNotIn("Tteorema", cabecera)
        self.assertNotIn("Aalgoritmo", cabecera)

    def test_solo_declara_los_libros_que_se_citan(self):
        self.c.precompilar()
        with self.kb.conectar() as c:
            c.execute("INSERT OR REPLACE INTO books VALUES (?,?,?,?,?,?,?,?);",
                      ("bk_z", "Calculus (Apostol)", "math", "s", 10, "m", 1, "hoy"))
            c.commit()
        self.c.precompilar()
        r = self.c.compilar_para(["c:regularizacion l2"], presupuesto=2000)
        self.assertNotIn("Apostol", r["texto"])
        self.assertIn("Goodfellow", r["texto"])

    def test_respeta_el_presupuesto(self):
        self.c.precompilar()
        for pres in (120, 250, 600):
            r = self.c.compilar_para(["c:regularizacion l2", "c:sobreajust"],
                                     presupuesto=pres)
            self.assertLessEqual(r["tokens"], pres * 1.15,
                                 f"se pasó del presupuesto {pres}")


class PruebaPrecompilado(Base):

    def test_guarda_y_sirve_sin_recalcular(self):
        r = self.c.precompilar()
        self.assertGreaterEqual(r["conceptos"], 1)
        self.assertGreater(r["reduccion"], 20)
        self.assertTrue(self.c.bloque("c:regularizacion l2"))

    def test_sobrevive_a_reabrir_la_base(self):
        self.c.precompilar()
        otro = CompiladorContexto(KnowledgeBase(os.path.join(self.tmp, "k.db")))
        self.assertTrue(otro.bloque("c:regularizacion l2"))

    def test_sin_precompilar_compila_al_vuelo(self):
        """ Media biblioteca compilada y media sin compilar tiene que funcionar. """
        r = self.c.compilar_para(["c:regularizacion l2"], presupuesto=2000)
        self.assertFalse(r["vacio"])

    def test_un_concepto_inexistente_no_rompe_nada(self):
        r = self.c.compilar_para(["c:fantasma"], presupuesto=2000)
        self.assertTrue(r["vacio"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
