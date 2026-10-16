"""Diferencial de file_manager.py: la versión de Python puro (REFERENCIA) contra la de ahora (Rust por prig_nativo).
Sobre el mismo árbol de archivos al azar (con enlaces, nombres raros, archivos sin permiso, bytes no UTF-8) y con
las mismas operaciones y rutas (relativas, absolutas, con `..`, vacías, con NUL), tienen que dar lo mismo: valores
devueltos, lo que se imprime y cómo queda el disco. También cuadernos deformes en read_notebook_structured.

    .venv/bin/python herramientas/diferencial_plataforma/archivos.py [semilla] [vueltas]
"""
import contextlib, io, json, os, random, shutil, stat, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import TMP, viejo  # noqa: E402
os.environ["PRIG_HUB_DIR"] = os.path.join(TMP, "hub")
import file_manager as fn  # noqa: E402
fv = viejo("file_manager")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
R = random.Random(semilla)
fallos, cuentas = [], {}
RAIZ = os.path.join(TMP, "mundo")
NOMBRES = ["a.py", "B.txt", "c", "ñ.md", ".oculto", ".gitignore", ".env.example", "node_modules", "target", "x y",
           "Ab", "aB", "nb.ipynb", "NB.IPYNB", "..raro", ".ipynb", "dir", "Dir", "ΣΑΣ", "İx", "z" * 40, "é"]


def fichero_al_azar(ruta):
    t = R.random()
    if t < 0.3:
        datos = R.choice([b"", b"hola\n", b"a\r\nb\rc\n", b"\xff\xfeA", "ñandú 😀".encode(), b"\xed\xa0\x80x", b"\xe2\x82", b"x\x00y"])
    elif t < 0.6:
        datos = json.dumps(cuaderno(), ensure_ascii=R.random() < 0.5).encode()
    else:
        datos = bytes(R.randrange(256) for _ in range(R.randint(0, 30)))
    with open(ruta, "wb") as f:
        f.write(datos)


def construir(dir_, prof=0):
    os.makedirs(dir_, exist_ok=True)
    for n in R.sample(NOMBRES, R.randint(0, 6)):
        p = os.path.join(dir_, n)
        t = R.random()
        if t < 0.35 and prof < 3:
            construir(p, prof + 1)
        elif t < 0.45 and prof > 0:
            try: os.symlink(R.choice(["..", "/etc", "a.py", "nada", "/tmp"]), p)
            except OSError: pass
        else:
            fichero_al_azar(p)
            if R.random() < 0.05: os.chmod(p, 0)


def valor(prof=0):
    t = R.random()
    if prof > 2 or t < 0.35:
        return R.choice([None, True, 0, 3, 1.5, -0.0, "", "x", "a\nb", "attachment:img.png", ["s", "t"], [1], {}])
    if t < 0.65:
        return [valor(prof + 1) for _ in range(R.randint(0, 3))]
    return {R.choice(["text/html", "text/plain", "image/png", "image/jpg", "k", "text"]): valor(prof + 1) for _ in range(R.randint(0, 3))}


def salida():
    o = {}
    if R.random() < 0.9: o["output_type"] = R.choice(["stream", "execute_result", "display_data", "error", "otro", 3])
    for k in ["text", "name", "data", "ename", "evalue", "traceback"]:
        if R.random() < 0.5:
            if k == "data" and R.random() < 0.6:
                o[k] = {m: R.choice([["<b>", "x</b>"], "plano", ["a", 1], 5]) for m in R.sample(["text/html", "text/plain", "image/png", "image/svg+xml", "image/gif"], R.randint(0, 3))}
            elif k in ("text", "traceback") and R.random() < 0.6:
                o[k] = R.choice([["l1\n", "l2"], "texto", ["a", None]])
            else:
                o[k] = valor()
    return o if R.random() < 0.95 else valor()


def celda():
    c = {}
    if R.random() < 0.8: c["cell_type"] = R.choice(["code", "markdown", "raw", 1])
    if R.random() < 0.9: c["source"] = R.choice([["a = 1\n", "b"], "x = 2", ["![i](attachment:img.png)"], valor()])
    if R.random() < 0.3:
        c["attachments"] = R.choice([{"img.png": {"image/png": R.choice(["QUJD\n", [" QU", "JD\r\n "], 5])}}, {}, valor()])
    if R.random() < 0.7: c["outputs"] = [salida() for _ in range(R.randint(0, 3))] if R.random() < 0.9 else valor()
    if R.random() < 0.6: c["execution_count"] = R.choice([None, 1, 7, "x"])
    return c if R.random() < 0.95 else valor()


def cuaderno():
    t = R.random()
    if t < 0.1: return valor()
    return {"cells": [celda() for _ in range(R.randint(0, 4))] if R.random() < 0.9 else valor(), "nbformat": 4}


def ruta_al_azar(base):
    t = R.random()
    candidatos = []
    for raiz, dirs, archivos in os.walk(base):
        for n in dirs + archivos:
            candidatos.append(os.path.join(raiz, n))
    if t < 0.4 and candidatos:
        p = R.choice(candidatos)
        return os.path.relpath(p, base) if R.random() < 0.4 else p
    return R.choice(["", "nuevo.py", "sub/nuevo.txt", "../fuera.txt", "/etc/passwd", "/", base, base + "/",
                     base + "/../mundo/a.py", "./a.py", "a.py/", "x\x00y", "~/a", "dir/../a.py", "//" + base.lstrip("/"),
                     os.path.join(TMP, "otra", "q.py"), os.path.join(TMP, "hub", "propios", "p.md"), "ñ/😀.py"])


def ejecutar(f):
    s = io.StringIO()
    with contextlib.redirect_stdout(s):
        try:
            r = ("ok", json.dumps(f(), ensure_ascii=False))
        except Exception as e:
            r = ("error", type(e).__name__, str(e))
    return r, s.getvalue()


def disco(base):
    out = []
    for raiz, dirs, archivos in os.walk(TMP):
        dirs.sort()
        for n in sorted(dirs + archivos):
            p = os.path.join(raiz, n)
            if os.path.islink(p):
                out.append((p, "->", os.readlink(p)))
            elif os.path.isfile(p):
                try:
                    with open(p, "rb") as f: out.append((p, f.read()))
                except OSError as e: out.append((p, str(e)))
            else:
                out.append((p, "dir"))
    return out


def comparar(nombre, a, b):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 12:
        # el primer paso distinto (o el disco)
        if isinstance(a, tuple) and len(a) == 2 and isinstance(a[0], list):
            for i, (x, y) in enumerate(zip(a[0], b[0])):
                if x != y:
                    fallos.append({"prueba": nombre, "paso": i, "viejo": str(x)[:900], "nuevo": str(y)[:900]})
                    return
            fallos.append({"prueba": nombre, "disco_viejo": str([d for d in a[1] if d not in b[1]])[:900],
                           "disco_nuevo": str([d for d in b[1] if d not in a[1]])[:900]})
            return
        fallos.append({"prueba": nombre, "viejo": str(a)[:900], "nuevo": str(b)[:900]})


def limpiar():
    for raiz, dirs, archivos in os.walk(TMP):
        for n in dirs + archivos:
            p = os.path.join(raiz, n)
            if not os.path.islink(p):
                try: os.chmod(p, 0o700 if os.path.isdir(p) else 0o600)
                except OSError: pass
    for n in os.listdir(TMP):
        p = os.path.join(TMP, n)
        if os.path.isdir(p) and not os.path.islink(p): shutil.rmtree(p)
        else: os.remove(p)


def vuelta():
    estado = R.getstate()
    ops = None
    res = []
    for mod in (fv, fn):
        R.setstate(estado)
        limpiar()
        construir(RAIZ)
        os.makedirs(os.path.join(TMP, "otra"), exist_ok=True)
        base = R.choice([RAIZ, RAIZ + "/", os.path.join(RAIZ, "dir")])
        fm = mod.FileManager(RAIZ)
        fm.base_dir = base
        fm.config_path = os.path.join(TMP, "config.json")
        pasos = []
        for _ in range(R.randint(1, 8)):
            op = R.choice(["arbol", "leer", "leer", "escribir", "crear", "borrar", "permitida", "resolver", "cuaderno"])
            p = ruta_al_azar(RAIZ)
            if op == "arbol":
                md = R.choice([6, 1, 2, 0])
                pasos.append(ejecutar(lambda: fm.get_file_tree(R.choice([None, p, ""]), max_depth=md)))
            elif op == "leer": pasos.append(ejecutar(lambda: fm.read_file(p)))
            elif op == "escribir":
                c = R.choice(["", "x\r\ny", "ñ", "\ud800", None, "a" * 50])
                pasos.append(ejecutar(lambda: fm.write_file(p, c)))
            elif op == "crear":
                d = R.random() < 0.5
                pasos.append(ejecutar(lambda: fm.create_item(p, d)))
            elif op == "borrar": pasos.append(ejecutar(lambda: fm.delete_item(p)))
            elif op == "permitida": pasos.append(ejecutar(lambda: fm.is_path_allowed(p) if p and "\x00" not in p else None))
            elif op == "resolver": pasos.append(ejecutar(lambda: fm.resolve(p)))
            else:
                texto = json.dumps(cuaderno()) if R.random() < 0.9 else R.choice(["", "{", "[1]", "NaN"])
                pasos.append(ejecutar(lambda: fm.read_notebook_structured(texto, p)))
        res.append((pasos, disco(RAIZ)))
    comparar("archivos", res[0], res[1])


def configuracion():
    cfg = os.path.join(TMP, "cfg.json")
    estado = R.getstate()
    res = []
    for mod in (fv, fn):
        R.setstate(estado)
        limpiar()
        os.makedirs(os.path.join(TMP, "w1"))
        c = R.choice([None, "", "{", "[]", json.dumps({"last_workspace": os.path.join(TMP, "w1"), "otra": "ñ"}),
                      json.dumps({"last_workspace": os.path.join(TMP, "no")}), json.dumps({"last_workspace": 3})])
        if c is not None:
            with open(cfg, "w") as f: f.write(c)
        fm = mod.FileManager(os.path.join(TMP, "w1"))
        fm.config_path = cfg
        pasos = [ejecutar(lambda: fm._load_last_workspace() if fm._load_last_workspace() != os.getcwd() else "cwd")]
        for _ in range(R.randint(1, 3)):
            p = R.choice([os.path.join(TMP, "w1"), os.path.join(TMP, "w1") + "/", os.path.join(TMP, "no"), "~", "~/",
                          "~nadie_existe/x", TMP + "/./w1/..", "", "w1"])
            pasos.append(ejecutar(lambda: fm.set_base_dir(p)))
            pasos.append(ejecutar(lambda: fm.base_dir))
        try:
            with open(cfg, "rb") as f: pasos.append(f.read())
        except OSError: pasos.append(None)
        res.append(pasos)
    comparar("configuracion", res[0], res[1])


for _ in range(N):
    vuelta()
    configuracion()
limpiar()
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
