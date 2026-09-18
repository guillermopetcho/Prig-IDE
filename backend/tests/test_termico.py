"""
Pruebas del gobernador térmico y de las temperaturas.

Sin GPU real: los sensores y el monitor son falsos. Lo que se protege:

  · se corta al LLEGAR al límite (60 °C) y también antes si la tendencia dice que
    va a llegar en la próxima lectura;
  · al llegar, se reconfigura (ráfaga máxima y descanso) para no volver a llegar,
    y afloja solo tras varias ráfagas frescas;
  · la generación cortada se RETOMA con lo ya escrito, sin repetirlo ni perderlo,
    y con los tokens restantes descontados;
  · un flujo emite las pausas en vivo, mientras el paso está en marcha;
  · la lectura de sensores entiende coretemp, k10temp, nvme y ventiladores.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from collections import namedtuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recursos import termico
from recursos.termico import Gobernador, Monitor

Sensor = namedtuple("Sensor", "label current high critical")
Fan = namedtuple("Fan", "label current")


class MonitorFalso:
    """ Temperaturas guionizadas: cada lectura avanza por la lista """

    def __init__(self, temps, tendencia=0.0):
        self.temps = list(temps)
        self.i = 0
        self.tendencia = tendencia

    def gpu(self, max_edad=2.5):
        t = self.temps[min(self.i, len(self.temps) - 1)]
        self.i += 1
        return t

    def tendencia_gpu(self, desde=None):
        return self.tendencia

    def trabajando(self):
        class Ctx:
            def __enter__(s):
                return self

            def __exit__(s, *a):
                return False
        return Ctx()


class _Aislado(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {
            "PRIG_RECURSOS_ARCHIVO": os.path.join(self.tmp.name, "r.json")})
        self.env.start()
        self.dormir = mock.patch.object(termico.time, "sleep")
        self.dormir.start()

    def tearDown(self):
        self.dormir.stop()
        self.env.stop()
        self.tmp.cleanup()


class Reloj:
    """ time.time() controlado """

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class PruebaDecisiones(_Aislado):

    def setUp(self):
        super().setUp()
        self.reloj = Reloj()
        self.p_reloj = mock.patch.object(termico.time, "time", self.reloj)
        self.p_reloj.start()

    def tearDown(self):
        self.p_reloj.stop()
        super().tearDown()

    def _tramo(self, g, inicio, arranque, dur, corte=None, en_pausa=None):
        """ Simula un tramo: temp al empezar, máximo en los primeros segundos, corte """
        tramo = termico.Tramo(inicio)
        self.reloj.t += 1
        tramo.anotar(arranque)
        self.reloj.t += dur - 1
        if corte is not None:
            tramo.temp_corte = corte
            tramo.anotar(corte)
        tramo.pico_en_pausa = en_pausa
        g.terminar_tramo(tramo, "limite" if corte is not None else None)
        return tramo

    def test_por_defecto_corta_a_59_y_reanuda_a_50(self):
        """ 60 − salto medido (8) − 2 """
        g = Gobernador(MonitorFalso([40]), guardar=False)
        self.assertEqual((g.limite, g.corte, g.reanudar), (60.0, 59.0, 50.0))
        self.assertTrue(g.viable)

    def test_corta_al_llegar_al_corte(self):
        g = Gobernador(MonitorFalso([50, 58, 59]), guardar=False)   # 50: al empezar
        tramo = g.empezar_tramo()
        self.assertIsNone(g.debe_cortar(tramo))
        self.assertEqual(g.debe_cortar(tramo), "limite")
        self.assertEqual(tramo.temp_corte, 59)

    def test_corta_antes_si_va_a_llegar(self):
        g = Gobernador(MonitorFalso([57], tendencia=1.5), guardar=False)
        self.assertEqual(g.debe_cortar(termico.Tramo(50)), "prevision")
        g = Gobernador(MonitorFalso([55], tendencia=0.36), guardar=False)
        self.assertIsNone(g.debe_cortar(termico.Tramo(50)))

    def test_sin_sensor_no_corta_nunca(self):
        self.assertIsNone(Gobernador(MonitorFalso([None]), guardar=False)
                          .debe_cortar(termico.Tramo(None)))

    def test_aprende_el_salto_al_empezar_y_reanuda_mas_frio(self):
        """ Medido: de 43 a 51 °C en el primer segundo de cada tramo """
        g = Gobernador(MonitorFalso([40]), guardar=False)
        self._tramo(g, inicio=43, arranque=53, dur=5, corte=59, en_pausa=60)
        self.assertEqual(g.ajustes["salto_c"], 10.0)
        self.assertEqual(g.reanudar, 48.0)                     # 60 − 10 − 2
        self.assertEqual(g.ajustes["alcances"], 1)
        # Inercia tras cortar: subió 1 °C más → corta con 1,5 de margen
        self.assertEqual(g.corte, 58.5)

    def test_el_salto_baja_despacio(self):
        g = Gobernador(MonitorFalso([40]), guardar=False)
        self._tramo(g, 40, 50, 5)
        self._tramo(g, 40, 44, 5)
        self.assertEqual(g.ajustes["salto_c"], 8.8)            # 0,8·10 + 0,2·4

    def test_tramo_muy_corto_no_mide_salto(self):
        g = Gobernador(MonitorFalso([40]), guardar=False)
        tramo = termico.Tramo(40)
        g.terminar_tramo(tramo, None)                          # 0 s
        self.assertIsNone(g.ajustes["salto_c"])

    def test_margen_tiene_tope_y_afloja_con_tramos_frescos(self):
        g = Gobernador(MonitorFalso([40]), guardar=False)
        self._tramo(g, 45, 50, 5, corte=59, en_pausa=66)
        self.assertEqual(g.ajustes["margen"], termico.MARGEN_MAXIMO)
        for _ in range(termico.FRESCAS_PARA_AFLOJAR):
            self._tramo(g, 40, 45, 5)
        self.assertLess(g.ajustes["margen"], termico.MARGEN_MAXIMO)

    def test_limite_inalcanzable_avisa_con_el_minimo_viable(self):
        """ Regresión real: límite 50, reposo 42, salto 8 → nunca por debajo """
        g = Gobernador(MonitorFalso([40]), guardar=False)
        g.ajustes.update(limite_gpu=50.0, salto_c=8.0)
        g._anotar_reposo(42.0)
        self.assertFalse(g.viable)
        self.assertEqual(g.limite_minimo_viable, 52.0)
        self.assertIn("52", g.aviso)
        self.assertEqual(g.reanudar, 43.0)                     # nunca por debajo del reposo
        g.fijar_limite(60)
        self.assertTrue(g.viable)
        self.assertIsNone(g.aviso)

    def test_lo_aprendido_se_guarda_y_sobrevive(self):
        g = Gobernador(MonitorFalso([40]))
        g.fijar_limite(58)
        self._tramo(g, 42, 52, 5, corte=57, en_pausa=58.5)
        otro = Gobernador(MonitorFalso([40]))
        self.assertEqual(otro.limite, 58.0)
        self.assertEqual(otro.ajustes["salto_c"], 10.0)
        otro.olvidar()
        self.assertIsNone(Gobernador(MonitorFalso([40])).ajustes["salto_c"])
        self.assertEqual(Gobernador(MonitorFalso([40])).limite, 58.0)

    def test_ajustes_viejos_desconocidos_se_ignoran(self):
        from recursos.almacen import almacen
        almacen().guardar_termico({"limite_gpu": 61, "rafaga_s": 30, "histeresis": 9})
        g = Gobernador(MonitorFalso([40]))
        self.assertEqual(g.limite, 61.0)
        self.assertNotIn("rafaga_s", g.ajustes)

    def test_limite_fuera_de_rango(self):
        with self.assertRaises(ValueError):
            Gobernador(MonitorFalso([40]), guardar=False).fijar_limite(20)

    def test_enfriar_espera_hasta_reanudar_y_avisa(self):
        g = Gobernador(MonitorFalso([61, 58, 55, 50]), guardar=False)
        eventos = []
        cancelar = threading.Event()
        tramo = termico.Tramo(50)
        with mock.patch.object(cancelar, "wait", side_effect=lambda s: setattr(
                self.reloj, "t", self.reloj.t + 1) or False):
            g.enfriar("limite", cancelar, eventos.append, tramo=tramo)
        self.assertEqual([e["tipo"] for e in eventos], ["enfriando", "reanudando"])
        self.assertEqual(tramo.pico_en_pausa, 61)
        self.assertIsNone(g.pausa)

    def test_si_la_gpu_no_baja_mas_reanuda_sin_esperar_10_minutos(self):
        g = Gobernador(MonitorFalso([49] + [42] * 200), guardar=False)
        g.ajustes.update(limite_gpu=50.0)
        cancelar = threading.Event()
        eventos = []
        with mock.patch.object(cancelar, "wait", side_effect=lambda s: setattr(
                self.reloj, "t", self.reloj.t + 1) or False):
            espera = g.enfriar("limite", cancelar, eventos.append)
        self.assertLess(espera, 60)
        self.assertTrue(eventos[1]["meseta"])
        self.assertEqual(g.ajustes["reposo_c"], 42)
        self.assertEqual(eventos[-1]["tipo"], "aviso_termico")  # 50 es inalcanzable

    def test_antes_de_paso_espera_solo_si_esta_por_encima_de_reanudar(self):
        with mock.patch.object(Gobernador, "enfriar", return_value=3.0) as enfriar:
            Gobernador(MonitorFalso([49]), guardar=False).antes_de_trabajar()
            enfriar.assert_not_called()
            Gobernador(MonitorFalso([53]), guardar=False).antes_de_trabajar()
            self.assertEqual(enfriar.call_args.args[0], "antes_de_paso")


class PruebaGeneracionRetomada(_Aislado):

    def _motor(self):
        from ai_engine import AIEngine
        motor = AIEngine.__new__(AIEngine)
        motor.base_url = "http://x"
        motor.config = {"num_ctx": 4096, "num_gpu": -1, "temperature": 0.3, "num_predict": 100}
        motor._active_streams, motor._streams_lock = set(), threading.Lock()
        motor._cancelables = set()
        motor._capacidades = {}
        return motor

    def test_corta_enfria_y_continua_sin_perder_lo_escrito(self):
        class Res:
            status_code = 200

            def __init__(self, trozos):
                self.trozos = trozos

            def iter_lines(self):
                for t, fin in self.trozos:
                    yield json.dumps({"message": {"content": t}, "done": fin}).encode()

            def close(self):
                pass

        enviados = []
        respuestas = [Res([("Hola", False), (" mun", False), ("do", False), (" cruel", False)]),
                      Res([("do", False), (".", True)])]

        def post(url, json=None, **kw):
            enviados.append(json)
            return respuestas.pop(0)

        g = Gobernador(MonitorFalso([40]), guardar=False)
        cortes = iter([None, "limite"])          # corta en el segundo control, tras " mun"
        g.debe_cortar = lambda tramo: next(cortes, None)
        eventos, tramos = [], []
        g.terminar_tramo = lambda tramo, motivo: tramos.append(motivo)
        with mock.patch("ai_engine.ai_engine_class.requests.post", side_effect=post), \
                mock.patch.object(g, "enfriar", side_effect=lambda *a, **k: eventos.append("enfriar")), \
                mock.patch("ai_engine.ai_engine_class.time.time",
                           side_effect=[float(i) * 2 for i in range(100)]):
            texto = self._motor().generar_con_pausas("di hola", "m", system_prompt="s",
                                                     gobernador=g, avisar=eventos.append)
        self.assertEqual(eventos, ["enfriar"])
        # Segunda petición: lo generado va como inicio de la respuesta del asistente
        self.assertEqual(enviados[1]["messages"][-1], {"role": "assistant", "content": "Hola mun"})
        self.assertEqual(enviados[1]["messages"][0], {"role": "system", "content": "s"})
        self.assertEqual(enviados[1]["options"]["num_predict"], 98)
        self.assertEqual(texto, "Hola mundo.")
        # Cada tramo se cierra para aprender: el cortado y el que terminó
        self.assertEqual(tramos, ["limite", None])

    def test_sin_gobernador_no_corta(self):
        class Res:
            status_code = 200

            def iter_lines(self):
                yield json.dumps({"message": {"content": "ok"}, "done": True}).encode()

            def close(self):
                pass
        with mock.patch("ai_engine.ai_engine_class.requests.post", return_value=Res()):
            self.assertEqual(self._motor().generar_con_pausas("x", "m"), "ok")


class PruebaChatConPausas(_Aislado):
    """ El chat del panel izquierdo también respeta el límite (antes solo los flujos) """
    _motor = PruebaGeneracionRetomada._motor

    class Res:
        status_code = 200

        def __init__(self, trozos):
            self.trozos = trozos

        def iter_lines(self):
            for t, fin in self.trozos:
                yield json.dumps({"message": {"content": t}, "done": fin,
                                  **({"eval_count": 3, "eval_duration": 10**9} if fin else {})}).encode()

        def close(self):
            pass

    def _chat(self, respuestas, cortes, temps):
        enviados = []

        def post(url, json=None, **kw):
            enviados.append(json)
            return respuestas.pop(0)

        g = Gobernador(MonitorFalso(temps), guardar=False)
        cortes = iter(cortes)
        g.debe_cortar = lambda tramo: next(cortes, None)
        g.terminar_tramo = lambda tramo, motivo: None
        motor = self._motor()
        with mock.patch("ai_engine.ai_engine_class.requests.post", side_effect=post), \
                mock.patch.object(motor, "capacidades", return_value=[]), \
                mock.patch.object(g, "enfriar", return_value=12.0) as enfriar, \
                mock.patch("ai_engine.ai_engine_class.time.time",
                           side_effect=[float(i) * 2 for i in range(200)]):
            eventos = list(motor.chat_eventos([{"role": "user", "content": "hola"}], "m", gobernador=g))
        return eventos, enviados, enfriar, motor

    def test_corta_avisa_y_continua_la_misma_respuesta(self):
        respuestas = [self.Res([("Hola", False), (" mun", False), ("do", False)]), self.Res([("do", False), (".", True)])]
        eventos, enviados, enfriar, motor = self._chat(respuestas, [None, "limite"], [40, 62, 62, 45])
        texto = "".join(e["v"] for e in eventos if e["t"] == "texto")
        self.assertEqual(texto, "Hola mundo.")
        termicos = [e for e in eventos if e["t"] == "termico"]
        self.assertEqual([e["pausa"] for e in termicos], [True, False])
        self.assertIn("pausa para enfriar", termicos[0]["v"])
        self.assertEqual(enfriar.call_count, 1)
        self.assertEqual(enviados[1]["messages"][-1], {"role": "assistant", "content": "Hola mun"})
        self.assertTrue(any(e["t"] == "stats" for e in eventos))
        self.assertEqual(motor._cancelables, set())   # se da de baja al terminar

    def test_detener_despierta_una_pausa(self):
        from ai_engine import AIEngine
        motor = self._motor()
        evento = threading.Event()
        motor._cancelables.add(evento)
        AIEngine.cancel_active_requests(motor)
        self.assertTrue(evento.is_set())


class PruebaSoltarModelos(_Aislado):
    _motor = PruebaGeneracionRetomada._motor

    def test_al_cerrar_suelta_los_que_uso_prig_y_no_los_ajenos(self):
        from ai_engine import AIEngine
        motor = self._motor()
        motor.config.update(agent1_model="qwen2.5-coder:7b")
        motor._usados = {"deepseek-r1:8b"}

        class Ps:
            def json(self):
                return {"models": [{"name": "deepseek-r1:8b"}, {"name": "qwen2.5-coder:7b"}, {"name": "de-otro:1b"}]}
        soltados = []
        with mock.patch("ai_engine.ai_engine_class.requests.get", return_value=Ps()), \
                mock.patch("ai_engine.ai_engine_class.requests.post",
                           side_effect=lambda url, json=None, **k: soltados.append(json)):
            AIEngine.unload_models(motor)
        self.assertEqual(sorted(j["model"] for j in soltados), ["deepseek-r1:8b", "qwen2.5-coder:7b"])
        self.assertTrue(all(j["keep_alive"] == 0 for j in soltados))


class PruebaFlujoConPausas(_Aislado):

    def test_las_pausas_salen_en_vivo_durante_el_paso(self):
        from agent_flows import FlowEngine

        class MotorFalso:
            def generar_con_pausas(self, prompt, gobernador=None, cancelar=None, avisar=None, **kw):
                avisar({"tipo": "enfriando", "mensaje": "GPU a 60 °C"})
                avisar({"tipo": "reanudando", "mensaje": "sigue"})
                return "resultado del paso"

            def generate_response(self, *a, **k):
                raise AssertionError("con gobernador debe usarse generar_con_pausas")

        gob = Gobernador(MonitorFalso([40]), guardar=False)
        motor = FlowEngine(MotorFalso(), gobernador=gob)
        flujo = {"nombre": "t", "pasos": [{"id": "a", "nombre": "A", "rol": "razonar",
                                            "modelo": "qwen2.5-coder:7b", "prompt": "{entrada}"}]}
        eventos = list(motor.ejecutar(flujo, entrada="hola"))
        tipos = [e["tipo"] for e in eventos]
        self.assertLess(tipos.index("paso_inicio"), tipos.index("enfriando"))
        self.assertLess(tipos.index("reanudando"), tipos.index("paso_fin"))
        fin = next(e for e in eventos if e["tipo"] == "fin")
        self.assertEqual(fin["final"], "resultado del paso")
        enfriando = next(e for e in eventos if e["tipo"] == "enfriando")
        self.assertEqual((enfriando["id"], enfriando["indice"]), ("a", 0))


class PruebaSensores(unittest.TestCase):

    def test_lee_intel_nvme_placa_y_ventiladores(self):
        temps = {
            "coretemp": [Sensor("Package id 0", 76.0, 100.0, 100.0), Sensor("Core 0", 81.0, 100.0, 100.0),
                         Sensor("Core 4", 70.0, 100.0, 100.0)],
            "nvme": [Sensor("Composite", 38.85, 80.85, 83.85), Sensor("Sensor 1", 38.85, 65261.85, 65261.85)],
            "acpitz": [Sensor("", 45.0, None, None)],
        }
        fans = {"acpi_fan": [Fan("", 2204)], "hp": [Fan("", 2204), Fan("", 2000)]}
        with mock.patch.object(termico, "_nvidia", return_value=[
                {"id": "gpu0", "tipo": "gpu", "nombre": "RTX", "temp": 58.0}]), \
                mock.patch.object(termico, "_psutil_temps", return_value=temps), \
                mock.patch.object(termico, "_psutil_fans", return_value=fans):
            l = termico.leer_sensores()
        por_tipo = {c["tipo"]: c for c in l["componentes"]}
        self.assertEqual(por_tipo["cpu"]["temp"], 76.0)
        self.assertEqual(por_tipo["cpu"]["nucleo_max"], 81.0)
        self.assertEqual(por_tipo["disco"]["temp"], 38.9)
        self.assertEqual(sum(1 for c in l["componentes"] if c["tipo"] == "disco"), 1)
        self.assertIn("placa", por_tipo)
        self.assertEqual(len(l["ventiladores"]), 2)             # sin el acpi_fan duplicado
        self.assertEqual(termico.temp_gpu(l), 58.0)

    def test_amd(self):
        temps = {"k10temp": [Sensor("Tctl", 66.5, None, None)],
                 "amdgpu": [Sensor("edge", 55.0, 100.0, 105.0)]}
        with mock.patch.object(termico, "_nvidia", return_value=[]), \
                mock.patch.object(termico, "_psutil_temps", return_value=temps), \
                mock.patch.object(termico, "_psutil_fans", return_value={}):
            l = termico.leer_sensores()
        self.assertEqual(termico.temp_cpu(l), 66.5)
        self.assertEqual(termico.temp_gpu(l), 55.0)

    def test_monitor_guarda_historial_y_tendencia(self):
        t = [100.0]
        valores = iter([50, 52, 54, 56])

        def lector():
            t[0] += 2
            return {"tomada": t[0], "componentes": [{"tipo": "gpu", "temp": next(valores)},
                                                    {"tipo": "cpu", "temp": 70}]}
        m = Monitor(lector)
        for _ in range(4):
            m._muestrear()
        self.assertEqual(len(m.historial), 4)
        self.assertAlmostEqual(m.tendencia_gpu(), 1.0)
        # Desde un instante posterior quedan menos de dos lecturas: sin tendencia
        self.assertEqual(m.tendencia_gpu(desde=107.5), 0.0)


if __name__ == "__main__":
    unittest.main()
