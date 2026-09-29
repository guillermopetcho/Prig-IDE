"""
Examen del proyecto (etapa 0 de docs/arquitectura-unificada.md): la vara con la que se mide cada
variante del sistema (sin banco, con banco, con ramas restauradas, con tronco…).

Las preguntas salen del banco (grafo resuelto, hechos, símbolos y código), así que su respuesta
correcta se conoce y se corrige sola:

  config      ¿qué funciones leen la clave de configuración X?
  endpoint    ¿qué función implementa el endpoint X y en qué archivo está?
  frontend    ¿qué funciones del frontend llaman al endpoint X?
  llamadores  ¿quién llama a la función X?
  ubicacion   ¿en qué archivo está definida X?
  recorrido   ¿por qué funciones pasa la ejecución desde X hasta Y?
  impacto     si cambia X, ¿qué endpoints se ven afectados?
  constante   ¿cuánto vale la constante X en el archivo Y?
  entorno     ¿qué función lee la variable de entorno X?

Corrección: fracción de lo esperado que aparece en la respuesta (por nombre corto o completo, por
ruta o por nombre de archivo, por valor), más los identificadores que la respuesta cita y no existen
en el proyecto (inventos). El examen se guarda en el banco: todas las variantes responden las mismas
preguntas.
"""

import ast
import hashlib
import json
import os
import random
import re
import time
import zlib
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

TIPOS = ("config", "endpoint", "frontend", "llamadores", "ubicacion", "recorrido", "impacto", "constante", "entorno")


def _es_test(ruta: str) -> bool:
    import banco_proyecto as bp
    return bool(bp._ES_TEST.search(ruta))


def _corto(nombre: str) -> str:
    return nombre.split(".")[-1]


def _crear_tablas(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS examen (
        id TEXT PRIMARY KEY, tipo TEXT, pregunta TEXT, esperado TEXT, evaluar TEXT, version INTEGER, creado TEXT);
    CREATE TABLE IF NOT EXISTS examen_resultados (
        corrida TEXT, id TEXT, variante TEXT, puntaje REAL, inventos TEXT, segundos REAL, tokens INTEGER,
        respuesta TEXT, cuando TEXT);
    """)


# ======================================================================
# Generación
# ======================================================================

def generar(banco, por_tipo: int = 17, semilla: int = 7, guardar: bool = True) -> List[Dict[str, Any]]:
    azar = random.Random(semilla)
    preguntas: List[Dict[str, Any]] = []
    with banco.conectar() as c:
        produccion = {f["ruta"] for f in c.execute("SELECT ruta, lenguaje FROM archivos")
                      if f["lenguaje"] in ("python", "js", "c", "go", "rust", "java") and not _es_test(f["ruta"])}
        hechos = [dict(f) for f in c.execute("SELECT s, r, o, ruta, linea FROM hechos")]
        llamadas = [dict(f) for f in c.execute("SELECT ruta, desde, a_ruta, a_nombre, confianza FROM llamadas WHERE confianza = 'exacta'")]
        simbolos = [dict(f) for f in c.execute("SELECT ruta, nombre, corto, tipo, ini FROM simbolos")]
        contenidos = {f["ruta"]: f["contenido"] for f in c.execute("SELECT ruta, contenido FROM archivos WHERE lenguaje = 'python'")}

    def elegir(candidatos: List[Any], n: int) -> List[Any]:
        candidatos = sorted(candidatos, key=lambda x: json.dumps(x, sort_keys=True, default=str))
        azar.shuffle(candidatos)
        return candidatos[:n]

    ids: Set[str] = set()

    def agregar(tipo: str, pregunta: str, esperado: List[str], evaluar: str = "conjunto"):
        pid = hashlib.sha1(f"{tipo}|{pregunta}".encode()).hexdigest()[:12]
        if pid in ids:                  # la misma pregunta por dos caminos (p. ej. dos recorridos iguales)
            return
        ids.add(pid)
        preguntas.append({"id": pid, "tipo": tipo, "pregunta": pregunta, "esperado": esperado, "evaluar": evaluar})

    # config / entorno: quién lee una clave
    for tipo, relacion, texto in (("config", "lee_config", "la clave de configuración"), ("entorno", "lee_entorno", "la variable de entorno")):
        lectores: Dict[str, Set[str]] = defaultdict(set)
        for h in hechos:
            if h["r"] == relacion and h["ruta"] in produccion and h["s"] != h["ruta"]:
                lectores[h["o"]].add(h["s"])
        candidatos = [(k, sorted(v)) for k, v in lectores.items() if 1 <= len(v) <= 4 and len(k) >= 3]
        for clave, quienes in elegir(candidatos, por_tipo):
            agregar(tipo, f"¿Qué funciones o métodos del proyecto leen {texto} `{clave}`?", quienes)

    # endpoint: qué función lo implementa y dónde
    expone = [h for h in hechos if h["r"] == "expone" and h["ruta"] in produccion]
    for h in elegir(expone, por_tipo):
        agregar("endpoint", f"¿Qué función implementa el endpoint `{h['o']}` y en qué archivo está?",
                [h["s"], h["ruta"]], "todos")

    # frontend: quién lo llama
    expuestos = {h["o"].split(" ", 1)[1] for h in expone}
    consumidores: Dict[str, Set[str]] = defaultdict(set)
    for h in hechos:
        if h["r"] == "llama_api" and h["o"] in expuestos and h["s"] != h["ruta"]:
            consumidores[h["o"]].add(h["s"])
    candidatos = [(k, sorted(v)) for k, v in consumidores.items() if 1 <= len(v) <= 4]
    for ruta, quienes in elegir(candidatos, por_tipo):
        agregar("frontend", f"¿Qué funciones del frontend llaman al endpoint `{ruta}`?", quienes)

    # llamadores exactos
    entrantes: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for l in llamadas:
        if l["ruta"] in produccion and l["a_ruta"] in produccion:
            entrantes[(l["a_ruta"], l["a_nombre"])].add(l["desde"])
    candidatos = [(k, sorted(v)) for k, v in entrantes.items()
                  if 1 <= len(v) <= 4 and not _corto(k[1]).startswith("__") and len(_corto(k[1])) > 3]
    for (ruta, nombre), quienes in elegir(candidatos, por_tipo):
        agregar("llamadores", f"¿Qué funciones o métodos llaman a `{nombre}` (definida en `{ruta}`)?", quienes)

    # ubicación: nombres únicos
    por_corto: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in simbolos:
        if s["tipo"] in ("funcion", "clase", "metodo"):
            por_corto[s["corto"]].append(s)
    candidatos = [v[0] for k, v in por_corto.items() if len(v) == 1 and v[0]["ruta"] in produccion
                  and len(k) > 6 and not k.startswith("_")]
    for s in elegir(candidatos, por_tipo):
        agregar("ubicacion", f"¿En qué archivo está definida `{s['nombre']}`?", [s["ruta"]], "ruta")

    # recorrido: desde un endpoint hasta una función a 3 saltos, por aristas exactas
    salientes: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
    for l in llamadas:
        if l["ruta"] in produccion and l["a_ruta"] in produccion:
            salientes[(l["ruta"], l["desde"])].append((l["a_ruta"], l["a_nombre"]))
    recorridos = []
    for h in expone:
        inicio = (h["ruta"], h["s"])
        previo = {inicio: None}
        frontera = [inicio]
        for nivel in range(3):
            nueva = []
            for n in frontera:
                for m in salientes.get(n, []):
                    if m not in previo:
                        previo[m] = n
                        nueva.append(m)
            frontera = nueva
        for destino in frontera:
            cadena = [destino]
            while previo[cadena[-1]] is not None:
                cadena.append(previo[cadena[-1]])
            cadena.reverse()
            if len(cadena) == 4 and len({_corto(n[1]) for n in cadena}) == 4:
                recorridos.append(cadena)
    for cadena in elegir(recorridos, por_tipo):
        agregar("recorrido", f"¿Por qué funciones pasa la ejecución desde `{cadena[0][1]}` (endpoint en `{cadena[0][0]}`) "
                             f"hasta llegar a `{cadena[-1][1]}` (en `{cadena[-1][0]}`)? Nombra las intermedias en orden.",
                [n[1] for n in cadena[1:-1]])

    # impacto: endpoints alcanzables hacia arriba en 3 saltos
    llamadores: Dict[Tuple[str, str], Set[Tuple[str, str]]] = defaultdict(set)
    for l in llamadas:
        if l["ruta"] in produccion and l["a_ruta"] in produccion:
            llamadores[(l["a_ruta"], l["a_nombre"])].add((l["ruta"], l["desde"]))
    endpoint_de = {(h["ruta"], h["s"]): h["o"] for h in expone}
    impactos = []
    for nodo in list(llamadores):
        if nodo in endpoint_de or _corto(nodo[1]).startswith("_"):
            continue
        vistos, frontera = set(), [nodo]
        for _ in range(3):
            frontera = [p for n in frontera for p in llamadores.get(n, ()) if p not in vistos]
            vistos |= set(frontera)
        eps = sorted({endpoint_de[v] for v in vistos if v in endpoint_de})
        if 1 <= len(eps) <= 4:
            impactos.append((nodo, eps))
    for (ruta, nombre), eps in elegir(impactos, por_tipo):
        agregar("impacto", f"Si cambio el comportamiento de `{nombre}` (en `{ruta}`), ¿qué endpoints HTTP del backend "
                           f"se ven afectados directa o indirectamente?", eps, "endpoints")

    # constantes de módulo en Python
    constantes = []
    for ruta, crudo in contenidos.items():
        if ruta not in produccion:
            continue
        try:
            arbol = ast.parse(zlib.decompress(crudo).decode("utf-8", "replace"))
        except (SyntaxError, ValueError):
            continue
        for nodo in arbol.body:
            if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
                nombre = nodo.targets[0].id
                valor = nodo.value
                if re.fullmatch(r"[A-Z][A-Z0-9_]{3,}", nombre) and isinstance(valor, ast.Constant) \
                        and isinstance(valor.value, (int, float)) and not isinstance(valor.value, bool):
                    constantes.append((ruta, nombre, repr(valor.value)))
    for ruta, nombre, valor in elegir(constantes, por_tipo):
        agregar("constante", f"¿Cuánto vale la constante `{nombre}` en `{ruta}`?", [valor], "valor")

    if guardar:
        with banco.conectar() as c:
            _crear_tablas(c)
            c.execute("DELETE FROM examen")
            ahora = datetime.now().isoformat(timespec="seconds")
            c.executemany("INSERT INTO examen VALUES (?,?,?,?,?,?,?)",
                          [(p["id"], p["tipo"], p["pregunta"], json.dumps(p["esperado"], ensure_ascii=False),
                            p["evaluar"], banco.version, ahora) for p in preguntas])
    return preguntas


def cargar(banco) -> List[Dict[str, Any]]:
    with banco.conectar() as c:
        _crear_tablas(c)
        filas = [dict(f) for f in c.execute("SELECT * FROM examen ORDER BY tipo, id")]
    for f in filas:
        f["esperado"] = json.loads(f["esperado"])
    return filas


# ======================================================================
# Corrección
# ======================================================================

def _aparece(nombre: str, texto: str) -> bool:
    for candidato in {nombre, _corto(nombre)}:
        if candidato and re.search(r"(?<![\w.])" + re.escape(candidato) + r"(?![\w])", texto):
            return True
    return False


def _numeros(texto: str) -> List[float]:
    salida = []
    for m in re.findall(r"-?\d[\d.,_]*", texto):
        limpio = m.replace("_", "")
        for cand in (limpio, limpio.replace(".", "").replace(",", "."), limpio.replace(",", "")):
            try:
                salida.append(float(cand))
            except ValueError:
                pass
    return salida


def nombres_conocidos(banco) -> Set[str]:
    """ Todo identificador que aparece en el código del proyecto (más símbolos, hechos y rutas): un
    nombre citado solo es un invento si no existe en ninguna parte (constantes, atributos y
    manejadores de eventos no son símbolos, pero existen) """
    conocidos: Set[str] = set()
    with banco.conectar() as c:
        for f in c.execute("SELECT contenido FROM archivos"):
            conocidos |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", zlib.decompress(f["contenido"]).decode("utf-8", "replace")))
        for f in c.execute("SELECT nombre, corto FROM simbolos"):
            conocidos |= {f["nombre"], f["corto"]}
        for f in c.execute("SELECT s, o FROM hechos"):
            conocidos |= {f["s"], f["o"], _corto(f["s"])}
        for f in c.execute("SELECT ruta FROM archivos"):
            conocidos |= {f["ruta"], os.path.basename(f["ruta"]), os.path.basename(f["ruta"]).rsplit(".", 1)[0]}
        for f in c.execute("SELECT nombre FROM usos"):
            conocidos.add(f["nombre"])
    return conocidos


_CITADO = re.compile(r"`([A-Za-z_][\w.]*)(?:\(\))?`")


def grafo_corto(banco) -> Dict[str, Set[str]]:
    """ Llamadas resueltas por nombre corto, para validar recorridos alternativos """
    g: Dict[str, Set[str]] = defaultdict(set)
    with banco.conectar() as c:
        for f in c.execute("SELECT desde, a_nombre FROM llamadas"):
            g[_corto(f["desde"])].add(_corto(f["a_nombre"]))
    return g


def _recorrido_valido(pregunta: Dict[str, Any], texto: str, grafo: Dict[str, Set[str]]) -> bool:
    """ ¿La respuesta nombra una cadena real de llamadas del inicio al final? Se buscan caminos que
    solo pasen por funciones que la respuesta menciona. """
    citados = re.findall(r"`([^`]+)`", pregunta["pregunta"])
    if len(citados) < 3:
        return False
    inicio, fin = _corto(citados[0]), _corto(citados[2])
    mencionados = {_corto(n) for n in re.findall(r"[A-Za-z_][\w.]*", texto)} | {inicio, fin}
    vistos, frontera = {inicio}, [inicio]
    for _ in range(8):
        frontera = [m for n in frontera for m in grafo.get(n, ()) if m in mencionados and m not in vistos]
        vistos |= set(frontera)
        if fin in vistos:
            return True
    return False


def corregir(pregunta: Dict[str, Any], respuesta: str, conocidos: Optional[Set[str]] = None,
             grafo: Optional[Dict[str, Set[str]]] = None) -> Dict[str, Any]:
    texto = respuesta or ""
    esperado = pregunta["esperado"]
    modo = pregunta["evaluar"]
    if pregunta.get("tipo") == "recorrido" and grafo is not None and _recorrido_valido(pregunta, texto, grafo):
        return {"puntaje": 1.0, "encontrados": list(esperado), "faltan": [], "inventos": [],
                "alternativo": not all(_aparece(e, texto) for e in esperado)} | (
            {"inventos": corregir({**pregunta, "tipo": "_"}, texto, conocidos)["inventos"]} if conocidos else {})
    if modo == "valor":
        objetivo = float(esperado[0])
        acierto = any(abs(n - objetivo) < 1e-9 * max(1.0, abs(objetivo)) for n in _numeros(texto)) or esperado[0] in texto
        encontrados = esperado if acierto else []
    elif modo == "ruta":
        ruta = esperado[0]
        encontrados = esperado if (ruta in texto or re.search(r"(?<![\w])" + re.escape(os.path.basename(ruta)) + r"(?![\w])", texto)) else []
    elif modo == "endpoints":
        encontrados = []
        for e in esperado:
            ruta = e.split(" ", 1)[-1]
            base = ruta.split("*")[0].rstrip("/")
            if base and base in texto:
                encontrados.append(e)
    elif modo == "todos":
        simbolo, ruta = esperado
        encontrados = [x for x, ok in ((simbolo, _aparece(simbolo, texto)),
                                       (ruta, ruta in texto or os.path.basename(ruta) in texto)) if ok]
    else:
        encontrados = [e for e in esperado if _aparece(e, texto)]
    inventos = []
    if conocidos is not None:
        for citado in set(_CITADO.findall(texto)):
            # Cada parte de un nombre con puntos tiene que existir (req.incluir_datos, btn.onclick)
            partes = [x for x in citado.split(".") if x]
            if len(citado) > 3 and any(x not in conocidos for x in partes) \
                    and ("_" in citado or re.search(r"[a-z][A-Z]", citado)):
                inventos.append(citado)
    return {"puntaje": round(len(encontrados) / max(1, len(esperado)), 3), "encontrados": encontrados,
            "faltan": [e for e in esperado if e not in encontrados], "inventos": sorted(inventos)}


# ======================================================================
# Correr una variante
# ======================================================================

def correr(banco, variante: str, preguntar: Callable[[str], Tuple[str, Dict[str, Any]]],
           tipos: Optional[List[str]] = None, por_tipo: Optional[int] = None,
           progreso: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """ `preguntar(texto) -> (respuesta, {"tokens": …})`. Guarda cada resultado y devuelve el resumen. """
    preguntas = cargar(banco) or generar(banco)
    if tipos:
        preguntas = [p for p in preguntas if p["tipo"] in tipos]
    if por_tipo:
        vistos: Dict[str, int] = defaultdict(int)
        elegidas = []
        for p in preguntas:
            if vistos[p["tipo"]] < por_tipo:
                elegidas.append(p)
                vistos[p["tipo"]] += 1
        preguntas = elegidas
    conocidos = nombres_conocidos(banco)
    grafo = grafo_corto(banco)
    corrida = f"{variante}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    resultados = []
    for n, p in enumerate(preguntas):
        t0 = time.time()
        try:
            respuesta, meta = preguntar(p["pregunta"])
        except Exception as e:
            respuesta, meta = f"[error: {e}]", {}
        segundos = round(time.time() - t0, 1)
        nota = corregir(p, respuesta, conocidos, grafo)
        resultados.append({**nota, "id": p["id"], "tipo": p["tipo"], "segundos": segundos})
        with banco.conectar() as c:
            _crear_tablas(c)
            c.execute("INSERT INTO examen_resultados VALUES (?,?,?,?,?,?,?,?,?)",
                      (corrida, p["id"], variante, nota["puntaje"], json.dumps(nota["inventos"]), segundos,
                       int(meta.get("tokens") or 0), respuesta, datetime.now().isoformat(timespec="seconds")))
        if progreso:
            progreso({"n": n + 1, "total": len(preguntas), "tipo": p["tipo"], "puntaje": nota["puntaje"]})
    return resumir(resultados, corrida)


def resumir(resultados: List[Dict[str, Any]], corrida: str = "") -> Dict[str, Any]:
    por_tipo: Dict[str, List[float]] = defaultdict(list)
    for r in resultados:
        por_tipo[r["tipo"]].append(r["puntaje"])
    total = [r["puntaje"] for r in resultados]
    return {"corrida": corrida, "preguntas": len(resultados),
            "puntaje": round(sum(total) / max(1, len(total)), 3),
            "por_tipo": {t: round(sum(v) / len(v), 3) for t, v in sorted(por_tipo.items())},
            "con_inventos": sum(1 for r in resultados if r["inventos"]),
            "segundos_media": round(sum(r["segundos"] for r in resultados) / max(1, len(resultados)), 1)}


def recorregir(banco, variante: str) -> Dict[str, Any]:
    """ Vuelve a corregir la última corrida de una variante con el corrector actual """
    preguntas = {p["id"]: p for p in cargar(banco)}
    conocidos, grafo = nombres_conocidos(banco), grafo_corto(banco)
    with banco.conectar() as c:
        ultima = c.execute("SELECT corrida FROM examen_resultados WHERE variante = ? ORDER BY rowid DESC LIMIT 1", (variante,)).fetchone()
        if not ultima:
            return {}
        filas = [dict(f) for f in c.execute("SELECT id, respuesta, segundos FROM examen_resultados WHERE corrida = ?", (ultima["corrida"],))]
    resultados = []
    for f in filas:
        p = preguntas.get(f["id"])
        if p:
            resultados.append({**corregir(p, f["respuesta"], conocidos, grafo), "id": f["id"], "tipo": p["tipo"], "segundos": f["segundos"]})
    return resumir(resultados, ultima["corrida"])
