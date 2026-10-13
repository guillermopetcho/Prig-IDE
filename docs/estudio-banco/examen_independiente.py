"""E6: examen con verdad independiente del banco. La respuesta correcta sale de ejecutar el código, de jedi
o de los decoradores (AST), nunca de las tablas del banco; las de diseño llevan rúbrica y se corrigen a mano.
Se regenera sobre el código actual del disco: correrlo DESPUÉS de sincronizar el banco (E7).
Uso: PYTHONPATH=~/.local/lib/python3.10/site-packages .venv/bin/python docs/estudio-banco/examen_independiente.py
Escribe docs/estudio-banco/examen_independiente.json"""
import ast, json, os, sys
RAIZ = "/home/ama-gi/Prig"
sys.path.insert(0, os.path.join(RAIZ, "backend"))
import banco_proyecto as bp, particion_proyecto as pp, examen_proyecto as ex, fichas_simbolos as fs
from ai_engine import motor_moe
from desafios import ejecucion

preguntas = []
def agregar(tipo, pregunta, esperado, evaluar, origen, rubrica=None):
    preguntas.append({"id": f"ind_{len(preguntas)+1:02d}", "tipo": tipo, "pregunta": pregunta, "esperado": esperado,
                      "evaluar": evaluar, "origen_de_la_verdad": origen, **({"rubrica": rubrica} if rubrica else {})})

# 1. Ejecución: ¿qué devuelve? (entender el código, no buscarlo)
def ejecutar(expr, llamada_legible, archivo):
    valor = eval(expr)
    agregar("ejecucion", f"Sin ejecutarlo, ¿qué devuelve `{llamada_legible}` (definida en `{archivo}`)?",
            [json.dumps(valor, ensure_ascii=False)], "valor_exacto", f"ejecución de {expr}")
ejecutar('bp.ruta_http_canonica("/api/x/{id}/y?z=1")', 'ruta_http_canonica("/api/x/{id}/y?z=1")', "backend/banco_proyecto.py")
ejecutar('bp.ruta_http_canonica("/api/desafios/${id}/comprobar/")', 'ruta_http_canonica("/api/desafios/${id}/comprobar/")', "backend/banco_proyecto.py")
ejecutar('bp.estimar_tokens("abcd" * 30)', 'estimar_tokens("abcd" * 30)', "backend/banco_proyecto.py")
ejecutar('bp.lenguaje_de("frontend/js/app.js")', 'lenguaje_de("frontend/js/app.js")', "backend/banco_proyecto.py")
ejecutar('bp.lenguaje_de("docs/notas.md")', 'lenguaje_de("docs/notas.md")', "backend/banco_proyecto.py")
ejecutar('pp._carpeta("backend/ai_engine/motor_moe.py")', '_carpeta("backend/ai_engine/motor_moe.py")', "backend/particion_proyecto.py")
ejecutar('pp._carpeta("backend/ai_engine/motor_moe.py", 1)', '_carpeta("backend/ai_engine/motor_moe.py", 1)', "backend/particion_proyecto.py")
ejecutar('ex._corto("Clase.metodo")', '_corto("Clase.metodo")', "backend/examen_proyecto.py")
ejecutar('ex._aparece("guardar", "Hub.guardar()")', '_aparece("guardar", "Hub.guardar()")', "backend/examen_proyecto.py")
ejecutar('fs._json_lista("antes ```json\\n[{\\"a\\": 1}, 2]\\n``` después")', "_json_lista('antes ```json\\n[{\"a\": 1}, 2]\\n``` después')", "backend/fichas_simbolos.py")
ejecutar('motor_moe.es_moe(" qwen3.6-35b-moe:prig ")', 'es_moe(" qwen3.6-35b-moe:prig ")', "backend/ai_engine/motor_moe.py")
ejecutar('motor_moe.CONTEXTOS[16384]', 'CONTEXTOS[16384]', "backend/ai_engine/motor_moe.py")
try:
    ejecucion.validar_paginas([{"nombre": f"p{i}.py", "contenido": ""} for i in range(9)])
    resultado = "no lanza"
except Exception as e:
    resultado = f"{type(e).__name__}: {e}"
agregar("ejecucion", "¿Qué pasa si se llama a `validar_paginas` (en `backend/desafios/ejecucion.py`) con 9 páginas?",
        [resultado.split(":")[0]], "contiene", "ejecución", rubrica=[resultado])

# 2. Llamadores según jedi, elegidos donde el banco pierde aristas (E2): ¿el modelo compensa leyendo?
try:
    import jedi
    proyecto = jedi.Project(path=RAIZ, added_sys_path=[os.path.join(RAIZ, "backend")])
    def llamadores_jedi(ruta, linea_def, nombre):
        texto = open(os.path.join(RAIZ, ruta)).read()
        linea = texto.splitlines()[linea_def - 1]
        col = linea.index(nombre)
        refs = jedi.Script(texto, path=os.path.join(RAIZ, ruta), project=proyecto).get_references(linea_def, col, scope="project")
        quien = set()
        for r in refs:
            if r.line == linea_def and str(r.module_path).endswith(ruta):
                continue
            ctx = r.parent()
            while ctx is not None and ctx.type not in ("function", "module"):
                ctx = ctx.parent()
            if ctx is not None and ctx.type == "function" and "/tests/" not in str(r.module_path):
                # un llamador homónimo del destino aparece ya en la pregunta: se exige su archivo
                quien.add(ctx.name if ctx.name != nombre else os.path.relpath(str(r.module_path), RAIZ))
        return sorted(quien)
    for ruta, nombre in [("backend/book_service.py", "get_book_citations"), ("backend/book_service.py", "delete_item"),
                         ("backend/recursos/gestor.py", "radiografia"), ("backend/study_plan_engine.py", "load_state")]:
        texto = open(os.path.join(RAIZ, ruta)).read().splitlines()
        linea = next(i for i, l in enumerate(texto, 1) if l.lstrip().startswith(f"def {nombre}("))
        quien = llamadores_jedi(ruta, linea, nombre)
        if quien:
            agregar("llamadores_independiente", f"¿Qué funciones o métodos (fuera de los tests) llaman a `{nombre}` definida en `{ruta}`?",
                    quien, "conjunto", "jedi get_references (no el banco)")
except ImportError:
    print("jedi no disponible: se omiten los llamadores independientes")

# 3. Endpoints del Hub con su ruta real (prefijo del router, AST)
arbol = ast.parse(open(os.path.join(RAIZ, "backend/hub/api.py")).read())
prefijo = next(kw.value.value for n in ast.walk(arbol) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "APIRouter"
               for kw in n.keywords if kw.arg == "prefix")
hub = []
for n in ast.walk(arbol):
    if isinstance(n, ast.FunctionDef):
        for d in n.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post") and d.args:
                hub.append((f"{d.func.attr.upper()} {prefijo}{d.args[0].value}", n.name))
for ruta_http, funcion in hub[:4]:
    agregar("endpoint_real", f"¿Qué función implementa el endpoint `{ruta_http}` y en qué archivo está?",
            [funcion, "backend/hub/api.py"], "conjunto", "decorador + prefijo de APIRouter (AST)")

# 4. Diseño («por qué»): rúbrica, corrección manual
diseno = [
    ("¿Por qué `LectorUnidades.mensajes` (en `backend/lectura_unidades.py`) no incluye el contexto del grafo ni la guía de la consola?",
     ["ese contexto cambia cuando se edita otra parte del proyecto", "si estuviera en el prefijo invalidaría el estado guardado",
      "por eso va con cada pregunta (pregunta_con_contexto)"]),
    ("¿Por qué el motor MoE tiene que guardar el estado exacto al final del bloque leído, y no uno parecido?",
     ["las capas SSM (DeltaNet) no pueden retroceder", "un estado posterior no sirve para otro sufijo"]),
    ("En la consola P, ¿qué impide que un código que tarda en `P.llm` se corte por la alarma de 30 s, y qué evita confundir respuestas?",
     ["la alarma se pausa mientras se espera a Prig", "cada petición lleva un número y las respuestas viejas se descartan"]),
    ("¿Qué hace `agrupar` (en `backend/particion_proyecto.py`) con las piezas que quedan sueltas, sin llamadas que las unan?",
     ["las junta por carpeta, de la más chica a la más grande", "las muy chicas se juntan aunque sean de carpetas distintas",
      "siempre respetando el tope de tokens"]),
    ("¿Qué impide que el código de la consola P modifique la base del banco?",
     ["la base se abre en solo lectura (mode=ro)", "P.sql solo acepta SELECT", "las escrituras las hace Prig a pedido"]),
    ("¿Cómo decide el motor MoE cuántos expertos calientes cargar, y qué hace si al arrancar no caben en la GPU?",
     ["según la VRAM libre y el contexto", "si no arranca, reintenta con menos expertos calientes", "y si no, sin MTP"]),
]
for p, r in diseno:
    agregar("diseno", p, [], "rubrica_manual", "lectura humana del código y sus docstrings", rubrica=r)

destino = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examen_independiente.json")
with open(destino, "w", encoding="utf-8") as f:
    json.dump(preguntas, f, ensure_ascii=False, indent=1)
print(len(preguntas), "preguntas →", destino)
for p in preguntas:
    print(f"  {p['id']} {p['tipo']:24} {p['pregunta'][:70]:70} → {p['esperado'][:3] if p['esperado'] else p['rubrica'][:1]}")
