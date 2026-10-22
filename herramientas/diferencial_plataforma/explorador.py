"""Diferencial de explorador.py: la versión de Python puro (REFERENCIA) contra la de ahora (Rust por prig_nativo).
Sobre la misma carpeta personal al azar (con libros, carpetas ocultas o ignoradas, enlaces que salen afuera o hacen
bucles), las mismas operaciones tienen que dar lo mismo: valores devueltos y excepciones (tipo y texto).

    .venv/bin/python herramientas/diferencial_plataforma/explorador.py [semilla] [vueltas]
"""
import json, os, random, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import TMP, viejo  # noqa: E402
CASA = os.path.join(TMP, "casa")
os.environ["HOME"] = CASA
import explorador as en  # noqa: E402
ev = viejo("explorador")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
R = random.Random(semilla)
fallos, cuentas = [], {}
NOMBRES = ["Libro de Python.pdf", "machine learning.EPUB", "notas.md", "a.txt", "b.TeX", "x.djvu", "c.ipynb", "d.rst",
           "foto.png", ".oculto.pdf", "Descargas", "Documentos", "Desktop", "node_modules", "snap", ".config", "sub",
           "Sub", "ñandú.pdf", "Python avanzado.pdf", "data.csv", ".pdf", "z" * 30 + ".md"]


def construir(d, prof=0):
    os.makedirs(d, exist_ok=True)
    for n in R.sample(NOMBRES, R.randint(0, 7)):
        p = os.path.join(d, n)
        t = R.random()
        if t < 0.35 and prof < 3 and "." not in n[1:]:
            construir(p, prof + 1)
        elif t < 0.45:
            try: os.symlink(R.choice(["/", "..", "a.txt", "nada", p, "/etc", TMP]), p)
            except OSError: pass
        else:
            with open(p, "wb") as f: f.write(b"x" * R.choice([0, 10, 5000, 1048576 // 3]))
            os.utime(p, (R.randrange(10**9), R.randrange(10**9) + R.random()))


def ejecutar(f):
    try:
        return ("ok", json.dumps(f(), ensure_ascii=False))
    except Exception as e:
        return ("error", type(e).__name__, str(e))


def vuelta():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    construir(CASA)
    ws = R.choice([None, os.path.join(TMP, "ws"), CASA, os.path.join(CASA, "sub")])
    if ws and ws.endswith("ws"): construir(ws)
    ops = []
    for _ in range(R.randint(1, 5)):
        op = R.choice(["listar", "listar", "buscar", "atajos", "permitida"])
        dirs = [r for r, _, _ in os.walk(CASA)]
        ruta = R.choice(dirs + [None, "", "~", "~/Descargas", "/", "/etc", TMP, os.path.join(CASA, "no"),
                                os.path.join(CASA, "a.txt"), CASA + "/sub/..", "relativa"])
        if op == "listar": ops.append((op, ruta, R.random() < 0.4))
        elif op == "buscar": ops.append((op, R.choice(["python", "PYTHON avanzado", "", "  ", "pdf", "ñ", "learning machine", "z"]), ruta, R.choice([120, 1])))
        else: ops.append((op, ruta))
    res = []
    for mod in (ev, en):
        e = mod.Explorador(ws)
        pasos = []
        for op in ops:
            if op[0] == "listar": pasos.append(ejecutar(lambda: e.listar(op[1], recursivo=op[2])))
            elif op[0] == "buscar": pasos.append(ejecutar(lambda: e.buscar(op[1], op[2], op[3])))
            elif op[0] == "atajos": pasos.append(ejecutar(lambda: e.atajos()))
            else: pasos.append(ejecutar(lambda: e.permitida(op[1]) if op[1] is not None else None))
        res.append(pasos)
    cuentas["explorador"] = cuentas.get("explorador", 0) + 1
    if res[0] != res[1] and len(fallos) < 10:
        for i, (a, b) in enumerate(zip(*res)):
            if a != b:
                fallos.append({"op": str(ops[i]), "viejo": str(a)[:800], "nuevo": str(b)[:800]})
                break


for _ in range(N):
    vuelta()
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
