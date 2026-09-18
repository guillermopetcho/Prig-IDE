"""
Lector de notebooks de Kaggle: buscar, abrir y leer con un profesor.

Sin red: las respuestas de la API de Kaggle se imitan con lo medido contra
www.kaggle.com/api/v1. Lo que se protege:

  · las credenciales se buscan en el orden del cliente oficial y nunca salen en estado();
  · «language=python» no se manda (Kaggle devuelve vacío) y se filtra aquí;
  · los enlaces que pega el usuario (con /notebook, /edit, …) dan la referencia correcta,
    y lo que no es un notebook se rechaza sin tocar la red;
  · el .ipynb se parte en celdas con sus salidas y se guarda una semana;
  · el profesor recibe el esquema, las celdas anteriores y la salida de la celda;
  · lo explicado se guarda (clave por celda, nivel y modelo) y cuenta como leído.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import kaggle_lector as kl  # noqa: E402

IPYNB = {
    "cells": [
        {"cell_type": "markdown", "source": ["# Titanic\n", "Predecir quién sobrevive."]},
        {"cell_type": "code", "source": ["import pandas as pd\n", "df = pd.read_csv('train.csv')"], "outputs": []},
        {"cell_type": "code", "source": "df.head()", "outputs": [
            {"output_type": "execute_result", "data": {"text/plain": ["   PassengerId  Survived\n", "0  1  0"]}}]},
        {"cell_type": "raw", "source": "ignorada"},
        {"cell_type": "code", "source": "df.survived", "outputs": [
            {"output_type": "error", "ename": "AttributeError", "evalue": "no survived"}]},
        {"cell_type": "code", "source": "print('fin')", "outputs": [{"output_type": "stream", "text": ["fin\n"]}]},
    ],
    "metadata": {}, "nbformat": 4, "nbformat_minor": 4,
}

PULL = {
    "metadata": {"ref": "alexisbcook/titanic-tutorial", "title": "Titanic Tutorial", "author": "alexisbcook",
                 "totalVotes": 30000, "currentVersionNumber": 5, "language": "python", "kernelType": "notebook",
                 "competitionDataSources": ["titanic"], "datasetDataSources": [], "kernelDataSources": []},
    "blob": {"source": json.dumps(IPYNB), "language": "python", "kernelType": "notebook"},
}

LISTA = [
    {"ref": "a/uno", "title": "Uno", "author": "a", "totalVotes": 10, "language": "python", "kernelType": "notebook"},
    {"ref": "b/dos", "title": "Dos", "author": "b", "totalVotes": 5, "language": "r", "kernelType": "notebook"},
    {"ref": "c/tres", "title": "Tres", "author": "c", "totalVotes": 1, "language": "python", "kernelType": "script"},
]


class Respuesta:
    def __init__(self, codigo, datos):
        self.status_code = codigo
        self._datos = datos

    def json(self):
        return self._datos


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        entorno = {"HOME": self.home, "PRIG_KAGGLE_DIR": os.path.join(self.tmp, "prig_kaggle"),
                   "PRIG_KAGGLE_CREDENCIALES": os.path.join(self.tmp, "prig_kaggle.json"),
                   "XDG_CONFIG_HOME": os.path.join(self.home, ".config")}
        for v in ("KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY", "KAGGLE_CONFIG_DIR"):
            entorno[v] = ""
        self.entorno = mock.patch.dict(os.environ, entorno)
        self.entorno.start()
        for v in ("KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY", "KAGGLE_CONFIG_DIR"):
            del os.environ[v]
        kl._cache.clear()
        self.llamadas = []

    def tearDown(self):
        self.entorno.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def red(self, respuestas):
        """ Sustituye requests.get: respuestas es {ruta: Respuesta} """
        def get(url, params=None, auth=None, headers=None, timeout=None):
            self.llamadas.append({"url": url, "params": params, "auth": auth, "headers": headers})
            ruta = url.split("/api/v1/")[1]
            return respuestas[ruta]
        return mock.patch.object(kl.requests, "get", side_effect=get)


class TestCredenciales(Base):
    def test_sin_nada_no_conectado(self):
        self.assertFalse(kl.estado()["conectado"])

    def test_kaggle_json_del_cliente_oficial(self):
        os.makedirs(os.path.join(self.home, ".kaggle"))
        with open(os.path.join(self.home, ".kaggle", "kaggle.json"), "w") as f:
            json.dump({"username": "ana", "key": "secreta123"}, f)
        e = kl.estado()
        self.assertTrue(e["conectado"])
        self.assertEqual(e["usuario"], "ana")
        self.assertEqual(e["origen"], "~/.kaggle/kaggle.json")
        self.assertNotIn("secreta123", json.dumps(e))

    def test_token_gana_a_kaggle_json_y_va_como_bearer(self):
        os.makedirs(os.path.join(self.home, ".kaggle"))
        with open(os.path.join(self.home, ".kaggle", "kaggle.json"), "w") as f:
            json.dump({"username": "ana", "key": "secreta123"}, f)
        os.environ["KAGGLE_API_TOKEN"] = "KGAT_tokendeprueba_1234567890"
        c = kl.credenciales()
        self.assertEqual(c["tipo"], "token")
        auth, cab = kl._auth(c)
        self.assertIsNone(auth)
        self.assertEqual(cab["Authorization"], "Bearer KGAT_tokendeprueba_1234567890")
        self.assertNotIn("KGAT", json.dumps(kl.estado()))

    def test_lo_guardado_en_prig_gana_a_todo(self):
        os.environ["KAGGLE_API_TOKEN"] = "KGAT_otro_token_1234567890"
        with open(os.environ["PRIG_KAGGLE_CREDENCIALES"], "w") as f:
            json.dump({"username": "luis", "key": "k"}, f)
        self.assertEqual(kl.estado()["origen"], "Prig")
        self.assertEqual(kl._auth(kl.credenciales())[0], ("luis", "k"))

    def test_guardar_comprueba_con_kaggle_y_deja_permisos_600(self):
        with self.red({"kernels/list": Respuesta(200, [])}):
            e = kl.guardar_credenciales('  {"username": "ana", "key": "abc"}  ')
        self.assertEqual(e["usuario"], "ana")
        self.assertEqual(self.llamadas[0]["auth"], ("ana", "abc"))
        self.assertEqual(os.stat(os.environ["PRIG_KAGGLE_CREDENCIALES"]).st_mode & 0o777, 0o600)
        self.assertEqual(kl.borrar_credenciales()["conectado"], False)

    def test_credenciales_malas_no_se_guardan(self):
        with self.red({"kernels/list": Respuesta(401, {})}):
            with self.assertRaisesRegex(kl.ErrorKaggle, "no aceptó tus credenciales"):
                kl.guardar_credenciales("KGAT_token_que_no_vale_123456")
        self.assertFalse(os.path.exists(os.environ["PRIG_KAGGLE_CREDENCIALES"]))

    def test_textos_que_no_son_credenciales(self):
        for malo, motivo in (("", "Pega"), ("{roto", "no se puede leer"), ('{"username": "a"}', "username"),
                             ("corto", "demasiado corto"), ("un token con espacios dentro", "espacios")):
            with self.assertRaisesRegex(kl.ErrorKaggle, motivo):
                kl.guardar_credenciales(malo)


class TestBuscar(Base):
    def setUp(self):
        super().setUp()
        os.environ["KAGGLE_API_TOKEN"] = "KGAT_tokendeprueba_1234567890"

    def test_sin_cuenta_explica_que_se_puede_abrir_por_enlace(self):
        del os.environ["KAGGLE_API_TOKEN"]
        with self.assertRaisesRegex(kl.ErrorKaggle, "enlace"):
            kl.buscar("titanic")

    def test_no_manda_language_y_filtra_python(self):
        with self.red({"kernels/list": Respuesta(200, LISTA)}):
            r = kl.buscar("titanic", orden="votos", competicion="titanic", por_pagina=3)
        p = self.llamadas[0]["params"]
        self.assertNotIn("language", p)
        self.assertEqual((p["search"], p["sortBy"], p["competition"], p["pageSize"]), ("titanic", "voteCount", "titanic", 3))
        self.assertEqual([n["ref"] for n in r["notebooks"]], ["a/uno", "c/tres"])
        self.assertEqual(r["notebooks"][0]["url"], "https://www.kaggle.com/code/a/uno")
        self.assertTrue(r["hay_mas"])

    def test_relevancia_sin_texto_pasa_a_tendencia_y_se_cachea(self):
        with self.red({"kernels/list": Respuesta(200, LISTA[:1])}):
            kl.buscar("", orden="relevancia")
            r = kl.buscar("", orden="relevancia")
        self.assertEqual(len(self.llamadas), 1)
        self.assertEqual(self.llamadas[0]["params"]["sortBy"], "hotness")
        self.assertFalse(r["hay_mas"])

    def test_errores_de_kaggle_en_castellano(self):
        for codigo, texto in ((429, "limitó"), (500, "500")):
            kl._cache.clear()
            with self.red({"kernels/list": Respuesta(codigo, {})}):
                with self.assertRaisesRegex(kl.ErrorKaggle, texto):
                    kl.buscar("x")


class TestAbrir(Base):
    def test_referencias_desde_enlaces(self):
        casos = {
            "https://www.kaggle.com/code/alexisbcook/titanic-tutorial": "alexisbcook/titanic-tutorial",
            "kaggle.com/code/pmarcelino/comprehensive-data-exploration-with-python/notebook": "pmarcelino/comprehensive-data-exploration-with-python",
            "https://www.kaggle.com/alexisbcook/titanic-tutorial/edit": "alexisbcook/titanic-tutorial",
            "https://www.kaggle.com/kernels/a_b/c-d.v2": "a_b/c-d.v2",
            "alexisbcook/titanic-tutorial": "alexisbcook/titanic-tutorial",
        }
        for texto, ref in casos.items():
            self.assertEqual(kl.ref_desde(texto), ref, texto)
        for malo in ("", "hola", "https://google.com", "a/b/c/d", "../../etc", "a/.."):
            with self.assertRaises(kl.ErrorKaggle, msg=malo):
                kl.ref_desde(malo)

    def test_abrir_sin_cuenta_parte_celdas_y_salidas(self):
        with self.red({"kernels/pull": Respuesta(200, PULL)}):
            nb = kl.abrir("https://www.kaggle.com/code/alexisbcook/titanic-tutorial")
        self.assertIsNone(self.llamadas[0]["auth"])
        self.assertNotIn("Authorization", self.llamadas[0]["headers"])
        self.assertEqual(self.llamadas[0]["params"], {"userName": "alexisbcook", "kernelSlug": "titanic-tutorial"})
        self.assertEqual([c["tipo"] for c in nb["celdas"]], ["markdown", "code", "code", "code", "code"])
        self.assertEqual([c["indice"] for c in nb["celdas"]], [0, 1, 2, 3, 4])
        self.assertEqual(nb["celdas"][1]["fuente"], "import pandas as pd\ndf = pd.read_csv('train.csv')")
        self.assertIn("PassengerId", nb["celdas"][2]["salida"])
        self.assertEqual(nb["celdas"][3]["salida"], "AttributeError: no survived")
        self.assertEqual(nb["celdas"][4]["salida"], "fin\n")
        self.assertEqual(nb["competiciones"], ["titanic"])
        vista = kl.vista(nb)
        self.assertNotIn("ipynb", vista)
        self.assertEqual(vista["lectura"]["leidas"], [])

    def test_se_guarda_y_no_vuelve_a_descargar(self):
        with self.red({"kernels/pull": Respuesta(200, PULL)}):
            kl.abrir("alexisbcook/titanic-tutorial")
            kl.abrir("alexisbcook/titanic-tutorial")
            self.assertEqual(len(self.llamadas), 1)
            kl.abrir("alexisbcook/titanic-tutorial", refrescar=True)
            self.assertEqual(len(self.llamadas), 2)

    def test_script_es_una_sola_celda_y_privado_da_mensaje(self):
        script = {"metadata": {"ref": "a/s", "title": "S", "kernelType": "script"}, "blob": {"source": "print(1)\n"}}
        with self.red({"kernels/pull": Respuesta(200, script)}):
            nb = kl.abrir("a/s")
        self.assertEqual(nb["celdas"], [{"tipo": "code", "fuente": "print(1)\n", "salida": "", "indice": 0}])
        with self.red({"kernels/pull": Respuesta(404, {})}):
            with self.assertRaisesRegex(kl.ErrorKaggle, "no existe"):
                kl.abrir("a/no-existe")

    def test_guardar_en_el_proyecto_es_el_ipynb_original(self):
        ws = os.path.join(self.tmp, "ws")
        os.makedirs(ws)
        with self.red({"kernels/pull": Respuesta(200, PULL)}):
            r = kl.guardar_en_workspace("alexisbcook/titanic-tutorial", ws)
        self.assertEqual(r["relativa"], os.path.join("kaggle_notebooks", "titanic-tutorial.ipynb"))
        with open(r["ruta"]) as f:
            self.assertEqual(json.load(f)["cells"][3]["cell_type"], "raw")
        self.assertIn("titanic", r["aviso"])


class ModeloFalso:
    def __init__(self, respuesta="### Qué hace\nLee el CSV."):
        self.respuesta = respuesta
        self.prompts = []

    def generate_response(self, prompt, model=None, system_prompt="", options=None, think=None,
                          on_thinking=None, on_token=None, uso=None, on_stats=None):
        self.prompts.append({"prompt": prompt, "sistema": system_prompt, "modelo": model, "think": think})
        for i in range(0, len(self.respuesta), 5):
            yield self.respuesta[i:i + 5]


def consumir(gen):
    trozos = []
    try:
        while True:
            trozos.append(next(gen))
    except StopIteration as fin:
        return fin.value, trozos


class TestProfesor(Base):
    def setUp(self):
        super().setUp()
        with self.red({"kernels/pull": Respuesta(200, PULL)}):
            self.nb = kl.abrir("alexisbcook/titanic-tutorial")

    def test_esquema_una_linea_por_celda(self):
        lineas = kl.esquema(self.nb).splitlines()
        self.assertEqual(len(lineas), 5)
        self.assertIn("Titanic", lineas[0])

    def test_explicar_manda_contexto_y_nivel(self):
        ai = ModeloFalso()
        texto, _ = consumir(kl.explicar(ai, "qwen", self.nb, 2, "principiante"))
        self.assertIn("Lee el CSV", texto)
        p = ai.prompts[0]
        self.assertIn("CELDA 2 A EXPLICAR", p["prompt"])
        self.assertIn("pd.read_csv", p["prompt"])            # celda anterior
        self.assertIn("SALIDA GUARDADA", p["prompt"])
        self.assertIn("ESQUEMA", p["prompt"])
        self.assertIn(kl.NIVELES["principiante"], p["sistema"])
        self.assertIn("Paso a paso", p["sistema"])

    def test_markdown_usa_otro_sistema_y_celda_inexistente_falla(self):
        ai = ModeloFalso("Comentario.")
        consumir(kl.explicar(ai, "qwen", self.nb, 0))
        self.assertEqual(ai.prompts[0]["sistema"].split("\n\n")[0], kl.SISTEMA_MARKDOWN.split("\n\n")[0])
        with self.assertRaises(kl.ErrorKaggle):
            consumir(kl.explicar(ai, "qwen", self.nb, 99))

    def test_guia_piensa_y_quita_think(self):
        ai = ModeloFalso("<think>plan secreto</think>## De qué trata\nTitanic.")
        texto, _ = consumir(kl.guia(ai, "qwen", self.nb))
        self.assertNotIn("secreto", texto)
        self.assertIn("De qué trata", texto)

    def test_preguntar_sobre_celda_y_sobre_todo(self):
        ai = ModeloFalso("Porque sí.")
        consumir(kl.preguntar(ai, "qwen", self.nb, 1, [{"rol": "usuario", "texto": "¿Qué es un DataFrame?"}]))
        consumir(kl.preguntar(ai, "qwen", self.nb, None, [{"rol": "usuario", "texto": "¿De qué va?"}]))
        self.assertIn("CELDA 1 A EXPLICAR", ai.prompts[0]["prompt"])
        self.assertIn("Alumno: ¿Qué es un DataFrame?", ai.prompts[0]["prompt"])
        self.assertNotIn("A EXPLICAR", ai.prompts[1]["prompt"])

    def test_explicaciones_guardadas_y_lectura(self):
        kl.guardar_explicacion(self.nb, 1, "intermedio", "qwen", "Explicación 1")
        kl.guardar_explicacion(self.nb, 3, "intermedio", "qwen", "Explicación 3")
        kl.guardar_explicacion(self.nb, None, "", "qwen", "La guía")
        self.assertEqual(kl.explicacion_guardada(self.nb, 1, "intermedio", "qwen"), "Explicación 1")
        self.assertIsNone(kl.explicacion_guardada(self.nb, 1, "avanzado", "qwen"))
        self.assertIsNone(kl.explicacion_guardada(self.nb, 1, "intermedio", "otro"))
        self.assertEqual(kl.explicacion_guardada(self.nb, None, "", "qwen"), "La guía")
        # Si la celda cambia en una versión nueva, la explicación vieja ya no vale
        cambiado = json.loads(json.dumps(self.nb))
        cambiado["celdas"][1]["fuente"] += "\ndf.info()"
        self.assertIsNone(kl.explicacion_guardada(cambiado, 1, "intermedio", "qwen"))

        r = kl.resumen_lecturas()
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["ref"], r[0]["leidas"], r[0]["total"], r[0]["ultima_celda"]),
                         ("alexisbcook/titanic-tutorial", 2, 5, 3))
        self.assertEqual(kl.vista(self.nb)["lectura"]["leidas"], [1, 3])

    def test_el_perfil_cuenta_lo_leido(self):
        import progreso
        from desafios.almacen import Almacen
        kl.marcar_leida(self.nb, 0)
        r = progreso.resumen(Almacen(os.path.join(self.tmp, "desafios")), kaggle=kl)
        act = [a for a in r["actividades"] if a["id"] == "kaggle"][0]
        self.assertEqual((act["hechos"], act["total"]), (1, 5))
        sig = [s for s in r["siguientes"] if s["tipo"] == "kaggle"][0]
        self.assertEqual((sig["ref"], sig["celda"]), ("alexisbcook/titanic-tutorial", 0))
        self.assertEqual(r["kaggle"][0]["leidas"], 1)


if __name__ == "__main__":
    unittest.main()
