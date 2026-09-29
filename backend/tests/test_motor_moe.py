"""
Motor MoE: Qwen3.6-35B-A3B con expertos calientes en la GPU, servido por un llama-server propio.

  · traducción Ollama → OpenAI: mensajes, razonamiento, llamadas a herramientas (argumentos como
    texto, tool_name → tool_call_id), opciones, think, formato JSON;
  · traducción de la respuesta: texto, razonamiento, herramientas, probabilidades y métricas con
    las unidades de Ollama; al continuar un mensaje del asistente, llama-server repite lo ya
    escrito (medido) y se quita;
  · expertos calientes que caben en la VRAM, keep_alive, el GGUF descargado por Ollama;
  · de punta a punta por el motor de IA (chat_eventos, generate_response) contra un
    llama-server falso: el resto de Prig lo ve como un modelo de Ollama más.

Sin GPU ni modelo: el servidor es un http.server local que responde como llama-server.
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


class Traduccion(unittest.TestCase):
    def test_chat_opciones_y_think(self):
        cuerpo, prefijos = motor_moe.a_openai("http://x/api/chat", {
            "model": motor_moe.NOMBRE, "stream": True, "think": False, "format": "json",
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
            "options": {"temperature": 0.2, "top_k": 20, "num_predict": 300, "num_ctx": 8192,
                        "num_thread": 4, "stop": ["</fin>"]}})
        self.assertEqual(cuerpo["messages"], [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
        self.assertEqual(cuerpo["temperature"], 0.2)
        self.assertEqual(cuerpo["top_k"], 20)
        self.assertEqual(cuerpo["max_tokens"], 300)
        self.assertEqual(cuerpo["stop"], ["</fin>"])
        self.assertNotIn("num_ctx", cuerpo)            # el contexto lo fija el servidor al arrancar
        self.assertEqual(cuerpo["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(cuerpo["response_format"], {"type": "json_object"})
        self.assertTrue(cuerpo["stream"])
        self.assertEqual(prefijos, {"content": "", "thinking": ""})

    def test_generate_y_esquema(self):
        esquema = {"type": "object", "properties": {"a": {"type": "integer"}}}
        cuerpo, _ = motor_moe.a_openai("http://x/api/generate", {
            "prompt": "p", "system": "s", "stream": False, "format": esquema, "options": {"num_predict": -1}})
        self.assertEqual(cuerpo["messages"], [{"role": "system", "content": "s"}, {"role": "user", "content": "p"}])
        self.assertFalse(cuerpo["stream"])
        self.assertNotIn("max_tokens", cuerpo)
        self.assertEqual(cuerpo["response_format"]["json_schema"]["schema"], esquema)
        # think sin fijar: sin razonamiento (Qwen3.6 razonaría por defecto: tokens que nadie pidió)
        self.assertEqual(cuerpo["chat_template_kwargs"], {"enable_thinking": False})
        cuerpo, _ = motor_moe.a_openai("http://x/api/generate", {"prompt": "p", "think": True})
        self.assertEqual(cuerpo["chat_template_kwargs"], {"enable_thinking": True})

    def test_solo_codigo(self):
        cuerpo, _ = motor_moe.a_openai("http://x/api/chat", {
            "messages": [{"role": "user", "content": "una función"}], "think": True, motor_moe.SOLO_CODIGO: True})
        self.assertEqual(cuerpo["chat_template_kwargs"], {"enable_thinking": False})   # nunca razona
        self.assertEqual(cuerpo["grammar"], motor_moe.GRAMATICA_CODIGO)
        self.assertIn("root", motor_moe.GRAMATICA_CODIGO)
        cuerpo, _ = motor_moe.a_openai("http://x/api/chat", {"messages": [{"role": "user", "content": "x"}]})
        self.assertNotIn("grammar", cuerpo)

    def test_muestreo_segun_el_uso(self):
        pedir = lambda **kw: motor_moe.a_openai("http://x/api/chat", {"messages": [{"role": "user", "content": "x"}], **kw})[0]
        self.assertEqual(pedir()["temperature"], 0.7)                                  # charla sin razonar
        self.assertEqual(pedir()["top_p"], 0.8)
        self.assertEqual(pedir(think=True)["temperature"], 0.6)                        # razonar
        self.assertEqual(pedir(**{motor_moe.SOLO_CODIGO: True})["temperature"], 0.6)   # código
        self.assertEqual(pedir(format="json")["temperature"], 0.3)                     # preciso
        self.assertEqual(pedir(**{motor_moe.PERFIL: "preciso"})["temperature"], 0.3)
        # Lo que fija quien pide manda sobre el perfil
        self.assertEqual(pedir(options={"temperature": 0.1})["temperature"], 0.1)
        self.assertEqual(pedir(options={"temperature": 0.1})["top_p"], 0.8)

    def test_herramientas_y_continuacion(self):
        cuerpo, prefijos = motor_moe.a_openai("http://x/api/chat", {"messages": [
            {"role": "user", "content": "¿clima?"},
            {"role": "assistant", "content": "", "thinking": "busco",
             "tool_calls": [{"function": {"name": "buscar", "arguments": {"q": "clima"}}},
                            {"function": {"name": "leer", "arguments": {"url": "u"}}}]},
            {"role": "tool", "tool_name": "leer", "content": "r2"},
            {"role": "tool", "tool_name": "buscar", "content": "r1"},
            {"role": "assistant", "content": "Según", "thinking": "ya está"}],
            "tools": [{"type": "function", "function": {"name": "buscar"}}], "logprobs": True, "top_logprobs": 3})
        asistente = cuerpo["messages"][1]
        self.assertEqual(asistente["reasoning_content"], "busco")
        self.assertEqual(asistente["tool_calls"][0]["function"], {"name": "buscar", "arguments": '{"q": "clima"}'})
        ids = {c["function"]["name"]: c["id"] for c in asistente["tool_calls"]}
        # cada resultado apunta a la llamada de su herramienta, aunque lleguen en otro orden
        self.assertEqual(cuerpo["messages"][2]["tool_call_id"], ids["leer"])
        self.assertEqual(cuerpo["messages"][3]["tool_call_id"], ids["buscar"])
        self.assertEqual(cuerpo["tools"][0]["function"]["name"], "buscar")
        self.assertEqual((cuerpo["logprobs"], cuerpo["top_logprobs"]), (True, 3))
        self.assertEqual(prefijos, {"content": "Según", "thinking": "ya está"})

    def test_respuesta_en_streaming(self):
        lineas = sse({"role": "assistant", "content": None},
                     {"reasoning_content": "Pien"}, {"reasoning_content": "so."},
                     {"content": "Hola"}, {"content": " mundo"},
                     timings={"prompt_n": 20, "prompt_ms": 400.0, "predicted_n": 5, "predicted_ms": 200.0})
        salida = list(motor_moe.a_ollama("http://x/api/chat", iter(lineas), {"content": "", "thinking": ""}, carga_s=2.0))
        self.assertEqual([o["message"].get("thinking") for o in salida[:2]], ["Pien", "so."])
        self.assertEqual("".join(o["message"]["content"] for o in salida[:-1]), "Hola mundo")
        final = salida[-1]
        self.assertTrue(final["done"])
        self.assertEqual(final["done_reason"], "stop")
        self.assertEqual(final["prompt_eval_count"], 20)
        self.assertEqual(final["eval_count"], 5)
        self.assertEqual(final["eval_duration"], 200_000_000)
        self.assertEqual(final["load_duration"], 2_000_000_000)
        m = AIEngine.metricas({**final, "contexto": 131072}, 8192)
        self.assertEqual(m["contexto"], 131072)                 # el real del motor, no el pedido
        m = AIEngine.metricas(final, 8192)
        self.assertEqual(m["generacion_tok_s"], 25.0)
        self.assertEqual(m["lectura_tok_s"], 50.0)

    def test_continuacion_quita_lo_ya_escrito(self):
        # medido en llama-server: el primer trozo repite el mensaje del asistente que se continúa
        lineas = sse({"content": "El mar de Plutón, dijo Ramírez, es un"}, {"content": " mar"},
                     {"reasoning_content": "Multiplico: 17 por 3 da "}, {"reasoning_content": "51"})
        salida = list(motor_moe.a_ollama("http://x/api/chat", iter(lineas),
                                         {"content": "El mar de Plutón, dijo Ramírez, es", "thinking": "Multiplico: 17 por 3 da"}))
        texto = "".join(o["message"]["content"] for o in salida[:-1])
        razonamiento = "".join(o["message"].get("thinking", "") for o in salida[:-1])
        self.assertEqual(texto, " un mar")
        self.assertEqual(razonamiento, " 51")

    def test_prefijo_en_varios_trozos(self):
        p = motor_moe._Prefijo("abcdef")
        self.assertEqual([p.filtrar(t) for t in ("ab", "cd", "efgh", "ij")], ["", "", "gh", "ij"])
        p = motor_moe._Prefijo("abc")
        self.assertEqual(p.filtrar("xyz"), "xyz")       # si no coincide, no se come nada

    def test_herramientas_en_streaming(self):
        lineas = sse({"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "buscar", "arguments": '{"q":'}}]},
                     {"tool_calls": [{"index": 0, "function": {"arguments": ' "x"}'}}]},
                     motivo="tool_calls")
        salida = list(motor_moe.a_ollama("http://x/api/chat", iter(lineas), {}))
        self.assertEqual(len(salida), 1)
        self.assertEqual(salida[0]["message"]["tool_calls"],
                         [{"id": "c1", "function": {"name": "buscar", "arguments": {"q": "x"}}}])

    def test_generate_en_streaming_y_largo(self):
        lineas = sse({"content": "uno"}, {"reasoning_content": "r"}, motivo="length")
        salida = list(motor_moe.a_ollama("http://x/api/generate", iter(lineas), {}))
        self.assertEqual(salida[0]["response"], "uno")
        self.assertEqual(salida[1]["thinking"], "r")
        self.assertEqual(salida[-1]["done_reason"], "length")
        self.assertIn("response", salida[-1])

    def test_probabilidades(self):
        linea = "data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": "a"}, "logprobs": {"content": [
            {"token": "a", "logprob": -0.1, "top_logprobs": [{"token": "a", "logprob": -0.1}, {"token": "b", "logprob": -2.0}]}]}}]})
        salida = list(motor_moe.a_ollama("http://x/api/chat", iter([linea, "data: [DONE]"]), {}))
        self.assertEqual(salida[0]["logprobs"][0]["top_logprobs"][1], {"token": "b", "logprob": -2.0})

    def test_error_del_servidor(self):
        linea = "data: " + json.dumps({"error": {"message": "contexto lleno"}})
        self.assertEqual(list(motor_moe.a_ollama("http://x/api/chat", iter([linea]), {})), [{"error": "contexto lleno"}])

    def test_respuesta_completa(self):
        datos = motor_moe.a_ollama_completo("http://x/api/chat", {
            "choices": [{"finish_reason": "stop", "message": {"content": "Hola, sigo", "reasoning_content": "r",
                                                              "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{}"}}]}}],
            "timings": {"predicted_n": 3, "predicted_ms": 30}}, {"content": "Hola,", "thinking": ""})
        self.assertEqual(datos["message"]["content"], " sigo")
        self.assertEqual(datos["message"]["thinking"], "r")
        self.assertEqual(datos["message"]["tool_calls"][0]["function"]["arguments"], {})
        self.assertEqual(datos["eval_count"], 3)


class Ajustes(unittest.TestCase):
    def test_keep_alive(self):
        k = motor_moe.segundos_keep_alive
        self.assertEqual([k("5m"), k("1h"), k("30s"), k(0), k(-1), k("10"), k(None), k("raro", 7)],
                         [300, 3600, 30, 0, -1, 10, 300, 7])

    def test_calientes_segun_vram(self):
        c = motor_moe.calientes_para
        self.assertEqual(c(None, 8192), 0)
        self.assertEqual(c(2000, 8192), 0)             # no cabe ni el núcleo: todo en RAM
        self.assertEqual(c(6100, 16384), 53)           # 6 GB libres con 16K (lotes de 2048), sin MTP
        self.assertLess(c(5800, 32768), c(5800, 8192))  # más contexto, menos expertos calientes
        self.assertEqual(c(24000, 8192), motor_moe.MAX_CALIENTES)

    def test_contexto_automatico(self):
        self.assertEqual(motor_moe.contexto_para(1000), 32768)          # empieza en 32K
        self.assertEqual(motor_moe.contexto_para(40000), 65536)
        self.assertEqual(motor_moe.contexto_para(200000), 262144)
        self.assertIsNone(motor_moe.contexto_para(300000))
        self.assertEqual([motor_moe.lote_para(c) for c in (16384, 32768, 65536, 131072, 262144)],
                         [2048, 2048, 2048, 2048, 1024])
        self.assertEqual(motor_moe.base_mb(100000), 3739)               # el medido igual o mayor
        self.assertEqual(motor_moe.base_mb(100000, mtp=True), 4799)
        pedido = {"messages": [{"role": "user", "content": "x" * 30000}], "options": {"num_predict": 1000}}
        self.assertEqual(motor_moe.estimar_tokens(pedido), 10000 + 1000 + 512)
        self.assertEqual(motor_moe.estimar_tokens({"prompt": "x" * 300}), 100 + 4096 + 512)

    def test_nucleo_q8(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(motor_moe, "CARPETA_MODELOS", d), \
                mock.patch.object(motor_moe, "blob_del_modelo", lambda: "/q4.gguf"):
            self.assertEqual(motor_moe.modelo_para("q8"), "/q4.gguf")          # sin construir: el Q4
            ruta = os.path.join(d, motor_moe.NUCLEOS["q8"])
            open(ruta, "wb").close()
            open(ruta + ".partes", "w").close()
            self.assertEqual(motor_moe.modelo_para("q8"), "/q4.gguf")          # a medias: el Q4
            os.remove(ruta + ".partes")
            self.assertEqual(motor_moe.modelo_para("q8"), ruta)
            self.assertEqual(motor_moe.modelo_para("q4"), "/q4.gguf")
            self.assertEqual(motor_moe.mb_por_caliente(ruta), motor_moe.MB_POR_CALIENTE)   # no es GGUF
            self.assertEqual(motor_moe.mb_nucleo_extra(ruta), 0.0)
        # un núcleo más grande deja menos sitio para los calientes
        self.assertLess(motor_moe.calientes_para(6126, 16384, extra_mb=670),
                        motor_moe.calientes_para(6126, 16384))

    def test_lista_caliente(self):
        global_ = [[2, 0, 1, 3]]
        self.assertEqual(motor_moe.lista_caliente([[0, 7, 0, 7]], global_), [[1, 3, 2, 0]])  # empates: orden global
        self.assertIsNone(motor_moe.lista_caliente([[0, 0, 0, 0]], global_))                # sin datos: nada
        self.assertEqual(len(motor_moe.lista_global()), 40)

    def test_prefijo_de_un_proyecto(self):
        grande = {"role": "user", "content": "x" * motor_moe.PROYECTO_MIN_CARACTERES}
        pregunta = {"role": "user", "content": "¿qué hace?"}
        sistema = {"role": "system", "content": "s"}
        self.assertEqual(motor_moe.prefijo_de({"messages": [sistema, grande, pregunta]}), [sistema, grande])
        self.assertIsNone(motor_moe.prefijo_de({"messages": [sistema, grande]}))          # sin pregunta aparte
        self.assertIsNone(motor_moe.prefijo_de({"messages": [sistema, pregunta, grande]}))  # el primero es chico
        self.assertIsNone(motor_moe.prefijo_de({"messages": []}))

    def test_podar_proyectos(self):
        with tempfile.TemporaryDirectory() as d:
            for i, nombre in enumerate(("viejo", "medio", "nuevo")):
                ruta = os.path.join(d, nombre + ".bin")
                open(ruta, "wb").write(b"x" * 1_000_000)
                os.utime(ruta, (1000 + i, 1000 + i))
            self.assertEqual(motor_moe.proyectos_guardados(d)["mb"], 3)
            self.assertEqual(motor_moe.podar_proyectos(d, limite_mb=2), 1)
            self.assertEqual(sorted(os.listdir(d)), ["medio.bin", "nuevo.bin"])

    def test_mtp_reserva_vram(self):
        c = motor_moe.calientes_para
        self.assertLess(c(6100, 16384, mtp=True), c(6100, 16384))
        self.assertEqual(c(6126, 16384, mtp=True), 42)
        self.assertEqual(c(6126, 131072, mtp=True), 10)                  # medido: con 17 no arrancó
        self.assertFalse(motor_moe.cabe_mtp(6126, 262144))               # con 256K no queda sitio
        self.assertTrue(motor_moe.cabe_mtp(6126, 131072))

    def test_orden_segun_modo_y_mtp(self):
        m = motor_moe.Motor(ajustes=lambda: {"contexto": 8192, "modo": "rapido"})
        m._registro = lambda t: None
        cmd, env, modo = m.orden("/m.gguf", 40, mtp=True)
        self.assertEqual(modo, "rapido")
        self.assertIn("draft-mtp", cmd)
        tras = cmd[cmd.index(motor_moe.SERVIDOR):]
        self.assertEqual(tras[tras.index("-c") + 1], "8192")
        self.assertEqual((env["AIPC_MOE_HOT_N"], env["AIPC_COLD_SKIP"], env["AIPC_OVERLAP"], env["AIPC_COLD_DROP"]),
                         ("40", "1", "1", "0.1"))
        m.ajustes = lambda: {"modo": "exacto"}
        cmd, env, modo = m.orden("/m.gguf", 40, mtp=False)
        self.assertNotIn("draft-mtp", cmd)
        self.assertNotIn("AIPC_COLD_DROP", env)           # exacto: el mismo resultado que el modelo original
        with mock.patch.dict(os.environ, {"AIPC_HOT_BIAS": "0.5"}):
            _, env, _ = m.orden("/m.gguf", 0)
        self.assertFalse([k for k in env if k.startswith("AIPC_")])   # sin calientes, nada; ni lo heredado
        m.ajustes = lambda: {"modo": "inventado"}
        self.assertEqual(m.orden("/m.gguf", 40)[2], motor_moe.MODO)

    def test_si_no_cabe_reintenta_sin_mtp(self):
        m = motor_moe.Motor(ajustes=lambda: {"contexto": 16384})
        m._registro = lambda t: None
        m._arrancar_vigia = lambda: None
        intentos = []
        m._lanzar = lambda blob, n, mtp=False: intentos.append((n, mtp)) or (not mtp and n > 0)
        disp = {"disponible": True, "motivo": None, "servidor": True, "modelo": "/m.gguf"}
        with mock.patch.object(motor_moe.Motor, "disponible", staticmethod(lambda: disp)), \
                mock.patch.object(motor_moe, "vram_libre_estable", lambda: 6100.0):
            m.asegurar()
        self.assertTrue(all(mtp for _, mtp in intentos[:2]))
        self.assertEqual(intentos[-1], (motor_moe.calientes_para(6100, 16384), False))

    def test_blob_del_modelo(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(motor_moe.blob_del_modelo(d))
            manif = os.path.join(d, "manifests", *motor_moe.MODELO_OLLAMA)
            os.makedirs(os.path.dirname(manif))
            with open(manif, "w") as f:
                json.dump({"layers": [{"mediaType": "application/vnd.ollama.image.template", "digest": "sha256:aa"},
                                      {"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:bb"}]}, f)
            self.assertIsNone(motor_moe.blob_del_modelo(d))          # el manifiesto sin el blob
            os.makedirs(os.path.join(d, "blobs"))
            open(os.path.join(d, "blobs", "sha256-bb"), "w").close()
            self.assertEqual(motor_moe.blob_del_modelo(d), os.path.join(d, "blobs", "sha256-bb"))

    def test_no_disponible_sin_servidor(self):
        with mock.patch.object(motor_moe, "SERVIDOR", "/no/existe/llama-server"):
            d = motor_moe.Motor.disponible()
        self.assertFalse(d["disponible"])
        self.assertIn("compilar.sh", d["motivo"])
        with mock.patch.object(motor_moe.Motor, "disponible", staticmethod(lambda: d)):
            self.assertEqual(AIEngine._modelos_propios(), [])

    def test_nucleos_de_rendimiento(self):
        from recursos import frio
        nucleos = motor_moe.nucleos_rendimiento()
        self.assertTrue(nucleos)
        self.assertFalse(set(nucleos) & set(frio.nucleos_eficientes()))
        self.assertEqual(len(nucleos), len(set(nucleos)))

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


class ServidorFalso(BaseHTTPRequestHandler):
    """ Responde como llama-server: /health y /v1/chat/completions (streaming o no) """
    pedidos = []

    def log_message(self, *a):
        pass

    uso = None

    def do_GET(self):
        ServidorFalso.pedidos.append({"_ruta": self.path})
        if self.path.startswith("/aipc/uso"):
            return self._json({"capas": ServidorFalso.uso or [], "calientes_por_capa": 2})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    carpeta = None

    def _json(self, datos, estado=200):
        self.send_response(estado)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(datos).encode())

    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        ServidorFalso.pedidos.append({"_ruta": self.path, **cuerpo})
        if self.path == "/apply-template":
            texto = "".join(f"<{m['role']}>{m['content']}</{m['role']}>" for m in cuerpo["messages"])
            return self._json({"prompt": texto if not cuerpo.get("add_generation_prompt", True) else texto + "<assistant>"})
        if self.path == "/completion":
            return self._json({"tokens_evaluated": len(cuerpo["prompt"]) // 3, "timings": {"prompt_ms": 2000.0}})
        if self.path == "/aipc/calientes":
            return self._json({"capas_cambiadas": len(cuerpo["capas"])})
        if self.path.startswith("/slots/0?action="):
            ruta = os.path.join(ServidorFalso.carpeta, cuerpo["filename"])
            if "save" in self.path:
                open(ruta, "w").write("estado")
                return self._json({"n_saved": 100})
            if not os.path.exists(ruta):
                return self._json({"error": "no existe"}, 400)
            return self._json({"n_restored": 100})
        timings = {"prompt_n": 10, "prompt_ms": 100, "predicted_n": 2, "predicted_ms": 50}
        if not cuerpo.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "listo"}}],
                                         "timings": timings}).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for linea in sse({"reasoning_content": "pienso"}, {"content": "Hola"}, {"content": " Prig"}, timings=timings):
            self.wfile.write((linea + "\n\n").encode())
            self.wfile.flush()


class DePuntaAPunta(unittest.TestCase):
    """ El motor de IA habla con el modelo MoE como con uno de Ollama """

    @classmethod
    def setUpClass(cls):
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), ServidorFalso)
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()

    def setUp(self):
        ServidorFalso.pedidos.clear()
        self.motor = motor_moe.Motor()
        self.motor._puerto = self.servidor.server_address[1]
        self.motor._vigia = threading.Thread()          # sin vigía de inactividad en la prueba
        self.ia = AIEngine()
        self.ia.gobernador = None
        parche = mock.patch.object(motor_moe, "motor", lambda **_: self.motor)
        parche.start()
        self.addCleanup(parche.stop)
        parche2 = mock.patch.object(motor_moe.Motor, "asegurar", lambda s: 0.0)
        parche2.start()
        self.addCleanup(parche2.stop)

    def test_chat_eventos(self):
        eventos = list(self.ia.chat_eventos([{"role": "user", "content": "hola"}], motor_moe.NOMBRE, think=True))
        self.assertEqual([e["v"] for e in eventos if e["t"] == "pensando"], ["pienso"])
        self.assertEqual("".join(e["v"] for e in eventos if e["t"] == "texto"), "Hola Prig")
        stats = [e["v"] for e in eventos if e["t"] == "stats"][0]
        self.assertEqual(stats["tokens_respuesta"], 2)
        self.assertEqual(stats["generacion_tok_s"], 40.0)
        pedido = ServidorFalso.pedidos[-1]
        self.assertEqual(pedido["chat_template_kwargs"], {"enable_thinking": True})
        self.assertEqual(self.motor._activas, 0)       # la petición terminó y se descontó

    def test_generate_response(self):
        partes = list(self.ia.generate_response("hola", model=motor_moe.NOMBRE, think=False))
        self.assertEqual("".join(partes), "Hola Prig")
        self.assertEqual(ServidorFalso.pedidos[0]["messages"][-1], {"role": "user", "content": "hola"})

    def test_sin_streaming_y_descarga(self):
        res = self.motor.post("http://x/api/chat", {"messages": [{"role": "user", "content": "x"}], "stream": False})
        self.assertEqual(res.json()["message"]["content"], "listo")
        with mock.patch.object(self.motor, "detener") as detener:
            res = self.motor.post("http://x/api/generate", {"model": motor_moe.NOMBRE, "keep_alive": 0})
            detener.assert_called_once()
        self.assertTrue(res.json()["done"])

    def test_cerrar_a_mitad_corta_y_descuenta(self):
        res = self.motor.post("http://x/api/chat", {"messages": [{"role": "user", "content": "x"}]})
        lineas = res.iter_lines()
        next(lineas)
        self.assertEqual(self.motor._activas, 1)
        res.close()                                    # «Detener» cierra la conexión
        self.assertEqual(list(lineas), [])
        self.assertEqual(self.motor._activas, 0)

    def test_proyecto_que_no_cabe_crece_el_contexto(self):
        self.motor.ajustes = lambda: {"contexto": "auto"}
        with mock.patch.object(self.motor, "en_marcha", lambda: True):
            self.motor.contexto = 32768
            crecio = []
            self.motor._crecer = lambda obj: crecio.append(obj) or False
            res = self.motor.post("http://x/api/chat", {"messages": [{"role": "user", "content": "x" * 300000}]})
            self.assertEqual(crecio, [131072])                  # 100K tokens + respuesta → 128K
            self.assertEqual(res.status_code, 200)
            res.close()
            res = self.motor.post("http://x/api/chat", {"messages": [{"role": "user", "content": "x" * 900000}]})
            self.assertEqual(res.status_code, 400)
            self.assertIn("262.144", res.json()["error"])

    def test_proyecto_se_lee_una_vez_y_despues_se_restaura(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(motor_moe, "CARPETA_PROYECTOS", d):
            ServidorFalso.carpeta = d
            proyecto = {"role": "user", "content": "### Archivo: a.py\n" + "x = 1\n" * 4000}
            conversacion = [{"role": "system", "content": "tutor"}, proyecto, {"role": "user", "content": "¿qué hace?"}]
            eventos = list(self.ia.chat_eventos(conversacion, motor_moe.NOMBRE, think=False))
            stats = [e["v"] for e in eventos if e["t"] == "stats"][0]
            self.assertEqual(stats["proyecto"]["origen"], "leido")
            self.assertEqual(stats["tokens_prompt"], 10 + stats["proyecto"]["tokens"])   # la lectura previa cuenta
            self.assertEqual(len(os.listdir(d)), 1)
            rutas = [p["_ruta"] for p in ServidorFalso.pedidos]
            self.assertEqual(rutas, ["/apply-template", "/completion", "/slots/0?action=save", "/v1/chat/completions"])
            plantilla = ServidorFalso.pedidos[0]
            self.assertFalse(plantilla["add_generation_prompt"])        # solo el proyecto, sin la respuesta
            self.assertEqual(len(plantilla["messages"]), 2)
            self.assertEqual(ServidorFalso.pedidos[1]["n_predict"], 0)  # estado EXACTO al final del proyecto
            # otra pregunta sobre el mismo proyecto: se restaura de disco, no se relee
            ServidorFalso.pedidos.clear()
            conversacion[-1] = {"role": "user", "content": "¿y los tests?"}
            eventos = list(self.ia.chat_eventos(conversacion, motor_moe.NOMBRE, think=False))
            stats = [e["v"] for e in eventos if e["t"] == "stats"][0]
            self.assertEqual(stats["proyecto"]["origen"], "disco")
            self.assertEqual([p["_ruta"] for p in ServidorFalso.pedidos],
                             ["/apply-template", "/slots/0?action=restore", "/v1/chat/completions"])
            self.assertEqual(self.motor.estado()["proyectos"]["archivos"], 1)
            self.assertEqual(self.motor.olvidar_proyectos(), 1)
            self.assertEqual(os.listdir(d), [])

    def test_el_proyecto_trae_su_lista_caliente(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(motor_moe, "CARPETA_PROYECTOS", d):
            ServidorFalso.carpeta = d
            ServidorFalso.uso = [[0, 5, 1, 9], [3, 0, 0, 1]]
            self.motor.calientes = 2
            conversacion = [{"role": "user", "content": "x = 1\n" * 4000}, {"role": "user", "content": "¿qué hace?"}]
            list(self.ia.chat_eventos(conversacion, motor_moe.NOMBRE, think=False))
            rutas = [p["_ruta"] for p in ServidorFalso.pedidos]
            self.assertEqual(rutas[:6], ["/apply-template", "/aipc/uso?reset=1", "/completion",
                                         "/slots/0?action=save", "/aipc/uso?reset=1", "/aipc/calientes"])
            enviada = [p for p in ServidorFalso.pedidos if p["_ruta"] == "/aipc/calientes"][0]["capas"]
            self.assertEqual([c[:2] for c in enviada], [[3, 1], [0, 3]])        # los más usados al leerlo
            guardadas = [f for f in os.listdir(d) if f.endswith(".calientes.json")]
            self.assertEqual(len(guardadas), 1)
            # misma lista ya en la GPU: al restaurar no se vuelve a enviar
            ServidorFalso.pedidos.clear()
            list(self.ia.chat_eventos(conversacion, motor_moe.NOMBRE, think=False))
            self.assertNotIn("/aipc/calientes", [p["_ruta"] for p in ServidorFalso.pedidos])
            # servidor nuevo (lista global): al restaurar se aplica la del proyecto
            ServidorFalso.pedidos.clear()
            self.motor._lista_actual = None
            list(self.ia.chat_eventos(conversacion, motor_moe.NOMBRE, think=False))
            self.assertIn("/aipc/calientes", [p["_ruta"] for p in ServidorFalso.pedidos])
            ServidorFalso.uso = None

    def test_sin_proyecto_no_se_guarda_nada(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(motor_moe, "CARPETA_PROYECTOS", d):
            list(self.ia.chat_eventos([{"role": "user", "content": "x" * 50000}], motor_moe.NOMBRE, think=False))
            self.assertEqual([p["_ruta"] for p in ServidorFalso.pedidos], ["/v1/chat/completions"])
            self.assertEqual(os.listdir(d), [])

    def test_aparece_en_la_lista_de_modelos(self):
        disp = {"disponible": True, "motivo": None, "servidor": True, "modelo": __file__}
        with mock.patch.object(motor_moe.Motor, "disponible", staticmethod(lambda: disp)), \
                mock.patch.object(motor_moe, "SERVIDOR", __file__):
            propios = AIEngine._modelos_propios()
        self.assertEqual(propios[0]["name"], motor_moe.NOMBRE)
        self.assertEqual(propios[0]["motor"], "moe")


if __name__ == "__main__":
    unittest.main()


class Endpoints(unittest.TestCase):
    """ Temperaturas → Motor MoE: estado, ajustes (se aplican en el próximo arranque) y parar """

    def setUp(self):
        import app
        self.app = app
        cfg = mock.patch.dict(app.ai_engine.config, {"moe_contexto": 16384, "moe_hilos": 0, "moe_calientes": "auto",
                                                     "moe_modo": "equilibrado", "moe_mtp": True, "moe_nucleo": "q8"})
        cfg.start()
        self.addCleanup(cfg.stop)
        guardar = mock.patch.object(app.ai_engine, "_save_config", lambda: None)
        guardar.start()
        self.addCleanup(guardar.stop)

    def test_estado_y_ajustes(self):
        e = self.app.recursos_moe()
        self.assertEqual(e["nombre"], motor_moe.NOMBRE)
        self.assertEqual(e["ajustes"], {"contexto": 16384, "hilos": 0, "calientes": "auto", "modo": "equilibrado", "mtp": True,
                                        "nucleo": "q8"})
        e = self.app.recursos_moe_ajustar(self.app.MoeRequest(contexto="999999", hilos=3, calientes="40"))
        self.assertEqual({k: e["ajustes"][k] for k in ("contexto", "hilos", "calientes")}, {"contexto": 262144, "hilos": 3, "calientes": 40})
        e = self.app.recursos_moe_ajustar(self.app.MoeRequest(contexto="auto"))
        self.assertEqual(e["ajustes"]["contexto"], "auto")
        with self.assertRaises(self.app.HTTPException):
            self.app.recursos_moe_ajustar(self.app.MoeRequest(contexto="mucho"))
        e = self.app.recursos_moe_ajustar(self.app.MoeRequest(calientes="auto"))
        self.assertEqual(e["ajustes"]["calientes"], "auto")
        with self.assertRaises(self.app.HTTPException):
            self.app.recursos_moe_ajustar(self.app.MoeRequest(calientes="muchos"))
        e = self.app.recursos_moe_ajustar(self.app.MoeRequest(modo="exacto", mtp=False))
        self.assertEqual((e["ajustes"]["modo"], e["ajustes"]["mtp"]), ("exacto", False))
        self.assertEqual(e["modos"], ["exacto", "equilibrado", "rapido"])
        with self.assertRaises(self.app.HTTPException):
            self.app.recursos_moe_ajustar(self.app.MoeRequest(modo="turbo"))
        self.assertEqual(self.app.recursos_moe_ajustar(self.app.MoeRequest(nucleo="q4"))["ajustes"]["nucleo"], "q4")
        with self.assertRaises(self.app.HTTPException):
            self.app.recursos_moe_ajustar(self.app.MoeRequest(nucleo="q2"))

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

    def test_detener(self):
        with mock.patch.object(motor_moe.Motor, "detener") as detener:
            self.app.recursos_moe_ajustar(self.app.MoeRequest(detener=True))
        detener.assert_called_once()
