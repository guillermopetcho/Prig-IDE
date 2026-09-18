"""
Pruebas de la ficha del libro.

La idea que sostiene todo esto: un libro de 600 páginas no cabe en un modelo de 7B,
pero su extracción sí. Índice, conceptos con frecuencias, muestra de afirmaciones,
símbolos y figuras juntos ocupan menos de mil tokens y describen el libro entero.
Si eso deja de cumplirse, el flujo empieza a recibir prompts truncados y responde a
medias sin avisar, así que aquí se comprueba.

Dos cosas más que se protegen y que ya fallaron: el importador tiraba el índice, las
figuras y las preguntas del paquete (información que el propio extractor ya había
sacado), y el contexto que recibe el planificador volcaba diccionarios en crudo.
"""

import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge_base import KnowledgeBase
from perfil_libro import PerfilLibro, _lista_corta, _nombrar, _aplanar


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = KnowledgeBase(os.path.join(self.tmp, "k.db"))
        self.pl = PerfilLibro(self.kb)
        self._poblar()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _poblar(self, source_id="bk1"):
        with self.kb.conectar() as c:
            c.execute("""INSERT OR REPLACE INTO books VALUES
                (?,?,?,?,?,?,?,?);""",
                (source_id, "Deep Learning", "deep_learning", "sha", 380, "m", 4, "hoy"))
            for n, (num, tit, a, b, temas) in enumerate([
                    ("4", "Regularizacion", 181, 240, ["regularizacion L2", "dropout"]),
                    ("5", "Optimizacion", 241, 310, ["descenso de gradiente"])]):
                c.execute("""INSERT OR REPLACE INTO sections VALUES
                    (?,?,?,?,?,?,?,1,?,?,?);""",
                    (f"{source_id}_c{n}", source_id, f"cap{n}", num, tit, a, b,
                     json.dumps(temas), "resumen del capitulo", "[]"))
            c.execute("INSERT OR REPLACE INTO concepts VALUES (?,?,?,?,?,?,?);",
                      ("c:regularizacion l2", "regularización L2", "regularizacion l2",
                       json.dumps(["deep_learning"]), 0, 4, 1))
            c.execute("INSERT OR REPLACE INTO aliases VALUES (?,?,?,?,1);",
                      ("regularizacion l2", "c:regularizacion l2", "regularización L2", source_id))
            c.execute("INSERT OR REPLACE INTO aliases VALUES (?,?,?,?,0);",
                      ("weight decay", "c:regularizacion l2", "weight decay", source_id))
            for i, (tipo, texto, pagina) in enumerate([
                    ("DEFINITION", "Penaliza la norma de los pesos.", 228),
                    ("FORMULA", "J = L + lambda ||w||^2", 229),
                    ("EXAMPLE", "Ejemplo resuelto con ridge.", 231),
                    ("CAVEAT", "Misma lambda en todas las capas es un error.", 235)]):
                c.execute("""INSERT OR REPLACE INTO claims VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?);""",
                    (f"cl{i}", "c:regularizacion l2", source_id, "deep_learning",
                     tipo, texto, f"cita {i}", pagina, 0.9, "none", "", "[]"))
            c.execute("INSERT INTO symbols VALUES (?,?,?,?,?,?);",
                      ("λ", "coeficiente de regularizacion", None, source_id,
                       "deep_learning", 228))
            c.execute("INSERT INTO figures VALUES (?,?,?,?,?);",
                      (source_id, "Figura 4.1", "Efecto de lambda", "figura", 230))
            c.execute("INSERT INTO questions VALUES (?,?,?,?);",
                      (source_id, "Por que no se regulariza el sesgo?", 228, None))
            c.commit()


class PruebaResumenCompacto(Base):
    """ Todo gira sobre que el libro entero quepa en un prompt. """

    def test_el_libro_entero_cabe_en_una_ventana_pequena(self):
        v = self.pl.variables("bk1")
        total = sum(len(t) / 3.6 for t in v.values())
        self.assertLess(total, 4000,
                        "el resumen del libro no cabe ni pidiéndolo todo de golpe")

    def test_cada_variable_va_por_separado(self):
        """ Un paso que deduce la notación no debe cargar con el índice. """
        v = self.pl.variables("bk1")
        self.assertIn("λ", v["libro:simbolos"])
        self.assertNotIn("λ", v["libro:indice"])
        self.assertIn("Regularizacion", v["libro:indice"])

    def test_el_indice_trae_las_paginas(self):
        """ Sin páginas, un plan no puede decir qué leer. """
        v = self.pl.variables("bk1")
        self.assertIn("p.181-240", v["libro:indice"])

    def test_los_conceptos_traen_su_frecuencia(self):
        """ La frecuencia es lo que distingue un tema central de uno mencionado. """
        self.assertIn("(4×", self.pl.variables("bk1")["libro:conceptos"])

    def test_la_muestra_se_reparte_por_tipos(self):
        m = self.pl.variables("bk1")["libro:muestra"]
        for tipo in ("DEFINITION", "FORMULA", "EXAMPLE", "CAVEAT"):
            self.assertIn(f"[{tipo}]", m)

    def test_un_libro_sin_indice_lo_dice_en_vez_de_callar(self):
        with self.kb.conectar() as c:
            c.execute("DELETE FROM sections;")
            c.commit()
        self.assertIn("no trae índice", self.pl.variables("bk1")["libro:indice"])

    def test_un_libro_que_no_existe_no_da_variables(self):
        self.assertEqual(self.pl.variables("inventado"), {})


class PruebaFicha(Base):

    def test_monta_las_piezas_de_cada_paso(self):
        ficha = self.pl.montar_ficha("bk1", {
            "temario": {"capitulos": [{"capitulo": "4", "titulo": "Regularizacion"}]},
            "identidad": {"nivel": "intermedio", "que_cubre": "redes profundas"},
            "lagunas": {"no_cubre": [{"tema": "transformers"}]},
        }, ["m:7b"])
        self.assertEqual(ficha["identidad"]["nivel"], "intermedio")
        self.assertEqual(ficha["temario"]["capitulos"][0]["capitulo"], "4")

    def test_desanida_cuando_el_paso_repite_la_clave(self):
        """ Un paso que devuelve {"asume": [...]} no debe dejar ficha["asume"]["asume"]. """
        ficha = self.pl.montar_ficha("bk1", {"prerrequisitos": {"asume": ["algebra"]}}, [])
        self.assertEqual(ficha["asume"], ["algebra"])

    def test_acepta_json_dentro_de_una_cadena(self):
        ficha = self.pl.montar_ficha(
            "bk1", {"identidad": 'Aquí tienes:\n```json\n{"nivel": "avanzado"}\n```'}, [])
        self.assertEqual(ficha["identidad"]["nivel"], "avanzado")

    def test_un_paso_fallido_no_tumba_el_resto(self):
        ficha = self.pl.montar_ficha("bk1", {"temario": None,
                                             "identidad": {"nivel": "básico"}}, [])
        self.assertNotIn("temario", ficha)
        self.assertEqual(ficha["identidad"]["nivel"], "básico")

    def test_lo_medido_sale_de_la_base_no_del_modelo(self):
        """ Las cifras no las dice un agente: se cuentan. """
        ficha = self.pl.montar_ficha("bk1", {}, [])
        self.assertEqual(ficha["medido"]["afirmaciones"], 4)
        self.assertEqual(ficha["medido"]["capitulos"], 2)
        self.assertEqual(ficha["medido"]["figuras"], 1)
        self.assertEqual(ficha["medido"]["por_tipo"]["EXAMPLE"], 1)

    def test_senala_los_conceptos_con_material_suficiente(self):
        ficha = self.pl.montar_ficha("bk1", {}, [])
        self.assertIn("regularización L2", ficha["medido"]["conceptos_con_material"])

    def test_se_guarda_y_se_recupera(self):
        self.pl.guardar("bk1", self.pl.montar_ficha("bk1", {"identidad": {"nivel": "x"}}, []))
        self.assertEqual(self.pl.obtener("bk1")["identidad"]["nivel"], "x")

    def test_listar_dice_cuales_tienen_ficha(self):
        self.assertIsNone(self.pl.listar()[0]["ficha_hecha"])
        self.pl.guardar("bk1", self.pl.montar_ficha("bk1", {}, []))
        self.assertIsNotNone(self.pl.listar()[0]["ficha_hecha"])


class PruebaMaterialParaEjercicio(Base):

    def test_resuelve_por_alias(self):
        m = self.pl.material_para_ejercicio("weight decay")
        self.assertTrue(m["encontrado"])
        self.assertEqual(m["concepto"], "regularización L2")

    def test_separa_ejemplos_y_errores_tipicos(self):
        m = self.pl.material_para_ejercicio("regularización L2")
        self.assertEqual(len(m["ejemplos_resueltos"]), 1)
        self.assertEqual(len(m["errores_tipicos"]), 1)
        self.assertIn("ridge", m["ejemplos_resueltos"][0]["text"])

    def test_localiza_el_capitulo_por_la_pagina(self):
        """ Para poder decir "lee el capítulo 4, p.181-240", no solo "p.228". """
        m = self.pl.material_para_ejercicio("regularización L2")
        self.assertEqual(m["secciones"][0]["numero"], "4")

    def test_trae_las_preguntas_del_propio_libro(self):
        m = self.pl.material_para_ejercicio("regularización L2")
        self.assertTrue(m["preguntas_del_libro"])

    def test_con_solo_una_definicion_no_hay_ejercicio(self):
        """ Un ejercicio necesita algo que HACER, no solo algo que saber. """
        with self.kb.conectar() as c:
            c.execute("DELETE FROM claims WHERE type IN ('FORMULA','EXAMPLE');")
            c.commit()
        self.assertFalse(
            self.pl.material_para_ejercicio("regularización L2")["suficiente_para_ejercicio"])

    def test_un_concepto_desconocido_lo_dice(self):
        m = self.pl.material_para_ejercicio("mecánica cuántica")
        self.assertFalse(m["encontrado"])


class PruebaContextoDelPlan(Base):

    def test_un_libro_sin_ficha_aparece_igual(self):
        """ Mejor decir que existe y no está analizado que ocultarlo. """
        ctx = self.pl.contexto_para_plan("objetivo")
        self.assertIn("Deep Learning", ctx)
        self.assertIn("sin analizar", ctx)

    def test_con_ficha_trae_nivel_temario_y_lagunas(self):
        self.pl.guardar("bk1", self.pl.montar_ficha("bk1", {
            "identidad": {"nivel": "intermedio", "que_cubre": "redes profundas"},
            "temario": {"capitulos": [{"capitulo": "4", "titulo": "Regularizacion",
                                       "paginas": "181-240", "dificultad": 3}]},
            "lagunas": {"no_cubre": [{"tema": "transformers",
                                      "gravedad": "hace falta otro libro"}]},
        }, []))
        ctx = self.pl.contexto_para_plan("objetivo")
        self.assertIn("Nivel: intermedio", ctx)
        self.assertIn("cap 4", ctx)
        self.assertIn("p.181-240", ctx)
        self.assertIn("NO cubre", ctx)
        self.assertIn("transformers", ctx)

    def test_no_vuelca_diccionarios_en_crudo(self):
        """ El planificador lee esto: un {'tema': ...} suelto no lo sabe interpretar. """
        self.pl.guardar("bk1", self.pl.montar_ficha("bk1", {
            "prerrequisitos": {"asume": [{"tema": "álgebra lineal",
                                          "como_de_necesario": "imprescindible"}],
                               "nivel_de_entrada": "primero de carrera"},
        }, []))
        ctx = self.pl.contexto_para_plan("objetivo")
        self.assertIn("álgebra lineal", ctx)
        for basura in ("{'tema'", '{"tema"', "como_de_necesario"):
            self.assertNotIn(basura, ctx)


class PruebaNombrado(unittest.TestCase):
    """ Los pasos devuelven JSON libre dentro de la forma pedida; leerlo mal deja
    el contexto del plan lleno de estructuras en crudo. """

    def test_nombra_una_cadena(self):
        self.assertEqual(_nombrar("álgebra"), "álgebra")

    def test_nombra_un_diccionario_por_su_clave_habitual(self):
        self.assertEqual(_nombrar({"tema": "cálculo"}), "cálculo")
        self.assertEqual(_nombrar({"nombre": "vectores"}), "vectores")

    def test_anade_el_matiz_entre_parentesis(self):
        self.assertEqual(_nombrar({"tema": "cálculo", "como_de_necesario": "imprescindible"}),
                         "cálculo (imprescindible)")

    def test_aplana_la_forma_envuelta(self):
        r = _lista_corta({"asume": [{"tema": "a"}, {"tema": "b"}], "nivel_de_entrada": "x"})
        self.assertEqual(r, "a, b")

    def test_aplana_una_lista_suelta(self):
        self.assertEqual(_lista_corta(["a", "b"]), "a, b")

    def test_tolera_lo_que_no_reconoce(self):
        self.assertIsInstance(_lista_corta({"raro": 42}), str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
