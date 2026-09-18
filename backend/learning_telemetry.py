"""
Telemetría de aprendizaje: el instrumento que valida (o refuta) la tesis del producto.

Prig se posiciona como "el IDE que sabe qué NO sabes". Esa afirmación solo vale algo
si se puede demostrar con datos. El hexágono actual mide ACTIVIDAD (bloques marcados
a mano), no competencia: un alumno puede marcarlo todo sin aprender nada.

Aquí se registran hechos comprobables —el resultado real de ejecutar el código del
alumno— y de ellos se derivan las métricas que sí hablan de aprendizaje:

  · acierto al primer intento y sin pistas
  · tiempo hasta el primer test en verde
  · reincidencia: volver a fallar el mismo concepto en los 7 días siguientes

Todo es local: un SQLite dentro del workspace.
"""

import os
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


class LearningTelemetry:
    def __init__(self, workspace_dir: Optional[str] = None):
        base = os.path.abspath(workspace_dir or os.getcwd())
        self.data_dir = os.path.join(base, ".prig_dataset")
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "learning.db")
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS exercise_events (
                    event_id     TEXT PRIMARY KEY,
                    exercise_id  TEXT NOT NULL,
                    concept      TEXT NOT NULL,
                    event_type   TEXT NOT NULL,   -- generated | submission | solution_revealed
                    passed       INTEGER,
                    attempt_num  INTEGER DEFAULT 1,
                    hints_used   INTEGER DEFAULT 0,
                    error_kind   TEXT,
                    elapsed      REAL DEFAULT 0,
                    created_at   TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_concept ON exercise_events(concept);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_exercise ON exercise_events(exercise_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_created ON exercise_events(created_at);")
            conn.commit()

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    @staticmethod
    def classify_error(stderr: str) -> str:
        """ Taxonomía mínima de errores. El traceback ya se captura y se tiraba:
        clasificarlo es lo que convierte un fallo en un dato sobre el alumno. """
        if not stderr:
            return "none"
        table = [
            ("AssertionError", "logica_incorrecta"),
            ("SyntaxError", "sintaxis"),
            ("IndentationError", "indentacion"),
            ("NameError", "nombre_no_definido"),
            ("TypeError", "tipos"),
            ("ValueError", "valor_invalido"),
            ("IndexError", "indice_fuera_de_rango"),
            ("KeyError", "clave_inexistente"),
            ("AttributeError", "atributo_inexistente"),
            ("ZeroDivisionError", "division_por_cero"),
            ("RecursionError", "recursion_infinita"),
            ("Tiempo límite", "bucle_infinito"),
        ]
        for needle, kind in table:
            if needle in stderr:
                return kind
        return "otro"

    def record(self, exercise_id: str, concept: str, event_type: str,
               passed: Optional[bool] = None, attempt_num: int = 1,
               hints_used: int = 0, stderr: str = "", elapsed: float = 0.0,
               created_at: Optional[datetime] = None) -> str:
        """ created_at permite fechar el evento en el pasado (datos de siembra);
        en uso normal se omite y vale el momento actual. """
        event_id = f"ev_{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO exercise_events
                    (event_id, exercise_id, concept, event_type, passed,
                     attempt_num, hints_used, error_kind, elapsed, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                event_id, exercise_id, concept, event_type,
                None if passed is None else int(passed),
                attempt_num, hints_used,
                self.classify_error(stderr) if passed is False else "none",
                elapsed, (created_at or datetime.now()).isoformat(),
            ))
            conn.commit()
        return event_id

    def attempt_number(self, exercise_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM exercise_events WHERE exercise_id = ? AND event_type = 'submission';",
                (exercise_id,)
            ).fetchone()
        return (row["n"] or 0) + 1

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------

    def recientes(self, n: int = 10) -> List[Dict[str, Any]]:
        """ Los últimos ejercicios en los que se trabajó, uno por ejercicio (para Inicio) """
        try:
            with self._connect() as conn:
                filas = conn.execute("""
                    SELECT exercise_id, concept, MAX(created_at) AS ultima, COUNT(*) AS envios,
                           MAX(COALESCE(passed, 0)) AS resuelto
                    FROM exercise_events WHERE event_type = 'submission'
                    GROUP BY exercise_id ORDER BY ultima DESC LIMIT ?""", (int(n),)).fetchall()
        except sqlite3.Error:
            return []
        return [{"ejercicio": f[0], "concepto": f[1], "fecha": f[2], "envios": f[3], "resuelto": bool(f[4])} for f in filas]

    def metrics(self, days: int = 30) -> Dict[str, Any]:
        since = (datetime.now() - timedelta(days=days)).isoformat()

        with self._connect() as conn:
            subs = [dict(r) for r in conn.execute(
                "SELECT * FROM exercise_events WHERE event_type='submission' AND created_at >= ? "
                "ORDER BY created_at ASC;", (since,)
            ).fetchall()]

        if not subs:
            return {
                "window_days": days, "submissions": 0, "exercises_attempted": 0,
                "first_try_pass_rate": None, "solve_rate": None,
                "median_attempts_to_pass": None, "avg_seconds_to_green": None,
                "error_profile": {}, "weak_concepts": [], "repeat_error_rate": None,
                "note": "Sin datos todavía: resuelve algún ejercicio para empezar a medir.",
            }

        by_exercise: Dict[str, List[dict]] = {}
        for s in subs:
            by_exercise.setdefault(s["exercise_id"], []).append(s)

        first_try_ok = sum(1 for evs in by_exercise.values()
                           if evs[0]["passed"] == 1 and evs[0]["hints_used"] == 0)
        solved = sum(1 for evs in by_exercise.values() if any(e["passed"] == 1 for e in evs))

        attempts_to_pass = []
        seconds_to_green = []
        for evs in by_exercise.values():
            for i, e in enumerate(evs, 1):
                if e["passed"] == 1:
                    attempts_to_pass.append(i)
                    try:
                        delta = datetime.fromisoformat(e["created_at"]) - datetime.fromisoformat(evs[0]["created_at"])
                        seconds_to_green.append(delta.total_seconds())
                    except Exception:
                        pass
                    break

        error_profile: Dict[str, int] = {}
        concept_fails: Dict[str, int] = {}
        for s in subs:
            if s["passed"] == 0:
                error_profile[s["error_kind"]] = error_profile.get(s["error_kind"], 0) + 1
                concept_fails[s["concept"]] = concept_fails.get(s["concept"], 0) + 1

        # Reincidencia: conceptos fallados en más de un día distinto
        by_concept_days: Dict[str, set] = {}
        for s in subs:
            if s["passed"] == 0:
                by_concept_days.setdefault(s["concept"], set()).add(s["created_at"][:10])
        reincidentes = [c for c, dias in by_concept_days.items() if len(dias) > 1]

        median_attempts = None
        if attempts_to_pass:
            ordered = sorted(attempts_to_pass)
            median_attempts = ordered[len(ordered) // 2]

        total_ex = len(by_exercise)
        return {
            "window_days": days,
            "submissions": len(subs),
            "exercises_attempted": total_ex,
            "first_try_pass_rate": round(first_try_ok / total_ex * 100, 1),
            "solve_rate": round(solved / total_ex * 100, 1),
            "median_attempts_to_pass": median_attempts,
            "avg_seconds_to_green": round(sum(seconds_to_green) / len(seconds_to_green), 1) if seconds_to_green else None,
            "error_profile": dict(sorted(error_profile.items(), key=lambda x: -x[1])),
            "weak_concepts": [
                {"concept": c, "failures": n}
                for c, n in sorted(concept_fails.items(), key=lambda x: -x[1])[:8]
            ],
            "repeat_error_rate": round(len(reincidentes) / max(1, len(by_concept_days)) * 100, 1),
            "repeated_concepts": reincidentes[:8],
        }
