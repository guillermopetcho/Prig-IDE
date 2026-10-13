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
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

PRIG_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rs():
    """ El modo frío en Rust (prig_nativo.frio) """
    from nativo_rust import rust
    return rust().frio


def _t():
    """ El controlador (prig_nativo.termico) """
    from nativo_rust import rust
    return rust().termico


# Los valores viven en Rust (frio.rs); aquí con sus nombres de siempre
POR_DEFECTO = _t().FRIO_POR_DEFECTO     # activo, objetivo_c (temperatura de la CPU a la que se tiende)
PERIODO_S = _rs().PERIODO_S             # ciclo de trabajo/pausa: 50 ms
BANDA_C = _rs().BANDA_C                 # por debajo de objetivo − BANDA: sin pausas
MINIMO = _rs().MINIMO                   # nunca se para del todo
INICIO = _t().INICIO                    # tras un rato sin trabajar, la próxima respuesta arranca suave (con turbo)
ACTIVIDAD = _t().ACTIVIDAD              # núcleos (descontando las pausas) que cuentan como «generando»
# Motor MoE con el turbo apagado: las pausas le cuestan casi la mitad de la velocidad y ahorran poco
# calor. Medido (turbo apagado, código, 3 × 700 tokens): con pausas a 60 °C, 22,8 tok/s de media
# (13,7 ya caliente) y la CPU a 57-59 °C; sin pausas, 38,4 tok/s estables y la CPU a 57-63 °C. Con
# esta holgura solo se le pausa como protección, por encima del objetivo.
HOLGURA_MOE_SIN_TURBO_C = _t().HOLGURA_MOE_SIN_TURBO_C


def turbo_apagado() -> bool:
    """ ¿Está apagado el turbo de la CPU? (intel_pstate/no_turbo o cpufreq/boost; sin root) """
    return _rs().turbo_apagado()


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

# Las señales y el pausador viven en Rust (backend-rust/crates/prig-recursos, frio.rs)

class Proceso:
    """ Un proceso concreto: las señales van por pidfd, así que si termina y el sistema reutiliza
    su número para otro programa, a ese otro no le llega nada. El pidfd se cierra al soltarlo. """

    def __init__(self, pid: int):
        self.pid = pid
        self._rs = _rs().Proceso(pid)

    @property
    def vivo(self) -> bool:
        return self._rs.vivo

    def senal(self, sig) -> bool:
        return self._rs.senal(int(sig))

    def cerrar(self):
        self._rs.cerrar()

    def tiempo_cpu(self) -> Optional[float]:
        """ Segundos de CPU usados (usuario + sistema, todos sus hilos) """
        return _rs().tiempo_cpu(self.pid)


class _Tiempo:
    """ Lo que el controlador mira de cada motor en pausa: su tiempo de CPU (sin abrir otro pidfd) """

    def __init__(self, pid: int):
        self.pid = pid

    def tiempo_cpu(self) -> Optional[float]:
        return _rs().tiempo_cpu(self.pid)


class Pausador:
    """ Trabaja `fraccion` de cada ciclo de PERIODO_S y congela los motores el resto. El ciclo corre en un hilo de
    Rust, con plazos absolutos y sin el GIL: en Python, con otro hilo de Prig ocupado, el tramo de trabajo de 6 ms
    se estiraba hasta 11,2 ms (docs/informe-rust-moe.md §2). """

    def __init__(self, periodo_s: float = PERIODO_S):
        self._rs = _rs().Pausador(periodo_s)

    @property
    def periodo(self) -> float:
        return self._rs.periodo

    @property
    def fraccion(self) -> float:
        return self._rs.fraccion

    @property
    def procesos(self) -> Dict[int, "_Tiempo"]:
        return {pid: _Tiempo(pid) for pid in self._rs.pids()}

    @property
    def _congelados(self) -> Set[int]:
        return set(self._rs.congelados())

    def fijar(self, pids: Set[int], fraccion: float):
        self._rs.fijar(set(pids), float(fraccion))

    def cerrar(self):
        """ Para las pausas y deja todos los motores trabajando """
        self._rs.cerrar()


# =========================================================================== los motores de Prig

def motores_de_prig() -> List[Dict[str, Any]]:
    """ Los llama-server de Prig del usuario: pid, blob de pesos y estado (leído de /proc, en Rust) """
    return [{"pid": pid, "blob": blob, "estado": estado} for pid, blob, estado in _rs().motores_de_prig(PRIG_RAIZ)]


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
    cambie en rampas y la temperatura no oscile. Las decisiones viven en Rust (frio.rs); esta clase
    le da el mundo (ajustes, motores, reloj, temperatura, pausador). """

    PERIODO_S = _t().FRIO_PERIODO_S
    SUBIDA = _t().FRIO_SUBIDA
    BAJADA = _t().FRIO_BAJADA
    SUAVIZADO = _t().FRIO_SUAVIZADO

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
        self._n = _t().NucleoFrio()
        self._parar = threading.Event()
        self._hilo: Optional[threading.Thread] = None

    @staticmethod
    def fraccion_objetivo(temp: Optional[float], objetivo: float) -> float:
        return _rs().fraccion_objetivo(temp, objetivo)

    @property
    def fraccion(self) -> Optional[float]:
        return self._n.fraccion

    @property
    def temp_media(self) -> Optional[float]:
        return self._n.temp_media

    @property
    def ultimo(self) -> Dict[str, Any]:
        return self._n.ultimo

    @property
    def _generaba(self) -> bool:
        return self._n.generaba

    def _tiempo_cpu(self, pid: int) -> Optional[float]:
        """ Segundos de CPU de un motor (del pausador si lo tiene, para no abrir otro pidfd) """
        return Proceso(pid).tiempo_cpu() if pid not in self.pausador.procesos else self.pausador.procesos[pid].tiempo_cpu()

    def paso(self) -> Dict[str, Any]:
        return self._n.paso(self)

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
