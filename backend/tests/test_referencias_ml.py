"""
Referencias de ML (backend/referencias_ml.py y /api/referencias/*): el catálogo es coherente, la elección de
referencias para el chat es pertinente (y no aparece en preguntas que no son de ML), y las acciones de la
Biblioteca (leer, abrir, guardar) solo usan URLs del catálogo. Sin red: descargas, biblioteca e índice se
sustituyen, así los tests no tocan la biblioteca del usuario.
"""

import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import referencias_ml as rm  # noqa: E402


def titulos(refs):
    return [r["titulo"] for r in refs]


class PruebaCatalogo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refs = rm.cargar()["referencias"]

    def test_catalogo_completo_y_coherente(self):
        self.assertGreater(len(self.refs), 300)
        ids = [r["id"] for r in self.refs]
        self.assertEqual(len(ids), len(set(ids)))
        cats = set(rm.CATEGORIA_POR_ID)
        for r in self.refs:
            self.assertIn(r["tipo"], rm.TIPOS, r["id"])
            self.assertTrue(r["categorias"] and set(r["categorias"]) <= cats, r["id"])
            self.assertRegex(r["url"], r"^https?://", r["id"])
            self.assertTrue(r.get("titulo") and r.get("autores"), r["id"])
            self.assertIn(r.get("acceso"), ("gratis", "pago"), r["id"])
            self.assertEqual(r.get("estado"), "ok", f"{r['id']}: {r.get('nota_verificacion') or r.get('nota_revision')}")
            if r.get("arxiv"):
                # los datos de arXiv vienen de su API, no escritos a mano
                self.assertTrue(r.get("resumen_original") and r.get("anio"), r["id"])
                self.assertEqual(r["url"], f"https://arxiv.org/abs/{r['arxiv']}")

    def test_todas_las_familias_tienen_libro_o_formulario_y_papers(self):
        for c in rm.CATEGORIAS:
            propias = [r for r in self.refs if c["id"] in r["categorias"]]
            self.assertTrue(any(r["tipo"] in ("libro", "formulario", "apuntes", "survey", "curso") for r in propias), c["id"])
            self.assertTrue(any(r["tipo"] in ("paper", "survey") for r in propias), c["id"])

    def test_orden_por_familia_y_tipo(self):
        orden = {c["id"]: i for i, c in enumerate(rm.CATEGORIAS)}
        posiciones = [orden[r["categorias"][0]] for r in self.refs]
        self.assertEqual(posiciones, sorted(posiciones))

    def test_listar_filtra(self):
        self.assertTrue(all(r["tipo"] == "formulario" for r in rm.listar(tipo="formulario")))
        self.assertIn("XGBoost: A Scalable Tree Boosting System", titulos(rm.listar(q="xgboost")))
        self.assertTrue(all("arboles" in r["categorias"] for r in rm.listar(categoria="arboles")))

    def test_titulos_parecidos(self):
        self.assertTrue(rm._titulos_parecidos("LOF: identifying density-based local outliers", "LOF"))
        self.assertTrue(rm._titulos_parecidos("Attention Is All You Need", "Attention is all you need"))
        self.assertFalse(rm._titulos_parecidos("Random Forests", "Soccermatics: could a Premier League team"))

    def test_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            destino = rm.markdown(destino=os.path.join(d, "r.md"))
            with open(destino, encoding="utf-8") as f:
                texto = f.read()
        self.assertIn("## Árboles de decisión y ensembles", texto)
        self.assertIn("[Attention Is All You Need](https://arxiv.org/abs/1706.03762)", texto)


class PruebaRelacionadas(unittest.TestCase):
    def test_elige_lo_pertinente(self):
        casos = {
            "hazme un resumen de random forest": "Random Forests",
            "¿cómo funciona la atención en los transformers?": "Attention Is All You Need",
            "explica PPO": "Proximal Policy Optimization Algorithms",
            "qué es el teorema de bayes": "Introduction to Probability (2nd ed.)",
            "diferencia entre lasso y ridge": "Regression Shrinkage and Selection Via the Lasso",
            "cómo funcionan los modelos de difusión": "Understanding Diffusion Models: A Unified Perspective",
            "series temporales con ARIMA": "Forecasting: Principles and Practice (3rd ed.)",
        }
        for pregunta, esperado in casos.items():
            self.assertIn(esperado, titulos(rm.relacionadas(pregunta)), pregunta)

    def test_nada_en_preguntas_que_no_son_de_ml(self):
        for pregunta in ("arregla este bug en mi función de login", "cómo leo un archivo csv en python", "hola",
                         "presta atención a este error de sintaxis", "resume este texto en tres líneas"):
            self.assertEqual(rm.relacionadas(pregunta), [], pregunta)

    def test_variedad_y_maximo(self):
        refs = rm.relacionadas("explícame redes neuronales, backpropagation, dropout y batch norm", maximo=5)
        self.assertLessEqual(len(refs), 5)
        tipos = [r["tipo"] for r in refs]
        self.assertTrue(all(tipos.count(t) <= 2 for t in tipos))

    def test_bloque_para_prompt(self):
        bloque, refs = rm.bloque_para_prompt("resumen de XGBoost")
        self.assertTrue(refs)
        self.assertIn("[XGBoost: A Scalable Tree Boosting System](https://arxiv.org/abs/1603.02754)", bloque)
        self.assertIn("No cites ninguna que no esté en esta lista", bloque)
        self.assertEqual(rm.bloque_para_prompt("hola"), ("", []))

    def test_cita_el_pdf_abierto_si_la_editorial_es_de_pago(self):
        bloque, _ = rm.bloque_para_prompt("hazme un resumen de random forest")
        self.assertIn("(https://www.stat.berkeley.edu/~breiman/randomforest2001.pdf)", bloque)

    def test_cita_corta(self):
        self.assertEqual(rm.cita_corta({"autores": ["scikit-learn developers"], "anio": 2024, "tipo": "documentacion"}), "scikit-learn developers, 2024")
        self.assertEqual(rm.cita_corta({"autores": ["Leo Breiman"], "anio": 2001}), "Breiman, 2001")
        self.assertEqual(rm.cita_corta({"autores": ["Ian Goodfellow", "Yoshua Bengio", "Aaron Courville"], "anio": 2016}), "Goodfellow et al., 2016")
        self.assertEqual(rm.cita_corta({"autores": ["Stephen Boyd", "Lieven Vandenberghe"], "anio": 2004}), "Boyd y Vandenberghe, 2004")


class PruebaEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as main_app
        from starlette.testclient import TestClient
        cls.app = main_app
        cls.client = TestClient(main_app.app)

    def test_listar_y_detalle(self):
        r = self.client.get("/api/referencias", params={"tipo": "libro"}).json()
        self.assertTrue(r["referencias"] and all(x["tipo"] == "libro" for x in r["referencias"]))
        self.assertNotIn("resumen_original", r["referencias"][0])
        d = self.client.get("/api/referencias/detalle", params={"id": "arxiv_1706_03762"}).json()
        self.assertEqual(d["titulo"], "Attention Is All You Need")
        self.assertTrue(d["tiene_pdf"] and d["resumen_original"])
        self.assertEqual(self.client.get("/api/referencias/detalle", params={"id": "no-existe"}).status_code, 404)

    def test_pdf_solo_desde_el_catalogo(self):
        pedidas = []

        def falso(url):
            pedidas.append(url)
            return b"%PDF-1.4 prueba"
        with mock.patch.object(self.app, "_descargar_pdf", falso):
            r = self.client.get("/api/referencias/pdf", params={"id": "arxiv_1706_03762"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertEqual(pedidas, ["https://arxiv.org/pdf/1706.03762"])
        # una página web sin PDF directo no se descarga
        sin_pdf = next(x for x in rm.cargar()["referencias"] if not x.get("url_pdf") and not x["url"].endswith(".pdf"))
        self.assertEqual(self.client.get("/api/referencias/pdf", params={"id": sin_pdf["id"]}).status_code, 404)

    def test_abrir_en_navegador(self):
        with mock.patch.object(self.app, "_lanzar_navegador_sistema", return_value=True) as lanzar:
            r = self.client.post("/api/referencias/abrir", json={"id": "arxiv_1412_6980"}).json()
        lanzar.assert_called_once_with("https://arxiv.org/abs/1412.6980")
        self.assertTrue(r["ok"])

    def test_guardar_en_biblioteca_e_indexar(self):
        importados = []

        def importar(ruta, categoria):
            with open(ruta, "rb") as f:
                importados.append((os.path.basename(ruta), categoria, f.read(5)))
            return {"path": "/tmp/x.pdf", "category": categoria.upper(), "filename": os.path.basename(ruta)}
        with mock.patch.object(self.app, "_descargar_pdf", return_value=b"%PDF-1.4 x"), \
                mock.patch.object(self.app.book_service, "import_file", importar), \
                mock.patch.object(self.app.knowledge_service, "index_single", return_value={"status": "INGESTED", "chunks_count": 7}):
            r = self.client.post("/api/referencias/guardar", json={"id": "arxiv_1706_03762"}).json()
        nombre, categoria, cabecera = importados[0]
        self.assertEqual(categoria, "papers")
        self.assertEqual(cabecera, b"%PDF-")
        self.assertTrue(nombre.startswith("Vaswani et al 2017 - Attention Is All You Need") and nombre.endswith(".pdf"))
        self.assertTrue(r["indexed"])
        self.assertEqual(r["chunks_count"], 7)

    def test_relacionadas_endpoint(self):
        r = self.client.get("/api/referencias/relacionadas", params={"q": "explica XGBoost"}).json()["referencias"]
        self.assertIn("XGBoost: A Scalable Tree Boosting System", [x["titulo"] for x in r])
        self.assertTrue(all(set(x) >= {"id", "titulo", "url", "cita", "tipo"} for x in r))

    def test_chats_de_las_secciones_reciben_las_referencias(self):
        prompt, refs = self.app._con_referencias("resumen de random forest", "PREGUNTA")
        self.assertTrue(prompt.endswith("PREGUNTA") and "REFERENCIAS DE LA BIBLIOTECA" in prompt and refs)
        self.assertEqual(self.app._con_referencias("hola", "PREGUNTA"), ("PREGUNTA", []))
        mensajes = [{"role": "user", "content": "¿qué es XGBoost?"}, {"role": "assistant", "content": "…"},
                    {"role": "user", "content": "resume el paper de XGBoost"}]
        nuevos = self.app._mensajes_con_referencias(mensajes)
        self.assertIn("arxiv.org/abs/1603.02754", nuevos[-1]["content"])
        self.assertEqual(nuevos[0]["content"], "¿qué es XGBoost?")      # solo el último mensaje del alumno
        self.assertEqual(mensajes[-1]["content"], "resume el paper de XGBoost")  # la original no se toca


if __name__ == "__main__":
    unittest.main()
