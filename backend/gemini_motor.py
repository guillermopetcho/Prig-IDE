"""
Google Gemini como motor opcional, en la nube, para los desafíos.

CÓMO SE CONECTA: con una clave de API que el usuario crea entrando con su cuenta de
Google en Google AI Studio (aistudio.google.com/apikey). Es la vía oficial para usar
Gemini desde otro programa y tiene nivel gratuito.

Lo que NO se hace: reutilizar la sesión de Gemini CLI o Antigravity guardada en
~/.gemini/oauth_creds.json. Las condiciones de Gemini CLI dicen que acceder a sus
servicios con su inicio de sesión desde software de terceros «es una violación de las
condiciones y políticas aplicables».

PRIVACIDAD: en el nivel gratuito, Google puede usar lo que se le envía (tema, enunciado,
plan y código del alumno) y las respuestas para mejorar sus productos, con revisión
humana. Por eso está apagado hasta que el usuario pega su clave y acepta el aviso.

La clave vive en ~/.prig_gemini.json con permisos 600 (o en GEMINI_API_KEY). Nunca se
devuelve al navegador, va en la cabecera x-goog-api-key (no en la URL) y se borra de
cualquier mensaje de error por si acaso.

Variables para las pruebas: PRIG_GEMINI_ARCHIVO (dónde se guarda) y PRIG_GEMINI_URL
(servidor falso en vez de generativelanguage.googleapis.com).

Todo está en Rust (backend-rust/crates/prig-ia, gemini.rs): guardar y comprobar la clave, la lista de modelos y
generar; las rutas /api/gemini/* son del servidor de Rust. Aquí queda leer la clave y el motor con la forma de
AIEngine.generate_response, que genera a través del servidor (POST /api/ia/gemini).
"""

import json
import os
import threading
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import requests

PREFIJO = "gemini:"


def ruta_config() -> str:
    return os.environ.get("PRIG_GEMINI_ARCHIVO") or os.path.expanduser("~/.prig_gemini.json")


def _leer() -> Dict[str, Any]:
    try:
        with open(ruta_config(), encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def clave_actual() -> Tuple[Optional[str], Optional[str]]:
    """ (clave, origen): primero lo guardado en Prig, después GEMINI_API_KEY """
    guardada = _leer().get("clave")
    if guardada:
        return guardada, "prig"
    entorno = os.environ.get("GEMINI_API_KEY")
    if entorno:
        return entorno, "entorno"
    return None, None


_activas = set()
_cerrojo = threading.Lock()


def cancelar_todo() -> int:
    """ Corta las respuestas de Gemini en curso (cerrar la conexión con el servidor de Rust la detiene) """
    with _cerrojo:
        respuestas = list(_activas)
        _activas.clear()
    for r in respuestas:
        try:
            r.close()
        except Exception:
            pass
    return len(respuestas)


class MotorGemini:
    """ Sustituye al motor de Ollama en los desafíos: el tutor no sabe con cuál habla. Los errores llegan como texto
    «[Error Gemini: …]», igual que el motor local devuelve «[Error Ollama: …]». """

    def __init__(self, extraer_json: Callable[[str], dict]):
        self._extraer_json = extraer_json

    def _extract_and_parse_json(self, texto: str) -> dict:
        return self._extraer_json(texto)

    @staticmethod
    def capacidades(model: str) -> List[str]:
        return []

    def generate_response(self, prompt: str, model: str, system_prompt: str = "", options: Optional[Dict[str, Any]] = None,
                          think: Optional[bool] = None, on_thinking=None, on_token=None, uso=None,
                          on_stats=None) -> Generator[str, None, None]:
        puerto = os.environ.get("PRIG_PUERTO_RUST")
        if not puerto:
            yield "[Error Gemini: no hay servidor de Rust (PRIG_PUERTO_RUST).]"
            return
        try:
            r = requests.post(f"http://127.0.0.1:{puerto}/api/ia/gemini", stream=True, timeout=(5, None),
                              json={"prompt": prompt, "model": model, "system_prompt": system_prompt, "options": options})
        except requests.RequestException:
            yield "[Error Gemini: el servidor de Rust no responde.]"
            return
        with _cerrojo:
            _activas.add(r)
        try:
            for linea in r.iter_lines():
                if not linea:
                    continue
                ev = json.loads(linea.decode("utf-8"))
                if ev.get("t") == "texto":
                    if ev.get("token") and on_token:
                        on_token(ev["v"])
                    yield ev["v"]
                elif ev.get("t") == "pensando" and on_thinking:
                    on_thinking(ev["v"])
                elif ev.get("t") == "stats" and on_stats:
                    on_stats(ev["v"])
        except (requests.RequestException, AttributeError, ValueError):
            return                                              # cancelado o conexión cortada
        finally:
            with _cerrojo:
                _activas.discard(r)
            try:
                r.close()
            except Exception:
                pass


def es_gemini(modelo: Optional[str]) -> bool:
    return bool(modelo) and modelo.startswith(PREFIJO)
