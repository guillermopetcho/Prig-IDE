"""
Pruebas integrales para el Motor de Aprendizaje por Grafo de Nodos (DAG).
Verifica topología, niveles (Junior a Senior), articulación de las 4 herramientas
(YouTube, GitHub, Kaggle, Prig Hub), ejecución determinista de tareas pre-respondidas
y endpoints de la API.
"""

import os
import sys
import unittest
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_aprendizaje_nodos import MotorAprendizajeNodos
from fastapi.testclient import TestClient
from app import app


class PruebaMotorAprendizajeNodos(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.motor = MotorAprendizajeNodos(workspace_dir=self.tmp_dir)
        self.cliente = TestClient(app)

    def tearDown(self):
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_topologia_y_consistencia_dag(self):
        """Verifica que el grafo contenga nodos y que las relaciones de prerrequisito sean consistentes."""
        self.assertGreaterEqual(len(self.motor.nodos), 4)
        
        # Verificar que todos los prerrequisitos y siguientes existan
        for nid, nodo in self.motor.nodos.items():
            for prereq in nodo.get("prerrequisitos", []):
                self.assertIn(prereq, self.motor.nodos, f"Prerrequisito '{prereq}' en nodo '{nid}' no existe")
            for sig in nodo.get("siguientes", []):
                self.assertIn(sig, self.motor.nodos, f"Nodo siguiente '{sig}' en nodo '{nid}' no existe")

    def test_cobertura_niveles_junior_a_senior(self):
        """Verifica que existan nodos en toda la escala pedagógica."""
        niveles_presentes = set(n["nivel"] for n in self.motor.nodos.values())
        self.assertIn("junior", niveles_presentes)
        self.assertIn("intermedio", niveles_presentes)
        self.assertIn("avanzado", niveles_presentes)
        self.assertIn("senior", niveles_presentes)

    def test_integracion_4_pilares_educativos(self):
        """Cada nodo debe articular YouTube, GitHub, Kaggle y Prig Hub."""
        for nid, nodo in self.motor.nodos.items():
            herrs = nodo.get("herramientas", {})
            self.assertIn("youtube", herrs, f"Nodo {nid} sin sección YouTube")
            self.assertIn("github", herrs, f"Nodo {nid} sin sección GitHub")
            self.assertIn("kaggle", herrs, f"Nodo {nid} sin sección Kaggle")
            self.assertIn("prig_hub", herrs, f"Nodo {nid} sin sección Prig Hub")

            yt = herrs["youtube"]
            self.assertTrue(yt.get("video_id"), f"Nodo {nid} sin video_id")
            self.assertTrue(yt.get("marcas_de_tiempo"), f"Nodo {nid} sin marcas_de_tiempo")

            gh = herrs["github"]
            self.assertTrue(gh.get("repositorio"), f"Nodo {nid} sin repositorio")

            kg = herrs["kaggle"]
            self.assertTrue(kg.get("dataset_slug"), f"Nodo {nid} sin dataset_slug")

            hub = herrs["prig_hub"]
            self.assertTrue(hub.get("pack_id"), f"Nodo {nid} sin pack_id")

    def test_marcos_teoricos_rigurosos(self):
        """Cada nodo debe incluir resumen, principios nucleares y fórmulas o axiomas formales."""
        for nid, nodo in self.motor.nodos.items():
            mt = nodo.get("marco_teorico", {})
            self.assertTrue(mt.get("resumen"), f"Nodo {nid} sin resumen teórico")
            self.assertGreaterEqual(len(mt.get("principios_nucleares", [])), 2, f"Nodo {nid} con insuficientes principios")
            self.assertTrue(mt.get("formulas_o_axiomas"), f"Nodo {nid} sin formulas_o_axiomas")

    def test_ejecucion_tareas_prerespondidas_referencia(self):
        """Verifica que la solución de referencia de cada nodo supere sus propias pruebas unitarias."""
        for nid, nodo in self.motor.nodos.items():
            res = self.motor.ejecutar_tarea(nodo_id=nid, codigo_usuario="", usar_solucion=True)
            self.assertTrue(res.get("ok"), f"La solución de referencia falló en {nid}: {res.get('error')}")
            self.assertLess(res.get("tiempo_ms", 9999), 3000, f"Ejecución en {nid} tardó más de 3 segundos")

    def test_ejecucion_codigo_incorrecto_falla(self):
        """Verifica que un código defectuoso del usuario falle controladamente."""
        codigo_defectuoso = "def analizar_tipos(datos): return {'inmutables': 0, 'mutables': 0, 'cadenas': []}"
        res = self.motor.ejecutar_tarea(nodo_id="nodo-py-01-fundamentos-sintaxis", codigo_usuario=codigo_defectuoso, usar_solucion=False)
        self.assertFalse(res.get("ok"))
        self.assertIn("AssertionError", res.get("error", ""))

    def test_abrir_en_editor_genera_archivos(self):
        """Verifica la generación de la estructura de archivos en aprendizaje/<nodo_id>/."""
        nid = "nodo-py-01-fundamentos-sintaxis"
        res = self.motor.abrir_en_editor(nid)
        self.assertTrue(res.get("ok"))
        
        carpeta = os.path.join(self.tmp_dir, "aprendizaje", nid)
        self.assertTrue(os.path.isdir(carpeta))
        self.assertTrue(os.path.isfile(os.path.join(carpeta, "ejercicio.py")))
        self.assertTrue(os.path.isfile(os.path.join(carpeta, "test_ejercicio.py")))
        self.assertTrue(os.path.isfile(os.path.join(carpeta, "MARCO_TEORICO.md")))
        self.assertTrue(os.path.isfile(os.path.join(carpeta, "SOLUCION_PRE_RESPONDIDA.md")))

    def test_busqueda_instantanea(self):
        """Verifica que la búsqueda por texto responda rápidamente con resultados pertinentes."""
        res_trans = self.motor.buscar("transformers atencion", limite=5)
        self.assertTrue(any("deep-learning" in n["id"] for n in res_trans))

        res_titanic = self.motor.buscar("titanic pandas", limite=5)
        self.assertTrue(len(res_titanic) > 0)

    def test_api_endpoints_fastapi(self):
        """Prueba los endpoints HTTP expuestos por la API de Prig."""
        # 1. GET /api/aprendizaje/grafo
        r = self.cliente.get("/api/aprendizaje/grafo")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data.get("ok"))
        self.assertGreaterEqual(len(data.get("nodos", [])), 4)

        # 2. GET /api/aprendizaje/nodo/{id}
        r_nodo = self.cliente.get("/api/aprendizaje/nodo/nodo-py-01-fundamentos-sintaxis")
        self.assertEqual(r_nodo.status_code, 200)
        data_nodo = r_nodo.json()
        self.assertTrue(data_nodo.get("ok"))
        self.assertEqual(data_nodo["nodo"]["id"], "nodo-py-01-fundamentos-sintaxis")

        # 3. GET /api/aprendizaje/buscar
        r_busq = self.cliente.get("/api/aprendizaje/buscar?q=python")
        self.assertEqual(r_busq.status_code, 200)
        self.assertTrue(r_busq.json().get("ok"))

        # 4. POST /api/aprendizaje/nodo/{id}/ejecutar
        r_ejec = self.cliente.post(
            "/api/aprendizaje/nodo/nodo-py-01-fundamentos-sintaxis/ejecutar",
            json={"codigo": "", "usar_solucion": True}
        )
        self.assertEqual(r_ejec.status_code, 200)
        self.assertTrue(r_ejec.json().get("ok"))

        # 5. GET /api/aprendizaje/estadisticas
        r_stats = self.cliente.get("/api/aprendizaje/estadisticas")
        self.assertEqual(r_stats.status_code, 200)
        self.assertTrue(r_stats.json().get("ok"))


if __name__ == "__main__":
    unittest.main()

