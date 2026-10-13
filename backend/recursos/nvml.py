"""
Sensores de la GPU NVIDIA por NVML (la biblioteca del controlador que usa nvidia-smi por
dentro), cargada con dlopen desde Rust (backend-rust/crates/prig-recursos, nvml.rs).

Por qué: cada «nvidia-smi --query-gpu=…» es un proceso nuevo de ~27 ms de CPU. Prig lo
lanzaba cada 1-3 s (monitor térmico, barra de estado) y eso bastaba para que auto-cpufreq
encendiera el turbo: midiendo solo la CPU en reposo, consultar nvidia-smi cada 0,2 s subía
la media de 51 a 57,5 °C con picos de 85 °C. Por NVML la misma lectura cuesta microsegundos
y no crea procesos. Si NVML no está (otra GPU, sin controlador), se devuelve None y quien
llama sigue usando nvidia-smi como antes.
"""

from typing import Any, Dict, List, Optional


def _rs():
    from nativo_rust import rust
    return rust().sensores


def disponible() -> bool:
    """ ¿Hay NVML? La primera llamada la carga (~2 s) """
    return _rs().nvml_disponible()


def lectura() -> Optional[List[Dict[str, Any]]]:
    """ [{indice, nombre, temp, consumo_w, uso_pct, ventilador_pct, vram_usada_mb, vram_total_mb, reloj_mhz}] """
    return _rs().nvml_lectura()
