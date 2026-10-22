"""Diferencial de ai_engine/motor_moe.py: la versión de Python puro (REFERENCIA) contra la de ahora (Rust por
prig_nativo). Las funciones puras (estimar, traducir Ollama → OpenAI, traducir el flujo SSE → NDJSON de Ollama,
la respuesta completa, contexto y VRAM) con entradas al azar, y de punta a punta: Motor.post contra un llama-server
falso local que guarda los BYTES de cada cuerpo recibido; las dos versiones tienen que mandar los mismos bytes (de
ellos sale el prompt) y devolver las mismas líneas.

    .venv/bin/python herramientas/diferencial_plataforma/moe.py [semilla] [vueltas]
"""
import http.server, json, os, random, sys, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import PRIG, viejo  # noqa: E402
os.environ["NO_PROXY"] = "127.0.0.1"
from ai_engine import motor_moe as mn  # noqa: E402
mv = viejo("motor_moe", "ai_engine/motor_moe.py")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
R = random.Random(semilla)
fallos, cuentas = [], {}


def texto():
    return R.choice(["", "hola", "ñandú 😀", "x" * R.choice([10, 13000]), "a\nb", '"comillas"', " ", None, 5])


def mensaje():
    rol = R.choice(["system", "user", "assistant", "tool", "otro"])
    m = {"role": rol, "content": texto()}
    if rol == "assistant":
        if R.random() < 0.4: m["thinking"] = texto()
        if R.random() < 0.5:
            m["tool_calls"] = [{"function": {"name": R.choice(["consola", "ver_simbolo", None]),
                                             "arguments": R.choice([{"q": "x", "n": 1.5}, '{"a": 1}', None, {}])},
                                **({"id": "c9"} if R.random() < 0.3 else {})} for _ in range(R.randint(1, 3))]
    if rol == "tool":
        for k in ("tool_name", "name", "tool_call_id"):
            if R.random() < 0.4: m[k] = R.choice(["consola", "ver_simbolo", "otro", ""])
    return m


def pedido():
    p = {}
    if R.random() < 0.8: p["messages"] = [mensaje() for _ in range(R.randint(0, 5))]
    if R.random() < 0.3: p["prompt"] = texto()
    if R.random() < 0.3: p["system"] = texto()
    if R.random() < 0.7:
        o = {}
        for k in ("temperature", "top_k", "top_p", "min_p", "typical_p", "seed", "stop", "num_predict", "repeat_penalty", "num_ctx"):
            if R.random() < 0.3: o[k] = R.choice([0, 0.6, 20, -1, 512, "128", None, ["\n"], 1.0])
        p["options"] = o
    for k, vals in (("think", [True, False, None]), ("stream", [True, False, None]), ("format", ["json", {"type": "object"}, None, ""]),
                    ("tools", [[{"type": "function", "function": {"name": "consola", "parameters": {"type": "object"}}}], None, []]),
                    ("logprobs", [True, False]), ("top_logprobs", [3, 0, "2"]), ("prig_solo_codigo", [True, False]),
                    ("prig_perfil", ["preciso", "charla", "raro", None]), ("keep_alive", ["5m", 0, -1, None])):
        if R.random() < 0.35: p[k] = R.choice(vals)
    return p


def ejecutar(f):
    try:
        return ("ok", json.dumps(f(), ensure_ascii=False))
    except Exception as e:
        return ("error", type(e).__name__, str(e))


def comparar(nombre, fv, fn, ctx):
    a, b = ejecutar(fv), ejecutar(fn)
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 12:
        fallos.append({"prueba": nombre, "ctx": str(ctx)[:400], "viejo": str(a)[:900], "nuevo": str(b)[:900]})


def sse_al_azar():
    lineas = []
    for _ in range(R.randint(0, 8)):
        d = {}
        t = R.random()
        if t < 0.3: d["content"] = R.choice(["Hola", " mundo", "", "ñ", "El mar"])
        elif t < 0.5: d["reasoning_content"] = R.choice(["pien", "so", ""])
        elif t < 0.7: d["tool_calls"] = [{"index": R.choice([0, 1]), **({"id": "c1"} if R.random() < 0.5 else {}),
                                          "function": {**({"name": "buscar"} if R.random() < 0.5 else {}), "arguments": R.choice(['{"q":', ' "x"}', ""])}}]
        eleccion = {"index": 0, "delta": d}
        if R.random() < 0.15: eleccion["finish_reason"] = R.choice(["stop", "length", "tool_calls"])
        if R.random() < 0.1: eleccion["logprobs"] = {"content": [{"token": "a", "logprob": -0.1, "top_logprobs": [{"token": "b", "logprob": -2.0}]}]}
        trozo = {"choices": [eleccion]}
        if R.random() < 0.1: trozo["timings"] = {"prompt_n": 20, "prompt_ms": 400.5, "predicted_n": 5, "predicted_ms": 200}
        lineas.append("data: " + json.dumps(trozo))
        if R.random() < 0.1: lineas.append(R.choice(["", ": comentario", "data: {roto", "data: " + json.dumps({"error": {"message": "lleno"}}), "data: " + json.dumps({"error": "x"})]))
    if R.random() < 0.7: lineas.append("data: [DONE]")
    return lineas


for _ in range(N):
    p = pedido()
    for ruta in ("http://x/api/chat", "http://x/api/generate"):
        comparar("a_openai", lambda: mv.a_openai(ruta, p), lambda: mn.a_openai(ruta, p), p)
    comparar("estimar_tokens", lambda: mv.estimar_tokens(p), lambda: mn.estimar_tokens(p), p)
    comparar("prefijo_de", lambda: mv.prefijo_de(p), lambda: mn.prefijo_de(p), p)
    comparar("keep_alive", lambda: mv.segundos_keep_alive(p.get("keep_alive")), lambda: mn.segundos_keep_alive(p.get("keep_alive")), p)
    lineas = sse_al_azar()
    pref = R.choice([{}, {"content": "Hola", "thinking": "pien"}, {"content": "", "thinking": ""}])
    proy = R.choice([None, {"leidos": 100, "lectura_ms": 2000.0, "origen": "leido"}])
    for ruta in ("http://x/api/chat", "http://x/api/generate"):
        comparar("a_ollama", lambda: list(mv.a_ollama(ruta, iter(lineas), pref, 1.5, 32768, proy)),
                 lambda: list(mn.a_ollama(ruta, iter(lineas), pref, 1.5, 32768, proy)), lineas)
    resp = {"choices": R.choice([[{"finish_reason": "stop", "message": {"content": "Hola, sigo", "reasoning_content": R.choice(["r", None]),
                                   "tool_calls": R.choice([[{"id": "c", "function": {"name": "f", "arguments": "{}"}}], None, [{"function": {"arguments": "x"}}]])}}], []]),
            "timings": R.choice([{"predicted_n": 3, "predicted_ms": 30}, None])}
    comparar("completo", lambda: mv.a_ollama_completo("http://x/api/chat", resp, {"content": "Hola,", "thinking": ""}, 0.5, None, proy),
             lambda: mn.a_ollama_completo("http://x/api/chat", resp, {"content": "Hola,", "thinking": ""}, 0.5, None, proy), resp)
    tok = R.choice([0, 1000, 40000, 300000])
    comparar("contexto", lambda: (mv.contexto_para(tok), mv.lote_para(tok), mv.base_mb(tok), mv.base_mb(tok, True)),
             lambda: (mn.contexto_para(tok), mn.lote_para(tok), mn.base_mb(tok), mn.base_mb(tok, True)), tok)
    libre = R.choice([None, 0, 3000.0, 6100.0, 9000.5])
    ctx = R.choice([8192, 32768, 262144, 100000])
    comparar("vram", lambda: (mv.calientes_para(libre, ctx, R.random() < 2), mv.cabe_mtp(libre, ctx)),
             lambda: (mn.calientes_para(libre, ctx, True), mn.cabe_mtp(libre, ctx)), (libre, ctx))
    uso = [[R.randint(0, 3) for _ in range(6)] for _ in range(R.randint(0, 3))]
    glob_ = [list(R.sample(range(6), 6)) for _ in range(R.randint(0, 3))]
    comparar("lista_caliente", lambda: mv.lista_caliente(uso, glob_), lambda: mn.lista_caliente(uso, glob_), (uso, glob_))

# el GGUF de verdad, si está (solo lectura)
for g in filter(None, [mn.blob_del_modelo(), mn.modelo_para("q8")]):
    mv._tamanos.clear() if hasattr(mv, "_tamanos") else None
    comparar("tamanos_gguf", lambda: mv.tamanos_gguf(g), lambda: mn.tamanos_gguf(g), g)

# de punta a punta, contra un llama-server falso
CUERPOS = []


class Falso(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        crudo = self.rfile.read(int(self.headers["Content-Length"]))
        CUERPOS.append((self.path, crudo))
        cuerpo = json.loads(crudo)
        if self.path == "/apply-template":
            texto = "".join(f"<{m['role']}>{m['content']}</{m['role']}>" for m in cuerpo["messages"])
            return self._json({"prompt": texto})
        if self.path == "/completion":
            return self._json({"tokens_evaluated": 77, "timings": {"prompt_ms": 2000.0}})
        if self.path.startswith("/slots/0"):
            return self._json({"n_saved": 1})
        if ESC["error"]:
            return self._json({"error": {"message": "fallo", "type": "otro"}}, 500)
        if not cuerpo.get("stream"):
            return self._json({"choices": [{"finish_reason": "stop", "message": {"content": "listo"}}], "timings": {"predicted_n": 2}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for l in ESC["lineas"]:
            datos = (l + "\n\n").encode()
            self.wfile.write(f"{len(datos):x}\r\n".encode() + datos + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")

    def do_GET(self):
        self._json({"capas": []})

    def _json(self, d, estado=200):
        b = json.dumps(d).encode()
        self.send_response(estado)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


ESC = {"lineas": [], "error": False}
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Falso)
threading.Thread(target=srv.serve_forever, daemon=True).start()
import tempfile  # noqa: E402
tmp = tempfile.mkdtemp()
mv.LIB, mv.SERVIDOR, mv.LISTA = mn.LIB, mn.SERVIDOR, mn.LISTA   # la referencia vive en una carpeta temporal
for mod in (mv, mn):
    mod.CARPETA_PROYECTOS = tmp
for _ in range(N // 3):
    p = pedido()
    p.setdefault("messages", [{"role": "user", "content": "hola"}])
    if R.random() < 0.3:
        p["messages"] = [{"role": "system", "content": "s"}, {"role": "user", "content": "P" * 13000}, {"role": "user", "content": "¿qué?"}]
    ESC["lineas"], ESC["error"] = sse_al_azar(), R.random() < 0.1
    res_ = []
    for mod in (mv, mn):
        for f in os.listdir(tmp): os.remove(os.path.join(tmp, f))
        CUERPOS.clear()
        motor = mod.Motor(ajustes=lambda: {"contexto": 32768, "cache_gb": 5})
        motor._puerto = srv.server_address[1]
        motor._vigia = threading.Thread()
        motor.asegurar = lambda: 0.0
        motor._registro = lambda t: None
        try:
            r = motor.post("http://x/api/chat", p)
            lineas = [l.decode() for l in r.iter_lines()] if r.status_code == 200 else r.json()
            res_.append((r.status_code, lineas, list(CUERPOS), motor._activas))
        except Exception as e:
            res_.append(("error", type(e).__name__, str(e), list(CUERPOS)))
    cuentas["punta_a_punta"] = cuentas.get("punta_a_punta", 0) + 1
    if res_[0] != res_[1] and len(fallos) < 12:
        a, b = res_
        detalle = {}
        if len(a) == len(b) == 4 and a[0] != "error" and b[0] != "error":
            if a[0] != b[0]: detalle["estado"] = (a[0], b[0])
            if a[1] != b[1]:
                for i, (x, y) in enumerate(zip(a[1], b[1])):
                    if x != y:
                        detalle["linea"] = (i, x[:600], y[:600]); break
                else:
                    detalle["lineas"] = (len(a[1]), len(b[1]))
            if a[2] != b[2]:
                for i, (x, y) in enumerate(zip(a[2], b[2])):
                    if x != y:
                        detalle["cuerpo"] = (i, x[0], y[0], x[1][-400:].decode(), y[1][-400:].decode()); break
                else:
                    detalle["cuerpos"] = ([c[0] for c in a[2]], [c[0] for c in b[2]])
            if a[3] != b[3]: detalle["activas"] = (a[3], b[3])
        else:
            detalle = {"viejo": str(a)[:600], "nuevo": str(b)[:600]}
        fallos.append({"prueba": "punta_a_punta", "detalle": detalle})
srv.shutdown()
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
