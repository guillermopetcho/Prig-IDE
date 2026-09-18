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
"""

import json
import os
import re
import threading
import urllib.request
from typing import Any, Dict, List, Optional

from .gguf import leer_con_rangos

OLLAMA = os.environ.get("PRIG_OLLAMA_URL", "http://localhost:11434")
REGISTRO = "https://registry.ollama.ai"
CACHE = os.path.expanduser("~/.prig_recursos_fichas.json")

# Bytes por elemento de la caché KV según su tipo
BYTES_KV = {"f16": 2.0, "q8_0": 1.0625, "q4_0": 0.5625}

_lock = threading.Lock()


# ===========================================================================
# Construcción de la ficha a partir de metadatos
# ===========================================================================

def _entero(v) -> Optional[int]:
    """ Algunos modelos dan un valor por capa (una lista): se toma el mayor, que
    es el que manda al reservar memoria. """
    if isinstance(v, list):
        v = max((x for x in v if isinstance(x, (int, float))), default=None)
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def desde_metadatos(meta: Dict[str, Any], nombre: str, bytes_peso: int,
                    capacidades: Optional[List[str]] = None,
                    plantilla: str = "", origen: str = "ollama",
                    cuantizacion: str = "") -> Dict[str, Any]:
    arch = meta.get("general.architecture") or ""

    def m(clave):
        return meta.get(f"{arch}.{clave}")

    capas = _entero(m("block_count")) or 0
    cabezas = _entero(m("attention.head_count")) or 0
    cabezas_kv = _entero(m("attention.head_count_kv")) or cabezas
    embedding = _entero(m("embedding_length")) or 0
    dim_k = _entero(m("attention.key_length")) or (embedding // cabezas if cabezas else 0)
    dim_v = _entero(m("attention.value_length")) or dim_k
    contexto = _entero(m("context_length")) or 0

    expertos = _entero(m("expert_count")) or 0
    usados = _entero(m("expert_used_count")) or 0
    ff_experto = _entero(m("expert_feed_forward_length")) or 0
    es_moe = expertos > 1 and usados > 0

    parametros = _entero(meta.get("general.parameter_count"))
    if not parametros:
        # Sin el recuento declarado, se deduce del tamaño y de los bits de la
        # cuantización. Es una aproximación: sirve para ordenar, no para medir.
        bits = {"Q4_K_M": 4.85, "Q4_0": 4.5, "Q5_K_M": 5.7, "Q8_0": 8.5,
                "F16": 16, "BF16": 16}.get((cuantizacion or "").upper(), 4.85)
        parametros = int(bytes_peso * 8 / bits) if bytes_peso else 0

    # Parámetros que se leen por cada token. En un modelo denso, todos. En un MoE,
    # todo menos los expertos que no se usan: es lo que decide la velocidad
    # cuando buena parte del modelo vive en la RAM.
    activos = parametros
    if es_moe and capas and embedding and ff_experto:
        por_expertos = capas * expertos * 3 * embedding * ff_experto
        activos = max(1, int(parametros - por_expertos * (1 - usados / expertos)))

    # Caché KV por token, en f16: 2 (K y V) × capas × cabezas KV × dimensión
    kv_por_token = capas * cabezas_kv * (dim_k + dim_v)

    caps = set(capacidades or [])
    embedding_puro = ("embedding" in caps
                      or meta.get(f"{arch}.pooling_type") is not None
                      or meta.get(f"{arch}.attention.causal") is False)
    plantilla = plantilla or str(meta.get("tokenizer.chat_template") or "")
    piensa = ("thinking" in caps
              or bool(re.search(r"<think>|enable_thinking|reasoning_content", plantilla)))

    return {
        "nombre": nombre,
        "origen": origen,
        "arquitectura": arch,
        "cuantizacion": cuantizacion or meta.get("general.file_type") or "",
        "bytes_peso": int(bytes_peso or 0),
        "parametros": parametros,
        "parametros_activos": activos,
        "fraccion_activa": round(activos / parametros, 4) if parametros else 1.0,
        "capas": capas,
        "cabezas_kv": cabezas_kv,
        "dim_cabeza": dim_k,
        "kv_bytes_token_f16": kv_por_token * 2,
        "contexto_max": contexto,
        "es_moe": es_moe,
        "expertos": expertos,
        "expertos_usados": usados,
        "embedding": embedding_puro,
        "piensa": piensa,
        "herramientas": "tools" in caps,
        "vision": "vision" in caps or f"{arch}.vision.block_count" in meta,
        "estimada": origen == "catalogo",
    }


def kv_bytes(ficha: Dict[str, Any], contexto: int, paralelo: int = 1,
             tipo: str = "f16") -> int:
    """ Caché KV para un contexto y un número de peticiones simultáneas.

    Cada ranura en paralelo reserva su propia caché: dos ranuras de 4096 ocupan
    lo mismo que una de 8192. Por eso subir el paralelo no es gratis.
    """
    por_token = ficha.get("kv_bytes_token_f16", 0) / 2 * BYTES_KV.get(tipo, 2.0)
    return int(por_token * contexto * max(1, paralelo))


# ===========================================================================
# Fuentes
# ===========================================================================

def _post(ruta: str, cuerpo: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(OLLAMA + ruta, data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get(url: str, timeout: int = 20, cabeceras: Optional[dict] = None):
    req = urllib.request.Request(url, headers=cabeceras or {})
    return urllib.request.urlopen(req, timeout=timeout)


def instalados() -> Dict[str, Dict[str, Any]]:
    """ Nombre → {tamaño, digest, detalles} de lo que Ollama tiene descargado """
    with _get(OLLAMA + "/api/tags", timeout=10) as r:
        return {m["name"]: m for m in json.load(r).get("models", [])}


def desde_ollama(nombre: str) -> Dict[str, Any]:
    inst = instalados()
    clave = nombre if nombre in inst else f"{nombre}:latest"
    if clave not in inst:
        raise LookupError(f"'{nombre}' no está instalado")
    datos = _post("/api/show", {"model": clave})
    detalles = datos.get("details") or {}
    return desde_metadatos(
        datos.get("model_info") or {}, clave, inst[clave].get("size", 0),
        capacidades=datos.get("capabilities") or [],
        plantilla=datos.get("template") or "",
        origen="ollama",
        cuantizacion=detalles.get("quantization_level", ""))


# Registros compatibles con Ollama (verificado: los tres sirven manifiestos y blobs)
REGISTROS_EXTERNOS = {"hf.co": "https://hf.co", "huggingface.co": "https://hf.co",
                      "modelscope.cn": "https://modelscope.cn"}


def registro_de(nombre: str):
    """ (url del registro, repo, etiqueta) para cualquier nombre que Ollama descarga:
    "qwen3:8b", "usuario/modelo:tag", "hf.co/org/repo:Q4_K_M", "modelscope.cn/org/repo:q4_k_m" """
    host, _, resto = nombre.partition("/")
    if host in REGISTROS_EXTERNOS and resto:
        base, _, tag = resto.partition(":")
        return REGISTROS_EXTERNOS[host], base, (tag or "latest")
    base, _, tag = nombre.partition(":")
    return REGISTRO, (base if "/" in base else f"library/{base}"), (tag or "latest")


def _separar(nombre: str):
    """ "qwen3:8b" → ("library/qwen3", "8b"); "usuario/modelo:tag" también vale """
    _, repo, tag = registro_de(nombre)
    return repo, tag


def desde_registro(nombre: str) -> Dict[str, Any]:
    """ Ficha de un modelo SIN descargarlo: solo la cabecera GGUF por rangos.

    Se guarda en caché por el digest de la capa: un blob con el mismo digest es el
    mismo modelo, así que no hay que volver a leerlo nunca.
    """
    registro, repo, tag = registro_de(nombre)
    with _get(f"{registro}/v2/{repo}/manifests/{tag}",
              cabeceras={"Accept": "application/vnd.docker.distribution.manifest.v2+json"}) as r:
        manifiesto = json.load(r)
    capas = manifiesto.get("layers", [])
    capa = next((l for l in capas if l.get("mediaType", "").endswith("image.model")), None)
    if not capa:
        raise LookupError(f"'{nombre}' no tiene capa de modelo en el registro")

    cache = _leer_cache()
    if capa["digest"] in cache:
        return {**cache[capa["digest"]], "nombre": nombre}

    url = f"{registro}/v2/{repo}/blobs/{capa['digest']}"

    def pedir(desde: int, hasta: int) -> bytes:
        # requests y no urllib: el CDN de ModelScope responde 206 pero urllib lee 0 bytes
        # (IncompleteRead); con requests funciona, y también con Ollama y Hugging Face
        import requests
        r = requests.get(url, headers={"Range": f"bytes={desde}-{hasta}"}, timeout=90)
        r.raise_for_status()
        return r.content

    meta = leer_con_rangos(pedir)

    # La plantilla va en su propia capa y es pequeña: dice si el modelo piensa
    plantilla = ""
    tcapa = next((l for l in capas if l.get("mediaType", "").endswith("image.template")), None)
    if tcapa and tcapa.get("size", 0) < 512 * 1024:
        try:
            with _get(f"{registro}/v2/{repo}/blobs/{tcapa['digest']}", timeout=30) as r:
                plantilla = r.read().decode("utf-8", errors="replace")
        except Exception:
            plantilla = ""

    cuant = ""
    m = re.search(r"(q\d_k_[sml]|q\d_\d|f16|bf16|q8_0)", tag, re.I)
    if m:
        cuant = m.group(1).upper()
    ficha = desde_metadatos(meta, nombre, capa["size"], plantilla=plantilla,
                            origen="registro", cuantizacion=cuant or "Q4_K_M")
    cache[capa["digest"]] = ficha
    _guardar_cache(cache)
    return ficha


def desde_catalogo(nombre: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """ Último recurso, sin red: estimada a partir del tamaño del catálogo.

    La caché KV se estima por lo alto (20 KB por cada mil millones de parámetros)
    para que un modelo desconocido nunca salga como "cabe" cuando no cabe.
    """
    gb = float(info.get("vram_gb") or 0)
    params = int(gb * 1e9 * 8 / 4.85)
    return {
        "nombre": nombre, "origen": "catalogo", "arquitectura": info.get("familia", ""),
        "cuantizacion": "Q4_K_M", "bytes_peso": int(gb * 1e9),
        "parametros": params, "parametros_activos": params, "fraccion_activa": 1.0,
        "capas": 0, "cabezas_kv": 0, "dim_cabeza": 0,
        "kv_bytes_token_f16": int(params / 1e9 * 20_000),
        "contexto_max": 32768, "es_moe": False, "expertos": 0, "expertos_usados": 0,
        "embedding": bool(info.get("embedding")),
        "piensa": info.get("piensa") in ("conmutable", "siempre"),
        "herramientas": False, "vision": False, "estimada": True,
    }


def obtener(nombre: str, catalogo: Optional[Dict[str, Any]] = None,
            red: bool = True) -> Dict[str, Any]:
    """ La mejor ficha disponible, probando las fuentes en orden de fiabilidad """
    errores = []
    try:
        return desde_ollama(nombre)
    except Exception as e:
        errores.append(f"ollama: {e}")
    if red:
        try:
            return desde_registro(nombre)
        except Exception as e:
            errores.append(f"registro: {e}")
    if catalogo and nombre in catalogo:
        ficha = desde_catalogo(nombre, catalogo[nombre])
        ficha["avisos"] = errores
        return ficha
    raise LookupError(f"No hay ficha para '{nombre}': " + "; ".join(errores))


# ===========================================================================

def _leer_cache() -> Dict[str, Any]:
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar_cache(datos: Dict[str, Any]):
    with _lock:
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.replace(tmp, CACHE)
