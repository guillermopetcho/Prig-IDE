"""
Todo lo configurable de los modelos de Ollama, y en qué capa lo decide el usuario.

SOLO LO QUE FUNCIONA. Cada opción de este catálogo se probó contra el Ollama de Prig
(0.34.1, motor llama-server) midiendo su EFECTO, no solo que la API la acepte:
salida distinta con la misma semilla, memoria en /api/ps, argumentos con los que
arranca el motor, velocidad o respuesta del servidor. Las que dan error o se
aceptan sin cambiar nada están en EXCLUIDAS con el motivo, y nunca se envían: una
opción que no hace nada es un interruptor falso en la pantalla.

CAPAS. Un valor puede fijarse en cuatro sitios, de menos a más prioridad:

    global            todos los modelos
    modelo            un modelo concreto (p. ej. qwen3:14b)
    uso               una tarea (tutor, flujos, extracción, revisión, autocompletado)
    modelo_uso        ese modelo en esa tarea

Lo que no se fija en ninguna capa NO se envía, y Ollama usa lo que trae el modelo en
su Modelfile. Antes Prig mandaba temperatura 0.3, top_k 40, top_p 0.9 y
repeat_penalty 1.1 a todos los modelos, y Qwen3 (que pide 0.6 / 20 / 0.95 / 1.0)
funcionaba peor de lo previsto.

Por encima de las capas solo están las opciones que una tarea exige por diseño
(la calibración, el canario de extracción, un paso JSON de un flujo): las pone quien
llama y mandan.

El catálogo, la validación y el almacén de capas están en Rust (backend-rust/crates/prig-modelos, opciones.rs; el
catálogo en opciones_catalogo.json): el archivo sale byte a byte igual que cuando lo escribía Python.
"""

import os
import threading
from typing import Any, Dict, List, Optional, Tuple


def _rs():
    from nativo_rust import rust
    return rust().opciones


_BASE = _rs().base()
CAPAS = tuple(_BASE["CAPAS"])
USOS: Dict[str, str] = _BASE["USOS"]
# Opciones del motor (van en "options"); `prueba`: cómo se verificó en esta máquina (se enseña al usuario)
OPCIONES: List[Dict[str, Any]] = _BASE["OPCIONES"]
# Campos de la petición (fuera de "options")
CAMPOS: List[Dict[str, Any]] = _BASE["CAMPOS"]
# Solo en "Probar" y en las llamadas que lo necesitan, no como ajuste guardado
CAMPOS_PRUEBA: Dict[str, str] = _BASE["CAMPOS_PRUEBA"]
# Lo que NO se añade, y por qué (medido en esta máquina)
EXCLUIDAS: Dict[str, Dict[str, str]] = _BASE["EXCLUIDAS"]
EXCLUIDAS_SERVIDOR: Dict[str, Dict[str, str]] = _BASE["EXCLUIDAS_SERVIDOR"]
EXCLUIDAS_GESTION: Dict[str, Dict[str, str]] = _BASE["EXCLUIDAS_GESTION"]
PLANTILLAS: Dict[str, Dict[str, Any]] = _BASE["PLANTILLAS"]

ErrorConfig = _rs().ErrorConfig


def validar(valores: Dict[str, Any]) -> Dict[str, Any]:
    """ Tipos y rangos. Una clave excluida o desconocida es un error, no se ignora. """
    return _rs().validar(valores)


def separar(valores: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """ (options del motor, campos de la petición) """
    return _rs().separar(valores)


def limpiar_para_ollama(opciones: Dict[str, Any]) -> Dict[str, Any]:
    """ Quita lo que Ollama rechaza o ignora, venga de donde venga (configuraciones
    viejas, llamadas antiguas). typical_p rompería la petición con un 400. """
    return _rs().limpiar_para_ollama(opciones)


# ===========================================================================
# Almacén de capas
# ===========================================================================

def ruta_por_defecto() -> str:
    return os.environ.get("PRIG_MODELOS_ARCHIVO") or os.path.expanduser("~/.prig_modelos.json")


def ConfigModelos(ruta: Optional[str] = None):
    """ El almacén de capas de un archivo. Métodos: capa, fijar, embeddings, fijar_embeddings, renombrar_modelo,
    resolver, todo; y ruta. """
    return _rs().ConfigModelos(ruta or ruta_por_defecto())


_config = None
_config_cerrojo = threading.Lock()


def config():
    global _config
    with _config_cerrojo:
        if _config is None or _config.ruta != ruta_por_defecto():
            _config = ConfigModelos()
        return _config


def catalogo(num_gpus: int = 1) -> Dict[str, Any]:
    return _rs().catalogo(num_gpus)
