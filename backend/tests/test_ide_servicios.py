"""
Servicios de IDE: ir a archivo, buscar y reemplazar en archivos, renombrar,
duplicar, problemas de sintaxis y carpetas recientes.

Reemplazar en archivos y renombrar TOCAN el disco del usuario: lo que se protege es
que no salgan del workspace, no pisen nada existente, no toquen binarios ni
archivos que no son UTF-8, y respeten los finales de línea.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from file_manager import FileManager  # noqa: E402
from ide_servicios import ServiciosIDE, ErrorIDE  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="prig_ide_ws_")
        self.fuera = tempfile.mkdtemp(prefix="prig_ide_fuera_")
        self.fm = FileManager(self.ws)
        self.fm.config_path = os.path.join(self.ws, ".prig_config_test.json")
        self.ide = ServiciosIDE(self.fm)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)
        shutil.rmtree(self.fuera, ignore_errors=True)

    def escribir(self, rel, contenido, modo="w"):
        ruta = os.path.join(self.ws, rel)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, modo, **({} if "b" in modo else {"encoding": "utf-8", "newline": ""})) as f:
            f.write(contenido)
        return ruta

    def leer(self, rel, binario=False):
        with open(os.path.join(self.ws, rel), "rb" if binario else "r",
                  **({} if binario else {"encoding": "utf-8", "newline": ""})) as f:
            return f.read()


class PruebaListar(_Base):
    def test_lista_relativas_y_salta_lo_ignorado(self):
        self.escribir("a.py", "")
        self.escribir("src/b.py", "")
        self.escribir(".git/config", "")
        self.escribir("venv/lib/x.py", "")
        self.escribir("__pycache__/a.pyc", "")
        rels = [a["rel"] for a in self.ide.listar()["archivos"]]
        self.assertEqual(sorted(rels), ["a.py", "src/b.py"])


class PruebaBuscar(_Base):
    def setUp(self):
        super().setUp()
        self.escribir("uno.py", "def perdida(x):\n    return Perdida(x)  # perdida\n")
        self.escribir("dos/tres.md", "La pérdida L2\nperdidas totales\n")
        self.escribir("img.bin", b"perdida\x00\x01", "wb")
        self.escribir("latin.txt", "perdida \xe9".encode("latin-1"), "wb")

    def test_por_defecto_ignora_mayusculas(self):
        r = self.ide.buscar("perdida")
        self.assertEqual(r["total"], 4)       # 3 en uno.py + "perdidas" en tres.md
        self.assertEqual({x["rel"] for x in r["resultados"]}, {"uno.py", "dos/tres.md"})
        primera = r["resultados"][0]["coincidencias"][0]
        self.assertEqual((primera["linea"], primera["col"]), (1, 5))

    def test_mayusculas_y_palabra_completa(self):
        self.assertEqual(self.ide.buscar("Perdida", mayusculas=True)["total"], 1)
        self.assertEqual(self.ide.buscar("perdida", palabra=True)["total"], 3)

    def test_regex_y_regex_invalida(self):
        self.assertEqual(self.ide.buscar(r"def \w+\(", regex=True)["total"], 1)
        with self.assertRaises(ErrorIDE):
            self.ide.buscar("def (", regex=True)

    def test_incluir_y_excluir(self):
        self.assertEqual({x["rel"] for x in self.ide.buscar("perdida", incluir="*.md")["resultados"]},
                         {"dos/tres.md"})
        self.assertEqual({x["rel"] for x in self.ide.buscar("perdida", excluir="dos")["resultados"]},
                         {"uno.py"})

    def test_no_entra_en_binarios_ni_en_no_utf8(self):
        rels = {x["rel"] for x in self.ide.buscar("perdida")["resultados"]}
        self.assertNotIn("img.bin", rels)
        self.assertNotIn("latin.txt", rels)

    def test_vacio_se_rechaza(self):
        with self.assertRaises(ErrorIDE):
            self.ide.buscar("")


class PruebaReemplazar(_Base):
    def test_reemplaza_solo_en_las_rutas_pedidas_y_conserva_crlf(self):
        self.escribir("a.py", "x = viejo\r\ny = viejo\r\n")
        self.escribir("b.py", "viejo\n")
        r = self.ide.reemplazar("viejo", "nuevo", solo=[os.path.join(self.ws, "a.py")])
        self.assertEqual(r["total"], 2)
        self.assertEqual(self.leer("a.py", binario=True), b"x = nuevo\r\ny = nuevo\r\n")
        self.assertEqual(self.leer("b.py"), "viejo\n")

    def test_sin_regex_el_reemplazo_es_literal(self):
        self.escribir("a.txt", "precio\n")
        self.ide.reemplazar("precio", r"\1 y \n")
        self.assertEqual(self.leer("a.txt"), "\\1 y \\n\n")

    def test_con_regex_usa_grupos(self):
        self.escribir("a.py", "foo_bar = 1\n")
        self.ide.reemplazar(r"(\w+)_(\w+)", r"\2_\1", regex=True)
        self.assertEqual(self.leer("a.py"), "bar_foo = 1\n")

    def test_grupo_inexistente_no_escribe_nada(self):
        self.escribir("a.py", "abc\n")
        with self.assertRaises(ErrorIDE):
            self.ide.reemplazar("abc", r"\3", regex=True)
        self.assertEqual(self.leer("a.py"), "abc\n")

    def test_no_toca_rutas_de_fuera(self):
        with self.assertRaises(PermissionError):
            self.ide.reemplazar("x", "y", solo=[os.path.join(self.fuera, "a.py")])

    def test_conserva_permisos(self):
        ruta = self.escribir("run.sh", "echo viejo\n")
        os.chmod(ruta, 0o755)
        self.ide.reemplazar("viejo", "nuevo")
        self.assertEqual(os.stat(ruta).st_mode & 0o777, 0o755)


class PruebaRenombrarDuplicar(_Base):
    def test_renombrar_en_el_mismo_directorio(self):
        self.escribir("src/a.py", "1")
        r = self.ide.renombrar("src/a.py", "b.py")
        self.assertTrue(r["path"].endswith("src/b.py"))
        self.assertEqual(self.leer("src/b.py"), "1")

    def test_mover_a_otra_carpeta_relativa(self):
        self.escribir("a.py", "1")
        self.ide.renombrar("a.py", "lib/nuevo.py")
        self.assertTrue(os.path.exists(os.path.join(self.ws, "lib", "nuevo.py")))

    def test_no_pisa_existentes(self):
        self.escribir("a.py", "1")
        self.escribir("b.py", "2")
        with self.assertRaises(ErrorIDE):
            self.ide.renombrar("a.py", "b.py")
        self.assertEqual(self.leer("b.py"), "2")

    def test_no_saca_archivos_del_workspace(self):
        self.escribir("a.py", "1")
        with self.assertRaises(PermissionError):
            self.ide.renombrar("a.py", os.path.join(self.fuera, "a.py"))
        self.assertTrue(os.path.exists(os.path.join(self.ws, "a.py")))

    def test_no_renombra_la_raiz_ni_mete_carpeta_en_si_misma(self):
        with self.assertRaises(ErrorIDE):
            self.ide.renombrar(self.ws, "otro")
        os.makedirs(os.path.join(self.ws, "d"))
        with self.assertRaises(ErrorIDE):
            self.ide.renombrar("d", "d/dentro")

    def test_duplicar_numera_las_copias(self):
        self.escribir("a.py", "1")
        self.assertTrue(self.ide.duplicar("a.py")["path"].endswith("a copia.py"))
        self.assertTrue(self.ide.duplicar("a.py")["path"].endswith("a copia 2.py"))
        os.makedirs(os.path.join(self.ws, "d"))
        self.escribir("d/x.txt", "x")
        self.assertTrue(os.path.exists(os.path.join(self.ide.duplicar("d")["path"], "x.txt")))


class PruebaProblemas(_Base):
    def test_codigo_correcto_no_tiene_problemas(self):
        self.assertEqual(self.ide.problemas("python", "def f():\n    return 1\n"), [])

    def test_error_de_sintaxis_con_posicion(self):
        p = self.ide.problemas("python", "x = 1\nif x\n    pass\n")
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]["linea"], 2)
        self.assertEqual(p[0]["gravedad"], "error")
        self.assertIn("SyntaxError", p[0]["mensaje"])

    def test_indentacion(self):
        p = self.ide.problemas("python", "def f():\nreturn 1\n")
        self.assertIn("IndentationError", p[0]["mensaje"])

    def test_otros_lenguajes_no_se_revisan(self):
        self.assertEqual(self.ide.problemas("javascript", "if ("), [])


class PruebaRecientes(_Base):
    def test_orden_sin_duplicados_y_solo_existentes(self):
        a, b = os.path.join(self.ws, "a"), os.path.join(self.ws, "b")
        os.makedirs(a)
        os.makedirs(b)
        self.ide.anotar_reciente(a)
        self.ide.anotar_reciente(b)
        self.ide.anotar_reciente(a)
        self.ide.anotar_reciente("/no/existe/xyz")
        self.assertEqual([r["path"] for r in self.ide.recientes()], [a, b])
        self.ide.olvidar_recientes()
        self.assertEqual(self.ide.recientes(), [])

    def test_conserva_el_resto_de_la_configuracion(self):
        with open(self.fm.config_path, "w") as f:
            json.dump({"last_workspace": self.ws, "otra": 1}, f)
        self.ide.anotar_reciente(self.ws)
        with open(self.fm.config_path) as f:
            datos = json.load(f)
        self.assertEqual(datos["otra"], 1)
        self.assertEqual(datos["last_workspace"], self.ws)


class PruebaMostrarEnSistema(_Base):
    def test_no_lanza_nada_fuera_del_workspace(self):
        with mock.patch("ide_servicios.subprocess.Popen") as popen, \
                mock.patch("ide_servicios.subprocess.run") as run:
            with self.assertRaises(PermissionError):
                self.ide.mostrar_en_sistema(self.fuera)
            popen.assert_not_called()
            run.assert_not_called()

    def test_abre_la_carpeta_si_no_hay_dbus(self):
        ruta = self.escribir("a.py", "")
        with mock.patch("ide_servicios.shutil.which", return_value=None), \
                mock.patch("ide_servicios.sys.platform", "linux"), \
                mock.patch("ide_servicios.subprocess.Popen") as popen:
            self.ide.mostrar_en_sistema(ruta)
        self.assertEqual(popen.call_args.args[0], ["xdg-open", self.ws])


if __name__ == "__main__":
    unittest.main()
