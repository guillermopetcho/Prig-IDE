import os
import sys
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import _formatear_gancho, AIInlinePromptRequest, ai_inline_prompt, AIChatRequest


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

    @patch("app.ai_engine.generate_response")
    def test_ai_inline_prompt_generacion(self, mock_generate):
        mock_generate.return_value = ["def cuadrado(x):\n", "    return x ** 2\n"]

        req = AIInlinePromptRequest(
            prompt="crear función cuadrado",
            file_path="mate.py",
            file_content="import math\n\n# Prig//: crear función cuadrado\n\nprint('fin')",
            line_number=3,
            language="python",
            model="qwen2.5-coder:7b"
        )
        res = ai_inline_prompt(req)
        self.assertEqual(res["status"], "ok")
        self.assertIn("def cuadrado(x):", res["code"])
        self.assertEqual(res["line_number"], 3)
        self.assertEqual(res["prompt"], "crear función cuadrado")

    @patch("app.ai_engine.generate_response")
    def test_ai_inline_prompt_limpieza_markdown(self, mock_generate):
        # Simular que el modelo envolvió en bloque de código markdown
        mock_generate.return_value = ["```python\nconst x = 10;\n```"]

        req = AIInlinePromptRequest(
            prompt="definir constante",
            file_path="app.js",
            file_content="// Prig//: definir constante\nconsole.log(x);",
            line_number=1,
            language="javascript",
            model="qwen2.5-coder:7b"
        )
        res = ai_inline_prompt(req)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["code"], "const x = 10;")
        self.assertNotIn("```", res["code"])

    @patch("app.ai_engine.generate_response")
    def test_ai_inline_prompt_con_prefix_suffix(self, mock_generate):
        mock_generate.return_value = ["    return a + b"]

        req = AIInlinePromptRequest(
            prompt="sumar a y b",
            prefix_code="def sumar(a, b):\n    # Prig//: sumar a y b",
            suffix_code="",
            language="python"
        )
        res = ai_inline_prompt(req)
        self.assertEqual(res["status"], "ok")
        self.assertIn("return a + b", res["code"])

    def test_ai_inline_prompt_vacio_falla(self):
        from fastapi import HTTPException
        req = AIInlinePromptRequest(prompt="")
        with self.assertRaises(HTTPException) as ctx:
            ai_inline_prompt(req)
        self.assertEqual(ctx.exception.status_code, 400)

    @patch("app.ai_engine.generate_response")
    def test_ai_inline_prompt_ollama_desconectado(self, mock_generate):
        from fastapi import HTTPException
        mock_generate.side_effect = ConnectionError("Failed to establish a new connection: Connection refused")

        req = AIInlinePromptRequest(
            prompt="crear funcion",
            file_path="test.py",
            file_content="x = 1",
            line_number=1
        )
        with self.assertRaises(HTTPException) as ctx:
            ai_inline_prompt(req)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("Ollama no está en marcha", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()


