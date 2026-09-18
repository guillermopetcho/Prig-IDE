"""
Los prompts de los agentes y sus modelos Pydantic deben describir lo MISMO.

Dos fallos reales en producción nacieron de aquí: el prompt pedía evidencias con
`locator`/`quote` cuando el modelo exigía `title`, y pedía `action: "CREATE"` cuando
el enum solo admite CREATED_FROM_SCRATCH. En ambos casos el backend no fallaba al
arrancar: reventaba minutos después, tras una generación completa.

Estos tests extraen el JSON de ejemplo de cada prompt y lo validan contra el modelo.
Si alguien cambia uno sin el otro, se ve aquí y no en la cara del usuario.
"""
import os
import re
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_engine.ai_engine_class import AIEngine  # noqa: E402
from study_plan_engine import (  # noqa: E402
    KnowledgeMap, PracticalCurriculum, ExecutableLearningPlan, ChangeRequest,
)


ANCLA = "con esta forma"


def extraer_json(texto: str) -> dict:
    """ El objeto JSON de ejemplo que sigue a "con esta forma:" en el prompt """
    pos = texto.find(ANCLA)
    inicio = texto.index("{", pos if pos >= 0 else 0)
    profundidad, fin = 0, inicio
    for i in range(inicio, len(texto)):
        if texto[i] == "{":
            profundidad += 1
        elif texto[i] == "}":
            profundidad -= 1
            if profundidad == 0:
                fin = i + 1
                break
    bruto = texto[inicio:fin]
    # Los ejemplos usan "a | b" para enumerar opciones; se queda la primera
    bruto = re.sub(r'"([A-Za-z_]+)\s*\|[^"]*"', r'"\1"', bruto)
    return json.loads(bruto)


class TestContratosDeAgentes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = AIEngine()

    def _comprobar(self, prompt: str, modelo, nombre: str):
        try:
            ejemplo = extraer_json(prompt)
        except Exception as err:
            self.fail(f"El prompt de {nombre} no contiene un JSON de ejemplo parseable: {err}")
        try:
            modelo.model_validate(ejemplo)
        except Exception as err:
            self.fail(
                f"El ejemplo del prompt de {nombre} NO valida contra {modelo.__name__}.\n"
                f"Prompt y modelo se han desincronizado:\n{err}"
            )

    def test_agente1_knowledge_architect(self):
        prompt = self.ai.run_knowledge_architect.__doc__ or ""
        # El prompt vive dentro del método; se recupera del código fuente
        import inspect
        fuente = inspect.getsource(self.ai.run_knowledge_architect)
        self._comprobar(fuente, KnowledgeMap, "Agente 1")

    def test_agente2_practice_architect(self):
        import inspect
        fuente = inspect.getsource(self.ai.run_practice_architect)
        self._comprobar(fuente, PracticalCurriculum, "Agente 2")

    def test_agente3_notebook_manager(self):
        import inspect
        fuente = inspect.getsource(self.ai.run_notebook_manager)
        self._comprobar(fuente, ExecutableLearningPlan, "Agente 3")


class TestToleranciaAOmisiones(unittest.TestCase):
    """ Un modelo pequeño omite campos; eso no puede tirar un trabajo de minutos """

    def test_evidencia_sin_titulo(self):
        km = KnowledgeMap.model_validate({"goal": "g", "domains": [{"domain_id": "d", "name": "D", "topics": [
            {"topic_id": "t", "name": "T", "concepts": [
                {"concept_id": "c", "name": "C", "evidence": [{"source_id": "libro.md", "quote": "cita"}]}]}]}]})
        ev = km.domains[0].topics[0].concepts[0].evidence[0]
        self.assertTrue(ev.title, "el título debe rellenarse, no invalidar el mapa")

    def test_mapa_sin_ids(self):
        km = KnowledgeMap.model_validate({"domains": [{"name": "Solo nombre", "topics": [
            {"name": "Tema", "concepts": [{"name": "Concepto"}]}]}]})
        self.assertTrue(km.domains[0].domain_id)
        self.assertTrue(km.domains[0].topics[0].concepts[0].concept_id)

    def test_conceptos_como_texto_plano(self):
        km = KnowledgeMap.model_validate({"domains": [{"name": "D", "topics": [
            {"name": "T", "concepts": ["Vectores", "Matrices"]}]}]})
        self.assertEqual([c.name for c in km.domains[0].topics[0].concepts], ["Vectores", "Matrices"])

    def test_prerequisito_como_cadena(self):
        km = KnowledgeMap.model_validate({"goal": "g", "prerequisites": ["Saber sumar"]})
        self.assertEqual(km.prerequisites[0].name, "Saber sumar")
        self.assertTrue(km.prerequisites[0].reason)

    def test_relacion_sin_origen_se_descarta(self):
        km = KnowledgeMap.model_validate({"goal": "g", "relationships": [{"target_concept_id": "c1"}]})
        self.assertEqual(len(km.relationships), 0)

    def test_curriculo_sin_id(self):
        curr = PracticalCurriculum.model_validate({"modules": [{"name": "Vectores"}]})
        self.assertTrue(curr.curriculum_id)
        self.assertTrue(curr.modules[0].module_id)
        self.assertTrue(curr.modules[0].objective)

    def test_accion_de_cuaderno_en_cualquier_forma(self):
        for escrito in ("CREATE", "create", "new", "COPY", "reuse", "inventada"):
            plan = ExecutableLearningPlan.model_validate({"modules_notebooks": [
                {"module_id": "m1", "module_name": "M", "notebooks": [
                    {"notebook_id": "n1", "title": "T", "action": escrito}]}]})
            self.assertIn(plan.modules_notebooks[0].notebooks[0].action.value,
                          ("CREATED_FROM_SCRATCH", "COPIED_AND_EXPLAINED"),
                          f"'{escrito}' debería mapearse a una acción válida")

    def test_bloque_con_temas_en_una_cadena(self):
        from study_plan_engine import SeguimientoBlock
        b = SeguimientoBlock.model_validate({"title": "T", "description": "d", "topics": "a, b, c"})
        self.assertEqual(b.topics, ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
