import os
import unittest
from fastapi.testclient import TestClient

import backend.tests
from backend.app import app


class TestCarrerasAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_obtener_catalogo_carreras(self):
        res = self.client.get("/api/carreras")
        self.assertEqual(res.status_code, 200)
        carreras = res.json()
        self.assertIsInstance(carreras, list)
        self.assertEqual(len(carreras), 2)

        ids = [c["id"] for c in carreras]
        self.assertIn("ingenieria_inteligencia_artificial", ids)
        self.assertIn("licenciatura_programacion", ids)

        # Verificar materias de IIA
        iia = next(c for c in carreras if c["id"] == "ingenieria_inteligencia_artificial")
        self.assertEqual(len(iia["etapas"]), 5)
        total_materias_iia = sum(len(et["materias"]) for et in iia["etapas"])
        self.assertEqual(total_materias_iia, 36)

        # Verificar materias de LPR
        lpr = next(c for c in carreras if c["id"] == "licenciatura_programacion")
        self.assertEqual(len(lpr["etapas"]), 5)
        total_materias_lpr = sum(len(et["materias"]) for et in lpr["etapas"])
        self.assertEqual(total_materias_lpr, 28)

    def test_obtener_materia_markdown(self):
        # Materia válida
        res = self.client.get(
            "/api/carreras/materia",
            params={"archivo": "carreras/ingenieria_inteligencia_artificial/etapa_1_fundamentos/IIA-101-algebra-lineal-y-geometria.md"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("Álgebra Lineal", data.get("contenido", ""))
        self.assertIn("YouTube", data.get("contenido", ""))
        self.assertIn("GitHub", data.get("contenido", ""))

    def test_seguridad_path_traversal(self):
        # Intento de path traversal fuera de carreras/
        res = self.client.get(
            "/api/carreras/materia",
            params={"archivo": "../backend/app.py"}
        )
        self.assertEqual(res.status_code, 404)

        res_inexistente = self.client.get(
            "/api/carreras/materia",
            params={"archivo": "carreras/no_existe.md"}
        )
        self.assertEqual(res_inexistente.status_code, 404)


if __name__ == "__main__":
    unittest.main()
