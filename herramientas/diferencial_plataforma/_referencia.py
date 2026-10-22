"""La versión de Python puro de los módulos de la plataforma (el commit REFERENCIA, antes de pasar a Rust), para
comparar con la de ahora: cada módulo se importa como `<nombre>_viejo` (`feature_flags_viejo`,
`perfiles_config_viejo`, ...). Se extraen con git archive en una carpeta temporal que se borra al salir; `TMP` es una
carpeta temporal para los archivos de las pruebas. Importar este módulo antes que nada.
"""
import atexit
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

REFERENCIA = "db6ea4a"      # el último commit con la plataforma (F2) en Python
PRIG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULOS = ["feature_flags", "perfiles_config", "file_manager", "ide_servicios", "explorador", "runner",
           "kernel_session", "inicio", "ollama_opciones", "ollama_gestion", "buscador_modelos"]

_base = tempfile.mkdtemp(prefix="prig-diferencial-plataforma-")
atexit.register(shutil.rmtree, _base, True)
TMP = os.path.join(_base, "tmp")
os.makedirs(TMP)

# Otros archivos de la referencia (rutas dentro de backend/), para viejo(nombre, ruta)
OTROS = ["ai_engine/motor_moe.py", "ai_engine/ai_engine_class.py", "ai_engine/web_search_engine.py",
         "ai_engine/reasoning_engine.py", "ai_engine/model_router.py", "ai_engine/__init__.py",
         "indice_semantico.py", "sondeo_libro.py", "referencias_ml.py", "referencias_dp.py",
         "desafios/__init__.py", "desafios/almacen.py", "desafios/ejecucion.py"]

_archivo = subprocess.run(["git", "-C", PRIG, "archive", REFERENCIA] + [f"backend/{m}.py" for m in MODULOS]
                          + [f"backend/{o}" for o in OTROS],
                          check=True, capture_output=True).stdout
subprocess.run(["tar", "-x", "-C", _base], input=_archivo, check=True)
sys.path.insert(0, os.path.join(PRIG, "backend"))


def viejo(nombre, ruta=None):
    """ El módulo de la referencia, importado como `<nombre>_viejo` (`ruta`: dentro de backend/, si no es
    `<nombre>.py`) """
    clave = f"{nombre}_viejo"
    if clave not in sys.modules:
        spec = importlib.util.spec_from_file_location(clave, os.path.join(_base, "backend", ruta or f"{nombre}.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[clave] = mod
        spec.loader.exec_module(mod)
    return sys.modules[clave]
