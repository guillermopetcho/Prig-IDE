"""
Gestión de modelos de Ollama: ficha, variantes, copias, importar GGUF, actualizaciones,
modelos cargados y descargas a medias.

Verificado contra Ollama 0.34.1 (ver ollama_opciones.EXCLUIDAS para lo que no entra):
  · /api/show verbose trae licencia, plantilla, Modelfile, parámetros, capacidades,
    model_info y tensores.
  · /api/create con from + system + parameters + messages + license crea la variante,
    y responde con esas instrucciones ("Arr!" con un system de pirata).
    `template` al crear se ACEPTA pero no se guarda: no se ofrece. `quantize` da error
    con modelos GGUF ("only supported for safetensors imports"): tampoco.
  · /api/copy y /api/delete.
  · Importar: HEAD/POST /api/blobs/<digest> + /api/create con `files`.
  · Actualizaciones: el digest de /api/tags es el sha256 del manifiesto del registro.

Todo está en Rust (backend-rust/crates/prig-modelos, gestion.rs): las peticiones no retienen el GIL y los errores
de red llegan como las excepciones de `requests`. Los flujos largos (crear una variante, importar un GGUF) son
iteradores que se consumen como los generadores de antes: nada se comprueba ni se pide hasta el primer paso.
"""

from typing import Any, Callable, Dict, Generator, List, Optional


def _rs():
    from nativo_rust import rust
    return rust().gestion


REGISTRO = _rs().REGISTRO

ErrorGestion = _rs().ErrorGestion


def _nombre(nombre: str) -> str:
    return _rs().nombre(nombre or "")


def _parametros(texto: str) -> Dict[str, Any]:
    """ "temperature 0.6\\nstop \\"<|im_end|>\\"" → {"temperature": "0.6", "stop": [...]} """
    return _rs().parametros(texto)


class GestorModelos:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base = base_url.rstrip("/")

    # ------------------------------------------------------------ listado y ficha
    def instalados(self) -> List[Dict[str, Any]]:
        return _rs().instalados(self.base)

    def ficha(self, modelo: str) -> Dict[str, Any]:
        return _rs().ficha(self.base, modelo)

    # ------------------------------------------------------------ crear, copiar, borrar
    def crear_variante(self, nombre: str, desde: str, system: str = "", parametros: Optional[Dict[str, Any]] = None,
                       mensajes: Optional[List[Dict[str, str]]] = None, licencia: str = "") -> Generator[Dict[str, Any], None, None]:
        return _rs().crear_variante(self.base, nombre or "", desde, system or "", parametros, mensajes, licencia or "")

    def copiar(self, origen: str, destino: str) -> Dict[str, Any]:
        return _rs().copiar(self.base, origen, destino or "")

    def borrar(self, modelo: str) -> Dict[str, Any]:
        return _rs().borrar(self.base, modelo)

    # ------------------------------------------------------------ importar GGUF
    def importar_gguf(self, ruta: str, nombre: str, cancelar: Optional[Callable[[], bool]] = None) -> Generator[Dict[str, Any], None, None]:
        return _rs().importar_gguf(self.base, ruta, nombre or "", cancelar)

    # ------------------------------------------------------------ actualizaciones
    def actualizaciones(self) -> List[Dict[str, Any]]:
        return _rs().actualizaciones(self.base, REGISTRO)

    # ------------------------------------------------------------ cargados
    def cargados(self) -> List[Dict[str, Any]]:
        return _rs().cargados(self.base)

    def precargar(self, modelo: str, opciones: Dict[str, Any], keep_alive: Optional[str]) -> Dict[str, Any]:
        return _rs().precargar(self.base, modelo, opciones, keep_alive)

    def descargar(self, modelo: str) -> Dict[str, Any]:
        return _rs().descargar(self.base, modelo)

    # ------------------------------------------------------------ descargas a medias
    @staticmethod
    def carpeta_modelos() -> str:
        return _rs().carpeta_modelos()

    def parciales(self, carpeta: Optional[str] = None) -> Dict[str, Any]:
        return _rs().parciales(carpeta)

    def borrar_parciales(self, carpeta: Optional[str] = None) -> Dict[str, Any]:
        """ Solo archivos con "partial" en el nombre dentro de blobs/: nunca un modelo completo """
        return _rs().borrar_parciales(carpeta)

    # ------------------------------------------------------------ probar
    def probar(self, cuerpo: Dict[str, Any], timeout: float = 900) -> Dict[str, Any]:
        return _rs().probar(self.base, cuerpo, timeout)

    def uso_disco(self) -> Dict[str, Any]:
        return _rs().uso_disco(self.base)

