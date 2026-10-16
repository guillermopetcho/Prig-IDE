import os
import sys
import unittest
from fastapi.testclient import TestClient

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import sql_service
from app import app


class TestSQLStudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.test_db = "test_sql_unit"

    def test_01_databases_list(self):
        res = self.client.get("/api/sql/databases")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertIsInstance(data.get("databases"), list)

    def test_02_create_database(self):
        res = self.client.post("/api/sql/databases/create", json={"nombre": self.test_db})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("nombre"), self.test_db)

    def test_03_seed_and_tables(self):
        # Sembrar datos de ejemplo en la BD de pruebas
        res_seed = self.client.post("/api/sql/seed", json={"db": self.test_db, "sql": ""})
        self.assertEqual(res_seed.status_code, 200)
        self.assertTrue(res_seed.json().get("success"))

        # Listar tablas
        res_tables = self.client.get(f"/api/sql/tables?db={self.test_db}")
        self.assertEqual(res_tables.status_code, 200)
        tables_data = res_tables.json()
        self.assertTrue(tables_data.get("success"))
        nombres = [t["nombre"] for t in tables_data.get("tables", [])]
        self.assertIn("usuarios", nombres)
        self.assertIn("productos", nombres)
        self.assertIn("pedidos", nombres)
        self.assertIn("metricas_ia", nombres)
        self.assertIn("logs_actividad", nombres)

    def test_04_schema_inspection(self):
        res = self.client.get(f"/api/sql/schema?db={self.test_db}&table=usuarios")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("table"), "usuarios")
        campos = [c["campo"] for c in data.get("columns", [])]
        self.assertIn("id", campos)
        self.assertIn("username", campos)
        self.assertIn("email", campos)

    def test_05_query_select(self):
        res = self.client.post("/api/sql/query", json={
            "db": self.test_db,
            "sql": "SELECT id, username, rol FROM usuarios WHERE activo = 1 ORDER BY id ASC;"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("columns"), ["id", "username", "rol"])
        self.assertGreaterEqual(len(data.get("rows", [])), 1)

    def test_06_mysql_dialect_compatibility(self):
        # SHOW TABLES
        res_show = self.client.post("/api/sql/query", json={
            "db": self.test_db,
            "sql": "SHOW TABLES"
        })
        self.assertEqual(res_show.status_code, 200)
        data_show = res_show.json()
        self.assertTrue(data_show.get("success"))
        self.assertIn(f"Tables_in_{self.test_db}", data_show.get("columns", []))

        # DESCRIBE
        res_desc = self.client.post("/api/sql/query", json={
            "db": self.test_db,
            "sql": "DESCRIBE productos"
        })
        self.assertEqual(res_desc.status_code, 200)
        data_desc = res_desc.json()
        self.assertTrue(data_desc.get("success"))
        self.assertIn("Field", data_desc.get("columns", []))


if __name__ == "__main__":
    unittest.main()

