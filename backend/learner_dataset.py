import os
import re
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import schema_migrations
from study_plan_engine import StudyPlanRepository, SeguimientoRepository

# Palabras clave para la clasificación en el Hexágono de Competencias
HEXAGON_KEYWORDS = {
    "matematicas": [
        "math", "matematica", "matemática", "algebra", "cálculo", "calculo",
        "estadistica", "estadística", "probabilidad", "logica", "lógica",
        "vector", "matriz", "matrices", "geometria", "optimizacion", "optimizó", "derivad"
    ],
    "programacion": [
        "programacion", "programación", "python", "javascript", "js", "cpp", "c++",
        "poo", "oop", "funcion", "función", "variable", "clase", "algoritmo",
        "codigo", "código", "sintaxis", "script", "git", "refactor", "bucle", "loop"
    ],
    "machine_learning": [
        "machine_learning", "machine learning", "ml", "regresion", "regresión",
        "clasificacion", "clasificación", "scikit-learn", "sklearn", "clustering",
        "random forest", "svm", "supervisado", "no supervisado", "arbol", "decision", "fit", "predict"
    ],
    "deep_learning": [
        "deep_learning", "deep learning", "dl", "redes neuronales", "red neuronal",
        "pytorch", "tensorflow", "keras", "cnn", "rnn", "transformer", "llm",
        "atencion", "atención", "backpropagation", "capa", "neurona", "loss", "optimizer"
    ],
    "base_de_datos": [
        "base_de_datos", "base de datos", "sql", "database", "pandas", "dataframe",
        "numpy", "etl", "postgres", "sqlite", "nosql", "consulta", "query", "tabla", "dataset"
    ],
    "teoria_computacional": [
        "teoria", "teoría", "computacion", "computación", "complejidad", "big o",
        "arquitectura", "sistema operativo", "redes", "patron", "patrón", "compilador",
        "memoria", "hilo", "concurrencia", "estructura de datos", "arbol", "grafo"
    ]
}


class HexagonCompetency(BaseModel):
    category_id: str
    label: str
    score: int = 0
    level: int = 1
    max_scale: int = 100
    completed_items_count: int = 0


class UserProfileMetrics(BaseModel):
    total_recorridos: int = 0
    total_seguimientos: int = 0
    completed_recorridos: int = 0
    completed_seguimientos: int = 0
    total_blocks_completed: int = 0
    total_topics_mastered: int = 0
    overall_progress_pct: float = 0.0
    last_activity: str = Field(default_factory=lambda: datetime.now().isoformat())


class UserLearningDataset(BaseModel):
    schema_version: int = Field(default_factory=lambda: schema_migrations.CURRENT_VERSIONS["dataset"])
    version: str = "2.0"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    metrics: UserProfileMetrics = Field(default_factory=UserProfileMetrics)
    hexagon: Dict[str, HexagonCompetency] = Field(default_factory=dict)
    activity_heatmap: Dict[str, int] = Field(default_factory=dict)  # "YYYY-MM-DD": count
    mastered_topics: List[Dict[str, Any]] = Field(default_factory=list)
    acquired_competencies: List[Dict[str, Any]] = Field(default_factory=list)
    recorridos: List[Dict[str, Any]] = Field(default_factory=list)
    seguimientos: List[Dict[str, Any]] = Field(default_factory=list)


class LearnerDatasetManager:
    def __init__(self, workspace_dir: Optional[str] = None):
        self.workspace_dir = os.path.abspath(workspace_dir or os.getcwd())
        self.dataset_dir = os.path.join(self.workspace_dir, ".prig_dataset")
        os.makedirs(self.dataset_dir, exist_ok=True)
        self.dataset_file = os.path.join(self.dataset_dir, "user_learning_dataset.json")

        self.plan_repo = StudyPlanRepository(self.workspace_dir)
        self.seg_repo = SeguimientoRepository(self.workspace_dir)

    def _classify_item(self, text_content: str) -> List[str]:
        """ Clasifica un texto en una o varias categorías del Hexágono """
        text_lower = text_content.lower()
        matched_categories = []
        for cat_id, keywords in HEXAGON_KEYWORDS.items():
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                    matched_categories.append(cat_id)
                    break
        
        # Si no coincide con ninguna categoría específica, fallback a Programación
        if not matched_categories:
            matched_categories.append("programacion")
        return matched_categories

    def build_and_save_dataset(self) -> UserLearningDataset:
        # 1. Cargar Recorridos y Seguimientos
        raw_plans = self.plan_repo.list_plans()
        full_recorridos = []
        for p in raw_plans:
            plan_id = p.get("plan_id")
            if plan_id:
                state = self.plan_repo.load_state(plan_id)
                if state:
                    full_recorridos.append(state.model_dump())

        raw_segs = self.seg_repo.list_all()
        full_seguimientos = []
        for s in raw_segs:
            seg_id = s.get("id")
            if seg_id:
                path_obj = self.seg_repo.load(seg_id)
                if path_obj:
                    full_seguimientos.append(path_obj.model_dump())

        # 2. Inicializar Hexágono de Competencias (6 ejes principales)
        hexagon_data = {
            "matematicas": HexagonCompetency(category_id="matematicas", label="Matemáticas", score=0, level=1),
            "programacion": HexagonCompetency(category_id="programacion", label="Programación", score=0, level=1),
            "machine_learning": HexagonCompetency(category_id="machine_learning", label="Machine Learning", score=0, level=1),
            "deep_learning": HexagonCompetency(category_id="deep_learning", label="Deep Learning", score=0, level=1),
            "base_de_datos": HexagonCompetency(category_id="base_de_datos", label="Base de Datos", score=0, level=1),
            "teoria_computacional": HexagonCompetency(category_id="teoria_computacional", label="Teoría Computacional", score=0, level=1)
        }

        activity_heatmap: Dict[str, int] = {}
        mastered_topics: List[Dict[str, Any]] = []
        acquired_competencies: List[Dict[str, Any]] = []

        total_rec = len(full_recorridos)
        total_seg = len(full_seguimientos)
        comp_rec = 0
        comp_seg = 0
        total_blocks_done = 0
        total_topics_mastered = 0

        today_str = datetime.now().strftime("%Y-%m-%d")

        def as_day(iso_value: str) -> str:
            """ Convierte una marca ISO en 'YYYY-MM-DD'; si falta, cae en hoy """
            if not iso_value:
                return today_str
            try:
                return datetime.fromisoformat(iso_value).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                return today_str

        def register_activity(day: str, amount: int = 1) -> None:
            activity_heatmap[day] = activity_heatmap.get(day, 0) + amount

        # -------------------------------------------------------------
        # PROCESAR RECORRIDOS (SOLO ELEMENTOS COMPLETADOS SUMAN AL HEXÁGONO)
        # -------------------------------------------------------------
        for r in full_recorridos:
            is_approved = r.get("status") == "APPROVED"
            approved_steps = set(r.get("approved_steps", []))
            completed_notebooks = set(r.get("completed_notebooks", []))
            user_goal = r.get("user_goal", "Recorrido de Estudio")
            # Los recorridos no guardan fecha por elemento, así que se usa la última
            # modificación del plan en lugar de amontonarlo todo en el día de hoy.
            plan_day = as_day(r.get("updated_at") or r.get("created_at"))

            if is_approved:
                comp_rec += 1
                register_activity(plan_day)

            # Sumar puntos por pasos aprobados
            for step_id in approved_steps:
                total_blocks_done += 1
                matched_cats = self._classify_item(f"{user_goal} {step_id}")
                for cat in matched_cats:
                    hexagon_data[cat].score += 15
                    hexagon_data[cat].completed_items_count += 1
                register_activity(plan_day)

            for nb in completed_notebooks:
                matched_cats = self._classify_item(f"{user_goal} {nb}")
                for cat in matched_cats:
                    hexagon_data[cat].score += 20
                    hexagon_data[cat].completed_items_count += 1
                register_activity(plan_day)

        # -------------------------------------------------------------
        # PROCESAR SEGUIMIENTOS (SOLO BLOQUES COMPLETADOS SUMAN AL HEXÁGONO)
        # -------------------------------------------------------------
        for s in full_seguimientos:
            goal = s.get("goal", "Seguimiento de Aprendizaje")
            blocks = s.get("blocks", [])
            completed_ids = set(s.get("completed_blocks", []))
            completion_dates = s.get("completion_dates", {}) or {}
            fallback_day = as_day(s.get("created_at"))

            if len(blocks) > 0 and len(completed_ids) == len(blocks):
                comp_seg += 1

            for b in blocks:
                b_id = b.get("block_id")
                b_title = b.get("title", "")
                b_desc = b.get("description", "")
                b_obj = b.get("learning_objective", "")
                b_check = b.get("validation_check", "")
                topics = b.get("topics", [])

                # REGLA ESTRICTA: SOLO CUANDO EL BLOQUE ESTÁ EN COMPLETED_BLOCKS SUMA
                if b_id in completed_ids:
                    total_blocks_done += 1
                    total_topics_mastered += len(topics)

                    combined_text = f"{goal} {b_title} {b_desc} {b_obj} {b_check} {' '.join(topics)}"
                    matched_cats = self._classify_item(combined_text)

                    # Incrementar puntuación en el Hexágono
                    for cat in matched_cats:
                        hexagon_data[cat].score += 15
                        hexagon_data[cat].completed_items_count += 1

                    # Registrar actividad en Mapa de Calor en la fecha real de completado
                    register_activity(as_day(completion_dates.get(b_id)) if completion_dates.get(b_id) else fallback_day)

                    # Agregar Temas Dominados
                    for t in topics:
                        mastered_topics.append({
                            "topic": t,
                            "source_goal": goal,
                            "block_title": b_title,
                            "categories": matched_cats,
                            "type": "seguimiento"
                        })

                    # Agregar Competencias Adquiridas
                    if b_obj or b_check:
                        acquired_competencies.append({
                            "title": b_title,
                            "objective": b_obj,
                            "check": b_check,
                            "source_goal": goal,
                            "categories": matched_cats
                        })

        # -------------------------------------------------------------
        # CALCULAR NIVELES Y ESCALAS DEL HEXÁGONO (Nivel = score // 100 + 1)
        # -------------------------------------------------------------
        for cat_id, hex_obj in hexagon_data.items():
            hex_obj.level = (hex_obj.score // 100) + 1
            # Normalizar valor relativo dentro de la escala activa (max 100 por nivel)
            hex_obj.max_scale = max(100, hex_obj.score + 50)

        total_items = total_rec + total_seg
        comp_items = comp_rec + comp_seg
        overall_pct = (comp_items / total_items * 100.0) if total_items > 0 else 0.0

        metrics = UserProfileMetrics(
            total_recorridos=total_rec,
            total_seguimientos=total_seg,
            completed_recorridos=comp_rec,
            completed_seguimientos=comp_seg,
            total_blocks_completed=total_blocks_done,
            total_topics_mastered=total_topics_mastered,
            overall_progress_pct=round(overall_pct, 1),
            last_activity=datetime.now().isoformat()
        )

        dataset = UserLearningDataset(
            updated_at=datetime.now().isoformat(),
            metrics=metrics,
            hexagon=hexagon_data,
            activity_heatmap=activity_heatmap,
            mastered_topics=mastered_topics,
            acquired_competencies=acquired_competencies,
            recorridos=full_recorridos,
            seguimientos=full_seguimientos
        )

        with open(self.dataset_file, 'w', encoding='utf-8') as f:
            f.write(dataset.model_dump_json(indent=2))

        return dataset

    def get_dataset(self) -> UserLearningDataset:
        if os.path.exists(self.dataset_file):
            try:
                doc = schema_migrations.load_migrated(self.dataset_file, "dataset")
                return UserLearningDataset.model_validate(doc)
            except Exception as err:
                print(f"⚠️ No se pudo leer el dataset guardado ({err}); se reconstruye.")
        return self.build_and_save_dataset()
