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

Gemini es del servidor de Rust (prig_ia::gemini): estas pruebas lo arrancan de verdad (target/release/prig-server)
y hablan con él por HTTP, como la interfaz. Sin el binario compilado, se omiten.
"""

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gemini_motor as gm
from tests import gemini_falso as falso
from runner import CodeRunner
from desafios import tutor
from desafios.ejecucion import ErrorDesafio

SERVIDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "backend-rust", "target", "release", "prig-server")


class ErrorGemini(Exception):
    pass


@unittest.skipUnless(os.path.exists(SERVIDOR), "falta el servidor de Rust (cargo build --release -p prig-server)")
class _ConServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.servidor = falso.arrancar()
        cls.tmp = tempfile.mkdtemp(prefix="prig_gemini_")
        cls.archivo = os.path.join(cls.tmp, "gemini.json")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.puerto = s.getsockname()[1]
        entorno = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        entorno.update(PRIG_GEMINI_ARCHIVO=cls.archivo, PRIG_GEMINI_URL=cls.url, HOME=cls.tmp,
                       PRIG_SIN_MOTOR_SUAVE="1", PRIG_SIN_AUTOARRANQUE_OLLAMA="1", PRIG_SIN_LIMPIAR_HUERFANOS="1")
        cls.rust = subprocess.Popen([SERVIDOR, "--port", str(cls.puerto), "--fallback-port", "9"], env=entorno,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                requests.get(f"http://127.0.0.1:{cls.puerto}/api/health", timeout=1)
                break
            except requests.RequestException:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.rust.terminate()
        cls.rust.wait(10)
        cls.servidor.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        entorno = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        entorno.update(PRIG_GEMINI_ARCHIVO=self.archivo, PRIG_PUERTO_RUST=str(self.puerto))
        self.env = mock.patch.dict(os.environ, entorno, clear=True)
        self.env.start()
        requests.delete(self.api("/api/gemini/clave"))      # sin clave ni caché de una prueba anterior
        falso.Manejador.peticiones.clear()

    def tearDown(self):
        self.env.stop()

    def api(self, ruta):
        return f"http://127.0.0.1:{self.puerto}{ruta}"

    def estado(self):
        return requests.get(self.api("/api/gemini/estado")).json()

    def guardar_clave(self, clave, acepto_aviso=True):
        r = requests.post(self.api("/api/gemini/clave"), json={"clave": clave, "acepto_aviso": acepto_aviso})
        if r.status_code == 400:
            raise ErrorGemini(r.json()["detail"])
        return r.json()

    def listar_modelos(self):
        r = requests.get(self.api("/api/gemini/modelos"))
        if r.status_code == 400:
            raise ErrorGemini(r.json()["detail"])
        return r.json()["modelos"]

    def conectar(self):
        return self.guardar_clave(falso.CLAVE_VALIDA)


class PruebaClave(_ConServidor):

    def test_sin_conectar(self):
        e = self.estado()
        self.assertFalse(e["configurado"])
        self.assertIn("mejorar sus productos", e["aviso"])
        self.assertEqual(e["url_claves"], "https://aistudio.google.com/apikey")
        with self.assertRaises(ErrorGemini):
            self.listar_modelos()

    def test_clave_nueva_de_ai_studio_con_formato_aq(self):
        """ El fallo real: la clave «AQ.…» (con puntos) se rechazaba como «no parece una clave» """
        r = self.guardar_clave(falso.CLAVE_AQ)
        self.assertTrue(r["configurado"])
        self.assertEqual(r["clave"], "AQ.A…5678")
        self.assertEqual(gm.clave_actual()[0], falso.CLAVE_AQ)
        self.assertEqual(falso.Manejador.peticiones[-1]["clave"], falso.CLAVE_AQ)   # tal cual, en la cabecera
        self.assertEqual([m["id"] for m in self.listar_modelos()], ["gemini-3-flash", "gemini-3.1-flash-lite"])

    def test_aq_desconocida_explica_en_castellano(self):
        with self.assertRaises(ErrorGemini) as e:
            self.guardar_clave("AQ.Ab8RN6PRUEBAinventada_no-valida.000000000000")
        self.assertIn("Google no reconoce esta clave", str(e.exception))
        self.assertNotIn("OAuth", str(e.exception))
        self.assertNotIn("inventada", str(e.exception))

    def test_guardar_exige_aviso_y_clave_valida(self):
        with self.assertRaises(ErrorGemini) as e:
            self.guardar_clave(falso.CLAVE_VALIDA, acepto_aviso=False)
        self.assertIn("aviso", str(e.exception))
        with self.assertRaises(ErrorGemini):
            self.guardar_clave("esto no es una clave")
        with self.assertRaises(ErrorGemini) as e:
            self.guardar_clave("AIzaSyPRUEBA_inventada_no_valida_000")
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
        self.assertFalse(requests.delete(self.api("/api/gemini/clave")).json()["configurado"])
        self.assertFalse(os.path.exists(gm.ruta_config()))

    def test_clave_por_variable_de_entorno(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": falso.CLAVE_VALIDA}):
            self.assertEqual(gm.clave_actual(), (falso.CLAVE_VALIDA, "entorno"))

    def test_no_usa_la_sesion_de_gemini_cli(self):
        raiz = os.path.dirname(SERVIDOR).replace(os.path.join("target", "release"), "")
        for fuente in (gm.__file__, os.path.join(raiz, "crates", "prig-ia", "src", "gemini.rs")):
            with open(fuente, encoding="utf-8") as f:
                codigo = f.read()
            codigo = codigo.split('"""', 2)[2] if fuente.endswith(".py") else \
                "\n".join(l for l in codigo.splitlines() if not l.lstrip().startswith("//"))
            self.assertNotIn("oauth_creds", codigo)
            self.assertNotIn(".gemini/", codigo)


class PruebaModelosYStreaming(_ConServidor):

    def test_lista_solo_gemini_de_texto_y_pagina(self):
        self.conectar()
        ids = [m["id"] for m in self.listar_modelos()]
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
        requests.delete(self.api("/api/gemini/clave"))
        self.assertIn("no está conectado", "".join(motor.generate_response("x", "gemini-3-flash")))


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
