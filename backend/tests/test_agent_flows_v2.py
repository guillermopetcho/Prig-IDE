import os
import sys
import unittest
import time
from typing import Dict, Any, Generator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_flows_v2
from agent_flows_v2 import (
    AgentState,
    DynamicFlowEngine,
    ejecutar_sandbox_python,
    extraer_json_seguro,
    plantillas_profesionales_sota,
)


class MockAIEngine:
    """ Motor de IA simulado para pruebas deterministas sin depender de Ollama """
    def __init__(self, respuestas: Dict[str, str] = None):
        self.respuestas = respuestas or {}
        self.llamadas = []

    def generate_response(self, prompt: str, **kwargs) -> Generator[str, None, None]:
        self.llamadas.append({"prompt": prompt, "kwargs": kwargs})
        # Buscar respuesta simulada basada en palabras clave
        for kw, resp in self.respuestas.items():
            if kw in prompt:
                # Simular streaming de trozos
                for word in resp.split(" "):
                    yield word + " "
                return
        yield "Respuesta genérica del modelo simulado."


class TestAgentFlowsV2(unittest.TestCase):

    def test_agent_state_variables(self):
        state = AgentState(entrada_inicial="Calcular Fibonacci en Python")
        self.assertEqual(state.entrada_inicial, "Calcular Fibonacci en Python")
        self.assertEqual(state.get_var("entrada"), "Calcular Fibonacci en Python")

        state.registrar_salida("coder", "def fib(n): return n if n <= 1 else fib(n-1)+fib(n-2)")
        self.assertEqual(state.get_var("anterior"), "def fib(n): return n if n <= 1 else fib(n-1)+fib(n-2)")
        self.assertIn("coder", state.salidas_nodos)
        self.assertEqual(state.iteraciones_nodos["coder"], 1)

    def test_sandbox_python_exito(self):
        codigo = """
```python
def suma(a, b):
    return a + b

res = suma(10, 20)
print(f"Resultado: {res}")
```
"""
        res = ejecutar_sandbox_python(codigo, timeout=5)
        self.assertTrue(res["exito"])
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("Resultado: 30", res["stdout"])
        self.assertEqual(res["stderr"], "")

    def test_sandbox_python_error_traceback(self):
        codigo = "x = 10 / 0"
        res = ejecutar_sandbox_python(codigo, timeout=5)
        self.assertFalse(res["exito"])
        self.assertNotEqual(res["exit_code"], 0)
        self.assertIn("ZeroDivisionError", res["stderr"])

    def test_sandbox_python_timeout(self):
        codigo = "import time\ntime.sleep(2)"
        res = ejecutar_sandbox_python(codigo, timeout=1)
        self.assertFalse(res["exito"])
        self.assertIn("Timeout", res["stderr"])

    def test_extraer_json_seguro(self):
        # Con markdown alrededor y bloque <think>
        texto = "<think>Analizando el código...</think>\n```json\n{\"aprobado\": true, \"score\": 0.95}\n```"
        datos = extraer_json_seguro(texto)
        self.assertIsInstance(datos, dict)
        self.assertTrue(datos.get("aprobado"))
        self.assertEqual(datos.get("score"), 0.95)

        # JSON plano embebido en texto
        texto2 = "Aquí está el resultado: {\"decision\": \"specialist_dl\", \"razon\": \"Es PyTorch\"} espero que sirva."
        datos2 = extraer_json_seguro(texto2)
        self.assertEqual(datos2.get("decision"), "specialist_dl")

    def test_flujo_secuencial_basico(self):
        ai = MockAIEngine({
            "paso_1": "Salida del paso 1",
            "paso_2": "Salida final paso 2"
        })
        motor = DynamicFlowEngine(ai)
        grafo = {
            "nombre": "Flujo Lineal",
            "nodos": [
                {"id": "n1", "nombre": "Paso 1", "prompt": "Generar paso_1"},
                {"id": "n2", "nombre": "Paso 2", "prompt": "Generar paso_2 a partir de {anterior}"}
            ]
        }
        eventos = list(motor.ejecutar_grafo(grafo, "Entrada"))
        tipos = [e["tipo"] for e in eventos]
        self.assertIn("grafo_inicio", tipos)
        self.assertIn("nodo_inicio", tipos)
        self.assertIn("nodo_fin", tipos)
        self.assertIn("grafo_fin", tipos)

        fin = next(e for e in eventos if e["tipo"] == "grafo_fin")
        self.assertIn("Salida final paso 2", fin["resultado_final"])

    def test_bucle_recursivo_con_feedback(self):
        # Simular que el crítico rechaza la vuelta 1 y aprueba la vuelta 2
        respuestas = {
            "Genera código": "def foo(): pass",
            "Evalúa": '{"aprobado": false, "score": 0.5, "motivo": "Falta implementar foo"}',
        }
        ai = MockAIEngine(respuestas)
        motor = DynamicFlowEngine(ai)

        grafo = {
            "nombre": "Flujo Recursivo",
            "nodo_inicial": "generador",
            "nodos": [
                {
                    "id": "generador",
                    "nombre": "Generador",
                    "prompt": "Genera código para {entrada}. {critica}",
                    "next_node": "critico"
                },
                {
                    "id": "critico",
                    "nombre": "Crítico",
                    "rol": "critico",
                    "prompt": "Evalúa el trabajo:\n{anterior}",
                    "loop": {
                        "target": "generador",
                        "max_iterations": 3
                    },
                    "next_node": "final"
                },
                {
                    "id": "final",
                    "nombre": "Final",
                    "prompt": "Resumen: {paso:generador}"
                }
            ]
        }

        # Ejecutamos el flujo
        eventos = list(motor.ejecutar_grafo(grafo, "Problema"))
        vueltas = [e for e in eventos if e["tipo"] == "vuelta_recursiva"]
        self.assertGreaterEqual(len(vueltas), 1)
        self.assertEqual(vueltas[0]["desde"], "critico")
        self.assertEqual(vueltas[0]["hacia"], "generador")

    def test_enrutamiento_dinamico_supervisor(self):
        respuestas = {
            "Clasifica": '{"decision": "nodo_b", "razon": "Requiere nodo B"}',
            "Soy Nodo B": "Ejecución exitosa de la rama B"
        }
        ai = MockAIEngine(respuestas)
        motor = DynamicFlowEngine(ai)

        grafo = {
            "nombre": "Flujo con Router",
            "nodo_inicial": "router",
            "nodos": [
                {
                    "id": "router",
                    "tipo": "router",
                    "prompt": "Clasifica la solicitud: {entrada}"
                },
                {
                    "id": "nodo_a",
                    "prompt": "Soy Nodo A"
                },
                {
                    "id": "nodo_b",
                    "prompt": "Soy Nodo B"
                }
            ]
        }

        eventos = list(motor.ejecutar_grafo(grafo, "Tarea para B"))
        rutas = [e for e in eventos if e["tipo"] == "enrutamiento_dinamico"]
        self.assertEqual(len(rutas), 1)
        self.assertEqual(rutas[0]["destino"], "nodo_b")

    def test_nodo_sandbox_tool(self):
        ai = MockAIEngine({
            "Genera script": "```python\nprint(2 + 2)\n```"
        })
        motor = DynamicFlowEngine(ai)

        grafo = {
            "nombre": "Flujo con Sandbox Tool",
            "nodos": [
                {
                    "id": "programador",
                    "prompt": "Genera script",
                    "next_node": "sandbox"
                },
                {
                    "id": "sandbox",
                    "tipo": "tool",
                    "herramienta": "python_sandbox",
                    "next_node": "informe"
                },
                {
                    "id": "informe",
                    "prompt": "Explica la salida: {anterior}"
                }
            ]
        }

        eventos = list(motor.ejecutar_grafo(grafo, "Sumar dos y dos"))
        tool_eventos = [e for e in eventos if e["tipo"] == "tool_fin"]
        self.assertEqual(len(tool_eventos), 1)
        self.assertTrue(tool_eventos[0]["exito"])
        self.assertIn("4", tool_eventos[0]["salida"])

    def test_plantillas_profesionales_sota(self):
        plantillas = plantillas_profesionales_sota("qwen2.5-coder:7b", "qwen3:8b")
        self.assertGreaterEqual(len(plantillas), 4)

        for p in plantillas:
            self.assertIn("id", p)
            self.assertIn("nombre", p)
            self.assertIn("nodos", p)
            self.assertIn("nodo_inicial", p)
            ids = [n["id"] for n in p["nodos"]]
            self.assertIn(p["nodo_inicial"], ids)


if __name__ == "__main__":
    unittest.main()
