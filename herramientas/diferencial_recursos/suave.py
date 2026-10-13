"""Diferencial de suave: la versión de Python puro (commit de referencia) contra la de ahora (Rust). Uso: .venv/bin/python suave.py [semilla] [vueltas]"""
import json, os, random, shutil, sys, tempfile, time
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402  (recursos_viejo: backend/recursos del commit de referencia)
os.environ["PRIG_ENERGIA_SIN_PKEXEC"] = "1"   # nunca pedir permisos de administrador
S = _referencia.TMP
from recursos_viejo import motor_suave as mv, energia as ev, ritmo as rv
from recursos import motor_suave as mn, energia as en, ritmo as rn
R = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
fallos = []
def j(x): return json.dumps(x, ensure_ascii=False)

# 1) el envoltorio, con rutas raras (sin compilar: biblioteca ya presente y más nueva que la fuente)
for i in range(30):
    d = tempfile.mkdtemp(dir=S)
    try:
        nombre = R.choice(["lib", "con espacio", "it's", "ñandú", 'a"b', "$x", "a;b"])
        res = {}
        for lado, mod in (("v", mv), ("n", mn)):
            lib = os.path.join(d, lado, "ollama"); os.makedirs(lib)
            open(os.path.join(lib, "llama-server"), "wb").write(b"\x7fELF original")
            so = os.path.join(d, lado, nombre, "prig_suave.so"); os.makedirs(os.path.dirname(so))
            open(so, "wb").write(b"so"); os.utime(so, (time.time() + 100, time.time() + 100))
            ctl = os.path.join(d, lado, nombre + "-ctl")
            with mock.patch.dict(os.environ, {"PRIG_OLLAMA_LIB": lib, "PRIG_SUAVE_SO": so, "PRIG_SUAVE_CONTROL": ctl}):
                r1 = mod.instalar(); r2 = mod.instalar()
                guion = open(os.path.join(lib, "llama-server"), "rb").read().replace(f"/{lado}/".encode(), b"/X/")
                inst = mod.instalado(); r3 = mod.desinstalar()
                res[lado] = (j(r1).replace(f"/{lado}/", "/X/"), j(r2), guion, inst, j(r3), open(os.path.join(lib, "llama-server"), "rb").read())
        if res["v"] != res["n"]: fallos.append(("envoltorio", nombre, [str(x)[:300] for x in res["v"]], [str(x)[:300] for x in res["n"]]))
    finally:
        shutil.rmtree(d, ignore_errors=True)

# 2) el controlador
class Reloj:
    def __init__(self): self.t, self.n = 1000.0, 0
    def __call__(self): self.n += 1; return self.t
class Monitor:
    def __init__(self, temps): self.temps, self.i = temps, 0
    def gpu(self, max_edad=2.5):
        t = self.temps[min(self.i, len(self.temps) - 1)]; self.i += 1
        if t == "error": raise RuntimeError("sensor")
        return t
for i in range(N):
    temps = [R.choice([40, 45.5, 55, 58, 60, 62, 70, None, "error"]) for _ in range(40)]
    ajustes = R.choice([{"objetivo_c": 60, "rampa_s": 0, "ritmo_minimo": 0.3, "tramo_motor_s": 0.02}, {"activo": False},
                        {"objetivo_c": 60, "rampa_s": 40, "ritmo_minimo": 0.25, "inicio_rampa": 0.2}, {"tramo_motor_s": 0}])
    pasos = [(R.choice([None, 0.1, 1.5, 3, 60]), R.choice([0, 0.5, 1])) for _ in range(R.randint(1, 25))]
    sal = {}
    for lado, mod, rmod in (("v", mv, rv), ("n", mn, rn)):
        d = tempfile.mkdtemp(dir=S); ctl = os.path.join(d, "control")
        reloj = Reloj(); salida = []
        with mock.patch.dict(os.environ, {"PRIG_SUAVE_CONTROL": ctl}), mock.patch.object(time, "time", reloj):
            c = mod.Controlador(rmod.Ritmo(ajustes), Monitor(temps))
            for hace, dt in pasos:
                reloj.t += dt
                if hace is None:
                    if os.path.exists(ctl + ".estado"): os.remove(ctl + ".estado")
                else:
                    open(ctl + ".estado", "w").write(f"123 {reloj.t - hace:.3f} 1.0 0.02 800\n")
                try:
                    r = c.paso(); salida.append(("ok", j(r)))
                except Exception as e:
                    salida.append(("error", type(e).__name__))
                control = open(ctl).read() if os.path.exists(ctl) else None
                salida.append((control, reloj.n, j(c.temp_media), c.fraccion))
        shutil.rmtree(d, ignore_errors=True)
        sal[lado] = salida
    if sal["v"] != sal["n"] and len(fallos) < 10:
        for a, b in zip(sal["v"], sal["n"]):
            if a != b: fallos.append(("controlador", ajustes, a, b)); break

# 3) energía: estado sobre un /sys falso al azar
for i in range(N):
    d = tempfile.mkdtemp(dir=S)
    def esc(ruta, texto):
        p = d + ruta; os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(texto)
    if R.random() < 0.7: esc("/sys/devices/system/cpu/intel_pstate/no_turbo", R.choice(["0\n", "1\n", "x\n", ""]))
    if R.random() < 0.5: esc("/sys/devices/system/cpu/cpufreq/boost", R.choice(["1\n", "0\n"]))
    if R.random() < 0.7: esc("/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw", R.choice(["45000000\n", "x\n", "", "999999\n", "-5\n"]))
    if R.random() < 0.5: esc("/run/prig-energia/modo", R.choice(["frio\n", "", "normal"]))
    if R.random() < 0.5: esc("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "powersave\n")
    if R.random() < 0.3: esc("/usr/bin/auto-cpufreq", "x")
    env = {"PRIG_ENERGIA_RAIZ": d, "PRIG_ENERGIA_AYUDANTE": R.choice(["", "/x/ayudante"])}
    falso = R.choice([os.path.join(d, "no-existe"), "/usr/bin/env"])
    with mock.patch.dict(os.environ, env), mock.patch.object(ev, "AYUDANTE", falso), mock.patch.object(en, "AYUDANTE", falso):
        a, b = j(ev.estado()), j(en.estado())
    if a != b: fallos.append(("energia", a, b))
    shutil.rmtree(d, ignore_errors=True)
print("fallos:", len(fallos))
for f in fallos[:8]: print(json.dumps(f, default=str, ensure_ascii=False)[:1200])
