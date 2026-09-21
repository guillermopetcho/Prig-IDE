"""
Inicio: la pantalla con la que abre Prig.

Reúne en una sola respuesta lo que el usuario necesita para decidir qué hacer: su perfil
(nombre, objetivo, racha, dominio), lo último que hizo en cualquier parte del programa,
qué le conviene hacer ahora, sus modelos (locales y Gemini), el estado de la máquina,
sus proyectos recientes y lo que tiene a medias en Kaggle.

Cada bloque se calcula por separado: si uno falla (Ollama apagado, sin sensores…) llega
vacío con su error y el resto de la pantalla funciona igual.

El perfil editable (nombre, objetivo, nivel, herramientas favoritas, abrir al inicio) se
guarda en ~/.prig_inicio.json (o PRIG_INICIO_ARCHIVO).
"""

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

NIVELES = ("principiante", "intermedio", "avanzado")
PERFIL_POR_DEFECTO = {"nombre": "", "objetivo": "", "nivel": "principiante", "mostrar_al_abrir": True,
                      "favoritas": ["herr.practica", "herr.kaggle", "herr.github", "herr.guiado"]}


def ruta_perfil() -> str:
    return os.environ.get("PRIG_INICIO_ARCHIVO") or os.path.expanduser("~/.prig_inicio.json")


def perfil() -> Dict[str, Any]:
    try:
        with open(ruta_perfil(), encoding="utf-8") as f:
            datos = json.load(f)
    except (FileNotFoundError, ValueError):
        datos = {}
    return {**PERFIL_POR_DEFECTO, **{k: v for k, v in datos.items() if k in PERFIL_POR_DEFECTO}}


def guardar_perfil(cambios: Dict[str, Any]) -> Dict[str, Any]:
    actual = perfil()
    if "nombre" in cambios:
        actual["nombre"] = re.sub(r"\s+", " ", str(cambios["nombre"] or "")).strip()[:60]
    if "objetivo" in cambios:
        actual["objetivo"] = str(cambios["objetivo"] or "").strip()[:300]
    if cambios.get("nivel") in NIVELES:
        actual["nivel"] = cambios["nivel"]
    if "mostrar_al_abrir" in cambios:
        actual["mostrar_al_abrir"] = bool(cambios["mostrar_al_abrir"])
    if isinstance(cambios.get("favoritas"), list):
        actual["favoritas"] = [str(x)[:60] for x in cambios["favoritas"]][:12]
    ruta = ruta_perfil()
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(actual, f, ensure_ascii=False, indent=1)
    os.replace(ruta + ".tmp", ruta)
    return actual


# ===========================================================================
# Actividad reciente: una línea de tiempo con todo lo que hizo
# ===========================================================================

ESTADOS_DESAFIO = {"resuelto": "Resolviste", "en_curso": "Trabajaste en", "rendido": "Viste la solución de",
                   "nuevo": "Empezaste"}


def _cuando(texto: Optional[str]) -> str:
    return str(texto or "")[:19]


def actividad(progreso_resumen: Optional[Dict[str, Any]], historial: List[Dict[str, Any]],
              lecturas: List[Dict[str, Any]], colecciones: List[Dict[str, Any]], descargas: List[Dict[str, Any]],
              ejercicios: List[Dict[str, Any]], n: int = 14) -> List[Dict[str, Any]]:
    """ [{tipo, icono, texto, detalle, fecha, abrir:{…}}] del más reciente al más antiguo """
    eventos: List[Dict[str, Any]] = []
    for d in historial[:30]:
        verbo = ESTADOS_DESAFIO.get(d.get("estado"), "Trabajaste en")
        mejor = d.get("mejor") or {}
        detalle = []
        if mejor.get("total"):
            detalle.append(f"{mejor.get('pasados', 0)}/{mejor['total']} pruebas")
        if d.get("intentos"):
            detalle.append(f"{d['intentos']} intentos")
        if d.get("conceptos"):
            detalle.append(", ".join(d["conceptos"][:3]))
        eventos.append({"tipo": "desafio", "icono": "fa-chess-knight", "texto": f"{verbo} el desafío «{d.get('titulo')}»",
                        "detalle": " · ".join(detalle), "fecha": _cuando(d.get("actualizado") or d.get("creado")),
                        "estado": d.get("estado"), "abrir": {"desafio": d.get("id")}})
    for l in lecturas[:20]:
        eventos.append({"tipo": "kaggle", "icono": "fa-book-open-reader", "texto": f"Leíste «{l.get('titulo')}» con el profesor",
                        "detalle": f"{l.get('leidas')} de {l.get('total')} celdas", "fecha": _cuando(l.get("ultima")),
                        "abrir": {"kaggle": {"tipo": "notebook", "ref": l.get("ref"), "celda": l.get("ultima_celda")}}})
    for it in colecciones[:20]:
        nombre = {"notebook": "el notebook", "dataset": "el dataset", "competicion": "la competición"}.get(it.get("tipo"), "")
        eventos.append({"tipo": "coleccion", "icono": "fa-bookmark", "texto": f"Guardaste {nombre} «{it.get('titulo')}»",
                        "detalle": f"en «{it.get('coleccion')}»", "fecha": _cuando(it.get("anadido")),
                        "abrir": {"kaggle": {"tipo": it.get("tipo"), "ref": it.get("ref")}}})
    for d in descargas[:20]:
        if not d.get("fecha"):
            continue
        eventos.append({"tipo": "datos", "icono": "fa-download", "texto": f"Descargaste los datos de «{d.get('nombre')}»",
                        "detalle": d.get("relativa") or "", "fecha": _cuando(d.get("fecha")),
                        "abrir": {"kaggle": {"tipo": d.get("tipo"), "ref": d.get("ref")}} if d.get("tipo") else None})
    for e in ejercicios[:20]:
        eventos.append({"tipo": "ejercicio", "icono": "fa-dumbbell",
                        "texto": f"{'Resolviste' if e.get('resuelto') else 'Practicaste'} un ejercicio de {e.get('concepto')}",
                        "detalle": f"{e.get('envios')} envíos", "fecha": _cuando(e.get("fecha")), "abrir": None})
    eventos = [e for e in eventos if e["fecha"]]
    eventos.sort(key=lambda e: e["fecha"], reverse=True)
    return eventos[:n]


def semana(actividad_por_dia: Dict[str, int], dias: int = 7) -> List[Dict[str, Any]]:
    """ Los últimos días con su número de acciones, para la tira de la semana """
    hoy = datetime.now().date()
    salida = []
    for i in range(dias - 1, -1, -1):
        d = hoy - timedelta(days=i)
        salida.append({"fecha": d.isoformat(), "dia": "LMXJVSD"[d.weekday()], "n": int(actividad_por_dia.get(d.isoformat(), 0))})
    return salida


# ===========================================================================
# Todo junto
# ===========================================================================

def _bloque(fn: Callable[[], Any], errores: Dict[str, str], nombre: str, vacio: Any = None) -> Any:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - un bloque roto no puede tirar la pantalla entera
        errores[nombre] = str(e)[:300]
        return vacio


def resumen(fuentes: Dict[str, Callable[[], Any]]) -> Dict[str, Any]:
    """ `fuentes` son funciones sin argumentos (las pone app.py con sus objetos) """
    errores: Dict[str, str] = {}
    obtener = lambda nombre, vacio=None: _bloque(fuentes[nombre], errores, nombre, vacio) if nombre in fuentes else vacio  # noqa: E731
    prog = obtener("progreso", {}) or {}
    historial = obtener("historial", []) or []
    lecturas = obtener("lecturas", []) or []
    guardado = obtener("colecciones_recientes", []) or []
    descargas = obtener("descargas", []) or []
    ejercicios = obtener("ejercicios", []) or []
    return {
        "perfil": perfil(),
        "hora": datetime.now().hour,
        "progreso": {k: prog.get(k) for k in ("desafios", "actividades", "racha", "conceptos", "fuertes", "flojos", "siguientes", "rutas")},
        "semana": semana(prog.get("actividad") or {}),
        "actividad": actividad(prog, historial, lecturas, guardado, descargas, ejercicios),
        "modelos": obtener("modelos", []),
        "cargados": obtener("cargados", []),
        "modelo_tutor": obtener("modelo_tutor"),
        "gemini": obtener("gemini"),
        "sistema": obtener("sistema"),
        "temperaturas": obtener("temperaturas"),
        "proyecto": obtener("proyecto"),
        "recientes": obtener("recientes", []),
        "kaggle": {"lecturas": lecturas[:4], "colecciones": (obtener("colecciones", []) or [])[:6],
                   "recientes": guardado, "cuenta": obtener("kaggle_cuenta")},
        "errores": errores,
        "generado": datetime.now().isoformat(timespec="seconds"),
    }
