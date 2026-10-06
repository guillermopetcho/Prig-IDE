"""E5: corrección funcional de la consola P sobre el banco real (solo métodos de lectura) y límites de uso.
Uso: PRIG_CONSOLA_ALARMA=5 .venv/bin/python docs/estudio-banco/consola.py"""
import sys, os, json, time, sqlite3
sys.path.insert(0, "/home/ama-gi/Prig/backend")
import banco_proyecto as bp, memoria_consulta as mc
banco = bp.BancoProyecto("/home/ama-gi/Prig")
db = sqlite3.connect("file:/home/ama-gi/.prig_bancos/Prig-ac5380d79d/banco.db?mode=ro", uri=True)
con = mc.Consola(banco)
def run(codigo):
    t = time.time(); r = con.ejecutar(codigo); return r, round(time.time() - t, 2)
casos = [
 ("api con método, endpoint normal", 'r = P.api("POST /api/ai/chat"); (len(r["expone"]), len(r["consume"]), [x["s"] for x in r["expone"]])'),
 ("api del Hub con su ruta real", 'r = P.api("GET /api/hub/estado"); (len(r["expone"]), len(r["consume"]))'),
 ("api del Hub con la ruta guardada", 'r = P.api("GET /estado"); (len(r["expone"]), [x["s"] for x in r["expone"]])'),
 ("llamadores de un método", 'len(P.llamadores("BancoProyecto.conectar"))'),
 ("llamadores de un nombre repetido", 'r = P.llamadores("get"); (type(r).__name__, len(r) if isinstance(r, list) else r)'),
 ("código de una función anidada", 'P.codigo("generar.elegir")[:120]'),
 ("camino entre dos funciones", 'P.camino("ai_chat", "BancoProyecto.registrar_resolucion")'),
 ("impacto de un método que solo usa una instancia global", 'r = P.impacto("BookService.get_book_citations"); {k: (len(v) if isinstance(v, list) else v) for k, v in r.items()}'),
 ("dónde: clave de configuración", 'r = P.donde("moe_contexto"); {k: (len(v) if isinstance(v, list) else v) for k, v in r.items()}'),
 ("dónde: variable de entorno", 'r = P.donde("PRIG_BANCOS"); {k: (len(v) if isinstance(v, list) else v) for k, v in r.items()}'),
 ("recorrido desde un endpoint", 'len(P.recorrido("/api/banco/consola").splitlines())'),
 ("símbolos basura del Markdown", 'len(P.simbolos(nombre="=" * 69))'),
 ("leer un cuaderno", 'len(P.lineas("ejemplo_notebook.ipynb"))'),
 ("sql de lectura", 'P.sql("SELECT COUNT(*) n FROM llamadas")'),
 ("sql que intenta escribir", 'P.sql("DELETE FROM meta WHERE clave = \'x\'")'),
 ("variable persiste entre llamadas (1)", 'guardado = 41'),
 ("variable persiste entre llamadas (2)", 'guardado + 1'),
 ("límite: bucle que no termina", 'while True: pass'),
 ("límite: salida enorme", 'print("x" * 100000)'),
 ("límite: memoria", 'x = [0] * 400_000_000'),
 ("sigue viva después de los límites", '1 + 1'),
]
res = []
for nombre, codigo in casos:
    r, s = run(codigo)
    res.append({"caso": nombre, "segundos": s, "salida": (r.get("salida") or "")[:220], "error": (r.get("error") or "")[:160]})
# referencias independientes (SQL directo sobre el banco)
ref = {"llamadores_conectar_sql": db.execute("SELECT COUNT(*) FROM llamadas WHERE a_nombre='BancoProyecto.conectar'").fetchone()[0]}
con.cerrar()
print(json.dumps({"casos": res, "referencias": ref}, ensure_ascii=False, indent=1))
