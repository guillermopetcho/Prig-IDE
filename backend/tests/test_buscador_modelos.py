"""
Buscador de modelos (Ollama, Hugging Face, ModelScope), seguimiento y cola de descargas.

Sin red: las páginas y respuestas de `datos_buscador/` son copias recortadas de lo
que devolvieron ollama.com, la API de Hugging Face y la de ModelScope al verificar
el buscador. Lo que se protege:

  · leer la búsqueda y las etiquetas de ollama.com (no tiene API) sin perder campos;
  · agrupar los GGUF de un repositorio en variantes con la etiqueta que Ollama
    entiende, sin contar el proyector de visión y juntando los archivos partidos;
  · saber ANTES de descargar si el registro sirve la variante (404, 400 partido,
    401 licencia) y guardar el digest del manifiesto para detectar actualizaciones;
  · que una plataforma caída no deje sin resultados a las demás;
  · seguidos: variantes nuevas, retiradas y cambiadas;
  · la cola: progreso, sin espacio, errores de Ollama traducidos, cancelar y reintentar.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import buscador_modelos as bm
import descargas_modelos as dm
from buscador_modelos import ErrorBuscador

DATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos_buscador")


def leer(nombre):
    with open(os.path.join(DATOS, nombre), encoding="utf-8") as f:
        return f.read()


class Respuesta:
    def __init__(self, codigo=200, cuerpo=b"", cabeceras=None, lineas=None):
        self.status_code = codigo
        self.content = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
        self.text = self.content.decode()
        self.headers = cabeceras or {}
        self._lineas = lineas or []

    def json(self):
        return json.loads(self.content)

    def iter_lines(self):
        for l in self._lineas:
            yield l if isinstance(l, bytes) else json.dumps(l).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _SinCache(unittest.TestCase):
    def setUp(self):
        self.cache = mock.patch.object(bm, "_cache", bm.Cache())
        self.cache.start()

    def tearDown(self):
        self.cache.stop()


# ===========================================================================
class PruebaUtilidades(unittest.TestCase):

    def test_cuantizacion_de_los_nombres_reales(self):
        casos = {
            "Qwen3-8B-Q4_K_M.gguf": "Q4_K_M",
            "Qwen3-8B-UD-Q4_K_XL.gguf": "UD-Q4_K_XL",
            "Qwen3-8B-UD-IQ1_S.gguf": "UD-IQ1_S",
            "qwen2.5-0.5b-instruct-q4_k_m.gguf": "q4_k_m",
            "Qwen3-8B-BF16.gguf": "BF16",
            "gpt-oss-20b-MXFP4.gguf": "MXFP4",
            "Q4_K_M/Qwen3-235B-A22B-Q4_K_M-00001-of-00003.gguf": "Q4_K_M",
            "Llama-3.2-1B-Instruct-IQ4_XS.gguf": "IQ4_XS",
        }
        for archivo, esperado in casos.items():
            self.assertEqual(bm.cuantizacion_de(archivo), esperado, archivo)
        self.assertIsNone(bm.cuantizacion_de("README.gguf"))

    def test_validar_ref(self):
        for bueno in ("qwen3", "qwen3:8b", "huihui_ai/dolphin3-r1-abliterated:8b",
                      "hf.co/unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL", "modelscope.cn/Qwen/Qwen2.5-0.5B-Instruct-GGUF:q4_k_m"):
            self.assertEqual(bm.validar_ref(bueno), bueno)
        for malo in ("", "Qwen3 8b", "hf.co/../etc:x", "a/b/c/d", "http://x.com/m", "qwen3;rm -rf"):
            with self.assertRaises(ErrorBuscador, msg=malo):
                bm.validar_ref(malo)

    def test_numeros_y_tamanos_de_ollama_com(self):
        self.assertEqual(bm._numero("105.3K"), 105300)
        self.assertEqual(bm._numero("2.1M"), 2100000)
        self.assertEqual(bm._numero("666"), 666)
        self.assertEqual(bm._bytes("5.2GB"), 5_200_000_000)
        self.assertEqual(bm._bytes("523MB"), 523_000_000)
        self.assertIsNone(bm._bytes("mucho"))

    def test_fuente_de_ref(self):
        self.assertEqual(bm.fuente_de_ref("hf.co/a/b:Q4_K_M"), "huggingface")
        self.assertEqual(bm.fuente_de_ref("modelscope.cn/a/b:q4_k_m"), "modelscope")
        self.assertEqual(bm.fuente_de_ref("qwen3:8b"), "ollama")

    def test_registro_de_cada_plataforma(self):
        self.assertEqual(bm.registro_de("hf.co/unsloth/Qwen3-8B-GGUF:Q4_K_M"), ("https://hf.co", "unsloth/Qwen3-8B-GGUF", "Q4_K_M"))
        self.assertEqual(bm.registro_de("modelscope.cn/Qwen/X-GGUF:q4_k_m"), ("https://modelscope.cn", "Qwen/X-GGUF", "q4_k_m"))
        registro, repo, tag = bm.registro_de("qwen3")
        self.assertEqual((repo, tag), ("library/qwen3", "latest"))


# ===========================================================================
class PruebaAgruparGguf(unittest.TestCase):

    def test_repositorio_real_de_hugging_face(self):
        repo = json.loads(leer("hf_repo.json"))
        variantes = bm.agrupar_gguf([(s["rfilename"], s["size"]) for s in repo["siblings"]], "hf.co/unsloth/Qwen3-8B-GGUF")
        etiquetas = [v["etiqueta"] for v in variantes]
        self.assertIn("Q4_K_M", etiquetas)
        self.assertIn("UD-Q4_K_XL", etiquetas)
        self.assertEqual(len(etiquetas), len(set(etiquetas)))
        self.assertEqual([v["bytes"] for v in variantes], sorted(v["bytes"] for v in variantes))
        q4 = next(v for v in variantes if v["etiqueta"] == "Q4_K_M")
        self.assertEqual(q4["ref"], "hf.co/unsloth/Qwen3-8B-GGUF:Q4_K_M")
        self.assertEqual(q4["bytes"], 5027784512)
        self.assertIsNone(q4["nota"])

    def test_partidos_se_juntan_y_mmproj_no_es_variante(self):
        archivos = [
            ("Q4_K_M/M-Q4_K_M-00001-of-00002.gguf", 40), ("Q4_K_M/M-Q4_K_M-00002-of-00002.gguf", 30),
            ("M-Q8_0.gguf", 100), ("mmproj-M-F16.gguf", 5), ("README.md", 1), ("M-F16.gguf", 200),
        ]
        variantes = bm.agrupar_gguf(archivos, "hf.co/a/M-GGUF")
        self.assertEqual([v["etiqueta"] for v in variantes], ["Q4_K_M", "Q8_0", "F16"])
        partido = variantes[0]
        self.assertEqual((partido["bytes"], partido["partes"]), (70, 2))
        self.assertIn("Partido", partido["nota"])

    def test_modelscope_etiquetas_en_minusculas(self):
        repo = json.loads(leer("modelscope_repo.json"))
        variantes = bm.agrupar_gguf([(f["Path"], f["Size"]) for f in repo["Data"]["Files"] if f["Type"] != "tree"],
                                    "modelscope.cn/Qwen/Qwen2.5-0.5B-Instruct-GGUF")
        self.assertIn("modelscope.cn/Qwen/Qwen2.5-0.5B-Instruct-GGUF:q4_k_m", [v["ref"] for v in variantes])
        self.assertEqual(len(variantes), 8)


# ===========================================================================
class PruebaOllamaCom(_SinCache):

    def test_busqueda(self):
        modelos = bm.Ollama.analizar_busqueda(leer("ollama_busqueda.html"))
        self.assertEqual(len(modelos), 4)
        q = next(m for m in modelos if m["id"] == "qwen3.6")
        self.assertTrue(q["oficial"])
        self.assertEqual(q["tamanos"], ["27b", "35b"])
        self.assertEqual(set(q["capacidades"]), {"vision", "tools", "thinking"})
        self.assertEqual(q["descargas"], 6_600_000)
        self.assertEqual(q["variantes_total"], 35)
        self.assertEqual(q["actualizado"], "2 weeks ago")
        self.assertTrue(q["descripcion"])
        self.assertEqual(q["url"], "https://ollama.com/library/qwen3.6")
        comunidad = next(m for m in modelos if "/" in m["id"])
        self.assertFalse(comunidad["oficial"])
        self.assertEqual(comunidad["autor"], comunidad["id"].split("/")[0])
        self.assertEqual(comunidad["url"], f"https://ollama.com/{comunidad['id']}")

    def test_etiquetas(self):
        variantes = bm.Ollama.analizar_etiquetas(leer("ollama_etiquetas.html"), "library/qwen3")
        por_tag = {v["etiqueta"]: v for v in variantes}
        self.assertEqual(set(por_tag), {"latest", "0.6b", "8b", "8b-q8_0"})
        v = por_tag["8b"]
        self.assertEqual(v["ref"], "qwen3:8b")
        self.assertEqual(v["bytes"], 5_200_000_000)
        self.assertEqual(v["contexto"], "40K")
        self.assertEqual(v["entrada"], ["Text"])
        self.assertEqual(v["digest"], por_tag["latest"]["digest"])     # latest es el 8b
        self.assertIsNone(v["descargable"])                              # se comprueba después

    def test_etiquetas_mlx_y_nube_no_son_descargables(self):
        pagina = leer("ollama_etiquetas.html")
        pagina = pagina.replace("qwen3:0.6b", "qwen3:8b-mlx").replace("qwen3:8b-q8_0", "qwen3:235b-cloud")
        por_tag = {v["etiqueta"]: v for v in bm.Ollama.analizar_etiquetas(pagina, "library/qwen3")}
        self.assertIs(por_tag["8b-mlx"]["descargable"], False)
        self.assertIn("Apple", por_tag["8b-mlx"]["nota"])
        self.assertIs(por_tag["235b-cloud"]["descargable"], False)

    def test_modelo_de_la_comunidad_usa_su_ruta(self):
        pagina = '<a href="/huihui_ai/dolphin3-r1:8b" class="md:hidden flex">x • 4.9GB • 128K context window • Text input • 3 months ago</a>'
        v = bm.Ollama.analizar_etiquetas(pagina, "huihui_ai/dolphin3-r1")[0]
        self.assertEqual(v["ref"], "huihui_ai/dolphin3-r1:8b")
        self.assertEqual(v["contexto"], "128K")

    def test_parametros_de_busqueda_y_paginas(self):
        pagina = leer("ollama_busqueda.html")
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, pagina.encode())) as get:
            r = bm.Ollama().buscar("qwen", "recientes", "tools", 1)
        self.assertEqual(get.call_args.kwargs["params"], {"q": "qwen", "o": "newest", "c": "tools"})
        self.assertNotIn("HX-Request", get.call_args.kwargs["headers"])
        self.assertIsNone(r["siguiente"])              # sin el enlace de htmx no hay más
        # ollama.com solo pagina si la petición viene de htmx (con «p» o sin la cabecera repite la primera)
        con_mas = pagina + '<li hx-get="/search?page=3&q=qwen" hx-trigger="revealed"></li>'
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, con_mas.encode())) as get:
            r = bm.Ollama().buscar("qwen", "recientes", "tools", 2)
        self.assertEqual(get.call_args.kwargs["params"], {"q": "qwen", "o": "newest", "c": "tools", "page": 2})
        self.assertEqual(get.call_args.kwargs["headers"]["HX-Request"], "true")
        self.assertEqual(r["siguiente"], 3)
        self.assertEqual(len(r["modelos"]), 4)         # el <li> de htmx no es un modelo
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, pagina.encode())) as get:
            bm.Ollama().buscar("", "relevancia", "inventada")
        self.assertEqual(get.call_args.kwargs["params"], {})


# ===========================================================================
class PruebaHuggingFace(_SinCache):

    def test_normalizar(self):
        modelos = [bm.HuggingFace.normalizar(m) for m in json.loads(leer("hf_busqueda.json"))]
        coder = modelos[0]
        self.assertEqual(coder["id"], "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF")
        self.assertEqual(coder["modelo_base"], "Qwen/Qwen3-Coder-30B-A3B-Instruct")
        self.assertEqual(coder["arquitectura"], "qwen3moe")
        self.assertEqual(coder["contexto"], 262144)
        self.assertEqual(coder["licencia"], "apache-2.0")
        self.assertIn("chat", coder["capacidades"])
        self.assertFalse(coder["requiere_licencia"])
        # Metadatos del proyector de visión: no es la arquitectura del modelo
        proyector = modelos[2]
        self.assertIsNone(proyector["arquitectura"])
        self.assertIn("vision", proyector["capacidades"])
        self.assertNotIn("clip", proyector["descripcion"])

    def test_repositorio_con_licencia(self):
        m = bm.HuggingFace.normalizar({"id": "google/gemma-3-4b-it-qat-q4_0-gguf", "gated": "manual", "tags": []})
        self.assertTrue(m["requiere_licencia"])

    def test_paginacion_por_cabecera_link(self):
        siguiente = "https://huggingface.co/api/models?filter=gguf&cursor=abc"
        resp = Respuesta(200, json.loads(leer("hf_busqueda.json")), {"Link": f'<{siguiente}>; rel="next"'})
        with mock.patch.object(bm.requests, "get", return_value=resp) as get:
            r = bm.HuggingFace().buscar("qwen3", "tendencia")
        self.assertEqual(get.call_args.kwargs["params"]["sort"], "trendingScore")
        self.assertEqual(get.call_args.kwargs["params"]["filter"], "gguf")
        self.assertEqual(len(r["modelos"]), 3)
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, [])) as get:
            bm.HuggingFace().buscar("qwen3", pagina=r["siguiente"])
        self.assertEqual(get.call_args.args[0], siguiente)

    def test_pagina_que_apunta_a_otro_sitio_se_rechaza(self):
        import base64
        malo = base64.urlsafe_b64encode(b"https://atacante.example/api/models?x").decode()
        with mock.patch.object(bm.requests, "get") as get:
            with self.assertRaises(ErrorBuscador):
                bm.HuggingFace().buscar("", pagina=malo)
            with self.assertRaises(ErrorBuscador):
                bm.HuggingFace().buscar("", pagina="%%%no-base64")
        get.assert_not_called()

    def test_variantes(self):
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, json.loads(leer("hf_repo.json")))):
            d = bm.HuggingFace().variantes("unsloth/Qwen3-8B-GGUF")
        self.assertEqual(len(d["variantes"]), 25)
        q4 = next(v for v in d["variantes"] if v["etiqueta"] == "Q4_K_M")
        self.assertEqual(q4["url_archivo"], "https://huggingface.co/unsloth/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf")
        with self.assertRaises(ErrorBuscador):
            bm.HuggingFace().variantes("../../etc")


# ===========================================================================
class PruebaModelScope(_SinCache):

    def test_busqueda_solo_gguf(self):
        datos = json.loads(leer("modelscope_busqueda.json"))
        datos["Data"]["Model"]["TotalCount"] = 45
        with mock.patch.object(bm.requests, "put", return_value=Respuesta(200, datos)) as put:
            r = bm.ModelScope().buscar("qwen2.5", "descargas")
        cuerpo = put.call_args.kwargs["json"]
        self.assertEqual(cuerpo["SortBy"], "DownloadsCount")
        # «SingleCriterion» lo ignora ModelScope (devolvía 10 GGUF de cada 30); «Criterion» sí filtra
        self.assertEqual(cuerpo["Criterion"], [{"category": "libraries", "predicate": "contains", "values": ["gguf"]}])
        self.assertNotIn("SingleCriterion", cuerpo)
        # Y por si acaso, lo que no sea GGUF se descarta aquí también
        self.assertEqual([m["id"] for m in r["modelos"]], ["Qwen/Qwen2.5-7B-Instruct-GGUF"])
        self.assertEqual(r["modelos"][0]["descargas"], datos["Data"]["Model"]["Models"][3]["Downloads"])
        self.assertTrue(r["modelos"][0]["actualizado"].endswith("Z"))
        self.assertEqual(r["siguiente"], 2)

    def test_variantes(self):
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, json.loads(leer("modelscope_repo.json")))):
            d = bm.ModelScope().variantes("Qwen/Qwen2.5-0.5B-Instruct-GGUF")
        v = next(v for v in d["variantes"] if v["etiqueta"] == "q4_k_m")
        self.assertTrue(v["url_archivo"].startswith("https://modelscope.cn/models/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/master/"))


# ===========================================================================
class PruebaComprobar(_SinCache):

    MANIFIESTO = {"layers": [{"mediaType": "application/vnd.ollama.image.model", "size": 1000},
                             {"mediaType": "application/vnd.ollama.image.projector", "size": 50},
                             {"mediaType": "application/vnd.ollama.image.template", "size": 5}]}

    def test_descargable_con_tamano_y_digest_del_manifiesto(self):
        cuerpo = json.dumps(self.MANIFIESTO).encode()
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, cuerpo)) as get:
            c = bm.comprobar("hf.co/a/b-GGUF:Q4_K_M")
            bm.comprobar("hf.co/a/b-GGUF:Q4_K_M")
        self.assertEqual(get.call_count, 1)                          # en caché
        self.assertEqual(get.call_args.args[0], "https://hf.co/v2/a/b-GGUF/manifests/Q4_K_M")
        self.assertTrue(c["descargable"])
        self.assertEqual(c["bytes"], 1055)
        self.assertTrue(c["vision"])
        # Ollama guarda como digest del modelo el sha256 del manifiesto
        self.assertEqual(c["digest"], hashlib.sha256(cuerpo).hexdigest())

    def test_modelscope_se_pide_como_ollama_y_el_resto_no(self):
        """ modelscope.cn devuelve otro manifiesto (y otro digest) si no es Ollama quien lo
        pide; registry.ollama.ai responde 401 al User-Agent de Ollama sin firma. """
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, {"layers": []})) as get:
            bm.comprobar("modelscope.cn/QuantFactory/SmolLM2-135M-Instruct-GGUF:Q2_K")
            self.assertTrue(get.call_args.kwargs["headers"]["User-Agent"].startswith("ollama/"))
            bm.comprobar("qwen3:8b")
            self.assertFalse(get.call_args.kwargs["headers"]["User-Agent"].startswith("ollama/"))
            bm.comprobar("hf.co/a/b:Q4_K_M")
            self.assertFalse(get.call_args.kwargs["headers"]["User-Agent"].startswith("ollama/"))

    def test_motivos_de_no_descargable(self):
        """ Cuerpos reales de hf.co y modelscope.cn al verificar """
        casos = (
            (404, b"{}", "No existe"),
            (400, b'{"error":"This repository only contains sharded GGUF files. Ollama does not yet support pulling sharded GGUF"}', "Partido"),
            (400, b'{"error":"The specified tag is not a valid quantization scheme. Please use another tag or \"latest\""}', "no reconoce «Q4_K_M»"),
            (400, b"The specified GGUF file does not exist.", "No existe"),
            (401, b"{}", "licencia"), (403, b"{}", "denegado"), (502, b"", "502"),
        )
        for i, (codigo, cuerpo, texto) in enumerate(casos):
            with mock.patch.object(bm.requests, "get", return_value=Respuesta(codigo, cuerpo)):
                c = bm.comprobar(f"hf.co/a/m{i}:Q4_K_M")
            self.assertFalse(c["descargable"])
            self.assertEqual(c["codigo"], codigo)
            self.assertIn(texto, c["motivo"])

    def test_sin_conexion_no_se_guarda_en_cache(self):
        with mock.patch.object(bm.requests, "get", side_effect=requests.ConnectionError("caído")) as get:
            self.assertFalse(bm.comprobar("qwen3:8b")["descargable"])
            bm.comprobar("qwen3:8b")
        self.assertEqual(get.call_count, 2)


# ===========================================================================
class PruebaFachada(_SinCache):

    def test_una_plataforma_caida_no_tumba_las_demas(self):
        def ollama(*a, **k):
            raise ErrorBuscador("ollama.com respondió 503")
        with mock.patch.object(bm.PROVEEDORES["ollama"], "buscar", side_effect=ollama), \
                mock.patch.object(bm.PROVEEDORES["huggingface"], "buscar", return_value={"modelos": [{"id": "a/b"}], "siguiente": "tok"}) as hf, \
                mock.patch.object(bm.PROVEEDORES["modelscope"], "buscar", side_effect=requests.Timeout("lento")):
            r = bm.buscar("qwen", ["ollama", "huggingface", "modelscope"], "descargas", paginas={"huggingface": "tok0"})
        self.assertIn("503", r["fuentes"]["ollama"]["error"])
        self.assertEqual(r["fuentes"]["ollama"]["modelos"], [])
        self.assertIsNone(r["fuentes"]["huggingface"]["error"])
        self.assertEqual(r["fuentes"]["huggingface"]["siguiente"], "tok")
        self.assertEqual(hf.call_args.args, ("qwen", "descargas", "tok0"))
        self.assertIn("lento", r["fuentes"]["modelscope"]["error"])

    def test_fuentes_desconocidas_buscan_en_todas(self):
        vacio = {"modelos": [], "siguiente": None}
        with mock.patch.object(bm.PROVEEDORES["ollama"], "buscar", return_value=vacio), \
                mock.patch.object(bm.PROVEEDORES["huggingface"], "buscar", return_value=vacio), \
                mock.patch.object(bm.PROVEEDORES["modelscope"], "buscar", return_value=vacio):
            r = bm.buscar("x", ["inventada"])
        self.assertEqual(set(r["fuentes"]), {"ollama", "huggingface", "modelscope"})

    def test_variantes_comprueba_cada_una_en_el_registro(self):
        datos = {"id": "a/b", "variantes": [
            {"ref": "hf.co/a/b:Q4_K_M", "etiqueta": "Q4_K_M", "bytes": 1, "descargable": None},
            {"ref": "hf.co/a/b:Q8_0", "etiqueta": "Q8_0", "bytes": 2, "descargable": None, "nota": "Partido"},
            {"ref": "hf.co/a/b:mlx", "etiqueta": "mlx", "descargable": False, "nota": "MLX"}]}
        respuestas = {"hf.co/a/b:Q4_K_M": {"descargable": True, "bytes": 999, "vision": False},
                      "hf.co/a/b:Q8_0": {"descargable": False, "motivo": "No puede servirla"}}
        with mock.patch.object(bm.PROVEEDORES["huggingface"], "variantes", return_value=datos), \
                mock.patch.object(bm, "comprobar", side_effect=lambda ref: respuestas[ref]) as comp:
            d = bm.variantes("huggingface", "a/b")
        self.assertEqual(comp.call_count, 2)                     # la de MLX ya se sabía
        q4, q8, mlx = d["variantes"]
        self.assertEqual((q4["descargable"], q4["bytes"]), (True, 999))
        self.assertEqual((q8["descargable"], q8["nota"]), (False, "No puede servirla"))
        self.assertEqual(mlx["nota"], "MLX")
        self.assertIsNone(datos["variantes"][0]["descargable"])  # no toca lo guardado en caché
        with self.assertRaises(ErrorBuscador):
            bm.variantes("github", "x")

    def test_actualizaciones_de_instalados(self):
        respuestas = {
            "qwen3:8b": {"descargable": True, "digest": "aaa", "bytes": 5},
            "hf.co/a/b:Q4_K_M": {"descargable": True, "digest": "nuevo", "bytes": 7},
            "mimodelo:latest": {"descargable": False, "codigo": 404, "motivo": "No existe"},
            "gemma3:4b": {"descargable": False, "motivo": "Sin conexión"},
        }
        instalados = [{"name": "qwen3:8b", "digest": "aaa"}, {"name": "hf.co/a/b:Q4_K_M", "digest": "viejo"},
                      {"name": "mimodelo:latest", "digest": "x"}, {"name": "gemma3:4b", "digest": "y"}]
        with mock.patch.object(bm, "comprobar", side_effect=lambda ref: respuestas[ref]):
            r = {x["modelo"]: x for x in bm.actualizaciones_instalados(instalados)}
        self.assertEqual(r["qwen3:8b"]["estado"], "al_dia")
        self.assertEqual(r["hf.co/a/b:Q4_K_M"]["estado"], "actualizable")
        self.assertEqual(r["hf.co/a/b:Q4_K_M"]["fuente"], "huggingface")
        self.assertEqual(r["mimodelo:latest"]["estado"], "local")
        self.assertEqual(r["gemma3:4b"]["estado"], "error")


# ===========================================================================
class PruebaEncontrarModelo(_SinCache):
    """ Sección «Encontrar un modelo concreto»: nombre, orden de Ollama o enlace pegado """

    def test_enlaces_de_cada_plataforma(self):
        casos = {
            "https://ollama.com/library/qwen3": ("ollama", "qwen3", None),
            "ollama.com/library/qwen3:8b": ("ollama", "qwen3", "8b"),
            "https://ollama.com/library/qwen3/tags": ("ollama", "qwen3", None),
            "https://ollama.com/huihui_ai/dolphin3-r1-abliterated:8b": ("ollama", "huihui_ai/dolphin3-r1-abliterated", "8b"),
            "https://ollama.com/huihui_ai/dolphin3-r1-abliterated/tags": ("ollama", "huihui_ai/dolphin3-r1-abliterated", None),
            "https://huggingface.co/unsloth/Qwen3-8B-GGUF": ("huggingface", "unsloth/Qwen3-8B-GGUF", None),
            "https://huggingface.co/unsloth/Qwen3-8B-GGUF/blob/main/Qwen3-8B-UD-Q4_K_XL.gguf": ("huggingface", "unsloth/Qwen3-8B-GGUF", "UD-Q4_K_XL"),
            "https://huggingface.co/unsloth/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf?download=true": ("huggingface", "unsloth/Qwen3-8B-GGUF", "Q4_K_M"),
            "https://huggingface.co/unsloth/Qwen3-235B-A22B-GGUF/tree/main/Q4_K_M": ("huggingface", "unsloth/Qwen3-235B-A22B-GGUF", "Q4_K_M"),
            "hf.co/unsloth/Qwen3-8B-GGUF:Q8_0": ("huggingface", "unsloth/Qwen3-8B-GGUF", "Q8_0"),
            "  ollama run hf.co/bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K_M ": ("huggingface", "bartowski/SmolLM2-135M-Instruct-GGUF", "Q4_K_M"),
            "https://modelscope.cn/models/Qwen/Qwen2.5-0.5B-Instruct-GGUF/files": ("modelscope", "Qwen/Qwen2.5-0.5B-Instruct-GGUF", None),
            "https://www.modelscope.cn/models/Qwen/Qwen2.5-0.5B-Instruct-GGUF/file/view/master/qwen2.5-0.5b-instruct-q4_k_m.gguf":
                ("modelscope", "Qwen/Qwen2.5-0.5B-Instruct-GGUF", "q4_k_m"),
            "modelscope.cn/Qwen/Qwen2.5-0.5B-Instruct-GGUF:q4_k_m": ("modelscope", "Qwen/Qwen2.5-0.5B-Instruct-GGUF", "q4_k_m"),
        }
        for texto, (fuente, id_modelo, etiqueta) in casos.items():
            q = bm.interpretar(texto)
            self.assertEqual((q["tipo"], q["fuente"], q["id"], q["etiqueta"]), ("enlace", fuente, id_modelo, etiqueta), texto)

    def test_nombres_repos_y_busquedas(self):
        self.assertEqual(bm.interpretar("unsloth/Qwen3-8B-GGUF")["tipo"], "repo")
        q = bm.interpretar("Qwen/Qwen2.5-0.5B-Instruct-GGUF:q2_k")
        self.assertEqual((q["tipo"], q["id"], q["etiqueta"]), ("repo", "Qwen/Qwen2.5-0.5B-Instruct-GGUF", "q2_k"))
        q = bm.interpretar("ollama pull gemma3:4b")
        self.assertEqual((q["tipo"], q["consulta"], q["etiqueta"]), ("nombre", "gemma3", "4b"))
        self.assertEqual(bm.interpretar("Qwen3   8B")["consulta"], "Qwen3 8B")
        # Un enlace a la búsqueda de la web es un nombre
        self.assertEqual(bm.interpretar("https://ollama.com/search?q=deepseek&o=newest")["consulta"], "deepseek")
        self.assertEqual(bm.interpretar("https://huggingface.co/models?search=qwen3%20coder")["consulta"], "qwen3 coder")

    def test_enlaces_que_no_son_un_modelo(self):
        for malo in ("", "   ", "https://ollama.com/", "https://huggingface.co/unsloth", "https://ollama.com/library/a/b/c",
                     "https://ollama.com/blog", "x" * 500, "???"):
            with self.assertRaises(ErrorBuscador, msg=malo):
                bm.interpretar(malo)
        # «..» codificado no llega a formar parte del nombre
        self.assertNotIn("..", bm.interpretar("https://huggingface.co/a/b%2F..%2Fc")["id"])

    def test_misma_clave_para_el_mismo_nombre(self):
        self.assertEqual(bm._clave("unsloth/Qwen3-8B-GGUF"), bm._clave("Qwen3 8B"))
        self.assertEqual(bm._clave("qwen3-8b:Q4_K_M"), bm._clave("Qwen3_8B.gguf"))
        self.assertNotEqual(bm._clave("Qwen3-8B-Instruct"), bm._clave("Qwen3-8B"))
        self.assertTrue(bm._parecido("SmolLM2 135M", "bartowski/SmolLM2-135M-Instruct-GGUF"))
        self.assertFalse(bm._parecido("SmolLM2 360M", "bartowski/SmolLM2-135M-Instruct-GGUF"))

    def test_ficha_repo_existe_o_no(self):
        hf = json.loads(leer("hf_busqueda.json"))[0]
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, hf)) as get:
            f = bm.ficha_repo("huggingface", "UNSLOTH/qwen3-coder-30b-a3b-instruct-gguf")
        self.assertEqual(get.call_args.args[0], "https://huggingface.co/api/models/UNSLOTH/qwen3-coder-30b-a3b-instruct-gguf")
        self.assertEqual(f["id"], "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF")        # el nombre bien escrito
        self.assertFalse(f["sin_gguf"])
        # Hugging Face responde 401 a lo que no existe (o es privado)
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(401, {"error": "Invalid username or password."})):
            self.assertIsNone(bm.ficha_repo("huggingface", "fulano/no-existe"))
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(500, b"")):
            with self.assertRaises(ErrorBuscador):
                bm.ficha_repo("huggingface", "a/caido")
        ms = json.loads(leer("modelscope_busqueda.json"))["Data"]["Model"]["Models"][0]       # sin GGUF
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, {"Code": 200, "Data": ms})):
            f = bm.ficha_repo("modelscope", "Qwen/Qwen2.5-7B-Instruct")
        self.assertTrue(f["sin_gguf"])
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(404, {"Success": False})):
            self.assertIsNone(bm.ficha_repo("modelscope", "Qwen/NoExiste"))
        pagina = '<meta name="description" content="Dolphin&#39;s first reasoning models."><span class="inline-flex items-center">tools</span><span class="inline-flex x">8b</span>'
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(200, pagina.encode())) as get:
            f = bm.ficha_repo("ollama", "huihui_ai/dolphin3-r1")
        self.assertEqual(get.call_args.args[0], "https://ollama.com/huihui_ai/dolphin3-r1")
        self.assertEqual((f["descripcion"], f["capacidades"], f["tamanos"], f["oficial"]),
                         ("Dolphin's first reasoning models.", ["tools"], ["8b"], False))
        with mock.patch.object(bm.requests, "get", return_value=Respuesta(404, b"")) as get:
            self.assertIsNone(bm.ficha_repo("ollama", "noexiste"))
            self.assertIsNone(bm.ficha_repo("ollama", "noexiste"))
        self.assertEqual(get.call_count, 1)                      # el «no existe» también se recuerda
        with mock.patch.object(bm.requests, "get") as get:
            self.assertIsNone(bm.ficha_repo("huggingface", "../../etc"))
        get.assert_not_called()

    @staticmethod
    def _modelo(fuente, id_modelo, descargas=0):
        return {"fuente": fuente, "id": id_modelo, "descargas": descargas}

    def test_enlace_va_directo_sin_buscar(self):
        ficha = {**self._modelo("huggingface", "unsloth/Qwen3-8B-GGUF"), "sin_gguf": False}
        with mock.patch.object(bm, "ficha_repo", return_value=ficha) as fr, mock.patch.object(bm, "buscar") as busca:
            r = bm.localizar("https://huggingface.co/unsloth/Qwen3-8B-GGUF/blob/main/Qwen3-8B-Q4_K_M.gguf")
        fr.assert_called_once_with("huggingface", "unsloth/Qwen3-8B-GGUF")
        busca.assert_not_called()
        self.assertEqual([m["id"] for m in r["exactos"]], ["unsloth/Qwen3-8B-GGUF"])
        self.assertEqual(r["exactos"][0]["destacar"], "Q4_K_M")

    def test_repo_se_mira_en_las_tres_y_sin_gguf_sugiere_versiones_gguf(self):
        def ficha(fuente, id_modelo):
            return {**self._modelo(fuente, id_modelo), "sin_gguf": True} if fuente in ("huggingface", "modelscope") else None
        busqueda = {"fuentes": {
            "huggingface": {"modelos": [self._modelo("huggingface", "Qwen/Qwen3-8B"), self._modelo("huggingface", "unsloth/Qwen3-8B-Instruct-abliterated-GGUF"),
                                        self._modelo("huggingface", "unsloth/Qwen3-8B-GGUF")], "error": None},
            "modelscope": {"modelos": [], "error": "ModelScope respondió 503"},
            "ollama": {"modelos": [self._modelo("ollama", "otro/modelo")], "error": None}}}
        with mock.patch.object(bm, "ficha_repo", side_effect=ficha) as fr, mock.patch.object(bm, "buscar", return_value=busqueda):
            r = bm.localizar("Qwen/Qwen3-8B")
        self.assertEqual({c.args[0] for c in fr.call_args_list}, {"ollama", "huggingface", "modelscope"})
        self.assertEqual([(m["fuente"], m["id"]) for m in r["exactos"]], [("huggingface", "Qwen/Qwen3-8B"), ("modelscope", "Qwen/Qwen3-8B")])
        # La versión GGUF con el mismo nombre va delante; lo que no se parece no aparece
        self.assertEqual([m["id"] for m in r["parecidos"]], ["unsloth/Qwen3-8B-GGUF", "unsloth/Qwen3-8B-Instruct-abliterated-GGUF"])
        self.assertIn("503", r["errores"]["modelscope"])

    def test_nombre_exactos_por_descargas_y_parecidos(self):
        busqueda = {"fuentes": {
            "ollama": {"modelos": [self._modelo("ollama", "qwen3"), self._modelo("ollama", "qwen3.8")], "error": None},
            "huggingface": {"modelos": [self._modelo("huggingface", "poco/Qwen3-GGUF", 5), self._modelo("huggingface", "mucho/qwen3-gguf", 900),
                                        self._modelo("huggingface", "x/Llama-3-8B-GGUF", 10 ** 6)], "error": None},
            "modelscope": {"modelos": [], "error": None}}}
        directo = {**self._modelo("ollama", "qwen3"), "sin_gguf": False}
        with mock.patch.object(bm, "ficha_repo", return_value=directo) as fr, mock.patch.object(bm, "buscar", return_value=busqueda) as busca:
            r = bm.localizar("qwen3:8b")
        fr.assert_called_once_with("ollama", "qwen3")
        self.assertEqual(busca.call_args.args[0], "qwen3")
        self.assertEqual([m["id"] for m in r["exactos"]], ["qwen3", "mucho/qwen3-gguf", "poco/Qwen3-GGUF"])
        self.assertEqual(r["exactos"][0]["destacar"], "8b")
        self.assertEqual([m["id"] for m in r["parecidos"]], ["qwen3.8"])
        # Con espacios no es un nombre de Ollama: no se comprueba directamente
        with mock.patch.object(bm, "ficha_repo") as fr, mock.patch.object(bm, "buscar", return_value=busqueda):
            bm.localizar("Qwen3 8B")
        fr.assert_not_called()


# ===========================================================================
class ProveedorFalso:
    def __init__(self):
        self.variantes_actuales = []

    def variantes(self, id_modelo):
        return {"id": id_modelo, "variantes": self.variantes_actuales}


class PruebaSeguimiento(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_buscador_")
        self.ruta = os.path.join(self.tmp, "buscador.json")
        self.prov = ProveedorFalso()
        self.s = bm.Seguimiento(self.ruta, {"ollama": self.prov})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_la_ruta_se_puede_aislar(self):
        with mock.patch.dict(os.environ, {"PRIG_BUSCADOR_ARCHIVO": self.ruta}):
            self.assertEqual(bm.ruta_estado(), self.ruta)

    def test_detecta_nuevas_retiradas_y_cambiadas(self):
        self.prov.variantes_actuales = [{"etiqueta": "8b", "bytes": 5, "digest": "a"},
                                        {"etiqueta": "4b", "bytes": 3, "digest": "b"},
                                        {"etiqueta": "Q4_K_M", "bytes": 10, "digest": None}]
        self.s.seguir("ollama", "qwen3")
        self.assertIsNone(self.s.revisar()[0]["cambios"])
        self.prov.variantes_actuales = [{"etiqueta": "8b", "bytes": 5, "digest": "a2"},
                                        {"etiqueta": "Q4_K_M", "bytes": 11, "digest": None},
                                        {"etiqueta": "14b", "bytes": 9, "digest": "c"}]
        seguido = self.s.revisar()[0]
        self.assertEqual(seguido["cambios"], {"nuevas": ["14b"], "retiradas": ["4b"], "cambiadas": ["8b", "Q4_K_M"]})
        self.assertNotIn("instantanea", seguido)
        # Persistente y «visto» acepta el estado actual
        otro = bm.Seguimiento(self.ruta, {"ollama": self.prov})
        self.assertTrue(otro.lista()[0]["cambios"])
        otro.marcar_visto("ollama", "qwen3")
        self.assertIsNone(otro.revisar()[0]["cambios"])

    def test_error_de_red_no_borra_los_cambios_pendientes(self):
        self.prov.variantes_actuales = [{"etiqueta": "8b", "bytes": 5}]
        self.s.seguir("ollama", "qwen3")
        self.prov.variantes_actuales = [{"etiqueta": "8b", "bytes": 5}, {"etiqueta": "1b", "bytes": 1}]
        self.s.revisar()
        with mock.patch.object(self.prov, "variantes", side_effect=requests.ConnectionError("sin red")):
            seguido = self.s.revisar()[0]
        self.assertEqual(seguido["cambios"]["nuevas"], ["1b"])
        self.assertIn("sin red", seguido["error"])

    def test_dejar_y_fuente_desconocida(self):
        self.s.seguir("ollama", "qwen3")
        self.s.dejar("ollama", "qwen3")
        self.assertEqual(self.s.lista(), [])
        with self.assertRaises(ErrorBuscador):
            self.s.seguir("github", "x")

    def test_actualizaciones_guardadas_una_vez_al_dia(self):
        resultado = [{"modelo": "qwen3:8b", "fuente": "ollama", "estado": "actualizable"},
                     {"modelo": "gemma3:4b", "fuente": "ollama", "estado": "al_dia"}]
        with mock.patch.object(bm, "actualizaciones_instalados", return_value=resultado) as calc:
            a = self.s.actualizaciones(lambda: [], max_edad=86400)
            b = self.s.actualizaciones(lambda: [], max_edad=86400)
            self.s.actualizaciones(lambda: [], max_edad=86400, forzar=True)
        self.assertEqual(calc.call_count, 2)
        self.assertEqual((a["actualizables"], a["de_cache"], b["de_cache"]), (1, False, True))
        # Al terminar de descargarlo deja de figurar como actualizable
        self.s.marcar_actualizado("qwen3:8b")
        c = self.s.actualizaciones(lambda: [], max_edad=86400)
        self.assertEqual(c["actualizables"], 0)
        self.assertEqual(c["modelos"][0]["estado"], "al_dia")


# ===========================================================================
class PruebaDescargas(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_descargas_")
        self.terminadas = []
        self.comprobacion = {"descargable": True, "bytes": 1000}
        self.d = dm.Descargas(lambda: "http://ollama.falso", lambda: self.tmp,
                              al_terminar=self.terminadas.append, comprobar=lambda ref: dict(self.comprobacion))
        self.disco = mock.patch.object(dm.shutil, "disk_usage", return_value=mock.Mock(free=10**12))
        self.disco.start()

    def tearDown(self):
        self.disco.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def esperar(self, id_, estados=("completado", "error", "cancelado"), limite=5):
        fin = time.time() + limite
        while time.time() < fin:
            item = next(i for i in self.d.lista() if i["id"] == id_)
            if item["estado"] in estados:
                return item
            time.sleep(0.02)
        self.fail(f"La descarga no llegó a {estados}: {item}")

    def test_descarga_completa_con_progreso_por_capas(self):
        lineas = [{"status": "pulling manifest"},
                  {"status": "pulling abc", "digest": "sha256:abc", "total": 900, "completed": 300},
                  {"status": "pulling def", "digest": "sha256:def", "total": 100, "completed": 100},
                  {"status": "pulling abc", "digest": "sha256:abc", "total": 900, "completed": 900},
                  {"status": "verifying sha256 digest"}, {"status": "writing manifest"}, {"status": "success"}]
        with mock.patch.object(dm.requests, "post", return_value=Respuesta(200, lineas=lineas)) as post:
            item = self.esperar(self.d.encolar("hf.co/a/b:Q4_K_M", "Mi modelo")["id"])
        self.assertEqual(post.call_args.kwargs["json"], {"model": "hf.co/a/b:Q4_K_M", "stream": True})
        self.assertEqual(post.call_args.args[0], "http://ollama.falso/api/pull")
        self.assertEqual(item["estado"], "completado")
        self.assertEqual((item["completado"], item["total"], item["porcentaje"]), (1000, 1000, 100.0))
        self.assertEqual((item["fuente"], item["titulo"]), ("huggingface", "Mi modelo"))
        self.assertEqual([t["ref"] for t in self.terminadas], ["hf.co/a/b:Q4_K_M"])

    def test_no_descargable_ni_siquiera_llama_a_ollama(self):
        self.comprobacion = {"descargable": False, "motivo": "Requiere iniciar sesión o aceptar una licencia."}
        with mock.patch.object(dm.requests, "post") as post:
            item = self.esperar(self.d.encolar("hf.co/google/gemma:Q4_0")["id"])
        post.assert_not_called()
        self.assertEqual(item["estado"], "error")
        self.assertIn("licencia", item["error"])

    def test_sin_espacio_en_disco(self):
        self.comprobacion = {"descargable": True, "bytes": 50 * 10**9}
        with mock.patch.object(dm.shutil, "disk_usage", return_value=mock.Mock(free=20 * 10**9)), \
                mock.patch.object(dm.requests, "post") as post:
            item = self.esperar(self.d.encolar("qwen3:30b")["id"])
        post.assert_not_called()
        self.assertIn("No hay espacio", item["error"])

    def test_errores_de_ollama_traducidos(self):
        with mock.patch.object(dm.requests, "post", return_value=Respuesta(200, lineas=[
                {"status": "pulling manifest"}, {"error": "pull model manifest: 412: requires a newer version of Ollama"}])):
            item = self.esperar(self.d.encolar("qwen3.8:27b")["id"])
        self.assertIn("más nueva", item["error"])
        with mock.patch.object(dm.requests, "post", return_value=Respuesta(500, {"error": "file does not exist"})):
            item = self.esperar(self.d.encolar("qwen3:99b")["id"])
        self.assertIn("no existe", item["error"])
        with mock.patch.object(dm.requests, "post", return_value=Respuesta(200, lineas=[{"status": "pulling manifest"}])):
            item = self.esperar(self.d.encolar("qwen3:4b")["id"])
        self.assertIn("sin confirmación", item["error"])

    def test_explicar_error(self):
        self.assertIn("conexión", dm.explicar_error("HTTPConnectionPool: Max retries exceeded"))
        self.assertIn("licencia", dm.explicar_error("", 401))
        self.assertIn("espacio", dm.explicar_error("write: no space left on device"))
        self.assertEqual(dm.explicar_error("otra cosa"), "otra cosa")

    def test_cancelar_duplicados_y_reintentar(self):
        seguir = threading.Event()

        def lineas_lentas():
            yield json.dumps({"status": "pulling abc", "digest": "abc", "total": 1000, "completed": 10}).encode()
            seguir.wait(5)
            yield json.dumps({"status": "pulling abc", "digest": "abc", "total": 1000, "completed": 20}).encode()
            yield json.dumps({"status": "success"}).encode()

        resp = Respuesta(200)
        resp.iter_lines = lineas_lentas
        with mock.patch.object(dm.requests, "post", return_value=resp):
            a = self.d.encolar("qwen3:8b")
            repetida = self.d.encolar("qwen3:8b")
            self.assertEqual(repetida["id"], a["id"])                          # no se duplica
            json.dumps(repetida)                                               # la API la devuelve tal cual
            self.assertFalse([k for k in repetida if k.startswith("_")])
            b = self.d.encolar("gemma3:4b")
            self.esperar(a["id"], ("descargando",))
            self.assertEqual(self.d.cancelar(b["id"])["estado"], "cancelado")  # en cola: al momento
            self.d.cancelar(a["id"])
            seguir.set()
            self.assertEqual(self.esperar(a["id"])["estado"], "cancelado")
        self.assertEqual(self.esperar(b["id"])["estado"], "cancelado")
        with mock.patch.object(dm.requests, "post", return_value=Respuesta(200, lineas=[{"status": "success"}])):
            nuevo = self.d.reintentar(a["id"])
            self.assertNotEqual(nuevo["id"], a["id"])
            self.assertEqual(self.esperar(nuevo["id"])["estado"], "completado")
        json.dumps(self.d.lista()), json.dumps(self.d.cancelar(a["id"])), json.dumps(self.d.reintentar(nuevo["id"]))
        self.assertEqual(self.d.limpiar_terminadas(), 3)
        self.assertEqual(self.d.lista(), [])
        with self.assertRaises(ErrorBuscador):
            self.d.cancelar(999)

    def test_ref_no_valida_no_entra_en_la_cola(self):
        with self.assertRaises(ErrorBuscador):
            self.d.encolar("qwen3; rm -rf /")
        self.assertEqual(self.d.lista(), [])


if __name__ == "__main__":
    unittest.main()
