"""
Modo suave: que los modelos trabajen de forma continua y gradual, sin picos de calor.

Medido en el portátil del usuario (i5-13420H + RTX 4050 6 GB, qwen2.5-coder:7b):

  GPU. En cuanto empieza a generar pasa de 7 W a 40 W (su tope) y sube unos 7 °C en un
  segundo; sin parar se asienta en 64,5 °C. El límite de potencia (nvidia-smi -pl) y
  los relojes necesitan permisos de administrador, así que Prig no puede bajarlos. Lo
  que sí puede es DOSIFICAR el trabajo: generar un tramo corto, pausar y seguir donde
  quedó (Ollama lo retoma igual, releyendo lo ya escrito en 7 ms). Con tramos de 0,25 s
  y pausas iguales la media baja de 40 a 32 W y la temperatura estable de 64,5 a 60 °C.

  Aquí la pausa no es fija: se calcula como un termostato proporcional. Lejos de la
  temperatura objetivo trabaja a pleno; al acercarse, las pausas se alargan poco a poco
  y la temperatura se queda cerca del objetivo en vez de subir y bajar en diente de
  sierra (que es lo que hace el corte de emergencia del gobernador al tocar el límite).
  Además hay ARRANQUE GRADUAL: tras un rato sin trabajar, la primera parte de cada
  respuesta va a ritmo reducido y sube hasta el 100 % a lo largo de la rampa, para que
  la máquina (y sus ventiladores) no pasen de golpe de reposo a tope.

  CPU. Con el modelo entero en la GPU, un hilo del motor espera a la GPU sin parar: la
  CPU saltaba de 43 a 80-92 °C. Fijar el proceso del modelo (llama-server) a los núcleos
  de EFICIENCIA la deja en 69-72 °C a la misma velocidad (38 tok/s). No hace falta ser
  administrador: el proceso es del propio usuario. Solo se hace si el modelo cabe entero
  en la GPU; si una parte va en la CPU, esos núcleos lo frenarían y se dejan todos.
  (Quitar el «sondeo» de llama.cpp con LLAMA_ARG_POLL=0 se probó y no cambia nada.)
"""

import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set

import requests

AJUSTES_POR_DEFECTO = {
    "activo": True,
    "objetivo_c": 55.0,       # temperatura a la que se quiere mantener la GPU trabajando
    "rampa_s": 60.0,          # arranque gradual: segundos hasta llegar al 100 %
    "inicio_rampa": 0.2,      # fracción con la que arranca una respuesta tras un rato parado
    "ritmo_minimo": 0.25,     # fracción mínima del tiempo trabajando (nunca se para del todo)
    "tramo_s": 1.0,           # pausando peticiones (sin motor suave): cuánto trabaja entre pausas
    "tramo_motor_s": 0.02,    # dentro del motor: tramos de 20 ms (medido: potencia estable, sin golpes)
    "cpu_eficiente": True,    # fijar el motor a los núcleos de eficiencia
}
BANDA_C = 8.0                 # por debajo de objetivo − BANDA trabaja a pleno
REPOSO_S = 30.0               # tras este tiempo sin generar, la rampa vuelve a empezar
PAUSA_MAXIMA_S = 4.0


class Ritmo:
    """ Cuánto trabajar y cuánto descansar en cada momento """

    def __init__(self, ajustes: Optional[Dict[str, Any]] = None, guardar=None):
        self.ajustes = {**AJUSTES_POR_DEFECTO, **(ajustes or {})}
        self._guardar = guardar
        self._cerrojo = threading.Lock()
        self._inicio_actividad: Optional[float] = None
        self._ultima_actividad = 0.0
        self.ultimo: Dict[str, Any] = {}

    # -- ajustes
    def fijar(self, cambios: Dict[str, Any]) -> Dict[str, Any]:
        limites = {"objetivo_c": (40.0, 90.0), "rampa_s": (0.0, 300.0), "ritmo_minimo": (0.1, 1.0), "tramo_s": (0.25, 5.0),
                   "tramo_motor_s": (0.005, 0.5), "inicio_rampa": (0.1, 1.0)}
        with self._cerrojo:
            for clave, valor in cambios.items():
                if clave in ("activo", "cpu_eficiente"):
                    self.ajustes[clave] = bool(valor)
                elif clave in limites and valor is not None:
                    bajo, alto = limites[clave]
                    self.ajustes[clave] = round(min(alto, max(bajo, float(valor))), 2)
            ajustes = dict(self.ajustes)
        if self._guardar:
            self._guardar(ajustes, "Modo suave " + ("activado" if ajustes["activo"] else "desactivado")
                          + f": objetivo {ajustes['objetivo_c']:.0f} °C, arranque gradual de {ajustes['rampa_s']:.0f} s.")
        return ajustes

    @property
    def activo(self) -> bool:
        return bool(self.ajustes.get("activo"))

    # -- actividad (para la rampa)
    def marcar(self, ahora: Optional[float] = None):
        ahora = ahora or time.time()
        with self._cerrojo:
            if self._inicio_actividad is None or ahora - self._ultima_actividad > REPOSO_S:
                self._inicio_actividad = ahora
            self._ultima_actividad = ahora

    # -- decisión
    def fraccion(self, temp: Optional[float], ahora: Optional[float] = None) -> float:
        """ Fracción del tiempo que se trabaja (1 = sin pausas) """
        ahora = ahora or time.time()
        a = self.ajustes
        minimo = float(a["ritmo_minimo"])
        por_temp = 1.0
        if temp is not None:
            margen = float(a["objetivo_c"]) - temp
            por_temp = min(1.0, max(minimo, minimo + (1 - minimo) * margen / BANDA_C))
        por_rampa = 1.0
        rampa = float(a["rampa_s"])
        with self._cerrojo:
            inicio, ultima = self._inicio_actividad, self._ultima_actividad
        if rampa > 0:
            arranque = float(a.get("inicio_rampa", 0.3))
            if inicio is None or ahora - ultima > REPOSO_S:
                por_rampa = max(minimo, arranque)       # parado: la próxima respuesta empieza suave
            else:
                por_rampa = min(1.0, max(minimo, arranque + (1 - arranque) * (ahora - inicio) / rampa))
        return round(min(por_temp, por_rampa), 3)

    def pausa(self, segundos_trabajando: float, temp: Optional[float], ahora: Optional[float] = None) -> Optional[float]:
        """ Si toca descansar tras este tramo, cuántos segundos; si no, None """
        if not self.activo or segundos_trabajando < float(self.ajustes["tramo_s"]):
            return None
        f = self.fraccion(temp, ahora)
        self.ultimo = {"fraccion": f, "temp": temp, "cuando": time.time()}
        if f >= 0.98:
            return None
        return round(min(PAUSA_MAXIMA_S, segundos_trabajando * (1 - f) / f), 2)

    def estado(self, temp: Optional[float] = None) -> Dict[str, Any]:
        return {**self.ajustes, "fraccion_ahora": self.fraccion(temp) if self.activo else 1.0,
                "ultimo": self.ultimo, "nucleos_eficientes": nucleos_eficientes()}


# ===========================================================================
# Núcleos de eficiencia
# ===========================================================================

def _leer_lista_cpus(texto: str) -> List[int]:
    cpus: List[int] = []
    for parte in (texto or "").strip().split(","):
        if "-" in parte:
            a, b = parte.split("-")
            cpus += list(range(int(a), int(b) + 1))
        elif parte.strip().isdigit():
            cpus.append(int(parte))
    return cpus


def nucleos_eficientes() -> List[int]:
    """ Los E-cores de los Intel híbridos (12.ª generación en adelante). Vacío si no hay. """
    try:
        with open("/sys/devices/cpu_atom/cpus") as f:
            eficientes = _leer_lista_cpus(f.read())
    except OSError:
        return []
    disponibles = set(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else set(eficientes)
    return [c for c in eficientes if c in disponibles]


class FijadorCPU:
    """ Pone el motor del modelo (llama-server) en los núcleos de eficiencia si el modelo
    está entero en la GPU, y lo devuelve a todos si no. Solo toca procesos del usuario. """

    def __init__(self, url_ollama: str = "http://localhost:11434"):
        self.url = url_ollama
        self._hechos: Dict[int, str] = {}      # pid → "eficientes" | "todos"
        self._blobs: Dict[str, Optional[str]] = {}
        self._ultimo = 0.0

    def _blob(self, modelo: str) -> Optional[str]:
        """ El archivo de pesos del modelo (lo que aparece en la línea de llama-server).
        El «digest» de /api/ps es el del manifiesto, no este: hay que pedírselo a /api/show. """
        if modelo in self._blobs:
            return self._blobs[modelo]
        try:
            ficha = requests.post(f"{self.url}/api/show", json={"model": modelo}, timeout=3).json()
        except Exception:
            return None
        m = re.search(r"sha256-([0-9a-f]{64})", ficha.get("modelfile") or "")
        self._blobs[modelo] = m.group(1) if m else None
        return self._blobs[modelo]

    def _modelos_en_gpu(self) -> Dict[str, bool]:
        """ blob de pesos → True si el modelo está entero en la VRAM """
        try:
            cargados = requests.get(f"{self.url}/api/ps", timeout=2).json().get("models", [])
        except Exception:
            return {}
        salida = {}
        for m in cargados:
            blob = self._blob(m.get("name") or m.get("model") or "")
            if blob:
                salida[blob] = m.get("size_vram", 0) >= 0.98 * max(1, m.get("size", 1))
        return salida

    def aplicar(self, forzar: bool = False) -> Dict[str, Any]:
        eficientes = nucleos_eficientes()
        if not eficientes or not hasattr(os, "sched_setaffinity"):
            return {"aplicado": False, "motivo": "Este procesador no tiene núcleos de eficiencia."}
        if not forzar and time.time() - self._ultimo < 5.0:
            return {"aplicado": None}
        self._ultimo = time.time()
        try:
            import psutil
        except ImportError:
            return {"aplicado": False, "motivo": "Falta psutil."}
        en_gpu = self._modelos_en_gpu()
        todos = sorted(os.sched_getaffinity(0))
        cambiados = []
        yo = os.getuid() if hasattr(os, "getuid") else None
        for p in psutil.process_iter(["pid", "cmdline", "uids"]):
            linea = " ".join(p.info.get("cmdline") or [])
            if "llama-server" not in linea or (yo is not None and p.info.get("uids") and p.info["uids"].real != yo):
                continue
            m = re.search(r"sha256-([0-9a-f]{64})", linea)
            entero = bool(m and en_gpu.get(m.group(1)))
            destino = "eficientes" if entero else "todos"
            if self._hechos.get(p.pid) == destino and not forzar:
                continue
            try:
                os.sched_setaffinity(p.pid, eficientes if entero else todos)
                # Los hilos ya creados heredan la máscara del proceso solo al crearse: se aplica a cada uno
                for hilo in p.threads():
                    try:
                        os.sched_setaffinity(hilo.id, eficientes if entero else todos)
                    except OSError:
                        pass
                self._hechos[p.pid] = destino
                cambiados.append({"pid": p.pid, "nucleos": destino})
            except (OSError, psutil.Error):
                continue
        vivos: Set[int] = set(psutil.pids())
        self._hechos = {k: v for k, v in self._hechos.items() if k in vivos}
        return {"aplicado": True, "cambiados": cambiados, "eficientes": eficientes}

    def soltar(self):
        """ Devuelve todos los núcleos a los procesos que se habían fijado """
        todos = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else []
        for pid in list(self._hechos):
            try:
                os.sched_setaffinity(pid, todos)
            except OSError:
                pass
        self._hechos.clear()
