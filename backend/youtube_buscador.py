"""
Módulo de Búsqueda de Cursos y Videos de YouTube para Prig IDE.

Permite:
1. Búsqueda nativa de cursos y playlists de YouTube sin necesidad de API Key externa.
2. Soporte de Palabras Registradas de alta relevancia ("Deep Learning", "Machine Learning", "Python", "C++")
   con expansión de consultas académicas/profesionales y filtrado educativo robusto.
3. Caché en memoria thread-safe con TTL para acelerar consultas y reducir latencia.
4. Verificación de disponibilidad vía oEmbed para evitar videos eliminados o privados.
5. Extracción enriquecida: miniaturas de alta calidad, duraciones, canales, conteo de videos en playlists.
"""

import html
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("prig.youtube_buscador")

# Palabras registradas para el motor de búsqueda de Prig
PALABRAS_REGISTRADAS = {
    "deep_learning": {
        "slug": "deep_learning",
        "palabra": "Deep Learning",
        "emoji": "🧠",
        "descripcion": "Redes neuronales, PyTorch, Transformers, LLMs, Visión Artificial y NLP.",
        "tags": ["Deep Learning", "PyTorch", "Redes Neuronales", "Transformers", "IA"],
        "color": "#8b5cf6", # Púrpura IA
        "queries_expansion": [
            "deep learning curso completo",
            "deep learning pytorch full course university",
            "mit deep learning 6.s191",
            "neural networks 3blue1brown"
        ]
    },
    "machine_learning": {
        "slug": "machine_learning",
        "palabra": "Machine Learning",
        "emoji": "🤖",
        "descripcion": "Aprendizaje supervisado y no supervisado, Scikit-Learn, algoritmos y matemáticas.",
        "tags": ["Machine Learning", "Scikit-Learn", "Data Science", "Python"],
        "color": "#3b82f6", # Azul ciencia
        "queries_expansion": [
            "curso machine learning completo español",
            "machine learning full course stanford andrew ng",
            "machine learning python scikit-learn tutorial"
        ]
    },
    "python": {
        "slug": "python",
        "palabra": "Python",
        "emoji": "🐍",
        "descripcion": "Fundamentos, programación orientada a objetos, proyectos, automatización y backend.",
        "tags": ["Python", "Programación", "POO", "Backend", "Principiantes"],
        "color": "#10b981", # Verde Python
        "queries_expansion": [
            "curso python desde cero completo",
            "python full course for beginners freecodecamp",
            "python proyectos completos programacion"
        ]
    },
    "cpp": {
        "slug": "cpp",
        "palabra": "C++",
        "emoji": "⚡",
        "descripcion": "C++ moderno (C++17/C++20), memoria y punteros, STL, algoritmos y sistemas de alto rendimiento.",
        "tags": ["C++", "Sistemas", "Estructuras de Datos", "Algoritmos", "Modern C++"],
        "color": "#f59e0b", # Ámbar / C++
        "queries_expansion": [
            "curso c++ completo desde cero",
            "c++ programming full course university",
            "c++ estructuras de datos algoritmos"
        ]
    }
}

# Caché en memoria: key -> (timestamp, resultados)
_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL_SEGS = 7200  # 2 horas de persistencia


def obtener_palabras_registradas() -> List[Dict[str, Any]]:
    """Devuelve la lista de palabras registradas para renderizar botones/filtros en la UI."""
    return list(PALABRAS_REGISTRADAS.values())


def verificar_disponibilidad_oembed(video_id: str, timeout: float = 3.0) -> bool:
    """Verifica si un video de YouTube está disponible públicamente usando oEmbed."""
    if not video_id or len(video_id) < 5:
        return False
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; PrigIDE/1.0; +https://github.com/guillermopetcho/Prig-IDE)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _limpiar_texto(obj: Any) -> str:
    """Extrae texto limpio de estructuras complejas de YouTube (runs o simpleText)."""
    if not obj:
        return ""
    if isinstance(obj, str):
        return html.unescape(obj.strip())
    if isinstance(obj, dict):
        if "simpleText" in obj:
            return html.unescape(str(obj["simpleText"]).strip())
        if "runs" in obj and isinstance(obj["runs"], list):
            partes = [html.unescape(r.get("text", "")) for r in obj["runs"] if isinstance(r, dict)]
            return "".join(partes).strip()
    return ""


def _parsear_duracion_a_segundos(dur_str: str) -> int:
    """Convierte '12:34' o '1:02:30' a número de segundos para ordenamiento/filtrado."""
    if not dur_str:
        return 0
    partes = dur_str.strip().split(":")
    try:
        if len(partes) == 2:
            return int(partes[0]) * 60 + int(partes[1])
        elif len(partes) == 3:
            return int(partes[0]) * 3600 + int(partes[1]) * 60 + int(partes[2])
    except Exception:
        return 0
    return 0


def _extraer_items_de_yt_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extrae videoRenderer y playlistRenderer de la respuesta JSON ytInitialData."""
    items: List[Dict[str, Any]] = []

    def recorrer(nodo: Any):
        if isinstance(nodo, dict):
            if "videoRenderer" in nodo:
                vr = nodo["videoRenderer"]
                vid = vr.get("videoId")
                if vid:
                    titulo = _limpiar_texto(vr.get("title"))
                    canal = _limpiar_texto(vr.get("ownerText") or vr.get("shortBylineText"))
                    duracion = _limpiar_texto(vr.get("lengthText"))
                    vistas = _limpiar_texto(vr.get("viewCountText"))
                    publicado = _limpiar_texto(vr.get("publishedTimeText"))
                    descripcion = _limpiar_texto(vr.get("detailedMetadataSnippets", [{}])[0].get("snippetText") if vr.get("detailedMetadataSnippets") else vr.get("descriptionSnippet"))
                    
                    # Miniatura
                    thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
                    thumb_url = thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    if thumb_url.startswith("//"):
                        thumb_url = "https:" + thumb_url

                    items.append({
                        "id": vid,
                        "tipo": "video",
                        "titulo": titulo or "Video de YouTube",
                        "canal": canal or "Canal YouTube",
                        "duracion": duracion or "Video",
                        "duracion_segundos": _parsear_duracion_a_segundos(duracion),
                        "vistas": vistas or "",
                        "publicado": publicado or "",
                        "descripcion": descripcion or "",
                        "miniatura": thumb_url,
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "es_playlist": False,
                    })
            elif "playlistRenderer" in nodo:
                pr = nodo["playlistRenderer"]
                pid = pr.get("playlistId")
                if pid:
                    titulo = _limpiar_texto(pr.get("title"))
                    canal = _limpiar_texto(pr.get("shortBylineText") or pr.get("ownerText"))
                    conteo = _limpiar_texto(pr.get("videoCount"))
                    if not conteo and "videoCountText" in pr:
                        conteo = _limpiar_texto(pr.get("videoCountText"))
                    
                    # Miniatura
                    thumbs = pr.get("thumbnails", [{}])[0].get("thumbnails", []) if pr.get("thumbnails") else []
                    thumb_url = thumbs[-1]["url"] if thumbs else ""
                    if thumb_url.startswith("//"):
                        thumb_url = "https:" + thumb_url

                    # Extraer video inicial de la playlist si existe
                    primervid = ""
                    nav = pr.get("navigationEndpoint", {}).get("watchEndpoint", {})
                    if nav and "videoId" in nav:
                        primervid = nav["videoId"]

                    items.append({
                        "id": pid,
                        "tipo": "playlist",
                        "titulo": titulo or "Lista de reproducción",
                        "canal": canal or "Canal YouTube",
                        "duracion": conteo or "Playlist",
                        "duracion_segundos": 99999,  # playlists tienen alta prioridad educativa
                        "vistas": "",
                        "publicado": "",
                        "descripcion": f"Playlist con {conteo} sobre {titulo}",
                        "miniatura": thumb_url or (f"https://i.ytimg.com/vi/{primervid}/hqdefault.jpg" if primervid else ""),
                        "url": f"https://www.youtube.com/playlist?list={pid}",
                        "es_playlist": True,
                        "video_inicial_id": primervid,
                        "conteo_videos": conteo
                    })
            else:
                for k, v in nodo.items():
                    recorrer(v)
        elif isinstance(nodo, list):
            for elemento in nodo:
                recorrer(elemento)

    recorrer(data)
    return items


def buscar_cursos_youtube(
    query: str,
    tipo: str = "todos",
    max_resultados: int = 16,
    filtro_educativo: bool = True,
    forzar_refresco: bool = False
) -> Dict[str, Any]:
    """
    Busca videos y playlists en YouTube nativamente.
    
    Args:
        query: Término de búsqueda (ej: 'Deep Learning', 'FastAPI', 'c++ algoritmos')
        tipo: 'todos', 'video', o 'playlist'
        max_resultados: Límite de resultados a retornar (por defecto 16)
        filtro_educativo: Si es True, prioriza cursos extensos, tutoriales completos y playlists.
        forzar_refresco: Si es True, ignora la caché local.
    """
    consulta_limpia = query.strip()
    if not consulta_limpia:
        return {"query": "", "total": 0, "resultados": [], "palabra_registrada": None}

    # Detectar si la consulta coincide con una palabra registrada
    slug_registrado = None
    query_lower = consulta_limpia.lower()
    for slug, meta in PALABRAS_REGISTRADAS.items():
        if query_lower == meta["palabra"].lower() or query_lower == slug:
            slug_registrado = slug
            break
    
    cache_key = f"{consulta_limpia.lower()}::tipo={tipo}::max={max_resultados}::edu={filtro_educativo}"
    ahora = time.time()

    if not forzar_refresco:
        with _CACHE_LOCK:
            if cache_key in _CACHE:
                timestamp, cached_data = _CACHE[cache_key]
                if ahora - timestamp < CACHE_TTL_SEGS:
                    return {
                        "query": consulta_limpia,
                        "total": len(cached_data),
                        "resultados": cached_data,
                        "desde_cache": True,
                        "palabra_registrada": PALABRAS_REGISTRADAS.get(slug_registrado) if slug_registrado else None
                    }

    # Si es una palabra registrada y filtro_educativo está activo, enriquecemos la consulta
    consulta_para_yt = consulta_limpia
    if slug_registrado and filtro_educativo:
        meta = PALABRAS_REGISTRADAS[slug_registrado]
        consulta_para_yt = f"{meta['palabra']} curso completo tutorial"

    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(consulta_para_yt)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html_content = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"Error al conectar con YouTube para la búsqueda '{query}': {e}")
        # Si falló, intentar responder con caché previa aunque esté vencida
        with _CACHE_LOCK:
            if cache_key in _CACHE:
                _, cached_data = _CACHE[cache_key]
                return {
                    "query": consulta_limpia,
                    "total": len(cached_data),
                    "resultados": cached_data,
                    "desde_cache": True,
                    "degradado": True,
                    "palabra_registrada": PALABRAS_REGISTRADAS.get(slug_registrado) if slug_registrado else None
                }
        return {"query": consulta_limpia, "total": 0, "resultados": [], "error": str(e), "palabra_registrada": None}

    # Extraer ytInitialData
    m = re.search(r"ytInitialData\s*=\s*({.+?});", html_content)
    if not m:
        logger.warning("No se encontró ytInitialData en la respuesta de YouTube")
        return {"query": consulta_limpia, "total": 0, "resultados": [], "palabra_registrada": None}

    try:
        yt_json = json.loads(m.group(1))
    except Exception as e:
        logger.warning(f"Error parseando JSON de ytInitialData: {e}")
        return {"query": consulta_limpia, "total": 0, "resultados": [], "palabra_registrada": None}

    items_crudos = _extraer_items_de_yt_data(yt_json)
    
    # Filtrar por tipo si se especifica
    if tipo == "video":
        items_filtrados = [it for it in items_crudos if not it.get("es_playlist")]
    elif tipo == "playlist":
        items_filtrados = [it for it in items_crudos if it.get("es_playlist")]
    else:
        items_filtrados = items_crudos

    # Deduplicar por id
    vistos = set()
    unicos: List[Dict[str, Any]] = []
    for it in items_filtrados:
        it_id = it.get("id")
        if it_id and it_id not in vistos:
            vistos.add(it_id)
            unicos.append(it)

    # Heurística educativa:
    # 1. Las playlists y cursos completos tienen alta ponderación
    # 2. Descartar videos muy cortos (< 2 minutos / 120s) si filtro_educativo está activo, a menos que no haya suficientes
    if filtro_educativo:
        cursos_prioritarios = []
        otros = []
        for it in unicos:
            # Playlists o videos con más de 120 segundos
            if it.get("es_playlist") or it.get("duracion_segundos", 0) >= 120:
                # Bonificación si tiene palabras como 'curso', 'tutorial', 'full course', 'aprender', 'masterclass'
                titulo_l = it.get("titulo", "").lower()
                es_curso_claro = any(p in titulo_l for p in ("curso", "course", "tutorial", "desde cero", "completo", "aprender", "bootcamp", "guia", "masterclass"))
                it["relevancia_educativa"] = 2 if es_curso_claro else 1
                cursos_prioritarios.append(it)
            else:
                otros.append(it)
        
        # Ordenar dando prioridad a videos marcados como cursos y playlists
        cursos_prioritarios.sort(key=lambda x: (x.get("relevancia_educativa", 0), x.get("duracion_segundos", 0)), reverse=True)
        resultado_final = (cursos_prioritarios + otros)[:max_resultados]
    else:
        resultado_final = unicos[:max_resultados]

    # Guardar en caché
    with _CACHE_LOCK:
        _CACHE[cache_key] = (ahora, resultado_final)

    return {
        "query": consulta_limpia,
        "total": len(resultado_final),
        "resultados": resultado_final,
        "desde_cache": False,
        "palabra_registrada": PALABRAS_REGISTRADAS.get(slug_registrado) if slug_registrado else None
    }
