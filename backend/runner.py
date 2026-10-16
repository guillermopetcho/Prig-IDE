"""
Ejecutar el código del usuario: archivos de Python, C y C++ (compilados con gcc/g++), JS, bash y cuadernos, con
tiempo límite y cancelables desde otra petición (se mata el grupo de procesos entero); y las celdas de los cuadernos
en una sesión persistente.

Todo está en Rust (backend-rust/crates/prig-plataforma, ejecucion.rs): esperar a un proceso no retiene el GIL.
Python es aquí solo una herramienta: el intérprete que corre el código del usuario (sys.executable).
"""
import sys
from typing import Dict, Any, Optional, List

from kernel_session import KernelSessionManager


def _rs():
    from nativo_rust import rust
    return rust().ejecucion


class CodeRunner:
    def __init__(self, timeout_seconds: int = 25):
        self._rs = _rs().Ejecutor(timeout_seconds, sys.executable)
        self.sessions = KernelSessionManager(_nucleo=self._rs.sesiones)

    @property
    def timeout_seconds(self) -> int:
        return self._rs.timeout_seconds

    @property
    def _active(self) -> Dict[str, int]:
        """ {identificador: pid} de las ejecuciones en marcha """
        return self._rs.activos()

    def cancel(self, run_id: str) -> Dict[str, Any]:
        """ Detiene una ejecución en curso, con todo su grupo de procesos """
        return self._rs.cancel(run_id)

    def cancel_all(self):
        """ Detiene todas las ejecuciones activas de scripts y sus grupos de procesos """
        self._rs.cancel_all()

    def shutdown(self):
        """ Apaga por completo el sistema de ejecución: procesos de scripts y sesiones de kernel """
        self._rs.shutdown()

    def _register(self, run_id: Optional[str], proc):
        if run_id:
            self._rs.registrar(run_id, proc.pid)

    def _unregister(self, run_id: Optional[str]):
        if run_id:
            self._rs.quitar(run_id)

    def run_cell_code(self, code_string: str, cwd: str = None, session_id: Optional[str] = None,
                      timeout: Optional[int] = None) -> Dict[str, Any]:
        """ Ejecuta una celda dentro de la sesión persistente del cuaderno.

        Las celdas comparten espacio de nombres, igual que en Jupyter: lo que se define
        en una celda sigue disponible en las siguientes.
        """
        return self._rs.run_cell_code(code_string, cwd, session_id, timeout)

    def reset_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """ Reinicia la sesión de un cuaderno, descartando todas sus variables """
        return {"status": "ok", "restarted": self.sessions.reset(session_id)}

    def run_file(self, file_path: str, cwd: str = None, timeout: Optional[int] = None,
                 run_id: Optional[str] = None, extra_sources: Optional[List[str]] = None) -> Dict[str, Any]:
        return self._rs.run_file(file_path, cwd, timeout, run_id, list(extra_sources) if extra_sources else None)
