"""
Títulos de los enlaces: cuando el usuario pega un enlace sin título, Prig lo busca.

Solo metadatos públicos y livianos: el oEmbed de YouTube (título y canal, sin clave) y,
para el resto, el <title> u og:title de la página, leyendo como mucho 256 KB. Nada se
descarga más allá de eso. Se guarda en caché (una semana) para no repetir peticiones.
Si falla, no pasa nada: el elemento se guarda con su enlace y el título queda vacío.
"""

import html
import json
import os
import re
import threading
import time
from typing import Any, Dict, Optional

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Prig-IDE/1.0 (Prig Hub; lee solo el título)"}
SEMANA = 7 * 24 * 3600
MAX_BYTES = 256 * 1024
_cerrojo = threading.Lock()


def _cache_ruta(base: str) -> str:
    return os.path.join(base, "cache", "titulos.json")


def _cache(base: str) -> Dict[str, Any]:
    try:
        with open(_cache_ruta(base), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _guardar_cache(base: str, datos: Dict[str, Any]):
    ruta = _cache_ruta(base)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(dict(list(datos.items())[-3000:]), f, ensure_ascii=False)
    os.replace(ruta + ".tmp", ruta)


def _youtube(url: str) -> Optional[Dict[str, str]]:
    r = requests.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, headers=UA, timeout=6)
    if r.status_code != 200:
        return None
    d = r.json()
    res = {"titulo": str(d.get("title") or "")[:200], "autor": str(d.get("author_name") or "")[:100]}
    if d.get("thumbnail_url"):
        res["miniatura"] = str(d["thumbnail_url"])[:500]
    return res


def _pagina(url: str) -> Optional[Dict[str, str]]:
    with requests.get(url, headers=UA, timeout=6, stream=True, allow_redirects=True) as r:
        if r.status_code != 200 or "html" not in (r.headers.get("Content-Type") or ""):
            return None
        trozo = b""
        for parte in r.iter_content(16384):
            trozo += parte
            if len(trozo) >= MAX_BYTES or b"</head>" in trozo.lower():
                break
    texto = trozo.decode(r.encoding or "utf-8", "replace")
    res: Dict[str, str] = {}
    for patron in (r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
                   r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title',
                   r"<title[^>]*>(.*?)</title>"):
        m = re.search(patron, texto, re.I | re.S)
        if m:
            t = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
            t = re.sub(r"\s*[|·–-]\s*(YouTube|Kaggle|GitHub|Coursera|Udemy|Hugging Face)\s*$", "", t)
            if t:
                res["titulo"] = t[:200]
                break
    for patron in (r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                   r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image'):
        m = re.search(patron, texto, re.I | re.S)
        if m:
            img = html.unescape(m.group(1)).strip()
            if img.startswith("http"):
                res["miniatura"] = img[:500]
                break
    return res or None


def titulo(base: str, info: Dict[str, Any]) -> Dict[str, str]:
    """ {"titulo", "autor"?} de un enlace reconocido; {} si no se pudo """
    clave = info["clave"]
    with _cerrojo:
        cache = _cache(base)
        guardado = cache.get(clave)
    if guardado and time.time() - guardado.get("ts", 0) < SEMANA:
        return {k: v for k, v in guardado.items() if k != "ts"}
    datos: Optional[Dict[str, str]] = None
    try:
        if info["plataforma"] == "youtube":
            datos = _youtube(info["url"])
        elif info["plataforma"] == "github" and info["tipo"] in ("repositorio", "persona"):
            datos = {"titulo": info["ref"]}
        else:
            datos = _pagina(info["url"])
    except (requests.RequestException, ValueError):
        datos = None
    datos = datos or {}
    # Un fallo (sin conexión, página caída) se recuerda solo una hora, no una semana
    ts = time.time() if datos else time.time() - SEMANA + 3600
    with _cerrojo:
        cache = _cache(base)
        cache[clave] = {**datos, "ts": ts}
        _guardar_cache(base, cache)
    return datos
