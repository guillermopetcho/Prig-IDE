"""
Banderas de funcionalidad.

Con un solo desarrollador y un proyecto de esta superficie, la alternativa son ramas
eternas: una función a medias o se termina o bloquea el resto. Con banderas se puede
integrar trabajo incompleto sin que aparezca en el flujo principal.

Prioridad: variable de entorno > archivo (~/.prig_flags.json) > valor por defecto.
La variable de entorno permite probar algo puntualmente sin tocar la configuración
guardada:  PRIG_FLAG_EXERCISES_UI=1 ./run.sh

El estado y la lógica están en Rust (backend-rust/crates/prig-plataforma, banderas.rs): el archivo sale byte a
byte igual que cuando lo escribía Python.
"""

import os
from typing import Dict, Any

FLAGS_PATH = os.path.expanduser("~/.prig_flags.json")


def _rs():
    from nativo_rust import rust
    return rust().banderas


# Toda bandera nueva se declara en Rust (banderas.rs, BANDERAS) con su valor por defecto y para qué sirve.
DEFAULT_FLAGS: Dict[str, Dict[str, Any]] = _rs().DEFAULT_FLAGS


def FeatureFlags(path: str = FLAGS_PATH):
    """ Las banderas de un archivo. Métodos: is_enabled(nombre), set(nombre, valor) (KeyError si no existe),
    reset(nombre), all(); y path. """
    return _rs().FeatureFlags(path)
