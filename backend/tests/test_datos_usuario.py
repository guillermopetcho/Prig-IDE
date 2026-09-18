"""
Migraciones, biblioteca y almacén de ejercicios: los tres sitios donde un fallo
se lleva por delante el historial del usuario en vez de dar un error visible.
"""
import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import schema_migrations as M          # noqa: E402
from book_service import BookService   # noqa: E402
from exercise_store import ExerciseStore  # noqa: E402


class TestMigraciones(unittest.TestCase):
    def test_documento_sin_marca_es_v1(self):
        self.assertEqual(M.detect_version({}, "seguimiento"), 1)

    def test_migra_y_siembra_fechas_de_completado(self):
        doc = {"id": "s1", "goal": "g", "completed_blocks": ["b1", "b2"],
               "created_at": "2026-01-05T10:00:00"}
        migrado, cambio = M.migrate("seguimiento", doc)
        self.assertTrue(cambio)
        self.assertEqual(migrado["schema_version"], M.CURRENT_VERSIONS["seguimiento"])
        self.assertEqual(migrado["completion_dates"]["b1"], "2026-01-05T10:00:00")

    def test_no_remigra_lo_que_ya_esta_al_dia(self):
        doc = {"schema_version": M.CURRENT_VERSIONS["seguimiento"], "completed_blocks": []}
        _, cambio = M.migrate("seguimiento", doc)
        self.assertFalse(cambio)

    def test_documento_mas_nuevo_no_se_degrada(self):
        with self.assertRaises(M.MigrationError):
            M.migrate("seguimiento", {"schema_version": 999})

    def test_migracion_ausente_falla_explicitamente(self):
        original = M.CURRENT_VERSIONS["seguimiento"]
        M.CURRENT_VERSIONS["seguimiento"] = original + 3
        try:
            with self.assertRaises(M.MigrationError):
                M.migrate("seguimiento", {"schema_version": original})
        finally:
            M.CURRENT_VERSIONS["seguimiento"] = original

    def test_carga_desde_disco_deja_respaldo(self):
        d = tempfile.mkdtemp()
        try:
            ruta = os.path.join(d, "seg.json")
            json.dump({"id": "s1", "goal": "g", "completed_blocks": ["b1"],
                       "created_at": "2026-01-05T10:00:00"}, open(ruta, "w"))
            M.load_migrated(ruta, "seguimiento")
            self.assertTrue(os.path.exists(ruta + ".v1.bak"), "debe respaldar antes de migrar")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestBiblioteca(unittest.TestCase):
    def setUp(self):
        self.lib = tempfile.mkdtemp(prefix="prig_test_lib_")
        self.bs = BookService(self.lib)

    def tearDown(self):
        shutil.rmtree(self.lib, ignore_errors=True)

    def test_un_archivo_roto_no_vacia_la_biblioteca(self):
        open(os.path.join(self.lib, "books", "bueno.md"), "w").write("# ok")
        os.symlink(os.path.join(self.lib, "no_existe.md"),
                   os.path.join(self.lib, "books", "roto.md"))
        nombres = [i["filename"] for i in self.bs.list_books()]
        self.assertIn("bueno.md", nombres)

    def test_titulo_nunca_es_nulo(self):
        ruta = os.path.join(self.lib, "books", "sin_titulo.md")
        open(ruta, "w").write("# x")
        self.bs.save_metadata(ruta, {"category": "BOOKS"})   # ficha sin "title"
        item = [i for i in self.bs.list_books() if i["filename"] == "sin_titulo.md"][0]
        self.assertTrue(item["title"], "un título nulo rompe la búsqueda del frontend")

    def test_homonimos_en_categorias_distintas_no_comparten_ficha(self):
        a = os.path.join(self.lib, "books", "notas.md")
        b = os.path.join(self.lib, "documentation", "notas.md")
        open(a, "w").write("a"); open(b, "w").write("b")
        self.bs.save_metadata(a, {"title": "LIBRO"})
        self.bs.save_metadata(b, {"title": "DOC"})
        self.assertEqual(self.bs.get_metadata(a)["title"], "LIBRO")
        self.assertEqual(self.bs.get_metadata(b)["title"], "DOC")

    def test_no_escapa_de_la_biblioteca(self):
        fuera = tempfile.mkdtemp()
        try:
            victima = os.path.join(fuera, "secreto.txt")
            open(victima, "w").write("privado")
            self.assertIsNone(self.bs._resolve_item(victima))
            self.assertIn("error", self.bs.get_book_content(victima))
        finally:
            shutil.rmtree(fuera, ignore_errors=True)

    def test_no_se_puede_borrar_una_categoria(self):
        self.assertIn("error", self.bs.delete_item("books"))
        self.assertTrue(os.path.isdir(os.path.join(self.lib, "books")))

    def test_borrar_lleva_su_ficha_y_respeta_al_homonimo(self):
        a = os.path.join(self.lib, "books", "notas.md")
        b = os.path.join(self.lib, "documentation", "notas.md")
        open(a, "w").write("a"); open(b, "w").write("b")
        self.bs.save_metadata(a, {"title": "LIBRO"})
        self.bs.save_metadata(b, {"title": "DOC"})
        self.assertTrue(self.bs.delete_item("books/notas.md").get("success"))
        self.assertIsNone(self.bs.get_metadata(a))
        self.assertEqual(self.bs.get_metadata(b)["title"], "DOC")

    def test_la_muestra_no_reaparece_tras_borrarla(self):
        guia = os.path.join(self.lib, "documentation", "Guia_Fundamentos_Deep_Learning.md")
        self.assertTrue(os.path.exists(guia))
        os.remove(guia)
        BookService(self.lib)          # equivale a reiniciar
        self.assertFalse(os.path.exists(guia))


class TestAlmacenEjercicios(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="prig_test_ws_")

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _ejercicio(self, eid="ex_1"):
        return {"exercise_id": eid, "concept": "listas", "title": "T",
                "statement": "S", "function_name": "f",
                "starter_code": "def f():\n    pass",
                "reference_solution": "def f():\n    return 1",
                "tests": "assert f() == 1"}

    def test_sobrevive_al_reinicio(self):
        ExerciseStore(self.ws).save(self._ejercicio())
        recargado = ExerciseStore(self.ws).get("ex_1")
        self.assertIsNotNone(recargado)
        self.assertEqual(recargado["tests"], "assert f() == 1")

    def test_archivo_corrupto_no_impide_arrancar(self):
        os.makedirs(os.path.join(self.ws, ".prig_dataset"), exist_ok=True)
        open(os.path.join(self.ws, ".prig_dataset", "exercises.json"), "w").write("{roto")
        self.assertEqual(ExerciseStore(self.ws).count(), 0)

    def test_poda_los_mas_antiguos(self):
        import exercise_store
        original = exercise_store.MAX_EXERCISES
        exercise_store.MAX_EXERCISES = 3
        try:
            store = ExerciseStore(self.ws)
            for i in range(6):
                e = self._ejercicio(f"ex_{i}")
                e["created_at"] = f"2026-01-0{i + 1}T00:00:00"
                store.save(e)
            self.assertEqual(store.count(), 3)
            self.assertIsNone(store.get("ex_0"), "debe caer el más antiguo")
            self.assertIsNotNone(store.get("ex_5"))
        finally:
            exercise_store.MAX_EXERCISES = original

    def test_la_vista_publica_no_filtra_la_solucion(self):
        from exercise_engine import ExerciseEngine
        publica = ExerciseEngine.public_view(self._ejercicio())
        self.assertNotIn("reference_solution", publica)
        self.assertNotIn("tests", publica)


if __name__ == "__main__":
    unittest.main()
