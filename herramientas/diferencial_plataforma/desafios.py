"""Diferencial de desafios/almacen.py (`Almacen.lista`): Python puro (REFERENCIA) contra Rust. Carpetas al azar con
desafíos hechos a partir de los del usuario (copiados; el original nunca se toca), claves que faltan, valores
falsos, NaN, enteros enormes, BOM, JSON roto, empates de fecha y archivos que no son JSON: la misma lista.

    .venv/bin/python herramientas/diferencial_plataforma/desafios.py [semilla] [vueltas] [carpeta con JSON de muestra]
"""
import copy, glob, json, math, os, random, shutil, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import PRIG, viejo  # noqa: E402
sys.path.insert(0, os.path.join(PRIG, "backend"))
from desafios import almacen as nuevo  # noqa: E402
import importlib.util  # noqa: E402
_base = _referencia._base
sys.path.insert(0, os.path.join(_base, "backend"))
spec = importlib.util.spec_from_file_location("desafios_v.almacen", os.path.join(_base, "backend", "desafios", "almacen.py"),
                                              submodule_search_locations=None)
import types  # noqa: E402
paquete = types.ModuleType("desafios_v")
paquete.__path__ = [os.path.join(_base, "backend", "desafios")]
sys.modules["desafios_v"] = paquete
v = importlib.util.module_from_spec(spec)
sys.modules["desafios_v.almacen"] = v
spec.loader.exec_module(v)

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 40
muestras = [json.load(open(f, encoding="utf-8")) for f in glob.glob(os.path.join(sys.argv[3], "*.json"))] if len(sys.argv) > 3 else []
R = random.Random(semilla)
fallos, cuentas, tiempos = [], {}, {"viejo": 0.0, "nuevo": 0.0}
FALSOS = [None, "", 0, 0.0, [], {}, False]


def desafio():
    d = copy.deepcopy(R.choice(muestras)) if muestras and R.random() < 0.7 else {"id": "des_0000000000", "titulo": "t"}
    for clave in ("titulo", "nivel", "conceptos", "origen", "comprobacion", "creado", "progreso", "id"):
        x = R.random()
        if x < 0.1:
            d.pop(clave, None)
        elif x < 0.18:
            d[clave] = copy.deepcopy(R.choice(FALSOS))
    if isinstance(d.get("origen"), dict) and R.random() < 0.5:
        d["origen"]["tema"] = "x"
    if R.random() < 0.3:
        d["comprobacion"] = {"tipo": R.choice(["ninguna", "unittest", None, 3])}
    p = d.get("progreso")
    if isinstance(p, dict):
        for clave in ("estado", "intentos", "pistas", "mejor", "historial"):
            if R.random() < 0.2:
                p.pop(clave, None)
            elif R.random() < 0.1:
                p[clave] = copy.deepcopy(R.choice(FALSOS + [float("nan"), 10 ** 30, -1.5e300, "ñ😀"]))
    d["actualizado"] = R.choice(["2026-10-01T10:00:00", "2026-10-02T10:00:00", "", "2025-01-01T00:00:00"]) if R.random() < 0.9 else None
    d.pop("actualizado", None) if R.random() < 0.05 else None
    return d


def comparar(nombre, a, b, ctx):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if json.dumps(a, sort_keys=False, default=str) != json.dumps(b, sort_keys=False, default=str) and len(fallos) < 10:
        fallos.append({"prueba": nombre, "ctx": str(ctx)[:200], "viejo": json.dumps(a)[:600], "nuevo": json.dumps(b)[:600]})


for vuelta in range(N):
    base = tempfile.mkdtemp(dir=_referencia.TMP)
    os.makedirs(os.path.join(base, "desafios"))
    for i in range(R.choice([0, 1, 5, 40, 300])):
        nombre = f"des_{i:010x}"
        ruta = os.path.join(base, "desafios", nombre + R.choice([".json", ".json", ".json", ".tmp", ""]))
        x = R.random()
        if x < 0.05:
            open(ruta, "wb").write(b"{roto")
        elif x < 0.08:
            open(ruta, "wb").write("﻿{}".encode())
        elif x < 0.1:
            open(ruta, "wb").write(b"\xff\xfe")
        else:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(desafio(), f, ensure_ascii=R.random() < 0.5, indent=R.choice([None, 1]))
    res = []
    for nombre, mod in (("viejo", v), ("nuevo", nuevo)):
        t = time.perf_counter()
        res.append(mod.Almacen(base).lista())
        tiempos[nombre] += time.perf_counter() - t
    # NaN != NaN: se compara su texto
    comparar("lista", res[0], res[1], base)
    shutil.rmtree(base)
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos),
                  "segundos": {k: round(x, 3) for k, x in tiempos.items()}}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
