"""
Radiografía de la máquina: lo que decide qué modelo cabe y a qué velocidad va.

Solo lee, nunca cambia nada, y tarda en torno a un segundo. Lo que mide, y por qué
cada cosa importa:

  · VRAM LIBRE DE VERDAD, no la total. En un portátil con gráficos híbridos el
    escritorio va por la integrada y la dedicada queda casi entera (medido: 15 MiB
    usados en reposo en una RTX 4050); en un sobremesa el escritorio se lleva entre
    300 y 800 MB, que es justo lo que separa "cabe" de "no cabe".
  · NÚCLEOS FÍSICOS, no hilos. La parte del modelo que corre en CPU rinde peor si
    se reparte entre hilos de hyperthreading.
  · RAM DISPONIBLE y SWAP. Un modelo que empieza a paginar a disco no va lento: se
    para. Hay que verlo venir.
  · QUIÉN ARRANCÓ OLLAMA. Las variables del servidor solo se pueden cambiar si el
    proceso es de Prig; si lo gestiona systemd, hay que decírselo al usuario.
  · ALIMENTACIÓN. Con batería no se lanza una extracción de una noche sin avisar.
Todo se lee en Rust (backend-rust/crates/prig-recursos, detector.rs), con las mismas reglas que psutil para
núcleos, memoria y batería. La huella sale idéntica: con ella se guarda la calibración.
"""

import os
import platform
from typing import Any, Dict, List, Optional

OLLAMA = os.environ.get("PRIG_OLLAMA_URL", "http://localhost:11434")
RAIZ_PRIG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rs():
    from nativo_rust import rust
    return rust().detector


# ===========================================================================
# GPU
# ===========================================================================

def gpus_nvidia() -> List[Dict[str, Any]]:
    return _rs().gpus_nvidia()


def gpus_amd() -> List[Dict[str, Any]]:
    return _rs().gpus_amd()


# ===========================================================================
# CPU, memoria, disco, energía
# ===========================================================================

def cpu() -> Dict[str, Any]:
    return _rs().cpu()


def memoria() -> Dict[str, Any]:
    return _rs().memoria()


def ancho_banda_ram(mb: int = 256) -> float:
    """ Velocidad de copia de memoria, en GB/s. Tarda unos 200 ms.

    En la parte del modelo que corre en CPU, los tokens por segundo los limita la
    velocidad a la que se leen los pesos de la RAM, no los núcleos. La medida se usa
    solo como valor previo y la calibración con un modelo de verdad la sustituye.
    """
    return _rs().ancho_banda_ram(mb)


def disco(ruta: Optional[str] = None) -> Dict[str, Any]:
    return _rs().disco(ruta)


def energia() -> Dict[str, Any]:
    """ ¿Portátil? ¿Con batería? Sin batería no hay por qué frenar nada. """
    return _rs().energia()


def sistema() -> Dict[str, Any]:
    return _rs().sistema(platform.python_version(), platform.platform())


# ===========================================================================
# Ollama
# ===========================================================================

def ollama() -> Dict[str, Any]:
    """ Si responde, versión, pid, binario, dueño (prig, systemd, usuario), variables del servidor, modelos
    cargados y ejecutores """
    return _rs().ollama(OLLAMA, RAIZ_PRIG)


# ===========================================================================
# Todo junto
# ===========================================================================

def radiografia(medir_ram: bool = True) -> Dict[str, Any]:
    return _rs().radiografia(medir_ram, platform.python_version(), platform.platform(), OLLAMA, RAIZ_PRIG)


def huella(datos: Dict[str, Any]) -> str:
    """ Identifica la combinación de hardware y software que afecta a las medidas.

    Si cambia (otra GPU, otro driver, otra versión de Ollama, otra RAM), lo que se
    calibró deja de valer y hay que volver a medir.
    """
    return _rs().huella(datos)
