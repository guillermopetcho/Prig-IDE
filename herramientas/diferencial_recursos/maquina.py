"""El detector en esta máquina: la radiografía de Python puro (commit de referencia) contra la de Rust (la huella
tiene que ser idéntica: con ella se guarda la calibración) y la huella con 3000 entradas al azar. Solo lee.
Uso: .venv/bin/python maquina.py"""
import json, os, random, sys
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from recursos_viejo import detector as dv  # noqa: E402
from recursos import detector as dn  # noqa: E402

# El viejo calcula la carpeta de Prig desde su propio archivo (en la carpeta temporal): se le da la de verdad
_abs = os.path.abspath
with mock.patch.object(dv.os.path, "abspath", lambda p: _abs(p).replace(os.path.dirname(dv.__file__), os.path.join(_referencia.PRIG, "backend", "recursos"))):
    a = dv.radiografia(medir_ram=False)
b = dn.radiografia(medir_ram=False)
print("huella:", a["huella"], b["huella"], "IGUAL" if a["huella"] == b["huella"] else "DISTINTA")
VOLATIL = {"ram_disponible", "swap_usada", "vram_usada_mb", "vram_libre_mb", "temperatura_c", "consumo_w", "uso_pct", "libre", "tomada"}


def comparar(x, y, ruta=""):
    if isinstance(x, dict) and isinstance(y, dict):
        if list(x) != list(y):
            print("  claves distintas en", ruta)
        for k in x:
            if k in y:
                comparar(x[k], y[k], ruta + "." + k)
    elif isinstance(x, list) and isinstance(y, list):
        for i, (p, q) in enumerate(zip(x, y)):
            comparar(p, q, f"{ruta}[{i}]")
    elif ruta.rsplit(".", 1)[-1] not in VOLATIL and (x != y or type(x) != type(y)):
        print("  DISTINTO", ruta, repr(x), repr(y))


comparar(a, b)
R = random.Random(3)
dif = 0
for _ in range(3000):
    d = {}
    if R.random() < 0.9:
        d["gpus"] = R.choice([[], [{}], [{"nombre": R.choice(["RTX", "ñ"]), "vram_total_mb": R.choice([None, 0, 6141, 6141.5, 6142.5, 1e5]),
                                        "driver": R.choice(["580", 5, None])}]])
    if R.random() < 0.9:
        d["cpu"] = {"modelo": R.choice(["i5", "", "ñ"])} if R.random() < 0.9 else {}
    if R.random() < 0.9:
        d["memoria"] = {"ram_total": R.choice([None, 0, 66965528576, 17179869184, 8.5e9, 1073741824 * 2.5])}
    if R.random() < 0.9:
        d["ollama"] = R.choice([{}, {"version": None}, {"version": "0.12.3"}, {"version": 12}])
    if json.dumps(dv.huella(d)) != json.dumps(dn.huella(d)):
        dif += 1
print("huellas al azar distintas:", dif, "de 3000")
