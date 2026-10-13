"""T7 corta: una entrada por pregunta y corrida, con los datos de la sonda y el veredicto de la auditoría a mano
(contra el código, no contra una clave; el detalle de cada una está en notas.md).

  .venv/bin/python ~/.cache/prig-estudio/t7/analisis.py   →   ~/.cache/prig-estudio/t7/analisis.json"""
import json, os
T = os.path.dirname(os.path.abspath(__file__))

# (veredicto, mecanismo, E7) — C correcta, P parcial, I incorrecta; en E8: detecta / no detecta / falso positivo
AUDITORIA = {
    "prig_general": {
        "ind_15": ("P", "hechos con delete_book (app.py:450) ignorados; 8 consultas; encuentra la línea sin el nombre e inventa la ruta", "I (3 de 3)"),
        "ind_16": ("P", "los hechos traían los 2 llamadores externos y los descarta con una restricción inventada («solo internas»)", "P"),
        "f46b5c0819d3": ("C", "3 de 4 endpoints (falta /api/progreso/resumen, dos saltos); 8 consultas; mismo criterio que E7", "C (clave incompleta)"),
        "a84a7fe1bad7": ("P", "_ajustes por el texto literal de los hechos + falso positivo ConfigModelos._leer (define el valor, no lo lee); omite embeber y estado", "P"),
        "29b468d8a2cb": ("C", "las dos rutas exactas, de los hechos («endpoints reached through the graph»)", "P"),
        "12bb842411c5": ("P", "POST /api/app/shutdown exacta de los hechos; inventa rutas «indirectas» (/api/chat…)", "I"),
        "0b5f93c17f28": ("I", "niega el camino; nombra las dos piezas sin unirlas; los hechos miran cada nombre por separado", "I"),
        "d408dee5873f": ("I", "niega el camino (régimen estable: el gobernador ya existe); 0 consultas", "I"),
        "ind_27": ("C", "0 consultas: el código literal del paquete alcanza; secuencia de reintentos incompleta pero sin nada falso", "agotada (28 consultas)"),
        "1f14bd2a14dd": ("C", "credenciales() l.89, la única lectora; 1 consulta", "agotada (vacía)"),
        "02bd1db0d170": ("C", "Hub._crear l.151 y Hub.editar_manifiesto l.222", "I (salida «...»)"),
        "8caebf27e7ba": ("C", "control: 20.0 bien, la línea mal (dice 22; es 60)", "C"),
    },
    "prig_unidad": {
        "ind_15": ("C", "usa los hechos: delete_book en app.py:450; 1 consulta", "I (3 de 3)"),
        "ind_16": ("C", "P.llamadores (con los de texto): los 4 reales + calibrar, falso positivo de la búsqueda por texto (atributo maq.radiografia)", "P"),
        "f46b5c0819d3": ("C", "fue a general (la mejor unidad 29 %): 4 de 4 esta vez; 7 consultas", "C (clave incompleta)"),
        "a84a7fe1bad7": ("P", "P.hechos(lee_config): embeber y estado; omite _ajustes (la lectora literal, que venía en los hechos)", "P"),
        "29b468d8a2cb": ("C", "las dos rutas exactas; razonamiento confuso («el grafo no la resolvió», falso)", "P"),
        "12bb842411c5": ("C", "P.impacto: la ruta exacta y los otros llamadores reales, sin invenciones", "I"),
        "0b5f93c17f28": ("I", "fue a general (27 %): niega el camino con una afirmación falsa explícita", "I"),
        "d408dee5873f": ("I", "fue a general (24 %): muestra termico.py:365 (Gobernador crea ControladorFrio) y aun así niega el camino", "I"),
        "ind_27": ("P", "5 consultas, sin bucle; da como «orden exacto» una secuencia de reintentos falsa (n sin MTP antes que n-8 con MTP; n sin MTP se recalcula) e inventa /var/log/prig.log", "agotada (28 consultas)"),
        "1f14bd2a14dd": ("C", "credenciales() l.89; 0 consultas", "agotada (vacía)"),
        "02bd1db0d170": ("C", "P.llamadores: Hub._crear l.151 y Hub.editar_manifiesto l.222", "I (salida «...»)"),
        "8caebf27e7ba": ("C", "fue a general (57 %, pero la mejor no llega a 1,5 × la segunda): 20.0 bien, la línea mal (dice 39)", "C"),
    },
    "e8_general": {
        "E8a_B2": ("falso positivo", "no ve `a = n + 1` (l.97); prueba el bucle de los hijos y da como error la cobertura contigua entre métodos (diseño)", None),
        "E8a_B3": ("detecta", "l.40, caso /home/usuario/workspace_malicioso, arreglo correcto; 0 consultas", None),
        "E8a_B6": ("no detecta", "salida degenerada («Espera… esto es correcto» ×6); nunca mira la l.93 (max_chunks_tokens)", None),
        "E8a_B7": ("no detecta", "«no tiene ningún error»; inventa un finally implícito; Flask en vez de FastAPI", None),
        "E8a_C2": ("correcto", "control sin falso positivo; afirma que «..» queda bloqueado, falso en esta copia por B3 (resolve delega en is_path_allowed)", None),
    },
    "e8_unidad": {
        "E8a_B2": ("falso positivo", "lectura al vuelo (T5); 8 consultas; mira el corte por líneas y lo abandona; repite el falso positivo del general y agrega una pérdida de líneas que no existe", None),
        "E8a_B3": ("no detecta", "lectura al vuelo; 0 consultas; «/workspace vs /workspace2 está protegido» (falso); ve el except de commonpath y lo justifica", None),
        "E8a_B6": ("falso positivo", "lectura al vuelo; 3 consultas (anotar rechazado); patrón degenerado y da como error el literal 120 de la l.117 (otro concepto)", None),
        "E8a_B7": ("no detecta", "lectura al vuelo; 0 consultas; dice que el commit corre también con excepción (falso); no ve que falta close", None),
        "E8a_C2": ("correcto", "restaura la lectura que T5 guardó en B3; control sin falso positivo; afirma que no hay huecos (falso en esta copia por B3)", None),
    },
    # Segunda tanda: g2/u2 otra muestra de cada modo; gf general con los hechos al final (arnés)
    "t2_prig": {
        "ind_15·g2": ("C", "delete_book app.py:446-450, POST /api/books/delete; 3 consultas", "I (3 de 3)"),
        "ind_15·gf": ("C", "la más precisa: la ruta, el código y descarta el homónimo file_mgr.delete_item", "I (3 de 3)"),
        "ind_15·u2": ("C", "mínima: delete_book, app.py:450; 0 consultas", "I (3 de 3)"),
        "ind_16·g2": ("C", "los 4 reales, sin falsos positivos", "P"),
        "ind_16·gf": ("C", "los 4; verifica y descarta calibrar (atributo) y detector.radiografia (homónimo)", "P"),
        "ind_16·u2": ("C", "los 4 + calibrar: el mismo falso positivo de la herramienta (sistemático en unidad)", "P"),
        "12bb842411c5·g2": ("C", "la única ruta exacta + lifespan + main.py; sin invenciones", "I"),
        "12bb842411c5·gf": ("C", "la única ruta exacta; lifespan explicado como no-endpoint; 0 consultas", "I"),
        "12bb842411c5·u2": ("C", "P.impacto; conciso (con el eco del código al principio)", "I"),
        "ind_27·g2": ("P", "«el mismo n sin MTP» (falso), un código simplificado presentado como literal, «8 capas»; sin el modo manual", "agotada (28 consultas)"),
        "ind_27·u2": ("C", "la secuencia exacta y literal; 0 calientes y 240 s verificados", "agotada (28 consultas)"),
        "a84a7fe1bad7·gf": ("P", "las 3 lectoras (primera vez) + _leer (define) y fijar_embeddings (escribe)", "P"),
        "29b468d8a2cb·gf": ("C", "las dos rutas, líneas, los 6 servicios y los consumidores del frontend", "P"),
        "02bd1db0d170·gf": ("C", "Hub._crear l.151 y Hub.editar_manifiesto l.222", "I (salida «...»)"),
    },
    "t2_e8": {
        "E8a_B3·g2": ("detecta", "l.39 (es 40), caso y arreglo correctos", None),
        "E8a_B3·u2": ("detecta", "l.37 (es 40), caso y arreglo correctos", None),
        "E8a_B3·g3": ("detecta", "l.39, caso y arreglo correctos", None),
        "E8a_B3·u3": ("detecta", "l.39, función literal, tres casos", None),
    },
}


def corrida(nombre):
    ruta = os.path.join(T, f"{nombre}.json")
    if not os.path.exists(ruta):
        return []
    d = json.load(open(ruta))
    salida = []
    for r in d["resultados"]:
        v = AUDITORIA[nombre].get(r["id"])
        salida.append({
            "corrida": nombre, "id": r["id"], "prueba": r.get("prueba"),
            "modo_pedido": d["condiciones"].get("modo"), "modo_usado": r["modo"], "unidad": r.get("unidad"),
            "motivo": r.get("motivo"), "segundos": r["segundos"], "consultas": len(r["consultas"]),
            "hechos_caracteres": r.get("hechos_caracteres"), "agotada": r["agotada"],
            "veredicto": v[0] if v else None, "mecanismo": v[1] if v else None, "e7": v[2] if v else None,
        })
    return salida


todas = [e for n in AUDITORIA for e in corrida(n)]
for e in todas:
    if e["id"] in AUDITORIA[e["corrida"]]:
        e["base"] = e["id"].split("·")[0]
        e["config"] = ("gf" if e["id"].endswith("·gf") else
                       "general" if e["corrida"].endswith("general") or e["id"].endswith(("·g2", "·g3")) else "unidad")
json.dump(todas, open(os.path.join(T, "analisis.json"), "w"), ensure_ascii=False, indent=1)

# Combinado: por pregunta y configuración, la fracción de correctas entre sus muestras; suma sobre las 11 de falla.
# «gf» donde no se midió (sin hechos que mover, o fuera de la segunda tanda) toma el valor del general, y se dice.
FALLA = ["ind_15", "ind_16", "f46b5c0819d3", "a84a7fe1bad7", "29b468d8a2cb", "12bb842411c5", "0b5f93c17f28",
         "d408dee5873f", "ind_27", "1f14bd2a14dd", "02bd1db0d170"]
prig = [e for e in todas if e["corrida"] in ("prig_general", "prig_unidad", "t2_prig")]
def fraccion(base, config):
    v = [e["veredicto"] for e in prig if e["base"] == base and e["config"] == config]
    return (sum(x == "C" for x in v) / len(v), len(v)) if v else (None, 0)
print("\npregunta        general        unidad         general+hechos al final")
suma = {"general": 0.0, "unidad": 0.0, "gf": 0.0}
for b in FALLA:
    fila = []
    for cfg in ("general", "unidad", "gf"):
        f, n = fraccion(b, cfg)
        prestada = f is None
        if prestada:
            f, n = fraccion(b, "general")
        suma[cfg] += f
        fila.append(f"{f:.1f} ({n}){'*' if prestada else ' '}")
    print(f"{b[:14]:15} " + "   ".join(f"{x:12}" for x in fila))
print("correctas esperadas en 11:", {k: round(v, 1) for k, v in suma.items()}, "· * = sin medir con gf: valor del general")
for n in AUDITORIA:
    filas = [e for e in todas if e["corrida"] == n]
    cuenta = {}
    for e in filas:
        cuenta[e["veredicto"]] = cuenta.get(e["veredicto"], 0) + 1
    print(n, len(filas), "preguntas ·", cuenta, "· en general:", sum(e["modo_usado"] == "general" for e in filas),
          "· s:", round(sum(e["segundos"] for e in filas)))
