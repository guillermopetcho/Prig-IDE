"""
Pruebas exhaustivas para el Motor Director LLM, Analizador AST y Memoria Comprimida Semántica.
"""

import os
import sys
import unittest
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_director import AnalizadorSintacticoAST, MemoriaArchivosDirector, LLMDirectorAgentes, director_llm


class TestLLMDirector(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_test_director_")
        self.mem_dir = os.path.join(self.tmp, ".prig_dataset")
        os.makedirs(self.mem_dir, exist_ok=True)
        self.mem_file = os.path.join(self.mem_dir, "cerebro_memoria_comprimida.json")
        self.memoria = MemoriaArchivosDirector(self.mem_file)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_analizador_ast_python_completo(self):
        codigo_py = '''
import math
from typing import List, Optional

class ProcesadorDatos:
    def __init__(self, limite: int = 100):
        self.limite = limite

    async def transformar(self, elementos: List[int]) -> List[float]:
        if not elementos:
            return []
        resultado = []
        for e in elementos:
            try:
                resultado.append(math.sqrt(e))
            except Exception as err:
                resultado.append(0.0)
        return resultado
'''
        res = AnalizadorSintacticoAST.analizar_codigo("procesador.py", codigo_py, "python")
        self.assertIsInstance(res, dict)
        self.assertIn("simbolos", res)
        self.assertIn("pasos_cfg", res)
        self.assertIn("dependencias", res)
        
        simbolos_nombres = [s["nombre"] for s in res["simbolos"]]
        self.assertIn("ProcesadorDatos", simbolos_nombres)
        self.assertIn("transformar", simbolos_nombres)
        
        # Verificar dependencias
        self.assertTrue(any("math" in d for d in res["dependencias"]))
        self.assertTrue(any("typing" in d for d in res["dependencias"]))

        # Verificar pasos CFG generados
        self.assertGreater(len(res["pasos_cfg"]), 0)

    def test_analizador_ast_codigo_con_error_sintaxis(self):
        # Código con sintaxis intencionalmente rota (en proceso de edición por el usuario)
        codigo_roto = '''
def funcion_incompleta(x, y
    if x > 0:
        return True
'''
        res = AnalizadorSintacticoAST.analizar_codigo("edicion.py", codigo_roto, "python")
        self.assertIsInstance(res, dict)
        self.assertIn("simbolos", res)
        self.assertGreaterEqual(res["complejidad_max"], 1)

    def test_analizador_ast_javascript_y_typescript(self):
        codigo_js = '''
import { useState, useEffect } from 'react';
import axios from 'axios';

export class ServicioAPI extends BaseService {
    constructor() {
        super();
    }
}

const procesarRespuesta = async (datos) => {
    for (let d of datos) {
        if (!d) continue;
    }
    return datos.map(x => x.id);
};
'''
        res = AnalizadorSintacticoAST.analizar_codigo("app.ts", codigo_js, "typescript")
        self.assertIsInstance(res, dict)
        simbolos = [s["nombre"] for s in res["simbolos"]]
        self.assertIn("ServicioAPI", simbolos)
        self.assertIn("procesarRespuesta", simbolos)
        self.assertTrue(len(res["dependencias"]) > 0)

    def test_memoria_comprimida_registro_y_persistencia(self):
        codigo = '''
import math
from typing import List

class CalculadoraVentas:
    def __init__(self, factor: float = 1.21):
        self.factor = factor

    def calcular_total(self, precios: List[float]) -> float:
        if not precios:
            return 0.0
        subtotal = sum(precios)
        return subtotal * self.factor

    def calcular_descuento(self, total: float, porcentaje: float) -> float:
        return total * (1.0 - porcentaje / 100.0)
'''
        self.memoria.registrar_lectura_archivo("ventas.py", codigo, "python")
        
        resumen = self.memoria.obtener_resumen_memoria()
        self.assertEqual(len(resumen), 1)
        self.assertEqual(resumen[0]["archivo"], "ventas.py")
        
        stats = self.memoria.obtener_estadisticas_tokens()
        self.assertEqual(stats["total_archivos_memorizados"], 1)
        self.assertGreaterEqual(stats["ahorro_global_porcentaje"], 0.0)

        # Cargar de nuevo la memoria desde el archivo guardado en disco
        memoria_recargada = MemoriaArchivosDirector(self.mem_file)
        self.assertIn("ventas.py", memoria_recargada.archivos_memorizados)

    def test_director_rotacion_lentes(self):
        director = LLMDirectorAgentes()
        lentes = [director._obtener_siguiente_lente()["id"] for _ in range(6)]
        self.assertEqual(len(set(lentes)), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)

