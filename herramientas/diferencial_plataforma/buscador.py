"""Diferencial de buscador_modelos.py: la versión de Python puro (REFERENCIA, con requests) contra la de ahora (Rust
por prig_nativo, con reqwest). Las páginas de ollama.com y los JSON de Hugging Face y ModelScope de las pruebas
(con mutaciones al azar), nombres de archivo, referencias, enlaces pegados y las peticiones contra un servidor falso
local (búsqueda, variantes, fichas, comprobar en el registro con 200/4xx/5xx) tienen que dar lo mismo: valores y
excepciones (tipo y texto). Nunca la red.

    .venv/bin/python herramientas/diferencial_plataforma/buscador.py [semilla] [vueltas]
"""
import http.server, json, os, random, sys, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import PRIG, viejo  # noqa: E402
for v in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
    os.environ.pop(v, None)
os.environ["NO_PROXY"] = "127.0.0.1"
import buscador_modelos as bn  # noqa: E402
bv = viejo("buscador_modelos")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
R = random.Random(semilla)
fallos, cuentas = [], {}
DATOS = os.path.join(PRIG, "backend", "tests", "datos_buscador")


def leer(n):
    with open(os.path.join(DATOS, n), encoding="utf-8") as f:
        return f.read()


HTML_BUSQUEDA, HTML_TAGS = leer("ollama_busqueda.html"), leer("ollama_etiquetas.html")
HF_BUSQUEDA, HF_REPO = json.loads(leer("hf_busqueda.json")), json.loads(leer("hf_repo.json"))
MS_BUSQUEDA, MS_REPO = json.loads(leer("modelscope_busqueda.json")), json.loads(leer("modelscope_repo.json"))
ESCENA = {"responder": lambda m, ruta, q, cuerpo: (404, b"", {})}


class Manejador(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _atender(self):
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo) if largo else b""
        ruta, _, q = self.path.partition("?")
        codigo, salida, cab = ESCENA["responder"](self.command, ruta, q, cuerpo)
        if not isinstance(salida, bytes):
            salida = json.dumps(salida).encode()
        self.send_response(codigo)
        for k, v in cab.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(salida)))
        self.end_headers()
        self.wfile.write(salida)

    do_GET = do_PUT = _atender

    def log_message(self, *a):
        pass


servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{servidor.server_address[1]}"
for mod in (bv, bn):
    for c in (mod.Ollama, mod.HuggingFace, mod.ModelScope):
        c.BASE = URL
    registro_real = mod.registro_de
    mod.registro_de = (lambda real: lambda ref: (f"{URL}/{real(ref)[0].split('//', 1)[1]}",) + tuple(real(ref)[1:]))(registro_real)


def mutar_texto(t):
    if R.random() < 0.5:
        return t
    c = list(t)
    for _ in range(R.randint(1, 20)):
        i = R.randrange(len(c) + 1)
        op = R.random()
        if op < 0.4 and c: del c[min(i, len(c) - 1)]
        else: c.insert(i, R.choice(list("<>/\"' abcQ_K-M0123456789.&;#\n•") + ["&amp;", "Pulls", " Tags", "GB", "context window", "Text, Image input"]))
    return "".join(c)


def mutar(v, prof=0):
    if R.random() < 0.15:
        return R.choice([None, "", 0, 3.5, [], {}, "x", ["vision"], True])
    if isinstance(v, dict):
        return {k: mutar(x, prof + 1) for k, x in v.items() if R.random() > 0.08}
    if isinstance(v, list):
        return [mutar(x, prof + 1) for x in v if R.random() > 0.08]
    if isinstance(v, str) and R.random() < 0.2:
        return mutar_texto(v)
    return v


def ejecutar(f):
    try:
        return ("ok", json.dumps(f(), ensure_ascii=False))
    except Exception as e:
        return ("error", type(e).__name__, str(e))


def comparar(nombre, fv, fn_, ctx):
    a, b = ejecutar(fv), ejecutar(fn_)
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 14:
        fallos.append({"prueba": nombre, "ctx": str(ctx)[:300], "viejo": str(a)[:900], "nuevo": str(b)[:900]})


NOMBRES = ["Qwen3-8B-Q4_K_M.gguf", "Qwen3-8B-UD-Q4_K_XL.gguf", "qwen2.5-0.5b-instruct-q4_k_m.gguf", "M-BF16.gguf", "gpt-oss-20b-MXFP4.gguf",
           "Q4_K_M/Qwen3-235B-A22B-Q4_K_M-00001-of-00003.gguf", "README.gguf", "x.GGUF", "mmproj-F16.gguf", "a-IQ4_XS.gguf\n", "q8_0.gguf",
           "Llama-TQ1_0.gguf", "m-Q4_0_4_4.gguf", "-q4_k.gguf", "a.Q5_K_S.gguf", "notes.md", "nvfp4.gguf", "x-NVFP4.gguf", "x-F32-00002-of-00002.gguf"]
TEXTOS = ["https://ollama.com/library/qwen3", "ollama.com/library/qwen3:8b", "https://ollama.com/library/qwen3/tags",
          "https://huggingface.co/unsloth/Qwen3-8B-GGUF/blob/main/Qwen3-8B-UD-Q4_K_XL.gguf", "hf.co/unsloth/Qwen3-8B-GGUF:Q8_0",
          "  ollama run hf.co/bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K_M ", "https://modelscope.cn/models/Qwen/X-GGUF/files",
          "https://www.modelscope.cn/models/Qwen/X/file/view/master/x-q4_k_m.gguf", "unsloth/Qwen3-8B-GGUF", "Qwen/Qwen2.5:q2_k",
          "ollama pull gemma3:4b", "Qwen3   8B", "https://ollama.com/search?q=deepseek&o=newest", "https://huggingface.co/models?search=qwen3%20coder",
          "", "   ", "https://ollama.com/", "https://huggingface.co/unsloth", "https://ollama.com/library/a/b/c", "https://ollama.com/blog",
          "x" * 500, "???", "https://huggingface.co/a/b%2F..%2Fc", "<qwen3>", "'hf.co/a/b'", "https://hf.co/api/models/a/b", "ñandú",
          "HTTPS://OLLAMA.COM/Library/Qwen3", "https://huggingface.co/a/b?x=1#y", "a/b/c", "qwen3:8b:extra", "https://ollama.com/u/m:t/tags"]

for _ in range(N):
    # piezas puras
    n = R.choice(NOMBRES)
    comparar("cuantizacion_de", lambda: bv.cuantizacion_de(n), lambda: bn.cuantizacion_de(n), n)
    t = R.choice(TEXTOS)
    if R.random() < 0.3: t = mutar_texto(t)
    comparar("interpretar", lambda: bv.interpretar(t), lambda: bn.interpretar(t), t)
    comparar("validar_ref", lambda: bv.validar_ref(t), lambda: bn.validar_ref(t), t)
    comparar("clave", lambda: bv._clave(t), lambda: bn._clave(t), t)
    comparar("parecido", lambda: bv._parecido(t, n), lambda: bn._parecido(t, n), (t, n))
    x = R.choice(["105.3K", "2.1M", "666", "1,234", "1.2.3K", "", "5 B", "5.2GB", "523MB", "mucho", "1.5 tb", "3k"])
    comparar("numero", lambda: bv._numero(x), lambda: bn._numero(x), x)
    comparar("bytes", lambda: bv._bytes(x), lambda: bn._bytes(x), x)
    pag = mutar_texto(HTML_BUSQUEDA) if R.random() < 0.7 else HTML_BUSQUEDA
    comparar("analizar_busqueda", lambda: bv.Ollama.analizar_busqueda(pag), lambda: bn.Ollama.analizar_busqueda(pag), "busqueda")
    tags = mutar_texto(HTML_TAGS)
    ruta = R.choice(["library/qwen3", "huihui_ai/dolphin3-r1", "library/x"])
    comparar("analizar_etiquetas", lambda: bv.Ollama.analizar_etiquetas(tags, ruta), lambda: bn.Ollama.analizar_etiquetas(tags, ruta), ruta)
    m = mutar(R.choice(HF_BUSQUEDA))
    comparar("hf_normalizar", lambda: bv.HuggingFace.normalizar(m), lambda: bn.HuggingFace.normalizar(m), m)
    ms = mutar(R.choice(MS_BUSQUEDA["Data"]["Model"]["Models"]))
    comparar("ms_normalizar", lambda: bv.ModelScope.normalizar(ms), lambda: bn.ModelScope.normalizar(ms), ms)
    archivos = [(R.choice(NOMBRES), R.choice([0, 5, 10**9, 2.5])) for _ in range(R.randint(0, 8))]
    comparar("agrupar", lambda: bv.agrupar_gguf(archivos, "hf.co/a/b"), lambda: bn.agrupar_gguf(archivos, "hf.co/a/b"), archivos)

    # con el servidor falso
    codigo = R.choice([200, 200, 200, 404, 401, 400, 500])
    contenido = {
        "/search": mutar_texto(HTML_BUSQUEDA).encode() + (b'<li hx-get="/search?page=2' if R.random() < 0.5 else b""),
        "tags": mutar_texto(HTML_TAGS).encode(),
        "/api/models": mutar(HF_BUSQUEDA), "repo": mutar(HF_REPO), "dolphin": mutar(MS_BUSQUEDA), "files": mutar(MS_REPO),
        "manifests": R.choice([b'{"layers": [{"mediaType": "a.model", "size": 10}, {"mediaType": "x.projector", "size": 2}]}',
                               b'{"error": "sharded"}', b"no json", b'{"layers": null}', b'["x"]']),
        "ficha_ms": {"Data": mutar(MS_BUSQUEDA["Data"]["Model"]["Models"][3])},
        "ficha_ol": b'<meta name="description" content="Hola &amp; adi&oacute;s"><span class="inline-flex a">tools</span><span class="inline-flex">8b</span>',
    }
    link = R.choice(["", f'<{URL}/api/models?filter=gguf&cursor=abc>; rel="next"', '<https://otro/x>; rel="next"'])
    cuerpo_error = R.choice([b"", b'{"error":"x"}', b"does not exist"])
    ficha_hf = R.choice(HF_BUSQUEDA)

    def responder(metodo, ruta, q, cuerpo, codigo=codigo, contenido=contenido, link=link, cuerpo_error=cuerpo_error, ficha_hf=ficha_hf):
        if codigo != 200:
            return codigo, cuerpo_error, {}
        if ruta == "/search": return 200, contenido["/search"], {}
        if ruta.endswith("/tags"): return 200, contenido["tags"], {}
        if ruta == "/api/models": return 200, contenido["/api/models"], {"Link": link} if link else {}
        if ruta.startswith("/api/models/"):
            return 200, (contenido["repo"] if "blobs=true" in q else ficha_hf), {}
        if ruta == "/api/v1/dolphin/models": return 200, contenido["dolphin"], {}
        if ruta.endswith("/repo/files"): return 200, contenido["files"], {}
        if ruta.startswith("/api/v1/models/"): return 200, contenido["ficha_ms"], {}
        if "/manifests/" in ruta: return 200, contenido["manifests"], {}
        return 200, contenido["ficha_ol"], {}
    ESCENA["responder"] = responder
    op = R.choice(["ollama_buscar", "ollama_var", "hf_buscar", "hf_var", "ms_buscar", "ms_var", "comprobar", "ficha"])
    for mod in (bv, bn):
        mod._cache = mod.Cache()
    if op == "ollama_buscar":
        a = (R.choice(["", "qwen", "ñ y"]), R.choice(["relevancia", "recientes", "otro"]), R.choice([None, "tools", "x"]), R.choice([1, 2]))
        comparar(op, lambda: bv.Ollama().buscar(*a), lambda: bn.Ollama().buscar(*a), a)
    elif op == "ollama_var":
        nom = R.choice(["qwen3", "huihui_ai/dolphin3-r1", "mal nombre"])
        comparar(op, lambda: bv.Ollama().variantes(nom), lambda: bn.Ollama().variantes(nom), nom)
    elif op == "hf_buscar":
        import base64
        pag = R.choice([None, base64.urlsafe_b64encode(f"{URL}/api/models?filter=gguf&cursor=abc".encode()).decode(), "%%%", "aHR0cDovL3g="])
        a = (R.choice(["", "qwen3"]), R.choice(["tendencia", "relevancia", "x"]), pag)
        comparar(op, lambda: bv.HuggingFace().buscar(*a), lambda: bn.HuggingFace().buscar(*a), a)
    elif op == "hf_var":
        repo = R.choice(["unsloth/Qwen3-8B-GGUF", "../x"])
        comparar(op, lambda: bv.HuggingFace().variantes(repo), lambda: bn.HuggingFace().variantes(repo), repo)
    elif op == "ms_buscar":
        a = (R.choice(["", "qwen"]), R.choice(["descargas", "actualizados", "relevancia"]), R.choice([1, 2, 0]))
        comparar(op, lambda: bv.ModelScope().buscar(*a), lambda: bn.ModelScope().buscar(*a), a)
    elif op == "ms_var":
        repo = R.choice(["Qwen/Qwen2.5-0.5B-Instruct-GGUF", "a b"])
        comparar(op, lambda: bv.ModelScope().variantes(repo), lambda: bn.ModelScope().variantes(repo), repo)
    elif op == "comprobar":
        r = R.choice(["hf.co/a/b-GGUF:Q4_K_M", "qwen3:8b", "modelscope.cn/a/b:q4_k_m", "mal ref"])
        comparar(op, lambda: bv.comprobar(r), lambda: bn.comprobar(r), r)
    else:
        a = (R.choice(["huggingface", "modelscope", "ollama", "otra"]), R.choice(["a/b", "qwen3", "huihui_ai/dolphin3-r1", "../x"]))
        comparar(op, lambda: bv.ficha_repo(*a), lambda: bn.ficha_repo(*a), a)
servidor.shutdown()
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
