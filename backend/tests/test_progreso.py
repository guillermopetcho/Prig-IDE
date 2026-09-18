"""
Avance del alumno: historial completo, dominio por concepto y qué sigue.

Con desafíos de mentira fechados a propósito, porque lo que se protege son las cuentas
que ve el usuario en el Perfil:

  · el historial trae todo lo que hizo (origen, bloque del plan, intentos, pistas, tiempo);
  · el dominio solo lo dan los desafíos comprobados ejecutando pruebas, baja con las
    pistas y con rendirse, y se olvida con el tiempo;
  · la racha cuenta días seguidos y no se rompe por mirar el perfil un día suelto;
  · «qué sigue» mezcla lo dejado a medias, los conceptos flojos y los bloques pendientes;
  · el contexto que se le manda al modelo son datos, no interpretaciones;
  · el análisis se guarda y se reaprovecha mientras no haya desafíos nuevos.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import progreso
from desafios.almacen import Almacen
from desafios import tutor
from tests.test_desafios import ModeloFalso


class GuidedFalso:
    def __init__(self, completados=("blk_listas",)):
        self.completados = list(completados)

    def list_paths(self):
        return [{"id": "seg_x"}]

    def get(self, path_id):
        if path_id != "seg_x":
            return None
        bloque = lambda bid, t, temas: type("B", (), {"block_id": bid, "title": t, "topics": temas})()
        return type("R", (), {"id": "seg_x", "goal": "Estructuras de datos", "level": "Intermedio",
                              "blocks": [bloque("blk_listas", "Listas", ["listas"]), bloque("blk_pilas", "Pilas", ["pila"])],
                              "completed_blocks": self.completados})()


class _ConDesafios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_progreso_")
        self.env = mock.patch.dict(os.environ, {"PRIG_DESAFIOS_DIR": self.tmp})
        self.env.start()
        self.almacen = Almacen()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def crear(self, titulo, conceptos, estado, intentos=1, pistas=0, pasos=0, dias=0, verificable=True,
              origen=None, segundos=None, plan=""):
        cuando = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
        d = self.almacen.guardar({
            "titulo": titulo, "conceptos": conceptos, "nivel": "intermedio",
            "comprobacion": {"tipo": "asserts" if verificable else "ninguna"},
            "origen": origen or {"tipo": "modelo", "nombre": "Modelo"},
            "paginas": [{"nombre": "a.py", "contenido": ""}],
            "privado": {"referencia": [{"nombre": "a.py", "contenido": "secreto"}]},
            "progreso": {"estado": estado, "intentos": intentos, "pistas": pistas, "pasos_vistos": pasos, "plan": plan,
                         "mejor": {"pasados": 3 if estado == "resuelto" else 1, "total": 3},
                         "historial": [{"cuando": cuando, "aprobado": estado == "resuelto", "pasados": 3, "total": 3}],
                         "empezado": cuando, "resuelto": cuando if estado == "resuelto" else None,
                         "rendido": cuando if estado == "rendido" else None, "segundos_hasta_resolver": segundos}})
        guardado = self.almacen.obtener(d["id"])
        guardado["creado"] = guardado["actualizado"] = cuando
        with open(self.almacen._ruta(d["id"]), "w", encoding="utf-8") as f:
            json.dump(guardado, f)
        return d["id"]

    def poblar(self):
        self.ids = {
            "binaria": self.crear("Búsqueda binaria", ["searches", "bucles"], "resuelto", intentos=3, pasos=6, segundos=900),
            "pila": self.crear("Pila con clases", ["clases", "pila"], "resuelto", dias=1, segundos=400, plan="mi plan"),
            "recursion": self.crear("Recursión difícil", ["recursion"], "rendido", intentos=5, pistas=3, dias=2),
            "dicts": self.crear("Diccionarios", ["dicts"], "en_curso", intentos=2, pistas=1, dias=3),
            "euler": self.crear("Euler 15", ["maths"], "nuevo", verificable=False, dias=40),
            "plan": self.crear("Del plan", ["pila"], "resuelto", intentos=2, dias=4, segundos=600,
                               origen={"tipo": "plan", "nombre": "Plan de estudios", "ruta_id": "seg_x",
                                       "bloque_id": "blk_pilas", "bloque": "Pilas"}),
        }


class PruebaHistorial(_ConDesafios):

    def test_trae_todo_lo_que_hizo_el_alumno(self):
        self.poblar()
        filas = {f["titulo"]: f for f in progreso.historial(self.almacen)}
        self.assertEqual(len(filas), 6)
        b = filas["Búsqueda binaria"]
        self.assertEqual((b["estado"], b["intentos"], b["pasos_razonamiento"], b["segundos"]), ("resuelto", 3, 6, 900))
        self.assertEqual(filas["Pila con clases"]["plan_escrito"], True)
        self.assertEqual(filas["Del plan"]["bloque"], "Pilas")
        self.assertEqual(filas["Del plan"]["ruta_id"], "seg_x")
        self.assertFalse(filas["Euler 15"]["verificable"])
        self.assertNotIn("secreto", json.dumps(list(filas.values())))       # ni referencia ni pruebas

    def test_filtros_y_orden(self):
        self.poblar()
        self.assertEqual(len(progreso.historial(self.almacen, estado="resuelto")), 3)
        self.assertEqual(len(progreso.historial(self.almacen, fuente="plan")), 1)
        self.assertEqual([f["titulo"] for f in progreso.historial(self.almacen, concepto="Clases")], ["Pila con clases"])
        self.assertEqual(len(progreso.historial(self.almacen, concepto="recursión")), 1)   # tildes y mayúsculas dan igual
        self.assertEqual(progreso.historial(self.almacen)[0]["titulo"], "Búsqueda binaria")  # lo más reciente primero
        self.assertEqual(len(progreso.historial(self.almacen, limite=2)), 2)


class PruebaDominio(_ConDesafios):

    def test_formula(self):
        self.assertEqual(progreso._dominio(0, 0, 0, None), 0)
        self.assertEqual(progreso._dominio(2, 2, 0, 0), 100)
        self.assertEqual(progreso._dominio(2, 1, 0, 0), 50)
        self.assertEqual(progreso._dominio(2, 2, 2, 0), 92)          # dos pistas en dos desafíos: −8
        self.assertEqual(progreso._dominio(1, 1, 0, 70), 90)         # diez semanas sin tocarlo: −10
        self.assertEqual(progreso._dominio(1, 1, 0, 3650), 80)       # el olvido no baja de −20

    def test_por_concepto(self):
        self.poblar()
        c = {x["concepto"]: x for x in progreso.conceptos(progreso.historial(self.almacen))}
        self.assertEqual(c["clases"]["dominio"], 100)
        self.assertEqual(c["pila"]["vistos"], 2)
        self.assertEqual(c["recursion"]["dominio"], 0)               # rendirse no es dominar
        self.assertEqual(c["recursion"]["rendidos"], 1)
        self.assertNotIn("maths", c)                                  # sin pruebas no se mide dominio
        orden = [x["concepto"] for x in progreso.conceptos(progreso.historial(self.almacen))]
        self.assertEqual(orden[:2], ["recursion", "dicts"])            # primero lo más flojo


class PruebaResumen(_ConDesafios):

    def test_racha(self):
        hoy = datetime.now().date()
        dias = {(hoy - timedelta(days=n)).isoformat(): 1 for n in (0, 1, 2, 5, 6)}
        self.assertEqual(progreso.racha(dias), {"actual": 3, "mejor": 3, "dias_activos": 5})
        ayer = {(hoy - timedelta(days=n)).isoformat(): 1 for n in (1, 2)}
        self.assertEqual(progreso.racha(ayer)["actual"], 2)            # aún cuenta si hoy no practicó
        self.assertEqual(progreso.racha({(hoy - timedelta(days=4)).isoformat(): 1})["actual"], 0)
        self.assertEqual(progreso.racha({})["actual"], 0)

    def test_resumen_completo(self):
        self.poblar()
        r = progreso.resumen(self.almacen, GuidedFalso(), None, None)
        d = r["desafios"]
        self.assertEqual((d["total"], d["por_estado"]["resuelto"], d["resueltos_sin_pistas"]), (6, 3, 3))
        self.assertEqual((d["con_razonamiento"], d["con_plan"], d["media_intentos"]), (1, 1, 2.0))
        self.assertEqual(d["minutos"], 32)
        actividades = {a["id"]: a for a in r["actividades"]}
        self.assertEqual((actividades["desafios"]["hechos"], actividades["desafios"]["total"]), (3, 6))
        self.assertEqual((actividades["plan"]["hechos"], actividades["plan"]["total"]), (1, 2))
        ruta = r["rutas"][0]
        self.assertEqual(ruta["completados"], 1)
        bloque = {b["id"]: b for b in ruta["bloques"]}["blk_pilas"]
        self.assertEqual((bloque["desafios"], bloque["resueltos"], bloque["completado"]), (1, 1, False))
        self.assertEqual([c["concepto"] for c in r["flojos"]], ["recursion", "dicts"])
        self.assertIn("clases", [c["concepto"] for c in r["fuertes"]])
        self.assertEqual(r["racha"]["dias_activos"], 6)

    def test_que_sigue(self):
        self.poblar()
        r = progreso.resumen(self.almacen, GuidedFalso(), None, None)
        tipos = [s["tipo"] for s in r["siguientes"]]
        self.assertEqual(tipos[0], "retomar")
        self.assertIn("Diccionarios", r["siguientes"][0]["texto"])
        self.assertEqual(r["siguientes"][0]["desafio_id"], self.ids["dicts"])
        practicar = [s for s in r["siguientes"] if s["tipo"] == "practicar"]
        self.assertEqual(practicar[0]["tema"], "recursion")
        bloque = [s for s in r["siguientes"] if s["tipo"] == "bloque"]
        self.assertEqual((bloque[0]["ruta_id"], bloque[0]["bloque_id"]), ("seg_x", "blk_pilas"))

    def test_sin_datos_no_falla(self):
        r = progreso.resumen(self.almacen, GuidedFalso(completados=[]), None, None)
        self.assertEqual(r["desafios"]["total"], 0)
        self.assertEqual(r["conceptos"], [])
        self.assertEqual(r["racha"]["actual"], 0)
        self.assertTrue(any(s["tipo"] == "bloque" for s in r["siguientes"]))   # el plan sigue guiando


class PruebaAnalisis(_ConDesafios):

    def test_contexto_es_solo_datos(self):
        self.poblar()
        filas = progreso.historial(self.almacen)
        texto = progreso.contexto_para_modelo(progreso.resumen(self.almacen, GuidedFalso(), None, None), filas)
        self.assertIn("6 en total, 3 resueltos (3 sin pistas)", texto)
        self.assertIn("- recursion: 0 (1/0/3, 1 con solución)", texto)
        self.assertIn("Ruta «Estructuras de datos»: 1/2 bloques; pendientes: Pilas.", texto)
        self.assertIn("«Búsqueda binaria»", texto)
        self.assertNotIn("secreto", texto)

    def test_guardar_y_leer(self):
        self.assertIsNone(progreso.analisis_guardado())
        texto = 'Vas bien.\n## Plan\n- **recursión** — repasa\n```json\n{"temas": ["recursión", "diccionarios"]}\n```'
        guardado = progreso.guardar_analisis(texto, "qwen2.5-coder:7b", 6)
        self.assertEqual(guardado["temas"], ["recursión", "diccionarios"])
        self.assertEqual(progreso.analisis_guardado()["desafios"], 6)
        self.assertEqual(progreso.temas_sugeridos("sin bloque"), [])
        self.assertNotIn("```json", progreso.sin_bloque_json(texto))
        self.assertIn("Vas bien.", progreso.sin_bloque_json(texto))

    def test_el_tutor_analiza_con_razonamiento(self):
        respuesta = ("## Dónde estás\nHas resuelto 3 de 6.\n## Lo que se te resiste\nrecursion.\n"
                     "## Cómo estás aprendiendo\nUsas poco el plan.\n## Plan para las próximas tres sesiones\n"
                     "- **recursión** — porque te rendiste\n## Cómo sabrás que avanzaste\nResolver sin pistas.\n"
                     '```json\n{"temas": ["recursión"]}\n```')
        ai = ModeloFalso([respuesta])
        gen = tutor.analisis_progreso(ai, "m", "DATOS")
        eventos = []
        try:
            while True:
                eventos.append(next(gen))
        except StopIteration as fin:
            texto = fin.value
        self.assertIn("## Plan para las próximas tres sesiones", texto)
        self.assertEqual(progreso.temas_sugeridos(texto), ["recursión"])
        self.assertIn("DATOS", ai.prompts[0][0])
        self.assertIn("sin inventar nada", ai.prompts[0][1])
        self.assertIs(ai.prompts[0][2], True)                 # aquí sí se deja razonar al modelo
        self.assertTrue(any(e.get("delta") for e in eventos))


if __name__ == "__main__":
    unittest.main()
