"""
Banco del proyecto: todo lo que un modelo necesita saber de un proyecto, sin límite de tamaño.

Un modelo tiene un contexto finito; un proyecto grande no cabe, y releerlo en cada pregunta
cuesta minutos. La idea es la de una memoria de trabajo con índice: el proyecto entero vive en
un SQLite y a cada pregunta se le da al modelo solo lo que le sirve, con herramientas para
pedir el resto. Así el tamaño del proyecto deja de depender del contexto.

Qué guarda (un SQLite por carpeta de trabajo, en ~/.prig_bancos):

  · archivos      su contenido (para calcular diffs), idioma, resumen y el análisis de IA
  · símbolos      clases, funciones y métodos con firma, docstring y líneas
                  (Python con `ast`; JS/TS, C/C++/CUDA, Java/C#, Go y Rust con patrones)
  · fragmentos    el código cortado por función, con índice de texto (FTS5) y vectores
  · usos/imports  quién llama a qué y quién importa a quién (el grafo del proyecto)
  · cambios       cada archivo nuevo, modificado o borrado, con su diff y las funciones tocadas
  · conocimiento  definiciones, teoría, decisiones y contexto (del usuario, del modelo o del
                  análisis), con aviso cuando un archivo del que hablan cambia
  · resoluciones  cada pregunta respondida: resumen, archivos, y si después cambiaron

Cómo se mantiene al día: `sincronizar()` mira fecha y tamaño de cada archivo y solo relee
los que cambiaron (y de esos, solo re-embebe las funciones cuyo texto cambió). Lo llama un
vigilante cada pocos segundos y el chat antes de cada pregunta: el modelo siempre ve el
proyecto tal como está.

Cómo se usa en cada pregunta:

  · `mapa()`     estructura estable del proyecto (archivos, resúmenes, símbolos principales).
                 No lleva nada que cambie con cada edición, así el motor MoE lo guarda como
                 prefijo y lo restaura en décimas de segundo.
  · `componer()` lo relevante para ESTA pregunta dentro de un presupuesto de tokens: cambios
                 desde la última respuesta, conocimiento, resoluciones parecidas y el código
                 (búsqueda por texto + vectores + símbolos nombrados + vecinos en el grafo).
  · herramientas para que el modelo pida lo que falte (herramientas_chat.py).
"""

import array
import ast
import difflib
import hashlib
import json
import math
import operator
import os
import re
import sqlite3
import subprocess
import threading
import time
import unicodedata
import zlib
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

VERSION_ESQUEMA = 4          # 4: llamadas resueltas al símbolo exacto (receptor + alias de import)
MAX_ARCHIVOS = 20000
MAX_BYTES = 1_000_000
MAX_BYTES_DATOS = 200_000          # json/yaml/csv: más grandes son datos, no código
MAX_LINEAS_FRAGMENTO = 120
LINEAS_BLOQUE_SUELTO = 60
MAX_DIFF = 3000
MAX_CAMBIOS_GUARDADOS = 3000
CARACTERES_POR_TOKEN = 3.5
RRF_K = 60

IGNORADAS = {
    "__pycache__", "node_modules", "venv", ".venv", "env", ".git", ".github", ".ipynb_checkpoints",
    "dist", "build", ".cache", "site-packages", ".idea", ".vscode", ".gemini", ".mypy_cache",
    ".pytest_cache", ".tox", ".next", "target", "coverage", ".gradle", "vendor",
}
LENGUAJES = {
    "py": "python", "pyi": "python",
    "js": "js", "jsx": "js", "ts": "js", "tsx": "js", "mjs": "js", "cjs": "js", "vue": "js", "svelte": "js",
    "c": "c", "h": "c", "cc": "c", "cpp": "c", "cxx": "c", "hpp": "c", "hh": "c", "hxx": "c",
    "cu": "c", "cuh": "c", "m": "c", "mm": "c",
    "java": "java", "kt": "java", "kts": "java", "cs": "java", "scala": "java", "swift": "java", "dart": "java",
    "go": "go", "rs": "rust",
    "md": "md", "markdown": "md", "rst": "md", "txt": "md", "tex": "md",
    "html": "texto", "htm": "texto", "css": "texto", "scss": "texto", "sql": "texto", "sh": "texto",
    "bash": "texto", "zsh": "texto", "ps1": "texto", "bat": "texto", "r": "texto", "jl": "texto",
    "lua": "texto", "rb": "texto", "php": "texto", "pl": "texto", "cmake": "texto", "proto": "texto",
    "yaml": "datos", "yml": "datos", "toml": "datos", "json": "datos", "ini": "datos", "cfg": "datos",
    "xml": "datos", "csv": "datos", "gbnf": "texto", "ipynb": "cuaderno",
}
SIN_EXTENSION = {"makefile": "texto", "dockerfile": "texto", "cmakelists.txt": "texto", "readme": "md",
                 "license": "md", "procfile": "texto", "gemfile": "texto"}
EXCLUIR_NOMBRES = re.compile(r"(\.min\.(js|css)$|\.lock$|-lock\.json$|\.map$|^package-lock\.json$)")
BLOQUE_LENGUAJE = {"python": "python", "js": "javascript", "c": "cpp", "java": "java", "go": "go",
                   "rust": "rust", "md": "markdown"}

PALABRAS_VACIAS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "the", "a", "an", "of",
    "que", "como", "cual", "cuales", "para", "por", "con", "sin", "sobre", "entre", "este", "esta",
    "esto", "estos", "estas", "ese", "esa", "eso", "esos", "esas", "cuando", "donde", "porque", "pero",
    "mas", "muy", "son", "ser", "estar", "hay", "tiene", "hace", "puede", "debe", "y", "o", "en", "se",
    "lo", "le", "les", "me", "mi", "tu", "su", "sus", "es", "no", "si", "ya", "todo", "toda", "todos",
    "explicame", "explica", "explicar", "dime", "quiero", "necesito", "saber", "funciona", "significa",
    "ayuda", "ayudame", "haz", "hacer", "podrias", "puedes", "algo", "cosa", "codigo", "archivo",
    "funcion", "clase", "metodo", "and", "or", "to", "in", "is", "it", "for", "on", "with", "this", "that",
    "what", "how", "why", "does", "do", "can", "be", "are", "was", "from", "by", "at", "as", "not",
    "self", "none", "true", "false", "return", "def", "import", "const", "let", "var", "int", "void",
}

TIPOS_CONOCIMIENTO = ("definicion", "teoria", "decision", "contexto", "nota")


# ======================================================================
# Utilidades
# ======================================================================

def estimar_tokens(texto: str) -> int:
    return int(len(texto or "") / CARACTERES_POR_TOKEN) + 1


def _sha(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8", "replace")).hexdigest()


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


_IDENT = re.compile(r"[A-Za-z_\u00C0-\u024F][A-Za-z0-9_\u00C0-\u024F]*")
_PARTES = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z\u00E0-\u024F]+|[A-Z]+|\d+")


def terminos(texto: str, limite: int = 4000) -> List[str]:
    """ Palabras buscables: identificadores completos y sus partes (snake_case y camelCase) """
    salida: List[str] = []
    vistos: Set[str] = set()
    for ident in _IDENT.findall(texto or ""):
        base = _sin_acentos(ident).lower()
        candidatos = [base]
        if "_" in ident or any(c.isupper() for c in ident[1:]):
            candidatos += [_sin_acentos(p).lower() for trozo in ident.split("_") for p in _PARTES.findall(trozo)]
        for t in candidatos:
            if len(t) >= 2 and t not in vistos:
                vistos.add(t)
                salida.append(t)
                if len(salida) >= limite:
                    return salida
    return salida


def terminos_consulta(texto: str) -> List[str]:
    return [t for t in terminos(texto, 64) if len(t) >= 3 and t not in PALABRAS_VACIAS]


def identificadores_nombrados(texto: str) -> Set[str]:
    """ Lo que en una pregunta parece un nombre de código: snake_case, camelCase, `entre comillas`,
    llamadas f() o rutas """
    salida: Set[str] = set()
    for m in re.findall(r"`([^`]{2,80})`", texto or ""):
        salida.update(_IDENT.findall(m))
    for ident in _IDENT.findall(texto or ""):
        if "_" in ident.strip("_") or re.search(r"[a-z][A-Z]", ident) or re.match(r"^[A-Z][a-z]+[A-Z]", ident):
            salida.add(ident)
    for m in re.findall(r"([A-Za-z_][\w]*)\s*\(", texto or ""):
        salida.add(m)
    return {s for s in salida if len(s) >= 3 and s.lower() not in PALABRAS_VACIAS}


def _empaquetar(v: Sequence[float]) -> bytes:
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return array.array("f", (x / norma for x in v)).tobytes()


def _desempaquetar(b: bytes) -> array.array:
    a = array.array("f")
    a.frombytes(b)
    return a


def _coseno(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(map(operator.mul, a, b))        # vectores ya normalizados


def carpeta_bancos() -> str:
    return os.environ.get("PRIG_BANCOS") or os.path.expanduser("~/.prig_bancos")


def lenguaje_de(ruta: str) -> Optional[str]:
    nombre = os.path.basename(ruta).lower()
    if nombre in SIN_EXTENSION:
        return SIN_EXTENSION[nombre]
    if "." not in nombre:
        return None
    return LENGUAJES.get(nombre.rsplit(".", 1)[1])


# ======================================================================
# Extracción de símbolos
# ======================================================================

class Simbolo(dict):
    """ nombre, corto, tipo, firma, doc, ini, fin, padre, usos (nombres llamados dentro) """


def _primera_linea(texto: Optional[str], maximo: int = 200) -> str:
    for linea in (texto or "").strip().splitlines():
        linea = linea.strip()
        if linea:
            return linea[:maximo]
    return ""


def alias_python(texto: str) -> List[Tuple[str, str]]:
    """ Nombres que los import dejan en el archivo: (alias, ruta con puntos). «import a.b» deja «a»;
    «import a.b as c», «c» → a.b; «from a import b as c», «c» → a.b (módulo o símbolo). """
    try:
        arbol = ast.parse(texto)
    except (SyntaxError, ValueError):
        return []
    salida = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for a in nodo.names:
                salida.append((a.asname, a.name) if a.asname else (a.name.split(".")[0], a.name.split(".")[0]))
        elif isinstance(nodo, ast.ImportFrom):
            base = "." * (nodo.level or 0) + (nodo.module or "")
            for a in nodo.names:
                if a.name != "*":
                    salida.append((a.asname or a.name, f"{base}.{a.name}" if nodo.module else base + a.name))
    return salida


def simbolos_python(texto: str) -> Tuple[List[Simbolo], List[str], str]:
    """ (símbolos, módulos importados, docstring del módulo) """
    try:
        arbol = ast.parse(texto)
    except (SyntaxError, ValueError):
        return [], [], ""
    simbolos: List[Simbolo] = []
    importados: List[str] = []

    def llamadas(nodo) -> List[Tuple[str, int, str]]:
        """ (nombre llamado, línea de la primera llamada, receptor). El receptor distingue
        calcular(...) (""), self.calcular(...) ("self"), motor.calcular(...) ("motor") y
        requests.post(...) ("requests"): sin él, cualquier .post() parecía llamar a Motor.post. """
        primeras: Dict[Tuple[str, str], int] = {}
        for n in ast.walk(nodo):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    clave = (f.id, "")
                elif isinstance(f, ast.Attribute):
                    try:
                        receptor = ast.unparse(f.value)
                    except Exception:
                        receptor = "?"
                    clave = (f.attr, receptor[:80])
                else:
                    continue
                if clave not in primeras or n.lineno < primeras[clave]:
                    primeras[clave] = n.lineno
        return sorted((nombre, linea, receptor) for (nombre, receptor), linea in primeras.items())

    def firma(nodo) -> str:
        if isinstance(nodo, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in nodo.bases) if nodo.bases else ""
            return f"class {nodo.name}({bases})" if bases else f"class {nodo.name}"
        try:
            args = ast.unparse(nodo.args)
        except Exception:
            args = "..."
        ret = f" -> {ast.unparse(nodo.returns)}" if getattr(nodo, "returns", None) is not None else ""
        pre = "async def" if isinstance(nodo, ast.AsyncFunctionDef) else "def"
        return f"{pre} {nodo.name}({args}){ret}"

    def visitar(cuerpo, padre: str = ""):
        for nodo in cuerpo:
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                ini = min([nodo.lineno] + [d.lineno for d in nodo.decorator_list])
                nombre = f"{padre}.{nodo.name}" if padre else nodo.name
                tipo = "clase" if isinstance(nodo, ast.ClassDef) else ("metodo" if padre else "funcion")
                simbolos.append(Simbolo(nombre=nombre, corto=nodo.name, tipo=tipo, firma=firma(nodo),
                                        doc=(ast.get_docstring(nodo) or "")[:600], ini=ini,
                                        fin=getattr(nodo, "end_lineno", nodo.lineno), padre=padre,
                                        usos=[] if tipo == "clase" else llamadas(nodo)))
                if isinstance(nodo, ast.ClassDef):
                    visitar(nodo.body, nombre)
    visitar(arbol.body)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados += [a.name for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            modulo = "." * (nodo.level or 0) + (nodo.module or "")
            importados.append(modulo)
            importados += [f"{modulo}.{a.name}" if modulo.strip(".") else "." * (nodo.level or 0) + a.name
                           for a in nodo.names]
    return simbolos, importados, ast.get_docstring(arbol) or ""


_CONTROL = {"if", "for", "while", "switch", "catch", "return", "sizeof", "else", "do", "try", "new",
            "delete", "throw", "case", "typeof", "await", "yield", "function", "elif", "match", "with"}
PATRONES: Dict[str, List[Tuple[re.Pattern, str]]] = {
    "js": [
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"), "clase"),
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\("), "funcion"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?"
                    r"(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|[A-Za-z_$][\w$]*\s*=>)"), "funcion"),
        (re.compile(r"^\s+(?:(?:public|private|protected|static|async|get|set|readonly|override)\s+)*"
                    r"([A-Za-z_$][\w$]*)\s*\([^;]*\)\s*(?::\s*[^{;]+)?\{\s*$"), "metodo"),
        (re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)"), "tipo"),
    ],
    "c": [
        (re.compile(r"^\s*(?:template\s*<.*>\s*)?(?:class|struct|union)\s+(?:\w+\s+)*?([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^;{]*)?\{?\s*$"), "clase"),
        (re.compile(r"^\s*(?:enum)\s+(?:class\s+)?([A-Za-z_]\w*)"), "tipo"),
        (re.compile(r"^\s*namespace\s+([A-Za-z_][\w:]*)"), "espacio"),
        (re.compile(r"^\s*(?:template\s*<.*>\s*)?(?:(?:static|inline|virtual|extern|constexpr|explicit|"
                    r"__global__|__device__|__host__|__forceinline__|GGML_API|LLAMA_API|const|unsigned|"
                    r"signed|struct|friend)\s+)*[A-Za-z_][\w:<>,\s\*&]*?[\s\*&]+\**([A-Za-z_~][\w:~]*)\s*\([^;]*$"),
         "funcion"),
    ],
    "java": [
        (re.compile(r"^\s*(?:(?:public|private|protected|internal|static|abstract|final|sealed|data|open)\s+)*"
                    r"(?:class|interface|enum|record|object|struct|trait)\s+([A-Za-z_]\w*)"), "clase"),
        (re.compile(r"^\s*(?:(?:public|private|protected|internal|static|abstract|final|override|synchronized|"
                    r"async|virtual|suspend|open)\s+)*(?:fun\s+|func\s+)?(?:[\w<>\[\],?\s]+\s+)?([A-Za-z_]\w*)\s*\([^;]*\)"
                    r"\s*(?:[:\w<>\[\],?\s]*)?(?:throws[\w\s,.]+)?\{?\s*$"), "funcion"),
    ],
    "go": [
        (re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("), "funcion"),
        (re.compile(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)"), "clase"),
    ],
    "rust": [
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+\"C\"\s+)?fn\s+([A-Za-z_]\w*)"), "funcion"),
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union)\s+([A-Za-z_]\w*)"), "clase"),
        (re.compile(r"^\s*impl(?:<[^>]*>)?\s+(?:[\w:<>]+\s+for\s+)?([A-Za-z_][\w:]*)"), "clase"),
        (re.compile(r"^\s*(?:pub\s+)?mod\s+([A-Za-z_]\w*)\s*\{"), "espacio"),
    ],
}
# Métodos de librería tan comunes que un nombre único en el proyecto no basta para enlazarlos
VERBOS_COMUNES = {
    "get", "post", "put", "delete", "patch", "run", "read", "write", "append", "extend", "update", "items",
    "keys", "values", "format", "join", "split", "strip", "open", "close", "execute", "send", "start", "stop",
    "add", "remove", "pop", "copy", "load", "dump", "loads", "dumps", "search", "match", "sub", "find",
    "replace", "lower", "upper", "encode", "decode", "sort", "index", "count", "insert", "clear", "set",
    "wait", "acquire", "release", "submit", "result", "json", "text", "exists", "mkdir", "call", "apply",
    "map", "filter", "reduce", "emit", "on", "then", "catch", "push", "slice", "splice", "forEach", "log",
    "error", "warn", "info", "debug", "parse", "stringify", "test", "exec", "render", "setdefault", "fetch",
    "flush", "readline", "readlines", "kill", "terminate", "poll", "communicate", "is_alive", "is_set",
    "setUp", "tearDown", "__init__", "__enter__", "__exit__", "main", "init", "reset", "next", "iter",
}

_ES_TEST = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$")
_LLAMADA = re.compile(r"\b([A-Za-z_][\w]*)\s*\(")
_COMENTARIO_LINEA = re.compile(r"^\s*(//+|#|\*|/\*\*?|--)\s?")


def _fin_por_llaves(lineas: List[str], ini: int) -> Optional[int]:
    """ Línea (índice) donde se cierra el bloque que abre en `ini`, o None si no abre bloque """
    profundidad, abierto = 0, False
    for i in range(ini, min(len(lineas), ini + 4000)):
        linea = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//.*$', "", lineas[i])
        for c in linea:
            if c == "{":
                profundidad += 1
                abierto = True
            elif c == "}":
                profundidad -= 1
                if abierto and profundidad <= 0:
                    return i
        if not abierto and (i - ini >= 3 or linea.rstrip().endswith(";")):
            return None
    return len(lineas) - 1 if abierto else None


def _doc_previa(lineas: List[str], ini: int) -> str:
    doc: List[str] = []
    i = ini - 1
    while i >= 0 and len(doc) < 12:
        s = lineas[i].strip()
        if not s or not (_COMENTARIO_LINEA.match(lineas[i]) or s.endswith("*/")):
            break
        doc.insert(0, _COMENTARIO_LINEA.sub("", s).rstrip("*/ ").strip())
        i -= 1
    return " ".join(d for d in doc if d)[:600]


def simbolos_genericos(texto: str, lenguaje: str) -> List[Simbolo]:
    patrones = PATRONES.get(lenguaje)
    if not patrones:
        return []
    lineas = texto.splitlines()
    simbolos: List[Simbolo] = []
    abiertos: List[Simbolo] = []            # clases que contienen la línea actual
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        while abiertos and abiertos[-1]["fin"] < i + 1:
            abiertos.pop()
        encontrado = None
        if linea.strip() and not _COMENTARIO_LINEA.match(linea) and not linea.lstrip().startswith("#"):
            for patron, tipo in patrones:
                m = patron.match(linea)
                if m and m.group(1).split("::")[-1] not in _CONTROL:
                    encontrado = (m.group(1), tipo)
                    break
        if encontrado:
            nombre_crudo, tipo = encontrado
            fin = _fin_por_llaves(lineas, i)
            if lenguaje == "go" and fin is None and tipo == "clase":
                fin = i
            if fin is not None:
                corto = nombre_crudo.split("::")[-1]
                padre = abiertos[-1]["nombre"] if abiertos and tipo in ("funcion", "metodo") else ""
                if padre and tipo == "funcion":
                    tipo = "metodo"
                nombre = f"{padre}.{corto}" if padre else nombre_crudo.replace("::", ".")
                cuerpo = "\n".join(lineas[i:fin + 1])
                s = Simbolo(nombre=nombre, corto=corto, tipo=tipo, firma=linea.strip()[:200].rstrip("{").strip(),
                            doc=_doc_previa(lineas, i), ini=i + 1, fin=fin + 1, padre=padre,
                            usos=sorted({n for n in _LLAMADA.findall(cuerpo) if n not in _CONTROL and n != corto})
                            if tipo in ("funcion", "metodo") else [])
                simbolos.append(s)
                if tipo in ("clase", "espacio"):
                    abiertos.append(s)
                else:
                    i = fin              # el cuerpo de una función no declara más símbolos de primer nivel
        i += 1
    return simbolos


def secciones_markdown(texto: str) -> List[Simbolo]:
    lineas = texto.splitlines()
    cabeceras = [(i, len(m.group(1)), m.group(2).strip()) for i, l in enumerate(lineas)
                 for m in [re.match(r"^(#{1,4})\s+(.+)$", l)] if m]
    salida: List[Simbolo] = []
    for k, (i, nivel, titulo) in enumerate(cabeceras):
        # Hasta la siguiente cabecera de cualquier nivel: las subsecciones son fragmentos propios
        fin = cabeceras[k + 1][0] - 1 if k + 1 < len(cabeceras) else len(lineas) - 1
        salida.append(Simbolo(nombre=titulo, corto=titulo, tipo="seccion", firma="#" * nivel + " " + titulo,
                              doc=_primera_linea("\n".join(lineas[i + 1:fin + 1])), ini=i + 1, fin=fin + 1,
                              padre="", usos=[]))
    return salida


def importaciones_genericas(texto: str, lenguaje: str) -> List[str]:
    if lenguaje == "js":
        return re.findall(r"""(?:from\s+|require\(\s*|import\s*\(\s*|import\s+)['"]([^'"]+)['"]""", texto)
    if lenguaje == "c":
        return re.findall(r'^\s*#\s*include\s+"([^"]+)"', texto, re.M)
    if lenguaje == "go":
        bloques = re.findall(r"import\s*\(([^)]*)\)", texto) + re.findall(r'import\s+("[^"]+")', texto)
        return re.findall(r'"([^"]+)"', "\n".join(bloques))
    if lenguaje == "rust":
        return re.findall(r"^\s*(?:pub\s+)?(?:use|mod)\s+([\w:]+)", texto, re.M)
    return []


# ======================================================================
# Hechos: el grafo de bajo nivel del proyecto
# ======================================================================

_ES_CONFIG = re.compile(r"(^|[._])(config|cfg|configuracion|ajustes|settings|opciones)$", re.I)
_METODOS_HTTP = {"get", "post", "put", "delete", "patch", "websocket", "route", "api_route"}
_SUBPROCESO = {"run", "Popen", "check_output", "check_call", "call"}


def _dentro(simbolos: List[Simbolo], linea: int, defecto: str) -> str:
    """ El símbolo más interno que contiene la línea """
    mejor = None
    for s in simbolos:
        if s["ini"] <= linea <= s["fin"] and (mejor is None or s["ini"] >= mejor["ini"]):
            mejor = s
    return mejor["nombre"] if mejor else defecto


def _constante(nodo) -> Optional[str]:
    return nodo.value if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) else None


def hechos_python(rel: str, texto: str, simbolos: List[Simbolo]) -> List[Tuple[str, str, str, int]]:
    try:
        arbol = ast.parse(texto)
    except (SyntaxError, ValueError):
        return []
    salida: List[Tuple[str, str, str, int]] = []
    donde = lambda n: _dentro(simbolos, getattr(n, "lineno", 0), rel)
    for n in ast.walk(arbol):
        if isinstance(n, ast.ClassDef):
            clase = _dentro(simbolos, n.lineno, n.name)
            for b in n.bases:
                try:
                    salida.append((clase, "hereda", ast.unparse(b), n.lineno))
                except Exception:
                    pass
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in _METODOS_HTTP \
                        and d.args and (_constante(d.args[0]) or "").startswith("/"):
                    metodo = "GET" if d.func.attr in ("route", "api_route") else d.func.attr.upper()
                    salida.append((_dentro(simbolos, n.lineno, n.name), "expone",
                                   f"{metodo} {ruta_http_canonica(_constante(d.args[0]))}", n.lineno))
        elif isinstance(n, ast.Raise) and n.exc is not None:
            f = n.exc.func if isinstance(n.exc, ast.Call) else n.exc
            nombre = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if nombre:
                salida.append((donde(n), "lanza", nombre, n.lineno))
        elif isinstance(n, ast.ExceptHandler) and n.type is not None:
            tipos = n.type.elts if isinstance(n.type, ast.Tuple) else [n.type]
            for t in tipos:
                try:
                    salida.append((donde(n), "captura", ast.unparse(t), n.lineno))
                except Exception:
                    pass
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            f = n.func
            try:
                base = ast.unparse(f.value)
            except Exception:
                base = ""
            clave = _constante(n.args[0]) if n.args else None
            if clave and f.attr == "get" and base.endswith("environ"):
                salida.append((donde(n), "lee_entorno", clave, n.lineno))
            elif clave and f.attr == "getenv":
                salida.append((donde(n), "lee_entorno", clave, n.lineno))
            elif clave and f.attr in ("get", "setdefault") and _ES_CONFIG.search(base):
                salida.append((donde(n), "lee_config", clave, n.lineno))
            elif f.attr in _SUBPROCESO and base == "subprocess" and n.args:
                a = n.args[0]
                prog = _constante(a) or (_constante(a.elts[0]) if isinstance(a, (ast.List, ast.Tuple)) and a.elts else None)
                if prog:
                    salida.append((donde(n), "ejecuta", prog.split()[0], n.lineno))
        elif isinstance(n, ast.Subscript):
            clave = _constante(n.slice)
            if clave:
                try:
                    base = ast.unparse(n.value)
                except Exception:
                    base = ""
                if base.endswith("environ"):
                    salida.append((donde(n), "lee_entorno", clave, n.lineno))
                elif _ES_CONFIG.search(base):
                    salida.append((donde(n), "lee_config", clave, n.lineno))
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                    duenio = _dentro(simbolos, n.lineno, "")
                    clase = duenio.rsplit(".", 1)[0] if "." in duenio else ""
                    if clase:
                        salida.append((clase, "atributo", t.attr, n.lineno))
    vistos: Set[Tuple[str, str, str]] = set()
    unicos = []
    for h in salida:
        if h[:3] not in vistos:
            vistos.add(h[:3])
            unicos.append(h)
    return unicos


_API_JS = re.compile(r"""(?:fetch|prigFetchJson|prigJson|json|post|get|put|del|axios\.\w+|request)\(\s*([`'"])(/api/.*?)\1""")


def ruta_http_canonica(ruta: str) -> str:
    """ La misma forma para las rutas del backend y del frontend, así se comparan con ==:
    /api/x/{id} y `/api/x/${id}` → /api/x/*  (sin consulta ni barra final) """
    ruta = re.sub(r"\$\{[^}]*\}", "*", ruta.split("?")[0].split("#")[0])
    ruta = re.sub(r"\{[^}]*\}", "*", ruta)
    return ruta.rstrip("/") or "/"
_DOM_USO = re.compile(r"""(?:getElementById|\$)\(\s*['"]([\w-]+)['"]\s*\)|querySelector(?:All)?\(\s*['"]#([\w-]+)""")
_DOM_DEF = re.compile(r"""\bid\s*=\s*["']([\w-]+)["']""")
_ENV_C = re.compile(r"""\bgetenv\(\s*"([^"]+)"\s*\)""")


def hechos_texto(rel: str, lenguaje: str, texto: str, simbolos: List[Simbolo]) -> List[Tuple[str, str, str, int]]:
    salida: List[Tuple[str, str, str, int]] = []
    vistos: Set[Tuple[str, str, str]] = set()

    def agregar(s: str, r: str, o: str, linea: int):
        if (s, r, o) not in vistos:
            vistos.add((s, r, o))
            salida.append((s, r, o, linea))
    for n, linea in enumerate(texto.splitlines(), 1):
        if lenguaje in ("js", "texto", "md"):
            for m in _API_JS.finditer(linea):
                agregar(_dentro(simbolos, n, rel), "llama_api", ruta_http_canonica(m.group(2)), n)
        if lenguaje in ("js",):
            for m in _DOM_USO.finditer(linea):
                agregar(_dentro(simbolos, n, rel), "usa_dom", m.group(1) or m.group(2), n)
        if lenguaje in ("js", "texto") and (rel.endswith((".html", ".htm", ".js", ".jsx", ".vue", ".svelte"))):
            for m in _DOM_DEF.finditer(linea):
                agregar(rel, "define_dom", m.group(1), n)
        if lenguaje in ("c", "rust", "go"):
            for m in _ENV_C.finditer(linea):
                agregar(_dentro(simbolos, n, rel), "lee_entorno", m.group(1), n)
    return salida


def extraer_hechos(rel: str, lenguaje: str, texto: str, simbolos: List[Simbolo]) -> List[Tuple[str, str, str, int]]:
    try:
        if lenguaje in ("python", "cuaderno"):
            return hechos_python(rel, texto, simbolos)
        return hechos_texto(rel, lenguaje, texto, simbolos)
    except Exception:            # un extractor no puede impedir que se indexe el archivo
        return []


# ======================================================================
# El banco
# ======================================================================

class BancoProyecto:
    def __init__(self, raiz: str, carpeta: Optional[str] = None,
                 embeber: Optional[Callable[[List[str]], List[List[float]]]] = None,
                 embebedor_listo: Optional[Callable[[], bool]] = None,
                 modelo_vectores: str = "bge-m3"):
        self.raiz = os.path.abspath(raiz)
        clave = hashlib.sha1(self.raiz.encode()).hexdigest()[:10]
        nombre = re.sub(r"[^\w.-]+", "_", os.path.basename(self.raiz) or "raiz")
        self.carpeta = carpeta or os.path.join(carpeta_bancos(), f"{nombre}-{clave}")
        os.makedirs(self.carpeta, exist_ok=True)
        self.ruta_db = os.path.join(self.carpeta, "banco.db")
        self.embeber = embeber
        self.embebedor_listo = embebedor_listo
        self.modelo_vectores = modelo_vectores
        self._lock = threading.RLock()
        self._vectores: Optional[Dict[str, array.array]] = None
        self._ultima_sincronizacion = 0.0
        self._crear()
        self._guardar_meta("raiz", self.raiz)

    # ------------------------------------------------------------------ base de datos
    @contextmanager
    def conectar(self):
        c = sqlite3.connect(self.ruta_db, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def _crear(self):
        with self.conectar() as c:
            c.execute("PRAGMA journal_mode=WAL;")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS archivos (
                ruta TEXT PRIMARY KEY, sha TEXT, mtime REAL, tamano INTEGER, lenguaje TEXT,
                lineas INTEGER, tokens INTEGER, resumen TEXT, resumen_ia TEXT, analizado_sha TEXT,
                contenido BLOB, version INTEGER);
            CREATE TABLE IF NOT EXISTS simbolos (
                id INTEGER PRIMARY KEY, ruta TEXT, nombre TEXT, corto TEXT, tipo TEXT, firma TEXT,
                doc TEXT, ini INTEGER, fin INTEGER, padre TEXT, sha TEXT);
            CREATE INDEX IF NOT EXISTS idx_sim_ruta ON simbolos(ruta);
            CREATE INDEX IF NOT EXISTS idx_sim_corto ON simbolos(corto);
            CREATE TABLE IF NOT EXISTS fragmentos (
                id INTEGER PRIMARY KEY, ruta TEXT, simbolo TEXT, tipo TEXT, ini INTEGER, fin INTEGER,
                texto TEXT, sha TEXT, tokens INTEGER);
            CREATE INDEX IF NOT EXISTS idx_frag_ruta ON fragmentos(ruta);
            CREATE INDEX IF NOT EXISTS idx_frag_sha ON fragmentos(sha);
            CREATE VIRTUAL TABLE IF NOT EXISTS fragmentos_fts USING fts5(ruta, simbolo, terminos);
            CREATE TABLE IF NOT EXISTS usos (ruta TEXT, nombre TEXT, linea INTEGER, dentro TEXT, receptor TEXT);
            CREATE TABLE IF NOT EXISTS alias (ruta TEXT, nombre TEXT, destino TEXT);
            CREATE INDEX IF NOT EXISTS idx_alias_ruta ON alias(ruta);
            CREATE TABLE IF NOT EXISTS llamadas (
                ruta TEXT, desde TEXT, a_ruta TEXT, a_nombre TEXT, linea INTEGER, confianza TEXT);
            CREATE INDEX IF NOT EXISTS idx_llam_desde ON llamadas(ruta, desde);
            CREATE INDEX IF NOT EXISTS idx_llam_a ON llamadas(a_ruta, a_nombre);
            CREATE INDEX IF NOT EXISTS idx_llam_nombre ON llamadas(a_nombre);
            CREATE INDEX IF NOT EXISTS idx_usos_nombre ON usos(nombre);
            CREATE INDEX IF NOT EXISTS idx_usos_ruta ON usos(ruta);
            CREATE TABLE IF NOT EXISTS importaciones (ruta TEXT, destino TEXT);
            CREATE INDEX IF NOT EXISTS idx_imp_destino ON importaciones(destino);
            CREATE INDEX IF NOT EXISTS idx_imp_ruta ON importaciones(ruta);
            CREATE TABLE IF NOT EXISTS cambios (
                id INTEGER PRIMARY KEY, version INTEGER, ruta TEXT, tipo TEXT, cuando TEXT,
                simbolos TEXT, diff TEXT, mas INTEGER, menos INTEGER);
            CREATE INDEX IF NOT EXISTS idx_cambios_version ON cambios(version);
            CREATE TABLE IF NOT EXISTS conocimiento (
                id INTEGER PRIMARY KEY, tipo TEXT, titulo TEXT, texto TEXT, rutas TEXT, origen TEXT,
                creado TEXT, actualizado TEXT, revisar INTEGER DEFAULT 0, version INTEGER);
            CREATE VIRTUAL TABLE IF NOT EXISTS conocimiento_fts USING fts5(titulo, terminos);
            CREATE TABLE IF NOT EXISTS resoluciones (
                id INTEGER PRIMARY KEY, pregunta TEXT, resumen TEXT, respuesta BLOB, rutas TEXT,
                modelo TEXT, cuando TEXT, version INTEGER);
            CREATE VIRTUAL TABLE IF NOT EXISTS resoluciones_fts USING fts5(pregunta, terminos);
            CREATE TABLE IF NOT EXISTS vectores (clave TEXT PRIMARY KEY, vector BLOB, modelo TEXT);
            CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
            CREATE TABLE IF NOT EXISTS hechos (
                s TEXT, r TEXT, o TEXT, ruta TEXT, linea INTEGER, origen TEXT, version INTEGER);
            CREATE INDEX IF NOT EXISTS idx_hechos_s ON hechos(s);
            CREATE INDEX IF NOT EXISTS idx_hechos_o ON hechos(o);
            CREATE INDEX IF NOT EXISTS idx_hechos_r ON hechos(r);
            CREATE INDEX IF NOT EXISTS idx_hechos_ruta ON hechos(ruta);
            DROP VIEW IF EXISTS grafo;
            CREATE VIEW grafo AS
                SELECT s, r, o, ruta, linea FROM hechos
                UNION ALL SELECT desde, 'llama', a_nombre, ruta, linea FROM llamadas
                UNION ALL SELECT ruta, 'importa', destino, ruta, 0 FROM importaciones
                UNION ALL SELECT ruta, 'define', nombre, ruta, ini FROM simbolos;
            CREATE TABLE IF NOT EXISTS trabajo (nombre TEXT PRIMARY KEY, valor TEXT, cuando TEXT);
            CREATE TABLE IF NOT EXISTS resumenes (
                nivel TEXT, clave TEXT, texto TEXT, sha_fuente TEXT, modelo TEXT, cuando TEXT,
                PRIMARY KEY (nivel, clave));
            """)
            if "receptor" not in {f[1] for f in c.execute("PRAGMA table_info(usos)")}:
                c.execute("ALTER TABLE usos ADD COLUMN receptor TEXT")
            previo = c.execute("SELECT valor FROM meta WHERE clave = 'esquema'").fetchone()
            if previo and int(previo[0]) < VERSION_ESQUEMA:
                # Un banco de una versión anterior: se reindexa todo en la próxima sincronización
                c.execute("INSERT OR REPLACE INTO meta VALUES ('reindexar', '1')")
            c.execute("INSERT OR REPLACE INTO meta VALUES ('esquema', ?)", (str(VERSION_ESQUEMA),))
            c.execute("INSERT OR IGNORE INTO meta VALUES ('version', '0')")

    def _meta(self, clave: str, defecto: Optional[str] = None) -> Optional[str]:
        with self.conectar() as c:
            f = c.execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
        return f["valor"] if f else defecto

    def _guardar_meta(self, clave: str, valor: Any, c=None):
        if c is not None:
            c.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (clave, str(valor)))
            return
        with self.conectar() as c2:
            c2.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (clave, str(valor)))

    @property
    def version(self) -> int:
        return int(self._meta("version", "0") or 0)

    # ------------------------------------------------------------------ listado
    def _listar(self) -> Dict[str, Tuple[float, int]]:
        rutas: Iterable[str]
        rutas = self._listar_git()
        if rutas is None:
            rutas = self._listar_disco()
        salida: Dict[str, Tuple[float, int]] = {}
        for rel in rutas:
            partes = rel.split("/")
            if any(p in IGNORADAS for p in partes[:-1]) or any(p.startswith(".") for p in partes[:-1]):
                continue
            nombre = partes[-1]
            lenguaje = lenguaje_de(nombre)
            if lenguaje is None or EXCLUIR_NOMBRES.search(nombre.lower()):
                continue
            try:
                st = os.stat(os.path.join(self.raiz, rel))
            except OSError:
                continue
            limite = MAX_BYTES_DATOS if lenguaje in ("datos", "cuaderno") else MAX_BYTES
            if st.st_size > limite or not os.path.isfile(os.path.join(self.raiz, rel)):
                continue
            salida[rel] = (st.st_mtime, st.st_size)
            if len(salida) >= MAX_ARCHIVOS:
                break
        return salida

    def _listar_git(self) -> Optional[List[str]]:
        """ Si es un repositorio, lo que git ve (respeta .gitignore). None si no es un repo. """
        try:
            r = subprocess.run(["git", "-C", self.raiz, "ls-files", "-co", "--exclude-standard", "-z"],
                               capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        return [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p]

    def _listar_disco(self) -> List[str]:
        salida = []
        for carpeta, subdirs, archivos in os.walk(self.raiz):
            subdirs[:] = sorted(d for d in subdirs if d not in IGNORADAS and not d.startswith("."))
            for nombre in sorted(archivos):
                if nombre.startswith("."):
                    continue
                salida.append(os.path.relpath(os.path.join(carpeta, nombre), self.raiz).replace(os.sep, "/"))
                if len(salida) >= MAX_ARCHIVOS * 2:
                    return salida
        return salida

    @staticmethod
    def _leer(ruta: str) -> Optional[str]:
        try:
            with open(ruta, "rb") as f:
                datos = f.read(MAX_BYTES + 1)
        except OSError:
            return None
        if b"\0" in datos[:8192]:
            return None
        return datos.decode("utf-8", "replace")

    # ------------------------------------------------------------------ sincronizar
    def sincronizar(self, forzar: bool = False) -> Dict[str, Any]:
        """ Relee solo lo que cambió. Rápido cuando no hay cambios (solo mira fecha y tamaño). """
        t0 = time.time()
        if self._meta("reindexar") == "1":
            forzar = True
            self._guardar_meta("reindexar", "0")
        with self._lock:
            listado = self._listar()
            with self.conectar() as c:
                conocidos = {f["ruta"]: (f["mtime"], f["tamano"], f["sha"])
                             for f in c.execute("SELECT ruta, mtime, tamano, sha FROM archivos")}
            inicial = not conocidos
            candidatos = [r for r, (mt, tam) in listado.items()
                          if forzar or r not in conocidos or conocidos[r][0] != mt or conocidos[r][1] != tam]
            borrados = [r for r in conocidos if r not in listado]
            nuevos, modificados, tocados = [], [], []
            version = self.version + 1
            with self.conectar() as c:
                for rel in candidatos:
                    texto = self._leer(os.path.join(self.raiz, rel))
                    if texto is None:
                        continue
                    sha = _sha(texto)
                    mt, tam = listado[rel]
                    if rel in conocidos and conocidos[rel][2] == sha and not forzar:
                        c.execute("UPDATE archivos SET mtime = ?, tamano = ? WHERE ruta = ?", (mt, tam, rel))
                        continue
                    previo = None
                    if rel in conocidos and not inicial:
                        f = c.execute("SELECT contenido FROM archivos WHERE ruta = ?", (rel,)).fetchone()
                        previo = zlib.decompress(f["contenido"]).decode("utf-8", "replace") if f and f["contenido"] else ""
                    viejos = self._simbolos_de(c, rel) if previo is not None else {}
                    self._indexar_archivo(c, rel, texto, sha, mt, tam, version)
                    tocados.append(rel)
                    if inicial:
                        continue
                    if previo is None:
                        nuevos.append(rel)
                        self._anotar_cambio(c, version, rel, "nuevo", "", texto, {}, self._simbolos_de(c, rel))
                    else:
                        modificados.append(rel)
                        self._anotar_cambio(c, version, rel, "modificado", previo, texto, viejos, self._simbolos_de(c, rel))
                for rel in borrados:
                    viejos = self._simbolos_de(c, rel)
                    self._borrar_archivo(c, rel)
                    tocados.append(rel)
                    self._anotar_cambio(c, version, rel, "borrado", "", "", viejos, {})
                hubo = bool(tocados)
                if hubo:
                    self._guardar_meta("version", version, c)
                    self._guardar_meta("actualizado", datetime.now().isoformat(timespec="seconds"), c)
                    if not inicial:
                        self._marcar_revisar(c, set(modificados) | set(borrados), version)
                    c.execute("DELETE FROM cambios WHERE id <= (SELECT MAX(id) FROM cambios) - ?",
                              (MAX_CAMBIOS_GUARDADOS,))
                if inicial and hubo:
                    self._guardar_meta("version_vista", version, c)
            if hubo:
                self._resolver_importaciones()
                self._resolver_llamadas()
                self._vectores = None
        self._ultima_sincronizacion = time.time()
        return {"inicial": inicial, "nuevos": len(nuevos) if not inicial else len(tocados),
                "modificados": len(modificados), "borrados": len(borrados),
                "rutas": (nuevos + modificados + borrados)[:50], "version": self.version,
                "archivos": len(listado), "segundos": round(time.time() - t0, 3)}

    def _simbolos_de(self, c, rel: str) -> Dict[str, str]:
        return {f["nombre"]: f["sha"] for f in c.execute("SELECT nombre, sha FROM simbolos WHERE ruta = ?", (rel,))}

    def _borrar_archivo(self, c, rel: str, conservar_archivo: bool = False):
        ids = [f["id"] for f in c.execute("SELECT id FROM fragmentos WHERE ruta = ?", (rel,))]
        for i in ids:
            c.execute("DELETE FROM fragmentos_fts WHERE rowid = ?", (i,))
        c.execute("DELETE FROM fragmentos WHERE ruta = ?", (rel,))
        c.execute("DELETE FROM simbolos WHERE ruta = ?", (rel,))
        c.execute("DELETE FROM usos WHERE ruta = ?", (rel,))
        c.execute("DELETE FROM alias WHERE ruta = ?", (rel,))
        c.execute("DELETE FROM importaciones WHERE ruta = ?", (rel,))
        c.execute("DELETE FROM hechos WHERE ruta = ? AND origen = 'codigo'", (rel,))
        if not conservar_archivo:
            c.execute("DELETE FROM archivos WHERE ruta = ?", (rel,))

    def _indexar_archivo(self, c, rel: str, texto: str, sha: str, mtime: float, tamano: int, version: int):
        lenguaje = lenguaje_de(rel) or "texto"
        if lenguaje == "cuaderno":
            texto = self._texto_de_cuaderno(texto)
        self._borrar_archivo(c, rel, conservar_archivo=True)
        lineas = texto.splitlines()
        importados: List[str] = []
        docmod = ""
        if lenguaje == "python" or (lenguaje == "cuaderno"):
            simbolos, importados, docmod = simbolos_python(texto)
        elif lenguaje == "md":
            simbolos = secciones_markdown(texto)
        else:
            simbolos = simbolos_genericos(texto, lenguaje)
            importados = importaciones_genericas(texto, lenguaje)
        resumen = self._resumen_basico(rel, lenguaje, texto, docmod, simbolos)
        c.execute("""INSERT INTO archivos (ruta, sha, mtime, tamano, lenguaje, lineas, tokens, resumen, contenido, version)
                     VALUES (?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(ruta) DO UPDATE SET sha=excluded.sha, mtime=excluded.mtime,
                       tamano=excluded.tamano, lenguaje=excluded.lenguaje, lineas=excluded.lineas,
                       tokens=excluded.tokens, resumen=excluded.resumen, contenido=excluded.contenido,
                       version=excluded.version""",
                  (rel, sha, mtime, tamano, lenguaje, len(lineas), estimar_tokens(texto), resumen,
                   zlib.compress(texto.encode("utf-8", "replace"), 6), version))
        for s in simbolos:
            cuerpo = "\n".join(lineas[s["ini"] - 1:s["fin"]])
            c.execute("INSERT INTO simbolos (ruta, nombre, corto, tipo, firma, doc, ini, fin, padre, sha) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (rel, s["nombre"], s["corto"], s["tipo"], s["firma"], s["doc"], s["ini"], s["fin"],
                       s["padre"], _sha(cuerpo)))
            for uso in s.get("usos") or []:
                if isinstance(uso, tuple):
                    nombre, linea, receptor = (uso + ("",))[:3] if len(uso) == 2 else uso
                else:
                    nombre, linea, receptor = uso, s["ini"], None
                c.execute("INSERT INTO usos (ruta, nombre, linea, dentro, receptor) VALUES (?,?,?,?,?)",
                          (rel, nombre, linea, s["nombre"], receptor))
        if lenguaje in ("python", "cuaderno"):
            for alias, destino in alias_python(texto):
                c.execute("INSERT INTO alias VALUES (?,?,?)", (rel, alias, destino))
        for h in extraer_hechos(rel, lenguaje, texto, simbolos):
            c.execute("INSERT INTO hechos (s, r, o, ruta, linea, origen, version) VALUES (?,?,?,?,?,'codigo',?)",
                      (h[0], h[1], h[2], rel, h[3], version))
        for modulo in importados:
            c.execute("INSERT INTO importaciones VALUES (?, ?)", (rel, "?" + modulo))
        for frag in self._fragmentar(rel, lenguaje, lineas, simbolos):
            cur = c.execute("INSERT INTO fragmentos (ruta, simbolo, tipo, ini, fin, texto, sha, tokens) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (rel, frag["simbolo"], frag["tipo"], frag["ini"], frag["fin"], frag["texto"],
                             _sha(rel + "\0" + frag["texto"]), estimar_tokens(frag["texto"])))
            c.execute("INSERT INTO fragmentos_fts (rowid, ruta, simbolo, terminos) VALUES (?,?,?,?)",
                      (cur.lastrowid, " ".join(terminos(rel)), " ".join(terminos(frag["simbolo"] or "")),
                       " ".join(terminos(frag["texto"]))))

    @staticmethod
    def _texto_de_cuaderno(texto: str) -> str:
        try:
            nb = json.loads(texto)
        except ValueError:
            return texto
        partes = []
        for celda in nb.get("cells", []):
            fuente = "".join(celda.get("source") or [])
            if celda.get("cell_type") == "markdown":
                partes.append("\n".join("# " + l for l in fuente.splitlines()))
            else:
                partes.append(fuente)
        return "\n\n".join(partes)

    @staticmethod
    def _resumen_basico(rel: str, lenguaje: str, texto: str, docmod: str, simbolos: List[Simbolo]) -> str:
        if docmod:
            return _primera_linea(docmod)
        if lenguaje == "md":
            for l in texto.splitlines():
                if l.strip().startswith("#"):
                    return l.strip("# ").strip()[:200]
        lineas = texto.splitlines()
        cabecera = []
        for l in lineas[:40]:
            s = l.strip()
            if not s or s.startswith("#!") or s.startswith("# -*-"):
                if cabecera:
                    break
                continue
            if _COMENTARIO_LINEA.match(l) or s.startswith('"""') or s.startswith("'''"):
                limpio = _COMENTARIO_LINEA.sub("", s).strip("\"' */")
                if limpio:
                    cabecera.append(limpio)
                if len(cabecera) >= 2:
                    break
            elif cabecera or not s.startswith(("import", "from", "#include", "package", "using", "use ")):
                break
        return " ".join(cabecera)[:200]

    def _fragmentar(self, rel: str, lenguaje: str, lineas: List[str], simbolos: List[Simbolo]) -> List[Dict[str, Any]]:
        """ Un fragmento por función/método/sección; las clases como ficha (cabecera, doc y firmas de
        sus métodos, sin repetir los cuerpos); el código suelto en bloques. """
        fragmentos: List[Dict[str, Any]] = []
        cubiertas = [False] * (len(lineas) + 2)

        def agregar(ini: int, fin: int, simbolo: str, tipo: str, texto: Optional[str] = None):
            if texto is None:
                texto = "\n".join(lineas[ini - 1:fin])
            if not texto.strip():
                return
            fragmentos.append({"ini": ini, "fin": fin, "simbolo": simbolo, "tipo": tipo, "texto": texto})

        hojas = [s for s in simbolos if s["tipo"] not in ("clase", "espacio")]
        for s in simbolos:
            if s["tipo"] in ("clase", "espacio"):
                hijos = [h for h in simbolos if h["padre"] == s["nombre"]]
                cabecera_fin = min([h["ini"] - 1 for h in hijos] + [s["fin"]])
                cabecera_fin = min(cabecera_fin, s["ini"] + 40)
                texto = "\n".join(lineas[s["ini"] - 1:cabecera_fin])
                if hijos:
                    texto += "\n    # métodos: " + "; ".join(f"{h['firma']} (l. {h['ini']})" for h in hijos[:40])
                agregar(s["ini"], cabecera_fin, s["nombre"], s["tipo"], texto)
                if not hijos:
                    for k in range(s["ini"], s["fin"] + 1):
                        cubiertas[k] = True
                else:
                    for k in range(s["ini"], cabecera_fin + 1):
                        cubiertas[k] = True
        for s in hojas:
            largo = s["fin"] - s["ini"] + 1
            if largo <= MAX_LINEAS_FRAGMENTO:
                agregar(s["ini"], s["fin"], s["nombre"], s["tipo"])
            else:
                parte = 1
                for ini in range(s["ini"], s["fin"] + 1, MAX_LINEAS_FRAGMENTO):
                    fin = min(s["fin"], ini + MAX_LINEAS_FRAGMENTO - 1)
                    texto = "\n".join(lineas[ini - 1:fin])
                    if parte > 1:
                        texto = f"# {s['firma']}  (continuación {parte})\n" + texto
                    agregar(ini, fin, s["nombre"], s["tipo"], texto)
                    parte += 1
            for k in range(s["ini"], s["fin"] + 1):
                cubiertas[k] = True
        # Código suelto (imports, constantes, script principal, archivos sin símbolos)
        n = 1
        while n <= len(lineas):
            if cubiertas[n]:
                n += 1
                continue
            ini = n
            while n <= len(lineas) and not cubiertas[n] and n - ini < LINEAS_BLOQUE_SUELTO:
                n += 1
            if any(lineas[k - 1].strip() for k in range(ini, n)):
                agregar(ini, n - 1, "", "bloque")
        fragmentos.sort(key=lambda f: f["ini"])
        return fragmentos

    def _anotar_cambio(self, c, version: int, rel: str, tipo: str, previo: str, nuevo: str,
                       viejos: Dict[str, str], nuevos: Dict[str, str]):
        diff_lineas = list(difflib.unified_diff(previo.splitlines(), nuevo.splitlines(), lineterm="", n=2))
        mas = sum(1 for l in diff_lineas if l.startswith("+") and not l.startswith("+++"))
        menos = sum(1 for l in diff_lineas if l.startswith("-") and not l.startswith("---"))
        diff = "\n".join(diff_lineas[2:]) if tipo == "modificado" else ""
        if len(diff) > MAX_DIFF:
            diff = diff[:MAX_DIFF] + "\n[… diff recortado]"
        simbolos = {"nuevos": sorted(set(nuevos) - set(viejos)), "borrados": sorted(set(viejos) - set(nuevos)),
                    "modificados": sorted(n for n in set(viejos) & set(nuevos) if viejos[n] != nuevos[n])}
        if tipo == "modificado" and not (mas or menos):
            return
        c.execute("INSERT INTO cambios (version, ruta, tipo, cuando, simbolos, diff, mas, menos) VALUES (?,?,?,?,?,?,?,?)",
                  (version, rel, tipo, datetime.now().isoformat(timespec="seconds"),
                   json.dumps(simbolos, ensure_ascii=False), diff, mas if tipo != "borrado" else 0,
                   menos if tipo != "nuevo" else 0))

    def _marcar_revisar(self, c, rutas: Set[str], version: int):
        if not rutas:
            return
        for f in c.execute("SELECT id, rutas FROM conocimiento WHERE revisar = 0").fetchall():
            try:
                suyas = set(json.loads(f["rutas"] or "[]"))
            except ValueError:
                suyas = set()
            if suyas & rutas:
                c.execute("UPDATE conocimiento SET revisar = ? WHERE id = ?", (version, f["id"]))

    def _resolver_importaciones(self):
        """ Traduce los módulos importados a archivos del proyecto (los de fuera se descartan) """
        with self.conectar() as c:
            rutas = [f["ruta"] for f in c.execute("SELECT ruta FROM archivos")]
            por_modulo: Dict[str, str] = {}
            por_nombre: Dict[str, List[str]] = {}
            for r in rutas:
                sin_ext = r.rsplit(".", 1)[0]
                por_modulo[sin_ext.replace("/", ".")] = r
                if sin_ext.endswith("/__init__"):
                    por_modulo[sin_ext[:-9].replace("/", ".")] = r
                por_nombre.setdefault(os.path.basename(r), []).append(r)
                por_nombre.setdefault(os.path.basename(sin_ext), []).append(r)
            pendientes = c.execute("SELECT rowid, ruta, destino FROM importaciones WHERE destino LIKE '?%'").fetchall()
            for f in pendientes:
                destino = self._resolver(f["ruta"], f["destino"][1:], por_modulo, por_nombre)
                if destino and destino != f["ruta"]:
                    c.execute("UPDATE importaciones SET destino = ? WHERE rowid = ?", (destino, f["rowid"]))
                else:
                    c.execute("DELETE FROM importaciones WHERE rowid = ?", (f["rowid"],))
            c.execute("DELETE FROM importaciones WHERE rowid NOT IN (SELECT MIN(rowid) FROM importaciones GROUP BY ruta, destino)")

    def _resolver_llamadas(self):
        """ Cada llamada, a su símbolo exacto (archivo + nombre completo). Por orden de confianza:
          · mismo archivo (función de primer nivel o clase), o método de la misma clase y sus bases
          · lo que dejaron los import (alias de módulo o de símbolo)
          · un nombre definido una sola vez en el proyecto, si no es un verbo común de librería
        Lo demás queda sin enlazar: es preferible a unir cualquier .post() con Motor.post.
        Se rehace entera tras cada cambio (depende de todos los archivos): ~1 s en Prig. """
        with self.conectar() as c:
            simbolos = [dict(f) for f in c.execute(
                "SELECT ruta, nombre, corto, tipo, padre, firma FROM simbolos WHERE tipo IN ('funcion','metodo','clase')")]
            rutas = [f["ruta"] for f in c.execute("SELECT ruta FROM archivos")]
            usos = [dict(f) for f in c.execute("SELECT ruta, nombre, linea, dentro, receptor FROM usos")]
            alias = [dict(f) for f in c.execute("SELECT ruta, nombre, destino FROM alias")]
            bases_raw = [dict(f) for f in c.execute("SELECT s, o, ruta FROM hechos WHERE r = 'hereda'")]
        primer_nivel: Dict[str, Dict[str, str]] = {}          # ruta → corto → nombre
        metodos: Dict[Tuple[str, str], Dict[str, str]] = {}    # (ruta, clase) → corto → nombre
        global_: Dict[str, List[Tuple[str, str]]] = {}         # corto → [(ruta, nombre)]
        clases: Dict[str, List[Tuple[str, str]]] = {}          # nombre corto de clase → [(ruta, nombre)]
        for x in simbolos:
            if not x["padre"]:
                primer_nivel.setdefault(x["ruta"], {})[x["corto"]] = x["nombre"]
            elif x["tipo"] == "metodo":
                metodos.setdefault((x["ruta"], x["padre"]), {})[x["corto"]] = x["nombre"]
            global_.setdefault(x["corto"], []).append((x["ruta"], x["nombre"]))
            if x["tipo"] == "clase":
                clases.setdefault(x["corto"], []).append((x["ruta"], x["nombre"]))
        por_modulo: Dict[str, str] = {}
        por_nombre: Dict[str, List[str]] = {}
        for r in rutas:
            sin_ext = r.rsplit(".", 1)[0]
            por_modulo[sin_ext.replace("/", ".")] = r
            if sin_ext.endswith("/__init__"):
                por_modulo[sin_ext[:-9].replace("/", ".")] = r
            por_nombre.setdefault(os.path.basename(r), []).append(r)
        # alias: (ruta, nombre) → (archivo destino, símbolo o None si es un módulo)
        resueltos: Dict[Tuple[str, str], Tuple[str, Optional[str]]] = {}
        for a in alias:
            modulo = self._resolver(a["ruta"], a["destino"], por_modulo, por_nombre)
            destino_mod = por_modulo.get(a["destino"].lstrip(".").replace("/", "."))
            if modulo and (modulo == destino_mod or modulo.rsplit(".", 1)[0].replace("/", ".").endswith(a["destino"].lstrip("."))):
                resueltos[(a["ruta"], a["nombre"])] = (modulo, None)
            elif "." in a["destino"].lstrip("."):
                padre, simbolo = a["destino"].rsplit(".", 1)
                archivo = self._resolver(a["ruta"], padre, por_modulo, por_nombre) if padre.strip(".") else None
                if archivo and simbolo in primer_nivel.get(archivo, {}):
                    resueltos[(a["ruta"], a["nombre"])] = (archivo, primer_nivel[archivo][simbolo])
                elif modulo:
                    resueltos[(a["ruta"], a["nombre"])] = (modulo, None)
        bases: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        for b in bases_raw:
            corto = b["o"].split(".")[-1].split("[")[0]
            cand = [x for x in clases.get(corto, []) if x[0] == b["ruta"]] or clases.get(corto, [])
            if len(cand) == 1:
                bases.setdefault((b["ruta"], b["s"]), []).append(cand[0])

        # Tipo de retorno anotado (-> "motor_moe.Motor"): permite seguir self.motor_moe().post(...)
        retorno: Dict[Tuple[str, str], str] = {}
        for x in simbolos:
            m = re.search(r"->\s*['\"]?([\w.]+)['\"]?\s*$", x.get("firma") or "")
            if m:
                retorno[(x["ruta"], x["nombre"])] = m.group(1).split(".")[-1]

        def clase_de_llamada(ruta: str, clase: str, receptor: str) -> Optional[Tuple[str, str]]:
            """ El receptor es una llamada (f(...) o self.f(...)): la clase que devuelve f """
            base = receptor.split("(", 1)[0]
            partes = base.split(".")
            if len(partes) == 2 and partes[0] in ("self", "cls") and clase:
                fn = metodo_en(ruta, clase, partes[1])
            elif len(partes) == 1:
                fn = (ruta, primer_nivel[ruta][partes[0]]) if partes[0] in primer_nivel.get(ruta, {}) else unico(partes[0], ruta)
            else:
                return None
            if fn and fn[1] in {x[1] for x in clases.get(fn[1].split(".")[-1], [])}:
                return fn                                  # Clase(...).metodo(): una instancia de esa clase
            tipo = retorno.get(fn) if fn else None
            cand = clases.get(tipo or "", [])
            return cand[0] if len(cand) == 1 else None

        def unico(nombre: str, desde: Optional[str] = None) -> Optional[Tuple[str, str]]:
            """ El único símbolo con ese nombre en el proyecto, del mismo lenguaje que quien llama
            (un JS no llama a una función de Python aunque se llamen igual) """
            cand = global_.get(nombre, [])
            if desde is not None:
                familia = lenguaje_de(desde)
                cand = [x for x in cand if lenguaje_de(x[0]) == familia]
            return cand[0] if len(cand) == 1 and nombre not in VERBOS_COMUNES else None

        def metodo_en(ruta: str, clase: str, nombre: str, profundidad: int = 0) -> Optional[Tuple[str, str]]:
            if nombre in metodos.get((ruta, clase), {}):
                return ruta, metodos[(ruta, clase)][nombre]
            if profundidad < 4:
                for base in bases.get((ruta, clase), []):
                    r = metodo_en(base[0], base[1], nombre, profundidad + 1)
                    if r:
                        return r
            return None

        filas = []
        for u in usos:
            ruta, n, receptor, dentro = u["ruta"], u["nombre"], u["receptor"], u["dentro"]
            clase = dentro.rsplit(".", 1)[0] if "." in dentro else ""
            destino, confianza = None, "exacta"
            if receptor is None:                                   # JS, C…: sin receptor conocido
                if n in primer_nivel.get(ruta, {}):
                    destino = (ruta, primer_nivel[ruta][n])
                elif clase and metodo_en(ruta, clase, n):
                    destino = metodo_en(ruta, clase, n)
                else:
                    destino, confianza = unico(n, ruta), "unica"
            elif receptor == "":
                if n in primer_nivel.get(ruta, {}):
                    destino = (ruta, primer_nivel[ruta][n])
                elif (ruta, n) in resueltos:
                    archivo, simbolo = resueltos[(ruta, n)]
                    destino = (archivo, simbolo) if simbolo else None
                else:
                    destino, confianza = unico(n, ruta), "unica"
                if destino and destino[1] in {x[1] for x in clases.get(destino[1].split(".")[-1], [])}:
                    init = metodo_en(destino[0], destino[1], "__init__")
                    destino = init or destino                      # llamar a una clase es llamar a su __init__
            elif receptor in ("self", "cls", "super()"):
                destino = metodo_en(ruta, clase, n) if clase else None
                if receptor == "super()" and clase:
                    destino = next((metodo_en(b[0], b[1], n) for b in bases.get((ruta, clase), []) if metodo_en(b[0], b[1], n)), None)
            elif (ruta, receptor) in resueltos and resueltos[(ruta, receptor)][1] is None:
                archivo = resueltos[(ruta, receptor)][0]
                if n in primer_nivel.get(archivo, {}):
                    destino = (archivo, primer_nivel[archivo][n])
            elif (ruta, receptor) in resueltos:                    # alias de una clase: Clase.metodo(...)
                archivo, simbolo = resueltos[(ruta, receptor)]
                destino = metodo_en(archivo, simbolo, n)
            elif receptor in clases and len(clases[receptor]) == 1:
                destino = metodo_en(clases[receptor][0][0], clases[receptor][0][1], n)
            elif receptor.endswith(")") and clase_de_llamada(ruta, clase, receptor):
                c_ruta, c_nombre = clase_de_llamada(ruta, clase, receptor)
                destino = metodo_en(c_ruta, c_nombre, n)
            else:                                                  # self.banco.anotar(…), obj.metodo(…)
                destino, confianza = unico(n, ruta), "aproximada"
            if destino and destino != (ruta, dentro):
                filas.append((ruta, dentro, destino[0], destino[1], u["linea"], confianza))
        with self.conectar() as c:
            c.execute("DELETE FROM llamadas")
            c.executemany("INSERT INTO llamadas VALUES (?,?,?,?,?,?)", filas)

    @staticmethod
    def _resolver(origen: str, modulo: str, por_modulo: Dict[str, str], por_nombre: Dict[str, List[str]]) -> Optional[str]:
        carpeta = os.path.dirname(origen)
        if modulo.startswith("./") or modulo.startswith("../") or "/" in modulo:
            base = os.path.normpath(os.path.join(carpeta, modulo)).replace(os.sep, "/")
            for cand in (base, *(base + e for e in (".js", ".ts", ".tsx", ".jsx", ".mjs", ".h", ".hpp", ".cpp")),
                         base + "/index.js", base + "/index.ts"):
                if cand in por_nombre.get(os.path.basename(cand), []):
                    return cand
            candidatos = por_nombre.get(os.path.basename(modulo), [])
            return candidatos[0] if len(candidatos) == 1 else None
        if modulo.startswith("."):
            nivel = len(modulo) - len(modulo.lstrip("."))
            paquete = carpeta.split("/") if carpeta else []
            paquete = paquete[:len(paquete) - (nivel - 1)] if nivel > 1 else paquete
            modulo = ".".join([p for p in paquete if p] + ([modulo.lstrip(".")] if modulo.lstrip(".") else []))
        partes = modulo.replace("::", ".").split(".")
        prefijos = [carpeta.replace("/", ".")] if carpeta else []
        prefijos += [".".join(carpeta.split("/")[:k]) for k in range(len(carpeta.split("/")) - 1, 0, -1)] if carpeta else []
        prefijos.append("")
        for k in range(len(partes), 0, -1):
            nombre = ".".join(partes[:k])
            for pre in prefijos:
                cand = f"{pre}.{nombre}" if pre else nombre
                if cand in por_modulo:
                    return por_modulo[cand]
        return None

    # ------------------------------------------------------------------ vectores
    def vectores_pendientes(self) -> int:
        with self.conectar() as c:
            f = c.execute("""SELECT COUNT(DISTINCT sha) n FROM fragmentos
                             WHERE 'f:' || sha NOT IN (SELECT clave FROM vectores)""").fetchone()
            g = c.execute("SELECT COUNT(*) n FROM conocimiento WHERE 'c:' || id NOT IN (SELECT clave FROM vectores)").fetchone()
            h = c.execute("SELECT COUNT(*) n FROM resoluciones WHERE 'r:' || id NOT IN (SELECT clave FROM vectores)").fetchone()
        return int(f["n"] + g["n"] + h["n"])

    def _embebedor_ok(self) -> bool:
        if not self.embeber:
            return False
        try:
            return self.embebedor_listo() if self.embebedor_listo else True
        except Exception:
            return False

    def indexar_vectores(self, maximo: int = 64, lote: int = 16) -> Dict[str, Any]:
        """ Embebe lo que falta (fragmentos nuevos o cambiados, conocimiento, resoluciones).
        Por tandas pequeñas: lo llama el vigilante sin acaparar la CPU. """
        if not self._embebedor_ok():
            return {"ok": False, "hechos": 0, "pendientes": self.vectores_pendientes()}
        with self.conectar() as c:
            filas = [("f:" + f["sha"], self._texto_para_vector(f["ruta"], f["simbolo"], f["texto"]))
                     for f in c.execute("""SELECT ruta, simbolo, texto, sha FROM fragmentos
                                          WHERE 'f:' || sha NOT IN (SELECT clave FROM vectores)
                                          GROUP BY sha LIMIT ?""", (maximo,))]
            if len(filas) < maximo:
                filas += [("c:" + str(f["id"]), f"{f['titulo']}\n{f['texto']}"[:1500])
                          for f in c.execute("""SELECT id, titulo, texto FROM conocimiento
                                               WHERE 'c:' || id NOT IN (SELECT clave FROM vectores) LIMIT ?""",
                                             (maximo - len(filas),))]
            if len(filas) < maximo:
                filas += [("r:" + str(f["id"]), f"{f['pregunta']}\n{f['resumen']}"[:1500])
                          for f in c.execute("""SELECT id, pregunta, resumen FROM resoluciones
                                               WHERE 'r:' || id NOT IN (SELECT clave FROM vectores) LIMIT ?""",
                                             (maximo - len(filas),))]
        hechos = 0
        for i in range(0, len(filas), lote):
            tanda = filas[i:i + lote]
            try:
                vectores = self.embeber([t for _, t in tanda])
            except Exception as e:
                return {"ok": False, "hechos": hechos, "error": str(e), "pendientes": self.vectores_pendientes()}
            if len(vectores) != len(tanda):
                break
            with self.conectar() as c:
                for (clave, _), v in zip(tanda, vectores):
                    c.execute("INSERT OR REPLACE INTO vectores VALUES (?,?,?)", (clave, _empaquetar(v), self.modelo_vectores))
            hechos += len(tanda)
        if hechos:
            self._vectores = None
        return {"ok": True, "hechos": hechos, "pendientes": self.vectores_pendientes()}

    @staticmethod
    def _texto_para_vector(ruta: str, simbolo: str, texto: str) -> str:
        return f"{ruta} {simbolo or ''}\n{texto}"[:1800]

    def _cargar_vectores(self) -> Dict[str, array.array]:
        if self._vectores is None:
            with self.conectar() as c:
                self._vectores = {f["clave"]: _desempaquetar(f["vector"]) for f in c.execute("SELECT clave, vector FROM vectores")}
        return self._vectores

    def _vector_consulta(self, texto: str) -> Optional[List[float]]:
        if not self._cargar_vectores() or not self._embebedor_ok():
            return None
        try:
            # La pregunta, siempre en la CPU (~0,1 s): en la GPU obligaría a cargar el embebedor justo
            # antes de que el generador la necesite
            consulta = getattr(self.embeber, "consulta", None)
            v = consulta(texto[:1500]) if consulta else self.embeber([texto[:1500]])[0]
        except Exception:
            return None
        norma = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norma for x in v]

    # ------------------------------------------------------------------ búsqueda
    @staticmethod
    def _consulta_fts(terms: List[str]) -> Optional[str]:
        """ Cada término, y para palabras largas también su raíz como prefijo («guardan» → guard*),
        que hace de lematizador barato en castellano y en inglés """
        partes = []
        for t in terms:
            t = t.replace('"', "")
            if not t:
                continue
            partes.append(f'"{t}"')
            if len(t) >= 6 and t.isalpha():
                partes.append(f'"{t[:max(4, len(t) - 3)]}"*')
        return " OR ".join(dict.fromkeys(partes)) if partes else None

    def buscar(self, consulta: str, k: int = 20, vector: Optional[List[float]] = None,
               con_vector: bool = True) -> List[Dict[str, Any]]:
        """ Fragmentos más relevantes: fusión por rangos de texto (BM25), vectores, símbolos
        nombrados y rutas mencionadas, más una pizca a lo que cambió hace poco. """
        listas: List[Tuple[List[int], float]] = []
        terms = terminos_consulta(consulta)
        with self.conectar() as c:
            q = self._consulta_fts(terms)
            if q:
                try:
                    ids = [f["rowid"] for f in c.execute(
                        "SELECT rowid FROM fragmentos_fts WHERE fragmentos_fts MATCH ? "
                        "ORDER BY bm25(fragmentos_fts, 2.0, 4.0, 1.0) LIMIT 80", (q,))]
                    listas.append((ids, 1.0))
                except sqlite3.OperationalError:
                    pass
            nombrados = identificadores_nombrados(consulta)
            if nombrados:
                marcas = ",".join("?" * len(nombrados))
                ids = [f["id"] for f in c.execute(
                    f"""SELECT fr.id FROM fragmentos fr JOIN simbolos s
                        ON s.ruta = fr.ruta AND fr.simbolo = s.nombre
                        WHERE s.corto IN ({marcas}) OR s.nombre IN ({marcas}) ORDER BY fr.ini""",
                    list(nombrados) * 2)]
                if ids:
                    listas.append((ids[:30], 2.0))
            rutas = self._rutas_mencionadas(c, consulta)
            if rutas:
                marcas = ",".join("?" * len(rutas))
                ids = [f["id"] for f in c.execute(
                    f"SELECT id FROM fragmentos WHERE ruta IN ({marcas}) ORDER BY ini LIMIT 40", list(rutas))]
                listas.append((ids, 1.5))
            if con_vector:
                qv = vector if vector is not None else self._vector_consulta(consulta)
                if qv is not None:
                    vectores = self._cargar_vectores()
                    por_sha: Dict[str, List[int]] = {}
                    for f in c.execute("SELECT id, sha FROM fragmentos"):
                        por_sha.setdefault(f["sha"], []).append(f["id"])
                    puntuados = []
                    for sha, ids_sha in por_sha.items():
                        v = vectores.get("f:" + sha)
                        if v is not None:
                            puntuados.append((_coseno(qv, v), ids_sha[0]))
                    puntuados.sort(reverse=True)
                    if puntuados:
                        # Solo los cercanos al mejor: el resto del proyecto no es «algo relevante»
                        piso = max(0.25, puntuados[0][0] - 0.2)
                        listas.append(([i for sim, i in puntuados[:80] if sim >= piso], 1.2))
            recientes = [f["ruta"] for f in c.execute(
                "SELECT DISTINCT ruta FROM cambios WHERE version > ? ORDER BY id DESC LIMIT 20",
                (max(0, self.version - 5),))]
            puntos: Dict[int, float] = {}
            for ids, peso in listas:
                for rango, i in enumerate(ids):
                    puntos[i] = puntos.get(i, 0.0) + peso / (RRF_K + rango + 1)
            if not puntos:
                return []
            mejores = sorted(puntos.items(), key=lambda x: -x[1])[:max(k * 2, 40)]
            corte = mejores[0][1] * 0.25          # lo que apenas coincide no merece contexto
            mejores = [(i, p) for i, p in mejores if p >= corte]
            marcas = ",".join("?" * len(mejores))
            filas = {f["id"]: dict(f) for f in c.execute(
                f"SELECT id, ruta, simbolo, tipo, ini, fin, texto, tokens FROM fragmentos WHERE id IN ({marcas})",
                [i for i, _ in mejores])}
        habla_de_tests = bool(re.search(r"\b(tests?|pruebas?|unittest|pytest|spec)\b", consulta or "", re.I))
        salida = []
        for i, p in mejores:
            f = filas.get(i)
            if not f:
                continue
            if f["ruta"] in recientes:
                p *= 1.1
            if f["tipo"] == "bloque" and f["ruta"].endswith((".json", ".yaml", ".yml", ".csv", ".toml")):
                p *= 0.7
            if not habla_de_tests and _ES_TEST.search(f["ruta"]):
                p *= 0.5
            f["puntos"] = p
            salida.append(f)
        salida.sort(key=lambda f: -f["puntos"])
        return salida[:k]

    def _rutas_mencionadas(self, c, texto: str) -> Set[str]:
        candidatos = set(re.findall(r"[\w./-]+\.[A-Za-z]{1,6}\b", texto or ""))
        if not candidatos:
            return set()
        salida = set()
        rutas = [f["ruta"] for f in c.execute("SELECT ruta FROM archivos")]
        for cand in candidatos:
            cand = cand.strip("./")
            for r in rutas:
                if r == cand or r.endswith("/" + cand):
                    salida.add(r)
        return salida

    def vecinos(self, fragmentos: List[Dict[str, Any]], limite: int = 12) -> List[Dict[str, Any]]:
        """ Las definiciones que llaman los fragmentos elegidos y quién los llama (1 salto, por
        aristas resueltas al símbolo exacto: no las de cualquier función homónima) """
        ya = {(f["ruta"], f["simbolo"]) for f in fragmentos}
        salida: List[Dict[str, Any]] = []
        with self.conectar() as c:
            for f in fragmentos[:6]:
                if not f.get("simbolo"):
                    continue
                for s in c.execute("""SELECT DISTINCT s.ruta, s.nombre, s.firma, s.doc, s.ini, s.fin
                                      FROM llamadas l JOIN simbolos s ON s.ruta = l.a_ruta AND s.nombre = l.a_nombre
                                      WHERE l.ruta = ? AND l.desde = ? ORDER BY l.linea LIMIT 20""", (f["ruta"], f["simbolo"])):
                    if (s["ruta"], s["nombre"]) not in ya:
                        ya.add((s["ruta"], s["nombre"]))
                        salida.append({**dict(s), "relacion": f"llamada desde {f['simbolo']}"})
                for u in c.execute("""SELECT DISTINCT s.ruta, s.nombre, s.firma, s.doc, s.ini, s.fin
                                      FROM llamadas l JOIN simbolos s ON s.ruta = l.ruta AND s.nombre = l.desde
                                      WHERE l.a_ruta = ? AND l.a_nombre = ? LIMIT 8""", (f["ruta"], f["simbolo"])):
                    if (u["ruta"], u["nombre"]) not in ya:
                        ya.add((u["ruta"], u["nombre"]))
                        salida.append({**dict(u), "relacion": f"llama a {f['simbolo'].split('.')[-1]}"})
        return salida[:limite]

    def buscar_conocimiento(self, consulta: str, k: int = 6, vector: Optional[List[float]] = None,
                            rutas: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        puntos: Dict[int, float] = {}
        with self.conectar() as c:
            q = self._consulta_fts(terminos_consulta(consulta))
            if q:
                try:
                    for rango, f in enumerate(c.execute(
                            "SELECT rowid FROM conocimiento_fts WHERE conocimiento_fts MATCH ? "
                            "ORDER BY bm25(conocimiento_fts, 3.0, 1.0) LIMIT 30", (q,))):
                        puntos[f["rowid"]] = puntos.get(f["rowid"], 0) + 1.0 / (RRF_K + rango + 1)
                except sqlite3.OperationalError:
                    pass
            if vector is not None:
                vectores = self._cargar_vectores()
                sims = sorted(((_coseno(vector, v), int(cl[2:])) for cl, v in vectores.items() if cl.startswith("c:")),
                              reverse=True)[:30]
                for rango, (sim, i) in enumerate(sims):
                    if sim >= 0.45:
                        puntos[i] = puntos.get(i, 0) + 1.2 / (RRF_K + rango + 1)
            filas = [dict(f) for f in c.execute("SELECT * FROM conocimiento")] if (puntos or rutas) else []
        salida = []
        for f in filas:
            p = puntos.get(f["id"], 0.0)
            suyas = set(json.loads(f["rutas"] or "[]"))
            if rutas and suyas & rutas:
                p += 0.5 / RRF_K
            if p > 0:
                f["puntos"] = p
                f["rutas"] = sorted(suyas)
                salida.append(f)
        salida.sort(key=lambda f: -f["puntos"])
        return salida[:k]

    def buscar_resoluciones(self, consulta: str, k: int = 3, vector: Optional[List[float]] = None) -> List[Dict[str, Any]]:
        puntos: Dict[int, float] = {}
        coincide_texto: Set[int] = set()
        with self.conectar() as c:
            terms = terminos_consulta(consulta)
            q = self._consulta_fts(terms)
            if q:
                try:
                    for rango, f in enumerate(c.execute(
                            "SELECT rowid, bm25(resoluciones_fts, 3.0, 1.0) b FROM resoluciones_fts "
                            "WHERE resoluciones_fts MATCH ? ORDER BY b LIMIT 20", (q,))):
                        puntos[f["rowid"]] = puntos.get(f["rowid"], 0) + 1.0 / (RRF_K + rango + 1)
                        coincide_texto.add(f["rowid"])
                except sqlite3.OperationalError:
                    pass
            sims: Dict[int, float] = {}
            if vector is not None:
                vectores = self._cargar_vectores()
                orden = sorted(((_coseno(vector, v), int(cl[2:])) for cl, v in vectores.items() if cl.startswith("r:")),
                               reverse=True)[:20]
                for rango, (sim, i) in enumerate(orden):
                    sims[i] = sim
                    if sim >= 0.55:
                        puntos[i] = puntos.get(i, 0) + 1.5 / (RRF_K + rango + 1)
            elegidos = list(puntos)
            if not elegidos:
                return []
            marcas = ",".join("?" * len(elegidos))
            filas = [dict(f) for f in c.execute(
                f"SELECT id, pregunta, resumen, rutas, modelo, cuando, version FROM resoluciones WHERE id IN ({marcas})",
                elegidos)]
            # Parecida de verdad: por significado, o compartiendo bastantes palabras con la pregunta
            def parecida(f) -> bool:
                if sims.get(f["id"], 0) >= 0.55:
                    return True
                comunes = set(terminos_consulta(f["pregunta"] + " " + f["resumen"])) & set(terms)
                return f["id"] in coincide_texto and len(comunes) >= max(2, len(set(terms)) // 3)
            filas = [f for f in filas if parecida(f)]
            for f in filas:
                f["rutas"] = json.loads(f["rutas"] or "[]")
                f["puntos"] = puntos.get(f["id"], 0)
                if f["rutas"]:
                    marcas2 = ",".join("?" * len(f["rutas"]))
                    f["cambiaron_despues"] = [x["ruta"] for x in c.execute(
                        f"SELECT DISTINCT ruta FROM cambios WHERE version > ? AND ruta IN ({marcas2})",
                        [f["version"]] + f["rutas"])]
                else:
                    f["cambiaron_despues"] = []
        filas.sort(key=lambda f: -f["puntos"])
        return filas[:k]

    def cambios_desde(self, version: int, limite: int = 40) -> List[Dict[str, Any]]:
        with self.conectar() as c:
            filas = [dict(f) for f in c.execute(
                "SELECT * FROM cambios WHERE version > ? ORDER BY id DESC LIMIT ?", (version, limite))]
        # El último estado de cada archivo, con los símbolos acumulados
        por_ruta: Dict[str, Dict[str, Any]] = {}
        for f in filas:
            f["simbolos"] = json.loads(f["simbolos"] or "{}")
            if f["ruta"] not in por_ruta:
                por_ruta[f["ruta"]] = f
            else:
                previo = por_ruta[f["ruta"]]
                previo["mas"] += f["mas"]
                previo["menos"] += f["menos"]
                for clave in ("nuevos", "borrados", "modificados"):
                    previo["simbolos"][clave] = sorted(set(previo["simbolos"].get(clave, [])) | set(f["simbolos"].get(clave, [])))
                if f["tipo"] == "nuevo":
                    previo["tipo"] = "nuevo"
        return list(por_ruta.values())

    # ------------------------------------------------------------------ mapa
    def mapa(self, presupuesto: int = 3000) -> str:
        """ Estructura del proyecto. Estable: no cambia con cada edición (sin números de línea ni
        tamaños), para que el motor la guarde como prefijo. Si no cabe, se resume por carpetas. """
        with self.conectar() as c:
            archivos = [dict(f) for f in c.execute(
                "SELECT ruta, lenguaje, resumen, resumen_ia FROM archivos ORDER BY ruta")]
            simbolos: Dict[str, List[str]] = {}
            for s in c.execute("SELECT ruta, nombre, tipo FROM simbolos WHERE padre = '' AND tipo IN "
                               "('clase','funcion','tipo') ORDER BY ruta, ini"):
                simbolos.setdefault(s["ruta"], []).append(s["nombre"])
            importancia: Dict[str, int] = {}
            for f in c.execute("SELECT destino, COUNT(*) n FROM importaciones GROUP BY destino"):
                importancia[f["destino"]] = importancia.get(f["destino"], 0) + 3 * f["n"]
            for f in c.execute("""SELECT s.ruta, COUNT(*) n FROM usos u JOIN simbolos s ON s.corto = u.nombre
                                  AND s.ruta != u.ruta GROUP BY s.ruta"""):
                importancia[f["ruta"]] = importancia.get(f["ruta"], 0) + f["n"]
        if not archivos:
            return ""
        nombre = os.path.basename(self.raiz)
        with self.conectar() as c:
            res_carpeta = {f["clave"]: f["texto"] for f in c.execute("SELECT clave, texto FROM resumenes WHERE nivel = 'carpeta'")}
            f = c.execute("SELECT texto FROM resumenes WHERE nivel = 'proyecto'").fetchone()
            res_proyecto = f["texto"] if f else ""
        cabecera = (f"MAPA DEL PROYECTO «{nombre}» ({len(archivos)} archivos). Estructura estable; el código "
                    f"relevante y los cambios recientes llegan con cada pregunta, y con las herramientas "
                    f"puedes consultar cualquier parte.\n" + (f"Resumen: {res_proyecto}\n" if res_proyecto else ""))
        # Detalle por archivo según importancia, hasta llenar el presupuesto
        orden = sorted(archivos, key=lambda a: (-importancia.get(a["ruta"], 0), a["ruta"]))
        detalle: Dict[str, int] = {}          # 0 solo nombre, 1 + resumen, 2 + símbolos
        for a in archivos:
            detalle[a["ruta"]] = 0

        def linea(a: Dict[str, Any], nivel: int) -> str:
            texto = "  " + os.path.basename(a["ruta"])
            if nivel >= 1:
                resumen = a.get("resumen_ia") or a.get("resumen")
                if resumen:
                    texto += " — " + resumen[:140]
            if nivel >= 2 and simbolos.get(a["ruta"]):
                lista = simbolos[a["ruta"]]
                texto += " · " + ", ".join(lista[:14]) + (f" (+{len(lista) - 14})" if len(lista) > 14 else "")
            return texto

        carpetas: Dict[str, List[str]] = {}
        for a in archivos:
            carpetas.setdefault(os.path.dirname(a["ruta"]) or ".", []).append(a["ruta"])
        subarbol: Dict[str, List[str]] = {}          # cada prefijo de carpeta con todo lo que cuelga
        for a in archivos:
            partes = (os.path.dirname(a["ruta"]) or ".").split("/")
            for k in range(1, len(partes) + 1):
                subarbol.setdefault("/".join(partes[:k]), []).append(a["ruta"])

        def plegada(carpeta: str, colapsar: Set[str]) -> Optional[str]:
            partes = carpeta.split("/")
            for k in range(1, len(partes) + 1):
                if "/".join(partes[:k]) in colapsar:
                    return "/".join(partes[:k])
            return None

        def render(colapsar: Set[str]) -> str:
            partes = [cabecera]
            hechas: Set[str] = set()
            for carpeta in sorted(carpetas):
                tope = plegada(carpeta, colapsar)
                if tope:
                    if tope in hechas:
                        continue
                    hechas.add(tope)
                    lista = subarbol[tope]
                    n_carpetas = len({os.path.dirname(r) for r in lista})
                    ejemplo = ", ".join(os.path.basename(r) for r in lista[:3])
                    donde = f" en {n_carpetas} carpetas" if n_carpetas > 1 else ""
                    resumen = f" — {res_carpeta[tope][:220]}" if tope in res_carpeta else ""
                    partes.append(f"{tope}/ ({len(lista)} archivos{donde}: {ejemplo}…){resumen}")
                    continue
                partes.append(f"{carpeta}/" + (f" — {res_carpeta[carpeta][:220]}" if carpeta in res_carpeta else ""))
                partes += [linea(a, detalle[a["ruta"]]) for a in archivos if (os.path.dirname(a["ruta"]) or ".") == carpeta]
            return "\n".join(partes)

        # Primero se pliegan los subárboles menos importantes (tests, datos, documentos) hasta que
        # los nombres ocupen menos de la mitad; el resto se reparte en resúmenes y símbolos de los
        # archivos más usados por los demás.
        def peso(d: str) -> float:
            lista = subarbol[d]
            base = sum(importancia.get(r, 0) for r in lista) / len(lista)
            if re.search(r"(^|/)(tests?|spec|__tests__|fixtures|data|datos|assets|static|docs?|ejemplos?|examples?)(/|$)", d):
                base *= 0.3
            return base

        colapsar: Set[str] = set()
        total = estimar_tokens(render(colapsar))
        for d in sorted((d for d in subarbol if d != "."), key=lambda d: (peso(d), -len(subarbol[d]), d)):
            if total <= presupuesto * 0.5:
                break
            if plegada(d, colapsar) or len(subarbol[d]) < 3:
                continue
            colapsar.add(d)
            total = estimar_tokens(render(colapsar))
        visibles = [a for a in orden if (os.path.dirname(a["ruta"]) or ".") not in colapsar]
        for nivel in (1, 2):
            for a in visibles:
                previo = detalle[a["ruta"]]
                if previo >= nivel:
                    continue
                coste = estimar_tokens(linea(a, nivel)) - estimar_tokens(linea(a, previo))
                if total + coste > presupuesto:
                    continue
                detalle[a["ruta"]] = nivel
                total += coste
        texto = render(colapsar)
        return texto

    # ------------------------------------------------------------------ contexto de una pregunta
    def componer(self, pregunta: str, presupuesto: int = 8000, version_vista: Optional[int] = None,
                 excluir_rutas: Optional[Set[str]] = None) -> Dict[str, Any]:
        """ Lo relevante para esta pregunta, dentro del presupuesto de tokens """
        t0 = time.time()
        vista = int(self._meta("version_vista", "0") or 0) if version_vista is None else version_vista
        vector = self._vector_consulta(pregunta)
        fragmentos = self.buscar(pregunta, k=40, vector=vector)
        rutas_top = {f["ruta"] for f in fragmentos[:8]}
        conocimiento = self.buscar_conocimiento(pregunta, vector=vector, rutas=rutas_top)
        resoluciones = self.buscar_resoluciones(pregunta, vector=vector)
        cambios = self.cambios_desde(vista) if vista < self.version else []
        excluir_rutas = excluir_rutas or set()

        secciones: List[str] = []
        usado = 0

        # 1. Cambios desde la última respuesta (hasta un 20 %)
        if cambios:
            tope = int(presupuesto * 0.2)
            lineas = ["## Cambios en el proyecto desde tu última respuesta"]
            for ch in cambios:
                s = ch["simbolos"]
                detalle = []
                for clave, etiqueta in (("modificados", "cambió"), ("nuevos", "nuevo"), ("borrados", "borró")):
                    if s.get(clave):
                        detalle.append(f"{etiqueta}: {', '.join(s[clave][:8])}")
                linea = f"- {ch['ruta']}: {ch['tipo']} (+{ch['mas']} −{ch['menos']})" + (f" · {'; '.join(detalle)}" if detalle else "")
                lineas.append(linea)
            texto = "\n".join(lineas)
            # Los diffs de lo más relevante para la pregunta, mientras quepan
            for ch in sorted(cambios, key=lambda ch: (ch["ruta"] not in rutas_top, ch["id"] * -1)):
                if ch["tipo"] != "modificado" or not ch.get("diff"):
                    continue
                bloque = f"\n```diff\n# {ch['ruta']}\n{ch['diff']}\n```"
                if estimar_tokens(texto + bloque) > tope:
                    continue
                texto += bloque
            if estimar_tokens(texto) > tope:
                texto = texto[:int(tope * CARACTERES_POR_TOKEN)] + "\n[…]"
            secciones.append(texto)
            usado += estimar_tokens(texto)

        # 2. Conocimiento (hasta un 15 %)
        if conocimiento:
            tope = int(presupuesto * 0.15)
            lineas = ["## Conocimiento guardado del proyecto (definiciones, teoría, decisiones)"]
            for k in conocimiento:
                aviso = " ⚠ puede estar desactualizado: sus archivos cambiaron" if k["revisar"] else ""
                donde = f" [{', '.join(k['rutas'][:4])}]" if k["rutas"] else ""
                linea = f"- ({k['tipo']}) **{k['titulo']}**: {k['texto'][:700]}{donde}{aviso}"
                if estimar_tokens("\n".join(lineas + [linea])) > tope:
                    break
                lineas.append(linea)
            if len(lineas) > 1:
                texto = "\n".join(lineas)
                secciones.append(texto)
                usado += estimar_tokens(texto)

        # 3. Resoluciones anteriores parecidas (hasta un 15 %)
        if resoluciones:
            tope = int(presupuesto * 0.15)
            lineas = ["## Preguntas parecidas ya resueltas en este proyecto (respuestas anteriores, no "
                      "verificadas: contrástalas con el código actual antes de repetirlas)"]
            for r in resoluciones:
                despues = (f" ⚠ después cambiaron: {', '.join(r['cambiaron_despues'][:5])}"
                           if r.get("cambiaron_despues") else "")
                linea = (f"- ({r['cuando'][:10]}) «{r['pregunta'][:200]}» → {r['resumen'][:500]}"
                         + (f" Archivos: {', '.join(r['rutas'][:6])}." if r["rutas"] else "") + despues)
                if estimar_tokens("\n".join(lineas + [linea])) > tope:
                    break
                lineas.append(linea)
            if len(lineas) > 1:
                texto = "\n".join(lineas)
                secciones.append(texto)
                usado += estimar_tokens(texto)

        # 4. Código relevante: el resto del presupuesto
        restante = presupuesto - usado
        elegidos: List[Dict[str, Any]] = []
        fichas: List[Dict[str, Any]] = []
        for f in fragmentos:
            if f["ruta"] in excluir_rutas:
                continue
            coste = f["tokens"] + 20
            if coste <= restante * 0.9 or (not elegidos and coste <= restante):
                elegidos.append(f)
                restante -= coste
            elif len(fichas) < 15:
                fichas.append(f)
        vecinos = [v for v in self.vecinos(elegidos) if v["ruta"] not in excluir_rutas]
        if elegidos:
            por_archivo: Dict[str, List[Dict[str, Any]]] = {}
            for f in elegidos:
                por_archivo.setdefault(f["ruta"], []).append(f)
            lenguajes = self._lenguajes(list(por_archivo))
            # El código primero y literal; la documentación aparte y después. Medido con el motor MoE:
            # con la prosa de docs/ delante, el modelo «reconstruía» funciones y constantes que no
            # existen en lugar de citar las que tenía delante.
            codigo = ["## Código relevante, literal del disco (archivo:líneas)"]
            documentos = ["## Documentación del proyecto relacionada"]
            for ruta, lista in sorted(por_archivo.items(), key=lambda x: -max(f["puntos"] for f in x[1])):
                lista.sort(key=lambda f: f["ini"])
                es_doc = lenguajes.get(ruta) == "md"
                for f in lista:
                    nombre = f" — {f['simbolo']}" if f["simbolo"] else ""
                    if es_doc:
                        documentos.append(f"### {ruta}{nombre}\n{f['texto'].strip()}")
                    else:
                        lang = BLOQUE_LENGUAJE.get(lenguajes.get(ruta, ""), "")
                        codigo.append(f"### {ruta}:{f['ini']}-{f['fin']}{nombre}\n```{lang}\n{f['texto']}\n```")
            if len(codigo) > 1:
                secciones.append("\n".join(codigo))
            if len(documentos) > 1:
                secciones.append("\n".join(documentos))
        otros = []
        for f in fichas:
            otros.append(f"- {f['ruta']}:{f['ini']}-{f['fin']} {f['simbolo'] or '(bloque)'}")
        for v in vecinos:
            doc = f" — {_primera_linea(v['doc'], 120)}" if v.get("doc") else ""
            otros.append(f"- {v['ruta']}:{v['ini']} {v['firma']}{doc} ({v['relacion']})")
        if otros and restante > 200:
            texto = "## También relacionado (pídelo con ver_simbolo o leer_archivo si lo necesitas)\n"
            for o in otros:
                if estimar_tokens(texto + o) > restante - 50:
                    break
                texto += o + "\n"
            secciones.append(texto.rstrip())

        cuerpo = ""
        if secciones:
            cuerpo = (f"BANCO DEL PROYECTO «{os.path.basename(self.raiz)}» — lo relevante para esta pregunta "
                      f"(estado actual del disco):\n\n" + "\n\n".join(secciones))
        return {"texto": cuerpo, "tokens": estimar_tokens(cuerpo), "fragmentos": len(elegidos),
                "archivos": sorted({f["ruta"] for f in elegidos}), "cambios": len(cambios),
                "conocimiento": len(conocimiento), "resoluciones": len(resoluciones),
                "vectores": vector is not None, "version": self.version,
                "segundos": round(time.time() - t0, 3)}

    def _lenguajes(self, rutas: List[str]) -> Dict[str, str]:
        if not rutas:
            return {}
        with self.conectar() as c:
            marcas = ",".join("?" * len(rutas))
            return {f["ruta"]: f["lenguaje"] for f in c.execute(
                f"SELECT ruta, lenguaje FROM archivos WHERE ruta IN ({marcas})", rutas)}

    # ------------------------------------------------------------------ conocimiento
    def anotar(self, tipo: str, titulo: str, texto: str, rutas: Optional[List[str]] = None,
               origen: str = "usuario") -> Dict[str, Any]:
        tipo = tipo if tipo in TIPOS_CONOCIMIENTO else "nota"
        titulo = (titulo or "").strip()[:200]
        texto = (texto or "").strip()[:4000]
        if not titulo or not texto:
            raise ValueError("Hacen falta un título y un texto.")
        with self.conectar() as c:
            validas = {f["ruta"] for f in c.execute("SELECT ruta FROM archivos")}
            rutas_ok = sorted({r.strip("./") for r in (rutas or []) if r and r.strip("./") in validas})
            ahora = datetime.now().isoformat(timespec="seconds")
            previa = c.execute("SELECT id FROM conocimiento WHERE lower(titulo) = lower(?) AND tipo = ?",
                               (titulo, tipo)).fetchone()
            if previa:
                i = previa["id"]
                c.execute("UPDATE conocimiento SET texto = ?, rutas = ?, origen = ?, actualizado = ?, revisar = 0, "
                          "version = ? WHERE id = ?", (texto, json.dumps(rutas_ok), origen, ahora, self.version, i))
                c.execute("DELETE FROM conocimiento_fts WHERE rowid = ?", (i,))
                c.execute("DELETE FROM vectores WHERE clave = ?", (f"c:{i}",))
            else:
                i = c.execute("INSERT INTO conocimiento (tipo, titulo, texto, rutas, origen, creado, actualizado, version) "
                              "VALUES (?,?,?,?,?,?,?,?)",
                              (tipo, titulo, texto, json.dumps(rutas_ok), origen, ahora, ahora, self.version)).lastrowid
            c.execute("INSERT INTO conocimiento_fts (rowid, titulo, terminos) VALUES (?,?,?)",
                      (i, " ".join(terminos(titulo)), " ".join(terminos(texto))))
        self._vectores = None
        return {"id": i, "tipo": tipo, "titulo": titulo, "rutas": rutas_ok, "actualizado": bool(previa)}

    def olvidar_conocimiento(self, i: int) -> bool:
        with self.conectar() as c:
            n = c.execute("DELETE FROM conocimiento WHERE id = ?", (i,)).rowcount
            c.execute("DELETE FROM conocimiento_fts WHERE rowid = ?", (i,))
            c.execute("DELETE FROM vectores WHERE clave = ?", (f"c:{i}",))
        self._vectores = None
        return bool(n)

    def listar_conocimiento(self, limite: int = 500) -> List[Dict[str, Any]]:
        with self.conectar() as c:
            filas = [dict(f) for f in c.execute("SELECT * FROM conocimiento ORDER BY actualizado DESC LIMIT ?", (limite,))]
        for f in filas:
            f["rutas"] = json.loads(f["rutas"] or "[]")
        return filas

    # ------------------------------------------------------------------ grafo y memoria de trabajo
    def afirmar(self, s: str, r: str, o: str, ruta: Optional[str] = None, origen: str = "modelo"):
        s, r, o = (str(x or "").strip()[:300] for x in (s, r, o))
        if not (s and r and o):
            raise ValueError("Un hecho necesita sujeto, relación y objeto.")
        with self.conectar() as c:
            if not c.execute("SELECT 1 FROM hechos WHERE s = ? AND r = ? AND o = ?", (s, r, o)).fetchone():
                c.execute("INSERT INTO hechos (s, r, o, ruta, linea, origen, version) VALUES (?,?,?,?,0,?,?)",
                          (s, r, o, ruta or "", origen, self.version))

    def guardar_trabajo(self, nombre: str, valor: Any):
        nombre = str(nombre or "").strip()[:120]
        if not nombre:
            raise ValueError("Hace falta un nombre.")
        texto = json.dumps(valor, ensure_ascii=False, default=str)
        if len(texto) > 2_000_000:
            raise ValueError("Demasiado grande para guardar (más de 2 MB).")
        with self.conectar() as c:
            c.execute("INSERT OR REPLACE INTO trabajo VALUES (?,?,?)",
                      (nombre, texto, datetime.now().isoformat(timespec="seconds")))

    def guardar_resumen(self, nivel: str, clave: str, texto: str, sha_fuente: str, modelo: str = ""):
        with self.conectar() as c:
            c.execute("INSERT OR REPLACE INTO resumenes VALUES (?,?,?,?,?,?)",
                      (nivel, clave, texto, sha_fuente, modelo, datetime.now().isoformat(timespec="seconds")))

    # ------------------------------------------------------------------ resoluciones
    def registrar_resolucion(self, pregunta: str, respuesta: str, modelo: str = "",
                             rutas: Optional[Iterable[str]] = None) -> Optional[int]:
        pregunta = (pregunta or "").strip()
        respuesta = (respuesta or "").strip()
        if not pregunta or not respuesta:
            return None
        with self.conectar() as c:
            validas = {f["ruta"] for f in c.execute("SELECT ruta FROM archivos")}
            mencionadas = set(rutas or []) & validas
            por_nombre: Dict[str, List[str]] = {}
            for r in validas:
                por_nombre.setdefault(os.path.basename(r), []).append(r)
            for cand in re.findall(r"[\w./-]+\.[A-Za-z]{1,6}\b", respuesta):
                cand = cand.strip("./")
                if cand in validas:
                    mencionadas.add(cand)
                elif len(por_nombre.get(os.path.basename(cand), [])) == 1:
                    mencionadas.add(por_nombre[os.path.basename(cand)][0])
            resumen = resumir_respuesta(respuesta)
            i = c.execute("INSERT INTO resoluciones (pregunta, resumen, respuesta, rutas, modelo, cuando, version) "
                          "VALUES (?,?,?,?,?,?,?)",
                          (pregunta[:4000], resumen, zlib.compress(respuesta.encode("utf-8", "replace")),
                           json.dumps(sorted(mencionadas)), modelo, datetime.now().isoformat(timespec="seconds"),
                           self.version)).lastrowid
            c.execute("INSERT INTO resoluciones_fts (rowid, pregunta, terminos) VALUES (?,?,?)",
                      (i, " ".join(terminos(pregunta)), " ".join(terminos(resumen))))
            self._guardar_meta("version_vista", self.version, c)
        self._vectores = None
        return i

    def listar_resoluciones(self, limite: int = 100) -> List[Dict[str, Any]]:
        with self.conectar() as c:
            filas = [dict(f) for f in c.execute(
                "SELECT id, pregunta, resumen, rutas, modelo, cuando, version FROM resoluciones "
                "ORDER BY id DESC LIMIT ?", (limite,))]
        for f in filas:
            f["rutas"] = json.loads(f["rutas"] or "[]")
        return filas

    def resolucion(self, i: int) -> Optional[Dict[str, Any]]:
        with self.conectar() as c:
            f = c.execute("SELECT * FROM resoluciones WHERE id = ?", (i,)).fetchone()
        if not f:
            return None
        d = dict(f)
        d["respuesta"] = zlib.decompress(d["respuesta"]).decode("utf-8", "replace")
        d["rutas"] = json.loads(d["rutas"] or "[]")
        return d

    def olvidar_resolucion(self, i: int) -> bool:
        with self.conectar() as c:
            n = c.execute("DELETE FROM resoluciones WHERE id = ?", (i,)).rowcount
            c.execute("DELETE FROM resoluciones_fts WHERE rowid = ?", (i,))
            c.execute("DELETE FROM vectores WHERE clave = ?", (f"r:{i}",))
        self._vectores = None
        return bool(n)

    # ------------------------------------------------------------------ análisis con IA
    def pendientes_de_analisis(self) -> List[str]:
        with self.conectar() as c:
            return [f["ruta"] for f in c.execute(
                "SELECT ruta FROM archivos WHERE (analizado_sha IS NULL OR analizado_sha != sha) "
                "AND lenguaje NOT IN ('datos', 'texto') ORDER BY ruta")]

    @staticmethod
    def _esperar(guardia: Optional[Callable[[], Optional[str]]], cancelar: Optional[threading.Event],
                 progreso: Optional[Callable[[Dict[str, Any]], None]]) -> bool:
        """ Espera mientras la guardia diga que no (chat en uso, calor, poca RAM). False si se canceló. """
        while guardia is not None:
            motivo = guardia()
            if not motivo:
                break
            if progreso:
                progreso({"esperando": motivo})
            if cancelar is not None:
                if cancelar.wait(10):
                    return False
            else:
                time.sleep(10)
        if progreso:
            progreso({"esperando": None})
        return not (cancelar is not None and cancelar.is_set())

    def analizar(self, generar: Callable[[str], str], cancelar: Optional[threading.Event] = None,
                 progreso: Optional[Callable[[Dict[str, Any]], None]] = None, limite: Optional[int] = None,
                 max_tokens_archivo: int = 6000,
                 guardia: Optional[Callable[[], Optional[str]]] = None) -> Dict[str, Any]:
        """ Un modelo lee cada archivo que cambió desde el último análisis y deja su resumen y las
        definiciones del dominio que usa. Solo rehace lo que cambió (por el hash del archivo). """
        pendientes = self.pendientes_de_analisis()
        if limite:
            pendientes = pendientes[:limite]
        hechos, errores = 0, 0
        t0 = time.time()
        for n, rel in enumerate(pendientes):
            if not self._esperar(guardia, cancelar, progreso):
                break
            with self.conectar() as c:
                f = c.execute("SELECT sha, contenido, lenguaje FROM archivos WHERE ruta = ?", (rel,)).fetchone()
            if not f:
                continue
            texto = zlib.decompress(f["contenido"]).decode("utf-8", "replace")
            if f["lenguaje"] == "cuaderno":
                texto = self._texto_de_cuaderno(texto)
            if estimar_tokens(texto) > max_tokens_archivo:
                texto = texto[:int(max_tokens_archivo * CARACTERES_POR_TOKEN)] + "\n[… archivo recortado]"
            if progreso:
                progreso({"archivo": rel, "hechos": hechos, "total": len(pendientes), "n": n})
            try:
                salida = generar(PROMPT_ANALISIS.format(ruta=rel, codigo=texto))
                datos = _json_de(salida)
            except Exception:
                datos = None
            if isinstance(datos, dict):
                datos = {"resumen": datos.get("summary") or datos.get("resumen"),
                         "definiciones": datos.get("definitions") or datos.get("definiciones") or [],
                         "decisiones": datos.get("decisions") or datos.get("decisiones") or []}
            if not isinstance(datos, dict) or not datos.get("resumen"):
                errores += 1
                continue
            with self.conectar() as c:
                c.execute("UPDATE archivos SET resumen_ia = ?, analizado_sha = ? WHERE ruta = ?",
                          (str(datos["resumen"])[:300], f["sha"], rel))
                viejas = [x["id"] for x in c.execute(
                    "SELECT id FROM conocimiento WHERE origen = 'analisis' AND rutas = ?", (json.dumps([rel]),))]
            for i in viejas:
                self.olvidar_conocimiento(i)
            modulo = os.path.basename(rel).rsplit(".", 1)[0].lower().replace("_", "")
            for d in (datos.get("definiciones") or [])[:8]:
                if not isinstance(d, dict):
                    continue
                termino = str(d.get("term") or d.get("termino") or "").strip()
                definicion = str(d.get("definition") or d.get("definicion") or "").strip()
                # Una «definición» que es el nombre del módulo no enseña nada
                if termino and definicion and termino.lower().replace("_", "").replace(" ", "") != modulo:
                    try:
                        self.anotar("definicion", termino, definicion, [rel], origen="analisis")
                    except ValueError:
                        pass
            for d in (datos.get("decisiones") or [])[:4]:
                if isinstance(d, dict):
                    titulo, texto = str(d.get("title") or d.get("titulo") or "").strip(), str(d.get("text") or d.get("texto") or "").strip()
                else:
                    titulo, texto = "", str(d or "").strip()
                if len(texto) > 15:
                    titulo = titulo or " ".join(texto.split()[:6])
                    try:
                        self.anotar("decision", f"{os.path.basename(rel)}: {titulo[:70]}", texto, [rel], origen="analisis")
                    except ValueError:
                        pass
            hechos += 1
        return {"hechos": hechos, "errores": errores, "pendientes": len(self.pendientes_de_analisis()),
                "segundos": round(time.time() - t0, 1)}

    def _contenido_de_carpetas(self) -> Dict[str, List[str]]:
        """ Para cada carpeta, las líneas «nombre — resumen» de sus archivos y subcarpetas directas """
        with self.conectar() as c:
            archivos = [dict(f) for f in c.execute(
                "SELECT ruta, COALESCE(resumen_ia, resumen) resumen FROM archivos ORDER BY ruta")]
            previos = {(f["nivel"], f["clave"]): f["texto"] for f in c.execute("SELECT nivel, clave, texto FROM resumenes")}
        carpetas: Dict[str, List[str]] = {}
        for a in archivos:
            d = os.path.dirname(a["ruta"]) or "."
            carpetas.setdefault(d, []).append(f"{os.path.basename(a['ruta'])} — {a['resumen'] or '(sin resumen)'}")
            partes = d.split("/") if d != "." else []
            for k in range(len(partes) - 1, -1, -1):             # asegura que existan las intermedias
                carpetas.setdefault("/".join(partes[:k]) or ".", [])
        for d in list(carpetas):
            hijas = [h for h in carpetas if h != d and (os.path.dirname(h) or ".") == d and h != "."]
            for h in sorted(hijas):
                carpetas[d].append(f"{os.path.basename(h)}/ — {previos.get(('carpeta', h), '(carpeta sin resumir)')}")
        return carpetas

    def sintetizar(self, generar: Callable[[str], str], cancelar: Optional[threading.Event] = None,
                   progreso: Optional[Callable[[Dict[str, Any]], None]] = None,
                   guardia: Optional[Callable[[], Optional[str]]] = None, modelo: str = "") -> Dict[str, Any]:
        """ Árbol de resúmenes (como RAPTOR): cada carpeta a partir de sus archivos y subcarpetas, de la
        más profunda a la raíz, y el proyecto a partir de todo. Solo se rehace una carpeta si cambió lo
        que contiene (se compara el hash de su entrada). """
        hechas, errores = 0, 0
        t0 = time.time()
        for _ in range(64):                  # cada pasada puede cambiar a las carpetas de arriba
            cambio = False
            carpetas = self._contenido_de_carpetas()
            with self.conectar() as c:
                previos = {f["clave"]: f["sha_fuente"] for f in c.execute("SELECT clave, sha_fuente FROM resumenes WHERE nivel = 'carpeta'")}
            orden = sorted((d for d in carpetas if d != "."), key=lambda d: (-d.count("/"), d))
            for d in orden:
                entrada = "\n".join(carpetas[d][:150])
                sha = _sha(entrada)
                if previos.get(d) == sha or not carpetas[d]:
                    continue
                if not self._esperar(guardia, cancelar, progreso):
                    return {"carpetas": hechas, "errores": errores, "segundos": round(time.time() - t0, 1)}
                if progreso:
                    progreso({"archivo": d + "/", "fase": "carpetas"})
                try:
                    datos = _json_de(generar(PROMPT_CARPETA.format(carpeta=d, contenido=entrada)))
                    texto = str(datos.get("summary") or datos["resumen"]).strip()
                    relaciones = datos.get("relations") or datos.get("relaciones")
                    if relaciones:
                        texto += " " + str(relaciones).strip()
                except Exception:
                    errores += 1
                    continue
                self.guardar_resumen("carpeta", d, texto[:600], sha, modelo)
                hechas += 1
                cambio = True
            if not cambio:
                break
        # El proyecto: las carpetas de primer nivel, los archivos de la raíz y el README
        carpetas = self._contenido_de_carpetas()
        entrada = "\n".join(carpetas.get(".", [])[:200])
        readme = ""
        with self.conectar() as c:
            f = c.execute("SELECT contenido FROM archivos WHERE lower(ruta) IN ('readme.md','readme','readme.rst') LIMIT 1").fetchone()
            if f:
                readme = zlib.decompress(f["contenido"]).decode("utf-8", "replace")[:6000]
            previo = c.execute("SELECT sha_fuente FROM resumenes WHERE nivel = 'proyecto'").fetchone()
        sha = _sha(entrada + readme)
        if entrada and (not previo or previo["sha_fuente"] != sha) and self._esperar(guardia, cancelar, progreso):
            if progreso:
                progreso({"archivo": "(proyecto)", "fase": "proyecto"})
            try:
                datos = _json_de(generar(PROMPT_PROYECTO.format(contenido=entrada, readme=readme)))
                self.guardar_resumen("proyecto", ".", str(datos.get("summary") or datos["resumen"]).strip()[:1500], sha, modelo)
                hechas += 1
            except Exception:
                errores += 1
        return {"carpetas": hechas, "errores": errores, "segundos": round(time.time() - t0, 1)}

    def trabajo_pendiente(self) -> Dict[str, int]:
        """ Lo que le queda al analista: archivos sin analizar y carpetas cuyo contenido cambió """
        carpetas = self._contenido_de_carpetas()
        with self.conectar() as c:
            previos = {f["clave"]: f["sha_fuente"] for f in c.execute("SELECT clave, sha_fuente FROM resumenes WHERE nivel = 'carpeta'")}
        sucias = sum(1 for d, lineas in carpetas.items()
                     if d != "." and lineas and previos.get(d) != _sha("\n".join(lineas[:150])))
        return {"archivos": len(self.pendientes_de_analisis()), "carpetas": sucias}

    # ------------------------------------------------------------------ consultas para herramientas
    def ver_simbolo(self, nombre: str, maximo: int = 4) -> str:
        nombre = (nombre or "").strip().strip("`").rstrip("()")
        with self.conectar() as c:
            filas = c.execute("""SELECT ruta, nombre, tipo, firma, ini, fin FROM simbolos
                                 WHERE nombre = ? OR corto = ? OR nombre LIKE ? ORDER BY (nombre = ?) DESC, ruta
                                 LIMIT ?""", (nombre, nombre.split(".")[-1], f"%.{nombre}", nombre, maximo)).fetchall()
            if not filas:
                return f"No hay ningún símbolo llamado «{nombre}». Prueba buscar_proyecto."
            partes = []
            for s in filas:
                f = c.execute("SELECT contenido, lenguaje FROM archivos WHERE ruta = ?", (s["ruta"],)).fetchone()
                lineas = zlib.decompress(f["contenido"]).decode("utf-8", "replace").splitlines()
                fin = min(s["fin"], s["ini"] + 400)
                cuerpo = "\n".join(f"{n:>5}  {lineas[n - 1]}" for n in range(s["ini"], fin + 1) if n <= len(lineas))
                n_usos = c.execute("SELECT COUNT(*) n FROM llamadas WHERE a_ruta = ? AND a_nombre = ?",
                                   (s["ruta"], s["nombre"])).fetchone()["n"]
                partes.append(f"{s['ruta']}:{s['ini']}-{s['fin']} ({s['tipo']}, {n_usos} llamadas en el proyecto)\n{cuerpo}"
                              + ("\n[… recortado]" if fin < s["fin"] else ""))
        return "\n\n".join(partes)

    def quien_usa(self, nombre: str, maximo: int = 60) -> str:
        nombre = (nombre or "").strip().strip("`").rstrip("()")
        with self.conectar() as c:
            filas = c.execute("""SELECT l.ruta, l.desde, l.linea, l.a_nombre FROM llamadas l
                                 WHERE l.a_nombre = ? OR l.a_nombre LIKE ? ORDER BY l.ruta, l.linea LIMIT ?""",
                              (nombre, f"%.{nombre.split('.')[-1]}", maximo)).fetchall()
        if not filas:
            return f"Nadie llama a «{nombre}» en el proyecto (o se usa de forma dinámica)."
        return "\n".join([f"Llamadas a {nombre}:"] + [f"- {f['ruta']}:{f['linea']} dentro de {f['desde']} → {f['a_nombre']}" for f in filas])

    def resumen_archivo(self, ruta: str) -> str:
        ruta = (ruta or "").strip().strip("./")
        with self.conectar() as c:
            a = c.execute("SELECT * FROM archivos WHERE ruta = ?", (ruta,)).fetchone()
            if not a:
                cands = [f["ruta"] for f in c.execute("SELECT ruta FROM archivos WHERE ruta LIKE ? LIMIT 5", (f"%{ruta}",))]
                if len(cands) == 1:
                    return self.resumen_archivo(cands[0])
                return f"No está en el banco: {ruta}" + (f". ¿Quisiste decir {', '.join(cands)}?" if cands else "")
            sims = c.execute("SELECT nombre, tipo, firma, doc, ini, fin FROM simbolos WHERE ruta = ? ORDER BY ini", (ruta,)).fetchall()
            importa = [f["destino"] for f in c.execute("SELECT destino FROM importaciones WHERE ruta = ?", (ruta,))]
            importado = [f["ruta"] for f in c.execute("SELECT ruta FROM importaciones WHERE destino = ?", (ruta,))]
            ultimos = c.execute("SELECT cuando, tipo, mas, menos FROM cambios WHERE ruta = ? ORDER BY id DESC LIMIT 3", (ruta,)).fetchall()
        salida = [f"{ruta} ({a['lenguaje']}, {a['lineas']} líneas, ~{a['tokens']} tokens)"]
        if a["resumen_ia"] or a["resumen"]:
            salida.append("Resumen: " + (a["resumen_ia"] or a["resumen"]))
        if sims:
            salida.append("Símbolos:")
            for s in sims[:120]:
                doc = f" — {_primera_linea(s['doc'], 100)}" if s["doc"] else ""
                salida.append(f"  l.{s['ini']}-{s['fin']} {s['firma']}{doc}")
        if importa:
            salida.append("Importa: " + ", ".join(importa))
        if importado:
            salida.append("Lo importan: " + ", ".join(importado))
        if ultimos:
            salida.append("Últimos cambios: " + "; ".join(f"{u['cuando']} {u['tipo']} +{u['mas']} −{u['menos']}" for u in ultimos))
        return "\n".join(salida)

    def texto_cambios(self, limite: int = 15) -> str:
        cambios = self.cambios_desde(max(0, self.version - 50), limite=limite * 3)[:limite]
        if not cambios:
            return "No hay cambios registrados desde que se indexó el proyecto."
        salida = []
        for ch in cambios:
            s = ch["simbolos"]
            toc = [f"{k}: {', '.join(v[:6])}" for k, v in s.items() if v]
            salida.append(f"- {ch['cuando']} {ch['ruta']}: {ch['tipo']} (+{ch['mas']} −{ch['menos']})"
                          + (f" · {'; '.join(toc)}" if toc else ""))
            if ch.get("diff"):
                salida.append("```diff\n" + ch["diff"][:1200] + "\n```")
        return "\n".join(salida)

    def recordar(self, consulta: str) -> str:
        vector = self._vector_consulta(consulta)
        conocimiento = self.buscar_conocimiento(consulta, k=8, vector=vector)
        resoluciones = self.buscar_resoluciones(consulta, k=5, vector=vector)
        if not conocimiento and not resoluciones:
            return "No hay nada guardado sobre eso."
        salida = []
        for k in conocimiento:
            salida.append(f"- ({k['tipo']}) {k['titulo']}: {k['texto']}" + (" [puede estar desactualizado]" if k["revisar"] else ""))
        for r in resoluciones:
            salida.append(f"- (resolución {r['cuando'][:10]}) «{r['pregunta'][:200]}» → {r['resumen']}"
                          + (f" [después cambiaron: {', '.join(r['cambiaron_despues'])}]" if r.get("cambiaron_despues") else ""))
        return "\n".join(salida)

    def texto_busqueda(self, consulta: str, k: int = 12) -> str:
        filas = self.buscar(consulta, k=k)
        if not filas:
            return "Sin resultados en el banco del proyecto."
        salida = []
        for f in filas:
            primeras = "\n".join(f["texto"].splitlines()[:6])
            salida.append(f"### {f['ruta']}:{f['ini']}-{f['fin']} {f['simbolo'] or ''}\n{primeras}")
        return "\n\n".join(salida)

    # ------------------------------------------------------------------ estado
    def estado(self) -> Dict[str, Any]:
        with self.conectar() as c:
            cuenta = lambda sql: c.execute(sql).fetchone()[0]
            datos = {
                "raiz": self.raiz, "carpeta": self.carpeta, "version": self.version,
                "archivos": cuenta("SELECT COUNT(*) FROM archivos"),
                "lineas": cuenta("SELECT COALESCE(SUM(lineas), 0) FROM archivos"),
                "tokens": cuenta("SELECT COALESCE(SUM(tokens), 0) FROM archivos"),
                "simbolos": cuenta("SELECT COUNT(*) FROM simbolos"),
                "fragmentos": cuenta("SELECT COUNT(*) FROM fragmentos"),
                "vectores": cuenta("SELECT COUNT(*) FROM vectores"),
                "conocimiento": cuenta("SELECT COUNT(*) FROM conocimiento"),
                "conocimiento_revisar": cuenta("SELECT COUNT(*) FROM conocimiento WHERE revisar > 0"),
                "resoluciones": cuenta("SELECT COUNT(*) FROM resoluciones"),
                "cambios": cuenta("SELECT COUNT(*) FROM cambios"),
                "analizados": cuenta("SELECT COUNT(*) FROM archivos WHERE analizado_sha = sha"),
                "actualizado": (c.execute("SELECT valor FROM meta WHERE clave = 'actualizado'").fetchone() or [None])[0],
                "version_vista": int((c.execute("SELECT valor FROM meta WHERE clave = 'version_vista'").fetchone() or ["0"])[0]),
            }
        datos["vectores_pendientes"] = self.vectores_pendientes()
        datos["pendientes_analisis"] = len(self.pendientes_de_analisis())
        with self.conectar() as c:
            datos["hechos"] = c.execute("SELECT COUNT(*) FROM hechos").fetchone()[0]
            datos["resumenes_carpeta"] = c.execute("SELECT COUNT(*) FROM resumenes WHERE nivel = 'carpeta'").fetchone()[0]
            datos["resumen_proyecto"] = bool(c.execute("SELECT 1 FROM resumenes WHERE nivel = 'proyecto'").fetchone())
            datos["trabajo_guardado"] = c.execute("SELECT COUNT(*) FROM trabajo").fetchone()[0]
        datos["carpetas_pendientes"] = self.trabajo_pendiente()["carpetas"]
        try:
            datos["mb"] = round(sum(os.path.getsize(os.path.join(self.carpeta, n)) for n in os.listdir(self.carpeta)) / 1e6, 1)
        except OSError:
            datos["mb"] = 0
        return datos


# Prompts del analista, en inglés y con salida terse: es el idioma en que el modelo razona mejor
# y el que menos tokens gasta (medido: el borrador MTP acierta 0,87-0,93 en código y notas técnicas,
# 0,69-0,72 en prosa castellana). Lo que se le muestra al usuario sigue en castellano.
PROMPT_ANALISIS = """Analyze this file from a software project. Reply ONLY with valid JSON:
{{"summary": "what the file does, one sentence, max 25 words",
  "definitions": [{{"term": "domain or project concept", "definition": "what it is and how it is used here, 1-2 terse sentences"}}],
  "decisions": [{{"title": "3-8 words", "text": "a design decision or constraint visible in the code, and why"}}]}}
Up to 6 definitions (only terms specific to this project or its domain; not Python/stdlib/library names,
not the file or module name itself) and up to 3 decisions. Terse technical English; exact identifiers.

File: {ruta}
```
{codigo}
```"""

PROMPT_CARPETA = """Summarize this folder of a software project from its contents. Reply ONLY with valid JSON:
{{"summary": "purpose and responsibilities of the folder, 2-4 terse sentences with real file/module names",
  "relations": "what other parts of the project it connects to and how, 1 sentence"}}

Folder: {carpeta}/
{contenido}"""

PROMPT_PROYECTO = """Summarize this software project from its top-level folders, root files and README. Reply ONLY with valid JSON:
{{"summary": "what the project is, its main parts and how they connect (backend, frontend, engines...), 5-8 terse sentences with real names"}}

Root contents:
{contenido}

README (start):
{readme}"""


def _json_de(texto: str) -> Any:
    texto = (texto or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", texto, re.S)
    if m:
        texto = m.group(1)
    else:
        ini, fin = texto.find("{"), texto.rfind("}")
        if ini >= 0 and fin > ini:
            texto = texto[ini:fin + 1]
    return json.loads(texto)


def resumir_respuesta(respuesta: str, maximo: int = 600) -> str:
    """ Resumen extractivo de una respuesta: la prosa inicial sin bloques de código, más qué código
    dejó (archivos de destino y lo que define) """
    sin_codigo = re.sub(r"```.*?(```|$)", " ", respuesta, flags=re.S)
    sin_codigo = re.sub(r"<think>.*?</think>", " ", sin_codigo, flags=re.S)
    prosa = " ".join(l.strip("#>*- ").strip() for l in sin_codigo.splitlines() if l.strip())
    prosa = re.sub(r"\s+", " ", prosa).strip()
    destinos = re.findall(r"###\s*Archivo:\s*(\S+)", respuesta)
    bloques = re.findall(r"```[\w+-]*\n(.*?)```", respuesta, flags=re.S)
    definidos: List[str] = []
    for b in bloques:
        definidos += re.findall(r"^\s*(?:async\s+)?(?:def|class|function|fn|func)\s+([A-Za-z_]\w*)", b, re.M)
    extra = []
    if destinos:
        extra.append("Archivos: " + ", ".join(dict.fromkeys(destinos)))
    if definidos:
        extra.append("Código: " + ", ".join(list(dict.fromkeys(definidos))[:10]))
    elif bloques:
        extra.append(f"{len(bloques)} bloque(s) de código")
    cola = (" " + ". ".join(extra) + ".") if extra else ""
    espacio = max(120, maximo - len(cola))
    if len(prosa) > espacio:
        corte = prosa[:espacio]
        punto = corte.rfind(". ")
        prosa = (corte[:punto + 1] if punto > espacio * 0.5 else corte.rstrip() + "…")
    return (prosa + cola).strip()


# ======================================================================
# Embebedor
# ======================================================================

class Embebedor:
    """ bge-m3 por Ollama, en la GPU cuando está libre y en la CPU si no.

    Medido con fragmentos de Prig: 0,04 s por fragmento en la GPU y 0,5-1,1 s en la CPU. Indexar
    un proyecto entero solo tiene sentido en la GPU; con un generador cargado (el motor MoE o un
    modelo de Ollama) se usa la CPU y solo para lo poco que cambia con cada edición. """

    def __init__(self, base_url: str = "http://localhost:11434", modelo: str = "bge-m3",
                 gpu_libre: Optional[Callable[[], bool]] = None, al_usar_gpu: Optional[Callable[[], None]] = None):
        self.base = base_url.rstrip("/")
        self.modelo = modelo
        self.gpu_libre = gpu_libre
        self.al_usar_gpu = al_usar_gpu
        self._disponible: Tuple[float, bool] = (0.0, False)

    def disponible(self) -> bool:
        cuando, valor = self._disponible
        if time.time() - cuando < 60:
            return valor
        import urllib.request
        try:
            with urllib.request.urlopen(f"{self.base}/api/tags", timeout=3) as r:
                nombres = {m["name"] for m in json.load(r).get("models", [])}
            valor = any(n == self.modelo or n.startswith(self.modelo + ":") for n in nombres)
        except Exception:
            valor = False
        self._disponible = (time.time(), valor)
        return valor

    def en_gpu(self) -> bool:
        try:
            return bool(self.gpu_libre and self.gpu_libre())
        except Exception:
            return False

    def consulta(self, texto: str) -> List[float]:
        return self([texto], timeout=60, gpu=False)[0]

    def __call__(self, textos: List[str], timeout: int = 600, gpu: Optional[bool] = None) -> List[List[float]]:
        import urllib.request
        gpu = self.en_gpu() if gpu is None else gpu
        cuerpo: Dict[str, Any] = {"model": self.modelo, "input": textos}
        if gpu:
            if self.al_usar_gpu:
                self.al_usar_gpu()
            # num_gpu explícito: sin él, Ollama reutiliza el embebedor que una consulta anterior dejó
            # cargado en la CPU, y la tanda «de GPU» tarda 25 veces más
            cuerpo["options"] = {"num_gpu": 999}
            cuerpo["keep_alive"] = "20s"          # suelta la VRAM enseguida si llega un generador
        else:
            cuerpo["options"] = {"num_gpu": 0}
            cuerpo["keep_alive"] = "10m"
        req = urllib.request.Request(f"{self.base}/api/embed", data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r).get("embeddings") or []


# ======================================================================
# Registro de bancos y vigilante
# ======================================================================

class Bancos:
    """ Un banco por carpeta de trabajo y un vigilante para la carpeta activa: cada pocos segundos
    sincroniza y embebe, por tandas pequeñas, lo que falte. """

    def __init__(self, embeber=None, embebedor_listo=None, intervalo: float = 4.0,
                 vectores_gpu: int = 128, vectores_cpu: int = 4):
        self.embeber = embeber
        self.embebedor_listo = embebedor_listo
        self.intervalo = intervalo
        self.vectores_gpu = vectores_gpu
        self.vectores_cpu = vectores_cpu
        self.max_pendientes_cpu = 24
        self._bancos: Dict[str, BancoProyecto] = {}
        self._lock = threading.Lock()
        self._vigilado: Optional[str] = None
        self._parar = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self.ultimo_error: Optional[str] = None
        self.analisis: Dict[str, Any] = {"activo": False}
        self._cancelar_analisis = threading.Event()
        # Devuelve el motivo para esperar (o None para seguir): la fija Prig (app.py)
        self.guardia: Optional[Callable[[], Optional[str]]] = None

    def para(self, raiz: str) -> BancoProyecto:
        raiz = os.path.abspath(raiz)
        with self._lock:
            if raiz not in self._bancos:
                self._bancos[raiz] = BancoProyecto(raiz, embeber=self.embeber, embebedor_listo=self.embebedor_listo)
            return self._bancos[raiz]

    def existe(self, raiz: str) -> bool:
        raiz = os.path.abspath(raiz)
        if raiz in self._bancos:
            return True
        clave = hashlib.sha1(raiz.encode()).hexdigest()[:10]
        nombre = re.sub(r"[^\w.-]+", "_", os.path.basename(raiz) or "raiz")
        return os.path.isfile(os.path.join(carpeta_bancos(), f"{nombre}-{clave}", "banco.db"))

    def vigilar(self, raiz: str):
        raiz = os.path.abspath(raiz)
        self.para(raiz)
        self._vigilado = raiz
        if self._hilo is None or not self._hilo.is_alive():
            self._parar.clear()
            self._hilo = threading.Thread(target=self._bucle, name="banco-vigilante", daemon=True)
            self._hilo.start()

    def detener(self):
        self._parar.set()

    @property
    def vigilado(self) -> Optional[str]:
        return self._vigilado if self._hilo is not None and self._hilo.is_alive() else None

    def _bucle(self):
        while not self._parar.wait(self.intervalo):
            raiz = self._vigilado
            if not raiz or not os.path.isdir(raiz):
                continue
            banco = self.para(raiz)
            try:
                banco.sincronizar()
                if banco.embeber:
                    en_gpu = bool(getattr(banco.embeber, "en_gpu", lambda: False)())
                    # En la CPU solo lo poco de cada edición: un proyecto entero (0,5-1 s por
                    # fragmento) espera a que la GPU quede libre
                    maximo = self.vectores_gpu if en_gpu else (
                        self.vectores_cpu if banco.vectores_pendientes() <= self.max_pendientes_cpu else 0)
                    if maximo:
                        banco.indexar_vectores(maximo=maximo, lote=64 if en_gpu else 4)
                self.ultimo_error = None
            except Exception as e:           # un fallo no puede matar al vigilante
                self.ultimo_error = f"{type(e).__name__}: {e}"

    def analizar_en_fondo(self, banco: BancoProyecto, generar: Callable[[str], str], modelo: str,
                          limite: Optional[int] = None, continuo: bool = False) -> Dict[str, Any]:
        """ El analista autónomo: archivos, luego carpetas y proyecto. Con `continuo`, sigue vivo y
        rehace lo que cambie. Antes de cada paso consulta la guardia (chat en uso, temperatura, RAM). """
        if self.analisis.get("activo"):
            return self.analisis
        self._cancelar_analisis.clear()
        self.analisis = {"activo": True, "modelo": modelo, "raiz": banco.raiz, "hechos": 0, "continuo": continuo,
                         "total": len(banco.pendientes_de_analisis()), "archivo": None, "fase": "archivos",
                         "esperando": None, "inicio": time.time()}

        def progreso(p):
            self.analisis.update(p)

        def trabajo():
            cancelar = self._cancelar_analisis
            try:
                while not cancelar.is_set():
                    self.analisis.update({"fase": "archivos", "total": len(banco.pendientes_de_analisis())})
                    r = banco.analizar(generar, cancelar, progreso, limite=limite, guardia=self.guardia)
                    self.analisis.update({"hechos": r["hechos"], "errores": r["errores"]})
                    if cancelar.is_set():
                        break
                    self.analisis["fase"] = "carpetas"
                    r2 = banco.sintetizar(generar, cancelar, progreso, guardia=self.guardia, modelo=modelo)
                    self.analisis.update({"carpetas": r2["carpetas"], "errores_carpetas": r2["errores"]})
                    if not continuo:
                        break
                    # Esperar a que haya algo nuevo (el vigilante marca lo que cambia)
                    self.analisis.update({"fase": "al día", "archivo": None})
                    while not cancelar.wait(30):
                        pendiente = banco.trabajo_pendiente()
                        if pendiente["archivos"] or pendiente["carpetas"]:
                            break
            except Exception as e:
                self.analisis["error"] = f"{type(e).__name__}: {e}"
            finally:
                self.analisis.update({"activo": False, "archivo": None, "esperando": None})

        threading.Thread(target=trabajo, name="banco-analista", daemon=True).start()
        return self.analisis

    def cancelar_analisis(self):
        self._cancelar_analisis.set()

    def borrar(self, raiz: str) -> bool:
        raiz = os.path.abspath(raiz)
        with self._lock:
            banco = self._bancos.pop(raiz, None)
        if self._vigilado == raiz:
            self._vigilado = None
        carpeta = banco.carpeta if banco else None
        if carpeta is None:
            clave = hashlib.sha1(raiz.encode()).hexdigest()[:10]
            nombre = re.sub(r"[^\w.-]+", "_", os.path.basename(raiz) or "raiz")
            carpeta = os.path.join(carpeta_bancos(), f"{nombre}-{clave}")
        if not os.path.isdir(carpeta):
            return False
        import shutil
        shutil.rmtree(carpeta, ignore_errors=True)
        return True
