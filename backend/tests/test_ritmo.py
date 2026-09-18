"""
Modo suave: dosificar la generación para que la máquina trabaje continua y sin picos.

  · la fracción de trabajo es un termostato proporcional: a pleno lejos del objetivo,
    menos al acercarse, nunca por debajo del mínimo;
  · el arranque es gradual tras un rato sin trabajar;
  · el gobernador pide pausas cortas («ritmo») antes de llegar al límite, y el corte
    de emergencia sigue mandando cuando se llega;
  · generate_response (Desafíos, Kaggle, GitHub…) pausa y sigue donde quedó por
    /api/chat sin perder ni repetir texto, y no corta a mitad del razonamiento;
  · el motor se fija a los núcleos de eficiencia solo si el modelo cabe entero en la GPU.
"""

import json
import os
import sys
import threading
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from recursos import ritmo as rt  # noqa: E402
from recursos import termico  # noqa: E402
from recursos.termico import Gobernador  # noqa: E402


class MonitorFalso:
    def __init__(self, temps):
        self.temps = list(temps)

    def gpu(self, max_edad=2.5):
        return self.temps.pop(0) if len(self.temps) > 1 else self.temps[0]

    def tendencia_gpu(self, desde=None):
        return 0.0

    def trabajando(self):
        class C:
            def __enter__(s): return self
            def __exit__(s, *a): pass
        return C()


class TestFraccion(unittest.TestCase):
    def ritmo(self, **k):
        return rt.Ritmo({"objetivo_c": 60, "rampa_s": 0, "ritmo_minimo": 0.3, **k})

    def test_termostato_proporcional(self):
        r = self.ritmo()
        self.assertEqual(r.fraccion(45), 1.0)            # lejos del objetivo: a pleno
        self.assertEqual(r.fraccion(52), 1.0)            # justo en el borde de la banda
        self.assertAlmostEqual(r.fraccion(56), 0.65, places=2)
        self.assertEqual(r.fraccion(60), 0.3)            # en el objetivo: el mínimo
        self.assertEqual(r.fraccion(75), 0.3)            # nunca se para del todo
        self.assertEqual(r.fraccion(None), 1.0)          # sin sensor no se dosifica
        vals = [r.fraccion(t) for t in range(50, 62)]
        self.assertEqual(vals, sorted(vals, reverse=True))   # a más calor, menos trabajo

    def test_arranque_gradual(self):
        r = self.ritmo(rampa_s=40, inicio_rampa=0.35)
        self.assertAlmostEqual(r.fraccion(40, ahora=990), 0.35)   # parado: la próxima empieza suave
        r.marcar(ahora=1000)
        self.assertAlmostEqual(r.fraccion(40, ahora=1000), 0.35)
        for t in range(1000, 1041, 10):                  # sigue trabajando (se marca en cada paso)
            r.marcar(ahora=t)
            if t == 1020:
                self.assertAlmostEqual(r.fraccion(40, ahora=1020), 0.675)
        self.assertEqual(r.fraccion(40, ahora=1040), 1.0)
        r.marcar(ahora=1050)
        self.assertEqual(r.fraccion(40, ahora=1050), 1.0)
        r.marcar(ahora=1050 + rt.REPOSO_S + 1)           # tras un descanso, sí
        self.assertAlmostEqual(r.fraccion(40, ahora=1050 + rt.REPOSO_S + 1), 0.35)

    def test_pausa(self):
        r = self.ritmo(tramo_s=1.0)
        self.assertIsNone(r.pausa(0.5, 60))              # el tramo aún no llegó al mínimo
        self.assertIsNone(r.pausa(1.2, 40))              # frío: sin pausa
        self.assertAlmostEqual(r.pausa(1.0, 60), 1.0 * 0.7 / 0.3, places=2)
        self.assertEqual(r.pausa(100, 60), rt.PAUSA_MAXIMA_S)
        r.fijar({"activo": False})
        self.assertIsNone(r.pausa(1.0, 80))

    def test_fijar_acota_y_guarda(self):
        guardado = []
        r = rt.Ritmo(guardar=lambda a, t: guardado.append((a, t)))
        a = r.fijar({"objetivo_c": 200, "rampa_s": -5, "ritmo_minimo": 0.01, "activo": 0, "raro": 1})
        self.assertEqual((a["objetivo_c"], a["rampa_s"], a["ritmo_minimo"], a["activo"]), (90.0, 0.0, 0.1, False))
        self.assertNotIn("raro", a)
        self.assertIn("desactivado", guardado[0][1])


class TestGobernador(unittest.TestCase):
    def gob(self, temps, **ajustes):
        g = Gobernador(MonitorFalso(temps), guardar=False)
        g.ajustes["limite_gpu"] = 80.0
        g.ritmo = rt.Ritmo({"objetivo_c": 60, "rampa_s": 0, "tramo_s": 1.0, "cpu_eficiente": False, **ajustes})
        return g

    def test_ritmo_antes_del_limite_y_el_limite_manda(self):
        g = self.gob([58])
        tramo = g.empezar_tramo()
        tramo.inicio -= 1.5
        self.assertEqual(g.debe_cortar(tramo), "ritmo")
        self.assertGreater(tramo.pausa_ritmo, 0)
        g = self.gob([45])
        tramo = g.empezar_tramo()
        tramo.inicio -= 1.5
        self.assertIsNone(g.debe_cortar(tramo))
        g = self.gob([80])
        tramo = g.empezar_tramo()
        tramo.inicio -= 1.5
        self.assertEqual(g.debe_cortar(tramo), "limite")

    def test_descansar_es_corto_y_cancelable(self):
        g = self.gob([60])
        tramo = g.empezar_tramo()
        tramo.pausa_ritmo = 5.0
        cancelar = threading.Event()
        cancelar.set()
        with mock.patch.object(cancelar, "wait", wraps=cancelar.wait) as w:
            self.assertEqual(g.enfriar("ritmo", cancelar, tramo=tramo), 5.0)
            w.assert_called_once_with(5.0)

    def test_tramos_de_ritmo_no_ensenan(self):
        g = self.gob([60])
        tramo = g.empezar_tramo()
        antes = dict(g.ajustes)
        g.terminar_tramo(tramo, "ritmo")
        self.assertEqual(g.ajustes, antes)

    def test_cpu_eficiente_al_empezar(self):
        g = self.gob([50], cpu_eficiente=True)
        with mock.patch.object(g.fijador, "aplicar") as aplicar:
            g.empezar_tramo()
            aplicar.assert_called_once()
        g.ritmo.fijar({"activo": False})
        with mock.patch.object(g.fijador, "aplicar") as aplicar:
            g.empezar_tramo()
            aplicar.assert_not_called()


class Res:
    status_code = 200

    def __init__(self, lineas):
        self.lineas = lineas

    def iter_lines(self):
        for l in self.lineas:
            yield json.dumps(l).encode()

    def close(self):
        pass


class TestGenerateResponse(unittest.TestCase):
    def motor(self, gob):
        from ai_engine import AIEngine
        m = AIEngine.__new__(AIEngine)
        m.base_url = "http://x"
        m.config = {"num_ctx": 4096, "num_gpu": -1, "temperature": 0.3, "num_predict": 50}
        m._active_streams, m._streams_lock = set(), threading.Lock()
        m._cancelables, m._capacidades = set(), {}
        m.gobernador = gob
        return m

    def correr(self, respuestas, cortes, sistema="sé breve"):
        enviados = []

        def post(url, json=None, **kw):
            enviados.append((url, json))
            return respuestas.pop(0)
        g = Gobernador(MonitorFalso([50]), guardar=False)
        cortes = iter(cortes)
        g.debe_cortar = lambda tramo: (lambda m: (setattr(tramo, "pausa_ritmo", 0.01), m)[1])(next(cortes, None))
        g.terminar_tramo = lambda *a: None
        m = self.motor(g)
        with mock.patch("ai_engine.ai_engine_class.requests.post", side_effect=post), \
                mock.patch.object(m, "capacidades", return_value=[]), \
                mock.patch("ai_engine.ai_engine_class.time.time", side_effect=[float(i) * 2 for i in range(400)]):
            texto = "".join(m.generate_response("di hola", model="m", system_prompt=sistema))
        return texto, enviados

    def test_pausa_y_sigue_por_chat_sin_perder_texto(self):
        texto, enviados = self.correr(
            [Res([{"response": "Hola"}, {"response": " qué"}, {"response": " no llega"}]),
             Res([{"message": {"content": " tal"}}, {"message": {"content": "?"}, "done": True}])],
            [None, "ritmo"])
        # Lo que no se leyó antes del corte no cuenta: Ollama sigue desde «Hola qué»
        self.assertEqual(texto, "Hola qué tal?")
        self.assertTrue(enviados[0][0].endswith("/api/generate"))
        url, cuerpo = enviados[1]
        self.assertTrue(url.endswith("/api/chat"))
        self.assertEqual(cuerpo["messages"][0], {"role": "system", "content": "sé breve"})
        self.assertEqual(cuerpo["messages"][1], {"role": "user", "content": "di hola"})
        self.assertEqual(cuerpo["messages"][-1], {"role": "assistant", "content": "Hola qué"})
        self.assertEqual(cuerpo["options"]["num_predict"], 48)
        self.assertNotIn("prompt", cuerpo)

    def test_no_corta_a_mitad_del_razonamiento(self):
        texto, enviados = self.correr(
            [Res([{"thinking": "pienso"}, {"thinking": " más"}, {"thinking": " y más"}, {"response": "listo", "done": True}])],
            ["ritmo", "ritmo", "ritmo"])
        self.assertEqual(len(enviados), 1)
        self.assertEqual(texto, "listo")

    def test_sin_gobernador_una_sola_peticion(self):
        m = self.motor(None)
        with mock.patch("ai_engine.ai_engine_class.requests.post", return_value=Res([{"response": "ok", "done": True}])) as p, \
                mock.patch.object(m, "capacidades", return_value=[]):
            self.assertEqual("".join(m.generate_response("x", model="m")), "ok")
            self.assertEqual(p.call_count, 1)


class TestFijadorCPU(unittest.TestCase):
    def test_solo_si_el_modelo_esta_entero_en_gpu(self):
        entero, partido = "a" * 64, "b" * 64

        class Proc:
            def __init__(self, pid, digest):
                self.pid = pid
                self.info = {"pid": pid, "cmdline": ["/x/llama-server", "--model", f"/m/blobs/sha256-{digest}"],
                             "uids": mock.Mock(real=os.getuid())}

            def threads(self):
                return [mock.Mock(id=self.pid * 10)]
        procesos = [Proc(101, entero), Proc(202, partido)]
        f = rt.FijadorCPU()
        fijados = {}
        with mock.patch.object(rt, "nucleos_eficientes", return_value=[8, 9, 10, 11]), \
                mock.patch.object(f, "_modelos_en_gpu", return_value={entero: True, partido: False}), \
                mock.patch("psutil.process_iter", return_value=procesos), \
                mock.patch("psutil.pids", return_value=[101, 202]), \
                mock.patch.object(rt.os, "sched_getaffinity", return_value=set(range(12))), \
                mock.patch.object(rt.os, "sched_setaffinity", side_effect=lambda pid, cpus: fijados.__setitem__(pid, list(cpus))):
            r = f.aplicar(forzar=True)
        self.assertTrue(r["aplicado"])
        self.assertEqual(fijados[101], [8, 9, 10, 11])
        self.assertEqual(fijados[1010], [8, 9, 10, 11])          # también sus hilos
        self.assertEqual(fijados[202], list(range(12)))          # el que no cabe en la GPU, todos los núcleos

    def test_sin_nucleos_de_eficiencia_no_hace_nada(self):
        with mock.patch.object(rt, "nucleos_eficientes", return_value=[]):
            self.assertFalse(rt.FijadorCPU().aplicar(forzar=True)["aplicado"])

    def test_leer_lista(self):
        self.assertEqual(rt._leer_lista_cpus("8-11"), [8, 9, 10, 11])
        self.assertEqual(rt._leer_lista_cpus("0,2-3\n"), [0, 2, 3])


if __name__ == "__main__":
    unittest.main()
