"""
Almacén persistente de ejercicios.

Antes vivían en un diccionario en memoria: si Prig se cerraba a media resolución,
el enunciado y sus tests ocultos desaparecían y el alumno no podía continuar.
También impedía medir el tiempo real hasta resolver, porque el ejercicio no
sobrevivía a una sesión.

Se guardan en el workspace, junto al resto de datos de aprendizaje. La solución y
los tests NO salen de aquí: el endpoint solo expone la vista pública.
"""

import os
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

MAX_EXERCISES = 500


class ExerciseStore:
    def __init__(self, workspace_dir: Optional[str] = None):
        base = os.path.abspath(workspace_dir or os.getcwd())
        self.data_dir = os.path.join(base, ".prig_dataset")
        os.makedirs(self.data_dir, exist_ok=True)
        self.path = os.path.join(self.data_dir, "exercises.json")
        self._lock = threading.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._cache = data
        except Exception as err:
            print(f"⚠️ No se pudieron leer los ejercicios guardados ({err}); se empieza vacío.")
            self._cache = {}

    def _flush(self):
        """ Escritura atómica: un corte a media escritura no debe dejar el archivo
        truncado y llevarse por delante todo el historial de ejercicios. """
        tmp = f"{self.path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as err:
            print(f"⚠️ No se pudieron guardar los ejercicios: {err}")
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def save(self, exercise: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            exercise.setdefault("created_at", datetime.now().isoformat())
            self._cache[exercise["exercise_id"]] = exercise

            if len(self._cache) > MAX_EXERCISES:
                ordenados = sorted(self._cache.items(), key=lambda kv: kv[1].get("created_at", ""))
                for key, _ in ordenados[: len(self._cache) - MAX_EXERCISES]:
                    self._cache.pop(key, None)

            self._flush()
        return exercise

    def get(self, exercise_id: str) -> Optional[Dict[str, Any]]:
        return self._cache.get(exercise_id)

    def delete(self, exercise_id: str) -> bool:
        with self._lock:
            existed = self._cache.pop(exercise_id, None) is not None
            if existed:
                self._flush()
        return existed

    def list_recent(self, limit: int = 20, concept: Optional[str] = None) -> List[Dict[str, Any]]:
        """ Vista pública de los ejercicios recientes, para poder retomarlos """
        items = list(self._cache.values())
        if concept:
            items = [e for e in items if e.get("concept") == concept]
        items.sort(key=lambda e: e.get("created_at", ""), reverse=True)
        return [
            {
                "exercise_id": e["exercise_id"],
                "concept": e.get("concept", ""),
                "title": e.get("title", ""),
                "created_at": e.get("created_at", ""),
            }
            for e in items[:limit]
        ]

    def count(self) -> int:
        return len(self._cache)
