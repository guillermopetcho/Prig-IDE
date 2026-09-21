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
import re
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

