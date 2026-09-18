"""
Pruebas del catálogo de modelos y su descarga.

Los tamaños del catálogo están verificados contra el registro de Ollama, no
recordados. Lo que se protege aquí son los fallos que aparecieron al añadir Qwen3:

  · el registro responde 412 cuando tu Ollama es anterior al modelo, con un mensaje
    que no dice qué versión tienes ni qué hacer;
  · `pull_model` informa de ese fallo como una línea más de texto, así que una
    descarga fallida terminaba anunciando éxito;
  · Ollama guarda «bge-m3» como «bge-m3:latest», y comparar a secas lo marcaba como
    no instalado y lo enseñaba dos veces.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_flows
from agent_flows import (MODELOS, MODELOS_EMBEDDING, FlowEngine, ROLES,
                         version_suficiente, ollama_necesario, _sin_pensamiento)


class PruebaCatalogo(unittest.TestCase):

    def test_estan_todas_las_tallas_de_qwen3(self):
        """ No existe un 9B: las tallas son 0.6, 1.7, 4, 8, 14 y la MoE 30b-a3b. """
        qwen3 = {m for m in MODELOS if m.startswith("qwen3:")}
        self.assertEqual(qwen3, {"qwen3:0.6b", "qwen3:1.7b", "qwen3:4b",
                                 "qwen3:8b", "qwen3:14b", "qwen3:30b-a3b"})
        self.assertNotIn("qwen3:9b", MODELOS)

    def test_los_tamanos_coinciden_con_el_registro(self):
        """ Verificados uno a uno; si cambian, la decisión de qué cabe cambia. """
        for modelo, gb in (("qwen3:8b", 5.2), ("qwen3:4b", 2.5), ("qwen3:14b", 9.3),
                           ("qwen2.5-coder:7b", 4.7), ("gemma3:4b", 3.3)):
            self.assertAlmostEqual(MODELOS[modelo]["vram_gb"], gb, places=1)

    def test_cada_modelo_declara_si_piensa(self):
        for nombre, info in MODELOS.items():
            self.assertIn(info.get("piensa"), ("conmutable", "siempre", "no"), nombre)

    def test_solo_qwen3_tiene_pensamiento_conmutable(self):
        conmutables = {m for m, i in MODELOS.items() if i["piensa"] == "conmutable"}
        self.assertTrue(all(m.startswith("qwen3") for m in conmutables))

    def test_cada_modelo_dice_para_que_sirve(self):
        roles = set(ROLES)
        for nombre, info in MODELOS.items():
            self.assertTrue(info.get("fuerte_en"), nombre)
            for r in info["fuerte_en"]:
                self.assertIn(r, roles, f"{nombre} declara el rol inexistente '{r}'")
            self.assertTrue(info.get("nota"), nombre)

    def test_hay_modelos_para_cada_rol(self):
        """ Si un rol no tiene ningún modelo bueno, el catálogo está incompleto. """
        for rol in ROLES:
            self.assertTrue(any(rol in i["fuerte_en"] for i in MODELOS.values()),
                            f"ningún modelo declara ser bueno en '{rol}'")

    def test_los_embebedores_van_aparte(self):
        """ No generan texto: ofrecerlos como generador daría un flujo roto. """
        self.assertFalse(set(MODELOS) & set(MODELOS_EMBEDDING))
        self.assertIn("bge-m3", MODELOS_EMBEDDING)

    def test_nuevos_modelos_moe_y_razonadores(self):
        """ Verifica que los modelos solicitados estén disponibles y bien tipados.

        Solo nombres que existen en su registro (comprobado con el manifiesto): los que
        no existían en ninguna plataforma se sustituyeron por su equivalente real. """
        requeridos = [
            "hf.co/bartowski/OLMoE-1B-7B-0924-Instruct-GGUF:Q4_K_M", "deepseek-r1:8b",
            "qwen3-coder:30b", "dolphin3:8b", "hf.co/RichardErkhov/Qwen_-_Qwen1.5-MoE-A2.7B-Chat-gguf:Q4_K_M",
            "deepseek-coder-v2:16b", "qwen3:30b-a3b", "qwen3.6:35b-a3b",
            "hf.co/bartowski/Phi-3.5-MoE-instruct-GGUF:Q4_K_M", "mixtral:8x7b"
        ]
        inventados = ["olmoe:1b-7b", "r1-distill-qwen-math:1.5b", "deepseek-r1-0528-qwen3:8b", "qwen3-coder-r1:slerp",
                      "dolphin-qwen3-r1:abliterated", "dolphin-r1-qwen:14b", "qwen2.5-moe:2.7b",
                      "qwen3-30b-a3b:r1-distill", "qwen3.6-35b-a3b:latest", "phi3.5-moe:latest"]
        for m in inventados:
            self.assertNotIn(m, MODELOS, f"{m} no existe en ningún registro: no se puede descargar")
        for m in requeridos:
            self.assertIn(m, MODELOS, f"Modelo {m} falta en MODELOS")
            info = MODELOS[m]
            self.assertGreater(info["vram_gb"], 0)
            self.assertTrue(info["familia"])
            self.assertIn(info["piensa"], ("conmutable", "siempre", "no"))
            self.assertGreaterEqual(info["razona"], 1)
            self.assertTrue(len(info["fuerte_en"]) > 0)



class PruebaVersionDeOllama(unittest.TestCase):

    def test_compara_versiones(self):
        self.assertTrue(version_suficiente("0.6.6", "0.6.6"))
        self.assertTrue(version_suficiente("0.12.1", "0.6.6"))
        self.assertTrue(version_suficiente("1.0.0", "0.9.9"))
        self.assertFalse(version_suficiente("0.5.7", "0.6.6"))
        self.assertFalse(version_suficiente("0.6.5", "0.6.6"))

    def test_compara_bien_los_numeros_de_dos_cifras(self):
        """ Comparando como texto, "0.10" saldría menor que "0.9". """
        self.assertTrue(version_suficiente("0.10.0", "0.9.0"))

    def test_tolera_una_version_rara(self):
        self.assertFalse(version_suficiente("", "0.6.6"))
        self.assertTrue(version_suficiente("0.7.0-rc1", "0.6.6"))

    def test_qwen3_necesita_una_ollama_nueva(self):
        self.assertEqual(ollama_necesario("qwen3:8b"), "0.6.6")
        self.assertEqual(ollama_necesario("qwen3:0.6b"), "0.6.6")

    def test_los_de_siempre_no_piden_nada(self):
        self.assertIsNone(ollama_necesario("qwen2.5-coder:7b"))
        self.assertIsNone(ollama_necesario("llama3.1:8b"))


class PruebaPensamientoPorPaso(unittest.TestCase):
    """ Lo que hace útil a Qwen3 en toda la cadena: pensar donde aporta y callar
    donde estorba. """

    def paso(self, rol, modelo="qwen3:8b", **extra):
        return {"rol": rol, "modelo": modelo, **extra}

    def test_no_piensa_al_extraer(self):
        """ El bloque de pensamiento ensucia el JSON y se come la ventana. """
        for rol in ("extraer", "clasificar", "programar", "corregir"):
            self.assertFalse(FlowEngine.debe_pensar(self.paso(rol)), rol)

    def test_si_piensa_al_razonar(self):
        for rol in ("razonar", "criticar", "verificar", "redactar"):
            self.assertTrue(FlowEngine.debe_pensar(self.paso(rol)), rol)

    def test_en_un_modelo_sin_conmutador_no_se_pide_nada(self):
        """ Mandarle el campo no le afecta, pero no hay nada que decidir. """
        self.assertIsNone(FlowEngine.debe_pensar(self.paso("razonar", "qwen2.5-coder:7b")))
        self.assertIsNone(FlowEngine.debe_pensar(self.paso("extraer", "deepseek-r1:7b")))

    def test_el_usuario_puede_decidirlo(self):
        self.assertTrue(FlowEngine.debe_pensar(self.paso("extraer", pensar=True)))
        self.assertFalse(FlowEngine.debe_pensar(self.paso("razonar", pensar=False)))

    def test_un_modelo_desconocido_no_rompe(self):
        self.assertIsNone(FlowEngine.debe_pensar(self.paso("razonar", "inventado:7b")))


class PruebaLimpiezaDelPensamiento(unittest.TestCase):
    """ Un modelo que ignora la petición de no pensar no debe romper el paso
    siguiente: un <think> delante de un JSON hace que no parsee. """

    def test_quita_el_bloque_cerrado(self):
        self.assertEqual(_sin_pensamiento('<think>a ver...</think>{"a":1}'), '{"a":1}')

    def test_quita_el_bloque_sin_cerrar(self):
        self.assertEqual(_sin_pensamiento('{"a":1}\n<think>y ademas'), '{"a":1}')

    def test_acepta_la_variante_thinking(self):
        self.assertEqual(_sin_pensamiento('<thinking>x</thinking>hola'), 'hola')

    def test_no_toca_un_texto_normal(self):
        self.assertEqual(_sin_pensamiento('respuesta normal'), 'respuesta normal')

    def test_no_se_come_una_etiqueta_html_parecida(self):
        self.assertIn("thin", _sin_pensamiento('usa <thin> como clase css'))

    def test_tolera_el_vacio(self):
        self.assertEqual(_sin_pensamiento(""), "")
        self.assertEqual(_sin_pensamiento(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
