"""Diferencial de ollama_opciones.py: la versión de Python puro (REFERENCIA) contra la de ahora (Rust por
prig_nativo). validar, separar, limpiar, el catálogo y el almacén de capas (con archivos rotos o de otro tipo y
operaciones al azar) tienen que dar lo mismo: valores, excepciones (tipo y texto) y el archivo byte a byte.

    .venv/bin/python herramientas/diferencial_plataforma/opciones.py [semilla] [vueltas]
"""
import json, math, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import TMP, viejo  # noqa: E402
import ollama_opciones as on  # noqa: E402
ov = viejo("ollama_opciones")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 400
R = random.Random(semilla)
fallos, cuentas = [], {}
CLAVES = [o["clave"] for o in ov.OPCIONES] + [c["clave"] for c in ov.CAMPOS] + list(ov.EXCLUIDAS)[:3] + ["otra"]
VALORES = [0, 1, -1, 5, 2.5, 0.05, 1e9, -3.7, 2**31, True, False, None, "", "3", "3.0", " 7 ", "1_0", "abc", "5m", "-1",
           "1.5h", "10ms", "x" * 4001, ["a", "", "b"], ["a"] * 9, [1, 2], {"a": 1}, "nan", float("nan"), "inf", 0.0, 262144, 512]


def ejecutar(f):
    try:
        r = f()
        return ("ok", json.dumps(r, ensure_ascii=False, default=str) if not isinstance(r, float) or not math.isnan(r) else "nan")
    except Exception as e:
        return ("error", type(e).__name__, str(e))


def leer(ruta):
    try:
        with open(ruta, "rb") as f: return f.read()
    except OSError as e: return type(e).__name__


def comparar(nombre, a, b, ctx):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 12:
        fallos.append({"prueba": nombre, "ctx": str(ctx)[:300], "viejo": str(a)[:900], "nuevo": str(b)[:900]})


comparar("catalogo", ejecutar(lambda: ov.catalogo(1)), ejecutar(lambda: on.catalogo(1)), 1)
comparar("catalogo", ejecutar(lambda: ov.catalogo(2)), ejecutar(lambda: on.catalogo(2)), 2)
for _ in range(N):
    v = {R.choice(CLAVES): R.choice(VALORES) for _ in range(R.randint(0, 3))}
    if R.random() < 0.05: v = R.choice([None, [], "x", {}])
    comparar("validar", ejecutar(lambda: ov.validar(v)), ejecutar(lambda: on.validar(v)), v)
    if isinstance(v, dict):
        comparar("separar", ejecutar(lambda: ov.separar(v)), ejecutar(lambda: on.separar(v)), v)
        comparar("limpiar", ejecutar(lambda: ov.limpiar_para_ollama(v)), ejecutar(lambda: on.limpiar_para_ollama(v)), v)

MODELOS = ["qwen3:14b", "qwen3:14b:latest", "qwen3:latest", "qwen3", "a|b", ""]
USOS = list(ov.USOS) + ["otro", None]
for _ in range(N // 2):
    inicial = R.choice([None, "", "{", "[]", json.dumps({"global": {"temperature": 0.5, "typical_p": 1}, "modelo": {"qwen3": {"top_k": 20, "mirostat": 1}}}),
                        json.dumps({"global": [], "modelo": {}}), json.dumps({"modelo": {"x": 3}}), json.dumps({"version": 2, "extra": "ñ"})])
    ops = []
    for _ in range(R.randint(1, 6)):
        t = R.choice(["fijar", "fijar", "capa", "resolver", "emb", "fijar_emb", "renombrar", "todo"])
        ops.append((t, R.choice(["global", "modelo", "uso", "modelo_uso", "otra"]), {R.choice(CLAVES[:20]): R.choice(VALORES[:20]) for _ in range(R.randint(0, 3))},
                    R.choice(MODELOS), R.choice(USOS), R.random() < 0.3,
                    (R.choice([None, " nomic ", ""]), R.choice([None, 128, 8, "64", "x", 100000]), R.choice([None, True, 0]), R.random() < 0.2)))
    res = []
    for mod in (ov, on):
        ruta = os.path.join(TMP, "sub", "m.json")
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        for f in os.listdir(os.path.dirname(ruta)): os.remove(os.path.join(os.path.dirname(ruta), f))
        if inicial is not None:
            with open(ruta, "w") as f: f.write(inicial)
        c = mod.ConfigModelos(ruta)
        pasos = []
        for t, capa, vals, modelo, uso, reemp, emb in ops:
            if t == "fijar": pasos.append(ejecutar(lambda: c.fijar(capa, vals, modelo=modelo, uso=uso, reemplazar=reemp)))
            elif t == "capa": pasos.append(ejecutar(lambda: c.capa(capa, modelo, uso)))
            elif t == "resolver": pasos.append(ejecutar(lambda: c.resolver(modelo, uso)))
            elif t == "emb": pasos.append(ejecutar(lambda: c.embeddings()))
            elif t == "fijar_emb": pasos.append(ejecutar(lambda: c.fijar_embeddings(emb[0], emb[1], emb[2], emb[3])))
            elif t == "renombrar": pasos.append(ejecutar(lambda: c.renombrar_modelo(modelo, "copia:1")))
            else: pasos.append(ejecutar(lambda: c.todo()))
        carpeta = os.path.dirname(ruta)
        pasos.append((leer(ruta), sorted(n if not n.startswith(".prig_modelos.") else "tmp" for n in os.listdir(carpeta)),
                      leer(ruta + ".roto"), oct(os.stat(ruta).st_mode) if os.path.exists(ruta) else None))
        res.append(pasos)
    comparar("almacen", res[0], res[1], (inicial, ops))
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
