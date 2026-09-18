"""
Pruebas de los flujos de agentes.

El objetivo de encadenar modelos pequeños es no tener que cargar uno grande. Eso
solo funciona si la cadena está bien montada, y los fallos de montaje no dan error:
dan resultados peores sin decir por qué. De ahí que casi todo lo que se prueba aquí
sea validación previa.

Dos de estas pruebas nacieron de fallos en las plantillas que trae Prig de serie:
un paso usaba {critica} sin que ningún revisor le devolviera el trabajo (llegaba
siempre vacía), y el bucle de crítica reejecutaba el paso con el prompt idéntico,
así que el modelo devolvía exactamente lo mismo.
"""

import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_flows
from agent_flows import (FlowEngine, FlowStore, validar_flujo, plan_de_modelos,
                         plantillas, variables_usadas, _json_de, _recortar,
                         _texto_critica, ROLES)


def paso(pid, rol="razonar", modelo="m:7b", prompt="{entrada}", **extra):
    return {"id": pid, "nombre": pid, "rol": rol, "modelo": modelo, "prompt": prompt,
            "sistema": "", "formato": ROLES[rol]["formato"],
            "temperatura": ROLES[rol]["temperatura"], "max_tokens": 800, **extra}


def flujo(*pasos, nombre="Prueba"):
    return {"id": "f1", "nombre": nombre, "descripcion": "", "ambito": "libre",
            "pasos": list(pasos)}


class IASimulada:
    """ Devuelve lo que se le diga, y guarda todo lo que recibió """

    def __init__(self, respuestas=None):
        self.llamadas = []
        self.respuestas = list(respuestas or [])

    def generate_response(self, prompt, model=None, system_prompt="", options=None):
        self.llamadas.append({"prompt": prompt, "modelo": model,
                              "sistema": system_prompt, "opciones": options or {}})
        yield self.respuestas.pop(0) if self.respuestas else f"[salida de {model}]"


class PruebaValidacion(unittest.TestCase):

    def test_un_flujo_correcto_no_da_problemas(self):
        self.assertEqual(validar_flujo(flujo(paso("a"), paso("b", prompt="{anterior}"))), [])

    def test_exige_al_menos_un_paso(self):
        self.assertTrue(validar_flujo(flujo()))

    def test_caza_los_identificadores_repetidos(self):
        problemas = validar_flujo(flujo(paso("a"), paso("a", prompt="{anterior}")))
        self.assertTrue(any("repetido" in p for p in problemas))

    def test_caza_la_referencia_a_un_paso_que_no_existe(self):
        problemas = validar_flujo(flujo(paso("a"), paso("b", prompt="{paso:fantasma}")))
        self.assertTrue(any("fantasma" in p for p in problemas))

    def test_caza_la_referencia_a_un_paso_posterior(self):
        """ Un paso no puede leer la salida de otro que aún no se ha ejecutado. """
        problemas = validar_flujo(flujo(paso("a", prompt="{paso:b}"), paso("b")))
        self.assertTrue(any("paso:b" in p for p in problemas))

    def test_caza_anterior_en_el_primer_paso(self):
        problemas = validar_flujo(flujo(paso("a", prompt="{anterior}")))
        self.assertTrue(any("primer paso" in p for p in problemas))

    def test_caza_una_variable_inventada(self):
        problemas = validar_flujo(flujo(paso("a", prompt="{inventada}")))
        self.assertTrue(any("inventada" in p for p in problemas))

    def test_caza_critica_sin_nadie_que_la_produzca(self):
        """ {critica} solo tiene contenido si un revisor devuelve el trabajo a ese
        paso. En cualquier otro sitio llega vacía y el prompt queda cojo. """
        problemas = validar_flujo(flujo(paso("a"), paso("b", prompt="{critica}")))
        self.assertTrue(any("critica" in p and "vacía" in p for p in problemas), problemas)

    def test_acepta_critica_cuando_un_revisor_devuelve_el_trabajo(self):
        f = flujo(paso("escribir", prompt="{entrada} {critica}"),
                  paso("revisar", rol="criticar", prompt="{anterior}",
                       si_falla={"volver_a": "escribir", "max_vueltas": 2}))
        self.assertEqual(validar_flujo(f), [])

    def test_solo_un_revisor_puede_devolver_el_trabajo(self):
        f = flujo(paso("a"), paso("b", rol="redactar", prompt="{anterior}",
                                  si_falla={"volver_a": "a", "max_vueltas": 1}))
        self.assertTrue(any("revisor o un verificador" in p for p in validar_flujo(f)))

    def test_no_se_puede_volver_a_un_paso_posterior(self):
        f = flujo(paso("a", rol="criticar", si_falla={"volver_a": "b"}), paso("b"))
        self.assertTrue(any("no es un paso anterior" in p for p in validar_flujo(f)))

    def test_todas_las_plantillas_son_validas(self):
        """ Las que trae Prig de serie tienen que pasar su propia validación. """
        for p in plantillas("base:7b", "razona:7b"):
            self.assertEqual(validar_flujo(p), [], f"la plantilla '{p['nombre']}' no valida")


class PruebaPlanDeModelos(unittest.TestCase):
    """ Con 6 GB solo cabe un modelo: cada cambio es una recarga desde disco. """

    def test_un_solo_modelo_es_una_carga(self):
        p = plan_de_modelos(flujo(paso("a", modelo="x"), paso("b", modelo="x")))
        self.assertEqual((p["cargas"], p["recargas_evitables"]), (1, 0))

    def test_alternar_modelos_cuesta_una_carga_por_paso(self):
        p = plan_de_modelos(flujo(paso("a", modelo="x"), paso("b", modelo="y"),
                                  paso("c", modelo="x"), paso("d", modelo="y")))
        self.assertEqual(p["cargas"], 4)
        self.assertEqual(p["cargas_minimas"], 2)
        self.assertEqual(p["recargas_evitables"], 2)

    def test_agrupar_los_pasos_elimina_las_recargas(self):
        p = plan_de_modelos(flujo(paso("a", modelo="x"), paso("b", modelo="x"),
                                  paso("c", modelo="y"), paso("d", modelo="y")))
        self.assertEqual(p["recargas_evitables"], 0)

    def test_avisa_si_un_modelo_no_cabe(self):
        agent_flows.MODELOS["gigante:70b"] = {"vram_gb": 40.0, "familia": "x",
                                              "razona": 5, "fuerte_en": [], "nota": ""}
        try:
            p = plan_de_modelos(flujo(paso("a", modelo="gigante:70b")))
            self.assertFalse(p["cabe_en_vram"])
        finally:
            agent_flows.MODELOS.pop("gigante:70b")


class PruebaEjecucion(unittest.TestCase):

    def eventos(self, f, ia, entrada="tema", contexto=None):
        motor = FlowEngine(ia, contexto, num_ctx=4096)
        return list(motor.ejecutar(f, entrada=entrada))

    def test_los_pasos_corren_en_orden(self):
        ia = IASimulada()
        evs = self.eventos(flujo(paso("a"), paso("b", prompt="{anterior}")), ia)
        ids = [e["id"] for e in evs if e["tipo"] == "paso_fin"]
        self.assertEqual(ids, ["a", "b"])

    def test_la_salida_de_un_paso_llega_al_siguiente(self):
        ia = IASimulada(["PRIMERA SALIDA", "segunda"])
        self.eventos(flujo(paso("a"), paso("b", prompt="Toma: {anterior}")), ia)
        self.assertIn("PRIMERA SALIDA", ia.llamadas[1]["prompt"])

    def test_se_puede_referenciar_un_paso_por_su_id(self):
        ia = IASimulada(["SALIDA DE A", "b", "c"])
        self.eventos(flujo(paso("a"), paso("b", prompt="{anterior}"),
                           paso("c", prompt="Recupero: {paso:a}")), ia)
        self.assertIn("SALIDA DE A", ia.llamadas[2]["prompt"])

    def test_cada_paso_usa_su_propio_modelo(self):
        ia = IASimulada()
        self.eventos(flujo(paso("a", modelo="uno:7b"),
                           paso("b", modelo="dos:7b", prompt="{anterior}")), ia)
        self.assertEqual([l["modelo"] for l in ia.llamadas], ["uno:7b", "dos:7b"])

    def test_avisa_de_las_recargas_de_modelo(self):
        ia = IASimulada()
        evs = self.eventos(flujo(paso("a", modelo="uno:7b"),
                                 paso("b", modelo="uno:7b", prompt="{anterior}"),
                                 paso("c", modelo="dos:7b", prompt="{anterior}")), ia)
        recargas = [e["recarga_modelo"] for e in evs if e["tipo"] == "paso_inicio"]
        self.assertEqual(recargas, [True, False, True])

    def test_el_rol_define_la_instruccion_de_sistema(self):
        ia = IASimulada()
        self.eventos(flujo(paso("a", rol="extraer")), ia)
        self.assertIn("copiada carácter a carácter", ia.llamadas[0]["sistema"])

    def test_una_instruccion_propia_sustituye_a_la_del_rol(self):
        ia = IASimulada()
        self.eventos(flujo(paso("a", rol="extraer", sistema="Haz lo que te digo.")), ia)
        self.assertEqual(ia.llamadas[0]["sistema"], "Haz lo que te digo.")

    def test_el_contexto_de_biblioteca_llega_al_prompt(self):
        class Ctx:
            def ensamblar(self, consulta, presupuesto_tokens=None, **kw):
                return {"vacio": False, "texto": f"MATERIAL SOBRE {consulta}"}
        ia = IASimulada()
        self.eventos(flujo(paso("a", prompt="Tema {entrada}\n{contexto}")), ia,
                     entrada="gradiente", contexto=Ctx())
        self.assertIn("MATERIAL SOBRE gradiente", ia.llamadas[0]["prompt"])

    def test_un_flujo_invalido_no_llega_a_ejecutarse(self):
        ia = IASimulada()
        evs = self.eventos(flujo(paso("a", prompt="{inventada}")), ia)
        self.assertEqual(evs[0]["tipo"], "error")
        self.assertEqual(ia.llamadas, [], "no debería haber llamado al modelo")

    def test_reintenta_una_vez_si_el_json_sale_mal(self):
        ia = IASimulada(["esto no es json", '{"ok": true}'])
        evs = self.eventos(flujo(paso("a", rol="extraer")), ia)
        self.assertEqual(len(ia.llamadas), 2)
        self.assertIn("no era JSON válido", ia.llamadas[1]["prompt"])
        self.assertEqual([e for e in evs if e["tipo"] == "paso_fin"][0]["datos"], {"ok": True})


class PruebaBucleDeCritica(unittest.TestCase):
    """ El patrón que más mejora la calidad, y el que más fácil se monta mal. """

    def flujo_con_revisor(self):
        return flujo(
            paso("escribir", rol="redactar", prompt="Escribe sobre {entrada}"),
            paso("revisar", rol="criticar", prompt="Revisa: {anterior}",
                 si_falla={"volver_a": "escribir", "max_vueltas": 2}))

    def test_el_revisor_devuelve_el_trabajo_y_luego_aprueba(self):
        ia = IASimulada([
            "primer intento",
            json.dumps({"aprobado": False, "problemas": [
                {"donde": "el final", "que": "falta la conclusión", "arreglo": "añádela"}]}),
            "segundo intento",
            json.dumps({"aprobado": True, "problemas": []}),
        ])
        evs = list(FlowEngine(ia, None, 4096).ejecutar(self.flujo_con_revisor(), "tema"))
        vueltas = [e for e in evs if e["tipo"] == "vuelta"]
        self.assertEqual(len(vueltas), 1)
        self.assertEqual(vueltas[0]["hacia"], "escribir")
        self.assertEqual(len(ia.llamadas), 4)

    def test_la_reejecucion_ve_la_critica(self):
        """ Sin esto el bucle reejecuta el prompt idéntico y el modelo devuelve lo
        mismo: daría vueltas sin arreglar nada. """
        ia = IASimulada([
            "primer intento",
            json.dumps({"aprobado": False, "problemas": [
                {"donde": "el final", "que": "falta la conclusión", "arreglo": "añádela"}]}),
            "segundo intento",
            json.dumps({"aprobado": True, "problemas": []}),
        ])
        list(FlowEngine(ia, None, 4096).ejecutar(self.flujo_con_revisor(), "tema"))
        segundo = ia.llamadas[2]["prompt"]
        self.assertIn("falta la conclusión", segundo)
        self.assertNotEqual(segundo, ia.llamadas[0]["prompt"])

    def test_respeta_el_tope_de_vueltas(self):
        ia = IASimulada(["intento"] + [json.dumps({"aprobado": False,
                                                   "problemas": ["sigue mal"]}),
                                       "intento"] * 6)
        evs = list(FlowEngine(ia, None, 4096).ejecutar(self.flujo_con_revisor(), "tema"))
        self.assertLessEqual(len([e for e in evs if e["tipo"] == "vuelta"]), 2)
        self.assertTrue(any(e["tipo"] == "aviso" for e in evs))

    def test_si_aprueba_a_la_primera_no_hay_vuelta(self):
        ia = IASimulada(["intento", json.dumps({"aprobado": True, "problemas": []})])
        evs = list(FlowEngine(ia, None, 4096).ejecutar(self.flujo_con_revisor(), "tema"))
        self.assertEqual([e for e in evs if e["tipo"] == "vuelta"], [])
        self.assertEqual(len(ia.llamadas), 2)

    def test_un_verificador_con_incorrectas_tambien_devuelve_el_trabajo(self):
        f = flujo(paso("hacer", rol="programar", prompt="{entrada}"),
                  paso("comprobar", rol="verificar", prompt="{anterior}",
                       si_falla={"volver_a": "hacer", "max_vueltas": 1}))
        ia = IASimulada(["codigo v1",
                         json.dumps({"correctas": [], "incorrectas": [
                             {"afirmacion": "f(0)=1", "fallo": "da 0"}]}),
                         "codigo v2",
                         json.dumps({"correctas": ["todo"], "incorrectas": []})])
        evs = list(FlowEngine(ia, None, 4096).ejecutar(f, "algo"))
        self.assertEqual(len([e for e in evs if e["tipo"] == "vuelta"]), 1)
        self.assertIn("da 0", ia.llamadas[2]["prompt"])


class PruebaPresupuesto(unittest.TestCase):

    def test_recorta_por_el_medio_no_por_el_final(self):
        """ Truncar por el final se come las conclusiones, que es lo que importa. """
        texto = "INICIO" + ("x" * 5000) + "FINAL"
        r = _recortar(texto, 100)
        self.assertTrue(r.startswith("INICIO"))
        self.assertTrue(r.endswith("FINAL"))
        self.assertIn("recortado", r)

    def test_no_recorta_lo_que_ya_cabe(self):
        self.assertEqual(_recortar("corto", 1000), "corto")

    def test_un_prompt_con_muchas_variables_no_desborda(self):
        largo = "y" * 40000
        ia = IASimulada(["a", "b", "c"])
        f = flujo(paso("a"), paso("b", prompt="{anterior}"),
                  paso("c", prompt="{paso:a} {paso:b} {anterior} {entrada}"))
        motor = FlowEngine(ia, None, num_ctx=2048)
        list(motor.ejecutar(f, entrada=largo))
        tokens = len(ia.llamadas[2]["prompt"]) / 3.6
        self.assertLess(tokens, 2048, "el prompt se pasó de la ventana del modelo")


class PruebaUtilidades(unittest.TestCase):

    def test_extrae_json_entre_markdown(self):
        self.assertEqual(_json_de('Aquí tienes:\n```json\n{"a": 1}\n```'), {"a": 1})

    def test_extrae_una_lista(self):
        self.assertEqual(_json_de('resultado: [1, 2, 3]'), [1, 2, 3])

    def test_devuelve_none_si_no_hay_json(self):
        self.assertIsNone(_json_de("no hay nada de json por aquí"))

    def test_la_critica_se_convierte_en_instrucciones(self):
        t = _texto_critica({"problemas": [{"donde": "el título", "que": "es vago",
                                           "arreglo": "concretar"}]})
        self.assertIn("el título", t)
        self.assertIn("concretar", t)

    def test_detecta_las_variables_de_un_prompt(self):
        self.assertEqual(variables_usadas("{entrada} y {paso:uno} y {entrada}"),
                         ["entrada", "paso:uno"])


class PruebaAlmacen(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = FlowStore(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_guarda_y_recupera(self):
        g = self.store.guardar(flujo(paso("a"), nombre="Mi flujo"))
        self.assertTrue(g["id"])
        self.assertEqual(self.store.obtener(g["id"])["nombre"], "Mi flujo")

    def test_sobrevive_a_reabrir(self):
        g = self.store.guardar(flujo(paso("a"), nombre="Persistente"))
        otro = FlowStore(self.tmp)
        self.assertEqual(otro.obtener(g["id"])["nombre"], "Persistente")

    def test_borra(self):
        g = self.store.guardar(flujo(paso("a")))
        self.assertTrue(self.store.borrar(g["id"]))
        self.assertIsNone(self.store.obtener(g["id"]))
        self.assertFalse(self.store.borrar(g["id"]))

    def test_el_historial_guarda_el_prompt_de_cada_paso(self):
        """ Es lo único que permite arreglar un flujo que da malos resultados. """
        f = self.store.guardar(flujo(paso("a")))
        registro = [{"id": "a", "nombre": "a", "rol": "razonar", "modelo": "m:7b",
                     "segundos": 1.0, "prompt": "EL PROMPT EXACTO", "salida": "s",
                     "vuelta": 0}]
        eid = self.store.anotar_ejecucion(f, "entrada", registro, 1.0)
        self.assertEqual(self.store.ejecucion(eid)["pasos"][0]["prompt"], "EL PROMPT EXACTO")

    def test_el_resumen_del_historial_no_arrastra_los_prompts(self):
        f = self.store.guardar(flujo(paso("a")))
        self.store.anotar_ejecucion(f, "e", [{"id": "a", "prompt": "x" * 9000,
                                              "salida": "y"}], 1.0)
        fila = self.store.historial()[0]
        self.assertNotIn("pasos", fila)
        self.assertEqual(fila["n_pasos"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
