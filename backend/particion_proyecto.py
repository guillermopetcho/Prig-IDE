"""
Partición del proyecto en unidades de lectura (etapa 1 de docs/arquitectura-unificada.md).

El motor MoE rinde a ≤32K de contexto (24 expertos calientes, ~40 tok/s). Un proyecto grande se lee
entonces por unidades de ≤16K tokens de código, más la tarjeta global y el contexto de la unidad. La
calidad de todo lo que viene después depende de cómo se corta y en qué orden se lee:

  · Piezas: cada archivo de producción es una pieza; los que no caben se cortan por símbolos de
    primer nivel (y una clase gigante, por métodos), nunca por líneas a ciegas.
  · Unidades: las piezas se agrupan por cuánto se llaman entre sí (grafo de llamadas resuelto e
    imports), con un tope de tokens. Agrupamiento aglomerativo con capacidad: sin dependencias.
  · Orden: primero lo que otros usan (dependencias antes que quien las usa), y a igualdad lo estable
    (menos commits en git) antes que lo que se edita seguido. La memoria del SSM olvida con la
    distancia y un cambio invalida todo lo que se lee después: así se protege lo que más importa.

Sin modelo: se recalcula en segundos. Se guarda en el banco (tabla `unidades`).
"""

import json
import math
import os
import re
import subprocess
import time
import zlib
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

PRESUPUESTO_UNIDAD = 16000          # tokens de código por unidad
LENGUAJES_CODIGO = ("python", "js", "c", "go", "rust", "java")


def es_produccion(ruta: str, lenguaje: str) -> bool:
    import banco_proyecto as bp
    return lenguaje in LENGUAJES_CODIGO and not bp._ES_TEST.search(ruta)


# ======================================================================
# Piezas
# ======================================================================

def _tokens_de(lineas: List[str], ini: int, fin: int) -> int:
    import banco_proyecto as bp
    return bp.estimar_tokens("\n".join(lineas[ini - 1:fin]))


def piezas_de_archivo(ruta: str, lineas: List[str], simbolos: List[Dict[str, Any]], tokens: int,
                      tope: int) -> List[Dict[str, Any]]:
    """ El archivo entero si cabe; si no, grupos consecutivos de símbolos de primer nivel (el código
    suelto entre medias va con el símbolo que sigue). Un símbolo que solo no cabe se corta por sus
    métodos, y un método que no cabe, por líneas. """
    total = len(lineas)
    if tokens <= tope or total == 0:
        return [{"ruta": ruta, "ini": 1, "fin": max(1, total), "tokens": tokens,
                 "simbolos": [s["nombre"] for s in simbolos if not s["padre"]]}]
    primer = sorted((s for s in simbolos if not s["padre"]), key=lambda s: s["ini"])
    # Tramos: [inicio del tramo, fin del símbolo] cubriendo todo el archivo
    tramos: List[Tuple[int, int, List[str], Optional[Dict[str, Any]]]] = []
    cursor = 1
    for s in primer:
        if s["fin"] < cursor:
            continue
        tramos.append((cursor, s["fin"], [s["nombre"]], s))
        cursor = s["fin"] + 1
    if cursor <= total:
        tramos.append((cursor, total, [], None))
    if not tramos:
        tramos = [(1, total, [], None)]

    # Los tramos que no caben solos se subdividen
    finos: List[Tuple[int, int, List[str]]] = []
    for ini, fin, nombres, s in tramos:
        if _tokens_de(lineas, ini, fin) <= tope:
            finos.append((ini, fin, nombres))
            continue
        hijos = sorted((h for h in simbolos if s is not None and h["padre"] == s["nombre"]), key=lambda h: h["ini"])
        cur = ini
        for h in hijos:
            if h["fin"] < cur:
                continue
            finos.append((cur, h["fin"], [h["nombre"]]))
            cur = h["fin"] + 1
        if cur <= fin:
            finos.append((cur, fin, nombres if not hijos else []))
    # Lo que aún no cabe (un método gigante, un script sin símbolos) va por líneas
    cortados: List[Tuple[int, int, List[str]]] = []
    for ini, fin, nombres in finos:
        if _tokens_de(lineas, ini, fin) <= tope:
            cortados.append((ini, fin, nombres))
            continue
        # Línea a línea hasta el tope (con líneas de largo muy desigual, un promedio se pasa)
        a, acumulado, primero = ini, 0, True
        for n in range(ini, fin + 1):
            t = _tokens_de(lineas, n, n)
            if acumulado + t > tope and n > a:
                cortados.append((a, n - 1, nombres if primero else []))
                a, acumulado, primero = n, 0, False
            acumulado += t
        cortados.append((a, fin, nombres if primero else []))
    # Agrupar tramos consecutivos hasta el tope (la cercanía en el archivo es cohesión)
    piezas: List[Dict[str, Any]] = []
    actual: Optional[Dict[str, Any]] = None
    for ini, fin, nombres in cortados:
        t = _tokens_de(lineas, ini, fin)
        if actual is not None and actual["tokens"] + t <= tope:
            actual["fin"] = fin
            actual["tokens"] += t
            actual["simbolos"] += nombres
        else:
            if actual is not None:
                piezas.append(actual)
            actual = {"ruta": ruta, "ini": ini, "fin": fin, "tokens": t, "simbolos": list(nombres)}
    if actual is not None:
        piezas.append(actual)
    return piezas


# ======================================================================
# Pesos entre piezas
# ======================================================================

def _pieza_de(indice: Dict[str, List[Tuple[int, int, int]]], ruta: str, linea: int) -> Optional[int]:
    for ini, fin, i in indice.get(ruta, []):
        if ini <= linea <= fin:
            return i
    lista = indice.get(ruta)
    return lista[0][2] if lista else None


def pesos_entre_piezas(c, piezas: List[Dict[str, Any]]) -> Dict[Tuple[int, int], float]:
    """ Peso de cada par de piezas: llamadas resueltas (1 cada una, en ambos sentidos), imports (2) y
    piezas contiguas del mismo archivo (3, para no separar sin necesidad lo que se lee seguido) """
    indice: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)
    for i, p in enumerate(piezas):
        indice[p["ruta"]].append((p["ini"], p["fin"], i))
    inicio_simbolo = {(f["ruta"], f["nombre"]): f["ini"] for f in c.execute("SELECT ruta, nombre, ini FROM simbolos")}
    pesos: Dict[Tuple[int, int], float] = defaultdict(float)

    def sumar(a: Optional[int], b: Optional[int], w: float):
        if a is None or b is None or a == b:
            return
        pesos[(min(a, b), max(a, b))] += w
    for f in c.execute("SELECT ruta, desde, a_ruta, a_nombre, linea FROM llamadas"):
        a = _pieza_de(indice, f["ruta"], f["linea"])
        linea_destino = inicio_simbolo.get((f["a_ruta"], f["a_nombre"]))
        b = _pieza_de(indice, f["a_ruta"], linea_destino) if linea_destino else None
        sumar(a, b, 1.0)
    for f in c.execute("SELECT ruta, destino FROM importaciones"):
        if f["ruta"] in indice and f["destino"] in indice:
            sumar(indice[f["ruta"]][0][2], indice[f["destino"]][0][2], 2.0)
    for lista in indice.values():
        orden = sorted(lista)
        for (_, _, a), (_, _, b) in zip(orden, orden[1:]):
            sumar(a, b, 3.0)
    return dict(pesos)


def dirigidas_entre_piezas(c, piezas: List[Dict[str, Any]]) -> Dict[Tuple[int, int], float]:
    """ Llamadas con sentido: (quien llama, a quien) → cantidad. Para ordenar la lectura. """
    indice: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)
    for i, p in enumerate(piezas):
        indice[p["ruta"]].append((p["ini"], p["fin"], i))
    inicio_simbolo = {(f["ruta"], f["nombre"]): f["ini"] for f in c.execute("SELECT ruta, nombre, ini FROM simbolos")}
    dirigidas: Dict[Tuple[int, int], float] = defaultdict(float)
    for f in c.execute("SELECT ruta, a_ruta, a_nombre, linea FROM llamadas"):
        a = _pieza_de(indice, f["ruta"], f["linea"])
        linea_destino = inicio_simbolo.get((f["a_ruta"], f["a_nombre"]))
        b = _pieza_de(indice, f["a_ruta"], linea_destino) if linea_destino else None
        if a is not None and b is not None and a != b:
            dirigidas[(a, b)] += 1.0
    return dict(dirigidas)


# ======================================================================
# Agrupamiento con capacidad
# ======================================================================

def _carpeta(ruta: str, niveles: int = 2) -> str:
    partes = ruta.split("/")[:-1]
    return "/".join(partes[:niveles])


def agrupar(piezas: List[Dict[str, Any]], pesos: Dict[Tuple[int, int], float], tope: int,
            normalizar: str = "raiz") -> List[List[int]]:
    """ Aglomerativo: se une el par de grupos más conectado (peso normalizado por tamaño) mientras
    quepa en el tope. Después, lo que quedó suelto se junta por carpeta. """
    grupos: Dict[int, Dict[str, Any]] = {i: {"piezas": [i], "tokens": p["tokens"], "carpetas": {_carpeta(p["ruta"])}}
                                         for i, p in enumerate(piezas)}
    vecinos: Dict[int, Dict[int, float]] = defaultdict(dict)
    for (a, b), w in pesos.items():
        vecinos[a][b] = vecinos[a].get(b, 0.0) + w
        vecinos[b][a] = vecinos[b].get(a, 0.0) + w

    def puntaje(a: int, b: int) -> float:
        w = vecinos[a].get(b, 0.0)
        if w <= 0:
            return 0.0
        ga, gb = grupos[a], grupos[b]
        bono = 1.3 if ga["carpetas"] & gb["carpetas"] else 1.0
        if normalizar == "suma":
            return bono * w / max(1, ga["tokens"] + gb["tokens"])
        if normalizar == "nada":
            return bono * w
        return bono * w / math.sqrt(max(1, ga["tokens"]) * max(1, gb["tokens"]) / 1e6)

    def unir(a: int, b: int):
        ga, gb = grupos[a], grupos.pop(b)
        ga["piezas"] += gb["piezas"]
        ga["tokens"] += gb["tokens"]
        ga["carpetas"] |= gb["carpetas"]
        for x, w in vecinos.pop(b, {}).items():
            vecinos[x].pop(b, None)
            if x != a:
                vecinos[a][x] = vecinos[a].get(x, 0.0) + w
                vecinos[x][a] = vecinos[x].get(a, 0.0) + w
        vecinos[a].pop(a, None)

    while True:
        mejor, par = 0.0, None
        for a in list(grupos):
            for b, _ in vecinos[a].items():
                if b <= a or b not in grupos or grupos[a]["tokens"] + grupos[b]["tokens"] > tope:
                    continue
                p = puntaje(a, b)
                if p > mejor:
                    mejor, par = p, (a, b)
        if par is None:
            break
        unir(*par)
    # Lo suelto (sin llamadas que lo unan): por carpeta, del más chico al más grande
    cambio = True
    while cambio:
        cambio = False
        chicos = sorted(grupos, key=lambda g: grupos[g]["tokens"])
        for a in chicos:
            if a not in grupos or grupos[a]["tokens"] > tope * 0.5:
                continue
            candidatos = [b for b in grupos if b != a and grupos[b]["carpetas"] & grupos[a]["carpetas"]
                          and grupos[a]["tokens"] + grupos[b]["tokens"] <= tope]
            if candidatos:
                b = min(candidatos, key=lambda b: grupos[b]["tokens"])
                unir(min(a, b), max(a, b))
                cambio = True
    # Unidades muy chicas sin relación con nadie: se juntan aunque sean de carpetas distintas (menos
    # lecturas y menos estados que guardar)
    cambio = True
    while cambio:
        cambio = False
        chicos = sorted(grupos, key=lambda g: grupos[g]["tokens"])
        for a in chicos:
            if a not in grupos or grupos[a]["tokens"] > tope * 0.25:
                continue
            candidatos = [b for b in grupos if b != a and grupos[a]["tokens"] + grupos[b]["tokens"] <= tope]
            if candidatos:
                b = min(candidatos, key=lambda b: grupos[b]["tokens"])
                unir(min(a, b), max(a, b))
                cambio = True
    return [g["piezas"] for g in grupos.values()]


# ======================================================================
# Orden de lectura
# ======================================================================

def cambios_git(raiz: str, commits: int = 300) -> Dict[str, int]:
    """ Cuántos de los últimos commits tocaron cada archivo (lo estable se lee primero) """
    try:
        r = subprocess.run(["git", "-C", raiz, "log", f"-{commits}", "--format=", "--name-only"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    cuenta: Dict[str, int] = defaultdict(int)
    for linea in r.stdout.splitlines():
        if linea.strip():
            cuenta[linea.strip()] += 1
    return dict(cuenta)


def componentes_fuertes(n: int, aristas: Dict[int, Set[int]]) -> List[List[int]]:
    """ Tarjan iterativo: grupos de unidades que se llaman en ciclo """
    indice, bajo, en_pila, pila, salida = {}, {}, set(), [], []
    contador = [0]
    for inicio in range(n):
        if inicio in indice:
            continue
        trabajo = [(inicio, iter(sorted(aristas.get(inicio, ()))))]
        indice[inicio] = bajo[inicio] = contador[0]
        contador[0] += 1
        pila.append(inicio)
        en_pila.add(inicio)
        while trabajo:
            v, hijos = trabajo[-1]
            avanzo = False
            for w in hijos:
                if w not in indice:
                    indice[w] = bajo[w] = contador[0]
                    contador[0] += 1
                    pila.append(w)
                    en_pila.add(w)
                    trabajo.append((w, iter(sorted(aristas.get(w, ())))))
                    avanzo = True
                    break
                if w in en_pila:
                    bajo[v] = min(bajo[v], indice[w])
            if avanzo:
                continue
            trabajo.pop()
            if trabajo:
                bajo[trabajo[-1][0]] = min(bajo[trabajo[-1][0]], bajo[v])
            if bajo[v] == indice[v]:
                comp = []
                while True:
                    w = pila.pop()
                    en_pila.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                salida.append(comp)
    return salida


def ordenar(unidades: List[List[int]], piezas: List[Dict[str, Any]], dirigidas: Dict[Tuple[int, int], float],
            churn: Dict[str, int]) -> Tuple[List[int], Dict[int, List[int]]]:
    """ Orden de las unidades (dependencias primero; a igualdad, lo estable primero) y orden de las
    piezas dentro de cada unidad (lo llamado antes que quien llama) """
    de_pieza = {p: u for u, lista in enumerate(unidades) for p in lista}
    usa: Dict[int, Set[int]] = defaultdict(set)           # unidad → unidades que usa
    for (a, b), _ in dirigidas.items():
        ua, ub = de_pieza.get(a), de_pieza.get(b)
        if ua is not None and ub is not None and ua != ub:
            usa[ua].add(ub)
    inestable = {u: max((churn.get(piezas[p]["ruta"], 0) for p in lista), default=0) for u, lista in enumerate(unidades)}
    comps = componentes_fuertes(len(unidades), usa)
    de_comp = {u: i for i, comp in enumerate(comps) for u in comp}
    depende: Dict[int, Set[int]] = defaultdict(set)
    for u, vs in usa.items():
        for v in vs:
            if de_comp[u] != de_comp[v]:
                depende[de_comp[u]].add(de_comp[v])
    # Kahn: se lee una componente cuando ya se leyó todo lo que usa
    pendientes = {i: len(depende[i]) for i in range(len(comps))}
    usada_por: Dict[int, Set[int]] = defaultdict(set)
    for i, ds in depende.items():
        for d in ds:
            usada_por[d].add(i)
    clave = lambda i: (min(inestable[u] for u in comps[i]), min(piezas[unidades[u][0]]["ruta"] for u in comps[i]))
    listas = sorted((i for i, n in pendientes.items() if n == 0), key=clave)
    orden_comps = []
    while listas:
        i = listas.pop(0)
        orden_comps.append(i)
        for j in usada_por[i]:
            pendientes[j] -= 1
            if pendientes[j] == 0:
                listas.append(j)
        listas.sort(key=clave)
    orden_unidades = [u for i in orden_comps for u in sorted(comps[i], key=lambda u: (inestable[u], piezas[unidades[u][0]]["ruta"]))]
    # Dentro de la unidad: primero lo que otras piezas de la unidad llaman
    internas: Dict[int, List[int]] = {}
    for u, lista in enumerate(unidades):
        conjunto = set(lista)
        llamada = defaultdict(float)
        for (a, b), w in dirigidas.items():
            if a in conjunto and b in conjunto:
                llamada[b] += w
                llamada[a] -= w
        internas[u] = sorted(lista, key=lambda p: (-llamada[p], piezas[p]["ruta"], piezas[p]["ini"]))
    return orden_unidades, internas


# ======================================================================
# Partición completa
# ======================================================================

def particionar(banco, tope: int = PRESUPUESTO_UNIDAD, guardar: bool = True) -> Dict[str, Any]:
    t0 = time.time()
    with banco.conectar() as c:
        archivos = [dict(f) for f in c.execute("SELECT ruta, lenguaje, tokens, contenido FROM archivos ORDER BY ruta")]
        simbolos_por_ruta: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for f in c.execute("SELECT ruta, nombre, padre, ini, fin FROM simbolos"):
            simbolos_por_ruta[f["ruta"]].append(dict(f))
        piezas: List[Dict[str, Any]] = []
        for a in archivos:
            if not es_produccion(a["ruta"], a["lenguaje"]):
                continue
            lineas = zlib.decompress(a["contenido"]).decode("utf-8", "replace").splitlines()
            piezas += piezas_de_archivo(a["ruta"], lineas, simbolos_por_ruta[a["ruta"]], a["tokens"], tope)
        pesos = pesos_entre_piezas(c, piezas)
        dirigidas = dirigidas_entre_piezas(c, piezas)
    grupos = agrupar(piezas, pesos, tope)
    churn = cambios_git(banco.raiz)
    orden, internas = ordenar(grupos, piezas, dirigidas, churn)

    de_pieza = {p: u for u, lista in enumerate(grupos) for p in lista}
    total_peso = sum(pesos.values()) or 1.0
    cortado = sum(w for (a, b), w in pesos.items() if de_pieza[a] != de_pieza[b])
    unidades = []
    for pos, u in enumerate(orden):
        lista = internas[u]
        rutas = sorted({piezas[p]["ruta"] for p in lista})
        # Vecinas: con qué otras unidades se llama más, y qué símbolos cruzan la frontera
        cruce: Dict[int, float] = defaultdict(float)
        for (a, b), w in pesos.items():
            if de_pieza[a] == u and de_pieza[b] != u:
                cruce[de_pieza[b]] += w
            elif de_pieza[b] == u and de_pieza[a] != u:
                cruce[de_pieza[a]] += w
        unidades.append({
            "id": u, "orden": pos, "tokens": sum(piezas[p]["tokens"] for p in lista),
            "nombre": nombre_unidad(rutas),
            "rutas": rutas,
            "piezas": [{k: piezas[p][k] for k in ("ruta", "ini", "fin", "tokens")} for p in lista],
            "simbolos": [s for p in lista for s in piezas[p]["simbolos"]],
            "vecinas": [v for v, _ in sorted(cruce.items(), key=lambda x: -x[1])[:6]],
            "cambios_git": max((churn.get(r, 0) for r in rutas), default=0),
        })
    # Las vecinas, por posición de lectura (el id interno no se guarda)
    posicion = {x["id"]: x["orden"] for x in unidades}
    for x in unidades:
        x["vecinas"] = [posicion[v] for v in x["vecinas"]]
    # Cobertura: qué parte del acoplamiento que cruza la frontera de cada unidad queda dentro de
    # sus vecinas (cuyas interfaces irán en su contexto). Medido en Prig: 0,94 de media.
    cruce_total: Dict[int, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for (a, b), w in pesos.items():
        if de_pieza[a] != de_pieza[b]:
            cruce_total[de_pieza[a]][de_pieza[b]] += w
            cruce_total[de_pieza[b]][de_pieza[a]] += w
    coberturas = [sum(sorted(v.values(), reverse=True)[:6]) / sum(v.values()) for v in cruce_total.values() if v]
    resumen = {
        "unidades": len(unidades), "piezas": len(piezas),
        "tokens": sum(x["tokens"] for x in unidades),
        "tokens_max": max((x["tokens"] for x in unidades), default=0),
        "tokens_media": round(sum(x["tokens"] for x in unidades) / max(1, len(unidades))),
        "archivos_partidos": sum(1 for r, n in _cuenta(piezas).items() if n > 1),
        "peso_cortado": round(cortado / total_peso, 3),
        "cobertura_vecinas": round(sum(coberturas) / len(coberturas), 3) if coberturas else 1.0,
        "cobertura_vecinas_min": round(min(coberturas), 3) if coberturas else 1.0,
        "tope": tope, "segundos": round(time.time() - t0, 2),
    }
    if guardar:
        banco.guardar_particion(unidades, resumen)
    return {"resumen": resumen, "unidades": unidades}


def _cuenta(piezas: List[Dict[str, Any]]) -> Dict[str, int]:
    cuenta: Dict[str, int] = defaultdict(int)
    for p in piezas:
        cuenta[p["ruta"]] += 1
    return cuenta


def nombre_unidad(rutas: List[str]) -> str:
    """ Carpeta común + los archivos principales: «backend/recursos: frio, termico» """
    if not rutas:
        return "(vacía)"
    comun = os.path.commonpath(rutas) if len(rutas) > 1 else os.path.dirname(rutas[0])
    nombres = [os.path.basename(r).rsplit(".", 1)[0] for r in rutas]
    visibles = ", ".join(nombres[:4]) + (f" +{len(nombres) - 4}" if len(nombres) > 4 else "")
    return f"{comun or '.'}: {visibles}"
