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

    def test_guardar_y_volver_a_automatico(self):
        r = app.update_ai_config(app.AIConfigUpdateRequest(modelo_codigo="codigo:7b", modelo_autocompletar="chico:1.5b"))
        self.assertEqual((r["modelo_codigo"], r["modelo_autocompletar"]), ("codigo:7b", "chico:1.5b"))
        r = app.update_ai_config(app.AIConfigUpdateRequest(modelo_codigo=""))
        self.assertEqual(r["modelo_codigo"], "")
        self.assertEqual(r["modelo_autocompletar"], "chico:1.5b")


# El modelo de «Prig//:» y el del autocompletado: servidor de Rust (prig-server/tests/asistente_tests.rs)


if __name__ == "__main__":
    unittest.main()
