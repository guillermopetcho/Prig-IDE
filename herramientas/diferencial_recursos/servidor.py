"""Diferencial de servidor: la versión de Python puro (commit de referencia) contra la de ahora (Rust). Uso: .venv/bin/python servidor.py [semilla] [vueltas]"""
import json, os, random, shutil, sys, tempfile
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402  (recursos_viejo: backend/recursos del commit de referencia)
S = _referencia.TMP
from recursos_viejo import servidor as sv, almacen as av
from recursos import servidor as sn, almacen as an
R = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 500
fallos = []
def j(x): return json.dumps(x, ensure_ascii=False, sort_keys=False, default=list)
def igual(nombre, fv, fn, *args):
    try: a = ("ok", j(fv(*args)))
    except Exception as e: a = ("error", type(e).__name__, str(e))
    try: b = ("ok", j(fn(*args)))
    except Exception as e: b = ("error", type(e).__name__, str(e))
    if a != b and len(fallos) < 12: fallos.append((nombre, repr(args)[:300], a, b))
d = tempfile.mkdtemp(dir=S)
os.makedirs(os.path.join(d, "modelos")); os.makedirs(os.path.join(d, "solo_lectura")); os.chmod(os.path.join(d, "solo_lectura"), 0o555)
libs = sn.librerias_disponibles()
VALORES = {"OLLAMA_KV_CACHE_TYPE": ["f16", "q8_0", "q4_0", "q2", " q8_0 ", ""], "OLLAMA_NUM_PARALLEL": ["1", "8", "9", "0", "dos", " 2", 3],
           "OLLAMA_FLASH_ATTENTION": ["0", "1", "2", 1, True], "OLLAMA_MAX_LOADED_MODELS": ["1", "9"], "OLLAMA_KEEP_ALIVE": ["5m", "  ", "-1"],
           "OLLAMA_CONTEXT_LENGTH": ["512", "511", "262144", "262145", "4k"], "OLLAMA_LLM_LIBRARY": libs + ["cuda_v99", ""],
           "LLAMA_ARG_FIT_TARGET": ["0", "65536", "65537", "-1"], "OLLAMA_LOAD_TIMEOUT": ["10s", "9s", "10000ms", "9999ms", "1m", "1h", "90", "s", "0.5m", "10S"],
           "OLLAMA_IGPU_ENABLE": ["0", "1", "x"], "OLLAMA_MODELS": [os.path.join(d, "modelos"), os.path.join(d, "no-existe"), os.path.join(d, "solo_lectura"), os.path.join(d, "modelos") + "/../modelos", "~"],
           "OLLAMA_HOST": ["127.0.0.1:11434", "0.0.0.0:11434", "localhost"], "OLLAMA_ORIGINS": ["*", "https://a.b", "http://x:8080, app://y", "ftp://z", ",", " , https://ok.com ,", "https://a b", "file://", "https://*.dominio.es:443"],
           "OLLAMA_DEBUG": ["0", "1"], "OLLAMA_NO_CLOUD": ["1", "0"], "OLLAMA_NOPRUNE": ["1"], "PATH": ["x"]}
try:
    with mock.patch.object(sv, "librerias_disponibles", lambda: libs):
        for i in range(N):
            cambios = {k: R.choice(VALORES[k]) for k in R.sample(list(VALORES), R.randint(1, 4))}
            if R.random() < 0.1: cambios[R.choice(list(VALORES))] = None
            igual("validar", sv.validar, sn.validar, cambios)
            entorno = {k: R.choice(["1", "q8_0", "", "x y"]) for k in R.sample(list(VALORES), R.randint(0, 4))}
            igual("instrucciones", sv.instrucciones, sn.instrucciones, R.choice(["systemd", "systemd-usuario", "usuario", None, "prig"]), entorno)
            # estado y entorno de arranque, con un almacén temporal en cada lado
            info = {"responde": R.choice([True, False]), "version": R.choice(["0.12", None]), "binario": R.choice(["/x/ollama", None]),
                    "dueno": R.choice(["prig", "systemd", None, "usuario"]), "entorno": {k: R.choice(["1", "q8_0", ""]) for k in R.sample(list(VALORES), R.randint(0, 4))},
                    "modelos_cargados": R.choice([[], [{"nombre": "m"}], None])}
            if R.random() < 0.2: info.pop("modelos_cargados")
            guardado = {k: R.choice(["1", "q8_0", "2"]) for k in R.sample(list(VALORES), R.randint(0, 3))}
            res = []
            for mod, alm in ((sv, av), (sn, an)):
                ruta = os.path.join(d, f"r-{i}-{mod.__name__}.json")
                with mock.patch.dict(os.environ, {"PRIG_RECURSOS_ARCHIVO": ruta, "HOME": d}):
                    alm.almacen().guardar_entorno_servidor(guardado)
                    try: e = mod.estado(info)
                    except Exception as ex: e = type(ex).__name__
                    res.append((j(e), j(mod.entorno_arranque({"PATH": "/usr/bin", "OLLAMA_KV_CACHE_TYPE": "f16"}))))
            if res[0] != res[1] and len(fallos) < 12: fallos.append(("estado", info, guardado, res[0][0][:400], res[1][0][:400]))
            # registro
            texto = "".join(R.choice(["línea\n", "a\r\n", "b\r", "ñ" * 50, "\n", "x" * 300, " ", "\x85", "\x1c", "fin"]) for _ in range(R.randint(0, 200)))
            reg = os.path.join(d, ".prig_ollama.log")
            if R.random() < 0.9: open(reg, "w", encoding="utf-8").write(texto)
            elif os.path.exists(reg): os.remove(reg)
            lineas = R.choice([1, 20, 21, 50, 400, 5000, 99999, -3])
            with mock.patch.dict(os.environ, {"HOME": d}):
                igual("leer_registro", sv.leer_registro, sn.leer_registro, lineas)
finally:
    os.chmod(os.path.join(d, "solo_lectura"), 0o755)
    shutil.rmtree(d, ignore_errors=True)
print("fallos:", len(fallos))
for f in fallos[:10]: print(json.dumps(f, ensure_ascii=False, default=str)[:900])
