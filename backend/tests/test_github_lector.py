"""
GitHub: buscar, abrir, leer archivos, explicar con el modelo, guardar, descargar y exportar.

Contra un GitHub falso (tests/github_falso.py). Lo que se protege:

  · los enlaces que pega el usuario (con /tree/…, /blob/…, .git) dan dueño/repo;
  · la búsqueda arma bien la consulta (lenguaje, estrellas, tema) y el límite sin cuenta
    se explica en castellano con cuánto esperar;
  · abrir un repositorio cuesta 3 consultas y la segunda vez ninguna (caché en disco);
  · los binarios y los archivos enormes no se leen;
  · el profesor recibe README, estructura y el código de los archivos clave;
  · las explicaciones se guardan y la de un archivo que cambió deja de valer;
  · la descarga quita la carpeta «repo-rama/» del zip y no escribe fuera;
  · la explicación se exporta a Markdown y el código explicado a PDF.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import github_falso  # noqa: E402
import github_lector as gl  # noqa: E402

URL, _SERVIDOR = github_falso.arrancar()


class ModeloFalso:
    def __init__(self, respuesta="## Qué es\nUna calculadora."):
        self.respuesta = respuesta
        self.prompts = []

    def generate_response(self, prompt, model=None, system_prompt="", options=None, think=None,
                          on_thinking=None, on_token=None, uso=None, on_stats=None):
        self.prompts.append({"prompt": prompt, "sistema": system_prompt})
        for i in range(0, len(self.respuesta), 6):
            yield self.respuesta[i:i + 6]


def consumir(gen):
    try:
        while True:
            next(gen)
    except StopIteration as fin:
        return fin.value


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ws")
        os.makedirs(self.ws)
        self.entorno = mock.patch.dict(os.environ, {"PRIG_GITHUB_DIR": os.path.join(self.tmp, "g"),
                                                    "PRIG_GITHUB_CREDENCIALES": os.path.join(self.tmp, "token.json")})
        self.entorno.start()
        for v in ("GITHUB_TOKEN", "GH_TOKEN"):
            os.environ.pop(v, None)
        self.orig = (gl.API, gl.RAW, gl.CODELOAD)
        github_falso.apuntar(gl, URL)
        gl._cache.clear()
        github_falso.Manejador.peticiones.clear()

    def tearDown(self):
        gl.API, gl.RAW, gl.CODELOAD = self.orig
        self.entorno.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestBuscarYAbrir(Base):
    def test_referencias(self):
        casos = {"https://github.com/ana/calc": "ana/calc", "https://github.com/ana/calc/tree/main/calc": "ana/calc",
                 "github.com/ana/calc/blob/main/README.md": "ana/calc", "git@github.com:ana/calc.git": "ana/calc",
                 "https://github.com/ana/calc.git": "ana/calc", "ana/calc": "ana/calc"}
        for texto, ref in casos.items():
            self.assertEqual(gl.ref_desde(texto), ref, texto)
        for malo in ("", "calc", "https://gitlab.com/x", "a/b/c/d", "../x"):
            with self.assertRaises(gl.ErrorGitHub, msg=malo):
                gl.ref_desde(malo)

    def test_buscar(self):
        r = gl.buscar("calculadora", "Python", "estrellas", estrellas_min=100, tema="ejemplo")
        p = github_falso.Manejador.peticiones[-1]["params"]
        self.assertEqual(p["q"], "calculadora language:Python stars:>=100 topic:ejemplo")
        self.assertEqual((p["sort"], p["order"]), ("stars", "desc"))
        self.assertEqual([x["ref"] for x in r["repos"]], ["ana/calc", "luis/web"])
        self.assertEqual((r["repos"][0]["licencia"], r["repos"][0]["estrellas"]), ("MIT", 1234))
        gl.buscar("otra", orden="relevancia")
        self.assertNotIn("sort", github_falso.Manejador.peticiones[-1]["params"])
        with self.assertRaisesRegex(gl.ErrorGitHub, "Escribe"):
            gl.buscar("  ")

    def test_limite_sin_cuenta(self):
        with self.assertRaisesRegex(gl.ErrorGitHub, r"búsquedas sin cuenta: vuelve a probar en \d+ min.*token"):
            gl.buscar("LIMITE")

    def test_abrir_tres_consultas_y_cache(self):
        info = gl.abrir("https://github.com/ana/calc/tree/main")
        api = [p for p in github_falso.Manejador.peticiones if not p["ruta"].startswith("/raw")]
        self.assertEqual(len(api), 3)
        self.assertEqual((info["ref"], info["rama"], info["readme_ruta"]), ("ana/calc", "main", "README.md"))
        self.assertEqual(info["lenguajes"][0], {"nombre": "Python", "pct": 90.0})
        self.assertEqual(len(info["archivos"]), len(github_falso.ARCHIVOS))       # solo archivos, no carpetas
        self.assertIn("calculadora", info["readme"])
        github_falso.Manejador.peticiones.clear()
        gl.abrir("ana/calc")
        self.assertEqual(github_falso.Manejador.peticiones, [])
        with self.assertRaisesRegex(gl.ErrorGitHub, "no existe"):
            gl.abrir("nadie/nada")

    def test_leer_archivos(self):
        a = gl.leer_archivo("ana/calc", "calc/operaciones.py")
        self.assertEqual((a["lenguaje"], a["lineas"]), ("python", 6))
        self.assertIn("def sumar", a["contenido"])
        self.assertTrue(gl.leer_archivo("ana/calc", "docs/logo.png")["binario"])
        with self.assertRaisesRegex(gl.ErrorGitHub, "no está"):
            gl.leer_archivo("ana/calc", "no/existe.py")
        with mock.patch.object(gl, "MAX_ARCHIVO", 10):
            self.assertTrue(gl.leer_archivo("ana/calc", "calc/cli.py")["grande"])


class TestProfesor(Base):
    def setUp(self):
        super().setUp()
        self.info = gl.abrir("ana/calc")

    def test_contexto_y_archivos_clave(self):
        clave = gl.archivos_clave(self.info)
        self.assertIn("pyproject.toml", clave)
        self.assertIn("calc/cli.py", clave)
        self.assertNotIn("tests/test_operaciones.py", clave)
        self.assertNotIn("docs/logo.png", clave)
        ctx = gl.contexto_repo(self.info)
        for esperado in ("REPOSITORIO: ana/calc", "Python 90.0%", "calc/  (3 archivos)", "README:", "--- calc/cli.py ---", "def sumar"):
            self.assertIn(esperado, ctx)

    def test_explicar_repo_y_archivo(self):
        ai = ModeloFalso()
        self.assertIn("calculadora", consumir(gl.explicar_repo(ai, "qwen", self.info)))
        self.assertIn("Por dónde empezar a leer", ai.prompts[0]["sistema"])
        ai = ModeloFalso("### Qué hace\nSuma y resta.")
        consumir(gl.explicar_archivo(ai, "qwen", self.info, "calc/operaciones.py", "principiante"))
        self.assertIn("ARCHIVO calc/operaciones.py (6 líneas)", ai.prompts[0]["prompt"])
        self.assertIn(gl.NIVELES["principiante"], ai.prompts[0]["sistema"])
        with self.assertRaisesRegex(gl.ErrorGitHub, "binario"):
            consumir(gl.explicar_archivo(ai, "qwen", self.info, "docs/logo.png"))
        ai = ModeloFalso("Porque sí.")
        consumir(gl.preguntar(ai, "qwen", self.info, "calc/cli.py", [{"rol": "usuario", "texto": "¿Qué hace sys.argv?"}]))
        self.assertIn("ARCHIVO ABIERTO calc/cli.py", ai.prompts[0]["prompt"])
        self.assertIn("Alumno: ¿Qué hace sys.argv?", ai.prompts[0]["prompt"])

    def test_explicaciones_guardadas_y_obsoletas(self):
        gl.guardar_explicacion(self.info, None, "", "qwen", "Resumen")
        gl.guardar_explicacion(self.info, "calc/cli.py", "intermedio", "qwen", "Explica cli")
        self.assertEqual(gl.explicacion_guardada(self.info, "calc/cli.py", "intermedio", "qwen"), "Explica cli")
        self.assertIsNone(gl.explicacion_guardada(self.info, "calc/cli.py", "avanzado", "qwen"))
        e = gl.explicadas(self.info)
        self.assertEqual((e["repo"]["texto"], list(e["archivos"])), ("Resumen", ["calc/cli.py"]))
        cambiado = {**self.info, "archivos": [dict(a, sha="f" * 40) if a["ruta"] == "calc/cli.py" else a for a in self.info["archivos"]]}
        self.assertEqual(gl.explicadas(cambiado)["archivos"], {})

    def test_exportar(self):
        with self.assertRaisesRegex(gl.ErrorGitHub, "Todavía no hay"):
            gl.exportar_markdown("ana/calc", self.ws)
        gl.guardar_explicacion(self.info, None, "", "qwen", "## Qué es\nUna calculadora.")
        gl.guardar_explicacion(self.info, "calc/operaciones.py", "intermedio", "qwen", "### Qué hace\n`sumar` y `restar`.")
        m = gl.exportar_markdown("ana/calc", self.ws)
        with open(m["ruta"], encoding="utf-8") as f:
            texto = f.read()
        self.assertEqual(m["relativa"], os.path.join("github_explicaciones", "ana__calc.md"))
        for esperado in ("# ana/calc", "# El repositorio en conjunto", "# `calc/operaciones.py`", "`sumar` y `restar`"):
            self.assertIn(esperado, texto)
        p = gl.exportar_pdf("ana/calc", self.ws)
        from pypdf import PdfReader
        pdf = "\n".join(pg.extract_text() for pg in PdfReader(p["ruta"]).pages)
        for esperado in ("REPOSITORIO DE GITHUB EXPLICADO", "ana/calc", "El repositorio en conjunto", "calc/operaciones.py",
                         "def sumar", "PROFESOR", "restar"):
            self.assertIn(esperado, pdf)


class TestGuardarYDescargar(Base):
    def test_guardados(self):
        gl.guardar("https://github.com/ana/calc", "para practicar")
        g = gl.guardados()
        self.assertEqual((g[0]["ref"], g[0]["nota"], g[0]["estrellas"]), ("ana/calc", "para practicar", 1234))
        gl.guardar("ana/calc")
        self.assertEqual(len(gl.guardados()), 1)
        self.assertEqual(gl.quitar("ANA/calc"), [])

    def test_descargar(self):
        eventos = []
        r = gl.descargar("ana/calc", self.ws, eventos.append)
        self.assertEqual(r["relativa"], os.path.join("github_repos", "calc"))
        self.assertEqual(r["archivos"], len(github_falso.ARCHIVOS))
        self.assertTrue(os.path.isfile(os.path.join(self.ws, "github_repos", "calc", "calc", "operaciones.py")))
        self.assertFalse(os.path.exists(os.path.join(self.ws, "github_repos", "calc-main")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "fuera.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.ws, "fuera.txt")))
        self.assertEqual(eventos[-1]["mensaje"], "Descomprimiendo…")
        self.assertEqual(gl.local("ana/calc", self.ws)["archivos"], len(github_falso.ARCHIVOS))

    def test_token(self):
        self.assertFalse(gl.estado()["con_token"])
        with self.assertRaisesRegex(gl.ErrorGitHub, "no aceptó"):
            gl.guardar_token("malo_token_de_prueba_1234")
        with self.assertRaisesRegex(gl.ErrorGitHub, "completo"):
            gl.guardar_token("corto")
        e = gl.guardar_token("github_pat_bueno_de_prueba_1234567890")
        self.assertTrue(e["con_token"])
        self.assertEqual(os.stat(os.environ["PRIG_GITHUB_CREDENCIALES"]).st_mode & 0o777, 0o600)
        gl.buscar("x")
        self.assertEqual(github_falso.Manejador.peticiones[-1]["auth"], "Bearer github_pat_bueno_de_prueba_1234567890")
        self.assertNotIn("github_pat", str(gl.estado()))
        self.assertFalse(gl.borrar_token()["con_token"])


if __name__ == "__main__":
    unittest.main()
