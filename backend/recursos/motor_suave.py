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
"""

import os
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Optional

RAIZ_PRIG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FUENTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nativo", "prig_suave.c")
MARCA_ENVOLTORIO = "# Prig · motor suave"
ACTIVO_S = 2.0            # el motor escribió su estado hace menos de esto → está generando


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
    destino = ruta_biblioteca()
    if not forzar and os.path.exists(destino) and os.path.getmtime(destino) >= os.path.getmtime(FUENTE):
        return {"ok": True, "ruta": destino}
    compilador = shutil.which("gcc") or shutil.which("cc")
    if not compilador:
        return {"ok": False, "motivo": "No hay compilador de C (gcc) en el sistema."}
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    r = subprocess.run([compilador, "-O2", "-shared", "-fPIC", "-o", destino + ".tmp", FUENTE, "-ldl"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return {"ok": False, "motivo": f"No se pudo compilar: {r.stderr.strip()[:300]}"}
    os.replace(destino + ".tmp", destino)
    return {"ok": True, "ruta": destino}


def _es_envoltorio(ruta: str) -> bool:
    try:
        with open(ruta, "rb") as f:
            return MARCA_ENVOLTORIO.encode() in f.read(400)
    except OSError:
        return False


def _guion(biblioteca: str, control: str) -> str:
    so, ctl = shlex.quote(biblioteca), shlex.quote(control)
    return f"""#!/bin/sh
{MARCA_ENVOLTORIO} (backend/recursos/motor_suave.py). El original está en llama-server.real.
# Al cargar un modelo: espera a la GPU durmiendo en vez de girando y acepta la dosificación de Prig.
DIR=$(dirname "$0")
if [ -f {so} ] && [ -z "$PRIG_SUAVE_DESACTIVADO" ]; then
  case " $* " in
    *" --model "*)
      LD_PRELOAD={so}${{LD_PRELOAD:+:$LD_PRELOAD}} PRIG_SUAVE_CONTROL="${{PRIG_SUAVE_CONTROL:-{ctl}}}" \\
        exec "$DIR/llama-server.real" "$@" --poll 0 ;;
  esac
fi
exec "$DIR/llama-server.real" "$@"
"""


def instalar() -> Dict[str, Any]:
    """ Compila la biblioteca y pone el envoltorio en el Ollama de Prig. Idempotente. """
    lib = dir_ollama()
    original, real = os.path.join(lib, "llama-server"), os.path.join(lib, "llama-server.real")
    if not os.path.exists(original) and not os.path.exists(real):
        return {"ok": False, "motivo": "Prig no tiene su propio Ollama: el modo suave pausa las peticiones."}
    c = compilar()
    if not c["ok"]:
        return c
    if os.path.exists(original) and not _es_envoltorio(original):
        os.replace(original, real)            # primera vez, o Ollama se actualizó y trajo uno nuevo
    if not os.path.exists(real):
        return {"ok": False, "motivo": "Falta el llama-server original de Ollama."}
    contenido = _guion(ruta_biblioteca(), ruta_control())
    try:
        with open(original, encoding="utf-8") as f:
            if f.read() == contenido:
                return {"ok": True, "instalado": True, "cambiado": False}
    except OSError:
        pass
    with open(original + ".tmp", "w", encoding="utf-8") as f:
        f.write(contenido)
    os.chmod(original + ".tmp", 0o755)
    os.replace(original + ".tmp", original)
    return {"ok": True, "instalado": True, "cambiado": True}


def desinstalar() -> Dict[str, Any]:
    """ Deja el Ollama de Prig exactamente como venía """
    lib = dir_ollama()
    original, real = os.path.join(lib, "llama-server"), os.path.join(lib, "llama-server.real")
    if os.path.exists(real) and (not os.path.exists(original) or _es_envoltorio(original)):
        os.replace(real, original)
    return {"ok": True, "instalado": False}


def instalado() -> bool:
    return _es_envoltorio(os.path.join(dir_ollama(), "llama-server")) and os.path.exists(os.path.join(dir_ollama(), "llama-server.real"))


# ===========================================================================
# Estado y control
# ===========================================================================

def leer_estado() -> Optional[Dict[str, Any]]:
    """ Lo que escribió el motor: {pid, ultima, fraccion, tramo, esperas_s} o None """
    try:
        with open(ruta_control() + ".estado") as f:
            partes = f.read().split()
        return {"pid": int(partes[0]), "ultima": float(partes[1]), "fraccion": float(partes[2]),
                "tramo": float(partes[3]), "esperas_s": float(partes[4])}
    except (OSError, ValueError, IndexError):
        return None


def generando(estado: Optional[Dict[str, Any]] = None) -> bool:
    estado = estado if estado is not None else leer_estado()
    return bool(estado and time.time() - estado["ultima"] < ACTIVO_S)


def escribir_control(fraccion: float, tramo: float):
    ruta = ruta_control()
    try:
        with open(ruta + ".tmp", "w") as f:
            f.write(f"{max(0.05, min(1.0, fraccion)):.3f} {tramo:.4f} {time.time():.3f}\n")
        os.replace(ruta + ".tmp", ruta)
    except OSError:
        pass


def quitar_control():
    for ruta in (ruta_control(), ruta_control() + ".tmp"):
        try:
            os.remove(ruta)
        except OSError:
            pass


class Controlador:
    """ Dos veces por segundo: temperatura → fracción de trabajo → archivo de control.

    Medido: aplicar directamente la fracción del termostato hacía oscilar la potencia entre
    21 y 33 W (el chip cambia de temperatura en un segundo y el termostato respondía a cada
    vaivén), con dientes de sierra de ±3 °C. Por eso la temperatura se suaviza con una media
    exponencial y la fracción solo puede cambiar despacio: sube como mucho SUBIDA por paso
    (llegar de 0,2 a 1 tarda más de 20 s) y baja como mucho BAJADA. La potencia cambia en
    rampas y la temperatura también.
    """

    PERIODO_S = 0.5
    SUBIDA = 0.02
    BAJADA = 0.06
    SUAVIZADO = 0.3           # peso de la lectura nueva en la media de temperatura

    def __init__(self, ritmo, monitor):
        self.ritmo = ritmo
        self.monitor = monitor
        self._parar = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self.ultimo: Dict[str, Any] = {}
        self.temp_media: Optional[float] = None
        self.fraccion: Optional[float] = None

    def iniciar(self):
        if self._hilo is None or not self._hilo.is_alive():
            self._parar.clear()
            self._hilo = threading.Thread(target=self._bucle, daemon=True, name="prig-motor-suave")
            self._hilo.start()

    def parar(self):
        self._parar.set()

    def paso(self) -> Dict[str, Any]:
        estado = leer_estado()
        activo = generando(estado)
        if activo:
            self.ritmo.marcar()
        temp = None
        if activo or self.ritmo.activo:
            try:
                temp = self.monitor.gpu(max_edad=1.0) if activo else self.monitor.gpu(max_edad=3.0)
            except Exception:
                temp = None
        if temp is not None:
            self.temp_media = temp if self.temp_media is None else \
                self.SUAVIZADO * temp + (1 - self.SUAVIZADO) * self.temp_media
        if self.ritmo.activo:
            objetivo = self.ritmo.fraccion(self.temp_media)
            if not activo or self.fraccion is None:
                fraccion = objetivo                 # parado: la próxima respuesta arranca ya en su punto
            else:
                fraccion = min(self.fraccion + self.SUBIDA, max(self.fraccion - self.BAJADA, objetivo))
            self.fraccion = fraccion
            escribir_control(fraccion, float(self.ritmo.ajustes.get("tramo_motor_s") or 0.02))
        else:
            fraccion = 1.0
            self.fraccion = None
            quitar_control()
        self.ultimo = {"generando": activo, "temp": temp, "temp_media": self.temp_media, "fraccion": fraccion, "motor": estado}
        return self.ultimo

    def _bucle(self):
        while not self._parar.wait(self.PERIODO_S):
            try:
                self.paso()
            except Exception:
                pass
