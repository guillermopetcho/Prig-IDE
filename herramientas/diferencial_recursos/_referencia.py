"""La versión de Python puro de backend/recursos y de backend/audio_monitor.py (el commit REFERENCIA, antes de pasar
a Rust), para comparar con la de ahora: `recursos_viejo` (paquete) y `audio_viejo` (módulo). Se extraen con git
archive en una carpeta temporal que se borra al salir; `TMP` es una carpeta temporal para los archivos de las
pruebas. Importar este módulo antes que nada.
"""
import atexit
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

REFERENCIA = "9d9bb98"      # el último commit con todo backend/recursos en Python
PRIG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_base = tempfile.mkdtemp(prefix="prig-diferencial-")
atexit.register(shutil.rmtree, _base, True)
TMP = os.path.join(_base, "tmp")
os.makedirs(TMP)

_archivo = subprocess.run(["git", "-C", PRIG, "archive", REFERENCIA, "backend/recursos", "backend/audio_monitor.py"],
                          check=True, capture_output=True).stdout
subprocess.run(["tar", "-x", "-C", _base], input=_archivo, check=True)
shutil.move(os.path.join(_base, "backend", "recursos"), os.path.join(_base, "recursos_viejo"))
sys.path.insert(0, _base)
sys.path.insert(0, os.path.join(PRIG, "backend"))

_spec = importlib.util.spec_from_file_location("audio_viejo", os.path.join(_base, "backend", "audio_monitor.py"))
audio_viejo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audio_viejo)
