"""Diferencial de red_http.py (HTTP por Rust con conexiones reutilizadas) contra `requests` y `urllib`: un servidor
local que devuelve lo que recibió (método, ruta con parámetros, cabeceras, cuerpo) y respuestas al azar (estados,
cabeceras repetidas, juegos de caracteres, redirecciones, JSON roto, cuerpos vacíos o binarios). Tiene que llegar lo
mismo al servidor y volver lo mismo al que llama. Sin internet.

    .venv/bin/python herramientas/diferencial_plataforma/red.py [semilla] [vueltas]
"""
import json, os, random, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend"))
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
import requests  # noqa: E402
import red_http  # noqa: E402

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
R = random.Random(semilla)
fallos, cuentas, recibido = [], {}, []
IGNORAR = {"accept-encoding", "connection", "date", "server", "host", "content-length"}


class Eco(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def responder(self):
        n = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(n) if n else b""
        recibido.append({"metodo": self.command, "ruta": self.path,
                         "cabeceras": sorted((k.lower(), v) for k, v in self.headers.items() if k.lower() not in IGNORAR),
                         "cuerpo": cuerpo.decode("latin-1")})
        if self.path.startswith("/redir"):
            self.send_response(302)
            self.send_header("Location", "/fin?de=redir")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        r = random.Random(self.path)
        estado = r.choice([200, 200, 201, 204, 304, 400, 403, 404, 422, 500])
        tipo = r.choice(["application/json", "application/json; charset=utf-8", "text/html; charset=ISO-8859-1",
                         "text/plain", None])
        cuerpo = b"" if estado in (204, 304) else r.choice([json.dumps({"a": 1, "ñ": "ü"}).encode(), "café".encode("latin-1"),
                                                             b"{roto", b"\x00\xff\x10", "texto ñ".encode()])
        self.send_response(estado)
        if tipo:
            self.send_header("Content-Type", tipo)
        self.send_header("X-Doble", "uno")
        self.send_header("X-Doble", "dos")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    do_GET = do_POST = do_PUT = do_DELETE = responder


srv = ThreadingHTTPServer(("127.0.0.1", 0), Eco)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def comparar(nombre, a, b, ctx):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 10:
        fallos.append({"prueba": nombre, "ctx": str(ctx)[:300], "viejo": str(a)[:700], "nuevo": str(b)[:700]})


def resp_requests(r):
    try:
        j = r.json()
    except ValueError as e:
        j = ("error", type(e).__name__)
    return (r.status_code, r.reason, r.ok, r.content, r.encoding, r.text, j, r.url,
            sorted((k.lower(), v) for k, v in r.headers.items() if k.lower() not in IGNORAR))


def llamar(f, *a, **k):
    del recibido[:]
    try:
        salida = ("ok", resp_requests(f(*a, **k)))
    except Exception as e:
        salida = ("error", type(e).__name__)
    time.sleep(0.002)
    return salida, list(recibido)


def sin_accept(recibidos):
    # urlopen de Rust manda también «Accept: */*» (desvío escrito en red_http.py)
    for x in recibidos:
        x["cabeceras"] = [c for c in x["cabeceras"] if c[0] != "accept"]
    return recibidos


def resp_urllib(f, req, timeout):
    del recibido[:]
    try:
        with f(req, timeout=timeout) as r:
            salida = ("ok", r.status, r.read(), r.headers.get_all("X-Doble"), r.headers.get_content_charset(), r.geturl())
    except urllib.error.HTTPError as e:
        salida = ("http", e.code, e.read())
    except Exception as e:
        salida = ("error", type(e).__name__)
    return salida, sin_accept(list(recibido))


for _ in range(N):
    ruta = R.choice(["/a", "/b/c", "/redir", "/x y", "/ñ"]) + R.choice(["", "?q=1", "?q=a+b&r=%C3%B1"])
    params = R.choice([None, {"q": "hola mundo", "n": 3}, {"l": ["a", "b"], "ñ": "é&="}, [("a", "1"), ("a", "2")]])
    cab = R.choice([None, {"User-Agent": "Prig/1"}, {"Authorization": "token x", "X-Nada": None}, {"Accept": "application/json"}])
    metodo = R.choice(["GET", "GET", "POST", "PUT", "DELETE"])
    extra = {}
    if metodo in ("POST", "PUT"):
        extra = R.choice([{"json": {"a": [1, 2], "ñ": None}}, {"data": {"k": "v w"}}, {"data": "crudo ñ"}, {}])
    auth = R.choice([None, None, ("ana", "sécret")])
    redir = R.choice([True, True, False])
    url = BASE + ruta.replace(" ", "%20")
    a = llamar(requests.request, metodo, url, params=params, headers=cab, auth=auth, timeout=5, allow_redirects=redir, **extra)
    b = llamar(red_http.request, metodo, url, params=params, headers=cab, auth=auth, timeout=5, allow_redirects=redir, **extra)
    comparar("requests", a, b, (metodo, url, params, cab, extra, auth, redir))
    datos = R.choice([None, b"x=1&y=2", "{}".encode()])
    req1 = urllib.request.Request(url, data=datos, headers=R.choice([{}, {"User-Agent": "Mozilla/5.0"}, {"Content-Type": "application/json"}]))
    req2 = urllib.request.Request(req1.full_url, data=req1.data, headers=dict(req1.header_items()))
    comparar("urlopen", resp_urllib(urllib.request.urlopen, req1, 5), resp_urllib(red_http.urlopen, req2, 5), (url, datos))

for nombre, f in (("requests", lambda: requests.get("http://127.0.0.1:9/", timeout=2)),
                  ("red_http", lambda: red_http.get("http://127.0.0.1:9/", timeout=2))):
    try:
        f()
    except Exception as e:
        cuentas.setdefault("sin_servidor", []).append((nombre, isinstance(e, requests.ConnectionError)))
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
