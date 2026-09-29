"""
Examen del proyecto (examen_proyecto.py): generación desde el banco y corrección automática.
"""

import os
import shutil
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import banco_proyecto as bp
import examen_proyecto as ex

APP = '''from fastapi import FastAPI
import os
app = FastAPI()
LIMITE_GPU = 75
MARGEN_MB = 250.5


def leer_limite(config):
    return config.get("limite_gpu")


def calcular(x):
    return x * int(os.environ.get("FACTOR", "2"))


def servir(config):
    return calcular(leer_limite(config))


@app.get("/api/estado")
def estado():
    return servir({})
'''
JS = '''async function pintar() {
  const d = await fetch('/api/estado');
}
'''


class TestExamen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_examen_")
        raiz = os.path.join(self.tmp, "p")
        for rel, texto in (("app.py", APP), ("web/panel.js", JS)):
            os.makedirs(os.path.dirname(os.path.join(raiz, rel)), exist_ok=True)
            with open(os.path.join(raiz, rel), "w") as f:
                f.write(texto)
        self.banco = bp.BancoProyecto(raiz, carpeta=os.path.join(self.tmp, "banco"))
        self.banco.sincronizar()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_genera_con_respuestas_conocidas(self):
        ps = ex.generar(self.banco)
        por = {p["tipo"]: p for p in ps}
        self.assertEqual(por["config"]["esperado"], ["leer_limite"])
        self.assertEqual(por["entorno"]["esperado"], ["calcular"])
        self.assertEqual(por["endpoint"]["esperado"], ["estado", "app.py"])
        self.assertEqual(por["frontend"]["esperado"], ["pintar"])
        self.assertIn("constante", por)
        self.assertEqual(len(ex.cargar(self.banco)), len(ps))            # queda guardado y fijo

    def test_corregir(self):
        p = {"esperado": ["Motor.asegurar", "ai_chat"], "evaluar": "conjunto"}
        self.assertEqual(ex.corregir(p, "La llaman `asegurar` y ai_chat.")["puntaje"], 1.0)
        self.assertEqual(ex.corregir(p, "Solo ai_chat_v2.")["puntaje"], 0.0)          # palabra entera
        v = {"esperado": ["0.08"], "evaluar": "valor"}
        self.assertEqual(ex.corregir(v, "Vale 0,08 (equilibrado).")["puntaje"], 1.0)
        self.assertEqual(ex.corregir(v, "Vale 0.1")["puntaje"], 0.0)
        r = {"esperado": ["backend/recursos/frio.py"], "evaluar": "ruta"}
        self.assertEqual(ex.corregir(r, "Está en `frio.py`.")["puntaje"], 1.0)
        e = {"esperado": ["GET /api/banco/conocimiento/*"], "evaluar": "endpoints"}
        self.assertEqual(ex.corregir(e, "Afecta a /api/banco/conocimiento/{id}.")["puntaje"], 1.0)
        t = {"esperado": ["banco_mapa", "backend/app.py"], "evaluar": "todos"}
        self.assertEqual(ex.corregir(t, "`banco_mapa` en app.py")["puntaje"], 1.0)

    def test_inventos(self):
        conocidos = ex.nombres_conocidos(self.banco)
        p = {"esperado": ["calcular"], "evaluar": "conjunto"}
        nota = ex.corregir(p, "La llama `servir` y también `calcular_todo_rapido()`.", conocidos)
        self.assertEqual(nota["inventos"], ["calcular_todo_rapido"])

    def test_correr(self):
        ex.generar(self.banco)
        r = ex.correr(self.banco, "eco", lambda texto: ("leer_limite calcular estado app.py pintar 75 250.5", {}))
        self.assertGreater(r["puntaje"], 0.5)
        self.assertIn("config", r["por_tipo"])


if __name__ == "__main__":
    unittest.main()
