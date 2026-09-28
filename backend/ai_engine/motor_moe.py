""" Motor MoE: Qwen3.6-35B-A3B con los expertos más usados en la GPU.

Ollama (llama.cpp) solo sabe repartir capas enteras entre GPU y RAM. Este motor usa un llama.cpp
modificado (moe-autopilot + parche de Prig, ver recursos/nativo/moe) que copia a la VRAM los
expertos más usados de cada capa y deja el resto en la RAM; la CPU solo calcula los expertos que
no están en la GPU. Medido en una RTX 4050 de 6 GB: 27 → 35 tok/s y 40 % menos trabajo de CPU
por token (docs/motor-moe.md).

Para el resto de Prig es un modelo más, «qwen3.6-35b-moe:prig»: el motor de IA le pasa las
peticiones con el formato de Ollama (/api/chat, /api/generate) y este módulo las traduce al
llama-server propio (formato OpenAI) y devuelve la respuesta con el formato de Ollama.

El servidor arranca con la primera petición y se para tras keep_alive sin uso, como un modelo
de Ollama. Antes de arrancar se descargan los modelos de Ollama de Prig para dejarle la VRAM.
"""
import glob
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import requests

NOMBRE = "qwen3.6-35b-moe:prig"
MODELO_OLLAMA = ("hf.co", "Elsephire", "Qwen3.6-35B-A3B-vocabulary-trimming-GGUF", "Q4_K_S")
CAPACIDADES = ["completion", "tools", "thinking"]

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.join(RAIZ, "lib", "moe")
SERVIDOR = os.path.join(LIB, "llama-server")
LISTA = os.path.join(RAIZ, "backend", "recursos", "nativo", "moe", "qwen36_calientes.txt")
REGISTRO = os.path.expanduser("~/.prig_moe.log")

CONTEXTO = "auto"
MAX_CALIENTES = 56
MB_POR_CALIENTE = 68.65       # medido: un experto caliente más en cada una de las 40 capas
MARGEN_MB = 250               # medido: +64–130 MB tras leer prompts largos; el resto, holgura
RESERVA_CUDA_MB = 370         # medido: CUDA deja usar ~5.770 de los 6.141 MB (nvidia-smi da ~6.126 libres)

# Modos: cuánto se aparta del modelo original para ir más rápido. Omite (no calcula) los expertos
# FRÍOS cuyo peso en la mezcla es menor que el umbral. Medido con MTP y solapamiento en una
# RTX 4050 (docs/motor-moe.md): exacto 53 tok/s; equilibrado 60 (divergencia KL 0,037,
# perplejidad +0,5 %); rápido 68 (KL 0,066, +1,6 %).
MODOS = {"exacto": None, "equilibrado": 0.08, "rapido": 0.10}
MODO = "equilibrado"


# Contexto: hasta el máximo del modelo (262.144 tokens). Caché de atención en 8 bits (q8_0): la
# mitad de VRAM que en 16 bits. Cada tamaño lee el prompt en lotes distintos: más grande = más
# rápido (medido con 26.600 tokens: 512 → 273 tok/s, 2048 → 646, 4096 → 815) pero su búfer crece
# con lote × contexto. VRAM base medida en una RTX 4050 (núcleo del modelo, caché, búferes, CUDA),
# sin expertos calientes, sin y con MTP (la cabeza MTP tiene su propia caché y su búfer de lectura):
CONTEXTOS = {        # contexto: (lote, MB sin MTP, MB con MTP; None = MTP no cabe)
    8192:   (4096, 2375, 3075),
    16384:  (4096, 2375, 3075),
    32768:  (4096, 2673, 3447),
    65536:  (2048, 2689, 3367),
    131072: (2048, 3739, 4799),
    262144: (1024, 5305, None),
}
CONTEXTO_MAX = 262144
CONTEXTO_INICIAL = 32768        # contexto automático: empieza aquí y crece si una petición no cabe
CARACTERES_POR_TOKEN = 3.0      # estimación prudente (código y español): se queda corta, no larga
CACHE_RAM_MB = 16384            # prompts ya leídos que llama-server guarda en RAM

# Proyectos guardados en disco. Cuando una conversación empieza con un bloque grande (los archivos
# enganchados, un proyecto entero), el estado del modelo tras leer SOLO ese bloque se guarda aquí.
# Las preguntas siguientes sobre el mismo proyecto, también en otra sesión, lo restauran (~0,1 s)
# en lugar de releerlo. Medido: 16.957 tokens → leer 21 s; restaurar 0,08 s y responder en 0,8 s.
# Tiene que ser el estado EXACTO al final del bloque: las capas SSM de este modelo no retroceden.
CARPETA_PROYECTOS = os.path.expanduser("~/.cache/prig-moe/proyectos")
PROYECTO_MIN_CARACTERES = 12000     # por debajo, leerlo cuesta menos que guardarlo
PROYECTOS_MAX_MB = 20480            # se borran los usados hace más tiempo


def contexto_para(tokens: int) -> Optional[int]:
    """ El menor contexto de la tabla que admite estos tokens (None si ninguno) """
    for c in sorted(CONTEXTOS):
        if c >= CONTEXTO_INICIAL and c >= tokens:
            return c
    return None


def _fila(contexto: int) -> Tuple[int, int, Optional[int]]:
    for c in sorted(CONTEXTOS):
        if c >= contexto:
            return CONTEXTOS[c]
    return CONTEXTOS[CONTEXTO_MAX]


def estimar_tokens(pedido: Dict[str, Any]) -> int:
    """ Tokens que necesita una petición de Ollama: lo que se lee (por caracteres, prudente) más
    lo que se puede generar """
    caracteres = len(str(pedido.get("prompt") or "")) + len(str(pedido.get("system") or ""))
    for m in pedido.get("messages") or []:
        caracteres += len(str(m.get("content") or "")) + len(str(m.get("thinking") or ""))
        if m.get("tool_calls"):
            caracteres += len(json.dumps(m["tool_calls"], ensure_ascii=False))
    if pedido.get("tools"):
        caracteres += len(json.dumps(pedido["tools"], ensure_ascii=False))
    tope = int((pedido.get("options") or {}).get("num_predict") or 0)
    return int(caracteres / CARACTERES_POR_TOKEN) + (tope if tope > 0 else 4096) + 512


def prefijo_de(cuerpo: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """ Mensajes (formato OpenAI) hasta el primer mensaje del usuario inclusive, si es grande y la
    conversación sigue después (la pregunta va en otro mensaje) """
    mensajes = cuerpo.get("messages") or []
    for i, m in enumerate(mensajes):
        if m.get("role") == "user":
            if i == len(mensajes) - 1 or len(str(m.get("content") or "")) < PROYECTO_MIN_CARACTERES:
                return None
            return mensajes[: i + 1]
    return None


def proyectos_guardados(carpeta: Optional[str] = None) -> Dict[str, Any]:
    carpeta = carpeta or CARPETA_PROYECTOS
    archivos = glob.glob(os.path.join(carpeta, "*.bin"))
    total = 0
    for a in archivos:
        try:
            total += os.path.getsize(a)
        except OSError:
            pass
    return {"archivos": len(archivos), "mb": round(total / 1e6), "carpeta": carpeta}


def podar_proyectos(carpeta: Optional[str] = None, limite_mb: float = PROYECTOS_MAX_MB) -> int:
    """ Borra los proyectos usados hace más tiempo hasta quedar bajo el límite """
    carpeta = carpeta or CARPETA_PROYECTOS
    archivos = []
    for a in glob.glob(os.path.join(carpeta, "*.bin")):
        try:
            archivos.append((os.path.getmtime(a), os.path.getsize(a), a))
        except OSError:
            pass
    total, borrados = sum(t for _, t, _ in archivos), 0
    for _, tam, a in sorted(archivos):
        if total <= limite_mb * 1e6:
            break
        try:
            os.remove(a)
            total -= tam
            borrados += 1
        except OSError:
            pass
    return borrados


def lote_para(contexto: int) -> int:
    return _fila(contexto)[0]


def base_mb(contexto: int, mtp: bool = False) -> Optional[float]:
    """ VRAM sin expertos calientes para este contexto (el tamaño medido igual o mayor); None si
    con MTP no cabe """
    _, sin, con = _fila(contexto)
    valor = con if mtp else sin
    return None if valor is None else float(valor)


def cabe_mtp(vram_libre_mb: Optional[float], contexto: int) -> bool:
    base = base_mb(contexto, mtp=True)
    return base is not None and (vram_libre_mb is None or vram_libre_mb - RESERVA_CUDA_MB - MARGEN_MB >= base)


def calientes_para(vram_libre_mb: Optional[float], contexto: int, mtp: bool = False) -> int:
    base = base_mb(contexto, mtp)
    if not vram_libre_mb or base is None:
        return 0
    n = int((vram_libre_mb - RESERVA_CUDA_MB - base - MARGEN_MB) // MB_POR_CALIENTE)
    return max(0, min(MAX_CALIENTES, n))


def carpeta_modelos() -> str:
    return os.environ.get("OLLAMA_MODELS") or os.path.expanduser("~/.ollama/models")


def blob_del_modelo(modelos: Optional[str] = None) -> Optional[str]:
    """ El GGUF que Ollama descargó (hf.co/Elsephire/…:Q4_K_S). Solo tiene texto: no hay
    archivo de visión que omitir. """
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


def es_moe(modelo: Optional[str]) -> bool:
    return (modelo or "").strip() == NOMBRE


def nucleos_rendimiento() -> List[int]:
    """ Un hilo lógico por núcleo P. Medido con este modelo y el turbo apagado: 4 hilos en los
    núcleos P rinden 24–30 tok/s; en los núcleos E, 14; con los 12 hilos, 21. """
    try:
        from recursos import frio
        eficientes = set(frio.nucleos_eficientes())
    except Exception:
        eficientes = set()
    vistos, elegidos = set(), []
    for cpu in sorted(int(p.rsplit("cpu", 1)[1]) for p in glob.glob("/sys/devices/system/cpu/cpu[0-9]*")):
        if cpu in eficientes:
            continue
        try:
            with open(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list") as f:
                hermanos = f.read().strip()
        except OSError:
            hermanos = str(cpu)
        if hermanos not in vistos:
            vistos.add(hermanos)
            elegidos.append(cpu)
    return elegidos


def vram_libre_estable(espera_max: float = 8.0) -> Optional[float]:
    """ VRAM libre cuando deja de cambiar: Ollama tarda un momento en soltar un modelo """
    previa, t0 = vram_libre_mb(), time.time()
    while time.time() - t0 < espera_max:
        time.sleep(0.5)
        ahora = vram_libre_mb()
        if ahora is None or previa is None or (abs(ahora - previa) < 50 and time.time() - t0 >= 1.0):
            return ahora
        previa = ahora
    return previa


def vram_libre_mb() -> Optional[float]:
    try:
        salida = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=5).stdout
        return float(salida.split()[0])
    except Exception:
        return None


def segundos_keep_alive(valor: Any, defecto: float = 300.0) -> float:
    """ Formato de Ollama: 300, "5m", "1h", "30s", 0 (descargar ya), negativo (no descargar) """
    if valor is None or valor == "":
        return defecto
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().lower()
    try:
        for sufijo, factor in (("ms", 0.001), ("h", 3600), ("m", 60), ("s", 1)):
            if texto.endswith(sufijo):
                return float(texto[: -len(sufijo)]) * factor
        return float(texto)
    except ValueError:
        return defecto


# ---------------------------------------------------------------------------------------------
# Traducción Ollama → OpenAI (llama-server)
# ---------------------------------------------------------------------------------------------

OPCIONES = {"temperature": "temperature", "top_k": "top_k", "top_p": "top_p", "min_p": "min_p",
            "typical_p": "typical_p", "repeat_penalty": "repeat_penalty", "repeat_last_n": "repeat_last_n",
            "presence_penalty": "presence_penalty", "frequency_penalty": "frequency_penalty",
            "seed": "seed", "stop": "stop"}


def _mensajes(mensajes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ Mensajes de Ollama → OpenAI: razonamiento, llamadas a herramientas (argumentos como
    texto, con id) y resultados (tool_name → tool_call_id de la llamada correspondiente). """
    salida: List[Dict[str, Any]] = []
    pendientes: List[Tuple[str, str]] = []    # (id, nombre) de llamadas aún sin resultado
    n = 0
    for m in mensajes:
        rol = m.get("role")
        nuevo: Dict[str, Any] = {"role": rol, "content": m.get("content") or ""}
        if rol == "assistant":
            if m.get("thinking"):
                nuevo["reasoning_content"] = m["thinking"]
            llamadas = []
            for llamada in m.get("tool_calls") or []:
                funcion = llamada.get("function") or {}
                argumentos = funcion.get("arguments")
                if not isinstance(argumentos, str):
                    argumentos = json.dumps(argumentos or {}, ensure_ascii=False)
                n += 1
                ident = llamada.get("id") or f"llamada_{n}"
                llamadas.append({"id": ident, "type": "function",
                                 "function": {"name": funcion.get("name", ""), "arguments": argumentos}})
                pendientes.append((ident, funcion.get("name", "")))
            if llamadas:
                nuevo["tool_calls"] = llamadas
        elif rol == "tool":
            nombre = m.get("tool_name") or m.get("name") or ""
            indice = next((i for i, (_, nom) in enumerate(pendientes) if nom == nombre), 0 if pendientes else None)
            if m.get("tool_call_id"):
                nuevo["tool_call_id"] = m["tool_call_id"]
            elif indice is not None:
                nuevo["tool_call_id"] = pendientes.pop(indice)[0]
        salida.append(nuevo)
    return salida


def a_openai(ruta: str, pedido: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """ Petición de Ollama → cuerpo para /v1/chat/completions, y los prefijos que llama-server
    repetirá al continuar un mensaje del asistente (hay que quitarlos de la respuesta). """
    if ruta.endswith("/api/generate"):
        mensajes = []
        if pedido.get("system"):
            mensajes.append({"role": "system", "content": pedido["system"]})
        mensajes.append({"role": "user", "content": pedido.get("prompt") or ""})
    else:
        mensajes = list(pedido.get("messages") or [])
    cuerpo: Dict[str, Any] = {"messages": _mensajes(mensajes), "stream": pedido.get("stream", True) is not False}
    opciones = pedido.get("options") or {}
    for de, a in OPCIONES.items():
        if opciones.get(de) is not None:
            cuerpo[a] = opciones[de]
    tope = opciones.get("num_predict")
    if tope is not None and int(tope) > 0:
        cuerpo["max_tokens"] = int(tope)
    if pedido.get("think") is not None:
        cuerpo["chat_template_kwargs"] = {"enable_thinking": bool(pedido["think"])}
    formato = pedido.get("format")
    if formato == "json":
        cuerpo["response_format"] = {"type": "json_object"}
    elif isinstance(formato, dict):
        cuerpo["response_format"] = {"type": "json_schema", "json_schema": {"name": "respuesta", "schema": formato}}
    if pedido.get("tools"):
        cuerpo["tools"] = pedido["tools"]
    if pedido.get("logprobs"):
        cuerpo["logprobs"] = True
        if pedido.get("top_logprobs"):
            cuerpo["top_logprobs"] = int(pedido["top_logprobs"])
    prefijos = {"content": "", "thinking": ""}
    if mensajes and mensajes[-1].get("role") == "assistant":
        prefijos = {"content": mensajes[-1].get("content") or "", "thinking": mensajes[-1].get("thinking") or ""}
    return cuerpo, prefijos


class _Prefijo:
    """ Quita de la respuesta el texto que ya tenía el mensaje del asistente que se continúa """

    def __init__(self, texto: str):
        self.resto = texto or ""

    def filtrar(self, trozo: str) -> str:
        if not self.resto or not trozo:
            return trozo
        if trozo.startswith(self.resto):
            trozo, self.resto = trozo[len(self.resto):], ""
            return trozo
        if self.resto.startswith(trozo):
            self.resto = self.resto[len(trozo):]
            return ""
        self.resto = ""
        return trozo


def _final(ruta: str, motivo: Optional[str], timings: Dict[str, Any], carga_s: float,
           llamadas: List[Dict[str, Any]], contexto: Optional[int] = None,
           proyecto: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ms = lambda v: int(float(v or 0) * 1e6)   # noqa: E731  ms → ns
    datos: Dict[str, Any] = {
        "model": NOMBRE, "done": True, "done_reason": {"length": "length"}.get(motivo or "", "stop"),
        "prompt_eval_count": int(timings.get("prompt_n") or 0),
        "prompt_eval_duration": ms(timings.get("prompt_ms")),
        "eval_count": int(timings.get("predicted_n") or 0),
        "eval_duration": ms(timings.get("predicted_ms")),
        "load_duration": int(carga_s * 1e9),
    }
    if proyecto:
        # el proyecto se leyó (o se restauró) antes de la pregunta: cuenta como lectura
        datos["prompt_eval_count"] += int(proyecto.get("leidos") or 0)
        datos["prompt_eval_duration"] += int(float(proyecto.get("lectura_ms") or 0) * 1e6)
        datos["proyecto"] = proyecto
    datos["total_duration"] = datos["prompt_eval_duration"] + datos["eval_duration"] + datos["load_duration"]
    if contexto:
        datos["contexto"] = contexto        # el real del motor (el automático crece con la petición)
    if ruta.endswith("/api/generate"):
        datos["response"] = ""
    else:
        mensaje: Dict[str, Any] = {"role": "assistant", "content": ""}
        if llamadas:
            mensaje["tool_calls"] = llamadas
        datos["message"] = mensaje
    return datos


def _llamadas(parciales: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    llamadas = []
    for i in sorted(parciales):
        p = parciales[i]
        try:
            argumentos = json.loads(p.get("argumentos") or "{}")
        except ValueError:
            argumentos = {"_texto": p.get("argumentos")}
        llamadas.append({"id": p.get("id"), "function": {"name": p.get("nombre", ""), "arguments": argumentos}})
    return llamadas


def _logprobs(eleccion: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"token": c.get("token"), "logprob": c.get("logprob"),
             "top_logprobs": [{"token": a.get("token"), "logprob": a.get("logprob")} for a in (c.get("top_logprobs") or [])]}
            for c in ((eleccion.get("logprobs") or {}).get("content") or [])]


def a_ollama(ruta: str, lineas: Iterator[str], prefijos: Dict[str, str], carga_s: float = 0.0,
             contexto: Optional[int] = None, proyecto: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
    """ Flujo SSE de llama-server → objetos NDJSON de Ollama (uno por trozo y el final con métricas) """
    generar = ruta.endswith("/api/generate")
    texto, razonamiento = _Prefijo(prefijos.get("content", "")), _Prefijo(prefijos.get("thinking", ""))
    parciales: Dict[int, Dict[str, Any]] = {}
    motivo, timings = None, {}
    for linea in lineas:
        if not linea or not linea.startswith("data:"):
            continue
        dato = linea[5:].strip()
        if dato == "[DONE]":
            break
        try:
            trozo = json.loads(dato)
        except ValueError:
            continue
        if trozo.get("error"):
            yield {"error": (trozo["error"] or {}).get("message") if isinstance(trozo["error"], dict) else str(trozo["error"])}
            return
        timings = trozo.get("timings") or timings
        for eleccion in trozo.get("choices") or []:
            delta = eleccion.get("delta") or {}
            motivo = eleccion.get("finish_reason") or motivo
            for llamada in delta.get("tool_calls") or []:
                p = parciales.setdefault(int(llamada.get("index", 0)), {})
                if llamada.get("id"):
                    p["id"] = llamada["id"]
                funcion = llamada.get("function") or {}
                if funcion.get("name"):
                    p["nombre"] = funcion["name"]
                p["argumentos"] = p.get("argumentos", "") + (funcion.get("arguments") or "")
            pensado = razonamiento.filtrar(delta.get("reasoning_content") or "")
            escrito = texto.filtrar(delta.get("content") or "")
            probabilidades = _logprobs(eleccion)
            if not (pensado or escrito or probabilidades):
                continue
            if generar:
                salida: Dict[str, Any] = {"model": NOMBRE, "response": escrito, "done": False}
                if pensado:
                    salida["thinking"] = pensado
            else:
                mensaje: Dict[str, Any] = {"role": "assistant", "content": escrito}
                if pensado:
                    mensaje["thinking"] = pensado
                salida = {"model": NOMBRE, "message": mensaje, "done": False}
            if probabilidades:
                salida["logprobs"] = probabilidades
            yield salida
    yield _final(ruta, motivo, timings, carga_s, _llamadas(parciales), contexto, proyecto)


def a_ollama_completo(ruta: str, respuesta: Dict[str, Any], prefijos: Dict[str, str], carga_s: float = 0.0,
                      contexto: Optional[int] = None, proyecto: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """ Respuesta sin streaming de llama-server → la de Ollama """
    eleccion = (respuesta.get("choices") or [{}])[0]
    mensaje = eleccion.get("message") or {}
    texto = _Prefijo(prefijos.get("content", "")).filtrar(mensaje.get("content") or "")
    pensado = _Prefijo(prefijos.get("thinking", "")).filtrar(mensaje.get("reasoning_content") or "")
    parciales = {i: {"id": c.get("id"), "nombre": (c.get("function") or {}).get("name"),
                     "argumentos": (c.get("function") or {}).get("arguments")}
                 for i, c in enumerate(mensaje.get("tool_calls") or [])}
    datos = _final(ruta, eleccion.get("finish_reason"), respuesta.get("timings") or {}, carga_s, _llamadas(parciales),
                   contexto, proyecto)
    if ruta.endswith("/api/generate"):
        datos["response"] = texto
        if pensado:
            datos["thinking"] = pensado
    else:
        datos["message"]["content"] = texto
        if pensado:
            datos["message"]["thinking"] = pensado
    if eleccion.get("logprobs"):
        datos["logprobs"] = _logprobs(eleccion)
    return datos


# ---------------------------------------------------------------------------------------------
# Respuesta con la interfaz de requests.Response que usa el motor de IA
# ---------------------------------------------------------------------------------------------

class Respuesta:
    """ status_code, iter_lines() (NDJSON de Ollama), json(), text y close() """

    def __init__(self, status_code: int, objetos: Optional[Iterator[Dict[str, Any]]] = None,
                 cuerpo: Optional[Dict[str, Any]] = None, subyacente=None, al_cerrar: Optional[Callable] = None):
        self.status_code = status_code
        self._objetos = objetos
        self._cuerpo = cuerpo
        self._subyacente = subyacente
        self._al_cerrar = al_cerrar
        self._cerrada = False

    def iter_lines(self) -> Iterator[bytes]:
        try:
            if self._cuerpo is not None:
                yield json.dumps(self._cuerpo, ensure_ascii=False).encode("utf-8")
                return
            for objeto in self._objetos or ():
                if self._cerrada:
                    return
                yield json.dumps(objeto, ensure_ascii=False).encode("utf-8")
        finally:
            self.close()

    def json(self) -> Dict[str, Any]:
        if self._cuerpo is None:
            ultimo: Dict[str, Any] = {}
            for linea in self.iter_lines():
                ultimo = json.loads(linea)
            self._cuerpo = ultimo
        return self._cuerpo

    @property
    def text(self) -> str:
        return json.dumps(self.json(), ensure_ascii=False)

    def close(self):
        if self._cerrada:
            return
        self._cerrada = True
        # Cerrar la conexión hace que llama-server deje de generar (como con Ollama)
        if self._subyacente is not None:
            try:
                self._subyacente.close()
            except Exception:
                pass
        if self._al_cerrar is not None:
            self._al_cerrar()


def _error(status: int, mensaje: str) -> Respuesta:
    return Respuesta(status, cuerpo={"error": mensaje})


# ---------------------------------------------------------------------------------------------
# El servidor
# ---------------------------------------------------------------------------------------------

class Motor:
    """ Un llama-server propio para el modelo MoE: arranca bajo demanda y se para sin uso """

    ESPERA_ARRANQUE_S = 240

    def __init__(self, liberar_gpu: Optional[Callable[[], None]] = None,
                 ajustes: Optional[Callable[[], Dict[str, Any]]] = None):
        self.liberar_gpu = liberar_gpu
        self.ajustes = ajustes or (lambda: {})
        self._cerrojo = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._puerto: Optional[int] = None
        self.calientes = 0
        self.mtp = False
        self.modo = MODO
        self.contexto = CONTEXTO_INICIAL
        self._contexto_pedido = CONTEXTO_INICIAL    # contexto automático: crece con las peticiones
        self._proyecto_cargado: Optional[str] = None  # clave del proyecto cuyo estado EXACTO tiene el motor
        self.ultimo_proyecto: Dict[str, Any] = {}
        self.nucleos: List[int] = []
        self._activas = 0
        self._ultimo_uso = 0.0
        self._keep_alive_s = 300.0
        self._vigia: Optional[threading.Thread] = None
        self.ultimo_error = ""

    # -- estado ----------------------------------------------------------------------------
    def contexto_deseado(self, a: Optional[Dict[str, Any]] = None) -> int:
        """ El fijado en los ajustes o, en automático, el que pidió la petición más grande """
        a = self.ajustes() if a is None else a
        valor = (a or {}).get("contexto")
        if valor in (None, "", "auto"):
            return max(CONTEXTO_INICIAL, self._contexto_pedido)
        return max(2048, min(CONTEXTO_MAX, int(valor)))

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

    def en_marcha(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def pid(self) -> Optional[int]:
        return self._proc.pid if self.en_marcha() else None

    def estado(self) -> Dict[str, Any]:
        version = ""
        try:
            with open(os.path.join(LIB, "VERSION")) as f:
                version = f.read().strip()
        except OSError:
            pass
        return {**self.disponible(), "nombre": NOMBRE, "en_marcha": self.en_marcha(), "pid": self.pid(),
                "puerto": self._puerto if self.en_marcha() else None, "calientes_por_capa": self.calientes,
                "mtp": self.mtp, "modo": self.modo,
                "contexto": self.contexto, "nucleos": self.nucleos, "activas": self._activas,
                "keep_alive_s": self._keep_alive_s, "ultimo_error": self.ultimo_error, "version": version,
                "proyectos": {**proyectos_guardados(), "ultimo": self.ultimo_proyecto}}

    # -- ciclo de vida ---------------------------------------------------------------------
    def _registro(self, texto: str):
        try:
            with open(REGISTRO, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
        except OSError:
            pass

    @staticmethod
    def _puerto_libre() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def orden(self, blob: str, calientes: int, mtp: bool = False) -> Tuple[List[str], Dict[str, str], str]:
        """ Comando, entorno y modo con que se lanza llama-server """
        a = self.ajustes() or {}
        self.contexto = self.contexto_deseado(a)
        lote = lote_para(self.contexto)
        self.nucleos = nucleos_rendimiento()
        hilos = int(a.get("hilos") or 0) or min(4, len(self.nucleos) or 4)
        self._puerto = self._puerto_libre()
        cmd = [SERVIDOR, "-m", blob, "-ngl", "99", "--n-cpu-moe", "99", "-c", str(self.contexto),
               "-t", str(hilos), "-tb", str(hilos), "--no-mmap", "-fa", "on", "--jinja", "-np", "1",
               "--host", "127.0.0.1", "--port", str(self._puerto), "--no-webui",
               # leer el prompt en lotes grandes: la GPU trae cada experto una vez para más tokens
               "-ub", str(lote), "-b", str(lote),
               # caché de atención en 8 bits: la mitad de VRAM (256K tokens caben en 6 GB)
               "-ctk", "q8_0", "-ctv", "q8_0",
               # lo ya leído queda en RAM: volver a un proyecto no obliga a releerlo
               "--cache-ram", str(CACHE_RAM_MB),
               # y los proyectos, también en disco (entre sesiones)
               "--slot-save-path", CARPETA_PROYECTOS]
        os.makedirs(CARPETA_PROYECTOS, exist_ok=True)
        if mtp:
            # la cabeza MTP del modelo propone 2 tokens y el modelo los verifica de una vez
            # (medido: acierta el 80–92 %; el resultado es el mismo que sin ella)
            cmd += ["--spec-type", "draft-mtp", "--spec-draft-n-max", "2"]
        env = dict(os.environ)
        env.pop("LD_LIBRARY_PATH", None)             # las bibliotecas van junto al binario ($ORIGIN)
        for clave in [k for k in env if k.startswith("AIPC_")]:
            env.pop(clave)                           # solo lo que decide este motor
        modo = str(a.get("modo") or MODO)
        if modo not in MODOS:
            modo = MODO
        if calientes > 0:
            env.update({"AIPC_MOE_HOT_LIST": LISTA, "AIPC_MOE_HOT_N": str(calientes),
                        "AIPC_NO_PAD": "1", "AIPC_COLD_SKIP": "1",
                        # la CPU calcula los fríos mientras la GPU calcula los calientes
                        "AIPC_OVERLAP": "1"})
            if MODOS[modo]:
                env["AIPC_COLD_DROP"] = str(MODOS[modo])
        nucleos = self.nucleos[:hilos] if self.nucleos else None
        if nucleos and shutil.which("taskset"):
            # desde el arranque: los hilos de cálculo nacen ya en los núcleos P
            cmd = ["taskset", "-c", ",".join(map(str, nucleos))] + cmd
        self._registro(f"arranque: {calientes} calientes/capa, contexto {self.contexto}, núcleos {nucleos}, "
                       f"MTP {'sí' if mtp else 'no'}, modo {modo}")
        return cmd, env, modo

    def _lanzar(self, blob: str, calientes: int, mtp: bool = False) -> bool:
        cmd, env, modo = self.orden(blob, calientes, mtp)
        registro = open(REGISTRO, "a", encoding="utf-8")
        try:
            self._proc = subprocess.Popen(cmd, env=env, stdout=registro, stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL, start_new_session=True)
        finally:
            registro.close()
        t0 = time.time()
        while time.time() - t0 < self.ESPERA_ARRANQUE_S:
            if self._proc.poll() is not None:
                return False
            try:
                if requests.get(f"http://127.0.0.1:{self._puerto}/health", timeout=2).status_code == 200:
                    self.calientes, self.mtp, self.modo = calientes, mtp, modo
                    return True
            except requests.RequestException:
                pass
            time.sleep(0.5)
        self._parar_proceso()
        return False

    def asegurar(self) -> float:
        """ Arranca el servidor si hace falta; devuelve los segundos de carga (0 si ya estaba) """
        with self._cerrojo:
            if self.en_marcha():
                return 0.0
            disp = self.disponible()
            if not disp["disponible"]:
                raise RuntimeError(disp["motivo"])
            t0 = time.time()
            if self.liberar_gpu is not None:
                try:
                    self.liberar_gpu()
                except Exception:
                    pass
            a = self.ajustes() or {}
            contexto = self.contexto_deseado(a)
            mtp = a.get("mtp", True) is not False
            pedido = a.get("calientes")
            automatico = pedido in (None, "", "auto")
            libre = vram_libre_estable() if automatico else None
            intentos: List[Tuple[int, bool]] = []
            for con_mtp in ([True, False] if mtp and cabe_mtp(libre, contexto) else [False]):
                n = calientes_para(libre, contexto, con_mtp) if automatico else int(pedido)
                # Si no cabe (otro programa ocupó la GPU), menos expertos calientes; si ni así, sin MTP
                intentos += [(n, con_mtp), (max(0, n - 8), con_mtp)]
            intentos.append((0, False))
            for n, con_mtp in dict.fromkeys(intentos):
                if self._lanzar(disp["modelo"], n, con_mtp):
                    self.ultimo_error = ""
                    self._arrancar_vigia()
                    return time.time() - t0
                self._registro(f"no arrancó con {n} calientes/capa{' y MTP' if con_mtp else ''}")
            self.ultimo_error = f"llama-server no arrancó (ver {REGISTRO})"
            raise RuntimeError(self.ultimo_error)

    def _preparar_proyecto(self, cuerpo: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """ Deja el motor con el estado exacto tras leer el proyecto (el primer mensaje grande):
        restaurado de disco si ya se leyó alguna vez, si no leyéndolo y guardándolo. La pregunta
        que sigue solo lee lo nuevo. None si la conversación no empieza con un bloque grande. """
        prefijo = prefijo_de(cuerpo)
        if not prefijo:
            return None
        base = f"http://127.0.0.1:{self._puerto}"
        try:
            r = requests.post(base + "/apply-template", timeout=60, json={
                "messages": prefijo, "tools": cuerpo.get("tools"), "add_generation_prompt": False,
                "chat_template_kwargs": cuerpo.get("chat_template_kwargs") or {}})
            texto = r.json().get("prompt") if r.status_code == 200 else None
        except (requests.RequestException, ValueError):
            texto = None
        if not texto:
            return None
        try:
            with open(os.path.join(LIB, "VERSION")) as f:
                version = f.read()
        except OSError:
            version = ""
        huella = hashlib.sha256(f"{version}|{blob_del_modelo()}|{self.modo}|".encode() + texto.encode())
        clave = huella.hexdigest()[:32]
        archivo = clave + ".bin"
        ruta = os.path.join(CARPETA_PROYECTOS, archivo)
        if self._proyecto_cargado == clave:
            return None                          # el motor ya está justo al final del proyecto
        t0 = time.time()
        if os.path.exists(ruta):
            try:
                r = requests.post(base + "/slots/0?action=restore", json={"filename": archivo}, timeout=600)
                if r.status_code == 200:
                    os.utime(ruta)               # usado ahora: el último en borrarse
                    self._proyecto_cargado = clave
                    self.ultimo_proyecto = {"origen": "disco", "tokens": r.json().get("n_restored"),
                                            "segundos": round(time.time() - t0, 2)}
                    self._registro(f"proyecto {clave[:8]} restaurado: {self.ultimo_proyecto}")
                    return dict(self.ultimo_proyecto)
            except requests.RequestException:
                pass
            try:
                os.remove(ruta)                  # no se pudo restaurar (otra versión…): se vuelve a leer
            except OSError:
                pass
        try:
            r = requests.post(base + "/completion", timeout=7200,
                              json={"prompt": texto, "n_predict": 0, "cache_prompt": True})
            if r.status_code != 200:
                return None
            datos = r.json()
            leidos = int(datos.get("tokens_evaluated") or 0)
            lectura_ms = float((datos.get("timings") or {}).get("prompt_ms") or 0)
            g = requests.post(base + "/slots/0?action=save", json={"filename": archivo}, timeout=600)
        except (requests.RequestException, ValueError):
            return None
        if g.status_code == 200:
            self._proyecto_cargado = clave
            podar_proyectos()
        self.ultimo_proyecto = {"origen": "leido", "tokens": leidos, "segundos": round(time.time() - t0, 1),
                                "guardado": g.status_code == 200}
        self._registro(f"proyecto {clave[:8]} leído: {self.ultimo_proyecto}")
        return {**self.ultimo_proyecto, "leidos": leidos, "lectura_ms": lectura_ms}

    def olvidar_proyectos(self) -> int:
        """ Borra los proyectos guardados en disco """
        n = 0
        for a in glob.glob(os.path.join(CARPETA_PROYECTOS, "*.bin")):
            try:
                os.remove(a)
                n += 1
            except OSError:
                pass
        self._proyecto_cargado = None
        return n

    def _crecer(self, objetivo: int) -> bool:
        """ Contexto automático: si la petición no cabe, se reinicia con uno mayor (≈15 s) """
        with self._cerrojo:
            if objetivo <= self._contexto_pedido and (not self.en_marcha() or self.contexto >= objetivo):
                return False
            self._contexto_pedido = max(self._contexto_pedido, objetivo)
            if self.en_marcha() and self.contexto < objetivo:
                if self._activas:
                    return False            # otra respuesta en curso: no se corta
                self._registro(f"contexto {self.contexto} → {objetivo}: reinicio")
                self._parar_proceso()
            return True

    def _parar_proceso(self):
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            os.kill(proc.pid, signal.SIGCONT)         #: por si el modo frío lo dejó en pausa
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def detener(self):
        with self._cerrojo:
            if self._proc is not None:
                self._registro("parado")
            self._parar_proceso()

    def _arrancar_vigia(self):
        if self._vigia is not None and self._vigia.is_alive():
            return
        self._vigia = threading.Thread(target=self._vigilar, name="motor-moe", daemon=True)
        self._vigia.start()

    def _vigilar(self):
        while self.en_marcha():
            time.sleep(5)
            with self._cerrojo:
                if (self._activas == 0 and self._keep_alive_s >= 0
                        and time.time() - self._ultimo_uso > self._keep_alive_s):
                    self._registro(f"sin uso durante {self._keep_alive_s:.0f} s")
                    self._parar_proceso()

    # -- peticiones ------------------------------------------------------------------------
    def post(self, url: str, pedido: Dict[str, Any], timeout: float = 600, _reintento: bool = False) -> Respuesta:
        """ Una petición de Ollama (/api/chat o /api/generate) servida por este motor """
        ruta = url.split("?", 1)[0]
        vacia = not pedido.get("messages") and not pedido.get("prompt")
        if vacia:
            # Ollama: sin mensajes solo carga o descarga el modelo (keep_alive 0 = descargar)
            if segundos_keep_alive(pedido.get("keep_alive")) == 0:
                self.detener()
            else:
                try:
                    self.asegurar()
                except RuntimeError as e:
                    return _error(500, str(e))
            return Respuesta(200, cuerpo=_final(ruta, "stop", {}, 0.0, []))
        automatico = (self.ajustes() or {}).get("contexto") in (None, "", "auto")
        necesarios = estimar_tokens(pedido)
        if automatico:
            objetivo = contexto_para(necesarios)
            if objetivo is None:
                return _error(400, f"La petición necesita ~{necesarios:,} tokens y el máximo del modelo es "
                                   f"{CONTEXTO_MAX:,}: divide el proyecto o pregunta por partes.".replace(",", "."))
            self._crecer(objetivo)
        with self._cerrojo:
            # arrancar y contar la petición juntos: el vigía no puede pararlo entre medio
            try:
                carga_s = self.asegurar()
            except RuntimeError as e:
                return _error(500, str(e))
            self._activas += 1
            self._ultimo_uso = time.time()
        self._keep_alive_s = segundos_keep_alive(pedido.get("keep_alive"), self._keep_alive_s)
        cuerpo, prefijos = a_openai(ruta, pedido)

        def terminar():
            with self._cerrojo:
                self._activas = max(0, self._activas - 1)
                self._ultimo_uso = time.time()

        # Tras esta respuesta el motor ya no está justo al final del proyecto (se restaurará)
        proyecto = self._preparar_proyecto(cuerpo) if ruta.endswith("/api/chat") else None
        self._proyecto_cargado = None
        try:
            res = requests.post(f"http://127.0.0.1:{self._puerto}/v1/chat/completions", json=cuerpo,
                                stream=cuerpo["stream"], timeout=timeout)
        except requests.RequestException as e:
            terminar()
            return _error(503, f"El motor MoE no responde: {e}")
        if res.status_code != 200:
            try:
                error = res.json().get("error")
            except ValueError:
                error = res.text
            detalle = error.get("message") if isinstance(error, dict) else error
            res.close()
            terminar()
            # La estimación por caracteres se quedó corta: llama-server dice cuántos tokens son
            if (automatico and not _reintento and isinstance(error, dict)
                    and error.get("type") == "exceed_context_size_error"):
                tope = int((pedido.get("options") or {}).get("num_predict") or 0)
                objetivo = contexto_para(int(error.get("n_prompt_tokens") or 0) + (tope if tope > 0 else 4096) + 512)
                if objetivo and self._crecer(objetivo):
                    return self.post(url, pedido, timeout, _reintento=True)
            return _error(res.status_code, str(detalle or "")[:500])
        if not cuerpo["stream"]:
            try:
                datos = a_ollama_completo(ruta, res.json(), prefijos, carga_s, self.contexto, proyecto)
            finally:
                res.close()
                terminar()
            return Respuesta(200, cuerpo=datos)
        lineas = (l.decode("utf-8", "replace") if isinstance(l, bytes) else l for l in res.iter_lines())
        return Respuesta(200, objetos=a_ollama(ruta, lineas, prefijos, carga_s, self.contexto, proyecto),
                         subyacente=res, al_cerrar=terminar)


def servidores_huerfanos() -> List[int]:
    """ llama-server de este motor que siguen vivos sin su Prig (se lanzan en su propia sesión) """
    propios = set()
    if _motor is not None and _motor.pid():
        propios.add(_motor.pid())
    pids = []
    real = os.path.realpath(SERVIDOR)
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in propios:
            continue
        try:
            if os.path.realpath(f"/proc/{d}/exe") == real and os.stat(f"/proc/{d}").st_uid == os.getuid():
                pids.append(int(d))
        except OSError:
            pass
    return pids


def limpiar_huerfanos() -> int:
    """ Al abrir Prig: cierra los servidores MoE que dejó una sesión anterior (liberan la VRAM) """
    pids = servidores_huerfanos()
    for pid in pids:
        for sig in (signal.SIGCONT, signal.SIGTERM):
            try:
                os.kill(pid, sig)
            except OSError:
                pass
    return len(pids)


_motor: Optional[Motor] = None
_motor_cerrojo = threading.Lock()


def motor(liberar_gpu: Optional[Callable[[], None]] = None,
          ajustes: Optional[Callable[[], Dict[str, Any]]] = None) -> Motor:
    global _motor
    with _motor_cerrojo:
        if _motor is None:
            _motor = Motor(liberar_gpu, ajustes)
        else:
            if liberar_gpu is not None:
                _motor.liberar_gpu = liberar_gpu
            if ajustes is not None:
                _motor.ajustes = ajustes
        return _motor


def generando() -> bool:
    """ ¿Hay alguna respuesta en curso en el motor MoE? """
    return _motor is not None and _motor.en_marcha() and _motor._activas > 0


def pid_en_marcha() -> Optional[int]:
    return _motor.pid() if _motor is not None else None
