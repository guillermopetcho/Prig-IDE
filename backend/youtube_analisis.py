"""
Módulo de Análisis de Videos de YouTube en Prig IDE.

Permite:
1. Extraer transcripciones y subtítulos cronometrados (timedtext) de YouTube de forma nativa.
2. Generar resúmenes estructurados para programadores (resumen ejecutivo, cheat-sheet de código y glosario).
3. Desglosar videos educativos en Objetivos de Aprendizaje didácticos interactivos con timestamps.
4. Generar desafíos interactivos autocontenidos y verificados para cada objetivo o video completo.
"""

import html
import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


def extraer_subtitulos_youtube(video_id: str) -> Optional[str]:
    """ Intenta extraer la transcripción o subtítulos automáticos del video desde YouTube """
    if not video_id:
        return None
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "es,en;q=0.9",
            },
        )
        raw_html = urllib.request.urlopen(req, timeout=7).read().decode("utf-8", errors="ignore")
        m = re.search(r"ytInitialPlayerResponse\s*=\s*({.+?});", raw_html)
        if not m:
            return None
        data = json.loads(m.group(1))
        captions = data.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
        if not captions:
            return None

        # Priorizar subtítulos en español, luego en inglés, o el primero disponible
        track = next((c for c in captions if c.get("languageCode") in ("es", "es-419", "es-ES")), None)
        if not track:
            track = next((c for c in captions if c.get("languageCode") in ("en", "en-US", "en-GB")), captions[0])

        base_url = track.get("baseUrl")
        if not base_url:
            return None

        cap_req = urllib.request.Request(base_url, headers={"User-Agent": "Mozilla/5.0"})
        cap_xml = urllib.request.urlopen(cap_req, timeout=7).read().decode("utf-8", errors="ignore")

        # Parsear marcas <text start="X" dur="Y">texto</text>
        lineas = []
        for start_str, txt in re.findall(r'<text start="([\d\.]+)"[^>]*>(.*?)</text>', cap_xml):
            limpio = html.unescape(txt).replace("\n", " ").strip()
            if limpio:
                segundos = int(float(start_str))
                m_num, s_num = divmod(segundos, 60)
                h_num, m_num = divmod(m_num, 60)
                if h_num > 0:
                    ts = f"[{h_num}:{m_num:02d}:{s_num:02d}]"
                else:
                    ts = f"[{m_num:02d}:{s_num:02d}]"
                lineas.append(f"{ts} {limpio}")

        if lineas:
            return "\n".join(lineas)
    except Exception:
        pass
    return None


def formatear_segundos_hms(segundos: float) -> str:
    """ Convierte segundos a formato MM:SS o HH:MM:SS """
    s_tot = max(0, int(segundos))
    m_num, s_num = divmod(s_tot, 60)
    h_num, m_num = divmod(m_num, 60)
    if h_num > 0:
        return f"{h_num}:{m_num:02d}:{s_num:02d}"
    return f"{m_num:02d}:{s_num:02d}"


DEFAULT_INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache_transcripciones")
os.makedirs(CACHE_DIR, exist_ok=True)


def _extraer_nombre_track(c: Dict[str, Any]) -> str:
    """ Extrae el nombre legible del track de subtítulos, compatible con formato simpleText y runs """
    name_obj = c.get("name") or {}
    if isinstance(name_obj, dict):
        if name_obj.get("simpleText"):
            return name_obj["simpleText"]
        runs = name_obj.get("runs")
        if runs and isinstance(runs, list) and len(runs) > 0 and isinstance(runs[0], dict):
            return runs[0].get("text", "")
    elif isinstance(name_obj, str):
        return name_obj
    return c.get("languageCode", "Desconocido")


def _obtener_caption_tracks(video_id: str) -> List[Dict[str, Any]]:
    """
    Obtiene la lista de captionTracks de YouTube ultra rápido.
    1. Intenta consulta directa con cliente Android de Innertube (toma ~0.8s, sin scraping de HTML).
    2. Fallback a scraping de watch?v= solo si la API directa no responde.
    """
    payload_android = json.dumps({
        "context": {
            "client": {
                "clientName": "ANDROID",
                "clientVersion": "20.10.38",
                "hl": "es",
                "gl": "ES"
            }
        },
        "videoId": video_id
    }).encode("utf-8")

    # 1. Consulta directa a Innertube Android con clave estándar (ultra rápido, ~0.8s)
    try:
        url_it = f"https://www.youtube.com/youtubei/v1/player?key={DEFAULT_INNERTUBE_API_KEY}"
        req_it = urllib.request.Request(
            url_it,
            data=payload_android,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "com.google.android.youtube/20.10.38"
            }
        )
        with urllib.request.urlopen(req_it, timeout=5) as resp_it:
            data_it = json.loads(resp_it.read().decode("utf-8", errors="ignore"))
            tracks = data_it.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
            if tracks:
                return tracks
    except Exception:
        pass

    # 2. Fallback: Scraping de watch?v= para extraer clave dinámica o ytInitialPlayerResponse
    try:
        url_watch = f"https://www.youtube.com/watch?v={video_id}"
        req_w = urllib.request.Request(
            url_watch,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "es,en;q=0.9"
            }
        )
        with urllib.request.urlopen(req_w, timeout=5) as resp_w:
            html_watch = resp_w.read().decode("utf-8", errors="ignore")

        m_key = re.search(r'"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"', html_watch)
        api_key = m_key.group(1) if m_key else ""
        if api_key and api_key != DEFAULT_INNERTUBE_API_KEY:
            url_it2 = f"https://www.youtube.com/youtubei/v1/player?key={api_key}"
            req_it2 = urllib.request.Request(
                url_it2,
                data=payload_android,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "com.google.android.youtube/20.10.38"
                }
            )
            with urllib.request.urlopen(req_it2, timeout=5) as resp_it2:
                data_it2 = json.loads(resp_it2.read().decode("utf-8", errors="ignore"))
                tracks = data_it2.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
                if tracks:
                    return tracks

        # Fallback de tracks dentro de ytInitialPlayerResponse en el propio HTML
        m_resp = re.search(r"ytInitialPlayerResponse\s*=\s*({.+?});", html_watch)
        if m_resp:
            data_resp = json.loads(m_resp.group(1))
            tracks = data_resp.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
            if tracks:
                return tracks
    except Exception:
        pass

    # 3. Fallback a cliente Web
    try:
        url_web = "https://www.youtube.com/youtubei/v1/player"
        payload_web = json.dumps({
            "context": {
                "client": {
                    "hl": "es",
                    "gl": "ES",
                    "clientName": "WEB",
                    "clientVersion": "2.20240101.01.00"
                }
            },
            "videoId": video_id
        }).encode("utf-8")
        req_web = urllib.request.Request(
            url_web,
            data=payload_web,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req_web, timeout=5) as resp_web:
            data_web = json.loads(resp_web.read().decode("utf-8", errors="ignore"))
            tracks = data_web.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
            if tracks:
                return tracks
    except Exception:
        pass

    return []


def _descargar_xml_timedtext(url: str) -> str:
    """ Descarga el XML de subtítulos cronometrados de YouTube utilizando User-Agent de Android y fallback """
    if not url:
        return ""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "com.google.android.youtube/20.10.38",
                "Accept-Language": "es,en;q=0.9"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        pass

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "es,en;q=0.9"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _parsear_fragmentos_subtitulos(xml_str: str) -> List[Dict[str, Any]]:
    """ Parsea XML de subtítulos soportando formato 1 (<text>) y formato 3 (<p>) """
    if not xml_str:
        return []
    entradas = []
    # Formato 1: <text start="..." dur="...">texto</text>
    for s_str, d_str, txt in re.findall(r'<text start="([\d\.]+)"(?:\s+dur="([\d\.]+)")?[^>]*>(.*?)</text>', xml_str, re.DOTALL):
        try:
            start = float(s_str)
            dur = float(d_str) if d_str else 3.0
            t = re.sub(r'<[^>]+>', '', txt)
            t = html.unescape(t).replace('\n', ' ').strip()
            if t:
                entradas.append({"start": round(start, 2), "dur": round(dur, 2), "end": round(start + dur, 2), "texto": t})
        except Exception:
            continue

    if not entradas:
        # Formato 3: <p t="ms" d="ms">texto</p>
        for t_str, d_str, txt in re.findall(r'<p t="(\d+)"(?:\s+d="(\d+)")?[^>]*>(.*?)</p>', xml_str, re.DOTALL):
            try:
                start = round(int(t_str) / 1000.0, 2)
                dur = round(int(d_str) / 1000.0, 2) if d_str else 3.0
                t = re.sub(r'<[^>]+>', '', txt)
                t = html.unescape(t).replace('\n', ' ').strip()
                if t:
                    entradas.append({"start": start, "dur": dur, "end": round(start + dur, 2), "texto": t})
            except Exception:
                continue

    return entradas


def _traducir_texto_rapido(texto: str, idioma_destino: str = "es") -> str:
    """ Traduce un texto mediante endpoint rápido con fallback seguro al texto original """
    if not texto or not texto.strip():
        return texto
    try:
        q = urllib.parse.quote(texto)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={idioma_destino}&dt=t&q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            partes = [item[0] for item in data[0] if item and item[0]]
            res = "".join(partes).strip()
            return res if res else texto
    except Exception:
        return texto


def _traducir_lote_parrafos(textos: List[str], idioma_destino: str = "es") -> List[str]:
    """
    Traduce una lista de párrafos de forma ultra rápida empaquetándolos en lotes
    con separador único para procesar todo un video en 1-2 peticiones concurrentes (~0.6s).
    """
    if not textos:
        return []

    SEP = " \n|||\n "
    bloques = []
    bloque_actual = []
    long_actual = 0

    for t in textos:
        t_limpio = t.strip() if isinstance(t, str) else ""
        if not t_limpio:
            bloque_actual.append("")
            continue
        if long_actual + len(t_limpio) > 2200 and bloque_actual:
            bloques.append(bloque_actual)
            bloque_actual = [t_limpio]
            long_actual = len(t_limpio)
        else:
            bloque_actual.append(t_limpio)
            long_actual += len(t_limpio) + len(SEP)

    if bloque_actual:
        bloques.append(bloque_actual)

    import concurrent.futures

    def _traducir_un_bloque(items: List[str]) -> List[str]:
        items_validos = [it for it in items if it]
        if not items_validos:
            return items

        texto_unido = SEP.join(items_validos)
        try:
            q = urllib.parse.quote(texto_unido)
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={idioma_destino}&dt=t&q={q}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                res_trad = "".join([item[0] for item in data[0] if item and item[0]])
                partes = res_trad.split("|||")
                if len(partes) == len(items_validos):
                    res_map = [p.strip() for p in partes]
                    idx = 0
                    final = []
                    for original in items:
                        if original:
                            final.append(res_map[idx])
                            idx += 1
                        else:
                            final.append("")
                    return final
                elif len(partes) > 1:
                    idx = 0
                    final = []
                    for original in items:
                        if original and idx < len(partes):
                            final.append(partes[idx].strip())
                            idx += 1
                        else:
                            final.append(original)
                    return final
        except Exception:
            pass
        return items

    resultados = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for res_b in executor.map(_traducir_un_bloque, bloques):
            resultados.extend(res_b)

    return resultados if len(resultados) == len(textos) else textos


def extraer_transcripcion_estructurada(video_id: str, idioma_destino: str = "es", forzar_refresco: bool = False) -> Dict[str, Any]:
    """
    Extrae la transcripción completa de YouTube con marcas de tiempo e intervalos calculados.
    Posee caché en disco ultra rápida (< 5ms) y traductor en lotes (< 1s).
    """
    if not video_id:
        return {"ok": False, "error": "ID de video vacío", "segmentos": []}

    # 1. Caché persistente en disco (respuesta instantánea < 5ms)
    cache_path = os.path.join(CACHE_DIR, f"{video_id}_{idioma_destino}.json")
    if not forzar_refresco and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                datos_cache = json.load(f)
                if datos_cache.get("ok") and datos_cache.get("segmentos"):
                    return datos_cache
        except Exception:
            pass

    try:
        captions = _obtener_caption_tracks(video_id)
        if not captions:
            return {
                "ok": False,
                "error": "Este video no tiene subtítulos disponibles en YouTube.",
                "segmentos": [],
                "idiomas_disponibles": []
            }

        idiomas_disponibles = [
            {
                "codigo": c.get("languageCode"),
                "nombre": _extraer_nombre_track(c),
                "es_traducible": c.get("isTranslatable", True)
            }
            for c in captions
        ]

        track_es = next((c for c in captions if (c.get("languageCode") or "").startswith("es")), None)
        track_orig = next((c for c in captions if (c.get("languageCode") or "").startswith("en")), captions[0])

        xml_origen = ""
        xml_traducido = ""
        idioma_usado = "es"
        idioma_nombre = "Español"
        idioma_origen = track_orig.get("languageCode", "en")
        nombre_origen = _extraer_nombre_track(track_orig)

        if idioma_destino in ("es", "es-419", "es-ES"):
            if track_es:
                # El video ya dispone de subtítulos oficiales en español
                xml_traducido = _descargar_xml_timedtext(track_es.get("baseUrl"))
                xml_origen = xml_traducido
                idioma_usado = "es"
                nombre_es = _extraer_nombre_track(track_es)
                idioma_nombre = f"Español ({nombre_es})" if nombre_es != "Español" else "Español (oficial de YouTube)"
                idioma_origen = track_es.get("languageCode", "es")
            else:
                # Descargar original para agrupar y traducir párrafos
                url_orig = track_orig.get("baseUrl", "")
                xml_origen = _descargar_xml_timedtext(url_orig)
                xml_traducido = xml_origen
                idioma_usado = idioma_origen
                idioma_nombre = f"{nombre_origen} (disponible en YouTube)"
        else:
            # El usuario eligió un idioma específico de los disponibles
            track_sel = next((c for c in captions if c.get("languageCode") == idioma_destino), captions[0])
            url_sel = track_sel.get("baseUrl", "")
            xml_traducido = _descargar_xml_timedtext(url_sel)
            xml_origen = xml_traducido
            idioma_usado = track_sel.get("languageCode", idioma_destino)
            idioma_nombre = _extraer_nombre_track(track_sel)
            idioma_origen = idioma_usado

        if not xml_traducido and xml_origen:
            xml_traducido = xml_origen

        entradas_orig = _parsear_fragmentos_subtitulos(xml_origen)
        entradas_trad = _parsear_fragmentos_subtitulos(xml_traducido)

        base_entradas = entradas_trad if entradas_trad else entradas_orig
        if not base_entradas:
            return {"ok": False, "error": "No se pudieron decodificar subtítulos para este video.", "segmentos": []}

        # Agrupar entradas en párrafos didácticos coherentes
        segmentos_agrupados = []
        actual_chunk = None

        for ent in base_entradas:
            orig_match = None
            if entradas_orig:
                orig_match = min(entradas_orig, key=lambda x: abs(x["start"] - ent["start"]))

            texto_orig_val = orig_match["texto"] if orig_match else ent["texto"]
            texto_trad_val = ent["texto"]

            if actual_chunk is None:
                actual_chunk = {
                    "start": ent["start"],
                    "end": ent["end"],
                    "textos_trad": [texto_trad_val],
                    "textos_orig": [texto_orig_val]
                }
            else:
                dur_actual = ent["end"] - actual_chunk["start"]
                long_actual = sum(len(x) for x in actual_chunk["textos_trad"])
                termina_oracion = actual_chunk["textos_trad"][-1].rstrip().endswith((".", "!", "?"))
                debe_cortar = (dur_actual >= 25.0) or (dur_actual >= 12.0 and termina_oracion) or (long_actual >= 220)

                if debe_cortar:
                    texto_final = " ".join(actual_chunk["textos_trad"]).strip()
                    texto_orig_final = " ".join(actual_chunk["textos_orig"]).strip()
                    s_str = formatear_segundos_hms(actual_chunk["start"])
                    e_str = formatear_segundos_hms(actual_chunk["end"])
                    segmentos_agrupados.append({
                        "id": f"seg_{len(segmentos_agrupados)}",
                        "start": round(actual_chunk["start"], 2),
                        "end": round(actual_chunk["end"], 2),
                        "dur": round(actual_chunk["end"] - actual_chunk["start"], 2),
                        "intervalo": f"{s_str} - {e_str}",
                        "texto": texto_final,
                        "texto_original": texto_orig_final
                    })
                    actual_chunk = {
                        "start": ent["start"],
                        "end": ent["end"],
                        "textos_trad": [texto_trad_val],
                        "textos_orig": [texto_orig_val]
                    }
                else:
                    actual_chunk["end"] = ent["end"]
                    actual_chunk["textos_trad"].append(texto_trad_val)
                    actual_chunk["textos_orig"].append(texto_orig_val)

        if actual_chunk:
            texto_final = " ".join(actual_chunk["textos_trad"]).strip()
            texto_orig_final = " ".join(actual_chunk["textos_orig"]).strip()
            s_str = formatear_segundos_hms(actual_chunk["start"])
            e_str = formatear_segundos_hms(actual_chunk["end"])
            segmentos_agrupados.append({
                "id": f"seg_{len(segmentos_agrupados)}",
                "start": round(actual_chunk["start"], 2),
                "end": round(actual_chunk["end"], 2),
                "dur": round(actual_chunk["end"] - actual_chunk["start"], 2),
                "intervalo": f"{s_str} - {e_str}",
                "texto": texto_final,
                "texto_original": texto_orig_final
            })

        # Si el usuario solicitó español pero YouTube solo entregó texto en inglés/otro idioma:
        # traducir los párrafos directamente al español con el traductor rápido en lotes (¡menos de 1 segundo!)
        if idioma_destino in ("es", "es-419", "es-ES") and idioma_usado != "es":
            try:
                textos_a_traducir = [seg.get("texto", "") for seg in segmentos_agrupados]
                textos_traducidos = _traducir_lote_parrafos(textos_a_traducir, "es")
                for i, trad in enumerate(textos_traducidos):
                    if trad and trad != segmentos_agrupados[i]["texto"]:
                        segmentos_agrupados[i]["texto"] = trad
                idioma_usado = "es"
                idioma_nombre = f"Español (traducido desde {nombre_origen})"
            except Exception:
                pass

        resultado = {
            "ok": True,
            "video_id": video_id,
            "idioma_destino": idioma_destino,
            "idioma_usado": idioma_usado,
            "idioma_nombre": idioma_nombre,
            "idiomas_disponibles": idiomas_disponibles,
            "total_segmentos": len(segmentos_agrupados),
            "segmentos": segmentos_agrupados
        }

        # Guardar en caché persistente en disco
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(resultado, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return resultado
    except Exception as e:
        return {"ok": False, "error": str(e), "segmentos": []}


def preparar_contexto_video(video_id: str, titulo: str, canal: str, duracion: str,
                            descripcion: str = "", texto_usuario: str = "",
                            notas_usuario: str = "") -> str:
    """ Compila y estructura todo el texto disponible del video """
    partes = [
        f"VIDEO: «{titulo}»",
        f"CANAL: {canal or 'YouTube'}",
        f"DURACIÓN: {duracion or 'N/A'}"
    ]

    if descripcion and descripcion.strip():
        partes.append(f"\nDESCRIPCIÓN / TEMARIO OFICIAL DEL CURSO:\n{descripcion.strip()}")

    if notas_usuario and notas_usuario.strip():
        partes.append(f"\nAPUNTES Y MARCAS DE TIEMPO DEL ALUMNO:\n{notas_usuario.strip()}")

    if texto_usuario and texto_usuario.strip():
        partes.append(f"\nTEXTO / TRANSCRIPCIÓN PROPORCIONADA POR EL USUARIO:\n{texto_usuario.strip()}")

    # Intentar subtítulos de YouTube si no hay texto largo del usuario
    if len(texto_usuario or "") < 100:
        subs = extraer_subtitulos_youtube(video_id)
        if subs:
            # Limitar a ~12000 caracteres para no desbordar contexto
            recorte = subs[:12000] + ("\n…(transcripción resumida)" if len(subs) > 12000 else "")
            partes.append(f"\nTRANSCRIPCIÓN DE SUBTÍTULOS DEL VIDEO:\n{recorte}")

    return "\n\n".join(partes)


def _extraer_json(texto: str) -> Optional[Any]:
    """ Extrae y deserializa el primer objeto o lista JSON válida encontrada en la respuesta """
    if not texto:
        return None
    t = re.sub(r"<think>[\s\S]*?</think>", "", texto, flags=re.I).strip()
    # Eliminar bloques markdown ```json ... ```
    m_code = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t, re.I)
    if m_code:
        try:
            return json.loads(m_code.group(1).strip())
        except Exception:
            pass
    # Intentar parseo directo
    try:
        return json.loads(t)
    except Exception:
        pass
    # Buscar primer { y último }
    i = t.find("{")
    j = t.rfind("}")
    if i != -1 and j > i:
        try:
            return json.loads(t[i:j+1])
        except Exception:
            pass
    # Buscar primer [ y último ]
    i_arr = t.find("[")
    j_arr = t.rfind("]")
    if i_arr != -1 and j_arr > i_arr:
        try:
            return json.loads(t[i_arr:j_arr+1])
        except Exception:
            pass
    return None


def generar_resumen_estructurado(motor, modelo: str, titulo: str, canal: str,
                                duracion: str, contexto: str, categoria: str = "") -> Dict[str, Any]:
    """ Genera un resumen didáctico estructurado (ejecutivo, snippets, glosario) """
    sistema = (
        "Eres un DOCENTE EXPERTO EN CIENCIAS DE LA COMPUTACIÓN Y PROGRAMACIÓN de Prig IDE.\n"
        "Tu misión es analizar el material de un video educativo y generar un RESUMEN TÉCNICO ESTRUCTURADO "
        "en español para programadores.\n\n"
        "Debes responder ÚNICAMENTE con un objeto JSON válido (sin markdown fuera del JSON) con esta estructura exacta:\n"
        "{\n"
        '  "resumen_ejecutivo": "Explicación clara, concisa y rigurosa de los conceptos esenciales...",\n'
        '  "puntos_clave": ["Idea o regla 1", "Idea o regla 2", "Idea o regla 3"],\n'
        '  "snippets_codigo": [\n'
        '    {"titulo": "Uso canónico", "lenguaje": "python o cpp", "codigo": "código aquí...", "explicacion": "breve nota"}\n'
        '  ],\n'
        '  "glosario": [\n'
        '    {"termino": "Concepto 1", "definicion": "Definición didáctica..."}\n'
        '  ],\n'
        '  "conclusiones": "Cómo aplicar lo aprendido en proyectos reales."\n'
        "}\n"
        "No inventes librerías externas innecesarias. Sé riguroso y pedagógico."
    )

    prompt = (
        f"Analiza la siguiente información de la clase «{titulo}» ({canal}, duración: {duracion}, tema: {categoria}).\n\n"
        f"{contexto}\n\n"
        "Genera el JSON con el resumen estructurado, puntos clave, snippets de código y glosario en español."
    )

    resp_raw = "".join(motor.generate_response(prompt, model=modelo, system_prompt=sistema, think=False,
                                               options={"temperature": 0.25}, uso="tutor"))
    datos = _extraer_json(resp_raw)
    if not datos or not isinstance(datos, dict):
        return {
            "resumen_ejecutivo": resp_raw.strip() or "No se pudo formatear el resumen estructurado.",
            "puntos_clave": [f"Estudio de {titulo}"],
            "snippets_codigo": [],
            "glosario": [],
            "conclusiones": "Continúa con la práctica activa para fijar los conocimientos."
        }
    return datos


def generar_objetivos_didacticos(motor, modelo: str, titulo: str, canal: str,
                                duracion: str, contexto: str, nivel: str = "intermedio",
                                categoria: str = "") -> List[Dict[str, Any]]:
    """ Descompone el video en 3 a 6 hitos u objetivos de aprendizaje concretos con timestamps """
    sistema = (
        "Eres un DISEÑADOR CURRICULAR Y PEDAGÓGICO DE PROGRAMACIÓN de Prig IDE.\n"
        "Tu misión es dividir el contenido de un video educativo en entre 3 y 6 OBJETIVOS DE APRENDIZAJE "
        "progresivos, secuenciales y prácticos (micro-metas).\n\n"
        "Debes responder ÚNICAMENTE con un objeto JSON válido (sin texto antes ni después) con esta forma:\n"
        "{\n"
        '  "objetivos": [\n'
        "    {\n"
        '      "id": "obj_1",\n'
        '      "numero": 1,\n'
        '      "titulo": "Título breve y activo (ej. Comprender la gestión de memoria en el Heap)",\n'
        '      "descripcion": "Explicación clara de lo que el alumno debe saber y saber hacer.",\n'
        '      "inicio_timestamp": "00:00",\n'
        '      "fin_timestamp": "06:30",\n'
        '      "inicio_segundos": 0,\n'
        '      "conceptos": ["punteros", "malloc", "heap"],\n'
        '      "dificultad": "principiante | intermedio | avanzado",\n'
        '      "criterio_evaluacion": "Qué debe ser capaz de implementar o responder para darlo por superado."\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "REGLAS:\n"
        "1. Los timestamps deben ser crecientes y cubrir momentos lógicos del video.\n"
        "2. Cada objetivo debe ser evaluable con un ejercicio de código o comprensión.\n"
        "3. La redacción debe ser en español neutro y motivador."
    )

    prompt = (
        f"Divide en 3 a 6 objetivos didácticos la clase «{titulo}» ({canal}, duración: {duracion}, nivel: {nivel}, categoría: {categoria}).\n\n"
        f"{contexto}\n\n"
        "Devuelve el JSON con la lista de objetivos cronometrados."
    )

    resp_raw = "".join(motor.generate_response(prompt, model=modelo, system_prompt=sistema, think=False,
                                               options={"temperature": 0.3}, uso="tutor"))
    datos = _extraer_json(resp_raw)
    if datos and isinstance(datos, dict) and isinstance(datos.get("objetivos"), list):
        return datos["objetivos"]
    if isinstance(datos, list):
        return datos

    # Fallback predeterminado si el modelo no genera formato JSON
    return [
        {
            "id": "obj_1",
            "numero": 1,
            "titulo": f"Fundamentos y conceptos clave de {titulo}",
            "descripcion": f"Comprender la base teórica y la arquitectura presentada en la primera parte de la lección.",
            "inicio_timestamp": "00:00",
            "fin_timestamp": "10:00",
            "inicio_segundos": 0,
            "conceptos": [categoria or "programación"],
            "dificultad": nivel or "principiante",
            "criterio_evaluacion": "Identificar los componentes esenciales y su aplicación práctica."
        },
        {
            "id": "obj_2",
            "numero": 2,
            "titulo": f"Implementación práctica y resolución de problemas",
            "descripcion": f"Aplicar los conceptos en código limpio siguiendo las mejores prácticas.",
            "inicio_timestamp": "10:00",
            "fin_timestamp": "25:00",
            "inicio_segundos": 600,
            "conceptos": [categoria or "programación", "código"],
            "dificultad": nivel or "intermedio",
            "criterio_evaluacion": "Escribir la solución y verificar con pruebas unitarias."
        }
    ]

