"""
Avance del alumno: un solo sitio donde se juntan todas las actividades.

Hasta ahora cada parte guardaba lo suyo y no se hablaban: los desafíos en su almacén,
los bloques en las rutas de Aprendizaje Guiado y los intentos de código en la telemetría.
Aquí se cruzan para responder a tres preguntas:

    ¿Qué he hecho?      historial completo de desafíos, con su origen y su resultado
    ¿Qué domino?        por concepto, a partir de lo que se resolvió ejecutando pruebas
    ¿Qué sigue?         conceptos flojos, desafíos a medias y bloques del plan pendientes

Dominio por concepto (0 a 100), pensado para ser explicable, no para parecer preciso:

    base       resueltos / vistos
    pistas     −8 puntos por cada pista usada de media
    rendirse   los desafíos vistos con solución cuentan como no resueltos
    olvido     −1 punto por cada semana desde la última vez, hasta un máximo de 20

Solo cuenta lo comprobado ejecutando pruebas: un desafío sin comprobación automática
(Project Euler) suma actividad, pero no dominio.
"""

import json
import os
import re
import threading
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from desafios.almacen import carpeta_base

MAX_HISTORIAL = 500


def _clave(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def _fecha(valor: Optional[str]) -> Optional[date]:
    try:
        return datetime.fromisoformat(valor).date() if valor else None
    except (TypeError, ValueError):
        return None


def _dias_desde(valor: Optional[str]) -> Optional[int]:
    f = _fecha(valor)
    return (date.today() - f).days if f else None


# ===========================================================================
# Historial de desafíos
# ===========================================================================

def historial(almacen, estado: Optional[str] = None, concepto: Optional[str] = None,
              fuente: Optional[str] = None, limite: int = 200) -> List[Dict[str, Any]]:
    """ Todos los desafíos, del más reciente al más antiguo, con lo que hizo el alumno """
    filas = []
    for d in almacen.lista():
        p = d.get("progreso") or {}
        origen = d.get("origen") or {}
        fila = {
            "id": d["id"], "titulo": d.get("titulo"), "nivel": d.get("nivel"),
            "conceptos": d.get("conceptos") or [], "estado": p.get("estado", "nuevo"),
            "verificable": d.get("verificable", True),
            "fuente": origen.get("tipo"), "fuente_nombre": origen.get("nombre"), "url": origen.get("url"),
            "ruta_id": origen.get("ruta_id"), "bloque_id": origen.get("bloque_id"), "bloque": origen.get("bloque"),
            "modelo": origen.get("modelo"), "motor": origen.get("motor"),
            "intentos": p.get("intentos", 0), "pistas": p.get("pistas", 0), "pasos_razonamiento": p.get("pasos_vistos", 0),
            "plan_escrito": bool((p.get("plan") or "").strip()),
            "mejor": p.get("mejor") or {"pasados": 0, "total": 0},
            "segundos": p.get("segundos_hasta_resolver"),
            "creado": d.get("creado"), "actualizado": d.get("actualizado"),
            "resuelto": p.get("resuelto"), "rendido": p.get("rendido"),
        }
        if estado and fila["estado"] != estado:
            continue
        if fuente and fila["fuente"] != fuente:
            continue
        if concepto and _clave(concepto) not in [_clave(c) for c in fila["conceptos"]] + [_clave(fila["titulo"])]:
            continue
        filas.append(fila)
    return filas[:max(1, min(limite, MAX_HISTORIAL))]


def _dominio(vistos: int, resueltos: int, pistas: int, dias: Optional[int]) -> int:
    if not vistos:
        return 0
    valor = 100 * resueltos / vistos
    valor -= 8 * (pistas / vistos)
    if dias is not None:
        valor -= min(20, dias // 7)
    return int(max(0, min(100, round(valor))))


def conceptos(filas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grupos: Dict[str, Dict[str, Any]] = {}
    for f in filas:
        if not f["verificable"]:
            continue                       # sin pruebas no se puede afirmar que se domine
        for c in (f["conceptos"] or [f["titulo"] or "general"])[:4]:
            g = grupos.setdefault(_clave(c), {"concepto": c, "vistos": 0, "resueltos": 0, "rendidos": 0,
                                              "intentos": 0, "pistas": 0, "ultima": None, "desafios": []})
            g["vistos"] += 1
            g["resueltos"] += f["estado"] == "resuelto"
            g["rendidos"] += f["estado"] == "rendido"
            g["intentos"] += f["intentos"]
            g["pistas"] += f["pistas"]
            g["desafios"].append(f["id"])
            if (f["actualizado"] or "") > (g["ultima"] or ""):
                g["ultima"] = f["actualizado"]
    salida = []
    for g in grupos.values():
        g["dominio"] = _dominio(g["vistos"], g["resueltos"], g["pistas"], _dias_desde(g["ultima"]))
        g["desafios"] = g["desafios"][:20]
        salida.append(g)
    return sorted(salida, key=lambda g: (g["dominio"], -g["vistos"]))


def actividad(filas: List[Dict[str, Any]], almacen, telemetria=None, dias: int = 120) -> Dict[str, int]:
    """ Cuántas acciones de aprendizaje hubo cada día (para el mapa de calor) """
    cuenta: Dict[str, int] = defaultdict(int)
    desde = (date.today() - timedelta(days=dias)).isoformat()
    for f in filas:
        try:
            d = almacen.obtener(f["id"])
        except Exception:
            continue
        for h in (d.get("progreso") or {}).get("historial") or []:
            dia = str(h.get("cuando", ""))[:10]
            if dia >= desde:
                cuenta[dia] += 1
        creado = str(d.get("creado") or "")[:10]
        if creado >= desde:
            cuenta[creado] += 1
    if telemetria is not None:
        try:
            with telemetria._connect() as conn:
                for fila in conn.execute("SELECT created_at FROM exercise_events WHERE event_type='submission' AND created_at >= ?;",
                                         (desde,)).fetchall():
                    cuenta[str(fila["created_at"])[:10]] += 1
        except Exception:
            pass
    return dict(sorted(cuenta.items()))


def racha(dias_activos: Dict[str, int]) -> Dict[str, int]:
    """ Días seguidos con actividad, contando hasta hoy o hasta ayer """
    fechas = {d for d, n in dias_activos.items() if n}
    hoy = date.today()
    actual = 0
    if hoy.isoformat() in fechas or (hoy - timedelta(days=1)).isoformat() in fechas:
        cursor = hoy if hoy.isoformat() in fechas else hoy - timedelta(days=1)
        while cursor.isoformat() in fechas:
            actual += 1
            cursor -= timedelta(days=1)
    mejor, seguidos = 0, 0
    anterior = None
    for d in sorted(fechas):
        f = date.fromisoformat(d)
        seguidos = seguidos + 1 if anterior and (f - anterior).days == 1 else 1
        mejor = max(mejor, seguidos)
        anterior = f
    return {"actual": actual, "mejor": mejor, "dias_activos": len(fechas)}


# ===========================================================================
# Plan de estudios y demás actividades
# ===========================================================================

def rutas(filas: List[Dict[str, Any]], guided) -> List[Dict[str, Any]]:
    """ Cada ruta con sus bloques y los desafíos que salieron de cada bloque """
    por_bloque: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in filas:
        if f.get("bloque_id"):
            por_bloque[f"{f['ruta_id']}:{f['bloque_id']}"].append(f)
    salida = []
    for resumen_ruta in guided.list_paths():
        ruta = guided.get(resumen_ruta["id"])
        if not ruta:
            continue
        hechos = set(ruta.completed_blocks or [])
        bloques = []
        for b in ruta.blocks:
            desafios = por_bloque.get(f"{ruta.id}:{b.block_id}", [])
            bloques.append({
                "id": b.block_id, "titulo": b.title, "temas": list(b.topics or []),
                "completado": b.block_id in hechos,
                "desafios": len(desafios), "resueltos": sum(1 for d in desafios if d["estado"] == "resuelto"),
            })
        salida.append({
            "id": ruta.id, "meta": ruta.goal, "nivel": ruta.level,
            "bloques": bloques, "total": len(bloques), "completados": len(hechos & {b.block_id for b in ruta.blocks}),
            "con_desafio": sum(1 for b in bloques if b["desafios"]),
        })
    return salida


def siguientes(filas: List[Dict[str, Any]], lista_conceptos: List[Dict[str, Any]],
               lista_rutas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ Qué hacer ahora, sin pedírselo a ningún modelo """
    pasos = []
    vistos = set()
    for f in filas:
        if f["estado"] == "en_curso" and _clave(f["titulo"] or "") not in vistos:
            vistos.add(_clave(f["titulo"] or ""))
            pasos.append({"tipo": "retomar", "texto": f"Sigue «{f['titulo']}», lo dejaste a medias"
                                                     + (f" ({f['mejor']['pasados']}/{f['mejor']['total']} pruebas)" if f["mejor"]["total"] else ""),
                          "desafio_id": f["id"]})
        if len(pasos) >= 2:
            break
    for c in lista_conceptos:
        if c["dominio"] < 60 and (c["rendidos"] or c["pistas"] or c["vistos"] > c["resueltos"]):
            pasos.append({"tipo": "practicar", "texto": f"Refuerza «{c['concepto']}»: dominio {c['dominio']}/100"
                                                       + (f", {c['rendidos']} visto con solución" if c["rendidos"] else ""),
                          "tema": c["concepto"]})
        if len(pasos) >= 5:
            break
    for r in lista_rutas:
        pendientes = [b for b in r["bloques"] if not b["completado"]]
        if pendientes:
            b = pendientes[0]
            pasos.append({"tipo": "bloque", "texto": f"Bloque «{b['titulo']}» de «{r['meta']}»"
                                                    + (" (sin desafíos todavía)" if not b["desafios"] else ""),
                          "ruta_id": r["id"], "bloque_id": b["id"], "tema": ", ".join([b["titulo"]] + b["temas"][:3])})
        if len(pasos) >= 7:
            break
    return pasos[:7]


def resumen(almacen, guided=None, telemetria=None, dataset=None, dias: int = 120, kaggle=None) -> Dict[str, Any]:
    filas = historial(almacen, limite=MAX_HISTORIAL)
    lista_conceptos = conceptos(filas)
    dias_activos = actividad(filas, almacen, telemetria, dias)
    lista_rutas = rutas(filas, guided) if guided is not None else []

    resueltos = [f for f in filas if f["estado"] == "resuelto"]
    tiempos = [f["segundos"] for f in resueltos if f.get("segundos")]
    por_estado = defaultdict(int)
    por_fuente = defaultdict(int)
    for f in filas:
        por_estado[f["estado"]] += 1
        por_fuente[f["fuente"] or "modelo"] += 1

    actividades = [{
        "id": "desafios", "nombre": "Desafíos", "hechos": len(resueltos), "total": len(filas),
        "detalle": f"{por_estado['en_curso']} en curso · {por_estado['rendido']} vistos con solución",
    }]
    if lista_rutas:
        actividades.append({
            "id": "plan", "nombre": "Plan de estudios",
            "hechos": sum(r["completados"] for r in lista_rutas), "total": sum(r["total"] for r in lista_rutas),
            "detalle": f"{len(lista_rutas)} ruta(s) · {sum(r['con_desafio'] for r in lista_rutas)} bloques con desafíos",
        })
    if telemetria is not None:
        try:
            m = telemetria.metrics(days=dias)
            if m.get("submissions"):
                actividades.append({"id": "ejercicios", "nombre": "Ejercicios y retos", "hechos": m.get("exercises_attempted", 0),
                                    "total": m.get("exercises_attempted", 0),
                                    "detalle": f"{m['submissions']} entregas · {m.get('solve_rate')}% resueltos"})
        except Exception:
            pass
    lecturas = []
    if kaggle is not None:
        try:
            lecturas = kaggle.resumen_lecturas()
        except Exception:
            lecturas = []
        if lecturas:
            actividades.append({"id": "kaggle", "nombre": "Notebooks de Kaggle",
                                "hechos": sum(l["leidas"] for l in lecturas), "total": sum(l["total"] for l in lecturas),
                                "detalle": f"{len(lecturas)} notebook(s) · {sum(1 for l in lecturas if l['total'] and l['leidas'] >= l['total'])} leídos enteros"})
    if dataset is not None:
        try:
            d = dataset.get_dataset()
            dominados = len(d.mastered_topics or [])
            if dominados:
                actividades.append({"id": "biblioteca", "nombre": "Biblioteca", "hechos": dominados, "total": dominados,
                                    "detalle": f"{dominados} temas marcados como dominados"})
        except Exception:
            pass

    return {
        "desafios": {
            "total": len(filas), "por_estado": dict(por_estado), "por_fuente": dict(por_fuente),
            "resueltos_sin_pistas": sum(1 for f in resueltos if not f["pistas"]),
            "con_razonamiento": sum(1 for f in filas if f["pasos_razonamiento"]),
            "con_plan": sum(1 for f in filas if f["plan_escrito"]),
            "minutos": round(sum(tiempos) / 60) if tiempos else 0,
            "media_intentos": round(sum(f["intentos"] for f in resueltos) / len(resueltos), 1) if resueltos else None,
        },
        "actividades": actividades,
        "conceptos": lista_conceptos,
        "fuertes": [c for c in reversed(lista_conceptos) if c["dominio"] >= 70][:5],
        "flojos": [c for c in lista_conceptos if c["dominio"] < 60][:5],
        "actividad": dias_activos,
        "racha": racha(dias_activos),
        "rutas": lista_rutas,
        "siguientes": siguientes(filas, lista_conceptos, lista_rutas) + [
            {"tipo": "kaggle", "texto": f"Sigue leyendo «{l['titulo']}» ({l['leidas']}/{l['total']} celdas)", "ref": l["ref"], "celda": l.get("ultima_celda")}
            for l in lecturas if l["total"] and l["leidas"] < l["total"]][:2],
        "kaggle": lecturas[:10],
        "ultimos": filas[:8],
        "generado": datetime.now().isoformat(timespec="seconds"),
    }


# ===========================================================================
# Lo que se le cuenta al modelo y su análisis guardado
# ===========================================================================

def contexto_para_modelo(r: Dict[str, Any], filas: List[Dict[str, Any]], maximo: int = 25) -> str:
    """ El avance en texto compacto: solo hechos medidos, sin interpretarlos """
    lineas = [f"Desafíos: {r['desafios']['total']} en total, {r['desafios']['por_estado'].get('resuelto', 0)} resueltos "
              f"({r['desafios']['resueltos_sin_pistas']} sin pistas), {r['desafios']['por_estado'].get('rendido', 0)} vistos con solución, "
              f"{r['desafios']['por_estado'].get('en_curso', 0)} a medias.",
              f"Usó la caja de razonamiento en {r['desafios']['con_razonamiento']} y escribió su plan en {r['desafios']['con_plan']}.",
              f"Racha actual: {r['racha']['actual']} días; mejor racha: {r['racha']['mejor']}; días activos: {r['racha']['dias_activos']}."]
    if r["desafios"]["media_intentos"]:
        lineas.append(f"Media de intentos hasta resolver: {r['desafios']['media_intentos']}.")
    if r["conceptos"]:
        lineas.append("Dominio por concepto (0-100, vistos/resueltos/pistas):")
        for c in r["conceptos"][:15]:
            lineas.append(f"  - {c['concepto']}: {c['dominio']} ({c['vistos']}/{c['resueltos']}/{c['pistas']}"
                          + (f", {c['rendidos']} con solución" if c["rendidos"] else "") + ")")
    for ruta in r["rutas"][:3]:
        pendientes = [b["titulo"] for b in ruta["bloques"] if not b["completado"]][:4]
        lineas.append(f"Ruta «{ruta['meta']}»: {ruta['completados']}/{ruta['total']} bloques; pendientes: {', '.join(pendientes) or 'ninguno'}.")
    for l in (r.get("kaggle") or [])[:5]:
        lineas.append(f"Notebook de Kaggle «{l['titulo']}»: leídas {l['leidas']} de {l['total']} celdas con el profesor.")
    lineas.append("Últimos desafíos:")
    for f in filas[:maximo]:
        lineas.append(f"  - {f['creado'][:10] if f['creado'] else ''} «{f['titulo']}» ({f['nivel']}, {f['fuente']}): {f['estado']}, "
                      f"{f['intentos']} intentos, {f['pistas']} pistas, mejor {f['mejor']['pasados']}/{f['mejor']['total']}"
                      + (f", conceptos: {', '.join(f['conceptos'][:3])}" if f["conceptos"] else ""))
    return "\n".join(lineas)


def ruta_analisis() -> str:
    return os.path.join(carpeta_base(), "analisis.json")


_cerrojo = threading.Lock()


def analisis_guardado() -> Optional[Dict[str, Any]]:
    try:
        with open(ruta_analisis(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def guardar_analisis(texto: str, modelo: str, desafios: int) -> Dict[str, Any]:
    datos = {"texto": texto, "modelo": modelo, "desafios": desafios,
             "fecha": datetime.now().isoformat(timespec="seconds"), "temas": temas_sugeridos(texto)}
    with _cerrojo:
        os.makedirs(carpeta_base(), exist_ok=True)
        tmp = ruta_analisis() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ruta_analisis())
    return datos


def temas_sugeridos(texto: str) -> List[str]:
    """ Los temas que el análisis propone practicar, para poder crear el desafío de un clic """
    m = re.search(r"```json\s*(\{.*?\})\s*```", texto or "", re.S)
    if m:
        try:
            temas = json.loads(m.group(1)).get("temas") or []
            return [str(t)[:80] for t in temas][:6]
        except ValueError:
            pass
    return []


def sin_bloque_json(texto: str) -> str:
    return re.sub(r"```json\s*\{.*?\}\s*```", "", texto or "", flags=re.S).strip()
