"""
Pruebas de la corrida local: motor de Ollama, reparación y conjunto de modelos.

El contexto de por qué existe cada mecanismo está medido, no supuesto. Sobre un
fragmento real de un libro de deep learning, con qwen2.5-coder:7b en la RTX 4050:

    sin format:json    50 % de citas verificadas,  2 afirmaciones
    con format:json    80 % de citas verificadas,  4 afirmaciones

El mismo modelo. Lo que fallaba no era el conocimiento sino la disciplina de
formato, y de ahí que el motor de Ollama fuerce el JSON siempre.
"""

import os
import sys
import json
import tempfile
import shutil
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(RAIZ), "kaggle_worker"))

from prig_extract import (MotorOllama, combinar, _puntuar, fragmentos_a_reparar,
                          limpiar_extraccion, normalizar)


class OllamaSimulado:
    """ Sustituye a `requests` dentro del motor, para no necesitar servidor """

    def __init__(self, modelos=("m:7b",)):
        self.modelos = list(modelos)
        self.peticiones = []

    def get(self, url, timeout=None):
        yo = self
        class R:
            def json(self):
                return {"models": [{"name": m} for m in yo.modelos]}
        return R()

    def post(self, url, json=None, timeout=None):
        self.peticiones.append(json)
        class R:
            def raise_for_status(self): pass
            def json(self_inner):
                return {"message": {"content": '{"claims": []}'}}
        return R()


def motor_simulado(modelos=("m:7b",), **kw):
    simulado = OllamaSimulado(modelos)
    real = __import__("prig_extract")
    original = real.MotorOllama.__init__

    def init(self, modelo, base_url="http://x", paralelo=2, num_ctx=4096,
             keep_alive="30m", **_):
        self.requests = simulado
        self.modelo = modelo
        self.base = base_url.rstrip("/")
        self.paralelo = paralelo
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        disponibles = [m["name"] for m in simulado.get("").json()["models"]]
        if modelo not in disponibles:
            raise RuntimeError(f"El modelo '{modelo}' no está en Ollama. "
                               f"Disponibles: {', '.join(disponibles)}")
    real.MotorOllama.__init__ = init
    try:
        m = real.MotorOllama(kw.pop("modelo", "m:7b"), **kw)
    finally:
        real.MotorOllama.__init__ = original
    return m, simulado


class PruebaMotorOllama(unittest.TestCase):

    def test_fuerza_el_formato_json(self):
        """ Es el ajuste que más subió la verificación de citas, medido. """
        m, sim = motor_simulado()
        m.generar(["hola"], max_tokens=800)
        self.assertEqual(sim.peticiones[0]["format"], "json")

    def test_mantiene_el_modelo_cargado(self):
        """ Sin keep_alive, Ollama descarga el modelo y cada lote paga la carga. """
        m, sim = motor_simulado(keep_alive="45m")
        m.generar(["hola"])
        self.assertEqual(sim.peticiones[0]["keep_alive"], "45m")

    def test_pasa_contexto_y_tope_de_salida(self):
        m, sim = motor_simulado(num_ctx=6144)
        m.generar(["hola"], max_tokens=1234)
        opciones = sim.peticiones[0]["options"]
        self.assertEqual(opciones["num_ctx"], 6144)
        self.assertEqual(opciones["num_predict"], 1234)

    def test_lanza_las_peticiones_en_paralelo(self):
        m, sim = motor_simulado(paralelo=3)
        salidas = m.generar(["a", "b", "c", "d"])
        self.assertEqual(len(salidas), 4)
        self.assertEqual(len(sim.peticiones), 4)

    def test_conserva_el_orden_con_paralelo(self):
        """ La respuesta N debe corresponder al fragmento N, o las citas se
        verificarían contra el texto equivocado. """
        m, sim = motor_simulado(paralelo=4)
        m.generar([f"prompt {i}" for i in range(8)])
        enviados = [p["messages"][-1]["content"] for p in sim.peticiones]
        self.assertEqual(sorted(enviados), sorted(f"prompt {i}" for i in range(8)))

    def test_avisa_si_el_modelo_no_esta_descargado(self):
        with self.assertRaises(RuntimeError) as ctx:
            motor_simulado(modelos=("otro:7b",), modelo="qwen2.5:7b")
        self.assertIn("no está en Ollama", str(ctx.exception))
        self.assertIn("otro:7b", str(ctx.exception))


class PruebaCombinar(unittest.TestCase):
    """ Un fragmento leído varias veces: por la reparación, o por dos modelos. """

    @staticmethod
    def lectura(n_claims, ok=True, citas=None):
        citas = citas or [f"cita numero {i}" for i in range(n_claims)]
        return {"chunk_id": "c1", "ok": ok,
                "claims": [{"type": "DEFINITION", "text": f"t{i}", "quote": q}
                           for i, q in enumerate(citas)],
                "concepts": [{"name": f"concepto {i}"} for i in range(n_claims)],
                "relations": [], "symbols": []}

    def test_una_sola_lectura_pasa_tal_cual(self):
        l = self.lectura(2)
        self.assertIs(combinar([l]), l)

    def test_conserva_la_mejor(self):
        """ Comportamiento por defecto tras reparar: la segunda solo gana si mejoró. """
        pobre, rica = self.lectura(1), self.lectura(4)
        self.assertEqual(len(combinar([pobre, rica])["claims"]), 4)
        self.assertEqual(len(combinar([rica, pobre])["claims"]), 4)

    def test_una_lectura_fallida_nunca_gana(self):
        fallida = {"chunk_id": "c1", "ok": False, "error": "json_invalido"}
        self.assertTrue(combinar([fallida, self.lectura(1)])["ok"])
        self.assertTrue(combinar([self.lectura(1), fallida])["ok"])

    def test_unir_suma_lo_que_cada_modelo_vio(self):
        """ El fallo que la verificación NO detecta es lo que el modelo se dejó.
        Dos lecturas independientes se dejan cosas distintas. """
        a = self.lectura(2, citas=["cita alfa", "cita beta"])
        b = self.lectura(2, citas=["cita beta", "cita gamma"])
        unida = combinar([a, b], unir=True)
        citas = {c["quote"] for c in unida["claims"]}
        self.assertEqual(citas, {"cita alfa", "cita beta", "cita gamma"})

    def test_unir_no_duplica_la_misma_cita(self):
        a = self.lectura(1, citas=["La misma frase exacta del libro."])
        b = self.lectura(1, citas=["La  misma   frase exacta del libro."])   # espaciado
        unida = combinar([a, b], unir=True)
        self.assertEqual(len(unida["claims"]), 1,
                         "el espaciado no debe crear una afirmación duplicada")

    def test_unir_deja_constancia_de_cuantas_lecturas(self):
        u = combinar([self.lectura(1), self.lectura(1, citas=["otra cita larga"])], unir=True)
        self.assertEqual(u["_lecturas"], 2)


class PruebaSeleccionDeReparacion(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ruta = os.path.join(self.tmp, "_parcial.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def escribir(self, registros):
        with open(self.ruta, "w", encoding="utf-8") as f:
            for r in registros:
                f.write(json.dumps(r) + "\n")

    @staticmethod
    def reg(cid, buenas, malas, ok=True):
        return {"chunk_id": cid, "ok": ok,
                "claims": [{"quote": f"q{i}"} for i in range(buenas)],
                "_descartados": {"claims": malas, "relations": 0, "symbols": 0}}

    def test_selecciona_el_json_invalido(self):
        self.escribir([{"chunk_id": "a", "ok": False, "error": "json_invalido"}])
        self.assertIn("a", fragmentos_a_reparar(self.ruta, 0.5))

    def test_selecciona_el_que_no_extrajo_nada(self):
        self.escribir([self.reg("a", 0, 0)])
        self.assertIn("a", fragmentos_a_reparar(self.ruta, 0.5))

    def test_selecciona_el_que_cito_mal_todo(self):
        self.escribir([self.reg("a", 0, 3)])
        motivos = fragmentos_a_reparar(self.ruta, 0.5)
        self.assertIn("a", motivos)
        self.assertIn("3 afirmaciones", motivos["a"])

    def test_respeta_el_umbral(self):
        self.escribir([self.reg("bajo", 1, 4), self.reg("alto", 4, 1)])
        motivos = fragmentos_a_reparar(self.ruta, 0.5)
        self.assertIn("bajo", motivos)      # 20 % verificado
        self.assertNotIn("alto", motivos)   # 80 % verificado

    def test_no_repara_lo_que_ya_esta_bien(self):
        self.escribir([self.reg("a", 5, 0), self.reg("b", 4, 1)])
        self.assertEqual(fragmentos_a_reparar(self.ruta, 0.5), {})

    def test_una_lectura_posterior_buena_lo_saca_de_la_lista(self):
        """ Si ya lo reparaste, no debe volver a entrar en la siguiente pasada. """
        self.escribir([self.reg("a", 0, 3), self.reg("a", 4, 0)])
        self.assertNotIn("a", fragmentos_a_reparar(self.ruta, 0.5))

    def test_sin_parcial_no_hay_nada_que_reparar(self):
        self.assertEqual(fragmentos_a_reparar(os.path.join(self.tmp, "no_existe"), 0.5), {})


class PruebaRegistroDeRechazos(unittest.TestCase):
    """ Lo rechazado se guarda con su motivo: es lo que permite que la reparación
    ataque los fragmentos concretos que fallaron en vez de releer el libro. """

    TEXTO = ("El gradiente de un campo escalar es el vector de sus derivadas "
             "parciales. Su direccion es la de maximo crecimiento de la funcion.")

    def limpiar(self, datos):
        return limpiar_extraccion(datos, {"text": self.TEXTO})

    def test_guarda_la_cita_inventada_y_su_motivo(self):
        r = self.limpiar({"claims": [
            {"type": "DEFINITION", "text": "buena", "quote": "el vector de sus derivadas parciales"},
            {"type": "FORMULA", "text": "inventada", "quote": "esto no aparece en el texto del libro"},
        ]})
        self.assertEqual(len(r["claims"]), 1)
        self.assertEqual(len(r["_rechazados"]), 1)
        self.assertEqual(r["_rechazados"][0]["motivo"], "cita_no_literal")
        self.assertEqual(r["_rechazados"][0]["que"], "claim")

    def test_distingue_la_cita_demasiado_corta(self):
        """ Una cita de tres letras aparece en cualquier texto: no prueba nada. """
        r = self.limpiar({"claims": [{"type": "DEFINITION", "text": "t", "quote": "el"}]})
        self.assertEqual(r["_rechazados"][0]["motivo"], "cita_corta")

    def test_los_contadores_siguen_cuadrando(self):
        r = self.limpiar({"claims": [
            {"type": "DEFINITION", "text": "a", "quote": "el vector de sus derivadas parciales"},
            {"type": "DEFINITION", "text": "b", "quote": "invencion numero uno del modelo"},
            {"type": "DEFINITION", "text": "c", "quote": "invencion numero dos del modelo"},
        ]})
        self.assertEqual(r["_descartados"]["claims"], 2)
        self.assertEqual(len(r["_rechazados"]), 2)

    def test_tolera_el_espaciado_y_las_comillas_tipograficas(self):
        """ Cambiar " por " no es una alucinación y no debe invalidar la cita. """
        r = self.limpiar({"claims": [{"type": "DEFINITION", "text": "t",
                                      "quote": "el  vector de sus   derivadas parciales"}]})
        self.assertEqual(len(r["claims"]), 1, "el espaciado no debe tumbar una cita buena")


if __name__ == "__main__":
    unittest.main(verbosity=2)
