"""
Modelos por tarea (Configuración global): uno para escribir código, otro para explicar
y otro para rellenar código mientras se escribe.

  · lo que se pide explícitamente manda; si no, el modelo del rol; vacío = automático;
  · Kaggle y GitHub usan el de explicar, Prig//: y los desafíos el de código;
  · el autocompletado respeta el elegido aunque no sepa rellenar al medio;
  · la configuración guarda los roles (también el vacío, para volver a automático).

Nada se escribe en ~/.prig_ai_config.json: se parchea la configuración en memoria.
"""

import os
import sys
import unittest
from unittest import mock

# La carpeta personal temporal la fija tests/__init__.py para toda la suite

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import app  # noqa: E402


class Res:
    status_code = 200

    def __init__(self, datos):
        self.datos = datos

    def json(self):
        return self.datos


class Base(unittest.TestCase):
    def setUp(self):
        self.cfg = mock.patch.dict(app.ai_engine.config, {
            "modelo_codigo": "", "modelo_explicar": "", "modelo_autocompletar": "",
            "agent1_model": "tutor:7b"})
        self.cfg.start()
        self.guardar = mock.patch.object(app.ai_engine, "_save_config")
        self.guardar.start()

    def tearDown(self):
        self.guardar.stop()
        self.cfg.stop()


class TestResolver(Base):
    def test_pedido_rol_y_automatico(self):
        e = app.ai_engine
        self.assertIsNone(e.modelo_para("explicar"))                       # automático
        e.config["modelo_explicar"] = "explica:14b"
        self.assertEqual(e.modelo_para("explicar"), "explica:14b")
        self.assertEqual(e.modelo_para("explicar", "otro:7b"), "otro:7b")  # lo pedido manda
        self.assertEqual(e.modelo_para("explicar", "  "), "explica:14b")
        self.assertIsNone(e.modelo_para("codigo"))
        self.assertEqual(e.modelo_para("modelo_explicar"), "explica:14b")  # también por clave

    def test_kaggle_y_github_explican_desafios_programan(self):
        app.ai_engine.config.update(modelo_explicar="explica:14b", modelo_codigo="codigo:7b")
        self.assertEqual(app._modelo_desafios(None, "explicar"), "explica:14b")
        self.assertEqual(app._modelo_desafios(None, "codigo"), "codigo:7b")
        self.assertEqual(app._modelo_desafios("elegido:3b", "explicar"), "elegido:3b")
        self.assertEqual(app._modelo_desafios(None), "tutor:7b")           # sin rol: el del tutor
        app.ai_engine.config["modelo_explicar"] = ""
        self.assertEqual(app._modelo_desafios(None, "explicar"), "tutor:7b")

    def test_los_endpoints_de_kaggle_y_github_piden_el_rol_explicar(self):
        import inspect
        fuente = inspect.getsource(app)
        for ruta in ("/api/kaggle/explicar", "/api/kaggle/preguntar", "/api/kaggle/guia",
                     "/api/kaggle/explicar_datos", "/api/github/explicar", "/api/github/preguntar"):
            cuerpo = fuente.split(f'@app.post("{ruta}")', 1)[1].split("@app.", 1)[0]
            self.assertIn('"explicar")', cuerpo, ruta)

    def test_guardar_y_volver_a_automatico(self):
        r = app.update_ai_config(app.AIConfigUpdateRequest(modelo_codigo="codigo:7b", modelo_autocompletar="chico:1.5b"))
        self.assertEqual((r["modelo_codigo"], r["modelo_autocompletar"]), ("codigo:7b", "chico:1.5b"))
        r = app.update_ai_config(app.AIConfigUpdateRequest(modelo_codigo=""))
        self.assertEqual(r["modelo_codigo"], "")
        self.assertEqual(r["modelo_autocompletar"], "chico:1.5b")


class TestPrigInline(Base):
    def correr(self, pedido=None):
        enviados = []

        def generar(prompt, model=None, **kw):
            enviados.append(model)
            return iter(["x = 1"])
        with mock.patch.object(app.ai_engine, "generate_response", side_effect=generar), \
                mock.patch.object(app.requests_lib, "get", side_effect=Exception("sin Ollama")):
            app.ai_inline_prompt(app.AIInlinePromptRequest(prompt="una variable", file_content="# Prig//: una variable",
                                                           line_number=1, language="python", model=pedido))
        return enviados[0]

    def test_prig_usa_el_modelo_de_codigo(self):
        self.assertEqual(self.correr(), "tutor:7b")
        app.ai_engine.config["modelo_codigo"] = "codigo:7b"
        self.assertEqual(self.correr(), "codigo:7b")
        self.assertEqual(self.correr("pedido:3b"), "pedido:3b")


class TestAutocompletado(Base):
    def caps(self, tabla):
        return mock.patch.object(app.ai_engine, "capacidades", side_effect=lambda m: tabla.get(m, []))

    def test_elegido_que_rellena_al_medio(self):
        app.ai_engine.config["modelo_autocompletar"] = "chico:1.5b"
        with self.caps({"chico:1.5b": ["completion", "insert"]}), \
                mock.patch.object(app.requests_lib, "post", return_value=Res({"response": "return a + b"})) as post:
            r = app.inline_complete(app.AIInlineCompleteRequest(code_prefix="def f(a, b):\n    ", code_suffix="\n"))
        self.assertEqual(r["modelo"], "chico:1.5b")
        self.assertTrue(r["relleno_al_medio"])
        self.assertEqual(post.call_args.kwargs["json"]["model"], "chico:1.5b")
        self.assertIn("suffix", post.call_args.kwargs["json"])

    def test_elegido_sin_insert_se_respeta(self):
        app.ai_engine.config["modelo_autocompletar"] = "charla:8b"
        usados = []

        def generar(prompt, model=None, **kw):
            usados.append(model)
            return iter(["b)"])
        with self.caps({"charla:8b": ["completion"], "chico:1.5b": ["insert"]}), \
                mock.patch.object(app.ai_engine, "generate_response", side_effect=generar), \
                mock.patch.object(app.requests_lib, "post") as post:
            r = app.inline_complete(app.AIInlineCompleteRequest(code_prefix="print(a, "))
        self.assertEqual(usados, ["charla:8b"])      # no se cambia en silencio por otro
        post.assert_not_called()
        self.assertEqual(r["completion"], "b)")

    def test_automatico_busca_el_mas_pequeno_que_rellena(self):
        tags = Res({"models": [{"name": "grande:14b", "size": 9e9}, {"name": "chico:1.5b", "size": 1e9},
                               {"name": "medio:7b", "size": 4e9}]})
        with self.caps({"grande:14b": ["insert"], "chico:1.5b": ["insert"], "medio:7b": ["completion"]}), \
                mock.patch.object(app.requests_lib, "get", return_value=tags), \
                mock.patch.object(app.requests_lib, "post", return_value=Res({"response": "1"})) as post:
            r = app.inline_complete(app.AIInlineCompleteRequest(code_prefix="x = "))
        self.assertEqual(r["modelo"], "chico:1.5b")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "chico:1.5b")


if __name__ == "__main__":
    unittest.main()
