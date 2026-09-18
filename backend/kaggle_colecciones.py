"""
Colecciones de Kaggle: grupos con nombre donde el usuario guarda notebooks, datasets y
competiciones (como las «Collections» y los marcadores de la web de Kaggle).

Cada elemento guarda una copia de lo necesario para pintarlo (título, autor, portada…),
de modo que la colección se ve sin red, y una nota libre del usuario. Una misma cosa
puede estar en varias colecciones.

Se guarda en ~/.prig_kaggle/colecciones.json (o PRIG_KAGGLE_DIR), con escritura atómica.
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import kaggle_lector as kl
from kaggle_lector import ErrorKaggle

TIPOS = ("notebook", "dataset", "competicion")
COLORES = ("#20beff", "#cba6f7", "#a6e3a1", "#f9e2af", "#fab387", "#f38ba8", "#94e2d5", "#89b4fa")
CAMPOS_ITEM = ("titulo", "subtitulo", "autor", "imagen", "votos", "url")
MAX_COLECCIONES = 200
MAX_ITEMS = 1000

_cerrojo = threading.RLock()


def _ruta() -> str:
    return os.path.join(kl.carpeta(), "colecciones.json")


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _leer() -> Dict[str, Any]:
    datos = kl._leer_json(_ruta()) or {}
    datos.setdefault("colecciones", [])
    return datos


def _escribir(datos: Dict[str, Any]):
    os.makedirs(kl.carpeta(), exist_ok=True)
    with open(_ruta() + ".tmp", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(_ruta() + ".tmp", _ruta())


def _buscar(datos: Dict[str, Any], id_: str) -> Dict[str, Any]:
    for c in datos["colecciones"]:
        if c["id"] == id_:
            return c
    raise ErrorKaggle("Esa colección no existe.")


def _limpiar_nombre(nombre: str) -> str:
    nombre = re.sub(r"\s+", " ", (nombre or "").strip())[:80]
    if not nombre:
        raise ErrorKaggle("Ponle un nombre a la colección.")
    return nombre


def _resumen(c: Dict[str, Any]) -> Dict[str, Any]:
    cuenta = {t: 0 for t in TIPOS}
    for it in c["items"]:
        cuenta[it["tipo"]] = cuenta.get(it["tipo"], 0) + 1
    portadas = [it["imagen"] for it in c["items"] if it.get("imagen")][:4]
    return {k: c[k] for k in ("id", "nombre", "descripcion", "color", "creada", "actualizada")} | \
        {"total": len(c["items"]), "cuenta": cuenta, "portadas": portadas}


# ===========================================================================
# Colecciones
# ===========================================================================

def listar() -> List[Dict[str, Any]]:
    """ Las colecciones, la tocada más recientemente primero """
    with _cerrojo:
        cols = _leer()["colecciones"]
    return [_resumen(c) for c in sorted(cols, key=lambda c: c.get("actualizada") or "", reverse=True)]


def obtener(id_: str) -> Dict[str, Any]:
    with _cerrojo:
        c = _buscar(_leer(), id_)
    return {**_resumen(c), "items": sorted(c["items"], key=lambda i: i.get("anadido") or "", reverse=True)}


def crear(nombre: str, descripcion: str = "", color: Optional[str] = None) -> Dict[str, Any]:
    nombre = _limpiar_nombre(nombre)
    with _cerrojo:
        datos = _leer()
        if len(datos["colecciones"]) >= MAX_COLECCIONES:
            raise ErrorKaggle(f"Como mucho {MAX_COLECCIONES} colecciones.")
        if any(c["nombre"].lower() == nombre.lower() for c in datos["colecciones"]):
            raise ErrorKaggle(f"Ya tienes una colección llamada «{nombre}».")
        c = {"id": uuid.uuid4().hex[:10], "nombre": nombre, "descripcion": (descripcion or "").strip()[:400],
             "color": color if color in COLORES else COLORES[len(datos["colecciones"]) % len(COLORES)],
             "creada": _ahora(), "actualizada": _ahora(), "items": []}
        datos["colecciones"].append(c)
        _escribir(datos)
    return _resumen(c)


def editar(id_: str, nombre: Optional[str] = None, descripcion: Optional[str] = None, color: Optional[str] = None) -> Dict[str, Any]:
    with _cerrojo:
        datos = _leer()
        c = _buscar(datos, id_)
        if nombre is not None:
            nombre = _limpiar_nombre(nombre)
            if any(o["id"] != id_ and o["nombre"].lower() == nombre.lower() for o in datos["colecciones"]):
                raise ErrorKaggle(f"Ya tienes una colección llamada «{nombre}».")
            c["nombre"] = nombre
        if descripcion is not None:
            c["descripcion"] = descripcion.strip()[:400]
        if color in COLORES:
            c["color"] = color
        c["actualizada"] = _ahora()
        _escribir(datos)
    return _resumen(c)


def borrar(id_: str) -> Dict[str, Any]:
    with _cerrojo:
        datos = _leer()
        _buscar(datos, id_)
        datos["colecciones"] = [c for c in datos["colecciones"] if c["id"] != id_]
        _escribir(datos)
    return {"ok": True}


# ===========================================================================
# Elementos
# ===========================================================================

def _validar_item(tipo: str, ref: str) -> str:
    if tipo not in TIPOS:
        raise ErrorKaggle("Solo se guardan notebooks, datasets y competiciones.")
    ref = (ref or "").strip()
    if tipo == "competicion":
        import kaggle_explorar
        return kaggle_explorar.ref_competicion(ref)
    if not kl.REF_VALIDA.match(ref) or ".." in ref:
        raise ErrorKaggle("Referencia no válida.")
    return ref


def anadir(id_: str, tipo: str, ref: str, datos_item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ref = _validar_item(tipo, ref)
    extra = {k: (datos_item or {}).get(k) for k in CAMPOS_ITEM}
    extra["titulo"] = (extra.get("titulo") or ref)[:200]
    with _cerrojo:
        datos = _leer()
        c = _buscar(datos, id_)
        existente = next((it for it in c["items"] if it["tipo"] == tipo and it["ref"] == ref), None)
        if existente:
            existente.update({k: v for k, v in extra.items() if v is not None})
        else:
            if len(c["items"]) >= MAX_ITEMS:
                raise ErrorKaggle(f"Una colección admite como mucho {MAX_ITEMS} elementos.")
            c["items"].append({"tipo": tipo, "ref": ref, **extra, "nota": "", "anadido": _ahora()})
        c["actualizada"] = _ahora()
        _escribir(datos)
    return _resumen(c)


def quitar(id_: str, tipo: str, ref: str) -> Dict[str, Any]:
    with _cerrojo:
        datos = _leer()
        c = _buscar(datos, id_)
        c["items"] = [it for it in c["items"] if not (it["tipo"] == tipo and it["ref"] == ref)]
        c["actualizada"] = _ahora()
        _escribir(datos)
    return _resumen(c)


def anotar(id_: str, tipo: str, ref: str, nota: str) -> Dict[str, Any]:
    with _cerrojo:
        datos = _leer()
        c = _buscar(datos, id_)
        it = next((it for it in c["items"] if it["tipo"] == tipo and it["ref"] == ref), None)
        if it is None:
            raise ErrorKaggle("Ese elemento no está en la colección.")
        it["nota"] = (nota or "").strip()[:2000]
        c["actualizada"] = _ahora()
        _escribir(datos)
    return {"ok": True}


def donde_esta(tipo: str, ref: str) -> List[str]:
    """ Ids de las colecciones que contienen este elemento (para marcar el botón «Guardar») """
    with _cerrojo:
        cols = _leer()["colecciones"]
    return [c["id"] for c in cols if any(it["tipo"] == tipo and it["ref"] == ref for it in c["items"])]


def guardados() -> Dict[str, List[str]]:
    """ {"tipo:ref": [ids]} de todo lo guardado: la interfaz marca las tarjetas de una vez """
    with _cerrojo:
        cols = _leer()["colecciones"]
    salida: Dict[str, List[str]] = {}
    for c in cols:
        for it in c["items"]:
            salida.setdefault(f"{it['tipo']}:{it['ref']}", []).append(c["id"])
    return salida


def recientes(n: int = 8) -> List[Dict[str, Any]]:
    """ Lo último guardado en cualquier colección (para Inicio) """
    with _cerrojo:
        cols = _leer()["colecciones"]
    todos = [{**it, "coleccion": c["nombre"], "coleccion_id": c["id"], "color": c["color"]} for c in cols for it in c["items"]]
    return sorted(todos, key=lambda i: i.get("anadido") or "", reverse=True)[:n]
