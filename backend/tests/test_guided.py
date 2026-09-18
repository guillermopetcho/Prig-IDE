"""
Aprendizaje Guiado: migración y CONTRATO de las respuestas.

El fallo que motivó estos tests fue de forma, no de lógica: /api/guided/list empezó
a devolver {"paths": [...]} y el frontend seguía tratándolo como un array. Nada
lanzaba en el backend, así que ningún test lo habría visto; por eso aquí se afirma
la ESTRUCTURA que el frontend consume, no solo que la petición responda 200.
"""
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study_plan_engine import (  # noqa: E402
    StudyPlanEngine, SeguimientoPath, SeguimientoBlock,
    PracticalCurriculum, PracticalModule,
)
from guided_learning import GuidedLearningService  # noqa: E402


class _AIFalsa:
    """ Evita depender de Ollama: los tests de contrato no deben necesitar un modelo """
    def run_topic_organizer(self, goal, topics, level="Intermedio", focus="Práctico", model=""):
        return {"goal": goal, "rationale": "r", "blocks": [
            {"title": "Bloque 1", "description": "d", "topics": ["t1"]},
            {"title": "Bloque 2", "description": "d", "topics": ["t2"]},
        ]}


class _LibrosFalsos:
    def list_books(self):
        return []


class TestAprendizajeGuiado(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="prig_test_ws_")
        self.svc = GuidedLearningService(self.ws, _AIFalsa(), _LibrosFalsos())

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    # ---------- Contrato de las respuestas ----------

    def test_list_paths_devuelve_una_lista(self):
        self.assertIsInstance(self.svc.list_paths(), list)

    def test_cada_ruta_trae_lo_que_pinta_la_interfaz(self):
        self.svc.generate_fast("Meta", "a, b")
        fila = self.svc.list_paths()[0]
        for campo in ("id", "goal", "created_at", "progress"):
            self.assertIn(campo, fila, f"la interfaz pinta {campo} en la lista")
        self.assertIsInstance(fila["progress"], (int, float))
        self.assertTrue(fila["created_at"], "una fecha vacía se pinta como 'Invalid Date'")

    def test_la_ruta_generada_trae_los_campos_del_lienzo(self):
        ruta = self.svc.generate_fast("Meta", "a, b").model_dump()
        for campo in ("id", "goal", "blocks", "completed_blocks", "source"):
            self.assertIn(campo, ruta)
        self.assertTrue(all("block_id" in b and "title" in b for b in ruta["blocks"]))

    def test_modo_rapido_se_marca_como_tal(self):
        self.assertEqual(self.svc.generate_fast("Meta", "a").source, "rapido")

    # ---------- Migración ----------

    def _plan_antiguo(self, meta="Álgebra", con_progreso=True):
        eng = StudyPlanEngine(self.ws)
        est = eng.create_new_plan(meta)
        est.practical_curriculum = PracticalCurriculum(curriculum_id="c1", modules=[
            PracticalModule(module_id="mod_01", name="Vectores", objective="Operar",
                            validation_criteria=["criterio"]),
            PracticalModule(module_id="mod_02", name="Matrices", objective="Multiplicar",
                            validation_criteria=["criterio"]),
        ])
        if con_progreso:
            est.completed_validation_criteria = {"mod_01": ["criterio"]}
        eng.save_state(est)
        return est

    def test_migracion_conserva_el_progreso(self):
        self._plan_antiguo()
        res = self.svc.migrate_legacy_plans()
        self.assertEqual(len(res["migrated"]), 1)

        ruta = self.svc.get(res["migrated"][0]["path_id"])
        self.assertEqual(ruta.source, "migrado")
        self.assertEqual([b.title for b in ruta.blocks], ["Vectores", "Matrices"])
        self.assertIn("blk_mod_01", ruta.completed_blocks)
        self.assertNotIn("blk_mod_02", ruta.completed_blocks)
        self.assertTrue(ruta.completion_dates, "el mapa de calor necesita la fecha")

    def test_migrar_dos_veces_no_duplica(self):
        self._plan_antiguo()
        self.svc.migrate_legacy_plans()
        segunda = self.svc.migrate_legacy_plans()
        self.assertEqual(len(segunda["migrated"]), 0)
        self.assertEqual(len(self.svc.list_paths()), 1)

    def test_plan_sin_curriculo_no_se_pierde(self):
        eng = StudyPlanEngine(self.ws)
        eng.save_state(eng.create_new_plan("Meta suelta"))
        self.svc.migrate_legacy_plans()
        ruta = self.svc.list_paths()[0]
        self.assertEqual(ruta["goal"], "Meta suelta")

    # ---------- Convivencia y borrado ----------

    def test_rutas_de_los_tres_origenes_conviven(self):
        self.svc.generate_fast("Rápida", "x")
        self._plan_antiguo("Migrada")
        self.svc.repo.save(SeguimientoPath(id="seg_previa", goal="Previa", blocks=[
            SeguimientoBlock(title="b", description="d", topics=["t"])
        ]))
        self.svc.migrate_legacy_plans()
        metas = {p["goal"] for p in self.svc.list_paths()}
        self.assertEqual(metas, {"Rápida", "Migrada", "Previa"})

    def test_borrar_una_ruta(self):
        ruta = self.svc.generate_fast("Meta", "a")
        self.assertTrue(self.svc.delete(ruta.id))
        self.assertIsNone(self.svc.get(ruta.id))
        self.assertFalse(self.svc.delete(ruta.id))

    def test_ruta_inexistente_devuelve_none(self):
        self.assertIsNone(self.svc.get("seg_fantasma"))

    def test_generate_fast_stream_emite_etapas_y_done(self):
        eventos = list(self.svc.generate_fast_stream("Meta Streaming", "t1, t2"))
        tipos = [e.get("type") for e in eventos]
        self.assertIn("stage", tipos)
        self.assertIn("done", tipos)
        done_event = [e for e in eventos if e.get("type") == "done"][0]
        self.assertIn("path", done_event)
        self.assertEqual(done_event["path"]["goal"], "Meta Streaming")


    def test_endpoint_cancel_guided(self):
        from fastapi.testclient import TestClient
        from app import app
        client = TestClient(app)
        res = client.post("/api/guided/cancel")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "cancelled")
        self.assertIn("active_requests_cancelled", data)

    def test_endpoint_generate_stream_empty_topics(self):
        from fastapi.testclient import TestClient
        from app import app
        import json
        client = TestClient(app)
        res = client.post("/api/guided/generate/stream", json={
            "goal": "Aprender Rust",
            "topics": "   ",
            "mode": "rapido"
        })
        self.assertEqual(res.status_code, 200)
        first_line = res.iter_lines().__next__()
        data = json.loads(first_line)
        self.assertEqual(data.get("type"), "error")
        self.assertIn("lista de temas", data.get("message", ""))



if __name__ == "__main__":
    unittest.main()
