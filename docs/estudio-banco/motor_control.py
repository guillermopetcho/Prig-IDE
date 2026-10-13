"""E4 (control): ¿la diferencia entre leer de una vez y restaurar viene de la restauración o del reparto
en lotes? Compara: una vez (×2), dos pasos sin guardar (×2) y dos pasos con guardar/restaurar."""
import sys, os, json, time, atexit
sys.path.insert(0, "/home/ama-gi/Prig/backend"); os.chdir("/home/ama-gi/Prig/backend")
import app as A
import lectura_unidades as lu
from ai_engine import motor_moe
atexit.register(A.ai_engine.unload_models)
m = A.ai_engine.motor_moe(); m.asegurar()
L = lu.LectorUnidades(A.bancos.para("/home/ama-gi/Prig"), A.ai_engine)
u = next(x for x in L._unidades.values() if 14000 <= x["tokens"] <= 15500)
P = m.directo("POST", "/apply-template", {"messages": L.mensajes(u)})["prompt"]
Q = ("<|im_start|>user\nList the three most important functions in this code and say in one sentence "
     "what each one does.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
def comp(prompt, cache, n=220):
    return m.directo("POST", "/completion", {"prompt": prompt, "n_predict": n, "temperature": 0, "top_k": 1, "cache_prompt": cache, "seed": 1})
salidas = {}
for i in (1, 2):
    m.directo("POST", "/slots/0?action=erase", {}); salidas[f"una_vez_{i}"] = comp(P + Q, False)["content"]
for i in (1, 2):
    m.directo("POST", "/slots/0?action=erase", {}); comp(P, True, 0); salidas[f"dos_pasos_{i}"] = comp(P + Q, True)["content"]
m.directo("POST", "/slots/0?action=erase", {}); comp(P, True, 0)
m.directo("POST", "/slots/0?action=save", {"filename": "e4_control.bin"})
m.directo("POST", "/slots/0?action=erase", {}); m.directo("POST", "/slots/0?action=restore", {"filename": "e4_control.bin"})
salidas["restaurado"] = comp(P + Q, True)["content"]
os.remove(os.path.join(motor_moe.CARPETA_PROYECTOS, "e4_control.bin"))
nombres = list(salidas)
print(json.dumps({"iguales": {f"{a} = {b}": salidas[a] == salidas[b] for i, a in enumerate(nombres) for b in nombres[i+1:]},
                  "tokens_aprox": {k: len(v) for k, v in salidas.items()}}, ensure_ascii=False, indent=1))
