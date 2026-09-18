"""
Sensores de la GPU NVIDIA por NVML (la biblioteca del controlador que usa nvidia-smi por
dentro), llamada directamente con ctypes.

Por qué: cada «nvidia-smi --query-gpu=…» es un proceso nuevo de ~27 ms de CPU. Prig lo
lanzaba cada 1-3 s (monitor térmico, barra de estado) y eso bastaba para que auto-cpufreq
encendiera el turbo: midiendo solo la CPU en reposo, consultar nvidia-smi cada 0,2 s subía
la media de 51 a 57,5 °C con picos de 85 °C. Por NVML la misma lectura cuesta microsegundos
y no crea procesos. Si NVML no está (otra GPU, sin controlador), se devuelve None y quien
llama sigue usando nvidia-smi como antes.
"""

import ctypes
import threading
from typing import Any, Dict, List, Optional

_cerrojo = threading.Lock()
_lib = None
_estado = {"iniciado": False, "fallo": False}

NVML_TEMPERATURE_GPU = 0
NVML_CLOCK_GRAPHICS = 0


class _Uso(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Memoria(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


def _iniciar() -> bool:
    global _lib
    if _estado["iniciado"]:
        return True
    if _estado["fallo"]:
        return False
    for nombre in ("libnvidia-ml.so.1", "libnvidia-ml.so"):
        try:
            _lib = ctypes.CDLL(nombre)
            break
        except OSError:
            _lib = None
    if _lib is None or _lib.nvmlInit_v2() != 0:
        _estado["fallo"] = True
        return False
    _estado["iniciado"] = True
    return True


def disponible() -> bool:
    with _cerrojo:
        return _iniciar()


def lectura() -> Optional[List[Dict[str, Any]]]:
    """ [{indice, nombre, temp, consumo_w, uso_pct, ventilador_pct, vram_usada_mb, vram_total_mb, reloj_mhz}] """
    with _cerrojo:
        if not _iniciar():
            return None
        n = ctypes.c_uint(0)
        if _lib.nvmlDeviceGetCount_v2(ctypes.byref(n)) != 0:
            return None
        salida = []
        for i in range(n.value):
            h = ctypes.c_void_p()
            if _lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(h)) != 0:
                continue
            nombre = ctypes.create_string_buffer(96)
            temp, potencia, reloj, ventilador = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
            uso, memoria = _Uso(), _Memoria()
            g = {"indice": i}
            g["nombre"] = nombre.value.decode(errors="replace") if _lib.nvmlDeviceGetName(h, nombre, 96) == 0 else "GPU"
            g["temp"] = float(temp.value) if _lib.nvmlDeviceGetTemperature(h, NVML_TEMPERATURE_GPU, ctypes.byref(temp)) == 0 else None
            g["consumo_w"] = potencia.value / 1000.0 if _lib.nvmlDeviceGetPowerUsage(h, ctypes.byref(potencia)) == 0 else None
            g["uso_pct"] = float(uso.gpu) if _lib.nvmlDeviceGetUtilizationRates(h, ctypes.byref(uso)) == 0 else None
            g["ventilador_pct"] = float(ventilador.value) if _lib.nvmlDeviceGetFanSpeed(h, ctypes.byref(ventilador)) == 0 else None
            if _lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(memoria)) == 0:
                g["vram_usada_mb"], g["vram_total_mb"] = memoria.used // 1048576, memoria.total // 1048576
            else:
                g["vram_usada_mb"] = g["vram_total_mb"] = None
            g["reloj_mhz"] = float(reloj.value) if _lib.nvmlDeviceGetClockInfo(h, NVML_CLOCK_GRAPHICS, ctypes.byref(reloj)) == 0 else None
            salida.append(g)
        return salida
