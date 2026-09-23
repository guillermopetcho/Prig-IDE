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

    def test_categoria_senior_avanzado(self):
        senior = cat.listar_repositorios(categoria="senior_avanzado")
        self.assertGreaterEqual(len(senior), 8)
        self.assertTrue(any(r["ref"] == "atcoder/ac-library" for r in senior))
        self.assertTrue(any(r["ref"] == "cheran-senthil/PyRival" for r in senior))
        self.assertTrue(any(r["ref"] == "destinationunknown/CSES" for r in senior))
        self.assertTrue(any(r["ref"] == "Jonathan-Uy/CSES-Solutions" for r in senior))
        self.assertTrue(any(r["ref"] == "jaehyunp/stanfordacm" for r in senior))
        self.assertTrue(any(r["ref"] == "danistefanovic/build-your-own-x" for r in senior))
        self.assertTrue(any(r["ref"] == "donnemartin/system-design-primer" for r in senior))

    def test_busqueda_estructuras_senior(self):
        res_st = cat.listar_repositorios(busqueda="segment-tree")
        self.assertGreaterEqual(len(res_st), 3)

        res_ch = cat.listar_repositorios(busqueda="consistent-hashing")
        self.assertTrue(any(r["ref"] == "donnemartin/system-design-primer" for r in res_ch))

        res_dinic = cat.listar_repositorios(busqueda="dinic")
        self.assertGreaterEqual(len(res_dinic), 2)

        res_hld = cat.listar_repositorios(busqueda="hld")
        self.assertTrue(any(r["ref"] == "Jonathan-Uy/CSES-Solutions" for r in res_hld))

    def test_categoria_cursos_notebooks(self):
        cursos = cat.listar_repositorios(categoria="cursos_notebooks")
        self.assertGreaterEqual(len(cursos), 5)
        self.assertTrue(any(r["ref"] == "Asabeneh/30-Days-Of-Python" for r in cursos))
        self.assertTrue(any(r["ref"] == "jakevdp/PythonDataScienceHandbook" for r in cursos))
        self.assertTrue(any(r["ref"] == "ageron/handson-ml3" for r in cursos))
        self.assertTrue(any(r["ref"] == "Pierian-Data/Complete-Python-3-Bootcamp" for r in cursos))

        # Verificar que tienen cuadernos y ejercicios destacados
        destacados_jake = cat.listar_ejercicios_repo("jakevdp/PythonDataScienceHandbook")
        self.assertGreaterEqual(len(destacados_jake["archivos"]), 5)
        self.assertTrue(any(a["nombre"].endswith(".ipynb") for a in destacados_jake["archivos"]))

    def test_categoria_cursos_notebooks_cpp(self):
        cursos_cpp = [r for r in cat.listar_repositorios(categoria="cursos_notebooks") if "cpp" in r["lenguajes"]]
        self.assertGreaterEqual(len(cursos_cpp), 4)
        self.assertTrue(any(r["ref"] == "rambasnet/CPP-Fundamentals" for r in cursos_cpp))
        self.assertTrue(any(r["ref"] == "changkun/modern-cpp-tutorial" for r in cursos_cpp))
        self.assertTrue(any(r["ref"] == "PacktPublishing/The-Modern-Cpp-Challenge" for r in cursos_cpp))
        self.assertTrue(any(r["ref"] == "hsf-training/cpluspluscourse" for r in cursos_cpp))

        # Verificar cuadernos Jupyter de C++
        destacados_ram = cat.listar_ejercicios_repo("rambasnet/CPP-Fundamentals")
        self.assertGreaterEqual(len(destacados_ram["archivos"]), 5)
        self.assertTrue(any(a["nombre"].endswith(".ipynb") and a["lenguaje"] == "cpp" for a in destacados_ram["archivos"]))

        # Verificar código de C++ moderno
        destacados_changkun = cat.listar_ejercicios_repo("changkun/modern-cpp-tutorial")
        self.assertGreaterEqual(len(destacados_changkun["archivos"]), 5)
        self.assertTrue(any(a["nombre"].endswith(".cpp") and a["lenguaje"] == "cpp" for a in destacados_changkun["archivos"]))

        # Verificar patrones de diseño GoF y proyectos gráficos
        repo_patrones = cat.obtener_repositorio("JakubVojvoda/design-patterns-cpp")
        self.assertIsNotNone(repo_patrones)
        self.assertIn("cpp", repo_patrones["lenguajes"])

        repo_renderer = cat.obtener_repositorio("ssloy/tinyrenderer")
        self.assertIsNotNone(repo_renderer)
        self.assertIn("cpp", repo_renderer["lenguajes"])

        repo_raytracing = cat.obtener_repositorio("RayTracing/raytracing.github.io")
        self.assertIsNotNone(repo_raytracing)
        self.assertIn("cpp", repo_raytracing["lenguajes"])

    def test_obtener_repositorio(self):
        repo = cat.obtener_repositorio("TheAlgorithms/Python")
        self.assertIsNotNone(repo)
        self.assertEqual(repo["ref"], "TheAlgorithms/Python")
        self.assertEqual(repo["licencia"], "MIT")

        inexistente = cat.obtener_repositorio("usuario/no_existe_12345")
        self.assertIsNone(inexistente)

    def test_todos_los_repos_tienen_destacados(self):
        for repo in cat.CATALOGO_REPOSITORIOS_GITHUB:
            ref = repo["ref"].lower()
            self.assertIn(ref, cat.EJERCICIOS_DESTACADOS_REPO, f"Falta lista destacada para {repo['ref']}")
            self.assertGreater(len(cat.EJERCICIOS_DESTACADOS_REPO[ref]), 0)

    def test_listar_ejercicios_repo_fallback(self):
        # Incluso simulando fallo en github_lector o sin conexión / límite superado
        with mock.patch("github_lector.abrir", side_effect=Exception("API rate limit exceeded")):
            ejercicios_py = cat.listar_ejercicios_repo("exercism/python")
            self.assertEqual(ejercicios_py["ref"], "exercism/python")
            self.assertGreater(len(ejercicios_py["archivos"]), 0)
            self.assertTrue(any(a["lenguaje"] == "python" for a in ejercicios_py["archivos"]))

            ejercicios_cpp = cat.listar_ejercicios_repo("exercism/cpp")
            self.assertEqual(ejercicios_cpp["ref"], "exercism/cpp")
            self.assertGreater(len(ejercicios_cpp["archivos"]), 0)
            self.assertTrue(any(a["lenguaje"] == "cpp" for a in ejercicios_cpp["archivos"]))


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

    def test_replicar_nivel_senior(self):
        respuesta_json = json.dumps({
            "titulo": "Fenwick Tree (Binary Indexed Tree)",
            "enunciado": "Implementa un Fenwick Tree con operaciones sum(i) y add(i, delta) en O(log N).",
            "nivel": "senior",
            "conceptos": ["fenwick-tree", "range-queries", "bit-manipulation"],
            "paginas": [
                {
                    "nombre": "fenwick.py",
                    "descripcion": "Árbol binario indexado",
                    "contenido": "class FenwickTree:\n    def __init__(self, n: int):\n        # TODO: init\n        pass\n    def add(self, i: int, delta: int):\n        # TODO: add\n        pass\n    def query(self, i: int) -> int:\n        # TODO: query\n        return 0\n"
                }
            ],
            "referencia": [
                {
                    "nombre": "fenwick.py",
                    "contenido": "class FenwickTree:\n    def __init__(self, n: int):\n        self.tree = [0] * (n + 1)\n    def add(self, i: int, delta: int):\n        while i < len(self.tree):\n            self.tree[i] += delta\n            i += i & (-i)\n    def query(self, i: int) -> int:\n        s = 0\n        while i > 0:\n            s += self.tree[i]\n            i -= i & (-i)\n        return s\n"
                }
            ],
            "pruebas": [
                "from fenwick import FenwickTree\nft = FenwickTree(5)\nft.add(1, 10)\nft.add(2, 20)\nassert ft.query(2) == 30",
                "from fenwick import FenwickTree\nft = FenwickTree(5)\nft.add(3, 5)\nassert ft.query(3) == 5\nassert ft.query(1) == 0"
            ]
        })

        ai = ModeloFalsoReplicar([respuesta_json])
        d = tu.replicar_desde_github(
            ai=ai,
            runner=RUNNER,
            modelo="test-model",
            ref="cheran-senthil/PyRival",
            ruta="pyrival/data_structures/fenwick.py",
            contenido="class FenwickTree: ...",
            lenguaje="python",
            nivel="senior"
        )

        self.assertEqual(d["titulo"], "Fenwick Tree (Binary Indexed Tree)")
        self.assertEqual(d["nivel"], "senior")
        self.assertEqual(d["lenguaje"], "python")
        self.assertIn("fenwick-tree", d["conceptos"])


class PruebaAnalizarPropuesta(unittest.TestCase):

    def test_analizar_propuesta_vacia_falla(self):
        ai = ModeloFalsoReplicar([""])
        with self.assertRaises(ErrorDesafio):
            list(tu.analizar_propuesta(ai=ai, modelo="test", propuesta="   ", lenguaje="python"))

    def test_analizar_propuesta_python(self):
        respuesta = "## Análisis de la propuesta\nEl algoritmo planteado tiene complejidad O(N log N)."
        ai = ModeloFalsoReplicar([respuesta])
        gen = tu.analizar_propuesta(
            ai=ai,
            modelo="test-model",
            propuesta="Quiero implementar un Segment Tree con Lazy Propagation",
            lenguaje="python",
            nivel="senior"
        )
        eventos = list(gen)
        salida = "".join(ev.get("delta", "") for ev in eventos if ev.get("tipo") == "texto")
        self.assertEqual(salida, respuesta)
        prompt, sys_prompt, _ = ai.prompts[0]
        self.assertIn("Segment Tree", prompt)
        self.assertIn("Python 3", prompt)
        self.assertIn("senior", prompt)
        self.assertIn("especialista en algoritmia", sys_prompt)

    def test_analizar_propuesta_cpp(self):
        respuesta = "## Análisis C++20\nUso de std::span y complejidad O(V + E)."
        ai = ModeloFalsoReplicar([respuesta])
        gen = tu.analizar_propuesta(
            ai=ai,
            modelo="test-model",
            propuesta="Grafo bipartito con BFS usando C++",
            lenguaje="cpp",
            nivel="medio"
        )
        eventos = list(gen)
        salida = "".join(ev.get("delta", "") for ev in eventos if ev.get("tipo") == "texto")
        self.assertEqual(salida, respuesta)
        prompt, sys_prompt, _ = ai.prompts[0]
        self.assertIn("C++20", prompt)
        self.assertIn("especialista en algoritmia", sys_prompt)


if __name__ == "__main__":
    unittest.main()

