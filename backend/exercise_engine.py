"""
Generación y VERIFICACIÓN POR EJECUCIÓN de ejercicios.

Un ejercicio no es un enunciado: es una tupla
    enunciado + código de partida + solución de referencia + tests.

Y no se le muestra al alumno hasta que el sistema ha comprobado, ejecutándolo, que:
  1. la solución de referencia pasa sus propios tests, y
  2. el código de partida NO los pasa.

La segunda comprobación es la que descarta tests inútiles (del tipo `assert True`),
que un modelo pequeño produce con frecuencia. Sin este filtro, un ejercicio mal
generado llega al alumno y destruye su confianza en el sistema.
"""

import re
import uuid
from typing import Dict, Any, Optional

# Marcador que imprime el arnés de pruebas cuando todo ha ido bien.
OK_MARKER = "__PRIG_EXERCISE_OK__"

REQUIRED_FIELDS = ("statement", "function_name", "starter_code", "reference_solution", "tests")


class ExerciseValidationError(Exception):
    pass


class ExerciseEngine:
    def __init__(self, ai_engine, runner):
        self.ai = ai_engine
        self.runner = runner

    # ------------------------------------------------------------------
    # Generación
    # ------------------------------------------------------------------

    SYSTEM_PROMPT = """Eres un GENERADOR DE EJERCICIOS DE PROGRAMACIÓN en Python.

Devuelve ÚNICAMENTE un objeto JSON válido, sin markdown ni texto alrededor, con esta forma exacta:
{
  "title": "Título breve del ejercicio",
  "statement": "Enunciado claro de lo que debe implementar el alumno",
  "function_name": "nombre_de_la_funcion",
  "starter_code": "def nombre_de_la_funcion(parametros):\\n    pass",
  "reference_solution": "def nombre_de_la_funcion(parametros):\\n    return resultado",
  "tests": "assert nombre_de_la_funcion(1) == 2\\nassert nombre_de_la_funcion(0) == 0"
}

REGLAS OBLIGATORIAS:
1. starter_code y reference_solution definen EL MISMO símbolo, con la misma firma.
   Puede ser una función (`def nombre(...)`) o una clase (`class Nombre:`); en ese
   caso "function_name" contiene el nombre de la clase.
2. starter_code tiene el cuerpo sin implementar (`pass`), nunca la solución.
3. tests son sentencias `assert` que llaman a esa función. Mínimo 3.
4. Los tests deben FALLAR con el starter_code y PASAR con reference_solution.
5. Nada de `assert True`, `input()`, red, ficheros ni bibliotecas externas.
6. Usa \\n para los saltos de línea dentro de las cadenas JSON."""

    def generate(self, concept: str, model: str = "qwen2.5-coder:7b",
                 level: str = "intermedio") -> Dict[str, Any]:
        prompt = (
            f"Concepto a practicar: {concept}\n"
            f"Nivel del alumno: {level}\n"
            "Genera un ejercicio corto y autocontenido sobre ese concepto."
        )
        raw = "".join(self.ai.generate_response(
            prompt, model=model, system_prompt=self.SYSTEM_PROMPT,
            options={"temperature": 0.4}
        ))

        data = self.ai._extract_and_parse_json(raw)  # lanza si no hay JSON válido

        missing = [f for f in REQUIRED_FIELDS if not str(data.get(f, "")).strip()]
        if missing:
            raise ExerciseValidationError(f"Faltan campos en el JSON: {', '.join(missing)}")

        data["concept"] = concept
        data["exercise_id"] = f"ex_{uuid.uuid4().hex[:8]}"
        return data

    # ------------------------------------------------------------------
    # Verificación por ejecución
    # ------------------------------------------------------------------

    def _run_isolated(self, code: str, timeout: int = 15) -> Dict[str, Any]:
        """ Ejecuta en una sesión propia y desechable, para que un ejercicio no
        contamine al siguiente. """
        session = f"__eval_{uuid.uuid4().hex[:10]}__"
        try:
            return self.runner.run_cell_code(code, cwd=None, session_id=session, timeout=timeout)
        finally:
            self.runner.reset_session(session)

    @staticmethod
    def _harness(solution: str, tests: str) -> str:
        return f"{solution}\n\n{tests}\n\nprint({OK_MARKER!r})\n"

    def validate(self, exercise: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        """ Comprueba el ejercicio EJECUTÁNDOLO. Devuelve el veredicto y el motivo. """
        checks: Dict[str, Any] = {}

        # 1. El símbolo declarado debe existir en ambos códigos.
        #    Acepta clases además de funciones: exigir solo `def` descartaba por
        #    error todos los ejercicios de programación orientada a objetos, donde
        #    lo que se define es `class Pila:`.
        fn = exercise.get("function_name", "")
        pattern = re.compile(rf"(?:def|class)\s+{re.escape(fn)}\s*[\(:]")
        checks["function_in_solution"] = bool(pattern.search(exercise.get("reference_solution", "")))
        checks["function_in_starter"] = bool(pattern.search(exercise.get("starter_code", "")))

        # 2. La solución de referencia DEBE pasar sus propios tests
        ref = self._run_isolated(self._harness(exercise["reference_solution"], exercise["tests"]), timeout)
        checks["reference_passes"] = ref.get("success", False) and OK_MARKER in (ref.get("stdout") or "")
        checks["reference_stderr"] = (ref.get("stderr") or "").strip()[-400:]

        # 3. El código de partida NO debe pasarlos: si pasa, los tests no comprueban nada
        stub = self._run_isolated(self._harness(exercise["starter_code"], exercise["tests"]), timeout)
        stub_passed = stub.get("success", False) and OK_MARKER in (stub.get("stdout") or "")
        checks["tests_discriminate"] = not stub_passed

        # 4. Los tests deben invocar realmente a la función
        checks["tests_call_function"] = bool(fn) and fn in exercise.get("tests", "")

        valid = all([
            checks["function_in_solution"],
            checks["function_in_starter"],
            checks["reference_passes"],
            checks["tests_discriminate"],
            checks["tests_call_function"],
        ])

        reason = "OK"
        if not valid:
            if not checks["reference_passes"]:
                reason = "La solución de referencia no pasa sus propios tests"
            elif not checks["tests_discriminate"]:
                reason = "Los tests pasan también con el código sin implementar: no comprueban nada"
            elif not (checks["function_in_solution"] and checks["function_in_starter"]):
                reason = "La función declarada no aparece en el código de partida o en la solución"
            else:
                reason = "Los tests no invocan al símbolo declarado"

        return {"valid": valid, "reason": reason, "checks": checks}

    def grade_submission(self, exercise: Dict[str, Any], user_code: str,
                         timeout: int = 15) -> Dict[str, Any]:
        """ Corrige la entrega EJECUTÁNDOLA contra los tests ocultos.

        Sustituye al veredicto por opinión del modelo ("¿está bien este código?"),
        que un 7B contesta que sí con una frecuencia alarmante. Aquí el resultado es
        un hecho comprobable, no una opinión.
        """
        if not user_code.strip():
            return {"passed": False, "reason": "No enviaste código.", "stdout": "", "stderr": ""}

        result = self._run_isolated(self._harness(user_code, exercise["tests"]), timeout)
        stdout = result.get("stdout") or ""
        stderr = (result.get("stderr") or "").strip()
        passed = result.get("success", False) and OK_MARKER in stdout

        reason = "Todos los tests pasan."
        if not passed:
            if "AssertionError" in stderr:
                reason = "Tu solución no cumple uno de los casos de prueba."
            elif "SyntaxError" in stderr:
                reason = "El código tiene un error de sintaxis."
            elif "Tiempo límite" in stderr:
                reason = "La ejecución tardó demasiado: revisa si hay un bucle infinito."
            elif stderr:
                first = stderr.strip().splitlines()[-1]
                reason = f"La ejecución falló: {first}"
            else:
                reason = "La ejecución no completó los tests."

        return {
            "passed": passed,
            "reason": reason,
            # El marcador interno no debe llegar al alumno
            "stdout": stdout.replace(OK_MARKER + "\n", "").replace(OK_MARKER, ""),
            "stderr": stderr,
            "elapsed": result.get("elapsed", 0),
        }

    HINT_LEVELS = {
        1: ("Pista conceptual",
            "Da UNA pista CONCEPTUAL: qué idea o estructura de Python resuelve esto. "
            "NO escribas código ni nombres de funciones concretas. Máximo 2 frases."),
        2: ("Pista de estructura",
            "Describe los PASOS en pseudocódigo o en una lista breve, sin escribir Python real. "
            "El alumno debe seguir teniendo que traducirlo a código. Máximo 4 líneas."),
        3: ("Pista concreta",
            "Muestra SOLO la línea o expresión clave que le falta, con una frase de explicación. "
            "No entregues la función completa."),
    }

    def hint(self, exercise: Dict[str, Any], level: int = 1,
             model: str = "qwen2.5-coder:7b") -> Dict[str, Any]:
        """ Pistas graduadas en vez de la solución de golpe.

        Cada nivel se registra: un ejercicio resuelto sin pistas no vale lo mismo que
        uno resuelto con tres, y esa diferencia es la que mide competencia real.
        """
        level = max(1, min(int(level), 3))
        titulo, instruccion = self.HINT_LEVELS[level]

        sys_prompt = (
            "Eres un tutor que guía sin resolver. El alumno está atascado en un ejercicio.\n"
            f"{instruccion}\n"
            "Responde en español, directo, sin saludos. Nunca entregues la solución completa "
            "aunque la conozcas."
        )
        prompt = (
            f"Enunciado: {exercise.get('statement', '')}\n"
            f"Debe definir: {exercise.get('function_name', '')}\n"
            f"Código de partida:\n{exercise.get('starter_code', '')}\n\n"
            f"(Referencia interna, NO revelar:\n{exercise.get('reference_solution', '')})"
        )

        try:
            texto = "".join(self.ai.generate_response(
                prompt, model=model, system_prompt=sys_prompt, options={"temperature": 0.3}
            )).strip()
        except Exception as err:
            return {"level": level, "title": titulo, "text": f"No se pudo generar la pista: {err}"}

        return {"level": level, "title": titulo, "text": texto}

    @staticmethod
    def public_view(exercise: Dict[str, Any]) -> Dict[str, Any]:
        """ Lo que puede ver el alumno: nunca la solución ni los tests ocultos """
        return {
            "exercise_id": exercise["exercise_id"],
            "concept": exercise.get("concept", ""),
            "title": exercise.get("title", ""),
            "statement": exercise.get("statement", ""),
            "function_name": exercise.get("function_name", ""),
            "starter_code": exercise.get("starter_code", ""),
            "attempts_used": exercise.get("attempts_used", 1),
        }

    def generate_validated(self, concept: str, model: str = "qwen2.5-coder:7b",
                           level: str = "intermedio", attempts: int = 3) -> Dict[str, Any]:
        """ Genera hasta conseguir un ejercicio que supere la verificación.

        Es el único método que debería usar la interfaz: garantiza que al alumno solo
        le llegan ejercicios comprobados.
        """
        history = []
        for attempt in range(1, attempts + 1):
            try:
                exercise = self.generate(concept, model=model, level=level)
            except Exception as err:
                history.append({"attempt": attempt, "stage": "generation", "error": str(err)})
                continue

            verdict = self.validate(exercise)
            history.append({"attempt": attempt, "stage": "validation",
                            "valid": verdict["valid"], "reason": verdict["reason"]})
            if verdict["valid"]:
                exercise["validation"] = verdict
                exercise["attempts_used"] = attempt
                return {"ok": True, "exercise": exercise, "history": history}

        return {"ok": False, "exercise": None, "history": history,
                "error": f"No se obtuvo un ejercicio válido para '{concept}' en {attempts} intentos"}
