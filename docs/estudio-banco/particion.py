"""E3: calidad y estabilidad de la partición, en memoria (sin escribir en el banco).
Uso: .venv/bin/python docs/estudio-banco/particion.py"""
import sys, os, json, random, zlib, sqlite3, subprocess, collections, copy, re, statistics
sys.path.insert(0, "/home/ama-gi/Prig/backend")
import particion_proyecto as pp
DB = "/home/ama-gi/.prig_bancos/Prig-ac5380d79d/banco.db"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
archivos = [dict(f) for f in c.execute("SELECT ruta, lenguaje, tokens, contenido FROM archivos ORDER BY ruta")]
simb = collections.defaultdict(list)
for f in c.execute("SELECT ruta, nombre, padre, ini, fin FROM simbolos"): simb[f["ruta"]].append(dict(f))
piezas = []
for a in archivos:
    if pp.es_produccion(a["ruta"], a["lenguaje"]):
        lineas = zlib.decompress(a["contenido"]).decode("utf-8", "replace").splitlines()
        piezas += pp.piezas_de_archivo(a["ruta"], lineas, simb[a["ruta"]], a["tokens"], pp.PRESUPUESTO_UNIDAD)
pesos = pp.pesos_entre_piezas(c, piezas); dirigidas = pp.dirigidas_entre_piezas(c, piezas)
churn = pp.cambios_git("/home/ama-gi/Prig")

def partir(piezas, pesos, dirigidas, tope=pp.PRESUPUESTO_UNIDAD):
    grupos = pp.agrupar(piezas, pesos, tope)
    orden, internas = pp.ordenar(grupos, piezas, dirigidas, churn)
    # «texto» de cada unidad = piezas en su orden interno con sus rangos y tokens: si cambia, cambia la llave
    return [tuple((piezas[p]["ruta"], piezas[p]["ini"], piezas[p]["fin"], piezas[p]["tokens"]) for p in internas[u]) for u in orden], grupos

base, grupos_base = partir(piezas, pesos, dirigidas)
res = {"unidades": len(base), "piezas": len(piezas)}
# 0. determinismo
res["determinista"] = partir(piezas, pesos, dirigidas)[0] == base

# 1. cohesión real: todas las llamadas del banco (código de producción), dentro o entre unidades
indice = collections.defaultdict(list)
for i, p in enumerate(piezas): indice[p["ruta"]].append((p["ini"], p["fin"], i))
de_pieza = {p: u for u, g in enumerate(grupos_base) for p in g}
ini_sim = {(f["ruta"], f["nombre"]): f["ini"] for f in c.execute("SELECT ruta, nombre, ini FROM simbolos")}
dentro = entre = misma_pieza = 0
for f in c.execute("SELECT ruta, a_ruta, a_nombre, linea FROM llamadas"):
    a = pp._pieza_de(indice, f["ruta"], f["linea"]); ld = ini_sim.get((f["a_ruta"], f["a_nombre"]))
    b = pp._pieza_de(indice, f["a_ruta"], ld) if ld else None
    if a is None or b is None: continue
    if a == b: misma_pieza += 1
    elif de_pieza[a] == de_pieza[b]: dentro += 1
    else: entre += 1
tot = misma_pieza + dentro + entre
res["llamadas"] = {"misma_pieza": misma_pieza, "misma_unidad_otra_pieza": dentro, "entre_unidades": entre,
                   "dentro_de_la_unidad": round((misma_pieza + dentro) / tot, 3)}

# 2. estabilidad: cuántas unidades cambian su texto (= estados invalidados) ante perturbaciones
def cambiadas(nueva):
    b = collections.Counter(base); n = collections.Counter(nueva)
    return sum((b - n).values())   # unidades de la base que ya no existen tal cual
def tokens_de(unidades_perdidas_idx): pass
random.seed(5)
def ensayo(nombre, n, mutar):
    cuentas = []
    for _ in range(n):
        pz, pw, dg, tocadas = mutar(copy.deepcopy(piezas), dict(pesos), dict(dirigidas))
        nueva, _ = partir(pz, pw, dg)
        total = cambiadas(nueva)
        # las unidades que contienen piezas tocadas se invalidan de todas formas: se cuentan aparte
        propias = {u for u, g in enumerate(base) for (r, i, f, t) in g if (r, i) in tocadas}
        cuentas.append((total, max(0, total - len(propias))))
    tot = [x[0] for x in cuentas]; extra = [x[1] for x in cuentas]
    res[nombre] = {"ensayos": n, "invalidadas_media": round(statistics.mean(tot), 2), "invalidadas_max": max(tot),
                   "de_rebote_media": round(statistics.mean(extra), 2), "de_rebote_max": max(extra),
                   "sin_rebote": sum(1 for x in extra if x == 0)}
def crecer(pz, pw, dg, delta=300):
    i = random.randrange(len(pz)); pz[i]["tokens"] += delta; return pz, pw, dg, {(pz[i]["ruta"], pz[i]["ini"])}
def llamada_nueva(pz, pw, dg):
    a, b = random.sample(range(len(pz)), 2)
    k = (min(a, b), max(a, b)); pw[k] = pw.get(k, 0) + 1.0; dg[(a, b)] = dg.get((a, b), 0) + 1.0
    return pz, pw, dg, {(pz[a]["ruta"], pz[a]["ini"])}
def archivo_nuevo(pz, pw, dg):
    j = len(pz); pz.append({"ruta": f"backend/nuevo_{random.randrange(9999)}.py", "ini": 1, "fin": 100, "tokens": 1500, "simbolos": []})
    for b in random.sample(range(j), 3):
        pw[(b, j)] = pw.get((b, j), 0) + 1.0; dg[(j, b)] = 1.0
    return pz, pw, dg, set()
ensayo("crece_una_funcion_300_tok", 40, crecer)
ensayo("una_llamada_nueva", 40, llamada_nueva)
ensayo("archivo_nuevo_1500_tok", 25, archivo_nuevo)

# 3. cambios reales: últimos 30 commits (tokens ≈ líneas cambiadas × 10, repartidos en las piezas del archivo)
log = subprocess.run(["git", "-C", "/home/ama-gi/Prig", "log", "-30", "--numstat", "--format=@%h"], capture_output=True, text=True).stdout
commits = []; actual = None
for l in log.splitlines():
    if l.startswith("@"): actual = {"id": l[1:], "archivos": {}}; commits.append(actual)
    elif l.strip() and actual is not None:
        partes = l.split("\t")
        if len(partes) == 3 and partes[0].isdigit(): actual["archivos"][partes[2]] = int(partes[0]) - int(partes[1])
reales = []
for cm in commits:
    pz = copy.deepcopy(piezas); tocadas = set()
    for ruta, delta in cm["archivos"].items():
        mias = [p for p in pz if p["ruta"] == ruta]
        for p in mias:
            p["tokens"] = max(10, p["tokens"] + int(delta * 10 / len(mias))); tocadas.add((p["ruta"], p["ini"]))
    if not tocadas: continue
    nueva, _ = partir(pz, pesos, dirigidas)
    total = cambiadas(nueva); propias = {u for u, g in enumerate(base) for (r, i, f, t) in g if (r, i) in tocadas}
    reales.append({"commit": cm["id"], "archivos_codigo": len({r for r, _ in tocadas}), "invalidadas": total, "propias": len(propias), "de_rebote": max(0, total - len(propias))})
res["commits_reales"] = reales

# 4. otros topes
for tope in (8000, 24000, 32000):
    pz = [p for a in archivos if pp.es_produccion(a["ruta"], a["lenguaje"]) for p in pp.piezas_de_archivo(
        a["ruta"], zlib.decompress(a["contenido"]).decode("utf-8", "replace").splitlines(), simb[a["ruta"]], a["tokens"], tope)]
    pw = pp.pesos_entre_piezas(c, pz); dg = pp.dirigidas_entre_piezas(c, pz)
    un, gr = partir(pz, pw, dg, tope)
    idx = collections.defaultdict(list)
    for i, p in enumerate(pz): idx[p["ruta"]].append((p["ini"], p["fin"], i))
    dp = {p: u for u, g in enumerate(gr) for p in g}; d = e = 0
    for f in c.execute("SELECT ruta, a_ruta, a_nombre, linea FROM llamadas"):
        a = pp._pieza_de(idx, f["ruta"], f["linea"]); ld = ini_sim.get((f["a_ruta"], f["a_nombre"]))
        b = pp._pieza_de(idx, f["a_ruta"], ld) if ld else None
        if a is None or b is None: continue
        if dp[a] == dp[b]: d += 1
        else: e += 1
    toks = [sum(x[3] for x in u) for u in un]
    res[f"tope_{tope}"] = {"unidades": len(un), "tokens_media": round(statistics.mean(toks)), "llamadas_dentro": round(d / (d + e), 3),
                           "disco_GB_estimado": round(sum(t + 6000 for t in toks) * 14.3e3 / 1e9, 1)}
res["tope_16000"] = {"unidades": len(base), "llamadas_dentro": res["llamadas"]["dentro_de_la_unidad"],
                     "disco_GB_estimado": round(sum(sum(x[3] for x in u) + 6000 for u in base) * 14.3e3 / 1e9, 1)}
print(json.dumps(res, ensure_ascii=False, indent=1))
