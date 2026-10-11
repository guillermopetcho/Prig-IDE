"""Copia congelada del SISTEMA bajo prueba (el backend de Prig), para medir sin que la edición diaria lo cambie.

El 09/10, al retomar E7, el backend ya no era el del plan del repositorio externo (huella 375d999bef8b8b11 del 03/10):
entre tanto entraron perfiles_config.py, audio_monitor.py, llm_director.py y endpoints nuevos en app.py. El estado del
03/10 no quedó guardado en ningún lado (ni en git), así que no se puede reconstruir: se congela el estado ACTUAL y lo
que falta (externo completo, E8, E9) se mide con él.

Se copian backend/ (sin __pycache__) y main.py; el resto del repositorio (lib/ con el motor, frontend/, docs/, data/…) se
enlaza: el motor se busca relativo a la raíz (motor_moe.RAIZ) y la app sirve frontend/. Los lotes y las sondas usan la
copia con PRIG_SISTEMA=<carpeta> (lote.py, sonda.py); su huella queda en el plan y se verifica en cada lote.

Uso: .venv/bin/python docs/estudio-banco/congelar_sistema.py   → imprime la carpeta y la huella
"""
import glob, hashlib, os, shutil, sys

REAL = "/home/ama-gi/Prig"
BASE = os.path.expanduser("~/.cache/prig-estudio/sistema")


def huella(raiz):
    """ La misma que lote.huella_sistema: backend sin tests ni __pycache__, y main.py """
    archivos = sorted(glob.glob(os.path.join(raiz, "backend/**/*.py"), recursive=True) + [os.path.join(raiz, "main.py")])
    h = hashlib.sha1()
    for a in archivos:
        if "/tests/" in a or "__pycache__" in a:
            continue
        h.update(os.path.relpath(a, raiz).encode()); h.update(open(a, "rb").read())
    return h.hexdigest()[:16]


h = huella(REAL)
destino = os.path.join(BASE, h)
if os.path.exists(destino):
    print(f"ya existe: {destino} (huella {h})"); sys.exit(0)
os.makedirs(destino)
shutil.copytree(os.path.join(REAL, "backend"), os.path.join(destino, "backend"),
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
shutil.copy2(os.path.join(REAL, "main.py"), os.path.join(destino, "main.py"))
for nombre in os.listdir(REAL):
    if nombre in ("backend", "main.py", ".git", "__pycache__") or nombre.startswith(".venv"):
        continue
    os.symlink(os.path.join(REAL, nombre), os.path.join(destino, nombre))
assert huella(destino) == h, "la copia no reproduce la huella"
print(f"sistema congelado: {destino} (huella {h})")
