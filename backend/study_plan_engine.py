import os
import json
import uuid
import schema_migrations
import shutil
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, model_validator, field_validator

# ==========================================
# 1. ENUMS
# ==========================================

class PlanStatusEnum(str, Enum):
    DRAFT = "DRAFT"
    KNOWLEDGE_REVIEW = "KNOWLEDGE_REVIEW"
    KNOWLEDGE_APPROVED = "KNOWLEDGE_APPROVED"
    PRACTICAL_REVIEW = "PRACTICAL_REVIEW"
    PRACTICAL_APPROVED = "PRACTICAL_APPROVED"
    LEARNING_REVIEW = "LEARNING_REVIEW"
    APPROVED = "APPROVED"

class ActionEnum(str, Enum):
    ADD_PREREQUISITE = "ADD_PREREQUISITE"
    REMOVE_PREREQUISITE = "REMOVE_PREREQUISITE"
    ADD_TOPIC = "ADD_TOPIC"
    REMOVE_TOPIC = "REMOVE_TOPIC"
    REDUCE_DEPTH = "REDUCE_DEPTH"
    INCREASE_DEPTH = "INCREASE_DEPTH"
    SWAP_NOTEBOOK = "SWAP_NOTEBOOK"
    CUSTOM_CORRECTION = "CUSTOM_CORRECTION"

class ConceptTypeEnum(str, Enum):
    FOUNDATIONAL = "FOUNDATIONAL"
    PRACTICAL = "PRACTICAL"
    ADVANCED = "ADVANCED"

class NotebookActionEnum(str, Enum):
    CREATED_FROM_SCRATCH = "CREATED_FROM_SCRATCH"
    COPIED_AND_EXPLAINED = "COPIED_AND_EXPLAINED"


# El modelo escribe "CREATE", "COPY" o "create_from_scratch" con total naturalidad;
# rechazar el plan entero por el nombre de una acción es desproporcionado.
ACCIONES_CUADERNO = {
    "create": NotebookActionEnum.CREATED_FROM_SCRATCH,
    "created": NotebookActionEnum.CREATED_FROM_SCRATCH,
    "create_from_scratch": NotebookActionEnum.CREATED_FROM_SCRATCH,
    "created_from_scratch": NotebookActionEnum.CREATED_FROM_SCRATCH,
    "new": NotebookActionEnum.CREATED_FROM_SCRATCH,
    "scratch": NotebookActionEnum.CREATED_FROM_SCRATCH,
    "copy": NotebookActionEnum.COPIED_AND_EXPLAINED,
    "copied": NotebookActionEnum.COPIED_AND_EXPLAINED,
    "copy_and_explain": NotebookActionEnum.COPIED_AND_EXPLAINED,
    "copied_and_explained": NotebookActionEnum.COPIED_AND_EXPLAINED,
    "reuse": NotebookActionEnum.COPIED_AND_EXPLAINED,
}

# ==========================================
# 2. CONTRATO 1: KNOWLEDGE_MAP (Agente 1)
# ==========================================

def _texto(valor, por_defecto: str = "") -> str:
    """ Lo que devuelve un modelo pequeño no siempre es una cadena """
    if valor is None:
        return por_defecto
    if isinstance(valor, str):
        return valor.strip() or por_defecto
    if isinstance(valor, (list, tuple)):
        return ", ".join(str(v) for v in valor) or por_defecto
    return str(valor)


def _rellenar(valores, reglas):
    """ Completa los campos que el modelo haya omitido, antes de validar.

    Un 7B omite campos. Si cada omisión invalida el contrato entero, un plan que
    tardó tres minutos en generarse se tira a la basura por un título ausente.
    Aquí se rellena lo que falta con algo razonable y se conserva el trabajo.
    """
    if not isinstance(valores, dict):
        return valores
    datos = dict(valores)
    for campo, generador in reglas.items():
        actual = datos.get(campo)
        vacio = actual is None or (isinstance(actual, str) and not actual.strip())
        if vacio:
            datos[campo] = generador(datos)
    return datos


class EvidenceSource(BaseModel):
    source_id: str = Field(description="ID único del documento en la Biblioteca (~/.prig_books/)")
    source_type: str = Field(default="book", description="book | paper | documentation | code | notebook")
    title: str = Field(description="Título del documento de origen")
    location: Optional[str] = Field(default="", description="Capítulo, sección o línea")
    confidence: str = Field(default="HIGH", description="HIGH | MEDIUM | LOW")

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        if isinstance(v, str):          # el modelo a veces cita como texto suelto
            v = {"source_id": v}
        v = _rellenar(v, {
            "source_id": lambda d: _texto(d.get("title"), "biblioteca"),
            "title": lambda d: _texto(d.get("source_id"), "Fuente de la biblioteca"),
        })
        # "locator" y "quote" son nombres que el modelo usa a menudo por su cuenta
        if isinstance(v, dict) and not v.get("location"):
            v["location"] = _texto(v.get("locator") or v.get("quote"), "")
        return v

class Concept(BaseModel):
    concept_id: str = Field(description="ID del concepto, ej: conc_backprop")
    name: str = Field(description="Nombre del concepto")
    type: ConceptTypeEnum = Field(default=ConceptTypeEnum.FOUNDATIONAL)
    characteristics: List[str] = Field(default_factory=list)
    specifications: Optional[str] = Field(default="")
    dependencies: List[str] = Field(default_factory=list, description="Lista de concept_ids dependientes")
    evidence: List[EvidenceSource] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        if isinstance(v, str):
            v = {"name": v}
        return _rellenar(v, {
            "name": lambda d: _texto(d.get("concept_id"), "Concepto"),
            "concept_id": lambda d: f"conc_{uuid.uuid4().hex[:6]}",
        })

class Topic(BaseModel):
    topic_id: str = Field(description="ID del tema, ej: top_neural_nets")
    name: str = Field(description="Nombre del tema")
    concepts: List[Concept] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        if isinstance(v, str):
            v = {"name": v}
        return _rellenar(v, {
            "name": lambda d: _texto(d.get("topic_id"), "Tema"),
            "topic_id": lambda d: f"top_{uuid.uuid4().hex[:6]}",
        })

class Domain(BaseModel):
    domain_id: str = Field(description="ID del dominio, ej: dom_dl_core")
    name: str = Field(description="Nombre del dominio principal")
    topics: List[Topic] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        if isinstance(v, str):
            v = {"name": v}
        return _rellenar(v, {
            "name": lambda d: _texto(d.get("domain_id"), "Dominio"),
            "domain_id": lambda d: f"dom_{uuid.uuid4().hex[:6]}",
        })

class Prerequisite(BaseModel):
    name: str = Field(description="Nombre del prerrequisito")
    reason: str = Field(description="Motivo pedagógico")
    required: bool = Field(default=True)

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        if isinstance(v, str):
            v = {"name": v}
        return _rellenar(v, {
            "name": lambda d: "Prerrequisito",
            "reason": lambda d: "Necesario para seguir la ruta.",
        })

class Relationship(BaseModel):
    source_concept_id: str
    target_concept_id: str
    relation_type: str = Field(default="PREREQUISITE_FOR")

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        return _rellenar(v, {
            "source_concept_id": lambda d: _texto(d.get("from") or d.get("source"), ""),
            "target_concept_id": lambda d: _texto(d.get("to") or d.get("target"), ""),
        })

class KnowledgeMap(BaseModel):
    goal: str
    prerequisites: List[Prerequisite] = Field(default_factory=list)
    domains: List[Domain] = Field(default_factory=list)
    relationships: List[Relationship] = Field(default_factory=list)
    exceptions: List[str] = Field(default_factory=list)
    terminology: Dict[str, str] = Field(default_factory=dict)
    recommended_order: List[str] = Field(default_factory=list)
    evidence_summary: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        v = _rellenar(v, {"goal": lambda d: "Ruta de aprendizaje"})
        # Una relación sin extremos no aporta nada y sí puede romper la validación
        if isinstance(v, dict) and isinstance(v.get("relationships"), list):
            v["relationships"] = [
                r for r in v["relationships"]
                if not isinstance(r, dict) or (r.get("source_concept_id") or r.get("from") or r.get("source"))
            ]
        return v

# ==========================================
# 3. CONTRATO 2: PRACTICAL_CURRICULUM (Agente 2)
# ==========================================

class PracticalTask(BaseModel):
    task_id: str
    description: str
    expected_output: Optional[str] = ""

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        if isinstance(v, str):
            v = {"description": v}
        return _rellenar(v, {
            "task_id": lambda d: f"task_{uuid.uuid4().hex[:6]}",
            "description": lambda d: "Tarea práctica del módulo.",
        })

class PracticalModule(BaseModel):
    module_id: str = Field(description="ID del módulo, ej: mod_01_cnn_basics")
    name: str = Field(description="Nombre del módulo de práctica")
    objective: str = Field(description="Objetivo principal del módulo")
    topics: List[str] = Field(default_factory=list)
    concepts: List[str] = Field(default_factory=list, description="Lista de concept_ids asociados del KnowledgeMap")
    practical_tasks: List[str] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list)
    validation_criteria: List[str] = Field(default_factory=list, description="¿Cómo sabemos que aprendió esto?")

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        if isinstance(v, str):
            v = {"name": v}
        return _rellenar(v, {
            "module_id": lambda d: f"mod_{uuid.uuid4().hex[:6]}",
            "name": lambda d: _texto(d.get("module_id"), "Módulo práctico"),
            "objective": lambda d: f"Practicar {_texto(d.get('name'), 'los conceptos del módulo')}.",
        })

class ModuleDependency(BaseModel):
    module_id: str
    depends_on: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        return _rellenar(v, {"module_id": lambda d: f"mod_{uuid.uuid4().hex[:6]}"})

class PracticalCurriculum(BaseModel):
    curriculum_id: str
    knowledge_map_version: int = Field(default=1)
    objectives: List[str] = Field(default_factory=list)
    modules: List[PracticalModule] = Field(default_factory=list)
    learning_dependencies: List[ModuleDependency] = Field(default_factory=list)
    progression: List[str] = Field(default_factory=list)
    validation_criteria_summary: Optional[str] = ""

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        return _rellenar(v, {"curriculum_id": lambda d: f"curr_{uuid.uuid4().hex[:8]}"})

# ==========================================
# 4. CONTRATO 3: EXECUTABLE_LEARNING_PLAN (Agente 3)
# ==========================================

class ExecutableNotebook(BaseModel):
    notebook_id: str
    title: str
    action: NotebookActionEnum = Field(default=NotebookActionEnum.COPIED_AND_EXPLAINED)
    source_library_notebook: Optional[str] = Field(default="", description="Ruta de origen en Biblioteca (~/.prig_books/)")
    executable_path: str = Field(description="Ruta destino editable fuera de la biblioteca")
    is_original_protected: bool = Field(default=True, description="Garantía de protección física del original")
    associated_datasets: List[str] = Field(default_factory=list)
    topics_covered: List[str] = Field(default_factory=list)
    line_by_line_explanations_added: bool = Field(default=True)
    validation_tests_included: bool = Field(default=True)


    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        v = _rellenar(v, {
            "notebook_id": lambda d: f"nb_{uuid.uuid4().hex[:6]}",
            "title": lambda d: _texto(d.get("notebook_id"), "Cuaderno de práctica"),
            "executable_path": lambda d: "",
        })
        if isinstance(v, dict) and v.get("action") is not None:
            clave = str(v["action"]).strip().lower()
            if clave in ACCIONES_CUADERNO:
                v["action"] = ACCIONES_CUADERNO[clave]
            elif clave not in {e.value.lower() for e in NotebookActionEnum}:
                v["action"] = (NotebookActionEnum.COPIED_AND_EXPLAINED
                               if v.get("source_library_notebook")
                               else NotebookActionEnum.CREATED_FROM_SCRATCH)
        return v

class ExecutableModule(BaseModel):
    module_id: str
    module_name: str
    notebooks: List[ExecutableNotebook] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        return _rellenar(v, {
            "module_id": lambda d: f"mod_{uuid.uuid4().hex[:6]}",
            "module_name": lambda d: _texto(d.get("module_id"), "Módulo"),
        })

class ExecutableLearningPlan(BaseModel):
    plan_id: str
    curriculum_version: int = Field(default=1)
    modules_notebooks: List[ExecutableModule] = Field(default_factory=list)
    total_notebooks_created: int = Field(default=0)
    total_notebooks_copied_and_edited: int = Field(default=0)
    total_datasets_linked: int = Field(default=0)
    status: str = Field(default="READY_FOR_APPROVAL")

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        return _rellenar(v, {"plan_id": lambda d: f"exec_{uuid.uuid4().hex[:8]}"})

# ==========================================
# 5. CONTRATO 4: CHANGE_REQUEST (Asistente Diseñador)
# ==========================================

class ChangeRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: f"cr_{uuid.uuid4().hex[:8]}")
    target_agent: str = Field(description="KNOWLEDGE_ARCHITECT | PRACTICE_ARCHITECT | NOTEBOOK_MANAGER")
    action: ActionEnum
    target: str = Field(description="Concepto, tema o cuaderno objetivo")
    parameter: Optional[str] = Field(default="", description="Parámetro adicional o prerrequisito")
    user_prompt: str = Field(description="Texto exacto ingresado por el usuario")
    reason: Optional[str] = Field(default="Solicitud explícita de corrección por el usuario")

# ==========================================
# 6. CONTRATO 5: DECISION_TRACE (Traza en Recorrido)
# ==========================================

class TraceStep(BaseModel):
    step: str
    message: str
    status: str = Field(default="DONE")
    details: Optional[str] = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

class DecisionTrace(BaseModel):
    agent_name: str
    status: str = Field(default="COMPLETED")
    steps: List[TraceStep] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)

# ==========================================
# 7. CONTRATO 6: STUDY_PLAN_STATE (Estado Central)
# ==========================================

class PlanRevision(BaseModel):
    version: int
    timestamp: str
    modified_by: str
    change_request: Optional[ChangeRequest] = None
    summary: str

class StudyPlanState(BaseModel):
    schema_version: int = Field(default=schema_migrations.CURRENT_VERSIONS["study_plan"])
    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:8]}")
    version: int = Field(default=1)
    status: PlanStatusEnum = Field(default=PlanStatusEnum.DRAFT)
    user_goal: str
    knowledge_map: Optional[KnowledgeMap] = None
    practical_curriculum: Optional[PracticalCurriculum] = None
    executable_learning_plan: Optional[ExecutableLearningPlan] = None
    decision_traces: List[DecisionTrace] = Field(default_factory=list)
    revisions: List[PlanRevision] = Field(default_factory=list)
    completed_validation_criteria: Dict[str, List[str]] = Field(default_factory=dict)
    completed_notebooks: List[str] = Field(default_factory=list)
    progress_percentage: float = Field(default=0.0)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def update_progress_percentage(self) -> float:
        total_items = 0
        completed_items = 0

        # Criterios de validación
        if self.practical_curriculum:
            for mod in self.practical_curriculum.modules:
                c_list = mod.validation_criteria or []
                total_items += len(c_list)
                comp_for_mod = self.completed_validation_criteria.get(mod.module_id, [])
                completed_items += len([c for c in c_list if c in comp_for_mod])

        # Cuadernos de código
        if self.executable_learning_plan:
            for mod in self.executable_learning_plan.modules_notebooks:
                for nb in mod.notebooks:
                    total_items += 1
                    if nb.notebook_id in self.completed_notebooks:
                        completed_items += 1

        if total_items == 0:
            self.progress_percentage = 0.0
        else:
            self.progress_percentage = round((completed_items / total_items) * 100.0, 1)

        return self.progress_percentage


# ==========================================
# 8. CAPA DE SEGURIDAD FÍSICA DE NOTEBOOKS
# ==========================================

class NotebookSafetyLayer:
    """ Capa física que impide modificar cualquier archivo dentro de ~/.prig_books/ """
    
    LIBRARY_DIR = os.path.expanduser("~/.prig_books")

    @classmethod
    def is_path_in_library(cls, path: str) -> bool:
        # startswith daba falsos positivos con rutas hermanas como ~/.prig_books_backup
        abs_path = os.path.abspath(path)
        abs_lib = os.path.abspath(cls.LIBRARY_DIR)
        try:
            return os.path.commonpath([abs_path, abs_lib]) == abs_lib
        except ValueError:
            return False

    @classmethod
    def create_notebook_copy(cls, source_path: str, dest_dir: str, new_name: str = None) -> str:
        abs_src = os.path.abspath(source_path)
        if not os.path.exists(abs_src):
            raise FileNotFoundError(f"El cuaderno original no existe en la biblioteca: {source_path}")

        abs_dest_dir = os.path.abspath(dest_dir)
        os.makedirs(abs_dest_dir, exist_ok=True)

        if cls.is_path_in_library(abs_dest_dir):
            raise PermissionError(f"🔒 PROTECCIÓN FÍSICA: No se permite crear copias editables dentro del directorio de la Biblioteca ({cls.LIBRARY_DIR}). Selecciona un directorio de proyecto activo.")

        filename = new_name or f"copia_{os.path.basename(abs_src)}"
        if not filename.endswith('.ipynb') and not filename.endswith('.py'):
            filename += '.ipynb'

        dest_path = os.path.join(abs_dest_dir, filename)
        shutil.copy2(abs_src, dest_path)
        return dest_path

    @classmethod
    def write_executable_notebook(cls, dest_path: str, content_json: dict) -> str:
        abs_dest = os.path.abspath(dest_path)
        if cls.is_path_in_library(abs_dest):
            raise PermissionError(f"🔒 PROTECCIÓN FÍSICA VIOLADA: Intento de escritura en archivo protegido de la Biblioteca ({abs_dest}).")

        os.makedirs(os.path.dirname(abs_dest), exist_ok=True)
        with open(abs_dest, 'w', encoding='utf-8') as f:
            json.dump(content_json, f, indent=2, ensure_ascii=False)

        return abs_dest


    @classmethod
    def generate_explained_notebook_content(cls, module_name: str, objective: str, validation_criteria: list, source_code: str = "") -> dict:
        """ Genera el formato JSON de cuaderno Jupyter (.ipynb v4) con celdas de teoría, validation_criteria y código """
        criteria_md = "\n".join([f"- [ ] {vc}" for vc in validation_criteria]) if validation_criteria else "- [ ] Práctica completada con éxito"

        header_md = (
            f"# 📓 {module_name}\n\n"
            f"### 🎯 Objetivo de Aprendizaje:\n{objective}\n\n"
            f"### 📋 Criterios de Validación de Aprendizaje (validation_criteria):\n{criteria_md}\n\n"
            f"---\n"
            f"*Cuaderno generado automáticamente por el **Notebook & Learning Manager** de Prig IDE.*"
        )

        theory_md = (
            f"## 💡 Explicación Teórica & Conceptos Base\n\n"
            f"En este cuaderno pondremos en práctica los conceptos del módulo.\n"
            f"Revisa el código a continuación, ejecuta las celdas secuencialmente (`Shift + Enter`) y verifica cada criterio de validación."
        )

        code_block = source_code.strip() if source_code else (
            "# Importaciones principales\n"
            "import sys\n"
            "import numpy as np\n\n"
            "# Imprimir entorno\n"
            "print('✨ Cuaderno de práctica activo')\n"
        )

        notebook_json = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": [header_md]
                },
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": [theory_md]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [code_block]
                }
            ],
            "metadata": {
                "language_info": {
                    "name": "python"
                }
            },
            "nbformat": 4,
            "nbformat_minor": 2
        }
        return notebook_json


# ==========================================
# 8.5 PLAN VALIDATOR (Componente Determinista de Validación Cruzada sin Modelo)
# ==========================================

class PlanValidator:
    """ Validador determinista de esquemas, referencias cruzadas de IDs y transiciones de estado """

    VALID_TRANSITIONS = {
        PlanStatusEnum.DRAFT: [PlanStatusEnum.KNOWLEDGE_REVIEW],
        PlanStatusEnum.KNOWLEDGE_REVIEW: [PlanStatusEnum.KNOWLEDGE_REVIEW, PlanStatusEnum.KNOWLEDGE_APPROVED],
        PlanStatusEnum.KNOWLEDGE_APPROVED: [PlanStatusEnum.PRACTICAL_REVIEW],
        PlanStatusEnum.PRACTICAL_REVIEW: [PlanStatusEnum.PRACTICAL_REVIEW, PlanStatusEnum.PRACTICAL_APPROVED],
        PlanStatusEnum.PRACTICAL_APPROVED: [PlanStatusEnum.LEARNING_REVIEW],
        PlanStatusEnum.LEARNING_REVIEW: [PlanStatusEnum.LEARNING_REVIEW, PlanStatusEnum.APPROVED],
        PlanStatusEnum.APPROVED: []
    }

    @classmethod
    def validate_state_transition(cls, current_status: PlanStatusEnum, next_status: PlanStatusEnum) -> bool:
        allowed = cls.VALID_TRANSITIONS.get(current_status, [])
        if next_status not in allowed:
            raise ValueError(f"❌ Transición de estado no válida: {current_status.value} ➔ {next_status.value}. Permitidas: {[s.value for s in allowed]}")
        return True

    @classmethod
    def validate_knowledge_map(cls, kmap: KnowledgeMap, library_items: List[dict] = None) -> List[str]:
        warnings = []
        concept_ids = set()

        # Extraer todos los concept_ids
        for dom in kmap.domains:
            for top in dom.topics:
                for conc in top.concepts:
                    if conc.concept_id in concept_ids:
                        warnings.append(f"ID de concepto duplicado detectado: {conc.concept_id}")
                    concept_ids.add(conc.concept_id)

        # Validar referencias en relationships
        for rel in kmap.relationships:
            if rel.source_concept_id not in concept_ids:
                warnings.append(f"Relación referencia a concept_id inexistente: {rel.source_concept_id}")
            if rel.target_concept_id not in concept_ids:
                warnings.append(f"Relación referencia a concept_id inexistente: {rel.target_concept_id}")

        return warnings

    @classmethod
    def validate_practical_curriculum(cls, curr: PracticalCurriculum, kmap: KnowledgeMap) -> List[str]:
        warnings = []
        kmap_concept_ids = set()

        if kmap:
            for dom in kmap.domains:
                for top in dom.topics:
                    for conc in top.concepts:
                        kmap_concept_ids.add(conc.concept_id)

        # Validar que los conceptos en los módulos prácticos existan en el KNOWLEDGE_MAP
        for mod in curr.modules:
            for conc_id in mod.concepts:
                if kmap_concept_ids and conc_id not in kmap_concept_ids:
                    warnings.append(f"Módulo práctico '{mod.module_id}' hace referencia a concept_id no encontrado en KnowledgeMap: {conc_id}")

        return warnings

    @classmethod
    def validate_executable_plan(cls, exec_plan: ExecutableLearningPlan, curr: PracticalCurriculum) -> List[str]:
        warnings = []
        curr_module_ids = set(m.module_id for m in curr.modules) if curr else set()

        for mod in exec_plan.modules_notebooks:
            if curr_module_ids and mod.module_id not in curr_module_ids:
                warnings.append(f"ExecutableModule hace referencia a module_id no existente en Curriculum: {mod.module_id}")

        return warnings

# ==========================================
# 9. REPOSITORIO DE PLANES CON VERSIONADO INMUTABLE
# ==========================================

class StudyPlanRepository:
    """ Repositorio inmutable que gestiona el almacenamiento versionado .prig_plans/<plan_id>/ (manifest.json, v1.json, v2.json, current.json) """

    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = os.path.abspath(workspace_dir or os.getcwd())
        self.plans_dir = os.path.join(self.workspace_dir, ".prig_plans")
        os.makedirs(self.plans_dir, exist_ok=True)

    def _get_plan_dir(self, plan_id: str) -> str:
        pdir = os.path.join(self.plans_dir, plan_id)
        os.makedirs(pdir, exist_ok=True)
        return pdir

    def save_state(self, state: StudyPlanState) -> None:
        state.updated_at = datetime.now().isoformat()
        pdir = self._get_plan_dir(state.plan_id)

        # 1. Guardar versión inmutable v{N}.json
        v_path = os.path.join(pdir, f"v{state.version}.json")
        with open(v_path, 'w', encoding='utf-8') as f:
            f.write(state.model_dump_json(indent=2))

        # 2. Guardar current.json
        curr_path = os.path.join(pdir, "current.json")
        with open(curr_path, 'w', encoding='utf-8') as f:
            f.write(state.model_dump_json(indent=2))

        # 3. Actualizar manifest.json
        manifest_path = os.path.join(pdir, "manifest.json")
        manifest = {
            "plan_id": state.plan_id,
            "user_goal": state.user_goal,
            "current_version": state.version,
            "status": state.status.value,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "versions_count": state.version,
            "revisions": [r.model_dump() for r in state.revisions]
        }
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    def load_state(self, plan_id: str, version: int = None) -> Optional[StudyPlanState]:
        pdir = os.path.join(self.plans_dir, plan_id)
        if not os.path.exists(pdir):
            # Fallback legacy .prig_plans/{plan_id}.json
            legacy_file = os.path.join(self.plans_dir, f"{plan_id}.json")
            if os.path.exists(legacy_file):
                doc = schema_migrations.load_migrated(legacy_file, "study_plan")
                return StudyPlanState.model_validate(doc)
            return None

        if version:
            target_path = os.path.join(pdir, f"v{version}.json")
        else:
            target_path = os.path.join(pdir, "current.json")

        if os.path.exists(target_path):
            doc = schema_migrations.load_migrated(target_path, "study_plan")
            return StudyPlanState.model_validate(doc)
        return None

    def list_plans(self) -> List[dict]:
        plans = []
        if not os.path.exists(self.plans_dir):
            return plans

        for item in os.listdir(self.plans_dir):
            item_path = os.path.join(self.plans_dir, item)
            if os.path.isdir(item_path):
                manifest_path = os.path.join(item_path, "manifest.json")
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, 'r', encoding='utf-8') as f:
                            plans.append(json.load(f))
                    except Exception:
                        pass
            elif item.endswith('.json'):
                # Legacy file
                try:
                    with open(item_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        plans.append({
                            "plan_id": data.get("plan_id"),
                            "user_goal": data.get("user_goal"),
                            "current_version": data.get("version", 1),
                            "status": data.get("status", "DRAFT"),
                            "updated_at": data.get("updated_at", "")
                        })
                except Exception:
                    pass

        plans.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return plans

    def delete_plan(self, plan_id: str) -> bool:
        pdir = os.path.join(self.plans_dir, plan_id)
        if os.path.exists(pdir) and os.path.isdir(pdir):
            shutil.rmtree(pdir)
            return True
        legacy_file = os.path.join(self.plans_dir, f"{plan_id}.json")
        if os.path.exists(legacy_file):
            os.remove(legacy_file)
            return True
        return False

# ==========================================
# 9.5 CONTRATO: SEGUIMIENTO (Topic-based path)
# ==========================================

class SeguimientoBlock(BaseModel):
    block_id: str = Field(default_factory=lambda: f"blk_{uuid.uuid4().hex[:6]}")
    title: str = Field(description="Título del bloque o etapa")
    description: str = Field(description="Descripción de lo que se debe aprender o hacer en este bloque")
    learning_objective: str = Field(default="", description="¿Qué competencia se lleva el usuario al terminar?")
    validation_check: str = Field(default="", description="¿Cómo sabemos que lo aprendió? (Mini hito práctico)")
    topics: List[str] = Field(description="Lista de temas específicos asignados a este bloque")
    type: str = Field(default="theory", description="theory | practice | project | mixed")
    estimated_time: str = Field(default="N/A", description="Tiempo estimado, ej: 2 horas, 1 semana")

    @model_validator(mode="before")
    @classmethod
    def _tolerar(cls, v):
        if isinstance(v, str):
            v = {"title": v}
        v = _rellenar(v, {
            "title": lambda d: "Bloque de estudio",
            "description": lambda d: _texto(d.get("learning_objective"), "Estudio del bloque."),
        })
        if isinstance(v, dict):
            temas = v.get("topics")
            if isinstance(temas, str):
                v["topics"] = [t.strip() for t in temas.split(",") if t.strip()]
            elif not temas:
                v["topics"] = [_texto(v.get("title"), "Tema general")]
        return v

class SeguimientoPath(BaseModel):
    """ Ruta de Aprendizaje Guiado.

    Modelo único al que convergen los dos sistemas anteriores: las rutas rápidas por
    temas (antes "Seguimiento") y los planes de tres agentes (antes "Recorrido").
    Se conserva el nombre de clase para no invalidar los archivos ya guardados.
    """
    schema_version: int = Field(default=schema_migrations.CURRENT_VERSIONS["seguimiento"])
    id: str = Field(default_factory=lambda: f"seg_{uuid.uuid4().hex[:8]}")
    goal: str = Field(description="La meta principal de la ruta")

    # Cómo se generó: rapido (un agente) | profundo (tres agentes) | migrado
    source: str = Field(default="rapido")
    level: str = Field(default="Intermedio")
    focus: str = Field(default="Práctico")

    # Rastro del plan de tres agentes, para no perder su análisis al unificar
    origin_plan_id: Optional[str] = Field(default=None)
    knowledge_map: Optional[Dict[str, Any]] = Field(default=None)
    decision_traces: List[Dict[str, Any]] = Field(default_factory=list)
    notebooks: List[Dict[str, Any]] = Field(default_factory=list)
    topics_raw: str = Field(default="", description="Temas originales ingresados por el usuario")
    blocks: List[SeguimientoBlock] = Field(default_factory=list, description="Lista ordenada de bloques a seguir")
    rationale: str = Field(default="", description="Explicación del modelo sobre por qué organizó los temas de esta forma")
    completed_blocks: List[str] = Field(default_factory=list, description="Lista de block_ids completados")
    completion_dates: Dict[str, str] = Field(
        default_factory=dict,
        description="block_id -> fecha ISO en que se completó, para el mapa de calor"
    )
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class SeguimientoRepository:
    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = os.path.abspath(workspace_dir or os.getcwd())
        self.seg_dir = os.path.join(self.workspace_dir, ".prig_seguimientos")
        os.makedirs(self.seg_dir, exist_ok=True)

    def save(self, path_obj: SeguimientoPath) -> None:
        file_path = os.path.join(self.seg_dir, f"{path_obj.id}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(path_obj.model_dump_json(indent=2))

    def load(self, seg_id: str) -> Optional[SeguimientoPath]:
        file_path = os.path.join(self.seg_dir, f"{seg_id}.json")
        if os.path.exists(file_path):
            doc = schema_migrations.load_migrated(file_path, "seguimiento")
            return SeguimientoPath.model_validate(doc)
        return None

    def list_all(self) -> List[dict]:
        items = []
        if not os.path.exists(self.seg_dir):
            return items
        for f in os.listdir(self.seg_dir):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(self.seg_dir, f), 'r', encoding='utf-8') as fp:
                        data = json.load(fp)
                        items.append({
                            "id": data.get("id"),
                            "goal": data.get("goal"),
                            "created_at": data.get("created_at"),
                            "progress": round((len(data.get("completed_blocks", [])) / max(1, len(data.get("blocks", [])))) * 100)
                        })
                except Exception:
                    pass
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items

    def delete(self, seg_id: str) -> bool:
        file_path = os.path.join(self.seg_dir, f"{seg_id}.json")
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False

# ==========================================
# 10. MOTOR Y MÁQUINA DE ESTADOS DEL PLAN DE ESTUDIO
# ==========================================

class StudyPlanEngine:
    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = os.path.abspath(workspace_dir or os.getcwd())
        self.repo = StudyPlanRepository(self.workspace_dir)

    def create_new_plan(self, user_goal: str) -> StudyPlanState:
        state = StudyPlanState(
            user_goal=user_goal,
            status=PlanStatusEnum.DRAFT
        )
        self.save_state(state)
        return state

    def save_state(self, state: StudyPlanState) -> None:
        self.repo.save_state(state)

    def load_state(self, plan_id: str, version: int = None) -> Optional[StudyPlanState]:
        return self.repo.load_state(plan_id, version)

    def list_all_plans(self) -> List[dict]:
        return self.repo.list_plans()

    def delete_plan(self, plan_id: str) -> bool:
        return self.repo.delete_plan(plan_id)


    def approve_knowledge_step(self, plan_id: str) -> StudyPlanState:
        state = self.load_state(plan_id)
        if not state or not state.knowledge_map:
            raise ValueError("No existe un KnowledgeMap válido para aprobar en este plan.")
        
        PlanValidator.validate_state_transition(state.status, PlanStatusEnum.KNOWLEDGE_APPROVED)

        state.status = PlanStatusEnum.KNOWLEDGE_APPROVED
        state.revisions.append(PlanRevision(
            version=state.version,
            timestamp=datetime.now().isoformat(),
            modified_by="USER",
            summary="Aprobación del Módulo 1 (Ciclo Básico - KnowledgeMap)"
        ))
        self.save_state(state)
        return state

    def approve_practical_step(self, plan_id: str) -> StudyPlanState:
        state = self.load_state(plan_id)
        if not state or not state.practical_curriculum:
            raise ValueError("No existe un PracticalCurriculum válido para aprobar.")

        PlanValidator.validate_state_transition(state.status, PlanStatusEnum.PRACTICAL_APPROVED)

        state.status = PlanStatusEnum.PRACTICAL_APPROVED
        state.revisions.append(PlanRevision(
            version=state.version,
            timestamp=datetime.now().isoformat(),
            modified_by="USER",
            summary="Aprobación del Módulo 2 (Ciclo Práctico - PracticalCurriculum)"
        ))
        self.save_state(state)
        return state

    def approve_learning_step(self, plan_id: str) -> StudyPlanState:
        state = self.load_state(plan_id)
        if not state or not state.executable_learning_plan:
            raise ValueError("No existe un ExecutableLearningPlan para aprobar.")

        PlanValidator.validate_state_transition(state.status, PlanStatusEnum.APPROVED)

        state.status = PlanStatusEnum.APPROVED
        state.revisions.append(PlanRevision(
            version=state.version,
            timestamp=datetime.now().isoformat(),
            modified_by="USER",
            summary="✨ PLAN APROBADO COMPLETAMENTE PARA COMENZAR"
        ))
        self.save_state(state)
        return state


    def apply_change_request(self, plan_id: str, change_req: ChangeRequest) -> StudyPlanState:
        state = self.load_state(plan_id)
        if not state:
            raise ValueError(f"Plan no encontrado: {plan_id}")

        old_version = state.version
        state.version += 1

        # Aplicar modificación incremental sobre el estado
        if change_req.action == ActionEnum.ADD_PREREQUISITE and state.knowledge_map:
            state.knowledge_map.prerequisites.append(Prerequisite(
                name=change_req.target,
                reason=change_req.reason or "Añadido por solicitud del usuario",
                required=True
            ))
        elif change_req.action == ActionEnum.REMOVE_PREREQUISITE and state.knowledge_map:
            state.knowledge_map.prerequisites = [
                p for p in state.knowledge_map.prerequisites
                if change_req.target.lower() not in p.name.lower()
            ]
        elif change_req.action == ActionEnum.ADD_CONCEPT and state.knowledge_map:
            if state.knowledge_map.domains and state.knowledge_map.domains[0].topics:
                new_conc = Concept(
                    concept_id=f"conc_{uuid.uuid4().hex[:6]}",
                    name=change_req.target,
                    specifications=change_req.reason or "Añadido manualmente"
                )
                state.knowledge_map.domains[0].topics[0].concepts.append(new_conc)
        elif change_req.action == ActionEnum.REMOVE_CONCEPT and state.knowledge_map:
            for dom in state.knowledge_map.domains:
                for top in dom.topics:
                    top.concepts = [c for c in top.concepts if change_req.target.lower() not in c.name.lower() and c.concept_id != change_req.target]
        elif change_req.action == ActionEnum.ADD_TOPIC and state.knowledge_map:
            if state.knowledge_map.domains:
                new_topic = Topic(
                    topic_id=f"top_{uuid.uuid4().hex[:6]}",
                    name=change_req.target,
                    concepts=[Concept(concept_id=f"conc_{uuid.uuid4().hex[:6]}", name=f"Concepto {change_req.target}")]
                )
                state.knowledge_map.domains[0].topics.append(new_topic)
        elif change_req.action == ActionEnum.MODIFY_OBJECTIVE:
            if state.knowledge_map:
                state.knowledge_map.goal = change_req.target
        elif change_req.action == ActionEnum.ADD_PRACTICAL_MODULE and state.practical_curriculum:
            new_mod_id = f"mod_{len(state.practical_curriculum.modules) + 1:02d}"
            state.practical_curriculum.modules.append(PracticalModule(
                module_id=new_mod_id,
                name=change_req.target,
                objective=change_req.reason or f"Practicar {change_req.target}",
                validation_criteria=[f"✓ Implementar {change_req.target}"]
            ))

        state.revisions.append(PlanRevision(
            version=state.version,
            timestamp=datetime.now().isoformat(),
            modified_by="USER_ASSISTANT",
            change_request=change_req,
            summary=f"Versión {state.version}: Corrección aplicada ({change_req.action.value} -> {change_req.target})"
        ))

        self.save_state(state)
        return state


    def toggle_validation_criterion(self, plan_id: str, module_id: str, criterion_text: str) -> StudyPlanState:
        state = self.load_state(plan_id)
        if not state:
            raise ValueError("Plan no encontrado.")

        mod_criteria = state.completed_validation_criteria.get(module_id, [])
        if criterion_text in mod_criteria:
            mod_criteria.remove(criterion_text)
        else:
            mod_criteria.append(criterion_text)

        state.completed_validation_criteria[module_id] = mod_criteria
        state.update_progress_percentage()
        self.save_state(state)
        return state

    def toggle_notebook_completion(self, plan_id: str, notebook_id: str) -> StudyPlanState:
        state = self.load_state(plan_id)
        if not state:
            raise ValueError("Plan no encontrado.")

        if notebook_id in state.completed_notebooks:
            state.completed_notebooks.remove(notebook_id)
        else:
            state.completed_notebooks.append(notebook_id)

        state.update_progress_percentage()
        self.save_state(state)
        return state

