"""E7: medición con el modelo, aislada (sin memoria de resoluciones), reanudable.
  .venv/bin/python docs/estudio-banco/e7.py prig          → examen de Prig (153) + examen independiente (27)
  PRIG_BANCOS=~/.cache/prig-estudio/bancos .venv/bin/python docs/estudio-banco/e7.py externo
                                                         → examen de full-stack-fastapi-template
Antes: la pasada de lectura de la misma raíz (lectura_unidades.py --pasada). Resultados en el banco
(examen_resultados) y en ~/.cache/prig-estudio/e7/<nombre>.jsonl (modo de cada respuesta, examen independiente).
La configuración del usuario no se toca: el contexto «auto» y la carpeta de trabajo se fijan solo en memoria."""
import asyncio, atexit, json, os, re, sys, time
sys.path.insert(0, "/home/ama-gi/Prig/backend"); os.chdir("/home/ama-gi/Prig/backend")
QUE = sys.argv[1] if len(sys.argv) > 1 else "prig"
RAIZ = "/home/ama-gi/Prig" if QUE == "prig" else os.path.expanduser("~/.cache/prig-estudio/repos/full-stack-fastapi-template")
SALIDA = os.path.expanduser("~/.cache/prig-estudio/e7"); os.makedirs(SALIDA, exist_ok=True)
import examen_proyecto as ex
import app as A
A.file_mgr.base_dir = RAIZ                       # solo en memoria (no toca last_workspace)
A.ai_engine.config["moe_contexto"] = "auto"
atexit.register(A.ai_engine.unload_models)
banco = A.bancos.para(RAIZ); banco.sincronizar()
registro = os.path.join(SALIDA, f"{QUE}.jsonl")

def preguntar(texto):
    req = A.AIChatRequest(prompt=texto, model="qwen3.6-35b-moe:prig", eventos=True, banco=True, think=False, memoria=False)
    res = A.ai_chat(req)
    async def leer(): return [c async for c in res.body_iterator]
    salida, tokens, modo = "", 0, "general"
    for linea in "".join((c.decode() if isinstance(c, bytes) else c) for c in asyncio.run(leer())).splitlines():
        if not linea.strip(): continue
        ev = json.loads(linea)
        if ev["t"] == "texto": salida += ev["v"]
        elif ev["t"] == "banco": modo = ev["v"].get("modo") or "general"
        elif ev["t"] == "stats": tokens += ev["v"].get("tokens_respuesta", 0)
    with open(registro, "a") as f:
        f.write(json.dumps({"pregunta": texto[:200], "modo": modo, "tokens": tokens}, ensure_ascii=False) + "\n")
    return salida, {"tokens": tokens}

def ultima_corrida(variante):
    with banco.conectar() as c:
        ex._crear_tablas(c)
        f = c.execute("SELECT corrida FROM examen_resultados WHERE variante = ? ORDER BY cuando DESC LIMIT 1", (variante,)).fetchone()
    return f["corrida"] if f else None

variante = f"e7_{QUE}"
r = ex.correr(banco, variante, preguntar, saltar_de=ultima_corrida(variante),
              progreso=lambda p: print(f"{time.strftime('%H:%M:%S')} {p['n']}/{p['total']} {p['tipo']} {p['puntaje']}", flush=True))
print("RESUMEN", json.dumps(r, ensure_ascii=False, default=str), flush=True)

if QUE == "prig":
    # examen independiente: la verdad no sale del banco (docs/estudio-banco/examen_independiente.py)
    preguntas = json.load(open("/home/ama-gi/Prig/docs/estudio-banco/examen_independiente.json"))
    destino = os.path.join(SALIDA, "independiente.jsonl")
    hechas = {json.loads(l)["id"] for l in open(destino)} if os.path.exists(destino) else set()
    for p in preguntas:
        if p["id"] in hechas: continue
        t = time.time(); texto, meta = preguntar(p["pregunta"])
        norm = lambda s: re.sub(r"\s+", "", s.replace("'", '"')).lower()
        if p["evaluar"] == "valor_exacto":
            esperado = p["esperado"][0]
            candidatos = {esperado, esperado.replace("true", "True").replace("false", "False").replace("null", "None")}
            puntaje = 1.0 if any(norm(x) in norm(texto) for x in candidatos) else 0.0
        elif p["evaluar"] in ("conjunto", "contiene"):
            puntaje = round(sum(1 for e in p["esperado"] if ex._aparece(e, texto) or e in texto) / len(p["esperado"]), 3)
        else:
            puntaje = None            # rúbrica: corrección manual
        with open(destino, "a") as f:
            f.write(json.dumps({"id": p["id"], "tipo": p["tipo"], "puntaje": puntaje, "segundos": round(time.time() - t, 1),
                                "respuesta": texto}, ensure_ascii=False) + "\n")
        print(f"{time.strftime('%H:%M:%S')} independiente {p['id']} {p['tipo']} {puntaje}", flush=True)
    print("FIN INDEPENDIENTE", flush=True)
