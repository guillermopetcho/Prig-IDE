"""
Ficha de un modelo: lo que hay que saber de él para decidir dónde y cómo cargarlo.

La etiqueta del nombre no sirve para eso. "qwen3:14b-q4_k_m" no dice cuántas capas
tiene, cuánta caché KV gasta por token ni si es una mezcla de expertos, y esas tres
cosas cambian el veredicto por completo. Medido en una RTX 4050 de 6 GB:

    qwen3:14b       denso, 48 % en GPU                     6,3 tok/s
    qwen3:30b-a3b   MoE, solo el 25 % en GPU, 3 B activos  22-28 tok/s

El de 30B va cuatro veces más rápido que el de 14B porque por cada token solo lee
8 de sus 128 expertos. Sin leer la cabecera, cualquier calculadora habría dicho lo
contrario.

La ficha sale de tres sitios, de más a menos fiable:

  1. Ollama, si el modelo está instalado (/api/show trae los metadatos y las
     capacidades declaradas, como "thinking").
  2. El registro, leyendo solo la cabecera GGUF por rangos: unos megas de un blob
     de gigas, sin descargar el modelo.
  3. El catálogo de Prig, como último recurso y marcada como estimada.

Todo está en Rust (backend-rust/crates/prig-recursos, ficha.rs), también las peticiones a Ollama y al
registro y la caché de fichas (~/.prig_recursos_fichas.json).
"""

import os
from typing import Any, Dict, List, Optional

OLLAMA = os.environ.get("PRIG_OLLAMA_URL", "http://localhost:11434")
CACHE = os.path.expanduser("~/.prig_recursos_fichas.json")


def _rs():
    from nativo_rust import rust
    return rust().ficha


# Bytes por elemento de la caché KV según su tipo
BYTES_KV = _rs().BYTES_KV
REGISTRO = _rs().REGISTRO


# ===========================================================================
# Construcción de la ficha a partir de metadatos
# ===========================================================================

def desde_metadatos(meta: Dict[str, Any], nombre: str, bytes_peso: int,
                    capacidades: Optional[List[str]] = None,
                    plantilla: str = "", origen: str = "ollama",
                    cuantizacion: str = "") -> Dict[str, Any]:
    """ La ficha a partir de los metadatos GGUF: capas, caché KV por token, expertos y parámetros activos,
    si piensa, si es un embebedor """
    return _rs().desde_metadatos(meta, nombre, bytes_peso, capacidades, plantilla, origen, cuantizacion)


def kv_bytes(ficha: Dict[str, Any], contexto: int, paralelo: int = 1,
             tipo: str = "f16") -> int:
    """ Caché KV para un contexto y un número de peticiones simultáneas.

    Cada ranura en paralelo reserva su propia caché: dos ranuras de 4096 ocupan
    lo mismo que una de 8192. Por eso subir el paralelo no es gratis.
    """
    return _rs().kv_bytes(ficha, contexto, paralelo, tipo)


# ===========================================================================
# Fuentes (las peticiones también van en Rust)
# ===========================================================================

def instalados() -> Dict[str, Dict[str, Any]]:
    """ Nombre → {tamaño, digest, detalles} de lo que Ollama tiene descargado """
    return _rs().instalados(OLLAMA)


def desde_ollama(nombre: str) -> Dict[str, Any]:
    return _rs().desde_ollama(OLLAMA, nombre)


# Registros compatibles con Ollama (verificado: los tres sirven manifiestos y blobs)
REGISTROS_EXTERNOS = _rs().REGISTROS_EXTERNOS


def registro_de(nombre: str):
    """ (url del registro, repo, etiqueta) para cualquier nombre que Ollama descarga:
    "qwen3:8b", "usuario/modelo:tag", "hf.co/org/repo:Q4_K_M", "modelscope.cn/org/repo:q4_k_m" """
    return _rs().registro_de(nombre)


def _separar(nombre: str):
    """ "qwen3:8b" → ("library/qwen3", "8b"); "usuario/modelo:tag" también vale """
    _, repo, tag = registro_de(nombre)
    return repo, tag


def desde_registro(nombre: str) -> Dict[str, Any]:
    """ Ficha de un modelo SIN descargarlo: solo la cabecera GGUF por rangos.

    Se guarda en caché por el digest de la capa: un blob con el mismo digest es el
    mismo modelo, así que no hay que volver a leerlo nunca.
    """
    return _rs().desde_registro(nombre, CACHE)


def desde_catalogo(nombre: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """ Último recurso, sin red: estimada a partir del tamaño del catálogo.

    La caché KV se estima por lo alto (20 KB por cada mil millones de parámetros)
    para que un modelo desconocido nunca salga como "cabe" cuando no cabe.
    """
    return _rs().desde_catalogo(nombre, info)


def obtener(nombre: str, catalogo: Optional[Dict[str, Any]] = None,
            red: bool = True) -> Dict[str, Any]:
    """ La mejor ficha disponible, probando las fuentes en orden de fiabilidad """
    return _rs().obtener(OLLAMA, nombre, catalogo, red, CACHE)
