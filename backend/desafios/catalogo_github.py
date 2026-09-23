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
    {"id": "cursos_notebooks", "nombre": "Cursos Completos y Cuadernos (Notebooks)"},
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
    },
    {
        "ref": "Asabeneh/30-Days-Of-Python",
        "nombre": "30 Days of Python Challenge",
        "descripcion": "Curso completo y progresivo de 30 días con explicaciones, docenas de ejemplos y cientos de ejercicios prácticos graduados (Nivel 1, 2 y 3).",
        "lenguajes": ["python"],
        "categoria": "cursos_notebooks",
        "etiquetas": ["curso", "30-days", "principiante", "intermedio", "ejercicios", "poo", "apis", "practica"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "46k",
        "dificultad": "principiante a intermedio"
    },
    {
        "ref": "jakevdp/PythonDataScienceHandbook",
        "nombre": "Python Data Science Handbook",
        "descripcion": "El curso y libro canónico en Jupyter Notebooks para dominar NumPy, manipulación con Pandas, visualización y Machine Learning con Scikit-Learn.",
        "lenguajes": ["python"],
        "categoria": "cursos_notebooks",
        "etiquetas": ["notebooks", "data-science", "numpy", "pandas", "matplotlib", "scikit-learn", "machine-learning"],
        "ruta_ejercicios": "notebooks",
        "licencia": "MIT",
        "estrellas_aprox": "42k",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "ageron/handson-ml3",
        "nombre": "Hands-On Machine Learning (3rd Edition)",
        "descripcion": "Colección completa de Jupyter Notebooks del curso y libro de referencia de ML y Deep Learning con Scikit-Learn, Keras y TensorFlow.",
        "lenguajes": ["python"],
        "categoria": "cursos_notebooks",
        "etiquetas": ["notebooks", "machine-learning", "deep-learning", "scikit-learn", "keras", "tensorflow", "clasificacion"],
        "ruta_ejercicios": "",
        "licencia": "Apache-2.0",
        "estrellas_aprox": "21k",
        "dificultad": "intermedio a avanzado"
    },
    {
        "ref": "Pierian-Data/Complete-Python-3-Bootcamp",
        "nombre": "Complete Python 3 Bootcamp",
        "descripcion": "Cuadernos interactivos del curso de Python más popular de Udemy (Jose Portilla), con apuntes, retos de funciones, POO, tareas y proyectos de hito.",
        "lenguajes": ["python"],
        "categoria": "cursos_notebooks",
        "etiquetas": ["curso", "bootcamp", "notebooks", "ejercicios", "poo", "decoradores", "generadores", "proyectos"],
        "ruta_ejercicios": "",
        "licencia": "MIT",
        "estrellas_aprox": "27k",
        "dificultad": "principiante a intermedio"
    },
    {
        "ref": "zhiwehu/Python-programming-exercises",
        "nombre": "100+ Python Challenging Programming Exercises",
        "descripcion": "Banco clásico de más de 100 ejercicios y problemas de lógica en Python divididos en 3 niveles, con enunciados, pistas y soluciones.",
        "lenguajes": ["python"],
        "categoria": "cursos_notebooks",
        "etiquetas": ["ejercicios", "retos", "practica", "logica", "recursividad", "algoritmos", "poo"],
        "ruta_ejercicios": "exercises",
        "licencia": "MIT",
        "estrellas_aprox": "17k",
        "dificultad": "principiante a avanzado"
    },
    {
        "ref": "gto76/python-cheatsheet",
        "nombre": "Comprehensive Python Cheatsheet",
        "descripcion": "Guía práctica exhaustiva con código de ejemplo ejecutable cubriendo todas las características del lenguaje, estructuras, async, POO y tips avanzados.",
        "lenguajes": ["python"],
        "categoria": "sintaxis",
        "etiquetas": ["cheatsheet", "ejemplos", "referencia", "sintaxis", "asyncio", "decoradores", "context-managers"],
        "ruta_ejercicios": "src",
        "licencia": "MIT",
        "estrellas_aprox": "38k",
        "dificultad": "principiante a avanzado"
    },
    {
        "ref": "AllenDowney/ThinkPython2",
        "nombre": "Think Python 2nd Edition (Green Tea Press)",
        "descripcion": "Libro interactivo universitario para aprender ciencias de la computación y pensamiento algorítmico en Python, con ejercicios de código en cada capítulo.",
        "lenguajes": ["python"],
        "categoria": "cursos_notebooks",
        "etiquetas": ["curso", "computacion", "algoritmos", "pensamiento-computacional", "poo", "recursividad"],
        "ruta_ejercicios": "code",
        "licencia": "CC BY-NC 3.0",
        "estrellas_aprox": "3.5k",
        "dificultad": "principiante a intermedio"
    },
    {
        "ref": "microsoft/c9-python-getting-started",
        "nombre": "Microsoft: Python for Beginners",
        "descripcion": "Material práctico del curso oficial de Microsoft para principiantes en Python, con ejemplos modulares, ejercicios de sintaxis, colecciones y consumo de APIs.",
        "lenguajes": ["python"],
        "categoria": "sintaxis",
        "etiquetas": ["curso", "microsoft", "principiante", "sintaxis", "funciones", "apis", "buenas-practicas"],
        "ruta_ejercicios": "python",
        "licencia": "MIT",
        "estrellas_aprox": "5.5k",
        "dificultad": "principiante"
    }
]


# Colección pre-indexada de ejercicios y archivos clave para los repositorios del catálogo.
# Garantiza que el usuario pueda explorar, aprender y replicar ejercicios al instante sin
# depender del límite estricto de 60 consultas/hora de la API pública de GitHub sin token,
# o incluso trabajando sin conexión a internet.
EJERCICIOS_DESTACADOS_REPO: Dict[str, List[Dict[str, Any]]] = {
    "exercism/python": [
        {"ruta": "exercises/practice/two-fer/two_fer.py", "nombre": "two_fer.py", "bytes": 450, "lenguaje": "python"},
        {"ruta": "exercises/practice/leap/leap.py", "nombre": "leap.py", "bytes": 520, "lenguaje": "python"},
        {"ruta": "exercises/practice/isogram/isogram.py", "nombre": "isogram.py", "bytes": 610, "lenguaje": "python"},
        {"ruta": "exercises/practice/raindrops/raindrops.py", "nombre": "raindrops.py", "bytes": 780, "lenguaje": "python"},
        {"ruta": "exercises/practice/word-count/word_count.py", "nombre": "word_count.py", "bytes": 890, "lenguaje": "python"},
        {"ruta": "exercises/practice/hamming/hamming.py", "nombre": "hamming.py", "bytes": 670, "lenguaje": "python"},
        {"ruta": "exercises/practice/binary-search/binary_search.py", "nombre": "binary_search.py", "bytes": 940, "lenguaje": "python"},
        {"ruta": "exercises/practice/circular-buffer/circular_buffer.py", "nombre": "circular_buffer.py", "bytes": 1420, "lenguaje": "python"},
        {"ruta": "exercises/practice/matching-brackets/matching_brackets.py", "nombre": "matching_brackets.py", "bytes": 830, "lenguaje": "python"},
        {"ruta": "exercises/practice/matrix/matrix.py", "nombre": "matrix.py", "bytes": 980, "lenguaje": "python"},
    ],
    "exercism/cpp": [
        {"ruta": "exercises/practice/hello-world/hello_world.cpp", "nombre": "hello_world.cpp", "bytes": 410, "lenguaje": "cpp"},
        {"ruta": "exercises/practice/two-fer/two_fer.cpp", "nombre": "two_fer.cpp", "bytes": 560, "lenguaje": "cpp"},
        {"ruta": "exercises/practice/leap/leap.cpp", "nombre": "leap.cpp", "bytes": 490, "lenguaje": "cpp"},
        {"ruta": "exercises/practice/reverse-string/reverse_string.cpp", "nombre": "reverse_string.cpp", "bytes": 620, "lenguaje": "cpp"},
        {"ruta": "exercises/practice/space-age/space_age.cpp", "nombre": "space_age.cpp", "bytes": 1280, "lenguaje": "cpp"},
        {"ruta": "exercises/practice/triangle/triangle.cpp", "nombre": "triangle.cpp", "bytes": 840, "lenguaje": "cpp"},
        {"ruta": "exercises/practice/grains/grains.cpp", "nombre": "grains.cpp", "bytes": 710, "lenguaje": "cpp"},
        {"ruta": "exercises/practice/circular-buffer/circular_buffer.cpp", "nombre": "circular_buffer.cpp", "bytes": 2100, "lenguaje": "cpp"},
        {"ruta": "exercises/practice/queen-attack/queen_attack.cpp", "nombre": "queen_attack.cpp", "bytes": 1150, "lenguaje": "cpp"},
        {"ruta": "exercises/practice/robot-simulator/robot_simulator.cpp", "nombre": "robot_simulator.cpp", "bytes": 1490, "lenguaje": "cpp"},
    ],
    "thealgorithms/python": [
        {"ruta": "searches/binary_search.py", "nombre": "binary_search.py", "bytes": 2400, "lenguaje": "python"},
        {"ruta": "searches/quick_select.py", "nombre": "quick_select.py", "bytes": 1800, "lenguaje": "python"},
        {"ruta": "sorts/quick_sort.py", "nombre": "quick_sort.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "sorts/merge_sort.py", "nombre": "merge_sort.py", "bytes": 1950, "lenguaje": "python"},
        {"ruta": "graphs/dijkstra.py", "nombre": "dijkstra.py", "bytes": 3200, "lenguaje": "python"},
        {"ruta": "graphs/breadth_first_search.py", "nombre": "breadth_first_search.py", "bytes": 2600, "lenguaje": "python"},
        {"ruta": "dynamic_programming/knapsack.py", "nombre": "knapsack.py", "bytes": 2800, "lenguaje": "python"},
        {"ruta": "dynamic_programming/longest_common_subsequence.py", "nombre": "longest_common_subsequence.py", "bytes": 2300, "lenguaje": "python"},
        {"ruta": "data_structures/binary_tree/binary_search_tree.py", "nombre": "binary_search_tree.py", "bytes": 4500, "lenguaje": "python"},
        {"ruta": "data_structures/heap/heap.py", "nombre": "heap.py", "bytes": 3100, "lenguaje": "python"},
    ],
    "thealgorithms/c-plus-plus": [
        {"ruta": "search/binary_search.cpp", "nombre": "binary_search.cpp", "bytes": 2200, "lenguaje": "cpp"},
        {"ruta": "sorting/quick_sort.cpp", "nombre": "quick_sort.cpp", "bytes": 2400, "lenguaje": "cpp"},
        {"ruta": "sorting/merge_sort.cpp", "nombre": "merge_sort.cpp", "bytes": 2600, "lenguaje": "cpp"},
        {"ruta": "graph/dijkstra.cpp", "nombre": "dijkstra.cpp", "bytes": 3800, "lenguaje": "cpp"},
        {"ruta": "graph/breadth_first_search.cpp", "nombre": "breadth_first_search.cpp", "bytes": 2900, "lenguaje": "cpp"},
        {"ruta": "dynamic_programming/01_knapsack.cpp", "nombre": "01_knapsack.cpp", "bytes": 3100, "lenguaje": "cpp"},
        {"ruta": "data_structures/binary_search_tree.cpp", "nombre": "binary_search_tree.cpp", "bytes": 4200, "lenguaje": "cpp"},
        {"ruta": "data_structures/trie.cpp", "nombre": "trie.cpp", "bytes": 3500, "lenguaje": "cpp"},
    ],
    "donnemartin/interactive-coding-challenges": [
        {"ruta": "arrays_strings/unique_chars/unique_chars.py", "nombre": "unique_chars.py", "bytes": 1800, "lenguaje": "python"},
        {"ruta": "arrays_strings/permutation/permutation.py", "nombre": "permutation.py", "bytes": 1950, "lenguaje": "python"},
        {"ruta": "linked_lists/remove_duplicates/remove_duplicates.py", "nombre": "remove_duplicates.py", "bytes": 2200, "lenguaje": "python"},
        {"ruta": "trees/bst_validate/bst_validate.py", "nombre": "bst_validate.py", "bytes": 2600, "lenguaje": "python"},
        {"ruta": "graphs/graph_bfs/graph_bfs.py", "nombre": "graph_bfs.py", "bytes": 2900, "lenguaje": "python"},
        {"ruta": "sorting_searching/quick_sort/quick_sort.py", "nombre": "quick_sort.py", "bytes": 2300, "lenguaje": "python"},
        {"ruta": "recursion_dynamic/fibonacci/fibonacci.py", "nombre": "fibonacci.py", "bytes": 1600, "lenguaje": "python"},
    ],
    "kamyu104/leetcode-solutions": [
        {"ruta": "Python/two-sum.py", "nombre": "two-sum.py", "bytes": 1400, "lenguaje": "python"},
        {"ruta": "Python/add-two-numbers.py", "nombre": "add-two-numbers.py", "bytes": 1900, "lenguaje": "python"},
        {"ruta": "Python/longest-substring-without-repeating-characters.py", "nombre": "longest-substring-without-repeating-characters.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "Python/median-of-two-sorted-arrays.py", "nombre": "median-of-two-sorted-arrays.py", "bytes": 2800, "lenguaje": "python"},
        {"ruta": "Python/trapping-rain-water.py", "nombre": "trapping-rain-water.py", "bytes": 2200, "lenguaje": "python"},
        {"ruta": "C++/two-sum.cpp", "nombre": "two-sum.cpp", "bytes": 1600, "lenguaje": "cpp"},
        {"ruta": "C++/add-two-numbers.cpp", "nombre": "add-two-numbers.cpp", "bytes": 2100, "lenguaje": "cpp"},
        {"ruta": "C++/longest-substring-without-repeating-characters.cpp", "nombre": "longest-substring-without-repeating-characters.cpp", "bytes": 2300, "lenguaje": "cpp"},
        {"ruta": "C++/trapping-rain-water.cpp", "nombre": "trapping-rain-water.cpp", "bytes": 2500, "lenguaje": "cpp"},
    ],
    "doocs/leetcode": [
        {"ruta": "solution/0000-0099/0001.Two Sum/Solution.py", "nombre": "0001.Two Sum.py", "bytes": 1500, "lenguaje": "python"},
        {"ruta": "solution/0000-0099/0002.Add Two Numbers/Solution.py", "nombre": "0002.Add Two Numbers.py", "bytes": 1800, "lenguaje": "python"},
        {"ruta": "solution/0000-0099/0003.Longest Substring Without Repeating Characters/Solution.py", "nombre": "0003.Longest Substring.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "solution/0000-0099/0001.Two Sum/Solution.cpp", "nombre": "0001.Two Sum.cpp", "bytes": 1700, "lenguaje": "cpp"},
        {"ruta": "solution/0000-0099/0015.3Sum/Solution.cpp", "nombre": "0015.3Sum.cpp", "bytes": 2400, "lenguaje": "cpp"},
        {"ruta": "solution/0000-0099/0042.Trapping Rain Water/Solution.cpp", "nombre": "0042.Trapping Rain Water.cpp", "bytes": 2600, "lenguaje": "cpp"},
    ],
    "azl397985856/leetcode": [
        {"ruta": "problems/1.two-sum.md", "nombre": "1.two-sum.md", "bytes": 3100, "lenguaje": "markdown"},
        {"ruta": "problems/15.3-sum.md", "nombre": "15.3-sum.md", "bytes": 3800, "lenguaje": "markdown"},
        {"ruta": "problems/20.valid-parentheses.md", "nombre": "20.valid-parentheses.md", "bytes": 2900, "lenguaje": "markdown"},
        {"ruta": "problems/42.trapping-rain-water.md", "nombre": "42.trapping-rain-water.md", "bytes": 4500, "lenguaje": "markdown"},
        {"ruta": "problems/146.lru-cache.md", "nombre": "146.lru-cache.md", "bytes": 4200, "lenguaje": "markdown"},
    ],
    "careercup/ctci-python": [
        {"ruta": "chapter_01/p01_is_unique.py", "nombre": "p01_is_unique.py", "bytes": 1400, "lenguaje": "python"},
        {"ruta": "chapter_01/p02_check_permutation.py", "nombre": "p02_check_permutation.py", "bytes": 1600, "lenguaje": "python"},
        {"ruta": "chapter_02/p01_remove_dups.py", "nombre": "p01_remove_dups.py", "bytes": 1800, "lenguaje": "python"},
        {"ruta": "chapter_03/p01_three_in_one.py", "nombre": "p01_three_in_one.py", "bytes": 2200, "lenguaje": "python"},
        {"ruta": "chapter_04/p01_route_between_nodes.py", "nombre": "p01_route_between_nodes.py", "bytes": 2400, "lenguaje": "python"},
        {"ruta": "chapter_08/p01_triple_step.py", "nombre": "p01_triple_step.py", "bytes": 1700, "lenguaje": "python"},
    ],
    "careercup/ctci-cpp": [
        {"ruta": "Chapter 1/1.1 - Is Unique/IsUnique.cpp", "nombre": "IsUnique.cpp", "bytes": 1500, "lenguaje": "cpp"},
        {"ruta": "Chapter 1/1.2 - Check Permutation/CheckPermutation.cpp", "nombre": "CheckPermutation.cpp", "bytes": 1750, "lenguaje": "cpp"},
        {"ruta": "Chapter 2/2.1 - Remove Dups/RemoveDups.cpp", "nombre": "RemoveDups.cpp", "bytes": 1900, "lenguaje": "cpp"},
        {"ruta": "Chapter 4/4.1 - Route Between Nodes/RouteBetweenNodes.cpp", "nombre": "RouteBetweenNodes.cpp", "bytes": 2600, "lenguaje": "cpp"},
        {"ruta": "Chapter 8/8.1 - Triple Step/TripleStep.cpp", "nombre": "TripleStep.cpp", "bytes": 1850, "lenguaje": "cpp"},
    ],
    "trekhleb/learn-python": [
        {"ruta": "src/algorithms/search/binary_search.py", "nombre": "binary_search.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "src/algorithms/sorting/quick_sort.py", "nombre": "quick_sort.py", "bytes": 2400, "lenguaje": "python"},
        {"ruta": "src/algorithms/sorting/merge_sort.py", "nombre": "merge_sort.py", "bytes": 2200, "lenguaje": "python"},
        {"ruta": "src/data_structures/tree/binary_search_tree.py", "nombre": "binary_search_tree.py", "bytes": 3800, "lenguaje": "python"},
        {"ruta": "src/data_structures/queue/queue.py", "nombre": "queue.py", "bytes": 1900, "lenguaje": "python"},
    ],
    "allalgorithms/python": [
        {"ruta": "searches/binary_search.py", "nombre": "binary_search.py", "bytes": 1600, "lenguaje": "python"},
        {"ruta": "sorting/bubble_sort.py", "nombre": "bubble_sort.py", "bytes": 1400, "lenguaje": "python"},
        {"ruta": "sorting/quick_sort.py", "nombre": "quick_sort.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "data_structures/stack.py", "nombre": "stack.py", "bytes": 1800, "lenguaje": "python"},
        {"ruta": "data_structures/queue.py", "nombre": "queue.py", "bytes": 1700, "lenguaje": "python"},
    ],
    "allalgorithms/cpp": [
        {"ruta": "searches/binary_search.cpp", "nombre": "binary_search.cpp", "bytes": 1900, "lenguaje": "cpp"},
        {"ruta": "sorting/bubble_sort.cpp", "nombre": "bubble_sort.cpp", "bytes": 1600, "lenguaje": "cpp"},
        {"ruta": "sorting/quick_sort.cpp", "nombre": "quick_sort.cpp", "bytes": 2300, "lenguaje": "cpp"},
        {"ruta": "data_structures/stack.cpp", "nombre": "stack.cpp", "bytes": 2000, "lenguaje": "cpp"},
        {"ruta": "data_structures/queue.cpp", "nombre": "queue.cpp", "bytes": 1900, "lenguaje": "cpp"},
    ],
    "rougier/numpy-100": [
        {"ruta": "100_Numpy_exercises.md", "nombre": "100_Numpy_exercises.md", "bytes": 18500, "lenguaje": "markdown"},
        {"ruta": "100_Numpy_exercises_with_hint.md", "nombre": "100_Numpy_exercises_with_hint.md", "bytes": 22000, "lenguaje": "markdown"},
        {"ruta": "100_Numpy_exercises_with_solutions.md", "nombre": "100_Numpy_exercises_with_solutions.md", "bytes": 26000, "lenguaje": "markdown"},
    ],
    "florinpop17/app-ideas": [
        {"ruta": "Projects/1-Beginner/Bin2Dec-App.md", "nombre": "Bin2Dec-App.md", "bytes": 2400, "lenguaje": "markdown"},
        {"ruta": "Projects/1-Beginner/Calculator-App.md", "nombre": "Calculator-App.md", "bytes": 3100, "lenguaje": "markdown"},
        {"ruta": "Projects/2-Intermediate/Bit-Masks-App.md", "nombre": "Bit-Masks-App.md", "bytes": 2800, "lenguaje": "markdown"},
        {"ruta": "Projects/2-Intermediate/Markdown-Previewer.md", "nombre": "Markdown-Previewer.md", "bytes": 3400, "lenguaje": "markdown"},
        {"ruta": "Projects/3-Advanced/Boole-Bots-Game.md", "nombre": "Boole-Bots-Game.md", "bytes": 4800, "lenguaje": "markdown"},
    ],
    "dabeaz-course/practical-python": [
        {"ruta": "Work/mortgage.py", "nombre": "mortgage.py", "bytes": 1200, "lenguaje": "python"},
        {"ruta": "Work/bounce.py", "nombre": "bounce.py", "bytes": 950, "lenguaje": "python"},
        {"ruta": "Work/report.py", "nombre": "report.py", "bytes": 2400, "lenguaje": "python"},
        {"ruta": "Work/portfolio.py", "nombre": "portfolio.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "Work/pcost.py", "nombre": "pcost.py", "bytes": 1600, "lenguaje": "python"},
    ],
    "cp-algorithms/cp-algorithms": [
        {"ruta": "src/algebra/binary-exp.md", "nombre": "binary-exp.md", "bytes": 3800, "lenguaje": "markdown"},
        {"ruta": "src/graph/dijkstra.md", "nombre": "dijkstra.md", "bytes": 4900, "lenguaje": "markdown"},
        {"ruta": "src/graph/depth-first-search.md", "nombre": "depth-first-search.md", "bytes": 4100, "lenguaje": "markdown"},
        {"ruta": "src/data_structures/segment_tree.md", "nombre": "segment_tree.md", "bytes": 7500, "lenguaje": "markdown"},
        {"ruta": "src/string/rabin-karp.md", "nombre": "rabin-karp.md", "bytes": 3900, "lenguaje": "markdown"},
    ],
    "kth-competitive-programming/kactl": [
        {"ruta": "content/data-structures/SegmentTree.h", "nombre": "SegmentTree.h", "bytes": 1900, "lenguaje": "cpp"},
        {"ruta": "content/data-structures/FenwickTree.h", "nombre": "FenwickTree.h", "bytes": 1200, "lenguaje": "cpp"},
        {"ruta": "content/graph/Dijkstra.h", "nombre": "Dijkstra.h", "bytes": 1600, "lenguaje": "cpp"},
        {"ruta": "content/graph/Dinic.h", "nombre": "Dinic.h", "bytes": 2500, "lenguaje": "cpp"},
        {"ruta": "content/numerical/FastFourierTransform.h", "nombre": "FastFourierTransform.h", "bytes": 2800, "lenguaje": "cpp"},
    ],
    "timvisee/advent-of-code-2023": [
        {"ruta": "README.md", "nombre": "README.md", "bytes": 3200, "lenguaje": "markdown"},
        {"ruta": "day01/README.md", "nombre": "day01_trebuchet.md", "bytes": 1900, "lenguaje": "markdown"},
        {"ruta": "day02/README.md", "nombre": "day02_cube_conundrum.md", "bytes": 2100, "lenguaje": "markdown"},
        {"ruta": "day03/README.md", "nombre": "day03_gear_ratios.md", "bytes": 2400, "lenguaje": "markdown"},
    ],
    "acmeism/rosettacodedata": [
        {"ruta": "Task/100-doors/Python/100-doors.py", "nombre": "100-doors.py", "bytes": 980, "lenguaje": "python"},
        {"ruta": "Task/100-doors/C++/100-doors.cpp", "nombre": "100-doors.cpp", "bytes": 1200, "lenguaje": "cpp"},
        {"ruta": "Task/Fibonacci-sequence/Python/fibonacci-sequence.py", "nombre": "fibonacci-sequence.py", "bytes": 1400, "lenguaje": "python"},
        {"ruta": "Task/Fibonacci-sequence/C++/fibonacci-sequence.cpp", "nombre": "fibonacci-sequence.cpp", "bytes": 1650, "lenguaje": "cpp"},
        {"ruta": "Task/Quicksort/Python/quicksort.py", "nombre": "quicksort.py", "bytes": 1500, "lenguaje": "python"},
        {"ruta": "Task/Quicksort/C++/quicksort.cpp", "nombre": "quicksort.cpp", "bytes": 1900, "lenguaje": "cpp"},
    ],
    "atcoder/ac-library": [
        {"ruta": "atcoder/dsu.hpp", "nombre": "dsu.hpp", "bytes": 2100, "lenguaje": "cpp"},
        {"ruta": "atcoder/fenwicktree.hpp", "nombre": "fenwicktree.hpp", "bytes": 2400, "lenguaje": "cpp"},
        {"ruta": "atcoder/segtree.hpp", "nombre": "segtree.hpp", "bytes": 3600, "lenguaje": "cpp"},
        {"ruta": "atcoder/lazysegtree.hpp", "nombre": "lazysegtree.hpp", "bytes": 4800, "lenguaje": "cpp"},
        {"ruta": "atcoder/maxflow.hpp", "nombre": "maxflow.hpp", "bytes": 4200, "lenguaje": "cpp"},
        {"ruta": "atcoder/mincostflow.hpp", "nombre": "mincostflow.hpp", "bytes": 5500, "lenguaje": "cpp"},
    ],
    "cheran-senthil/pyrival": [
        {"ruta": "pyrival/data_structures/FenwickTree.py", "nombre": "FenwickTree.py", "bytes": 1600, "lenguaje": "python"},
        {"ruta": "pyrival/data_structures/SegmentTree.py", "nombre": "SegmentTree.py", "bytes": 2900, "lenguaje": "python"},
        {"ruta": "pyrival/data_structures/DisjointSetUnion.py", "nombre": "DisjointSetUnion.py", "bytes": 1750, "lenguaje": "python"},
        {"ruta": "pyrival/graphs/dijkstra.py", "nombre": "dijkstra.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "pyrival/graphs/bellman_ford.py", "nombre": "bellman_ford.py", "bytes": 2300, "lenguaje": "python"},
        {"ruta": "pyrival/algebra/mod_inverse.py", "nombre": "mod_inverse.py", "bytes": 1100, "lenguaje": "python"},
    ],
    "destinationunknown/cses": [
        {"ruta": "introductory_problems/weird_algorithm.cpp", "nombre": "weird_algorithm.cpp", "bytes": 750, "lenguaje": "cpp"},
        {"ruta": "introductory_problems/missing_number.cpp", "nombre": "missing_number.cpp", "bytes": 850, "lenguaje": "cpp"},
        {"ruta": "introductory_problems/repetitions.cpp", "nombre": "repetitions.cpp", "bytes": 920, "lenguaje": "cpp"},
        {"ruta": "sorting_and_searching/distinct_numbers.cpp", "nombre": "distinct_numbers.cpp", "bytes": 980, "lenguaje": "cpp"},
        {"ruta": "dynamic_programming/dice_combinations.cpp", "nombre": "dice_combinations.cpp", "bytes": 1200, "lenguaje": "cpp"},
        {"ruta": "graph_algorithms/counting_rooms.cpp", "nombre": "counting_rooms.cpp", "bytes": 1600, "lenguaje": "cpp"},
    ],
    "jonathan-uy/cses-solutions": [
        {"ruta": "Introductory Problems/Weird Algorithm.cpp", "nombre": "Weird Algorithm.cpp", "bytes": 800, "lenguaje": "cpp"},
        {"ruta": "Introductory Problems/Missing Number.cpp", "nombre": "Missing Number.cpp", "bytes": 900, "lenguaje": "cpp"},
        {"ruta": "Introductory Problems/Number Spiral.cpp", "nombre": "Number Spiral.cpp", "bytes": 1250, "lenguaje": "cpp"},
        {"ruta": "Sorting and Searching/Apartments.cpp", "nombre": "Apartments.cpp", "bytes": 1400, "lenguaje": "cpp"},
        {"ruta": "Dynamic Programming/Coin Combinations I.cpp", "nombre": "Coin Combinations I.cpp", "bytes": 1300, "lenguaje": "cpp"},
        {"ruta": "Graph Algorithms/Building Roads.cpp", "nombre": "Building Roads.cpp", "bytes": 1700, "lenguaje": "cpp"},
    ],
    "jaehyunp/stanfordacm": [
        {"ruta": "code/Geometry.cc", "nombre": "Geometry.cc", "bytes": 4500, "lenguaje": "cpp"},
        {"ruta": "code/MaxFlowDinic.cc", "nombre": "MaxFlowDinic.cc", "bytes": 3100, "lenguaje": "cpp"},
        {"ruta": "code/SuffixAutomaton.cc", "nombre": "SuffixAutomaton.cc", "bytes": 3600, "lenguaje": "cpp"},
        {"ruta": "code/HeavyLight.cc", "nombre": "HeavyLight.cc", "bytes": 3400, "lenguaje": "cpp"},
        {"ruta": "code/Treap.cc", "nombre": "Treap.cc", "bytes": 3200, "lenguaje": "cpp"},
    ],
    "jilljenn/tryalgo": [
        {"ruta": "tryalgo/dijkstra.py", "nombre": "dijkstra.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "tryalgo/kruskal.py", "nombre": "kruskal.py", "bytes": 1950, "lenguaje": "python"},
        {"ruta": "tryalgo/knapsack.py", "nombre": "knapsack.py", "bytes": 2200, "lenguaje": "python"},
        {"ruta": "tryalgo/bipartite_matching.py", "nombre": "bipartite_matching.py", "bytes": 2400, "lenguaje": "python"},
        {"ruta": "tryalgo/fenwick.py", "nombre": "fenwick.py", "bytes": 1700, "lenguaje": "python"},
    ],
    "djeada/algorithms-and-data-structures": [
        {"ruta": "src/algorithms/search/binary_search.py", "nombre": "binary_search.py", "bytes": 2200, "lenguaje": "python"},
        {"ruta": "src/algorithms/sorting/merge_sort.py", "nombre": "merge_sort.py", "bytes": 2400, "lenguaje": "python"},
        {"ruta": "src/algorithms/graph/dijkstra.py", "nombre": "dijkstra.py", "bytes": 2800, "lenguaje": "python"},
        {"ruta": "src/data_structures/trees/avl_tree.py", "nombre": "avl_tree.py", "bytes": 4100, "lenguaje": "python"},
        {"ruta": "src/data_structures/trees/red_black_tree.py", "nombre": "red_black_tree.py", "bytes": 5200, "lenguaje": "python"},
    ],
    "kmoraza/advanced_data_structures_using_python": [
        {"ruta": "Segment Tree/Segment_Tree.py", "nombre": "Segment_Tree.py", "bytes": 2900, "lenguaje": "python"},
        {"ruta": "Trie/Trie.py", "nombre": "Trie.py", "bytes": 2300, "lenguaje": "python"},
        {"ruta": "Suffix Array/Suffix_Array.py", "nombre": "Suffix_Array.py", "bytes": 3100, "lenguaje": "python"},
        {"ruta": "Disjoint Set/Disjoint_Set.py", "nombre": "Disjoint_Set.py", "bytes": 1850, "lenguaje": "python"},
        {"ruta": "Fenwick Tree/Fenwick_Tree.py", "nombre": "Fenwick_Tree.py", "bytes": 1900, "lenguaje": "python"},
    ],
    "youngyangyang04/leetcode-master": [
        {"ruta": "problems/0001.两数之和.md", "nombre": "0001.两数之和.md", "bytes": 3200, "lenguaje": "markdown"},
        {"ruta": "problems/0015.三数之和.md", "nombre": "0015.三数之和.md", "bytes": 3900, "lenguaje": "markdown"},
        {"ruta": "problems/0020.有效的括号.md", "nombre": "0020.有效的括号.md", "bytes": 2800, "lenguaje": "markdown"},
        {"ruta": "problems/0070.爬楼梯.md", "nombre": "0070.爬楼梯.md", "bytes": 2600, "lenguaje": "markdown"},
        {"ruta": "problems/0206.翻转链表.md", "nombre": "0206.翻转链表.md", "bytes": 3100, "lenguaje": "markdown"},
    ],
    "danistefanovic/build-your-own-x": [
        {"ruta": "README.md", "nombre": "README.md", "bytes": 15000, "lenguaje": "markdown"},
        {"ruta": "build-your-own-database.md", "nombre": "build-your-own-database.md", "bytes": 4500, "lenguaje": "markdown"},
        {"ruta": "build-your-own-git.md", "nombre": "build-your-own-git.md", "bytes": 5200, "lenguaje": "markdown"},
        {"ruta": "build-your-own-operating-system.md", "nombre": "build-your-own-operating-system.md", "bytes": 5900, "lenguaje": "markdown"},
        {"ruta": "build-your-own-physics-engine.md", "nombre": "build-your-own-physics-engine.md", "bytes": 3800, "lenguaje": "markdown"},
    ],
    "donnemartin/system-design-primer": [
        {"ruta": "solutions/system_design/pastebin/README.md", "nombre": "pastebin_system_design.md", "bytes": 6200, "lenguaje": "markdown"},
        {"ruta": "solutions/system_design/twitter/README.md", "nombre": "twitter_system_design.md", "bytes": 7800, "lenguaje": "markdown"},
        {"ruta": "solutions/system_design/web_crawler/README.md", "nombre": "web_crawler_system_design.md", "bytes": 6900, "lenguaje": "markdown"},
        {"ruta": "solutions/system_design/mint/README.md", "nombre": "mint_system_design.md", "bytes": 5800, "lenguaje": "markdown"},
    ],
    "neetcode-gh/leetcode": [
        {"ruta": "python/0001-two-sum.py", "nombre": "0001-two-sum.py", "bytes": 1400, "lenguaje": "python"},
        {"ruta": "python/0020-valid-parentheses.py", "nombre": "0020-valid-parentheses.py", "bytes": 1600, "lenguaje": "python"},
        {"ruta": "python/0021-merge-two-sorted-lists.py", "nombre": "0021-merge-two-sorted-lists.py", "bytes": 1800, "lenguaje": "python"},
        {"ruta": "python/0121-best-time-to-buy-and-sell-stock.py", "nombre": "0121-best-time-to-buy-and-sell-stock.py", "bytes": 1500, "lenguaje": "python"},
        {"ruta": "python/0125-valid-palindrome.py", "nombre": "0125-valid-palindrome.py", "bytes": 1300, "lenguaje": "python"},
        {"ruta": "python/0141-linked-list-cycle.py", "nombre": "0141-linked-list-cycle.py", "bytes": 1600, "lenguaje": "python"},
        {"ruta": "python/0146-lru-cache.py", "nombre": "0146-lru-cache.py", "bytes": 2800, "lenguaje": "python"},
        {"ruta": "python/0200-number-of-islands.py", "nombre": "0200-number-of-islands.py", "bytes": 2200, "lenguaje": "python"},
        {"ruta": "cpp/0001-two-sum.cpp", "nombre": "0001-two-sum.cpp", "bytes": 1600, "lenguaje": "cpp"},
        {"ruta": "cpp/0020-valid-parentheses.cpp", "nombre": "0020-valid-parentheses.cpp", "bytes": 1750, "lenguaje": "cpp"},
        {"ruta": "cpp/0021-merge-two-sorted-lists.cpp", "nombre": "0021-merge-two-sorted-lists.cpp", "bytes": 1950, "lenguaje": "cpp"},
        {"ruta": "cpp/0146-lru-cache.cpp", "nombre": "0146-lru-cache.cpp", "bytes": 3100, "lenguaje": "cpp"},
        {"ruta": "cpp/0200-number-of-islands.cpp", "nombre": "0200-number-of-islands.cpp", "bytes": 2400, "lenguaje": "cpp"},
    ],
    "asabeneh/30-days-of-python": [
        {"ruta": "01_Day_Introduction/01_introduction.py", "nombre": "01_introduction.py", "bytes": 1200, "lenguaje": "python"},
        {"ruta": "02_Day_Variables_builtin_functions/variables.py", "nombre": "variables.py", "bytes": 1600, "lenguaje": "python"},
        {"ruta": "03_Day_Operators/operators.py", "nombre": "operators.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "04_Day_Strings/strings.py", "nombre": "strings.py", "bytes": 2800, "lenguaje": "python"},
        {"ruta": "05_Day_Lists/lists.py", "nombre": "lists.py", "bytes": 3200, "lenguaje": "python"},
        {"ruta": "06_Day_Tuples/tuples.py", "nombre": "tuples.py", "bytes": 1400, "lenguaje": "python"},
        {"ruta": "07_Day_Sets/sets.py", "nombre": "sets.py", "bytes": 1800, "lenguaje": "python"},
        {"ruta": "08_Day_Dictionaries/dictionaries.py", "nombre": "dictionaries.py", "bytes": 2400, "lenguaje": "python"},
        {"ruta": "09_Day_Conditionals/conditionals.py", "nombre": "conditionals.py", "bytes": 2200, "lenguaje": "python"},
        {"ruta": "10_Day_Loops/loops.py", "nombre": "loops.py", "bytes": 2600, "lenguaje": "python"},
        {"ruta": "11_Day_Functions/functions.py", "nombre": "functions.py", "bytes": 3400, "lenguaje": "python"},
        {"ruta": "12_Day_Modules/modules.py", "nombre": "modules.py", "bytes": 1900, "lenguaje": "python"},
        {"ruta": "13_Day_List_comprehension/list_comprehension.py", "nombre": "list_comprehension.py", "bytes": 1700, "lenguaje": "python"},
        {"ruta": "14_Day_Higher_order_functions/higher_order_functions.py", "nombre": "higher_order_functions.py", "bytes": 2900, "lenguaje": "python"},
        {"ruta": "17_Day_Exception_handling/exception_handling.py", "nombre": "exception_handling.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "18_Day_Regular_expressions/regular_expressions.py", "nombre": "regular_expressions.py", "bytes": 3100, "lenguaje": "python"},
        {"ruta": "21_Day_Classes_and_objects/classes_and_objects.py", "nombre": "classes_and_objects.py", "bytes": 3500, "lenguaje": "python"},
        {"ruta": "25_Day_Pandas/pandas_intro.py", "nombre": "pandas_intro.py", "bytes": 2800, "lenguaje": "python"},
    ],
    "jakevdp/pythondatasciencehandbook": [
        {"ruta": "notebooks/02.01-Understanding-Data-Types.ipynb", "nombre": "02.01-Understanding-Data-Types.ipynb", "bytes": 14500, "lenguaje": "python"},
        {"ruta": "notebooks/02.02-The-Basics-Of-NumPy-Arrays.ipynb", "nombre": "02.02-The-Basics-Of-NumPy-Arrays.ipynb", "bytes": 18200, "lenguaje": "python"},
        {"ruta": "notebooks/02.03-Computation-on-arrays-ufuncs.ipynb", "nombre": "02.03-Computation-on-arrays-ufuncs.ipynb", "bytes": 16400, "lenguaje": "python"},
        {"ruta": "notebooks/02.04-Computation-on-arrays-aggregates.ipynb", "nombre": "02.04-Computation-on-arrays-aggregates.ipynb", "bytes": 15800, "lenguaje": "python"},
        {"ruta": "notebooks/02.05-Computation-on-arrays-broadcasting.ipynb", "nombre": "02.05-Computation-on-arrays-broadcasting.ipynb", "bytes": 17200, "lenguaje": "python"},
        {"ruta": "notebooks/02.06-Boolean-Arrays-and-Masks.ipynb", "nombre": "02.06-Boolean-Arrays-and-Masks.ipynb", "bytes": 16900, "lenguaje": "python"},
        {"ruta": "notebooks/03.01-Introducing-Pandas-Objects.ipynb", "nombre": "03.01-Introducing-Pandas-Objects.ipynb", "bytes": 19500, "lenguaje": "python"},
        {"ruta": "notebooks/03.02-Data-Indexing-and-Selection.ipynb", "nombre": "03.02-Data-Indexing-and-Selection.ipynb", "bytes": 18400, "lenguaje": "python"},
        {"ruta": "notebooks/03.03-Operations-in-Pandas.ipynb", "nombre": "03.03-Operations-in-Pandas.ipynb", "bytes": 14800, "lenguaje": "python"},
        {"ruta": "notebooks/03.07-Merge-and-Join.ipynb", "nombre": "03.07-Merge-and-Join.ipynb", "bytes": 22100, "lenguaje": "python"},
        {"ruta": "notebooks/03.08-Aggregation-and-Grouping.ipynb", "nombre": "03.08-Aggregation-and-Grouping.ipynb", "bytes": 21500, "lenguaje": "python"},
        {"ruta": "notebooks/05.02-Introducing-Scikit-Learn.ipynb", "nombre": "05.02-Introducing-Scikit-Learn.ipynb", "bytes": 24000, "lenguaje": "python"},
        {"ruta": "notebooks/05.06-Linear-Regression.ipynb", "nombre": "05.06-Linear-Regression.ipynb", "bytes": 23500, "lenguaje": "python"},
        {"ruta": "notebooks/05.07-Support-Vector-Machines.ipynb", "nombre": "05.07-Support-Vector-Machines.ipynb", "bytes": 25800, "lenguaje": "python"},
        {"ruta": "notebooks/05.08-Random-Forests.ipynb", "nombre": "05.08-Random-Forests.ipynb", "bytes": 24200, "lenguaje": "python"},
        {"ruta": "notebooks/05.09-PCA.ipynb", "nombre": "05.09-PCA.ipynb", "bytes": 21800, "lenguaje": "python"},
        {"ruta": "notebooks/05.11-K-Means.ipynb", "nombre": "05.11-K-Means.ipynb", "bytes": 22400, "lenguaje": "python"},
    ],
    "ageron/handson-ml3": [
        {"ruta": "01_the_machine_learning_landscape.ipynb", "nombre": "01_the_machine_learning_landscape.ipynb", "bytes": 28000, "lenguaje": "python"},
        {"ruta": "02_end_to_end_machine_learning_project.ipynb", "nombre": "02_end_to_end_machine_learning_project.ipynb", "bytes": 48000, "lenguaje": "python"},
        {"ruta": "03_classification.ipynb", "nombre": "03_classification.ipynb", "bytes": 36000, "lenguaje": "python"},
        {"ruta": "04_training_linear_models.ipynb", "nombre": "04_training_linear_models.ipynb", "bytes": 39000, "lenguaje": "python"},
        {"ruta": "05_support_vector_machines.ipynb", "nombre": "05_support_vector_machines.ipynb", "bytes": 32000, "lenguaje": "python"},
        {"ruta": "06_decision_trees.ipynb", "nombre": "06_decision_trees.ipynb", "bytes": 27000, "lenguaje": "python"},
        {"ruta": "07_ensemble_learning_and_random_forests.ipynb", "nombre": "07_ensemble_learning_and_random_forests.ipynb", "bytes": 34000, "lenguaje": "python"},
        {"ruta": "08_dimensionality_reduction.ipynb", "nombre": "08_dimensionality_reduction.ipynb", "bytes": 29000, "lenguaje": "python"},
        {"ruta": "09_unsupervised_learning.ipynb", "nombre": "09_unsupervised_learning.ipynb", "bytes": 35000, "lenguaje": "python"},
        {"ruta": "10_neural_nets_with_keras.ipynb", "nombre": "10_neural_nets_with_keras.ipynb", "bytes": 41000, "lenguaje": "python"},
    ],
    "pierian-data/complete-python-3-bootcamp": [
        {"ruta": "00-Python Object and Data Structure Basics/01-Numbers.ipynb", "nombre": "01-Numbers.ipynb", "bytes": 5200, "lenguaje": "python"},
        {"ruta": "00-Python Object and Data Structure Basics/03-Lists.ipynb", "nombre": "03-Lists.ipynb", "bytes": 8400, "lenguaje": "python"},
        {"ruta": "00-Python Object and Data Structure Basics/04-Dictionaries.ipynb", "nombre": "04-Dictionaries.ipynb", "bytes": 7900, "lenguaje": "python"},
        {"ruta": "02-Python Statements/01-if, elif, and else Statements.ipynb", "nombre": "01-if, elif, and else Statements.ipynb", "bytes": 6200, "lenguaje": "python"},
        {"ruta": "02-Python Statements/02-for Loops.ipynb", "nombre": "02-for Loops.ipynb", "bytes": 7400, "lenguaje": "python"},
        {"ruta": "03-Methods and Functions/03-Function Practice Exercises.ipynb", "nombre": "03-Function Practice Exercises.ipynb", "bytes": 11200, "lenguaje": "python"},
        {"ruta": "03-Methods and Functions/08-Functions and Methods - Homework Assignment.ipynb", "nombre": "08-Functions and Methods - Homework Assignment.ipynb", "bytes": 9800, "lenguaje": "python"},
        {"ruta": "04-Milestone Project - 1/01-Milestone Project 1 - Assignment.ipynb", "nombre": "01-Milestone Project 1 - Assignment.ipynb", "bytes": 14500, "lenguaje": "python"},
        {"ruta": "05-Object Oriented Programming/01-Object Oriented Programming.ipynb", "nombre": "01-Object Oriented Programming.ipynb", "bytes": 12800, "lenguaje": "python"},
        {"ruta": "05-Object Oriented Programming/04-OOP Challenge.ipynb", "nombre": "04-OOP Challenge.ipynb", "bytes": 6400, "lenguaje": "python"},
        {"ruta": "07-Errors and Exception Handling/02-Errors and Exceptions Homework.ipynb", "nombre": "02-Errors and Exceptions Homework.ipynb", "bytes": 5800, "lenguaje": "python"},
        {"ruta": "10-Python Decorators/01-Decorators.ipynb", "nombre": "01-Decorators.ipynb", "bytes": 9100, "lenguaje": "python"},
        {"ruta": "11-Python Generators/01-Generators.ipynb", "nombre": "01-Generators.ipynb", "bytes": 8600, "lenguaje": "python"},
    ],
    "zhiwehu/python-programming-exercises": [
        {"ruta": "exercises/question_01.py", "nombre": "question_01.py", "bytes": 550, "lenguaje": "python"},
        {"ruta": "exercises/question_02.py", "nombre": "question_02.py", "bytes": 620, "lenguaje": "python"},
        {"ruta": "exercises/question_03.py", "nombre": "question_03.py", "bytes": 580, "lenguaje": "python"},
        {"ruta": "exercises/question_06.py", "nombre": "question_06.py", "bytes": 840, "lenguaje": "python"},
        {"ruta": "exercises/question_07.py", "nombre": "question_07.py", "bytes": 920, "lenguaje": "python"},
        {"ruta": "exercises/question_08.py", "nombre": "question_08.py", "bytes": 710, "lenguaje": "python"},
        {"ruta": "exercises/question_10.py", "nombre": "question_10.py", "bytes": 680, "lenguaje": "python"},
        {"ruta": "exercises/question_14.py", "nombre": "question_14.py", "bytes": 790, "lenguaje": "python"},
        {"ruta": "exercises/question_18.py", "nombre": "question_18.py", "bytes": 1150, "lenguaje": "python"},
        {"ruta": "exercises/question_20.py", "nombre": "question_20.py", "bytes": 890, "lenguaje": "python"},
        {"ruta": "exercises/question_25.py", "nombre": "question_25.py", "bytes": 760, "lenguaje": "python"},
    ],
    "gto76/python-cheatsheet": [
        {"ruta": "src/01_types_and_operations.py", "nombre": "01_types_and_operations.py", "bytes": 3800, "lenguaje": "python"},
        {"ruta": "src/02_collections.py", "nombre": "02_collections.py", "bytes": 4500, "lenguaje": "python"},
        {"ruta": "src/03_control_flow.py", "nombre": "03_control_flow.py", "bytes": 3100, "lenguaje": "python"},
        {"ruta": "src/04_functions_and_scopes.py", "nombre": "04_functions_and_scopes.py", "bytes": 4200, "lenguaje": "python"},
        {"ruta": "src/05_classes_and_oop.py", "nombre": "05_classes_and_oop.py", "bytes": 4900, "lenguaje": "python"},
        {"ruta": "src/06_exceptions_and_context.py", "nombre": "06_exceptions_and_context.py", "bytes": 3400, "lenguaje": "python"},
        {"ruta": "src/07_concurrency_and_async.py", "nombre": "07_concurrency_and_async.py", "bytes": 4100, "lenguaje": "python"},
        {"ruta": "src/08_standard_library.py", "nombre": "08_standard_library.py", "bytes": 5200, "lenguaje": "python"},
    ],
    "allendowney/thinkpython2": [
        {"ruta": "code/polygon.py", "nombre": "polygon.py", "bytes": 2200, "lenguaje": "python"},
        {"ruta": "code/pie.py", "nombre": "pie.py", "bytes": 1900, "lenguaje": "python"},
        {"ruta": "code/ackermann.py", "nombre": "ackermann.py", "bytes": 850, "lenguaje": "python"},
        {"ruta": "code/palindrome.py", "nombre": "palindrome.py", "bytes": 1250, "lenguaje": "python"},
        {"ruta": "code/rotate.py", "nombre": "rotate.py", "bytes": 1100, "lenguaje": "python"},
        {"ruta": "code/wordlist.py", "nombre": "wordlist.py", "bytes": 1400, "lenguaje": "python"},
        {"ruta": "code/markov.py", "nombre": "markov.py", "bytes": 2800, "lenguaje": "python"},
        {"ruta": "code/Time1.py", "nombre": "Time1.py", "bytes": 2400, "lenguaje": "python"},
        {"ruta": "code/Point1.py", "nombre": "Point1.py", "bytes": 2100, "lenguaje": "python"},
        {"ruta": "code/Card.py", "nombre": "Card.py", "bytes": 3200, "lenguaje": "python"},
    ],
    "microsoft/c9-python-getting-started": [
        {"ruta": "python/01_strings.py", "nombre": "01_strings.py", "bytes": 850, "lenguaje": "python"},
        {"ruta": "python/02_numeric_types.py", "nombre": "02_numeric_types.py", "bytes": 950, "lenguaje": "python"},
        {"ruta": "python/03_dates.py", "nombre": "03_dates.py", "bytes": 1200, "lenguaje": "python"},
        {"ruta": "python/04_error_handling.py", "nombre": "04_error_handling.py", "bytes": 1100, "lenguaje": "python"},
        {"ruta": "python/05_conditionals.py", "nombre": "05_conditionals.py", "bytes": 1300, "lenguaje": "python"},
        {"ruta": "python/06_complex_conditions.py", "nombre": "06_complex_conditions.py", "bytes": 1250, "lenguaje": "python"},
        {"ruta": "python/07_collections.py", "nombre": "07_collections.py", "bytes": 1600, "lenguaje": "python"},
        {"ruta": "python/08_loops.py", "nombre": "08_loops.py", "bytes": 1450, "lenguaje": "python"},
        {"ruta": "python/09_functions.py", "nombre": "09_functions.py", "bytes": 1700, "lenguaje": "python"},
        {"ruta": "python/10_decorators.py", "nombre": "10_decorators.py", "bytes": 1550, "lenguaje": "python"},
        {"ruta": "python/11_calling_api.py", "nombre": "11_calling_api.py", "bytes": 1900, "lenguaje": "python"},
    ]
}


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
    repo_meta = obtener_repositorio(ref)
    nombre = repo_meta["nombre"] if repo_meta else ref
    descripcion = repo_meta["descripcion"] if repo_meta else ""

    # Si tenemos ejercicios destacados curados para este repositorio, úsalos como base o fallback
    destacados = EJERCICIOS_DESTACADOS_REPO.get(ref.lower()) or EJERCICIOS_DESTACADOS_REPO.get(ref) or []

    salida = []

    # Intentar obtener la lista viva de GitHub
    try:
        import github_lector
        info = github_lector.abrir(ref)
        if info.get("nombre"):
            nombre = info["nombre"]
        if info.get("descripcion"):
            descripcion = info["descripcion"]
        archivos = info.get("archivos") or []

        # Filtrar archivos relevantes de código (.py, .cpp, .hpp, .h, .md con ejercicios)
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
    except Exception:
        # Si GitHub API está limitada (60 consultas/h), sin conexión o bloqueada, no fallamos
        salida = []

    # Si la lista viva no devolvió ejercicios o falló la API, usar los ejercicios destacados
    if not salida and destacados:
        for d in destacados:
            path = d["ruta"]
            if ruta_sub and not path.startswith(ruta_sub):
                continue
            salida.append({
                "ruta": path,
                "nombre": d.get("nombre") or os.path.basename(path),
                "bytes": d.get("bytes", 1500),
                "lenguaje": d.get("lenguaje", "python" if path.endswith(".py") else "cpp" if path.endswith((".cpp", ".cc", ".cxx", ".h", ".hpp")) else "markdown"),
                "es_ejercicio": True
            })
            if len(salida) >= limite:
                break

    return {
        "ref": ref,
        "nombre": nombre,
        "descripcion": descripcion,
        "archivos": salida
    }


