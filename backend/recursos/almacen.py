"""
Lo que el gestor de recursos recuerda entre sesiones.

Todo va en un único JSON (~/.prig_recursos.json) escrito de forma atómica: se
escribe a un temporal y se renombra, así un corte de luz a mitad no deja un
archivo roto que haga perder la calibración.

Las medidas se guardan POR HUELLA de máquina (GPU, driver, CPU, RAM, versión de
Ollama). Si la huella cambia, lo medido deja de aplicarse, pero no se borra: si se
vuelve a la configuración anterior (se desconecta una eGPU, se revierte un driver)
las medidas vuelven a valer sin recalibrar. Se conservan las últimas huellas.

Los ajustes que el usuario escribe a mano NUNCA se sobrescriben en silencio:
"Aplicar" guarda una copia de lo que había para poder "Restaurar".
"""

import copy
import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

VERSION = 1
MAX_HUELLAS = 5
MAX_EVENTOS = 200
MAX_PRUEBAS_POR_HUELLA = 60

_VACIO = {
    "version": VERSION,
    "huella_actual": None,
    "radiografia": None,
    "maquinas": {},         # huella -> {calibracion, pruebas, vista}
    "aplicado": {},         # perfil -> {modelo, opciones, fecha, anterior}
    "ultima_buena": {},     # perfil -> {modelo, opciones, fecha, huella}
    "entorno_servidor": {}, # OLLAMA_* que Prig pone al arrancar su servidor
    "termico": {},          # límite de la GPU y lo aprendido por el gobernador
    "eventos": [],
}


def ruta_por_defecto() -> str:
    return os.environ.get("PRIG_RECURSOS_ARCHIVO") or os.path.expanduser("~/.prig_recursos.json")


def _ahora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Almacen:
    def __init__(self, ruta: Optional[str] = None):
        self.ruta = ruta or ruta_por_defecto()
        self._cerrojo = threading.RLock()
        self._datos = self._leer()

    # -------------------------------------------------------------- disco
    def _leer(self) -> Dict[str, Any]:
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos = json.load(f)
            if not isinstance(datos, dict) or datos.get("version") != VERSION:
                raise ValueError("versión desconocida")
        except FileNotFoundError:
            return copy.deepcopy(_VACIO)
        except Exception:
            # Archivo roto o de otra versión: se aparta, no se pisa sin más
            try:
                os.replace(self.ruta, self.ruta + f".roto-{int(time.time())}")
            except OSError:
                pass
            return copy.deepcopy(_VACIO)
        for clave, valor in _VACIO.items():
            datos.setdefault(clave, copy.deepcopy(valor))
        return datos

    def _guardar(self):
        carpeta = os.path.dirname(os.path.abspath(self.ruta))
        os.makedirs(carpeta, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".prig_recursos.", dir=carpeta)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._datos, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.ruta)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -------------------------------------------------------------- máquina
    def registrar_radiografia(self, radiografia: Dict[str, Any]) -> Dict[str, Any]:
        """ Guarda la radiografía y dice si la máquina cambió desde la última vez """
        with self._cerrojo:
            nueva = radiografia.get("huella")
            anterior = self._datos.get("huella_actual")
            cambio = bool(anterior and nueva and anterior != nueva)
            self._datos["huella_actual"] = nueva
            self._datos["radiografia"] = radiografia
            maq = self._maquina(nueva, crear=True)
            maq["vista"] = _ahora()
            if cambio:
                self._evento("maquina_cambiada",
                             f"La máquina cambió ({anterior} → {nueva}): las medidas "
                             f"anteriores no se aplican hasta volver a calibrar.",
                             {"anterior": anterior, "nueva": nueva})
            self._podar_huellas()
            self._guardar()
            return {"cambio": cambio, "anterior": anterior,
                    "calibrada": bool(maq.get("calibracion"))}

    def _maquina(self, huella: Optional[str], crear: bool = False) -> Dict[str, Any]:
        if not huella:
            return {}
        maquinas = self._datos["maquinas"]
        if huella not in maquinas and crear:
            maquinas[huella] = {"calibracion": None, "pruebas": {}, "vista": _ahora()}
        return maquinas.get(huella, {})

    def _podar_huellas(self):
        maquinas = self._datos["maquinas"]
        if len(maquinas) <= MAX_HUELLAS:
            return
        actual = self._datos.get("huella_actual")
        viejas = sorted((h for h in maquinas if h != actual),
                        key=lambda h: maquinas[h].get("vista", ""))
        for h in viejas[:len(maquinas) - MAX_HUELLAS]:
            del maquinas[h]

    # -------------------------------------------------------------- calibración
    def calibracion(self, huella: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """ Solo la de la huella actual (o la pedida): nunca la de otra máquina """
        with self._cerrojo:
            h = huella or self._datos.get("huella_actual")
            cal = self._maquina(h).get("calibracion")
            return copy.deepcopy(cal) if cal else None

    def guardar_calibracion(self, huella: str, valores: Dict[str, Any],
                            detalle: Optional[Dict[str, Any]] = None):
        with self._cerrojo:
            maq = self._maquina(huella, crear=True)
            previa = maq.get("calibracion") or {}
            # Lo nuevo manda, lo que esta calibración no midió se conserva
            fusion = {k: v for k, v in previa.items() if k not in ("fecha", "detalle")}
            fusion.update({k: v for k, v in valores.items() if v is not None})
            fusion["fecha"] = _ahora()
            if detalle:
                fusion["detalle"] = detalle
            maq["calibracion"] = fusion
            self._evento("calibrada", "Calibración guardada.",
                         {"huella": huella, "valores": valores})
            self._guardar()

    def olvidar_calibracion(self, huella: Optional[str] = None):
        with self._cerrojo:
            maq = self._maquina(huella or self._datos.get("huella_actual"))
            if maq:
                maq["calibracion"] = None
                maq["pruebas"] = {}
                self._evento("calibracion_borrada", "Calibración y pruebas borradas.")
                self._guardar()

    # -------------------------------------------------------------- pruebas
    @staticmethod
    def clave_prueba(modelo: str, perfil: str) -> str:
        return f"{modelo}|{perfil}"

    def guardar_prueba(self, huella: str, modelo: str, perfil: str,
                       resultado: Dict[str, Any]):
        with self._cerrojo:
            maq = self._maquina(huella, crear=True)
            pruebas = maq.setdefault("pruebas", {})
            pruebas[self.clave_prueba(modelo, perfil)] = {**resultado, "fecha": _ahora()}
            if len(pruebas) > MAX_PRUEBAS_POR_HUELLA:
                sobran = sorted(pruebas, key=lambda k: pruebas[k].get("fecha", ""))
                for k in sobran[:len(pruebas) - MAX_PRUEBAS_POR_HUELLA]:
                    del pruebas[k]
            if resultado.get("ok"):
                self._datos["ultima_buena"][perfil] = {
                    "modelo": modelo, "opciones": resultado.get("opciones", {}),
                    "fecha": _ahora(), "huella": huella}
            self._guardar()

    def pruebas(self, huella: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        with self._cerrojo:
            h = huella or self._datos.get("huella_actual")
            return copy.deepcopy(self._maquina(h).get("pruebas") or {})

    def prueba(self, modelo: str, perfil: str,
               huella: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.pruebas(huella).get(self.clave_prueba(modelo, perfil))

    def ultima_buena(self, perfil: str) -> Optional[Dict[str, Any]]:
        """ Solo si se midió en ESTA máquina """
        with self._cerrojo:
            u = self._datos["ultima_buena"].get(perfil)
            if u and u.get("huella") == self._datos.get("huella_actual"):
                return copy.deepcopy(u)
            return None

    # -------------------------------------------------------------- aplicar
    def registrar_aplicado(self, perfil: str, modelo: str, opciones: Dict[str, Any],
                           anterior: Dict[str, Any]):
        """ Guarda lo aplicado Y lo que había antes, para poder restaurar.

        Si se aplica dos veces seguidas, `anterior` sigue siendo lo que había antes de
        la PRIMERA vez: restaurar tiene que volver a lo que el usuario tenía, no a una
        recomendación intermedia.
        """
        with self._cerrojo:
            previo = self._datos["aplicado"].get(perfil)
            original = previo["anterior"] if previo else anterior
            self._datos["aplicado"][perfil] = {
                "modelo": modelo, "opciones": opciones, "fecha": _ahora(),
                "anterior": original, "huella": self._datos.get("huella_actual")}
            self._evento("aplicado", f"Recomendación aplicada a {perfil}: {modelo}.",
                         {"perfil": perfil, "opciones": opciones})
            self._guardar()

    def aplicado(self, perfil: str) -> Optional[Dict[str, Any]]:
        with self._cerrojo:
            a = self._datos["aplicado"].get(perfil)
            return copy.deepcopy(a) if a else None

    def quitar_aplicado(self, perfil: str) -> Optional[Dict[str, Any]]:
        """ Devuelve lo que había antes de aplicar y olvida la aplicación """
        with self._cerrojo:
            a = self._datos["aplicado"].pop(perfil, None)
            if a:
                self._evento("restaurado", f"Restaurados los ajustes previos de {perfil}.",
                             {"perfil": perfil})
                self._guardar()
            return copy.deepcopy(a["anterior"]) if a else None

    # -------------------------------------------------------------- servidor
    def entorno_servidor(self) -> Dict[str, str]:
        with self._cerrojo:
            return dict(self._datos.get("entorno_servidor") or {})

    def guardar_entorno_servidor(self, entorno: Dict[str, str]):
        with self._cerrojo:
            limpio = {k: str(v) for k, v in entorno.items()
                      if k.startswith(("OLLAMA_", "LLAMA_ARG_")) and v is not None and str(v) != ""}
            self._datos["entorno_servidor"] = limpio
            self._evento("entorno_servidor", "Variables del servidor actualizadas.", limpio)
            self._guardar()

    # -------------------------------------------------------------- térmico
    def termico(self) -> Dict[str, Any]:
        with self._cerrojo:
            return dict(self._datos.get("termico") or {})

    def guardar_termico(self, ajustes: Dict[str, Any], texto: Optional[str] = None,
                        datos: Optional[Dict[str, Any]] = None):
        with self._cerrojo:
            self._datos["termico"] = dict(ajustes)
            if texto:
                self._evento("termico", texto, datos)
            self._guardar()

    def ritmo(self) -> Dict[str, Any]:
        with self._cerrojo:
            return dict(self._datos.get("ritmo") or {})

    def guardar_ritmo(self, ajustes: Dict[str, Any], texto: Optional[str] = None):
        with self._cerrojo:
            self._datos["ritmo"] = dict(ajustes)
            if texto:
                self._evento("ritmo", texto)
            self._guardar()

    # -------------------------------------------------------------- eventos
    def _evento(self, tipo: str, texto: str, datos: Optional[Dict[str, Any]] = None):
        eventos = self._datos["eventos"]
        eventos.append({"fecha": _ahora(), "tipo": tipo, "texto": texto,
                        **({"datos": datos} if datos else {})})
        del eventos[:-MAX_EVENTOS]

    def evento(self, tipo: str, texto: str, datos: Optional[Dict[str, Any]] = None):
        with self._cerrojo:
            self._evento(tipo, texto, datos)
            self._guardar()

    def eventos(self, limite: int = 50) -> List[Dict[str, Any]]:
        with self._cerrojo:
            return copy.deepcopy(self._datos["eventos"][-limite:])[::-1]

    @property
    def huella_actual(self) -> Optional[str]:
        return self._datos.get("huella_actual")

    @property
    def radiografia(self) -> Optional[Dict[str, Any]]:
        with self._cerrojo:
            return copy.deepcopy(self._datos.get("radiografia"))


_global: Optional[Almacen] = None
_global_cerrojo = threading.Lock()


def almacen() -> Almacen:
    global _global
    with _global_cerrojo:
        if _global is None or _global.ruta != ruta_por_defecto():
            _global = Almacen()
        return _global
