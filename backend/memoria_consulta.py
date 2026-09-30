"""
Memoria de consulta: el banco del proyecto como un objeto programable que el modelo controla.

Un contexto finito no puede contener un proyecto grande, pero no hace falta: basta con que el
modelo pueda PREGUNTARLE cosas al proyecto con la precisión de un programa. La idea viene de los
Recursive Language Models (Zhang y Khattab, 2025): el texto largo no entra en el contexto del
modelo; vive como una variable en un entorno de Python, y el modelo escribe código para
inspeccionarlo, cortarlo, cruzarlo y, si hace falta, llamarse a sí mismo sobre un trozo. Aquí esa
variable es `P`, el banco entero del proyecto: archivos, líneas, símbolos, el grafo de hechos
(define, llama, hereda, importa, lanza, lee config/entorno, expone o consume un endpoint), cambios,
memoria y resoluciones.

Qué gana el modelo:
  · Cantidad ilimitada: recorre 2 millones de tokens con un bucle y solo trae al contexto lo que
    imprime (recortado). Los resultados intermedios quedan en variables, fuera del contexto.
  · Precisión: `P.sql(...)` y `P.hechos(...)` responden preguntas exactas («¿qué endpoints no llama
    nadie?», «¿qué funciones leen la clave moe_modo?») que una búsqueda aproximada no puede.
  · Recursión: `P.llm(pregunta, contexto)` pide a un modelo que lea un trozo y devuelva lo
    esencial. Un bucle de `P.llm` es un map-reduce sobre el proyecto entero.
  · Memoria entre sesiones: `P.guardar(nombre, valor)` y `P.recuperar(nombre)`.

Seguridad (el código lo escribe un modelo): corre en un proceso aparte, con la base de datos en
solo lectura, sin `open`, sin red y sin importar nada fuera de una lista corta; el código se
revisa antes de ejecutarlo (sin atributos que empiecen por «_», sin eval/exec), con tope de
memoria y de tiempo por ejecución. Todo lo que escribe (anotar, afirmar, guardar) y las llamadas
a otro modelo pasan por el proceso de Prig, que decide.
"""

import ast
import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

MAX_SALIDA = 6000
TIEMPO_POR_EJECUCION = 30
MEMORIA_MB = 2048
MAX_LLM_POR_EJECUCION = 12
MAX_LLM_POR_RESPUESTA = 24          # medido: sin tope por respuesta, una pregunta tardó 30 min en subllamadas
TIEMPO_TOTAL_POR_EJECUCION = 180    # s, incluido lo que tarden las subllamadas a P.llm
MODULOS_PERMITIDOS = {"re", "math", "json", "collections", "itertools", "functools", "statistics", "difflib",
                      "ast", "textwrap", "heapq", "bisect", "operator", "string", "fnmatch", "datetime"}
NOMBRES_PROHIBIDOS = {"eval", "exec", "compile", "open", "__import__", "globals", "locals", "vars", "getattr",
                      "setattr", "delattr", "breakpoint", "input", "memoryview", "exit", "quit", "help",
                      "classmethod", "staticmethod", "property", "super", "object"}
BUILTINS_PERMITIDOS = [
    "abs", "all", "any", "ascii", "bin", "bool", "bytes", "callable", "chr", "complex", "dict", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "hasattr", "hash", "hex", "int", "isinstance",
    "issubclass", "iter", "len", "list", "map", "max", "min", "next", "oct", "ord", "pow", "print", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "type", "zip",
    "Exception", "ValueError", "KeyError", "IndexError", "TypeError", "StopIteration", "True", "False", "None",
]

AYUDA = """P — el proyecto entero, consultable con Python (las variables persisten entre llamadas):
  P.archivos(patron=None, lenguaje=None)        → [{ruta, lenguaje, lineas, tokens, resumen}]
  P.leer(ruta, desde=1, hasta=None)             → texto con números de línea
  P.lineas(ruta)                                → [str] (sin numerar, para procesar)
  P.grep(regex, rutas=None, maximo=200)         → [{ruta, linea, texto}]
  P.buscar(consulta, k=10)                      → fragmentos por significado y palabras [{ruta, ini, fin, simbolo, texto}]
  P.simbolos(nombre=None, ruta=None, tipo=None) → [{ruta, nombre, tipo, firma, doc, ini, fin}]
  P.codigo(nombre)                              → código completo del símbolo (con líneas)
  P.hechos(s=None, r=None, o=None, limite=500)  → [{s, r, o, ruta, linea}] grafo del proyecto; relaciones:
        define, llama, importa, hereda, lanza, captura, lee_config, lee_entorno, expone ("GET /api/x/*"),
        llama_api ("/api/x/*", fetch del frontend), usa_dom, define_dom, atributo, ejecuta  (% es comodín)
        En las rutas HTTP los parámetros son * en ambos lados: compáralas con ==
  P.ficha(nombre)                               → TODO sobre un símbolo: ubicación, firma, doc, llamadores, llamadas, hechos, notas
  P.recorrido(inicio, profundidad=4)            → árbol de llamadas hacia abajo desde una función o un endpoint ("/api/x")
  P.impacto(nombre)                             → qué se rompe si cambia: llamadores transitivos, endpoints y frontend
  P.donde(x)                                    → dónde está y dónde se toca x (clave de config, endpoint, variable de entorno,
                                                  id del DOM, archivo de datos o símbolo): hechos, implementación, consumidores
                                                  y apariciones literales en el código
  P.llamadores(nombre) / P.llamados(simbolo)    → quién lo llama / a qué llama (aristas resueltas al símbolo exacto;
                                                  nombre completo «Clase.metodo» o «ruta:nombre» si hay varios)
  P.camino(desde, hasta)                        → cadena de llamadas más corta entre dos símbolos, o None
  P.api(ruta_http)                              → quién expone el endpoint y quién lo consume
  P.ast(ruta)                                   → árbol ast de un archivo Python
  P.cambios(desde_version=None) / P.diff(ruta)  → cambios registrados (con diff y funciones tocadas)
  P.memoria(consulta) / P.resoluciones(consulta)→ definiciones, decisiones y preguntas ya resueltas
  P.resumenes(nivel=None)                       → resúmenes jerárquicos (archivo, carpeta, proyecto)
  P.sql("SELECT …")                             → consulta de solo lectura; P.esquema() muestra las tablas
  P.llm(pregunta, contexto, max_tokens=500)     → otro modelo lee `contexto` y responde (recursión; máx. 12 por ejecución)
  P.anotar(tipo, titulo, texto, rutas=[])       → memoria: definicion | teoria | decision | contexto | nota
  P.afirmar(s, r, o, ruta=None)                 → añade un hecho al grafo
  P.guardar(nombre, valor) / P.recuperar(nombre)→ resultados que sobreviven a la sesión
Empieza por P.ficha / P.recorrido / P.impacto: responden en una línea lo que costaría escribir un bucle.
Código corto, sin comentarios ni prints decorativos. Imprime solo lo necesario (se recorta a 6.000
caracteres): guarda lo grande en variables."""


# ======================================================================
# Revisión del código
# ======================================================================

class CodigoNoPermitido(Exception):
    pass


def revisar(codigo: str) -> ast.Module:
    try:
        arbol = ast.parse(codigo, mode="exec")
    except SyntaxError as e:
        raise CodigoNoPermitido(f"Error de sintaxis: {e.msg} (línea {e.lineno})")
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Attribute) and nodo.attr.startswith("_"):
            raise CodigoNoPermitido(f"No se permiten atributos que empiezan por «_»: .{nodo.attr}")
        if isinstance(nodo, ast.Name) and (nodo.id in NOMBRES_PROHIBIDOS or nodo.id.startswith("__")):
            raise CodigoNoPermitido(f"No está permitido: {nodo.id}")
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            modulos = [a.name for a in nodo.names] if isinstance(nodo, ast.Import) else [nodo.module or ""]
            for m in modulos:
                if m.split(".")[0] not in MODULOS_PERMITIDOS:
                    raise CodigoNoPermitido(f"No se puede importar «{m}». Permitidos: {', '.join(sorted(MODULOS_PERMITIDOS))}")
        if isinstance(nodo, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await)):
            raise CodigoNoPermitido("No se permiten global, nonlocal ni async.")
    return arbol


# ======================================================================
# El proceso aislado (worker)
# ======================================================================

def _worker(ruta_db: str, raiz: str):
    """ Bucle del proceso aislado: lee peticiones JSON por stdin, ejecuta, responde por stdout """
    import builtins
    import contextlib
    import io
    import resource
    import signal
    import sqlite3

    conexion = sqlite3.connect(f"file:{ruta_db}?mode=ro", uri=True, timeout=30, check_same_thread=False)
    conexion.row_factory = sqlite3.Row
    entrada = sys.stdin
    salida_real = sys.stdout

    numero = [0]

    def pedir(tipo: str, datos: Dict[str, Any]) -> Any:
        """ Lo que el proceso aislado no puede hacer solo: escribir, llamar a un modelo. La alarma de
        30 s se pausa mientras tanto (mide el cómputo propio, no la espera a Prig) y cada petición
        lleva un número: una respuesta vieja se descarta en vez de tomarse por la de otra petición. """
        numero[0] += 1
        restante = signal.alarm(0)
        try:
            salida_real.write(json.dumps({"peticion": tipo, "id": numero[0], "datos": datos}, ensure_ascii=False, default=str) + "\n")
            salida_real.flush()
            while True:
                linea = entrada.readline()
                if not linea:
                    raise RuntimeError("Prig cerró la consola")
                respuesta = json.loads(linea)
                if respuesta.get("id") == numero[0]:
                    break
        finally:
            if restante:
                signal.alarm(restante)
        if respuesta.get("error"):
            raise RuntimeError(respuesta["error"])
        return respuesta.get("valor")

    P = API(conexion, raiz, pedir)

    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORIA_MB * 1024 * 1024, MEMORIA_MB * 1024 * 1024))
    except (ValueError, OSError):
        pass

    def importar(nombre, globales=None, locales=None, lista=(), nivel=0):
        if nombre.split(".")[0] not in MODULOS_PERMITIDOS or nivel:
            raise ImportError(f"No se puede importar «{nombre}»")
        return __import__(nombre, globales, locales, lista, nivel)

    seguros = {n: getattr(builtins, n) for n in BUILTINS_PERMITIDOS if hasattr(builtins, n)}
    seguros["__import__"] = importar
    espacio: Dict[str, Any] = {"__builtins__": seguros, "P": P, "ayuda": lambda: print(AYUDA)}

    alarma = int(os.environ.get("PRIG_CONSOLA_ALARMA") or TIEMPO_POR_EJECUCION)

    def tiempo_agotado(*_):
        raise TimeoutError(f"La ejecución pasó de {alarma} s: divide el trabajo o usa P.sql.")
    signal.signal(signal.SIGALRM, tiempo_agotado)

    for linea in entrada:
        try:
            pedido = json.loads(linea)
        except ValueError:
            continue
        if pedido.get("fin"):
            break
        codigo = pedido.get("codigo") or ""
        buffer = io.StringIO()
        error = None
        P.reiniciar_contadores()
        try:
            arbol = revisar(codigo)
            # Como un REPL: si lo último es una expresión, se muestra su valor
            ultimo = None
            if arbol.body and isinstance(arbol.body[-1], ast.Expr):
                ultimo = ast.Expression(arbol.body.pop().value)
            signal.alarm(alarma)
            with contextlib.redirect_stdout(buffer):
                exec(compile(arbol, "<consola>", "exec"), espacio)
                if ultimo is not None:
                    valor = eval(compile(ultimo, "<consola>", "eval"), espacio)
                    if valor is not None:
                        print(_mostrar(valor))
        except CodigoNoPermitido as e:
            error = str(e)
        except MemoryError:
            error = f"Sin memoria (tope {MEMORIA_MB} MB): procesa por partes."
        except BaseException as e:            # noqa: BLE001 — cualquier fallo vuelve al modelo como texto
            error = f"{type(e).__name__}: {e}"
        finally:
            signal.alarm(0)
        texto = buffer.getvalue()
        if len(texto) > MAX_SALIDA:
            texto = (texto[:MAX_SALIDA] + f"\n[… salida recortada: {len(texto)} caracteres. Guarda el resultado en "
                     f"una variable e imprime solo lo necesario]")
        variables = sorted(k for k, v in espacio.items()
                           if not k.startswith("__") and k not in ("P", "ayuda") and not callable(v))
        salida_real.write(json.dumps({"resultado": {"salida": texto, "error": error, "variables": variables[:60],
                                                    "llm": P.llamadas_llm}}, ensure_ascii=False) + "\n")
        salida_real.flush()


def _mostrar(valor: Any) -> str:
    if isinstance(valor, str):
        return valor
    if isinstance(valor, list) and valor and isinstance(valor[0], dict):
        return "\n".join(json.dumps(v, ensure_ascii=False, default=str) for v in valor)
    try:
        return json.dumps(valor, ensure_ascii=False, indent=1, default=str)
    except (TypeError, ValueError):
        return repr(valor)


# ======================================================================
# La API que ve el modelo
# ======================================================================

class API:
    """ Lo que el modelo puede hacer con el proyecto. Solo lectura sobre la base; lo demás, pidiéndolo. """

    def __init__(self, conexion, raiz: str, pedir: Callable[[str, Dict[str, Any]], Any]):
        self._c = conexion
        self._raiz = raiz
        self._pedir = pedir
        self._contenido: Dict[str, List[str]] = {}
        self.llamadas_llm = 0

    def reiniciar_contadores(self):
        self.llamadas_llm = 0

    # ------------------------------------------------------------------ internos
    def _filas(self, sql: str, args=()) -> List[Dict[str, Any]]:
        return [dict(f) for f in self._c.execute(sql, args)]

    def _ruta(self, ruta: str) -> str:
        ruta = (ruta or "").strip().lstrip("./")
        if self._c.execute("SELECT 1 FROM archivos WHERE ruta = ?", (ruta,)).fetchone():
            return ruta
        cands = [f["ruta"] for f in self._c.execute("SELECT ruta FROM archivos WHERE ruta LIKE ?", (f"%{ruta}",))]
        if len(cands) == 1:
            return cands[0]
        raise KeyError(f"No está en el banco: {ruta}" + (f" (¿{', '.join(cands[:6])}?)" if cands else ""))

    def lineas(self, ruta: str) -> List[str]:
        import zlib
        ruta = self._ruta(ruta)
        if ruta not in self._contenido:
            f = self._c.execute("SELECT contenido FROM archivos WHERE ruta = ?", (ruta,)).fetchone()
            self._contenido[ruta] = zlib.decompress(f["contenido"]).decode("utf-8", "replace").splitlines()
            if len(self._contenido) > 400:
                self._contenido.pop(next(iter(self._contenido)))
        return list(self._contenido[ruta])

    # ------------------------------------------------------------------ archivos y texto
    def archivos(self, patron: Optional[str] = None, lenguaje: Optional[str] = None) -> List[Dict[str, Any]]:
        import fnmatch
        filas = self._filas("SELECT ruta, lenguaje, lineas, tokens, COALESCE(resumen_ia, resumen) resumen "
                            "FROM archivos ORDER BY ruta")
        if patron:
            filas = [f for f in filas if fnmatch.fnmatch(f["ruta"], patron) or fnmatch.fnmatch(f["ruta"], f"*{patron}*")]
        if lenguaje:
            filas = [f for f in filas if f["lenguaje"] == lenguaje]
        return filas

    def leer(self, ruta: str, desde: int = 1, hasta: Optional[int] = None) -> str:
        lineas = self.lineas(ruta)
        desde = max(1, int(desde or 1))
        hasta = min(len(lineas), int(hasta or desde + 199))
        return "\n".join(f"{n:>5}  {lineas[n - 1]}" for n in range(desde, hasta + 1))

    def grep(self, regex: str, rutas: Optional[List[str]] = None, maximo: int = 200) -> List[Dict[str, Any]]:
        patron = re.compile(regex)
        salida = []
        for ruta in (rutas or [f["ruta"] for f in self._c.execute("SELECT ruta FROM archivos ORDER BY ruta")]):
            for n, linea in enumerate(self.lineas(ruta), 1):
                if patron.search(linea):
                    salida.append({"ruta": ruta, "linea": n, "texto": linea.strip()[:240]})
                    if len(salida) >= maximo:
                        return salida
        return salida

    def buscar(self, consulta: str, k: int = 10) -> List[Dict[str, Any]]:
        return self._pedir("buscar", {"consulta": consulta, "k": int(k)})

    # ------------------------------------------------------------------ símbolos y grafo
    def simbolos(self, nombre: Optional[str] = None, ruta: Optional[str] = None,
                 tipo: Optional[str] = None) -> List[Dict[str, Any]]:
        sql, args = "SELECT ruta, nombre, tipo, firma, doc, ini, fin FROM simbolos WHERE 1=1", []
        if nombre:
            sql += " AND (nombre LIKE ? OR corto LIKE ?)"
            args += [nombre, nombre]
        if ruta:
            sql += " AND ruta = ?"
            args.append(self._ruta(ruta))
        if tipo:
            sql += " AND tipo = ?"
            args.append(tipo)
        return self._filas(sql + " ORDER BY ruta, ini LIMIT 2000", args)

    def codigo(self, nombre: str) -> str:
        filas = self._filas("SELECT ruta, nombre, ini, fin FROM simbolos WHERE nombre = ? OR corto = ? "
                            "ORDER BY (nombre = ?) DESC LIMIT 5", (nombre, nombre.split(".")[-1], nombre))
        if not filas:
            raise KeyError(f"No hay ningún símbolo llamado «{nombre}»")
        partes = []
        for s in filas:
            partes.append(f"# {s['ruta']}:{s['ini']}-{s['fin']} {s['nombre']}\n" + self.leer(s["ruta"], s["ini"], s["fin"]))
        return "\n\n".join(partes)

    def hechos(self, s: Optional[str] = None, r: Optional[str] = None, o: Optional[str] = None,
               limite: int = 500) -> List[Dict[str, Any]]:
        sql, args = "SELECT s, r, o, ruta, linea FROM grafo WHERE 1=1", []
        for campo, valor in (("s", s), ("r", r), ("o", o)):
            if valor:
                sql += f" AND {campo} LIKE ?"
                args.append(valor)
        return self._filas(sql + " LIMIT ?", args + [int(limite)])

    # ------------------------------------------------------------------ grafo de llamadas resuelto
    # Cada arista va de un símbolo exacto (archivo + nombre completo) a otro: la resolución usa el
    # receptor de la llamada, los import y el tipo de retorno anotado (banco_proyecto._resolver_llamadas).
    def _nodos(self, nombre: str) -> List[tuple]:
        """ Símbolos que casan con un nombre: completo («Motor.asegurar»), corto («asegurar») o
        «ruta:nombre» para desambiguar """
        if ":" in nombre and not nombre.startswith("/"):
            ruta, n = nombre.split(":", 1)
            return [(f["ruta"], f["nombre"]) for f in self._c.execute(
                "SELECT ruta, nombre FROM simbolos WHERE ruta LIKE ? AND (nombre = ? OR corto = ?)", (f"%{ruta}", n, n))]
        filas = [(f["ruta"], f["nombre"]) for f in self._c.execute("SELECT ruta, nombre FROM simbolos WHERE nombre = ?", (nombre,))]
        return filas or [(f["ruta"], f["nombre"]) for f in self._c.execute(
            "SELECT ruta, nombre FROM simbolos WHERE corto = ?", (nombre.split(".")[-1],))]

    def _ubicacion(self, nodo: tuple) -> str:
        f = self._c.execute("SELECT ini FROM simbolos WHERE ruta = ? AND nombre = ?", nodo).fetchone()
        return f"{nodo[0]}:{f['ini']}" if f else nodo[0]

    def _salientes(self, nodo: tuple) -> List[tuple]:
        return [(f["a_ruta"], f["a_nombre"]) for f in self._c.execute(
            "SELECT DISTINCT a_ruta, a_nombre FROM llamadas WHERE ruta = ? AND desde = ? ORDER BY linea", nodo)]

    def _entrantes(self, nodo: tuple) -> List[Dict[str, Any]]:
        return [dict(f) for f in self._c.execute(
            "SELECT ruta, desde, linea, confianza FROM llamadas WHERE a_ruta = ? AND a_nombre = ? ORDER BY ruta, linea", nodo)]

    def llamadores(self, nombre: str) -> List[Dict[str, Any]]:
        return [{"s": f["desde"], "ruta": f["ruta"], "linea": f["linea"], "confianza": f["confianza"], "a": n[1]}
                for n in self._nodos(nombre) for f in self._entrantes(n)]

    def llamados(self, simbolo: str) -> List[Dict[str, Any]]:
        return [{"o": d[1], "ruta": d[0]} for n in self._nodos(simbolo) for d in self._salientes(n)]

    def camino(self, desde: str, hasta: str, maximo: int = 10) -> Optional[List[str]]:
        """ Cadena de llamadas más corta entre dos símbolos (búsqueda en anchura sobre aristas resueltas) """
        destinos = set(self._nodos(hasta))
        previo: Dict[tuple, Optional[tuple]] = {n: None for n in self._nodos(desde)}
        frontera = list(previo)
        for _ in range(maximo):
            nueva = []
            for nodo in frontera:
                for sig in self._salientes(nodo):
                    if sig in previo:
                        continue
                    previo[sig] = nodo
                    if sig in destinos:
                        cadena = [sig]
                        while previo[cadena[-1]] is not None:
                            cadena.append(previo[cadena[-1]])
                        return [f"{n[1]} ({self._ubicacion(n)})" for n in reversed(cadena)]
                    nueva.append(sig)
            frontera = nueva
        return None

    # ------------------------------------------------------------------ primitivas de alto nivel
    # Cada una evita que el modelo escriba 100-300 tokens de Python: escribir es 20-80 veces más caro
    # que leer (medido), así que las consultas frecuentes van hechas.
    def ficha(self, nombre: str) -> Dict[str, Any]:
        """ Todo lo que se sabe de un símbolo: dónde está, firma, doc, quién lo llama, a qué llama,
        sus hechos, el resumen de su archivo y las notas de memoria de ese archivo """
        nodos = self._nodos(nombre)
        if not nodos:
            raise KeyError(f"No hay ningún símbolo llamado «{nombre}»")
        nodo = nodos[0]
        s = dict(self._c.execute("SELECT ruta, nombre, tipo, firma, doc, ini, fin FROM simbolos WHERE ruta = ? AND nombre = ?", nodo).fetchone())
        archivo = self._c.execute("SELECT COALESCE(resumen_ia, resumen) r FROM archivos WHERE ruta = ?", (s["ruta"],)).fetchone()
        return {
            "simbolo": f"{s['nombre']} ({s['tipo']}) {s['ruta']}:{s['ini']}-{s['fin']}",
            "firma": s["firma"], "doc": (s["doc"] or "")[:400],
            "otros_con_ese_nombre": [f"{n[0]}:{n[1]}" for n in nodos[1:8]],
            "llamado_por": [f"{f['desde']} ({f['ruta']}:{f['linea']})" + ("" if f["confianza"] == "exacta" else " ?")
                            for f in self._entrantes(nodo)][:40],
            "llama_a": [f"{d[1]} ({d[0]})" for d in self._salientes(nodo)][:40],
            "hechos": [f"{h['r']} {h['o']}" for h in self._filas(
                "SELECT r, o FROM hechos WHERE s = ? AND ruta = ? LIMIT 60", (s["nombre"], s["ruta"]))],
            "archivo": archivo["r"] if archivo else "",
            "notas": [f"({f['tipo']}) {f['titulo']}: {f['texto'][:200]}" for f in self._filas(
                "SELECT tipo, titulo, texto FROM conocimiento WHERE rutas LIKE ? LIMIT 8", (f'%"{s["ruta"]}"%',))],
        }

    def _inicio(self, inicio: str) -> List[tuple]:
        """ Un símbolo, o un endpoint («GET /api/x» o «/api/x») resuelto a la función que lo expone """
        if "/api" in inicio or inicio.startswith("/"):
            from banco_proyecto import ruta_http_canonica
            ruta = ruta_http_canonica(inicio.split(" ", 1)[-1])
            return [(h["ruta"], h["s"]) for h in self._filas("SELECT s, ruta FROM hechos WHERE r = 'expone' AND o LIKE ?", (f"% {ruta}",))]
        return self._nodos(inicio)[:1]

    def recorrido(self, inicio: str, profundidad: int = 4, maximo: int = 60) -> str:
        """ Árbol de llamadas hacia abajo, con ubicaciones (solo lo definido en el proyecto) """
        lineas: List[str] = []
        vistos = set()

        def bajar(nodo: tuple, nivel: int):
            if len(lineas) >= maximo:
                return
            repetido = nodo in vistos
            lineas.append(f"{'  ' * nivel}{nodo[1]}  {self._ubicacion(nodo)}" + ("  (ya visto)" if repetido else ""))
            if repetido or nivel >= profundidad:
                return
            vistos.add(nodo)
            for sig in self._salientes(nodo):
                bajar(sig, nivel + 1)
        inicios = self._inicio(inicio)
        if not inicios:
            raise KeyError(f"No encontré «{inicio}» (ni como símbolo ni como endpoint)")
        for nodo in inicios:
            bajar(nodo, 0)
        return "\n".join(lineas) + ("\n[… recortado]" if len(lineas) >= maximo else "")

    def impacto(self, nombre: str, profundidad: int = 4) -> Dict[str, Any]:
        """ Qué se ve afectado si cambia `nombre`: quién lo llama (transitivamente, por aristas
        resueltas), qué endpoints exponen esos llamadores y qué partes del frontend los consumen """
        afectados: Dict[tuple, int] = {}
        frontera = self._nodos(nombre)[:1]
        for nivel in range(1, profundidad + 1):
            nueva = []
            for nodo in frontera:
                for f in self._entrantes(nodo):
                    clave = (f["ruta"], f["desde"])
                    if clave not in afectados:
                        afectados[clave] = nivel
                        nueva.append(clave)
            frontera = nueva
        todos = list(afectados) + self._nodos(nombre)[:1]
        endpoints = sorted({h["o"] for r, s in todos for h in self._filas(
            "SELECT o FROM hechos WHERE r = 'expone' AND s = ? AND ruta = ?", (s, r))})
        consumidores = sorted({f"{h['s']} ({h['ruta']})" for e in endpoints for h in self._filas(
            "SELECT s, ruta FROM hechos WHERE r = 'llama_api' AND o = ?", (e.split(" ", 1)[1],))})
        es_test = lambda r: "/tests/" in r or os.path.basename(r).startswith("test_")
        orden = sorted(afectados, key=lambda k: (afectados[k], k))
        return {"llamadores": [f"{n[1]} ({n[0]}) nivel {afectados[n]}" for n in orden if not es_test(n[0])][:80],
                "tests": sorted({n[1] for n in afectados if es_test(n[0])})[:40],
                "total": len(afectados), "endpoints": endpoints, "frontend": consumidores}

    def donde(self, x: str, maximo: int = 40) -> Dict[str, Any]:
        """ Dónde está y dónde se toca `x`, sea una clave de configuración, un endpoint, una variable de
        entorno, un id del DOM, un archivo de datos o un símbolo: los hechos del grafo agrupados por
        relación, la función que implementa el endpoint y quién lo consume, y dónde aparece como texto
        literal en el código (defaults, formularios, rutas de archivos). """
        x = (x or "").strip().strip("`")
        salida: Dict[str, Any] = {"x": x}
        if x.startswith("/") or re.match(r"^(GET|POST|PUT|DELETE|PATCH) /", x):
            salida["endpoint"] = self.api(x.split(" ", 1)[-1])
        por_relacion: Dict[str, List[str]] = {}
        for h in self._filas("SELECT s, r, o, ruta, linea FROM hechos WHERE o = ? OR o LIKE ? LIMIT 400", (x, f"% {x}")):
            por_relacion.setdefault(h["r"], []).append(f"{h['s']} ({h['ruta']}:{h['linea']})")
        if por_relacion:
            salida["hechos"] = {r: v[:maximo] for r, v in por_relacion.items()}
        simbolos = self._filas("SELECT ruta, nombre, tipo, ini FROM simbolos WHERE nombre = ? OR corto = ? LIMIT 10", (x, x.split(".")[-1]))
        if simbolos:
            salida["simbolos"] = [f"{s['nombre']} ({s['tipo']}) {s['ruta']}:{s['ini']}" for s in simbolos]
        literal = re.compile(r"""["'`]""" + re.escape(x) + r"""["'`/]""")
        apariciones = []
        for f in self._c.execute("SELECT ruta FROM archivos ORDER BY ruta"):
            for n, linea in enumerate(self.lineas(f["ruta"]), 1):
                if literal.search(linea):
                    apariciones.append(f"{f['ruta']}:{n}: {linea.strip()[:160]}")
                    if len(apariciones) >= maximo:
                        break
            if len(apariciones) >= maximo:
                break
        if apariciones:
            salida["como_texto"] = apariciones
        return salida

    def api(self, ruta_http: str) -> Dict[str, Any]:
        """ Rutas canónicas: los parámetros son * (/api/x/{id} y `/api/x/${id}` → /api/x/*) """
        from banco_proyecto import ruta_http_canonica
        ruta_http = ruta_http_canonica(ruta_http)
        expone = self._filas("SELECT s, o, ruta, linea FROM grafo WHERE r = 'expone' AND o LIKE ?", (f"% {ruta_http}",))
        consume = self._filas("SELECT s, o, ruta, linea FROM grafo WHERE r = 'llama_api' AND o = ?", (ruta_http,))
        return {"expone": expone, "consume": consume}

    def ast(self, ruta: str):
        import ast as modulo_ast
        return modulo_ast.parse("\n".join(self.lineas(ruta)))

    # ------------------------------------------------------------------ historia y memoria
    def cambios(self, desde_version: Optional[int] = None) -> List[Dict[str, Any]]:
        if desde_version is None:
            v = self._c.execute("SELECT valor FROM meta WHERE clave = 'version'").fetchone()
            desde_version = max(0, int(v["valor"]) - 20) if v else 0
        filas = self._filas("SELECT version, ruta, tipo, cuando, simbolos, mas, menos FROM cambios "
                            "WHERE version > ? ORDER BY id DESC LIMIT 300", (desde_version,))
        for f in filas:
            f["simbolos"] = json.loads(f["simbolos"] or "{}")
        return filas

    def diff(self, ruta: str) -> str:
        ruta = self._ruta(ruta)
        filas = self._filas("SELECT cuando, diff FROM cambios WHERE ruta = ? AND diff != '' ORDER BY id DESC LIMIT 3", (ruta,))
        return "\n\n".join(f"# {f['cuando']}\n{f['diff']}" for f in filas) or "Sin diffs registrados."

    def memoria(self, consulta: str = "") -> List[Dict[str, Any]]:
        if not consulta:
            return self._filas("SELECT id, tipo, titulo, texto, rutas, origen, revisar FROM conocimiento ORDER BY actualizado DESC LIMIT 200")
        return self._pedir("memoria", {"consulta": consulta})

    def resoluciones(self, consulta: str = "") -> List[Dict[str, Any]]:
        if not consulta:
            return self._filas("SELECT id, pregunta, resumen, rutas, cuando FROM resoluciones ORDER BY id DESC LIMIT 50")
        return self._pedir("resoluciones", {"consulta": consulta})

    def resumenes(self, nivel: Optional[str] = None) -> List[Dict[str, Any]]:
        if nivel:
            return self._filas("SELECT nivel, clave, texto FROM resumenes WHERE nivel = ? ORDER BY clave", (nivel,))
        return self._filas("SELECT nivel, clave, texto FROM resumenes ORDER BY nivel, clave")

    def sql(self, consulta: str, limite: int = 2000) -> List[Dict[str, Any]]:
        if not re.match(r"^\s*(select|with)\b", consulta, re.I):
            raise ValueError("Solo consultas SELECT (la base está en solo lectura).")
        filas = []
        for f in self._c.execute(consulta):
            d = dict(f)
            for k, v in d.items():
                if isinstance(v, bytes):
                    d[k] = f"<{len(v)} bytes>"
            filas.append(d)
            if len(filas) >= limite:
                break
        return filas

    def esquema(self) -> str:
        return "\n".join(f["sql"] for f in self._c.execute(
            "SELECT sql FROM sqlite_master WHERE type IN ('table','view') AND sql IS NOT NULL "
            "AND name NOT LIKE '%fts%' AND name NOT IN ('vectores')"))

    # ------------------------------------------------------------------ lo que se pide a Prig
    def llm(self, pregunta: str, contexto: str = "", max_tokens: int = 500) -> str:
        if self.llamadas_llm >= MAX_LLM_POR_EJECUCION:
            raise RuntimeError(f"Máximo {MAX_LLM_POR_EJECUCION} llamadas a P.llm por ejecución: agrupa el contexto.")
        self.llamadas_llm += 1
        return self._pedir("llm", {"pregunta": str(pregunta), "contexto": str(contexto),
                                   "max_tokens": max(50, min(int(max_tokens), 2000))})

    def anotar(self, tipo: str, titulo: str, texto: str, rutas: Optional[List[str]] = None) -> str:
        return self._pedir("anotar", {"tipo": tipo, "titulo": titulo, "texto": texto, "rutas": list(rutas or [])})

    def afirmar(self, s: str, r: str, o: str, ruta: Optional[str] = None) -> str:
        return self._pedir("afirmar", {"s": s, "r": r, "o": o, "ruta": ruta})

    def guardar(self, nombre: str, valor: Any) -> str:
        return self._pedir("guardar", {"nombre": nombre, "valor": json.loads(json.dumps(valor, default=str))})

    def recuperar(self, nombre: str) -> Any:
        f = self._c.execute("SELECT valor FROM trabajo WHERE nombre = ?", (nombre,)).fetchone()
        if not f:
            raise KeyError(f"No hay nada guardado como «{nombre}»")
        return json.loads(f["valor"])


# ======================================================================
# Lado de Prig: la sesión
# ======================================================================

class Consola:
    """ Una sesión de la memoria de consulta: un proceso aislado cuyas variables duran lo que dura
    la respuesta del modelo. `generar(pregunta, contexto, max_tokens)` atiende P.llm. """

    def __init__(self, banco, generar: Optional[Callable[[str, str, int], str]] = None,
                 al_llamar_llm: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.banco = banco
        self.generar = generar
        self.al_llamar_llm = al_llamar_llm
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.ejecuciones = 0
        self.llamadas_llm = 0

    def _arrancar(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        entorno = {"PATH": "/usr/bin:/bin", "PYTHONPATH": os.path.dirname(os.path.abspath(__file__)),
                   "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
                   "PRIG_CONSOLA_ALARMA": str(int(TIEMPO_POR_EJECUCION))}
        self._proc = subprocess.Popen(
            [sys.executable, "-I", "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); import memoria_consulta as m; m._worker(sys.argv[2], sys.argv[3])",
             os.path.dirname(os.path.abspath(__file__)), self.banco.ruta_db, self.banco.raiz],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
            env=entorno, cwd="/", start_new_session=True)

    def ejecutar(self, codigo: str, timeout: float = TIEMPO_TOTAL_POR_EJECUCION) -> Dict[str, Any]:
        import select
        with self._lock:
            self._arrancar()
            self.ejecuciones += 1
            proc = self._proc
            proc.stdin.write(json.dumps({"codigo": codigo}, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            limite = time.time() + timeout
            while True:
                # Esperar con plazo real: readline() solo se bloquearía sin límite
                listo, _, _ = select.select([proc.stdout], [], [], max(0.0, limite - time.time()))
                if not listo:
                    self.cerrar()
                    return {"salida": "", "error": f"La ejecución pasó de {timeout:.0f} s (subllamadas incluidas) y la "
                                                   f"consola se reinició (se perdieron las variables). Divide el trabajo.",
                            "variables": []}
                linea = proc.stdout.readline()
                if not linea:
                    self._proc = None
                    return {"salida": "", "error": "La consola terminó (memoria o tiempo agotados); se reinicia en la próxima llamada.",
                            "variables": []}
                try:
                    mensaje = json.loads(linea)
                except ValueError:
                    continue
                if "resultado" in mensaje:
                    return mensaje["resultado"]
                if "peticion" in mensaje:
                    try:
                        valor = self._atender(mensaje["peticion"], mensaje.get("datos") or {})
                        respuesta = {"id": mensaje.get("id"), "valor": valor}
                    except Exception as e:       # vuelve al código del modelo como excepción
                        respuesta = {"id": mensaje.get("id"), "error": f"{type(e).__name__}: {e}"}
                    proc.stdin.write(json.dumps(respuesta, ensure_ascii=False, default=str) + "\n")
                    proc.stdin.flush()

    def _atender(self, tipo: str, d: Dict[str, Any]) -> Any:
        b = self.banco
        if tipo == "buscar":
            return [{k: f[k] for k in ("ruta", "ini", "fin", "simbolo", "tipo", "texto")} for f in b.buscar(d["consulta"], k=d.get("k", 10))]
        if tipo == "memoria":
            return b.buscar_conocimiento(d["consulta"], k=12, vector=b._vector_consulta(d["consulta"]))
        if tipo == "resoluciones":
            return b.buscar_resoluciones(d["consulta"], k=8, vector=b._vector_consulta(d["consulta"]))
        if tipo == "anotar":
            r = b.anotar(d.get("tipo", "nota"), d.get("titulo", ""), d.get("texto", ""), d.get("rutas") or [], origen="modelo")
            return f"{'Actualizado' if r['actualizado'] else 'Guardado'}: ({r['tipo']}) {r['titulo']}"
        if tipo == "afirmar":
            b.afirmar(d["s"], d["r"], d["o"], d.get("ruta"), origen="modelo")
            return "Hecho añadido."
        if tipo == "guardar":
            b.guardar_trabajo(d["nombre"], d["valor"])
            return f"Guardado como «{d['nombre']}»."
        if tipo == "llm":
            if self.generar is None:
                raise RuntimeError("No hay un modelo disponible para P.llm en esta sesión.")
            if self.llamadas_llm >= MAX_LLM_POR_RESPUESTA:
                raise RuntimeError(f"Se agotaron las {MAX_LLM_POR_RESPUESTA} llamadas a P.llm de esta respuesta: "
                                   f"responde con lo que ya tienes o usa P.hechos / P.sql / P.grep.")
            self.llamadas_llm += 1
            if self.al_llamar_llm:
                self.al_llamar_llm({"pregunta": d["pregunta"][:200], "tokens_contexto": len(d["contexto"]) // 4})
            return self.generar(d["pregunta"], d["contexto"], d["max_tokens"])
        raise ValueError(f"Petición desconocida: {tipo}")

    def cerrar(self):
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.stdin.write(json.dumps({"fin": True}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        for tubo in (proc.stdin, proc.stdout):
            try:
                tubo.close()
            except Exception:
                pass

    def __del__(self):
        try:
            self.cerrar()
        except Exception:
            pass


def formatear(resultado: Dict[str, Any]) -> str:
    """ El resultado de una ejecución, como lo lee el modelo """
    partes = []
    if resultado.get("salida"):
        partes.append(resultado["salida"].rstrip())
    if resultado.get("error"):
        partes.append(f"ERROR: {resultado['error']}")
    if not partes:
        partes.append("(sin salida: usa print() o deja una expresión al final)")
    if resultado.get("variables"):
        partes.append(f"[variables: {', '.join(resultado['variables'])}]")
    return "\n".join(partes)
