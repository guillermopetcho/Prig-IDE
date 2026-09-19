"""
Pruebas del Catálogo de Desafíos de GitHub y del motor de Replicación interactiva.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner import CodeRunner
from desafios import catalogo_github as cat, tutor as tu
from desafios.ejecucion import ErrorDesafio

RUNNER = CodeRunner()


class ModeloFalsoReplicar:
    """ Doble del motor de IA para replicar desafíos de GitHub """
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


class PruebaCatalogoGitHub(unittest.TestCase):

    def test_catalogo_completo(self):
        repos = cat.listar_repositorios()
        self.assertGreaterEqual(len(repos), 15)
        self.assertTrue(any(r["ref"] == "TheAlgorithms/Python" for r in repos))
        self.assertTrue(any(r["ref"] == "TheAlgorithms/C-Plus-Plus" for r in repos))
        self.assertTrue(any(r["ref"] == "donnemartin/interactive-coding-challenges" for r in repos))
        self.assertTrue(any(r["ref"] == "kamyu104/LeetCode-Solutions" for r in repos))

    def test_filtro_por_lenguaje(self):
        py_repos = cat.listar_repositorios(lenguaje="python")
        self.assertTrue(all("python" in r["lenguajes"] for r in py_repos))
        self.assertTrue(any(r["ref"] == "exercism/python" for r in py_repos))
        self.assertFalse(any(r["ref"] == "exercism/cpp" for r in py_repos))

        cpp_repos = cat.listar_repositorios(lenguaje="cpp")
        self.assertTrue(all("cpp" in r["lenguajes"] for r in cpp_repos))
        self.assertTrue(any(r["ref"] == "exercism/cpp" for r in cpp_repos))
        self.assertFalse(any(r["ref"] == "exercism/python" for r in cpp_repos))

    def test_filtro_por_categoria(self):
        entrevistas = cat.listar_repositorios(categoria="entrevistas")
        self.assertTrue(all(r["categoria"] == "entrevistas" for r in entrevistas))
        self.assertTrue(any("leetcode" in r["nombre"].lower() or "interview" in r["nombre"].lower() for r in entrevistas))

    def test_busqueda_por_texto(self):
        res = cat.listar_repositorios(busqueda="numpy")
        self.assertTrue(any(r["ref"] == "rougier/numpy-100" for r in res))

        res_ctci = cat.listar_repositorios(busqueda="cracking")
        self.assertGreaterEqual(len(res_ctci), 1)

    def test_obtener_repositorio(self):
        repo = cat.obtener_repositorio("TheAlgorithms/Python")
        self.assertIsNotNone(repo)
        self.assertEqual(repo["ref"], "TheAlgorithms/Python")
        self.assertEqual(repo["licencia"], "MIT")

        inexistente = cat.obtener_repositorio("usuario/no_existe_12345")
        self.assertIsNone(inexistente)


class PruebaReplicacionGitHub(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_rep_test_")
        self.env = mock.patch.dict(os.environ, {
            "PRIG_DESAFIOS_DIR": self.tmp,
            "PRIG_DESAFIOS_CACHE": os.path.join(self.tmp, "cache")
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_replicar_desde_github_python(self):
        respuesta_json = json.dumps({
            "titulo": "Caracteres únicos",
            "enunciado": "Determina si una cadena tiene todos los caracteres únicos.\n\nEjemplo: 'abc' -> True, 'aab' -> False.",
            "nivel": "principiante",
            "conceptos": ["strings", "sets"],
            "paginas": [
                {
                    "nombre": "unicos.py",
                    "descripcion": "Verificación de unicidad",
                    "contenido": "def son_unicos(cadena: str) -> bool:\n    # TODO: implementar\n    pass\n"
                }
            ],
            "referencia": [
                {
                    "nombre": "unicos.py",
                    "contenido": "def son_unicos(cadena: str) -> bool:\n    return len(set(cadena)) == len(cadena)\n"
                }
            ],
            "pruebas": [
                "from unicos import son_unicos\nassert son_unicos('abc') is True",
                "from unicos import son_unicos\nassert son_unicos('aab') is False",
                "from unicos import son_unicos\nassert son_unicos('') is True"
            ]
        })

        ai = ModeloFalsoReplicar([respuesta_json])
        d = tu.replicar_desde_github(
            ai=ai,
            runner=RUNNER,
            modelo="test-model",
            ref="donnemartin/interactive-coding-challenges",
            ruta="challenges/unique_chars.py",
            contenido="class UniqueChars: ...",
            lenguaje="python"
        )

        self.assertEqual(d["titulo"], "Caracteres únicos")
        self.assertEqual(d["lenguaje"], "python")
        self.assertEqual(len(d["paginas"]), 1)
        self.assertEqual(d["paginas"][0]["nombre"], "unicos.py")
        self.assertEqual(d["comprobacion"]["tipo"], "asserts")
        self.assertGreaterEqual(d["comprobacion"]["pruebas"], 2)
        self.assertEqual(d["origen"]["tipo"], "github")
        self.assertIn("donnemartin", d["origen"]["ref"])

    def test_replicar_desde_github_cpp(self):
        respuesta_json = json.dumps({
            "titulo": "Suma de dos números en C++",
            "enunciado": "Implementa una función suma(a, b) que devuelva la suma de dos enteros.",
            "nivel": "principiante",
            "conceptos": ["funciones", "c++"],
            "paginas": [
                {
                    "nombre": "suma.h",
                    "descripcion": "Cabecera de suma",
                    "contenido": "#ifndef SUMA_H\n#define SUMA_H\nint suma(int a, int b);\n#endif\n"
                },
                {
                    "nombre": "suma.cpp",
                    "descripcion": "Implementación de suma",
                    "contenido": '#include "suma.h"\nint suma(int a, int b) {\n    // TODO: implementar\n    return 0;\n}\n'
                }
            ],
            "referencia": [
                {
                    "nombre": "suma.h",
                    "contenido": "#ifndef SUMA_H\n#define SUMA_H\nint suma(int a, int b);\n#endif\n"
                },
                {
                    "nombre": "suma.cpp",
                    "contenido": '#include "suma.h"\nint suma(int a, int b) {\n    return a + b;\n}\n'
                }
            ],
            "pruebas": [
                "REQUIRE(suma(2, 3) == 5);",
                "REQUIRE(suma(-1, 1) == 0);",
                "REQUIRE(suma(0, 0) == 0);"
            ]
        })

        ai = ModeloFalsoReplicar([respuesta_json])
        d = tu.replicar_desde_github(
            ai=ai,
            runner=RUNNER,
            modelo="test-model",
            ref="TheAlgorithms/C-Plus-Plus",
            ruta="math/sum.cpp",
            contenido="int suma(int a, int b) { return a + b; }",
            lenguaje="cpp"
        )

        self.assertEqual(d["titulo"], "Suma de dos números en C++")
        self.assertEqual(d["lenguaje"], "cpp")
        self.assertEqual(len(d["paginas"]), 2)
        self.assertEqual(d["comprobacion"]["tipo"], "cpp_asserts")
        self.assertGreaterEqual(d["comprobacion"]["pruebas"], 2)
        self.assertEqual(d["origen"]["tipo"], "github")


if __name__ == "__main__":
    unittest.main()
