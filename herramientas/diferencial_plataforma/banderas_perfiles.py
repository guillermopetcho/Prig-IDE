"""Diferencial de feature_flags.py y perfiles_config.py: la versión de Python puro (REFERENCIA) contra la de ahora
(Rust por prig_nativo). Con los mismos archivos de partida (bien formados, rotos, de otro tipo) y las mismas
operaciones, tienen que dar lo mismo: valores devueltos, archivos byte a byte y lo que se imprime (salvo el texto
de la excepción de Python dentro de un aviso).

    .venv/bin/python herramientas/diferencial_plataforma/banderas_perfiles.py [semilla] [vueltas]
"""
import contextlib, io, json, os, random, re, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import TMP, viejo  # noqa: E402
import feature_flags as fn, perfiles_config as pn  # noqa: E402
fv, pv = viejo("feature_flags"), viejo("perfiles_config")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
R = random.Random(semilla)
fallos, cuentas = [], {}
NOMBRES = list(fv.DEFAULT_FLAGS) + ["otra", "", "KNOWLEDGE_CHAT"]


def texto_raro():
    return R.choice(["", "a", "ñandú", "x\ny", "\"comillas\"", "\\", " ", "😀", "\x00", "tab\t", "</script>"])


def valor(prof=0):
    t = R.random()
    if prof > 3 or t < 0.3:
        return R.choice([None, True, False, 0, 1, -7, 2**70, 0.5, 1.0, 1e-9, 1e300, -0.0, 3.14159, texto_raro()])
    if t < 0.65:
        return [valor(prof + 1) for _ in range(R.randint(0, 4))]
    return {texto_raro() + str(i): valor(prof + 1) for i in range(R.randint(0, 4))}


def contenido():
    t = R.random()
    if t < 0.15: return None                      # no hay archivo
    if t < 0.25: return R.choice(["", "{", "nul", "[1,", "\xff"])  # roto
    if t < 0.35: return json.dumps(valor(), ensure_ascii=R.random() < 0.5)
    if t < 0.45: return json.dumps(R.choice([[1, 2], 3, "x", None]))
    d = {}
    for n in R.sample(NOMBRES, R.randint(0, len(NOMBRES))):
        d[n] = R.choice([True, False, 0, 1, "", "no", None, [], [0], 2.5])
    return json.dumps(d, indent=R.choice([None, 2]))


def avisos(texto):
    # El texto de la excepción de Python dentro de un aviso es distinto (lo da Rust): se compara sin él
    return re.sub(r"\((?:[^()]|\([^()]*\))*\)|: .*$", "(…)", texto, flags=re.M)


def ejecutar(f):
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        try:
            r = ("ok", json.dumps(f(), ensure_ascii=False))
        except Exception as e:
            r = ("error", type(e).__name__, str(e))
    return r, avisos(salida.getvalue())


def leer(ruta):
    try:
        with open(ruta, "rb") as f: return f.read()
    except OSError as e: return type(e).__name__


def comparar(nombre, a, b):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 12:
        fallos.append({"prueba": nombre, "viejo": str(a)[:600], "nuevo": str(b)[:600]})


def preparar(dir_, cont):
    shutil.rmtree(dir_, ignore_errors=True)
    os.makedirs(dir_)
    ruta = os.path.join(dir_, "flags.json")
    if cont is not None:
        with open(ruta, "wb") as f: f.write(cont.encode("utf-8", "surrogatepass") if isinstance(cont, str) else cont)
    return ruta


def banderas():
    cont = contenido()
    entorno = {}
    for n in R.sample(list(fv.DEFAULT_FLAGS), R.randint(0, 2)):
        entorno[f"PRIG_FLAG_{n.upper()}"] = R.choice(["1", "0", " TRUE ", "sí", "Si", "off", "", "yes"])
    ops = []
    for _ in range(R.randint(0, 6)):
        ops.append((R.choice(["is_enabled", "set", "reset", "all"]), R.choice(NOMBRES), R.choice([True, False, 0, 1, "", "x", None])))
    res = []
    for mod, sub in ((fv, "v"), (fn, "n")):
        ruta = preparar(os.path.join(TMP, "flags"), cont)
        viejos = {k: os.environ.get(k) for k in entorno}
        os.environ.update(entorno)
        try:
            pasos = []
            r, s = ejecutar(lambda: mod.FeatureFlags(ruta) and None)
            ff = None
            with contextlib.redirect_stdout(io.StringIO()):
                ff = mod.FeatureFlags(ruta)
            pasos.append((r, s))
            for op, n, v in ops:
                if op == "is_enabled": pasos.append(ejecutar(lambda: ff.is_enabled(n)))
                elif op == "set": pasos.append(ejecutar(lambda: ff.set(n, v)))
                elif op == "reset": pasos.append(ejecutar(lambda: ff.reset(n)))
                else: pasos.append(ejecutar(lambda: ff.all()))
            pasos.append(ejecutar(lambda: ff.all()))
            res.append((pasos, leer(ruta)))
        finally:
            for k, v in viejos.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
    comparar("banderas", res[0], res[1])


SECC = ["perfiles", "apariencia", "sintaxis", "motor_movimiento", "accesibilidad", "audio_reactivo"]
RUTAS = {"perfiles": "RUTA_PERFILES", "apariencia": "RUTA_APARIENCIA", "sintaxis": "RUTA_SINTAXIS",
         "motor_movimiento": "RUTA_MOTOR_MOVIMIENTO", "accesibilidad": "RUTA_ACCESIBILIDAD",
         "audio_reactivo": "RUTA_AUDIO_REACTIVO"}


def perfiles():
    archivos = {s: (R.choice([None, json.dumps({"perfiles": valor(), "perfil_activo": "x"})]) if s == "perfiles" and R.random() < 0.5 else contenido()) for s in SECC}
    crear_dir = R.random() < 0.8
    ops = []
    for _ in range(R.randint(1, 6)):
        t = R.random()
        if t < 0.3: ops.append(("cargar", R.choice(SECC)))
        elif t < 0.55: ops.append(("guardar", R.choice(SECC), valor()))
        elif t < 0.7: ops.append(("completo",))
        else:
            d = {s: R.choice([valor(), {"a": valor()}, None]) for s in R.sample(SECC + ["otra"], R.randint(0, 4))}
            ops.append(("guardar_completo", d))
    res = []
    for mod, sub in ((pv, "v"), (pn, "n")):
        base = os.path.join(TMP, "perfiles")
        shutil.rmtree(base, ignore_errors=True)
        os.makedirs(base)
        dir_ = os.path.join(base, ".prig_dataset")
        if crear_dir: os.makedirs(dir_)
        mod.DATASET_DIR = dir_
        mod.RUTA_PERFILES = os.path.join(dir_, "config_profiles.json")
        for s in SECC:
            setattr(mod, RUTAS[s], os.path.join(dir_, os.path.basename(getattr(pv, RUTAS[s]))))
            if crear_dir and archivos[s] is not None:
                with open(getattr(mod, RUTAS[s]), "w", encoding="utf-8", errors="surrogatepass") as f: f.write(archivos[s])
        pasos = []
        for op in ops:
            if op[0] == "cargar": pasos.append(ejecutar(lambda: getattr(mod, f"cargar_{op[1]}")()))
            elif op[0] == "guardar": pasos.append(ejecutar(lambda: getattr(mod, f"guardar_{op[1]}")(op[2])))
            elif op[0] == "completo": pasos.append(ejecutar(lambda: mod.cargar_estado_completo()))
            else: pasos.append(ejecutar(lambda: mod.guardar_estado_completo(op[1])))
        disco = {s: leer(getattr(mod, RUTAS[s])) for s in SECC}
        res.append((pasos, disco, sorted(os.listdir(dir_)) if os.path.isdir(dir_) else None))
    comparar("perfiles", res[0], res[1])


comparar("predeterminados", json.dumps(pv.PERFILES_PREDETERMINADOS), json.dumps(pn.PERFILES_PREDETERMINADOS))
comparar("DEFAULT_FLAGS", json.dumps(fv.DEFAULT_FLAGS, ensure_ascii=False), json.dumps(fn.DEFAULT_FLAGS, ensure_ascii=False))
for _ in range(N):
    banderas()
    perfiles()
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
