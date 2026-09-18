"""
Banderas de funcionalidad.

Con un solo desarrollador y un proyecto de esta superficie, la alternativa son ramas
eternas: una función a medias o se termina o bloquea el resto. Con banderas se puede
integrar trabajo incompleto sin que aparezca en el flujo principal.

Prioridad: variable de entorno > archivo (~/.prig_flags.json) > valor por defecto.
La variable de entorno permite probar algo puntualmente sin tocar la configuración
guardada:  PRIG_FLAG_EXERCISES_UI=1 ./run.sh
"""

import os
import json
from typing import Dict, Any

FLAGS_PATH = os.path.expanduser("~/.prig_flags.json")

# Toda bandera nueva se declara aquí con su valor por defecto y para qué sirve.
DEFAULT_FLAGS: Dict[str, Dict[str, Any]] = {
    "knowledge_chat": {
        "default": True,
        "description": "Respuestas del tutor fundamentadas en la biblioteca, con citas",
    },
    "library_indexing": {
        "default": True,
        "description": "Indexar la biblioteca para que el tutor pueda consultarla",
    },
    "query_expansion": {
        "default": True,
        "description": "Reformular la consulta con el modelo antes de buscar (compensa el índice léxico)",
    },
    "exercises_api": {
        "default": True,
        "description": "Generar y corregir ejercicios verificados por ejecución",
    },
    "exercises_ui": {
        "default": False,
        "description": "Pantalla del alumno para resolver ejercicios (aún sin construir)",
    },
    "kaggle_window": {
        "default": False,
        "description": "Ventana nativa de Kaggle con lectura de página (suspendida)",
    },
    "learning_telemetry": {
        "default": True,
        "description": "Registrar intentos de ejercicios para medir el aprendizaje",
    },
}


class FeatureFlags:
    def __init__(self, path: str = FLAGS_PATH):
        self.path = path
        self._overrides: Dict[str, bool] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._overrides = {k: bool(v) for k, v in saved.items() if k in DEFAULT_FLAGS}
        except Exception as err:
            print(f"⚠️ No se pudieron leer las banderas ({err}); se usan los valores por defecto.")
            self._overrides = {}

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._overrides, f, indent=2, ensure_ascii=False)
        except Exception as err:
            print(f"⚠️ No se pudieron guardar las banderas: {err}")

    @staticmethod
    def _from_env(name: str):
        raw = os.environ.get(f"PRIG_FLAG_{name.upper()}")
        if raw is None:
            return None
        return raw.strip().lower() in ("1", "true", "yes", "on", "si", "sí")

    def is_enabled(self, name: str) -> bool:
        if name not in DEFAULT_FLAGS:
            return False
        env = self._from_env(name)
        if env is not None:
            return env
        return self._overrides.get(name, DEFAULT_FLAGS[name]["default"])

    def set(self, name: str, value: bool) -> bool:
        if name not in DEFAULT_FLAGS:
            raise KeyError(f"Bandera desconocida: {name}")
        self._overrides[name] = bool(value)
        self._save()
        return self.is_enabled(name)

    def reset(self, name: str) -> bool:
        self._overrides.pop(name, None)
        self._save()
        return self.is_enabled(name)

    def all(self) -> Dict[str, Any]:
        return {
            name: {
                "enabled": self.is_enabled(name),
                "default": meta["default"],
                "description": meta["description"],
                "source": (
                    "entorno" if self._from_env(name) is not None
                    else "configuración" if name in self._overrides
                    else "por defecto"
                ),
            }
            for name, meta in DEFAULT_FLAGS.items()
        }
