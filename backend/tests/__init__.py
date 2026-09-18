import os

# Importar app.py crea el gobernador térmico real. Sin esto arrancaría el controlador del
# motor suave, que escribe en el archivo de control compartido con un Prig abierto y
# en el de las pruebas del motor (recursos/termico.py).
os.environ["PRIG_SIN_MOTOR_SUAVE"] = "1"
