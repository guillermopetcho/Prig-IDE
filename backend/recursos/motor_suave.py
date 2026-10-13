"""
Motor suave: el modo suave aplicado DENTRO del proceso del modelo, no cortando peticiones.

Pieza nativa: recursos/nativo/prig_suave.c (ver sus comentarios con las mediciones). Se
compila aquí con el gcc del sistema a <Prig>/lib/prig/prig_suave.so y se precarga en el
llama-server del Ollama PROPIO de Prig (<Prig>/lib/ollama) con un envoltorio:

    llama-server        → guion de Prig: al cargar un modelo añade LD_PRELOAD y --poll 0
    llama-server.real   → el lanzador original de Ollama, intacto

--poll 0 no se puede pasar de otro modo: Ollama arma la línea de órdenes y esa opción no
tiene variable de entorno (se comprobó en libllama-common: LLAMA_ARG_POLL no existe). El
Ollama del sistema nunca se toca; si Prig no usa el suyo, el modo suave sigue funcionando
como antes (pausando peticiones) y esto queda inactivo.

Control: dos veces por segundo se escribe «fraccion tramo marca» en el archivo de control
(tmpfs del usuario). Si Prig se cierra, la marca caduca a los 5 s y el motor vuelve a
trabajar a pleno. El motor escribe su estado cada segundo en «<control>.estado»: así se
sabe si el modo suave está actuando dentro del motor.
Todo está en Rust (backend-rust/crates/prig-recursos, motor_suave.rs). Las rutas siguen saliendo del entorno en
cada llamada, y el controlador lee el reloj, el estado y el monitor a través de esta fachada.
"""

import os
import threading
import time
from typing import Any, Dict, Optional

RAIZ_PRIG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FUENTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nativo", "prig_suave.c")


def _rs():
    from nativo_rust import rust
    return rust().motor_suave


MARCA_ENVOLTORIO = _rs().MARCA_ENVOLTORIO
ACTIVO_S = _rs().ACTIVO_S            # el motor escribió su estado hace menos de esto → está generando


def ruta_control() -> str:
    if os.environ.get("PRIG_SUAVE_CONTROL"):
        return os.environ["PRIG_SUAVE_CONTROL"]
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, "prig_suave")


def ruta_biblioteca() -> str:
    return os.environ.get("PRIG_SUAVE_SO") or os.path.join(RAIZ_PRIG, "lib", "prig", "prig_suave.so")


def dir_ollama() -> str:
    return os.environ.get("PRIG_OLLAMA_LIB") or os.path.join(RAIZ_PRIG, "lib", "ollama")


# ===========================================================================
# Compilar e instalar
# ===========================================================================

def compilar(forzar: bool = False) -> Dict[str, Any]:
    return _rs().compilar(RAIZ_PRIG, forzar)


def instalar() -> Dict[str, Any]:
    """ Compila la biblioteca y pone el envoltorio en el Ollama de Prig. Idempotente. """
    return _rs().instalar(RAIZ_PRIG)


def desinstalar() -> Dict[str, Any]:
    """ Deja el Ollama de Prig exactamente como venía """
    return _rs().desinstalar(RAIZ_PRIG)


def instalado() -> bool:
    return _rs().instalado(RAIZ_PRIG)


# ===========================================================================
# Estado y control
# ===========================================================================

def leer_estado() -> Optional[Dict[str, Any]]:
    """ Lo que escribió el motor: {pid, ultima, fraccion, tramo, esperas_s} o None """
    return _rs().leer_estado(RAIZ_PRIG)


def generando(estado: Optional[Dict[str, Any]] = None) -> bool:
    estado = estado if estado is not None else leer_estado()
    return bool(estado) and _rs().generando(estado, time.time())


def escribir_control(fraccion: float, tramo: float):
    _rs().escribir_control(RAIZ_PRIG, fraccion, tramo, time.time())


def quitar_control():
    _rs().quitar_control(RAIZ_PRIG)


class Controlador:
    """ Dos veces por segundo: temperatura → fracción de trabajo → archivo de control.

    Medido: aplicar directamente la fracción del termostato hacía oscilar la potencia entre
    21 y 33 W (el chip cambia de temperatura en un segundo y el termostato respondía a cada
    vaivén), con dientes de sierra de ±3 °C. Por eso la temperatura se suaviza con una media
    exponencial y la fracción solo puede cambiar despacio: sube como mucho SUBIDA por paso
    (llegar de 0,2 a 1 tarda más de 20 s) y baja como mucho BAJADA. La potencia cambia en
    rampas y la temperatura también.
    """

    PERIODO_S = _rs().PERIODO_S
    SUBIDA = _rs().SUBIDA
    BAJADA = _rs().BAJADA
    SUAVIZADO = _rs().SUAVIZADO      # peso de la lectura nueva en la media de temperatura

    def __init__(self, ritmo, monitor):
        self.ritmo = ritmo
        self.monitor = monitor
        self._n = _rs().Controlador()
        self._parar = threading.Event()
        self._hilo: Optional[threading.Thread] = None

    # Lo que el paso (en Rust) lee y escribe fuera: aquí, para poder sustituirlo
    @staticmethod
    def _leer_estado():
        return leer_estado()

    @staticmethod
    def _generando(estado):
        return generando(estado)

    @staticmethod
    def _escribir_control(fraccion, tramo):
        escribir_control(fraccion, tramo)

    @staticmethod
    def _quitar_control():
        quitar_control()

    @property
    def ultimo(self) -> Dict[str, Any]:
        return self._n.ultimo

    @property
    def temp_media(self) -> Optional[float]:
        return self._n.temp_media

    @property
    def fraccion(self) -> Optional[float]:
        return self._n.fraccion

    def iniciar(self):
        if self._hilo is None or not self._hilo.is_alive():
            self._parar.clear()
            self._hilo = threading.Thread(target=self._bucle, daemon=True, name="prig-motor-suave")
            self._hilo.start()

    def parar(self):
        self._parar.set()

    def paso(self) -> Dict[str, Any]:
        return self._n.paso(self)

    def _bucle(self):
        while not self._parar.wait(self.PERIODO_S):
            try:
                self.paso()
            except Exception:
                pass
