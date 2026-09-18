"""
Versionado y migración de los datos de usuario.

Los planes, seguimientos y el dataset de aprendizaje viven como JSON en disco y se
cargan con `Model.model_validate(...)`. Mientras solo se AÑADEN campos con valor por
defecto, Pydantic lo tolera por casualidad; en cuanto se renombra un campo o cambia
un tipo, los archivos antiguos dejan de validar y el historial del usuario se pierde
en silencio.

Aquí cada documento lleva `schema_version` y se migra al cargarlo. Añadir una
migración es añadir una función a la lista correspondiente.
"""

import os
import json
import shutil
from typing import Any, Callable, Dict, List, Tuple

# Versión actual de cada tipo de documento
CURRENT_VERSIONS: Dict[str, int] = {
    "study_plan": 2,
    "seguimiento": 3,
    "dataset": 2,
}

# Una migración transforma el documento de la versión N a la N+1
Migration = Callable[[Dict[str, Any]], Dict[str, Any]]


# ----------------------------------------------------------------------
# Migraciones de SEGUIMIENTO
# ----------------------------------------------------------------------

def _seguimiento_1_to_2(doc: Dict[str, Any]) -> Dict[str, Any]:
    """ v2 añade completion_dates para que el mapa de calor use fechas reales.

    Los seguimientos anteriores no guardaban cuándo se completó cada bloque; se
    siembra con la fecha de creación, que es la mejor aproximación disponible y
    evita amontonar todo el historial en el día de hoy.
    """
    doc.setdefault("completion_dates", {})
    created = doc.get("created_at")
    if created:
        for block_id in doc.get("completed_blocks", []):
            doc["completion_dates"].setdefault(block_id, created)
    return doc


# ----------------------------------------------------------------------
# Migraciones de PLAN DE ESTUDIO
# ----------------------------------------------------------------------

def _study_plan_1_to_2(doc: Dict[str, Any]) -> Dict[str, Any]:
    """ v2 normaliza las colecciones de progreso, que en v1 podían faltar. """
    doc.setdefault("completed_validation_criteria", {})
    doc.setdefault("completed_notebooks", [])
    doc.setdefault("decision_traces", [])
    doc.setdefault("revisions", [])
    return doc


# ----------------------------------------------------------------------
# Migraciones del DATASET DE APRENDIZAJE
# ----------------------------------------------------------------------

def _dataset_1_to_2(doc: Dict[str, Any]) -> Dict[str, Any]:
    """ v2 añade el mapa de calor y las competencias adquiridas. """
    doc.setdefault("activity_heatmap", {})
    doc.setdefault("acquired_competencies", [])
    doc.setdefault("mastered_topics", [])
    return doc


def _seguimiento_2_to_3(doc: Dict[str, Any]) -> Dict[str, Any]:
    """ v3 unifica Seguimiento y Recorrido en "Aprendizaje Guiado".

    Las rutas anteriores se marcan como generadas en modo rápido, que es lo que
    eran, y estrenan los campos donde ahora vive el análisis de los tres agentes.
    """
    doc.setdefault("source", "rapido")
    doc.setdefault("level", "Intermedio")
    doc.setdefault("focus", "Práctico")
    doc.setdefault("origin_plan_id", None)
    doc.setdefault("knowledge_map", None)
    doc.setdefault("decision_traces", [])
    doc.setdefault("notebooks", [])
    return doc


MIGRATIONS: Dict[str, List[Tuple[int, Migration]]] = {
    "seguimiento": [(1, _seguimiento_1_to_2), (2, _seguimiento_2_to_3)],
    "study_plan": [(1, _study_plan_1_to_2)],
    "dataset": [(1, _dataset_1_to_2)],
}


class MigrationError(Exception):
    pass


def detect_version(doc: Dict[str, Any], kind: str) -> int:
    """ Versión declarada; los documentos sin marca se consideran v1 """
    raw = doc.get("schema_version", 1)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def migrate(kind: str, doc: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """ Lleva el documento a la versión actual. Devuelve (documento, ¿cambió?). """
    if kind not in CURRENT_VERSIONS:
        raise MigrationError(f"Tipo de documento desconocido: {kind}")

    target = CURRENT_VERSIONS[kind]
    version = detect_version(doc, kind)

    if version > target:
        # Archivo escrito por una versión más nueva del programa: no se toca, pero
        # se avisa, porque degradarlo destruiría campos que aquí no se conocen.
        raise MigrationError(
            f"El documento usa el esquema v{version}, más nuevo que el soportado (v{target}). "
            "Actualiza Prig para abrirlo sin perder datos."
        )

    changed = False
    steps = {frm: fn for frm, fn in MIGRATIONS.get(kind, [])}

    while version < target:
        step = steps.get(version)
        if step is None:
            raise MigrationError(f"Falta la migración de {kind} v{version} a v{version + 1}")
        doc = step(doc)
        version += 1
        changed = True

    doc["schema_version"] = target
    return doc, changed


def load_migrated(path: str, kind: str, backup: bool = True) -> Dict[str, Any]:
    """ Lee un JSON de disco y lo devuelve migrado.

    Si migra, deja una copia `.v<N>.bak` junto al original: una migración con un
    fallo no debe ser la primera vez que el usuario pierde su historial.
    """
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    original_version = detect_version(doc, kind)
    doc, changed = migrate(kind, doc)

    if changed and backup:
        bak = f"{path}.v{original_version}.bak"
        if not os.path.exists(bak):
            try:
                shutil.copy2(path, bak)
            except OSError as err:
                print(f"⚠️ No se pudo respaldar {path}: {err}")

    return doc


def stamp(doc: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """ Marca un documento con la versión actual antes de guardarlo """
    doc["schema_version"] = CURRENT_VERSIONS[kind]
    return doc
