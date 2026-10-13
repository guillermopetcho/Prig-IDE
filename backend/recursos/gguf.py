"""
Lector mínimo de la cabecera GGUF.

Un GGUF empieza por sus metadatos: arquitectura, número de capas, cabezas de
atención, contexto máximo, expertos. Con eso se calcula exactamente cuánta caché KV
ocupará el modelo, que es la parte que decide si cabe o no en la GPU. La etiqueta
"8B" no basta: Qwen2.5-7B ocupa 56 KB de caché por token y Qwen3-14B, 160 KB.

Solo se leen los metadatos, nunca los tensores. El registro de Ollama sirve los
blobs por rangos, así que de un modelo de 5 GB basta con bajar sus primeros megas
para saber todo lo que la calculadora necesita, antes de decidir si merece la pena
descargarlo.
La lectura está en Rust (backend-rust/crates/prig-recursos, gguf.rs).
"""

from typing import Any, Callable, Dict


def _rs():
    from nativo_rust import rust
    return rust().gguf


MAGIA = b"GGUF"
# Arrays largos que no aportan nada a la calculadora: el vocabulario y las fusiones del tokenizador
NO_GUARDAR = tuple(_rs().NO_GUARDAR)
# El búfer se acabó antes que la cabecera: hay que pedir más
FaltanBytes = _rs().FaltanBytes


def leer_metadatos(datos: bytes) -> Dict[str, Any]:
    """ Metadatos de una cabecera GGUF completa. Lanza FaltanBytes si no llega. """
    return _rs().leer_metadatos(datos)


def leer_con_rangos(pedir: Callable[[int, int], bytes],
                    inicial: int = 256 * 1024,
                    maximo: int = 48 * 1024 * 1024) -> Dict[str, Any]:
    """ Lee la cabecera pidiendo bytes por rangos, cada vez más, hasta que llega.

    `pedir(desde, hasta)` devuelve los bytes de ese rango. Se empieza por poco y se
    dobla: un modelo con vocabulario pequeño se resuelve en 256 KB y uno de Qwen
    necesita unos 8 MB. El tope evita descargar el modelo entero si algo va mal.
    """
    return _rs().leer_con_rangos(pedir, inicial, maximo)
