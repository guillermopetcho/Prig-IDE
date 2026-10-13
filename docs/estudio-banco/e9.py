"""E9: memoria viva y cambios.

  .venv/bin/python docs/estudio-banco/e9.py preparar          → copia de Prig para E9 (mismo prefijo: reusa las lecturas)
  .venv/bin/python docs/estudio-banco/e9.py seleccionar       → preguntas del examen con memoria guardada (para E9a)
  .venv/bin/python docs/estudio-banco/e9.py memoria real|sembrada|vaciar   → carga la memoria de ese brazo en el banco E9
  .venv/bin/python docs/estudio-banco/e9.py corregir_a        → E9a: puntajes con memoria frente a sin memoria (E7)
  .venv/bin/python docs/estudio-banco/e9.py notas             → E9b: qué notas se marcan al editar (sin modelo)
  .venv/bin/python docs/estudio-banco/e9.py editar            → E9c: un cambio de comportamiento en la copia E9

E9a · ¿La memoria de respuestas reinyecta errores? Las mismas preguntas del examen, con memoria=True, en dos brazos:
      «real» = las 313 resoluciones y 6 notas que tenía el banco de Prig el 30/09 (respaldo); «sembrada» = una
      resolución EQUIVOCADA plantada para cada pregunta (respuesta plausible de otra pregunta del mismo tipo). La base
      es la respuesta sin memoria de la serie limpia de E7. Mide si copia aciertos, si copia errores y cuánto.
E9b · Vigencia: las notas se marcan «puede estar desactualizado» por ARCHIVO; se mide cuántas marcas sobran (otra
      función del mismo archivo cambió) y cuántas faltan (cambió una función de la que la nota depende, en otro archivo).
E9c · ¿Ve el modelo un cambio recién hecho, sin pasada? Se edita un valor en la copia y se pregunta enseguida."""
import hashlib, json, os, random, re, shutil, sqlite3, sys, tempfile, time, zlib
ACCION = sys.argv[1]
SISTEMA = "/home/ama-gi/Prig"
LIMPIA = os.path.expanduser("~/.cache/prig-estudio/repos/Prig")
COPIA = os.path.expanduser("~/.cache/prig-estudio/repos-e9/Prig")
BANCOS = os.path.expanduser("~/.cache/prig-estudio/bancos")
RESPALDO = os.path.expanduser("~/.cache/prig-estudio/banco-Prig-respaldo-2026-09-30/banco.db")
E7 = os.path.expanduser("~/.cache/prig-estudio/e7")
DIR = os.path.expanduser("~/.cache/prig-estudio/e9"); os.makedirs(DIR, exist_ok=True)
os.environ["PRIG_BANCOS"] = BANCOS
sys.path.insert(0, os.path.join(SISTEMA, "backend"))
import banco_proyecto as bp
bp.BancoProyecto._embebedor_ok = lambda self: False
bp.BancoProyecto.indexar_vectores = lambda self, *a, **k: {"omitido": "medición sin vectores"}


def banco_de(raiz):
    clave = hashlib.sha1(os.path.abspath(raiz).encode()).hexdigest()[:10]
    return os.path.join(BANCOS, f"{os.path.basename(raiz)}-{clave}")


def examen():
    c = sqlite3.connect(f"file:{E7}/examen_prig.db?mode=ro", uri=True); c.row_factory = sqlite3.Row
    filas = {f["id"]: dict(f) for f in c.execute("SELECT * FROM examen")}
    for f in filas.values():
        f["esperado"] = json.loads(f["esperado"])
    return filas


def respuestas_e7():
    """ id → {respuesta, puntaje, modo} de la serie limpia (sin repeticiones) """
    salida = {}
    for n in range(1, 16):
        ruta = f"{E7}/prig_lote{n:02d}.json"
        if not os.path.exists(ruta): continue
        inf = json.load(open(ruta))
        for x in inf["resultados"]:
            salida[x["id"]] = {"respuesta": inf["respuestas"][x["id"]], "puntaje": x["puntaje"], "modo": x["modo"], "lote": n}
    return salida


# ------------------------------------------------------------------------------------------------ preparar
if ACCION == "preparar":
    import lectura_unidades as lu
    if not hasattr(lu.LectorUnidades, "_estados_de_otros_bancos"):
        sys.exit("El sistema no tiene el arreglo de reasignar (estados compartidos entre bancos): no se prepara")
    if os.path.exists(COPIA) or os.path.exists(banco_de(COPIA)):
        if "--rehacer" not in sys.argv: sys.exit("ya existe: --rehacer")
        shutil.rmtree(COPIA, ignore_errors=True); shutil.rmtree(banco_de(COPIA), ignore_errors=True)
    shutil.copytree(LIMPIA, COPIA, symlinks=True)
    os.makedirs(banco_de(COPIA))
    o = sqlite3.connect(f"file:{banco_de(LIMPIA)}/banco.db?mode=ro", uri=True)
    d = sqlite3.connect(os.path.join(banco_de(COPIA), "banco.db")); o.backup(d)
    d.execute("INSERT OR REPLACE INTO meta VALUES ('raiz', ?)", (COPIA,)); d.commit(); d.close(); o.close()
    banco = bp.BancoProyecto(COPIA)
    sinc = banco.sincronizar()
    lector = lu.LectorUnidades(banco, None); lector.reasignar()
    vencidas = [x for x in lector._unidades if not lector.vigente(x)]
    print(json.dumps({"copia": COPIA, "banco": banco.ruta_db, "sincronizacion": {k: sinc[k] for k in ("nuevos", "modificados", "borrados")},
                      "unidades": len(lector._unidades), "vencidas": vencidas}, ensure_ascii=False))

# ------------------------------------------------------------------------------------------------ E9a
if ACCION == "seleccionar":
    ex, e7 = examen(), respuestas_e7()
    r = sqlite3.connect(f"file:{RESPALDO}?mode=ro", uri=True)
    guardadas = {p for (p,) in r.execute("SELECT pregunta FROM resoluciones")}
    cands = [i for i, p in ex.items() if p["pregunta"] in guardadas and i in e7]
    generales = [i for i in cands if e7[i]["modo"] == "general"]
    unidad = [i for i in cands if e7[i]["modo"] != "general"]
    random.Random(9).shuffle(generales); random.Random(9).shuffle(unidad)
    elegidas = (generales + unidad)[:12]
    sel = [{"id": i, "pregunta": ex[i]["pregunta"], "tipo": ex[i]["tipo"], "modo_e7": e7[i]["modo"], "puntaje_e7": e7[i]["puntaje"]}
           for i in elegidas]
    json.dump(sel, open(os.path.join(DIR, "preguntas_e9a.json"), "w"), ensure_ascii=False, indent=1)
    print(f"candidatas {len(cands)} (generales {len(generales)}, unidad {len(unidad)}); elegidas {len(sel)}:",
          [(s["id"], s["tipo"], s["modo_e7"], s["puntaje_e7"]) for s in sel])


def respuesta_equivocada(p, ex):
    """ Una respuesta plausible pero equivocada: lo esperado de OTRA pregunta del mismo tipo (o, si no hay, un valor
    cambiado), redactada como las respuestas del modelo """
    otros = [q for q in ex.values() if q["tipo"] == p["tipo"] and q["id"] != p["id"]
             and not set(map(str, q["esperado"])) & set(map(str, p["esperado"]))]
    random.Random(p["id"]).shuffle(otros)
    if otros:
        falso = [str(x) for x in otros[0]["esperado"]]
    else:
        falso = [str(x) + "1" for x in p["esperado"]]
    if p["tipo"] == "constante":
        try:
            v = float(p["esperado"][0]); falso = [str(v * 2 if v else 7)]
        except (ValueError, TypeError):
            pass
    lista = "\n".join(f"- `{x}`" for x in falso)
    return falso, f"Según el código del proyecto, la respuesta es:\n\n{lista}\n\nLo verifiqué en el grafo de llamadas y en el código fuente."


if ACCION == "memoria":
    brazo = sys.argv[2]
    banco = bp.BancoProyecto(COPIA)
    assert banco.ruta_db.startswith(BANCOS)
    with banco.conectar() as c:
        for t in ("resoluciones", "resoluciones_fts", "conocimiento", "conocimiento_fts"):
            c.execute(f"DELETE FROM {t}")
    plantadas = {}
    if brazo == "real":
        r = sqlite3.connect(f"file:{RESPALDO}?mode=ro", uri=True); r.row_factory = sqlite3.Row
        for f in r.execute("SELECT * FROM resoluciones ORDER BY id"):
            banco.registrar_resolucion(f["pregunta"], zlib.decompress(f["respuesta"]).decode("utf-8", "replace"),
                                       f["modelo"] or "", json.loads(f["rutas"] or "[]"))
        for f in r.execute("SELECT * FROM conocimiento ORDER BY id"):
            banco.anotar(f["tipo"], f["titulo"], f["texto"], json.loads(f["rutas"] or "[]"))
    elif brazo == "sembrada":
        ex = examen()
        for s in json.load(open(os.path.join(DIR, "preguntas_e9a.json"))):
            falso, texto = respuesta_equivocada(ex[s["id"]], ex)
            banco.registrar_resolucion(s["pregunta"], texto, "qwen3.6-35b-moe:prig")
            plantadas[s["id"]] = falso
        json.dump(plantadas, open(os.path.join(DIR, "plantadas.json"), "w"), ensure_ascii=False, indent=1)
    with banco.conectar() as c:
        version = c.execute("SELECT valor FROM meta WHERE clave = 'version'").fetchone()[0]
        c.execute("INSERT OR REPLACE INTO meta VALUES ('version_vista', ?)", (version,))
        n = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("resoluciones", "conocimiento", "cambios", "vectores")}
    print(brazo, n, f"plantadas {len(plantadas)}" if plantadas else "")

if ACCION == "corregir_a":
    import examen_proyecto as ex_mod
    ex, e7 = examen(), respuestas_e7()
    plantadas = json.load(open(os.path.join(DIR, "plantadas.json"))) if os.path.exists(os.path.join(DIR, "plantadas.json")) else {}
    filas = []
    for brazo in ("real", "sembrada"):
        ruta = os.path.join(DIR, f"respuestas_e9a_{brazo}.json")
        if not os.path.exists(ruta): continue
        for r in json.load(open(ruta))["resultados"]:
            p = ex[r["id"]]
            punt = ex_mod.corregir(p, r["respuesta"])["puntaje"]
            copia = [x for x in plantadas.get(r["id"], []) if ex_mod._aparece(x, r["respuesta"])] if brazo == "sembrada" else []
            menciona_memoria = bool(re.search(r"resoluci|respuesta anterior|ya (respond|resolv)|memoria", r["respuesta"], re.I))
            filas.append({"brazo": brazo, "id": r["id"], "tipo": p["tipo"], "modo": r["modo"], "modo_e7": e7[r["id"]]["modo"],
                          "sin_memoria_e7": e7[r["id"]]["puntaje"], "con_memoria": punt, "copia_plantado": copia,
                          "menciona_memoria": menciona_memoria, "segundos": r["segundos"], "consultas": len(r["consultas"])})
    json.dump(filas, open(os.path.join(DIR, "correccion_e9a.json"), "w"), ensure_ascii=False, indent=1)
    for b in ("real", "sembrada"):
        xs = [f for f in filas if f["brazo"] == b]
        if not xs: continue
        m0 = sum(f["sin_memoria_e7"] for f in xs) / len(xs); m1 = sum(f["con_memoria"] for f in xs) / len(xs)
        print(f"{b}: {len(xs)} preguntas · sin memoria (E7) {m0:.3f} → con memoria {m1:.3f} · copian lo plantado "
              f"{sum(bool(f['copia_plantado']) for f in xs)} · modos {[f['modo'] for f in xs]}")
    for f in filas:
        print(f)

# ------------------------------------------------------------------------------------------------ E9b
if ACCION == "notas":
    import lectura_unidades as lu
    tmp = tempfile.mkdtemp(prefix="e9b_")
    raiz = os.path.join(tmp, "Prig")
    shutil.copytree(LIMPIA, raiz, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    banco = bp.BancoProyecto(raiz, carpeta=os.path.join(tmp, "banco"))
    o = sqlite3.connect(f"file:{banco_de(LIMPIA)}/banco.db?mode=ro", uri=True)
    d = sqlite3.connect(banco.ruta_db); o.backup(d); d.execute("INSERT OR REPLACE INTO meta VALUES ('raiz', ?)", (raiz,))
    d.commit(); d.close(); o.close()
    banco.sincronizar()
    # Notas sobre funciones concretas. Se cambia SOLO Tramo.pico_real (termico.py)
    notas = {
        "N1": ("teoria", "pico_real devuelve None sin lecturas", "Tramo.pico_real devuelve None si no hubo lecturas.",
               ["backend/recursos/termico.py"], "la función cambiada: debe marcarse"),
        "N2": ("nota", "MESETA_S es 20 s", "La meseta de enfriamiento (MESETA_S) dura 20 s.",
               ["backend/recursos/termico.py"], "otra cosa del mismo archivo, que no cambió: marcarla sobra"),
        "N3": ("decision", "el informe de temperatura usa pico_real", "Gobernador.estado y los informes usan el pico real del tramo.",
               ["backend/app.py"], "depende de la función cambiada, desde otro archivo: debería marcarse"),
        "N4": ("nota", "ruta_http_canonica normaliza ${id}", "ruta_http_canonica cambia ${id} por *.",
               ["backend/banco_proyecto.py"], "nada que ver: no debe marcarse"),
    }
    ids = {}
    for k, (tipo, titulo, texto, rutas, _) in notas.items():
        ids[k] = banco.anotar(tipo, titulo, texto, rutas)["id"]
    ruta = os.path.join(raiz, "backend/recursos/termico.py")
    t = open(ruta, encoding="utf-8").read()
    assert t.count("return max(picos) if picos else None") == 1
    open(ruta, "w", encoding="utf-8").write(t.replace("return max(picos) if picos else None", "return max(picos) if picos else 0.0"))
    sinc = banco.sincronizar()
    with banco.conectar() as c:
        marcas = {k: bool(c.execute("SELECT revisar FROM conocimiento WHERE id = ?", (i,)).fetchone()[0]) for k, i in ids.items()}
        fichas_viejas = c.execute("SELECT COUNT(*) FROM fichas f JOIN simbolos s ON s.ruta = f.ruta AND s.nombre = f.nombre "
                                  "WHERE f.sha != s.sha").fetchone()[0]
        fichas_termico = c.execute("SELECT COUNT(*) FROM fichas WHERE ruta = 'backend/recursos/termico.py'").fetchone()[0]
    compuesto = banco.componer("¿Qué devuelve Tramo.pico_real si no hubo lecturas?", usar_resoluciones=True)
    texto_compuesto = compuesto.get("texto") or json.dumps(compuesto, ensure_ascii=False)
    salida = {"cambio": "termico.py: Tramo.pico_real devuelve 0.0 en vez de None sin lecturas",
              "sincronizacion": {k: sinc[k] for k in ("modificados",)},
              "notas": {k: {"marcada": marcas[k], "deberia": v[4]} for k, v in notas.items()},
              "fichas_con_sha_viejo": fichas_viejas, "fichas_del_archivo": fichas_termico,
              "aviso_en_el_contexto": "puede estar desactualizado" in texto_compuesto}
    json.dump(salida, open(os.path.join(DIR, "e9b_notas.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(salida, ensure_ascii=False, indent=1))
    shutil.rmtree(tmp, ignore_errors=True)

# ------------------------------------------------------------------------------------------------ E9c
CAMBIO_C = {"ruta": "backend/recursos/termico.py", "antes": "MESETA_S = 20.0", "ahora": "MESETA_S = 45.0"}
if ACCION == "editar":
    ruta = os.path.join(COPIA, CAMBIO_C["ruta"])
    t = open(ruta, encoding="utf-8").read()
    assert t.count(CAMBIO_C["antes"]) == 1
    open(ruta, "w", encoding="utf-8").write(t.replace(CAMBIO_C["antes"], CAMBIO_C["ahora"]))
    preguntas = [
        {"id": "E9c_1", "pregunta": "¿Cuánto vale la constante `MESETA_S` en `backend/recursos/termico.py`?"},
        {"id": "E9c_2", "pregunta": "¿Cuántos segundos espera el gobernador térmico sin que la temperatura baje 1 °C antes de dar "
                                    "por terminado el enfriamiento?"},
        {"id": "E9c_3", "pregunta": "¿Qué cambió en el proyecto desde tu última respuesta?"},
    ]
    json.dump(preguntas, open(os.path.join(DIR, "preguntas_e9c.json"), "w"), ensure_ascii=False, indent=1)
    print("editado", CAMBIO_C, "→ preguntas en", os.path.join(DIR, "preguntas_e9c.json"))
