"""
Configuración de modelos, chat por eventos, herramientas y gestión de modelos.

Sin Ollama real: las respuestas del servidor se simulan con lo que devolvió el Ollama
0.34.1 de verdad al verificar cada opción. Lo que se protege:

  · nunca se envía una opción excluida (typical_p rompe la petición con un 400);
  · lo que ninguna capa fija NO se envía: manda el Modelfile del modelo;
  · prioridad de capas y lo que exige la llamada por encima;
  · `think` solo a modelos con la capacidad (a los demás Ollama responde 400);
  · el chat continúa una respuesta cortada y ejecuta herramientas en bucle;
  · ejecutar Python solo si el usuario lo permite; leer archivos no sale del workspace;
  · importar solo GGUF de verdad; borrar descargas a medias no toca modelos completos.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ollama_opciones as oo
from ollama_opciones import ConfigModelos, ErrorConfig


class _Temporal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_modelos_")
        self.env = mock.patch.dict(os.environ, {"PRIG_MODELOS_ARCHIVO": os.path.join(self.tmp, "modelos.json")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ===========================================================================
class PruebaCatalogo(unittest.TestCase):

    def test_ninguna_opcion_del_catalogo_esta_excluida(self):
        claves = {o["clave"] for o in oo.OPCIONES} | {c["clave"] for c in oo.CAMPOS}
        self.assertEqual(claves & set(oo.EXCLUIDAS), set())

    def test_las_que_fallaron_estan_excluidas_con_motivo(self):
        for clave in ("typical_p", "mirostat", "mirostat_tau", "mirostat_eta", "tfs_z", "penalize_newline",
                      "use_mlock", "numa", "low_vram", "f16_kv", "vocab_only", "logits_all", "embedding_only"):
            self.assertIn(clave, oo.EXCLUIDAS)
            self.assertTrue(oo.EXCLUIDAS[clave]["motivo"])
        self.assertEqual(oo.EXCLUIDAS["typical_p"]["tipo"], "error")

    def test_cada_opcion_dice_como_se_verifico(self):
        for o in oo.OPCIONES + oo.CAMPOS:
            self.assertTrue(o.get("prueba"), o["clave"])
            self.assertTrue(o.get("ayuda"), o["clave"])

    def test_main_gpu_solo_con_varias_gpus(self):
        self.assertNotIn("main_gpu", {o["clave"] for o in oo.catalogo(1)["opciones"]})
        self.assertIn("main_gpu", {o["clave"] for o in oo.catalogo(2)["opciones"]})

    def test_validacion(self):
        self.assertEqual(oo.validar({"temperature": "0.5", "top_k": 20, "stop": "FIN", "use_mmap": False, "keep_alive": "30m"}),
                         {"temperature": 0.5, "top_k": 20, "stop": ["FIN"], "use_mmap": False, "keep_alive": "30m"})
        for malo in ({"typical_p": 0.9}, {"temperature": 5}, {"top_k": 2.5}, {"use_mmap": "sí"},
                     {"keep_alive": "mañana"}, {"inventada": 1}, {"stop": list("abcdefghij")}):
            with self.assertRaises(ErrorConfig, msg=malo):
                oo.validar(malo)

    def test_limpiar_quita_lo_excluido(self):
        self.assertEqual(oo.limpiar_para_ollama({"temperature": 0.2, "typical_p": 0.9, "low_vram": True}), {"temperature": 0.2})


class PruebaCapas(_Temporal):

    def test_prioridad_y_origen(self):
        c = ConfigModelos()
        c.fijar("global", {"temperature": 0.9, "num_predict": 100})
        c.fijar("modelo", {"temperature": 0.6}, modelo="qwen3:14b")
        c.fijar("uso", {"temperature": 0.3, "think": False}, uso="flujos")
        c.fijar("modelo_uso", {"temperature": 0.1}, modelo="qwen3:14b", uso="flujos")
        r = c.resolver("qwen3:14b", "flujos")
        self.assertEqual(r["opciones"], {"temperature": 0.1, "num_predict": 100})
        self.assertEqual(r["campos"], {"think": False})
        self.assertEqual(r["origen"]["temperature"], "modelo_uso")
        self.assertEqual(c.resolver("qwen3:14b", "tutor")["opciones"]["temperature"], 0.6)
        self.assertEqual(c.resolver("otro", "flujos")["opciones"]["temperature"], 0.3)
        self.assertEqual(c.resolver("otro", None)["origen"]["temperature"], "global")

    def test_none_quita_y_capa_vacia_desaparece(self):
        c = ConfigModelos()
        c.fijar("modelo", {"temperature": 0.6}, modelo="m")
        c.fijar("modelo", {"temperature": None}, modelo="m")
        self.assertNotIn("m", c.todo()["modelo"])

    def test_persistencia_y_limpieza_de_configuraciones_viejas(self):
        with open(os.environ["PRIG_MODELOS_ARCHIVO"], "w") as f:
            json.dump({"version": 1, "global": {"temperature": 0.4, "typical_p": 0.9},
                       "modelo": {"m": {"low_vram": True, "top_k": 10}}, "uso": {}, "modelo_uso": {}}, f)
        c = ConfigModelos()
        self.assertEqual(c.capa("global"), {"temperature": 0.4})
        self.assertEqual(c.capa("modelo", "m"), {"top_k": 10})

    def test_capa_o_uso_desconocidos(self):
        c = ConfigModelos()
        with self.assertRaises(ErrorConfig):
            c.fijar("inventada", {"top_k": 1})
        with self.assertRaises(ErrorConfig):
            c.fijar("uso", {"top_k": 1}, uso="jugar")

    def test_copiar_configuracion_al_copiar_modelo(self):
        c = ConfigModelos()
        c.fijar("modelo", {"top_k": 5}, modelo="a")
        c.fijar("modelo_uso", {"top_k": 6}, modelo="a", uso="tutor")
        c.renombrar_modelo("a", "b")
        self.assertEqual(c.resolver("b", "tutor")["opciones"]["top_k"], 6)

    def test_embeddings(self):
        c = ConfigModelos()
        self.assertEqual(c.fijar_embeddings(modelo="bge-m3", dimensiones=128)["dimensiones"], 128)
        self.assertIsNone(c.fijar_embeddings(quitar_dimensiones=True)["dimensiones"])
        with self.assertRaises(ErrorConfig):
            c.fijar_embeddings(dimensiones=4)


# ===========================================================================
def _motor(config=None):
    from ai_engine import AIEngine
    motor = AIEngine.__new__(AIEngine)
    motor.base_url = "http://x"
    motor.config = {"num_ctx": 4096, "num_gpu": -1, "num_thread": 0, "num_predict": 0, "keep_alive": "5m",
                    "temperature": 0.3, "top_k": 40, "top_p": 0.9, "repeat_penalty": 1.1,
                    "low_vram": False, "f16_kv": True, "muestreo_del_modelo": True, **(config or {})}
    motor._active_streams, motor._streams_lock = set(), threading.Lock()
    motor._caps_cache = {}
    return motor


class Res:
    def __init__(self, lineas, codigo=200):
        self.status_code = codigo
        self._lineas = [json.dumps(l).encode() for l in lineas]

    def iter_lines(self):
        return iter(self._lineas)

    def json(self):
        return {"error": "fallo"}

    def close(self):
        pass


class PruebaMotor(_Temporal):

    def test_por_defecto_no_pisa_el_muestreo_del_modelo(self):
        o = _motor()._build_options(None, "qwen3:14b", "tutor")
        for clave in ("temperature", "top_k", "top_p", "repeat_penalty", "low_vram", "f16_kv", "num_gpu"):
            self.assertNotIn(clave, o)
        self.assertEqual(o["num_ctx"], 4096)

    def test_muestreo_global_si_se_pide(self):
        o = _motor({"muestreo_del_modelo": False})._build_options(None)
        self.assertEqual((o["temperature"], o["top_k"]), (0.3, 40))

    def test_capas_y_llamada(self):
        ConfigModelos().fijar("modelo", {"temperature": 0.6, "num_ctx": 8192}, modelo="m")
        o = _motor()._build_options({"temperature": 0.0, "typical_p": 0.9}, "m")
        self.assertEqual(o["temperature"], 0.0)          # lo exige la llamada
        self.assertEqual(o["num_ctx"], 8192)             # la capa pisa la configuración global
        self.assertNotIn("typical_p", o)                 # jamás llega a Ollama

    def test_think_solo_a_modelos_que_piensan(self):
        motor = _motor()
        ConfigModelos().fijar("uso", {"think": True, "system_extra": "Sé breve.", "keep_alive": "30m", "shift": False}, uso="tutor")
        for caps, espera in ((["completion", "thinking"], True), (["completion"], None)):
            motor._caps_cache = {"m": (1e18, caps)}
            p = {}
            extra = motor._completar_payload(p, "m", "tutor", None, "Eres un tutor.")
            self.assertEqual(p.get("think"), espera)
            self.assertEqual(extra["sistema"], "Eres un tutor.\n\nSé breve.")
            self.assertEqual((p["keep_alive"], p["shift"]), ("30m", False))

    def test_metricas(self):
        m = _motor().metricas({"total_duration": 2e9, "load_duration": 1e9, "prompt_eval_count": 100, "prompt_eval_duration": 5e8,
                               "eval_count": 50, "eval_duration": 1e9, "done_reason": "length"}, 1000)
        self.assertEqual((m["generacion_tok_s"], m["lectura_tok_s"], m["cortada"], m["contexto_usado_pct"]), (50.0, 200.0, True, 15.0))

    def test_generate_response_informa_de_las_metricas(self):
        motor = _motor()
        vistas = []
        final = {"response": "", "done": True, "done_reason": "stop", "eval_count": 2, "eval_duration": 1e8,
                 "prompt_eval_count": 3, "prompt_eval_duration": 1e7, "total_duration": 2e8, "load_duration": 0}
        with mock.patch("ai_engine.ai_engine_class.requests.post", return_value=Res([{"response": "hola", "done": False}, final])):
            texto = "".join(motor.generate_response("x", "m", on_stats=vistas.append))
        self.assertEqual(texto, "hola")
        self.assertEqual(vistas[0]["motivo_fin"], "stop")

    def test_chat_eventos_razonamiento_texto_confianza_y_stats(self):
        motor = _motor()
        motor._caps_cache = {"m": (1e18, ["completion", "thinking"])}
        enviados = []
        lineas = [{"message": {"thinking": "pienso"}}, {"message": {"content": "Hola"}, "logprobs": [{"token": "Hola", "logprob": -0.1, "top_logprobs": [{"token": "Hola", "logprob": -0.1}]}]},
                  {"message": {"content": ""}, "done": True, "done_reason": "length", "eval_count": 1, "eval_duration": 1e8,
                   "prompt_eval_count": 1, "prompt_eval_duration": 1e7, "total_duration": 1e8, "load_duration": 0}]

        def post(url, json=None, **kw):
            enviados.append(json)
            return Res(lineas)
        with mock.patch("ai_engine.ai_engine_class.requests.post", side_effect=post):
            eventos = list(motor.chat_eventos([{"role": "user", "content": "hola"}, {"role": "assistant", "content": "Ho"}],
                                              "m", "tutor", think=True, logprobs=2))
        tipos = [e["t"] for e in eventos]
        self.assertEqual(tipos, ["pensando", "texto", "logprobs", "stats"])
        self.assertTrue(eventos[-1]["v"]["cortada"])
        self.assertEqual(enviados[0]["messages"][-1], {"role": "assistant", "content": "Ho"})   # continuar
        self.assertEqual((enviados[0]["think"], enviados[0]["top_logprobs"]), (True, 2))

    def test_chat_eventos_bucle_de_herramientas(self):
        motor = _motor()
        motor._caps_cache = {"m": (1e18, ["completion", "tools"])}
        rondas = [
            [{"message": {"content": "", "tool_calls": [{"function": {"name": "sumar", "arguments": {"a": 2, "b": 3}}}]}},
             {"message": {}, "done": True, "done_reason": "stop"}],
            [{"message": {"content": "Da 5."}}, {"message": {}, "done": True, "done_reason": "stop"}],
        ]
        enviados = []

        def post(url, json=None, **kw):
            enviados.append(json)
            return Res(rondas.pop(0))

        class Herr:
            def definiciones(self):
                return [{"type": "function", "function": {"name": "sumar"}}]

            def ejecutar(self, nombre, argumentos):
                return str(argumentos["a"] + argumentos["b"])
        with mock.patch("ai_engine.ai_engine_class.requests.post", side_effect=post):
            eventos = list(motor.chat_eventos([{"role": "user", "content": "2+3"}], "m", herramientas=Herr()))
        self.assertEqual([e["t"] for e in eventos], ["herramienta", "resultado", "texto", "stats"])
        segunda = enviados[1]["messages"]
        self.assertEqual(segunda[-1], {"role": "tool", "tool_name": "sumar", "content": "5"})
        self.assertIn("tool_calls", segunda[-2])

    def test_herramientas_a_modelo_sin_capacidad(self):
        motor = _motor()
        motor._caps_cache = {"m": (1e18, ["completion"])}
        with mock.patch("ai_engine.ai_engine_class.requests.post", return_value=Res([{"message": {"content": "ok"}, "done": True}])) as p:
            eventos = list(motor.chat_eventos([{"role": "user", "content": "x"}], "m", herramientas=mock.Mock(definiciones=lambda: [{}])))
        self.assertEqual(eventos[0]["t"], "aviso")
        self.assertNotIn("tools", p.call_args.kwargs["json"])


# ===========================================================================
class PruebaHerramientas(unittest.TestCase):

    def setUp(self):
        from file_manager import FileManager
        from ide_servicios import ServiciosIDE
        self.ws = tempfile.mkdtemp(prefix="prig_herr_ws_")
        self.fuera = tempfile.mkdtemp(prefix="prig_herr_fuera_")
        open(os.path.join(self.ws, "a.py"), "w").write("uno\ndos\ntres\n")
        open(os.path.join(self.fuera, "secreto.txt"), "w").write("no")
        self.fm = FileManager(self.ws)
        self.ide = ServiciosIDE(self.fm)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)
        shutil.rmtree(self.fuera, ignore_errors=True)

    def test_python_solo_si_se_permite(self):
        from herramientas_chat import Herramientas
        runner = mock.Mock()
        h = Herramientas(None, self.fm, self.ide, runner)
        self.assertNotIn("ejecutar_python", [d["function"]["name"] for d in h.definiciones()])
        self.assertIn("no disponible", h.ejecutar("ejecutar_python", {"codigo": "print(1)"}))
        runner.run_cell_code.assert_not_called()
        runner.run_cell_code.return_value = {"success": True, "stdout": "1\n"}
        h2 = Herramientas(None, self.fm, self.ide, runner, permitir_codigo=True)
        self.assertEqual(h2.ejecutar("ejecutar_python", {"codigo": "print(1)"}), "1\n")

    def test_leer_y_buscar_dentro_y_no_fuera(self):
        from herramientas_chat import Herramientas
        h = Herramientas(None, self.fm, self.ide, None)
        self.assertIn("2  dos", h.ejecutar("leer_archivo", {"ruta": "a.py", "desde_linea": 2, "hasta_linea": 2}))
        self.assertIn("a.py:3: tres", h.ejecutar("buscar_en_archivos", {"texto": "tres"}))
        self.assertIn("a.py", h.ejecutar("listar_archivos", {}))
        fuera = h.ejecutar("leer_archivo", {"ruta": os.path.join(self.fuera, "secreto.txt")})
        self.assertNotIn("no\n", fuera)
        self.assertRegex(fuera.lower(), "denegado|fuera")
        self.assertIn("Argumentos no válidos", h.ejecutar("leer_archivo", {"archivo": "a.py"}))
        self.assertIn("no disponible", h.ejecutar("borrar_todo", {}))


# ===========================================================================
class PruebaGestion(unittest.TestCase):

    def setUp(self):
        from ollama_gestion import GestorModelos
        self.g = GestorModelos("http://x")
        self.tmp = tempfile.mkdtemp(prefix="prig_gestion_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parametros_del_modelfile(self):
        from ollama_gestion import _parametros
        self.assertEqual(_parametros('temperature 0.6\nstop "<|im_start|>"\nstop "<|im_end|>"'),
                         {"temperature": "0.6", "stop": ["<|im_start|>", "<|im_end|>"]})

    def test_nombres(self):
        from ollama_gestion import _nombre, ErrorGestion
        self.assertEqual(_nombre(" qwen3-tutor:v1 "), "qwen3-tutor:v1")
        for malo in ("", "con espacios", "../etc", ":solo-tag"):
            with self.assertRaises(ErrorGestion):
                _nombre(malo)

    def test_importar_solo_gguf_de_verdad(self):
        from ollama_gestion import ErrorGestion
        falso = os.path.join(self.tmp, "falso.gguf")
        open(falso, "wb").write(b"PK\x03\x04 no es gguf")
        with self.assertRaises(ErrorGestion):
            list(self.g.importar_gguf(falso, "x"))

    def test_importar_calcula_huella_sube_y_crea(self):
        ruta = os.path.join(self.tmp, "m.gguf")
        datos = b"GGUF" + b"\x00" * 1000
        open(ruta, "wb").write(datos)
        digest = "sha256:" + hashlib.sha256(datos).hexdigest()
        creado = {}

        class R:
            status_code = 201
            def json(self): return {}
        def head(url, **kw):
            return mock.Mock(status_code=404)
        def post(url, data=None, json=None, stream=False, **kw):
            if "/api/blobs/" in url:
                b"".join(data)
                creado["subido"] = url.endswith(digest)
                return R()
            creado["cuerpo"] = json
            r = mock.MagicMock(status_code=200)
            r.__enter__.return_value = r
            r.iter_lines.return_value = [b'{"status":"success"}']
            return r
        with mock.patch("ollama_gestion.requests.head", side_effect=head), \
                mock.patch("ollama_gestion.requests.post", side_effect=post):
            eventos = list(self.g.importar_gguf(ruta, "mi-modelo"))
        self.assertTrue(creado["subido"])
        self.assertEqual(creado["cuerpo"]["files"], {"m.gguf": digest})
        self.assertEqual(eventos[-1], {"fase": "listo", "modelo": "mi-modelo"})

    def test_descargas_a_medias_no_toca_modelos_completos(self):
        blobs = os.path.join(self.tmp, "blobs")
        os.makedirs(blobs)
        open(os.path.join(blobs, "sha256-aaa-partial"), "wb").write(b"x" * 10)
        open(os.path.join(blobs, "sha256-aaa-partial-0"), "wb").write(b"x" * 5)
        open(os.path.join(blobs, "sha256-bbb"), "wb").write(b"modelo")
        r = self.g.borrar_parciales(self.tmp)
        self.assertEqual((r["borrados"], r["bytes"]), (2, 15))
        self.assertEqual(os.listdir(blobs), ["sha256-bbb"])

    def test_actualizaciones(self):
        manifiesto = b'{"layers": []}'
        local = hashlib.sha256(manifiesto).hexdigest()
        tags = {"models": [{"name": "a:1", "digest": local}, {"name": "b:1", "digest": "otro"}, {"name": "mio:latest", "digest": "x"}]}

        def get(url, **kw):
            if url.endswith("/api/tags"):
                return mock.Mock(status_code=200, json=lambda: tags)
            if "/mio/" in url:
                return mock.Mock(status_code=404)
            return mock.Mock(status_code=200, content=manifiesto)
        with mock.patch("ollama_gestion.requests.get", side_effect=get):
            estados = {x["modelo"]: x["estado"] for x in self.g.actualizaciones()}
        self.assertEqual(estados, {"a:1": "al_dia", "b:1": "actualizable", "mio:latest": "local"})


class PruebaServidorNuevasVariables(unittest.TestCase):

    def test_validaciones(self):
        from recursos import servidor as S
        ok = S.validar({"OLLAMA_CONTEXT_LENGTH": "8192", "LLAMA_ARG_FIT_TARGET": "1024", "OLLAMA_LOAD_TIMEOUT": "90s",
                        "OLLAMA_DEBUG": "1", "OLLAMA_NO_CLOUD": "1", "OLLAMA_HOST": "0.0.0.0:11434",
                        "OLLAMA_ORIGINS": "https://a.com, http://localhost:3000", "OLLAMA_MODELS": tempfile.gettempdir()})
        self.assertEqual(ok["OLLAMA_ORIGINS"], "https://a.com,http://localhost:3000")
        for malo in ({"OLLAMA_LOAD_TIMEOUT": "1ms"}, {"OLLAMA_LOAD_TIMEOUT": "5s"}, {"OLLAMA_HOST": "0.0.0.0:9999"},
                     {"OLLAMA_CONTEXT_LENGTH": "10"}, {"OLLAMA_ORIGINS": "javascript:alert(1)"},
                     {"OLLAMA_MODELS": "/no/existe/nunca"}, {"OLLAMA_LLM_LIBRARY": "rocm"},
                     {"OLLAMA_GPU_OVERHEAD": "1"}, {"OLLAMA_MAX_QUEUE": "1"}, {"LLAMA_ARG_FIT": "off"}):
            with self.assertRaises(ValueError, msg=malo):
                S.validar(malo)

    def test_las_llama_arg_se_guardan(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"PRIG_RECURSOS_ARCHIVO": os.path.join(tmp, "r.json")}):
            from recursos.almacen import almacen
            from recursos import servidor as S
            almacen().guardar_entorno_servidor({"LLAMA_ARG_FIT_TARGET": "1024", "PATH": "x"})
            self.assertEqual(S.entorno_arranque({})["LLAMA_ARG_FIT_TARGET"], "1024")

    def test_leer_registro(self):
        from recursos import servidor as S
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(S, "ruta_registro", return_value=os.path.join(tmp, "o.log")):
            self.assertIn("aviso", S.leer_registro(50))
            with open(os.path.join(tmp, "o.log"), "w") as f:
                f.write("\n".join(f"linea {i}" for i in range(100)))
            texto = S.leer_registro(20)["texto"].splitlines()
            self.assertEqual((len(texto), texto[-1]), (20, "linea 99"))


class PruebaIndiceDimensiones(_Temporal):

    def test_dimensiones_distintas_no_comparan_basura(self):
        from knowledge_base import KnowledgeBase
        from indice_semantico import IndiceSemantico, _empaquetar
        kb = KnowledgeBase(os.path.join(self.tmp, "k.db"))
        idx = IndiceSemantico(kb)
        with kb.conectar() as c:
            c.execute("INSERT INTO vectores VALUES (?,?,?,?,?);", ("c1", _empaquetar([1.0, 0.0, 0.0]), 3, "bge-m3", "hoy"))
            c.commit()
        idx.embeber = lambda textos, timeout=None: [[1.0, 0.0]]
        self.assertEqual(idx.puntuar("x"), [])
        idx.embeber = lambda textos, timeout=None: [[1.0, 0.0, 0.0]]
        self.assertEqual(idx.puntuar("x")[0][1], "c1")
        ConfigModelos().fijar_embeddings(modelo="nomic-embed-text")
        idx.disponible = lambda: True
        self.assertTrue(idx.estado()["necesita_reindexar"])


if __name__ == "__main__":
    unittest.main()
