"""
Pruebas del gestor de recursos (botón "Recomendado").

Ninguna prueba descarga modelos ni carga nada en la GPU: las máquinas son
radiografías simuladas y las fichas son las reales de los modelos, copiadas aquí.
Lo que se protege:

  · la calculadora contra lo MEDIDO en la máquina de referencia (RTX 4050 portátil
    de 6 GB): memoria ±10 %, reparto GPU ±0,1, velocidad ±25 %;
  · veredictos sensatos en máquinas muy distintas (4 GB, 12 GB, 24 GB, solo CPU,
    Apple con memoria unificada, AMD);
  · regresiones vistas al construirlo: caché q8_0 para extraer, dos ranuras que no
    caben, un 32B "entero" en 6 GB, suponer menos ranuras de las del servidor;
  · la recuperación de falta de memoria, el canario de citas, el almacén (huellas,
    restaurar, archivo roto) y la validación de variables del servidor.
"""

import json
import os
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recursos import calibracion, gguf, servidor
from recursos.almacen import Almacen
from recursos.calculadora import (GB, Maquina, elegir_modelo, estimar, recomendar,
                                  servidor_efectivo)
from recursos.ficha import desde_metadatos, kv_bytes

MB = 1024 ** 2

# Fichas reales, leídas de /api/show
QWEN25_7B = {"nombre": "qwen2.5-coder:7b", "arquitectura": "qwen2", "bytes_peso": 4683087561,
             "parametros": 7615616512, "parametros_activos": 7615616512, "fraccion_activa": 1.0,
             "capas": 28, "cabezas_kv": 4, "dim_cabeza": 128, "kv_bytes_token_f16": 57344,
             "contexto_max": 32768, "es_moe": False, "piensa": False, "embedding": False}
QWEN3_14B = {"nombre": "qwen3:14b-q4_k_m", "arquitectura": "qwen3", "bytes_peso": 9276198565,
             "parametros": 14768307200, "parametros_activos": 14768307200, "fraccion_activa": 1.0,
             "capas": 40, "cabezas_kv": 8, "dim_cabeza": 128, "kv_bytes_token_f16": 163840,
             "contexto_max": 40960, "es_moe": False, "piensa": True, "embedding": False}
QWEN3_30B_A3B = {"nombre": "qwen3:30b-a3b-q4_k_m", "arquitectura": "qwen3moe",
                 "bytes_peso": 18622563179, "parametros": 30532122624,
                 "parametros_activos": 3353032704, "fraccion_activa": 0.1098, "capas": 48,
                 "cabezas_kv": 4, "dim_cabeza": 128, "kv_bytes_token_f16": 98304,
                 "contexto_max": 40960, "es_moe": True, "piensa": True, "embedding": False}
QWEN3_8B = {"nombre": "qwen3:8b", "arquitectura": "qwen3", "bytes_peso": 5225374496,
            "parametros": 8619174426, "parametros_activos": 8619174426, "fraccion_activa": 1.0,
            "capas": 36, "cabezas_kv": 8, "dim_cabeza": 128, "kv_bytes_token_f16": 147456,
            "contexto_max": 40960, "es_moe": False, "piensa": True, "embedding": False}
# qwen2.5:32b, aproximada con la geometría real (64 capas, 8 cabezas KV)
QWEN25_32B = {"nombre": "qwen2.5:32b", "arquitectura": "qwen2", "bytes_peso": 19851336640,
              "parametros": 32763876352, "parametros_activos": 32763876352,
              "fraccion_activa": 1.0, "capas": 64, "cabezas_kv": 8, "dim_cabeza": 128,
              "kv_bytes_token_f16": 262144, "contexto_max": 32768, "es_moe": False,
              "piensa": False, "embedding": False}
TODAS = [QWEN25_7B, QWEN3_8B, QWEN3_14B, QWEN3_30B_A3B, QWEN25_32B]

# Medido en la máquina de referencia (fase 0): contexto → (GB totales, fracción GPU, tok/s)
FASE0 = {
    "qwen2.5-coder:7b": {2048: (4.63, 1.0, 39.9), 4096: (4.75, 1.0, 37.2), 8192: (5.38, 0.877, 31.4)},
    "qwen3:14b-q4_k_m": {2048: (9.81, 0.477, 6.4), 4096: (10.15, 0.476, 6.3), 8192: (10.82, 0.43, 4.7)},
    "qwen3:30b-a3b-q4_k_m": {2048: (19.06, 0.254, 25.5), 4096: (19.29, 0.249, 22.0),
                             8192: (19.67, 0.246, 26.4)},
}
CALIBRACION_REFERENCIA = {"presupuesto_gpu": 4.85e9, "vram_parcial": 4.75e9,
                          "ancho_gpu": 178.0, "ancho_cpu": 38.0}


def radiografia(gpu=None, vram_mb=0, ram_gb=64, fabricante="nvidia", unificada=False,
                entorno=None, ajenos_mb=0, ancho_ram=10.0):
    gpus = []
    if gpu:
        gpus.append({"fabricante": fabricante, "nombre": gpu, "vram_total_mb": vram_mb,
                     "memoria_unificada": unificada, "flash_attention": True,
                     "otros_procesos": ([{"pid": 1, "proceso": "juego", "mb": ajenos_mb}]
                                        if ajenos_mb else [])})
    return {"huella": f"{gpu}-{vram_mb}-{ram_gb}", "gpus": gpus,
            "memoria": {"ram_total": ram_gb * GB, "ram_disponible": ram_gb * GB * 0.8,
                        "swap_usada": 0},
            "cpu": {"nucleos_fisicos": 8}, "ancho_banda_ram_gbps": ancho_ram,
            "ollama": {"entorno": entorno or {}}}


def referencia(entorno=None, calibrada=True):
    return Maquina(radiografia("NVIDIA GeForce RTX 4050 Laptop GPU", 6141, 62, entorno=entorno),
                   CALIBRACION_REFERENCIA if calibrada else None)


# ===========================================================================

class PruebaCalculadoraContraLoMedido(unittest.TestCase):

    def test_memoria_reparto_y_velocidad_de_la_fase0(self):
        maq = referencia()
        fichas = {f["nombre"]: f for f in TODAS}
        for modelo, por_ctx in FASE0.items():
            for ctx, (gb, frac, tok_s) in por_ctx.items():
                with self.subTest(modelo=modelo, ctx=ctx):
                    e = estimar(fichas[modelo], maq, ctx)
                    self.assertLess(abs(e["total_gb"] - gb) / gb, 0.10, e)
                    self.assertLess(abs(e["fraccion_gpu"] - frac), 0.10, e)
                    self.assertLess(abs(e["tok_s"] - tok_s) / tok_s, 0.25, e)

    def test_el_moe_repartido_va_mas_rapido_que_el_denso_de_14b(self):
        maq = referencia()
        self.assertGreater(estimar(QWEN3_30B_A3B, maq, 4096)["tok_s"],
                           3 * estimar(QWEN3_14B, maq, 4096)["tok_s"])

    def test_sin_calibrar_los_previos_no_se_alejan_demasiado(self):
        """ Los valores previos tienen que servir antes de medir nada """
        maq = referencia(calibrada=False)
        self.assertFalse(maq.calibrada)
        e = estimar(QWEN25_7B, maq, 4096)
        self.assertEqual(e["donde"], "gpu")
        self.assertLess(abs(e["tok_s"] - 37.2) / 37.2, 0.35)


class PruebaVeredictos(unittest.TestCase):

    def test_referencia_6gb(self):
        maq = referencia()
        self.assertEqual(recomendar(QWEN25_7B, maq, "extraccion")["veredicto"], "entero")
        self.assertEqual(recomendar(QWEN3_30B_A3B, maq, "extraccion")["veredicto"], "parcial")
        self.assertIn(recomendar(QWEN3_14B, maq, "extraccion")["veredicto"], ("lento", "parcial"))

    def test_un_32b_nunca_sale_entero_en_6gb(self):
        for maq in (referencia(), referencia(calibrada=False)):
            for perfil in ("extraccion", "tutor", "flujos", "revision"):
                r = recomendar(QWEN25_32B, maq, perfil)
                self.assertNotIn(r["veredicto"], ("entero", "ajustando"), (perfil, r["motivo"]))

    def test_extraccion_nunca_cuantiza_la_cache(self):
        for maq in (referencia(), referencia({"OLLAMA_KV_CACHE_TYPE": "f16"})):
            for f in TODAS:
                for tirador in ("calidad", "equilibrado", "velocidad"):
                    r = recomendar(f, maq, "extraccion", tirador)
                    self.assertEqual(r["estimacion"]["kv"], "f16", (f["nombre"], tirador))
                    m = r.get("mejora_con_servidor")
                    if m:
                        self.assertNotEqual(m["cambios"].get("OLLAMA_KV_CACHE_TYPE"), "q8_0")

    def test_no_supone_dos_ranuras_si_el_servidor_tiene_una(self):
        r = recomendar(QWEN25_7B, referencia(), "extraccion")
        self.assertEqual(r["estimacion"]["paralelo"], 1)

    def test_con_dos_ranuras_en_el_servidor_se_cuenta_la_cache_doble(self):
        """ Ollama reserva caché para todas las ranuras aunque llegue una petición """
        una = recomendar(QWEN25_7B, referencia(), "tutor")["estimacion"]
        dos = recomendar(QWEN25_7B, referencia({"OLLAMA_NUM_PARALLEL": "2"}), "tutor")["estimacion"]
        self.assertEqual(dos["paralelo"], 2)
        self.assertGreater(kv_bytes(QWEN25_7B, dos["ctx"], 2), kv_bytes(QWEN25_7B, una["ctx"], 1))

    def test_tutor_respeta_la_cache_del_servidor_y_propone_el_cambio_aparte(self):
        r = recomendar(QWEN25_7B, referencia(), "tutor")
        self.assertEqual(r["estimacion"]["kv"], "f16")
        m = r["mejora_con_servidor"]
        self.assertIsNotNone(m)
        self.assertEqual(m["cambios"].get("OLLAMA_KV_CACHE_TYPE"), "q8_0")
        self.assertTrue(any("79" in c for c in m["contras"]))

        r = recomendar(QWEN25_7B, referencia({"OLLAMA_KV_CACHE_TYPE": "q8_0",
                                              "OLLAMA_FLASH_ATTENTION": "1"}), "tutor")
        self.assertEqual(r["estimacion"]["kv"], "q8_0")
        self.assertIsNone(r["aviso_servidor"])

    def test_extraccion_con_servidor_en_q8_avisa_y_propone_volver(self):
        maq = referencia({"OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_FLASH_ATTENTION": "1"})
        r = recomendar(QWEN25_7B, maq, "extraccion")
        self.assertIsNotNone(r["aviso_servidor"])
        self.assertEqual(r["mejora_con_servidor"]["cambios"].get("OLLAMA_KV_CACHE_TYPE"), "f16")

    def test_portatil_4gb(self):
        maq = Maquina(radiografia("NVIDIA GeForce RTX 3050 Laptop GPU", 4096, 16))
        self.assertNotIn(recomendar(QWEN25_7B, maq, "tutor")["veredicto"], ("entero",))
        self.assertEqual(recomendar(QWEN3_30B_A3B, maq, "tutor")["veredicto"], "no_viable")

    def test_12gb(self):
        maq = Maquina(radiografia("NVIDIA GeForce RTX 3060", 12288, 32))
        self.assertIn(recomendar(QWEN3_14B, maq, "extraccion")["veredicto"], ("entero", "ajustando"))
        self.assertNotIn(recomendar(QWEN25_32B, maq, "extraccion")["veredicto"],
                         ("entero", "ajustando"))

    def test_24gb(self):
        maq = Maquina(radiografia("NVIDIA GeForce RTX 4090", 24564, 64))
        self.assertEqual(recomendar(QWEN3_14B, maq, "tutor")["veredicto"], "entero")
        self.assertIn(recomendar(QWEN3_30B_A3B, maq, "extraccion")["veredicto"],
                      ("entero", "ajustando"))
        self.assertGreater(estimar(QWEN3_14B, maq, 4096)["tok_s"], 40)

    def test_solo_cpu_16gb(self):
        maq = Maquina(radiografia(None, ram_gb=16))
        self.assertFalse(maq.hay_gpu)
        r = recomendar(QWEN25_7B, maq, "tutor")
        self.assertIn(r["veredicto"], ("solo_cpu", "lento"))
        self.assertEqual(r["estimacion"]["fraccion_gpu"], 0.0)
        self.assertEqual(recomendar(QWEN25_32B, maq, "tutor")["veredicto"], "no_viable")

    def test_apple_memoria_unificada(self):
        """ Lo que va en la "GPU" también sale de la RAM: no se puede contar dos veces """
        maq = Maquina(radiografia("Apple M2", int(16 * 0.66 * 1024), 16, fabricante="apple",
                                  unificada=True))
        self.assertIn(recomendar(QWEN25_7B, maq, "tutor")["veredicto"], ("entero", "ajustando"))
        self.assertEqual(recomendar(QWEN3_30B_A3B, maq, "tutor")["veredicto"], "no_viable")
        self.assertTrue(estimar(QWEN3_14B, maq, 4096)["riesgo_swap"] or
                        estimar(QWEN3_14B, maq, 4096)["donde"] != "gpu")

    def test_amd(self):
        maq = Maquina(radiografia("AMD Radeon RX 7600", 8176, 32, fabricante="amd"))
        self.assertTrue(maq.hay_gpu)
        self.assertIn(recomendar(QWEN25_7B, maq, "extraccion")["veredicto"], ("entero", "ajustando"))

    def test_otros_programas_en_la_gpu_quitan_sitio(self):
        libre = Maquina(radiografia("NVIDIA GeForce RTX 4050 Laptop GPU", 6141, 62))
        ocupada = Maquina(radiografia("NVIDIA GeForce RTX 4050 Laptop GPU", 6141, 62,
                                      ajenos_mb=2500))
        self.assertEqual(estimar(QWEN25_7B, libre, 4096)["donde"], "gpu")
        self.assertNotEqual(estimar(QWEN25_7B, ocupada, 4096)["donde"], "gpu")

    def test_elegir_modelo_prefiere_util_y_salta_embeddings(self):
        emb = {**QWEN25_7B, "nombre": "bge-m3", "embedding": True}
        filas = elegir_modelo(TODAS + [emb], referencia(), "extraccion")
        self.assertNotIn("bge-m3", [f["modelo"] for f in filas])
        self.assertTrue(filas[0]["util"])
        self.assertNotEqual(filas[0]["modelo"], "qwen2.5:32b")

    def test_tutor_prefiere_el_moe_rapido_al_14b_lento(self):
        """ Regresión: sin calibrar, el tutor elegía qwen3:14b (estimado 8,5 tok/s,
        medido 4,7) antes que qwen3:30b-a3b (22-31 tok/s) de calidad parecida """
        for maq in (referencia(), referencia(calibrada=False)):
            for tirador in ("equilibrado", "calidad"):
                filas = elegir_modelo([QWEN25_7B, QWEN3_14B, QWEN3_30B_A3B], maq, "tutor", tirador)
                self.assertEqual(filas[0]["modelo"], "qwen3:30b-a3b-q4_k_m", (tirador, maq.calibrada))
        # El 14B, a menos de 8 tok/s en su cota baja, no se vende como útil para el tutor
        r = recomendar(QWEN3_14B, referencia(), "tutor")
        self.assertEqual(r["veredicto"], "lento")

    def test_opciones_no_fijan_capas(self):
        """ Forzar num_gpu no aceleró nada y provocó OOM: solo se baja al recuperarse """
        for f in TODAS:
            self.assertNotIn("num_gpu", recomendar(f, referencia(), "tutor")["opciones"])

    def test_servidor_efectivo(self):
        self.assertEqual(servidor_efectivo({}), {"kv": "f16", "paralelo": 1,
                                                  "flash_attention": False, "max_modelos": None})
        s = servidor_efectivo({"OLLAMA_KV_CACHE_TYPE": "Q8_0", "OLLAMA_NUM_PARALLEL": "x",
                               "OLLAMA_FLASH_ATTENTION": "true"})
        self.assertEqual((s["kv"], s["paralelo"], s["flash_attention"]), ("q8_0", 1, True))


# ===========================================================================

def _gguf(pares, tensores=0):
    """ Cabecera GGUF v3 sintética """
    def cadena(t):
        b = t.encode()
        return struct.pack("<Q", len(b)) + b
    cuerpo = b""
    for clave, tipo, valor in pares:
        cuerpo += cadena(clave) + struct.pack("<I", tipo)
        if tipo == 8:
            cuerpo += cadena(valor)
        elif tipo == 4:
            cuerpo += struct.pack("<I", valor)
        elif tipo == 9:
            sub, items = valor
            cuerpo += struct.pack("<I", sub) + struct.pack("<Q", len(items))
            for it in items:
                cuerpo += cadena(it) if sub == 8 else struct.pack("<I", it)
    return b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", tensores) + \
        struct.pack("<Q", len(pares)) + cuerpo


class PruebaFichas(unittest.TestCase):
    PARES = [("general.architecture", 8, "qwen3moe"),
             ("tokenizer.ggml.tokens", 9, (8, ["a", "bb", "ccc"] * 1000)),
             ("qwen3moe.block_count", 4, 48), ("qwen3moe.attention.head_count", 4, 32),
             ("qwen3moe.attention.head_count_kv", 4, 4), ("qwen3moe.embedding_length", 4, 2048),
             ("qwen3moe.attention.key_length", 4, 128), ("qwen3moe.context_length", 4, 40960),
             ("qwen3moe.expert_count", 4, 128), ("qwen3moe.expert_used_count", 4, 8),
             ("qwen3moe.expert_feed_forward_length", 4, 768)]

    def test_gguf_lee_metadatos_y_salta_el_vocabulario(self):
        meta = gguf.leer_metadatos(_gguf(self.PARES))
        self.assertEqual(meta["qwen3moe.block_count"], 48)
        self.assertNotIn("tokenizer.ggml.tokens", {k for k, v in meta.items() if v})

    def test_gguf_pide_mas_bytes_si_la_cabecera_no_cabe(self):
        datos = _gguf(self.PARES)
        pedidos = []

        def pedir(desde, hasta):
            pedidos.append((desde, hasta))
            return datos[desde:hasta + 1]
        meta = gguf.leer_con_rangos(pedir, inicial=64)
        self.assertEqual(meta["qwen3moe.expert_count"], 128)
        self.assertGreater(len(pedidos), 1)

    def test_gguf_rechaza_lo_que_no_es_gguf(self):
        with self.assertRaises(Exception):
            gguf.leer_metadatos(b"PK\x03\x04" + b"\0" * 100)

    def test_ficha_moe_calcula_activos_y_cache(self):
        meta = gguf.leer_metadatos(_gguf(self.PARES))
        meta["general.parameter_count"] = 30532122624
        f = desde_metadatos(meta, "qwen3:30b-a3b", 18622563179, capacidades=["thinking"])
        self.assertTrue(f["es_moe"])
        self.assertAlmostEqual(f["parametros_activos"] / 1e9, 3.4, delta=0.2)
        self.assertEqual(f["kv_bytes_token_f16"], QWEN3_30B_A3B["kv_bytes_token_f16"])
        self.assertTrue(f["piensa"])

    def test_kv_bytes(self):
        self.assertEqual(kv_bytes(QWEN25_7B, 4096), 57344 * 4096)
        self.assertEqual(kv_bytes(QWEN25_7B, 4096, 2), 2 * 57344 * 4096)
        self.assertLess(kv_bytes(QWEN25_7B, 4096, 1, "q8_0"), kv_bytes(QWEN25_7B, 4096))


# ===========================================================================

class _SinSensores(unittest.TestCase):
    """ Sin nvidia-smi, sin Ollama y sin esperas reales """

    def setUp(self):
        self.parches = [mock.patch.object(calibracion, "estado_gpu", return_value=None),
                        mock.patch.object(calibracion, "descargar"),
                        mock.patch.object(calibracion.time, "sleep")]
        for p in self.parches:
            p.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {
            "PRIG_RECURSOS_ARCHIVO": os.path.join(self.tmp.name, "recursos.json")})
        self.env.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()


def _respuesta_ok(texto="{}", tok=160, seg=4.0):
    return {"response": texto, "eval_count": tok, "eval_duration": int(seg * 1e9),
            "prompt_eval_count": 500, "prompt_eval_duration": int(0.3e9),
            "load_duration": int(2e9)}


class PruebaCalibracion(_SinSensores):

    def test_canario_distingue_citas_literales_de_inventadas(self):
        buena = "Cuanto mayor es lambda, más se penalizan los pesos grandes"
        mala = "La regularización L2 siempre lleva los pesos exactamente a cero"
        r = calibracion.puntuar_canario(json.dumps(
            {"afirmaciones": [{"texto": "x", "cita": buena}, {"texto": "y", "cita": mala}]}))
        self.assertEqual((r["citas"], r["citas_literales"], r["calidad"]), (2, 1, 0.5))
        self.assertEqual(calibracion.puntuar_canario("no es json")["calidad"], 0.0)
        self.assertFalse(calibracion.puntuar_canario("no es json")["fiable"])

    def test_canario_lee_citas_de_un_json_cortado(self):
        """ Regresión: el tope de tokens cortaba el JSON y todo modelo puntuaba 0 """
        cortado = ('{"afirmaciones": [{"texto": "a", "cita": "Cuanto mayor es lambda, más se '
                   'penalizan los pesos grandes"}, {"texto": "b", "cita": "La parada temprana '
                   'detiene el entrenamiento"}, {"texto": "c", "cita": "Durante la infer')
        r = calibracion.puntuar_canario(cortado)
        self.assertFalse(r["json_valido"])
        self.assertEqual((r["citas"], r["citas_literales"], r["calidad"], r["fiable"]),
                         (2, 2, 1.0, True))

    def test_oom_baja_contexto_y_luego_capas(self):
        errores = ["llama runner process has terminated: cudaMalloc failed: out of memory",
                   "CUDA error: out of memory"]
        cuerpos = []

        def generar(cuerpo):
            cuerpos.append(cuerpo["options"].copy())
            if errores:
                raise RuntimeError(errores.pop(0))
            return _respuesta_ok(json.dumps({"afirmaciones": []}))

        r = calibracion.probar(QWEN3_14B, {"num_ctx": 4096}, generar=generar,
                               ps=lambda m: {"size": 10e9, "size_vram": 4.7e9})
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["recuperado_de_oom"])
        self.assertEqual(cuerpos[1]["num_ctx"], 2048)
        self.assertIn("num_gpu", cuerpos[2])
        self.assertLess(cuerpos[2]["num_gpu"], QWEN3_14B["capas"] + 1)
        self.assertEqual(r["tok_s"], 40.0)
        # Qwen3 piensa: la prueba lo apaga para medir generación y JSON limpios
        self.assertEqual(r["opciones"], {"num_ctx": 2048, "num_gpu": cuerpos[2]["num_gpu"]})

    def test_error_que_no_es_memoria_no_se_reintenta(self):
        llamadas = []

        def generar(cuerpo):
            llamadas.append(1)
            raise RuntimeError("model 'x' not found")
        r = calibracion.probar(QWEN25_7B, {"num_ctx": 4096}, generar=generar, ps=lambda m: None)
        self.assertFalse(r["ok"])
        self.assertEqual(len(llamadas), 1)

    def test_reducir_termina(self):
        opc, pasos = {"num_ctx": 8192}, 0
        while opc is not None:
            opc = calibracion.reducir(QWEN25_7B, opc)
            pasos += 1
            self.assertLess(pasos, 20)

    def test_cancelar(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(calibracion.Cancelado):
            calibracion.probar(QWEN25_7B, {}, cancelar=ev, generar=lambda c: _respuesta_ok())

    def test_deducir_recupera_los_anchos_de_la_referencia(self):
        maq = referencia(calibrada=False)
        # 7B entero: 37,2 tok/s a 4096
        d = calibracion.deducir(QWEN25_7B, {"ok": True, "tok_s": 37.2, "total_gb": 4.75,
                                            "fraccion_gpu": 1.0, "opciones": {"num_ctx": 4096}}, maq)
        self.assertLess(abs(d["ancho_gpu"] - 178) / 178, 0.12)
        maq = Maquina(maq.radiografia, {"ancho_gpu": d["ancho_gpu"]})
        # 14B repartido: 6,3 tok/s con el 47,6 % en GPU
        d2 = calibracion.deducir(QWEN3_14B, {"ok": True, "tok_s": 6.3, "total_gb": 10.15,
                                             "fraccion_gpu": 0.476, "opciones": {"num_ctx": 4096}}, maq)
        self.assertLess(abs(d2["ancho_cpu"] - 38) / 38, 0.30, d2)
        self.assertAlmostEqual(d2["vram_parcial"] / GB, 4.83, delta=0.2)

    def test_capas_forzadas_no_calibran(self):
        d = calibracion.deducir(QWEN3_14B, {"ok": True, "tok_s": 6.0, "total_gb": 10,
                                            "fraccion_gpu": 0.5,
                                            "opciones": {"num_ctx": 2048, "num_gpu": 10}},
                                referencia())
        self.assertEqual(d, {})

    def test_combinar_usa_la_mediana_y_respeta_lo_que_cupo(self):
        v = calibracion.combinar(None, [{"ancho_gpu": 170}, {"ancho_gpu": 180},
                                        {"ancho_gpu": 900}])
        self.assertEqual(v["ancho_gpu"], 180)
        v = calibracion.combinar(v, [{"presupuesto_gpu": 4.0e9, "presupuesto_minimo": 4.8e9}])
        self.assertGreaterEqual(v["presupuesto_gpu"], 4.8e9)
        self.assertNotIn("presupuesto_minimo", v)

    def test_elegir_modelos_de_prueba(self):
        elegidos = [f["nombre"] for f in calibracion.elegir_modelos_prueba(TODAS, referencia())]
        self.assertEqual(elegidos[0], "qwen2.5-coder:7b")        # cabe entero
        self.assertEqual(len(elegidos), 2)
        self.assertNotIn("qwen2.5:32b", elegidos)                  # demasiado repartido

    def test_una_sola_calibracion_a_la_vez(self):
        self.assertTrue(calibracion.EN_CURSO.acquire(blocking=False))
        try:
            with self.assertRaises(RuntimeError):
                calibracion.calibrar(TODAS, referencia())
        finally:
            calibracion.EN_CURSO.release()


# ===========================================================================

class PruebaAlmacen(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.tmp.name, "r.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_calibracion_por_huella(self):
        a = Almacen(self.ruta)
        a.registrar_radiografia({"huella": "A"})
        a.guardar_calibracion("A", {"ancho_gpu": 178})
        self.assertEqual(a.calibracion()["ancho_gpu"], 178)

        r = a.registrar_radiografia({"huella": "B"})     # otra GPU, otro driver…
        self.assertTrue(r["cambio"])
        self.assertIsNone(a.calibracion())

        a.registrar_radiografia({"huella": "A"})         # se vuelve a la de antes
        self.assertEqual(Almacen(self.ruta).calibracion()["ancho_gpu"], 178)

    def test_restaurar_vuelve_a_lo_original_aunque_se_aplique_dos_veces(self):
        a = Almacen(self.ruta)
        a.registrar_aplicado("tutor", "m1", {"num_ctx": 8192}, {"num_ctx": 2048, "num_gpu": 20})
        a.registrar_aplicado("tutor", "m2", {"num_ctx": 4096}, {"num_ctx": 8192, "num_gpu": -1})
        self.assertEqual(a.quitar_aplicado("tutor"), {"num_ctx": 2048, "num_gpu": 20})
        self.assertIsNone(a.quitar_aplicado("tutor"))

    def test_ultima_buena_solo_en_esta_maquina(self):
        a = Almacen(self.ruta)
        a.registrar_radiografia({"huella": "A"})
        a.guardar_prueba("A", "m", "tutor", {"ok": True, "opciones": {"num_ctx": 4096}})
        self.assertEqual(a.ultima_buena("tutor")["modelo"], "m")
        a.registrar_radiografia({"huella": "B"})
        self.assertIsNone(a.ultima_buena("tutor"))

    def test_archivo_roto_se_aparta_sin_perderlo(self):
        with open(self.ruta, "w") as f:
            f.write("{roto")
        a = Almacen(self.ruta)
        self.assertIsNone(a.calibracion())
        self.assertTrue(any(n.startswith("r.json.roto-") for n in os.listdir(self.tmp.name)))
        a.evento("x", "y")
        with open(self.ruta) as f:
            self.assertEqual(json.load(f)["eventos"][-1]["tipo"], "x")

    def test_eventos_acotados(self):
        a = Almacen(self.ruta)
        for i in range(260):
            a._evento("e", str(i))
        self.assertEqual(len(a.eventos(1000)), 200)


class PruebaServidor(unittest.TestCase):

    def test_cache_cuantizada_activa_flash_attention(self):
        self.assertEqual(servidor.validar({"OLLAMA_KV_CACHE_TYPE": "q8_0"}),
                         {"OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_FLASH_ATTENTION": "1"})

    def test_rechaza_lo_que_no_gestiona_o_no_es_valido(self):
        for malo in ({"OLLAMA_NOPRUNE": "1"}, {"OLLAMA_GPU_OVERHEAD": "1"}, {"OLLAMA_KV_CACHE_TYPE": "q2"},
                     {"OLLAMA_NUM_PARALLEL": "40"}, {"OLLAMA_NUM_PARALLEL": "dos"}):
            with self.assertRaises(ValueError):
                servidor.validar(malo)

    def test_instrucciones_para_systemd(self):
        t = servidor.instrucciones("systemd", {"OLLAMA_KV_CACHE_TYPE": "q8_0"})
        self.assertIn('Environment="OLLAMA_KV_CACHE_TYPE=q8_0"', t)
        self.assertIn("sudo systemctl edit ollama", t)
        self.assertIn("--user", servidor.instrucciones("systemd-usuario", {"A": "1"}))

    def test_no_reinicia_un_ollama_que_no_es_de_prig(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"PRIG_RECURSOS_ARCHIVO": os.path.join(tmp, "r.json")}), \
                mock.patch.object(servidor.detector, "ollama",
                                  return_value={"dueno": "systemd", "responde": True}), \
                mock.patch.object(servidor, "reiniciar_servidor") as reiniciar:
            r = servidor.aplicar({"OLLAMA_NUM_PARALLEL": "2"})
            reiniciar.assert_not_called()
            self.assertFalse(r["aplicado"])
            self.assertIn("systemctl", r["instrucciones"])

    def test_pide_confirmar_si_hay_modelos_cargados(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"PRIG_RECURSOS_ARCHIVO": os.path.join(tmp, "r.json")}), \
                mock.patch.object(servidor.detector, "ollama",
                                  return_value={"dueno": "prig", "responde": True,
                                                "modelos_cargados": [{"nombre": "m"}]}), \
                mock.patch.object(servidor, "reiniciar_servidor") as reiniciar:
            r = servidor.aplicar({"OLLAMA_NUM_PARALLEL": "2"})
            reiniciar.assert_not_called()
            self.assertTrue(r["necesita_confirmar"])

    def test_entorno_de_arranque_incluye_lo_guardado(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"PRIG_RECURSOS_ARCHIVO": os.path.join(tmp, "r.json")}):
            from recursos.almacen import almacen
            almacen().guardar_entorno_servidor({"OLLAMA_KV_CACHE_TYPE": "q8_0", "PATH": "x"})
            env = servidor.entorno_arranque({"PATH": "/usr/bin"})
            self.assertEqual(env["OLLAMA_KV_CACHE_TYPE"], "q8_0")
            self.assertEqual(env["PATH"], "/usr/bin")


class PruebaRecuperacionEnElMotor(_SinSensores):

    def test_generate_response_sobrevive_a_un_oom(self):
        from ai_engine import AIEngine
        from recursos import gestor as gestor_mod

        class Res:
            def __init__(self, codigo, cuerpo=None, lineas=()):
                self.status_code = codigo
                self._cuerpo = cuerpo or {}
                self._lineas = lineas

            def json(self):
                return self._cuerpo

            def iter_lines(self):
                return iter(self._lineas)

            def close(self):
                pass

        enviados = []
        respuestas = [Res(500, {"error": "llama runner process has terminated: "
                                         "cudaMalloc failed: out of memory"}),
                      Res(200, lineas=[json.dumps({"response": "hola", "done": True}).encode()])]

        def post(url, json=None, **kw):
            enviados.append(json["options"].copy())
            return respuestas.pop(0)

        motor = AIEngine.__new__(AIEngine)
        motor.base_url = "http://x"
        motor.config = {"num_ctx": 4096, "num_gpu": -1, "temperature": 0.3}
        motor._active_streams, motor._streams_lock = set(), threading.Lock()
        g = gestor_mod.Gestor()
        with mock.patch("ai_engine.ai_engine_class.requests.post", side_effect=post), \
                mock.patch.object(gestor_mod, "_gestor", g), \
                mock.patch.object(g, "ficha", return_value=QWEN25_7B):
            salida = "".join(motor.generate_response("hola", model="qwen2.5-coder:7b"))
        self.assertEqual(salida, "hola")
        self.assertEqual(enviados[0]["num_ctx"], 4096)
        self.assertEqual(enviados[1]["num_ctx"], 2048)
        self.assertEqual(motor._active_streams, set())


if __name__ == "__main__":
    unittest.main()
