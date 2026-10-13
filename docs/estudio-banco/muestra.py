import json, os, random, sys
import jedi
random.seed(11)
r = json.load(open("aristas.json"))
SNAP = "snap"; proyecto = jedi.Project(path=SNAP, added_sys_path=[os.path.join(SNAP, "backend")])
def jedi_en(ruta, linea, nombre):
    texto = open(os.path.join(SNAP, ruta)).read(); l = texto.splitlines()[linea-1]
    col = l.find(nombre + "(")
    if col < 0: col = l.find(nombre)
    if col < 0: return "?"
    try:
        ds = jedi.Script(texto, path=os.path.join(SNAP, ruta), project=proyecto).goto(linea, col, follow_imports=True)
        return [f"{os.path.relpath(str(d.module_path), SNAP) if str(d.module_path).startswith(os.path.abspath(SNAP)) or str(d.module_path).startswith(SNAP) else 'EXT:'+os.path.basename(str(d.module_path))}:{d.full_name}" for d in ds][:3]
    except Exception as e: return f"err {e}"
for cat, n in [(a, int(b)) for a, b in (x.split("=") for x in sys.argv[1:])]:
    ej = r["ejemplos"][cat]; print(f"##### {cat} (total {r['conteos'][cat]}), muestra {n}")
    for e in random.sample(ej, min(n, len(ej))):
        k, linea = (e[0], e[1]) if isinstance(e[0], list) else (e, None)
        ruta, desde, a_ruta, a_nombre = k
        if linea is None: continue
        texto = open(os.path.join(SNAP, ruta)).read().splitlines()[linea-1].strip()[:120]
        corto = a_nombre.split(".")[-1]
        print(f"- {ruta}:{linea} [{desde}] banco→ {a_ruta}:{a_nombre}\n    {texto}\n    jedi: {jedi_en(ruta, linea, corto)}")
