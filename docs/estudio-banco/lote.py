"""E7 por lotes cortos y verificados.

  .venv/bin/python docs/estudio-banco/lote.py preparar prig       → limpia el banco medido (sin examen, vectores ni historial)
  .venv/bin/python docs/estudio-banco/lote.py examen   prig       → genera el examen en su base aparte
  .venv/bin/python docs/estudio-banco/lote.py plan     prig       → congela el plan de lotes (preguntas mezcladas por tipo)
  .venv/bin/python docs/estudio-banco/lote.py correr   prig 1     → corre el lote 1 y lo verifica (--rep: repetición, para medir el ruido)
  .venv/bin/python docs/estudio-banco/lote.py estado   prig       → qué lotes están hechos y verificados
  («externo» en lugar de «prig»: el repositorio full-stack-fastapi-template)

Objeto medido: COPIAS CONGELADAS Y LIMPIAS (docs/estudio-banco/congelar.py), con sus bancos en ~/.cache/prig-estudio/bancos.
Sistema bajo prueba: el backend de /home/ama-gi/Prig (su huella se fija en el plan: si cambia, no se mezcla).

El examen NO vive en el banco que lee el modelo: la consola P puede leer cualquier tabla del banco (P.sql, P.esquema), y el
02/10 el modelo citó la clave de corrección que estaba dentro del proyecto medido. Las preguntas, lo esperado y los
resultados están en ~/.cache/prig-estudio/e7/examen_<repo>.db; el banco se adjunta ahí solo para leer.

Condiciones fijas, verificadas en cada lote: sin memoria de resoluciones, SIN VECTORES (el proceso desactiva el
embebedor aunque Ollama esté en marcha), sin tablas del examen ni historial de cambios en el banco, GPU libre al empezar,
código medido y sistema idénticos a los del plan, examen idéntico al del plan.
Se registra qué herramientas usó el modelo en cada respuesta (para auditar qué consultó).
La configuración del usuario no se toca (contexto «auto» y carpeta de trabajo solo en memoria)."""
import asyncio, atexit, contextlib, glob, hashlib, json, os, random, re, sqlite3, subprocess, sys, time
ACCION, QUE = sys.argv[1], sys.argv[2]
REPETICION = "--rep" in sys.argv
os.environ["PRIG_BANCOS"] = os.path.expanduser("~/.cache/prig-estudio/bancos")     # antes de crear cualquier banco
SISTEMA = "/home/ama-gi/Prig"
sys.path.insert(0, os.path.join(SISTEMA, "backend"))
RAIZ = os.path.expanduser("~/.cache/prig-estudio/repos/" + ("Prig" if QUE == "prig" else "full-stack-fastapi-template"))
DIR = os.path.expanduser("~/.cache/prig-estudio/e7"); os.makedirs(DIR, exist_ok=True)
PLAN = os.path.join(DIR, f"plan_{QUE}.json")
EXAMEN_DB = os.path.join(DIR, f"examen_{QUE}.db")
INDEP = os.path.join(SISTEMA, "docs/estudio-banco/examen_independiente.json")
RESPALDO = os.path.expanduser("~/.cache/prig-estudio/banco-Prig-respaldo-2026-09-30/banco.db")
TAM = 12
VRAM_MAX_ANTES_MB = 600

import banco_proyecto as bp, examen_proyecto as ex, lectura_unidades as lu
from ai_engine import motor_moe
# Sin vectores en este proceso: ni búsqueda semántica ni el vigilante indexando (con Ollama en marcha lo haría,
# y además ocuparía la GPU que necesita el motor)
bp.BancoProyecto._embebedor_ok = lambda self: False
bp.BancoProyecto.indexar_vectores = lambda self, *a, **k: {"omitido": "medición sin vectores"}
banco = bp.BancoProyecto(RAIZ)
assert banco.ruta_db.startswith(os.environ["PRIG_BANCOS"]), banco.ruta_db


class AlmacenExamen:
    """ El examen en su propia base, con el banco medido adjunto SOLO PARA LEER (examen_proyecto lee los símbolos y el
    grafo del banco para generar y corregir). Se usa donde examen_proyecto espera «banco». """
    def __init__(self, ruta: str, banco_medido):
        self.ruta, self.banco = ruta, banco_medido

    @contextlib.contextmanager
    def conectar(self):
        c = sqlite3.connect(f"file:{self.ruta}", uri=True, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("ATTACH DATABASE ? AS medido", (f"file:{self.banco.ruta_db}?mode=ro",))
        try:
            yield c
            c.commit()
        finally:
            c.close()

    @property
    def version(self):
        return meta("version")


almacen = AlmacenExamen(EXAMEN_DB, banco)

def meta(clave):
    with banco.conectar() as c:
        f = c.execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
    return f[0] if f else None

def huella_codigo():
    """ Huella del código de producción del proyecto medido (lo que entra en las unidades) """
    import particion_proyecto as pp
    with banco.conectar() as c:
        filas = sorted((r, s) for r, l, s in c.execute("SELECT ruta, lenguaje, sha FROM archivos") if pp.es_produccion(r, l))
    return hashlib.sha1(json.dumps(filas).encode()).hexdigest()[:16]

def huella_sistema():
    """ Huella del sistema bajo prueba: el backend (sin tests) y main.py del repositorio de trabajo """
    archivos = sorted(glob.glob(os.path.join(SISTEMA, "backend/**/*.py"), recursive=True) + [os.path.join(SISTEMA, "main.py")])
    h = hashlib.sha1()
    for a in archivos:
        if "/tests/" in a or "__pycache__" in a: continue
        h.update(os.path.relpath(a, SISTEMA).encode()); h.update(open(a, "rb").read())
    return h.hexdigest()[:16]

def conteo(tabla):
    with banco.conectar() as c:
        return c.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]

def tablas_examen_en_banco():
    with banco.conectar() as c:
        return [f[0] for f in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'examen%'")]

def gpu():
    q = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,temperature.gpu", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True).stdout.strip().split(", ")
    return {"vram_mb": int(q[0]), "temp_c": int(q[1])}

def corregir_indep(p, texto):
    """ Puntaje automático de una pregunta del examen independiente (None: rúbrica, se corrige a mano).
    Valor exacto: el valor real, también escrito como Python (True/False/None y tuplas: la clave se guarda en JSON,
    donde (2048, 1803, 2580) queda como [2048, 1803, 2580]; antes eso daba 0 a una respuesta correcta).
    Un texto se guarda con comillas JSON ("/api/x/*/y") y el modelo lo escribe entre backticks (`/api/x/*/y`): también
    vale (03/10, lote 3: ind_02 exacto daba 0). Sin delimitador no: "js" o "md" sueltos aparecen en cualquier texto """
    norm = lambda s: re.sub(r"\s+", "", s.replace("'", '"')).lower()
    if p["evaluar"] == "valor_exacto":
        e = p["esperado"][0]
        cands = {e, e.replace("true", "True").replace("false", "False").replace("null", "None")}
        cands |= {x.replace("[", "(").replace("]", ")") for x in list(cands)}
        if len(e) >= 2 and e[0] == e[-1] == '"':
            cands.add("`" + e[1:-1] + "`")
        return 1.0 if any(norm(x) in norm(texto) for x in cands) else 0.0
    if p["evaluar"] in ("conjunto", "contiene"):
        return round(sum(1 for x in p["esperado"] if ex._aparece(x, texto) or x in texto) / len(p["esperado"]), 3)
    return None

# ------------------------------------------------------------------------------------------ preparar, examen, plan
if ACCION == "recorregir":
    # vuelve a puntuar las preguntas independientes de los lotes ya hechos con el corrector actual
    indep = {p["id"]: p for p in json.load(open(INDEP))}
    for f in sorted(glob.glob(os.path.join(DIR, f"{QUE}_lote*.json"))):
        inf = json.load(open(f)); cambios = []
        for x in inf["resultados"]:
            if x["id"] in indep:
                nuevo = corregir_indep(indep[x["id"]], inf["respuestas"][x["id"]])
                if nuevo != x["puntaje"]:
                    cambios.append((x["id"], x["puntaje"], nuevo)); x.setdefault("puntaje_original", x["puntaje"]); x["puntaje"] = nuevo
        if cambios:
            v = [x["puntaje"] for x in inf["resultados"] if x["puntaje"] is not None]
            inf["media"] = round(sum(v) / len(v), 3) if v else None
            for t in {x["tipo"] for x in inf["resultados"]}:
                w = [x["puntaje"] for x in inf["resultados"] if x["tipo"] == t and x["puntaje"] is not None]
                inf["por_tipo"][t] = round(sum(w) / len(w), 3) if w else None
            inf.setdefault("recorregido", []).append({"cuando": time.strftime("%Y-%m-%d %H:%M"), "cambios": cambios})
            json.dump(inf, open(f, "w"), ensure_ascii=False, indent=1)
        print(os.path.basename(f), "cambios:", cambios or "ninguno")
    sys.exit(0)

if ACCION == "preparar":
    with banco.conectar() as c:
        antes = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("vectores", "cambios")}
        for t in ("examen", "examen_resultados"):
            c.execute(f"DROP TABLE IF EXISTS {t}")
        c.execute("DELETE FROM vectores"); c.execute("DELETE FROM cambios")
        c.execute("INSERT OR REPLACE INTO meta VALUES ('version_vista', (SELECT valor FROM meta WHERE clave = 'version'))")
    print("banco preparado:", banco.ruta_db, "· borrados", antes, "· tablas del examen:", tablas_examen_en_banco())
    sys.exit(0)

if ACCION == "examen":
    preguntas = ex.generar(almacen)
    print(f"examen: {len(preguntas)} preguntas en {EXAMEN_DB}")
    sys.exit(0)

if ACCION == "plan":
    preguntas = ex.cargar(almacen)
    por_tipo = {}
    for p in preguntas: por_tipo.setdefault(p["tipo"], []).append(p["id"])
    if QUE == "prig":
        for p in json.load(open(INDEP)): por_tipo.setdefault("indep_" + p["tipo"], []).append(p["id"])
    random.seed(20260930)
    for v in por_tipo.values(): random.shuffle(v)
    orden = []                                   # intercalado por tipo: cada lote mezcla todos los tipos
    while any(por_tipo.values()):
        for t in sorted(por_tipo):
            if por_tipo[t]: orden.append(por_tipo[t].pop())
    lotes = [orden[i:i + TAM] for i in range(0, len(orden), TAM)]
    json.dump({"que": QUE, "version_banco": meta("version"), "huella_codigo": huella_codigo(), "huella_sistema": huella_sistema(),
               "examen": sorted(p["id"] for p in preguntas), "lotes": lotes, "creado": time.strftime("%Y-%m-%d %H:%M")},
              open(PLAN, "w"), indent=1)
    print(f"plan: {len(orden)} preguntas en {len(lotes)} lotes de hasta {TAM} → {PLAN}")
    sys.exit(0)

plan = json.load(open(PLAN))
def informe_de(n, rep=False):
    return os.path.join(DIR, f"{QUE}_lote{n:02d}{'_rep' if rep else ''}.json")

if ACCION == "estado":
    for n in range(1, len(plan["lotes"]) + 1):
        partes = []
        for rep in (False, True):
            if os.path.exists(informe_de(n, rep)):
                r = json.load(open(informe_de(n, rep)))
                partes.append(f"{'repetición: ' if rep else ''}{'OK ' if r['ok'] else 'FALLÓ'} · media {r['media']} · {r['segundos']} s"
                              + (" · " + ", ".join(r["problemas"][:3]) if r["problemas"] else ""))
        print(f"lote {n:2d}: " + (" | ".join(partes) if partes else "pendiente"))
    sys.exit(0)

# ------------------------------------------------------------------------------------------ correr un lote
n = int(sys.argv[3]); ids = plan["lotes"][n - 1]
problemas = []
# 1. chequeos previos (el banco se sincroniza ANTES de comparar: si no, un cambio en el disco pasaría el chequeo
#    y aparecería recién con la primera pregunta, que sincroniza)
sinc = banco.sincronizar()
if sinc["nuevos"] or sinc["modificados"] or sinc["borrados"]:
    problemas.append(f"la copia congelada cambió (nuevos {sinc['nuevos']}, modificados {sinc['modificados']}, borrados {sinc['borrados']})")
if huella_codigo() != plan.get("huella_codigo"):
    problemas.append("el código medido no coincide con el del plan")
if huella_sistema() != plan.get("huella_sistema"):
    problemas.append("el sistema bajo prueba (backend de Prig) cambió desde el plan: las respuestas no serían comparables")
if sorted(p["id"] for p in ex.cargar(almacen)) != plan["examen"]:
    problemas.append("el examen no coincide con el del plan")
if tablas_examen_en_banco():
    problemas.append(f"el banco medido tiene tablas del examen ({tablas_examen_en_banco()}): el modelo podría leerlas")
if conteo("resoluciones") or conteo("conocimiento"):
    problemas.append(f"hay memoria guardada (resoluciones {conteo('resoluciones')}, conocimiento {conteo('conocimiento')})")
if conteo("vectores"):
    problemas.append(f"el banco tiene {conteo('vectores')} vectores (la medición es sin vectores)")
if conteo("cambios") or meta("version_vista") != meta("version"):
    problemas.append("el banco tiene historial de cambios o la versión vista atrasada (aparecería en el contexto)")
lector = lu.LectorUnidades(banco, None)
vencidas = [o for o in lector._unidades if not lector.vigente(o)]
if vencidas:
    problemas.append(f"{len(vencidas)} unidades sin lectura vigente: correr antes la pasada")
if subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True).returncode == 0:
    problemas.append("ya hay un llama-server corriendo")
g0 = gpu()
if g0["temp_c"] > 70:
    problemas.append(f"GPU a {g0['temp_c']} °C: esperar a que enfríe")
if g0["vram_mb"] > VRAM_MAX_ANTES_MB:
    problemas.append(f"GPU ocupada ({g0['vram_mb']} MB): el motor tendría menos expertos calientes que en los otros lotes")
if problemas:
    print("NO SE CORRE el lote", n, "·", "; ".join(problemas)); sys.exit(1)

condiciones = {"raiz": RAIZ, "version_banco": meta("version"), "huella_codigo": huella_codigo(), "huella_sistema": huella_sistema(),
               "vectores": 0, "unidades_vigentes": len(lector._unidades), "gpu_antes": g0, "repeticion": REPETICION,
               "ollama_escuchando": subprocess.run(["bash", "-c", "ss -ltn | grep -q ':11434 '"]).returncode == 0,
               # los expertos corren en CPU: con la máquina en uso la generación baja (03/10: 33 → 12,7 tok/s con
               # kdenlive y obs abiertos). No cambia la exactitud, sí los tiempos: se registra para interpretarlos
               "carga_cpu_antes": [round(x, 2) for x in os.getloadavg()]}
estados_antes = set(glob.glob(os.path.join(motor_moe.CARPETA_PROYECTOS, "*.bin")))
os.chdir(os.path.join(SISTEMA, "backend"))
import app as A
A.bancos.embebedor_listo = lambda: False
A.file_mgr.base_dir = RAIZ; A.ai_engine.config["moe_contexto"] = "auto"
atexit.register(A.ai_engine.unload_models)
modos, herramientas, agotadas = {}, {}, set()
# Tope por pregunta. El chat con banco no limita los tokens de la respuesta: el 03/10 (lote 4) una respuesta entró en
# bucle (31.937 tokens en 17,7 min, borrador MTP aceptado al 99,7 %), no cupo en 64K, el motor creció a 128K y siguió;
# sin tope el lote no terminaba nunca. Al vencer se corta como el botón Detener (cerrar el flujo activa la cancelación
# de _flujo_cancelable y el motor deja de generar); lo leído hasta ahí se corrige igual y queda marcado «agotada»
# para auditarlo a mano. 600 s = 3 veces la respuesta más lenta medida antes (196 s): no habría cortado ninguna.
LIMITE_S = 600

def cortar_generacion():
    """ Al vencer el tope. Cerrar el flujo (como Detener) no alcanza cuando la respuesta en bucle no emite trozos
    intermedios: el hilo que la produce no ve la cancelación hasta terminar, y la generación sigue ocupando el único
    lugar del motor (03/10, lote 6: 11.459 tokens hasta llenar 32K, reinicio a 64K y vuelta a empezar; asyncio.run se
    quedó esperando ese hilo). Se cancela como /api/ai/cancel y, si el motor sigue ocupado, se lo detiene DESDE DENTRO
    (detener() deja su estado coherente; matar el proceso desde fuera hizo fallar en 1 s las 3 preguntas siguientes,
    porque el motor lo seguía creyendo vivo). Se espera a que quede libre antes de la próxima pregunta. """
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

memoria_del_modelo = []

def limpiar_memoria_escrita(texto):
    """ memoria=False no guarda la respuesta, pero el modelo puede escribir notas con la herramienta «anotar» (el prompt
    del modo general se lo pide: app.py «guárdalo con anotar») y esas notas entran en el contexto de las preguntas
    siguientes. Visto el 03/10 en el lote 10. Se registran y se borran después de cada pregunta: cada una empieza
    aislada, como pretende memoria=False (el modelo no se entera: su llamada a anotar funcionó). """
    with banco.conectar() as c:
        notas = [dict(f) for f in c.execute("SELECT id, tipo, titulo, texto, rutas, origen FROM conocimiento")]
        resol = [dict(f) for f in c.execute("SELECT id, pregunta, resumen FROM resoluciones")]
        if notas:
            c.execute("DELETE FROM conocimiento_fts WHERE rowid IN (SELECT id FROM conocimiento)"); c.execute("DELETE FROM conocimiento")
        if resol:
            c.execute("DELETE FROM resoluciones_fts WHERE rowid IN (SELECT id FROM resoluciones)"); c.execute("DELETE FROM resoluciones")
    if notas or resol:
        memoria_del_modelo.append({"pregunta": texto, "notas": notas, "resoluciones": resol})
        print(f"{time.strftime('%H:%M:%S')} MEMORIA escrita por el modelo y borrada: {len(notas)} notas, {len(resol)} resoluciones", flush=True)

def preguntar(texto):
    try:
        return _preguntar(texto)
    finally:
        limpiar_memoria_escrita(texto)

def _preguntar(texto):
    req = A.AIChatRequest(prompt=texto, model="qwen3.6-35b-moe:prig", eventos=True, banco=True, think=False, memoria=False)
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
            corte[0] = cortar_generacion()             # antes de salir: asyncio.run espera al hilo productor
            return True
        finally:
            with contextlib.suppress(Exception):
                await it.aclose()
    corte = [None]
    agotada = asyncio.run(leer())
    salida, tokens, modo, usadas = "", 0, "general", []
    for linea in "".join((c.decode() if isinstance(c, bytes) else c) for c in trozos).splitlines():
        if not linea.strip(): continue
        try:
            ev = json.loads(linea)
        except ValueError:
            if agotada: continue                     # la última línea pudo quedar cortada
            raise
        if ev["t"] == "texto": salida += ev["v"]
        elif ev["t"] == "banco": modo = ev["v"].get("modo") or "general"
        elif ev["t"] == "stats": tokens += ev["v"].get("tokens_respuesta", 0)
        elif ev["t"] == "herramienta":
            usadas.append({"nombre": ev.get("nombre"), "argumentos": json.dumps(ev.get("argumentos"), ensure_ascii=False)[:400]})
        elif ev["t"] == "resultado" and usadas:
            usadas[-1]["resultado_caracteres"] = len(str(ev.get("v") or ""))
    modos[texto] = modo; herramientas[texto] = usadas
    if agotada:
        agotadas.add(texto)
        salida += f"\n[agotada: cortada a los {LIMITE_S} s sin terminar]"
        print(f"{time.strftime('%H:%M:%S')} AGOTADA a los {LIMITE_S} s ({len(salida)} caracteres; {corte[0]})", flush=True)
    return salida, {"tokens": tokens}

t0 = time.time()
ids_examen = [i for i in ids if not i.startswith("ind_")]
ids_indep = [i for i in ids if i.startswith("ind_")]
resultados = []
if ids_examen:
    r = ex.correr(almacen, f"e7_{QUE}_lote{n:02d}{'_rep' if REPETICION else ''}", preguntar, ids=ids_examen,
                  progreso=lambda p: print(f"{time.strftime('%H:%M:%S')} {p['n']}/{p['total']} {p['tipo']} {p['puntaje']}", flush=True))
    with almacen.conectar() as c:
        resultados = [dict(f) for f in c.execute("SELECT * FROM examen_resultados WHERE corrida = ?", (r["corrida"],))]
indep = {p["id"]: p for p in json.load(open(INDEP))} if ids_indep else {}
for i in ids_indep:
    p = indep[i]; t = time.time(); texto, _ = preguntar(p["pregunta"])
    punt = corregir_indep(p, texto)
    resultados.append({"id": i, "tipo": p["tipo"], "pregunta": p["pregunta"], "puntaje": punt, "respuesta": texto,
                       "segundos": round(time.time() - t, 1), "esperado": json.dumps(p["esperado"], ensure_ascii=False)})
    print(f"{time.strftime('%H:%M:%S')} independiente {i} {p['tipo']} {punt}", flush=True)
try:
    estado_motor = A.ai_engine.motor_moe().estado()
    condiciones["motor"] = {k: estado_motor.get(k) for k in ("contexto", "calientes_por_capa", "mtp", "modo")}
except Exception as e:
    condiciones["motor"] = {"error": str(e)}

# 3. verificación
if len(resultados) != len(ids):
    problemas.append(f"{len(resultados)} resultados para {len(ids)} preguntas")
for x in resultados:
    resp = (x.get("respuesta") or "").strip()
    if not resp: problemas.append(f"{x['id']}: respuesta vacía")
    elif resp.startswith(("[Error", "Error al", "Error:")): problemas.append(f"{x['id']}: respuesta con error: {resp[:80]}")
    if not x.get("pregunta"): problemas.append(f"{x['id']}: sin texto de pregunta")
if conteo("resoluciones") or conteo("conocimiento"):
    problemas.append("se guardó memoria durante el lote (memoria=False no se respetó)")
if conteo("vectores"):
    problemas.append(f"se escribieron {conteo('vectores')} vectores durante el lote")
if meta("version") != condiciones["version_banco"] or conteo("cambios"):
    problemas.append(f"el banco cambió durante el lote (versión {condiciones['version_banco']} → {meta('version')})")
if len(modos) != len(ids):
    problemas.append(f"modo registrado para {len(modos)} de {len(ids)}")
preguntas_examen = {p["id"]: p for p in ex.cargar(almacen)}
for x in resultados:
    if x["id"] in preguntas_examen:
        rec = ex.corregir(preguntas_examen[x["id"]], x["respuesta"])["puntaje"]
        if abs(rec - x["puntaje"]) > 1e-9: problemas.append(f"{x['id']}: puntaje guardado {x['puntaje']} ≠ recalculado {rec}")
nuevos = set(glob.glob(os.path.join(motor_moe.CARPETA_PROYECTOS, "*.bin"))) - estados_antes
if nuevos: problemas.append(f"{len(nuevos)} estados nuevos en disco durante el lote")
# rastro de la clave de corrección en las herramientas o en el texto (no debería poder pasar: es la alarma)
fuga = re.compile(r"examen_resultados|\bexamen\b.*\besperado\b|estudio-banco|examen_independiente", re.I)
for x in resultados:
    usadas = json.dumps(herramientas.get(x.get("pregunta"), []), ensure_ascii=False)
    if fuga.search(usadas) or fuga.search(x.get("respuesta") or ""):
        problemas.append(f"{x['id']}: rastro de la clave de corrección en la respuesta o en las consultas")
# comparación con la corrida final anterior (misma pregunta por texto, en el respaldo)
previas = []
if QUE == "prig" and os.path.exists(RESPALDO):
    v = sqlite3.connect(f"file:{RESPALDO}?mode=ro", uri=True)
    texto_id = {p: i for i, p in v.execute("SELECT id, pregunta FROM examen")}
    for x in resultados:
        i = texto_id.get(x.get("pregunta"))
        if i:
            ant = v.execute("SELECT puntaje FROM examen_resultados WHERE id = ? AND corrida = 'final-20260930-064546'", (i,)).fetchone()
            if ant and x["puntaje"] is not None and abs(ant[0] - x["puntaje"]) > 0.01:
                previas.append({"id": x["id"], "antes": ant[0], "ahora": x["puntaje"]})
condiciones["gpu_despues"] = gpu(); condiciones["carga_cpu_despues"] = [round(x, 2) for x in os.getloadavg()]
puntajes = [x["puntaje"] for x in resultados if x["puntaje"] is not None]
por_tipo = {}
for t in {x["tipo"] for x in resultados}:
    v = [x["puntaje"] for x in resultados if x["tipo"] == t and x["puntaje"] is not None]
    por_tipo[t] = round(sum(v) / len(v), 3) if v else None          # None: se corrige a mano (rúbrica)
informe = {"lote": n, "repeticion": REPETICION, "ok": not problemas, "problemas": problemas, "preguntas": len(ids),
           "condiciones": condiciones, "media": round(sum(puntajes) / len(puntajes), 3) if puntajes else None,
           "segundos": round(time.time() - t0), "modos": {m: list(modos.values()).count(m) for m in set(modos.values())},
           "por_tipo": por_tipo, "distintos_a_la_corrida_final": previas, "limite_s": LIMITE_S,
           "agotadas": [x["id"] for x in resultados if x.get("pregunta") in agotadas],
           "memoria_del_modelo": [{"id": next((x["id"] for x in resultados if x.get("pregunta") == m["pregunta"]), "?"),
                                   "notas": m["notas"], "resoluciones": m["resoluciones"]} for m in memoria_del_modelo],
           "resultados": [{k: x.get(k) for k in ("id", "tipo", "puntaje", "segundos")}
                          | {"modo": modos.get(x.get("pregunta"), "?"), "herramientas": len(herramientas.get(x.get("pregunta"), []))}
                          for x in resultados],
           "consultas": {x["id"]: herramientas.get(x.get("pregunta"), []) for x in resultados},
           "respuestas": {x["id"]: x.get("respuesta") for x in resultados}}
json.dump(informe, open(informe_de(n, REPETICION), "w"), ensure_ascii=False, indent=1)
print("VERIFICACIÓN", "OK" if informe["ok"] else "FALLÓ", json.dumps({k: informe[k] for k in ("lote", "repeticion", "media", "segundos", "modos", "por_tipo", "problemas", "agotadas", "distintos_a_la_corrida_final")}, ensure_ascii=False),
      "· memoria escrita por el modelo (borrada):", [m["id"] for m in informe["memoria_del_modelo"]])
sys.exit(0 if informe["ok"] else 1)
