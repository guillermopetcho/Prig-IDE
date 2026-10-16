"""Diferencial de ai_engine/web_search_engine.py: Python puro (REFERENCIA, BeautifulSoup) contra la de ahora (Rust,
html5ever). Detectar si una pregunta pide internet, reordenar resultados, leer páginas BIEN FORMADAS y armar el
contexto (contra un servidor falso local, con la caché en una carpeta temporal) tienen que dar lo mismo.

    .venv/bin/python herramientas/diferencial_plataforma/web.py [semilla] [vueltas]
"""
import http.server, json, os, random, sys, tempfile, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import viejo  # noqa: E402
os.environ["NO_PROXY"] = "127.0.0.1"
from ai_engine import web_search_engine as wn  # noqa: E402
wv = viejo("web_search_engine", "ai_engine/web_search_engine.py")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
R = random.Random(semilla)
fallos, cuentas = [], {}
PREGUNTAS = ["¿cómo usar pandas?", "hola", "error de TypeError en python", "qué tal", "tutorial de docker", "abc",
             "Como Hacer una clase", "versión 3", "explícame los vs", "", "  x  ", "función lambda"]
TROZOS = ["<p>Hola <b>mundo</b></p>", "<h1>Título</h1>", "<h2> Sub </h2>", "<pre>código\n  x = 1</pre>", "<code>y()</code>",
          "<ul><li>uno</li><li>dos <code>z</code></li></ul>", "<script>malo()</script>", "<nav><p>menú</p></nav>",
          "<footer><li>pie</li></footer>", "<div>suelto</div>", "<p>  </p>", "<p>a &amp; b &lt;c&gt;</p>", "<!-- comentario -->",
          "<li><p>anidado</p></li>", "<h3>ñandú 😀</h3>", "<aside>al lado</aside>", "<p>" + "largo " * 300 + "</p>", "\n\n\n"]


def pagina():
    return "<html><head><title>t</title><style>x{}</style></head><body>" + "".join(R.choice(TROZOS) for _ in range(R.randint(0, 10))) + "</body></html>"


def ejecutar(f):
    try:
        return ("ok", json.dumps(f(), ensure_ascii=False))
    except Exception as e:
        return ("error", type(e).__name__, str(e))


def comparar(nombre, fv, fn, ctx):
    a, b = ejecutar(fv), ejecutar(fn)
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 10:
        fallos.append({"prueba": nombre, "ctx": str(ctx)[:400], "viejo": str(a)[:900], "nuevo": str(b)[:900]})


PAGINAS = {}


class Falso(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cuerpo = PAGINAS.get(self.path)
        if cuerpo is None:
            self.send_response(404); self.end_headers(); return
        b = cuerpo.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Falso)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"
ev, en = wv.WebSearchEngine(use_cache=False), wn.WebSearchEngine(use_cache=False)

for _ in range(N):
    q = R.choice(PREGUNTAS)
    comparar("pide_internet", lambda: ev.should_auto_search(q), lambda: en.should_auto_search(q), q)
    items = [{"title": R.choice(["Pandas groupby", "Docs", "x", "Python tutorial"]),
              "href": R.choice([f"{URL}/a", "https://docs.python.org/3/x", "https://geeksforgeeks.org/y", "", f"{URL}/b"]),
              "snippet": R.choice(["pandas usa groupby", "", "python docker"])} for _ in range(R.randint(0, 6))]
    comparar("reordenar", lambda: ev.score_and_rerank(q, items), lambda: en.score_and_rerank(q, items), (q, items))
    h = pagina()
    PAGINAS["/a"], PAGINAS["/b"] = h, pagina()
    comparar("leer_pagina", lambda: ev.fetch_url_content(f"{URL}/a"), lambda: en.fetch_url_content(f"{URL}/a"), h)
    locales = [i for i in items if i["href"].startswith(URL) or not i["href"]]
    if locales:
        ev.search = en.search = lambda query, prefer_official=True: [dict(x) for x in locales]
        comparar("contexto", lambda: ev.get_web_context(q), lambda: en.get_web_context(q), locales)
# la caché, en una carpeta temporal
d = tempfile.mkdtemp()
cv, cn = wv.WebSearchCache(os.path.join(d, "v")), wn.WebSearchCache(os.path.join(d, "n"))
for c in (cv, cn):
    c.set("Hola ", "ctx ñ", [{"a": 1}])
comparar("cache", lambda: cv.get("hola"), lambda: cn.get("hola"), "cache")
srv.shutdown()
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
