"""Diferencial de referencias_ml.py y referencias_dp.py (relacionadas, _normalizar, _aparece): Python puro
(REFERENCIA) contra Rust. Preguntas al azar hechas con el vocabulario del catálogo real (títulos, temas, claves de
las familias, plurales, tildes, mayúsculas) y texto raro: las mismas referencias, en el mismo orden.

    .venv/bin/python herramientas/diferencial_plataforma/referencias.py [semilla] [vueltas]
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import PRIG, viejo  # noqa: E402
sys.path.insert(0, os.path.join(PRIG, "backend"))
import referencias_ml as nml, referencias_dp as ndp  # noqa: E402

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
R = random.Random(semilla)
fallos, cuentas, tiempos = [], {}, {"viejo": 0.0, "nuevo": 0.0}
CATALOGO = nml.RUTA                 # el de DP aún no existe: las dos versiones se prueban con el de ML

pares = []
for nombre, nuevo in (("referencias_ml", nml), ("referencias_dp", ndp)):
    v = viejo(nombre)
    for m in (v, nuevo):
        original = m.cargar
        m.cargar = (lambda o: lambda ruta=CATALOGO: o(ruta))(original)
    pares.append((nombre, v, nuevo))

refs = nml.cargar()["referencias"]
vocab = []
for r in refs:
    vocab += r.get("temas", []) + [r.get("titulo", "")] + r.get("titulo", "").split()
for m in (nml, ndp):
    for c in m.CATEGORIAS:
        vocab += c["claves"]
RAROS = ["", "¿", "ñ", "İ", "ﬁ", "Σ", "es", "s", "a1", "x", "  ", "\n", "-", "3d", "é", "é"]


def pregunta():
    partes = []
    for _ in range(R.randint(0, 14)):
        w = R.choice(vocab) if R.random() < 0.8 else R.choice(RAROS)
        w = R.choice([w, w.upper(), w.capitalize(), w + "s", w + "es", w + "x", "x" + w])
        partes.append(w)
    return R.choice([" ", ", ", ". ", "/"]).join(partes)


def comparar(nombre, a, b, ctx):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 10:
        fallos.append({"prueba": nombre, "ctx": repr(ctx)[:300], "viejo": str(a)[:400], "nuevo": str(b)[:400]})


for _ in range(N):
    q = pregunta()
    for nombre, v, n in pares:
        maximo = R.choice([5, 1, 3, 50])
        t = time.perf_counter(); a = [r.get("id") for r in v.relacionadas(q, maximo)]; tiempos["viejo"] += time.perf_counter() - t
        t = time.perf_counter(); b = [r.get("id") for r in n.relacionadas(q, maximo)]; tiempos["nuevo"] += time.perf_counter() - t
        comparar(f"relacionadas_{nombre[-2:]}", a, b, q)
        comparar("normalizar", v._normalizar(q), n._normalizar(q), q)
        clave = R.choice(vocab).lower()
        comparar("aparece", v._aparece(clave, v._normalizar(q)), n._aparece(clave, n._normalizar(q)), (clave, q))
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos),
                  "segundos": {k: round(x, 3) for k, x in tiempos.items()}}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
