"""
Buscador de modelos en las plataformas desde las que Ollama descarga.

No hace falta ningún complemento: Ollama descarga por sí solo de tres registros, y
así se verificó en esta máquina (Ollama 0.34.1) bajando un modelo pequeño de cada
uno, generando texto con él y borrándolo:

    ollama.com       smollm2:135m                                      271 MB
    Hugging Face     hf.co/bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K_M 105 MB
    ModelScope       modelscope.cn/Qwen/Qwen2.5-0.5B-Instruct-GGUF:q4_k_m  491 MB

Cómo se busca en cada una (verificado):

  · ollama.com no tiene API de búsqueda: la página /search tiene una estructura
    estable (nombre, descripción, capacidades, tamaños, descargas, fecha), acepta
    q, o=newest, c=<capacidad> y p=<página>, e incluye modelos de la comunidad
    (usuario/modelo). Las variantes salen de /<modelo>/tags.
  · Hugging Face tiene API oficial: /api/models con filter=gguf, orden por
    tendencia, descargas, me gusta, actualización o creación, y paginación por la
    cabecera Link. Los archivos y sus tamaños salen de /api/models/<repo>?blobs=true.
  · ModelScope tiene API oficial: /api/v1/dolphin/models (búsqueda) y
    /api/v1/models/<repo>/repo/files (archivos con tamaño).

Antes de descargar, cada variante se COMPRUEBA pidiendo su manifiesto al registro
correspondiente: si existe, se descarga seguro y se sabe su tamaño exacto; si no
(por ejemplo, un GGUF partido en varios archivos), se avisa en vez de fallar a mitad.
"""

import base64
import hashlib
import html
import json
import os
import re
import urllib.parse
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import requests

UA = {"User-Agent": "Prig-IDE (buscador de modelos local)"}
MANIFIESTO = {"Accept": "application/vnd.docker.distribution.manifest.v2+json", **UA}
# modelscope.cn da a Ollama un manifiesto con más campos que a otros clientes, y Ollama
# usa el sha256 de ese texto como digest del modelo: para poder compararlo hay que pedirlo
# igual. registry.ollama.ai, en cambio, responde 401 a ese User-Agent sin firma.
MANIFIESTO_COMO_OLLAMA = {**MANIFIESTO, "User-Agent": "ollama/0.34.1 (Prig)"}

FUENTES = {
    "ollama": {"nombre": "Ollama", "web": "https://ollama.com"},
    "huggingface": {"nombre": "Hugging Face", "web": "https://huggingface.co"},
    "modelscope": {"nombre": "ModelScope", "web": "https://modelscope.cn"},
}

ORDENES = {
    "ollama": {"relevancia": None, "recientes": "newest"},
    "huggingface": {"relevancia": "downloads", "descargas": "downloads", "tendencia": "trendingScore",
                    "me_gusta": "likes", "actualizados": "lastModified", "recientes": "createdAt"},
    "modelscope": {"relevancia": "Default", "descargas": "DownloadsCount", "actualizados": "GmtModified"},
}

CAPACIDADES_OLLAMA = ("tools", "thinking", "vision", "embedding", "audio", "cloud")

# "Q4_K_M", "UD-Q4_K_XL", "IQ3_XXS", "q4_k_m", "F16", "BF16", "MXFP4_MOE"…
_CUANT = re.compile(
    r"(?i)(?:^|[-_.])((?:UD-)?(?:IQ\d(?:_[A-Z]+)?|Q\d(?:_[A-Z0-9]+)*|TQ\d_\d|F16|F32|BF16|MXFP4(?:_MOE)?|NVFP4))$")
_PARTE = re.compile(r"(?i)-(\d{5})-of-(\d{5})$")
REF_VALIDA = re.compile(
    r"^(?:(?:hf\.co|huggingface\.co|modelscope\.cn)/[\w.\-]+/[\w.\-]+|(?:[a-z0-9][\w.\-]*/)?[a-z0-9][\w.\-]*)(?::[\w.\-]+)?$")


class ErrorBuscador(Exception):
    pass


# ===========================================================================
# Utilidades
# ===========================================================================

class Cache:
    def __init__(self):
        self._datos: Dict[str, Tuple[float, Any]] = {}
        self._cerrojo = threading.Lock()

    def obtener(self, clave: str, ttl: float):
        with self._cerrojo:
            v = self._datos.get(clave)
            if v and time.time() - v[0] < ttl:
                return v[1]
        return None

    def guardar(self, clave: str, valor: Any):
        with self._cerrojo:
            self._datos[clave] = (time.time(), valor)
            if len(self._datos) > 500:
                for k in sorted(self._datos, key=lambda k: self._datos[k][0])[:100]:
                    del self._datos[k]
        return valor


_cache = Cache()


def _texto(fragmento: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragmento))).strip()


def _numero(texto: str) -> Optional[int]:
    m = re.match(r"^([\d.,]+)\s*([KMB])?$", (texto or "").strip(), re.I)
    if not m:
        return None
    valor = float(m.group(1).replace(",", ""))
    return int(valor * {"K": 1e3, "M": 1e6, "B": 1e9}.get((m.group(2) or "").upper(), 1))


def _bytes(texto: str) -> Optional[int]:
    m = re.match(r"^([\d.]+)\s*(KB|MB|GB|TB)$", (texto or "").strip(), re.I)
    if not m:
        return None
    return int(float(m.group(1)) * {"KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}[m.group(2).upper()])


def cuantizacion_de(nombre_archivo: str) -> Optional[str]:
    base = os.path.basename(nombre_archivo)
    base = re.sub(r"(?i)\.gguf$", "", base)
    base = _PARTE.sub("", base)
    m = _CUANT.search(base)
    return m.group(1) if m else None


def validar_ref(ref: str) -> str:
    ref = (ref or "").strip()
    if not REF_VALIDA.match(ref) or ".." in ref:
        raise ErrorBuscador(f"Nombre de modelo no válido: {ref!r}")
    return ref


# ===========================================================================
# Comprobar en el registro (sin descargar)
# ===========================================================================

def registro_de(ref: str) -> Tuple[str, str, str]:
    from recursos.ficha import registro_de as _r
    return _r(ref)


def _motivo_registro(codigo: int, cuerpo: str, tag: str) -> str:
    """ El registro explica el 400 en el cuerpo; se traduce lo conocido """
    t = (cuerpo or "").lower()
    if "sharded" in t:
        return "Partido en varios archivos: Ollama todavía no descarga GGUF partidos desde el registro."
    if "not a valid quantization" in t:
        return f"El registro no reconoce «{tag}» como cuantización: esta variante no se puede descargar con Ollama."
    if "does not exist" in t or codigo == 404:
        return "No existe en el registro."
    if codigo == 401:
        return "Requiere iniciar sesión o aceptar una licencia."
    if codigo == 403:
        return "Acceso denegado: modelo privado o con licencia por aceptar."
    if codigo == 400:
        return "El registro no puede servir esta variante a Ollama."
    return f"El registro respondió HTTP {codigo}."


def comprobar(ref: str, timeout: float = 30) -> Dict[str, Any]:
    """ ¿Se puede descargar? Pide el manifiesto al registro que corresponde.
    Devuelve el tamaño exacto, las capas (modelo, plantilla, proyector de visión…)
    y el digest con el que luego se detectan actualizaciones. """
    ref = validar_ref(ref)
    clave = f"comprobar:{ref}"
    guardado = _cache.obtener(clave, 600)
    if guardado:
        return guardado
    registro, repo, tag = registro_de(ref)
    try:
        cabeceras = MANIFIESTO_COMO_OLLAMA if "modelscope.cn" in registro else MANIFIESTO
        r = requests.get(f"{registro}/v2/{repo}/manifests/{tag}", headers=cabeceras, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        return {"ref": ref, "descargable": False, "motivo": f"Sin conexión con el registro: {e}"}
    if r.status_code != 200:
        return _cache.guardar(clave, {"ref": ref, "descargable": False, "codigo": r.status_code,
                                      "motivo": _motivo_registro(r.status_code, r.text, tag)})
    try:
        m = r.json()
    except ValueError:
        return {"ref": ref, "descargable": False, "motivo": "Respuesta del registro no válida"}
    capas = m.get("layers") or []
    tipos = sorted({c.get("mediaType", "").split(".")[-1] for c in capas})
    return _cache.guardar(clave, {
        "ref": ref, "descargable": True, "bytes": sum(c.get("size", 0) for c in capas),
        "capas": tipos, "vision": "projector" in tipos, "digest": hashlib.sha256(r.content).hexdigest(),
    })


# ===========================================================================
# Ollama
# ===========================================================================

class Ollama:
    BASE = "https://ollama.com"

    def buscar(self, consulta: str = "", orden: str = "relevancia", capacidad: Optional[str] = None,
               pagina: int = 1) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if consulta:
            params["q"] = consulta
        o = ORDENES["ollama"].get(orden)
        if o:
            params["o"] = o
        if capacidad in CAPACIDADES_OLLAMA:
            params["c"] = capacidad
        cabeceras = dict(UA)
        if pagina > 1:
            # Las páginas siguientes las carga htmx al hacer scroll: sin esta cabecera
            # ollama.com ignora «page» y devuelve otra vez la primera
            params["page"] = pagina
            cabeceras["HX-Request"] = "true"
        clave = "ollama:" + json.dumps(params, sort_keys=True)
        guardado = _cache.obtener(clave, 600)
        if guardado:
            return guardado
        r = requests.get(f"{self.BASE}/search", params=params, headers=cabeceras, timeout=25)
        if r.status_code != 200:
            raise ErrorBuscador(f"ollama.com respondió {r.status_code}")
        modelos = self.analizar_busqueda(r.text)
        hay_mas = f'hx-get="/search?page={pagina + 1}' in r.text
        return _cache.guardar(clave, {"modelos": modelos, "siguiente": pagina + 1 if hay_mas and modelos else None})

    @staticmethod
    def analizar_busqueda(pagina: str) -> List[Dict[str, Any]]:
        salida = []
        for bloque in re.split(r"<li\b", pagina)[1:]:
            m = re.search(r'<a href="/((?:library/)?[a-z0-9][\w.\-]*(?:/[\w.\-]+)?)" class="group w-full"', bloque)
            if not m:
                continue
            ruta = m.group(1)
            nombre = ruta[len("library/"):] if ruta.startswith("library/") else ruta
            titulo = re.search(r"<h2[^>]*>\s*<span[^>]*>([^<]+)</span>", bloque)
            desc = re.search(r'<p class="max-w-lg[^"]*">(.*?)</p>', bloque, re.S)
            chips = [html.unescape(c).strip() for c in re.findall(r'<span\s+class="inline-flex my-1[^"]*">([^<]+)</span>', bloque)]
            tamanos = [c for c in chips if re.match(r"^(?:e?\d+(?:\.\d+)?[bmk]|\d+x\d+(?:\.\d+)?b)$", c, re.I)]
            capacidades = [c for c in chips if c not in tamanos]
            plano = _texto(bloque)
            descargas = re.search(r"([\d.,]+[KMB]?)\s*Pulls?", plano, re.I)
            etiquetas = re.search(r"(\d+)\s*Tags?", plano, re.I)
            actualizado = re.search(r"Updated\s+(.+?ago|yesterday|today)", plano, re.I)
            salida.append({
                "fuente": "ollama", "id": nombre, "nombre": html.unescape(titulo.group(1)).strip() if titulo else nombre,
                "autor": "ollama" if "/" not in nombre else nombre.split("/")[0],
                "oficial": "/" not in nombre,
                "descripcion": _texto(desc.group(1)) if desc else "",
                "capacidades": capacidades, "tamanos": tamanos,
                "descargas": _numero(descargas.group(1)) if descargas else None,
                "variantes_total": int(etiquetas.group(1)) if etiquetas else None,
                "actualizado": actualizado.group(1) if actualizado else None,
                "url": f"https://ollama.com/{ruta}",
                "solo_nube": capacidades == ["cloud"] or ("cloud" in capacidades and not tamanos),
            })
        return salida

    def variantes(self, nombre: str) -> Dict[str, Any]:
        nombre = validar_ref(nombre)
        clave = f"ollama-variantes:{nombre}"
        guardado = _cache.obtener(clave, 1800)
        if guardado:
            return guardado
        ruta = nombre if "/" in nombre else f"library/{nombre}"
        r = requests.get(f"{self.BASE}/{ruta}/tags", headers=UA, timeout=25)
        if r.status_code != 200:
            raise ErrorBuscador(f"No se encontró {nombre} en ollama.com ({r.status_code})")
        return _cache.guardar(clave, {"id": nombre, "variantes": self.analizar_etiquetas(r.text, ruta)})

    @staticmethod
    def analizar_etiquetas(pagina: str, ruta: str) -> List[Dict[str, Any]]:
        vistos, salida = set(), []
        patron = re.compile(r'<a href="/' + re.escape(ruta) + r':([^"]+)" class="md:hidden[^"]*"(.*?)</a>', re.S)
        for m in patron.finditer(pagina):
            tag = html.unescape(m.group(1))
            if tag in vistos:
                continue
            vistos.add(tag)
            plano = _texto(m.group(2))
            tam = re.search(r"([\d.]+\s*(?:KB|MB|GB|TB))", plano)
            ctx = re.search(r"([\d.]+[KM]?)\s*context window", plano)
            entrada = re.search(r"((?:Text|Image|Audio)(?:,\s*(?:Text|Image|Audio))*)\s*input", plano)
            digest = re.search(r"\b([0-9a-f]{12})\b", plano)
            cuando = re.search(r"input\s*•\s*(.+?ago|yesterday|today)", plano)
            ref = f"{ruta[len('library/'):] if ruta.startswith('library/') else ruta}:{tag}"
            nota = None
            if "mlx" in tag.lower():
                nota = "Formato MLX: solo para Mac con Apple Silicon."
            elif "cloud" in tag.lower():
                nota = "Se ejecuta en la nube de Ollama: requiere cuenta."
            salida.append({
                "ref": ref, "etiqueta": tag, "bytes": _bytes(tam.group(1)) if tam else None,
                "contexto": ctx.group(1) if ctx else None,
                "entrada": [x.strip() for x in entrada.group(1).split(",")] if entrada else [],
                "digest": digest.group(1) if digest else None,
                "actualizado": cuando.group(1) if cuando else None,
                "predeterminada": "latest" in plano.split(tag, 1)[-1][:40],
                "nota": nota, "descargable": None if nota is None else False,
            })
        return salida


# ===========================================================================
# Hugging Face
# ===========================================================================

class HuggingFace:
    BASE = "https://huggingface.co"
    EXPANDIR = ["downloads", "likes", "lastModified", "createdAt", "gguf", "pipeline_tag", "tags", "trendingScore", "gated", "cardData"]

    def buscar(self, consulta: str = "", orden: str = "relevancia", pagina: Optional[str] = None,
               limite: int = 30) -> Dict[str, Any]:
        if pagina:
            try:
                url = base64.urlsafe_b64decode(pagina.encode()).decode()
            except Exception:
                raise ErrorBuscador("Página no válida")
            if not url.startswith(f"{self.BASE}/api/models?"):
                raise ErrorBuscador("Página no válida")
            params = None
        else:
            url = f"{self.BASE}/api/models"
            params = {"filter": "gguf", "sort": ORDENES["huggingface"].get(orden, "downloads"), "direction": -1,
                      "limit": limite, "expand[]": self.EXPANDIR}
            if consulta:
                params["search"] = consulta
        clave = "hf:" + url + json.dumps(params, sort_keys=True, default=str)
        guardado = _cache.obtener(clave, 600)
        if guardado:
            return guardado
        r = requests.get(url, params=params, headers=UA, timeout=25)
        if r.status_code != 200:
            raise ErrorBuscador(f"Hugging Face respondió {r.status_code}")
        siguiente = None
        m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link", ""))
        if m:
            siguiente = base64.urlsafe_b64encode(m.group(1).encode()).decode()
        return _cache.guardar(clave, {"modelos": [self.normalizar(x) for x in r.json()], "siguiente": siguiente})

    @staticmethod
    def normalizar(m: Dict[str, Any]) -> Dict[str, Any]:
        tags = m.get("tags") or []
        gguf = m.get("gguf") or {}
        capacidades = []
        if m.get("pipeline_tag") in ("image-text-to-text",) or "vision" in tags or "multimodal" in tags:
            capacidades.append("vision")
        if "conversational" in tags:
            capacidades.append("chat")
        base = next((t[len("base_model:quantized:"):] for t in tags if t.startswith("base_model:quantized:")), None) \
            or next((t.split(":", 1)[1] for t in tags if t.startswith("base_model:") and t.count(":") == 1), None)
        arquitectura = gguf.get("architecture")
        if arquitectura == "clip":          # los metadatos son los del proyector de visión, no los del modelo
            arquitectura = None
            if "vision" not in capacidades:
                capacidades.append("vision")
        licencia = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), None)
        return {
            "fuente": "huggingface", "id": m["id"], "nombre": m["id"].split("/")[-1], "autor": m["id"].split("/")[0],
            "oficial": False, "descripcion": " · ".join(x for x in (f"basado en {base}" if base else "", arquitectura or "") if x),
            "capacidades": capacidades, "tamanos": [], "descargas": m.get("downloads"), "me_gusta": m.get("likes"),
            "tendencia": m.get("trendingScore"), "actualizado": m.get("lastModified"), "creado": m.get("createdAt"),
            "contexto": gguf.get("context_length"), "arquitectura": arquitectura,
            "parametros": gguf.get("total") if arquitectura else None, "licencia": licencia, "modelo_base": base,
            "requiere_licencia": bool(m.get("gated")), "url": f"https://huggingface.co/{m['id']}",
        }

    def variantes(self, repo: str) -> Dict[str, Any]:
        if not re.match(r"^[\w.\-]+/[\w.\-]+$", repo or ""):
            raise ErrorBuscador("Repositorio no válido")
        clave = f"hf-variantes:{repo}"
        guardado = _cache.obtener(clave, 1800)
        if guardado:
            return guardado
        r = requests.get(f"{self.BASE}/api/models/{repo}", params={"blobs": "true"}, headers=UA, timeout=25)
        if r.status_code != 200:
            raise ErrorBuscador(f"No se encontró {repo} en Hugging Face ({r.status_code})")
        d = r.json()
        archivos = [(s["rfilename"], s.get("size") or 0) for s in d.get("siblings", [])]
        variantes = agrupar_gguf(archivos, prefijo=f"hf.co/{repo}")
        for v in variantes:
            v["url_archivo"] = f"{self.BASE}/{repo}/resolve/main/{v['archivos'][0]}"
        gguf = d.get("gguf") or {}
        return _cache.guardar(clave, {
            "id": repo, "variantes": variantes, "contexto": gguf.get("context_length"),
            "arquitectura": gguf.get("architecture"), "requiere_licencia": bool(d.get("gated")),
            "vision": any("mmproj" in a[0].lower() for a in archivos),
        })


# ===========================================================================
# ModelScope
# ===========================================================================

class ModelScope:
    BASE = "https://modelscope.cn"

    def buscar(self, consulta: str = "", orden: str = "relevancia", pagina: int = 1, limite: int = 30) -> Dict[str, Any]:
        cuerpo = {"PageSize": limite, "PageNumber": max(1, int(pagina)), "SortBy": ORDENES["modelscope"].get(orden, "Default"),
                  "Target": "", "Name": consulta,
                  # «Criterion» con «gguf» en minúsculas filtra en el servidor; «SingleCriterion» se ignora
                  "Criterion": [{"category": "libraries", "predicate": "contains", "values": ["gguf"]}]}
        clave = "ms:" + json.dumps(cuerpo, sort_keys=True)
        guardado = _cache.obtener(clave, 600)
        if guardado:
            return guardado
        r = requests.put(f"{self.BASE}/api/v1/dolphin/models", json=cuerpo, headers=UA, timeout=25)
        if r.status_code != 200:
            raise ErrorBuscador(f"ModelScope respondió {r.status_code}")
        datos = (r.json().get("Data") or {}).get("Model") or {}
        modelos = [self.normalizar(m) for m in datos.get("Models") or []
                   if "gguf" in [x.lower() for x in (m.get("Libraries") or [])]]
        total = datos.get("TotalCount") or 0
        return _cache.guardar(clave, {"modelos": modelos, "siguiente": pagina + 1 if pagina * limite < total else None})

    @staticmethod
    def normalizar(m: Dict[str, Any]) -> Dict[str, Any]:
        repo = f"{m.get('Path')}/{m.get('Name')}"
        ts = m.get("LastUpdatedTime")
        return {
            "fuente": "modelscope", "id": repo, "nombre": m.get("Name"), "autor": m.get("Path"), "oficial": False,
            "descripcion": " · ".join(x for x in (m.get("ChineseName") or "", f"basado en {', '.join(m.get('BaseModel') or [])}" if m.get("BaseModel") else "") if x),
            "capacidades": [], "tamanos": [], "descargas": m.get("Downloads"), "me_gusta": m.get("Stars"),
            "actualizado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None,
            "licencia": m.get("License"), "url": f"https://modelscope.cn/models/{repo}",
        }

    def variantes(self, repo: str) -> Dict[str, Any]:
        if not re.match(r"^[\w.\-]+/[\w.\-]+$", repo or ""):
            raise ErrorBuscador("Repositorio no válido")
        clave = f"ms-variantes:{repo}"
        guardado = _cache.obtener(clave, 1800)
        if guardado:
            return guardado
        r = requests.get(f"{self.BASE}/api/v1/models/{repo}/repo/files", params={"Recursive": "true"}, headers=UA, timeout=25)
        if r.status_code != 200:
            raise ErrorBuscador(f"No se encontró {repo} en ModelScope ({r.status_code})")
        archivos = [(f["Path"], f.get("Size") or 0) for f in ((r.json().get("Data") or {}).get("Files") or []) if f.get("Type") != "tree"]
        variantes = agrupar_gguf(archivos, prefijo=f"modelscope.cn/{repo}")
        for v in variantes:
            v["url_archivo"] = f"{self.BASE}/models/{repo}/resolve/master/{v['archivos'][0]}"
        return _cache.guardar(clave, {"id": repo, "variantes": variantes,
                                      "vision": any("mmproj" in a[0].lower() for a in archivos)})


def agrupar_gguf(archivos: List[Tuple[str, int]], prefijo: str) -> List[Dict[str, Any]]:
    """ Archivos .gguf de un repositorio → variantes descargables por Ollama.

    Una variante partida en varios archivos (-00001-of-00003) se agrupa en una sola
    entrada; el proyector de visión (mmproj) no es una variante. La etiqueta de Ollama
    es la cuantización tal como aparece en el nombre (Q4_K_M, UD-Q4_K_XL, q4_k_m…).
    """
    grupos: Dict[str, Dict[str, Any]] = {}
    for ruta, tam in archivos:
        if not ruta.lower().endswith(".gguf") or "mmproj" in ruta.lower():
            continue
        cuant = cuantizacion_de(ruta) or cuantizacion_de(os.path.dirname(ruta) + ".gguf")
        if not cuant:
            continue
        g = grupos.setdefault(cuant.lower(), {"etiqueta": cuant, "archivos": [], "bytes": 0, "partes": 0})
        g["archivos"].append(ruta)
        g["bytes"] += tam
        g["partes"] += 1
    salida = []
    for g in grupos.values():
        partido = g["partes"] > 1 or any(_PARTE.search(re.sub(r"(?i)\.gguf$", "", a)) for a in g["archivos"])
        salida.append({
            "ref": f"{prefijo}:{g['etiqueta']}", "etiqueta": g["etiqueta"], "bytes": g["bytes"],
            "archivos": sorted(g["archivos"]), "partes": g["partes"],
            "nota": "Partido en varios archivos: Ollama no siempre puede descargarlo; se comprueba antes." if partido else None,
            "descargable": None,
        })
    return sorted(salida, key=lambda v: v["bytes"])


# ===========================================================================
# Fachada
# ===========================================================================

PROVEEDORES = {"ollama": Ollama(), "huggingface": HuggingFace(), "modelscope": ModelScope()}


def buscar(consulta: str, fuentes: List[str], orden: str = "relevancia", capacidad: Optional[str] = None,
           paginas: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """ Busca en varias plataformas a la vez. Si una falla, las demás siguen. """
    paginas = paginas or {}
    fuentes = [f for f in fuentes if f in PROVEEDORES] or list(PROVEEDORES)

    def una(fuente):
        try:
            p = PROVEEDORES[fuente]
            if fuente == "ollama":
                return fuente, p.buscar(consulta, orden, capacidad, int(paginas.get(fuente) or 1)), None
            if fuente == "huggingface":
                return fuente, p.buscar(consulta, orden, paginas.get(fuente)), None
            return fuente, p.buscar(consulta, orden, int(paginas.get(fuente) or 1)), None
        except (ErrorBuscador, requests.RequestException, ValueError) as e:
            return fuente, {"modelos": [], "siguiente": None}, str(e)

    with ThreadPoolExecutor(len(fuentes)) as ex:
        resultados = list(ex.map(una, fuentes))
    return {"fuentes": {f: {**r, "error": e} for f, r, e in resultados}}


def variantes(fuente: str, id_modelo: str, comprobar_todas: bool = True) -> Dict[str, Any]:
    if fuente not in PROVEEDORES:
        raise ErrorBuscador("Fuente desconocida")
    datos = dict(PROVEEDORES[fuente].variantes(id_modelo))
    lista = [dict(v) for v in datos["variantes"]]
    if comprobar_todas:
        pendientes = [v for v in lista if v.get("descargable") is None][:60]
        with ThreadPoolExecutor(8) as ex:
            for v, c in zip(pendientes, ex.map(lambda v: comprobar(v["ref"]), pendientes)):
                v["descargable"] = c["descargable"]
                if c["descargable"]:
                    v["bytes"] = c["bytes"]
                    v["vision"] = c.get("vision")
                else:
                    v["nota"] = c.get("motivo")
    datos["variantes"] = lista
    return datos


def novedades() -> Dict[str, Any]:
    """ Lo último de cada plataforma: modelos nuevos en Ollama, tendencias GGUF en
    Hugging Face y lo más recién actualizado en ModelScope. """
    trabajos = {
        "ollama_nuevos": lambda: PROVEEDORES["ollama"].buscar("", "recientes")["modelos"],
        "huggingface_tendencia": lambda: PROVEEDORES["huggingface"].buscar("", "tendencia", limite=20)["modelos"],
        "modelscope_actualizados": lambda: PROVEEDORES["modelscope"].buscar("", "actualizados", limite=20)["modelos"],
    }

    def correr(item):
        nombre, fn = item
        try:
            return nombre, fn(), None
        except Exception as e:
            return nombre, [], str(e)
    with ThreadPoolExecutor(3) as ex:
        return {n: {"modelos": m, "error": e} for n, m, e in ex.map(correr, trabajos.items())}


def fuente_de_ref(ref: str) -> str:
    if ref.startswith(("hf.co/", "huggingface.co/")):
        return "huggingface"
    if ref.startswith("modelscope.cn/"):
        return "modelscope"
    return "ollama"


def actualizaciones_instalados(instalados: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ Compara cada modelo instalado con su registro de origen. El digest local de
    /api/tags es el sha256 del manifiesto (verificado descargando de Ollama, Hugging Face
    y ModelScope). """
    def revisar(m):
        ref = m["name"]
        c = comprobar(ref)
        base = {"modelo": ref, "fuente": fuente_de_ref(ref)}
        if not c["descargable"]:
            estado = "local" if c.get("codigo") in (404, 400) else "error"
            return {**base, "estado": estado, "detalle": "No está en ningún registro (creado o importado aquí)" if estado == "local" else c.get("motivo")}
        return {**base, "estado": "al_dia" if c["digest"] == m.get("digest") else "actualizable",
                "bytes": c["bytes"], "local": (m.get("digest") or "")[:12], "remoto": c["digest"][:12]}
    with ThreadPoolExecutor(6) as ex:
        return list(ex.map(revisar, instalados))


def analizar_variante(ref: str) -> Dict[str, Any]:
    """ ¿Cómo iría en esta máquina? Lee solo la cabecera GGUF del registro y pasa la
    ficha por la calculadora de Recomendado. """
    from recursos import ficha as fichas
    from recursos.calculadora import recomendar
    from recursos.gestor import gestor
    ref = validar_ref(ref)
    f = fichas.desde_registro(ref)
    maq = gestor().maquina()
    resultado = {"ref": ref, "ficha": {k: f.get(k) for k in ("arquitectura", "parametros", "parametros_activos", "es_moe", "capas",
                                                           "contexto_max", "piensa", "embedding", "bytes_peso")}}
    if f.get("embedding"):
        resultado["veredicto"] = {"veredicto": "embeddings", "etiqueta": "Modelo de embeddings", "motivo": "Se usa en CPU para el índice semántico."}
        return resultado
    rec = recomendar(f, maq, "tutor")
    resultado["veredicto"] = {k: rec.get(k) for k in ("veredicto", "etiqueta", "motivo")}
    resultado["veredicto"]["tok_s"] = rec.get("estimacion", {}).get("tok_s")
    resultado["veredicto"]["memoria_gb"] = rec.get("estimacion", {}).get("total_gb")
    return resultado


# ===========================================================================
# Encontrar un modelo concreto: por nombre o pegando un enlace
# ===========================================================================

_WEB = re.compile(r"^(?:https?://)?(?:www\.)?(ollama\.com|huggingface\.co|hf\.co|modelscope\.cn)(?:/(.*))?$", re.I)
_SEGMENTO = re.compile(r"^[\w.\-]+$")


def _separar_etiqueta(nombre: str) -> Tuple[str, Optional[str]]:
    if ":" in nombre:
        base, tag = nombre.split(":", 1)
        return base, (tag or None)
    return nombre, None


def interpretar(texto: str) -> Dict[str, Any]:
    """ Qué ha escrito o pegado el usuario.

    · enlace de ollama.com, huggingface.co / hf.co o modelscope.cn (a la ficha, a las
      etiquetas, a un archivo .gguf…)            → {"tipo": "enlace", fuente, id, etiqueta}
    · lo que se le pasa a Ollama: «ollama run hf.co/…:Q4_K_M», «qwen3:8b»
    · «propietario/repositorio», que puede estar en cualquier plataforma → {"tipo": "repo"}
    · cualquier otra cosa es un nombre a buscar  → {"tipo": "nombre", consulta, etiqueta}
    """
    t = (texto or "").strip().strip("\"'`<>")
    t = re.sub(r"^ollama\s+(?:run|pull)\s+", "", t, flags=re.I).strip()
    if not t:
        raise ErrorBuscador("Escribe un nombre o pega un enlace")
    if len(t) > 400:
        raise ErrorBuscador("Texto demasiado largo")

    web = _WEB.match(t.split()[0]) if " " not in t else None
    if web:
        sitio = web.group(1).lower()
        ruta = urllib.parse.unquote(re.split(r"[?#]", web.group(2) or "", 1)[0]).strip("/")
        consulta = urllib.parse.parse_qs(urllib.parse.urlsplit("http://x/" + (web.group(2) or "")).query)
        partes = [x for x in ruta.split("/") if x]
        fuente = {"ollama.com": "ollama", "modelscope.cn": "modelscope"}.get(sitio, "huggingface")
        busqueda = (consulta.get("q") or consulta.get("search") or consulta.get("name") or [None])[0]
        if busqueda:
            return interpretar_nombre(busqueda)

        if fuente == "ollama":
            if partes[:1] == ["library"]:
                partes = partes[1:]
            for i, x in enumerate(partes):          # …/tags, …/blobs/<digest>
                if x in ("tags", "blobs"):
                    partes = partes[:i]
                    break
            if not partes or len(partes) > 2 or partes[0] in ("search", "models", "download", "blog", "settings", "signin"):
                raise ErrorBuscador("El enlace de ollama.com no apunta a un modelo")
            base, tag = _separar_etiqueta("/".join(partes))
            return _validar_enlace("ollama", base, tag)

        if fuente == "modelscope" and partes[:1] == ["models"]:
            partes = partes[1:]
        if fuente == "huggingface" and partes[:1] in (["models"], ["api"]):
            partes = partes[2:] if partes[:2] == ["api", "models"] else partes[1:]
        if len(partes) < 2:
            raise ErrorBuscador("El enlace no apunta a un repositorio (propietario/nombre)")
        repo_nombre, tag = _separar_etiqueta(partes[1])
        if not tag:      # enlace a un archivo .gguf o a la carpeta de una cuantización
            tag = next((c for c in (cuantizacion_de(x) for x in reversed(partes[2:])) if c), None)
        return _validar_enlace(fuente, f"{partes[0]}/{repo_nombre}", tag)

    if re.fullmatch(r"[\w.\-]+/[\w.\-]+(?::[\w.\-]+)?", t):
        base, tag = _separar_etiqueta(t)
        return {"tipo": "repo", "fuente": None, "id": base, "etiqueta": tag, "consulta": base.split("/")[1]}
    return interpretar_nombre(t)


def interpretar_nombre(texto: str) -> Dict[str, Any]:
    t = texto.strip()
    tag = None
    if re.fullmatch(r"[\w.\-]+:[\w.\-]+", t):
        t, tag = _separar_etiqueta(t)
    t = re.sub(r"\s+", " ", t)
    if not re.search(r"\w", t):
        raise ErrorBuscador("Escribe un nombre o pega un enlace")
    return {"tipo": "nombre", "fuente": None, "id": None, "etiqueta": tag, "consulta": t[:100]}


def _validar_enlace(fuente: str, id_modelo: str, tag: Optional[str]) -> Dict[str, Any]:
    if not all(_SEGMENTO.match(x) for x in id_modelo.split("/")) or id_modelo.count("/") > 1 or ".." in id_modelo:
        raise ErrorBuscador("El enlace no tiene un nombre de modelo válido")
    if tag is not None and not _SEGMENTO.match(tag):
        tag = None
    return {"tipo": "enlace", "fuente": fuente, "id": id_modelo, "etiqueta": tag,
            "consulta": id_modelo.split("/")[-1]}


def _clave(nombre: str) -> str:
    """ «unsloth/Qwen3-8B-GGUF», «qwen3-8b» y «Qwen3 8B» son el mismo nombre """
    base = (nombre or "").split("/")[-1].split(":")[0].lower()
    base = re.sub(r"[-_. ]?gguf$", "", base)
    return re.sub(r"[^a-z0-9]", "", base)


def _parecido(consulta: str, id_modelo: str) -> bool:
    fichas = [x for x in re.split(r"[^a-z0-9]+", consulta.lower()) if x]
    texto = id_modelo.lower()
    return bool(fichas) and all(f in texto for f in fichas)


def ficha_repo(fuente: str, id_modelo: str) -> Optional[Dict[str, Any]]:
    """ Datos de un modelo concreto, o None si no existe (o es privado) en esa plataforma """
    if not re.fullmatch(r"[\w.\-]+(?:/[\w.\-]+)?", id_modelo or "") or ".." in id_modelo:
        return None
    clave = f"ficha:{fuente}:{id_modelo}"
    guardado = _cache.obtener(clave, 600)
    if guardado is not None:
        return guardado or None
    resultado: Optional[Dict[str, Any]] = None
    if fuente == "huggingface" and "/" in id_modelo:
        r = requests.get(f"{HuggingFace.BASE}/api/models/{id_modelo}", params={"expand[]": HuggingFace.EXPANDIR}, headers=UA, timeout=25)
        if r.status_code == 200:
            d = r.json()
            resultado = HuggingFace.normalizar(d)
            resultado["sin_gguf"] = "gguf" not in (d.get("tags") or []) and not d.get("gguf")
        elif r.status_code not in (401, 404):
            raise ErrorBuscador(f"Hugging Face respondió {r.status_code}")
    elif fuente == "modelscope" and "/" in id_modelo:
        r = requests.get(f"{ModelScope.BASE}/api/v1/models/{id_modelo}", headers=UA, timeout=25)
        if r.status_code == 200 and (r.json().get("Data") or {}).get("Name"):
            d = r.json()["Data"]
            resultado = ModelScope.normalizar(d)
            resultado["sin_gguf"] = "gguf" not in [x.lower() for x in (d.get("Libraries") or [])]
        elif r.status_code not in (200, 404):
            raise ErrorBuscador(f"ModelScope respondió {r.status_code}")
    elif fuente == "ollama":
        ruta = id_modelo if "/" in id_modelo else f"library/{id_modelo}"
        r = requests.get(f"{Ollama.BASE}/{ruta}", headers=UA, timeout=25)
        if r.status_code == 200:
            desc = re.search(r'<meta name="description" content="([^"]*)"', r.text)
            chips = [html.unescape(c).strip() for c in re.findall(r'<span\s+class="inline-flex[^"]*"[^>]*>\s*([^<]+?)\s*</span>', r.text)]
            resultado = {
                "fuente": "ollama", "id": id_modelo, "nombre": id_modelo, "autor": id_modelo.split("/")[0] if "/" in id_modelo else "ollama",
                "oficial": "/" not in id_modelo, "descripcion": html.unescape(desc.group(1)) if desc else "",
                "capacidades": [c for c in chips if c in CAPACIDADES_OLLAMA],
                "tamanos": [c for c in chips if re.fullmatch(r"e?\d+(?:\.\d+)?[bmk]|\d+x\d+(?:\.\d+)?b", c, re.I)],
                "url": f"{Ollama.BASE}/{ruta}", "sin_gguf": False,
            }
        elif r.status_code != 404:
            raise ErrorBuscador(f"ollama.com respondió {r.status_code}")
    _cache.guardar(clave, resultado or {})
    return resultado


def localizar(texto: str) -> Dict[str, Any]:
    """ Encuentra un modelo concreto en las plataformas.

    Con un enlace se va directo a ese modelo; con «propietario/repositorio» se mira en
    las tres; con un nombre se busca en las tres y se separan las coincidencias exactas
    de las parecidas. Si lo encontrado no tiene GGUF (Ollama no podría usarlo), se
    buscan versiones GGUF con el mismo nombre. """
    q = interpretar(texto)
    exactos: List[Dict[str, Any]] = []
    parecidos: List[Dict[str, Any]] = []
    errores: Dict[str, str] = {}

    def ficha_segura(fuente, id_modelo):
        try:
            return fuente, ficha_repo(fuente, id_modelo), None
        except (ErrorBuscador, requests.RequestException, ValueError) as e:
            return fuente, None, str(e)

    if q["tipo"] in ("enlace", "repo"):
        fuentes = [q["fuente"]] if q["fuente"] else list(PROVEEDORES)
        with ThreadPoolExecutor(len(fuentes)) as ex:
            for fuente, ficha, error in ex.map(lambda f: ficha_segura(f, q["id"]), fuentes):
                if ficha:
                    exactos.append(ficha)
                elif error:
                    errores[fuente] = error
        buscar_nombre = not exactos or all(m.get("sin_gguf") for m in exactos)
    else:
        buscar_nombre = True

    if buscar_nombre:
        consulta = q["consulta"]
        with ThreadPoolExecutor(2) as ex:
            directo = ex.submit(ficha_segura, "ollama", _clave_ollama(consulta)) if q["tipo"] == "nombre" and _clave_ollama(consulta) else None
            r = buscar(consulta, list(PROVEEDORES))
            if directo:
                _, ficha, _ = directo.result()
                if ficha:
                    exactos.append(ficha)
        vistos = {(m["fuente"], m["id"].lower()) for m in exactos}
        objetivo = _clave(consulta)
        mismos_nombres: List[Dict[str, Any]] = []
        for fuente, datos in r["fuentes"].items():
            if datos.get("error"):
                errores.setdefault(fuente, datos["error"])
            n = 0
            for m in datos["modelos"]:
                if (fuente, m["id"].lower()) in vistos:
                    continue
                if _clave(m["id"]) == objetivo:
                    # Con un nombre, es lo que se buscaba; si el enlace era un repo sin GGUF,
                    # son sus versiones GGUF y van delante de lo parecido
                    (exactos if q["tipo"] == "nombre" else mismos_nombres).append(m)
                    vistos.add((fuente, m["id"].lower()))
                elif _parecido(consulta, m["id"]) and n < 6:
                    parecidos.append(m)
                    vistos.add((fuente, m["id"].lower()))
                    n += 1
        parecidos = mismos_nombres + parecidos
        # Lo comprobado directamente va primero; lo que salió de buscar, por descargas
        directos = [m for m in exactos if m.get("sin_gguf") is not None]      # solo ficha_repo pone «sin_gguf»
        de_busqueda = sorted((m for m in exactos if m.get("sin_gguf") is None), key=lambda m: -(m.get("descargas") or 0))
        exactos = directos + de_busqueda

    for m in exactos:
        m["destacar"] = q["etiqueta"]
    return {"interpretado": q, "exactos": exactos, "parecidos": parecidos, "errores": errores}


def _clave_ollama(consulta: str) -> Optional[str]:
    """ «Qwen3» → «qwen3»: los modelos oficiales de Ollama van en minúsculas y sin espacios """
    c = consulta.strip().lower()
    return c if re.fullmatch(r"[a-z0-9][a-z0-9.\-_]*", c) else None


# ===========================================================================
# Seguidos y comprobación periódica
# ===========================================================================

def ruta_estado() -> str:
    return os.environ.get("PRIG_BUSCADOR_ARCHIVO") or os.path.expanduser("~/.prig_buscador.json")


class Seguimiento:
    """ Modelos que el usuario sigue. Guarda cómo estaban la última vez que los vio y
    avisa de variantes nuevas, retiradas o cambiadas (otro tamaño o digest). """

    def __init__(self, ruta: Optional[str] = None, proveedores=None):
        self.ruta = ruta or ruta_estado()
        self.proveedores = proveedores or PROVEEDORES
        self._cerrojo = threading.RLock()

    def _leer(self) -> Dict[str, Any]:
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos = json.load(f)
        except (FileNotFoundError, ValueError):
            datos = {}
        datos.setdefault("seguidos", {})
        datos.setdefault("actualizaciones", None)
        return datos

    def _guardar(self, datos: Dict[str, Any]):
        tmp = self.ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.ruta)

    @staticmethod
    def _instantanea(variantes: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {v["etiqueta"]: {"bytes": v.get("bytes"), "digest": v.get("digest")} for v in variantes}

    def _variantes(self, fuente: str, id_modelo: str) -> List[Dict[str, Any]]:
        return self.proveedores[fuente].variantes(id_modelo)["variantes"]

    def seguir(self, fuente: str, id_modelo: str, titulo: Optional[str] = None) -> Dict[str, Any]:
        if fuente not in self.proveedores:
            raise ErrorBuscador("Fuente desconocida")
        variantes = self._variantes(fuente, id_modelo)
        with self._cerrojo:
            datos = self._leer()
            datos["seguidos"][f"{fuente}:{id_modelo}"] = {
                "fuente": fuente, "id": id_modelo, "titulo": titulo or id_modelo, "desde": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "instantanea": self._instantanea(variantes), "cambios": None, "revisado": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self._guardar(datos)
            return datos["seguidos"][f"{fuente}:{id_modelo}"]

    def dejar(self, fuente: str, id_modelo: str):
        with self._cerrojo:
            datos = self._leer()
            datos["seguidos"].pop(f"{fuente}:{id_modelo}", None)
            self._guardar(datos)

    def lista(self) -> List[Dict[str, Any]]:
        with self._cerrojo:
            return [{k: v for k, v in s.items() if k != "instantanea"} for s in self._leer()["seguidos"].values()]

    def revisar(self) -> List[Dict[str, Any]]:
        with self._cerrojo:
            datos = self._leer()
        seguidos = list(datos["seguidos"].values())

        def uno(s):
            try:
                ahora = self._instantanea(self._variantes(s["fuente"], s["id"]))
            except Exception as e:
                return s, None, str(e)
            antes = s["instantanea"]
            cambios = {
                "nuevas": sorted(set(ahora) - set(antes)),
                "retiradas": sorted(set(antes) - set(ahora)),
                "cambiadas": sorted(k for k in set(ahora) & set(antes)
                                    if (ahora[k].get("digest") and antes[k].get("digest") and ahora[k]["digest"] != antes[k]["digest"])
                                    or (ahora[k].get("bytes") and antes[k].get("bytes") and ahora[k]["bytes"] != antes[k]["bytes"])),
            }
            return s, cambios, None
        with ThreadPoolExecutor(4) as ex:
            resultados = list(ex.map(uno, seguidos))
        with self._cerrojo:
            datos = self._leer()
            for s, cambios, error in resultados:
                clave = f"{s['fuente']}:{s['id']}"
                if clave not in datos["seguidos"]:
                    continue
                datos["seguidos"][clave]["revisado"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                datos["seguidos"][clave]["error"] = error
                if cambios is not None:
                    datos["seguidos"][clave]["cambios"] = cambios if any(cambios.values()) else None
            self._guardar(datos)
        return self.lista()

    def marcar_visto(self, fuente: str, id_modelo: str) -> Dict[str, Any]:
        """ Acepta el estado actual como el nuevo punto de comparación """
        return self.seguir(fuente, id_modelo, (self._leer()["seguidos"].get(f"{fuente}:{id_modelo}") or {}).get("titulo"))

    def marcar_actualizado(self, ref: str):
        """ Tras descargar `ref`, lo guardado deja de decir que tiene versión nueva """
        with self._cerrojo:
            datos = self._leer()
            guardado = datos.get("actualizaciones")
            if not guardado:
                return
            for m in guardado["modelos"]:
                if m["modelo"] in (ref, f"{ref}:latest") and m["estado"] == "actualizable":
                    m["estado"] = "al_dia"
            guardado["actualizables"] = sum(1 for m in guardado["modelos"] if m["estado"] == "actualizable")
            self._guardar(datos)

    def actualizaciones(self, instalados_fn, max_edad: float = 86400, forzar: bool = False) -> Dict[str, Any]:
        """ Resultado guardado si tiene menos de `max_edad` segundos; si no, se recalcula """
        with self._cerrojo:
            guardado = self._leer().get("actualizaciones")
        if guardado and not forzar and time.time() - guardado.get("marca", 0) < max_edad:
            return {**guardado, "de_cache": True}
        resultados = actualizaciones_instalados(instalados_fn())
        nuevo = {"marca": time.time(), "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"), "modelos": resultados,
                 "actualizables": sum(1 for r in resultados if r["estado"] == "actualizable")}
        with self._cerrojo:
            datos = self._leer()
            datos["actualizaciones"] = nuevo
            self._guardar(datos)
        return {**nuevo, "de_cache": False}
