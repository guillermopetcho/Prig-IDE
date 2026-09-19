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
    {"id": "senior_avanzado", "nombre": "Nivel Senior: Algoritmos y Sistemas Complejos"},
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
        "etiquetas": ["competitiva", "geometria", "grafos", "algebra", "c++", "senior"],
        "ruta_ejercicios": "src",
        "licencia": "CC BY-SA 4.0",
        "estrellas_aprox": "7k",
        "dificultad": "avanzado a senior"
    },
    {
        "ref": "kth-competitive-programming/kactl",
        "nombre": "KTH Algorithm Competition Template Library (KACTL)",
        "descripcion": "Librería ultracompacta y testeada de algoritmos en C++ para ICPC y concursos de programación.",
        "lenguajes": ["cpp"],
        "categoria": "competitiva",
        "etiquetas": ["icpc", "competitiva", "c++", "algoritmos-optimizados", "senior"],
        "ruta_ejercicios": "content",
        "licencia": "CC0",
        "estrellas_aprox": "3.5k",
        "dificultad": "avanzado a senior"
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
    },
    {
        "ref": "atcoder/ac-library",
        "nombre": "AtCoder Library (ACL) en C++",
        "descripcion": "Biblioteca oficial de AtCoder para programación competitiva y algoritmia de élite: Segment Trees con Lazy Propagation, Fenwick Trees, DSU, Dinic Max Flow, Min-Cost Flow, 2-SAT, SCC, NTT Convolution y Suffix Array.",
        "lenguajes": ["cpp"],
        "categoria": "senior_avanzado",
        "etiquetas": ["atcoder", "senior", "segment-tree", "lazy-propagation", "fenwick", "dsu", "max-flow", "dinic", "min-cost-flow", "2-sat", "scc", "ntt", "c++20"],
        "ruta_ejercicios": "atcoder",
        "licencia": "CC0",
        "estrellas_aprox": "4.5k",
        "dificultad": "senior a experto"
    },
    {
        "ref": "cheran-senthil/PyRival",
        "nombre": "PyRival: Estructuras y Algoritmos Avanzados en Python",
        "descripcion": "La colección más completa de estructuras de datos no triviales y algoritmos de alta velocidad para Python: Segment Trees, Fenwick, Treap, DSU, Dinic, LCA, Hopcroft-Karp, NTT, Suffix Automaton y Convex Hull.",
        "lenguajes": ["python"],
        "categoria": "senior_avanzado",
        "etiquetas": ["pyrival", "senior", "segment-tree", "fenwick", "treap", "dsu", "dinic", "lca", "matching", "ntt", "suffix-automaton", "geometria"],
        "ruta_ejercicios": "pyrival",
        "licencia": "Apache-2.0",
        "estrellas_aprox": "3k",
        "dificultad": "senior"
    },
    {
        "ref": "destinationunknown/CSES",
        "nombre": "CSES Problem Set Solutions (Python & C++)",
        "descripcion": "Soluciones comentadas en Python3 y C++ al CSES Problem Set: Range Queries (Segment Tree, Fenwick), Tree Algorithms, Dynamic Programming avanzada, Graph Algorithms, Mathematics y String Algorithms.",
        "lenguajes": ["python", "cpp"],
        "categoria": "senior_avanzado",
        "etiquetas": ["cses", "senior", "range-queries", "segment-tree", "arboles", "dp-avanzado", "grafos", "geometria"],
        "ruta_ejercicios": "src",
        "licencia": "MIT",
        "estrellas_aprox": "1k",
        "dificultad": "senior"
    },
    {
        "ref": "Jonathan-Uy/CSES-Solutions",
        "nombre": "CSES Master Solutions (C++)",
        "descripcion": "Más de 300 soluciones aceptadas en C++ cubriendo todo el espectro de CSES: Heavy-Light Decomposition (HLD), Centroid Decomposition, Min-Cost Flow, 2-SAT, Geometry y FFT.",
        "lenguajes": ["cpp"],
        "categoria": "senior_avanzado",
        "etiquetas": ["cses", "senior", "hld", "centroid-decomposition", "flujos", "2-sat", "fft", "c++20", "experto"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "1.2k",
        "dificultad": "senior a experto"
    },
    {
        "ref": "jaehyunp/stanfordacm",
        "nombre": "Stanford ACM-ICPC Team Notebook",
        "descripcion": "Cuaderno oficial de algoritmos de Stanford University para ACM-ICPC: flujos de redes (Dinic, Push-Relabel, MCMF), geometría computacional (Convex Hull, KD-Tree), matching bipolar y FFT en C++.",
        "lenguajes": ["cpp"],
        "categoria": "senior_avanzado",
        "etiquetas": ["stanford", "icpc", "senior", "flujos", "dinic", "mcmf", "geometria", "matching", "fft"],
        "ruta_ejercicios": "code",
        "licencia": "MIT",
        "estrellas_aprox": "3.8k",
        "dificultad": "senior a experto"
    },
    {
        "ref": "jilljenn/tryalgo",
        "nombre": "TryAlgo: Algoritmos y Estructuras Avanzadas en Python",
        "descripcion": "Librería de algoritmos y estructuras complejas en Python para concursos y entrevistas Senior: Tarjan SCC, 2-SAT, Hopcroft-Karp, Edmonds-Karp, Bellman-Ford, Fenwick Trees y optimizaciones DP.",
        "lenguajes": ["python"],
        "categoria": "senior_avanzado",
        "etiquetas": ["python", "senior", "tarjan", "scc", "2-sat", "matching", "fenwick", "grafos"],
        "ruta_ejercicios": "tryalgo",
        "licencia": "MIT",
        "estrellas_aprox": "1.5k",
        "dificultad": "avanzado a senior"
    },
    {
        "ref": "djeada/Algorithms-And-Data-Structures",
        "nombre": "Algorithms & Data Structures (C++ & Python)",
        "descripcion": "Implementación modular y desacoplada de estructuras y algoritmos en C++ y Python con pruebas unitarias: árboles binarios balanceados, grafos dirigidos, backtracking y optimización de complejidad.",
        "lenguajes": ["python", "cpp"],
        "categoria": "senior_avanzado",
        "etiquetas": ["estructuras-de-datos", "grafos", "arboles", "dp", "c++", "python", "senior", "tdd"],
        "ruta_ejercicios": "src",
        "licencia": "MIT",
        "estrellas_aprox": "5k",
        "dificultad": "avanzado a senior"
    },
    {
        "ref": "KMORaza/Advanced_Data_Structures_using_Python",
        "nombre": "Advanced Data Structures Suite (Python)",
        "descripcion": "Estructuras de datos complejas en Python: Segment Trees con Lazy Propagation, Fenwick Trees, Treaps, Árboles AVL y Rojo-Negro, Suffix Trees y Fibonacci Heaps.",
        "lenguajes": ["python"],
        "categoria": "senior_avanzado",
        "etiquetas": ["segment-tree", "lazy-propagation", "fenwick", "treap", "rojo-negro", "fibonacci-heap", "senior"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "800",
        "dificultad": "senior"
    },
    {
        "ref": "youngyangyang04/leetcode-master",
        "nombre": "LeetCode Master: Patrones Algorítmicos Complejos",
        "descripcion": "Más de 50k estrellas en GitHub. Desglose sistemático de técnicas avanzadas en C++ y Python: Programación Dinámica (0-1 knapsack, complete knapsack, subsecuencias), Pilas Monótonas, Backtracking y Grafos.",
        "lenguajes": ["python", "cpp"],
        "categoria": "entrevistas",
        "etiquetas": ["patrones", "dp-avanzado", "pila-monotona", "backtracking", "c++", "python", "senior"],
        "ruta_ejercicios": "problems",
        "licencia": "Apache-2.0",
        "estrellas_aprox": "52k",
        "dificultad": "intermedio a senior"
    },
    {
        "ref": "danistefanovic/build-your-own-x",
        "nombre": "Build Your Own X: Ingeniería y Metodologías Complejas",
        "descripcion": "Construye desde cero sistemas reales con metodologías algorítmicas complejas: motores de bases de datos (B-Trees / LSM), sistemas de archivos, compiladores, parsers, motores regex y Git en C++ y Python.",
        "lenguajes": ["python", "cpp"],
        "categoria": "senior_avanzado",
        "etiquetas": ["sistemas", "motores-bd", "b-tree", "lsm-tree", "compiladores", "parsers", "senior", "arquitectura"],
        "ruta_ejercicios": "",
        "licencia": "CC0",
        "estrellas_aprox": "340k",
        "dificultad": "senior a arquitecto"
    },
    {
        "ref": "donnemartin/system-design-primer",
        "nombre": "System Design & Distributed Algorithmic Paradigms",
        "descripcion": "Patrones algorítmicos para escalabilidad y sistemas distribuidos: Consistent Hashing con nodos virtuales, Bloom Filters, cachés LRU/LFU O(1), Rate Limiting (Token Bucket / Leaky Bucket) y sharding.",
        "lenguajes": ["python"],
        "categoria": "senior_avanzado",
        "etiquetas": ["system-design", "consistent-hashing", "bloom-filter", "lru", "token-bucket", "sistemas-distribuidos", "senior"],
        "ruta_ejercicios": "solutions",
        "licencia": "CC BY-SA 4.0",
        "estrellas_aprox": "280k",
        "dificultad": "senior a staff"
    },
    {
        "ref": "neetcode-gh/leetcode",
        "nombre": "NeetCode Practice & Canonical Solutions",
        "descripcion": "Soluciones canónicas del roadmap NeetCode en Python y C++ ordenadas por patrones algorítmicos esenciales: dos punteros, ventana deslizante, pilas, árboles, grafos, DP y bit manipulation.",
        "lenguajes": ["python", "cpp"],
        "categoria": "entrevistas",
        "etiquetas": ["neetcode", "patrones", "algoritmos", "c++", "python", "entrevistas"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "12k",
        "dificultad": "intermedio a avanzado"
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

