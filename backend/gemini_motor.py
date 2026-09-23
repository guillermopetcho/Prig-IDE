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
"""

import json
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import requests

PREFIJO = "gemini:"
URL_CLAVES = "https://aistudio.google.com/apikey"
# No se valida el formato de la clave: lo decide Google al comprobarla. Desde el 28 de mayo de
# 2026 AI Studio crea claves nuevas «AQ.…» (con puntos) y un filtro pensado para las antiguas
# «AIza…» las rechazaba. Solo se descarta lo que no puede ser una clave (espacios, muy corta).
CARACTERES_INVISIBLES = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00a0]")
AVISO_PRIVACIDAD = (
    "Cuando uses un modelo Gemini, Prig envía a Google el tema, el enunciado, tu plan, tu código y los "
    "mensajes del tutor de ese desafío. En el nivel gratuito, Google puede usar ese contenido y las "
    "respuestas para mejorar sus productos, y puede revisarlo una persona. No escribas datos personales. "
    "Con facturación activada (nivel de pago) Google no lo usa para mejorar sus productos."
)


class ErrorGemini(Exception):
    pass


def _base() -> str:
    return (os.environ.get("PRIG_GEMINI_URL") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")


def ruta_config() -> str:
    return os.environ.get("PRIG_GEMINI_ARCHIVO") or os.path.expanduser("~/.prig_gemini.json")


# ===========================================================================
# La clave
# ===========================================================================

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


def enmascarar(clave: Optional[str]) -> Optional[str]:
    if not clave:
        return None
    return f"{clave[:4]}…{clave[-4:]}" if len(clave) > 12 else "…"


def estado() -> Dict[str, Any]:
    clave, origen = clave_actual()
    datos = _leer()
    return {"configurado": bool(clave), "origen": origen, "clave": enmascarar(clave),
            "aviso_aceptado": datos.get("aviso_aceptado") if origen == "prig" else None,
            "aviso": AVISO_PRIVACIDAD, "url_claves": URL_CLAVES}


def limpiar_clave(texto: str) -> str:
    """ La clave tal como se usa, a partir de lo que se pegó.

    Acepta la clave sola o como suele copiarse junto a otras cosas: entre comillas,
    `GEMINI_API_KEY=…`, `export GEMINI_API_KEY="…"`, `x-goog-api-key: …` o una URL con `key=…`.
    Quita espacios de los extremos y caracteres invisibles que a veces se cuelan al copiar.
    Si no puede ser una clave lo dice sin repetirla (los mensajes pueden acabar en pantalla). """
    t = CARACTERES_INVISIBLES.sub("", texto or "").strip()
    m = re.search(r"[?&]key=([^&\s]+)", t)
    if m:
        t = m.group(1)
    t = re.sub(r"^(?:export\s+)?[A-Z_]*API_KEY\s*=\s*", "", t)
    t = re.sub(r"^x-goog-api-key\s*:\s*", "", t, flags=re.I)
    t = t.strip().strip("\"'`").strip()
    if not t:
        raise ErrorGemini("No pegaste ninguna clave.")
    if re.search(r"\s", t):
        raise ErrorGemini("Lo que pegaste tiene espacios o saltos de línea en medio: copia solo la clave "
                          "(en AI Studio, el botón de copiar junto a la clave).")
    if len(t) < 20:
        raise ErrorGemini(f"Lo que pegaste tiene {len(t)} caracteres y una clave de Gemini es más larga: "
                          "parece que falta un trozo. Cópiala de nuevo con el botón de copiar de AI Studio.")
    if not all(33 <= ord(c) <= 126 for c in t):
        raise ErrorGemini("Lo que pegaste tiene caracteres que no aparecen en las claves (acentos, símbolos "
                          "especiales): cópiala de nuevo desde AI Studio.")
    return t


def guardar_clave(clave: str, acepto_aviso: bool) -> Dict[str, Any]:
    if not acepto_aviso:
        raise ErrorGemini("Para conectar Gemini tienes que aceptar el aviso de privacidad.")
    clave = limpiar_clave(clave)
    modelos = listar_modelos(clave, usar_cache=False)          # comprueba que funciona antes de guardarla
    ruta = ruta_config()
    tmp = ruta + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"clave": clave, "aviso_aceptado": datetime.now().isoformat(timespec="seconds")}, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ruta)
    _cache.clear()
    return {**estado(), "modelos": modelos}


def borrar_clave() -> Dict[str, Any]:
    try:
        os.remove(ruta_config())
    except FileNotFoundError:
        pass
    _cache.clear()
    return estado()


# ===========================================================================
# Peticiones
# ===========================================================================

def _explicar(codigo: int, cuerpo: str, clave: Optional[str]) -> str:
    try:
        error = json.loads(cuerpo).get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    motivo = " ".join(str(d.get("reason", "")) for d in error.get("details") or [] if isinstance(d, dict))
    mensaje = str(error.get("message") or cuerpo or "")[:300]
    if clave:
        mensaje = mensaje.replace(clave, "…")
    if "API_KEY_INVALID" in motivo or "API key not valid" in mensaje:
        return "La clave de Gemini no es válida. Crea otra en Google AI Studio y vuelve a conectarla."
    if codigo == 401 or "ACCESS_TOKEN_TYPE_UNSUPPORTED" in motivo:
        # Medido: así responde Google a una clave «AQ.…» que no reconoce (mal copiada, borrada o de otro proyecto)
        return ("Google no reconoce esta clave. Suele pasar si se copió incompleta o si la borraste en AI Studio. "
                "Cópiala de nuevo con el botón de copiar de AI Studio, o crea otra.")
    if codigo == 429 or error.get("status") == "RESOURCE_EXHAUSTED":
        return ("Llegaste al límite gratuito de Gemini (por minuto o por día). Espera un poco o usa un "
                "modelo local mientras tanto.")
    if codigo == 403:
        return f"Google rechazó la petición: la clave no tiene permiso para usar Gemini ({mensaje})."
    if codigo == 404:
        return "Ese modelo de Gemini no existe o tu clave no tiene acceso a él. Elige otro de la lista."
    if codigo >= 500:
        return "Gemini no responde ahora mismo (error del servidor de Google). Prueba más tarde."
    return f"Gemini respondió {codigo}: {mensaje}"


class _Cache:
    def __init__(self):
        self._d: Dict[str, Tuple[float, Any]] = {}

    def obtener(self, k, ttl):
        v = self._d.get(k)
        return v[1] if v and time.time() - v[0] < ttl else None

    def guardar(self, k, v):
        self._d[k] = (time.time(), v)
        return v

    def clear(self):
        self._d.clear()


_cache = _Cache()


def listar_modelos(clave: Optional[str] = None, usar_cache: bool = True) -> List[Dict[str, Any]]:
    """ Modelos Gemini que la clave puede usar para generar texto """
    clave = clave or clave_actual()[0]
    if not clave:
        raise ErrorGemini("Gemini no está conectado.")
    k = f"modelos:{hash(clave)}"
    if usar_cache and _cache.obtener(k, 600) is not None:
        return _cache.obtener(k, 600)
    modelos, token = [], None
    for _ in range(10):
        params = {"pageSize": 200}
        if token:
            params["pageToken"] = token
        try:
            r = requests.get(f"{_base()}/models", params=params, headers={"x-goog-api-key": clave}, timeout=20)
        except requests.RequestException:
            raise ErrorGemini("Sin conexión con Google: comprueba internet.")
        if r.status_code != 200:
            raise ErrorGemini(_explicar(r.status_code, r.text, clave))
        datos = r.json()
        for m in datos.get("models") or []:
            nombre = str(m.get("name", "")).split("/")[-1]
            metodos = m.get("supportedGenerationMethods") or []
            if "generateContent" not in metodos or not nombre.startswith("gemini"):
                continue
            if re.search(r"embedding|tts|image|audio|live|robotics|computer-use", nombre):
                continue
            modelos.append({"id": nombre, "nombre": m.get("displayName") or nombre, "piensa": bool(m.get("thinking")),
                            "entrada": m.get("inputTokenLimit"), "salida": m.get("outputTokenLimit")})
        token = datos.get("nextPageToken")
        if not token:
            break
    # Primero los Flash (los del nivel gratuito), los más recientes arriba
    modelos.sort(key=lambda m: ("flash" not in m["id"], "lite" in m["id"], "preview" in m["id"], m["id"]), reverse=False)
    return _cache.guardar(k, modelos)


# ===========================================================================
# Motor con la misma forma que AIEngine.generate_response
# ===========================================================================

_activas = set()
_cerrojo = threading.Lock()


def cancelar_todo() -> int:
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
    """ Sustituye al motor de Ollama en los desafíos: el tutor no sabe con cuál habla.

    Los errores se devuelven como texto «[Error Gemini: …]», igual que el motor local
    devuelve «[Error Ollama: …]», y el tutor los convierte en un mensaje para el alumno. """

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
        clave = clave_actual()[0]
        if not clave:
            yield "[Error Gemini: Gemini no está conectado. Conéctalo o elige un modelo local.]"
            return
        cuerpo: Dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if system_prompt:
            cuerpo["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        config = {}
        if options and options.get("temperature") is not None:
            config["temperature"] = float(options["temperature"])
        if options and options.get("format") == "json":
            config["responseMimeType"] = "application/json"
        if config:
            cuerpo["generationConfig"] = config
        url = f"{_base()}/models/{model}:streamGenerateContent"
        try:
            r = requests.post(url, params={"alt": "sse"}, json=cuerpo, stream=True, timeout=(15, 300),
                              headers={"x-goog-api-key": clave, "Content-Type": "application/json"})
        except requests.RequestException:
            yield "[Error Gemini: Sin conexión con Google: comprueba internet.]"
            return
        with _cerrojo:
            _activas.add(r)
        try:
            if r.status_code != 200:
                yield f"[Error Gemini: {_explicar(r.status_code, r.text, clave)}]"
                return
            # text/event-stream llega sin charset y requests lo leería como Latin-1: «límite» → «lÃ­mite»
            r.encoding = "utf-8"
            for linea in r.iter_lines(decode_unicode=True):
                if not linea or not linea.startswith("data:"):
                    continue
                try:
                    datos = json.loads(linea[5:].strip())
                except ValueError:
                    continue
                bloqueo = (datos.get("promptFeedback") or {}).get("blockReason")
                if bloqueo:
                    yield f"[Error Gemini: Google bloqueó la petición por sus filtros ({bloqueo}).]"
                    return
                for candidato in datos.get("candidates") or []:
                    for parte in (candidato.get("content") or {}).get("parts") or []:
                        if parte.get("thought"):
                            if on_thinking and isinstance(parte.get("text"), str):
                                on_thinking(parte["text"])
                            continue
                        texto = parte.get("text")
                        if texto:
                            if on_token:
                                on_token(texto)
                            yield texto
                uso_tokens = datos.get("usageMetadata")
                if uso_tokens and on_stats:
                    on_stats({"motor": "gemini", **uso_tokens})
        except requests.RequestException:
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
