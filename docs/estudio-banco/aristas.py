"""E2 (c): grafo a nivel de arista (quién llama → a quién), contra jedi, con las convenciones del banco"""
# Uso: PYTHONPATH=~/.local/lib/python3.10/site-packages .venv/bin/python docs/estudio-banco/aristas.py (crea snap/ junto al script)
import ast, json, os, sqlite3, zlib, collections, random
import jedi
D = os.environ.get("ESTUDIO_TMP") or os.path.dirname(os.path.abspath(__file__)); SNAP = os.path.join(D, "snap")
BANCO_DB = os.environ.get("BANCO_DB", "/home/ama-gi/.prig_bancos/Prig-ac5380d79d/banco.db")
c = sqlite3.connect(f'file:{BANCO_DB}?mode=ro', uri=True)
archivos = {r: zlib.decompress(t).decode("utf-8", "replace") for r, l, t in c.execute("SELECT ruta, lenguaje, contenido FROM archivos") if l == "python" and t}
for _r, _t in archivos.items():  # instantánea del código tal como está en el banco (no el disco actual)
    _p = os.path.join(SNAP, _r); os.makedirs(os.path.dirname(_p), exist_ok=True)
    with open(_p, "w") as _f: _f.write(_t)
prod = [r for r in archivos if "/tests/" not in r]
sim = {}; tipo_de = {}; por_archivo = collections.defaultdict(list)
for ruta, nombre, tipo, ini, fin in c.execute("SELECT ruta, nombre, tipo, ini, fin FROM simbolos"):
    sim[(ruta, ini)] = nombre; tipo_de[(ruta, nombre)] = tipo; por_archivo[ruta].append((ini, fin, nombre))
def simbolo_de(rel, linea, corto):
    """ el símbolo del banco que jedi señala: mismo nombre corto y la línea de jedi dentro de su rango
    (con decoradores, el banco empieza en el decorador y jedi en el def) """
    cands = [(ini, n) for ini, fin, n in por_archivo.get(rel, []) if ini <= linea <= fin and n.split(".")[-1] == corto]
    return max(cands)[1] if cands else sim.get((rel, linea))
canon = lambda n: n[:-9] if n.endswith(".__init__") else n
banco = {}
for ruta, desde, a_ruta, a_nombre, linea, cf in c.execute("SELECT * FROM llamadas"):
    if ruta in prod: banco[(ruta, desde, a_ruta, canon(a_nombre))] = (cf, linea)
proyecto = jedi.Project(path=SNAP, added_sys_path=[os.path.join(SNAP, "backend")])
verdad = {}   # arista -> (lugar, forma, linea)
juzgable = set()   # (ruta, desde, nombre llamado) que jedi resolvió a algo (propio o externo)
def recorrer(nodo, alcance, en_lambda, salida):
    for h in ast.iter_child_nodes(nodo):
        if isinstance(h, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            recorrer(h, f"{alcance}.{h.name}" if alcance else h.name, False, salida)
        elif isinstance(h, ast.Lambda):
            recorrer(h, alcance, True, salida)
        else:
            if isinstance(h, ast.Call): salida.append((h, alcance, en_lambda))
            recorrer(h, alcance, en_lambda, salida)
for ruta in prod:
    texto = archivos[ruta]
    try: arbol = ast.parse(texto)
    except SyntaxError: continue
    llamadas = []; recorrer(arbol, "", False, llamadas)
    script = jedi.Script(texto, path=os.path.join(SNAP, ruta), project=proyecto)
    for n, alcance, en_lambda in llamadas:
        f = n.func
        if isinstance(f, ast.Name): linea, col, nombre, forma = f.lineno, f.col_offset, f.id, "nombre()"
        elif isinstance(f, ast.Attribute):
            linea, col, nombre = f.end_lineno, f.end_col_offset - len(f.attr), f.attr
            forma = "self.x()" if isinstance(f.value, ast.Name) and f.value.id in ("self", "cls") else "obj.x()"
        else: continue
        # el banco atribuye la llamada al método/función que la contiene; una clase no llama (su cuerpo es de módulo)
        partes = alcance.split(".") if alcance else []
        while partes and tipo_de.get((ruta, ".".join(partes))) == "clase": partes.pop()
        desde = ".".join(partes) or "<módulo>"
        lugar = "módulo" if desde == "<módulo>" else ("lambda" if en_lambda else "normal")
        try: defs = script.goto(linea, col, follow_imports=True)
        except Exception: defs = []
        if defs: juzgable.add((ruta, desde, nombre))
        for d in defs:
            mp = str(d.module_path or "")
            if mp.startswith(SNAP):
                nm = simbolo_de(os.path.relpath(mp, SNAP), d.line, d.name)
                if nm:
                    k = (ruta, desde, os.path.relpath(mp, SNAP), canon(nm))
                    if k not in verdad or lugar == "normal": verdad[k] = (lugar, forma, linea)
res = collections.Counter(); ej = collections.defaultdict(list)
def nota(cat, x):
    res[cat] += 1
    if len(ej[cat]) < 300: ej[cat].append(x)
for k, (cf, linea) in banco.items():
    if k in verdad: nota(f"banco|{cf}|confirmada", k)
    else:
        corto = k[3].split(".")[-1]
        nota(f"banco|{cf}|{'jedi resolvió otra cosa' if (k[0], k[1], corto) in juzgable else 'jedi no resolvió'}", (k, linea))
for k, (lugar, forma, linea) in verdad.items():
    if k not in banco: nota(f"falta|{lugar}|{forma}|{tipo_de.get((k[2], k[3]), '?')}", (k, linea))
json.dump({"conteos": dict(res), "ejemplos": ej}, open(os.path.join(D, "aristas.json"), "w"), ensure_ascii=False, default=str)
print("aristas banco", len(banco), "aristas jedi", len(verdad), "(normal:", sum(1 for v in verdad.values() if v[0]=="normal"), ")")
for k, v in sorted(res.items()): print(f"{v:6}  {k}")
