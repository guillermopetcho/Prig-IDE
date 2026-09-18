import os
import sys
import json
import signal
import subprocess
import tempfile
import threading
import time
from typing import Dict, Any, Optional

from kernel_session import KernelSessionManager


class CodeRunner:
    def __init__(self, timeout_seconds: int = 25):
        self.timeout_seconds = timeout_seconds
        self.sessions = KernelSessionManager()
        # Procesos en marcha, para poder detenerlos desde otra petición. Sin esto,
        # lanzar un bucle infinito solo dejaba esperar al tiempo límite.
        self._active: Dict[str, subprocess.Popen] = {}
        self._active_lock = threading.Lock()

    def cancel(self, run_id: str) -> Dict[str, Any]:
        """ Detiene una ejecución en curso, con todo su grupo de procesos """
        with self._active_lock:
            proc = self._active.get(run_id)
        if proc is None:
            return {"cancelled": False, "reason": "No hay ninguna ejecución con ese identificador."}
        try:
            # El proceso se lanza con start_new_session, así que se mata el grupo
            # entero: si el script abrió hijos, matar solo al padre los dejaría vivos.
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except Exception:
                return {"cancelled": False, "reason": "La ejecución ya había terminado."}
        return {"cancelled": True, "run_id": run_id}

    def cancel_all(self):
        """ Detiene todas las ejecuciones activas de scripts y sus grupos de procesos """
        with self._active_lock:
            procs = list(self._active.values())
            self._active.clear()
        for proc in procs:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except Exception:
                    pass
            except Exception:
                pass

    def shutdown(self):
        """ Apaga por completo el sistema de ejecución: procesos de scripts y sesiones de kernel """
        self.cancel_all()
        self.sessions.shutdown_all()

    def _register(self, run_id: Optional[str], proc: subprocess.Popen):
        if run_id:
            with self._active_lock:
                self._active[run_id] = proc

    def _unregister(self, run_id: Optional[str]):
        if run_id:
            with self._active_lock:
                self._active.pop(run_id, None)

    def run_cell_code(
        self,
        code_string: str,
        cwd: str = None,
        session_id: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """ Ejecuta una celda dentro de la sesión persistente del cuaderno.

        Las celdas comparten espacio de nombres, igual que en Jupyter: lo que se define
        en una celda sigue disponible en las siguientes.
        """
        working_dir = cwd if cwd and os.path.isdir(cwd) else os.getcwd()
        effective_timeout = timeout or self.timeout_seconds

        start_time = time.time()
        try:
            session = self.sessions.get(session_id, working_dir)
            result = session.execute(code_string, effective_timeout)
            return {
                "success": result.get("ok", False),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "exit_code": 0 if result.get("ok", False) else 1,
                "elapsed": round(time.time() - start_time, 3)
            }
        except TimeoutError as e:
            self.sessions.reset(session_id)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Error: {e}. La sesión del cuaderno se reinició; vuelve a ejecutar las celdas anteriores.",
                "exit_code": -1,
                "elapsed": effective_timeout
            }
        except Exception as e:
            self.sessions.reset(session_id)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Error al ejecutar celda: {str(e)}",
                "exit_code": 1,
                "elapsed": round(time.time() - start_time, 3)
            }

    def reset_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """ Reinicia la sesión de un cuaderno, descartando todas sus variables """
        existed = self.sessions.reset(session_id)
        return {"status": "ok", "restarted": existed}

    def run_file(self, file_path: str, cwd: str = None, timeout: Optional[int] = None,
                 run_id: Optional[str] = None) -> Dict[str, Any]:
        effective_timeout = timeout or self.timeout_seconds
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            return {"error": f"Archivo no existe: {file_path}", "stdout": "", "stderr": "", "exit_code": 1}

        working_dir = cwd if cwd and os.path.isdir(cwd) else os.path.dirname(abs_path)
        ext = os.path.splitext(abs_path)[1].lower()

        target_executable_script = abs_path
        temp_script_path = None

        if ext == '.ipynb':
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    nb_data = json.load(f)
                
                code_lines = []
                for cell in nb_data.get("cells", []):
                    if cell.get("cell_type") == "code":
                        source = cell.get("source", [])
                        code_lines.append("".join(source) if isinstance(source, list) else str(source))
                        code_lines.append("\n\n")

                temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8')
                temp_file.write("\n".join(code_lines))
                temp_file.close()
                temp_script_path = temp_file.name
                target_executable_script = temp_script_path
                ext = '.py'
            except Exception as e:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Error al procesar cuaderno .ipynb: {str(e)}",
                    "exit_code": 1,
                    "elapsed": 0
                }

        cmd = None
        if ext == '.py':
            cmd = [sys.executable, target_executable_script]
        elif ext == '.js':
            cmd = ['node', target_executable_script]
        elif ext in ['.sh', '.bash']:
            cmd = ['bash', target_executable_script]
        else:
            cmd = [sys.executable, target_executable_script]

        start_time = time.time()
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=working_dir,
                start_new_session=True
            )
            self._register(run_id, process)
            stdout, stderr = process.communicate(timeout=effective_timeout)
            self._unregister(run_id)

            # returncode negativo = terminado por señal, típicamente nuestra cancelación
            if process.returncode is not None and process.returncode < 0:
                if temp_script_path and os.path.exists(temp_script_path):
                    os.remove(temp_script_path)
                return {
                    "success": False,
                    "cancelled": True,
                    "stdout": stdout,
                    "stderr": "Ejecución detenida por el usuario.",
                    "exit_code": process.returncode,
                    "elapsed": round(time.time() - start_time, 3)
                }
            elapsed = round(time.time() - start_time, 3)

            if temp_script_path and os.path.exists(temp_script_path):
                os.remove(temp_script_path)

            return {
                "success": process.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": process.returncode,
                "elapsed": elapsed
            }
        except subprocess.TimeoutExpired:
            self._unregister(run_id)
            process.kill()
            stdout, stderr = process.communicate()
            if temp_script_path and os.path.exists(temp_script_path):
                os.remove(temp_script_path)
            return {
                "success": False,
                "stdout": stdout,
                "stderr": f"Error: Tiempo límite de ejecución excedido ({effective_timeout}s)",
                "exit_code": -1,
                "elapsed": effective_timeout
            }
        except Exception as e:
            self._unregister(run_id)
            if temp_script_path and os.path.exists(temp_script_path):
                os.remove(temp_script_path)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Error al ejecutar: {str(e)}",
                "exit_code": 1,
                "elapsed": 0
            }
