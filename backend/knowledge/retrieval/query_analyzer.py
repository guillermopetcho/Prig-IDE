import re
from typing import Dict, Any, List
from enum import Enum

class QueryTypeEnum(str, Enum):
    CONCEPTUAL = "CONCEPTUAL"
    MATHEMATICAL = "MATHEMATICAL"
    CODE = "CODE"
    ALGORITHM = "ALGORITHM"
    DEFINITION = "DEFINITION"
    COMPARISON = "COMPARISON"
    PROCEDURAL = "PROCEDURAL"
    MULTI_HOP = "MULTI_HOP"

class QueryAnalyzer:
    """ Clasificador determinista de consultas del usuario para activar filtros específicos """

    @classmethod
    def analyze_query(cls, query: str) -> Dict[str, Any]:
        q_lower = query.lower()
        active_types: List[str] = []

        is_math = bool(re.search(r'(derivad|gradiente|ecuaci|fórmula|pérdida|loss|matemátic|matriz|tensor|integral|optimiza)', q_lower))
        is_code = bool(re.search(r'(código|implementa|pytorch|tensorflow|python|función|class|import|notebook|script)', q_lower))
        is_procedural = bool(re.search(r'(cómo|paso a paso|pasos|procedimiento|guía|instrucciones)', q_lower))
        is_comparison = bool(re.search(r'(diferencia|compar|difiere|versus|vs|frente a)', q_lower))
        is_definition = bool(re.search(r'(qué es|defina|concepto de|significado)', q_lower))

        if is_math:
            active_types.append(QueryTypeEnum.MATHEMATICAL.value)
        if is_code:
            active_types.append(QueryTypeEnum.CODE.value)
        if is_procedural:
            active_types.append(QueryTypeEnum.PROCEDURAL.value)
        if is_comparison:
            active_types.append(QueryTypeEnum.COMPARISON.value)
        if is_definition:
            active_types.append(QueryTypeEnum.DEFINITION.value)

        if len(active_types) > 1:
            active_types.append(QueryTypeEnum.MULTI_HOP.value)
        elif not active_types:
            active_types.append(QueryTypeEnum.CONCEPTUAL.value)

        primary_type = active_types[0]

        return {
            "query": query,
            "primary_type": primary_type,
            "active_types": active_types,
            "is_math_required": is_math,
            "is_code_required": is_code,
            "is_procedural_required": is_procedural
        }
