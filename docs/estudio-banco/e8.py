"""E8: razonamiento profundo con verdad conocida, sobre una copia de Prig con errores inyectados.

  .venv/bin/python docs/estudio-banco/e8.py preparar     → copia mutada + su banco (sin historial de cambios)
  .venv/bin/python docs/estudio-banco/e8.py verdad       → corre los tests: base y cada error por separado
  .venv/bin/python docs/estudio-banco/e8.py preguntas    → escribe las preguntas (E8a, E8b, E8c)
  .venv/bin/python docs/estudio-banco/e8.py corregir     → ayudas automáticas para la auditoría a mano
  (la pasada de la copia y las preguntas se corren con lectura_unidades.py --pasada y sonda.py)

Tres pruebas:
  E8a · ¿encuentra el error? La MISMA pregunta («¿tiene algún error?») sobre 8 funciones con un error inyectado y 4 sin
        tocar (controles: miden los falsos positivos). Dos de cada clase: off-by-one, caso borde, clave de configuración
        mal escrita, recurso sin liberar.
  E8b · ¿predice el impacto? Se le da el cambio (antes → ahora) y se le pregunta qué tests fallan. La verdad sale de
        correr los tests: la copia limpia, y cada error solo, en copias aparte.
  E8c · ¿explica un flujo con citas comprobables? Cada «archivo:línea» citado se verifica contra el código.

La copia se llama «Prig» (otra carpeta padre) para que el prefijo de las unidades sea el mismo: las unidades sin errores
reutilizan las lecturas del motor y solo se releen las que cambiaron (eso también mide E9: una sesión de edición).
El historial de cambios del banco se borra: si no, «Cambios desde tu última respuesta» y P.diff mostrarían los errores."""
import glob, hashlib, json, os, random, re, shutil, sqlite3, subprocess, sys, tempfile, time
ACCION = sys.argv[1]
SISTEMA = "/home/ama-gi/Prig"
LIMPIA = os.path.expanduser("~/.cache/prig-estudio/repos/Prig")
COPIA = os.path.expanduser("~/.cache/prig-estudio/repos-e8/Prig")
BANCOS = os.path.expanduser("~/.cache/prig-estudio/bancos")
DIR = os.path.expanduser("~/.cache/prig-estudio/e8"); os.makedirs(DIR, exist_ok=True)
os.environ["PRIG_BANCOS"] = BANCOS
sys.path.insert(0, os.path.join(SISTEMA, "backend"))

MUTACIONES = [
    {"id": "B1", "clase": "off-by-one", "ruta": "backend/progreso.py", "funcion": "racha",
     "antes": "seguidos = seguidos + 1 if anterior and (f - anterior).days == 1 else 1",
     "ahora": "seguidos = seguidos + 1 if anterior and (f - anterior).days == 1 else 0",
     "efecto": "la mejor racha sale 1 menos (cada racha nueva empieza en 0)"},
    {"id": "B2", "clase": "off-by-one", "ruta": "backend/particion_proyecto.py", "funcion": "piezas_de_archivo",
     "antes": "a, acumulado, primero = n, 0, False",
     "ahora": "a, acumulado, primero = n + 1, 0, False",
     "efecto": "al cortar por líneas un bloque que no cabe, la línea n del corte no queda en ninguna pieza"},
    {"id": "B3", "clase": "caso borde", "ruta": "backend/file_manager.py", "funcion": "FileManager.is_path_allowed",
     "antes": "if os.path.commonpath([abs_path, root]) == root:",
     "ahora": "if abs_path.startswith(root):",
     "efecto": "acepta rutas hermanas con el mismo prefijo (raíz /ws: /ws-otro/x pasa)"},
    {"id": "B4", "clase": "caso borde", "ruta": "backend/recursos/termico.py", "funcion": "Tramo.pico_real",
     "antes": "return max(picos) if picos else None",
     "ahora": "return max(picos)",
     "efecto": "sin lecturas de temperatura (sin sensor) max([]) lanza ValueError"},
    {"id": "B5", "clase": "clave mal escrita", "ruta": "backend/recursos/ritmo.py", "funcion": "Ritmo.activo",
     "antes": 'return bool(self.ajustes.get("activo"))',
     "ahora": 'return bool(self.ajustes.get("activa"))',
     "efecto": "el modo suave nunca está activo (la clave guardada es «activo»)"},
    {"id": "B6", "clase": "clave mal escrita", "ruta": "backend/job_exporter.py", "funcion": "JobExporter.preparar",
     "antes": 'tope = int(ajustes.get("max_chunk_tokens") or max_chunk_tokens)',
     "ahora": 'tope = int(ajustes.get("max_chunks_tokens") or max_chunk_tokens)',
     "efecto": "el tope de tokens por trozo configurado se ignora (siempre el valor por defecto)"},
    {"id": "B7", "clase": "recurso sin liberar", "ruta": "backend/banco_proyecto.py", "funcion": "BancoProyecto.conectar",
     "antes": "        try:\n            yield c\n            c.commit()\n        finally:\n            c.close()\n",
     "ahora": "        yield c\n        c.commit()\n",
     "efecto": "la conexión SQLite nunca se cierra (y si hay una excepción, tampoco se confirma ni se cierra)"},
    {"id": "B8", "clase": "recurso sin liberar", "ruta": "backend/runner.py", "funcion": "CodeRunner.run_file",
     "antes": "            self._unregister(run_id)\n            process.kill()\n            stdout, stderr = process.communicate()",
     "ahora": "            self._unregister(run_id)\n            stdout, stderr = process.communicate()",
     "efecto": "al vencer el tiempo no se mata el proceso: communicate() sin tope espera para siempre"},
]
CONTROLES = [
    {"id": "C1", "ruta": "backend/recursos/termico.py", "funcion": "Gobernador.reanudar"},
    {"id": "C2", "ruta": "backend/file_manager.py", "funcion": "FileManager.resolve"},
    {"id": "C3", "ruta": "backend/inicio.py", "funcion": "perfil"},
    {"id": "C4", "ruta": "backend/recursos/ritmo.py", "funcion": "Ritmo.marcar"},
]
FLUJOS = [
    {"id": "F1", "pregunta": "Explica paso a paso qué ocurre en el backend cuando el frontend llama a "
     "`POST /api/desafios/{id}/comprobar`, desde el endpoint hasta que se devuelve el resultado. "
     "Cita `archivo:línea` en cada paso."},
    {"id": "F2", "pregunta": "¿Cómo decide el motor MoE (`backend/ai_engine/motor_moe.py`) el tamaño del contexto en modo "
     "automático y qué hace cuando una petición no cabe? Cita `archivo:línea` en cada afirmación."},
    {"id": "F3", "pregunta": "Cuando un archivo del proyecto cambia en el disco, ¿cómo se entera el banco del proyecto y "
     "qué actualiza (archivos, símbolos, grafo, unidades, lecturas)? Cita `archivo:línea` en cada paso."},
]
PREGUNTA_A = ("Revisa `{funcion}` en `{ruta}`. ¿Tiene algún error de programación? Si lo tiene, di en qué línea, qué hace "
              "mal y un caso concreto en el que falla. Si no lo tiene, dilo.")
PREGUNTA_B = ("En `{ruta}` (`{funcion}`) se acaba de hacer este cambio.\n\nAntes:\n```python\n{antes}\n```\nAhora:\n"
              "```python\n{ahora}\n```\n¿Qué tests de `backend/tests/` fallan (o se cuelgan) con este cambio? Nombra el "
              "archivo y el método de cada uno, o di que no falla ninguno.")


def banco_de(raiz):
    clave = hashlib.sha1(os.path.abspath(raiz).encode()).hexdigest()[:10]
    return os.path.join(BANCOS, f"{os.path.basename(raiz)}-{clave}")


def mutar(raiz, m):
    ruta = os.path.join(raiz, m["ruta"])
    texto = open(ruta, encoding="utf-8").read()
    assert texto.count(m["antes"]) == 1, (m["id"], texto.count(m["antes"]))
    inicio = texto.index(m["antes"])
    open(ruta, "w", encoding="utf-8").write(texto.replace(m["antes"], m["ahora"]))
    return texto[:inicio].count("\n") + 1                   # línea donde empieza el cambio


# ------------------------------------------------------------------------------------------------ preparar
if ACCION == "preparar":
    import banco_proyecto as bp, particion_proyecto as pp, lectura_unidades as lu
    # La copia comparte estados del motor con la copia limpia y con el banco real de Prig (mismo prefijo). Sin el
    # arreglo del 03/10, reasignar() borraba los estados de las unidades mutadas aunque OTRO banco los usara
    if not hasattr(lu.LectorUnidades, "_estados_de_otros_bancos"):
        sys.exit("El sistema no tiene el arreglo de reasignar (estados compartidos entre bancos): no se prepara")
    if os.path.exists(COPIA) or os.path.exists(banco_de(COPIA)):
        if "--rehacer" not in sys.argv:
            sys.exit(f"Ya existe {COPIA} o su banco: --rehacer")
        shutil.rmtree(COPIA, ignore_errors=True); shutil.rmtree(banco_de(COPIA), ignore_errors=True)
    shutil.copytree(LIMPIA, COPIA, symlinks=True)
    lineas = {m["id"]: mutar(COPIA, m) for m in MUTACIONES}
    os.makedirs(banco_de(COPIA))
    origen = sqlite3.connect(f"file:{banco_de(LIMPIA)}/banco.db?mode=ro", uri=True)
    destino = sqlite3.connect(os.path.join(banco_de(COPIA), "banco.db"))
    origen.backup(destino)
    destino.execute("INSERT OR REPLACE INTO meta VALUES ('raiz', ?)", (COPIA,))
    destino.commit(); destino.close(); origen.close()
    banco = bp.BancoProyecto(COPIA)
    assert banco.ruta_db.startswith(BANCOS)
    t = time.time(); sinc = banco.sincronizar(); t_sinc = time.time() - t
    t = time.time(); part = pp.particionar(banco); t_part = time.time() - t
    lector = lu.LectorUnidades(banco, None)
    lector.reasignar()
    vencidas = [o for o in lector._unidades if not lector.vigente(o)]
    with banco.conectar() as c:
        n_cambios = c.execute("SELECT COUNT(*) FROM cambios").fetchone()[0]
        c.execute("DELETE FROM cambios")
        version = c.execute("SELECT valor FROM meta WHERE clave = 'version'").fetchone()[0]
        c.execute("INSERT OR REPLACE INTO meta VALUES ('version_vista', ?)", (version,))
        for t_ in ("examen", "examen_resultados"):
            c.execute(f"DROP TABLE IF EXISTS {t_}")
    info = {"copia": COPIA, "banco": banco.ruta_db, "lineas_mutadas": lineas,
            "sincronizacion": {k: sinc[k] for k in ("nuevos", "modificados", "borrados")}, "segundos_sincronizar": round(t_sinc, 2),
            "segundos_particionar": round(t_part, 2), "unidades": len(lector._unidades),
            "vencidas": [{"orden": o, "tokens": lector._unidades[o]["tokens"], "rutas": lector._unidades[o]["rutas"]} for o in vencidas],
            "tokens_a_releer": sum(lector._unidades[o]["tokens"] for o in vencidas), "cambios_borrados": n_cambios}
    json.dump(info, open(os.path.join(DIR, "preparacion.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in info.items() if k != "vencidas"}, ensure_ascii=False),
          "\nvencidas:", [(v["orden"], v["tokens"], v["rutas"][:3]) for v in info["vencidas"]])

# ------------------------------------------------------------------------------------------------ verdad (tests)
def correr_tests(raiz, modulos, limite=240):
    """ unittest por archivo, aislado: HOME y bancos temporales, sin GPU, sin escribir .pyc. Devuelve
    {test: ok|FAIL|ERROR|skip|COLGADO} """
    casa = tempfile.mkdtemp(prefix="e8_home_")
    env = {**os.environ, "HOME": casa, "PRIG_BANCOS": os.path.join(casa, "bancos"), "CUDA_VISIBLE_DEVICES": "",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": ""}
    resultado = {}
    py = os.path.join(SISTEMA, ".venv/bin/python")
    for mod in modulos:
        try:
            p = subprocess.run([py, "-m", "unittest", "-v", f"tests.{mod}"], cwd=os.path.join(raiz, "backend"), env=env,
                               capture_output=True, text=True, timeout=limite)
            salida = p.stderr
        except subprocess.TimeoutExpired as e:
            # el archivo se colgó: cada test por separado, para saber cuál
            listado = subprocess.run([py, "-c", "import unittest,sys;s=unittest.defaultTestLoader.loadTestsFromName(sys.argv[1])\n"
                                      "def it(x):\n  for y in x:\n    yield from (it(y) if isinstance(y, unittest.TestSuite) else [y])\n"
                                      "print('\\n'.join(t.id() for t in it(s)))", f"tests.{mod}"],
                                     cwd=os.path.join(raiz, "backend"), env=env, capture_output=True, text=True, timeout=60).stdout.split()
            for tid in listado:
                try:
                    q = subprocess.run([py, "-m", "unittest", "-v", tid], cwd=os.path.join(raiz, "backend"), env=env,
                                       capture_output=True, text=True, timeout=60)
                    estado = "ok" if q.returncode == 0 else ("FAIL" if "FAIL" in q.stderr else "ERROR")
                    if "skipped" in q.stderr: estado = "skip"
                except subprocess.TimeoutExpired:
                    estado = "COLGADO"
                resultado[tid.split("tests.", 1)[-1]] = estado
            continue
        for m in re.finditer(r"^(\w+) \(([\w.]+)\)(?:\n.*?)? \.\.\. (ok|FAIL|ERROR|skipped.*?|expected failure|unexpected success)$",
                             salida, re.M):
            nombre, clase, estado = m.groups()
            estado = "skip" if estado.startswith("skipped") else estado
            resultado[f"{clase.split('tests.', 1)[-1]}.{nombre}"] = estado
        if p.returncode != 0 and not any(k.startswith(mod + ".") and v in ("FAIL", "ERROR") for k, v in resultado.items()):
            resultado[f"{mod}.<archivo>"] = "ERROR"             # no llegó a correr (falla al importar)
    shutil.rmtree(casa, ignore_errors=True)
    return resultado


if ACCION == "verdad":
    modulos = sorted(os.path.basename(f)[:-3] for f in glob.glob(os.path.join(LIMPIA, "backend/tests/test_*.py")))
    if "--modulos" in sys.argv:
        modulos = sys.argv[sys.argv.index("--modulos") + 1].split(",")
    pruebas = os.path.join(DIR, "pruebas")
    shutil.rmtree(pruebas, ignore_errors=True)
    def copia_para(nombre, m=None):
        destino = os.path.join(pruebas, nombre)
        shutil.copytree(LIMPIA, destino, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        if m: mutar(destino, m)
        return destino
    t0 = time.time()
    base = correr_tests(copia_para("base"), modulos)
    print(f"base: {len(base)} tests en {time.time() - t0:.0f} s; fallan {[k for k, v in base.items() if v not in ('ok', 'skip')]}", flush=True)
    verdad = {"base": base, "mutaciones": {}}
    for m in MUTACIONES:
        t = time.time()
        r = correr_tests(copia_para(m["id"], m), modulos)
        nuevos = {k: v for k, v in r.items() if v not in ("ok", "skip") and base.get(k) in ("ok", None)}
        verdad["mutaciones"][m["id"]] = {"fallan": nuevos, "tests": len(r), "segundos": round(time.time() - t)}
        print(f"{m['id']}: {len(nuevos)} tests nuevos fallan en {time.time() - t:.0f} s: {sorted(nuevos)}", flush=True)
        json.dump(verdad, open(os.path.join(DIR, "verdad_tests.json"), "w"), ensure_ascii=False, indent=1)
    shutil.rmtree(pruebas, ignore_errors=True)
    print("FIN verdad", round(time.time() - t0), "s")

# ------------------------------------------------------------------------------------------------ preguntas
if ACCION == "preguntas":
    a = [{"id": f"E8a_{m['id']}", "prueba": "E8a", "objetivo": m["id"], "pregunta": PREGUNTA_A.format(**m)}
         for m in MUTACIONES + CONTROLES]
    random.Random(8).shuffle(a)                                    # orden fijo, mezclado
    b = [{"id": f"E8b_{m['id']}", "prueba": "E8b", "objetivo": m["id"], "pregunta": PREGUNTA_B.format(
        ruta=m["ruta"], funcion=m["funcion"], antes=m["antes"].strip("\n"), ahora=m["ahora"].strip("\n"))} for m in MUTACIONES]
    c = [{"id": f"E8c_{f['id']}", "prueba": "E8c", "objetivo": f["id"], "pregunta": f["pregunta"]} for f in FLUJOS]
    json.dump(a + b + c, open(os.path.join(DIR, "preguntas_e8.json"), "w"), ensure_ascii=False, indent=1)
    print(len(a), len(b), len(c), "preguntas →", os.path.join(DIR, "preguntas_e8.json"))

# ------------------------------------------------------------------------------------------------ corregir (ayudas)
CITA = re.compile(r"`?((?:backend|frontend)/[\w./-]+\.\w+)`?(?:\s*\(?\s*(?:l[íi]neas?|l\.)\s*|:)(\d+)(?:\s*[-–]\s*(\d+))?")

def verificar_citas(texto, raiz):
    """ Cada «archivo:línea» citado: ¿existe el archivo, la línea, y algún identificador de la misma oración aparece
    a ±3 líneas? (lo último es una ayuda; el juicio final es a mano) """
    citas = []
    for m in CITA.finditer(texto):
        ruta, a, b = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
        archivo = os.path.join(raiz, ruta)
        if not os.path.exists(archivo):
            citas.append({"cita": m.group(0), "estado": "archivo inexistente"}); continue
        lineas = open(archivo, encoding="utf-8", errors="replace").read().splitlines()
        if a < 1 or a > len(lineas):
            citas.append({"cita": m.group(0), "estado": f"línea fuera del archivo ({len(lineas)})"}); continue
        oracion = texto[max(0, texto.rfind("\n", 0, m.start())):texto.find("\n", m.end()) if texto.find("\n", m.end()) > 0 else None]
        ids = {x for x in re.findall(r"`([A-Za-z_][\w.]*)(?:\(\))?`", oracion) if x not in (ruta,)} | \
              {x for x in re.findall(r"\b([a-z_]+[a-z0-9]*_[a-z0-9_]+|[A-Z][a-z]+[A-Z]\w+)\b", oracion)}
        ventana = "\n".join(lineas[max(0, a - 4):min(len(lineas), b + 3)])
        vistos = sorted(x for x in ids if x.split(".")[-1] in ventana)
        citas.append({"cita": m.group(0), "estado": "coincide" if vistos else ("sin identificadores" if not ids else "no coincide"),
                      "identificadores": sorted(ids)[:8], "vistos": vistos})
    return citas


if ACCION == "corregir":
    resp = json.load(open(os.path.join(DIR, sys.argv[2] if len(sys.argv) > 2 else "respuestas_e8.json")))["resultados"]
    verdad = json.load(open(os.path.join(DIR, "verdad_tests.json")))
    mut = {m["id"]: m for m in MUTACIONES}
    salida = []
    for r in resp:
        x = {"id": r["id"], "prueba": r["prueba"], "objetivo": r["objetivo"], "modo": r["modo"], "segundos": r["segundos"],
             "consultas": len(r["consultas"]), "agotada": r["agotada"]}
        texto = r["respuesta"]
        if r["prueba"] == "E8a":
            niega = bool(re.search(r"no (tiene|encontr\w+|hay|veo|presenta)\b[^.\n]{0,40}(error|fallo|bug|problema)", texto, re.I))
            if r["objetivo"] in mut:
                m = mut[r["objetivo"]]
                distintivo = [t for t in re.findall(r"[\w\"'.+]+", m["ahora"]) if t not in re.findall(r"[\w\"'.+]+", m["antes"])] \
                    or re.findall(r"\w+", m["antes"].replace(m["ahora"].strip(), ""))
                x["ayuda"] = {"niega_error": niega, "menciona_lo_cambiado": [t for t in set(distintivo) if t.strip("\"'") in texto]}
            else:
                x["ayuda"] = {"niega_error": niega}
        elif r["prueba"] == "E8b":
            esperados = set(verdad["mutaciones"][r["objetivo"]]["fallan"])
            esperados_metodos = {k.split(".")[-1] for k in esperados}
            dichos = set(re.findall(r"\b(test_\w+)\b", texto)) - {k.split(".")[0] for k in esperados}  # métodos (no archivos)
            dichos = {d for d in dichos if not os.path.exists(os.path.join(COPIA, "backend/tests", d + ".py"))}
            acierto = dichos & esperados_metodos
            x["ayuda"] = {"verdad": sorted(esperados), "dichos": sorted(dichos), "aciertos": sorted(acierto),
                          "precision": round(len(acierto) / len(dichos), 2) if dichos else None,
                          "cobertura": round(len(acierto) / len(esperados_metodos), 2) if esperados_metodos else None,
                          "dice_ninguno": bool(re.search(r"ning[uú]n test|no falla ning|ninguno", texto, re.I))}
        else:
            citas = verificar_citas(texto, COPIA)
            x["ayuda"] = {"citas": len(citas), "coinciden": sum(c["estado"] == "coincide" for c in citas),
                          "malas": [c for c in citas if c["estado"] not in ("coincide",)]}
        salida.append(x)
    json.dump(salida, open(os.path.join(DIR, "correccion_e8.json"), "w"), ensure_ascii=False, indent=1)
    for x in salida:
        print(x["id"], x["modo"], x["segundos"], json.dumps(x["ayuda"], ensure_ascii=False)[:300])
