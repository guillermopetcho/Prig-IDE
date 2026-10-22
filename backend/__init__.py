# El backend importa sus módulos por su nombre (`from nativo_rust import rust`, `from knowledge_base import ...`).
# Importado como paquete (`backend.knowledge...`, como hacen las pruebas de knowledge), su carpeta también tiene que
# estar en la ruta de módulos. Va al final: no tapa nada.
import os as _os
import sys as _sys

_aqui = _os.path.dirname(_os.path.abspath(__file__))
if _aqui not in _sys.path:
    _sys.path.append(_aqui)
