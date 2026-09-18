"""
Cola de descargas de modelos, con progreso, velocidad, tiempo restante y cancelación.

Una sola descarga a la vez: varias en paralelo no bajan más rápido (se reparten el
mismo ancho de banda) y complican ver qué pasa. Antes de empezar:

  · se comprueba el manifiesto en el registro de origen (existe, tamaño exacto);
  · se comprueba que cabe en el disco donde Ollama guarda los modelos.

Cancelar cierra la conexión: Ollama conserva lo descargado y, si se reintenta,
continúa desde ahí.

Los errores de Ollama se traducen a algo accionable: 412 (tu Ollama es anterior al
modelo), manifiesto inexistente, licencia sin aceptar, sin espacio o sin conexión.
"""

import itertools
import json
import os
import shutil
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import requests

import buscador_modelos as buscador

MAX_HISTORIAL = 40


def explicar_error(texto: str, codigo: Optional[int] = None) -> str:
    t = (texto or "").lower()
    if "llama-server binary not found" in t:
        from ai_engine.ai_engine_class import MENSAJE_RUNTIME_INCOMPLETO
        return MENSAJE_RUNTIME_INCOMPLETO
    if codigo == 412 or "412" in t or "newer version" in t or "requires a newer" in t:
        return "Este modelo necesita una versión de Ollama más nueva que la instalada."
    if "file does not exist" in t or "not found" in t or codigo == 404:
        return "El modelo o la variante no existe en el registro."
    if codigo in (401, 403) or "unauthorized" in t or "forbidden" in t or "gated" in t:
        return "El modelo requiere iniciar sesión o aceptar su licencia en la web de la plataforma."
    if "no space" in t or "disk" in t and "full" in t:
        return "No queda espacio en el disco de los modelos."
    if "timeout" in t or "connection" in t or "max retries" in t or "eof" in t:
        return "Se cortó la conexión. Reintenta: continúa desde lo ya descargado."
    return texto or "Error desconocido"


class Descargas:
    def __init__(self, base_url_fn: Callable[[], str], carpeta_modelos_fn: Callable[[], str],
                 al_terminar: Optional[Callable[[Dict[str, Any]], None]] = None,
                 comprobar=buscador.comprobar):
        self._base = base_url_fn
        self._carpeta = carpeta_modelos_fn
        self._al_terminar = al_terminar
        self._comprobar = comprobar
        self._cerrojo = threading.RLock()
        self._hay_trabajo = threading.Event()
        self._items: List[Dict[str, Any]] = []
        self._ids = itertools.count(1)
        self._hilo: Optional[threading.Thread] = None

    # ------------------------------------------------------------ cola
    def encolar(self, ref: str, titulo: Optional[str] = None) -> Dict[str, Any]:
        ref = buscador.validar_ref(ref)
        with self._cerrojo:
            activo = next((i for i in self._items if i["ref"] == ref and i["estado"] in ("en_cola", "comprobando", "descargando")), None)
            if activo:
                return self._publico(activo)
            item = {"id": next(self._ids), "ref": ref, "titulo": titulo or ref, "fuente": buscador.fuente_de_ref(ref),
                    "estado": "en_cola", "completado": 0, "total": None, "velocidad": None, "restante_s": None,
                    "fase": None, "error": None, "creado": time.time(), "terminado": None, "_cancelar": threading.Event()}
            self._items.append(item)
            self._podar()
            self._arrancar()
            self._hay_trabajo.set()
            return self._publico(item)

    def cancelar(self, id_: int) -> Dict[str, Any]:
        with self._cerrojo:
            item = self._buscar(id_)
            if item["estado"] in ("en_cola", "comprobando", "descargando"):
                item["_cancelar"].set()
                if item["estado"] == "en_cola":
                    item["estado"] = "cancelado"
                    item["terminado"] = time.time()
            return self._publico(item)

    def reintentar(self, id_: int) -> Dict[str, Any]:
        with self._cerrojo:
            item = self._buscar(id_)
            if item["estado"] not in ("error", "cancelado"):
                return self._publico(item)
            return self.encolar(item["ref"], item["titulo"])

    def limpiar_terminadas(self) -> int:
        with self._cerrojo:
            antes = len(self._items)
            self._items = [i for i in self._items if i["estado"] in ("en_cola", "comprobando", "descargando")]
            return antes - len(self._items)

    def lista(self) -> List[Dict[str, Any]]:
        with self._cerrojo:
            return [self._publico(i) for i in sorted(self._items, key=lambda i: -i["id"])]

    def _buscar(self, id_: int) -> Dict[str, Any]:
        item = next((i for i in self._items if i["id"] == id_), None)
        if not item:
            raise buscador.ErrorBuscador("Descarga desconocida")
        return item

    @staticmethod
    def _publico(item: Dict[str, Any]) -> Dict[str, Any]:
        d = {k: v for k, v in item.items() if not k.startswith("_")}
        d["porcentaje"] = round(100 * item["completado"] / item["total"], 1) if item.get("total") else None
        return d

    def _podar(self):
        terminadas = [i for i in self._items if i["estado"] not in ("en_cola", "comprobando", "descargando")]
        for i in sorted(terminadas, key=lambda i: i["id"])[:max(0, len(terminadas) - MAX_HISTORIAL)]:
            self._items.remove(i)

    def _arrancar(self):
        if self._hilo is None or not self._hilo.is_alive():
            self._hilo = threading.Thread(target=self._bucle, daemon=True, name="prig-descargas")
            self._hilo.start()

    def _bucle(self):
        while True:
            with self._cerrojo:
                item = next((i for i in sorted(self._items, key=lambda i: i["id"]) if i["estado"] == "en_cola"), None)
            if item is None:
                self._hay_trabajo.clear()
                if not self._hay_trabajo.wait(30):
                    with self._cerrojo:
                        if not any(i["estado"] == "en_cola" for i in self._items):
                            self._hilo = None
                            return
                continue
            self._descargar(item)

    # ------------------------------------------------------------ descarga
    def _fijar(self, item, **cambios):
        with self._cerrojo:
            item.update(cambios)

    def _descargar(self, item: Dict[str, Any]):
        self._fijar(item, estado="comprobando", fase="Comprobando en el registro")
        c = self._comprobar(item["ref"])
        if not c.get("descargable"):
            self._terminar(item, "error", error=c.get("motivo") or "No se puede descargar")
            return
        self._fijar(item, total=c.get("bytes"))
        carpeta = self._carpeta()
        try:
            libre = shutil.disk_usage(carpeta if os.path.isdir(carpeta) else os.path.expanduser("~")).free
        except OSError:
            libre = None
        if libre is not None and c.get("bytes") and libre < c["bytes"] * 1.05:
            self._terminar(item, "error", error=f"No hay espacio: hacen falta {c['bytes']/1e9:.1f} GB y quedan {libre/1e9:.1f} GB libres en {carpeta}.")
            return
        if item["_cancelar"].is_set():
            self._terminar(item, "cancelado")
            return

        self._fijar(item, estado="descargando", fase="Conectando")
        capas: Dict[str, Dict[str, int]] = {}
        muestras: List = []
        try:
            with requests.post(f"{self._base()}/api/pull", json={"model": item["ref"], "stream": True},
                               stream=True, timeout=(15, 600)) as r:
                if r.status_code != 200:
                    try:
                        detalle = r.json().get("error", "")
                    except ValueError:
                        detalle = r.text[:200]
                    self._terminar(item, "error", error=explicar_error(detalle, r.status_code))
                    return
                for linea in r.iter_lines():
                    if item["_cancelar"].is_set():
                        self._terminar(item, "cancelado")
                        return
                    if not linea:
                        continue
                    d = json.loads(linea)
                    if d.get("error"):
                        self._terminar(item, "error", error=explicar_error(d["error"]))
                        return
                    if d.get("digest") and d.get("total"):
                        capas[d["digest"]] = {"total": d["total"], "completado": d.get("completed", 0)}
                    completado = sum(x["completado"] for x in capas.values())
                    total = max(sum(x["total"] for x in capas.values()), item.get("total") or 0)
                    ahora = time.time()
                    muestras.append((ahora, completado))
                    muestras = [m for m in muestras if ahora - m[0] <= 8]
                    velocidad = None
                    if len(muestras) >= 2 and muestras[-1][0] > muestras[0][0]:
                        velocidad = (muestras[-1][1] - muestras[0][1]) / (muestras[-1][0] - muestras[0][0])
                    restante = (total - completado) / velocidad if velocidad and velocidad > 0 else None
                    fase = d.get("status", "")
                    self._fijar(item, completado=completado, total=total or item.get("total"), velocidad=velocidad,
                                restante_s=restante, fase=_fase_legible(fase))
                    if fase == "success":
                        self._fijar(item, completado=total or completado)
                        self._terminar(item, "completado")
                        return
            self._terminar(item, "error", error="La descarga terminó sin confirmación de Ollama. Reintenta.")
        except requests.RequestException as e:
            self._terminar(item, "cancelado" if item["_cancelar"].is_set() else "error",
                           error=None if item["_cancelar"].is_set() else explicar_error(str(e)))

    def _terminar(self, item, estado, error=None):
        self._fijar(item, estado=estado, error=error, terminado=time.time(), velocidad=None, restante_s=None,
                    fase={"completado": "Listo", "cancelado": "Cancelado (lo descargado se conserva)"}.get(estado, "Error"))
        if estado == "completado" and self._al_terminar:
            try:
                self._al_terminar(self._publico(item))
            except Exception:
                pass


def _fase_legible(status: str) -> str:
    s = status or ""
    if s.startswith("pulling manifest"):
        return "Leyendo el manifiesto"
    if s.startswith("pulling"):
        return "Descargando"
    if s.startswith("verifying"):
        return "Verificando"
    if s.startswith("writing"):
        return "Guardando"
    if s == "success":
        return "Listo"
    return s
