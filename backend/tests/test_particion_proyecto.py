"""
Partición del proyecto en unidades de lectura (particion_proyecto.py): piezas por símbolos, tope de
tokens, agrupamiento por llamadas y orden de lectura (dependencias primero, lo estable primero).
"""

import os
import shutil
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import banco_proyecto as bp
import particion_proyecto as pp


def funcion(nombre, llama=None, lineas=30):
    cuerpo = "\n".join(f"    x{i} = {i}  # relleno para que ocupe tokens de verdad" for i in range(lineas))
    llamada = f"\n    return {llama}()" if llama else "\n    return 0"
    return f"def {nombre}():\n{cuerpo}{llamada}\n\n\n"


class TestParticion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_particion_")
        self.raiz = os.path.join(self.tmp, "p")
        archivos = {
            # base.py no usa a nadie; servicio.py usa base; api.py usa servicio: se leen en ese orden
            "nucleo/base.py": funcion("util_base") + funcion("otra_base"),
            "nucleo/servicio.py": "from nucleo.base import util_base\n\n" + funcion("servir", "util_base"),
            "web/api.py": "from nucleo.servicio import servir\n\n" + funcion("endpoint", "servir"),
            # un archivo grande que no cabe en una unidad
            "grande.py": "".join(funcion(f"f{i}", f"f{i + 1}" if i < 11 else None, 60) for i in range(12)),
            "tests/test_base.py": "def test_x():\n    assert True\n",
        }
        for rel, texto in archivos.items():
            ruta = os.path.join(self.raiz, rel)
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "w") as f:
                f.write(texto)
        self.banco = bp.BancoProyecto(self.raiz, carpeta=os.path.join(self.tmp, "banco"))
        self.banco.sincronizar()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tope_y_cobertura(self):
        r = pp.particionar(self.banco, tope=1500)
        todas = {(p["ruta"], p["ini"]) for u in r["unidades"] for p in u["piezas"]}
        self.assertTrue(all(u["tokens"] <= 1500 for u in r["unidades"]), [u["tokens"] for u in r["unidades"]])
        rutas = {p["ruta"] for u in r["unidades"] for p in u["piezas"]}
        self.assertEqual(rutas, {"nucleo/base.py", "nucleo/servicio.py", "web/api.py", "grande.py"})  # sin tests
        self.assertGreater(r["resumen"]["archivos_partidos"], 0)                   # grande.py se partió
        # grande.py se cortó por funciones, no por la mitad de una
        with self.banco.conectar() as c:
            inicios = {f["ini"] for f in c.execute("SELECT ini FROM simbolos WHERE ruta = 'grande.py'")}
        cortes = sorted(ini for ruta, ini in todas if ruta == "grande.py")
        # cada corte empieza en una función o en las líneas en blanco justo antes
        self.assertTrue(all(ini == 1 or any(ini + k in inicios for k in range(4)) for ini in cortes), cortes)

    def test_dependencias_se_leen_primero(self):
        r = pp.particionar(self.banco, tope=400)
        posicion = {}
        for u in r["unidades"]:
            for p in u["piezas"]:
                posicion.setdefault(p["ruta"], u["orden"])
        self.assertLessEqual(posicion["nucleo/base.py"], posicion["nucleo/servicio.py"])
        self.assertLessEqual(posicion["nucleo/servicio.py"], posicion["web/api.py"])

    def test_lo_que_se_llama_queda_junto(self):
        r = pp.particionar(self.banco, tope=100000)             # todo cabe: una sola unidad
        self.assertEqual(len(r["unidades"]), 1)
        self.assertEqual(r["resumen"]["peso_cortado"], 0.0)

    def test_se_guarda_en_el_banco(self):
        pp.particionar(self.banco, tope=1500)
        unidades = self.banco.unidades()
        self.assertTrue(unidades)
        self.assertEqual([u["orden"] for u in unidades], list(range(len(unidades))))
        self.assertIn("unidades", self.banco.particion())
        self.assertTrue(all(isinstance(u["piezas"], list) and u["nombre"] for u in unidades))

    def test_componentes_fuertes(self):
        comps = pp.componentes_fuertes(4, {0: {1}, 1: {0}, 2: {3}})
        self.assertIn(sorted([0, 1]), [sorted(c) for c in comps])
        self.assertEqual(len(comps), 3)


if __name__ == "__main__":
    unittest.main()
