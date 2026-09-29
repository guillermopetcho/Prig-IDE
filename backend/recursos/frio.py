"""
Modo frío: modelos que viven en RAM (32–40B en una GPU de 6 GB) sin que la CPU se caliente.

Lo que se midió en un i5-13420H con turbo (docs/modo-frio.md):
  · generar con un modelo en RAM está limitado por la velocidad de la memoria, no por la CPU:
    4 hilos dan lo mismo que 8, y en los núcleos de eficiencia (E) un poco más;
  · el calor lo pone el turbo: con cualquier número de hilos la CPU pasaba de 50 a 90–97 °C;
  · la temperatura sigue a la potencia MEDIA. Congelando el motor ENTERO una parte de cada
    ciclo de 50 ms, en 4 núcleos E: al 50 % → 2,3 tok/s a 61 °C; al 33 % → 1,3 tok/s a 47 °C
    (sin control: 5,1 tok/s a 87 °C);
  · ponerle un tope por cgroup rinde entre 1,6 y 3,6 veces menos a igual temperatura, y usar
    todos los núcleos con tope todavía menos: el motor sincroniza sus hilos en cada capa y,
    cuando el kernel frena a uno, los demás se quedan girando esperándolo. Congelar el proceso
    entero para todos los hilos a la vez: no hay espera inútil.

Cómo se hace (sin root):
  · `Pausador` congela (SIGSTOP) y reanuda (SIGCONT) los motores de los modelos que NO caben
    enteros en la GPU. Las señales van por pidfd: apuntan a ese proceso exacto, así que nunca
    tocan a otro que reutilice su número. Siempre se reanuda al salir y, al arrancar Prig,
    se reanuda cualquier motor suyo que hubiera quedado congelado por un cierre brusco.
  · `ControladorFrio`, una vez por segundo con el motor trabajando, lee la temperatura de la
    CPU y ajusta la fracción de cada ciclo en que el motor trabaja, en rampas suaves.
  · Esos motores van a los núcleos E con 4 hilos (ritmo.FijadorCPU y ai_engine).
  · Solo motores de Prig (su llama-server). Un Ollama ajeno o del sistema no se toca.

Los modelos que caben enteros en la GPU no pasan por aquí: los regula el modo suave.
Con root (opcional, recursos/energia.py) se apaga además el turbo y se baja el tope de potencia.
"""

import atexit
import os
import re
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

POR_DEFECTO = {
    "activo": True,
    "objetivo_c": 60.0,        # temperatura de la CPU a la que se tiende
}
PERIODO_S = 0.05               # ciclo de trabajo/pausa: 50 ms
BANDA_C = 8.0                  # por debajo de objetivo − BANDA: sin pausas
MINIMO = 0.12                  # nunca se para del todo
INICIO = 0.30                  # tras un rato sin trabajar, la próxima respuesta arranca suave (con turbo)
ACTIVIDAD = 0.5                # núcleos (descontando las pausas) que cuentan como «generando»
# Motor MoE con el turbo apagado: las pausas le cuestan casi la mitad de la velocidad y ahorran poco
# calor. Medido (turbo apagado, código, 3 × 700 tokens): con pausas a 60 °C, 22,8 tok/s de media
# (13,7 ya caliente) y la CPU a 57-59 °C; sin pausas, 38,4 tok/s estables y la CPU a 57-63 °C. Con
# esta holgura solo se le pausa como protección, por encima del objetivo.
HOLGURA_MOE_SIN_TURBO_C = 8.0
PRIG_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def turbo_apagado() -> bool:
    """ ¿Está apagado el turbo de la CPU? (intel_pstate/no_turbo o cpufreq/boost; sin root) """
    for ruta, apagado in (("/sys/devices/system/cpu/intel_pstate/no_turbo", "1"),
                          ("/sys/devices/system/cpu/cpufreq/boost", "0")):
        try:
            with open(ruta) as f:
                return f.read().strip() == apagado
        except OSError:
            pass
    return False


def ncpu() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 4


def nucleos_eficientes() -> List[int]:
    try:
        from .ritmo import nucleos_eficientes as ne
        return ne()
    except Exception:
        return []


def hilos_en_frio() -> Optional[int]:
    """ Hilos para un modelo en RAM: tantos como núcleos E (4 rinden lo mismo que 8) """
    e = nucleos_eficientes()
    return len(e) if e else None


# =========================================================================== señales seguras

class Proceso:
    """ Un proceso concreto: las señales van por pidfd, así que si termina y el sistema reutiliza
    su número para otro programa, a ese otro no le llega nada """

    def __init__(self, pid: int):
        self.pid = pid
        self.fd: Optional[int] = None
        if hasattr(os, "pidfd_open"):
            try:
                self.fd = os.pidfd_open(pid)
            except OSError:
                self.fd = None
        self.vivo = self.fd is not None or (not hasattr(os, "pidfd_open") and _existe(pid))

    def senal(self, sig) -> bool:
        if not self.vivo:
            return False
        try:
            if self.fd is not None:
                signal.pidfd_send_signal(self.fd, sig)
            else:
                os.kill(self.pid, sig)
            return True
        except (ProcessLookupError, OSError):
            self.vivo = False
            return False

    def cerrar(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def tiempo_cpu(self) -> Optional[float]:
        """ Segundos de CPU usados (usuario + sistema, todos sus hilos) """
        try:
            with open(f"/proc/{self.pid}/stat") as f:
                campos = f.read().rsplit(")", 1)[1].split()
            return (int(campos[11]) + int(campos[12])) / os.sysconf("SC_CLK_TCK")
        except (OSError, IndexError, ValueError):
            return None


def _existe(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Pausador:
    """ Trabaja `fraccion` de cada ciclo de PERIODO_S y congela los motores el resto """

    def __init__(self, periodo_s: float = PERIODO_S):
        self.periodo = periodo_s
        self.fraccion = 1.0
        self.procesos: Dict[int, Proceso] = {}
        self._cerrojo = threading.Lock()
        self._parar = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._congelados: Set[int] = set()

    def fijar(self, pids: Set[int], fraccion: float):
        with self._cerrojo:
            for pid in list(self.procesos):
                if pid not in pids:
                    p = self.procesos.pop(pid)
                    p.senal(signal.SIGCONT)
                    p.cerrar()
            for pid in pids:
                if pid not in self.procesos:
                    p = Proceso(pid)
                    if p.vivo:
                        self.procesos[pid] = p
            self.fraccion = max(0.0, min(1.0, fraccion))
        if self.procesos and self.fraccion < 0.995:
            self._arrancar()

    def _arrancar(self):
        if self._hilo is None or not self._hilo.is_alive():
            self._parar.clear()
            self._hilo = threading.Thread(target=self._bucle, daemon=True, name="prig-modo-frio-pausas")
            self._hilo.start()

    def _todos(self, sig):
        with self._cerrojo:
            procesos = list(self.procesos.values())
        for p in procesos:
            if p.senal(sig):
                if sig == signal.SIGSTOP:
                    self._congelados.add(p.pid)
                else:
                    self._congelados.discard(p.pid)

    def _bucle(self):
        try:
            while not self._parar.is_set():
                with self._cerrojo:
                    fraccion, hay = self.fraccion, bool(self.procesos)
                if not hay or fraccion >= 0.995:
                    if self._parar.wait(self.periodo * 4):
                        break
                    continue
                trabajo = self.periodo * fraccion
                if self._parar.wait(trabajo):
                    break
                self._todos(signal.SIGSTOP)
                try:
                    self._parar.wait(self.periodo - trabajo)
                finally:
                    self._todos(signal.SIGCONT)            # pase lo que pase, se reanuda
        finally:
            self._todos(signal.SIGCONT)

    def cerrar(self):
        """ Para las pausas y deja todos los motores trabajando """
        self._parar.set()
        if self._hilo is not None and self._hilo.is_alive() and self._hilo is not threading.current_thread():
            self._hilo.join(timeout=1.0)
        self._todos(signal.SIGCONT)
        with self._cerrojo:
            for p in self.procesos.values():
                p.cerrar()
            self.procesos.clear()


# =========================================================================== los motores de Prig

def motores_de_prig() -> List[Dict[str, Any]]:
    """ Los llama-server de Prig del usuario: pid, blob de pesos y estado """
    try:
        import psutil
    except ImportError:
        return []
    yo = os.getuid()
    salida = []
    for p in psutil.process_iter(["pid", "cmdline", "uids", "status"]):
        try:
            cmd = p.info.get("cmdline") or []
            if not cmd or (p.info.get("uids") and p.info["uids"].real != yo):
                continue
            if "llama-server" not in os.path.basename(cmd[0]) or "--model" not in cmd:
                continue
            if not os.path.realpath(cmd[0]).startswith(PRIG_RAIZ + os.sep):
                continue                                   # solo el motor de Prig
            m = re.search(r"sha256-([0-9a-f]{64})", " ".join(cmd))
            salida.append({"pid": p.info["pid"], "blob": m.group(1) if m else None, "estado": p.info.get("status")})
        except Exception:
            continue
    return salida


def reanudar_huerfanos() -> int:
    """ Al arrancar: si un cierre brusco dejó congelado un motor de Prig, se reanuda """
    n = 0
    for m in motores_de_prig():
        if m["estado"] in ("stopped", "tracing-stop"):
            if Proceso(m["pid"]).senal(signal.SIGCONT):
                n += 1
    return n


# =========================================================================== el controlador

class ControladorFrio:
    """ Cada segundo: temperatura de la CPU → parte de cada ciclo en que trabajan los motores de
    los modelos que viven en RAM.

    Termostato proporcional (sin pausas por debajo de objetivo − BANDA, el mínimo en el objetivo)
    con media exponencial de la temperatura y cambios limitados por paso, para que la potencia
    cambie en rampas y la temperatura no oscile. """

    PERIODO_S = 1.0
    SUBIDA = 0.03
    BAJADA = 0.08
    SUAVIZADO = 0.3

    def __init__(self, ajustes: Callable[[], Dict[str, Any]], leer_temp: Callable[[], Optional[float]],
                 motores_en_ram: Callable[[], Set[int]], pausador: Optional[Pausador] = None,
                 reloj: Callable[[], float] = time.monotonic, sin_turbo: Callable[[], bool] = turbo_apagado,
                 holgura: Callable[[Set[int]], float] = lambda pids: 0.0):
        self.ajustes = ajustes
        self.holgura = holgura         # °C sobre el objetivo según qué motores haya (el MoE sin turbo)
        self.leer_temp = leer_temp
        self.motores_en_ram = motores_en_ram
        self.pausador = pausador or Pausador()
        self.reloj = reloj
        self.sin_turbo = sin_turbo
        self._generaba = False
        self.fraccion: Optional[float] = None
        self.temp_media: Optional[float] = None
        self._cpu_previa: Dict[int, tuple] = {}
        self.ultimo: Dict[str, Any] = {}
        self._parar = threading.Event()
        self._hilo: Optional[threading.Thread] = None

    @staticmethod
    def fraccion_objetivo(temp: Optional[float], objetivo: float) -> float:
        if temp is None or temp <= objetivo - BANDA_C:
            return 1.0
        if temp >= objetivo:
            return MINIMO
        return MINIMO + (1.0 - MINIMO) * (objetivo - temp) / BANDA_C

    def _actividad(self, pids: Set[int]) -> Optional[float]:
        """ Núcleos que usarían los motores sin pausas (lo medido, descontando la fracción) """
        ahora, total, hubo = self.reloj(), 0.0, False
        nuevos = {}
        for pid in pids:
            t = Proceso(pid).tiempo_cpu() if pid not in self.pausador.procesos else self.pausador.procesos[pid].tiempo_cpu()
            if t is None:
                continue
            nuevos[pid] = (ahora, t)
            previo = self._cpu_previa.get(pid)
            if previo and ahora > previo[0]:
                total += (t - previo[1]) / (ahora - previo[0])
                hubo = True
        self._cpu_previa = nuevos
        if not hubo:
            return None
        return total / max(self.fraccion or 1.0, MINIMO)

    def paso(self) -> Dict[str, Any]:
        a = {**POR_DEFECTO, **(self.ajustes() or {})}
        pids = set(self.motores_en_ram() or ()) if a["activo"] else set()
        if not pids:
            self.pausador.fijar(set(), 1.0)
            self.fraccion = None
            self.temp_media = None
            self._cpu_previa = {}
            self.ultimo = {"activo": bool(a["activo"]), "en_ram": 0, "fraccion": None, "objetivo_c": float(a["objetivo_c"])}
            return self.ultimo
        actividad = self._actividad(pids)
        generando = actividad is not None and actividad >= ACTIVIDAD
        temp = None
        if generando:
            # Los sensores solo se leen con el motor trabajando: en reposo no cuesta nada
            temp = self.leer_temp()
            if temp is not None:
                self.temp_media = temp if self.temp_media is None else \
                    self.SUAVIZADO * temp + (1 - self.SUAVIZADO) * self.temp_media
        objetivo_c = float(a["objetivo_c"]) + float(self.holgura(pids) or 0.0)
        objetivo = self.fraccion_objetivo(self.temp_media, objetivo_c)
        # La rampa desde el 30 % evita el salto del turbo (50 → 90 °C en segundos). Sin turbo no hay
        # salto: cada respuesta arranca con lo que permite la temperatura de ese momento (medido con
        # el motor MoE: la rampa tardaba ~23 s en llegar al 100 % con la CPU a 47 °C).
        sin_turbo = self.sin_turbo()
        if not generando:
            fraccion = 1.0 if sin_turbo else INICIO     # la próxima respuesta arranca suave (con turbo)
            self.temp_media = None
        elif self.fraccion is None or (sin_turbo and not self._generaba):
            fraccion = objetivo if sin_turbo else min(objetivo, INICIO)
        else:
            fraccion = min(self.fraccion + self.SUBIDA, max(self.fraccion - self.BAJADA, objetivo))
        self._generaba = generando
        self.fraccion = round(fraccion, 3)
        self.pausador.fijar(pids, self.fraccion)
        self.ultimo = {"activo": True, "en_ram": len(pids), "generando": generando,
                       "temp": temp, "temp_media": round(self.temp_media, 1) if self.temp_media is not None else None,
                       "fraccion": self.fraccion, "objetivo_c": float(a["objetivo_c"]), "objetivo_efectivo_c": objetivo_c}
        return self.ultimo

    def iniciar(self):
        if self._hilo is None or not self._hilo.is_alive():
            self._parar.clear()
            atexit.register(self.pausador.cerrar)
            self._hilo = threading.Thread(target=self._bucle, daemon=True, name="prig-modo-frio")
            self._hilo.start()

    def parar(self):
        self._parar.set()
        self.pausador.cerrar()

    def _bucle(self):
        while not self._parar.wait(self.PERIODO_S):
            try:
                self.paso()
            except Exception:
                pass
