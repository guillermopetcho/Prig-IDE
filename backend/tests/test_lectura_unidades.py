"""
Lectura por unidades (lectura_unidades.py): prefijo por capas, lectura con estado guardado,
expertos por unidad y preguntas sobre la lectura restaurada. Con un motor falso.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import banco_proyecto as bp
import lectura_unidades as lu
import particion_proyecto as pp


class MotorFalso:
    def __init__(self):
        self._proyecto_cargado = None


class AIFalsa:
    """ chat_eventos como el real: la primera vez «lee» la unidad (y el motor guarda su estado con una
    clave por prefijo); después la restaura """
    def __init__(self, carpeta):
        self.carpeta = carpeta
        self.motor = MotorFalso()
        self.llamadas = []

    def motor_moe(self):
        return self.motor

    def chat_eventos(self, mensajes, modelo, uso, **kw):
        herramientas = kw["herramientas"].definiciones()
        self.llamadas.append({"mensajes": mensajes, "herramientas": herramientas, "extra": kw.get("extra")})
        clave = json.dumps([mensajes[:2], herramientas], sort_keys=True).__hash__().__abs__().__str__()
        ruta = os.path.join(self.carpeta, clave + ".bin")
        origen = "disco" if os.path.exists(ruta) else "leido"
        with open(ruta, "wb") as f:
            f.write(b"x" * 100)
        with open(os.path.join(self.carpeta, clave + ".calientes.json"), "w") as f:
            json.dump([[2, 0], [1, 3]], f)
        self.motor._proyecto_cargado = clave
        self.motor.ultimo_proyecto = {"origen": origen, "tokens": 1234, "segundos": 2.0, "clave": clave}
        yield {"t": "texto", "v": "- purpose: calcula"}
        yield {"t": "stats", "v": {"generacion_tok_s": 30.0, "rondas": 1,
                                   "proyecto": {"origen": origen, "tokens": 1234, "segundos": 2.0}}}


class TestLectura(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_lectura_")
        raiz = os.path.join(self.tmp, "p")
        os.makedirs(os.path.join(raiz, "nucleo"))
        with open(os.path.join(raiz, "nucleo", "base.py"), "w") as f:
            f.write("def util():\n    return 1\n")
        with open(os.path.join(raiz, "app.py"), "w") as f:
            f.write("from nucleo.base import util\n\n\ndef usar():\n    return util()\n")
        self.banco = bp.BancoProyecto(raiz, carpeta=os.path.join(self.tmp, "banco"))
        self.banco.sincronizar()
        pp.particionar(self.banco, tope=20)                 # una unidad por archivo
        self.estados = os.path.join(self.tmp, "estados")
        os.makedirs(self.estados)
        self.ai = AIFalsa(self.estados)
        self.parche = mock.patch("ai_engine.motor_moe.CARPETA_PROYECTOS", self.estados)
        self.parche.start()
        self.lector = lu.LectorUnidades(self.banco, self.ai)

    def tearDown(self):
        self.parche.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prefijo_estable_y_contexto_con_la_pregunta(self):
        unidades = self.banco.unidades()
        u = [x for x in unidades if "app.py" in x["rutas"]][0]
        mensajes = self.lector.mensajes(u)
        texto = mensajes[1]["content"]
        self.assertEqual(mensajes[0]["content"], lu.SISTEMA_LECTOR)
        self.assertLess(texto.index("PROJECT CARD"), texto.index("<|file_sep|>app.py"))
        self.assertIn("<|repo_name|>p", texto)
        self.assertNotIn("Uses from other units", texto)             # lo del grafo no va en el prefijo
        pregunta = self.lector.pregunta_con_contexto(u, "¿Qué hace usar?")
        self.assertIn("Uses from other units:", pregunta)
        self.assertIn("nucleo/base.py", pregunta)
        self.assertTrue(pregunta.endswith("¿Qué hace usar?"))

    def test_tarjeta_congelada(self):
        tarjeta = self.lector.tarjeta_global()
        with open(os.path.join(self.banco.raiz, "nuevo.py"), "w") as f:
            f.write("def nuevo():\n    return 2\n")
        self.banco.sincronizar()
        otro = lu.LectorUnidades(self.banco, self.ai)
        self.assertEqual(otro.tarjeta_global(), tarjeta)             # agregar un archivo no la cambia
        self.assertIn("nuevo.py", otro.renovar_tarjeta())
        self.assertIn("nuevo.py", lu.LectorUnidades(self.banco, self.ai).tarjeta_global())

    def test_unidad_renumerada_se_reusa(self):
        self.lector.leer(0)
        n = len(self.ai.llamadas)
        with self.banco.conectar() as c:                             # simula que la unidad cambió de número
            c.execute("UPDATE unidades SET orden = 50 WHERE orden = 0")
        lector = lu.LectorUnidades(self.banco, self.ai)
        r = lector.leer(50)
        self.assertEqual(r["origen"], "reusada")
        self.assertEqual(len(self.ai.llamadas), n)                  # sin llamar al modelo
        self.assertTrue(lector.vigente(50))

    def test_pasada_tras_renumerar_no_pisa_registros(self):
        # Dos unidades leídas que intercambian su número al reparticionar: la pasada leía en orden y el
        # registro de una pisaba el de la otra (INSERT OR REPLACE por número) → se volvía a llamar al modelo
        self.lector.pasada()
        n = len(self.ai.llamadas)
        with self.banco.conectar() as c:
            c.execute("UPDATE unidades SET orden = 99 WHERE orden = 0")
            c.execute("UPDATE unidades SET orden = 0 WHERE orden = 1")
            c.execute("UPDATE unidades SET orden = 1 WHERE orden = 99")
        lector = lu.LectorUnidades(self.banco, self.ai)
        self.assertEqual(lector.pasada(), [])                         # todo se reasigna, nada se relee
        self.assertEqual(len(self.ai.llamadas), n)
        self.assertTrue(lector.vigente(0) and lector.vigente(1))

    def test_reasignar_borra_los_estados_que_ya_no_sirven(self):
        self.lector.pasada()
        viejo = self.lector.lectura(0)["archivo"]
        self.assertTrue(os.path.exists(os.path.join(self.estados, viejo)))
        with open(os.path.join(self.banco.raiz, "app.py"), "a") as f:     # cambia el código de una unidad
            f.write("\n\ndef otra():\n    return 3\n")
        self.banco.sincronizar(); pp.particionar(self.banco, tope=20)
        lector = lu.LectorUnidades(self.banco, self.ai)
        vigentes_antes = {lector.lectura(o)["archivo"] for o in lector._unidades if lector.lectura(o)}
        lector.reasignar()
        en_disco = set(os.listdir(self.estados))
        usados = {lector.lectura(o)["archivo"] for o in lector._unidades if lector.lectura(o)}
        self.assertTrue(usados <= en_disco)                                  # lo que sirve sigue
        self.assertEqual({a for a in en_disco if a.endswith(".bin")} - usados, set())   # lo viejo se borró

    def test_reasignar_no_borra_estados_que_usa_otro_banco(self):
        # Dos carpetas con el mismo nombre y el mismo código comparten los estados del motor (mismo prefijo). Que una
        # cambie no puede borrarle a la otra una lectura válida
        self.lector.pasada()
        otra = os.path.join(self.tmp, "copia", "p")                 # mismo nombre de carpeta: mismo prefijo
        shutil.copytree(self.banco.raiz, otra)
        banco2 = bp.BancoProyecto(otra, carpeta=os.path.join(self.tmp, "banco2"))
        banco2.sincronizar(); pp.particionar(banco2, tope=20)
        lector2 = lu.LectorUnidades(banco2, self.ai)
        lector2.pasada()
        compartidos = {lector2.lectura(o)["archivo"] for o in lector2._unidades}
        self.assertEqual(compartidos, {self.lector.lectura(o)["archivo"] for o in self.lector._unidades})
        with open(os.path.join(otra, "app.py"), "a") as f:          # cambia SOLO la copia
            f.write("\n\ndef otra():\n    return 3\n")
        banco2.sincronizar(); pp.particionar(banco2, tope=20)
        lu.LectorUnidades(banco2, self.ai).reasignar()
        for archivo in compartidos:                                   # el primer banco los sigue usando
            self.assertTrue(os.path.exists(os.path.join(self.estados, archivo)), archivo)
        original = lu.LectorUnidades(self.banco, self.ai)
        self.assertTrue(all(original.vigente(o) for o in original._unidades))

    def test_leer_guarda_estado_expertos_y_resumen(self):
        r = self.lector.leer(0)
        self.assertEqual(r["tokens"], 1234)
        self.assertEqual(r["origen"], "leido")
        self.assertEqual(r["expertos"], [[2, 0], [1, 3]])
        self.assertTrue(r["archivo"].endswith(".bin"))
        self.assertTrue(self.lector.vigente(0))
        self.assertEqual(self.lector.lectura(0)["resumen"], "- purpose: calcula")
        from ai_engine import motor_moe
        self.assertEqual(self.ai.llamadas[0]["extra"], {motor_moe.PERFIL: "preciso"})

    def test_mismo_prefijo_y_herramientas_fijas(self):
        """ Leer y preguntar usan exactamente el mismo prefijo y las mismas herramientas: el motor
        restaura la lectura en lugar de releerla """
        self.lector.leer(0)
        r = self.lector.preguntar(0, "¿Qué hace util?")
        a, b = self.ai.llamadas
        self.assertEqual(a["mensajes"][:2], b["mensajes"][:2])
        self.assertEqual(a["herramientas"], b["herramientas"])
        self.assertEqual([d["function"]["name"] for d in a["herramientas"]], list(lu.HERRAMIENTAS_UNIDAD))
        self.assertEqual(r["lectura"], "disco")

    def test_pasada_salta_lo_vigente(self):
        self.lector.pasada()
        n = len(self.ai.llamadas)
        self.assertEqual(self.lector.pasada(), [])
        self.assertEqual(len(self.ai.llamadas), n)

    def test_enrutador(self):
        con_util = [o for o, u in self.lector._unidades.items() if "nucleo/base.py" in u["rutas"]][0]
        r = self.lector.elegir_unidad("¿Qué devuelve `util` en nucleo/base.py?")
        self.assertEqual(r["orden"], con_util)
        self.assertFalse(r["vigente"])                                  # todavía no se leyó
        self.lector.leer(con_util)
        self.assertTrue(self.lector.elegir_unidad("¿Qué devuelve `util` en nucleo/base.py?")["vigente"])
        self.assertIsNone(self.lector.elegir_unidad("xyzzy")["orden"])  # nada coincide

    def test_cambiar_el_codigo_invalida_la_lectura(self):
        self.lector.leer(0)
        u = self.banco.unidades()[0]
        ruta = os.path.join(self.banco.raiz, u["rutas"][0])
        with open(ruta, "a") as f:
            f.write("\n# cambio\n")
        self.banco.sincronizar()
        lector = lu.LectorUnidades(self.banco, self.ai)
        self.assertFalse(lector.vigente(0))


if __name__ == "__main__":
    unittest.main()
