"""Sondas con el modelo para E8 y E9: una lista de preguntas sobre una copia del proyecto, con las mismas
condiciones que los lotes de E7 (lote.py) pero sin el examen.

  .venv/bin/python docs/estudio-banco/sonda.py RAIZ PREGUNTAS.json SALIDA.json [--memoria] [--limite 600]

PREGUNTAS.json: [{"id": ..., "pregunta": ...}, ...] (los demás campos se copian al informe tal cual).
El informe guarda, por pregunta: la respuesta, los segundos, el modo (unidad / general), las consultas a la consola
y si se cortó por tiempo. La corrección va aparte (e8.py, e9.py y la auditoría a mano).

Condiciones: sin vectores (el embebedor se desactiva en este proceso), sin memoria salvo --memoria, GPU libre al
empezar, ningún llama-server corriendo, contexto «auto» y carpeta de trabajo solo en memoria (la configuración del
usuario no se toca). Los bancos de las copias viven en ~/.cache/prig-estudio/bancos."""
import asyncio, atexit, contextlib, json, os, subprocess, sys, time
RAIZ, PREGUNTAS, SALIDA = (os.path.abspath(os.path.expanduser(x)) for x in sys.argv[1:4])
MEMORIA = "--memoria" in sys.argv
LIMITE_S = int(sys.argv[sys.argv.index("--limite") + 1]) if "--limite" in sys.argv else 600
os.environ["PRIG_BANCOS"] = os.path.expanduser("~/.cache/prig-estudio/bancos")
SISTEMA = "/home/ama-gi/Prig"
sys.path.insert(0, os.path.join(SISTEMA, "backend"))
import banco_proyecto as bp, lectura_unidades as lu
bp.BancoProyecto._embebedor_ok = lambda self: False
bp.BancoProyecto.indexar_vectores = lambda self, *a, **k: {"omitido": "medición sin vectores"}
banco = bp.BancoProyecto(RAIZ)
assert banco.ruta_db.startswith(os.environ["PRIG_BANCOS"]), banco.ruta_db


def gpu():
    q = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,temperature.gpu", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True).stdout.strip().split(", ")
    return {"vram_mb": int(q[0]), "temp_c": int(q[1])}


def conteo(tabla):
    with banco.conectar() as c:
        return c.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


preguntas = json.load(open(PREGUNTAS))
problemas = []
sinc = banco.sincronizar()
lector = lu.LectorUnidades(banco, None)
vencidas = [o for o in lector._unidades if not lector.vigente(o)]
if subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True).returncode == 0:
    problemas.append("ya hay un llama-server corriendo")
g0 = gpu()
if g0["temp_c"] > 70 or g0["vram_mb"] > 600:
    problemas.append(f"GPU no disponible ({g0})")
if conteo("vectores"):
    problemas.append(f"el banco tiene {conteo('vectores')} vectores")
if not MEMORIA and (conteo("resoluciones") or conteo("conocimiento")):
    problemas.append("hay memoria guardada y la sonda es sin memoria")
if problemas:
    print("NO SE CORRE la sonda ·", "; ".join(problemas)); sys.exit(1)
condiciones = {"raiz": RAIZ, "banco": banco.ruta_db, "memoria": MEMORIA, "limite_s": LIMITE_S, "gpu_antes": g0,
               "sincronizacion": {k: sinc[k] for k in ("nuevos", "modificados", "borrados")},
               "unidades": len(lector._unidades), "vencidas": vencidas,
               "resoluciones": conteo("resoluciones"), "conocimiento": conteo("conocimiento"), "cambios": conteo("cambios")}
print("CONDICIONES", json.dumps(condiciones, ensure_ascii=False), flush=True)

os.chdir(os.path.join(SISTEMA, "backend"))
import app as A
A.bancos.embebedor_listo = lambda: False
A.file_mgr.base_dir = RAIZ; A.ai_engine.config["moe_contexto"] = "auto"
atexit.register(A.ai_engine.unload_models)


def cortar_generacion():
    """ Igual que lote.cortar_generacion: cancelar y, si el motor sigue ocupado, detenerlo desde dentro """
    with contextlib.suppress(Exception):
        A.ai_engine.cancel_active_requests()
    motor = A.ai_engine.motor_moe()
    ocupado = lambda: bool(getattr(motor, "_activas", 0))
    for _ in range(20):
        if not ocupado(): return "cancelada"
        time.sleep(0.5)
    motor.detener()
    for _ in range(120):
        if not ocupado(): return "motor detenido"
        time.sleep(0.5)
    return "motor detenido; seguía ocupado"


def limpiar_memoria_escrita():
    """ Igual que lote.limpiar_memoria_escrita: sin --memoria, lo que el modelo anote se registra y se borra después
    de cada pregunta (memoria=False no le impide usar «anotar») """
    with banco.conectar() as c:
        notas = [dict(f) for f in c.execute("SELECT id, tipo, titulo, texto, rutas, origen FROM conocimiento")]
        resol = [dict(f) for f in c.execute("SELECT id, pregunta, resumen FROM resoluciones")]
        if notas:
            c.execute("DELETE FROM conocimiento_fts WHERE rowid IN (SELECT id FROM conocimiento)"); c.execute("DELETE FROM conocimiento")
        if resol:
            c.execute("DELETE FROM resoluciones_fts WHERE rowid IN (SELECT id FROM resoluciones)"); c.execute("DELETE FROM resoluciones")
    return {"notas": notas, "resoluciones": resol} if (notas or resol) else None


def preguntar(texto):
    """ Igual que lote.preguntar: el flujo del chat con banco, cortado como el botón Detener si pasa el límite """
    req = A.AIChatRequest(prompt=texto, model="qwen3.6-35b-moe:prig", eventos=True, banco=True, think=False, memoria=MEMORIA)
    res = A.ai_chat(req)
    trozos = []
    async def leer():
        it, fin = res.body_iterator.__aiter__(), time.monotonic() + LIMITE_S
        try:
            while True:
                trozos.append(await asyncio.wait_for(it.__anext__(), max(0.01, fin - time.monotonic())))
        except StopAsyncIteration:
            return False
        except asyncio.TimeoutError:
            corte[0] = cortar_generacion()
            return True
        finally:
            with contextlib.suppress(Exception):
                await it.aclose()
    corte = [None]
    agotada = asyncio.run(leer())
    salida, tokens, modo, usadas, unidad = "", 0, "general", [], None
    for linea in "".join((c.decode() if isinstance(c, bytes) else c) for c in trozos).splitlines():
        if not linea.strip(): continue
        try:
            ev = json.loads(linea)
        except ValueError:
            if agotada: continue
            raise
        if ev["t"] == "texto": salida += ev["v"]
        elif ev["t"] == "banco":
            modo = ev["v"].get("modo") or "general"; unidad = ev["v"].get("unidad", unidad)
        elif ev["t"] == "stats": tokens += ev["v"].get("tokens_respuesta", 0)
        elif ev["t"] == "herramienta":
            usadas.append({"nombre": ev.get("nombre"), "argumentos": json.dumps(ev.get("argumentos"), ensure_ascii=False)[:400]})
        elif ev["t"] == "resultado" and usadas:
            usadas[-1]["resultado_caracteres"] = len(str(ev.get("v") or ""))
    return {"respuesta": salida, "agotada": agotada, "corte": corte[0], "modo": modo, "unidad": unidad, "tokens": tokens,
            "consultas": usadas}


t0, resultados = time.time(), []
for i, p in enumerate(preguntas, 1):
    t = time.time()
    r = preguntar(p["pregunta"])
    r = {**p, **r, "segundos": round(time.time() - t, 1)}
    if not MEMORIA:
        r["memoria_del_modelo"] = limpiar_memoria_escrita()
    resultados.append(r)
    print(f"{time.strftime('%H:%M:%S')} {i}/{len(preguntas)} {p['id']} {r['modo']} {r['segundos']} s"
          + (" AGOTADA" if r["agotada"] else "") + ("" if r["respuesta"].strip() else " VACÍA"), flush=True)
    json.dump({"condiciones": condiciones, "resultados": resultados}, open(SALIDA, "w"), ensure_ascii=False, indent=1)
condiciones["gpu_despues"] = gpu()
condiciones["segundos"] = round(time.time() - t0)
condiciones["vectores_despues"] = conteo("vectores")
condiciones["memoria_despues"] = {"resoluciones": conteo("resoluciones"), "conocimiento": conteo("conocimiento")}
json.dump({"condiciones": condiciones, "resultados": resultados}, open(SALIDA, "w"), ensure_ascii=False, indent=1)
vacias = [r["id"] for r in resultados if not r["respuesta"].strip()]
print("FIN DE LA SONDA", json.dumps({"preguntas": len(resultados), "segundos": condiciones["segundos"], "vacias": vacias,
                                     "agotadas": [r["id"] for r in resultados if r["agotada"]]}, ensure_ascii=False), flush=True)
sys.exit(1 if vacias else 0)
