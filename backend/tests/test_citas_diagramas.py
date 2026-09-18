"""
Pruebas para el sistema de Citas de Libros PDF, Analista de Librerías y Formato para IA.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_TMP_TEST_DIR = tempfile.mkdtemp(prefix="prig_test_env_")
os.environ["HOME"] = _TMP_TEST_DIR
os.environ["PRIG_BOOKS_DIR"] = os.path.join(_TMP_TEST_DIR, "books")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from book_service import BookService
from librerias_service import LibreriasService
import app as main_app
from starlette.testclient import TestClient


class TestCitasYDiagramas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.books_dir = os.path.join(self.tmp, "books")
        self.librerias_dir = os.path.join(self.tmp, "librerias")
        self.workspace_dir = os.path.join(self.tmp, "workspace")
        os.makedirs(self.books_dir, exist_ok=True)
        os.makedirs(self.librerias_dir, exist_ok=True)
        os.makedirs(self.workspace_dir, exist_ok=True)

        self.book_service = BookService(books_dir=self.books_dir)
        self.lib_service = LibreriasService(base_dir=self.librerias_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_book_citations_crud_and_export(self):
        """Verifica creación, lectura, actualización, borrado y exportación de citas de libros."""
        nombre_libro = "deep_learning_goodfellow.pdf"
        
        # 1. Obtener inicial (vacío)
        citas_data = self.book_service.get_book_citations(nombre_libro)
        self.assertEqual(citas_data["libro"], nombre_libro)
        self.assertEqual(len(citas_data["citas"]), 0)

        # 2. Guardar cita
        cita1 = {
            "pagina": 15,
            "capitulo": "Capítulo 2: Álgebra Lineal",
            "texto": "Un escalar es un único número, a diferencia de la mayoría de los otros objetos estudiados en álgebra lineal.",
            "nota": "Concepto fundamental para tensores en PyTorch.",
            "tags": ["álgebra", "tensores", "fundamentos"]
        }
        res_save = self.book_service.save_book_citation(nombre_libro, cita1)
        self.assertTrue(res_save["ok"])
        self.assertIn("id", res_save["cita"])
        cid1 = res_save["cita"]["id"]

        # Verificar guardado en archivo JSON
        json_path = os.path.join(self.book_service.citas_dir, "deep_learning_goodfellow.json")
        self.assertTrue(os.path.exists(json_path))
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(len(data["citas"]), 1)
            self.assertEqual(data["citas"][0]["pagina"], 15)

        # 3. Guardar segunda cita
        cita2 = {
            "pagina": 42,
            "capitulo": "Capítulo 4: Optimización Numérica",
            "texto": "El descenso de gradiente converge a un mínimo local cuando la tasa de aprendizaje es adecuada.",
            "nota": "Regla para ajuste de lr.",
            "tags": ["optimización", "gradiente"]
        }
        res_save2 = self.book_service.save_book_citation(nombre_libro, cita2)
        cid2 = res_save2["cita"]["id"]

        citas_data = self.book_service.get_book_citations(nombre_libro)
        self.assertEqual(len(citas_data["citas"]), 2)

        # 4. Obtener todas las citas para IA
        ai_citas = self.book_service.get_all_citations_for_ai("gradiente")
        self.assertEqual(len(ai_citas), 1)
        self.assertEqual(ai_citas[0]["id"], cid2)

        # 5. Exportar a espacio de trabajo
        res_exp = self.book_service.export_citations_to_workspace(nombre_libro, self.workspace_dir)
        self.assertTrue(res_exp["ok"])
        exported_file = os.path.join(self.workspace_dir, "deep_learning_goodfellow.json")
        self.assertTrue(os.path.exists(exported_file))
        with open(exported_file, "r", encoding="utf-8") as f:
            exp_data = json.load(f)
            self.assertEqual(len(exp_data["citas"]), 2)

        # 6. Borrar una cita
        res_del = self.book_service.delete_book_citation(nombre_libro, cid1)
        self.assertTrue(res_del["ok"])
        citas_data = self.book_service.get_book_citations(nombre_libro)
        self.assertEqual(len(citas_data["citas"]), 1)
        self.assertEqual(citas_data["citas"][0]["id"], cid2)

    def test_pdf_page_edit(self):
        """Verifica que las correcciones manuales de texto de página PDF se guarden y recuperen."""
        from pypdf import PdfWriter

        nombre_libro = "matematicas_ml.pdf"
        dummy_pdf = os.path.join(self.books_dir, "books", nombre_libro)
        os.makedirs(os.path.dirname(dummy_pdf), exist_ok=True)
        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(width=72, height=72)
        with open(dummy_pdf, "wb") as f:
            writer.write(f)

        num_pag = 3
        texto_editado = "Texto corregido manualmente con fórmulas matemáticas: E = mc^2 y W = X @ Theta."

        res = self.book_service.save_pdf_page_edit(nombre_libro, num_pag, texto_editado)
        self.assertTrue(res.get("ok") or res.get("success"))

        paginas_info = self.book_service.get_pdf_pages(nombre_libro, page=3)
        self.assertEqual(paginas_info["current_page"], 3)
        self.assertEqual(paginas_info["page_text"], texto_editado)
        self.assertTrue(paginas_info["has_edit"])

    def test_librerias_service_curated_and_custom(self):
        """Verifica la lista de librerías, repositorios custom y gestión de citas JSON."""
        # 1. Listar inicial (debe incluir numpy, matplotlib, etc.)
        libs = self.lib_service.list_libraries()
        ids = [lib["id"] for lib in libs]
        self.assertIn("numpy", ids)
        self.assertIn("matplotlib", ids)
        self.assertIn("pytorch", ids)
        self.assertIn("scikit-learn", ids)

        # Citas iniciales de muestra
        np_citas = self.lib_service.get_library_citations("numpy")
        self.assertEqual(np_citas["libreria"], "numpy")
        self.assertGreaterEqual(len(np_citas["citas"]), 1)

        # 2. Agregar librería personalizada
        res_add = self.lib_service.add_library(
            repo="optuna/optuna",
            name="optuna",
            desc="Framework de optimización automática de hiperparámetros"
        )
        self.assertTrue(res_add["ok"])
        libs2 = self.lib_service.list_libraries()
        ids2 = [l["id"] for l in libs2]
        self.assertIn("optuna", ids2)

        # 3. Guardar cita en optuna
        cita_opt = {
            "tema": "study.optimize",
            "funcion_o_clase": "optuna.create_study",
            "explicacion": "Crea un estudio de optimización con un sampler especificado (por defecto TPE).",
            "codigo_ejemplo": "study = optuna.create_study(direction='maximize')\nstudy.optimize(objective, n_trials=50)",
            "tags": ["optuna", "hiperparametros", "tpe"]
        }
        res_save = self.lib_service.save_library_citation("optuna", cita_opt)
        self.assertTrue(res_save["ok"])
        cid = res_save["cita"]["id"]

        # Verificar archivo json de optuna
        optuna_json = os.path.join(self.lib_service.citas_dir, "optuna.json")
        self.assertTrue(os.path.exists(optuna_json))

        # 4. Exportar citas de librería al workspace
        res_exp = self.lib_service.export_library_citations("optuna", self.workspace_dir)
        self.assertTrue(res_exp["ok"])
        self.assertTrue(os.path.exists(os.path.join(self.workspace_dir, "optuna.json")))

        # 5. Borrar cita
        res_del = self.lib_service.delete_library_citation("optuna", cid)
        self.assertTrue(res_del["ok"])
        opt_citas = self.lib_service.get_library_citations("optuna")
        self.assertEqual(len(opt_citas["citas"]), 0)

    def test_formatear_citas_helper(self):
        """Verifica que el helper _formatear_citas en app.py arme un bloque Markdown claro para el LLM."""
        citas_libros = [
            {
                "libro": "DeepLearning.pdf",
                "pagina": 33,
                "capitulo": "Cap 3",
                "texto": "Las redes convolucionales son modelos para datos en cuadrícula.",
                "nota": "Ver convolución 2D",
                "tags": ["cnn", "convolucion"]
            }
        ]
        citas_librerias = [
            {
                "libreria": "torch",
                "tema": "nn.Conv2d",
                "funcion_o_clase": "torch.nn.Conv2d",
                "explicacion": "Aplica una convolución 2D sobre una señal compuesta por varios planos de entrada.",
                "codigo_ejemplo": "conv = nn.Conv2d(in_channels=3, out_channels=16, kernel_size=3)",
                "tags": ["pytorch", "cnn"]
            }
        ]

        bloque = main_app._formatear_citas(citas_libros, citas_librerias)
        self.assertIn("CITAS BIBLIOGRÁFICAS Y DE LIBRERÍAS CARGADAS", bloque)
        self.assertIn("DeepLearning.pdf", bloque)
        self.assertIn("Pág. 33", bloque)
        self.assertIn("nn.Conv2d", bloque)
        self.assertIn("torch.nn.Conv2d", bloque)

    def test_fastapi_endpoints(self):
        """Prueba las rutas REST expuestas en FastAPI usando Starlette TestClient."""
        client = TestClient(main_app.app)

        # 1. Endpoint librerías
        res = client.get("/api/librerias/list")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertTrue(any(l["id"] == "numpy" for l in data))

        # 2. Endpoint citas de librería
        res = client.get("/api/librerias/citations?id=numpy")
        self.assertEqual(res.status_code, 200)
        citas = res.json()
        self.assertEqual(citas["libreria"], "numpy")

        # 3. Guardar cita en librería vía API
        nueva_cita = {
            "tema": "numpy.random",
            "funcion": "np.random.randn",
            "explicacion": "Genera muestras de la distribución normal estándar.",
            "snippet": "arr = np.random.randn(5, 5)",
            "tags": ["numpy", "random", "gauss"]
        }
        res_post = client.post("/api/librerias/citations/save", json={
            "lib_id": "numpy",
            "citation": nueva_cita
        })
        self.assertEqual(res_post.status_code, 200)
        save_data = res_post.json()
        self.assertTrue(save_data.get("ok"))
        created_id = save_data["cita"]["id"]

        # 4. All citations endpoint
        res_all = client.get("/api/librerias/all-citations")
        self.assertEqual(res_all.status_code, 200)
        all_c = res_all.json()
        self.assertTrue(any(c.get("libreria") == "NumPy" for c in all_c))

        # 5. Borrar cita vía API
        res_del = client.post("/api/librerias/citations/delete", json={
            "lib_id": "numpy",
            "citation_id": created_id
        })
        self.assertEqual(res_del.status_code, 200)


if __name__ == "__main__":
    unittest.main()
