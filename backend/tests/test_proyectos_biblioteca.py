"""
Pruebas integrales de gestión de carpetas, proyectos guardados y su integración con Biblioteca.
"""

import os
import sys
import json
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

        # Leer contenido del proyecto
        contenido = self.book_service.get_book_content(proj_dir)
        self.assertTrue(contenido.get("is_project"))
        self.assertEqual(contenido.get("type"), "project")
        self.assertEqual(contenido.get("files_count"), 2)
        self.assertEqual(contenido.get("dirs_count"), 1)
        self.assertTrue(any("main.py" in s for s in contenido.get("sample_files", [])))

    def test_endpoints_api_proyectos(self):
        p_dir = os.path.join(self.tmp, "proyecto_api")
        os.makedirs(p_dir, exist_ok=True)

        # 1. Guardar proyecto
        res_save = self.client.post("/api/workspace/projects/save", json={
            "path": p_dir,
            "nombre": "Proyecto Test API",
            "origen": "test"
        })
        self.assertEqual(res_save.status_code, 200)
        self.assertTrue(res_save.json().get("success"))

        # 2. Listar proyectos
        res_list = self.client.get("/api/workspace/projects")
        self.assertEqual(res_list.status_code, 200)
        data = res_list.json()
        rutas = [p["path"] for p in data.get("guardados", [])]
        self.assertIn(p_dir, rutas)

        # 3. Explorar directorios
        res_dirs = self.client.get(f"/api/workspace/directories?ruta={self.tmp}")
        self.assertEqual(res_dirs.status_code, 200)
        dirs_data = res_dirs.json()
        self.assertEqual(dirs_data["current"], self.tmp)
        self.assertTrue(any(d["name"] == "proyecto_api" for d in dirs_data["subdirectories"]))
        self.assertTrue(len(dirs_data["shortcuts"]) > 0)

        # 4. Eliminar proyecto
        res_del = self.client.post("/api/workspace/projects/remove", json={
            "path": p_dir
        })
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.json().get("success"))

        # 5. Verificar que ya no está guardado
        res_list_after = self.client.get("/api/workspace/projects")
        rutas_after = [p["path"] for p in res_list_after.json().get("guardados", [])]
        self.assertNotIn(p_dir, rutas_after)


if __name__ == "__main__":
    unittest.main()
