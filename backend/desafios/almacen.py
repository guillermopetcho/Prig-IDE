"""
Almacén de desafíos: un JSON por desafío en ~/.prig_desafios/desafios.

Dentro de cada desafío hay dos mitades que nunca se mezclan:

    público   enunciado, páginas de partida, páginas del alumno, razonamiento, progreso
    privado   pruebas ocultas y solución de referencia

La API solo entrega la mitad privada cuando el alumno se rinde o ya lo resolvió.

La carpeta se puede cambiar con PRIG_DESAFIOS_DIR (las pruebas la aíslan así).
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .ejecucion import ErrorDesafio

MAX_DESAFIOS = 1000
ID_VALIDO = re.compile(r"^des_[0-9a-f]{10}$")


def carpeta_base() -> str:
    return os.environ.get("PRIG_DESAFIOS_DIR") or os.path.expanduser("~/.prig_desafios")


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def nuevo_id() -> str:
    return f"des_{uuid.uuid4().hex[:10]}"


def progreso_inicial() -> Dict[str, Any]:
    return {"estado": "nuevo", "intentos": 0, "pistas": 0, "pasos_vistos": 0, "plan": "",
            "mejor": {"pasados": 0, "total": 0}, "historial": [], "empezado": None, "resuelto": None,
            "rendido": None, "segundos_hasta_resolver": None}


class Almacen:
    def __init__(self, base: Optional[str] = None):
        self.base = base or carpeta_base()
        self.dir = os.path.join(self.base, "desafios")
        # La carpeta se crea al guardar el primer desafío: importar la app no debe tocar el disco
        self._cerrojo = threading.RLock()

    def _ruta(self, id_: str) -> str:
        if not ID_VALIDO.match(id_ or ""):
            raise ErrorDesafio("Desafío desconocido")
        return os.path.join(self.dir, f"{id_}.json")

    # ------------------------------------------------------------ lectura y escritura
    def guardar(self, d: Dict[str, Any]) -> Dict[str, Any]:
        with self._cerrojo:
            d.setdefault("id", nuevo_id())
            d.setdefault("creado", ahora())
            d.setdefault("progreso", progreso_inicial())
            d["actualizado"] = ahora()
            os.makedirs(self.dir, exist_ok=True)
            ruta = self._ruta(d["id"])
            tmp = ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, ruta)
            self._podar()
        return d

    def obtener(self, id_: str) -> Dict[str, Any]:
        try:
            with open(self._ruta(id_), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise ErrorDesafio("Ese desafío ya no existe.")
        except ValueError:
            raise ErrorDesafio("El archivo del desafío está dañado.")

    def borrar(self, id_: str) -> bool:
        with self._cerrojo:
            try:
                os.remove(self._ruta(id_))
                return True
            except FileNotFoundError:
                return False

    def modificar(self, id_: str, cambio) -> Dict[str, Any]:
        """ Leer, aplicar `cambio(d)` y guardar, sin que otra petición se cuele en medio """
        with self._cerrojo:
            d = self.obtener(id_)
            cambio(d)
            return self.guardar(d)

    def lista(self) -> List[Dict[str, Any]]:
        salida = []
        if not os.path.isdir(self.dir):
            return salida
        for nombre in os.listdir(self.dir):
            if not nombre.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, nombre), encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                continue
            p = d.get("progreso") or {}
            salida.append({
                "id": d.get("id"), "titulo": d.get("titulo"), "nivel": d.get("nivel"),
                "conceptos": d.get("conceptos") or [],
                # El origen entero (ruta, bloque, modelo…) lo necesita el historial del perfil
                "origen": {k: v for k, v in (d.get("origen") or {}).items() if k != "tema"},
                "verificable": (d.get("comprobacion") or {}).get("tipo") != "ninguna",
                "estado": p.get("estado", "nuevo"), "intentos": p.get("intentos", 0), "pistas": p.get("pistas", 0),
                "mejor": p.get("mejor"), "creado": d.get("creado"), "actualizado": d.get("actualizado"),
                "progreso": {k: v for k, v in p.items() if k != "historial"},
            })
        return sorted(salida, key=lambda x: x.get("actualizado") or "", reverse=True)

    def _podar(self):
        archivos = [os.path.join(self.dir, n) for n in os.listdir(self.dir) if n.endswith(".json")]
        if len(archivos) <= MAX_DESAFIOS:
            return
        for ruta in sorted(archivos, key=os.path.getmtime)[:len(archivos) - MAX_DESAFIOS]:
            try:
                os.remove(ruta)
            except OSError:
                pass

    # ------------------------------------------------------------ vistas
    @staticmethod
    def publico(d: Dict[str, Any]) -> Dict[str, Any]:
        """ Todo menos las pruebas ocultas y la solución """
        vista = {k: v for k, v in d.items() if k != "privado"}
        p = d.get("progreso") or {}
        vista["solucion_disponible"] = p.get("estado") in ("resuelto", "rendido")
        vista["pistas_fuente"] = bool((d.get("privado") or {}).get("pistas_fuente"))
        return vista

    # ------------------------------------------------------------ progreso
    @staticmethod
    def registrar_comprobacion(d: Dict[str, Any], resultado: Dict[str, Any]):
        p = d.setdefault("progreso", progreso_inicial())
        p["intentos"] = p.get("intentos", 0) + 1
        p["empezado"] = p.get("empezado") or ahora()
        p.setdefault("historial", []).append({"cuando": ahora(), "aprobado": resultado["aprobado"],
                                              "pasados": resultado["pasados"], "total": resultado["total"]})
        p["historial"] = p["historial"][-50:]
        if resultado["total"] and resultado["pasados"] >= (p.get("mejor") or {}).get("pasados", 0):
            p["mejor"] = {"pasados": resultado["pasados"], "total": resultado["total"]}
        if resultado["aprobado"] and p.get("estado") != "resuelto":
            p["resuelto"] = ahora()
            try:
                inicio = datetime.fromisoformat(p["empezado"])
                p["segundos_hasta_resolver"] = int((datetime.fromisoformat(p["resuelto"]) - inicio).total_seconds())
            except (TypeError, ValueError):
                pass
            # Rendirse y luego aprobar copiando la solución no cuenta como resuelto
            if p.get("estado") != "rendido":
                p["estado"] = "resuelto"
        elif p.get("estado") == "nuevo":
            p["estado"] = "en_curso"

    @staticmethod
    def empezar(d: Dict[str, Any]):
        p = d.setdefault("progreso", progreso_inicial())
        p["empezado"] = p.get("empezado") or ahora()
        if p.get("estado") == "nuevo":
            p["estado"] = "en_curso"
