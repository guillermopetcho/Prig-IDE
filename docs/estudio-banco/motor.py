"""E4: motor y máquina. Restauración exacta (misma respuesta token a token), latencias en frío y en
caliente, velocidad de lectura y generación, MTP tras leer y tras restaurar, VRAM y temperatura.
Usa un estado de prueba propio (e4_prueba.bin) que borra al final. La configuración del usuario no se toca.
Uso: .venv/bin/python docs/estudio-banco/motor.py"""
import sys, os, json, time, subprocess, atexit
sys.path.insert(0, "/home/ama-gi/Prig/backend"); os.chdir("/home/ama-gi/Prig/backend")
import app as A
import lectura_unidades as lu
from ai_engine import motor_moe
atexit.register(A.ai_engine.unload_models)
def gpu():
    q = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,temperature.gpu,clocks.sm,power.draw", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True).stdout.strip().split(", ")
    return {"vram_mb": int(q[0]), "temp_c": int(q[1]), "reloj_mhz": int(q[2]), "watts": float(q[3])}
def enfriar(ruta):   # saca el archivo de la caché de páginas del sistema (sin root)
    fd = os.open(ruta, os.O_RDONLY); os.fsync(fd) if False else None
    os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED); os.close(fd)
res = {"gpu_reposo": gpu()}
m = A.ai_engine.motor_moe()
t = time.time(); m.asegurar(); res["arranque_s"] = round(time.time() - t, 1)
res["motor"] = {k: v for k, v in m.estado().items() if k in ("contexto", "calientes_por_capa", "mtp", "modo", "nucleos")}
res["gpu_motor_cargado"] = gpu()
banco = A.bancos.para("/home/ama-gi/Prig"); L = lu.LectorUnidades(banco, A.ai_engine)
u = next(x for x in L._unidades.values() if 14000 <= x["tokens"] <= 15500)
plantilla = m.directo("POST", "/apply-template", {"messages": L.mensajes(u)})["prompt"]
P = plantilla
Q = ("<|im_start|>user\nList the three most important functions in this code and say in one sentence "
     "what each one does.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
def completar(prompt, cache, n=220):
    t = time.time()
    r = m.directo("POST", "/completion", {"prompt": prompt, "n_predict": n, "temperature": 0, "top_k": 1,
                                         "cache_prompt": cache, "seed": 1})
    return r, round(time.time() - t, 2)
m.directo("POST", "/slots/0?action=erase", {})
# 1. lectura completa desde cero + pregunta
r1, s1 = completar(P + Q, False)
res["lectura_desde_cero"] = {"segundos": s1, "timings": r1.get("timings"), "gpu": gpu()}
texto_fresco = r1["content"]
# 2. guardar el estado tras leer SOLO el prefijo
m.directo("POST", "/slots/0?action=erase", {})
r0, s0 = completar(P, True, n=0)
res["lectura_prefijo"] = {"segundos": s0, "tokens": (r0.get("timings") or {}).get("prompt_n"), "tok_s": (r0.get("timings") or {}).get("prompt_per_second")}
t = time.time(); m.directo("POST", "/slots/0?action=save", {"filename": "e4_prueba.bin"}); res["guardar_s"] = round(time.time() - t, 2)
archivo = os.path.join(motor_moe.CARPETA_PROYECTOS, "e4_prueba.bin")
res["bytes_estado"] = os.path.getsize(archivo)
# 3. restaurar en frío y en caliente, y la misma pregunta
rest = []
for modo in ("frio", "caliente", "frio", "caliente"):
    m.directo("POST", "/slots/0?action=erase", {})
    if modo == "frio": enfriar(archivo)
    t = time.time(); m.directo("POST", "/slots/0?action=restore", {"filename": "e4_prueba.bin"}); tr = round(time.time() - t, 3)
    r, s = completar(P + Q, True)
    rest.append({"modo": modo, "restaurar_s": tr, "responder_s": s, "timings": r.get("timings"), "igual_a_lectura": r["content"] == texto_fresco})
res["restauraciones"] = rest
# 4. lectura del archivo en crudo (disco), en frío
enfriar(archivo); t = time.time()
with open(archivo, "rb") as f:
    while f.read(16 << 20): pass
res["disco_MBps_frio"] = round(res["bytes_estado"] / 1e6 / (time.time() - t))
res["gpu_final"] = gpu()
os.remove(archivo)
res["respuesta_muestra"] = texto_fresco[:300]
print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
