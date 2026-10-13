"""Diferencial de termico: la versión de Python puro (commit de referencia) contra la de ahora (Rust). Uso: .venv/bin/python termico.py [semilla] [vueltas]"""
import json, os, random, re, shutil, sys, tempfile, threading, time
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402  (recursos_viejo: backend/recursos del commit de referencia)
S = _referencia.TMP
os.environ["PRIG_SIN_MOTOR_SUAVE"] = "1"
from recursos_viejo import termico as tv, frio as fv, ritmo as rv
from recursos import termico as tn, frio as fn, ritmo as rn
R = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
fallos = []
FECHA = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
def j(x): return FECHA.sub("F", json.dumps(x, ensure_ascii=False, default=str))

class Reloj:
    def __init__(self): self.t, self.n = 1000.0, 0
    def __call__(self): self.n += 1; return self.t

class MonitorFalso:
    def __init__(self, temps, tendencias, reloj):
        self.temps, self.tend, self.i, self.k, self.reloj, self.llamadas = temps, tendencias, 0, 0, reloj, []
    def gpu(self, max_edad=2.5):
        self.llamadas.append(("gpu", max_edad))
        t = self.temps[min(self.i, len(self.temps) - 1)]; self.i += 1
        return t
    def tendencia_gpu(self, desde=None):
        self.llamadas.append(("tend", desde))
        v = self.tend[min(self.k, len(self.tend) - 1)]; self.k += 1
        return v
    def trabajando(self):
        m = self
        class C:
            def __enter__(s): m.llamadas.append("entra"); return m
            def __exit__(s, *a): m.llamadas.append("sale"); return False
        return C()

def temp(): return R.choice([None, 40, 45.5, 50, 55, 57, 58, 59, 60, 61, 62.5, 66, 80, 42])

def correr(lado, plan):
    tmod, rmod = (tv, rv) if lado == "v" else (tn, rn)
    d = tempfile.mkdtemp(dir=S)
    reloj = Reloj()
    salida = []
    env = {"PRIG_RECURSOS_ARCHIVO": os.path.join(d, "r.json")}
    try:
        with mock.patch.dict(os.environ, env), mock.patch.object(time, "time", reloj), mock.patch.object(time, "sleep", lambda s: setattr(reloj, "t", reloj.t + s)):
            mon = MonitorFalso(plan["temps"], plan["tend"], reloj)
            g = tmod.Gobernador(mon, guardar=plan["guardar"])
            g.ritmo = rmod.Ritmo(plan["ritmo"])
            for k, v in plan["ajustes"].items():
                g.ajustes[k] = v
            dosifica, moe = plan["dosifica"], plan["moe"]
            g.dosifica_el_motor = lambda: dosifica
            with mock.patch.object(tmod, "_moe_generando", lambda: moe), mock.patch.object(g.fijador, "aplicar", lambda forzar=False: salida.append("fijar")):
                tramo = None
                for op, args, dt in plan["ops"]:
                    reloj.t += dt
                    try:
                        if op == "empezar":
                            tramo = g.empezar_tramo(); r = None
                        elif op == "cortar":
                            r = g.debe_cortar(tramo or tmod.Tramo(args[0]))
                        elif op == "terminar":
                            t2 = tramo or tmod.Tramo(args[0])
                            if args[1] is not None: t2.temp_corte = args[1]
                            if args[2] is not None: t2.pico_en_pausa = args[2]
                            r = g.terminar_tramo(t2, args[3])
                        elif op == "enfriar":
                            ev = []
                            cancelar = threading.Event()
                            pasos = [0]
                            def espera(s, pasos=pasos):
                                reloj.t += s; pasos[0] += 1
                                return pasos[0] > args[2]
                            with mock.patch.object(cancelar, "wait", side_effect=espera):
                                r = g.enfriar(args[0], cancelar if args[1] else None, ev.append, tramo=tramo if args[3] else None,
                                              objetivo=args[4], maximo_s=args[5])
                            salida.append(("eventos", ev))
                        elif op == "antes":
                            ev = []
                            cancelar = threading.Event()
                            with mock.patch.object(cancelar, "wait", side_effect=lambda s: setattr(reloj, "t", reloj.t + s) or reloj.t > 5000):
                                r = g.antes_de_trabajar(cancelar, ev.append)
                            salida.append(("eventos", ev))
                        elif op == "limite":
                            r = g.fijar_limite(args[0])
                        elif op == "olvidar":
                            r = g.olvidar()
                        elif op == "reposo":
                            r = g._anotar_reposo(args[0])
                        elif op == "estado":
                            r = {k: v for k, v in g.estado().items() if k != "ritmo"}
                        elif op == "descansar":
                            t2 = tramo or tmod.Tramo(40)
                            t2.pausa_ritmo = args[0]
                            r = g.descansar(t2)
                        salida.append(("ok", op, j(r)))
                    except Exception as e:
                        salida.append(("error", op, type(e).__name__, str(e)))
                    tr = None if tramo is None else (tramo.inicio, tramo.temp_inicio, tramo.pico, tramo.max_arranque, tramo.temp_corte, tramo.pico_en_pausa, getattr(tramo, "pausa_ritmo", None))
                    salida.append(("estado", j(dict(g.ajustes)), j(g.pausa), g.aviso, reloj.n, j(tr), g.limite, g.corte, g.reanudar, g.viable, g.limite_minimo_viable))
            salida.append(("monitor", mon.llamadas))
            archivo = open(env["PRIG_RECURSOS_ARCHIVO"]).read() if os.path.exists(env["PRIG_RECURSOS_ARCHIVO"]) else None
            salida.append(("archivo", FECHA.sub("F", archivo) if archivo else None))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return salida

for i in range(N):
    ops = []
    for _ in range(R.randint(1, 15)):
        k = R.randint(0, 9)
        if k == 0: ops.append(("empezar", (), R.choice([0, 1])))
        elif k in (1, 2): ops.append(("cortar", (temp(),), R.choice([0, 0.5, 1.5, 5])))
        elif k == 3: ops.append(("terminar", (temp(), R.choice([None, 59, 57.5]), R.choice([None, 60, 61, 66, 58.5]), R.choice([None, "limite", "ritmo", "prevision"])), R.choice([0, 1, 2, 5])))
        elif k == 4: ops.append(("enfriar", (R.choice(["limite", "prevision", "antes_de_paso", "ritmo", "otro"]), R.random() < 0.8, R.randint(0, 40), R.random() < 0.5, R.choice([None, 45.0, 50]), R.choice([600.0, 10.0, 3.0])), 0))
        elif k == 5: ops.append(("antes", (), 0))
        elif k == 6: ops.append(("limite", (R.choice([20, 40, 50, 58, 61.5, 95, 96]),), 0))
        elif k == 7: ops.append(("olvidar", (), 0))
        elif k == 8: ops.append(("reposo", (R.choice([42, 42.3, 45, 50.5]),), 0))
        else: ops.append(R.choice([("estado", (), 0), ("descansar", (R.choice([0, 0.5, 2.0, None]),), 0)]))
    plan = {"temps": [temp() for _ in range(300)], "tend": [R.choice([0.0, 0.3, 1.5, -1.0, 3.0]) for _ in range(50)],
            "guardar": R.random() < 0.5, "dosifica": R.random() < 0.2, "moe": R.random() < 0.2,
            "ritmo": R.choice([{"activo": False}, {"objetivo_c": 60, "rampa_s": 0, "tramo_s": 1.0, "cpu_eficiente": False},
                               {"objetivo_c": 55, "rampa_s": 20, "tramo_s": 0.5, "cpu_eficiente": True}]),
            "ajustes": R.choice([{}, {"limite_gpu": 80.0}, {"limite_gpu": 50.0, "salto_c": 8.0}, {"margen": 2.5, "frescas_seguidas": 7}]),
            "ops": ops}
    a, b = correr("v", plan), correr("n", plan)
    if a != b and len(fallos) < 6:
        for x, y in zip(a, b):
            if x != y: fallos.append(("gobernador", i, x, y)); break
        else: fallos.append(("gobernador-largo", len(a), len(b)))

# ---------------------------------------------------------------- controlador del modo frío
class PausadorFalso:
    def __init__(self): self.llamadas, self.procesos = [], {}
    def fijar(self, pids, fraccion): self.llamadas.append((sorted(pids), fraccion, type(pids).__name__))
    def cerrar(self): pass
for i in range(N):
    pasos = [(R.choice([{111}, {111, 222}, set(), {222, 7, 1000}]), {p: R.choice([0, 0.2, 1, 4, 8]) for p in (111, 222, 7, 1000)},
              R.choice([None, 40, 48, 55.5, 57, 58, 60, 66, 90]), R.choice([True, True, False]), R.choice([0.0, 0.0, 8.0]), R.random() < 0.3,
              R.choice([1.0, 1.0, 0.5, 0.0])) for _ in range(R.randint(1, 30))]
    obj = R.choice([60, 60.0, 55, 70.5])
    sal = {}
    for lado, mod in (("v", fv), ("n", fn)):
        t = [0.0]; cpu = {111: 0.0, 222: 0.0, 7: 0.0, 1000: 0.0}; lecturas = [0]; estado = {"pids": set(), "temp": None, "activo": True, "holgura": 0.0, "turbo": False}
        p = PausadorFalso()
        def leer_temp(): lecturas[0] += 1; return estado["temp"]
        c = mod.ControladorFrio(lambda: {"activo": estado["activo"], "objetivo_c": obj}, leer_temp, lambda: estado["pids"], pausador=p,
                                reloj=lambda: t[0], sin_turbo=lambda: estado["turbo"], holgura=lambda pids: estado["holgura"])
        salida = []
        with mock.patch.object(mod.Proceso, "tiempo_cpu", lambda self: cpu.get(self.pid)):
            for pids, nucleos, tmp, activo, holg, turbo, dt in pasos:
                estado.update(pids=set(pids), temp=tmp, activo=activo, holgura=holg, turbo=turbo)
                t[0] += dt
                for pid, n in nucleos.items(): cpu[pid] += n * (c.fraccion or 1.0) * dt
                try: salida.append(("ok", j(c.paso())))
                except Exception as e: salida.append(("error", type(e).__name__, str(e)))
                salida.append((c.fraccion, j(c.temp_media), lecturas[0], p.llamadas[-1:]))
        sal[lado] = salida
    if sal["v"] != sal["n"] and len(fallos) < 12:
        for x, y in zip(sal["v"], sal["n"]):
            if x != y: fallos.append(("frio", i, x, y)); break

# ---------------------------------------------------------------- monitor
for i in range(N):
    t = [100.0]
    lecturas = [{"tomada": None, "componentes": [{"tipo": "gpu", "temp": R.choice([None, 50, 52.5, 60])}, {"tipo": "gpu", "temp": R.choice([None, 51, 70])},
                                                  {"tipo": "cpu", "temp": R.choice([None, 70, 65.5])}]} for _ in range(40)]
    ops = [(R.choice(["muestrear", "lectura", "gpu", "tend"]), R.choice([0, 0.5, 1, 2, 3, 6]), R.choice([None, 1.0, 3.0]), R.choice([None, 103.0, 110.0])) for _ in range(R.randint(1, 40))]
    sal = {}
    for lado, mod in (("v", tv), ("n", tn)):
        reloj = Reloj(); reloj.t = 100.0; k = [0]
        def lector():
            l = dict(lecturas[k[0] % len(lecturas)]); l["tomada"] = reloj.t; k[0] += 1; return l
        salida = []
        with mock.patch.object(time, "time", reloj), mock.patch.object(threading, "Thread", mock.Mock()):
            m = mod.Monitor(lector)
            for op, dt, edad, desde in ops:
                reloj.t += dt
                if op == "muestrear": r = m._muestrear()
                elif op == "lectura": r = m.lectura(edad) if edad else m.lectura()
                elif op == "gpu": r = m.gpu(edad) if edad else m.gpu()
                else: r = m.tendencia_gpu(desde)
                salida.append((op, j(r), reloj.n, j(list(m.historial))))
        sal[lado] = salida
    if sal["v"] != sal["n"] and len(fallos) < 18:
        for x, y in zip(sal["v"], sal["n"]):
            if x != y: fallos.append(("monitor", i, x, y)); break
print("fallos:", len(fallos))
for f in fallos: print(json.dumps(f, ensure_ascii=False, default=str)[:1500])
