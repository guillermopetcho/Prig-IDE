"""Diferencial de runner.py y kernel_session.py: la versión de Python puro (REFERENCIA) contra la de ahora (Rust
por prig_nativo). Los mismos scripts (Python, C, C++ con errores de compilación, bash, JS si hay node, cuadernos,
salida con \\r\\n o que no es UTF-8, códigos de salida, tiempo límite) y las mismas celdas tienen que dar lo mismo.
`elapsed` y las rutas de los temporales se comparan sin su valor.

    .venv/bin/python herramientas/diferencial_plataforma/ejecucion.py [semilla] [vueltas]
"""
import json, os, random, re, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import TMP, viejo  # noqa: E402
import runner as rn  # noqa: E402
viejo("kernel_session")
sys.modules["kernel_session"] = sys.modules["kernel_session_viejo"]
rv = viejo("runner")
sys.modules.pop("kernel_session")
import kernel_session  # noqa: E402,F401

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 40
R = random.Random(semilla)
fallos, cuentas = [], {}

SCRIPTS = {
    "hola.py": "print('hola')\nprint('ñ 😀')",
    "error.py": "import sys\nprint('antes')\nsys.stderr.write('mal\\n')\nsys.exit(3)",
    "excepcion.py": "raise ValueError('x')",
    "crlf.py": "import sys\nsys.stdout.write('a\\r\\nb\\rc\\n')",
    "bytes.py": "import sys\nsys.stdout.buffer.write(b'ok\\xff\\xfe')",
    "bytes_err.py": "import sys\nsys.stderr.buffer.write(b'\\xe2\\x82')",
    "lento.py": "import time\ntime.sleep(5)\nprint('fin')",
    "senal.py": "import os, signal\nos.kill(os.getpid(), signal.SIGTERM)",
    "cwd.py": "import os\nprint(os.path.basename(os.getcwd()))",
    "ok.c": "#include <stdio.h>\nint main(){printf(\"c %d\\n\", 7); return 0;}",
    "mal.c": "int main(){ return x; }",
    "ok.cpp": "#include <iostream>\nint main(){std::cout << \"cpp\" << std::endl; return 2;}",
    "mal.cpp": "int main(){ undefined_fn(); }",
    "s.sh": "echo bash $((2+3)); exit 1",
    "otro.txt": "print('como python')",
    "nb.ipynb": json.dumps({"cells": [{"cell_type": "code", "source": ["x = 2\n", "print(x * 3)"]},
                                      {"cell_type": "markdown", "source": "# t"}, {"cell_type": "code", "source": "print('dos')"}]}),
    "roto.ipynb": "{no es json",
    "lista.ipynb": "[1, 2]",
}
CELDAS = ["x = 41", "x + 1", "print(x)", "import sys; sys.stderr.write('e')", "raise KeyError('k')", "1/0", "def f(:", "None",
          "y = [i for i in range(3)]; y", "import time; time.sleep(3)", "exit()", "'ñ'", ""]


def limpio(r):
    t = json.dumps(r, ensure_ascii=False, sort_keys=False)
    t = re.sub(r'"elapsed": [0-9.]+', '"elapsed": X', t)
    t = re.sub(r"/tmp/tmp[a-z0-9_]{8}\.py", "<tmp.py>", t)
    t = re.sub(r"/tmp/prig_bin_[a-z0-9_]{8}", "<bin>", t)
    t = re.sub(r"/tmp/prig_kernel_[a-z0-9_]{8}\.py", "<driver>", t)
    t = re.sub(r"/tmp/cc[A-Za-z0-9]+\.o", "<obj>", t)
    return t


def ejecutar(f):
    try:
        return ("ok", limpio(f()))
    except Exception as e:
        return ("error", type(e).__name__, str(e))


def comparar(nombre, a, b, contexto):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 12:
        fallos.append({"prueba": nombre, "contexto": contexto, "viejo": str(a)[:1500], "nuevo": str(b)[:1500]})


carpeta = os.path.join(TMP, "proyecto")
os.makedirs(carpeta)
for n, t in SCRIPTS.items():
    with open(os.path.join(carpeta, n), "w") as f: f.write(t)
viejo_r, nuevo_r = rv.CodeRunner(timeout_seconds=3), rn.CodeRunner(timeout_seconds=3)

for _ in range(N):
    n = R.choice(list(SCRIPTS) + ["no_existe.py"])
    cwd = R.choice([None, TMP, "/no/existe"])
    timeout = R.choice([None, 2, 0])
    ruta = os.path.join(carpeta, n) if R.random() < 0.8 else os.path.relpath(os.path.join(carpeta, n))
    a = ejecutar(lambda: viejo_r.run_file(ruta, cwd=cwd, timeout=timeout))
    b = ejecutar(lambda: nuevo_r.run_file(ruta, cwd=cwd, timeout=timeout))
    comparar("run_file", a, b, (n, cwd, timeout))

for _ in range(N):
    sesion = R.choice([None, os.path.join(carpeta, "nb.ipynb"), "otro.ipynb"])
    cwd = R.choice([None, carpeta])
    pasos = [R.choice(CELDAS) for _ in range(R.randint(1, 4))]
    res = []
    for r in (viejo_r, nuevo_r):
        r.reset_session(sesion)
        res.append([ejecutar(lambda: r.run_cell_code(c, cwd=cwd, session_id=sesion, timeout=2)) for c in pasos]
                   + [ejecutar(lambda: r.reset_session(sesion))])
    comparar("celdas", res[0], res[1], (sesion, cwd, pasos))

viejo_r.shutdown()
nuevo_r.shutdown()
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
