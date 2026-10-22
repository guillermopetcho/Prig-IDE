"""Prueba con el motor MoE de verdad (usa la GPU unos minutos): las mismas preguntas, con temperatura 0 y semilla
fija, por la versión de Python puro (REFERENCIA) y por la de ahora, contra el MISMO llama-server: las respuestas
tienen que ser idénticas. No toca Ollama (no descarga sus modelos) ni guarda estados de proyectos.

    .venv/bin/python herramientas/diferencial_plataforma/moe_real.py
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import viejo  # noqa: E402
os.environ["NO_PROXY"] = "127.0.0.1"
from ai_engine import motor_moe as mn  # noqa: E402
from ai_engine import AIEngine  # noqa: E402
mv = viejo("motor_moe", "ai_engine/motor_moe.py")
mv.LIB, mv.SERVIDOR, mv.LISTA = mn.LIB, mn.SERVIDOR, mn.LISTA

ia = AIEngine()
ajustes = ia.motor_moe().ajustes
motor = mn.Motor(liberar_gpu=lambda: None, ajustes=lambda: {**ajustes(), "cache_gb": 0})
t0 = time.time()
print("arrancando el motor…", flush=True)
carga = motor.asegurar()
print(f"listo en {carga:.1f} s ({motor.calientes} calientes/capa, MTP {motor.mtp})", flush=True)
viejo_m = mv.Motor(liberar_gpu=lambda: None, ajustes=lambda: {**ajustes(), "cache_gb": 0})
viejo_m._puerto, viejo_m._proc = motor._puerto, motor._proc
viejo_m.asegurar = lambda: 0.0
viejo_m.contexto = motor.contexto

PREGUNTAS = [
    "¿Qué es un experto en un modelo de mezcla de expertos (MoE)? Responde en dos frases.",
    "Escribe una función de Python que devuelva los números primos menores que n.",
    "Explain in one sentence what a KV cache is.",
]
iguales = 0
try:
    for i, q in enumerate(PREGUNTAS):
        pedido = {"messages": [{"role": "user", "content": q}], "stream": True, "think": False,
                  "options": {"temperature": 0, "seed": 7, "num_predict": 160}, "keep_alive": "5m"}
        salidas = []
        orden = (("nuevo", motor), ("viejo", viejo_m)) if i % 2 else (("viejo", viejo_m), ("nuevo", motor))
        for nombre, m in orden:
            t = time.time()
            r = m.post("http://x/api/chat", json.loads(json.dumps(pedido)))
            texto, final = "", {}
            for linea in r.iter_lines():
                d = json.loads(linea)
                texto += (d.get("message") or {}).get("content") or ""
                if d.get("done"):
                    final = d
            salidas.append(texto)
            print(f"[{i}] {nombre}: {time.time() - t:.1f} s, {final.get('eval_count')} tokens", flush=True)
        igual = salidas[0] == salidas[1]  # (en el orden de la vuelta)
        iguales += igual
        print(f"[{i}] {'IGUALES' if igual else 'DISTINTAS'}\n--- {salidas[0][:300]!r}" + ("" if igual else f"\n+++ {salidas[1][:300]!r}"), flush=True)
finally:
    motor.detener()
print(json.dumps({"preguntas": len(PREGUNTAS), "iguales": iguales, "segundos": round(time.time() - t0)}))
