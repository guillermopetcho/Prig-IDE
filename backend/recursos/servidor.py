"""
Ajustes del SERVIDOR de Ollama: los que no se pueden mandar en cada petición.

La caché KV cuantizada, las ranuras en paralelo o FlashAttention se fijan con
variables de entorno al arrancar `ollama serve`. Cambiarlas exige reiniciarlo, y
eso solo es seguro si el proceso es de Prig:

  · dueño "prig": Prig lo arrancó con su binario → se reinicia con las variables.
  · dueño "systemd" / "systemd-usuario": lo gestiona el sistema → se dan las
    instrucciones exactas (un override de systemd) y no se toca nada.
  · dueño "usuario": alguien lo lanzó a mano en una terminal → instrucciones.

Nunca se actualiza ni se sustituye el binario de Ollama del sistema.
Las reglas, el estado, las instrucciones, el registro y las señales están en Rust (backend-rust/crates/
prig-recursos, servidor.rs). Aquí queda lo que toca al motor de Python: aplicar y reiniciar.
"""

import os
from typing import Any, Dict, Optional

from . import detector
from .almacen import almacen

RAIZ_PRIG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rs():
    from nativo_rust import rust
    return rust().servidor


# Variables que Prig gestiona. El resto (OLLAMA_MODELS, OLLAMA_HOST…) se respeta.
GESTIONADAS = tuple(_rs().GESTIONADAS)
VALORES_VALIDOS = {k: set(v) for k, v in _rs().VALORES_VALIDOS.items()}
# Qué hace cada una y cómo se comprobó, para la interfaz
DESCRIPCIONES = {k: tuple(v) for k, v in _rs().DESCRIPCIONES.items()}


def librerias_disponibles() -> list:
    """ Motores instalados junto al binario de Ollama de Prig, más la CPU """
    return _rs().librerias_disponibles(RAIZ_PRIG)


def validar(cambios: Dict[str, Any]) -> Dict[str, str]:
    """ Las variables limpias (ValueError si alguna no vale). La caché cuantizada activa FlashAttention: sin ella,
    Ollama la ignora en silencio y el usuario cree tener un ajuste que no tiene. """
    return _rs().validar(cambios, RAIZ_PRIG)


def estado(info_ollama: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    info = info_ollama or detector.ollama()
    return _rs().estado(info, almacen().entorno_servidor(), RAIZ_PRIG, ruta_registro())


def instrucciones(dueno: Optional[str], entorno: Dict[str, str]) -> str:
    return _rs().instrucciones(dueno, entorno)


def aplicar(cambios: Dict[str, Any], motor=None, reiniciar: bool = True,
            forzar: bool = False) -> Dict[str, Any]:
    """ Guarda las variables y, si el servidor es de Prig, lo reinicia con ellas """
    limpio = validar(cambios)
    guardado = almacen().entorno_servidor()
    guardado.update(limpio)
    guardado = {k: v for k, v in guardado.items() if v != ""}
    almacen().guardar_entorno_servidor(guardado)

    info = detector.ollama()
    dueno = info.get("dueno")
    if dueno not in ("prig", None):
        return {"aplicado": False, "guardado": guardado, "dueno": dueno,
                "instrucciones": instrucciones(dueno, guardado)}
    if not reiniciar:
        return {"aplicado": False, "guardado": guardado, "dueno": dueno,
                "mensaje": "Guardado. Se usará la próxima vez que Prig arranque Ollama."}
    if info.get("modelos_cargados") and not forzar:
        return {"aplicado": False, "guardado": guardado, "dueno": dueno,
                "necesita_confirmar": True,
                "mensaje": "Hay modelos cargados: reiniciar corta lo que estén generando. "
                           "Confirma para reiniciar igualmente."}
    return reiniciar_servidor(info, motor, guardado)


def ruta_registro() -> str:
    return os.path.expanduser("~/.prig_ollama.log")


def abrir_registro():
    """ Archivo donde Prig manda la salida de su `ollama serve`. Antes iba a /dev/null
    y cualquier fallo llegaba sin explicación. Se rota al pasar de 5 MB. """
    ruta = ruta_registro()
    try:
        _rs().rotar_registro(ruta)
        return open(ruta, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return None


def leer_registro(lineas: int = 400, dueno: Optional[str] = None) -> Dict[str, Any]:
    return _rs().leer_registro(int(lineas), dueno, ruta_registro())


def entorno_arranque(base: Dict[str, str]) -> Dict[str, str]:
    """ El entorno con el que Prig arranca `ollama serve` """
    return _rs().entorno_arranque(dict(base), almacen().entorno_servidor())


def reiniciar_servidor(info: Dict[str, Any], motor, guardado: Dict[str, str]) -> Dict[str, Any]:
    pid = info.get("pid")
    if pid and info.get("dueno") == "prig":
        _rs().parar_ollama(pid)

    arrancado = False
    if motor is not None:
        try:
            arrancado = bool(motor.try_autostart_ollama())
        except Exception as e:
            return {"aplicado": False, "guardado": guardado, "error": str(e)}

    nuevo = detector.ollama()
    real = nuevo.get("entorno") or {}
    faltan = {k: v for k, v in guardado.items() if real.get(k) != v}
    almacen().evento("servidor_reiniciado",
                     "Ollama reiniciado con las variables de Prig." if not faltan
                     else "Ollama reiniciado, pero no tomó todas las variables.",
                     {"entorno": real, "faltan": faltan})
    return {"aplicado": arrancado and not faltan, "guardado": guardado,
            "dueno": nuevo.get("dueno"), "entorno": real, "faltan": faltan,
            "version": nuevo.get("version")}
