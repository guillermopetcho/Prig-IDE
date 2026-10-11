"""
Banco del proyecto: todo lo que un modelo necesita saber de un proyecto, sin límite de tamaño.

Un modelo tiene un contexto finito; un proyecto grande no cabe, y releerlo en cada pregunta
cuesta minutos. La idea es la de una memoria de trabajo con índice: el proyecto entero vive en
un SQLite y a cada pregunta se le da al modelo solo lo que le sirve, con herramientas para
pedir el resto. Así el tamaño del proyecto deja de depender del contexto.

Qué guarda (un SQLite por carpeta de trabajo, en ~/.prig_bancos):

  · archivos      su contenido (para calcular diffs), idioma, resumen y el análisis de IA
  · símbolos      clases, funciones y métodos con firma, docstring y líneas
                  (Python con su árbol sintáctico; JS/TS, C/C++/CUDA, Java/C#, Go y Rust con patrones)
  · fragmentos    el código cortado por función, con índice de texto (FTS5) y vectores
  · usos/imports  quién llama a qué y quién importa a quién (el grafo del proyecto)
  · cambios       cada archivo nuevo, modificado o borrado, con su diff y las funciones tocadas
  · conocimiento  definiciones, teoría, decisiones y contexto (del usuario, del modelo o del
                  análisis), con aviso cuando un archivo del que hablan cambia
  · resoluciones  cada pregunta respondida: resumen, archivos, y si después cambiaron

El motor es de Rust (el módulo `prig_banco`, código en ~/prig-memoria; banco_motor.py lo carga): indexa, analiza
el código, resuelve el grafo, busca, arma el mapa y el paquete de cada pregunta, guarda la memoria y parte el
proyecto en unidades. Hace exactamente lo que hacía el motor de Python que reemplazó (mismas tablas, ids y textos;
docs/plan-banco-rust.md), unas 10 veces más rápido al indexar. Aquí queda la cara que usa Prig, con los mismos
nombres de siempre, y lo que no es del motor: el análisis con IA (llama al modelo), el embebedor (Ollama) y el
gestor de bancos (hilos).

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

import json
import math
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from banco_motor import rust as _rust

VERSION_ESQUEMA = 6          # 5: funciones anidadas como símbolos; 6: prefijo de APIRouter/Blueprint en `expone`,
                             #    métodos de route(), `lee_config` sin escrituras ni tests, `llama_api` con cualquier
                             #    cadena /api/ (docs/estudio-banco.md, E2). El esquema lo crea el motor.
CARACTERES_POR_TOKEN = 3.5
TIPOS_CONOCIMIENTO = ("definicion", "teoria", "decision", "contexto", "nota")


# ======================================================================
# Utilidades (del motor)
# ======================================================================

def estimar_tokens(texto: str) -> int:
    return _rust().estimar_tokens(texto or "")


def _sha(texto: str) -> str:
    return _rust().sha(texto)


def terminos(texto: str, limite: int = 4000) -> List[str]:
    """ Palabras buscables: identificadores completos y sus partes (snake_case y camelCase) """
    return _rust().terminos(texto or "", limite)


def terminos_consulta(texto: str) -> List[str]:
    return _rust().terminos_consulta(texto or "")


def identificadores_nombrados(texto: str) -> Set[str]:
    """ Lo que en una pregunta parece un nombre de código: snake_case, camelCase, `entre comillas`,
    llamadas f() o rutas """
    return set(_rust().identificadores_nombrados(texto or ""))


def carpeta_bancos() -> str:
    return _rust().carpeta_bancos()


def lenguaje_de(ruta: str) -> Optional[str]:
    return _rust().lenguaje_de(ruta)


def simbolos_python(texto: str) -> Tuple[List[Dict[str, Any]], List[str], str]:
    """ (símbolos, módulos importados, docstring del módulo) """
    s, i, d = _rust().simbolos_python(texto)
    return s, i, d


def alias_python(texto: str) -> List[Tuple[str, str]]:
    return _rust().alias_python(texto)


def simbolos_genericos(texto: str, lenguaje: str) -> List[Dict[str, Any]]:
    """ Símbolos de JS/TS, C/C++/CUDA, Java/C#, Go y Rust, por patrones """
    return _rust().simbolos_genericos(texto, lenguaje)


def secciones_markdown(texto: str) -> List[Dict[str, Any]]:
    return _rust().secciones_markdown(texto)


def importaciones_genericas(texto: str, lenguaje: str) -> List[str]:
    return _rust().importaciones_genericas(texto, lenguaje)


def hechos_python(rel: str, texto: str, simbolos: List[Dict[str, Any]]) -> List[Tuple[str, str, str, int]]:
    return _rust().hechos_python(rel, texto, list(simbolos))


def hechos_texto(rel: str, lenguaje: str, texto: str, simbolos: List[Dict[str, Any]]) -> List[Tuple[str, str, str, int]]:
    return _rust().hechos_texto(rel, lenguaje, texto, list(simbolos))


def extraer_hechos(rel: str, lenguaje: str, texto: str, simbolos: List[Dict[str, Any]]) -> List[Tuple[str, str, str, int]]:
    try:
        if lenguaje in ("python", "cuaderno"):
            return hechos_python(rel, texto, simbolos)
        return hechos_texto(rel, lenguaje, texto, simbolos)
    except Exception:            # un extractor no puede impedir que se indexe el archivo
        return []


def ruta_http_canonica(ruta: str) -> str:
    """ La misma forma para las rutas del backend y del frontend, así se comparan con ==:
    /api/x/{id} y `/api/x/${id}` → /api/x/*  (sin consulta ni barra final) """
    return _rust().ruta_http_canonica(ruta)


def endpoint_de(consumida: str, expuestas: Iterable[str]) -> Optional[str]:
    """ La ruta expuesta que atiende una ruta que llama el frontend: la misma, o la más larga que sea sufijo """
    return _rust().endpoint_de(consumida, list(expuestas))


def resumir_respuesta(respuesta: str, maximo: int = 600) -> str:
    """ Resumen extractivo de una respuesta: la prosa inicial sin bloques de código, más qué código dejó """
    return _rust().resumir_respuesta(respuesta, maximo)


class _EsTest:
    """ `_ES_TEST.search(ruta)` de siempre, resuelto por el motor """

    @staticmethod
    def search(ruta: str) -> bool:
        return _rust().es_test(ruta)


_ES_TEST = _EsTest()


# ======================================================================
# El banco
# ======================================================================

class BancoProyecto:
    def __init__(self, raiz: str, carpeta: Optional[str] = None,
                 embeber: Optional[Callable[[List[str]], List[List[float]]]] = None,
                 embebedor_listo: Optional[Callable[[], bool]] = None,
                 modelo_vectores: str = "bge-m3"):
        self._rs = _rust().Banco(raiz, carpeta, modelo_vectores)
        self.raiz = self._rs.raiz
        self.carpeta = self._rs.carpeta
        self.ruta_db = self._rs.ruta_db
        self.embeber = embeber
        self.embebedor_listo = embebedor_listo
        self.modelo_vectores = modelo_vectores
        self._lock = threading.RLock()
        self._ultima_sincronizacion = 0.0

    # ------------------------------------------------------------------ base de datos
    @contextmanager
    def conectar(self):
        """ Una conexión de Python al mismo archivo: la usan los módulos que guardan sus tablas en el banco
        (lecturas, fichas, examen). La misma libsqlite3 que el motor, así que conviven sin pisarse. """
        c = sqlite3.connect(self.ruta_db, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def _meta(self, clave: str, defecto: Optional[str] = None) -> Optional[str]:
        valor = self._rs.meta(clave)
        return defecto if valor is None else valor

    def _guardar_meta(self, clave: str, valor: Any, c=None):
        self._rs.guardar_meta(clave, str(valor))

    @property
    def version(self) -> int:
        return self._rs.version

    # ------------------------------------------------------------------ sincronizar
    def sincronizar(self, forzar: bool = False) -> Dict[str, Any]:
        """ Relee solo lo que cambió. Rápido cuando no hay cambios (solo mira fecha y tamaño). """
        with self._lock:
            r = self._rs.sincronizar(forzar)
        self._ultima_sincronizacion = time.time()
        return r

    def _resolver_importaciones(self):
        self._rs.resolver_importaciones()

    def _resolver_llamadas(self):
        self._rs.resolver_llamadas()

    # ------------------------------------------------------------------ vectores
    def vectores_pendientes(self) -> int:
        return self._rs.vectores_pendientes()

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
        filas = [tuple(x) for x in self._rs.vectores_por_hacer(maximo)]
        hechos = 0
        for i in range(0, len(filas), lote):
            tanda = filas[i:i + lote]
            try:
                vectores = self.embeber([t for _, t in tanda])
            except Exception as e:
                return {"ok": False, "hechos": hechos, "error": str(e), "pendientes": self.vectores_pendientes()}
            if len(vectores) != len(tanda):
                break
            self._rs.guardar_vectores([(clave, [float(x) for x in v]) for (clave, _), v in zip(tanda, vectores)])
            hechos += len(tanda)
        return {"ok": True, "hechos": hechos, "pendientes": self.vectores_pendientes()}

    def _vector_consulta(self, texto: str) -> Optional[List[float]]:
        if not self._rs.hay_vectores() or not self._embebedor_ok():
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
    def buscar(self, consulta: str, k: int = 20, vector: Optional[List[float]] = None,
               con_vector: bool = True) -> List[Dict[str, Any]]:
        """ Fragmentos más relevantes: fusión por rangos de texto (BM25), vectores, símbolos
        nombrados y rutas mencionadas, más una pizca a lo que cambió hace poco. """
        qv = (vector if vector is not None else self._vector_consulta(consulta)) if con_vector else None
        return self._rs.buscar(consulta, k, qv)

    def _rutas_mencionadas(self, c, texto: str) -> Set[str]:
        return set(self._rs.rutas_mencionadas(texto or ""))

    def vecinos(self, fragmentos: List[Dict[str, Any]], limite: int = 12) -> List[Dict[str, Any]]:
        """ Las definiciones que llaman los fragmentos elegidos y quién los llama (1 salto, por aristas resueltas) """
        return self._rs.vecinos(fragmentos, limite)

    def buscar_conocimiento(self, consulta: str, k: int = 6, vector: Optional[List[float]] = None,
                            rutas: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        return self._rs.buscar_conocimiento(consulta, k, vector, set(rutas) if rutas else None)

    def buscar_resoluciones(self, consulta: str, k: int = 3, vector: Optional[List[float]] = None) -> List[Dict[str, Any]]:
        return self._rs.buscar_resoluciones(consulta, k, vector)

    def cambios_desde(self, version: int, limite: int = 40) -> List[Dict[str, Any]]:
        return self._rs.cambios_desde(version, limite)

    # ------------------------------------------------------------------ mapa y contexto
    def mapa(self, presupuesto: int = 3000) -> str:
        """ Estructura del proyecto. Estable: no cambia con cada edición (sin números de línea ni
        tamaños), para que el motor la guarde como prefijo. Si no cabe, se resume por carpetas. """
        return self._rs.mapa(presupuesto)

    def componer(self, pregunta: str, presupuesto: int = 8000, version_vista: Optional[int] = None,
                 excluir_rutas: Optional[Set[str]] = None, usar_resoluciones: bool = True) -> Dict[str, Any]:
        """ Lo relevante para esta pregunta, dentro del presupuesto de tokens. `usar_resoluciones=False`: sin
        las respuestas anteriores (mediciones aisladas: si no, cada corrida ve las respuestas de la anterior) """
        return self._rs.componer(pregunta, presupuesto, version_vista, set(excluir_rutas or ()), usar_resoluciones,
                                 self._vector_consulta(pregunta))

    def _lenguajes(self, rutas: List[str]) -> Dict[str, str]:
        return self._rs.lenguajes(list(rutas))

    # ------------------------------------------------------------------ conocimiento
    def anotar(self, tipo: str, titulo: str, texto: str, rutas: Optional[List[str]] = None,
               origen: str = "usuario") -> Dict[str, Any]:
        return self._rs.anotar(tipo, str(titulo or ""), str(texto or ""), [str(x) for x in (rutas or []) if x], origen)

    def olvidar_conocimiento(self, i: int) -> bool:
        return self._rs.olvidar_conocimiento(int(i))

    def listar_conocimiento(self, limite: int = 500) -> List[Dict[str, Any]]:
        return self._rs.listar_conocimiento(limite)

    # ------------------------------------------------------------------ grafo y memoria de trabajo
    def afirmar(self, s: str, r: str, o: str, ruta: Optional[str] = None, origen: str = "modelo"):
        self._rs.afirmar(str(s or ""), str(r or ""), str(o or ""), ruta or "", origen)

    def guardar_trabajo(self, nombre: str, valor: Any):
        self._rs.guardar_trabajo(str(nombre or ""), json.dumps(valor, ensure_ascii=False, default=str))

    # ------------------------------------------------------------------ unidades de lectura
    def guardar_particion(self, unidades: List[Dict[str, Any]], resumen: Dict[str, Any]):
        """ La partición del proyecto en unidades de lectura (particion_proyecto.py) """
        self._rs.guardar_particion(unidades, resumen)

    def unidades(self) -> List[Dict[str, Any]]:
        return self._rs.unidades()

    def particion(self) -> Optional[Dict[str, Any]]:
        return self._rs.particion()

    def guardar_resumen(self, nivel: str, clave: str, texto: str, sha_fuente: str, modelo: str = ""):
        self._rs.guardar_resumen(nivel, clave, texto, sha_fuente, modelo)

    # ------------------------------------------------------------------ resoluciones
    def registrar_resolucion(self, pregunta: str, respuesta: str, modelo: str = "",
                             rutas: Optional[Iterable[str]] = None) -> Optional[int]:
        return self._rs.registrar_resolucion(pregunta or "", respuesta or "", modelo, [str(x) for x in (rutas or [])])

    def listar_resoluciones(self, limite: int = 100) -> List[Dict[str, Any]]:
        return self._rs.listar_resoluciones(limite)

    def resolucion(self, i: int) -> Optional[Dict[str, Any]]:
        return self._rs.resolucion(int(i))

    def olvidar_resolucion(self, i: int) -> bool:
        return self._rs.olvidar_resolucion(int(i))

    # ------------------------------------------------------------------ análisis con IA
    def pendientes_de_analisis(self) -> List[str]:
        return self._rs.pendientes_de_analisis()

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
            f = self._rs.para_analizar(rel)
            if not f:
                continue
            sha, texto = f
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
            self._rs.guardar_analisis(rel, str(datos["resumen"])[:300], sha)
            for i in self._rs.notas_de_analisis(rel):
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
        return self._rs.contenido_de_carpetas()

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
            previos = self._rs.shas_de_resumenes("carpeta")
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
        readme, hay_previo, previo = self._rs.readme_y_previo()
        sha = _sha(entrada + readme)
        if entrada and (not hay_previo or previo != sha) and self._esperar(guardia, cancelar, progreso):
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
        return self._rs.trabajo_pendiente()

    # ------------------------------------------------------------------ consultas para herramientas
    def ver_simbolo(self, nombre: str, maximo: int = 4) -> str:
        return self._rs.ver_simbolo(nombre or "", maximo)

    def quien_usa(self, nombre: str, maximo: int = 60) -> str:
        return self._rs.quien_usa(nombre or "", maximo)

    def resumen_archivo(self, ruta: str) -> str:
        return self._rs.resumen_archivo(ruta or "")

    def texto_cambios(self, limite: int = 15) -> str:
        return self._rs.texto_cambios(limite)

    def recordar(self, consulta: str) -> str:
        return self._rs.recordar(consulta, self._vector_consulta(consulta))

    def texto_busqueda(self, consulta: str, k: int = 12) -> str:
        return self._rs.texto_busqueda(consulta, k, self._vector_consulta(consulta))

    # ------------------------------------------------------------------ estado
    def estado(self) -> Dict[str, Any]:
        return self._rs.estado()


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
        return os.path.isfile(os.path.join(_rust().carpeta_de(raiz), "banco.db"))

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
            carpeta = _rust().carpeta_de(raiz)
        if not os.path.isdir(carpeta):
            return False
        import shutil
        shutil.rmtree(carpeta, ignore_errors=True)
        return True
