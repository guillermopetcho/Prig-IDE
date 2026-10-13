"""
Los subsistemas de Prig ya portados a Rust: el módulo `prig_nativo` (backend-rust/crates/prig-nativo-py).

Mientras su anfitrión (el chat, las rutas) siga en Python, cada subsistema portado se usa desde aquí, dentro de este
mismo proceso: una sola instancia y un solo dueño del estado, con la lógica, los hilos y los sensores en Rust (sin el
GIL). docs/plan-prig-rust.md, sección 4.1.

Instalación (en el .venv de Prig):
    herramientas/compilar_nativo.sh   (o, solo el módulo: cd backend-rust/crates/prig-nativo-py && VIRTUAL_ENV=../../../.venv maturin develop --release)
"""

from typing import Any

INTERFAZ = 13          # la versión de la interfaz de prig_nativo que entiende Prig

_modulo: Any = None


def rust():
    """ El módulo prig_nativo. ImportError si no está instalado o su interfaz no es la que espera Prig. """
    global _modulo
    if _modulo is None:
        try:
            import prig_nativo
        except ImportError as e:
            raise ImportError("Falta el módulo nativo de Prig (prig_nativo). Compílalo e instálalo en el .venv con "
                              "herramientas/compilar_nativo.sh") from e
        interfaz = getattr(prig_nativo, "INTERFAZ", None)
        if interfaz != INTERFAZ:
            raise ImportError(f"prig_nativo tiene la interfaz {interfaz} y Prig espera la {INTERFAZ}: recompila backend-rust")
        _modulo = prig_nativo
    return _modulo
