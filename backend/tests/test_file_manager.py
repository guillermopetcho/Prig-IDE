"""
file_manager decide qué archivos del usuario se leen, se escriben y se BORRAN.
Un fallo aquí no da un error: destruye trabajo o filtra datos fuera del workspace.
"""
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from file_manager import FileManager  # noqa: E402


class TestConfinamiento(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="prig_test_ws_")
        self.fuera = tempfile.mkdtemp(prefix="prig_test_fuera_")
        self.fm = FileManager(self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)
        shutil.rmtree(self.fuera, ignore_errors=True)

    def test_escribir_dentro_funciona(self):
        res = self.fm.write_file(os.path.join(self.ws, "a.py"), "print(1)")
        self.assertTrue(res.get("success"))
        self.assertEqual(self.fm.read_file(os.path.join(self.ws, "a.py"))["content"], "print(1)")

    def test_ruta_relativa_se_resuelve_contra_el_workspace(self):
        self.fm.write_file("sub/b.py", "x=1")
        self.assertTrue(os.path.exists(os.path.join(self.ws, "sub", "b.py")))

    def test_escribir_fuera_se_rechaza(self):
        destino = os.path.join(self.fuera, "intruso.txt")
        res = self.fm.write_file(destino, "contenido")
        self.assertIn("error", res)
        self.assertFalse(os.path.exists(destino))

    def test_leer_fuera_se_rechaza(self):
        victima = os.path.join(self.fuera, "secreto.txt")
        open(victima, "w").write("datos privados")
        self.assertIn("error", self.fm.read_file(victima))

    def test_escapar_con_puntos_se_rechaza(self):
        res = self.fm.read_file(os.path.join(self.ws, "..", "..", "etc", "passwd"))
        self.assertIn("error", res)

    def test_borrar_fuera_se_rechaza(self):
        victima = os.path.join(self.fuera, "no_borrar.txt")
        open(victima, "w").write("importante")
        self.assertIn("error", self.fm.delete_item(victima))
        self.assertTrue(os.path.exists(victima), "el archivo de fuera NO debe borrarse")

    def test_no_se_puede_borrar_la_raiz_del_workspace(self):
        self.assertIn("error", self.fm.delete_item(self.ws))
        self.assertTrue(os.path.isdir(self.ws))

    def test_borrar_inexistente_informa_en_vez_de_fingir_exito(self):
        self.assertIn("error", self.fm.delete_item(os.path.join(self.ws, "fantasma.py")))


class TestArbol(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="prig_test_ws_")
        self.fm = FileManager(self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_profundidad_suficiente_para_proyectos_reales(self):
        hondo = os.path.join(self.ws, "a", "b", "c", "d")
        os.makedirs(hondo)
        open(os.path.join(hondo, "hondo.py"), "w").write("x=1")

        def buscar(nodos, nombre):
            for n in nodos:
                if n["name"] == nombre:
                    return True
                if n.get("children") and buscar(n["children"], nombre):
                    return True
            return False

        self.assertTrue(buscar(self.fm.get_file_tree(), "hondo.py"))

    def test_no_lista_fuera_del_workspace(self):
        fuera = tempfile.mkdtemp(prefix="prig_test_fuera_")
        try:
            self.assertEqual(self.fm.get_file_tree(fuera), [])
        finally:
            shutil.rmtree(fuera, ignore_errors=True)


class TestNotebook(unittest.TestCase):
    def test_notebook_ilegible_no_tumba_la_lectura(self):
        ws = tempfile.mkdtemp(prefix="prig_test_ws_")
        try:
            fm = FileManager(ws)
            roto = os.path.join(ws, "roto.ipynb")
            open(roto, "w").write("{esto no es json")
            res = fm.read_file(roto)
            self.assertNotIn("error", res, "debe devolver el contenido crudo igualmente")
            self.assertIn("error", res["notebook_data"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
