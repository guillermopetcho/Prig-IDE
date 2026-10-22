import os
import sys
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import _formatear_gancho


class TestInlinePromptAndGancho(unittest.TestCase):
    def test_formatear_gancho_vacio(self):
        self.assertEqual(_formatear_gancho(None), "")
        self.assertEqual(_formatear_gancho([]), "")

    def test_formatear_gancho_con_archivos(self):
        archivos = [
            {"path": "main.py", "content": "print('hola')"},
            {"path": "utils.py", "content": "def suma(a, b): return a + b"}
        ]
        res = _formatear_gancho(archivos)
        self.assertIn("ARCHIVOS ENGANCHADOS POR EL USUARIO", res)
        self.assertIn("### Archivo: main.py", res)
        self.assertIn("print('hola')", res)
        self.assertIn("### Archivo: utils.py", res)
        self.assertIn("def suma(a, b): return a + b", res)



# Las instrucciones «Prig//:» las atiende el servidor de Rust: backend-rust/crates/prig-server/tests/asistente_tests.rs


if __name__ == "__main__":
    unittest.main()


