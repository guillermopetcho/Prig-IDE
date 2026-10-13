"""
Sección YouTube: buscador (filtros nativos, listas en formato lockup, idioma, orden), transcripciones
(sin solapes), contexto del análisis (usa la transcripción real, repartida por todo el video), objetivos
validados y catálogo curado consistente. Sin red: las llamadas a YouTube se sustituyen.
"""

import base64
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import youtube_analisis as ya  # noqa: E402
import youtube_buscador as yb  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def video(vid, titulo, dur="10:00", publicado="hace 1 año", vistas="1,000 vistas"):
    return {"videoRenderer": {"videoId": vid, "title": {"runs": [{"text": titulo}]}, "ownerText": {"runs": [{"text": "Canal"}]},
                              "lengthText": {"simpleText": dur}, "viewCountText": {"simpleText": vistas},
                              "publishedTimeText": {"simpleText": publicado}}}


def lista(pid, titulo, primer="abcdefghijk", conteo="12 lecciones"):
    return {"lockupViewModel": {
        "contentId": pid, "contentType": "LOCKUP_CONTENT_TYPE_PLAYLIST",
        "contentImage": {"collectionThumbnailViewModel": {"primaryThumbnail": {"thumbnailViewModel": {
            "image": {"sources": [{"url": f"https://i.ytimg.com/vi/{primer}/hq720.jpg"}]},
            "overlays": [{"thumbnailOverlayBadgeViewModel": {"thumbnailBadges": [{"thumbnailBadgeViewModel": {"text": conteo}}]}}]}}}},
        "metadata": {"lockupMetadataViewModel": {"title": {"content": titulo}, "metadata": {"contentMetadataViewModel": {
            "metadataRows": [{"metadataParts": [{"text": {"content": "Canal de listas"}}]}]}}}},
        "itemPlayback": {"inlinePlayerData": {"onSelect": {"innertubeCommand": {"watchEndpoint": {"videoId": primer, "playlistId": pid}}}}}}}


class PruebaBuscador(unittest.TestCase):
    def setUp(self):
        yb._CACHE.clear()
        p = mock.patch.object(yb, "_guardar_cache_disco")
        p.start()
        self.addCleanup(p.stop)

    def buscar(self, crudos, **kw):
        llamadas = []

        def falso(query, params="", idioma="todos"):
            llamadas.append((query, params, idioma))
            return yb._extraer_items_de_yt_data({"contents": crudos})
        with mock.patch.object(yb, "_buscar_innertube", falso), mock.patch.object(yb, "_buscar_html_scraper", lambda *a: None):
            return yb.buscar_cursos_youtube(query="python", forzar_refresco=True, **kw), llamadas

    def test_las_listas_en_formato_lockup_no_se_pierden(self):
        # YouTube manda las listas como lockupViewModel: antes se descartaban (14 de 20 resultados)
        r, _ = self.buscar([video("aaaaaaaaaaa", "Curso de Python"), lista("PLxyz", "Curso de Python completo", "bbbbbbbbbbb")])
        tipos = {x["id"]: x for x in r["resultados"]}
        self.assertIn("PLxyz", tipos)
        pl = tipos["PLxyz"]
        self.assertTrue(pl["es_playlist"])
        self.assertEqual(pl["video_inicial_id"], "bbbbbbbbbbb")
        self.assertEqual(pl["duracion"], "12 lecciones")
        self.assertEqual(pl["canal"], "Canal de listas")
        # Sin valores inventados que desordenen «duración» y «vistas»
        self.assertEqual((pl["duracion_segundos"], pl["vistas_numero"]), (0, 0))

    def test_tipo_y_duracion_se_piden_a_youtube(self):
        _, llamadas = self.buscar([lista("PLxyz", "Curso")], tipo="playlist")
        self.assertEqual(base64.b64decode(llamadas[0][1]), b"\x12\x02\x10\x03")
        _, llamadas = self.buscar([video("aaaaaaaaaaa", "Clase", "1:00:00")], duracion_filtro="cursos")
        self.assertEqual(base64.b64decode(llamadas[0][1]), b"\x12\x04\x10\x01\x18\x02")
        self.assertEqual(yb._params_busqueda("todos", "todas"), "")

    def test_si_nada_cumple_el_filtro_se_avisa_en_vez_de_devolver_otra_cosa(self):
        r, _ = self.buscar([video("aaaaaaaaaaa", "Clase corta", "5:00")], duracion_filtro="cursos")
        self.assertEqual(r["resultados"], [])
        self.assertIn("filtros", r["aviso"])

    def test_idioma_pedido_va_a_youtube_y_filtra(self):
        crudos = [video("aaaaaaaaaaa", "Learn Python: the full course for beginners"),
                  video("bbbbbbbbbbb", "Curso de Python desde cero para principiantes")]
        r, llamadas = self.buscar(crudos, idioma="en")
        self.assertEqual(llamadas[0][2], "en")
        self.assertEqual([x["id"] for x in r["resultados"]], ["aaaaaaaaaaa"])

    def test_orden_recientes(self):
        crudos = [video("aaaaaaaaaaa", "A", publicado="hace 3 años"), video("bbbbbbbbbbb", "B", publicado="2 weeks ago"),
                  video("ccccccccccc", "C", publicado="Transmitido hace 5 días"), lista("PLxyz", "Lista")]
        r, _ = self.buscar(crudos, orden="recientes")
        self.assertEqual([x["id"] for x in r["resultados"]], ["ccccccccccc", "bbbbbbbbbbb", "aaaaaaaaaaa", "PLxyz"])

    def test_sin_resultados_no_es_error_de_conexion(self):
        r, _ = self.buscar([])
        self.assertNotIn("error", r)
        self.assertTrue(r["aviso"])

    def test_vistas(self):
        casos = {"1,823,481 vistas": 1823481, "1.2M views": 1200000, "12 mil visualizaciones": 12000,
                 "3,4 M de vistas": 3400000, "684K views": 684000, "Sin vistas": 0, "1 vista": 1}
        for texto, esperado in casos.items():
            self.assertEqual(yb._parsear_vistas_a_numero(texto), esperado, texto)

    def test_idioma_heuristico(self):
        self.assertEqual(yb._detectar_idioma_heuristico("Machine Learning: the complete guide for beginners", ""), "en")
        self.assertEqual(yb._detectar_idioma_heuristico("Machine Learning desde cero con Python", ""), "es")
        self.assertEqual(yb._detectar_idioma_heuristico("PyTorch", "", "en"), "en")


class PruebaTranscripcion(unittest.TestCase):
    def test_intervalos_sin_solapes(self):
        xml = ('<text start="0.5" dur="15">uno</text><text start="13.0" dur="16">dos</text>'
               '<text start="27.0" dur="4">tres</text>')
        e = ya._parsear_fragmentos_subtitulos(xml)
        self.assertEqual([x["end"] for x in e], [13.0, 27.0, 31.0])
        self.assertTrue(all(a["end"] <= b["start"] for a, b in zip(e, e[1:])))


def transcripcion_falsa(n=2000):
    return {"ok": True, "segmentos": [{"start": i * 20.0, "end": i * 20.0 + 20, "texto": f"parrafo {i} " + "x" * 150}
                                      for i in range(n)]}


class PruebaContextoAnalisis(unittest.TestCase):
    def test_usa_la_transcripcion_repartida_por_todo_el_video(self):
        with mock.patch.object(ya, "extraer_transcripcion_estructurada", lambda *a, **k: transcripcion_falsa()):
            c = ya.preparar_contexto_video("vid", "Curso", "Canal", "11:06:40")
        self.assertEqual(c["fuente"], "transcripcion")
        self.assertFalse(c["transcripcion_completa"])
        self.assertEqual(c["duracion_segundos"], 40000)
        self.assertLess(len(c["texto"]), ya.PRESUPUESTO_TRANSCRIPCION + 2000)
        # Extractos del principio y del final, no solo de los primeros minutos
        self.assertIn("parrafo 0 ", c["texto"])
        minutos = [int(m) for m in re.findall(r"\[(\d+):\d\d:\d\d\]", c["texto"])]
        self.assertGreaterEqual(max(minutos), 10)

    def test_sin_subtitulos_lo_dice_y_pide_no_inventar(self):
        with mock.patch.object(ya, "extraer_transcripcion_estructurada", lambda *a, **k: {"ok": False, "segmentos": []}):
            c = ya.preparar_contexto_video("vid", "Curso", "Canal", "10:00")
        self.assertEqual(c["fuente"], "solo_metadatos")
        self.assertIn("no inventes", c["texto"])

    def test_texto_del_usuario_evita_descargar(self):
        with mock.patch.object(ya, "extraer_transcripcion_estructurada", side_effect=AssertionError("no debía descargar")):
            c = ya.preparar_contexto_video("vid", "Curso", "Canal", "10:00", texto_usuario="t" * 200)
        self.assertEqual(c["fuente"], "texto_usuario")


class MotorFalso:
    def __init__(self, respuesta):
        self.respuesta = respuesta

    def generate_response(self, *a, **k):
        yield self.respuesta


class PruebaObjetivos(unittest.TestCase):
    def test_sin_json_es_error_y_no_objetivos_inventados(self):
        with self.assertRaises(ValueError):
            ya.generar_objetivos_didacticos(MotorFalso("no sé"), "m", "T", "C", "10:00", "ctx")

    def test_error_del_motor_no_se_guarda_como_resultado(self):
        motor = MotorFalso("[Error de conexión con Ollama: rechazada]")
        with self.assertRaises(ValueError):
            ya.generar_resumen_estructurado(motor, "m", "T", "C", "10:00", "ctx")
        with self.assertRaisesRegex(ValueError, "Error de conexión"):
            ya.generar_objetivos_didacticos(motor, "m", "T", "C", "10:00", "ctx")

    def test_normaliza_ids_y_minutos(self):
        crudo = json.dumps({"objetivos": [
            {"id": "x", "titulo": "a", "inicio_timestamp": "10:00", "fin_timestamp": "5:00"},
            {"titulo": "b", "inicio_timestamp": "2:00:00"},
            {"titulo": ""},
            {"titulo": "c", "inicio_timestamp": "1:00"}]})
        o = ya.generar_objetivos_didacticos(MotorFalso(crudo), "m", "T", "C", "1:00:00", "ctx", duracion_segundos=3600)
        self.assertEqual([x["id"] for x in o], ["obj_1", "obj_2", "obj_3"])
        self.assertEqual([x["inicio_segundos"] for x in o], [600, 3600, 3600])  # recortado al video y creciente
        self.assertEqual(o[0]["fin_timestamp"], "")  # un fin anterior al inicio se descarta


class PruebaCatalogo(unittest.TestCase):
    def test_catalogo_js_y_json_iguales_y_sin_ids_repetidos(self):
        with open(os.path.join(RAIZ, "frontend", "data", "cursos_youtube.json"), encoding="utf-8") as f:
            datos = json.load(f)
        with open(os.path.join(RAIZ, "frontend", "js", "youtube_hub.js"), encoding="utf-8") as f:
            js = f.read()
        i = js.index("const VIDEOS_CURADOS = ") + len("const VIDEOS_CURADOS = ")
        en_js = json.loads(js[i:js.index("\n];", i) + 2])
        self.assertEqual(en_js, datos)
        ids = [d["id"] for d in datos]
        self.assertEqual(len(ids), len(set(ids)))
        for d in datos:
            self.assertRegex(d["id"], r"^[\w-]{11}$")
            # Un texto de curso («20 clases») solo tiene sentido si la lista existe en la ficha
            if not re.fullmatch(r"\d+(:\d\d){1,2}", d["duracion"]):
                self.assertTrue(d.get("playlist"), d["id"])


if __name__ == "__main__":
    unittest.main()
