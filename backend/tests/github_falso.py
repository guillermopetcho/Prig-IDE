"""
GitHub falso para las pruebas: API, archivos en crudo y zip, en un solo servidor.

    API       = <url>              /search/repositories, /repos/…, /rate_limit
    RAW       = <url>/raw          /<dueño>/<repo>/<rama>/<ruta>
    CODELOAD  = <url>/codeload     /<dueño>/<repo>/zip/refs/heads/<rama>

Una búsqueda con «LIMITE» responde como GitHub al agotar el límite sin cuenta.
"""

import io
import json
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ARCHIVOS = {
    "README.md": "# Calculadora\n\nUna **calculadora** de ejemplo.\n\n![logo](docs/logo.png)\n",
    "calc/__init__.py": "from .operaciones import sumar, restar\n",
    "calc/operaciones.py": "def sumar(a, b):\n    return a + b\n\n\ndef restar(a, b):\n    return a - b\n",
    "calc/cli.py": "import sys\nfrom calc import sumar\n\nif __name__ == '__main__':\n    print(sumar(int(sys.argv[1]), int(sys.argv[2])))\n",
    "tests/test_operaciones.py": "from calc import sumar\n\ndef test_sumar():\n    assert sumar(2, 2) == 4\n",
    "pyproject.toml": "[project]\nname = 'calc'\n",
    "docs/logo.png": "\x89PNG\x00\x00binario",
}

REPO = {"full_name": "ana/calc", "name": "calc", "owner": {"login": "ana", "avatar_url": "https://avatars.example/ana?v=4"},
        "description": "Una calculadora de ejemplo", "stargazers_count": 1234, "forks_count": 56, "language": "Python",
        "topics": ["python", "ejemplo"], "pushed_at": "2026-09-01T10:00:00Z", "license": {"spdx_id": "MIT"},
        "default_branch": "main", "size": 12, "open_issues_count": 3, "homepage": "", "archived": False, "fork": False,
        "html_url": "https://github.com/ana/calc"}
OTRO = {**REPO, "full_name": "luis/web", "name": "web", "owner": {"login": "luis", "avatar_url": "https://avatars.example/luis?v=4"},
        "description": "Un sitio web", "language": "JavaScript", "stargazers_count": 10, "html_url": "https://github.com/luis/web"}


def _zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for ruta, contenido in ARCHIVOS.items():
            z.writestr(f"calc-main/{ruta}", contenido)
        z.writestr("calc-main/../../fuera.txt", "malo")
    return buf.getvalue()


class Manejador(BaseHTTPRequestHandler):
    peticiones = []

    def log_message(self, *a):
        pass

    def _enviar(self, codigo, cuerpo, tipo="application/json", cabeceras=None):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        for k, v in (cabeceras or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        ruta = unquote(u.path)
        Manejador.peticiones.append({"ruta": ruta, "params": q, "auth": self.headers.get("Authorization")})
        if ruta == "/rate_limit":
            return self._enviar(401 if (self.headers.get("Authorization") or "").endswith("malo_token_de_prueba_1234") else 200, {})
        if ruta == "/search/repositories":
            if "LIMITE" in q.get("q", ""):
                return self._enviar(403, {"message": "API rate limit exceeded"}, cabeceras={
                    "X-RateLimit-Remaining": "0", "X-RateLimit-Resource": "search", "X-RateLimit-Reset": str(int(time.time()) + 120)})
            return self._enviar(200, {"total_count": 2, "items": [REPO, OTRO]})
        if ruta == "/repos/ana/calc":
            return self._enviar(200, REPO)
        if ruta == "/repos/ana/calc/languages":
            return self._enviar(200, {"Python": 900, "Shell": 100})
        if ruta == "/repos/ana/calc/git/trees/main":
            return self._enviar(200, {"truncated": False, "tree": [{"path": "calc", "type": "tree"}] + [
                {"path": r, "type": "blob", "size": len(c.encode()), "sha": f"{abs(hash(r + c)):040x}"[:40]} for r, c in ARCHIVOS.items()]})
        if ruta.startswith("/repos/"):
            return self._enviar(404, {"message": "Not Found"})
        if ruta.startswith("/raw/ana/calc/main/"):
            archivo = ruta[len("/raw/ana/calc/main/"):]
            if archivo in ARCHIVOS:
                return self._enviar(200, ARCHIVOS[archivo].encode("latin-1" if archivo.endswith(".png") else "utf-8"), "text/plain")
            return self._enviar(404, b"404", "text/plain")
        if ruta == "/codeload/ana/calc/zip/refs/heads/main":
            return self._enviar(200, _zip(), "application/zip")
        self._enviar(404, {"message": "Not Found"})


def arrancar(puerto: int = 0):
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{servidor.server_address[1]}", servidor


def apuntar(modulo, url: str):
    """ Hace que github_lector hable con este servidor """
    modulo.API, modulo.RAW, modulo.CODELOAD = url, url + "/raw", url + "/codeload"
