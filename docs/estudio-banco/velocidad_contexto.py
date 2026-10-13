"""¿La generación es más lenta con más contexto? Mismo pedido con ~300 y con ~20.000 tokens delante."""
import sys, os, json, time, atexit
sys.path.insert(0, "/home/ama-gi/Prig/backend"); os.chdir("/home/ama-gi/Prig/backend")
import app as A
import lectura_unidades as lu
atexit.register(A.ai_engine.unload_models)
m = A.ai_engine.motor_moe(); m.asegurar()
L = lu.LectorUnidades(A.bancos.para("/home/ama-gi/Prig"), A.ai_engine)
u = next(x for x in L._unidades.values() if 14000 <= x["tokens"] <= 15500)
largo = m.directo("POST", "/apply-template", {"messages": L.mensajes(u)})["prompt"]
corto = m.directo("POST", "/apply-template", {"messages": [{"role": "system", "content": "You are a code assistant."},
    {"role": "user", "content": L.codigo_unidad(u)[:1200]}]})["prompt"]
Q = ("<|im_start|>user\nList the three most important functions in this code and say in one sentence "
     "what each one does.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
for nombre, prefijo in (("corto", corto), ("largo", largo), ("corto_2", corto)):
    m.directo("POST", "/slots/0?action=erase", {})
    r = m.directo("POST", "/completion", {"prompt": prefijo + Q, "n_predict": 250, "temperature": 0, "top_k": 1, "cache_prompt": False})
    t = r.get("timings") or {}
    print(nombre, "contexto", t.get("prompt_n"), "· generación", round(t.get("predicted_per_second") or 0, 1), "tok/s ·",
          t.get("predicted_n"), "tokens · MTP", t.get("draft_n_accepted"), "/", t.get("draft_n"))
