"""
Catálogo curado de repositorios de desafíos y algoritmos en GitHub (Python y C++).

Proporciona un registro estructurado de repositorios con licencias abiertas
que contienen ejercicios, algoritmos, retos de entrevistas y proyectos prácticos.
Permite buscarlos, explorar sus archivos y replicarlos como desafíos interactivos
en Prig IDE.
"""

import json
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional

import requests

from .ejecucion import ErrorDesafio


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


CATEGORIAS = [
    {"id": "todos", "nombre": "Todas las categorías"},
    {"id": "algoritmos", "nombre": "Algoritmos y Estructuras de Datos"},
    {"id": "entrevistas", "nombre": "Entrevistas y LeetCode"},
    {"id": "sintaxis", "nombre": "Sintaxis y Conceptos del Lenguaje"},
    {"id": "proyectos", "nombre": "Proyectos y Aplicaciones Reales"},
    {"id": "data_science", "nombre": "Data Science y Computación Numérica"},
    {"id": "competitiva", "nombre": "Programación Competitiva y Matemáticas"},
]


CATALOGO_REPOSITORIOS_GITHUB: List[Dict[str, Any]] = [
    {
        "ref": "exercism/python",
        "nombre": "Exercism (Pista de Python)",
        "descripcion": "140+ ejercicios estructurados con enunciado, código de partida, pruebas automáticas unittest y solución de referencia.",
        "lenguajes": ["python"],
        "categoria": "sintaxis",
        "etiquetas": ["tdd", "conceptos", "practica", "unittest", "exercism"],
        "ruta_ejercicios": "exercises/practice",
        "licencia": "MIT",
        "estrellas_aprox": "3.5k",
        "dificultad": "principiante a avanzado"
    },
    {
        "ref": "exercism/cpp",
        "nombre": "Exercism (Pista de C++)",
        "descripcion": "70+ ejercicios de C++ moderno (C++17/20) con cabeceras .h, implementaciones .cpp y pruebas completas en Catch2.",
        "lenguajes": ["cpp"],
        "categoria": "sintaxis",
        "etiquetas": ["catch2", "c++20", "templates", "stl", "exercism"],
        "ruta_ejercicios": "exercises/practice",
        "licencia": "MIT",
        "estrellas_aprox": "1.8k",
        "dificultad": "principiante a avanzado"
    },
    {
        "ref": "TheAlgorithms/Python",
        "nombre": "TheAlgorithms (Python)",
        "descripcion": "Colección de más de 600 algoritmos clásicos y estructuras de datos (grafos, ordenación, árboles, DP, ML) con doctests.",
        "lenguajes": ["python"],
        "categoria": "algoritmos",
        "etiquetas": ["algoritmos", "estructuras-de-datos", "doctest", "grafos", "ordenacion", "dp"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "190k",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "TheAlgorithms/C-Plus-Plus",
        "nombre": "TheAlgorithms (C++)",
        "descripcion": "Más de 400 algoritmos y estructuras de datos optimizadas en C++ estándar, con pruebas y benchmarks.",
        "lenguajes": ["cpp"],
        "categoria": "algoritmos",
        "etiquetas": ["algoritmos", "c++", "grafos", "arboles", "busqueda", "ordenacion"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "33k",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "donnemartin/interactive-coding-challenges",
        "nombre": "Interactive Coding Challenges",
        "descripcion": "120+ desafíos interactivos de algoritmos y diseño en Python con suites de pruebas unitarias completas y pistas.",
        "lenguajes": ["python"],
        "categoria": "entrevistas",
        "etiquetas": ["entrevistas", "algoritmos", "tdd", "estructuras-de-datos", "unittest"],
        "ruta_ejercicios": "challenges",
        "licencia": "Apache-2.0",
        "estrellas_aprox": "32k",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "kamyu104/LeetCode-Solutions",
        "nombre": "LeetCode Solutions (Python & C++)",
        "descripcion": "Soluciones exhaustivas y de complejidad óptima a problemas de LeetCode implementadas en Python y C++.",
        "lenguajes": ["python", "cpp"],
        "categoria": "entrevistas",
        "etiquetas": ["leetcode", "entrevistas", "algoritmos", "optimizacion", "dos-punteros", "dp"],
        "ruta_ejercicios": "Python",
        "licencia": "Apache-2.0",
        "estrellas_aprox": "13k",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "doocs/leetcode",
        "nombre": "Doocs LeetCode",
        "descripcion": "Catálogo masivo con más de 2500 problemas de algoritmos con explicaciones paso a paso y código en Python y C++.",
        "lenguajes": ["python", "cpp"],
        "categoria": "entrevistas",
        "etiquetas": ["leetcode", "algoritmos", "explicaciones", "patrones", "entrevistas"],
        "ruta_ejercicios": "solution",
        "licencia": "CC BY-SA 4.0",
        "estrellas_aprox": "34k",
        "dificultad": "todos los niveles"
    },
    {
        "ref": "azl397985856/leetcode",
        "nombre": "LeetCode Algorithmic Patterns",
        "descripcion": "Guía sistemática de problemas de algoritmos clasificados por patrones (ventana deslizante, dos punteros, backtracking, grafos).",
        "lenguajes": ["python", "cpp"],
        "categoria": "entrevistas",
        "etiquetas": ["patrones", "algoritmos", "sliding-window", "backtracking", "grafos"],
        "ruta_ejercicios": "problems",
        "licencia": "Apache-2.0",
        "estrellas_aprox": "55k",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "careercup/ctci-python",
        "nombre": "Cracking the Coding Interview (Python)",
        "descripcion": "Implementación en Python con pruebas unitarias de los problemas del libro clásico 'Cracking the Coding Interview'.",
        "lenguajes": ["python"],
        "categoria": "entrevistas",
        "etiquetas": ["ctci", "entrevistas", "estructuras-de-datos", "unittest"],
        "ruta_ejercicios": "chapter_01",
        "licencia": "MIT",
        "estrellas_aprox": "2.5k",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "careercup/ctci-cpp",
        "nombre": "Cracking the Coding Interview (C++)",
        "descripcion": "Implementaciones de los retos de 'Cracking the Coding Interview' en C++ moderno con manejo de punteros y memoria.",
        "lenguajes": ["cpp"],
        "categoria": "entrevistas",
        "etiquetas": ["ctci", "c++", "punteros", "entrevistas", "memoria"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "1.2k",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "trekhleb/learn-python",
        "nombre": "Learn Python Playground",
        "descripcion": "Colección interactiva de retos sobre sintaxis, operadores, estructuras de datos y algoritmos en Python con aserciones.",
        "lenguajes": ["python"],
        "categoria": "sintaxis",
        "etiquetas": ["sintaxis", "poo", "generadores", "decoradores", "asserts"],
        "ruta_ejercicios": "src",
        "licencia": "MIT",
        "estrellas_aprox": "7.5k",
        "dificultad": "principiante a intermedio"
    },
    {
        "ref": "AllAlgorithms/python",
        "nombre": "AllAlgorithms (Python)",
        "descripcion": "Biblioteca de algoritmos estándar implementada de manera limpia y didáctica para aprender los fundamentos.",
        "lenguajes": ["python"],
        "categoria": "algoritmos",
        "etiquetas": ["algoritmos", "didactico", "busqueda", "ordenacion", "recursividad"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "1.5k",
        "dificultad": "principiante a intermedio"
    },
    {
        "ref": "AllAlgorithms/cpp",
        "nombre": "AllAlgorithms (C++)",
        "descripcion": "Algoritmos esenciales y estructuras de datos explicadas e implementadas en C++.",
        "lenguajes": ["cpp"],
        "categoria": "algoritmos",
        "etiquetas": ["algoritmos", "c++", "didactico", "recursividad"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "1.1k",
        "dificultad": "principiante a intermedio"
    },
    {
        "ref": "rougier/numpy-100",
        "nombre": "100 NumPy Exercises",
        "descripcion": "100 ejercicios prácticos de computación vectorial, matrices y operaciones numéricas con NumPy, con soluciones y pistas.",
        "lenguajes": ["python"],
        "categoria": "data_science",
        "etiquetas": ["numpy", "matrices", "data-science", "vectores", "computacion-cientifica"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "11k",
        "dificultad": "principiante a avanzado"
    },
    {
        "ref": "Florinpop17/app-ideas",
        "nombre": "App Ideas Collection",
        "descripcion": "Colección de retos de proyectos de desarrollo organizados en 3 niveles con historias de usuario, requisitos y bonus.",
        "lenguajes": ["python", "cpp"],
        "categoria": "proyectos",
        "etiquetas": ["proyectos", "historias-de-usuario", "software", "retos-practicos"],
        "ruta_ejercicios": "Projects",
        "licencia": "MIT",
        "estrellas_aprox": "78k",
        "dificultad": "todos los niveles"
    },
    {
        "ref": "dabeaz-course/practical-python",
        "nombre": "Practical Python Programming",
        "descripcion": "El prestigioso curso de Python de David Beazley con ejercicios prácticos de análisis de datos, POO y archivos.",
        "lenguajes": ["python"],
        "categoria": "proyectos",
        "etiquetas": ["curso", "practico", "poo", "analisis-de-datos", "beazley"],
        "ruta_ejercicios": "Exercises",
        "licencia": "CC BY-SA 4.0",
        "estrellas_aprox": "8.5k",
        "dificultad": "intermedio"
    },
    {
        "ref": "cp-algorithms/cp-algorithms",
        "nombre": "Competitive Programming Algorithms",
        "descripcion": "Algoritmos avanzados de programación competitiva (geometría, combinatoria, grafos, álgebra) con código en C++.",
        "lenguajes": ["cpp"],
        "categoria": "competitiva",
        "etiquetas": ["competitiva", "geometria", "grafos", "algebra", "c++"],
        "ruta_ejercicios": "src",
        "licencia": "CC BY-SA 4.0",
        "estrellas_aprox": "7k",
        "dificultad": "avanzado"
    },
    {
        "ref": "kth-competitive-programming/kactl",
        "nombre": "KTH Algorithm Competition Template Library (KACTL)",
        "descripcion": "Librería ultracompacta y testeada de algoritmos en C++ para ICPC y concursos de programación.",
        "lenguajes": ["cpp"],
        "categoria": "competitiva",
        "etiquetas": ["icpc", "competitiva", "c++", "algoritmos-optimizados"],
        "ruta_ejercicios": "content",
        "licencia": "CC0",
        "estrellas_aprox": "3.5k",
        "dificultad": "avanzado"
    },
    {
        "ref": "timvisee/advent-of-code-2023",
        "nombre": "Advent of Code Solutions",
        "descripcion": "Puzzles diarios de algoritmia y lógica resueltos con enfoque pedagógico en Python y C++.",
        "lenguajes": ["python", "cpp"],
        "categoria": "competitiva",
        "etiquetas": ["advent-of-code", "puzzles", "logica", "algoritmos"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "500",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "acmeism/RosettaCodeData",
        "nombre": "Rosetta Code Data",
        "descripcion": "Miles de tareas clásicas de programación con soluciones comparadas en Python y C++.",
        "lenguajes": ["python", "cpp"],
        "categoria": "algoritmos",
        "etiquetas": ["rosetta-code", "tareas", "multi-lenguaje", "comparativas"],
        "ruta_ejercicios": "Task",
        "licencia": "GFDL 1.2",
        "estrellas_aprox": "1.3k",
        "dificultad": "todos los niveles"
    }
]


def listar_repositorios(lenguaje: Optional[str] = None, categoria: Optional[str] = None,
                        busqueda: Optional[str] = None) -> List[Dict[str, Any]]:
    """ Filtra el catálogo por lenguaje ('python', 'cpp'), categoría o término de búsqueda """
    res = []
    norm_q = normalizar(busqueda) if busqueda else ""
    for r in CATALOGO_REPOSITORIOS_GITHUB:
        if lenguaje and lenguaje != "todos":
            if lenguaje not in r["lenguajes"]:
                continue
        if categoria and categoria != "todos":
            if r["categoria"] != categoria:
                continue
        if norm_q:
            texto_buscable = normalizar(f"{r['nombre']} {r['ref']} {r['descripcion']} {' '.join(r['etiquetas'])}")
            if not all(term in texto_buscable for term in norm_q.split()):
                continue
        res.append(dict(r))
    return res


def obtener_repositorio(ref: str) -> Optional[Dict[str, Any]]:
    """ Busca un repositorio en el catálogo por su ref 'owner/repo' """
    return next((dict(r) for r in CATALOGO_REPOSITORIOS_GITHUB if r["ref"].lower() == (ref or "").lower()), None)


def listar_ejercicios_repo(ref: str, ruta_sub: str = "", limite: int = 50) -> Dict[str, Any]:
    """ Lista archivos de ejercicios sugeridos en un repositorio de GitHub """
    import github_lector
    info = github_lector.abrir(ref)
    archivos = info.get("archivos") or []
    
    # Filtrar archivos relevantes de código (.py, .cpp, .hpp, .h, .md con ejercicios)
    salida = []
    for a in archivos:
        path = a["ruta"]
        if ruta_sub and not path.startswith(ruta_sub):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext in (".py", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".md"):
            # Excluir tests internos, configs, builds
            if any(part.startswith((".", "test_", "tests_", "CMake")) for part in path.split("/")):
                if not ("challenge" in path.lower() or "exercise" in path.lower() or "problem" in path.lower()):
                    continue
            salida.append({
                "ruta": path,
                "nombre": os.path.basename(path),
                "bytes": a.get("bytes", 0),
                "lenguaje": "python" if ext == ".py" else "cpp" if ext in (".cpp", ".cc", ".cxx", ".h", ".hpp") else "markdown",
                "es_ejercicio": True
            })
        if len(salida) >= limite:
            break

    return {
        "ref": ref,
        "nombre": info.get("nombre", ref),
        "descripcion": info.get("descripcion", ""),
        "archivos": salida
    }
