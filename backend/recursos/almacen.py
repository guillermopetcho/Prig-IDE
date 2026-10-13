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
El almacén está en Rust (backend-rust/crates/prig-recursos, almacen.rs): el archivo sale byte a byte igual que
cuando lo escribía Python, con los mismos permisos (0600).
"""

import os
import threading
from typing import Optional


def _rs():
    from nativo_rust import rust
    return rust().almacen


VERSION = _rs().VERSION
MAX_HUELLAS = _rs().MAX_HUELLAS
MAX_EVENTOS = _rs().MAX_EVENTOS
MAX_PRUEBAS_POR_HUELLA = _rs().MAX_PRUEBAS_POR_HUELLA


def ruta_por_defecto() -> str:
    return os.environ.get("PRIG_RECURSOS_ARCHIVO") or os.path.expanduser("~/.prig_recursos.json")


def Almacen(ruta: Optional[str] = None):
    """ El almacén de un archivo (por defecto, el de ruta_por_defecto()). Métodos: registrar_radiografia,
    calibracion, guardar_calibracion, olvidar_calibracion, clave_prueba, guardar_prueba, pruebas, prueba,
    ultima_buena, registrar_aplicado, aplicado, quitar_aplicado, entorno_servidor, guardar_entorno_servidor,
    termico, guardar_termico, frio, guardar_frio, ritmo, guardar_ritmo, evento, eventos; y huella_actual,
    radiografia y ruta. """
    return _rs().Almacen(ruta or ruta_por_defecto())


_global = None
_global_cerrojo = threading.Lock()


def almacen():
    global _global
    with _global_cerrojo:
        if _global is None or _global.ruta != ruta_por_defecto():
            _global = Almacen()
        return _global
