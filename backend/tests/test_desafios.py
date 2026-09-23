"""
Desafíos: páginas de código, pruebas ocultas, fuentes de internet y tutor.

Sin red y sin modelo: las fuentes se leen de `datos_desafios/` (copias recortadas de
Exercism, TheAlgorithms y Project Euler) y el modelo es un doble que devuelve textos
fijos. Lo que SÍ se ejecuta de verdad es Python, porque es justo lo que se protege:

  · las páginas se importan entre sí como módulos y la comprobación dice cuántas
    pruebas pasan y cuál falla (unittest, doctest y asserts);
  · un desafío solo vale si la referencia pasa y el código de partida no;
  · la solución y las pruebas no salen del almacén hasta rendirse o resolver;
  · rendirse y después aprobar no cuenta como resuelto;
  · de las fuentes: índice, búsqueda en castellano, carga y verificación ejecutando;
  · del tutor: reintentar contándole al modelo por qué falló, reparar cuerpos vacíos,
    rechazar páginas que ya traen la solución y sacar el código de la caja de razonamiento.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from runner import CodeRunner
from desafios import almacen as alm, ejecucion as ej, fuentes as fu, tutor as tu
from desafios.ejecucion import ErrorDesafio

DATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos_desafios")


def dato(nombre):
    with open(os.path.join(DATOS, nombre), encoding="utf-8") as f:
        return f.read()


RUNNER = CodeRunner()

PILA = {"nombre": "pila.py", "contenido": "class Pila:\n    def __init__(self):\n        self.d = []\n\n"
                                          "    def apilar(self, x):\n        self.d.append(x)\n\n"
                                          "    def desapilar(self):\n        return self.d.pop() if self.d else None\n"}
PILA_VACIA = {"nombre": "pila.py", "contenido": "class Pila:\n    def apilar(self, x):\n        pass\n\n    def desapilar(self):\n        pass\n"}
PRINCIPAL = {"nombre": "principal.py", "contenido": "from pila import Pila\np = Pila()\np.apilar(7)\nprint('saca', p.desapilar())\n"}
ASSERTS = ["from pila import Pila\np = Pila()\np.apilar(1)\np.apilar(2)\nassert p.desapilar() == 2",
           "from pila import Pila\nassert Pila().desapilar() is None, 'vacía devuelve None'",
           "from pila import Pila\np = Pila()\np.apilar('a')\nassert p.desapilar() == 'a'"]


class _Carpeta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_desafios_test_")
        self.env = mock.patch.dict(os.environ, {"PRIG_DESAFIOS_DIR": self.tmp})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ===========================================================================
class PruebaPaginas(unittest.TestCase):

    def test_nombres_de_pagina(self):
        self.assertEqual([p["nombre"] for p in ej.validar_paginas([{"nombre": " pila.py ", "contenido": "x"}])], ["pila.py"])
        for malo in ("mi pila.py", "pila", "../pila.py", "1pila.py", "pila-dos.py", "pytest.py", "_prig_config.py", ""):
            with self.assertRaises(ErrorDesafio, msg=malo):
                ej.validar_paginas([{"nombre": malo, "contenido": ""}])
        with self.assertRaises(ErrorDesafio):
            ej.validar_paginas([{"nombre": "a.py"}, {"nombre": "A.py"}])
        with self.assertRaises(ErrorDesafio):
            ej.validar_paginas([])
        with self.assertRaises(ErrorDesafio):
            ej.validar_paginas([{"nombre": f"p{i}.py"} for i in range(ej.MAX_PAGINAS + 1)])
        with self.assertRaises(ErrorDesafio):
            ej.validar_paginas([{"nombre": "grande.py", "contenido": "x" * (ej.MAX_BYTES_PAGINA + 1)}])

    def test_una_pagina_importa_otra(self):
        r = ej.ejecutar_pagina(RUNNER, [PILA, PRINCIPAL], "principal.py")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["stdout"].strip(), "saca 7")
        with self.assertRaises(ErrorDesafio):
            ej.ejecutar_pagina(RUNNER, [PILA], "no_existe.py")

    def test_el_error_no_muestra_la_carpeta_temporal(self):
        r = ej.ejecutar_pagina(RUNNER, [{"nombre": "roto.py", "contenido": "1/0\n"}], "roto.py")
        self.assertFalse(r["ok"])
        self.assertIn("ZeroDivisionError", r["stderr"])
        self.assertNotIn("prig_desafio_", r["stderr"])


class PruebaComprobar(unittest.TestCase):

    def test_asserts_cuenta_y_explica(self):
        r = ej.comprobar(RUNNER, [PILA_VACIA], {"comprobacion": {"tipo": "asserts", "asserts": ASSERTS}})
        self.assertFalse(r["aprobado"])
        self.assertEqual((r["pasados"], r["total"]), (1, 3))       # la segunda pasa: pass devuelve None
        self.assertEqual(r["fallos"][0]["nombre"], "prueba 1")
        self.assertIn("assert p.desapilar() == 2", r["fallos"][0]["codigo"])
        r = ej.comprobar(RUNNER, [PILA], {"comprobacion": {"tipo": "asserts", "asserts": ASSERTS}})
        self.assertTrue(r["aprobado"], r)

    def test_unittest_con_sustituto_de_pytest(self):
        pruebas = ("import unittest\nimport pytest\nfrom pila import Pila\n\n"
                   "class T(unittest.TestCase):\n"
                   "    @pytest.mark.task(taskno=1)\n    def test_apilar_y_desapilar(self):\n        p = Pila(); p.apilar(3); self.assertEqual(p.desapilar(), 3)\n"
                   "    def test_vacia(self):\n        self.assertIsNone(Pila().desapilar())\n"
                   "    def test_lanza(self):\n        with pytest.raises(ValueError, match='no'):\n            raise ValueError('no hay')\n")
        priv = {"comprobacion": {"tipo": "unittest", "archivos": {"pila_test.py": pruebas}}}
        r = ej.comprobar(RUNNER, [PILA], priv)
        self.assertTrue(r["aprobado"], r)
        self.assertEqual(r["total"], 3)
        r = ej.comprobar(RUNNER, [{"nombre": "pila.py", "contenido": "class Pila:\n    def apilar(self, x): pass\n    def desapilar(self): return 0\n"}], priv)
        self.assertEqual((r["pasados"], r["total"]), (1, 3))
        self.assertIn("apilar y desapilar", [f["nombre"] for f in r["fallos"]])
        with self.assertRaises(ErrorDesafio):     # una página no puede llamarse como las pruebas
            ej.comprobar(RUNNER, [{"nombre": "pila_test.py", "contenido": ""}], priv)

    def test_doctest(self):
        priv = {"comprobacion": {"tipo": "doctest", "modulo": "doble", "ejemplos": ">>> doble(2)\n4\n>>> doble('a')\n'aa'\n>>> doble(0)\n0"}}
        r = ej.comprobar(RUNNER, [{"nombre": "doble.py", "contenido": "def doble(x):\n    return x + x\n"}], priv)
        self.assertTrue(r["aprobado"], r)
        r = ej.comprobar(RUNNER, [{"nombre": "doble.py", "contenido": "def doble(x):\n    return x * 3\n"}], priv)
        self.assertEqual((r["pasados"], r["total"]), (1, 3))
        self.assertIn("Se esperaba: 4", r["fallos"][0]["mensaje"])
        r = ej.comprobar(RUNNER, [{"nombre": "doble.py", "contenido": "def doble(x:\n"}], priv)
        self.assertIn("no se puede importar", r["error"])

    def test_bucle_infinito_y_sin_pruebas(self):
        r = ej.comprobar(RUNNER, [{"nombre": "m.py", "contenido": "while True:\n    pass\n"}],
                         {"comprobacion": {"tipo": "asserts", "asserts": ["import m"]}}, timeout=2)
        self.assertFalse(r["aprobado"])
        self.assertIn("bucle", r["error"])
        r = ej.comprobar(RUNNER, [PILA], {"comprobacion": {"tipo": "ninguna"}})
        self.assertFalse(r["comprobable"])

    def test_validar_desafio(self):
        priv = {"comprobacion": {"tipo": "asserts", "asserts": ASSERTS}}
        v = ej.validar_desafio(RUNNER, [PILA_VACIA], [PILA], priv, minimo_pruebas=3)
        self.assertTrue(v["valido"], v)
        self.assertEqual(v["pruebas"], 3)
        # Pruebas que no comprueban nada: pasan también con el código de partida
        v = ej.validar_desafio(RUNNER, [PILA_VACIA], [PILA], {"comprobacion": {"tipo": "asserts", "asserts": ["assert True"]}})
        self.assertFalse(v["valido"])
        self.assertIn("no comprueban nada", v["motivo"])
        # Referencia que no pasa sus pruebas
        v = ej.validar_desafio(RUNNER, [PILA_VACIA], [PILA_VACIA], priv)
        self.assertIn("referencia no pasa", v["motivo"])
        # Páginas distintas
        v = ej.validar_desafio(RUNNER, [PILA_VACIA], [PILA, PRINCIPAL], priv)
        self.assertIn("mismas páginas", v["motivo"])
        v = ej.validar_desafio(RUNNER, [PILA_VACIA], [PILA], priv, minimo_pruebas=4)
        self.assertIn("al menos 4", v["motivo"])


# ===========================================================================
class PruebaAlmacen(_Carpeta):

    def nuevo(self):
        a = alm.Almacen()
        d = a.guardar({"titulo": "Pila", "paginas": [PILA_VACIA], "comprobacion": {"tipo": "asserts"},
                       "origen": {"tipo": "modelo"}, "privado": {"referencia": [PILA], "comprobacion": {"tipo": "asserts", "asserts": ASSERTS}}})
        return a, d

    def test_no_crea_carpetas_hasta_guardar(self):
        a = alm.Almacen()
        self.assertEqual(a.lista(), [])
        self.assertFalse(os.path.exists(a.dir))
        with self.assertRaises(ErrorDesafio):
            a.obtener(alm.nuevo_id())
        self.assertFalse(os.path.exists(a.dir))

    def test_ruta_aislada_y_ids_validos(self):
        a, d = self.nuevo()
        self.assertTrue(a.dir.startswith(self.tmp))
        self.assertRegex(d["id"], r"^des_[0-9a-f]{10}$")
        for malo in ("../x", "des_zz", "", "des_0123456789/../../"):
            with self.assertRaises(ErrorDesafio):
                a.obtener(malo)
        self.assertFalse(a.borrar(alm.nuevo_id()))

    def test_la_vista_publica_no_lleva_solucion_ni_pruebas(self):
        a, d = self.nuevo()
        vista = alm.Almacen.publico(a.obtener(d["id"]))
        self.assertNotIn("privado", vista)
        self.assertNotIn("p.desapilar() == 2", json.dumps(vista))        # pruebas
        self.assertNotIn("self.d.pop()", json.dumps(vista))              # solución
        self.assertFalse(vista["solucion_disponible"])

    def test_progreso(self):
        a, d = self.nuevo()
        fallo = {"aprobado": False, "pasados": 1, "total": 3}
        bien = {"aprobado": True, "pasados": 3, "total": 3}
        d = a.modificar(d["id"], lambda x: alm.Almacen.registrar_comprobacion(x, fallo))
        self.assertEqual((d["progreso"]["estado"], d["progreso"]["intentos"], d["progreso"]["mejor"]), ("en_curso", 1, {"pasados": 1, "total": 3}))
        d = a.modificar(d["id"], lambda x: alm.Almacen.registrar_comprobacion(x, bien))
        self.assertEqual(d["progreso"]["estado"], "resuelto")
        self.assertIsNotNone(d["progreso"]["segundos_hasta_resolver"])
        self.assertTrue(alm.Almacen.publico(d)["solucion_disponible"])
        # Rendirse y después aprobar no es resolverlo
        _, otro = self.nuevo()
        otro = a.modificar(otro["id"], lambda x: x["progreso"].update(estado="rendido"))
        otro = a.modificar(otro["id"], lambda x: alm.Almacen.registrar_comprobacion(x, bien))
        self.assertEqual(otro["progreso"]["estado"], "rendido")
        lista = a.lista()
        self.assertEqual(len(lista), 2)
        self.assertEqual({x["estado"] for x in lista}, {"resuelto", "rendido"})
        self.assertNotIn("privado", json.dumps(lista))


# ===========================================================================
class DescargaFalsa:
    """ Sustituye a fuentes.descargar sirviendo los archivos de datos_desafios """
    MAPA = {
        "exercism/python/main/config.json": "exercism_config.json",
        "practice/binary-search/.meta/config.json": "binary_search__.meta_config.json",
        "practice/binary-search/.docs/instructions.md": "binary_search__.docs_instructions.md",
        "practice/binary-search/.docs/instructions.append.md": "binary_search__.docs_instructions.append.md",
        "practice/binary-search/binary_search.py": "binary_search__binary_search.py",
        "practice/binary-search/binary_search_test.py": "binary_search__binary_search_test.py",
        "practice/binary-search/.meta/example.py": "binary_search__.meta_example.py",
        "TheAlgorithms/Python/master/DIRECTORY.md": "thealgorithms_directory.md",
        "TheAlgorithms/Python/master/searches/binary_search.py": "thealgorithms_binary_search.py",
        "minimal=problems;csv": "euler_problems.csv",
        "minimal=15": "euler_15.html",
    }

    def __init__(self):
        self.pedidas = []

    def __call__(self, url, ttl, obligatorio=True):
        self.pedidas.append(url)
        for final, archivo in self.MAPA.items():
            if url.endswith(final):
                return dato(archivo)
        if obligatorio:
            raise ErrorDesafio(f"No existe: {url}")
        return None


class PruebaFuentes(_Carpeta):

    def setUp(self):
        super().setUp()
        self.descarga = DescargaFalsa()
        self.parche = mock.patch.object(fu, "descargar", self.descarga)
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        super().tearDown()

    def test_terminos_en_castellano(self):
        etiquetas, palabras = fu.terminos("Quiero practicar búsqueda binaria y recursividad")
        self.assertTrue({"binary-search", "searches", "recursion"} <= etiquetas)
        self.assertIn("recursividad", palabras)
        self.assertNotIn("quiero", palabras)
        etiquetas, _ = fu.terminos("pila", extra=["Linked List"])
        self.assertIn("linked-list", etiquetas)

    def test_indices(self):
        ex = {e["ref"]: e for e in fu.Exercism().indice()}
        self.assertIn("practice/binary-search", ex)
        self.assertNotIn("practice/hello-world", ex)            # no es un desafío
        self.assertNotIn("practice/retirado", ex)               # obsoleto
        self.assertNotIn("concept/log-levels", ex)              # en construcción
        self.assertEqual(ex["concept/inventory-management"]["nivel"], "principiante")
        ta = {e["ref"]: e for e in fu.TheAlgorithms().indice()}
        self.assertIn("searches/binary_search.py", ta)
        self.assertIn("data_structures/arrays/kth_largest_element.py", ta)
        self.assertIn("arrays", ta["data_structures/arrays/kth_largest_element.py"]["etiquetas"])
        self.assertFalse(any(r.startswith("web_programming/") for r in ta))   # necesitan red
        pe = fu.ProjectEuler().indice()
        self.assertEqual(pe[0]["ref"], "1")
        self.assertFalse(pe[0]["verificable"])
        self.assertEqual(pe[0]["nivel"], "principiante")

    def test_buscar(self):
        r = fu.buscar("búsqueda binaria")
        refs = [(x["fuente"], x["ref"]) for x in r["resultados"]]
        self.assertEqual(refs[0], ("exercism", "practice/binary-search"))
        ta = [x for x in r["resultados"] if x["fuente"] == "thealgorithms"]
        self.assertEqual(ta[0]["ref"], "searches/binary_search.py")
        self.assertNotIn("palabras", r["resultados"][0])
        self.assertEqual(fu.buscar("diccionarios", fuentes=["exercism"])["resultados"][0]["ref"], "concept/inventory-management")
        self.assertEqual(fu.buscar("zzzz qqqq")["resultados"], [])

    def test_fuente_caida_no_tumba_la_busqueda(self):
        def descarga(url, ttl, obligatorio=True):
            if "projecteuler" in url:
                raise ErrorDesafio("Sin conexión con projecteuler.net")
            return self.descarga(url, ttl, obligatorio)
        with mock.patch.object(fu, "descargar", descarga):
            r = fu.buscar("búsqueda binaria")
        self.assertIn("projecteuler", r["errores"])
        self.assertTrue(r["resultados"])

    def test_importar_exercism_verificado_ejecutando(self):
        d = fu.importar("exercism", "practice/binary-search", RUNNER)
        self.assertEqual([p["nombre"] for p in d["paginas"]], ["binary_search.py"])
        self.assertEqual(d["comprobacion"]["pruebas"], 11)
        self.assertIn("binary_search_test.py", d["privado"]["comprobacion"]["archivos"])
        self.assertEqual(d["privado"]["referencia"][0]["nombre"], "binary_search.py")
        self.assertIn("Exception messages", d["enunciado"])       # instructions + append
        self.assertEqual(d["origen"]["licencia"], "MIT")
        with self.assertRaises(ErrorDesafio):
            fu.importar("exercism", "practice/../../x", RUNNER)
        with self.assertRaises(ErrorDesafio):
            fu.importar("codewars", "x", RUNNER)

    def test_admoniciones_de_exercism(self):
        md = fu.Exercism._admoniciones("Hola\n~~~~exercism/caution\nSolo listas ordenadas.\n~~~~\nFin")
        self.assertIn("> **Cuidado**", md)
        self.assertIn("> Solo listas ordenadas.", md)

    def test_importar_thealgorithms_con_doctest(self):
        d = fu.importar("thealgorithms", "searches/binary_search.py", RUNNER)
        pagina = d["paginas"][0]["contenido"]
        self.assertEqual(d["paginas"][0]["nombre"], "binary_search.py")
        self.assertIn("raise NotImplementedError", pagina)
        self.assertNotIn('if __name__ == "__main__"', pagina)
        self.assertNotIn("searches = (", pagina)                  # constante que no usa
        self.assertEqual(d["comprobacion"]["tipo"], "doctest")
        self.assertGreaterEqual(d["comprobacion"]["pruebas"], 3)
        self.assertTrue(d["origen"]["otras_funciones"])
        otra = d["origen"]["otras_funciones"][0]
        d2 = fu.importar("thealgorithms", "searches/binary_search.py", RUNNER, funcion=otra)
        self.assertEqual(d2["origen"]["funcion"], otra)
        with self.assertRaises(ErrorDesafio):
            fu.importar("thealgorithms", "searches/binary_search.py", RUNNER, funcion="no_existe")

    def test_project_euler_sin_pruebas(self):
        d = fu.importar("projecteuler", "15", RUNNER)
        self.assertEqual(d["comprobacion"]["tipo"], "ninguna")
        self.assertIn("$20 \\times 20$", d["enunciado"])
        self.assertIn("https://projecteuler.net/resources/images/0015.png", d["enunciado"])
        self.assertNotIn("<p>", d["enunciado"])
        self.assertIn("CC BY-NC-SA 4.0", d["origen"]["atribucion"])
        self.assertTrue(ej.ejecutar_pagina(RUNNER, d["paginas"], "euler_15.py")["stderr"])   # NotImplementedError

    def test_descargar_con_cache_y_sin_red(self):
        self.parche.stop()
        try:
            respuesta = mock.Mock(status_code=200, text="contenido")
            with mock.patch.object(fu.requests, "get", return_value=respuesta) as get:
                self.assertEqual(fu.descargar("https://example.org/a", 100), "contenido")
                self.assertEqual(fu.descargar("https://example.org/a", 100), "contenido")
            self.assertEqual(get.call_count, 1)
            with mock.patch.object(fu.requests, "get", side_effect=requests.ConnectionError("sin red")):
                self.assertEqual(fu.descargar("https://example.org/a", 0), "contenido")   # copia vieja
                with self.assertRaises(ErrorDesafio):
                    fu.descargar("https://example.org/otra", 0)
            with mock.patch.object(fu.requests, "get", return_value=mock.Mock(status_code=404, text="")):
                self.assertIsNone(fu.descargar("https://example.org/falta", 100, obligatorio=False))
        finally:
            self.parche.start()


# ===========================================================================
class ModeloFalso:
    """ Doble del motor: devuelve respuestas en orden y registra los prompts """

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.prompts = []

    def generate_response(self, prompt, model=None, system_prompt="", options=None, think=None,
                          on_thinking=None, on_token=None, uso=None, on_stats=None):
        self.prompts.append((prompt, system_prompt, think))
        texto = self.respuestas.pop(0)
        for trozo in [texto[i:i + 7] for i in range(0, len(texto), 7)]:
            if on_token:
                on_token(trozo)
            yield trozo

    @staticmethod
    def _extract_and_parse_json(texto):
        from ai_engine import AIEngine
        return AIEngine._extract_and_parse_json(None, texto)


def desafio_json(**cambios):
    datos = {"titulo": "Pila", "enunciado": "Markdown en español: Implementa una pila.", "nivel": "intermedio",
             "conceptos": ["clases"], "paginas": [{"nombre": "pila", "descripcion": "La pila", "contenido": PILA_VACIA["contenido"]}],
             "referencia": [{"nombre": "pila.py", "contenido": PILA["contenido"]}], "pruebas": ASSERTS}
    datos.update(cambios)
    return json.dumps(datos)


class PruebaTutor(unittest.TestCase):

    def test_crear_reintenta_contando_el_fallo(self):
        malo = desafio_json(pruebas=["from pila import Pila\nassert True", "assert 1", "assert 2"])
        ai = ModeloFalso(["esto no es json", malo, "<think>pienso</think>" + desafio_json()])
        eventos = []
        d = tu.crear(ai, RUNNER, "m", "pilas", "intermedio", avisar=eventos.append)
        self.assertEqual(d["comprobacion"]["pruebas"], 3)
        self.assertEqual(d["paginas"][0]["nombre"], "pila.py")
        self.assertEqual(d["enunciado"], "Implementa una pila.")
        self.assertEqual(len(d["intentos_creacion"]), 3)
        self.assertIn("JSON", ai.prompts[1][0])                   # el 2º intento sabe por qué falló el 1º
        self.assertIn("no comprueban nada", ai.prompts[2][0])
        self.assertTrue(all(p[2] is False for p in ai.prompts))   # sin pensamiento en voz alta
        self.assertTrue(any(e.get("descartado") for e in eventos))

    def test_crear_se_rinde_tras_los_intentos(self):
        ai = ModeloFalso(["nada"] * 3)
        with self.assertRaises(ErrorDesafio) as e:
            tu.crear(ai, RUNNER, "m", "pilas", intentos=3)
        self.assertIn("3 intentos", str(e.exception))
        with self.assertRaises(ErrorDesafio):
            tu.crear(ModeloFalso([]), RUNNER, "m", "  ")

    def test_error_de_ollama_se_explica(self):
        ai = ModeloFalso(["[Error Ollama: 500: error starting llama-server: llama-server binary not found (checked: x)]"])
        with self.assertRaises(ErrorDesafio) as e:
            tu.crear(ai, RUNNER, "m", "pilas")
        self.assertIn("Reinicia Ollama desde Prig", str(e.exception))

    def test_repara_cuerpos_vacios_de_los_modelos(self):
        codigo = ("class Pila:\n    def apilar(self, x):\n        # TODO: apilar\n\n    def desapilar(self):\n        # TODO\n"
                  "\ndef validar(cadena):\n    # TODO: validar\n    ")
        reparado = tu.reparar_cuerpos_vacios(codigo)
        compile(reparado, "x", "exec")
        self.assertEqual(reparado.count("pass"), 3)
        self.assertIn("# TODO: apilar\n        pass", reparado)
        self.assertEqual(tu.reparar_cuerpos_vacios("def f(:\n  pass"), "def f(:\n  pass")   # otros errores no se tocan

    def test_limpiar_codigo(self):
        fence_py = "```python\ndef foo():\n    return 42\n```"
        self.assertEqual(tu.limpiar_codigo(fence_py, "python"), "def foo():\n    return 42")

        fence_cpp = "```cpp\nint foo() { return 42; }\n```"
        self.assertEqual(tu.limpiar_codigo(fence_cpp, "cpp"), "int foo() { return 42; }")

        barras_py = "// Comentario de C++\ndef foo():\n    // TODO: implement\n    return 0"
        limpio = tu.limpiar_codigo(barras_py, "python")
        self.assertIn("# Comentario de C++", limpio)
        self.assertIn("    # TODO: implement", limpio)
        self.assertNotIn("//", limpio)

    def test_repara_cuerpos_vacios_con_fences_y_barras(self):
        codigo = "```python\nclass Test:\n    def metodo(self):\n        // TODO: por hacer\n```"
        reparado = tu.reparar_cuerpos_vacios(codigo)
        compile(reparado, "test.py", "exec")
        self.assertIn("pass", reparado)
        self.assertNotIn("```", reparado)
        self.assertNotIn("//", reparado)

    def test_repara_cuerpos_vacios_final_de_archivo_y_def_consecutivos(self):
        c1 = "def f():"
        r1 = tu.reparar_cuerpos_vacios(c1)
        compile(r1, "c1.py", "exec")
        self.assertIn("pass", r1)

        c2 = "def a():\ndef b():\n    pass"
        r2 = tu.reparar_cuerpos_vacios(c2)
        compile(r2, "c2.py", "exec")
        self.assertEqual(r2.count("pass"), 2)

    def test_crear_repara_referencia_y_fences(self):
        # Desafío con fences en paginas y un cuerpo vacío sin pass en referencia
        ref_con_stub = PILA["contenido"] + "\n\ndef helper():\n    # TODO: stub sin pass\n"
        desafio_con_fences = desafio_json(
            paginas=[{"nombre": "pila.py", "descripcion": "La pila", "contenido": f"```python\n{PILA_VACIA['contenido']}\n```"}],
            referencia=[{"nombre": "pila.py", "contenido": f"```python\n{ref_con_stub}\n```"}],
            pruebas=[f"```python\n{p}\n```" for p in ASSERTS]
        )
        ai = ModeloFalso([desafio_con_fences])
        d = tu.crear(ai, RUNNER, "m", "pilas", intentos=1)
        self.assertEqual(len(d["intentos_creacion"]), 1)
        self.assertTrue(d["intentos_creacion"][0]["valido"])
        self.assertNotIn("```", d["paginas"][0]["contenido"])
        # Verificar que la referencia se reparó y compila
        ref_reparada = d["privado"]["referencia"][0]["contenido"]
        self.assertNotIn("```", ref_reparada)
        self.assertIn("pass", ref_reparada)
        compile(ref_reparada, "pila.py", "exec")

    def test_detecta_pruebas_con_error_sintaxis(self):
        pruebas_malas = ["from pila import Pila", "assert (1 == "]
        error = tu._pruebas_sin_compilar(pruebas_malas, "python")
        self.assertIsNotNone(error)
        self.assertIn("prueba 2", error)

        pruebas_buenas = ["from pila import Pila", "assert 1 == 1"]
        self.assertIsNone(tu._pruebas_sin_compilar(pruebas_buenas, "python"))

    def test_rechaza_pagina_que_ya_trae_la_solucion(self):
        resuelta = desafio_json(paginas=[{"nombre": "pila.py", "contenido": PILA["contenido"]}, {"nombre": "extra.py", "contenido": "def f():\n    pass\n"}],
                                referencia=[{"nombre": "pila.py", "contenido": PILA["contenido"]}, {"nombre": "extra.py", "contenido": "def f():\n    return 1\n"}],
                                pruebas=ASSERTS + ["from extra import f\nassert f() == 1"])
        ai = ModeloFalso([resuelta, desafio_json()])
        d = tu.crear(ai, RUNNER, "m", "pilas", intentos=2)
        self.assertIn("ya trae la solución", d["intentos_creacion"][0]["motivo"])
        self.assertIn("pila.py", ai.prompts[1][0])

    def test_caja_de_razonamiento_sin_codigo(self):
        texto = ("## 1. Qué me piden\n*¿Qué entra?*\nUna lista.\n\n## 2. Ejemplos a mano y casos límite\nVacía.\n"
                 "## 3. Descomponer el problema\nPartes.\n## 4. Qué estrategia usar y por qué\nDos punteros.\n"
                 "```python\ndef resolver(lista):\n    return sorted(lista)\n```\n"
                 "## 5. El algoritmo paso a paso\n1. Ordenar.\n```\nentrada → salida\n```\n## 6. Cómo comprobarlo y cuánto cuesta\nO(n log n).")
        pasos = tu.separar_pasos(texto)
        self.assertEqual([p["titulo"] for p in pasos], tu.PASOS)
        self.assertNotIn("def resolver", pasos[3]["contenido"])
        self.assertIn("no da la solución", pasos[3]["contenido"])
        self.assertIn("entrada → salida", pasos[4]["contenido"])  # un esquema que no es código se queda
        self.assertEqual(len(tu.separar_pasos("Texto sin secciones")), 1)
        self.assertEqual(tu.separar_pasos(""), [])

    def test_flujo_emite_texto_sin_pensamiento(self):
        # El doble parte el texto en trozos de 7 caracteres: las etiquetas llegan partidas
        ai = ModeloFalso(["<think>pienso mucho</think>Hola alumno"])
        gen = tu.razonamiento(ai, "m", {"titulo": "T", "enunciado": "E", "paginas": [PILA_VACIA]})
        eventos = []
        try:
            while True:
                eventos.append(next(gen))
        except StopIteration as fin:
            pasos = fin.value
        self.assertIn("Hola alumno", "".join(e.get("delta", "") for e in eventos))
        self.assertNotIn("think", "".join(e.get("delta", "") for e in eventos))
        self.assertEqual(pasos[0]["contenido"], "Hola alumno")
        self.assertNotIn("return self.d.pop", ai.prompts[0][0])  # la caja no ve la solución

    def test_plan_pista_y_chat_no_exponen_la_referencia_como_tal(self):
        d = {"titulo": "Pila", "enunciado": "E", "paginas": [PILA_VACIA], "privado": {"referencia": [PILA]}}
        for gen in (tu.revisar_plan(ModeloFalso(["ok"]), "m", d, "mi plan"),
                    tu.pista(ModeloFalso(["ok"]), "m", d, 2, [PILA_VACIA], {"fallos": [{"nombre": "prueba 1", "mensaje": "falla"}]})):
            list(gen)
        ai = ModeloFalso(["ok"])
        list(tu.pista(ai, "m", d, 9, [PILA_VACIA]))
        self.assertIn("NO revelar", ai.prompts[0][0])
        self.assertIn("Pista concreta", ai.prompts[0][1] + "Pista concreta")
        with self.assertRaises(ErrorDesafio):
            list(tu.revisar_plan(ModeloFalso([]), "m", d, "  "))
        ai = ModeloFalso(["hola"])
        list(tu.chat(ai, "m", [{"rol": "usuario", "texto": "quiero practicar pilas"}]))
        self.assertIn("Alumno: quiero practicar pilas", ai.prompts[0][0])
        self.assertNotIn("return self.d.pop", ai.prompts[0][0])

    def test_palabras_clave(self):
        self.assertEqual(tu.palabras_clave(ModeloFalso(['{"terminos": ["stack", "linked list"]}']), "m", "pila"), ["stack", "linked list"])
        self.assertEqual(tu.palabras_clave(ModeloFalso(["no sé"]), "m", "pila"), [])


if __name__ == "__main__":
    unittest.main()
