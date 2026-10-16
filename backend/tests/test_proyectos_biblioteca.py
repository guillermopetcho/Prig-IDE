"""
Pruebas integrales de gestión de carpetas, proyectos guardados y su integración con Biblioteca.
"""

import os
import sys
import tempfile
import shutil
import unittest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from file_manager import FileManager
from ide_servicios import ServiciosIDE
from book_service import BookService
from app import app


class TestProyectosYBiblioteca(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config_file = os.path.join(self.tmp, "prig_config.json")
        self.books_dir = os.path.join(self.tmp, "books")
        os.makedirs(self.books_dir, exist_ok=True)

        self.fm = FileManager(self.tmp)
        self.fm.config_path = self.config_file
        self.ide = ServiciosIDE(self.fm)
        self.ide._config_path = lambda: self.config_file

        self.book_service = BookService(books_dir=self.books_dir)
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_guardar_proyecto_y_listar_en_biblioteca(self):
        # Crear un proyecto simulado
        proj_dir = os.path.join(self.tmp, "mi_proyecto_ml")
        os.makedirs(os.path.join(proj_dir, "src"), exist_ok=True)
        with open(os.path.join(proj_dir, "main.py"), "w", encoding="utf-8") as f:
            f.write("print('Hola Mundo')\n")
        with open(os.path.join(proj_dir, "src", "modelo.py"), "w", encoding="utf-8") as f:
            f.write("# Modelo\n")

        # Guardar proyecto con IDEServicios
        self.ide.guardar_proyecto(proj_dir, "Mi Proyecto ML", origen="biblioteca")

        # Mockear get_saved_projects en book_service para usar nuestro ide
        self.book_service.get_saved_projects = lambda: self.ide.proyectos_guardados()

        # Listar libros en categoría PROJECTS
        libros = self.book_service.list_books(category_filter="PROJECTS")
        self.assertTrue(any(b["path"] == proj_dir for b in libros))

        proyecto_item = next(b for b in libros if b["path"] == proj_dir)
        self.assertEqual(proyecto_item["category"], "PROJECTS")
        self.assertEqual(proyecto_item["title"], "Mi Proyecto ML")

        # El resumen del proyecto (leerlo): prig-server/tests/libros_tests.rs


if __name__ == "__main__":
    unittest.main()
