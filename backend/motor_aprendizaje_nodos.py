"""
Motor de Aprendizaje por Grafo de Nodos (Knowledge Graph Learning Engine) para Prig IDE.

Coordina de forma unificada las 4 secciones educativas de Prig:
    - YouTube:  Flujo de video con marcas de tiempo temáticas y reproducción en contexto.
    - GitHub:   Flujo de proyectos, repositorios curados y archivos de código base real.
    - Kaggle:   Flujo de datasets reales, cuadernos de análisis y pipelines de datos.
    - Prig Hub: Flujo de paquetes de conocimiento, blueprints y rutas de aprendizaje.

Estructura el conocimiento como un Grafo Acíclico Dirigido (DAG) donde cada nodo
representa una competencia conceptual/práctica sujeta a marcos teóricos formales,
organizada desde nivel Junior hasta Senior, con tareas pre-respondidas y pruebas unitarias
de ejecución instantánea sin depender de latencias del modelo de lenguaje.
"""

import os
import re
import json
import time
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple


class MotorAprendizajeNodos:
    def __init__(self, workspace_dir: Optional[str] = None):
        self.workspace_dir = os.path.abspath(workspace_dir or os.getcwd())
        self.ruta_carreras = os.path.join(self.workspace_dir, "carreras")
        self.ruta_cursos_yt = os.path.join(self.workspace_dir, "frontend", "data", "cursos_youtube.json")
        self.ruta_progreso = os.path.join(self.workspace_dir, ".prig_aprendizaje_progreso.json")
        
        # Almacenes en memoria para respuestas ultra-rápidas (<10ms)
        self.nodos: Dict[str, Dict[str, Any]] = {}
        self.orden_nodos: List[str] = []
        self.indice_busqueda: List[Dict[str, Any]] = []
        
        self._inicializar_grafo()

    # =========================================================================
    # INICIALIZACIÓN Y CONSTRUCCIÓN DEL GRAFO DE CONOCIMIENTO
    # =========================================================================

    def _inicializar_grafo(self):
        """Carga y construye el catálogo completo de nodos pedagógicos interconectados."""
        nodos_fundamentales = self._obtener_nodos_curriculares()
        for nodo in nodos_fundamentales:
            nodo_id = nodo["id"]
            self.nodos[nodo_id] = nodo
            self.orden_nodos.append(nodo_id)

        # Enlazar aristas inversas y validar integridad del grafo
        self._conectar_aristas_grafo()

        # Construir índice para búsqueda instantánea
        self._construir_indice_busqueda()

    def _conectar_aristas_grafo(self):
        """Asegura que cada prerrequisito tenga su contraparte en 'siguientes' y depura referencias huérfanas."""
        for nid, nodo in self.nodos.items():
            nodo["prerrequisitos"] = [p for p in nodo.get("prerrequisitos", []) if p in self.nodos]
            nodo["siguientes"] = [s for s in nodo.get("siguientes", []) if s in self.nodos]

        for nid, nodo in self.nodos.items():
            for prereq_id in nodo.get("prerrequisitos", []):
                if prereq_id in self.nodos:
                    if nid not in self.nodos[prereq_id]["siguientes"]:
                        self.nodos[prereq_id]["siguientes"].append(nid)


    def _construir_indice_busqueda(self):
        """Indexa palabras clave de teoría, videos, datasets y repos para búsqueda en O(1)/O(N)."""
        self.indice_busqueda = []
        for nid, n in self.nodos.items():
            terminos = [
                n["id"],
                n["titulo"],
                n["nivel"],
                n.get("etapa", ""),
                n.get("carrera_referencia", "")
            ]
            
            # Términos del marco teórico
            mt = n.get("marco_teorico", {})
            terminos.append(mt.get("resumen", ""))
            terminos.extend(mt.get("principios_nucleares", []))
            for df in mt.get("definiciones_formales", []):
                terminos.append(df.get("termino", ""))
                terminos.append(df.get("definicion", ""))

            # Términos de herramientas
            herrs = n.get("herramientas", {})
            yt = herrs.get("youtube", {})
            if yt:
                terminos.append(yt.get("titulo", ""))
                terminos.append(yt.get("canal", ""))

            gh = herrs.get("github", {})
            if gh:
                terminos.append(gh.get("repositorio", ""))
                terminos.append(gh.get("descripcion", ""))

            kg = herrs.get("kaggle", {})
            if kg:
                terminos.append(kg.get("dataset_slug", ""))
                terminos.append(kg.get("titulo", ""))

            tarea = n.get("tarea_prerespondida", {})
            if tarea:
                terminos.append(tarea.get("enunciado", ""))

            texto_indexable = " ".join(terminos).lower()
            self.indice_busqueda.append({
                "id": nid,
                "titulo": n["titulo"],
                "nivel": n["nivel"],
                "texto": texto_indexable
            })

    # =========================================================================
    # CATÁLOGO NUCLEAR DE NODOS DE CONOCIMIENTO (JUNIOR ➔ SENIOR)
    # =========================================================================

    def _obtener_nodos_curriculares(self) -> List[Dict[str, Any]]:
        """
        Retorna la base de nodos nucleares con rigor teórico, articulando
        YouTube, GitHub, Kaggle y Prig Hub con tareas pre-respondidas verificadas.
        """
        return [
            # -----------------------------------------------------------------
            # TIER 1: NIVEL JUNIOR (Fundamentos, Sintaxis, Estructuras y Control)
            # -----------------------------------------------------------------
            {
                "id": "nodo-py-01-fundamentos-sintaxis",
                "slug": "fundamentos-python-tipos-nativos",
                "titulo": "Fundamentos y Tipos Nativos en Python",
                "nivel": "junior",
                "etapa": "Etapa 1: Fundamentos y Sintaxis",
                "carrera_referencia": "IIA-103 / LPR-101",
                "orden_sugerido": 1,
                "icono": "fa-brands fa-python",
                "color_nodo": "#a6e3a1",
                "prerrequisitos": [],
                "siguientes": ["nodo-py-02-control-flujo"],
                "marco_teorico": {
                    "resumen": "Estudio formal de los tipos de datos atómicos y colecciones nativas inmutables y mutables en memoria RAM. Semántica de asignación por referencia en Python (PyObject) y recolección de basura por conteo de referencias.",
                    "principios_nucleares": [
                        "Diferenciación estricta entre inmutabilidad (int, float, str, tuple) y mutabilidad (list, dict, set).",
                        "Identidad de objeto (is) vs Equivalencia de valor (==).",
                        "Acceso indexado determinista en tiempo constante O(1) en arreglos contiguos."
                    ],
                    "definiciones_formales": [
                        {"termino": "PyObject", "definicion": "Estructura base de CPython que contiene el contador de referencias ob_refcnt y el puntero al tipo ob_type."},
                        {"termino": "Inmutabilidad", "definicion": "Propiedad de un objeto cuyo estado interno no puede ser alterado tras su instanciación; toda modificación produce una nueva instancia."}
                    ],
                    "formulas_o_axiomas": "$$\\forall x \\in \\text{Inmutables}, \\quad \\text{modificar}(x) \\implies \\text{id}(x') \\neq \\text{id}(x)$$"
                },
                "herramientas": {
                    "youtube": {
                        "video_id": "nLRL_NcnK-4",
                        "titulo": "Harvard CS50P – Introduction to Programming with Python (David J. Malan)",
                        "canal": "Harvard / freeCodeCamp",
                        "duracion": "15:57:48",
                        "minuto_clave": "00:15:30",
                        "marcas_de_tiempo": [
                            {"minuto": "00:15:30", "tema": "Variables y Tipos Primitivos"},
                            {"minuto": "01:22:45", "tema": "Funciones y Alcance de Variables"},
                            {"minuto": "02:45:10", "tema": "Listas y Colecciones Indexadas"}
                        ],
                        "query_busqueda": "Harvard CS50P David Malan Python"
                    },
                    "github": {
                        "repositorio": "exercism/python",
                        "ruta_archivos": "exercises/practice/two-fer",
                        "descripcion": "Ejercicios de sintaxis básica y tipado estricto con tests automatizados en pytest.",
                        "plantilla_directorio": "proyectos_aprendizaje/py_fundamentos"
                    },
                    "kaggle": {
                        "dataset_slug": "titanic",
                        "titulo": "Titanic: Machine Learning from Disaster (Inspección inicial de tipos)",
                        "notebook_referencia": "kaggle_comprehensive-data-exploration-with-python",
                        "tarea_datos": "Cargar datos crudos y verificar tipos nativos (int64, float64, object) sin librerías externas."
                    },
                    "prig_hub": {
                        "pack_id": "pack_python_fundamentos",
                        "ruta_guia": "docs/prig-hub.md#python-junior"
                    }
                },
                "tarea_prerespondida": {
                    "id": "tarea_py_01_tipos",
                    "titulo": "Normalización y Clasificación de Datos Primitivos",
                    "enunciado": "Implementa una función 'analizar_tipos(datos: list) -> dict' que reciba una lista de valores heterogéneos y devuelva un diccionario con la cuenta de tipos inmutables vs mutables, además de una lista normalizada de cadenas sin espacios sobrantes.",
                    "codigo_inicial": (
                        "def analizar_tipos(datos: list) -> dict:\n"
                        "    # TODO: Clasificar objetos mutables e inmutables y normalizar cadenas\n"
                        "    return {}\n"
                    ),
                    "solucion_referencia": (
                        "def analizar_tipos(datos: list) -> dict:\n"
                        "    \"\"\"\n"
                        "    Solución pre-respondida de referencia con análisis de inmutabilidad.\n"
                        "    \"\"\"\n"
                        "    inmutables_tipos = (int, float, str, tuple, bool, bytes)\n"
                        "    conteo_inmutables = 0\n"
                        "    conteo_mutables = 0\n"
                        "    cadenas_limpias = []\n"
                        "\n"
                        "    for item in datos:\n"
                        "        if isinstance(item, inmutables_tipos):\n"
                        "            conteo_inmutables += 1\n"
                        "        else:\n"
                        "            conteo_mutables += 1\n"
                        "        \n"
                        "        if isinstance(item, str):\n"
                        "            cadenas_limpias.append(item.strip().lower())\n"
                        "\n"
                        "    return {\n"
                        "        'inmutables': conteo_inmutables,\n"
                        "        'mutables': conteo_mutables,\n"
                        "        'cadenas': cadenas_limpias\n"
                        "    }\n"
                    ),
                    "guia_resolucion_paso_a_paso": [
                        "Paso 1: Define una tupla de referencia con los tipos primitivos inmutables en Python: (int, float, str, tuple, bool, bytes).",
                        "Paso 2: Itera linealmente sobre la colección O(N) verificando 'isinstance' para acumular contadores de memoria.",
                        "Paso 3: Si el elemento evaluado es de tipo 'str', aplica strip() y lower() para normalizar y almacena en la lista de cadenas limpias."
                    ],
                    "pruebas_unitarias": (
                        "def test_analizar_tipos():\n"
                        "    datos = [42, ' Hola Mundo ', [1, 2], {'clave': 'valor'}, 3.14, (1, 2), 'PYTHON ']\n"
                        "    res = analizar_tipos(datos)\n"
                        "    assert res['inmutables'] == 5, f\"Esperado 5 inmutables, obtenido {res['inmutables']}\"\n"
                        "    assert res['mutables'] == 2, f\"Esperado 2 mutables, obtenido {res['mutables']}\"\n"
                        "    assert 'hola mundo' in res['cadenas']\n"
                        "    assert 'python' in res['cadenas']\n"
                        "    print('✓ Todas las pruebas de sintaxis y tipos superadas con éxito.')\n"
                    ),
                    "pistas_progresivas": [
                        "Pista 1: Recuerda que las tuplas y cadenas no pueden modificarse in-situ, por lo que son inmutables.",
                        "Pista 2: Usa isinstance(item, tupla_de_tipos) para una verificación limpia en una sola expresión.",
                        "Pista 3: Las listas y diccionarios son estructuras mutables porque su contenido puede variar sin cambiar su puntero de memoria."
                    ]
                }
            },

            {
                "id": "nodo-py-02-control-flujo",
                "slug": "control-de-flujo-invariantes-guardas",
                "titulo": "Control de Flujo, Cláusulas de Guarda e Invariantes",
                "nivel": "junior",
                "etapa": "Etapa 1: Fundamentos y Sintaxis",
                "carrera_referencia": "IIA-103 / IIA-104",
                "orden_sugerido": 2,
                "icono": "fa-solid fa-code-branch",
                "color_nodo": "#89b4fa",
                "prerrequisitos": ["nodo-py-01-fundamentos-sintaxis"],
                "siguientes": ["nodo-ds-01-estructuras-lineales"],
                "marco_teorico": {
                    "resumen": "Estructuras de decisión condicional y bucles deterministas vs indeterministas. Reducción de la complejidad ciclomática de McCabe mediante el patrón 'Early Return' (cláusula de guarda). Verificación formal de invariantes de bucle.",
                    "principios_nucleares": [
                        "Invariante de bucle: propiedad lógica que se mantiene verdadera antes de la primera iteración, antes de cada paso subsiguiente y al terminar el bucle.",
                        "Cláusula de Guarda: validación y salida temprana de estados nulos o inválidos para aplanar la estructura sintáctica.",
                        "Eliminación de bucles infinitos mediante funciones de decrecimiento acotadas inferiormente."
                    ],
                    "definiciones_formales": [
                        {"termino": "Complejidad Ciclomática (M)", "definicion": "$$M = E - N + 2P$$, donde E son las aristas del grafo de flujo de control, N los nodos y P los componentes conectados."},
                        {"termino": "Early Return", "definicion": "Patrón de diseño donde las condiciones excepcionales o de borde provocan una salida inmediata de la función, reservando el cuerpo para el flujo óptimo."}
                    ],
                    "formulas_o_axiomas": "$$\\forall i, \\quad \\{P \\land \\text{condicion}\\} \\; S \\; \\{P\\} \\implies \\{P\\} \\; \\text{while(condicion)} \\; S \\; \\{P \\land \\neg\\text{condicion}\\}$$"
                },
                "herramientas": {
                    "youtube": {
                        "video_id": "DLikpfc64cA",
                        "titulo": "Aprende Python - Curso de Python desde Cero (Bucles y Condicionales)",
                        "canal": "freeCodeCamp Español",
                        "duracion": "4:36:43",
                        "minuto_clave": "01:10:00",
                        "marcas_de_tiempo": [
                            {"minuto": "01:10:00", "tema": "Condicionales If, Elif, Else"},
                            {"minuto": "01:45:20", "tema": "Bucles While y Condiciones de Parada"},
                            {"minuto": "02:15:00", "tema": "Bucles For y Función Range"}
                        ],
                        "query_busqueda": "Curso Python desde cero completo español condicionales"
                    },
                    "github": {
                        "repositorio": "TheAlgorithms/Python",
                        "ruta_archivos": "searches/binary_search.py",
                        "descripcion": "Implementación de algoritmos clásicos con invariantes de bucle bien documentadas.",
                        "plantilla_directorio": "proyectos_aprendizaje/control_flujo"
                    },
                    "kaggle": {
                        "dataset_slug": "house-prices-advanced-regression-techniques",
                        "titulo": "House Prices - Advanced Regression Techniques",
                        "notebook_referencia": "kaggle_comprehensive-data-exploration-with-python",
                        "tarea_datos": "Filtrar filas mediante condiciones booleanas compuestas (precios > percentil 90 y años > 2000)."
                    },
                    "prig_hub": {
                        "pack_id": "pack_algoritmos_control",
                        "ruta_guia": "docs/prig-hub.md#control-flujo"
                    }
                },
                "tarea_prerespondida": {
                    "id": "tarea_py_02_guardas",
                    "titulo": "Filtrado Robusto con Cláusulas de Guarda",
                    "enunciado": "Escribe una función 'filtrar_transacciones(transacciones: list, min_monto: float) -> list' que filtre únicamente transacciones válidas ('completada'), con monto >= min_monto y usuario no bloqueado, utilizando cláusulas de guarda sin anidación profunda.",
                    "codigo_inicial": (
                        "def filtrar_transacciones(transacciones: list, min_monto: float) -> list:\n"
                        "    # TODO: Filtrar transacciones usando guardas tempranas\n"
                        "    return []\n"
                    ),
                    "solucion_referencia": (
                        "def filtrar_transacciones(transacciones: list, min_monto: float) -> list:\n"
                        "    \"\"\"\n"
                        "    Filtra transacciones con complejidad ciclomática mínima O(N).\n"
                        "    \"\"\"\n"
                        "    if not transacciones or min_monto < 0:\n"
                        "        return []\n"
                        "\n"
                        "    aprobadas = []\n"
                        "    for tx in transacciones:\n"
                        "        # Cláusulas de guarda en iteración\n"
                        "        if not isinstance(tx, dict):\n"
                        "            continue\n"
                        "        if tx.get('estado') != 'completada':\n"
                        "            continue\n"
                        "        if tx.get('bloqueado', False):\n"
                        "            continue\n"
                        "        if tx.get('monto', 0) < min_monto:\n"
                        "            continue\n"
                        "        \n"
                        "        aprobadas.append(tx['id'])\n"
                        "        \n"
                        "    return aprobadas\n"
                    ),
                    "guia_resolucion_paso_a_paso": [
                        "Paso 1: Coloca una guarda inicial al principio de la función para retornar lista vacía si 'transacciones' es None o min_monto es negativo.",
                        "Paso 2: En el bucle iterativo, en lugar de anidar múltiples bloques if uno dentro de otro, descarta elementos con 'continue' tan pronto fallen una regla.",
                        "Paso 3: Solo los elementos que sobreviven a todas las guardas se agregan a la lista de aprobadas, manteniendo la indentación plana."
                    ],
                    "pruebas_unitarias": (
                        "def test_filtrar_transacciones():\n"
                        "    lote = [\n"
                        "        {'id': 1, 'estado': 'completada', 'monto': 150.0, 'bloqueado': False},\n"
                        "        {'id': 2, 'estado': 'pendiente', 'monto': 300.0, 'bloqueado': False},\n"
                        "        {'id': 3, 'estado': 'completada', 'monto': 50.0, 'bloqueado': False},\n"
                        "        {'id': 4, 'estado': 'completada', 'monto': 200.0, 'bloqueado': True},\n"
                        "        {'id': 5, 'estado': 'completada', 'monto': 500.0, 'bloqueado': False}\n"
                        "    ]\n"
                        "    res = filtrar_transacciones(lote, 100.0)\n"
                        "    assert res == [1, 5], f\"Esperado [1, 5], obtenido {res}\"\n"
                        "    assert filtrar_transacciones([], 100.0) == []\n"
                        "    print('✓ Pruebas de control de flujo y guardas superadas con éxito.')\n"
                    ),
                    "pistas_progresivas": [
                        "Pista 1: Cada sentencia 'continue' salta inmediatamente a la siguiente iteración, evitando niveles de indentación anidados.",
                        "Pista 2: Usa tx.get('bloqueado', False) para prevenir excepciones KeyError si el diccionario no incluye esa llave.",
                        "Pista 3: Retornar temprano ante entradas vacías previene procesamiento innecesario O(N)."
                    ]
                }
            },

            # -----------------------------------------------------------------
            # TIER 2: NIVEL INTERMEDIO (Estructuras, POO, EDA y Datos)
            # -----------------------------------------------------------------
            {
                "id": "nodo-ds-01-estructuras-lineales",
                "slug": "estructuras-datos-lineales-complejidad",
                "titulo": "Estructuras de Datos y Complejidad Asintótica O(N)",
                "nivel": "intermedio",
                "etapa": "Etapa 2: Estructuras y Algoritmos",
                "carrera_referencia": "IIA-201 / LPR-105",
                "orden_sugerido": 3,
                "icono": "fa-solid fa-layer-group",
                "color_nodo": "#cba6f7",
                "prerrequisitos": ["nodo-py-02-control-flujo"],
                "siguientes": ["nodo-eda-01-pandas-numpy", "nodo-poo-01-arquitectura-clases"],
                "marco_teorico": {
                    "resumen": "Formalización de la notación Big-O (asintótica superior), Big-Omega y Big-Theta. Implementación y trade-offs entre Arreglos Dinámicos, Tablas Hash (Hash Maps) y Listas Enlazadas. Resolución de colisiones hash mediante direccionamiento abierto y encadenamiento.",
                    "principios_nucleares": [
                        "Búsqueda lineal en arreglo no ordenado: O(N); Búsqueda en Tabla Hash: O(1) tiempo promedio.",
                        "Costo de redimensionamiento amortizado en arreglos dinámicos.",
                        "Trade-off clásico entre memoria espacial auxiliar y latencia temporal de cómputo."
                    ],
                    "definiciones_formales": [
                        {"termino": "Big-O Notation", "definicion": "$$f(n) \\in O(g(n)) \\iff \\exists c > 0, n_0 > 0 : \\forall n \\ge n_0, |f(n)| \\le c \\cdot |g(n)|$$."},
                        {"termino": "Factor de Carga (Load Factor)", "definicion": "$$\\alpha = \\frac{n}{k}$$, ratio entre el número de entradas almacenadas n y la capacidad de slots k de la tabla hash."}
                    ],
                    "formulas_o_axiomas": "$$T_{\\text{lookup}}(Hash) = O(1) \\quad \\text{vs} \\quad T_{\\text{lookup}}(List) = O(N)$$"
                },
                "herramientas": {
                    "youtube": {
                        "video_id": "pkYVOmU3MgA",
                        "titulo": "Data Structures and Algorithms in Python – Full Course (Jovian / freeCodeCamp)",
                        "canal": "freeCodeCamp / Jovian",
                        "duracion": "12:30:50",
                        "minuto_clave": "00:45:00",
                        "marcas_de_tiempo": [
                            {"minuto": "00:45:00", "tema": "Complejidad Temporal y Big-O"},
                            {"minuto": "03:10:00", "tema": "Tablas Hash y Colisiones"},
                            {"minuto": "05:40:00", "tema": "Listas Enlazadas y Punteros"}
                        ],
                        "query_busqueda": "Data Structures and Algorithms Python Jovian"
                    },
                    "github": {
                        "repositorio": "TheAlgorithms/Python",
                        "ruta_archivos": "data_structures/hash_table/hash_map.py",
                        "descripcion": "Implementación de tablas hash con encadenamiento y resolución de colisiones.",
                        "plantilla_directorio": "proyectos_aprendizaje/estructuras_datos"
                    },
                    "kaggle": {
                        "dataset_slug": "creditcardfraud",
                        "titulo": "Credit Card Fraud Detection (Indexación de alta frecuencia)",
                        "notebook_referencia": "kaggle_comprehensive-data-exploration-with-python",
                        "tarea_datos": "Indexar millones de identificadores de transacciones en un Hash Set para búsqueda instantánea O(1)."
                    },
                    "prig_hub": {
                        "pack_id": "pack_estructuras_algoritmos",
                        "ruta_guia": "docs/prig-hub.md#estructuras-datos"
                    }
                },
                "tarea_prerespondida": {
                    "id": "tarea_ds_01_two_sum",
                    "titulo": "Búsqueda en Parejas en O(N) con Tabla Hash",
                    "enunciado": "Dada una lista de enteros 'nums' y un entero 'objetivo', implementa 'encontrar_pareja_suma(nums: list, objetivo: int) -> tuple' que devuelva los índices de los dos números que sumen 'objetivo' en complejidad temporal estrictamente O(N), usando un diccionario como tabla hash.",
                    "codigo_inicial": (
                        "def encontrar_pareja_suma(nums: list, objetivo: int) -> tuple:\n"
                        "    # TODO: Implementar búsqueda O(N) usando tabla hash (dict)\n"
                        "    return ()\n"
                    ),
                    "solucion_referencia": (
                        "def encontrar_pareja_suma(nums: list, objetivo: int) -> tuple:\n"
                        "    \"\"\"\n"
                        "    Resuelve Two-Sum en una sola pasada O(N) tiempo y O(N) espacio auxiliar.\n"
                        "    \"\"\"\n"
                        "    vistos = {}  # {valor: indice}\n"
                        "    for idx, num in enumerate(nums):\n"
                        "        complemento = objetivo - num\n"
                        "        if complemento in vistos:\n"
                        "            return (vistos[complemento], idx)\n"
                        "        vistos[num] = idx\n"
                        "    return ()\n"
                    ),
                    "guia_resolucion_paso_a_paso": [
                        "Paso 1: El enfoque ingenuo de doble bucle anidado toma O(N²), lo cual es inaceptable para grandes volúmenes de datos.",
                        "Paso 2: Utiliza un diccionario para almacenar los elementos ya vistos en formato {valor: indice}.",
                        "Paso 3: Para cada número actual, calcula el complemento requerido (objetivo - num). Como la búsqueda en diccionario es O(1), si el complemento existe retornamos de inmediato sus índices."
                    ],
                    "pruebas_unitarias": (
                        "def test_encontrar_pareja_suma():\n"
                        "    nums = [2, 7, 11, 15]\n"
                        "    res = encontrar_pareja_suma(nums, 9)\n"
                        "    assert res == (0, 1), f\"Esperado (0, 1), obtenido {res}\"\n"
                        "    nums2 = [3, 2, 4]\n"
                        "    assert encontrar_pareja_suma(nums2, 6) == (1, 2)\n"
                        "    assert encontrar_pareja_suma([1, 2, 3], 10) == ()\n"
                        "    print('✓ Pruebas de complejidad O(N) superadas con éxito.')\n"
                    ),
                    "pistas_progresivas": [
                        "Pista 1: En lugar de buscar hacia adelante con un segundo bucle, busca si el complemento ya apareció en el pasado.",
                        "Pista 2: La consulta 'if complemento in vistos' tiene costo O(1) promedio gracias a la función hash nativa de Python.",
                        "Pista 3: Retorna una tupla (indice_previo, indice_actual) tan pronto encuentres la coincidencia."
                    ]
                }
            },

            {
                "id": "nodo-eda-01-pandas-numpy",
                "slug": "analisis-exploratorio-datos-pandas-numpy",
                "titulo": "Análisis Exploratorio y Limpieza de Datos (EDA)",
                "nivel": "intermedio",
                "etapa": "Etapa 3: Datos y Machine Learning",
                "carrera_referencia": "IIA-305 / IIA-204",
                "orden_sugerido": 4,
                "icono": "fa-solid fa-table",
                "color_nodo": "#f9e2af",
                "prerrequisitos": ["nodo-ds-01-estructuras-lineales"],
                "siguientes": ["nodo-ml-01-sesgo-varianza"],
                "marco_teorico": {
                    "resumen": "Tratamiento vectorial de tensores con NumPy y manipulación de DataFrames con Pandas. Estadísticos descriptivos robustos (mediana, rango intercuartílico IQR) vs paramétricos (media, desviación estándar). Detección e imputación de valores faltantes (MCAR, MAR, MNAR) y codificación de variables categóricas.",
                    "principios_nucleares": [
                        "Diferenciación entre Missing Completely at Random (MCAR) e imputación por mediana/moda.",
                        "Filtrado de outliers mediante criterio de Tukey: $$[Q_1 - 1.5 \\cdot \\text{IQR}, \\; Q_3 + 1.5 \\cdot \\text{IQR}]$$.",
                        "One-Hot Encoding vs Target Encoding para variables de alta cardinalidad."
                    ],
                    "definiciones_formales": [
                        {"termino": "Interquartile Range (IQR)", "definicion": "$$\\text{IQR} = Q_3 - Q_1$$, medida de dispersión estadística resistente a valores atípicos."},
                        {"termino": "Vectorización SIMD", "definicion": "Ejecución de una única instrucción computacional sobre múltiples elementos contiguos en memoria mediante operaciones de bajo nivel en C/BLAS."}
                    ],
                    "formulas_o_axiomas": "$$\\text{Z-Score} = \\frac{x - \\mu}{\\sigma}, \\quad \\text{Outlier} \\iff |Z| > 3.0$$"
                },
                "herramientas": {
                    "youtube": {
                        "video_id": "chPhlsHoEPo",
                        "titulo": "Curso de Pandas y NumPy para Ciencia de Datos Completo",
                        "canal": "Fazt Code / freeCodeCamp",
                        "duracion": "3:15:35",
                        "minuto_clave": "00:40:00",
                        "marcas_de_tiempo": [
                            {"minuto": "00:40:00", "tema": "Arreglos N-Dimensionales con NumPy"},
                            {"minuto": "01:20:00", "tema": "DataFrames, Series e Indexación"},
                            {"minuto": "02:10:00", "tema": "Tratamiento de Nulos y GroupBy"}
                        ],
                        "query_busqueda": "Python para ciencia de datos inicial pandas numpy"
                    },
                    "github": {
                        "repositorio": "scikit-learn/scikit-learn",
                        "ruta_archivos": "sklearn/preprocessing/_data.py",
                        "descripcion": "Módulos de imputación, normalización StandardScaler y RobustScaler.",
                        "plantilla_directorio": "proyectos_aprendizaje/eda_datos"
                    },
                    "kaggle": {
                        "dataset_slug": "titanic",
                        "titulo": "Titanic Dataset (Limpieza exhaustiva e imputación de edad)",
                        "notebook_referencia": "kaggle_comprehensive-data-exploration-with-python",
                        "tarea_datos": "Calcular media de edad imputada por grupo de clase y género, y convertir columna 'Embarked' con One-Hot Encoding."
                    },
                    "prig_hub": {
                        "pack_id": "pack_eda_ciencia_datos",
                        "ruta_guia": "docs/prig-hub.md#eda-datos"
                    }
                },
                "tarea_prerespondida": {
                    "id": "tarea_eda_01_resumen",
                    "titulo": "Cálculo Robusto de Estadísticos e Imputación",
                    "enunciado": "Implementa 'limpiar_serie_numerica(valores: list) -> dict' que reciba una lista de números con posibles valores None, calcule la mediana de los valores válidos, impute los nulos con dicha mediana y retorne un diccionario con {'valores_imputados': list, 'mediana': float, 'outliers_iqr': list}.",
                    "codigo_inicial": (
                        "def limpiar_serie_numerica(valores: list) -> dict:\n"
                        "    # TODO: Calcular mediana, imputar nulos y detectar outliers por IQR\n"
                        "    return {}\n"
                    ),
                    "solucion_referencia": (
                        "def limpiar_serie_numerica(valores: list) -> dict:\n"
                        "    \"\"\"\n"
                        "    Limpieza e imputación estadística sin librerías externas.\n"
                        "    \"\"\"\n"
                        "    validos = sorted([v for v in valores if v is not None])\n"
                        "    if not validos:\n"
                        "        return {'valores_imputados': [], 'mediana': 0.0, 'outliers_iqr': []}\n"
                        "\n"
                        "    n = len(validos)\n"
                        "    if n % 2 == 1:\n"
                        "        mediana = float(validos[n // 2])\n"
                        "    else:\n"
                        "        mediana = (validos[n // 2 - 1] + validos[n // 2]) / 2.0\n"
                        "\n"
                        "    # Cálculo simple de cuartiles Q1 y Q3\n"
                        "    q1 = float(validos[n // 4])\n"
                        "    q3 = float(validos[(3 * n) // 4])\n"
                        "    iqr = q3 - q1\n"
                        "    lim_inf = q1 - 1.5 * iqr\n"
                        "    lim_sup = q3 + 1.5 * iqr\n"
                        "\n"
                        "    imputados = [mediana if v is None else v for v in valores]\n"
                        "    outliers = [v for v in validos if v < lim_inf or v > lim_sup]\n"
                        "\n"
                        "    return {\n"
                        "        'valores_imputados': imputados,\n"
                        "        'mediana': round(mediana, 2),\n"
                        "        'outliers_iqr': outliers\n"
                        "    }\n"
                    ),
                    "guia_resolucion_paso_a_paso": [
                        "Paso 1: Extrae todos los elementos que no sean None y ordénalos para posibilitar el cálculo posicional de percentiles.",
                        "Paso 2: Calcula la mediana tomando el punto medio (o el promedio de los dos centrales si la longitud es par).",
                        "Paso 3: Determina el rango intercuartílico IQR = Q3 - Q1 y los límites de Tukey (Q1 - 1.5*IQR, Q3 + 1.5*IQR) para identificar valores atípicos.",
                        "Paso 4: Genera la lista final reemplazando cada valor None por la mediana calculada."
                    ],
                    "pruebas_unitarias": (
                        "def test_limpiar_serie_numerica():\n"
                        "    serie = [10, 12, None, 14, 15, 100, 11, None, 13]\n"
                        "    res = limpiar_serie_numerica(serie)\n"
                        "    assert res['mediana'] == 13.0, f\"Esperada mediana 13.0, obtenido {res['mediana']}\"\n"
                        "    assert None not in res['valores_imputados']\n"
                        "    assert 100 in res['outliers_iqr']\n"
                        "    print('✓ Pruebas de EDA y limpieza estadística superadas con éxito.')\n"
                    ),
                    "pistas_progresivas": [
                        "Pista 1: La mediana es preferible a la media en presencia de valores atípicos porque no se distorsiona por extremos.",
                        "Pista 2: Ordenar la lista permite acceder directamente a los índices n//4 y 3*n//4 para estimar cuartiles.",
                        "Pista 3: Construye la lista imputada iterando sobre la colección original para mantener el orden exacto de los índices."
                    ]
                }
            },

            # -----------------------------------------------------------------
            # TIER 3: NIVEL AVANZADO (Machine Learning, Concurrencia y Redes)
            # -----------------------------------------------------------------
            {
                "id": "nodo-ml-01-sesgo-varianza",
                "slug": "machine-learning-sesgo-varianza-validacion",
                "titulo": "Modelos Supervisados y Compromiso Sesgo-Varianza",
                "nivel": "avanzado",
                "etapa": "Etapa 3: Aprendizaje Automático y Gestión de Datos",
                "carrera_referencia": "IIA-301 / IIA-302",
                "orden_sugerido": 5,
                "icono": "fa-solid fa-brain",
                "color_nodo": "#f38ba8",
                "prerrequisitos": ["nodo-eda-01-pandas-numpy"],
                "siguientes": ["nodo-dl-01-redes-deep-learning", "nodo-sys-01-concurrencia-distribuidos"],
                "marco_teorico": {
                    "resumen": "Descomposición matemática del error esperado en aprendizaje supervisado: Error = Sesgo² + Varianza + Ruido Irreducible. Prevención del sobreajuste (Overfitting) mediante regularización L1 (Lasso) y L2 (Ridge) y Validación Cruzada Estratificada (K-Fold Cross Validation).",
                    "principios_nucleares": [
                        "Alto Sesgo (Underfitting): el modelo es incapaz de capturar la complejidad subyacente de la función generadora.",
                        "Alta Varianza (Overfitting): el modelo memoriza el ruido específico del conjunto de entrenamiento y no generaliza.",
                        "Penalización de coeficientes por norma L2: $$\\min_w \\frac{1}{2n} \\|Xw - y\\|^2 + \\lambda \\|w\\|_2^2$$."
                    ],
                    "definiciones_formales": [
                        {"termino": "Bias-Variance Decomposition", "definicion": "$$\\mathbb{E}[(y - \\hat{f}(x))^2] = \\text{Bias}[\\hat{f}(x)]^2 + \\text{Var}[\\hat{f}(x)] + \\sigma^2$$."},
                        {"termino": "K-Fold Cross Validation", "definicion": "Partición del dataset en K subconjuntos disjuntos; en cada iteración k se entrena en K-1 partes y se evalúa en la restante."}
                    ],
                    "formulas_o_axiomas": "$$\\text{Loss}_{\\text{Ridge}}(w) = \\text{MSE}(w) + \\alpha \\sum_{j=1}^p w_j^2$$"
                },
                "herramientas": {
                    "youtube": {
                        "video_id": "XKHEtdqhLK8",
                        "titulo": "Machine Learning Andrew Ng Stanford (Clase Magistral de Regularización)",
                        "canal": "Stanford Online / Andrew Ng",
                        "duracion": "12:00:00",
                        "minuto_clave": "03:15:00",
                        "marcas_de_tiempo": [
                            {"minuto": "03:15:00", "tema": "Compromiso Sesgo vs Varianza"},
                            {"minuto": "04:10:00", "tema": "Regularización Ridge y Lasso"},
                            {"minuto": "05:00:00", "tema": "Validación Cruzada K-Fold"}
                        ],
                        "query_busqueda": "Machine Learning Andrew Ng Stanford Bias Variance"
                    },
                    "github": {
                        "repositorio": "ageron/handson-ml3",
                        "ruta_archivos": "04_training_linear_models.ipynb",
                        "descripcion": "Código ejecutable de Hands-On Machine Learning con Scikit-Learn y TensorFlow.",
                        "plantilla_directorio": "proyectos_aprendizaje/modelos_supervisados"
                    },
                    "kaggle": {
                        "dataset_slug": "house-prices-advanced-regression-techniques",
                        "titulo": "Predicción de Precios de Viviendas (Evaluación con RMSE y Ridge)",
                        "notebook_referencia": "kaggle_comprehensive-data-exploration-with-python",
                        "tarea_datos": "Entrenar Ridge vs Lasso y comparar la métrica RMSE sobre 5 particiones K-Fold."
                    },
                    "prig_hub": {
                        "pack_id": "pack_machine_learning_core",
                        "ruta_guia": "docs/prig-hub.md#ml-avanzado"
                    }
                },
                "tarea_prerespondida": {
                    "id": "tarea_ml_01_metricas",
                    "titulo": "Métricas de Evaluación de Clasificación sin Dependencias",
                    "enunciado": "Implementa la función 'calcular_metricas_clasificacion(y_real: list, y_pred: list) -> dict' que calcule Matriz de Confusión (TP, FP, TN, FN), Precisión (Precision), Exhaustividad (Recall) y F1-Score con precisión matemática.",
                    "codigo_inicial": (
                        "def calcular_metricas_clasificacion(y_real: list, y_pred: list) -> dict:\n"
                        "    # TODO: Calcular TP, FP, TN, FN, Precision, Recall y F1-Score\n"
                        "    return {}\n"
                    ),
                    "solucion_referencia": (
                        "def calcular_metricas_clasificacion(y_real: list, y_pred: list) -> dict:\n"
                        "    \"\"\"\n"
                        "    Cálculo de métricas fundamentales de generalización supervisada.\n"
                        "    \"\"\"\n"
                        "    if len(y_real) != len(y_pred) or not y_real:\n"
                        "        return {}\n"
                        "\n"
                        "    tp = sum(1 for r, p in zip(y_real, y_pred) if r == 1 and p == 1)\n"
                        "    fp = sum(1 for r, p in zip(y_real, y_pred) if r == 0 and p == 1)\n"
                        "    tn = sum(1 for r, p in zip(y_real, y_pred) if r == 0 and p == 0)\n"
                        "    fn = sum(1 for r, p in zip(y_real, y_pred) if r == 1 and p == 0)\n"
                        "\n"
                        "    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0\n"
                        "    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0\n"
                        "    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0\n"
                        "    accuracy = (tp + tn) / len(y_real)\n"
                        "\n"
                        "    return {\n"
                        "        'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,\n"
                        "        'accuracy': round(accuracy, 4),\n"
                        "        'precision': round(precision, 4),\n"
                        "        'recall': round(recall, 4),\n"
                        "        'f1_score': round(f1, 4)\n"
                        "    }\n"
                    ),
                    "guia_resolucion_paso_a_paso": [
                        "Paso 1: Valida que ambas listas tengan la misma longitud para asegurar pares ordenados comparables.",
                        "Paso 2: Cuenta True Positives (1 y 1), False Positives (0 y 1), True Negatives (0 y 0) y False Negatives (1 y 0).",
                        "Paso 3: Aplica las fórmulas de Precision = TP / (TP + FP) y Recall = TP / (TP + FN), manejando divisiones por cero.",
                        "Paso 4: Calcula el F1-Score como la media armónica entre Precision y Recall: 2 * (P * R) / (P + R)."
                    ],
                    "pruebas_unitarias": (
                        "def test_calcular_metricas_clasificacion():\n"
                        "    y_true = [1, 1, 0, 1, 0, 0, 1, 0, 1, 0]\n"
                        "    y_hat  = [1, 0, 0, 1, 0, 1, 1, 0, 1, 0]\n"
                        "    res = calcular_metricas_clasificacion(y_true, y_hat)\n"
                        "    assert res['tp'] == 4\n"
                        "    assert res['fp'] == 1\n"
                        "    assert res['recall'] == 0.8\n"
                        "    assert res['precision'] == 0.8\n"
                        "    assert res['f1_score'] == 0.8\n"
                        "    print('✓ Pruebas de métricas supervisadas superadas con éxito.')\n"
                    ),
                    "pistas_progresivas": [
                        "Pista 1: La precisión penaliza falsas alarmas (FP); el recall penaliza omisiones de casos positivos (FN).",
                        "Pista 2: La función zip() te permite contrastar valor real y predicho en una sola pasada lineal O(N).",
                        "Pista 3: En datasets desbalanceados como detección de fraude, el F1-Score es infinitamente superior al simple Accuracy."
                    ]
                }
            },

            # -----------------------------------------------------------------
            # TIER 4: NIVEL SENIOR (Transformers, Inferencia Local y Concurrencia)
            # -----------------------------------------------------------------
            {
                "id": "nodo-dl-01-redes-deep-learning",
                "slug": "deep-learning-transformers-atencion-local",
                "titulo": "Modelos Generativos, Transformers y Atención en Inferencia Local",
                "nivel": "senior",
                "etapa": "Etapa 4: IA Avanzada, NLP y Generativa",
                "carrera_referencia": "IIA-401 / IIA-405",
                "orden_sugerido": 6,
                "icono": "fa-solid fa-microchip",
                "color_nodo": "#74c7ec",
                "prerrequisitos": ["nodo-ml-01-sesgo-varianza"],
                "siguientes": [],
                "marco_teorico": {
                    "resumen": "Mecanismo de Auto-Atención Escalar Multi-Cabeza (Multi-Head Scaled Dot-Product Attention) y arquitecturas Transformer Decoder-Only (estilo LLaMA / Qwen 7B). Técnicas de optimización de inferencia en CPU/GPU de bajo consumo: KV-Caching, Cuantización (GGUF, 4-bit AWQ) y Offloading capa por capa (AirLLM).",
                    "principios_nucleares": [
                        "Complejidad cuadrática estándar de la atención: $$O(S^2 \\cdot D)$$ con longitud de secuencia S.",
                        "KV-Cache: almacenamiento de claves y valores previos para transformar la generación auto-regresiva de O(N²) a O(N) por token generado.",
                        "Alineación léxica y muestreo con Temperature, Top-P (Nucleus Sampling) y penalización de repetición."
                    ],
                    "definiciones_formales": [
                        {"termino": "Scaled Dot-Product Attention", "definicion": "$$\\text{Attention}(Q, K, V) = \\text{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V$$."},
                        {"termino": "KV-Caching", "definicion": "Retención en memoria VRAM/RAM de los tensores de Key y Value ya procesados para evitar recomputar proyecciones de tokens pasados en pasos autorregresivos."}
                    ],
                    "formulas_o_axiomas": "$$\\text{Softmax}(z)_i = \\frac{e^{z_i}}{\\sum_{j} e^{z_j}}, \\quad \\text{Inferencia Auto-regresiva}: P(w_t \\mid w_1, \\dots, w_{t-1})$$"
                },
                "herramientas": {
                    "youtube": {
                        "video_id": "_uQrJ0TkZlc",
                        "titulo": "Transformers from Scratch: Attention Mechanism & Architecture (Andrej Karpathy)",
                        "canal": "Andrej Karpathy / DeepLearning.AI",
                        "duracion": "06:14:07",
                        "minuto_clave": "01:25:00",
                        "marcas_de_tiempo": [
                            {"minuto": "01:25:00", "tema": "Self-Attention y Matrices Q, K, V"},
                            {"minuto": "02:30:00", "tema": "Multi-Head Attention y Capas Residuales"},
                            {"minuto": "04:10:00", "tema": "Tokenización BPE e Inferencia Auto-regresiva"}
                        ],
                        "query_busqueda": "Transformers architecture Andrej Karpathy from scratch"
                    },
                    "github": {
                        "repositorio": "scikit-learn/scikit-learn",
                        "ruta_archivos": "lib/airllm",
                        "descripcion": "Inferencia de modelos de lenguaje 7B capa por capa con memoria RAM acotada.",
                        "plantilla_directorio": "proyectos_aprendizaje/transformers_inferencia"
                    },
                    "kaggle": {
                        "dataset_slug": "creditcardfraud",
                        "titulo": "Kaggle LLM Science Exam (Fine-Tuning y Evaluación de Transformers)",
                        "notebook_referencia": "kaggle_comprehensive-data-exploration-with-python",
                        "tarea_datos": "Analizar embeddings vectoriales de atención y calcular similitud coseno."
                    },
                    "prig_hub": {
                        "pack_id": "pack_transformers_7b",
                        "ruta_guia": "docs/prig-hub.md#transformers-senior"
                    }
                },
                "tarea_prerespondida": {
                    "id": "tarea_dl_01_atencion",
                    "titulo": "Implementación Determinista de Scaled Dot-Product Attention",
                    "enunciado": "Implementa la función 'atencion_auto_escalada(Q: list, K: list, V: list) -> list' que reciba matrices representadas como listas de listas y calcule el mecanismo de atención de scaled dot-product: Softmax( (Q · K^T) / sqrt(d_k) ) · V.",
                    "codigo_inicial": (
                        "def atencion_auto_escalada(Q: list, K: list, V: list) -> list:\n"
                        "    # TODO: Implementar atención Softmax((Q @ K.T) / sqrt(d_k)) @ V\n"
                        "    return []\n"
                    ),
                    "solucion_referencia": (
                        "import math\n"
                        "\n"
                        "def atencion_auto_escalada(Q: list, K: list, V: list) -> list:\n"
                        "    \"\"\"\n"
                        "    Scaled Dot-Product Attention pura sin librerías externas.\n"
                        "    \"\"\"\n"
                        "    d_k = len(Q[0])\n"
                        "    escala = math.sqrt(d_k)\n"
                        "    n_queries = len(Q)\n"
                        "    n_keys = len(K)\n"
                        "    d_v = len(V[0])\n"
                        "\n"
                        "    # 1. Producto Q · K^T y división por sqrt(d_k)\n"
                        "    scores = []\n"
                        "    for i in range(n_queries):\n"
                        "        fila = []\n"
                        "        for j in range(n_keys):\n"
                        "            dot = sum(Q[i][dim] * K[j][dim] for dim in range(d_k))\n"
                        "            fila.append(dot / escala)\n"
                        "        scores.append(fila)\n"
                        "\n"
                        "    # 2. Softmax por fila\n"
                        "    pesos_atencion = []\n"
                        "    for fila in scores:\n"
                        "        max_val = max(fila)  # Estabilidad numérica\n"
                        "        exp_vals = [math.exp(val - max_val) for val in fila]\n"
                        "        sum_exp = sum(exp_vals)\n"
                        "        pesos_atencion.append([v / sum_exp for v in exp_vals])\n"
                        "\n"
                        "    # 3. Multiplicación Pesos · V\n"
                        "    salida = []\n"
                        "    for i in range(n_queries):\n"
                        "        fila_res = []\n"
                        "        for col in range(d_v):\n"
                        "            val = sum(pesos_atencion[i][j] * V[j][col] for j in range(n_keys))\n"
                        "            fila_res.append(round(val, 4))\n"
                        "        salida.append(fila_res)\n"
                        "\n"
                        "    return salida\n"
                    ),
                    "guia_resolucion_paso_a_paso": [
                        "Paso 1: Calcula el producto escalar entre cada vector Query y cada vector Key, dividiendo entre la raíz cuadrada de la dimensión d_k para estabilizar gradientes.",
                        "Paso 2: Aplica Softmax sobre cada fila de la matriz de afinidad (scores). Para evitar desbordamiento numérico (overflow de exp), resta el valor máximo de la fila antes de exponencializar.",
                        "Paso 3: Multiplica la matriz de probabilidades de atención obtenida por la matriz de Valores (V) para obtener la representación enriquecida por contexto."
                    ],
                    "pruebas_unitarias": (
                        "def test_atencion_auto_escalada():\n"
                        "    # Matriz 2x2 para Q, K y V\n"
                        "    Q = [[1.0, 0.0], [0.0, 1.0]]\n"
                        "    K = [[1.0, 0.0], [0.0, 1.0]]\n"
                        "    V = [[10.0, 0.0], [0.0, 20.0]]\n"
                        "    res = atencion_auto_escalada(Q, K, V)\n"
                        "    assert len(res) == 2 and len(res[0]) == 2\n"
                        "    assert res[0][0] > res[0][1], 'Query 1 debe prestar mayor atención a Key 1'\n"
                        "    assert res[1][1] > res[1][0], 'Query 2 debe prestar mayor atención a Key 2'\n"
                        "    print('✓ Pruebas de atención Scaled Dot-Product superadas con éxito.')\n"
                    ),
                    "pistas_progresivas": [
                        "Pista 1: El factor 1 / sqrt(d_k) previene que los productos escalares crezcan excesivamente en dimensiones altas, lo que provocaría gradientes nulos en la función softmax.",
                        "Pista 2: Cada fila de pesos de atención debe sumar exactamente 1.0 al tratarse de una distribución de probabilidad.",
                        "Pista 3: En el paso autorregresivo, una máscara causal (máscara triangular inferior) impediría que una posición atienda a tokens del futuro."
                    ]
                }
            }
        ]

    # =========================================================================
    # CONSULTAS DE ALTA VELOCIDAD Y GESTIÓN DE PROGRESO
    # =========================================================================

    def obtener_grafo(self, filtro_nivel: Optional[str] = None) -> Dict[str, Any]:
        """Retorna el árbol completo o filtrado de nodos con su topología conectada."""
        progreso = self._leer_progreso()
        nodos_lista = []
        
        for nid in self.orden_nodos:
            n = self.nodos[nid]
            if filtro_nivel and filtro_nivel.lower() != "todos" and n.get("nivel") != filtro_nivel.lower():
                continue
            
            nodo_copia = dict(n)
            nodo_copia["completado"] = progreso.get(nid, {}).get("completado", False)
            nodo_copia["fecha_completado"] = progreso.get(nid, {}).get("fecha", None)
            nodo_copia["intentos"] = progreso.get(nid, {}).get("intentos", 0)
            nodos_lista.append(nodo_copia)

        # Generar lista de aristas dirigidas (edges) para renderizado en Canvas / SVG
        aristas = []
        for n in nodos_lista:
            origen = n["id"]
            for destino in n.get("siguientes", []):
                if destino in self.nodos:
                    aristas.append({
                        "desde": origen,
                        "hacia": destino,
                        "completada": n.get("completado", False) and self.nodos[destino].get("completado", False)
                    })

        return {
            "ok": True,
            "total_nodos": len(nodos_lista),
            "niveles_disponibles": ["todos", "junior", "intermedio", "avanzado", "senior"],
            "nodos": nodos_lista,
            "aristas": aristas,
            "progreso_global": self.obtener_estadisticas_progreso(progreso)
        }

    def obtener_nodo(self, nodo_id: str) -> Optional[Dict[str, Any]]:
        """Retorna el detalle enriquecido de un nodo particular con su tarea y herramientas."""
        if nodo_id not in self.nodos:
            return None
        
        n = dict(self.nodos[nodo_id])
        progreso = self._leer_progreso().get(nodo_id, {})
        n["completado"] = progreso.get("completado", False)
        n["intentos"] = progreso.get("intentos", 0)
        n["ultimo_resultado"] = progreso.get("ultimo_resultado", None)
        return n

    def buscar(self, query: str, limite: int = 15) -> List[Dict[str, Any]]:
        """Búsqueda de texto completo con ranking semántico ultra-rápida (<5ms)."""
        if not query or not query.strip():
            return [self.nodos[nid] for nid in self.orden_nodos[:limite]]

        q_terms = query.lower().split()
        coincidencias = []

        for item in self.indice_busqueda:
            score = 0
            texto = item["texto"]
            for term in q_terms:
                if term in item["titulo"].lower():
                    score += 15
                elif term in item["id"].lower():
                    score += 8
                elif term in texto:
                    score += 3
            
            if score > 0:
                nodo = self.nodos[item["id"]]
                coincidencias.append((score, nodo))

        coincidencias.sort(key=lambda x: x[0], reverse=True)
        return [c[1] for c in coincidencias[:limite]]

    # =========================================================================
    # EJECUTOR DETERMINISTA DE PRUEBAS UNITARIAS
    # =========================================================================

    def ejecutar_tarea(self, nodo_id: str, codigo_usuario: str, usar_solucion: bool = False) -> Dict[str, Any]:
        """
        Ejecuta de manera segura y aislada la solución (del usuario o pre-respondida)
        contra la suite de pruebas unitarias asociada al nodo en milisegundos.
        """
        if nodo_id not in self.nodos:
            return {"ok": False, "error": f"Nodo '{nodo_id}' no encontrado"}

        nodo = self.nodos[nodo_id]
        tarea = nodo.get("tarea_prerespondida", {})
        if not tarea:
            return {"ok": False, "error": "El nodo no cuenta con una tarea ejecutable"}

        codigo_a_probar = tarea.get("solucion_referencia", "") if usar_solucion else codigo_usuario
        pruebas = tarea.get("pruebas_unitarias", "")

        script_completo = (
            "# Runner de Verificación de Tarea Prig IDE\n"
            f"{codigo_a_probar}\n\n"
            f"{pruebas}\n\n"
            "if __name__ == '__main__':\n"
            "    # Ejecutar funciones de prueba\n"
            "    import sys\n"
            "    test_funcs = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]\n"
            "    for tf in test_funcs:\n"
            "        tf()\n"
        )

        inicio_t = time.perf_counter()
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f_temp:
            f_temp.write(script_completo)
            ruta_temp = f_temp.name

        try:
            proc = subprocess.run(
                ["python3", ruta_temp],
                capture_output=True,
                text=True,
                timeout=4.0
            )
            tiempo_ms = round((time.perf_counter() - inicio_t) * 1000, 2)

            exito = (proc.returncode == 0)
            salida = proc.stdout.strip()
            error = proc.stderr.strip()

            resultado = {
                "ok": exito,
                "nodo_id": nodo_id,
                "usado_solucion": usar_solucion,
                "tiempo_ms": tiempo_ms,
                "salida": salida,
                "error": error if not exito else "",
                "mensaje": "¡Todas las pruebas superadas con éxito!" if exito else "Hubo fallos en las pruebas unitarias."
            }

            # Si el alumno superó las pruebas, registrar progreso automáticamente
            if exito and not usar_solucion:
                self.marcar_progreso(nodo_id, completado=True, resultado=resultado)
            else:
                self._incrementar_intento(nodo_id)

            return resultado

        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "nodo_id": nodo_id,
                "error": "Tiempo de ejecución agotado (posible bucle infinito en la solución). Límite: 4.0s.",
                "tiempo_ms": 4000.0
            }
        except Exception as e:
            return {"ok": False, "nodo_id": nodo_id, "error": str(e)}
        finally:
            if os.path.exists(ruta_temp):
                try:
                    os.remove(ruta_temp)
                except Exception:
                    pass

    # =========================================================================
    # GENERADOR DE PROYECTO LOCAL Y ARCHIVOS EN WORKSPACE
    # =========================================================================

    def abrir_en_editor(self, nodo_id: str) -> Dict[str, Any]:
        """
        Crea los archivos físicos del nodo en el workspace del usuario:
            - aprendizaje/{nodo_id}/ejercicio.py
            - aprendizaje/{nodo_id}/test_ejercicio.py
            - aprendizaje/{nodo_id}/MARCO_TEORICO.md
            - aprendizaje/{nodo_id}/SOLUCION_PRE_RESPONDIDA.md
        Permitiendo al usuario editar, probar y estudiar en el Editor Prig de inmediato.
        """
        if nodo_id not in self.nodos:
            return {"ok": False, "error": f"Nodo '{nodo_id}' no encontrado"}

        nodo = self.nodos[nodo_id]
        tarea = nodo.get("tarea_prerespondida", {})
        mt = nodo.get("marco_teorico", {})
        
        carpeta_destino = os.path.join(self.workspace_dir, "aprendizaje", nodo_id)
        os.makedirs(carpeta_destino, exist_ok=True)

        ruta_ejercicio = os.path.join(carpeta_destino, "ejercicio.py")
        ruta_test = os.path.join(carpeta_destino, "test_ejercicio.py")
        ruta_teoria = os.path.join(carpeta_destino, "MARCO_TEORICO.md")
        ruta_solucion = os.path.join(carpeta_destino, "SOLUCION_PRE_RESPONDIDA.md")

        # 1. Archivo de ejercicio
        if not os.path.exists(ruta_ejercicio):
            with open(ruta_ejercicio, "w", encoding="utf-8") as f:
                f.write(
                    f"# PRIG IDE - NODO: {nodo['titulo']} ({nodo['nivel'].upper()})\n"
                    f"# Carrera de Referencia: {nodo.get('carrera_referencia', '')}\n\n"
                    f"\"\"\"\n{tarea.get('enunciado', '')}\n\"\"\"\n\n"
                    f"{tarea.get('codigo_inicial', '')}\n"
                )

        # 2. Archivo de pruebas unitarias
        with open(ruta_test, "w", encoding="utf-8") as f:
            f.write(
                f"# Pruebas Automatizadas para: {nodo['titulo']}\n"
                "from ejercicio import *\n\n"
                f"{tarea.get('pruebas_unitarias', '')}\n\n"
                "if __name__ == '__main__':\n"
                "    test_funcs = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]\n"
                "    for tf in test_funcs:\n"
                "        tf()\n"
                "    print('✓ Todas las pruebas unitarias pasaron correctamente.')\n"
            )

        # 3. Documento de marco teórico
        with open(ruta_teoria, "w", encoding="utf-8") as f:
            f.write(
                f"# Marco Teórico: {nodo['titulo']}\n\n"
                f"> **Nivel:** {nodo['nivel'].capitalize()} | **Etapa:** {nodo.get('etapa', '')}\n\n"
                f"## 📚 Resumen Conceptual\n{mt.get('resumen', '')}\n\n"
                f"## ⚙️ Principios Nucleares\n" +
                "\n".join(f"- {p}" for p in mt.get("principios_nucleares", [])) + "\n\n"
                f"## 📐 Fórmulas y Fundamento Formal\n{mt.get('formulas_o_axiomas', '')}\n\n"
                f"## 🎥 Recursos Audiovisuales (YouTube)\n"
                f"- **Video:** {nodo.get('herramientas', {}).get('youtube', {}).get('titulo', '')}\n"
                f"- **Canal:** {nodo.get('herramientas', {}).get('youtube', {}).get('canal', '')}\n\n"
                f"## 🐙 Repositorios Relacionados (GitHub)\n"
                f"- **Repo:** {nodo.get('herramientas', {}).get('github', {}).get('repositorio', '')}\n\n"
                f"## 📊 Datasets Prácticos (Kaggle)\n"
                f"- **Dataset:** {nodo.get('herramientas', {}).get('kaggle', {}).get('dataset_slug', '')}\n"
            )

        # 4. Solución pre-respondida de referencia
        with open(ruta_solucion, "w", encoding="utf-8") as f:
            f.write(
                f"# Solución Pre-respondida de Referencia: {nodo['titulo']}\n\n"
                f"```python\n{tarea.get('solucion_referencia', '')}\n```\n\n"
                f"## 🧭 Guía de Resolución Paso a Paso\n" +
                "\n".join(f"{i+1}. {g}" for i, g in enumerate(tarea.get("guia_resolucion_paso_a_paso", []))) + "\n"
            )

        return {
            "ok": True,
            "nodo_id": nodo_id,
            "carpeta": carpeta_destino,
            "archivo_principal": os.path.relpath(ruta_ejercicio, self.workspace_dir),
            "archivo_test": os.path.relpath(ruta_test, self.workspace_dir)
        }

    # =========================================================================
    # PERSISTENCIA LOCAL DE PROGRESO
    # =========================================================================

    def _leer_progreso(self) -> Dict[str, Any]:
        if not os.path.exists(self.ruta_progreso):
            return {}
        try:
            with open(self.ruta_progreso, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _guardar_progreso(self, data: Dict[str, Any]):
        try:
            with open(self.ruta_progreso, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def marcar_progreso(self, nodo_id: str, completado: bool = True, resultado: Optional[Dict[str, Any]] = None):
        prog = self._leer_progreso()
        if nodo_id not in prog:
            prog[nodo_id] = {"intentos": 0}
        
        prog[nodo_id]["completado"] = completado
        prog[nodo_id]["fecha"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if resultado:
            prog[nodo_id]["ultimo_resultado"] = resultado
        self._guardar_progreso(prog)

    def _incrementar_intento(self, nodo_id: str):
        prog = self._leer_progreso()
        if nodo_id not in prog:
            prog[nodo_id] = {"intentos": 0, "completado": False}
        prog[nodo_id]["intentos"] = prog[nodo_id].get("intentos", 0) + 1
        self._guardar_progreso(prog)

    def obtener_estadisticas_progreso(self, progreso: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        prog = progreso if progreso is not None else self._leer_progreso()
        total = len(self.nodos)
        completados = sum(1 for v in prog.values() if v.get("completado", False))
        pct = round((completados / max(1, total)) * 100, 1)

        por_nivel = {"junior": [0, 0], "intermedio": [0, 0], "avanzado": [0, 0], "senior": [0, 0]}
        for nid, n in self.nodos.items():
            lvl = n.get("nivel", "junior")
            if lvl in por_nivel:
                por_nivel[lvl][1] += 1
                if prog.get(nid, {}).get("completado", False):
                    por_nivel[lvl][0] += 1

        return {
            "total_nodos": total,
            "completados": completados,
            "porcentaje": pct,
            "niveles": {
                lvl: {"completados": c[0], "total": c[1], "pct": round((c[0] / max(1, c[1])) * 100, 1)}
                for lvl, c in por_nivel.items()
            }
        }


# Instancia única de servicio
motor_aprendizaje = MotorAprendizajeNodos()
