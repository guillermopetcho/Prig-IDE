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
"""

import struct
from typing import Any, Callable, Dict, Optional

MAGIA = b"GGUF"

# Tipos de valor de la especificación GGUF
_ESCALARES = {
    0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2),
    4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1),
    10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8),
}
TIPO_CADENA = 8
TIPO_ARRAY = 9

# Arrays largos que no aportan nada a la calculadora: el vocabulario y las fusiones
# del tokenizador son cientos de miles de entradas. Se recorren (hay que hacerlo para
# llegar a lo que viene detrás) pero no se guardan.
NO_GUARDAR = ("tokenizer.ggml.tokens", "tokenizer.ggml.merges",
              "tokenizer.ggml.token_type", "tokenizer.ggml.scores")


class FaltanBytes(Exception):
    """ El búfer se acabó antes que la cabecera: hay que pedir más """


class _Lector:
    def __init__(self, datos: bytes):
        self.d = datos
        self.p = 0

    def _tomar(self, n: int) -> bytes:
        if self.p + n > len(self.d):
            raise FaltanBytes()
        trozo = self.d[self.p:self.p + n]
        self.p += n
        return trozo

    def escalar(self, tipo: int):
        fmt, n = _ESCALARES[tipo]
        return struct.unpack(fmt, self._tomar(n))[0]

    def cadena(self) -> str:
        n = struct.unpack("<Q", self._tomar(8))[0]
        if n > 64 * 1024 * 1024:
            raise ValueError("cadena GGUF imposible: archivo corrupto o no es GGUF")
        return self._tomar(n).decode("utf-8", errors="replace")

    def valor(self, tipo: int, guardar: bool = True):
        if tipo in _ESCALARES:
            return self.escalar(tipo)
        if tipo == TIPO_CADENA:
            return self.cadena()
        if tipo == TIPO_ARRAY:
            sub = struct.unpack("<I", self._tomar(4))[0]
            n = struct.unpack("<Q", self._tomar(8))[0]
            if not guardar:
                # Saltarlo sin construir la lista: el vocabulario de Qwen son
                # 150.000 cadenas y no hace falta ninguna.
                if sub in _ESCALARES:
                    self._tomar(_ESCALARES[sub][1] * n)
                else:
                    for _ in range(n):
                        self.valor(sub, guardar=False)
                return None
            return [self.valor(sub) for _ in range(n)]
        raise ValueError(f"tipo GGUF desconocido: {tipo}")


def leer_metadatos(datos: bytes) -> Dict[str, Any]:
    """ Metadatos de una cabecera GGUF completa. Lanza FaltanBytes si no llega. """
    r = _Lector(datos)
    if r._tomar(4) != MAGIA:
        raise ValueError("no es un archivo GGUF")
    version = struct.unpack("<I", r._tomar(4))[0]
    if version not in (2, 3):
        raise ValueError(f"versión de GGUF no soportada: {version}")
    n_tensores = struct.unpack("<Q", r._tomar(8))[0]
    n_claves = struct.unpack("<Q", r._tomar(8))[0]

    meta: Dict[str, Any] = {"_gguf_version": version, "_tensores": n_tensores}
    for _ in range(n_claves):
        clave = r.cadena()
        tipo = struct.unpack("<I", r._tomar(4))[0]
        guardar = not clave.startswith(NO_GUARDAR)
        valor = r.valor(tipo, guardar=guardar)
        if guardar:
            meta[clave] = valor
    meta["_bytes_cabecera"] = r.p
    return meta


def leer_con_rangos(pedir: Callable[[int, int], bytes],
                    inicial: int = 256 * 1024,
                    maximo: int = 48 * 1024 * 1024) -> Dict[str, Any]:
    """ Lee la cabecera pidiendo bytes por rangos, cada vez más, hasta que llega.

    `pedir(desde, hasta)` devuelve los bytes de ese rango. Se empieza por poco y se
    dobla: un modelo con vocabulario pequeño se resuelve en 256 KB y uno de Qwen
    necesita unos 8 MB. El tope evita descargar el modelo entero si algo va mal.
    """
    tam = inicial
    datos = b""
    while True:
        if len(datos) < tam:
            datos += pedir(len(datos), tam - 1)
        try:
            return leer_metadatos(datos)
        except FaltanBytes:
            if tam >= maximo:
                raise ValueError(f"la cabecera GGUF ocupa más de {maximo // 1024 // 1024} MB")
            tam = min(tam * 2, maximo)
