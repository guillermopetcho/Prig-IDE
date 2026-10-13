"""Diferencial de almacen: la versión de Python puro (commit de referencia) contra la de ahora (Rust). Uso: .venv/bin/python almacen.py [semilla] [vueltas]"""
import json, os, random, re, shutil, stat, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402  (recursos_viejo: backend/recursos del commit de referencia)
S = _referencia.TMP
from recursos_viejo import almacen as av
from recursos import almacen as an
import prig_nativo
pj = prig_nativo.almacen
R = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
fallos = []

# 1) el archivo real (solo lectura)
real = os.path.expanduser("~/.prig_recursos.json")
if os.path.exists(real):
    texto = open(real, encoding="utf-8").read()
    py = json.dumps(json.load(open(real, encoding="utf-8")), ensure_ascii=False, indent=1)
    rs = pj.escribir_json(pj.leer_json(texto), 1)
    print("archivo real:", len(texto), "bytes; Python lo reescribe igual:", py == texto, "; Rust igual:", rs == texto)

# 2) JSON al azar
def txt():
    return "".join(R.choice(['a', 'ñ', '"', '\\', '\n', '\t', '\x01', '\x1f', '\x7f', '€', '𝄞', ' ', '/', '\u2028']) for _ in range(R.randint(0, 6)))
def val(p=0):
    t = R.randint(0, 9 if p < 3 else 5)
    if t == 0: return None
    if t == 1: return R.choice([True, False])
    if t == 2: return R.choice([0, -1, 2**63, -2**70, 10**30, 7])
    if t == 3: return R.choice([0.0, -0.0, 1.5, 1e16, 1e-5, 123456789.123, float("nan"), float("inf"), -float("inf"), 0.1 + 0.2, 5e-324, 1.7976931348623157e308])
    if t in (4, 5): return txt()
    if t in (6, 7): return [val(p + 1) for _ in range(R.randint(0, 3))]
    return {txt(): val(p + 1) for _ in range(R.randint(0, 3))}
for i in range(N * 10):
    v = val()
    a = json.dumps(v, ensure_ascii=False, indent=R.choice([1, 1, 2]))
    ind = 1 if "\n " not in a or "\n  " not in a.split("\n")[1] else None
    for sangria in (1, 2):
        a = json.dumps(v, ensure_ascii=False, indent=sangria)
        b = pj.escribir_json(v, sangria)
        if a != b and len(fallos) < 8: fallos.append(("escribir", repr(v)[:300], a[:300], b[:300]))
    # leer: lo escrito y versiones rotas
    for t in (a, a[:R.randint(0, len(a))], a.replace(",", ",,", 1), " " + a + " ", a + "x"):
        try: x = ("ok", json.dumps(json.loads(t), ensure_ascii=False))
        except Exception: x = ("error",)
        try: y = ("ok", json.dumps(pj.leer_json(t), ensure_ascii=False))
        except Exception: y = ("error",)
        if x != y and len(fallos) < 8: fallos.append(("leer", repr(t)[:300], x, y))

# 3) secuencias de operaciones
FECHA = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
def norm(x): return FECHA.sub("FECHA", json.dumps(x, ensure_ascii=False, sort_keys=False))
HUELLAS = ["A", "B", "C", "D", "E", "F", "G", "", None]
def op(a):
    k = R.randint(0, 17)
    h = R.choice(HUELLAS)
    if k == 0: return ("registrar_radiografia", ({"huella": h, "gpus": [{"nombre": "x"}], "n": R.random()},))
    if k == 1: return ("calibracion", (R.choice([None, h]),))
    if k == 2: return ("guardar_calibracion", (h, {"ancho_gpu": R.choice([178, 1.5, None]), "x": R.choice([1, None])}, R.choice([None, {}, {"d": 1}])))
    if k == 3: return ("olvidar_calibracion", (R.choice([None, h]),))
    if k == 4: return ("guardar_prueba", (h, R.choice(["m1", "m2"]), R.choice(["tutor", "flujos"]), {"ok": R.choice([True, False, None]), "opciones": {"num_ctx": 4096}, "fecha": "x"}))
    if k == 5: return ("pruebas", (R.choice([None, h]),))
    if k == 6: return ("prueba", (R.choice(["m1", "m2"]), "tutor", R.choice([None, h])))
    if k == 7: return ("ultima_buena", (R.choice(["tutor", "flujos"]),))
    if k == 8: return ("registrar_aplicado", (R.choice(["tutor", "flujos"]), R.choice(["m1", "m2"]), {"num_ctx": R.randint(1, 9)}, {"num_gpu": R.randint(0, 3)}))
    if k == 9: return ("aplicado", (R.choice(["tutor", "flujos"]),))
    if k == 10: return ("quitar_aplicado", (R.choice(["tutor", "flujos"]),))
    if k == 11: return ("guardar_entorno_servidor", ({"OLLAMA_X": R.choice(["1", "", None, 2]), "LLAMA_ARG_Y": "z", "OTRA": "w"},))
    if k == 12: return ("guardar_termico", ({"limite_gpu": R.choice([60.0, 65])}, R.choice([None, "", "texto"]), R.choice([None, {"pico": 61}])))
    if k == 13: return ("guardar_frio", ({"activo": R.choice([True, False])}, R.choice([None, "frío"])))
    if k == 14: return ("guardar_ritmo", ({"activo": True, "objetivo_c": 55.0}, R.choice([None, "ritmo"])))
    if k == 15: return ("evento", ("tipo", "texto ñ", R.choice([None, {}, {"a": [1, 2.5]}])))
    if k == 16: return ("eventos", (R.choice([0, 1, 5, 50, 1000, -3]),))
    return R.choice([("termico", ()), ("frio", ()), ("ritmo", ()), ("entorno_servidor", ())])

for vuelta in range(N // 10 + 1):
    d = tempfile.mkdtemp(dir=S)
    try:
        rv, rn = os.path.join(d, "v.json"), os.path.join(d, "n.json")
        if R.random() < 0.2:
            contenido = R.choice(["{roto", '{"version": 2}', '[]', '{"version": 1, "eventos": [], "maquinas": {"A": {"vista": "2020", "calibracion": {"ancho_gpu": 1}}}}', '{"version": 1.0}'])
            open(rv, "w").write(contenido); open(rn, "w").write(contenido)
        a, b = av.Almacen(rv), an.Almacen(rn)
        for paso in range(R.randint(5, 40)):
            nombre, args = op(a)
            try: x = ("ok", norm(getattr(a, nombre)(*args)))
            except Exception as e: x = ("error", type(e).__name__)
            try: y = ("ok", norm(getattr(b, nombre)(*args)))
            except Exception as e: y = ("error", type(e).__name__)
            fv = FECHA.sub("FECHA", open(rv, encoding="utf-8").read()) if os.path.exists(rv) else None
            fn = FECHA.sub("FECHA", open(rn, encoding="utf-8").read()) if os.path.exists(rn) else None
            mv = stat.S_IMODE(os.stat(rv).st_mode) if os.path.exists(rv) else None
            mn = stat.S_IMODE(os.stat(rn).st_mode) if os.path.exists(rn) else None
            for que, p, q in (("resultado", x, y), ("archivo", fv, fn), ("permisos", mv, mn), ("huella_actual", a.huella_actual, b.huella_actual),
                              ("radiografia", norm(a.radiografia), norm(b.radiografia))):
                if p != q and len(fallos) < 8:
                    fallos.append((que, nombre, repr(args)[:200], str(p)[:400], str(q)[:400]))
        rotos = lambda pref: sorted(re.sub(r"\d+$", "T", n.replace(pref, "")) for n in os.listdir(d) if n.startswith(pref + ".roto"))
        if rotos("v.json") != rotos("n.json") and len(fallos) < 8: fallos.append(("rotos", rotos("v.json"), rotos("n.json")))
    finally:
        shutil.rmtree(d, ignore_errors=True)
print("fallos:", len(fallos))
for f in fallos: print(f)
