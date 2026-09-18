"""
Sesiones de ejecución persistentes para las celdas de los cuadernos.

Antes cada celda se ejecutaba en un proceso de Python nuevo, así que las variables,
imports y funciones definidos en una celda no existían en la siguiente y cualquier
cuaderno real fallaba con NameError en la segunda celda. Aquí se mantiene un proceso
intérprete vivo por cuaderno, al que se le envían las celdas por stdin.
"""

import os
import sys
import json
import queue
import threading
import subprocess
import signal
import tempfile
from collections import deque
from typing import Dict, Any, Optional

# Driver que corre dentro del proceso hijo: lee una celda por línea en stdin,
# la ejecuta en un espacio de nombres persistente y devuelve una línea JSON.
_DRIVER_SOURCE = r'''
import sys, os, json, io, ast, contextlib, traceback

def _run(code, namespace):
    """ Ejecuta la celda imitando a Jupyter: la última expresión se muestra. """
    tree = ast.parse(code, filename="<celda>", mode="exec")
    last_expr = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last_expr = ast.Expression(tree.body.pop().value)

    if tree.body:
        exec(compile(tree, "<celda>", "exec"), namespace)

    if last_expr is not None:
        value = eval(compile(last_expr, "<celda>", "eval"), namespace)
        if value is not None:
            print(repr(value))


def _format_user_traceback():
    """ Traceback sin los marcos internos del driver, como haría Jupyter """
    exc_type, exc, tb = sys.exc_info()
    driver_file = os.path.abspath(__file__)
    while tb is not None and os.path.abspath(tb.tb_frame.f_code.co_filename) == driver_file:
        tb = tb.tb_next
    return "".join(traceback.format_exception(exc_type, exc, tb))


def main():
    protocol_out = sys.stdout
    namespace = {"__name__": "__main__", "__builtins__": __builtins__}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception:
            continue

        if request.get("command") == "shutdown":
            break

        buf_out, buf_err = io.StringIO(), io.StringIO()
        ok = True
        try:
            with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                _run(request.get("code", ""), namespace)
        except SystemExit:
            pass
        except BaseException:
            ok = False
            buf_err.write(_format_user_traceback())

        protocol_out.write(json.dumps({
            "ok": ok,
            "stdout": buf_out.getvalue(),
            "stderr": buf_err.getvalue()
        }) + "\n")
        protocol_out.flush()


main()
'''


class KernelSession:
    """ Un proceso de Python persistente asociado a un cuaderno """

    def __init__(self, cwd: str):
        self.cwd = cwd
        self._driver_path = self._write_driver()
        self._stdout_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stderr_tail: deque = deque(maxlen=50)
        self._lock = threading.Lock()

        self.proc = subprocess.Popen(
            [sys.executable, "-u", self._driver_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            start_new_session=True
        )

        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    @staticmethod
    def _write_driver() -> str:
        fd, path = tempfile.mkstemp(prefix="prig_kernel_", suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_DRIVER_SOURCE)
        return path

    def _pump_stdout(self):
        try:
            for line in self.proc.stdout:
                self._stdout_queue.put(line)
        except Exception:
            pass
        finally:
            self._stdout_queue.put(None)

    def _pump_stderr(self):
        # Hay que drenar stderr aunque no lo usemos: si se llena el búfer de la
        # tubería el proceso hijo se bloquea indefinidamente.
        try:
            for line in self.proc.stderr:
                self._stderr_tail.append(line)
        except Exception:
            pass

    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def execute(self, code: str, timeout: int) -> Dict[str, Any]:
        with self._lock:
            if not self.is_alive():
                raise BrokenPipeError("La sesión del cuaderno no está activa.")

            # Descartar restos de una ejecución anterior abortada por timeout
            while True:
                try:
                    self._stdout_queue.get_nowait()
                except queue.Empty:
                    break

            self.proc.stdin.write(json.dumps({"code": code}) + "\n")
            self.proc.stdin.flush()

            try:
                line = self._stdout_queue.get(timeout=timeout)
            except queue.Empty:
                self.shutdown()
                raise TimeoutError(f"Tiempo límite de celda excedido ({timeout}s)")

            if line is None:
                detail = "".join(self._stderr_tail).strip()
                raise BrokenPipeError(detail or "El proceso de la sesión terminó inesperadamente.")

            return json.loads(line)

    def shutdown(self):
        try:
            if self.is_alive():
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except Exception:
                    self.proc.kill()
                try:
                    self.proc.wait(timeout=1)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if os.path.exists(self._driver_path):
                os.remove(self._driver_path)
        except Exception:
            pass


class KernelSessionManager:
    """ Mantiene una sesión viva por cuaderno y la reinicia cuando muere """

    def __init__(self):
        self._sessions: Dict[str, KernelSession] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(session_id: Optional[str]) -> str:
        return os.path.abspath(session_id) if session_id else "__scratch__"

    def get(self, session_id: Optional[str], cwd: str) -> KernelSession:
        key = self._key(session_id)
        with self._lock:
            session = self._sessions.get(key)
            if session is None or not session.is_alive() or session.cwd != cwd:
                if session is not None:
                    session.shutdown()
                session = KernelSession(cwd)
                self._sessions[key] = session
            return session

    def reset(self, session_id: Optional[str]) -> bool:
        key = self._key(session_id)
        with self._lock:
            session = self._sessions.pop(key, None)
        if session is not None:
            session.shutdown()
            return True
        return False

    def shutdown_all(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.shutdown()
