"""
Pruebas para el sistema de Citas de Libros PDF, Analista de Librerías y Formato para IA.
"""

import os
import shutil
import sys
import tempfile
import unittest

# La carpeta personal temporal la fija tests/__init__.py para toda la suite

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from book_service import BookService
import app as main_app


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

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # Las citas de un libro (crear, ordenar, buscar, exportar, borrar) y corregir una página de un PDF:
    # prig-server/tests/libros_tests.rs

    # La lista, el alta, guardar, exportar y borrar citas de librerías: prig-server/tests/librerias_tests.rs

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


if __name__ == "__main__":
    unittest.main()
