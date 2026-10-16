"""Diferencial de ollama_gestion.py: la versión de Python puro (REFERENCIA, con requests) contra la de ahora (Rust por
prig_nativo, con reqwest), las dos contra el mismo Ollama falso local (nunca el del usuario) con escenarios al azar:
listas de modelos, fichas, errores de Ollama en JSON o en texto, flujos de creación que fallan a mitad, el registro
con 200, 404 o 500, e importar un GGUF. Tienen que dar lo mismo: valores, pasos y excepciones (tipo y texto).

    .venv/bin/python herramientas/diferencial_plataforma/gestion.py [semilla] [vueltas]
"""
import hashlib, http.server, json, os, random, sys, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import TMP, viejo  # noqa: E402
os.environ.pop("http_proxy", None); os.environ.pop("HTTP_PROXY", None)
os.environ["NO_PROXY"] = "127.0.0.1"
import ollama_gestion as gn  # noqa: E402
gv = viejo("ollama_gestion")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 150
R = random.Random(semilla)
fallos, cuentas = [], {}
ESCENA = {}


class Manejador(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _atender(self):
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            cuerpo = b""
            while True:
                n = int(self.rfile.readline().strip(), 16)
                if n == 0:
                    self.rfile.readline(); break
                cuerpo += self.rfile.read(n); self.rfile.readline()
        else:
            cuerpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        codigo, salida = ESCENA["responder"](self.command, self.path, cuerpo)
        self.send_response(codigo)
        self.send_header("Content-Length", str(len(salida)))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(salida)

    do_GET = do_POST = do_HEAD = do_DELETE = _atender

    def log_message(self, *a):
        pass


servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{servidor.server_address[1]}"
gv.REGISTRO = gn.REGISTRO = URL + "/registro"


def error_ollama():
    return R.choice([(404, b'{"error": "model not found"}'), (500, b'{"error": {"message": "fallo"}}'), (400, b"texto plano"),
                     (500, b""), (400, b'["lista"]'), (500, b'{"error": ""}'), (400, b'{"error": 7}')])


def modelo():
    n = R.choice(["qwen3:14b", "a:1", "mio:latest", "x/y:z", "solo"])
    m = {"name": n}
    for k, v in (("size", R.choice([0, 123, 4.5e9])), ("digest", R.choice(["d" * 64, None])), ("modified_at", "2026-10-01T10:00:00Z"),
                 ("details", R.choice([{"family": "qwen3", "parameter_size": "14B", "quantization_level": "Q4_K_M", "format": "gguf"}, None, {}]))):
        if R.random() < 0.85: m[k] = v
    return m


def escena():
    tags = {"models": [modelo() for _ in range(R.randint(0, 4))]} if R.random() < 0.9 else R.choice([{}, {"models": []}])
    ps = {"models": [dict(m, size_vram=10, context_length=4096, expires_at="2026") for m in tags.get("models", [])[:R.randint(0, 2)]]}
    show = {"capabilities": R.choice([["completion", "tools"], None]), "details": {"family": "qwen3"},
            "model_info": {"general.architecture": "qwen3", "qwen3.context_length": 40960, "tokenizer.ggml.tokens": ["a"] * R.choice([3, 100])},
            "parameters": R.choice(['temperature 0.6\nstop "<|im_start|>"\nstop "<|im_end|>"', "", None, "solo\nk  v  w\n\"q\" \"\""]),
            "template": "{{ .Prompt }}", "license": "MIT", "modelfile": "FROM x", "tensors": [{"type": R.choice(["Q4_K", "F32", None])} for _ in range(R.randint(0, 5))]}
    malos = {k: error_ollama() for k in ("tags", "ps", "show", "copy", "delete", "generate", "create", "head", "blob") if R.random() < 0.12}
    lineas = [json.dumps({"status": s}) for s in ("reading", "writing", "success")]
    if R.random() < 0.2:
        lineas.insert(R.randint(0, 3), json.dumps({"error": R.choice(["se cortó", 5])}))
    if R.random() < 0.1:
        lineas.insert(1, "")
    registro = R.choice([200, 404, 500])
    manifiesto = b'{"layers": []}'

    def responder(metodo, ruta, cuerpo):
        if ruta == "/api/tags": return malos.get("tags") or (200, json.dumps(tags).encode())
        if ruta == "/api/ps": return malos.get("ps") or (200, json.dumps(ps).encode())
        if ruta == "/api/show": return malos.get("show") or (200, json.dumps(show).encode())
        if ruta == "/api/copy": return malos.get("copy") or (200, b"")
        if ruta == "/api/delete": return malos.get("delete") or (200, b"")
        if ruta == "/api/generate": return malos.get("generate") or (200, json.dumps({"response": "ok", "cuerpo": json.loads(cuerpo)}).encode())
        if ruta == "/api/create": return malos.get("create") or (200, ("\n".join(lineas) + "\n").encode())
        if ruta.startswith("/api/blobs/"):
            if metodo == "HEAD": return malos.get("head") or (R.choice([200, 404]), b"")
            return malos.get("blob") or (201, b"")
        if ruta.startswith("/registro/"):
            if "/mio/" in ruta or registro == 404: return 404, b""
            return (registro, manifiesto if registro == 200 else b"")
        return 404, b""
    return responder, tags


def ejecutar(f):
    try:
        r = f()
        if hasattr(r, "__next__") or hasattr(r, "__iter__") and not isinstance(r, (list, dict)):
            pasos = []
            try:
                for p in r:
                    pasos.append(p)
            except Exception as e:
                pasos.append(("error", type(e).__name__, str(e)))
            r = pasos
        return ("ok", json.dumps(r, ensure_ascii=False, sort_keys=False))
    except Exception as e:
        return ("error", type(e).__name__, str(e))


gguf = os.path.join(TMP, "m.gguf")
with open(gguf, "wb") as f: f.write(b"GGUF" + os.urandom(3000))
falso = os.path.join(TMP, "falso.gguf")
with open(falso, "wb") as f: f.write(b"PK\x03\x04")

for _ in range(N):
    estado = R.getstate()
    ops = None
    res = []
    for mod in (gv, gn):
        R.setstate(estado)
        ESCENA["responder"], tags = escena()
        g = mod.GestorModelos(URL + R.choice(["", "/"]))
        nombres = [m.get("name", "x") for m in tags.get("models", [])] or ["nada"]
        pasos = []
        for _ in range(R.randint(1, 4)):
            op = R.choice(["instalados", "ficha", "copiar", "borrar", "actualizaciones", "cargados", "precargar", "descargar",
                           "probar", "uso_disco", "variante", "importar", "nombre"])
            n = R.choice(nombres)
            if op == "instalados": pasos.append(ejecutar(g.instalados))
            elif op == "ficha": pasos.append(ejecutar(lambda: g.ficha(n)))
            elif op == "copiar":
                d = R.choice(["copia:1", " ok ", "mal nombre", "", "../x"])
                pasos.append(ejecutar(lambda: g.copiar(n, d)))
            elif op == "borrar": pasos.append(ejecutar(lambda: g.borrar(n)))
            elif op == "actualizaciones": pasos.append(ejecutar(g.actualizaciones))
            elif op == "cargados": pasos.append(ejecutar(g.cargados))
            elif op == "precargar":
                k = R.choice([None, "5m", -1])
                pasos.append(ejecutar(lambda: g.precargar(n, {"num_ctx": 2048}, k)))
            elif op == "descargar": pasos.append(ejecutar(lambda: g.descargar(n)))
            elif op == "probar": pasos.append(ejecutar(lambda: g.probar({"model": n, "prompt": "hola"})))
            elif op == "uso_disco": pasos.append(ejecutar(g.uso_disco))
            elif op == "variante":
                args = (R.choice(["tutor:v1", "qwen3:14b", "qwen3", "mal nombre"]), R.choice(["qwen3:14b", "qwen3"]),
                        R.choice(["", "  ", "Eres un pirata"]), R.choice([None, {}, {"temperature": 0.5, "keep_alive": "5m"}, {"typical_p": 1}, {"num_ctx": "x"}]),
                        R.choice([None, [], [{"role": "user", "content": "hola"}, {"role": "otro", "content": "x"}, {"role": "assistant", "content": "  "}]]),
                        R.choice(["", "MIT"]))
                pasos.append(ejecutar(lambda: g.crear_variante(*args)))
            elif op == "importar":
                r = R.choice([gguf, falso, os.path.join(TMP, "no.gguf")])
                nm = R.choice(["mi-modelo", "mal nombre"])
                pasos.append(ejecutar(lambda: [p for p in g.importar_gguf(r, nm) if p.get("fase") != "subida" or p["hecho"] == p["total"]]))
            else:
                x = R.choice([" qwen3-tutor:v1 ", "", "con espacios", "../etc", ":solo-tag", "a\n", "a" * 130])
                pasos.append(ejecutar(lambda: mod._nombre(x)))
        res.append(pasos)
    cuentas["gestion"] = cuentas.get("gestion", 0) + 1
    if res[0] != res[1] and len(fallos) < 10:
        for i, (a, b) in enumerate(zip(*res)):
            if a != b:
                fallos.append({"paso": i, "viejo": str(a)[:1200], "nuevo": str(b)[:1200]})
                break
servidor.shutdown()
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
