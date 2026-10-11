"""
Partición del proyecto en unidades de lectura (etapa 1 de docs/arquitectura-unificada.md).

El motor MoE rinde a ≤32K de contexto (24 expertos calientes, ~40 tok/s). Un proyecto grande se lee
entonces por unidades de ≤16K tokens de código, más la tarjeta global y el contexto de la unidad. La
calidad de todo lo que viene después depende de cómo se corta y en qué orden se lee:

  · Piezas: cada archivo de producción es una pieza; los que no caben se cortan por símbolos de
    primer nivel (y una clase gigante, por métodos), nunca por líneas a ciegas.
  · Unidades: las piezas se agrupan por cuánto se llaman entre sí (grafo de llamadas resuelto e
    imports), con un tope de tokens. Agrupamiento aglomerativo con capacidad: sin dependencias.
  · Orden: primero lo que otros usan (dependencias antes que quien las usa), y a igualdad lo estable
    (menos commits en git) antes que lo que se edita seguido. La memoria del SSM olvida con la
    distancia y un cambio invalida todo lo que se lee después: así se protege lo que más importa.

Sin modelo: se recalcula en décimas de segundo. Se guarda en el banco (tabla `unidades`). La calcula el motor del
banco (Rust, banco_motor.py); el código de Python que la calculaba quedó en ~/prig-memoria/referencia.
"""

from typing import Any, Dict, List, Set

from banco_motor import rust as _rust

PRESUPUESTO_UNIDAD = 16000          # tokens de código por unidad
LENGUAJES_CODIGO = ("python", "js", "c", "go", "rust", "java")


def es_produccion(ruta: str, lenguaje: str) -> bool:
    return lenguaje in LENGUAJES_CODIGO and not _rust().es_test(ruta)


def componentes_fuertes(n: int, aristas: Dict[int, Set[int]]) -> List[List[int]]:
    """ Tarjan iterativo: grupos de unidades que se llaman en ciclo """
    return _rust().componentes_fuertes(n, aristas)


def particionar(banco, tope: int = PRESUPUESTO_UNIDAD, guardar: bool = True) -> Dict[str, Any]:
    """ {"resumen": {...}, "unidades": [...]}; con `guardar`, la deja en el banco """
    return banco._rs.particionar(tope, guardar)
