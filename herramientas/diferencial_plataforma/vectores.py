"""Diferencial de indice_semantico.py (puntuar, _coseno, _desempaquetar): Python puro (REFERENCIA) contra Rust.
Índices al azar en una base temporal (empates, ids repetidos en la petición, ids que no están, otra dimensión) y un
embebedor falso: las mismas puntuaciones, bit a bit, en el mismo orden.

    .venv/bin/python herramientas/diferencial_plataforma/vectores.py [semilla] [vueltas]
"""
import json, os, random, struct, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import PRIG, viejo  # noqa: E402
sys.path.insert(0, os.path.join(PRIG, "backend"))
import indice_semantico as nuevo  # noqa: E402
from knowledge_base import KnowledgeBase  # noqa: E402
v = viejo("indice_semantico")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 60
R = random.Random(semilla)
fallos, cuentas = [], {}


def comparar(nombre, a, b, ctx):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if repr(a) != repr(b) and len(fallos) < 10:
        fallos.append({"prueba": nombre, "ctx": str(ctx)[:300], "viejo": repr(a)[:600], "nuevo": repr(b)[:600]})


def vector(d):
    return [R.choice([0.0, 1.0, -1.0, R.uniform(-1, 1), R.gauss(0, 3), 1e-30]) for _ in range(d)]


tiempos = {"viejo": 0.0, "nuevo": 0.0}
for vuelta in range(N):
    d = R.choice([1, 2, 3, 8, 384, 1024])
    base = tempfile.mkdtemp()
    kb = KnowledgeBase(os.path.join(base, "kb.db"))
    n = R.choice([0, 1, 5, 40, 300 if d < 1024 else 1500])
    comunes = [vector(d) for _ in range(3)]
    ids = [f"c{R.randint(0, n * 2)}" for _ in range(n)]
    with kb.conectar() as c:
        c.execute("CREATE TABLE IF NOT EXISTS vectores (concept_id TEXT PRIMARY KEY, vector BLOB, dimension INTEGER, modelo TEXT, indexado_en TEXT);")
        for cid in ids:
            x = R.choice(comunes) if R.random() < 0.3 else vector(d)
            c.execute("INSERT OR REPLACE INTO vectores VALUES (?,?,?,?,?)", (cid, struct.pack(f"{d}f", *x), d, "m", "t"))
        c.commit()
    preguntas = [vector(d) for _ in range(4)] + [vector(d + 1)]
    for q in preguntas:
        pedidos = R.choice([None, [], ids[:R.randint(0, len(ids))] + ["zz", R.choice(ids or ["c0"])], ["nada"]])
        res = []
        for nombre, mod in (("viejo", v), ("nuevo", nuevo)):
            ind = mod.IndiceSemantico.__new__(mod.IndiceSemantico)
            ind.kb, ind._cache, ind.modelo = kb, None, "m"
            ind.embeber = lambda textos, timeout=0, q=q: [q]
            t = time.perf_counter()
            res.append(ind.puntuar("p", pedidos))
            tiempos[nombre] += time.perf_counter() - t
        comparar("puntuar", res[0], res[1], (d, n, pedidos))
    a, b = vector(d), R.choice([vector(d), vector(d + 1), []])
    comparar("coseno", v._coseno(a, b), nuevo._coseno(a, b), (a[:4], b[:4]))
    blob = struct.pack(f"{d}f", *vector(d))
    comparar("desempaquetar", v._desempaquetar(blob), nuevo._desempaquetar(blob), d)
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos),
                  "segundos": {k: round(x, 3) for k, x in tiempos.items()}}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
