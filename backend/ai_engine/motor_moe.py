""" Motor MoE: Qwen3.6-35B-A3B con los expertos más usados en la GPU.

Ollama (llama.cpp) solo sabe repartir capas enteras entre GPU y RAM. Este motor usa un llama.cpp
modificado (moe-autopilot + parche de Prig, ver recursos/nativo/moe) que copia a la VRAM los
expertos más usados de cada capa y deja el resto en la RAM (docs/motor-moe.md).

El motor es del servidor de Rust (backend-rust/crates/prig-ia, motor.rs y moe.rs): arranca y para el llama-server,
traduce las peticiones, guarda y restaura los proyectos y elige los expertos calientes. Es el único dueño del proceso,
que además muere con Prig (PDEATHSIG). Este módulo es su cliente mientras el chat y la lectura por unidades sigan en
Python: le pasa las peticiones con el formato de Ollama (como a Ollama) a `/api/moe/…` del servidor de Rust, cuyo
puerto le da la ventana en PRIG_PUERTO_RUST.
"""
import json
import os
from typing import Any, Callable, Dict, List, Optional

import requests


def _rs():
    from nativo_rust import rust
    return rust().moe


NOMBRE = "qwen3.6-35b-moe:prig"
MODELO_OLLAMA = ("hf.co", "Elsephire", "Qwen3.6-35B-A3B-vocabulary-trimming-GGUF", "Q4_K_S")
CAPACIDADES = ["completion", "tools", "thinking"]

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.join(RAIZ, "lib", "moe")
SERVIDOR = os.path.join(LIB, "llama-server")

# Valores por defecto de los ajustes (moe_* en la configuración de IA); los aplica el motor de Rust
CONTEXTO = "auto"
CONTEXTO_MAX = 262144
NUCLEOS = {"q4": None, "q8": "nucleo-q8-expertos-q4.gguf"}
NUCLEO = "q8"
MODOS = {"exacto": None, "equilibrado": 0.08, "rapido": 0.10}
MODO = "equilibrado"
# Estados de proyectos guardados por el motor (la lectura por unidades los lista y los borra)
CARPETA_PROYECTOS = os.path.expanduser("~/.cache/prig-moe/proyectos")

# Campos propios de Prig en la petición (Ollama los ignoraría; solo los mira este motor)
SOLO_CODIGO = "prig_solo_codigo"
PERFIL = "prig_perfil"
GRAMATICA_CODIGO = _rs().GRAMATICA_CODIGO
INSTRUCCION_SOLO_CODIGO = _rs().INSTRUCCION_SOLO_CODIGO


def es_moe(modelo: Optional[str]) -> bool:
    return (modelo or "").strip() == NOMBRE


def estimar_tokens(pedido: Dict[str, Any]) -> int:
    """ Tokens que necesita una petición de Ollama: lo que se lee (por caracteres, prudente) más lo que se genera """
    return _rs().estimar_tokens(pedido)


def carpeta_modelos() -> str:
    return os.environ.get("OLLAMA_MODELS") or os.path.expanduser("~/.ollama/models")


def blob_del_modelo(modelos: Optional[str] = None) -> Optional[str]:
    """ El GGUF que Ollama descargó (hf.co/Elsephire/…:Q4_K_S) """
    modelos = modelos or carpeta_modelos()
    manifiesto = os.path.join(modelos, "manifests", *MODELO_OLLAMA)
    try:
        with open(manifiesto, encoding="utf-8") as f:
            capas = json.load(f).get("layers") or []
    except (OSError, ValueError):
        return None
    for capa in capas:
        if str(capa.get("mediaType", "")).endswith(".model"):
            ruta = os.path.join(modelos, "blobs", str(capa.get("digest", "")).replace(":", "-"))
            return ruta if os.path.isfile(ruta) else None
    return None


def _servidor_rust() -> Optional[str]:
    puerto = os.environ.get("PRIG_PUERTO_RUST")
    return f"http://127.0.0.1:{puerto}" if puerto else None


class _SinMotor(requests.Response):
    """ Respuesta de error con el formato de Ollama (`{"error": ...}`) """

    def __init__(self, estado: int, mensaje: str):
        super().__init__()
        self.status_code = estado
        self._content = json.dumps({"error": mensaje}, ensure_ascii=False).encode("utf-8")


SIN_SERVIDOR = "El motor MoE lo sirve el servidor de Rust de Prig: abre Prig con su ventana (run.sh)."


class Motor:
    """ Cliente del motor MoE del servidor de Rust, con la interfaz que usan el chat, la lectura por unidades y el panel
    de recursos """

    def __init__(self, liberar_gpu: Optional[Callable[[], None]] = None,
                 ajustes: Optional[Callable[[], Dict[str, Any]]] = None,
                 propios: Optional[Callable[[], List[str]]] = None):
        self.liberar_gpu = liberar_gpu
        self.ajustes = ajustes or (lambda: {})
        # Los modelos de Ollama que cargó Prig: el motor los descarga antes de arrancar para tener la VRAM
        self.propios = propios or (lambda: [])

    @staticmethod
    def disponible() -> Dict[str, Any]:
        servidor = os.access(SERVIDOR, os.X_OK)
        blob = blob_del_modelo()
        motivo = None
        if not servidor:
            motivo = "Falta compilar el motor: backend/recursos/nativo/moe/compilar.sh"
        elif not blob:
            motivo = "Falta el modelo: ollama pull " + "/".join(MODELO_OLLAMA[:3]) + ":" + MODELO_OLLAMA[3]
        return {"disponible": motivo is None, "motivo": motivo, "servidor": servidor, "modelo": blob}

    # -- llamadas al servidor de Rust ----------------------------------------------------------------------------------
    def _url(self, ruta: str) -> str:
        base = _servidor_rust()
        if not base:
            raise RuntimeError(SIN_SERVIDOR)
        return base + ruta

    def _get(self, ruta: str) -> Dict[str, Any]:
        r = requests.get(self._url(ruta), timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, ruta: str, cuerpo: Optional[Dict[str, Any]] = None, timeout: float = 60) -> Dict[str, Any]:
        r = requests.post(self._url(ruta), json=cuerpo or {}, timeout=timeout)
        if r.status_code != 200:
            try:
                detalle = r.json().get("detail")
            except ValueError:
                detalle = r.text
            raise RuntimeError(str(detalle)[:300])
        return r.json()

    def estado(self) -> Dict[str, Any]:
        e = self._get("/api/moe/estado")
        for k in ("generando", "contexto_deseado"):
            e.pop(k, None)
        return e

    def contexto_deseado(self, a: Optional[Dict[str, Any]] = None) -> int:
        """ El contexto que usaría el motor ahora (el fijado en los ajustes o, en automático, el que hizo falta) """
        try:
            return int(self.estado()["contexto_deseado"])
        except Exception:
            return 32768

    def en_marcha(self) -> bool:
        return pid_en_marcha() is not None

    def pid(self) -> Optional[int]:
        return pid_en_marcha()

    def detener(self):
        if _servidor_rust():
            self._post("/api/moe/detener")

    def podar(self) -> int:
        return int(self._post("/api/moe/podar").get("borrados", 0))

    def olvidar_proyectos(self) -> int:
        return int(self._post("/api/moe/olvidar").get("borrados", 0))

    def tomar_ultimo_proyecto(self) -> Dict[str, Any]:
        """ Lo que hizo el motor con el prefijo de la última conversación (leerlo o restaurarlo); se olvida al leerlo """
        try:
            return self._post("/api/moe/ultimo_proyecto").get("proyecto") or {}
        except Exception:
            return {}

    def directo(self, metodo: str, ruta: str, cuerpo: Optional[Dict[str, Any]] = None, timeout: float = 900) -> Any:
        """ Petición cruda a llama-server (/apply-template, /completion, /slots, /aipc…) para la lectura por unidades """
        r = requests.post(self._url("/api/moe/directo"), timeout=timeout + 30,
                          json={"metodo": metodo, "ruta": ruta, "cuerpo": cuerpo, "timeout": timeout})
        if r.status_code != 200:
            try:
                detalle = r.json().get("detail")
            except ValueError:
                detalle = r.text
            raise RuntimeError(str(detalle)[:400])
        return r.json()

    def post(self, url: str, pedido: Dict[str, Any], timeout: float = 600) -> requests.Response:
        """ Una petición de Ollama (/api/chat o /api/generate) servida por el motor; la respuesta es la de Ollama
        (NDJSON en streaming): cerrarla corta la conexión y el motor deja de generar """
        ruta = url.split("?", 1)[0]
        tipo = "generate" if ruta.endswith("/api/generate") else "chat"
        base = _servidor_rust()
        if not base:
            return _SinMotor(503, SIN_SERVIDOR)
        try:
            propios = [m for m in self.propios() if m]
        except Exception:
            propios = []
        cuerpo = json.dumps({**pedido, "_prig_liberar": propios, "_prig_timeout": timeout}, ensure_ascii=False)
        try:
            return requests.post(f"{base}/api/moe/ollama/{tipo}", data=cuerpo.encode("utf-8"), stream=True,
                                 headers={"Content-Type": "application/json"}, timeout=(5, None))
        except requests.RequestException as e:
            return _SinMotor(503, f"El motor MoE no responde: {e}")


_motor: Optional[Motor] = None


def motor(liberar_gpu: Optional[Callable[[], None]] = None,
          ajustes: Optional[Callable[[], Dict[str, Any]]] = None,
          propios: Optional[Callable[[], List[str]]] = None) -> Motor:
    global _motor
    if _motor is None:
        _motor = Motor(liberar_gpu, ajustes, propios)
    else:
        if liberar_gpu is not None:
            _motor.liberar_gpu = liberar_gpu
        if ajustes is not None:
            _motor.ajustes = ajustes
        if propios is not None:
            _motor.propios = propios
    return _motor


def _actividad() -> Dict[str, Any]:
    base = _servidor_rust()
    if not base:
        return {}
    try:
        return requests.get(f"{base}/api/moe/actividad", timeout=2).json()
    except Exception:
        return {}


def generando() -> bool:
    """ ¿Hay alguna respuesta en curso en el motor MoE? """
    return bool(_actividad().get("generando"))


def pid_en_marcha() -> Optional[int]:
    return _actividad().get("pid")


def limpiar_huerfanos() -> int:
    """ Lo hace el servidor de Rust al arrancar (es el dueño del motor) """
    return 0
