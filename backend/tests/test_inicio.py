"""
Pantalla de Inicio: perfil editable, línea de tiempo de actividad y resumen tolerante.

  · el perfil se valida (nombre recortado, nivel conocido, favoritas acotadas) y se
    guarda aparte, sin tocar nada del usuario en las pruebas;
  · la actividad mezcla desafíos, lecturas de Kaggle, colecciones, descargas y
    ejercicios, ordenada por fecha, con a dónde lleva cada una;
  · si un bloque falla (Ollama apagado, sin sensores…) el resto llega igual;
  · la tira de la semana tiene siempre 7 días, hoy el último;
  · el endpoint /api/inicio responde con todos los bloques.
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import inicio  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.entorno = mock.patch.dict(os.environ, {"PRIG_INICIO_ARCHIVO": os.path.join(self.tmp, "inicio.json")})
        self.entorno.start()

    def tearDown(self):
        self.entorno.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestPerfil(Base):
    def test_valores_por_defecto_y_guardado(self):
        p = inicio.perfil()
        self.assertEqual((p["nombre"], p["nivel"], p["mostrar_al_abrir"]), ("", "principiante", True))
        p = inicio.guardar_perfil({"nombre": "  Ana   María ", "nivel": "experto", "objetivo": "x" * 500,
                                   "mostrar_al_abrir": False, "favoritas": [f"c{i}" for i in range(20)], "raro": 1})
        self.assertEqual(p["nombre"], "Ana María")
        self.assertEqual(p["nivel"], "principiante")          # «experto» no existe
        self.assertEqual(len(p["objetivo"]), 300)
        self.assertEqual(len(p["favoritas"]), 12)
        self.assertFalse(p["mostrar_al_abrir"])
        self.assertNotIn("raro", inicio.perfil())
        self.assertEqual(inicio.perfil()["nombre"], "Ana María")
        inicio.guardar_perfil({"nivel": "avanzado"})
        self.assertEqual((inicio.perfil()["nivel"], inicio.perfil()["nombre"]), ("avanzado", "Ana María"))


class TestActividad(Base):
    def test_mezcla_y_ordena(self):
        historial = [{"id": "d1", "titulo": "Pila", "estado": "resuelto", "mejor": {"pasados": 4, "total": 4},
                      "intentos": 2, "conceptos": ["clases"], "actualizado": "2026-09-10T10:00:00"},
                     {"id": "d2", "titulo": "Colas", "estado": "en_curso", "creado": "2026-09-12T09:00:00"}]
        lecturas = [{"ref": "a/b", "titulo": "EDA", "leidas": 3, "total": 10, "ultima": "2026-09-11T12:00:00", "ultima_celda": 4}]
        colecciones = [{"tipo": "dataset", "ref": "y/t", "titulo": "Titanic", "coleccion": "ML", "anadido": "2026-09-13T08:00:00"}]
        descargas = [{"nombre": "titanic", "tipo": "competicion", "ref": "titanic", "relativa": "kaggle_datos/titanic", "fecha": "2026-09-09T08:00:00"},
                     {"nombre": "suelto", "tipo": None, "ref": "suelto", "fecha": None}]
        ejercicios = [{"ejercicio": "e1", "concepto": "bucles", "fecha": "2026-09-14 10:00:00", "envios": 3, "resuelto": True}]
        ev = inicio.actividad({}, historial, lecturas, colecciones, descargas, ejercicios)
        self.assertEqual([e["tipo"] for e in ev], ["ejercicio", "coleccion", "desafio", "kaggle", "desafio", "datos"])
        self.assertEqual(ev[1]["texto"], "Guardaste el dataset «Titanic»")
        self.assertEqual(ev[2]["abrir"], {"desafio": "d2"})
        self.assertEqual(ev[3]["abrir"]["kaggle"], {"tipo": "notebook", "ref": "a/b", "celda": 4})
        self.assertIn("4/4 pruebas", ev[4]["detalle"])
        self.assertTrue(ev[4]["texto"].startswith("Resolviste"))
        self.assertEqual(len(inicio.actividad({}, historial * 20, [], [], [], [], n=5)), 5)

    def test_semana(self):
        hoy = date.today().isoformat()
        s = inicio.semana({hoy: 4})
        self.assertEqual(len(s), 7)
        self.assertEqual((s[-1]["fecha"], s[-1]["n"]), (hoy, 4))
        self.assertEqual(sum(d["n"] for d in s), 4)


class TestResumen(Base):
    def test_un_bloque_roto_no_tira_el_resto(self):
        def roto():
            raise RuntimeError("Ollama apagado")
        r = inicio.resumen({"progreso": lambda: {"racha": {"actual": 3}, "actividad": {}}, "modelos": roto,
                            "gemini": lambda: {"configurado": False}, "lecturas": lambda: []})
        self.assertEqual(r["errores"], {"modelos": "Ollama apagado"})
        self.assertEqual(r["modelos"], [])
        self.assertEqual(r["progreso"]["racha"], {"actual": 3})
        self.assertEqual(r["gemini"], {"configurado": False})
        self.assertIsNone(r["sistema"])                         # fuente que no se dio
        self.assertEqual(len(r["semana"]), 7)

    def test_endpoint(self):
        from fastapi.testclient import TestClient
        import app as prig
        with mock.patch.object(prig.gestor_modelos, "instalados", return_value=[{"nombre": "m", "bytes": 1}]), \
                mock.patch.object(prig.gestor_modelos, "cargados", return_value=[]):
            cliente = TestClient(prig.app)
            r = cliente.get("/api/inicio")
            self.assertEqual(r.status_code, 200)
            d = r.json()
            for clave in ("perfil", "progreso", "semana", "actividad", "modelos", "sistema", "proyecto", "kaggle", "errores"):
                self.assertIn(clave, d)
            self.assertEqual(d["modelos"], [{"nombre": "m", "bytes": 1}])
            r = cliente.patch("/api/inicio/perfil", json={"nombre": "Prueba", "mostrar_al_abrir": False})
            self.assertEqual((r.json()["nombre"], r.json()["mostrar_al_abrir"]), ("Prueba", False))
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "inicio.json")))


if __name__ == "__main__":
    unittest.main()
