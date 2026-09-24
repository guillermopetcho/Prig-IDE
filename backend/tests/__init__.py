import atexit
import os
import shutil
import tempfile

# Importar app.py crea el gobernador térmico real. Sin esto arrancaría el controlador del
# motor suave, que escribe en el archivo de control compartido con un Prig abierto y
# en el de las pruebas del motor (recursos/termico.py).
os.environ["PRIG_SIN_MOTOR_SUAVE"] = "1"

# Una carpeta personal temporal para TODA la suite, fijada antes de importar nada:
#   · ninguna prueba puede tocar los ~/.prig_* reales del usuario;
#   · todas ven la MISMA carpeta. Antes cada módulo cambiaba HOME al importarse, y como
#     app.py fija la carpeta personal al importarse (Explorador), las pruebas que corrían
#     después miraban una carpeta distinta de la que app conocía.
# Este paquete se importa dos veces en la misma suite («backend.tests» desde la raíz y «tests»
# cuando una prueba añade backend/ al path): la carpeta se elige una sola vez.
if not os.environ.get("PRIG_PRUEBAS_HOME"):
    _HOME_PRUEBAS = tempfile.mkdtemp(prefix="prig_test_home_")
    os.environ["PRIG_PRUEBAS_HOME"] = _HOME_PRUEBAS
    atexit.register(shutil.rmtree, _HOME_PRUEBAS, True)
os.environ["HOME"] = os.environ["PRIG_PRUEBAS_HOME"]
os.environ["PRIG_BOOKS_DIR"] = os.path.join(os.environ["PRIG_PRUEBAS_HOME"], ".prig_books")
