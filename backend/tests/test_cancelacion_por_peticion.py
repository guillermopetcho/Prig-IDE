"""
Cancelación por petición: cada respuesta del modelo se detiene sola si su cliente se va,
y solo esa.

  · el cliente cierra la conexión a mitad → el modelo deja de generar (no queda un
    «fantasma» ocupando la GPU hasta terminar);
  · lo mismo para los endpoints que devuelven un generador síncrono (chat, explicaciones,
    aprendizaje guiado…), envueltos con app._flujo_cancelable;
  · dos peticiones a la vez: cortar una no corta la otra (antes «Cancelar» en Desafíos
    llamaba a /api/ai/cancel y detenía lo que se estuviera generando en todas las secciones).

Contra un Ollama falso que emite un token cada 20 ms y cuenta cuántos llegó a enviar.
"""

import json
import os
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import app  # noqa: E402
from ai_engine import AIEngine  # noqa: E402

TOKENS = 400          # a 20 ms cada uno, una respuesta completa tardaría 8 s


class OllamaLento(BaseHTTPRequestHandler):
    enviados = {}     # id de la petición → tokens que llegaron a salir

    def log_message(self, *a):
        pass

    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        clave = cuerpo.get("prompt", "?")
        OllamaLento.enviados[clave] = 0
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for i in range(TOKENS):
                self.wfile.write((json.dumps({"response": f"t{i} ", "done": False}) + "\n").encode())
                self.wfile.flush()
                OllamaLento.enviados[clave] += 1
                time.sleep(0.02)
            self.wfile.write((json.dumps({"response": "", "done": True}) + "\n").encode())
        except (BrokenPipeError, ConnectionResetError):
            pass                                  # Prig cerró la conexión: se deja de generar


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestCancelacionPorPeticion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ollama = ThreadingHTTPServer(("127.0.0.1", 0), OllamaLento)
        threading.Thread(target=cls.ollama.serve_forever, daemon=True).start()
        motor = AIEngine.__new__(AIEngine)
        motor.base_url = f"http://127.0.0.1:{cls.ollama.server_address[1]}"
        motor.config = {"num_ctx": 2048, "num_gpu": -1, "temperature": 0.3, "num_predict": -1}
        motor._active_streams, motor._streams_lock = set(), threading.Lock()
        motor._cancelables, motor._capacidades = set(), {}
        motor.gobernador = None
        motor.capacidades = lambda modelo: []
        cls.motor = motor

        from fastapi import FastAPI
        import uvicorn
        web = FastAPI()

        @web.get("/generar")
        def generar(texto: str):
            def trabajo(avisar):
                for trozo in motor.generate_response(texto, model="falso"):
                    avisar({"tipo": "texto", "delta": trozo})
                return "fin"
            return app._ndjson_en_hilo(trabajo)

        from fastapi.responses import StreamingResponse

        @web.get("/generar_sync")
        def generar_sync(texto: str):
            def gen():
                for trozo in motor.generate_response(texto, model="falso"):
                    yield json.dumps({"delta": trozo}) + "\n"
            return StreamingResponse(app._flujo_cancelable(gen()), media_type="application/x-ndjson")

        cls.puerto = puerto_libre()
        cls.servidor = uvicorn.Server(uvicorn.Config(web, host="127.0.0.1", port=cls.puerto, log_level="error"))
        threading.Thread(target=cls.servidor.run, daemon=True).start()
        for _ in range(100):
            if cls.servidor.started:
                break
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.should_exit = True
        cls.ollama.shutdown()

    def leer_y_cortar(self, texto, eventos=3, ruta="generar"):
        r = requests.get(f"http://127.0.0.1:{self.puerto}/{ruta}", params={"texto": texto}, stream=True, timeout=10)
        leidos = 0
        for linea in r.iter_lines():
            if linea:
                leidos += 1
            if leidos >= eventos:
                break
        r.close()                                   # el usuario cerró la sección

    def esperar_estable(self, clave, segundos=3.0):
        """ Espera a que el contador deje de subir y devuelve su valor """
        fin = time.time() + segundos
        anterior = -1
        while time.time() < fin:
            actual = OllamaLento.enviados.get(clave, 0)
            if actual == anterior:
                return actual
            anterior = actual
            time.sleep(0.4)
        return OllamaLento.enviados.get(clave, 0)

    def test_si_el_cliente_se_va_el_modelo_deja_de_generar(self):
        self.leer_y_cortar("uno")
        enviados = self.esperar_estable("uno")
        self.assertLess(enviados, TOKENS // 4, f"siguió generando para nadie: {enviados} de {TOKENS} tokens")

    def test_generador_sincrono_tambien_se_detiene(self):
        self.leer_y_cortar("sync", ruta="generar_sync")
        enviados = self.esperar_estable("sync")
        self.assertLess(enviados, TOKENS // 4, f"siguió generando para nadie: {enviados} de {TOKENS} tokens")

    def test_generador_sincrono_completo_llega_entero(self):
        r = requests.get(f"http://127.0.0.1:{self.puerto}/generar_sync", params={"texto": "sync-entera"}, stream=True, timeout=30)
        trozos = [json.loads(l)["delta"] for l in r.iter_lines() if l]
        self.assertEqual(OllamaLento.enviados["sync-entera"], TOKENS)
        self.assertEqual("".join(trozos), "".join(f"t{i} " for i in range(TOKENS)))

    def test_cortar_una_no_corta_la_otra(self):
        completa = {}

        def leer_entera():
            r = requests.get(f"http://127.0.0.1:{self.puerto}/generar", params={"texto": "entera"}, stream=True, timeout=30)
            eventos = [json.loads(l) for l in r.iter_lines() if l]
            completa["ultimo"] = eventos[-1]
        hilo = threading.Thread(target=leer_entera)
        hilo.start()
        time.sleep(0.3)
        self.leer_y_cortar("cortada")
        hilo.join(timeout=30)
        self.assertLess(self.esperar_estable("cortada"), TOKENS // 4)
        self.assertEqual(OllamaLento.enviados["entera"], TOKENS)           # la otra llegó hasta el final
        self.assertEqual(completa["ultimo"], {"tipo": "fin", "resultado": "fin"})


if __name__ == "__main__":
    unittest.main()
