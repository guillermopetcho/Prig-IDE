"""Diferencial de calibracion: la versión de Python puro (commit de referencia) contra la de ahora (Rust). Uso: .venv/bin/python calibracion.py [semilla] [vueltas]"""
import json, os, random, sys, tempfile, threading, time
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402  (recursos_viejo: backend/recursos del commit de referencia)
S = _referencia.TMP
os.environ["PRIG_SIN_MOTOR_SUAVE"] = "1"
os.environ["PRIG_RECURSOS_ARCHIVO"] = tempfile.mktemp(dir=S)
from recursos_viejo import calibracion as cv, calculadora as calv
from recursos import calibracion as cn, calculadora as caln
R = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
fallos = []
def j(x): return json.dumps(x, ensure_ascii=False, sort_keys=False, default=str)
def igual(nombre, fv, fn, *args):
    try: a = ("ok", j(fv(*args)))
    except Exception as e: a = ("error", type(e).__name__, str(e)[:200])
    try: b = ("ok", j(fn(*args)))
    except Exception as e: b = ("error", type(e).__name__, str(e)[:200])
    if a != b and len(fallos) < 12: fallos.append((nombre, repr(args)[:400], a, b))

CITAS = ["Cuanto mayor es lambda, más se penalizan los pesos grandes", "La parada temprana detiene el entrenamiento",
         "inventada por completo sin estar en el texto", "  «la normalización hace que la escala de los pesos»  ", "corta",
         "Durante la inferencia no se apaga\\nninguna neurona", 'con \\"comillas\\" dentro', "ÉPOCAS FIJO", "\t" * 3]
def respuesta():
    k = R.randint(0, 5)
    citas = R.sample(CITAS, R.randint(0, 4))
    if k == 0: return json.dumps({"afirmaciones": [{"texto": "x", "cita": c} for c in citas]}, ensure_ascii=R.random() < 0.5)
    if k == 1:
        t = json.dumps({"afirmaciones": [{"texto": "x", "cita": c} for c in citas]})
        return t[:R.randint(0, len(t))]
    if k == 2: return R.choice(["no es json", "", None, "[]", '{"afirmaciones": 3}', '{"afirmaciones": [1, {"cita": null}, {"x": 1}]}'])
    if k == 3: return '"cita" : "' + R.choice(CITAS) + '", "cita":"' + R.choice(CITAS)
    if k == 4: return '{"afirmaciones": [{"cita": "a\\\nb"}, {"cita": "' + R.choice(CITAS) + '"}]}'
    return '"cita":"Cuanto mayor es lambda, más se penalizan los pesos grandes" "cita" :"x\\q"'
for i in range(N * 3):
    igual("canario", cv.puntuar_canario, cn.puntuar_canario, respuesta())
    igual("oom", cv.es_oom, cn.es_oom, R.choice(["out of memory", "CUDA ERROR: x", "vk::Queue OutOfMemory", "vk::\nOutOfMemory", "model not found", "", None, "ErrorOutOfDeviceMemory", "Requires More System Memory"]))
    ficha = {"nombre": "m", "capas": R.choice([28, 0, None, 48]), "bytes_peso": R.choice([4683087561, 9276198565, 18622563179]), "fraccion_activa": R.choice([1.0, 0.11]),
             "kv_bytes_token_f16": R.choice([57344, 163840])}
    opc = R.choice([{"num_ctx": 8192}, {"num_ctx": 4096}, {"num_ctx": 2048}, {"num_ctx": 2048, "num_gpu": 3}, {"num_ctx": 1024, "num_gpu": 0}, {"num_ctx": 3000.0}, {}, {"num_ctx": 2048, "num_gpu": 29}])
    igual("reducir", cv.reducir, cn.reducir, ficha, opc)
    rad = {"gpus": R.choice([[], [{"nombre": "RTX 4050 Laptop", "vram_total_mb": 6141}]]), "memoria": {"ram_disponible": 50e9}}
    maq = (calv.Maquina(rad), caln.Maquina(rad))
    r = {"ok": R.choice([True, False]), "tok_s": R.choice([0, 6.3, 37.2, 25.0]), "total_gb": R.choice([0, 4.75, 10.15, 19.0]),
         "fraccion_gpu": R.choice([None, 0.0, 0.01, 0.476, 0.995, 1.0, 0.25]), "opciones": R.choice([{"num_ctx": 4096}, {"num_ctx": 2048, "num_gpu": 10}])}
    igual("deducir", lambda *a: cv.deducir(*a, maq[0]), lambda *a: cn.deducir(*a, maq[1]), ficha, r)
    previa = R.choice([None, {}, {"muestras": {"ancho_gpu": [170.0, 180.0], "presupuesto_minimo": [4.8e9]}}, {"muestras": {"ancho_cpu": [38, 40, 41]}}])
    nuevas = [{k: R.choice([1.0, 2, True, "x", None, 4.0e9, 5.0e9]) for k in R.sample(["ancho_gpu", "ancho_cpu", "presupuesto_gpu", "presupuesto_minimo", "vram_parcial"], R.randint(0, 3))} for _ in range(R.randint(0, 12))]
    igual("combinar", cv.combinar, cn.combinar, previa, nuevas)
FICHAS = [{"nombre": f"m{k}", "bytes_peso": b, "kv_bytes_token_f16": 57344, "capas": 28, "embedding": e, "estimada": s}
          for k, (b, e, s) in enumerate([(4683087561, False, False), (9276198565, False, False), (18622563179, False, False), (274302450, True, False), (3e9, False, True), (0, False, False), (6e9, False, False)])]
for i in range(N):
    rad = {"gpus": R.choice([[], [{"nombre": "RTX 4050 Laptop", "vram_total_mb": R.choice([4096, 6141, 12282])}]]), "memoria": {"ram_disponible": R.choice([8e9, 50e9])}}
    fs = R.sample(FICHAS, R.randint(0, len(FICHAS)))
    igual("elegir", lambda f: cv.elegir_modelos_prueba(f, calv.Maquina(rad)), lambda f: cn.elegir_modelos_prueba(f, caln.Maquina(rad)), fs)

# probar con un motor guionizado
QWEN3 = {"nombre": "qwen3:14b", "bytes_peso": 9276198565, "capas": 40, "piensa": True, "kv_bytes_token_f16": 163840}
QWEN25 = {"nombre": "qwen2.5-coder:7b", "bytes_peso": 4683087561, "capas": 28, "piensa": False, "kv_bytes_token_f16": 57344}
class Reloj:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
for i in range(N):
    guion = [R.choice(["ok", "oom", "oom2", "otro", "calor", "ok_json"]) for _ in range(6)]
    temps = [R.choice([None, 40.0, 55.0, 70.0]) for _ in range(3)]
    ficha = R.choice([QWEN3, QWEN25])
    opciones = R.choice([{"num_ctx": 4096}, {"num_ctx": 8192, "think": True, "otra": 1}, {}, {"num_gpu": 5, "num_ctx": 2048}])
    cancelar = R.random() < 0.1
    dejar = R.random() < 0.3
    cargado = R.choice([None, {"size": 10e9, "size_vram": 4.7e9}])
    sal = []
    for mod in (cv, cn):
        cuerpos, eventos, descargas, suenos = [], [], [], []
        g = list(guion)
        def generar(cuerpo, mod=mod, g=g, cuerpos=cuerpos):
            cuerpos.append(json.loads(j(cuerpo)))
            paso = g.pop(0) if g else "ok"
            if paso == "oom": raise RuntimeError("llama runner process has terminated: cudaMalloc failed: out of memory")
            if paso == "oom2": raise RuntimeError("CUDA error: out of memory")
            if paso == "otro": raise RuntimeError("model 'x' not found")
            if paso == "calor": raise mod._PorCalor()
            texto = json.dumps({"afirmaciones": [{"texto": "a", "cita": "Cuanto mayor es lambda, más se penalizan los pesos grandes"}]}) if paso == "ok_json" else "{}"
            return {"response": texto, "eval_count": 160, "eval_duration": int(4e9), "prompt_eval_count": 500, "prompt_eval_duration": int(0.3e9), "load_duration": int(2e9), "done": True}
        ts = list(temps)
        def estado(ts=ts):
            if threading.current_thread() is not threading.main_thread():
                return None          # el muestreador (otro hilo) no consume el guion: sería una carrera
            if not ts:
                return None
            t = ts.pop(0)
            return None if t is None else {"vram_mb": 1000.0, "temp_c": t, "consumo_w": 10.0}
        reloj = Reloj()
        ev = threading.Event()
        if cancelar: ev.set()
        def espera(s, reloj=reloj):
            reloj.t += s
            return False
        def dormir(s, suenos=suenos, reloj=reloj):
            suenos.append(s)
            reloj.t += s
        with mock.patch.object(mod, "estado_gpu", estado), \
                mock.patch.object(mod, "descargar", lambda m, d=descargas: d.append(m)), \
                mock.patch.object(time, "sleep", dormir), \
                mock.patch.object(time, "time", reloj), mock.patch.object(ev, "wait", side_effect=espera):
            try:
                r = ("ok", j(mod.probar(ficha, opciones, eventos.append, ev, 200, dejar, generar, lambda m, c=cargado: c)))
            except Exception as e:
                r = ("error", type(e).__name__, str(e))
        sal.append((r, j(eventos), j(cuerpos), descargas, suenos))
    a, b = sal
    if a != b and len(fallos) < 12:
        for x, y in zip(a, b):
            if x != y:
                fallos.append(("probar", guion, temps, opciones, cancelar, str(x)[:1500], str(y)[:1500]))
                break
print("fallos:", len(fallos))
for f in fallos[:8]: print(json.dumps(f, ensure_ascii=False, default=str)[:1500])
