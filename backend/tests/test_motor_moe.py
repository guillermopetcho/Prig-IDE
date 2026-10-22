"""
Motor MoE desde Python: el cliente del motor del servidor de Rust (ai_engine/motor_moe.py).

El motor (arrancar y parar llama-server, traducir, proyectos guardados, expertos calientes) y sus pruebas están en Rust
(backend-rust/crates/prig-ia: motor.rs y moe.rs); el panel (/api/recursos/moe) lo compara el comparador de rutas. Aquí:

  · de punta a punta por el motor de IA (chat_eventos, generate_response) contra un servidor de Rust falso: el resto
    de Prig lo ve como un modelo de Ollama más, y el cliente le pasa los modelos de Ollama que hay que descargar;
  · sin servidor de Rust, un error claro en lugar de un cuelgue;
  · lo que sigue en Python: la lista de modelos, la configuración y cómo arma el chat sus mensajes.

Sin GPU ni modelo.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from ai_engine import motor_moe  # noqa: E402
from ai_engine.ai_engine_class import AIEngine  # noqa: E402


def sse(*trozos, timings=None, motivo="stop"):
    lineas = []
    for t in trozos:
        lineas.append("data: " + json.dumps({"choices": [{"index": 0, "finish_reason": None, "delta": t}]}))
    final = {"choices": [{"index": 0, "finish_reason": motivo, "delta": {}}]}
    if timings is not None:
        final["timings"] = timings
    lineas.append("data: " + json.dumps(final))
    lineas.append("data: [DONE]")
    return lineas


class LoQueSigueEnPython(unittest.TestCase):
    def test_no_disponible_sin_servidor(self):
        with mock.patch.object(motor_moe, "SERVIDOR", "/no/existe/llama-server"):
            d = motor_moe.Motor.disponible()
        self.assertFalse(d["disponible"])
        self.assertIn("compilar.sh", d["motivo"])
        with mock.patch.object(motor_moe.Motor, "disponible", staticmethod(lambda: d)):
            self.assertEqual(AIEngine._modelos_propios(), [])

    def test_contexto_viejo_por_defecto_pasa_a_automatico(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "cfg.json")
            for guardado, esperado in (({"moe_contexto": 16384}, "auto"),                      # de antes de los modos
                                       ({"moe_contexto": 16384, "moe_modo": "exacto"}, 16384),  # elegido después
                                       ({"moe_contexto": 65536}, 65536)):
                json.dump(guardado, open(ruta, "w"))
                with mock.patch("ai_engine.ai_engine_class.CONFIG_PATH", ruta):
                    self.assertEqual(AIEngine().config["moe_contexto"], esperado)

    def test_capacidades_sin_ollama(self):
        motor = AIEngine.__new__(AIEngine)
        self.assertEqual(motor.capacidades(motor_moe.NOMBRE), ["completion", "tools", "thinking"])


    def test_aparece_en_la_lista_de_modelos(self):
        disp = {"disponible": True, "motivo": None, "servidor": True, "modelo": __file__}
        with mock.patch.object(motor_moe.Motor, "disponible", staticmethod(lambda: disp)), \
                mock.patch.object(motor_moe, "SERVIDOR", __file__):
            propios = AIEngine._modelos_propios()
        self.assertEqual(propios[0]["name"], motor_moe.NOMBRE)
        self.assertEqual(propios[0]["motor"], "moe")




class RustFalso(BaseHTTPRequestHandler):
    """ Responde como las rutas /api/moe/… del servidor de Rust (NDJSON de Ollama ya traducido) """
    pedidos = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        datos = {"generando": False, "pid": None}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(datos).encode())

    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        RustFalso.pedidos.append({"_ruta": self.path, **cuerpo})
        self.send_response(200)
        if self.path.startswith("/api/ia/"):
            # generar es del servidor de Rust: eventos ya armados (prig_ia::generar)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            if self.path == "/api/ia/chat":
                eventos = [{"t": "pensando", "v": "pienso"}, {"t": "texto", "v": "Hola"}, {"t": "texto", "v": " Prig"},
                           {"t": "stats", "v": {"rondas": 1}}]
            else:
                eventos = [{"t": "pensando", "v": "pienso"}, {"t": "texto", "v": "Hola", "token": True},
                           {"t": "texto", "v": " Prig", "token": True}, {"t": "stats", "v": {"motivo_fin": "stop"}}]
            for e in eventos:
                self.wfile.write((json.dumps(e) + "\n").encode())
            return
        if not cuerpo.get("stream", True):
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"message": {"role": "assistant", "content": "listo"}, "done": True}).encode())
            return
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        generar = self.path.endswith("/generate")
        trozos = [{"thinking": "pienso"}, {"content": "Hola"}, {"content": " Prig"}]
        for t in trozos:
            linea = ({"response": t.get("content", ""), **({"thinking": t["thinking"]} if "thinking" in t else {}), "done": False}
                     if generar else {"message": {"role": "assistant", "content": t.get("content", ""), **t}, "done": False})
            self.wfile.write((json.dumps(linea) + "\n").encode())
        final = {"done": True, "done_reason": "stop", "prompt_eval_count": 10, "prompt_eval_duration": 100_000_000,
                 "eval_count": 2, "eval_duration": 50_000_000}
        final.update({"response": ""} if generar else {"message": {"role": "assistant", "content": ""}})
        self.wfile.write((json.dumps(final) + "\n").encode())


class DePuntaAPunta(unittest.TestCase):
    """ El motor de IA habla con el modelo MoE (servido por Rust) como con uno de Ollama """

    @classmethod
    def setUpClass(cls):
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), RustFalso)
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()

    def setUp(self):
        RustFalso.pedidos.clear()
        entorno = mock.patch.dict(os.environ, {"PRIG_PUERTO_RUST": str(self.servidor.server_address[1])})
        entorno.start()
        self.addCleanup(entorno.stop)
        self.ia = AIEngine()
        self.ia.gobernador = None

    def test_chat_eventos(self):
        eventos = list(self.ia.chat_eventos([{"role": "user", "content": "hola"}], motor_moe.NOMBRE, think=True))
        self.assertEqual([e["v"] for e in eventos if e["t"] == "pensando"], ["pienso"])
        self.assertEqual("".join(e["v"] for e in eventos if e["t"] == "texto"), "Hola Prig")
        pedido = RustFalso.pedidos[-1]
        self.assertEqual(pedido["_ruta"], "/api/ia/chat")
        self.assertTrue(pedido["think"])
        self.assertEqual((pedido["model"], pedido["mensajes"][-1]["content"]), (motor_moe.NOMBRE, "hola"))
        self.assertIsNone(pedido["herramientas"])
        self.assertFalse(pedido["gobernador"])

    def test_generate_response(self):
        pensado, tokens, stats = [], [], []
        partes = list(self.ia.generate_response("hola", model=motor_moe.NOMBRE, think=False, on_thinking=pensado.append,
                                                on_token=tokens.append, on_stats=stats.append))
        self.assertEqual("".join(partes), "Hola Prig")
        self.assertEqual((pensado, tokens, stats[0]["motivo_fin"]), (["pienso"], ["Hola", " Prig"], "stop"))
        pedido = RustFalso.pedidos[-1]
        self.assertEqual(pedido["_ruta"], "/api/ia/generar")
        self.assertEqual((pedido["prompt"], pedido["think"], pedido["con_pensamiento"]), ("hola", False, True))

    def test_herramientas_las_ejecuta_python(self):
        """ El servidor de Rust genera el chat y pide cada herramienta a /api/interno/herramienta """
        from ai_engine.ai_engine_class import SESIONES_HERRAMIENTAS
        import app
        from fastapi.testclient import TestClient
        vistas = {}

        class Herr:
            def definiciones(self):
                return [{"type": "function", "function": {"name": "sumar"}}]

            def ejecutar(self, nombre, argumentos):
                return str(argumentos["a"] + argumentos["b"])
        for e in self.ia.chat_eventos([{"role": "user", "content": "2+3"}], "m", herramientas=Herr()):
            pedido = RustFalso.pedidos[-1]
            sesion = pedido["herramientas"]["sesion"]
            vistas["definiciones"] = pedido["herramientas"]["definiciones"]
            r = TestClient(app.app).post("/api/interno/herramienta",
                                         json={"sesion": sesion, "nombre": "sumar", "argumentos": {"a": 2, "b": 3}})
            vistas["resultado"] = r.json()["resultado"]
            break
        self.assertEqual(vistas, {"definiciones": [{"type": "function", "function": {"name": "sumar"}}], "resultado": "5"})
        self.assertEqual(SESIONES_HERRAMIENTAS, {})             # al terminar el chat se da de baja

    def test_sin_streaming(self):
        res = motor_moe.motor().post("http://x/api/chat", {"messages": [{"role": "user", "content": "x"}], "stream": False})
        self.assertEqual(res.json()["message"]["content"], "listo")

    def test_actividad_para_el_modo_frio(self):
        self.assertFalse(motor_moe.generando())
        self.assertIsNone(motor_moe.pid_en_marcha())


class SinServidorDeRust(unittest.TestCase):
    def test_error_claro(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PRIG_PUERTO_RUST", None)
            res = motor_moe.Motor().post("http://x/api/chat", {"messages": [{"role": "user", "content": "x"}]})
            self.assertEqual(res.status_code, 503)
            self.assertIn("servidor de Rust", res.json()["error"])
            self.assertFalse(motor_moe.generando())
            with self.assertRaises(RuntimeError):
                motor_moe.Motor().directo("POST", "/completion", {})


class Endpoints(unittest.TestCase):
    """ Cómo arma el chat sus mensajes para el motor MoE """

    def setUp(self):
        import app
        self.app = app
        cfg = mock.patch.dict(app.ai_engine.config, {"moe_contexto": 16384, "moe_hilos": 0, "moe_calientes": "auto",
                                                     "moe_modo": "equilibrado", "moe_mtp": True, "moe_nucleo": "q8",
                                                     "moe_cache_gb": 32, "moe_cache_reserva_gb": 20})
        cfg.start()
        self.addCleanup(cfg.stop)
        guardar = mock.patch.object(app.ai_engine, "_save_config", lambda: None)
        guardar.start()
        self.addCleanup(guardar.stop)

    def test_el_chat_manda_el_gancho_en_su_propio_mensaje(self):
        vistos = []

        def chat_eventos(mensajes, modelo, uso, **kw):
            vistos.append(mensajes)
            return iter([{"t": "texto", "v": "ok"}])
        archivos = [{"path": "a.py", "content": "print(1)"}]
        with mock.patch.object(self.app.ai_engine, "chat_eventos", chat_eventos), \
                mock.patch.object(self.app.ai_engine.web_search, "should_auto_search", lambda q: False), \
                mock.patch.object(self.app, "_formatear_citas", lambda *a: ""), \
                mock.patch.object(self.app.book_service, "get_all_citations_for_ai", lambda *a, **k: []), \
                mock.patch.object(self.app.librerias_service, "get_all_library_citations_for_ai", lambda *a, **k: []):
            for modelo in (motor_moe.NOMBRE, "qwen2.5-coder:7b"):
                req = self.app.AIChatRequest(prompt="¿qué hace?", model=modelo, eventos=True,
                                             hooked_files=archivos, code_context="x = 2")
                respuesta = self.app.ai_chat(req)
                import asyncio

                async def consumir():
                    return [c async for c in respuesta.body_iterator]
                asyncio.run(consumir())
        moe, otro = vistos
        self.assertEqual([m["role"] for m in moe], ["system", "user", "user"])
        self.assertIn("### Archivo: a.py", moe[1]["content"])             # el proyecto, solo
        self.assertNotIn("x = 2", moe[1]["content"])                      # lo que cambia va con la pregunta
        self.assertIn("x = 2", moe[2]["content"])
        self.assertIn("¿qué hace?", moe[2]["content"])
        self.assertEqual([m["role"] for m in otro], ["system", "user"])  # otros modelos: como siempre
        self.assertIn("### Archivo: a.py", otro[1]["content"])

    def test_solo_codigo_y_sin_extras_automaticos(self):
        vistos = []

        def chat_eventos(mensajes, modelo, uso, **kw):
            vistos.append((mensajes, kw))
            return iter([{"t": "texto", "v": "ok"}])
        buscar_citas = mock.Mock(return_value=[])
        with mock.patch.object(self.app.ai_engine, "chat_eventos", chat_eventos), \
                mock.patch.object(self.app.ai_engine.web_search, "should_auto_search", lambda q: True), \
                mock.patch.object(self.app.ai_engine.web_search, "get_web_context", lambda q: ("WEB", [])), \
                mock.patch.object(self.app.book_service, "get_all_citations_for_ai", buscar_citas), \
                mock.patch.object(self.app.librerias_service, "get_all_library_citations_for_ai", lambda *a, **k: []):
            import asyncio
            for solo in (True, False):
                req = self.app.AIChatRequest(prompt="haz una función", model=motor_moe.NOMBRE, eventos=True,
                                             think=True, herramientas=True, solo_codigo=solo)
                respuesta = self.app.ai_chat(req)

                async def consumir():
                    return [c async for c in respuesta.body_iterator]
                asyncio.run(consumir())
        (codigo, kw_codigo), (normal, kw_normal) = vistos
        self.assertEqual(codigo[0]["content"], motor_moe.INSTRUCCION_SOLO_CODIGO)   # sin prompt de tutor
        self.assertEqual(kw_codigo["extra"], {motor_moe.SOLO_CODIGO: True})
        self.assertFalse(kw_codigo["think"])
        self.assertIsNone(kw_codigo["herramientas"])
        self.assertIsNone(kw_normal["extra"])
        self.assertTrue(kw_normal["think"])
        # con el motor MoE nada automático: ni web ni citas que el usuario no pidió
        self.assertNotIn("WEB", codigo[-1]["content"] + normal[-1]["content"])
        buscar_citas.assert_not_called()



if __name__ == "__main__":
    unittest.main()
