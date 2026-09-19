"""
Desafíos de internet que se pueden copiar legalmente.

Se eligieron por su licencia, no solo por ser gratis:

    Exercism (pista de Python)  MIT             enunciado, código de partida, tests y
                                                solución de referencia → verificable
    TheAlgorithms/Python        MIT             algoritmos clásicos con doctests →
                                                verificable con los ejemplos del docstring
    Project Euler               CC BY-NC-SA 4.0 problemas matemáticos; sin respuestas
                                                publicadas → sin comprobación automática

No se copian LeetCode, HackerRank ni Codewars: sus condiciones no lo permiten (Codewars
prohíbe expresamente copiar o traducir su contenido).

Todo se descarga de las URL «raw» de GitHub y de la vista mínima de Project Euler, y se
guarda en disco: el índice una semana, cada ejercicio un mes.
"""

import ast
import csv
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import ejecucion
from .almacen import carpeta_base
from .ejecucion import ErrorDesafio

UA = {"User-Agent": "Prig-IDE (desafios de programacion; uso educativo local)"}
SEMANA = 7 * 86400
MES = 30 * 86400


# ===========================================================================
# Descargas con caché en disco
# ===========================================================================

def _cache_dir() -> str:
    try:
        d = os.path.join(carpeta_base(), "cache")
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        import tempfile
        d = os.path.join(tempfile.gettempdir(), "prig_desafios_cache")
        os.makedirs(d, exist_ok=True)
        return d


def descargar(url: str, ttl: float, obligatorio: bool = True) -> Optional[str]:
    """ Texto de `url`, desde la caché si es reciente. Si no hay red, sirve la copia vieja. """
    ruta = os.path.join(_cache_dir(), hashlib.sha1(url.encode()).hexdigest() + ".txt")
    if os.path.exists(ruta) and time.time() - os.path.getmtime(ruta) < ttl:
        with open(ruta, encoding="utf-8") as f:
            texto = f.read()
        return None if texto == "\x00404" else texto
    try:
        r = requests.get(url, headers=UA, timeout=25)
    except requests.RequestException as e:
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                texto = f.read()
            return None if texto == "\x00404" else texto
        raise ErrorDesafio(f"Sin conexión con {url.split('/')[2]}: {e}")
    if r.status_code == 404:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("\x00404")
        if obligatorio:
            raise ErrorDesafio(f"No existe: {url}")
        return None
    if r.status_code != 200:
        raise ErrorDesafio(f"{url.split('/')[2]} respondió {r.status_code}")
    r.encoding = "utf-8"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(r.text)
    return r.text


# ===========================================================================
# Búsqueda por tema (también en castellano)
# ===========================================================================

def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


# frase (normalizada) → etiquetas en el vocabulario de las fuentes
SINONIMOS: Dict[str, List[str]] = {
    "recursion": ["recursion"], "recursividad": ["recursion"], "recursivo": ["recursion"], "recursiva": ["recursion"],
    "comprension de listas": ["list-comprehensions"], "comprensiones": ["list-comprehensions", "other-comprehensions"],
    "list comprehension": ["list-comprehensions"],
    "lista": ["lists", "list-methods"], "listas": ["lists", "list-methods"], "arreglo": ["lists"], "arreglos": ["lists"],
    "array": ["lists"], "vector": ["lists"],
    "diccionario": ["dicts", "dict-methods", "hashes"], "diccionarios": ["dicts", "dict-methods", "hashes"],
    "hash": ["dicts", "hashes"], "mapa": ["dicts"],
    "conjunto": ["sets"], "conjuntos": ["sets"], "tupla": ["tuples"], "tuplas": ["tuples"],
    "cadena": ["strings", "string-methods"], "cadenas": ["strings", "string-methods"], "texto": ["strings"],
    "string": ["strings"], "formato": ["string-formatting"],
    "bucle": ["loops", "iteration"], "bucles": ["loops", "iteration"], "ciclo": ["loops"], "ciclos": ["loops"],
    "iteracion": ["iteration", "loops"], "for": ["loops"], "while": ["loops"],
    "condicional": ["conditionals", "bools"], "condicionales": ["conditionals", "bools"], "if": ["conditionals"],
    "booleano": ["bools"], "booleanos": ["bools", "boolean-algebra"], "logica": ["bools", "boolean-algebra"],
    "comparacion": ["comparisons"], "comparaciones": ["comparisons"],
    "numero": ["numbers", "maths"], "numeros": ["numbers", "maths"], "matematica": ["maths"], "matematicas": ["maths"],
    "aritmetica": ["numbers", "maths"], "primo": ["prime", "maths"], "primos": ["prime", "maths"],
    "funcion": ["functions", "function-arguments"], "funciones": ["functions", "function-arguments"],
    "argumentos": ["function-arguments"], "parametros": ["function-arguments"],
    "orden superior": ["higher-order-functions"], "lambda": ["anonymous-functions", "higher-order-functions"],
    "clase": ["classes"], "clases": ["classes", "class-inheritance", "class-composition"],
    "objeto": ["classes"], "objetos": ["classes"], "poo": ["classes", "class-inheritance", "class-composition"],
    "programacion orientada a objetos": ["classes", "class-inheritance", "class-composition"],
    "herencia": ["class-inheritance"], "composicion": ["class-composition"],
    "excepcion": ["raising-and-handling-errors", "user-defined-errors"],
    "excepciones": ["raising-and-handling-errors", "user-defined-errors"], "errores": ["raising-and-handling-errors"],
    "generador": ["generators", "generator-expressions"], "generadores": ["generators", "generator-expressions"],
    "iterador": ["iterators"], "iteradores": ["iterators"], "decorador": ["decorators"], "decoradores": ["decorators"],
    "expresiones regulares": ["regular-expressions"], "regex": ["regular-expressions"],
    "enumeracion": ["enums"], "desempaquetado": ["unpacking-and-multiple-assignment"],
    "busqueda": ["searches", "binary-search"], "buscar": ["searches"], "busqueda binaria": ["binary-search", "searches"],
    "binaria": ["binary-search"], "ordenamiento": ["sorts"], "ordenar": ["sorts"], "ordenacion": ["sorts"],
    "grafo": ["graphs"], "grafos": ["graphs"], "arbol": ["data-structures", "binary-tree", "tree"],
    "arboles": ["data-structures", "binary-tree", "tree"], "pila": ["data-structures", "stack"],
    "cola": ["data-structures", "queue"], "lista enlazada": ["data-structures", "linked-list"],
    "estructuras de datos": ["data-structures"], "estructura de datos": ["data-structures"],
    "heap": ["data-structures", "heap"], "monticulo": ["data-structures", "heap"],
    "programacion dinamica": ["dynamic-programming"], "dinamica": ["dynamic-programming"],
    "memoizacion": ["dynamic-programming"], "voraz": ["greedy-methods"], "voraces": ["greedy-methods"],
    "greedy": ["greedy-methods"], "backtracking": ["backtracking"], "vuelta atras": ["backtracking"],
    "divide y venceras": ["divide-and-conquer"], "mochila": ["knapsack"],
    "bits": ["bit-manipulation"], "binario": ["bit-manipulation", "conversions"], "conversion": ["conversions"],
    "cifrado": ["ciphers"], "criptografia": ["ciphers"], "compresion": ["data-compression"],
    "matriz": ["matrix", "linear-algebra"], "matrices": ["matrix", "linear-algebra"],
    "geometria": ["geometry"], "algoritmos": ["searches", "sorts"], "algoritmo": ["searches", "sorts"],
    "fibonacci": ["fibonacci"], "factorial": ["factorial"], "palindromo": ["palindrome"],
    "burbuja": ["sorts", "bubble"], "insercion": ["sorts", "insertion"], "seleccion": ["sorts", "selection"],
    "quicksort": ["sorts", "quick"], "rapido": ["quick"], "mezcla": ["sorts", "merge"], "merge sort": ["sorts", "merge"],
    "anchura": ["graphs", "breadth-first"], "profundidad": ["graphs", "depth-first"], "camino mas corto": ["graphs", "dijkstra"],
    "parentesis": ["balanced-parentheses", "matching-brackets"], "anagrama": ["anagram"], "subcadena": ["substring"],
    "puntero": ["pointers", "memory"], "punteros": ["pointers", "memory"], "referencia": ["references"],
    "referencias": ["references"], "template": ["templates", "generics"], "templates": ["templates", "generics"],
    "stl": ["containers", "standard-library"], "vector": ["lists", "vectors"], "c++": ["cpp", "c++"], "cpp": ["cpp", "c++"],
}
VACIAS = set("de la el los las un una y o en a con para por que del al como sobre practicar quiero ejercicio "
             "ejercicios desafio desafios python nivel basico intermedio avanzado principiante the of and to".split())


def terminos(consulta: str, extra: Optional[List[str]] = None) -> Tuple[set, set]:
    """ (etiquetas, palabras) de una consulta en castellano o inglés """
    q = normalizar(consulta)
    etiquetas, palabras = set(), set()
    for frase in sorted(SINONIMOS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(frase)}\b", q):
            etiquetas.update(SINONIMOS[frase])
    for texto in [q] + [normalizar(e) for e in (extra or [])]:
        for p in texto.split():
            if len(p) >= 3 and p not in VACIAS:
                palabras.add(p)
                if p.endswith("s") and len(p) > 4:
                    palabras.add(p[:-1])
    for e in extra or []:
        etiquetas.add(normalizar(e).replace(" ", "-"))
    return etiquetas, palabras


def _nivel_por(valor: Optional[int], cortes: Tuple[int, int]) -> str:
    if valor is None:
        return "intermedio"
    return "principiante" if valor <= cortes[0] else "intermedio" if valor <= cortes[1] else "avanzado"


# ===========================================================================
# Exercism
# ===========================================================================

class Exercism:
    ID = "exercism"
    NOMBRE = "Exercism"
    RAW = "https://raw.githubusercontent.com/exercism/python/main"
    LICENCIA = "MIT"

    def indice(self) -> List[Dict[str, Any]]:
        cfg = json.loads(descargar(f"{self.RAW}/config.json", SEMANA))
        salida = []
        for tipo in ("concept", "practice"):
            for e in cfg["exercises"].get(tipo, []):
                if e.get("status") in ("deprecated", "wip") or e["slug"] == "hello-world":
                    continue
                principales = e.get("practices") or e.get("concepts") or []
                salida.append({
                    "fuente": self.ID, "ref": f"{tipo}/{e['slug']}", "titulo": e["name"],
                    "etiquetas": principales, "previas": e.get("prerequisites") or [],
                    "palabras": normalizar(e["slug"] + " " + e["name"]).split(),
                    "nivel": "principiante" if tipo == "concept" else _nivel_por(e.get("difficulty"), (2, 5)),
                    "tipo": "concepto" if tipo == "concept" else "práctica", "verificable": True,
                    "url": f"https://exercism.org/tracks/python/exercises/{e['slug']}", "licencia": self.LICENCIA,
                })
        return salida

    @staticmethod
    def _admoniciones(md: str) -> str:
        """ ~~~~exercism/note … ~~~~ → cita en markdown """
        def cambiar(m):
            tipo = {"note": "Nota", "caution": "Cuidado", "tip": "Consejo", "advanced": "Avanzado"}.get(m.group(1), m.group(1).capitalize())
            cuerpo = "\n".join("> " + l for l in m.group(2).strip().splitlines())
            return f"> **{tipo}**\n>\n{cuerpo}\n"
        return re.sub(r"~~~~exercism/(\w+)\n(.*?)\n~~~~", cambiar, md or "", flags=re.S)

    def cargar(self, ref: str) -> Dict[str, Any]:
        if not re.fullmatch(r"(concept|practice)/[a-z0-9\-]+", ref or ""):
            raise ErrorDesafio("Ejercicio de Exercism no válido")
        tipo, slug = ref.split("/")
        base = f"{self.RAW}/exercises/{tipo}/{slug}"
        meta = json.loads(descargar(f"{base}/.meta/config.json", MES))
        archivos = meta.get("files") or {}
        solucion = archivos.get("solution") or []
        pruebas = archivos.get("test") or []
        ejemplo = archivos.get("example") or archivos.get("exemplar") or []
        editor = archivos.get("editor") or []
        if not solucion or not pruebas or not ejemplo:
            raise ErrorDesafio(f"«{slug}» no trae código de partida, pruebas y solución.")

        paginas = [{"nombre": os.path.basename(n), "contenido": descargar(f"{base}/{n}", MES), "descripcion": ""} for n in solucion]
        paginas += [{"nombre": os.path.basename(n), "contenido": descargar(f"{base}/{n}", MES),
                     "descripcion": "Página de apoyo: no hace falta cambiarla.", "solo_lectura": True} for n in editor]
        referencia = []
        for i, n in enumerate(ejemplo):
            destino = os.path.basename(n) if os.path.basename(n) in {os.path.basename(s) for s in solucion} else os.path.basename(solucion[min(i, len(solucion) - 1)])
            referencia.append({"nombre": destino, "contenido": descargar(f"{base}/{n}", MES)})
        referencia += [p for p in paginas if p.get("solo_lectura")]
        tests = {os.path.basename(n): descargar(f"{base}/{n}", MES) for n in pruebas}

        docs = {n: descargar(f"{base}/.docs/{n}", MES, obligatorio=False)
                for n in ("introduction.md", "instructions.md", "instructions.append.md", "hints.md")}
        enunciado = "\n\n".join(self._admoniciones(docs[n]) for n in ("instructions.md", "instructions.append.md") if docs[n])
        teoria = self._admoniciones(docs["introduction.md"] or "")
        indice = {e["ref"]: e for e in self.indice()}
        e = indice.get(ref, {})
        autores = (meta.get("authors") or []) + (meta.get("contributors") or [])
        return {
            "titulo": e.get("titulo") or slug.replace("-", " ").title(),
            "enunciado": enunciado.strip(), "teoria": teoria.strip(), "idioma": "en",
            "nivel": e.get("nivel", "intermedio"), "conceptos": (e.get("etiquetas") or []) + (e.get("previas") or [])[:3],
            "paginas": paginas,
            "comprobacion": {"tipo": "unittest", "pruebas_visibles": False},
            "origen": {"tipo": self.ID, "nombre": "Exercism · pista de Python", "ref": ref, "url": e.get("url") or f"https://exercism.org/tracks/python/exercises/{slug}",
                       "codigo": f"https://github.com/exercism/python/tree/main/exercises/{tipo}/{slug}",
                       "licencia": self.LICENCIA, "autores": autores[:8],
                       "atribucion": "Ejercicio de Exercism (github.com/exercism/python), licencia MIT."},
            "privado": {"comprobacion": {"tipo": "unittest", "archivos": tests}, "referencia": referencia,
                        "pistas_fuente": self._admoniciones(docs["hints.md"] or "")},
        }


class ExercismCpp:
    ID = "exercism_cpp"
    NOMBRE = "Exercism (C++)"
    RAW = "https://raw.githubusercontent.com/exercism/cpp/main"
    LICENCIA = "MIT"
    LENGUAJE = "cpp"

    def indice(self) -> List[Dict[str, Any]]:
        cfg = json.loads(descargar(f"{self.RAW}/config.json", SEMANA))
        salida = []
        for tipo in ("concept", "practice"):
            for e in cfg["exercises"].get(tipo, []):
                if e.get("status") in ("deprecated", "wip") or e["slug"] == "hello-world":
                    continue
                principales = e.get("practices") or e.get("concepts") or []
                salida.append({
                    "fuente": self.ID, "ref": f"{tipo}/{e['slug']}", "titulo": f"{e['name']} (C++)",
                    "etiquetas": principales + ["cpp", "c++"], "previas": e.get("prerequisites") or [],
                    "palabras": normalizar(e["slug"] + " " + e["name"] + " cpp c++").split(),
                    "nivel": "principiante" if tipo == "concept" else _nivel_por(e.get("difficulty"), (2, 5)),
                    "tipo": "concepto" if tipo == "concept" else "práctica", "verificable": True,
                    "lenguaje": "cpp",
                    "url": f"https://exercism.org/tracks/cpp/exercises/{e['slug']}", "licencia": self.LICENCIA,
                })
        return salida

    def cargar(self, ref: str) -> Dict[str, Any]:
        if not re.fullmatch(r"(concept|practice)/[a-z0-9\-]+", ref or ""):
            raise ErrorDesafio("Ejercicio de Exercism no válido")
        tipo, slug = ref.split("/")
        base = f"{self.RAW}/exercises/{tipo}/{slug}"
        meta = json.loads(descargar(f"{base}/.meta/config.json", MES))
        archivos = meta.get("files") or {}
        solucion = archivos.get("solution") or []
        pruebas = archivos.get("test") or []
        ejemplo = archivos.get("example") or archivos.get("exemplar") or []
        editor = archivos.get("editor") or []
        if not solucion or not pruebas or not ejemplo:
            raise ErrorDesafio(f"«{slug}» no trae código de partida, pruebas y solución.")

        paginas = [{"nombre": os.path.basename(n), "contenido": descargar(f"{base}/{n}", MES), "descripcion": ""} for n in solucion]
        paginas += [{"nombre": os.path.basename(n), "contenido": descargar(f"{base}/{n}", MES),
                     "descripcion": "Página de apoyo: no hace falta cambiarla.", "solo_lectura": True} for n in editor]
        referencia = []
        for i, n in enumerate(ejemplo):
            destino = os.path.basename(n) if os.path.basename(n) in {os.path.basename(s) for s in solucion} else os.path.basename(solucion[min(i, len(solucion) - 1)])
            referencia.append({"nombre": destino, "contenido": descargar(f"{base}/{n}", MES)})
        referencia += [p for p in paginas if p.get("solo_lectura")]
        tests = {os.path.basename(n): descargar(f"{base}/{n}", MES) for n in pruebas}

        docs = {n: descargar(f"{base}/.docs/{n}", MES, obligatorio=False)
                for n in ("introduction.md", "instructions.md", "instructions.append.md", "hints.md")}
        enunciado = "\n\n".join(Exercism._admoniciones(docs[n]) for n in ("instructions.md", "instructions.append.md") if docs[n])
        teoria = Exercism._admoniciones(docs["introduction.md"] or "")
        indice = {e["ref"]: e for e in self.indice()}
        e = indice.get(ref, {})
        autores = (meta.get("authors") or []) + (meta.get("contributors") or [])
        return {
            "titulo": e.get("titulo") or f"{slug.replace('-', ' ').title()} (C++)",
            "enunciado": enunciado.strip(), "teoria": teoria.strip(), "idioma": "en",
            "nivel": e.get("nivel", "intermedio"), "conceptos": (e.get("etiquetas") or []) + (e.get("previas") or [])[:3],
            "paginas": paginas,
            "lenguaje": "cpp",
            "comprobacion": {"tipo": "cpp_test", "pruebas_visibles": False},
            "origen": {"tipo": self.ID, "nombre": "Exercism · pista de C++", "ref": ref, "url": e.get("url") or f"https://exercism.org/tracks/cpp/exercises/{slug}",
                       "codigo": f"https://github.com/exercism/cpp/tree/main/exercises/{tipo}/{slug}",
                       "licencia": self.LICENCIA, "autores": autores[:8], "lenguaje": "cpp",
                       "atribucion": "Ejercicio de Exercism (github.com/exercism/cpp), licencia MIT."},
            "privado": {"comprobacion": {"tipo": "cpp_test", "archivos": tests}, "referencia": referencia,
                        "pistas_fuente": Exercism._admoniciones(docs["hints.md"] or "")},
        }


# ===========================================================================
# TheAlgorithms/Python
# ===========================================================================

class TheAlgorithms:
    ID = "thealgorithms"
    NOMBRE = "TheAlgorithms"
    RAW = "https://raw.githubusercontent.com/TheAlgorithms/Python/master"
    LICENCIA = "MIT"
    # Categorías que necesitan numpy, red, imágenes o sonido, o que no son ejercicios
    EXCLUIDAS = {"audio_filters", "computer_vision", "digital_image_processing", "file_transfer", "fractals",
                 "graphics", "machine_learning", "neural_network", "quantum", "web_programming", "docs",
                 "project_euler", "scripts", "tests", "genetic_algorithm", "fuzzy_logic", "linear_programming",
                 "blockchain", "networking_flow"}

    def indice(self) -> List[Dict[str, Any]]:
        texto = descargar(f"{self.RAW}/DIRECTORY.md", SEMANA)
        salida, categoria, sub = [], None, None
        for linea in texto.splitlines():
            m = re.match(r"^## \[([^\]]+)\]\(([^)]+)\)", linea)
            if m:
                categoria, sub = m.group(2).strip("/"), None
                continue
            if not categoria or categoria in self.EXCLUIDAS:
                continue
            m = re.match(r"^\s*\* \[([^\]]+)\]\((?:https://github\.com/TheAlgorithms/Python/blob/master/)?([^)]+\.py)\)", linea)
            if m:
                ruta = m.group(2)
                if "/tests/" in ruta or os.path.basename(ruta).startswith("__"):
                    continue
                salida.append({
                    "fuente": self.ID, "ref": ruta, "titulo": m.group(1),
                    "etiquetas": [categoria.replace("_", "-")] + ([sub] if sub else []), "previas": [],
                    "palabras": normalizar(m.group(1) + " " + os.path.basename(ruta)[:-3] + " " + (sub or "")).split(),
                    "nivel": "avanzado" if categoria in ("dynamic_programming", "graphs", "backtracking") else "intermedio",
                    "tipo": categoria.replace("_", " "), "verificable": True,
                    "url": f"https://github.com/TheAlgorithms/Python/blob/master/{ruta}", "licencia": self.LICENCIA,
                })
                continue
            m = re.match(r"^\s*\* ([^\[\]]+)$", linea)
            if m:
                sub = normalizar(m.group(1)).replace(" ", "-")
        return salida

    @staticmethod
    def _solo_biblioteca_estandar(arbol: ast.AST) -> Optional[str]:
        for nodo in ast.walk(arbol):
            modulos = []
            if isinstance(nodo, ast.Import):
                modulos = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                modulos = [nodo.module]
            for m in modulos:
                raiz = m.split(".")[0]
                # pytest solo se usa para marcar pruebas; en la carpeta de ejecución hay un sustituto
                if raiz not in sys.stdlib_module_names and raiz not in ("__future__", "pytest"):
                    return raiz
        return None

    @staticmethod
    def _nombres_usados(nodo: ast.AST, docstring: str) -> set:
        usados = {n.id for n in ast.walk(nodo) if isinstance(n, ast.Name)}
        usados |= {n.attr for n in ast.walk(nodo) if isinstance(n, ast.Attribute)}
        for linea in docstring.splitlines():
            if linea.strip().startswith((">>>", "...")):
                usados |= set(re.findall(r"[A-Za-z_]\w*", linea))
        return usados

    def cargar(self, ref: str, funcion: Optional[str] = None) -> Dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9_]+(?:/[a-z0-9_]+)*\.py", ref or "") or ".." in ref:
            raise ErrorDesafio("Archivo de TheAlgorithms no válido")
        fuente = descargar(f"{self.RAW}/{ref}", MES)
        try:
            arbol = ast.parse(fuente)
        except SyntaxError:
            raise ErrorDesafio("No se pudo leer ese archivo.")
        externa = self._solo_biblioteca_estandar(arbol)
        if externa:
            raise ErrorDesafio(f"Este algoritmo usa «{externa}», que no viene con Python: elige otro.")

        definiciones = {n.name: n for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for n in arbol.body:
            if isinstance(n, (ast.Assign, ast.AnnAssign)):
                objetivos = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in objetivos:
                    if isinstance(t, ast.Name) and not t.id.startswith("__"):
                        definiciones.setdefault(t.id, n)
        candidatas = []
        for n in arbol.body:
            doc = ast.get_docstring(n) if isinstance(n, ast.FunctionDef) else None
            if doc and ">>>" in doc and not n.name.startswith("_") and n.name != "main":
                candidatas.append((doc.count(">>>"), n))
        if not candidatas:
            raise ErrorDesafio("Este archivo no tiene funciones con ejemplos comprobables.")
        if funcion:
            elegida = next((n for _, n in candidatas if n.name == funcion), None)
            if elegida is None:
                raise ErrorDesafio(f"No hay una función «{funcion}» con ejemplos en ese archivo.")
        else:
            # La primera con varios ejemplos: suele ser la principal del archivo
            elegida = next((n for c, n in candidatas if c >= 3), candidatas[0][1])
        doc = ast.get_docstring(elegida)

        # Qué más hace falta: definiciones que usa la función o sus ejemplos (transitivo)
        necesarias, pendientes = set(), [elegida]
        while pendientes:
            actual = pendientes.pop()
            doc_actual = (ast.get_docstring(actual) or "") if isinstance(actual, (ast.FunctionDef, ast.ClassDef)) else ""
            for nombre in self._nombres_usados(actual, doc_actual):
                if nombre in definiciones and nombre != elegida.name and nombre not in necesarias:
                    necesarias.add(nombre)
                    pendientes.append(definiciones[nombre])
        lineas = fuente.splitlines()

        def texto(nodo):
            inicio = (nodo.decorator_list[0].lineno if getattr(nodo, "decorator_list", None) else nodo.lineno) - 1
            return "\n".join(lineas[inicio:nodo.end_lineno])

        cabecera = [texto(n) for n in arbol.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        # Solo lo que la función necesita, en el orden del archivo (una constante puede usar otra)
        usados = {id(definiciones[n]) for n in necesarias}
        apoyo = [texto(n) for n in arbol.body if id(n) in usados]
        constantes = []

        cuerpo_inicio = elegida.body[1].lineno - 1 if len(elegida.body) > 1 else elegida.body[0].end_lineno
        firma_y_doc = "\n".join(lineas[(elegida.decorator_list[0].lineno if elegida.decorator_list else elegida.lineno) - 1:cuerpo_inicio])
        sangria = " " * (elegida.body[0].col_offset)
        partida = f"{firma_y_doc}\n{sangria}# Escribe aquí tu solución\n{sangria}raise NotImplementedError\n"
        completa = texto(elegida)

        def pagina(principal):
            bloques = cabecera + constantes + apoyo + [principal]
            return "\n\n\n".join(b for b in bloques if b.strip()) + "\n"

        modulo = re.sub(r"\W", "_", os.path.basename(ref)[:-3])
        if not re.match(r"[A-Za-z_]", modulo):
            modulo = "algoritmo_" + modulo
        nombre = modulo + ".py"
        prosa = doc.split(">>>")[0].strip()
        ejemplos = "\n".join(l for l in doc.splitlines() if l.strip())
        ejemplos = ejemplos[ejemplos.find(">>>"):]
        firma = lineas[elegida.lineno - 1].strip()
        e = next((x for x in self.indice() if x["ref"] == ref), {})
        enunciado = (f"{prosa}\n\n**Implement** `{elegida.name}` in the page `{nombre}`.\n\n"
                     f"```python\n{firma}\n```\n\n**Examples** (these are also the tests):\n\n```python\n{ejemplos}\n```")
        return {
            "titulo": f"{e.get('titulo') or modulo.replace('_', ' ').title()} · {elegida.name}",
            "enunciado": enunciado, "teoria": "", "idioma": "en",
            "nivel": e.get("nivel", "intermedio"), "conceptos": e.get("etiquetas") or [],
            "paginas": [{"nombre": nombre, "contenido": pagina(partida), "descripcion": ""}],
            "comprobacion": {"tipo": "doctest", "pruebas_visibles": True},
            "origen": {"tipo": self.ID, "nombre": "TheAlgorithms/Python", "ref": ref, "funcion": elegida.name,
                       "url": f"https://github.com/TheAlgorithms/Python/blob/master/{ref}", "licencia": self.LICENCIA,
                       "otras_funciones": [n.name for _, n in candidatas if n.name != elegida.name][:10],
                       "atribucion": "Algoritmo de TheAlgorithms/Python (github.com/TheAlgorithms/Python), licencia MIT."},
            "privado": {"comprobacion": {"tipo": "doctest", "modulo": modulo, "ejemplos": ejemplos},
                        "referencia": [{"nombre": nombre, "contenido": pagina(completa)}]},
        }


# ===========================================================================
# TheAlgorithms/C-Plus-Plus
# ===========================================================================

class TheAlgorithmsCpp:
    ID = "thealgorithms_cpp"
    NOMBRE = "TheAlgorithms (C++)"
    RAW = "https://raw.githubusercontent.com/TheAlgorithms/C-Plus-Plus/master"
    LICENCIA = "MIT"
    LENGUAJE = "cpp"
    EXCLUIDAS = {"docs", "scripts", "build", "cmake"}

    def indice(self) -> List[Dict[str, Any]]:
        texto = descargar(f"{self.RAW}/DIRECTORY.md", SEMANA, obligatorio=False)
        salida = []
        if not texto:
            return salida
        categoria, sub = None, None
        for linea in texto.splitlines():
            m = re.match(r"^## \[([^\]]+)\]\(([^)]+)\)", linea)
            if m:
                categoria, sub = m.group(2).strip("/"), None
                continue
            if not categoria or categoria in self.EXCLUIDAS:
                continue
            m = re.match(r"^\s*\* \[([^\]]+)\]\((?:https://github\.com/TheAlgorithms/C-Plus-Plus/blob/master/)?([^)]+\.cpp)\)", linea)
            if m:
                ruta = m.group(2)
                salida.append({
                    "fuente": self.ID, "ref": ruta, "titulo": f"{m.group(1)} (C++)",
                    "etiquetas": [categoria.replace("_", "-"), "cpp", "c++"] + ([sub] if sub else []), "previas": [],
                    "palabras": normalizar(m.group(1) + " " + os.path.basename(ruta)[:-4] + " cpp c++ " + (sub or "")).split(),
                    "nivel": "avanzado" if categoria in ("dynamic_programming", "graphs", "backtracking") else "intermedio",
                    "tipo": categoria.replace("_", " "), "verificable": False, "lenguaje": "cpp",
                    "url": f"https://github.com/TheAlgorithms/C-Plus-Plus/blob/master/{ruta}", "licencia": self.LICENCIA,
                })
                continue
        return salida

    def cargar(self, ref: str) -> Dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9_]+(?:/[a-z0-9_]+)*\.cpp", ref or "", re.I) or ".." in ref:
            raise ErrorDesafio("Archivo de TheAlgorithms C++ no válido")
        fuente = descargar(f"{self.RAW}/{ref}", MES)
        nombre = os.path.basename(ref)
        e = next((x for x in self.indice() if x["ref"] == ref), {})
        return {
            "titulo": e.get("titulo") or nombre.replace(".cpp", "").replace("_", " ").title(),
            "enunciado": f"Implementa y experimenta con el algoritmo `{nombre}` de TheAlgorithms C++.\n\n"
                         f"Examina el archivo de partida, adapta la solución y ejecuta tu código.",
            "teoria": "", "idioma": "en", "nivel": e.get("nivel", "intermedio"),
            "conceptos": e.get("etiquetas") or ["cpp"],
            "paginas": [{"nombre": nombre, "contenido": fuente, "descripcion": "Código de partida en C++"}],
            "lenguaje": "cpp",
            "comprobacion": {"tipo": "ninguna", "pruebas_visibles": False},
            "origen": {"tipo": self.ID, "nombre": "TheAlgorithms · C++", "ref": ref,
                       "url": f"https://github.com/TheAlgorithms/C-Plus-Plus/blob/master/{ref}", "licencia": self.LICENCIA,
                       "lenguaje": "cpp",
                       "atribucion": "Algoritmo de TheAlgorithms/C-Plus-Plus, licencia MIT."},
            "privado": {"comprobacion": {"tipo": "ninguna"}, "referencia": [{"nombre": nombre, "contenido": fuente}]},
        }


# ===========================================================================
# Project Euler
# ===========================================================================

class ProjectEuler:
    ID = "projecteuler"
    NOMBRE = "Project Euler"
    LICENCIA = "CC BY-NC-SA 4.0"

    def indice(self) -> List[Dict[str, Any]]:
        texto = descargar("https://projecteuler.net/minimal=problems;csv", SEMANA)
        salida = []
        for fila in csv.DictReader(io.StringIO(texto)):
            try:
                n, resueltos = int(fila["ID"]), int(fila.get("Solved By") or 0)
            except (KeyError, ValueError):
                continue
            salida.append({
                "fuente": self.ID, "ref": str(n), "titulo": f"{n}. {fila.get('Title', '')}",
                "etiquetas": ["maths"], "previas": [], "palabras": normalizar(fila.get("Title", "")).split(),
                "nivel": "principiante" if resueltos > 100_000 else "intermedio" if resueltos > 20_000 else "avanzado",
                "resueltos": resueltos, "tipo": "matemáticas", "verificable": False,
                "url": f"https://projecteuler.net/problem={n}", "licencia": self.LICENCIA,
            })
        return salida

    @staticmethod
    def a_markdown(pagina: str) -> str:
        t = pagina
        t = re.sub(r'<img[^>]*src="([^"]+)"[^>]*>', lambda m: f"![imagen](https://projecteuler.net/{m.group(1).lstrip('/')})", t)
        t = re.sub(r"<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>",
                   lambda m: f"[{m.group(2)}]({m.group(1) if m.group(1).startswith('http') else 'https://projecteuler.net/' + m.group(1).lstrip('/')})", t, flags=re.S)
        t = re.sub(r"</?(b|strong)>", "**", t)
        t = re.sub(r"</?(i|em|var)>", "*", t)
        t = re.sub(r"<br\s*/?>", "  \n", t)
        t = re.sub(r"<sup>(.*?)</sup>", r"^{\1}", t)
        t = re.sub(r"<sub>(.*?)</sub>", r"_{\1}", t)
        t = re.sub(r"</p>\s*", "\n\n", t)
        t = re.sub(r"<p[^>]*>", "", t)
        t = re.sub(r"<(?!/?(table|tr|td|th|tbody|thead)\b)[^>]+>", "", t)
        return html.unescape(t).strip()

    def cargar(self, ref: str, lenguaje: str = "python") -> Dict[str, Any]:
        if not re.fullmatch(r"\d{1,4}", ref or ""):
            raise ErrorDesafio("Problema de Project Euler no válido")
        n = int(ref)
        texto = descargar(f"https://projecteuler.net/minimal={n}", 90 * 86400)
        if not texto.strip():
            raise ErrorDesafio(f"No existe el problema {n} de Project Euler.")
        e = next((x for x in self.indice() if x["ref"] == ref), {})
        if lenguaje == "cpp":
            pag = [{"nombre": f"euler_{n}.cpp", "descripcion": "",
                    "contenido": (f"#include <iostream>\n\n"
                                  f"// Resuelve el problema {n} de Project Euler\n"
                                  f"long long solucion() {{\n"
                                  f"    // Escribe aquí tu solución\n"
                                  f"    return 0;\n"
                                  f"}}\n\n"
                                  f"int main() {{\n"
                                  f"    std::cout << solucion() << std::endl;\n"
                                  f"    return 0;\n"
                                  f"}}\n")}]
        else:
            pag = [{"nombre": f"euler_{n}.py", "descripcion": "",
                    "contenido": (f'def solucion():\n    """Devuelve la respuesta del problema {n}."""\n    # Escribe aquí tu solución\n'
                                  f'    raise NotImplementedError\n\n\nif __name__ == "__main__":\n    print(solucion())\n')}]
        return {
            "titulo": e.get("titulo") or f"Problema {n}", "enunciado": self.a_markdown(texto), "teoria": "", "idioma": "en",
            "nivel": e.get("nivel", "intermedio"), "conceptos": ["maths"],
            "paginas": pag,
            "lenguaje": lenguaje,
            "comprobacion": {"tipo": "ninguna", "pruebas_visibles": False},
            "origen": {"tipo": self.ID, "nombre": "Project Euler", "ref": ref, "url": f"https://projecteuler.net/problem={n}",
                       "licencia": self.LICENCIA, "lenguaje": lenguaje,
                       "atribucion": f"Problema {n} de Project Euler (projecteuler.net), licencia CC BY-NC-SA 4.0. "
                                     "Si se traduce, la traducción se comparte con la misma licencia.",
                       "nota": "Project Euler no publica las respuestas: ejecuta tu página y compruébala en su web (hace falta cuenta)."},
            "privado": {"comprobacion": {"tipo": "ninguna"}, "referencia": []},
        }


FUENTES = {f.ID: f for f in (Exercism(), ExercismCpp(), TheAlgorithms(), TheAlgorithmsCpp(), ProjectEuler())}


def buscar(tema: str, nivel: Optional[str] = None, fuentes: Optional[List[str]] = None,
           extra: Optional[List[str]] = None, por_fuente: int = 8, lenguaje: Optional[str] = None) -> Dict[str, Any]:
    """ Desafíos de cada fuente que tratan `tema`, de más a menos relacionado """
    etiquetas, palabras = terminos(tema, extra)
    resultados, errores = [], {}
    fuentes_disponibles = list(FUENTES)
    if lenguaje == "cpp":
        fuentes_disponibles = ["exercism_cpp", "thealgorithms_cpp", "projecteuler"]
    elif lenguaje == "python":
        fuentes_disponibles = ["exercism", "thealgorithms", "projecteuler"]

    for fid in fuentes or fuentes_disponibles:
        if fid not in FUENTES:
            continue
        try:
            items = FUENTES[fid].indice()
        except ErrorDesafio as e:
            errores[fid] = str(e)
            continue
        puntuados = []
        for it in items:
            if lenguaje and it.get("lenguaje") and it.get("lenguaje") != lenguaje and fid != "projecteuler":
                continue
            p = 0.0
            p += 5 * len(etiquetas & set(it["etiquetas"]))
            p += 2 * len(etiquetas & set(it["previas"]))
            propias = set(it["palabras"])
            coincidencias = palabras & propias
            p += 3 * len(coincidencias)
            # Etiqueta traducida que aparece en el nombre: «busqueda binaria» → binary_search.py / binary_search.cpp
            for et in etiquetas:
                trozos = [t for t in et.split("-") if t]
                if trozos and all(any(w == t or (len(t) >= 6 and w[:6] == t[:6]) for w in propias) for t in trozos):
                    p += 4
            p += 1.5 * sum(1 for w in palabras for et in it["etiquetas"] if w in et.split("-"))
            if p <= 0:
                continue
            if nivel and it["nivel"] == nivel:
                p += 1
            if fid == "projecteuler" and it.get("resueltos"):
                p += min(1.0, it["resueltos"] / 500_000)       # a igualdad, los más asequibles
            puntuados.append((p, it))
        puntuados.sort(key=lambda x: -x[0])
        for p, it in puntuados[:por_fuente]:
            resultados.append({k: v for k, v in it.items() if k not in ("palabras", "previas")} | {"puntuacion": round(p, 1)})
    return {"resultados": resultados, "etiquetas": sorted(etiquetas), "palabras": sorted(palabras), "errores": errores}


def importar(fuente: str, ref: str, runner, funcion: Optional[str] = None, lenguaje: Optional[str] = None) -> Dict[str, Any]:
    """ Trae el desafío y, si es verificable, comprueba ejecutándolo que sus pruebas funcionan aquí """
    if fuente not in FUENTES:
        raise ErrorDesafio("Fuente desconocida")
    if fuente == "thealgorithms":
        d = FUENTES[fuente].cargar(ref, funcion)
    elif fuente == "projecteuler":
        d = FUENTES[fuente].cargar(ref, lenguaje=lenguaje or "python")
    else:
        d = FUENTES[fuente].cargar(ref)
    priv = d["privado"]
    if priv["comprobacion"]["tipo"] != "ninguna":
        v = ejecucion.validar_desafio(runner, [p for p in d["paginas"]], priv["referencia"], priv)
        if not v["valido"]:
            raise ErrorDesafio(f"Este desafío no se puede comprobar en tu equipo: {v['motivo']}")
        d["comprobacion"]["pruebas"] = v["pruebas"]
    return d
