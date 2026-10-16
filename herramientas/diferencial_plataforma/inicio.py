"""Diferencial de inicio.py: la versión de Python puro (REFERENCIA) contra la de ahora (Rust por prig_nativo).
El perfil (con archivos rotos o de otro tipo y cambios al azar), la línea de actividad y la tira de la semana
tienen que dar lo mismo, con las mismas excepciones, y el archivo del perfil tiene que quedar igual byte a byte.

    .venv/bin/python herramientas/diferencial_plataforma/inicio.py [semilla] [vueltas]
"""
import json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import TMP, viejo  # noqa: E402
os.environ["PRIG_INICIO_ARCHIVO"] = os.path.join(TMP, "sub", "inicio.json")
import inicio as inn  # noqa: E402
inv = viejo("inicio")

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 400
R = random.Random(semilla)
fallos, cuentas = [], {}
RUTA = os.environ["PRIG_INICIO_ARCHIVO"]


def val(prof=0):
    t = R.random()
    if prof > 1 or t < 0.6:
        return R.choice([None, "", "x", " Ana  María\t", "ñ" * 70, 0, 3, 2.5, True, False, "2026-10-14T10:11:12.123+00:00",
                         "2026-10-13", ["a", "b", "c", "d"], [1, 2]])
    if t < 0.8: return [val(prof + 1) for _ in range(R.randint(0, 3))]
    return {R.choice(["total", "pasados", "x"]): val(prof + 1) for _ in range(R.randint(0, 2))}


def item(claves):
    if R.random() < 0.05: return val()
    return {k: (val() if R.random() < 0.5 else R.choice(["resuelto", "nuevo", "notebook", "dataset", "2026-10-1%d" % R.randint(0, 9)]))
            for k in R.sample(claves, R.randint(0, len(claves)))}


def ejecutar(f):
    try:
        return ("ok", json.dumps(f(), ensure_ascii=False))
    except Exception as e:
        return ("error", type(e).__name__, str(e))


def leer():
    try:
        with open(RUTA, "rb") as f: return f.read()
    except OSError as e: return type(e).__name__


def comparar(nombre, a, b):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 10:
        fallos.append({"prueba": nombre, "viejo": str(a)[:900], "nuevo": str(b)[:900]})


for _ in range(N):
    inicial = R.choice([None, "", "{", "[]", "null", json.dumps({"nombre": "Ana", "otra": 1, "nivel": "avanzado"}),
                        json.dumps({"favoritas": [], "mostrar_al_abrir": 0})])
    cambios = [{k: val() if R.random() < 0.7 else R.choice(["intermedio", "avanzado", "x"])
                for k in R.sample(["nombre", "objetivo", "nivel", "mostrar_al_abrir", "favoritas", "otra"], R.randint(0, 6))}
               for _ in range(R.randint(0, 3))]
    res = []
    for mod in (inv, inn):
        os.makedirs(os.path.dirname(RUTA), exist_ok=True)
        if inicial is None:
            if os.path.exists(RUTA): os.remove(RUTA)
        else:
            with open(RUTA, "w") as f: f.write(inicial)
        pasos = [ejecutar(mod.perfil)]
        for c in cambios:
            pasos.append(ejecutar(lambda: mod.guardar_perfil(c)))
        pasos.append(leer())
        res.append(pasos)
    comparar("perfil", res[0], res[1])

    listas = [[item(["estado", "mejor", "intentos", "conceptos", "titulo", "actualizado", "creado", "id"]) for _ in range(R.randint(0, 4))],
              [item(["titulo", "leidas", "total", "ultima", "ref", "ultima_celda"]) for _ in range(R.randint(0, 3))],
              [item(["tipo", "titulo", "coleccion", "anadido", "ref"]) for _ in range(R.randint(0, 3))],
              [item(["fecha", "nombre", "relativa", "tipo", "ref"]) for _ in range(R.randint(0, 3))],
              [item(["resuelto", "concepto", "envios", "fecha"]) for _ in range(R.randint(0, 3))]]
    n = R.choice([14, 2])
    comparar("actividad", ejecutar(lambda: inv.actividad({}, *listas, n=n)), ejecutar(lambda: inn.actividad({}, *listas, n=n)))
    import datetime
    hoy = datetime.date.today()
    por_dia = R.choice([{}, None, [], {(hoy - datetime.timedelta(days=R.randint(0, 8))).isoformat(): R.choice([1, 2.7, "3", "x", None, True]) for _ in range(3)}])
    comparar("semana", ejecutar(lambda: inv.semana(por_dia)), ejecutar(lambda: inn.semana(por_dia)))
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
