"""
Pruebas de desafíos C++: páginas multiarchivo, compilador g++, arnés Catch2,
fuentes de internet (Exercism C++, TheAlgorithms C++, Project Euler C++) y comprobación.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner import CodeRunner
from desafios import ejecucion as ej, fuentes as fu, tutor as tu
from desafios.ejecucion import ErrorDesafio


RUNNER = CodeRunner()

STACK_H = {
    "nombre": "stack.h",
    "contenido": """#ifndef STACK_H
#define STACK_H
#include <vector>
#include <stdexcept>

class Stack {
private:
    std::vector<int> data;
public:
    void push(int x);
    int pop();
    bool empty() const;
    size_t size() const;
};

#endif
"""
}

STACK_CPP = {
    "nombre": "stack.cpp",
    "contenido": """#include "stack.h"

void Stack::push(int x) {
    data.push_back(x);
}

int Stack::pop() {
    if (data.empty()) {
        throw std::runtime_error("Stack is empty");
    }
    int val = data.back();
    data.pop_back();
    return val;
}

bool Stack::empty() const {
    return data.empty();
}

size_t Stack::size() const {
    return data.size();
}
"""
}

STACK_CPP_ROTO = {
    "nombre": "stack.cpp",
    "contenido": """#include "stack.h"

void Stack::push(int x) {
    // vacio a proposito
}

int Stack::pop() {
    return 0; // valor incorrecto
}

bool Stack::empty() const {
    return true;
}

size_t Stack::size() const {
    return 0;
}
"""
}

MAIN_CPP = {
    "nombre": "main.cpp",
    "contenido": """#include <iostream>
#include "stack.h"

int main() {
    Stack s;
    s.push(42);
    s.push(99);
    std::cout << "size: " << s.size() << ", popped: " << s.pop() << std::endl;
    return 0;
}
"""
}


class PruebaPaginasCpp(unittest.TestCase):

    def test_nombres_validos_cpp(self):
        paginas = [
            {"nombre": "main.cpp", "contenido": ""},
            {"nombre": "stack.h", "contenido": ""},
            {"nombre": "queue.hpp", "contenido": ""},
            {"nombre": "helper.cc", "contenido": ""},
            {"nombre": "algo.cxx", "contenido": ""},
            {"nombre": "compat.c", "contenido": ""}
        ]
        validadas = ej.validar_paginas(paginas)
        nombres = [p["nombre"] for p in validadas]
        self.assertEqual(nombres, ["main.cpp", "stack.h", "queue.hpp", "helper.cc", "algo.cxx", "compat.c"])

    def test_nombres_invalidos_cpp(self):
        for malo in ("stack.cppp", "stack.java", "stack.rs", "bad name.cpp", "-stack.cpp"):
            with self.assertRaises(ErrorDesafio, msg=malo):
                ej.validar_paginas([{"nombre": malo, "contenido": ""}])

    def test_compilacion_y_ejecucion_multiarchivo(self):
        r = ej.ejecutar_pagina(RUNNER, [STACK_H, STACK_CPP, MAIN_CPP], "main.cpp")
        self.assertTrue(r["ok"], r)
        self.assertIn("size: 2, popped: 99", r["stdout"])

    def test_error_compilacion_limpia_ruta_temporal(self):
        roto = {"nombre": "syntax_error.cpp", "contenido": "int main() { syntax_error; return 0; }"}
        r = ej.ejecutar_pagina(RUNNER, [roto], "syntax_error.cpp")
        self.assertFalse(r["ok"])
        self.assertIn("Error de compilación", r["stderr"])
        self.assertNotIn("prig_desafio_", r["stderr"])


class PruebaComprobarCpp(unittest.TestCase):

    def test_cpp_asserts_pasa_todas(self):
        desafio = {
            "lenguaje": "cpp",
            "comprobacion": {
                "tipo": "cpp_asserts",
                "includes": ["#include \"stack.h\""],
                "asserts": [
                    "Stack s; s.push(10); assert(s.size() == 1);",
                    "Stack s; s.push(1); s.push(2); assert(s.pop() == 2);",
                    "Stack s; assert(s.empty());"
                ]
            }
        }
        r = ej.comprobar(RUNNER, [STACK_H, STACK_CPP], desafio)
        self.assertTrue(r["aprobado"], r)
        self.assertEqual(r["pasados"], 3)
        self.assertEqual(r["total"], 3)

    def test_cpp_asserts_falla_parcial(self):
        desafio = {
            "lenguaje": "cpp",
            "comprobacion": {
                "tipo": "cpp_asserts",
                "includes": ["#include \"stack.h\""],
                "asserts": [
                    "Stack s; assert(s.empty());",  # este pasa en STACK_CPP_ROTO
                    "Stack s; s.push(10); assert(s.pop() == 10);",  # este falla
                ]
            }
        }
        r = ej.comprobar(RUNNER, [STACK_H, STACK_CPP_ROTO], desafio)
        self.assertFalse(r["aprobado"])
        self.assertEqual(r["pasados"], 1)
        self.assertEqual(r["total"], 2)
        self.assertTrue(r["fallos"])

    def test_cpp_test_catch2_pasa(self):
        catch_test = """#include "test/catch.hpp"
#include "stack.h"

TEST_CASE("Stack operations", "[stack]") {
    Stack s;
    REQUIRE(s.empty());

    SECTION("push and pop") {
        s.push(1);
        s.push(2);
        REQUIRE(s.size() == 2);
        REQUIRE(s.pop() == 2);
        REQUIRE(s.pop() == 1);
        REQUIRE(s.empty());
    }

    SECTION("throws on empty pop") {
        REQUIRE_THROWS(s.pop());
    }
}
"""
        desafio = {
            "lenguaje": "cpp",
            "comprobacion": {
                "tipo": "cpp_test",
                "codigo": catch_test,
                "pruebas": 3
            }
        }
        r = ej.comprobar(RUNNER, [STACK_H, STACK_CPP], desafio)
        self.assertTrue(r["aprobado"], r)
        self.assertGreaterEqual(r["pasados"], 1)

    def test_cpp_test_con_main_de_alumno_no_colisiona(self):
        """Si el alumno tiene un main.cpp en sus páginas, comprobar() no debe fallar con multiple definition of main."""
        catch_test = """#include "test/catch.hpp"
#include "stack.h"

TEST_CASE("Stack size check", "[stack]") {
    Stack s;
    s.push(5);
    REQUIRE(s.size() == 1);
}
"""
        desafio = {
            "lenguaje": "cpp",
            "comprobacion": {
                "tipo": "cpp_test",
                "codigo": catch_test,
                "pruebas": 1
            }
        }
        # MAIN_CPP tiene int main(), y STACK_H + STACK_CPP tienen la clase
        r = ej.comprobar(RUNNER, [STACK_H, STACK_CPP, MAIN_CPP], desafio)
        self.assertTrue(r["aprobado"], r)


class DescargaFalsaCpp:
    def __init__(self):
        self.pedidas = []

    def __call__(self, url, ttl, obligatorio=True):
        self.pedidas.append(url)
        if url.endswith("exercism/cpp/main/config.json"):
            import json
            return json.dumps({
                "exercises": {
                    "practice": [
                        {"slug": "two-fer", "name": "Two Fer", "difficulty": 1, "practices": ["strings", "pointers"]},
                        {"slug": "reverse-string", "name": "Reverse String", "difficulty": 1, "practices": ["strings"]}
                    ]
                }
            })
        if "practice/two-fer/.meta/config.json" in url:
            import json
            return json.dumps({
                "files": {
                    "solution": ["two_fer.h", "two_fer.cpp"],
                    "test": ["two_fer_test.cpp"],
                    "example": [".meta/example.cpp"]
                }
            })
        if "practice/two-fer/.docs/instructions.md" in url:
            return "# Two-fer\nTwo-fer or 2-fer is short for two for one."
        if "practice/two-fer/.docs/instructions.append.md" in url:
            return ""
        if "practice/two-fer/.docs/hints.md" in url:
            return ""
        if "practice/two-fer/.docs/introduction.md" in url:
            return ""
        if "practice/two-fer/two_fer.h" in url:
            return "#ifndef TWO_FER_H\n#define TWO_FER_H\n#include <string>\nnamespace two_fer { std::string two_fer(const std::string& name = \"you\"); }\n#endif\n"
        if "practice/two-fer/two_fer.cpp" in url:
            return "#include \"two_fer.h\"\nnamespace two_fer { std::string two_fer(const std::string& name) { return \"\"; } }\n"
        if "practice/two-fer/two_fer_test.cpp" in url:
            return '#include "test/catch.hpp"\n#include "two_fer.h"\nTEST_CASE("no_name_given") { REQUIRE(two_fer::two_fer() == "One for you, one for me."); }\n'
        if "practice/two-fer/.meta/example.cpp" in url:
            return '#include "two_fer.h"\nnamespace two_fer { std::string two_fer(const std::string& name) { return "One for " + name + ", one for me."; } }\n'
        if url.endswith("TheAlgorithms/C-Plus-Plus/master/DIRECTORY.md"):
            return """## [Search](search)\n\n* [Binary Search](search/binary_search.cpp)\n* [Linear Search](search/linear_search.cpp)\n"""
        if "search/binary_search.cpp" in url:
            return """#include <iostream>\n#include <vector>\n\nint binary_search(const std::vector<int>& arr, int target) {\n    return -1;\n}\n\nint main() {\n    return 0;\n}\n"""
        if "minimal=problems;csv" in url:
            return '1,"Multiples of 3 or 5",1000\n2,"Even Fibonacci numbers",800\n'
        if "minimal=1" in url:
            return "<p>If we list all the natural numbers below 10 that are multiples of 3 or 5, we get 3, 5, 6 and 9. The sum of these multiples is 23.</p>"
        if obligatorio:
            raise ErrorDesafio(f"No existe: {url}")
        return None


class PruebaFuentesCpp(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_cpp_test_")
        self.env = mock.patch.dict(os.environ, {
            "PRIG_DESAFIOS_DIR": self.tmp,
            "PRIG_DESAFIOS_CACHE": os.path.join(self.tmp, "cache")
        })
        self.env.start()
        self.descarga = DescargaFalsaCpp()
        self.parche = mock.patch.object(fu, "descargar", self.descarga)
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exercism_cpp_indice_y_cargar(self):
        ex = fu.ExercismCpp()
        ejercicios = ex.indice()
        self.assertGreaterEqual(len(ejercicios), 2)
        self.assertTrue(any(e["ref"] == "practice/two-fer" for e in ejercicios))
        d = ex.cargar("practice/two-fer")
        self.assertEqual(d["lenguaje"], "cpp")
        self.assertTrue(any(p["nombre"].endswith(".h") for p in d["paginas"]))
        self.assertTrue(any(p["nombre"].endswith(".cpp") for p in d["paginas"]))
        self.assertEqual(d["comprobacion"]["tipo"], "cpp_test")

    def test_thealgorithms_cpp_indice_y_cargar(self):
        algo = fu.TheAlgorithmsCpp()
        items = algo.indice()
        self.assertGreaterEqual(len(items), 2)
        self.assertTrue(any(i["ref"] == "search/binary_search.cpp" for i in items))
        d = algo.cargar("search/binary_search.cpp")
        self.assertEqual(d["lenguaje"], "cpp")
        self.assertEqual(d["comprobacion"]["tipo"], "ninguna")
        self.assertTrue(any(p["nombre"].endswith(".cpp") for p in d["paginas"]))

    def test_project_euler_cpp(self):
        euler = fu.ProjectEuler()
        d = euler.cargar("1", lenguaje="cpp")
        self.assertEqual(d["lenguaje"], "cpp")
        self.assertTrue(d["paginas"][0]["nombre"].endswith(".cpp"))
        self.assertEqual(d["comprobacion"]["tipo"], "ninguna")

    def test_buscar_con_lenguaje_cpp(self):
        resultados = fu.buscar("punteros", lenguaje="cpp")
        self.assertTrue(resultados["resultados"])
        for r in resultados["resultados"]:
            self.assertEqual(r.get("lenguaje"), "cpp")


if __name__ == "__main__":
    unittest.main()
