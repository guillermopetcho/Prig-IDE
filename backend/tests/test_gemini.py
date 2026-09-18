"""
Google Gemini como motor opcional de los desafíos.

Contra un servidor falso (tests/gemini_falso.py) que imita las respuestas reales de la
API, incluido el error 400 API_KEY_INVALID medido con una clave inventada. Se protege:

  · la clave se guarda con permisos 600, nunca se devuelve entera y va en la cabecera,
    nunca en la URL ni en los mensajes de error;
  · no se guarda una clave sin aceptar el aviso de privacidad ni una que Google rechaza;
  · se listan solo modelos Gemini que generan texto, paginando;
  · el streaming ignora el pensamiento del modelo y explica bloqueos, cuota y errores;
  · el tutor de desafíos funciona igual con Gemini: crea un desafío y lo verifica ejecutándolo;
  · la sesión de Gemini CLI (~/.gemini/oauth_creds.json) no se usa.
"""

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gemini_motor as gm
from tests import gemini_falso as falso
from runner import CodeRunner
from desafios import tutor
from desafios.ejecucion import ErrorDesafio


class _ConServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.servidor = falso.arrancar()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_gemini_")
        entorno = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        entorno.update(PRIG_GEMINI_ARCHIVO=os.path.join(self.tmp, "gemini.json"), PRIG_GEMINI_URL=self.url)
        self.env = mock.patch.dict(os.environ, entorno, clear=True)
        self.env.start()
        gm._cache.clear()
        falso.Manejador.peticiones.clear()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conectar(self):
        return gm.guardar_clave(falso.CLAVE_VALIDA, acepto_aviso=True)


class PruebaClave(_ConServidor):

    def test_sin_conectar(self):
        e = gm.estado()
        self.assertFalse(e["configurado"])
        self.assertIn("mejorar sus productos", e["aviso"])
        self.assertEqual(e["url_claves"], "https://aistudio.google.com/apikey")
        with self.assertRaises(gm.ErrorGemini):
            gm.listar_modelos()

    def test_clave_nueva_de_ai_studio_con_formato_aq(self):
        """ El fallo real: la clave «AQ.…» (con puntos) se rechazaba como «no parece una clave» """
        r = gm.guardar_clave(falso.CLAVE_AQ, acepto_aviso=True)
        self.assertTrue(r["configurado"])
        self.assertEqual(r["clave"], "AQ.A…5678")
        self.assertEqual(gm.clave_actual()[0], falso.CLAVE_AQ)
        self.assertEqual(falso.Manejador.peticiones[-1]["clave"], falso.CLAVE_AQ)   # tal cual, en la cabecera
        self.assertEqual([m["id"] for m in gm.listar_modelos()], ["gemini-3-flash", "gemini-3.1-flash-lite"])

    def test_aq_desconocida_explica_en_castellano(self):
        with self.assertRaises(gm.ErrorGemini) as e:
            gm.guardar_clave("AQ.Ab8RN6PRUEBAinventada_no-valida.000000000000", acepto_aviso=True)
        self.assertIn("Google no reconoce esta clave", str(e.exception))
        self.assertNotIn("OAuth", str(e.exception))
        self.assertNotIn("inventada", str(e.exception))

    def test_limpiar_lo_pegado(self):
        for pegado in (f"  {falso.CLAVE_AQ}\n", f'"{falso.CLAVE_AQ}"', f"'{falso.CLAVE_AQ}'", f"`{falso.CLAVE_AQ}`",
                       f"GEMINI_API_KEY={falso.CLAVE_AQ}", f'export GEMINI_API_KEY="{falso.CLAVE_AQ}"',
                       f"x-goog-api-key: {falso.CLAVE_AQ}", f"\u200b{falso.CLAVE_AQ}\ufeff",
                       f"https://generativelanguage.googleapis.com/v1beta/models?key={falso.CLAVE_AQ}&pageSize=1"):
            self.assertEqual(gm.limpiar_clave(pegado), falso.CLAVE_AQ, repr(pegado))
        self.assertEqual(gm.limpiar_clave(falso.CLAVE_VALIDA), falso.CLAVE_VALIDA)
        casos = {"": "ninguna clave", "   ": "ninguna clave", "AQ.corta": "falta un trozo",
                 "AQ.Ab8RN6 PRUEBA_formato.nuevo123": "espacios", f"{falso.CLAVE_AQ}\nsegunda línea": "espacios",
                 "AQ.Ab8RN6PRUEBAñandú_formato.nuevo": "caracteres"}
        for pegado, motivo in casos.items():
            with self.assertRaises(gm.ErrorGemini, msg=repr(pegado)) as e:
                gm.limpiar_clave(pegado)
            self.assertIn(motivo, str(e.exception))
            self.assertNotIn("PRUEBA", str(e.exception))         # nunca repite lo pegado

    def test_guardar_exige_aviso_y_clave_valida(self):
        with self.assertRaises(gm.ErrorGemini) as e:
            gm.guardar_clave(falso.CLAVE_VALIDA, acepto_aviso=False)
        self.assertIn("aviso", str(e.exception))
        with self.assertRaises(gm.ErrorGemini):
            gm.guardar_clave("esto no es una clave", acepto_aviso=True)
        with self.assertRaises(gm.ErrorGemini) as e:
            gm.guardar_clave("AIzaSyPRUEBA_inventada_no_valida_000", acepto_aviso=True)
        self.assertIn("no es válida", str(e.exception))
        self.assertFalse(os.path.exists(gm.ruta_config()))       # la rechazada no se guarda

    def test_guardada_con_permisos_600_y_enmascarada(self):
        r = self.conectar()
        self.assertTrue(r["configurado"])
        self.assertEqual(r["origen"], "prig")
        self.assertEqual(stat.S_IMODE(os.stat(gm.ruta_config()).st_mode), 0o600)
        self.assertNotIn(falso.CLAVE_VALIDA, json.dumps(r))
        self.assertEqual(r["clave"], "AIza…abcd")
        self.assertTrue(r["aviso_aceptado"])
        self.assertTrue(all(not p["clave_en_url"] for p in falso.Manejador.peticiones))
        self.assertFalse(gm.borrar_clave()["configurado"])
        self.assertFalse(os.path.exists(gm.ruta_config()))

    def test_clave_por_variable_de_entorno(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": falso.CLAVE_VALIDA}):
            e = gm.estado()
            self.assertEqual((e["configurado"], e["origen"]), (True, "entorno"))

    def test_no_usa_la_sesion_de_gemini_cli(self):
        fuente = open(gm.__file__, encoding="utf-8").read()
        codigo = fuente.split('"""', 2)[2]                       # sin el docstring que lo explica
        self.assertNotIn("oauth_creds", codigo)
        self.assertNotIn(".gemini", codigo)


class PruebaModelosYStreaming(_ConServidor):

    def test_lista_solo_gemini_de_texto_y_pagina(self):
        self.conectar()
        ids = [m["id"] for m in gm.listar_modelos()]
        self.assertEqual(ids, ["gemini-3-flash", "gemini-3.1-flash-lite"])
        self.assertTrue(any("pageToken=pagina2" in p["ruta"] for p in falso.Manejador.peticiones))

    def test_stream_ignora_el_pensamiento(self):
        self.conectar()
        motor = gm.MotorGemini(lambda t: json.loads(t))
        tokens, pensado, stats = [], [], []
        texto = "".join(motor.generate_response("hola", "gemini-3-flash", "sé breve", options={"temperature": 0.2},
                                                on_token=tokens.append, on_thinking=pensado.append, on_stats=stats.append))
        self.assertEqual(texto, "Respuesta de Gemini de prueba.")
        self.assertNotIn("secreto", texto)
        self.assertEqual(pensado, ["pienso en secreto"])
        self.assertEqual("".join(tokens), texto)
        self.assertEqual(stats[-1]["candidatesTokenCount"], 20)
        cuerpo = falso.Manejador.peticiones[-1]["cuerpo"]
        self.assertEqual(cuerpo["systemInstruction"]["parts"][0]["text"], "sé breve")
        self.assertEqual(cuerpo["generationConfig"]["temperature"], 0.2)

    def test_errores_explicados_sin_la_clave(self):
        self.conectar()
        motor = gm.MotorGemini(json.loads)
        self.assertIn("no existe", "".join(motor.generate_response("x", "no-existe")))
        self.assertIn("filtros (SAFETY)", "".join(motor.generate_response("BLOQUEAR esto", "gemini-3-flash")))
        with open(gm.ruta_config(), "w") as f:
            json.dump({"clave": falso.CLAVE_SIN_CUOTA}, f)
        salida = "".join(motor.generate_response("x", "gemini-3-flash"))
        self.assertIn("límite gratuito", salida)
        self.assertNotIn(falso.CLAVE_SIN_CUOTA, salida)
        self.assertNotIn(falso.CLAVE_VALIDA, gm._explicar(403, json.dumps({"error": {"message": f"clave {falso.CLAVE_VALIDA} mala"}}), falso.CLAVE_VALIDA))
        gm.borrar_clave()
        self.assertIn("no está conectado", "".join(motor.generate_response("x", "gemini-3-flash")))

    def test_sin_internet(self):
        self.conectar()
        with mock.patch.dict(os.environ, {"PRIG_GEMINI_URL": "http://127.0.0.1:9/v1beta"}):
            self.assertIn("Sin conexión", "".join(gm.MotorGemini(json.loads).generate_response("x", "gemini-3-flash")))


class PruebaDesafiosConGemini(_ConServidor):

    def motor(self):
        from ai_engine import AIEngine
        return gm.MotorGemini(lambda t: AIEngine._extract_and_parse_json(None, t))

    def test_crea_un_desafio_verificado(self):
        self.conectar()
        d = tutor.crear(self.motor(), CodeRunner(), "gemini-3-flash", "cadenas", "principiante")
        self.assertEqual(d["titulo"], "Contar vocales")
        self.assertEqual(d["comprobacion"]["pruebas"], 4)
        self.assertIn("pass", d["paginas"][0]["contenido"])      # el cuerpo vacío se reparó

    def test_caja_de_razonamiento(self):
        self.conectar()
        gen = tutor.razonamiento(self.motor(), "gemini-3-flash", {"titulo": "T", "enunciado": "E", "paginas": []})
        eventos = []
        try:
            while True:
                eventos.append(next(gen))
        except StopIteration as fin:
            pasos = fin.value
        self.assertEqual([p["titulo"] for p in pasos], tutor.PASOS)
        self.assertNotIn("secreto", "".join(e.get("delta", "") for e in eventos))

    def test_error_de_gemini_llega_como_mensaje(self):
        with open(gm.ruta_config(), "w") as f:
            json.dump({"clave": falso.CLAVE_SIN_CUOTA}, f)
        with self.assertRaises(ErrorDesafio) as e:
            tutor.crear(self.motor(), CodeRunner(), "gemini-3-flash", "cadenas")
        self.assertIn("límite gratuito", str(e.exception))


if __name__ == "__main__":
    unittest.main()
