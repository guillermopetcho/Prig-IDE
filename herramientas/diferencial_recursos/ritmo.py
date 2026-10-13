"""Diferencial de ritmo: la versión de Python puro (commit de referencia) contra la de ahora (Rust). Uso: .venv/bin/python ritmo.py [semilla] [vueltas]"""
import json, os, random, sys, time
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402  (recursos_viejo: backend/recursos del commit de referencia)
S = _referencia.TMP
from recursos_viejo import ritmo as rv
from recursos import ritmo as rn
R = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
fallos = []
def j(x): return json.dumps(x, ensure_ascii=False, sort_keys=False)

class Reloj:
    def __init__(self): self.t, self.n = 1000.0, 0
    def __call__(self): self.n += 1; return self.t

def correr(mod, pasos, ajustes):
    reloj = Reloj()
    guardados = []
    salida = []
    with mock.patch.object(time, "time", reloj), mock.patch.object(mod, "nucleos_eficientes", return_value=[8, 9]):
        r = mod.Ritmo(ajustes, guardar=lambda a, t: guardados.append((a, t)))
        for (op, args, dt) in pasos:
            reloj.t += dt
            try:
                v = getattr(r, op)(*args)
                salida.append(("ok", op, j(v), reloj.n))
            except Exception as e:
                salida.append(("error", op, type(e).__name__, str(e), reloj.n))
            salida.append(("estado", j(r.ajustes), j(r.ultimo), r.activo))
    return salida, j(guardados)

def temp(): return R.choice([None, 40, 50.5, 55, 58, 60, 62.25, 80, 30])
for i in range(N):
    ajustes = R.choice([None, {}, {"objetivo_c": 60, "rampa_s": 0, "ritmo_minimo": 0.3}, {"rampa_s": 40, "inicio_rampa": 0.35},
                        {"activo": False}, {"objetivo_c": 55, "tramo_s": 0.5}, {"ritmo_minimo": 0.3, "rampa_s": 20}])
    pasos = []
    for _ in range(R.randint(1, 30)):
        k = R.randint(0, 6)
        if k == 0: pasos.append(("marcar", (R.choice([None, 0, 1000.0 + R.randint(0, 200)]),), R.choice([0, 1, 5, 31])))
        elif k == 1: pasos.append(("fraccion", (temp(), R.choice([None, 1000.0 + R.randint(0, 200)])), R.choice([0, 1, 10])))
        elif k == 2: pasos.append(("pausa", (R.choice([0.2, 0.5, 1.0, 1.2, 3, 100]), temp(), R.choice([None, 1100.0])), R.choice([0, 1])))
        elif k == 3: pasos.append(("fijar", ({R.choice(["activo", "objetivo_c", "rampa_s", "ritmo_minimo", "tramo_s", "tramo_motor_s", "inicio_rampa", "cpu_eficiente", "raro"]):
                                               R.choice([True, False, 0, 1, 200, -5, 0.01, 0.3, "0.5", "x", None, 55])},), 0))
        elif k == 4: pasos.append(("estado", (temp(),), R.choice([0, 1])))
        else: pasos.append(("fraccion", (temp(),), R.choice([0, 2])))
    a, b = correr(rv, pasos, ajustes), correr(rn, pasos, ajustes)
    if a != b and len(fallos) < 5:
        for x, y in zip(a[0], b[0]):
            if x != y:
                fallos.append(("ritmo", ajustes, x, y)); break
        else:
            fallos.append(("ritmo-guardar", a[1][:300], b[1][:300]))

# ---------------------------------------------------------------- fijador
class Proc:
    def __init__(self, pid, cmdline, uid, hilos, falla_hilos):
        self.pid = pid
        self.info = {"pid": pid, "cmdline": cmdline, "uids": mock.Mock(real=uid) if uid is not None else None}
        self._hilos, self._falla = hilos, falla_hilos
    def threads(self):
        if self._falla:
            import psutil; raise psutil.NoSuchProcess(self.pid)
        return [mock.Mock(id=h) for h in self._hilos]

class Sistema:
    def __init__(self, procs, todos, fallan): self.procs, self.todos, self.fallan, self.fijados = procs, todos, fallan, []
    def procesos(self): return [(p.pid, p.info["cmdline"] or [], p.info["uids"].real if p.info["uids"] else None) for p in self.procs]
    def hilos(self, pid):
        p = next(p for p in self.procs if p.pid == pid)
        if p._falla: raise OSError("no está")
        return p._hilos
    def fijar(self, pid, cpus):
        if pid in self.fallan: raise OSError("no")
        self.fijados.append((pid, list(cpus)))
    def afinidad_propia(self): return self.todos
    def uid(self): return os.getuid()
    def pids(self): return [p.pid for p in self.procs]

BLOBS = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
for i in range(N):
    procs = []
    for k in range(R.randint(0, 6)):
        pid = 100 + k
        tipo = R.randint(0, 5)
        blob = R.choice(BLOBS)
        cmd = {0: ["/x/llama-server", "--model", f"/m/blobs/sha256-{blob}"], 1: ["/home/u/Prig/lib/moe/llama-server", "-m", f"/b/sha256-{blob}"],
               2: ["python3", "x.py"], 3: ["/x/llama-server", "--version"], 4: None, 5: ["/x/llama-server", f"sha256-zz sha256-{blob}"]}[tipo]
        uid = R.choice([os.getuid(), os.getuid(), os.getuid() + 1, None])
        procs.append(Proc(pid, cmd, uid, [pid * 10, pid * 10 + 1], R.random() < 0.1))
    en_gpu = {b: R.choice([True, False]) for b in R.sample(BLOBS, R.randint(0, 4))}
    eficientes = R.choice([[8, 9, 10, 11], [], [4]])
    todos = sorted(R.sample(range(16), R.randint(1, 16)))
    fallan = {p.pid for p in procs if R.random() < 0.1}
    ram = R.random() < 0.5
    rondas = [(R.choice([True, False]), R.choice([0, 1, 6])) for _ in range(R.randint(1, 4))]

    # viejo: psutil y os simulados
    fij_v, sal_v = [], []
    fv = rv.FijadorCPU(); fv.ram_en_eficientes = lambda: ram
    reloj = Reloj()
    def poner(pid, cpus):
        if pid in fallan: raise OSError("no")
        fij_v.append((pid, list(cpus)))
    with mock.patch.object(rv, "nucleos_eficientes", return_value=eficientes), mock.patch.object(fv, "_modelos_en_gpu", return_value=en_gpu), \
            mock.patch("psutil.process_iter", return_value=procs), mock.patch("psutil.pids", return_value=[p.pid for p in procs]), \
            mock.patch.object(rv.os, "sched_getaffinity", return_value=set(todos)), mock.patch.object(rv.os, "sched_setaffinity", side_effect=poner), \
            mock.patch.object(time, "time", reloj):
        for forzar, dt in rondas:
            reloj.t += dt
            sal_v.append((j(fv.aplicar(forzar=forzar)), reloj.n))
    # nuevo: el sistema falso
    sis = Sistema(procs, todos, fallan)
    fn = rn.FijadorCPU(sistema=sis); fn.ram_en_eficientes = lambda: ram
    reloj = Reloj(); sal_n = []
    with mock.patch.object(rn, "nucleos_eficientes", return_value=eficientes), mock.patch.object(fn, "_modelos_en_gpu", return_value=en_gpu), \
            mock.patch.object(time, "time", reloj):
        for forzar, dt in rondas:
            reloj.t += dt
            sal_n.append((j(fn.aplicar(forzar=forzar)), reloj.n))
    if (sal_v, fij_v) != (sal_n, sis.fijados) and len(fallos) < 10:
        fallos.append(("fijador", [(p.pid, p.info["cmdline"], p._falla) for p in procs], en_gpu, eficientes, rondas, sal_v, sal_n, fij_v, sis.fijados))
print("fallos:", len(fallos))
for f in fallos: print(json.dumps(f, default=str, ensure_ascii=False)[:1500])
