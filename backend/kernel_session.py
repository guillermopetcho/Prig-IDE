"""
Sesiones de ejecución persistentes para las celdas de los cuadernos.

Antes cada celda se ejecutaba en un proceso de Python nuevo, así que las variables,
imports y funciones definidos en una celda no existían en la siguiente y cualquier
cuaderno real fallaba con NameError en la segunda celda. Aquí se mantiene un proceso
intérprete vivo por cuaderno, al que se le envían las celdas por stdin.

Las sesiones están en Rust (backend-rust/crates/prig-plataforma, ejecucion.rs; el driver que corre dentro del
intérprete, en kernel_driver.py): leer la salida y esperar las respuestas no retiene el GIL.
"""

import sys
from typing import Any, Dict, Optional


def _rs():
    from nativo_rust import rust
    return rust().ejecucion


# El driver que corre dentro del proceso hijo: lee una celda por línea en stdin, la ejecuta en un espacio de
# nombres persistente y devuelve una línea JSON
_DRIVER_SOURCE = _rs().DRIVER


class KernelSession:
    """ Un proceso de Python persistente asociado a un cuaderno """

    def __init__(self, cwd: str, _nucleo=None):
        self._rs = _nucleo if _nucleo is not None else _rs().Sesion(cwd, sys.executable)

    @property
    def cwd(self) -> str:
        return self._rs.cwd

    @property
    def _driver_path(self) -> str:
        return self._rs.driver

    def is_alive(self) -> bool:
        return self._rs.is_alive()

    def execute(self, code: str, timeout: int) -> Dict[str, Any]:
        """ TimeoutError si se pasa del tiempo (y la sesión se apaga); BrokenPipeError si no está viva """
        return self._rs.execute(code, timeout)

    def shutdown(self):
        self._rs.shutdown()


class KernelSessionManager:
    """ Mantiene una sesión viva por cuaderno y la reinicia cuando muere """

    def __init__(self, _nucleo=None):
        self._rs = _nucleo if _nucleo is not None else _rs().Sesiones(sys.executable)

    @property
    def _sessions(self) -> Dict[str, Any]:
        return {k: True for k in self._rs.claves()}

    def get(self, session_id: Optional[str], cwd: str) -> KernelSession:
        return KernelSession(cwd, _nucleo=self._rs.get(session_id, cwd))

    def reset(self, session_id: Optional[str]) -> bool:
        return self._rs.reset(session_id)

    def shutdown_all(self):
        self._rs.shutdown_all()
