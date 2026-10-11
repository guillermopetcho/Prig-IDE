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

Las consultas de datos de `P` (líneas, símbolos, grafo, caminos, hechos para la pregunta…) las responde el motor
del banco (Rust, banco_motor.py); aquí quedan la consola aislada que ejecuta el código del modelo y la sesión.

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

from banco_motor import rust as _rust

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
  P.cargar(ruta, sustituir={})                  → las funciones del archivo .py para EJECUTARLAS con un caso:
        m = P.cargar("x.py"); m.f(...). Para «¿tiene algún error?», pruébala así con un caso borde en vez
        de reescribirla. Lo que importa de otros módulos del proyecto queda en m.omitidos: pásalo en
        sustituir={"nombre": lambda ...: ...}
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
                                                  nombre completo «Clase.metodo» o «ruta:nombre» si hay varios).
                                                  P.llamadores agrega, con confianza «texto: …», llamadas que el grafo
                                                  no resuelve (instancia global, fábrica, función pasada como valor):
                                                  revisa su «codigo» antes de contarlas o descartarlas
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


def _importar_seguro(nombre, globales=None, locales=None, lista=(), nivel=0):
    if nombre.split(".")[0] not in MODULOS_PERMITIDOS or nivel:
        raise ImportError(f"No se puede importar «{nombre}» en la consola (para lo del proyecto: P.cargar(..., sustituir=))")
    return __import__(nombre, globales, locales, lista, nivel)


def _builtins_seguros() -> Dict[str, Any]:
    """ Los builtins de la consola: los del código del modelo y los del código que carga P.cargar """
    import builtins
    seguros = {n: getattr(builtins, n) for n in BUILTINS_PERMITIDOS if hasattr(builtins, n)}
    seguros["__import__"] = _importar_seguro
    return seguros


class _SinAnotaciones(ast.NodeTransformer):
    """ Sin las anotaciones de tipo: se evalúan al definir (List[str]…) y `typing` no se importa en la consola """

    def visit_arg(self, nodo):
        nodo.annotation = None
        return nodo

    def visit_FunctionDef(self, nodo):
        nodo.returns = None
        self.generic_visit(nodo)
        return nodo

    def visit_AnnAssign(self, nodo):
        if nodo.value is None:
            return None
        return ast.copy_location(ast.Assign(targets=[nodo.target], value=nodo.value), nodo)


class Cargado:
    """ Lo que devuelve P.cargar: las funciones, clases y constantes del archivo como atributos """

    def __init__(self, ruta: str, espacio: Dict[str, Any], cargados: List[str], omitidos: Dict[str, str]):
        for nombre in cargados:
            if not nombre.startswith("_"):
                setattr(self, nombre, espacio[nombre])
        self.ruta, self.cargados, self.omitidos = ruta, cargados, omitidos

    def __repr__(self):
        omitidos = "; ".join(f"{k}: {v}" for k, v in list(self.omitidos.items())[:12])
        return (f"<{self.ruta}: cargados {', '.join(self.cargados)}"
                + (f" · omitidos (lo que usan no está en la consola) → {omitidos}" if omitidos else "") + ">")


# ======================================================================
# El proceso aislado (worker)
# ======================================================================


# ======================================================================
# La API que ve el modelo
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
    P._en_caja = True

    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORIA_MB * 1024 * 1024, MEMORIA_MB * 1024 * 1024))
    except (ValueError, OSError):
        pass

    espacio: Dict[str, Any] = {"__builtins__": _builtins_seguros(), "P": P, "ayuda": lambda: print(AYUDA)}

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



class API:
    """ Lo que el modelo puede hacer con el proyecto. Solo lectura sobre la base; lo demás, pidiéndolo. """

    def __init__(self, conexion, raiz: str, pedir: Callable[[str, Dict[str, Any]], Any]):
        self._c = conexion
        self._raiz = raiz
        self._pedir = pedir
        self._contenido: Dict[str, List[str]] = {}
        self.llamadas_llm = 0
        self._en_caja = False           # True solo en el proceso aislado: P.cargar ejecuta código
        # Las consultas de datos las responde el motor del banco (Rust, banco_motor.py); lo que ejecuta código, aquí
        import banco_motor
        self._rs = banco_motor.consulta(conexion, raiz)

    def reiniciar_contadores(self):
        self.llamadas_llm = 0

    # ------------------------------------------------------------------ internos
    def _filas(self, sql: str, args=()) -> List[Dict[str, Any]]:
        return [dict(f) for f in self._c.execute(sql, args)]

    def _ruta(self, ruta: str) -> str:
        return self._rs.ruta(ruta or "")

    def lineas(self, ruta: str) -> List[str]:
        # Una caché de listas: P.grep recorre todo el proyecto
        ruta = self._ruta(ruta)
        if ruta not in self._contenido:
            self._contenido[ruta] = self._rs.lineas(ruta)
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
        desde = max(1, int(desde or 1))
        return self._rs.leer(ruta or "", desde, int(hasta) if hasta else None)

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
        return self._rs.simbolos(str(nombre) if nombre else None, str(ruta) if ruta else None, str(tipo) if tipo else None)

    def codigo(self, nombre: str) -> str:
        return self._rs.codigo(str(nombre))

    def cargar(self, ruta: str, sustituir: Optional[Dict[str, Any]] = None) -> "Cargado":
        """ Las funciones, clases y constantes de un archivo Python del proyecto, para EJECUTARLAS con un caso
        dentro de la consola (m = P.cargar("x.py"); m.f(...)). Revisando una función, el modelo solo podía
        reescribirla a mano, y al reescribirla elegía mal el caso o corregía el error sin verlo (E8, B2: 2 de 6).
        Cada definición pasa la MISMA revisión que el código del modelo (revisar: sin «_» en atributos, sin
        open/exec/getattr…, solo los módulos permitidos) y corre con los mismos builtins, en el mismo proceso
        aislado: no amplía lo que la consola puede hacer. Lo que no pasa queda en `.omitidos`, con el motivo.
        `sustituir`: nombres que el archivo trae de otros módulos del proyecto, reemplazados por algo simple
        ({"_tokens_de": lambda lineas, a, b: …}). """
        if not self._en_caja:
            raise RuntimeError("P.cargar solo funciona dentro de la consola")
        ruta = self._ruta(ruta)
        if not ruta.endswith(".py"):
            raise ValueError("P.cargar carga archivos Python")
        arbol = _SinAnotaciones().visit(ast.parse("\n".join(self.lineas(ruta))))
        espacio: Dict[str, Any] = {"__builtins__": _builtins_seguros(), "__name__": "cargado"}
        cargados: List[str] = []
        omitidos: Dict[str, str] = {}
        for nodo in arbol.body:
            if isinstance(nodo, ast.Expr) and isinstance(nodo.value, ast.Constant):
                continue                                                  # docstring
            if isinstance(nodo, ast.FunctionDef) or isinstance(nodo, ast.ClassDef):
                nombres = [nodo.name]
            elif isinstance(nodo, ast.Assign):
                nombres = [n.id for o in nodo.targets for n in ast.walk(o) if isinstance(n, ast.Name)]
            elif isinstance(nodo, (ast.Import, ast.ImportFrom)):
                nombres = [(a.asname or a.name).split(".")[0] for a in nodo.names]
            else:
                continue                                                  # if __name__…, llamadas sueltas
            try:
                modulo = ast.fix_missing_locations(ast.Module(body=[nodo], type_ignores=[]))
                revisar(ast.unparse(modulo))
                exec(compile(modulo, f"<{ruta}>", "exec"), espacio)
                cargados += [n for n in nombres if not isinstance(nodo, (ast.Import, ast.ImportFrom))]
            except CodigoNoPermitido as e:
                if not isinstance(nodo, (ast.Import, ast.ImportFrom)):
                    omitidos.update({n: str(e) for n in nombres})
            except Exception as e:                                    # noqa: BLE001 — una definición que no carga
                omitidos.update({n: f"{type(e).__name__}: {e}" for n in nombres})
        for nombre, valor in (sustituir or {}).items():
            espacio[nombre] = valor
            if nombre not in cargados:
                cargados.append(nombre)
            omitidos.pop(nombre, None)
        return Cargado(ruta, espacio, cargados, omitidos)

    def hechos(self, s: Optional[str] = None, r: Optional[str] = None, o: Optional[str] = None,
               limite: int = 500) -> List[Dict[str, Any]]:
        return self._rs.hechos(str(s) if s else None, str(r) if r else None, str(o) if o else None, int(limite))

    # ------------------------------------------------------------------ grafo de llamadas resuelto
    # Cada arista va de un símbolo exacto (archivo + nombre completo) a otro: la resolución usa el
    # receptor de la llamada, los import y el tipo de retorno anotado (banco_proyecto._resolver_llamadas).
    def _nodos(self, nombre: str) -> List[tuple]:
        """ Símbolos que casan con un nombre: completo («Motor.asegurar»), corto («asegurar») o
        «ruta:nombre» para desambiguar """
        return self._rs.nodos(nombre)


    def llamadores(self, nombre: str) -> List[Dict[str, Any]]:
        """ Las aristas resueltas del grafo y, marcadas con confianza «texto: …», las llamadas que el grafo
        no resuelve pero están en el código: por una instancia global o una fábrica (`servicio.f()`,
        `gestor().f()`), una función pasada como valor (`_desafio(modulo.f, …)`) o una lambda. Medido en el
        estudio del banco (docs/estudio-banco.md): esos huecos daban `[]` y el modelo concluía «nadie la
        llama» con una sola consulta. Lo de texto puede ser una homónima: conviene mirarlo. """
        return self._rs.llamadores(str(nombre))

    def _simbolo_en(self, ruta: str, linea: int) -> Optional[str]:
        return self._rs.simbolo_en(ruta, int(linea))


    def llamados(self, simbolo: str) -> List[Dict[str, Any]]:
        return self._rs.llamados(str(simbolo))

    def camino(self, desde: str, hasta: str, maximo: int = 10) -> Optional[List[str]]:
        """ Cadena de llamadas más corta entre dos símbolos (búsqueda en anchura sobre aristas resueltas) """
        return self._rs.camino(str(desde), str(hasta), int(maximo))

    def camino_con_llamadas(self, desde: str, hasta: str, maximo: int = 10) -> Optional[List[Dict[str, Any]]]:
        """ El camino, con la línea de cada llamada: la evidencia de cada salto. En T7 el modelo negó un camino que le
        daban los hechos porque, al leer el código, no vio dos de las llamadas (una dentro de un argumento, otra dentro
        de un diccionario literal; docs/estudio-banco.md) """
        return self._rs.camino_con_llamadas(str(desde), str(hasta), int(maximo))

    def codigo_del_salto(self, nodo: tuple, linea_llamada: Optional[int], maximo: int = 14) -> str:
        """ El código de una función intermedia de un camino: entera si es corta; si no, la firma y la línea de la
        llamada con su vecina. En T7 el paquete del modo general traía las dos puntas de 0b5f pero no la función del
        medio (la que llama a la siguiente), y el modelo negaba el camino con la evidencia en los hechos """
        return self._rs.codigo_del_salto(list(nodo), int(linea_llamada) if linea_llamada else None, int(maximo))


    # ------------------------------------------------------------------ primitivas de alto nivel
    # Cada una evita que el modelo escriba 100-300 tokens de Python: escribir es 20-80 veces más caro
    # que leer (medido), así que las consultas frecuentes van hechas.
    def ficha(self, nombre: str) -> Dict[str, Any]:
        """ Todo lo que se sabe de un símbolo: dónde está, firma, doc, quién lo llama, a qué llama,
        sus hechos, el resumen de su archivo y las notas de memoria de ese archivo """
        return self._rs.ficha(str(nombre))


    def recorrido(self, inicio: str, profundidad: int = 4, maximo: int = 60) -> str:
        """ Árbol de llamadas hacia abajo, con ubicaciones (solo lo definido en el proyecto) """
        return self._rs.recorrido(str(inicio), int(profundidad), int(maximo))

    def impacto(self, nombre: str, profundidad: int = 4) -> Dict[str, Any]:
        """ Qué se ve afectado si cambia `nombre`: quién lo llama (transitivamente, por aristas
        resueltas), qué endpoints exponen esos llamadores y qué partes del frontend los consumen """
        return self._rs.impacto(str(nombre), int(profundidad))

    def alcance_por_texto(self, nombre: str, profundidad: int = 3, maximo: int = 15) -> List[Dict[str, Any]]:
        """ Endpoints a los que se llega subiendo por los llamadores del grafo Y por los de texto (instancia global,
        fábrica, función pasada como valor, lambda), hasta `profundidad` llamadas. El grafo solo no veía, por ejemplo,
        `GET /api/progreso/resumen` para `progreso.historial`: `resumen` la llama y a `resumen` se la pasa como valor
        a `_desafio` (T7, f46b). `maximo` acota las búsquedas por texto (cada una recorre los archivos) """
        return self._rs.alcance_por_texto(str(nombre), int(profundidad), int(maximo))

    def donde(self, x: str, maximo: int = 40) -> Dict[str, Any]:
        """ Dónde está y dónde se toca `x`, sea una clave de configuración, un endpoint, una variable de
        entorno, un id del DOM, un archivo de datos o un símbolo: los hechos del grafo agrupados por
        relación, la función que implementa el endpoint y quién lo consume, y dónde aparece como texto
        literal en el código (defaults, formularios, rutas de archivos). """
        return self._rs.donde(str(x or ""), int(maximo))

    def api(self, ruta_http: str) -> Dict[str, Any]:
        """ Rutas canónicas: los parámetros son * (/api/x/{id} y `/api/x/${id}` → /api/x/*).
        Acepta el método delante («GET /api/x»): filtra lo expuesto por ese método """
        return self._rs.api(str(ruta_http))

    def ast(self, ruta: str):
        import ast as modulo_ast
        return modulo_ast.parse("\n".join(self.lineas(ruta)))

    # ------------------------------------------------------------------ historia y memoria
    def cambios(self, desde_version: Optional[int] = None) -> List[Dict[str, Any]]:
        return self._rs.cambios(int(desde_version) if desde_version is not None else None)

    def diff(self, ruta: str) -> str:
        return self._rs.diff(str(ruta))

    def memoria(self, consulta: str = "") -> List[Dict[str, Any]]:
        if not consulta:
            return self._rs.memoria_toda()
        return self._pedir("memoria", {"consulta": consulta})

    def resoluciones(self, consulta: str = "") -> List[Dict[str, Any]]:
        if not consulta:
            return self._rs.resoluciones_todas()
        return self._pedir("resoluciones", {"consulta": consulta})

    def resumenes(self, nivel: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._rs.resumenes(str(nivel) if nivel else None)

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


def _nombres_importados(lineas: List[str]) -> set:
    """ Los nombres que un archivo trae con import, en cualquier línea (Prig importa también a mitad de archivo y
    dentro de funciones), con los alias y los «from x import (a, b)» de varias líneas """
    return _rust().nombres_importados(list(lineas))


# ======================================================================
# Hechos para una pregunta (modo unidad)
# ======================================================================
# En el estudio del banco (docs/estudio-banco.md) el modo unidad acertó 86 % frente a 97 % del modo general en
# las mismas clases de pregunta: el general recibe en el prompt lo que el banco sabe de lo preguntado; el de
# unidad tenía que saber qué consultar, y fallaba ahí (P.llamadores sobre una clave de configuración, una sola
# consulta que el grafo no cubre, rutas inventadas). Esto le da lo mismo de entrada, sin tocar el prefijo
# guardado: va con la pregunta.


def terminos_de(pregunta: str, maximo: int = 4) -> List[str]:
    """ Lo que la pregunta nombra del código: rutas HTTP, lo que va entre `comillas` e identificadores con
    forma de código (snake_case, Clase.metodo, CONSTANTE). Las rutas de archivo no: ya están en la pregunta """
    return _rust().terminos_de(pregunta or "", maximo)


def _como_probarla(api: "API", nombre: str, rutas: Optional[List[str]] = None) -> str:
    """ Para «¿tiene algún error?» sobre una función de Python: cómo ejecutarla con un caso en la consola y qué
    dependencias del proyecto hay que sustituir. En E8 el modelo reescribía la función a mano (y elegía mal el caso o
    corregía el error sin verlo) y, aun con P.cargar disponible, no la ejecutó (B2) """
    filas = [f for f in api._filas("SELECT ruta, nombre FROM simbolos WHERE (nombre = ? OR corto = ?) AND ruta LIKE '%.py'",
                                    (nombre, nombre.split(".")[-1]))
             if not rutas or any(f["ruta"] == r or f["ruta"].endswith("/" + r) for r in rutas)]
    if not filas:
        return ""
    ruta, completo = filas[0]["ruta"], filas[0]["nombre"]
    arbol = ast.parse("\n".join(api.lineas(ruta)))
    externos, con_import = set(), set()
    for nodo in arbol.body:
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            modulo = nodo.module if isinstance(nodo, ast.ImportFrom) else None
            for a in nodo.names:
                raiz = (modulo or a.name).split(".")[0]
                if raiz not in MODULOS_PERMITIDOS:
                    externos.add((a.asname or a.name).split(".")[0])
        elif isinstance(nodo, ast.FunctionDef) and any(
                isinstance(x, (ast.Import, ast.ImportFrom)) and ((x.module if isinstance(x, ast.ImportFrom) else x.names[0].name)
                                                                 or "").split(".")[0] not in MODULOS_PERMITIDOS
                for x in ast.walk(nodo)):
            con_import.add(nodo.name)
    objetivo = None
    partes = completo.split(".")
    for nodo in arbol.body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name == partes[-1] and len(partes) == 1:
            objetivo = nodo
        elif isinstance(nodo, ast.ClassDef) and len(partes) == 2 and nodo.name == partes[0]:
            objetivo = next((m for m in nodo.body if isinstance(m, ast.FunctionDef) and m.name == partes[1]), None)
    if objetivo is None:
        return ""
    usados = {n.id for n in ast.walk(objetivo) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    tipos = {"List", "Dict", "Optional", "Tuple", "Set", "Any", "Callable", "Iterable", "Sequence", "Union"}
    sustituir = sorted((usados & con_import) - tipos)
    # Solo funciones de primer nivel que no usan módulos de afuera (os, sqlite3, subprocess…) y cuyos ayudantes del
    # proyecto se reemplazan fácil: un método hay que construirlo, y uno con E/S no se prueba así (y el modelo ya
    # encontraba esos errores leyendo; la pista lo distraería)
    if len(partes) != 1 or (usados & externos) - tipos or len(sustituir) > 2:
        return ""
    try:
        revisar(ast.unparse(_SinAnotaciones().visit(objetivo)))      # P.cargar la omitiría (open, getattr, «_»…)
    except CodigoNoPermitido:
        return ""
    llamada = f"m.{partes[0]}(...).{partes[1]}(...)" if len(partes) == 2 else f"m.{partes[0]}(...)"
    texto = (f"· to check `{completo}`, RUN it with a case instead of re-reading it (the console executes the project's "
             f"functions):\n  m = P.cargar(\"{ruta}\"" + (", sustituir={" + ", ".join(f'"{s}": ...' for s in sustituir) + "}"
                                                         if sustituir else "") + f"); {llamada}\n"
             "  try the edge cases: empty input, one element, exactly at the limit, just over it; compare what it returns "
             "with what it should return")
    if sustituir:
        texto += (f"\n  {', '.join(sustituir)}: from modules the console does not load (other project modules, os, "
                  "subprocess…): pass a simple version in sustituir")
    return texto


def sugiere_ejecutar(banco, pregunta: str) -> bool:
    """ ¿Es una pregunta de revisión sobre una función que conviene EJECUTAR con un caso (la pista de los hechos)? El chat
    lo usa para pedirle, una vez, que la ejecute si respondió sin hacerlo: con la pista sola, B2 de E8 la usó 1 de 3 """
    if not _rust().es_revision(pregunta or ""):
        return False
    rutas = _rust().rutas_de(pregunta or "")
    import sqlite3
    try:
        conexion = sqlite3.connect(f"file:{banco.ruta_db}?mode=ro", uri=True, timeout=10, check_same_thread=False)
        conexion.row_factory = sqlite3.Row
    except sqlite3.Error:
        return False
    try:
        api = API(conexion, banco.raiz, lambda *a, **k: None)
        for t in terminos_de(pregunta):
            try:
                if api._nodos(t) and _como_probarla(api, t, rutas):
                    return True
            except Exception:
                continue
        return False
    finally:
        conexion.close()


def hechos_de_la_pregunta(banco, pregunta: str, maximo_caracteres: int = 5000) -> str:
    """ Lo que el banco sabe de lo que nombra la pregunta, para el modo unidad: definición, hechos del grafo
    (lee_config, lee_entorno, expone, llama_api…), llamadores (resueltos y por texto), endpoints alcanzados y
    apariciones literales. Vacío si la pregunta no nombra nada del código o el banco no lo conoce. """
    if not terminos_de(pregunta):
        return ""
    import sqlite3
    try:
        conexion = sqlite3.connect(f"file:{banco.ruta_db}?mode=ro", uri=True, timeout=10, check_same_thread=False)
        conexion.row_factory = sqlite3.Row
    except sqlite3.Error:
        return ""
    try:
        api = API(conexion, banco.raiz, lambda *a, **k: None)
        # El motor arma los bloques (camino entre los nombrados, hechos de cada término y, en una revisión, el código
        # y las trampas); «cómo probarla» usa revisar, la regla de la consola aislada, y va aquí
        partes = api._rs.hechos_de_la_pregunta(pregunta)
        bloques = list(partes["bloques"])
        if partes["revision"]:
            # Primero lo de la revisión (el código, las trampas, cómo probarla): el total se recorta por el final
            revision = []
            for r in partes["revision"]:
                try:
                    como = _como_probarla(api, r["termino"], partes["rutas"])
                except Exception:
                    como = ""
                revision += [b for b in (r["codigo"], r["trampas"], como) if b]
            bloques = revision + bloques
    finally:
        conexion.close()
    return _texto_de_hechos(bloques, maximo_caracteres)


def _texto_de_hechos(bloques: List[str], maximo_caracteres: int) -> str:
    if not bloques:
        return ""
    texto = ("FACTS FROM THE PROJECT BANK about what the question names (call graph + literal text of the code; "
             "they can be incomplete — confirm with the console when it matters):\n" + "\n".join(bloques))
    return texto if len(texto) <= maximo_caracteres else texto[:maximo_caracteres].rsplit("\n", 1)[0] + "\n  (…)"


_CIERRE_INVENTADO = re.compile(r"^\s*</")
_CERCA = re.compile(r"^\s*```\w*\s*$")


def limpiar_codigo(codigo: str) -> str:
    """ Lo que el modelo agrega al código y nunca es Python: cercas de Markdown y «etiquetas de cierre»
    inventadas (visto en el estudio del banco: «print(P.api(...))\\n</print(P.api(...))» en la mitad de las
    consultas de una respuesta, cada una con su error y su repetición; docs/estudio-banco.md) """
    lineas = [l for l in (codigo or "").splitlines() if not _CIERRE_INVENTADO.match(l) and not _CERCA.match(l)]
    return "\n".join(lineas)


class Consola:
    """ Una sesión de la memoria de consulta: un proceso aislado cuyas variables duran lo que dura
    la respuesta del modelo. `generar(pregunta, contexto, max_tokens)` atiende P.llm. """

    def __init__(self, banco, generar: Optional[Callable[[str, str, int], str]] = None,
                 al_llamar_llm: Optional[Callable[[Dict[str, Any]], None]] = None, escribir: bool = True):
        self.banco = banco
        self.generar = generar
        self.al_llamar_llm = al_llamar_llm
        self.escribir = escribir        # False: el chat no tiene memoria; anotar/afirmar/guardar no escriben
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
        codigo = limpiar_codigo(codigo)
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
        if tipo in ("anotar", "afirmar", "guardar") and not self.escribir:
            return "No se guardó: este chat tiene la memoria desactivada."
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
