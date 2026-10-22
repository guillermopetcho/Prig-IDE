"""Diferencial de ide_servicios.py: la versión de Python puro (REFERENCIA) contra la de ahora (Rust por prig_nativo).
Sobre el mismo árbol al azar y con las mismas operaciones (listar, buscar y reemplazar con expresiones de Python,
renombrar, duplicar, recientes, proyectos guardados, explorar carpetas), tienen que dar lo mismo: valores devueltos,
excepciones (tipo y texto) y cómo queda el disco. Las fechas de los proyectos guardados se comparan sin su valor.
Los errores de expresiones regulares mal escritas solo se comparan por tipo (el texto es el de Rust, ver
regex_py.rs).

    .venv/bin/python herramientas/diferencial_plataforma/ide.py [semilla] [vueltas]
"""
import json, os, random, re, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import TMP, viejo  # noqa: E402
os.environ["HOME"] = os.path.join(TMP, "casa")
os.environ["PRIG_HUB_DIR"] = os.path.join(TMP, "hub")
import file_manager as fmn, ide_servicios as idn  # noqa: E402
fmv, idv = viejo("file_manager"), viejo("ide_servicios")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 150
R = random.Random(semilla)
fallos, cuentas = [], {}
MUNDO = os.path.join(TMP, "mundo")
NOMBRES = ["a.py", "b.txt", "c.md", ".oculto", ".gitignore", "node_modules", "target", ".git", "x y.py", "Ab.py",
           "aB.py", "dir", "Dir", "sub", "ñ.txt", "z.bin", "datos.json", "README"]
LINEAS = ["def foo(x):", "    return x + 1", "foo = 3", "FOO = foo", "print(foo)", "# foo bar baz", "a{2} $x",
          "x = [1, 2]", "ñandú foo", "tab\there", "", "foofoo", "def bar(): pass", "foo\r", "uno\u2028dos", "x\x0cy"]


def construir(d, prof=0):
    os.makedirs(d, exist_ok=True)
    for n in R.sample(NOMBRES, R.randint(0, 6)):
        p = os.path.join(d, n)
        t = R.random()
        if t < 0.3 and prof < 2:
            construir(p, prof + 1)
        elif t < 0.37 and prof > 0:
            try: os.symlink(R.choice(["a.py", "nada", os.path.join(TMP, "externa")]), p)
            except OSError: pass
        else:
            with open(p, "wb") as f:
                if n.endswith(".bin"):
                    f.write(b"foo\x00bar")
                elif R.random() < 0.1:
                    f.write(b"foo \xff\xfe")
                else:
                    sep = R.choice(["\n", "\r\n", "\n"])
                    f.write(sep.join(R.choice(LINEAS) for _ in range(R.randint(0, 8))).encode())
            if R.random() < 0.1: os.chmod(p, 0o755)


def todo_el_disco():
    out = []
    for raiz, dirs, archivos in os.walk(TMP):
        dirs.sort()
        for n in sorted(dirs + archivos):
            p = os.path.join(raiz, n)
            if os.path.islink(p): out.append((p, "->", os.readlink(p)))
            elif os.path.isfile(p):
                try:
                    with open(p, "rb") as f: out.append((p, f.read(), oct(os.stat(p).st_mode)))
                except OSError as e: out.append((p, str(e), oct(os.stat(p).st_mode)))
            else: out.append((p, "dir"))
    return out


FECHA = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?")


def ejecutar(f, solo_tipo=False):
    try:
        r = ("ok", FECHA.sub("<fecha>", json.dumps(f(), ensure_ascii=False)))
    except Exception as e:
        if solo_tipo and "regular no válida" in str(e):
            return ("error", type(e).__name__, "Expresión regular no válida")
        r = ("error", type(e).__name__, str(e))
    return r


def comparar(nombre, a, b):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 12:
        for i, (x, y) in enumerate(zip(a[0], b[0])):
            if x != y:
                fallos.append({"prueba": nombre, "paso": i, "op": a[2][i] if len(a) > 2 else None, "viejo": str(x)[:3000], "nuevo": str(y)[:3000]})
                return
        da, db = a[1], b[1]
        fallos.append({"prueba": nombre, "disco_viejo": str([d for d in da if d not in db])[:700],
                       "disco_nuevo": str([d for d in db if d not in da])[:700], "ops": str(a[2])[:400]})


def limpiar():
    for raiz, dirs, archivos in os.walk(TMP):
        for n in archivos:
            p = os.path.join(raiz, n)
            if not os.path.islink(p):
                try: os.chmod(p, 0o600)
                except OSError: pass
    for n in os.listdir(TMP):
        p = os.path.join(TMP, n)
        if os.path.isdir(p) and not os.path.islink(p): shutil.rmtree(p)
        else: os.remove(p)


CONSULTAS = [("foo", False), ("FOO", False), ("o", False), ("a{2}", False), ("$x", False), ("ñ", False), ("x + 1", False),
             (r"\bfoo\b", True), (r"f(o+)", True), (r"(?P<n>\w+) =", True), (r"^def", True), (r"\)$", True), (r"a{2}", True),
             (r"\d+", True), (r"[[]", True), (r"foo|", True), (r"(\w+)\s*=\s*(\w+)", True), (r"x\Z", True), (r"[a-c]+", True),
             (r"(foo)(?P=n)", True), (r"(?P<n>foo)(?P=n)", True), (r"(", True), (r"\q", True), (r"{", True), (r"x{,2}y", True),
             (r"(?i)FOO", True), (r".*", True), ("", False)]
REEMPLAZOS = ["X", "", r"\1", r"[\1]", r"\g<0>!", r"\g<n>", r"\n", r"\q", r"\9", "\\", r"a\\b", r"\g<x>", r"\g<1", "$1", r"\0", r"\101"]


def vuelta():
    estado = R.getstate()
    res = []
    for fm_mod, ide_mod in ((fmv, idv), (fmn, idn)):
        R.setstate(estado)
        limpiar()
        externa = os.path.join(TMP, "externa")
        os.makedirs(os.path.join(externa, "sub"))
        for n, modo in (("leible.txt", 0o644), ("secreto.txt", 0), ("sub/x.py", 0o644)):
            with open(os.path.join(externa, n), "w") as f: f.write("foo\n")
            os.chmod(os.path.join(externa, n), modo)
        os.symlink("nada", os.path.join(externa, "roto"))
        construir(MUNDO)
        os.makedirs(os.path.join(TMP, "casa", R.choice(["Documentos", "Descargas", "Desktop"])), exist_ok=True)
        fm = fm_mod.FileManager(MUNDO)
        fm.base_dir = R.choice([MUNDO, MUNDO + "/"])
        fm.config_path = os.path.join(TMP, "cfg.json")
        cfg = R.choice([None, "", "[]", "null", "{}", json.dumps({"recent_workspaces": [MUNDO, "/no", MUNDO, 3][:R.randint(0, 4)],
                         "last_workspace": R.choice(["", MUNDO]), "saved_projects": R.choice([
                             [MUNDO, {"path": os.path.join(MUNDO, "dir"), "name": "D"}, {"path": "/no/x"}, {"name": "sin ruta"}],
                             [{"path": MUNDO, "source": "otro", "created_at": "ayer"}, MUNDO], "x", None, [{"path": MUNDO, "name": 5}]])})])
        if cfg is not None:
            with open(fm.config_path, "w") as f: f.write(cfg)
        ide = ide_mod.ServiciosIDE(fm)
        pasos, ops = [], []
        for _ in range(R.randint(1, 6)):
            op = R.choice(["listar", "buscar", "buscar", "reemplazar", "renombrar", "duplicar", "recientes", "anotar",
                           "olvidar", "proyectos", "guardar", "eliminar", "directorios"])
            ops.append(op)
            archivos = [os.path.join(r, n) for r, ds, fs in os.walk(MUNDO) for n in ds + fs]
            ruta = R.choice(archivos + ["", "../x", "/etc", "no.py", MUNDO]) if archivos else "no.py"
            if op == "listar":
                lim = R.choice([20000, 3, 0])
                pasos.append(ejecutar(lambda: ide.listar(lim)))
            elif op == "buscar":
                c, rx = R.choice(CONSULTAS)
                kw = dict(regex=rx, mayusculas=R.random() < 0.3, palabra=R.random() < 0.2,
                          incluir=R.choice(["", "*.py", "sub", "*.py, *.md", "sub/", "[ab]*"]), excluir=R.choice(["", "*.md", "dir"]),
                          limite=R.choice([5000, 2]))
                ops[-1] = (op, c, kw)
                pasos.append(ejecutar(lambda: ide.buscar(c, **kw), solo_tipo=True))
            elif op == "reemplazar":
                c, rx = R.choice(CONSULTAS)
                rep = R.choice(REEMPLAZOS)
                solo = R.choice([None, [ruta] if ruta else [], ["/etc/passwd"]])
                kw = dict(regex=rx, mayusculas=R.random() < 0.3, palabra=R.random() < 0.2, incluir=R.choice(["", "*.py"]), solo=solo)
                ops[-1] = (op, c, rep, kw)
                pasos.append(ejecutar(lambda: ide.reemplazar(c, rep, **kw), solo_tipo=True))
            elif op == "renombrar":
                dest = R.choice(["nuevo.py", "sub/otro.py", "dir", "../fuera", os.path.basename(ruta) if ruta else "x", "a.py", ruta + "/hijo" if ruta else "y"])
                ops[-1] = (op, ruta, dest)
                pasos.append(ejecutar(lambda: ide.renombrar(ruta, dest)))
            elif op == "duplicar":
                ops[-1] = (op, ruta)
                pasos.append(ejecutar(lambda: ide.duplicar(ruta)))
            elif op == "recientes": pasos.append(ejecutar(lambda: ide.recientes()))
            elif op == "anotar":
                r = R.choice([MUNDO, os.path.join(MUNDO, "dir"), "/no"])
                pasos.append(ejecutar(lambda: ide.anotar_reciente(r)))
            elif op == "olvidar": pasos.append(ejecutar(lambda: ide.olvidar_recientes()))
            elif op == "proyectos": pasos.append(ejecutar(lambda: ide.proyectos_guardados()))
            elif op == "guardar":
                r = R.choice([MUNDO, os.path.join(MUNDO, "dir"), "/no", "~", MUNDO + "/.", ruta])
                n = R.choice([None, "", "  Mi proyecto  ", "ñ"])
                pasos.append(ejecutar(lambda: ide.guardar_proyecto(r, n, R.choice(["biblioteca", "manual"]))))
            elif op == "eliminar":
                r = R.choice([MUNDO, "/no/x", "~", os.path.join(MUNDO, "dir")])
                pasos.append(ejecutar(lambda: ide.eliminar_proyecto_guardado(r)))
            else:
                r = R.choice([None, "", MUNDO, "~", "/no/existe", os.path.join(MUNDO, "sub"), TMP + "/../" + os.path.basename(TMP)])
                pasos.append(ejecutar(lambda: ide.listar_directorios(r)))
        disco = todo_el_disco()
        disco = [(d[0], FECHA.sub("<fecha>", d[1].decode("utf-8", "replace")) if isinstance(d[1], bytes) and d[0].endswith("cfg.json") else d[1], *d[2:]) for d in disco]
        res.append((pasos, disco, ops))
    comparar("ide", res[0], res[1])


for _ in range(N):
    vuelta()
limpiar()
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
