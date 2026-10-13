"""E2 (d): hechos del banco contra una extracción independiente por AST (endpoints y variables de entorno)"""
import ast, os, re, sqlite3, zlib, collections, json
c = sqlite3.connect('file:/home/ama-gi/.prig_bancos/Prig-ac5380d79d/banco.db?mode=ro', uri=True)
archivos = {r: zlib.decompress(t).decode("utf-8", "replace") for r, l, t in c.execute("SELECT ruta, lenguaje, contenido FROM archivos") if t}
py = {r: t for r, t in archivos.items() if r.endswith(".py") and "/tests/" not in r}
canon = lambda p: (re.sub(r"\{[^}]*\}", "*", p.split("?")[0]).rstrip("/") or "/")
# --- endpoints: decoradores @X.get/post/... y prefijos de APIRouter / include_router
METODOS = {"get", "post", "put", "delete", "patch", "websocket"}
verdad = set(); prefijo_router = {}
for ruta, t in py.items():
    try: arbol = ast.parse(t)
    except SyntaxError: continue
    for n in ast.walk(arbol):
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "APIRouter":
            for kw in n.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant): prefijo_router[ruta] = kw.value.value
    for n in ast.walk(arbol):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in METODOS and d.args and isinstance(d.args[0], ast.Constant):
                    receptor = ast.unparse(d.func.value)
                    pref = prefijo_router.get(ruta, "") if receptor != "app" else ""
                    verdad.add((f"{d.func.attr.upper()} {canon(pref + d.args[0].value)}", ruta))
banco = {(o, ruta) for o, ruta in c.execute("SELECT o, ruta FROM hechos WHERE r='expone'")}
print("endpoints: verdad", len(verdad), "banco", len(banco), "coinciden", len(verdad & banco))
print("  solo banco:", sorted(banco - verdad)[:8]); print("  solo verdad:", sorted(verdad - banco)[:8])
print("  prefijos de router:", prefijo_router)
# --- variables de entorno
env_v = set()
for ruta, t in py.items():
    try: arbol = ast.parse(t)
    except SyntaxError: continue
    for n in ast.walk(arbol):
        nombre = None
        if isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
            f = ast.unparse(n.func)
            if f in ("os.environ.get", "os.getenv", "environ.get", "getenv", "os.environ.setdefault", "os.environ.pop"): nombre = n.args[0].value
        elif isinstance(n, ast.Subscript) and ast.unparse(n.value) in ("os.environ", "environ") and isinstance(n.slice, ast.Constant):
            nombre = n.slice.value
        if nombre: env_v.add((nombre, ruta))
env_b = {(o, ruta) for o, ruta in c.execute("SELECT o, ruta FROM hechos WHERE r='lee_entorno'")}
env_b_py = {x for x in env_b if x[1].endswith(".py") and "/tests/" not in x[1]}
print("entorno (py, sin tests): verdad", len(env_v), "banco", len(env_b_py), "coinciden", len(env_v & env_b_py))
print("  solo banco:", sorted(env_b_py - env_v)[:10]); print("  solo verdad:", sorted(env_v - env_b_py)[:10])
