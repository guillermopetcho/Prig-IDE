"""
Fichas por símbolo (fichas_simbolos.py): escritura por tandas sobre la unidad restaurada,
verificación sin modelo y regeneración solo de lo que cambió. Con un lector falso.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import banco_proyecto as bp
import fichas_simbolos as fs
import particion_proyecto as pp

CODIGO = '''LIMITE = 5


def calcular(x):
    """Multiplica."""
    return x * LIMITE


def usar():
    return calcular(2)
'''


class LectorFalso:
    def __init__(self, banco, respuestas):
        self._unidades = {u["orden"]: u for u in banco.unidades()}
        self.respuestas = respuestas
        self.pedidos = []

    def preguntar(self, orden, texto, max_rondas=10):
        self.pedidos.append(texto)
        return {"texto": self.respuestas.pop(0) if self.respuestas else "[]"}


class TestFichas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_fichas_")
        raiz = os.path.join(self.tmp, "p")
        os.makedirs(raiz)
        with open(os.path.join(raiz, "mod.py"), "w") as f:
            f.write(CODIGO)
        self.banco = bp.BancoProyecto(raiz, carpeta=os.path.join(self.tmp, "banco"))
        self.banco.sincronizar()
        pp.particionar(self.banco)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def respuesta(self, **extra):
        return json.dumps([
            {"name": "calcular", "does": "Multiplies `x` by `LIMITE`.", "contract": "x number -> number",
             "effects": "none", "risks": "none", "change": "edit `LIMITE` (see l.200)", **extra},
            {"name": "usar", "does": "Calls `calcular` with 2.", "contract": "-> number", "effects": "none",
             "risks": "none", "change": "edit l.10"},
        ])

    def test_fichar_y_verificar(self):
        lector = LectorFalso(self.banco, ["```json\n" + self.respuesta() + "\n```"])
        f = fs.Fichas(self.banco, lector)
        r = f.fichar_unidad(0)
        self.assertEqual(r["fichas"], 2)
        self.assertIn("- calcular (funcion", lector.pedidos[0])
        ficha = f.ficha("mod.py", "calcular")
        self.assertEqual(ficha["datos"]["contract"], "x number -> number")
        # `LIMITE` existe; «l.1» está fuera de calcular (l.4-6) pero la línea se cita desde change
        self.assertTrue(any("línea 200 no contiene" in p for p in ficha["problemas"]))
        self.assertEqual(f.ficha("mod.py", "usar")["problemas"], [])

    def test_linea_fuera_del_simbolo_valida_si_contiene_lo_citado(self):
        lector = LectorFalso(self.banco, [self.respuesta(change="edit `LIMITE` at l.1")])
        f = fs.Fichas(self.banco, lector)
        f.fichar_unidad(0)
        self.assertEqual(f.ficha("mod.py", "calcular")["problemas"], [])   # l.1 define LIMITE

    def test_detecta_nombres_inventados(self):
        lector = LectorFalso(self.banco, [self.respuesta(risks="calls `borrar_todo_rapido` sometimes")])
        f = fs.Fichas(self.banco, lector)
        f.fichar_unidad(0)
        self.assertIn("nombre inexistente: borrar_todo_rapido", f.ficha("mod.py", "calcular")["problemas"])

    def test_solo_rehace_lo_que_cambio(self):
        lector = LectorFalso(self.banco, [self.respuesta(), self.respuesta()])
        f = fs.Fichas(self.banco, lector)
        f.fichar_unidad(0)
        self.assertEqual(f.pendientes(0), [])
        with open(os.path.join(self.banco.raiz, "mod.py"), "w") as fh:
            fh.write(CODIGO.replace("return calcular(2)", "return calcular(3)"))
        self.banco.sincronizar()
        pp.particionar(self.banco)
        lector2 = LectorFalso(self.banco, [self.respuesta()])
        f2 = fs.Fichas(self.banco, lector2)
        self.assertEqual([s["nombre"] for s in f2.pendientes(0)], ["usar"])

    def test_respuesta_rota_no_rompe(self):
        f = fs.Fichas(self.banco, LectorFalso(self.banco, ["no es json"]))
        r = f.fichar_unidad(0)
        self.assertEqual(r["fichas"], 0)
        self.assertEqual(r["sin_respuesta"], 2)


if __name__ == "__main__":
    unittest.main()
