"""
Aprendizaje Guiado: el sistema único de rutas de estudio.

Antes había dos que hacían casi lo mismo por caminos distintos:

  · "Seguimiento" — un agente organizaba una lista de temas en bloques.
  · "Recorrido"   — tres agentes producían mapa de conocimiento, currículo
                    práctico y cuadernos ejecutables.

Duplicaban interfaz, almacenamiento y seguimiento del progreso. Aquí convergen en un
solo modelo de ruta con bloques, y la diferencia pasa a ser únicamente la PROFUNDIDAD
con la que se genera:

  · rápido   — un agente, resultado en segundos
  · profundo — los tres agentes, con su análisis y sus cuadernos

Los planes antiguos se migran a este modelo sin perder nada.
"""

import os
import json
import queue
import threading
import inspect
from datetime import datetime
from typing import Any, Dict, List, Optional, Generator

from study_plan_engine import (
    SeguimientoPath, SeguimientoBlock, SeguimientoRepository,
    StudyPlanRepository, KnowledgeMap, PracticalCurriculum,
    ExecutableLearningPlan, NotebookSafetyLayer, PlanValidator,
)


class GuidedLearningService:
    def __init__(self, workspace_dir: str, ai_engine, book_service):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.repo = SeguimientoRepository(self.workspace_dir)
        self.legacy_plans = StudyPlanRepository(self.workspace_dir)
        self.ai = ai_engine
        self.books = book_service

    # ------------------------------------------------------------------
    # Generación
    # ------------------------------------------------------------------

    def generate_fast(self, goal: str, topics: str, level: str = "Intermedio",
                      focus: str = "Práctico", model: str = "qwen2.5-coder:7b") -> SeguimientoPath:
        raw = self.ai.run_topic_organizer(goal, topics, level=level, focus=focus, model=model)
        path = SeguimientoPath.model_validate(raw)
        path.goal = goal
        path.topics_raw = topics
        path.source = "rapido"
        path.level = level
        path.focus = focus
        self.repo.save(path)
        return path

    def generate_deep(self, goal: str, topics: str = "", level: str = "Intermedio",
                      focus: str = "Práctico", model: str = "qwen2.5-coder:7b") -> SeguimientoPath:
        """ Los tres agentes, volcados al modelo unificado.

        El valor del plan profundo era el análisis, no su formato propio: se conserva
        el mapa de conocimiento y las trazas, pero el progreso se lleva con los
        mismos bloques que cualquier otra ruta.
        """
        library = self.books.list_books()
        traces: List[Dict[str, Any]] = []

        # Agente 1 — mapa de conocimiento
        kmap = KnowledgeMap.model_validate(
            self.ai.run_knowledge_architect(goal, library, model=model)
        )
        avisos = PlanValidator.validate_knowledge_map(kmap, library)
        traces.append({
            "agent": "Knowledge Architect",
            "summary": f"{len(kmap.domains)} dominios · {len(kmap.prerequisites)} prerrequisitos",
            "warnings": avisos,
        })

        # Agente 2 — currículo práctico
        curr = PracticalCurriculum.model_validate(
            self.ai.run_practice_architect(kmap.model_dump(), model=model)
        )
        avisos2 = PlanValidator.validate_practical_curriculum(curr, kmap)
        traces.append({
            "agent": "Practice Architect",
            "summary": f"{len(curr.modules)} módulos prácticos",
            "warnings": avisos2,
        })

        path = SeguimientoPath(
            goal=goal,
            topics_raw=topics or ", ".join(
                c.name for d in kmap.domains for t in d.topics for c in t.concepts
            )[:2000],
            rationale=getattr(kmap, "goal", "") or "Ruta generada con análisis profundo.",
            source="profundo",
            level=level,
            focus=focus,
            knowledge_map=kmap.model_dump(),
            decision_traces=traces,
        )

        # Cada módulo práctico se convierte en un bloque de la ruta
        conceptos = {
            c.concept_id: c.name
            for d in kmap.domains for t in d.topics for c in t.concepts
        }
        for mod in curr.modules:
            temas = [conceptos.get(cid, cid) for cid in (mod.concepts or [])]
            criterios = mod.validation_criteria or []
            path.blocks.append(SeguimientoBlock(
                block_id=f"blk_{mod.module_id}",
                title=mod.name,
                description=mod.objective or f"Practicar {mod.name}.",
                learning_objective=mod.objective or "",
                validation_check=criterios[0] if criterios else "Resolver el ejercicio del bloque sin ayuda.",
                topics=temas or [mod.name],
                type="practice",
            ))

        # Agente 3 — cuadernos ejecutables (opcional: si falla, la ruta sigue sirviendo)
        try:
            code_items = [
                b for b in library
                if b.get("category_id") in ("code", "notebooks") or b.get("ext") in ("py", "ipynb")
            ]
            exec_plan = ExecutableLearningPlan.model_validate(
                self.ai.run_notebook_manager(curr.model_dump(), code_items, model=model)
            )
            path.notebooks = self._materialize_notebooks(exec_plan, curr)
            traces.append({
                "agent": "Notebook Manager",
                "summary": f"{len(path.notebooks)} cuadernos generados",
                "warnings": PlanValidator.validate_executable_plan(exec_plan, curr),
            })
        except Exception as err:
            traces.append({
                "agent": "Notebook Manager",
                "summary": "No se generaron cuadernos",
                "warnings": [str(err)],
            })

        path.decision_traces = traces
        self.repo.save(path)
        return path

    def generate_fast_stream(self, goal: str, topics: str, level: str = "Intermedio",
                             focus: str = "Práctico", model: str = "qwen2.5-coder:7b") -> Generator[Dict[str, Any], None, None]:
        q = queue.Queue()
        sentinel = object()
        result_holder = {}

        def worker():
            try:
                def _stage(msg, pct):
                    stage_num = 1 if pct <= 20 else (2 if pct <= 40 else (3 if pct <= 75 else 4))
                    q.put({"type": "stage", "stage_num": stage_num, "total_stages": 4, "message": msg, "pct": pct})

                def _thought(text):
                    q.put({"type": "thought", "text": text})

                def _token(text):
                    q.put({"type": "token", "text": text})

                q.put({"type": "stage", "stage_num": 1, "total_stages": 4, "message": f"Conectando con Ollama y cargando modelo {model}...", "pct": 10})

                sig = inspect.signature(self.ai.run_topic_organizer)
                kwargs = {"level": level, "focus": focus, "model": model}
                if "on_thinking" in sig.parameters:
                    kwargs["on_thinking"] = _thought
                if "on_token" in sig.parameters:
                    kwargs["on_token"] = _token
                if "on_stage" in sig.parameters:
                    kwargs["on_stage"] = _stage

                raw = self.ai.run_topic_organizer(goal, topics, **kwargs)
                path = SeguimientoPath.model_validate(raw)
                path.goal = goal
                path.topics_raw = topics
                path.source = "rapido"
                path.level = level
                path.focus = focus
                self.repo.save(path)
                result_holder["path"] = path
            except Exception as e:
                result_holder["error"] = str(e)
            finally:
                q.put(sentinel)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        while True:
            try:
                event = q.get(timeout=0.1)
                if event is sentinel:
                    break
                yield event
            except queue.Empty:
                if not t.is_alive() and q.empty():
                    break

        if "error" in result_holder:
            yield {"type": "error", "message": result_holder["error"]}
        elif "path" in result_holder:
            yield {"type": "stage", "stage_num": 4, "total_stages": 4, "message": "¡Plan de aprendizaje generado con éxito!", "pct": 100}
            yield {"type": "done", "path": result_holder["path"].model_dump()}

    def generate_deep_stream(self, goal: str, topics: str = "", level: str = "Intermedio",
                             focus: str = "Práctico", model: str = "qwen2.5-coder:7b") -> Generator[Dict[str, Any], None, None]:
        q = queue.Queue()
        sentinel = object()
        result_holder = {}

        def worker():
            try:
                def _thought(text):
                    q.put({"type": "thought", "text": text})

                def _token(text):
                    q.put({"type": "token", "text": text})

                # Etapa 1
                q.put({"type": "stage", "stage_num": 1, "total_stages": 5, "message": "Explorando biblioteca y analizando libros/documentos...", "pct": 10})
                library = self.books.list_books()
                traces: List[Dict[str, Any]] = []

                # Etapa 2: Agente 1
                q.put({"type": "stage", "stage_num": 2, "total_stages": 5, "message": "Agente 1 (Knowledge Architect): Diseñando mapa conceptual y dependencias...", "pct": 30})
                sig1 = inspect.signature(self.ai.run_knowledge_architect)
                kw1 = {"model": model}
                if "on_thinking" in sig1.parameters:
                    kw1["on_thinking"] = _thought
                if "on_token" in sig1.parameters:
                    kw1["on_token"] = _token

                kmap = KnowledgeMap.model_validate(
                    self.ai.run_knowledge_architect(goal, library, **kw1)
                )
                avisos = PlanValidator.validate_knowledge_map(kmap, library)
                traces.append({
                    "agent": "Knowledge Architect",
                    "summary": f"{len(kmap.domains)} dominios · {len(kmap.prerequisites)} prerrequisitos",
                    "warnings": avisos,
                })

                # Etapa 3: Agente 2
                q.put({"type": "stage", "stage_num": 3, "total_stages": 5, "message": "Agente 2 (Practice Architect): Construyendo currículo y módulos prácticos...", "pct": 60})
                sig2 = inspect.signature(self.ai.run_practice_architect)
                kw2 = {"model": model}
                if "on_thinking" in sig2.parameters:
                    kw2["on_thinking"] = _thought
                if "on_token" in sig2.parameters:
                    kw2["on_token"] = _token

                curr = PracticalCurriculum.model_validate(
                    self.ai.run_practice_architect(kmap.model_dump(), **kw2)
                )
                avisos2 = PlanValidator.validate_practical_curriculum(curr, kmap)
                traces.append({
                    "agent": "Practice Architect",
                    "summary": f"{len(curr.modules)} módulos prácticos",
                    "warnings": avisos2,
                })

                # Etapa 4: Agente 3
                q.put({"type": "stage", "stage_num": 4, "total_stages": 5, "message": "Agente 3 (Notebook Manager): Generando cuadernos interactivos Jupyter...", "pct": 80})
                path = SeguimientoPath(
                    goal=goal,
                    topics_raw=topics or ", ".join(
                        c.name for d in kmap.domains for t in d.topics for c in t.concepts
                    )[:2000],
                    rationale=getattr(kmap, "goal", "") or "Ruta generada con análisis profundo.",
                    source="profundo",
                    level=level,
                    focus=focus,
                    knowledge_map=kmap.model_dump(),
                    decision_traces=traces,
                )

                conceptos = {
                    c.concept_id: c.name
                    for d in kmap.domains for t in d.topics for c in t.concepts
                }
                for mod in curr.modules:
                    temas = [conceptos.get(cid, cid) for cid in (mod.concepts or [])]
                    criterios = mod.validation_criteria or []
                    path.blocks.append(SeguimientoBlock(
                        block_id=f"blk_{mod.module_id}",
                        title=mod.name,
                        description=mod.objective or f"Practicar {mod.name}.",
                        learning_objective=mod.objective or "",
                        validation_check=criterios[0] if criterios else "Resolver el ejercicio del bloque sin ayuda.",
                        topics=temas or [mod.name],
                        type="practice",
                    ))

                try:
                    code_items = [
                        b for b in library
                        if b.get("category_id") in ("code", "notebooks") or b.get("ext") in ("py", "ipynb")
                    ]
                    sig3 = inspect.signature(self.ai.run_notebook_manager)
                    kw3 = {"model": model}
                    if "on_thinking" in sig3.parameters:
                        kw3["on_thinking"] = _thought
                    if "on_token" in sig3.parameters:
                        kw3["on_token"] = _token

                    exec_plan = ExecutableLearningPlan.model_validate(
                        self.ai.run_notebook_manager(curr.model_dump(), code_items, **kw3)
                    )
                    path.notebooks = self._materialize_notebooks(exec_plan, curr)
                    traces.append({
                        "agent": "Notebook Manager",
                        "summary": f"{len(path.notebooks)} cuadernos generados",
                        "warnings": PlanValidator.validate_executable_plan(exec_plan, curr),
                    })
                except Exception as err:
                    traces.append({
                        "agent": "Notebook Manager",
                        "summary": "No se generaron cuadernos",
                        "warnings": [str(err)],
                    })

                # Etapa 5: Guardado
                q.put({"type": "stage", "stage_num": 5, "total_stages": 5, "message": "Finalizando y guardando ruta profunda...", "pct": 95})
                path.decision_traces = traces
                self.repo.save(path)
                result_holder["path"] = path
            except Exception as e:
                result_holder["error"] = str(e)
            finally:
                q.put(sentinel)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        while True:
            try:
                event = q.get(timeout=0.1)
                if event is sentinel:
                    break
                yield event
            except queue.Empty:
                if not t.is_alive() and q.empty():
                    break

        if "error" in result_holder:
            yield {"type": "error", "message": result_holder["error"]}
        elif "path" in result_holder:
            yield {"type": "stage", "stage_num": 5, "total_stages": 5, "message": "¡Plan de aprendizaje profundo generado con éxito!", "pct": 100}
            yield {"type": "done", "path": result_holder["path"].model_dump()}

    def _materialize_notebooks(self, exec_plan, curr) -> List[Dict[str, Any]]:
        """ Escribe los cuadernos fuera de la biblioteca, nunca sobre los originales """
        destino = os.path.join(self.workspace_dir, "notebooks_plan")
        os.makedirs(destino, exist_ok=True)
        modulos = {m.module_id: m for m in curr.modules}
        creados = []

        for mod in exec_plan.modules_notebooks:
            base = modulos.get(mod.module_id)
            for nb in mod.notebooks:
                ruta = os.path.join(destino, f"{mod.module_id}_{nb.notebook_id}.ipynb")
                fuente = ""
                if nb.source_library_notebook and os.path.exists(nb.source_library_notebook):
                    try:
                        with open(nb.source_library_notebook, "r", encoding="utf-8", errors="ignore") as f:
                            fuente = f.read()
                    except OSError:
                        pass
                contenido = NotebookSafetyLayer.generate_explained_notebook_content(
                    module_name=base.name if base else mod.module_name,
                    objective=base.objective if base else "Practicar los conceptos del módulo",
                    validation_criteria=base.validation_criteria if base else [],
                    source_code=fuente,
                )
                try:
                    escrito = NotebookSafetyLayer.write_executable_notebook(ruta, contenido)
                    creados.append({
                        "block_id": f"blk_{mod.module_id}",
                        "title": nb.title or mod.module_name,
                        "path": escrito,
                    })
                except Exception as err:
                    print(f"Advertencia al generar cuaderno: {err}")
        return creados

    # ------------------------------------------------------------------
    # Migración de los planes antiguos
    # ------------------------------------------------------------------

    def migrate_legacy_plans(self) -> Dict[str, Any]:
        """ Convierte los planes de .prig_plans/ en rutas. Idempotente. """
        ya_migrados = {
            p.get("origin_plan_id")
            for p in self._raw_paths() if p.get("origin_plan_id")
        }

        migrados, fallidos = [], []
        for manifest in self.legacy_plans.list_plans():
            plan_id = manifest.get("plan_id")
            if not plan_id or plan_id in ya_migrados:
                continue
            try:
                estado = self.legacy_plans.load_state(plan_id)
                if estado:
                    ruta = self._plan_to_path(estado)
                    self.repo.save(ruta)
                    migrados.append({"plan_id": plan_id, "path_id": ruta.id, "goal": ruta.goal})
            except Exception as err:
                fallidos.append({"plan_id": plan_id, "error": str(err)})

        return {"migrated": migrados, "failed": fallidos,
                "already": len(ya_migrados), "total_paths": len(self.repo.list_all())}

    def _raw_paths(self) -> List[Dict[str, Any]]:
        datos = []
        if not os.path.isdir(self.repo.seg_dir):
            return datos
        for nombre in os.listdir(self.repo.seg_dir):
            if not nombre.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.repo.seg_dir, nombre), "r", encoding="utf-8") as f:
                    datos.append(json.load(f))
            except Exception:
                continue
        return datos

    def _plan_to_path(self, estado) -> SeguimientoPath:
        """ Un StudyPlanState pasa a ser una ruta, conservando su progreso """
        ruta = SeguimientoPath(
            goal=estado.user_goal,
            source="migrado",
            origin_plan_id=estado.plan_id,
            created_at=estado.created_at,
            rationale="Plan de estudio migrado al sistema de Aprendizaje Guiado.",
            knowledge_map=estado.knowledge_map.model_dump() if estado.knowledge_map else None,
        )

        completados = set(estado.completed_notebooks or [])
        criterios_hechos = estado.completed_validation_criteria or {}

        modulos = estado.practical_curriculum.modules if estado.practical_curriculum else []
        for mod in modulos:
            bid = f"blk_{mod.module_id}"
            criterios = mod.validation_criteria or []
            ruta.blocks.append(SeguimientoBlock(
                block_id=bid,
                title=mod.name,
                description=mod.objective or f"Practicar {mod.name}.",
                learning_objective=mod.objective or "",
                validation_check=criterios[0] if criterios else "Completar el módulo.",
                topics=list(mod.concepts or []) or [mod.name],
                type="practice",
            ))
            # Se daba por hecho si sus criterios estaban marcados o su cuaderno completado
            hechos = criterios_hechos.get(mod.module_id, [])
            if (criterios and len(hechos) >= len(criterios)) or bid in completados:
                ruta.completed_blocks.append(bid)
                ruta.completion_dates[bid] = estado.updated_at or estado.created_at

        if not ruta.blocks:
            # Plan sin currículo: al menos se conserva la meta y su trazabilidad
            ruta.blocks.append(SeguimientoBlock(
                block_id="blk_meta",
                title=estado.user_goal,
                description="Plan migrado sin módulos prácticos generados.",
                topics=[estado.user_goal],
                type="theory",
            ))
        return ruta

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def list_paths(self) -> List[Dict[str, Any]]:
        resumen = {p["id"]: p for p in self.repo.list_all()}
        for raw in self._raw_paths():
            if raw.get("id") in resumen:
                resumen[raw["id"]]["source"] = raw.get("source", "rapido")
                resumen[raw["id"]]["blocks_total"] = len(raw.get("blocks", []))
        return sorted(resumen.values(), key=lambda x: x.get("created_at", ""), reverse=True)

    def get(self, path_id: str) -> Optional[SeguimientoPath]:
        return self.repo.load(path_id)

    def delete(self, path_id: str) -> bool:
        return self.repo.delete(path_id)
