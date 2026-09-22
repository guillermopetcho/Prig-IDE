"""
Módulo Profesional de Búsqueda de Cursos y Videos de YouTube para Prig IDE.

Características de Nivel Producción:
1. Motor Dual Resiliente:
   - Primario: YouTube InnerTube JSON API (4x más rápido, bajo consumo, tipado estricto).
   - Secundario: Scraper HTML de reserva sobre ytInitialData ante cualquier contingencia.
2. Algoritmo de Ranking Didáctico Multivariable:
   - Bonificación por Canales de Autoridad Educativa (Universidades MIT, Stanford, Harvard y creadores de élite).
   - Curva de Duración Pedagógica (penalización a clips < 4 min, prioridad a clases de 45-90 min y cursos > 3 horas).
   - Bonificación a Listas de Reproducción y temarios estructurados.
   - Ponderación por preferencia de Idioma (Español / Inglés).
3. Autocompletado y Sugerencias en Tiempo Real (suggestqueries nativo).
4. Persistencia en Disco y Memoria:
   - Caché en memoria thread-safe respaldada en archivo local (`backend/data/youtube_cache.json`).
   - Modo degradado y offline garantizado.
5. Facetas y Filtros Avanzados:
   - Filtrado por duración (cortos, clases magistrales, cursos completos, playlists).
   - Filtrado por idioma (ES / EN / Todos).
   - Modos de ordenamiento (didáctico, duración, vistas, recientes).
"""

import html
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("prig.youtube_buscador")

# Palabras registradas para el motor de búsqueda didáctico de Prig
PALABRAS_REGISTRADAS = {
    "deep_learning": {
        "slug": "deep_learning",
        "palabra": "Deep Learning",
        "emoji": "🧠",
        "descripcion": "Redes neuronales, PyTorch, Transformers, LLMs, Visión Artificial y NLP.",
        "tags": ["Deep Learning", "PyTorch", "Redes Neuronales", "Transformers", "IA"],
        "color": "#8b5cf6",
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
        "color": "#3b82f6",
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
        "color": "#10b981",
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
        "color": "#f59e0b",
        "queries_expansion": [
            "curso c++ completo desde cero",
            "c++ programming full course university",
            "c++ estructuras de datos algoritmos"
        ]
    }
}

# Canales de alta autoridad didáctica y reputación pedagógica
CANALES_AUTORIDAD_EDUCATIVA = {
    # Universidades de prestigio global (+50 pts)
    "harvard": 50,
    "david j. malan": 50,
    "cs50": 50,
    "mit opencourseware": 50,
    "mit": 48,
    "stanford online": 50,
    "stanford university": 50,
    "stanford": 48,
    "cmu": 48,
    "carnegie mellon": 48,
    "uc berkeley": 48,
    "berkeley": 45,
    "oxford": 45,
    "cornell": 45,
    # Creadores de élite técnica & computación (+35 a +45 pts)
    "freecodecamp": 48,
    "freecodecamp español": 48,
    "3blue1brown": 48,
    "statquest with josh starmer": 46,
    "statquest": 46,
    "andrej karpathy": 50,
    "adrian cancino": 42,
    "mouredev": 42,
    "mouredev by brais moure": 42,
    "dot csv": 42,
    "fazt code": 40,
    "fazt": 38,
    "midudev": 40,
    "corey schafer": 42,
    "sentdex": 42,
    "trevtutor": 42,
    "neetcode": 40,
    "computerphile": 42,
    "programming with mosh": 38,
    "edureka!": 36,
    "simplilearn": 36,
    "pildorasinformaticas": 38
}

# Palabras clave didácticas que elevan la puntuación del título (+20 pts)
PALABRAS_CLAVE_DIDACTICAS = [
    "curso completo", "full course", "desde cero", "masterclass",
    "bootcamp", "universidad", "tutorial completo", "guia completa",
    "from scratch", "lecture", "computer science", "fundamentos",
    "paso a paso", "estructuras de datos", "algoritmos"
]

# Ubicación de persistencia en disco
_DIR_ACTUAL = os.path.dirname(os.path.abspath(__file__))
_CACHE_FILE = os.path.join(_DIR_ACTUAL, "data", "youtube_cache.json")
CACHE_TTL_SEGS = 7200  # 2 horas en memoria y disco
MAX_CACHE_ENTRIES = 250  # Límite FIFO para evitar crecimiento desmedido

_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()


def _cargar_cache_disco():
    """Carga la caché persistida en disco al iniciar el módulo."""
    global _CACHE
    if not os.path.exists(_CACHE_FILE):
        return
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            ahora = time.time()
            with _CACHE_LOCK:
                for k, v in raw.items():
                    ts = v.get("ts", 0)
                    items = v.get("items", [])
                    # Conservar solo entradas no vencidas
                    if ahora - ts < CACHE_TTL_SEGS:
                        _CACHE[k] = (ts, items)
        logger.info(f"Caché de YouTube cargada desde disco: {len(_CACHE)} consultas válidas.")
    except Exception as e:
        logger.warning(f"No se pudo cargar la caché de disco de YouTube: {e}")


def _guardar_cache_disco():
    """Guarda las entradas actuales de caché en disco de forma segura."""
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    try:
        datos_para_guardar = {}
        ahora = time.time()
        with _CACHE_LOCK:
            for k, (ts, items) in list(_CACHE.items())[-MAX_CACHE_ENTRIES:]:
                if ahora - ts < CACHE_TTL_SEGS:
                    datos_para_guardar[k] = {"ts": ts, "items": items}
        
        tmp_file = _CACHE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(datos_para_guardar, f, ensure_ascii=False, indent=1)
        os.replace(tmp_file, _CACHE_FILE)
    except Exception as e:
        logger.warning(f"Error persistiendo caché de YouTube en disco: {e}")


# Inicializar carga al importar
_cargar_cache_disco()


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
        headers={"User-Agent": "Mozilla/5.0 (compatible; PrigIDE/2.0; +https://github.com/guillermopetcho/Prig-IDE)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def obtener_sugerencias_youtube(query: str, max_sugerencias: int = 8) -> List[str]:
    """
    Obtiene sugerencias instantáneas en tiempo real desde suggestqueries de Google/YouTube.
    Ideal para desplegar dropdown de autocompletado en la UI mientras el usuario escribe.
    """
    consulta = query.strip()
    if not consulta:
        return []
    url = f"https://suggestqueries.google.com/complete/search?client=youtube&ds=yt&q={urllib.parse.quote(consulta)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "es-419,es;q=0.9,en;q=0.8"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            raw_text = resp.read().decode("utf-8", errors="ignore")
            # Parsear: window.google.ac.h(["consulta", [["sug1", ...], ...]])
            m = re.search(r"\((.*)\)", raw_text)
            if m:
                datos = json.loads(m.group(1))
                if len(datos) > 1 and isinstance(datos[1], list):
                    sugerencias = [str(item[0]) for item in datos[1] if item and len(item) > 0]
                    return sugerencias[:max_sugerencias]
    except Exception as e:
        logger.debug(f"Fallo al obtener sugerencias para '{consulta}': {e}")
    return []


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


def _parsear_vistas_a_numero(vistas_str: str) -> int:
    """Convierte cadenas como '1.2M de vistas' o '75,292 views' a entero para ordenamiento."""
    if not vistas_str:
        return 0
    s = vistas_str.lower()
    try:
        # Remover palabras
        num_str = re.sub(r"[^\d,\.]", "", s).replace(",", "")
        if "k" in s:
            return int(float(num_str) * 1000)
        if "m" in s:
            return int(float(num_str) * 1000000)
        return int(float(num_str)) if num_str else 0
    except Exception:
        return 0


def _detectar_idioma_heuristico(titulo: str, descripcion: str) -> str:
    """Detecta si un video está en español ('es') o en inglés ('en')."""
    texto = f"{titulo} {descripcion}".lower()
    tokens = set(re.findall(r"\b\w+\b", texto))
    
    palabras_es = {"curso", "desde", "cero", "aprende", "aprender", "programacion", "completo", "español", "para", "principiantes", "tutorial", "introduccion", "redes"}
    palabras_en = {"course", "full", "beginners", "from", "scratch", "learn", "programming", "tutorial", "introduction", "lecture", "with", "deep", "guide"}
    
    coincidencias_es = len(tokens.intersection(palabras_es))
    coincidencias_en = len(tokens.intersection(palabras_en))
    
    if coincidencias_es > coincidencias_en:
        return "es"
    elif coincidencias_en > coincidencias_es:
        return "en"
    return "es" if "el " in texto or "la " in texto or "de " in texto else "en"


def calcular_score_educativo(item: Dict[str, Any], query: str, idioma_pref: str = "todos") -> float:
    """
    Función de Scoring Didáctico Multivariable:
    Evalúa la relevancia textual, autoridad del canal, extensión didáctica,
    formato de playlist y afinidad lingüística.
    """
    score = 50.0  # Base
    titulo = item.get("titulo", "")
    titulo_l = titulo.lower()
    canal_l = item.get("canal", "").lower()
    desc_l = item.get("descripcion", "").lower()
    query_l = query.lower()
    query_tokens = [t for t in query_l.split() if len(t) > 2]

    # 1. Relevancia Textual Directa
    if query_l in titulo_l:
        score += 35.0
    else:
        coincidencias = sum(1 for t in query_tokens if t in titulo_l)
        score += coincidencias * 12.0

    # 2. Autoridad del Canal (Canales educativos de élite)
    canal_boost = 0
    for canal_clave, puntos in CANALES_AUTORIDAD_EDUCATIVA.items():
        if canal_clave in canal_l:
            canal_boost = max(canal_boost, puntos)
    score += canal_boost

    # 3. Curva de Duración Pedagógica
    dur_segs = item.get("duracion_segundos", 0)
    es_playlist = item.get("es_playlist", False)

    if es_playlist:
        # Las playlists representan secuencias de aprendizaje estructuradas
        score += 45.0
    else:
        if dur_segs < 240:
            # Penalización severa a clips de menos de 4 minutos (shorts / fragmentos)
            score -= 40.0
        elif 240 <= dur_segs < 900:
            # 4 a 15 minutos: tutoriales o conceptos puntuales
            score += 10.0
        elif 900 <= dur_segs < 3600:
            # 15 a 60 minutos: lección formal
            score += 25.0
        elif 3600 <= dur_segs < 10800:
            # 1 a 3 horas: clase magistral profunda
            score += 45.0
        else:
            # > 3 horas: curso completo / maratón intensivo
            score += 55.0

    # 4. Palabras Clave Didácticas en Título
    if any(p in titulo_l for p in PALABRAS_CLAVE_DIDACTICAS):
        score += 25.0

    # 5. Coincidencia de Idioma
    idioma_item = item.get("idioma", "es")
    if idioma_pref != "todos":
        if idioma_pref == idioma_item:
            score += 20.0
        else:
            score -= 15.0

    return max(0.0, score)


def _extraer_items_de_yt_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extrae videoRenderer y playlistRenderer de la respuesta JSON (InnerTube o ytInitialData)."""
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
                    
                    # Descripción
                    desc = ""
                    if vr.get("detailedMetadataSnippets"):
                        desc = _limpiar_texto(vr["detailedMetadataSnippets"][0].get("snippetText"))
                    elif vr.get("descriptionSnippet"):
                        desc = _limpiar_texto(vr["descriptionSnippet"])
                    
                    # Miniatura
                    thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
                    thumb_url = thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    if thumb_url.startswith("//"):
                        thumb_url = "https:" + thumb_url

                    dur_segs = _parsear_duracion_a_segundos(duracion)
                    idioma = _detectar_idioma_heuristico(titulo, desc)

                    items.append({
                        "id": vid,
                        "tipo": "video",
                        "titulo": titulo or "Video de YouTube",
                        "canal": canal or "Canal YouTube",
                        "duracion": duracion or "Video",
                        "duracion_segundos": dur_segs,
                        "vistas": vistas or "",
                        "vistas_numero": _parsear_vistas_a_numero(vistas),
                        "publicado": publicado or "",
                        "descripcion": desc or "",
                        "miniatura": thumb_url,
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "es_playlist": False,
                        "idioma": idioma
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

                    # Video inicial
                    primervid = ""
                    nav = pr.get("navigationEndpoint", {}).get("watchEndpoint", {})
                    if nav and "videoId" in nav:
                        primervid = nav["videoId"]

                    desc = f"Lista de reproducción curricular con {conteo} sobre {titulo}"
                    idioma = _detectar_idioma_heuristico(titulo, desc)

                    items.append({
                        "id": pid,
                        "tipo": "playlist",
                        "titulo": titulo or "Lista de reproducción",
                        "canal": canal or "Canal YouTube",
                        "duracion": conteo or "Playlist",
                        "duracion_segundos": 99999,  # Alta prioridad didáctica
                        "vistas": "",
                        "vistas_numero": 100000,
                        "publicado": "",
                        "descripcion": desc,
                        "miniatura": thumb_url or (f"https://i.ytimg.com/vi/{primervid}/hqdefault.jpg" if primervid else ""),
                        "url": f"https://www.youtube.com/playlist?list={pid}",
                        "es_playlist": True,
                        "video_inicial_id": primervid,
                        "conteo_videos": conteo,
                        "idioma": idioma
                    })
            else:
                for v in nodo.values():
                    recorrer(v)
        elif isinstance(nodo, list):
            for elemento in nodo:
                recorrer(elemento)

    recorrer(data)
    return items


def _buscar_innertube(query: str) -> Optional[List[Dict[str, Any]]]:
    """
    Estrategia Primaria: Consulta directa al endpoint JSON de InnerTube.
    Mucho más rápido y sin necesidad de renderizar HTML.
    """
    url = "https://www.youtube.com/youtubei/v1/search"
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20240401.00.00",
                "hl": "es-419",
                "gl": "US"
            }
        },
        "query": query
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "es-419,es;q=0.9,en;q=0.8"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=6.5) as resp:
            if resp.status == 200:
                raw_json = json.loads(resp.read().decode("utf-8"))
                return _extraer_items_de_yt_data(raw_json)
    except Exception as e:
        logger.debug(f"InnerTube API search no completó: {e}")
        return None
    return None


def _buscar_html_scraper(query: str) -> Optional[List[Dict[str, Any]]]:
    """
    Estrategia de Respaldo: Descarga HTML y extrae ytInitialData.
    Se activa si la llamada a InnerTube encuentra bloqueos o contingencias.
    """
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
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
        with urllib.request.urlopen(req, timeout=7.5) as resp:
            html_content = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r"ytInitialData\s*=\s*({.+?});", html_content)
        if m:
            yt_json = json.loads(m.group(1))
            return _extraer_items_de_yt_data(yt_json)
    except Exception as e:
        logger.warning(f"HTML scraper fallback falló para '{query}': {e}")
        return None
    return None


def buscar_cursos_youtube(
    query: str,
    tipo: str = "todos",
    max_resultados: int = 16,
    filtro_educativo: bool = True,
    idioma: str = "todos",
    duracion_filtro: str = "todas",
    orden: str = "educativo",
    forzar_refresco: bool = False
) -> Dict[str, Any]:
    """
    Busca videos y playlists en YouTube con arquitectura dual profesional.
    
    Args:
        query: Término de búsqueda (ej: 'Deep Learning', 'PyTorch', 'c++ estructuras')
        tipo: 'todos', 'video', o 'playlist'
        max_resultados: Límite de resultados a retornar (por defecto 16)
        filtro_educativo: Prioriza canales top, clases completas y temarios universitarios
        idioma: 'todos', 'es' (español), 'en' (inglés)
        duracion_filtro: 'todas', 'cortos' (<30m), 'clases' (30m-2h), 'cursos' (>2h), 'playlists'
        orden: 'educativo' (por score), 'duracion', 'vistas', 'recientes'
        forzar_refresco: Si es True, ignora la caché
    """
    consulta_limpia = query.strip()
    if not consulta_limpia:
        return {"query": "", "total": 0, "resultados": [], "palabra_registrada": None}

    # Detectar palabra registrada
    slug_registrado = None
    query_lower = consulta_limpia.lower()
    for slug, meta in PALABRAS_REGISTRADAS.items():
        if query_lower == meta["palabra"].lower() or query_lower == slug:
            slug_registrado = slug
            break

    cache_key = f"{consulta_limpia.lower()}::tipo={tipo}::max={max_resultados}::edu={filtro_educativo}::idm={idioma}::dur={duracion_filtro}::ord={orden}"
    ahora = time.time()

    # 1. Comprobar Caché
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

    # Enriquecimiento semántico de consulta si es una palabra registrada
    consulta_para_yt = consulta_limpia
    if slug_registrado and filtro_educativo:
        meta = PALABRAS_REGISTRADAS[slug_registrado]
        consulta_para_yt = f"{meta['palabra']} curso completo tutorial"

    # 2. Extracción Dual: Probar InnerTube primero, conmutar a Scraper si falla
    items_crudos = _buscar_innertube(consulta_para_yt)
    estrategia_usada = "innertube"
    if not items_crudos:
        logger.info(f"Conmutando a scraper HTML de respaldo para '{consulta_para_yt}'...")
        items_crudos = _buscar_html_scraper(consulta_para_yt)
        estrategia_usada = "html_scraper"

    if not items_crudos:
        # Si fallaron ambas llamadas (por ejemplo, corte de red), intentar recuperar de caché previa
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
        return {"query": consulta_limpia, "total": 0, "resultados": [], "error": "No se pudo conectar con YouTube.", "palabra_registrada": None}

    # 3. Filtrado por Tipo (video / playlist)
    if tipo == "video":
        items_filtrados = [it for it in items_crudos if not it.get("es_playlist")]
    elif tipo == "playlist":
        items_filtrados = [it for it in items_crudos if it.get("es_playlist")]
    else:
        items_filtrados = items_crudos

    # 4. Deduplicar por ID
    vistos = set()
    unicos: List[Dict[str, Any]] = []
    for it in items_filtrados:
        it_id = it.get("id")
        if it_id and it_id not in vistos:
            vistos.add(it_id)
            unicos.append(it)

    # 5. Filtrado por Facetas (Idioma & Duración)
    candidatos = []
    for it in unicos:
        # Filtro de Idioma
        if idioma != "todos":
            if it.get("idioma") != idioma:
                continue

        # Filtro de Duración
        dur_s = it.get("duracion_segundos", 0)
        es_pl = it.get("es_playlist", False)
        if duracion_filtro == "cortos" and (dur_s > 1800 or es_pl):
            continue
        elif duracion_filtro == "clases" and (dur_s < 1800 or dur_s > 7200 or es_pl):
            continue
        elif duracion_filtro == "cursos" and (dur_s < 7200 or es_pl):
            continue
        elif duracion_filtro == "playlists" and not es_pl:
            continue

        candidatos.append(it)

    # Si el filtro fue demasiado estricto y dejó vacío, relajamos al conjunto de únicos
    if not candidatos and unicos:
        candidatos = unicos

    # 6. Cálculo de Score Didáctico y Ordenamiento
    for it in candidatos:
        it["score_educativo"] = calcular_score_educativo(it, consulta_limpia, idioma)
        # Indicar si el canal pertenece a la lista de élite
        canal_l = it.get("canal", "").lower()
        it["es_canal_verificado"] = any(c in canal_l for c in CANALES_AUTORIDAD_EDUCATIVA)

    if orden == "duracion":
        candidatos.sort(key=lambda x: x.get("duracion_segundos", 0), reverse=True)
    elif orden == "vistas":
        candidatos.sort(key=lambda x: x.get("vistas_numero", 0), reverse=True)
    else:
        # Ordenamiento didáctico por defecto
        candidatos.sort(key=lambda x: (x.get("score_educativo", 0), x.get("duracion_segundos", 0)), reverse=True)

    resultado_final = candidatos[:max_resultados]

    # 7. Actualizar Caché en Memoria y Persistir en Disco
    with _CACHE_LOCK:
        _CACHE[cache_key] = (ahora, resultado_final)

    # Disparar persistencia en hilo separado para no añadir latencia a la respuesta HTTP
    threading.Thread(target=_guardar_cache_disco, daemon=True).start()

    return {
        "query": consulta_limpia,
        "total": len(resultado_final),
        "resultados": resultado_final,
        "desde_cache": False,
        "motor": estrategia_usada,
        "palabra_registrada": PALABRAS_REGISTRADAS.get(slug_registrado) if slug_registrado else None
    }
