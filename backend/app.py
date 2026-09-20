import os
import re
import sys
import json
import queue
import signal
import threading
import subprocess
import zipfile
import requests as requests_lib
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from file_manager import FileManager
from runner import CodeRunner
from ai_engine import AIEngine
from ai_engine.ai_engine_class import explicar_error_motor
from book_service import BookService
from librerias_service import LibreriasService
from papers_service import PapersService
from knowledge_service import KnowledgeService
from knowledge_base import KnowledgeBase
from pack_importer import PackImporter, PackImportError
from knowledge_context import ContextAssembler
from contexto_modelo import CompiladorContexto
from indice_semantico import IndiceSemantico
from job_exporter import JobExporter
import agent_flows
from agent_flows import FlowEngine, FlowStore
import agent_flows_v2
from agent_flows_v2 import DynamicFlowEngine, plantillas_profesionales_sota, ROLES_V2
from perfil_libro import PerfilLibro
from explorador import Explorador
from sondeo_libro import SondeoLibro
from ide_servicios import ServiciosIDE, ErrorIDE
import ollama_opciones
from ollama_opciones import ErrorConfig
from ollama_gestion import GestorModelos, ErrorGestion
from herramientas_chat import Herramientas, ETIQUETAS as ETIQUETAS_HERRAMIENTAS
import buscador_modelos
from buscador_modelos import ErrorBuscador
from descargas_modelos import Descargas
from recursos.gestor import gestor as _gestor_recursos
from recursos import calculadora as recursos_calc, ficha as recursos_ficha
from recursos import calibracion as recursos_cal, servidor as recursos_srv
from recursos.almacen import almacen as recursos_almacen
from recursos import termico as recursos_termico
from recursos.perfiles import PERFILES as RECURSOS_PERFILES, TIRADORES as RECURSOS_TIRADORES
from exercise_engine import ExerciseEngine
from feature_flags import FeatureFlags
from learning_telemetry import LearningTelemetry
from exercise_store import ExerciseStore
from guided_learning import GuidedLearningService
from pdf_exporter import PDFExporter
from study_plan_engine import (
    StudyPlanEngine, NotebookSafetyLayer, PlanValidator, KnowledgeMap, PracticalCurriculum,
    ExecutableLearningPlan, ChangeRequest, ActionEnum, PlanStatusEnum, DecisionTrace, TraceStep,
    SeguimientoPath, SeguimientoRepository
)
import kaggle_lector
import kaggle_explorar
import kaggle_colecciones
import kaggle_pdf
import inicio
import github_lector
from datetime import datetime

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    yield
    cleanup_all_processes()

app = FastAPI(title="Prig IDE Backend API", lifespan=lifespan)

# El frontend se sirve desde este mismo origen, por lo que no hace falta abrir CORS
# a "*": hacerlo permitiría que cualquier web visitada por el usuario leyera y
# escribiera sus archivos a través de la API local.
LOCAL_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("127.0.0.1", "localhost")
    for port in ("8000", "8080")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from learner_dataset import LearnerDatasetManager

file_mgr = FileManager()
runner = CodeRunner()
ai_engine = AIEngine()
# El gobernador térmico (límite de temperatura y modo suave) se aplica a TODA generación
# local, no solo a los flujos y al chat: Desafíos, Kaggle, GitHub y el profesor también
ai_engine.gobernador = recursos_termico.gobernador()
book_service = BookService()
librerias_service = LibreriasService(book_service.books_dir)
papers_service = PapersService()
# Único punto de indexación y consulta del conocimiento. Comparte carpeta con
# book_service: los mismos archivos, pero fragmentados y buscables.
knowledge_service = KnowledgeService(book_service.books_dir)

# Todos los repositorios cuelgan del workspace activo. Antes StudyPlanEngine usaba
# os.getcwd() mientras el resto usaba file_mgr.base_dir, así que los planes se
# escribían en una carpeta y el perfil los leía de otra.
study_plan_engine = StudyPlanEngine(file_mgr.base_dir)
seguimiento_repo = SeguimientoRepository(file_mgr.base_dir)
dataset_mgr = LearnerDatasetManager(file_mgr.base_dir)


knowledge_base = KnowledgeBase()
pack_importer = PackImporter(knowledge_base)
compilador_contexto = CompiladorContexto(knowledge_base)
context_assembler = ContextAssembler(knowledge_base, compilador_contexto)
indice_semantico = IndiceSemantico(knowledge_base)
job_exporter = JobExporter(book_service.books_dir)
flow_store = FlowStore(file_mgr.base_dir)
perfil_libro = PerfilLibro(knowledge_base)
explorador = Explorador(file_mgr.base_dir)
from explorador import EXTENSIONES as explorador_extensiones
sondeo = SondeoLibro(ai_engine)
exercise_engine = ExerciseEngine(ai_engine, runner)
flags = FeatureFlags()
telemetry = LearningTelemetry(file_mgr.base_dir)
exercise_store = ExerciseStore(file_mgr.base_dir)

# Aprendizaje Guiado: sistema único de rutas. Sustituye a Recorrido y Seguimiento,
# que hacían casi lo mismo con dos modelos, dos interfaces y dos almacenes.
guided = GuidedLearningService(file_mgr.base_dir, ai_engine, book_service)

_tracked_child_processes: List[subprocess.Popen] = []
_tracked_lock = threading.Lock()
_active_flow_engine: Optional[FlowEngine] = None

def cleanup_all_processes() -> None:
    """ Detiene de forma garantizada todos los análisis en curso y procesos hijos del programa """
    # 1. Apagar análisis de IA activos en Ollama (libera sockets y cómputo GPU de inmediato)
    try:
        ai_engine.cancel_active_requests()
    except Exception:
        pass
    # …y soltar de la GPU los modelos que cargó Prig: si no, siguen ocupándola (y con la
    # ventana ya cerrada) hasta que vence su keep_alive
    try:
        ai_engine.unload_models()
    except Exception:
        pass

    # 2. Apagar flujos de agentes en curso
    global _active_flow_engine
    if _active_flow_engine is not None:
        try:
            _active_flow_engine.detener()
        except Exception:
            pass

    # 3. Detener indexación en segundo plano
    try:
        knowledge_service.stop()
    except Exception:
        pass

    # 4. Detener ejecuciones de scripts activos y sesiones de kernel
    try:
        runner.shutdown()
    except Exception:
        pass

    # 5. Terminar subprocesos hijos registrados (ventanas independientes, etc.)
    with _tracked_lock:
        procs = list(_tracked_child_processes)
        _tracked_child_processes.clear()
    for p in procs:
        try:
            if p.poll() is None:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    p.kill()
        except Exception:
            pass

    # 6. Red de seguridad con psutil: terminar cualquier subproceso huérfano descendiente
    try:
        import psutil
        current_proc = psutil.Process()
        children = current_proc.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        gone, alive = psutil.wait_procs(children, timeout=1.5)
        for child in alive:
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass

def rebind_workspace(new_base_dir: str) -> None:
    """ Reapunta los repositorios al workspace recién abierto.

    Sin esto los objetos quedaban congelados en la carpeta que había al arrancar,
    de modo que los planes y seguimientos nuevos seguían guardándose en la antigua.
    """
    global study_plan_engine, seguimiento_repo, dataset_mgr, telemetry, exercise_store, guided
    study_plan_engine = StudyPlanEngine(new_base_dir)
    seguimiento_repo = SeguimientoRepository(new_base_dir)
    dataset_mgr = LearnerDatasetManager(new_base_dir)
    telemetry = LearningTelemetry(new_base_dir)
    exercise_store = ExerciseStore(new_base_dir)
    guided = GuidedLearningService(new_base_dir, ai_engine, book_service)


frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

class OpenFolderRequest(BaseModel):
    path: str

class FileWriteRequest(BaseModel):
    path: str
    content: str

class FileCreateRequest(BaseModel):
    path: str
    is_dir: bool = False

class CodeRunRequest(BaseModel):
    path: str
    run_id: Optional[str] = None

class RunCancelRequest(BaseModel):
    run_id: str

class CellRunRequest(BaseModel):
    code: str
    path: Optional[str] = None

class SessionResetRequest(BaseModel):
    path: Optional[str] = None

class AIChatRequest(BaseModel):
    prompt: str
    model: str = "qwen2.5-coder:7b"
    mode: str = "chat"
    code_context: Optional[str] = None
    hooked_files: Optional[List[Dict[str, str]]] = None  # [{"path": "...", "content": "..."}]
    selected_citations: Optional[List[Dict[str, Any]]] = None  # Citas de libros o librerías seleccionadas para razonar
    use_web: bool = False
    # Modo por eventos (NDJSON): razonamiento, métricas, confianza y herramientas
    eventos: bool = False
    think: Optional[bool] = None
    logprobs: int = 0
    herramientas: bool = False
    permitir_codigo: bool = False
    continuar: Optional[str] = None      # respuesta cortada que el modelo debe seguir

class AIInlinePromptRequest(BaseModel):
    prompt: str
    file_path: Optional[str] = None
    file_content: Optional[str] = None
    prefix_code: Optional[str] = None
    suffix_code: Optional[str] = None
    line_number: Optional[int] = 1
    language: str = "python"
    model: Optional[str] = None

class AISearchRequest(BaseModel):
    query: str

class ModelPullRequest(BaseModel):
    model: str = "qwen2.5-coder:7b"

class WorkflowStep(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = "Agente"
    model: str = "qwen2.5-coder:7b"
    role: str = "programmer"
    prompt: str = ""
    temperature: Optional[float] = 0.3
    system_prompt: Optional[str] = ""
    tipo: Optional[str] = "agent"
    loop: Optional[Dict[str, Any]] = None
    routing_rules: Optional[List[Dict[str, Any]]] = None
    herramienta: Optional[str] = None
    next_node: Optional[str] = None

class WorkflowRequest(BaseModel):
    initial_input: str
    steps: Optional[List[WorkflowStep]] = []
    nodos: Optional[List[Dict[str, Any]]] = None
    grafo: Optional[Dict[str, Any]] = None

class BookSnippetRequest(BaseModel):
    book_id: str
    page: int = 1
    box: Optional[Dict[str, Any]] = None
    text: Optional[str] = ""
    label: Optional[str] = ""

class BookAnalyzeRequest(BaseModel):
    book_id: str
    path: Optional[str] = None
    model: str = "qwen2.5-coder:7b"

class BookImportRequest(BaseModel):
    path: str
    category: Optional[str] = None

@app.get("/api/books/list")
def list_books(category: Optional[str] = Query(default=None)):
    items = book_service.list_books(category)

    # Marcar qué elementos están realmente indexados: sin esto el usuario no
    # distingue entre "está en la carpeta" y "el tutor puede consultarlo".
    try:
        indexed_paths = knowledge_service.get_indexed_paths()
        for item in items:
            item["indexed"] = os.path.abspath(item.get("path", "")) in indexed_paths
    except Exception:
        for item in items:
            item["indexed"] = None

    return items

@app.get("/api/books/read")
def read_book(id: str = Query(...)):
    return book_service.get_book_content(id)

@app.post("/api/books/analyze")
def analyze_book(req: BookAnalyzeRequest):
    target = req.path or req.book_id
    return book_service.analyze_document(target, ai_engine, req.model)

@app.post("/api/books/import")
def import_book(req: BookImportRequest):
    res = book_service.import_file(req.path, req.category)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])

    # Importar e indexar son el mismo acto: si se separan, la biblioteca y el
    # catálogo se desincronizan y el tutor deja de "ver" lo que el usuario añadió.
    try:
        ingest = knowledge_service.index_single(res["path"], res.get("category", "book").lower())
        res["indexed"] = ingest.get("status") in ("INGESTED", "ALREADY_EXISTS")
        res["chunks_count"] = ingest.get("chunks_count", 0)
    except Exception as err:
        res["indexed"] = False
        res["index_error"] = str(err)

    return res


class BookDeleteRequest(BaseModel):
    id: str

@app.post("/api/books/delete")
def delete_book(req: BookDeleteRequest):
    """ Elimina un elemento de la biblioteca y lo retira del catálogo de conocimiento """
    target = book_service._resolve_item(req.id)

    res = book_service.delete_item(req.id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])

    # Si no se retira también del catálogo, el tutor seguiría citando un libro
    # que ya no existe en disco.
    try:
        res["removed_from_index"] = knowledge_service.remove_by_path(target) if target else False
    except Exception as err:
        res["removed_from_index"] = False
        res["index_error"] = str(err)

    return res


@app.get("/api/books/metadata")
def get_book_metadata_by_query(id: str = Query(...)):
    """ Variante con parámetro de consulta: admite rutas relativas con '/', que como
    parámetro de ruta no encajarían en el enrutador. """
    meta = book_service.get_metadata(id)
    if not meta:
        raise HTTPException(status_code=404, detail="Metadatos de IA no encontrados")
    return meta

@app.get("/api/books/metadata/{book_id}")
def get_book_metadata(book_id: str):
    meta = book_service.get_metadata(book_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Metadatos de IA no encontrados")
    return meta

@app.post("/api/books/snippet")
def save_book_snippet(req: BookSnippetRequest):
    return book_service.save_snippet(req.book_id, req.page, req.box or {}, req.text or "", req.label or "")

@app.get("/api/books/snippets")
def list_snippets():
    return book_service.load_snippets()

@app.get("/api/books/snippet/{snippet_id}")
def get_snippet(snippet_id: str):
    return book_service.get_snippet(snippet_id)

# =========================================================================
# LECTOR DE TEXTO PDF Y CITAS (nombre_libro.json)
# =========================================================================

class BookPageEditRequest(BaseModel):
    book_id: str
    page: int
    text: str

class BookCitationSaveRequest(BaseModel):
    book_id: str
    citation: Dict[str, Any]

class BookCitationDeleteRequest(BaseModel):
    book_id: str
    citation_id: str

class BookCitationExportRequest(BaseModel):
    book_id: str
    workspace_path: Optional[str] = None

@app.get("/api/books/pdf-pages")
def get_book_pdf_pages(id: str = Query(...), page: int = Query(default=1), search: Optional[str] = Query(default=None)):
    res = book_service.get_pdf_pages(id, page=page, search_query=search)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/books/pdf-page-save")
def save_book_pdf_page_edit(req: BookPageEditRequest):
    res = book_service.save_pdf_page_edit(req.book_id, req.page, req.text)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.get("/api/books/citations")
def get_book_citations(id: str = Query(...)):
    return book_service.get_book_citations(id)

@app.post("/api/books/citations/save")
def save_book_citation(req: BookCitationSaveRequest):
    res = book_service.save_book_citation(req.book_id, req.citation)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/books/citations/delete")
def delete_book_citation(req: BookCitationDeleteRequest):
    res = book_service.delete_book_citation(req.book_id, req.citation_id)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/books/citations/export")
def export_book_citations(req: BookCitationExportRequest):
    ws_path = req.workspace_path or file_mgr.base_dir
    res = book_service.export_citations_to_workspace(req.book_id, ws_path)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.get("/api/books/all-citations")
def get_all_book_citations(query: Optional[str] = Query(default=None)):
    return book_service.get_all_citations_for_ai(query=query)

# =========================================================================
# ANALISTA DE LIBRERÍAS Y CITAS TÉCNICAS (libreria.json)
# =========================================================================

class LibraryAddRequest(BaseModel):
    repo: str
    name: Optional[str] = None
    desc: Optional[str] = None

class LibraryCitationSaveRequest(BaseModel):
    lib_id: str
    citation: Dict[str, Any]

class LibraryCitationDeleteRequest(BaseModel):
    lib_id: str
    citation_id: str

class LibraryCitationExportRequest(BaseModel):
    lib_id: str
    workspace_path: Optional[str] = None

class LibraryAnalyzeRequest(BaseModel):
    lib_id: str
    topic: str
    model: Optional[str] = "qwen2.5-coder:7b"

@app.get("/api/librerias/list")
def list_libraries():
    return librerias_service.list_libraries()

@app.post("/api/librerias/add")
def add_library(req: LibraryAddRequest):
    res = librerias_service.add_library(req.repo, req.name, req.desc)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.get("/api/librerias/citations")
def get_library_citations(id: str = Query(...)):
    return librerias_service.get_library_citations(id)

@app.post("/api/librerias/citations/save")
def save_library_citation(req: LibraryCitationSaveRequest):
    res = librerias_service.save_library_citation(req.lib_id, req.citation)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/librerias/citations/delete")
def delete_library_citation(req: LibraryCitationDeleteRequest):
    res = librerias_service.delete_library_citation(req.lib_id, req.citation_id)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/librerias/citations/export")
def export_library_citations(req: LibraryCitationExportRequest):
    ws_path = req.workspace_path or file_mgr.base_dir
    res = librerias_service.export_library_citations(req.lib_id, ws_path)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/librerias/analyze")
def analyze_library(req: LibraryAnalyzeRequest):
    model = req.model or "qwen2.5-coder:7b"
    res = librerias_service.analyze_library_topic(req.lib_id, req.topic, ai_engine, model=model)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.get("/api/librerias/all-citations")
def get_all_library_citations(query: Optional[str] = Query(default=None)):
    return librerias_service.get_all_library_citations_for_ai(query=query)


# ==========================================
# ENDPOINTS: PAPERS Y ALGORITMOS SEMINALES ML
# ==========================================

class PaperDownloadRequest(BaseModel):
    paper_id: str
    tipo: Optional[str] = "analisis"
    workspace_path: Optional[str] = None

class PaperAskRequest(BaseModel):
    paper_id: str
    pregunta: str
    modelo: Optional[str] = None
    tipo: Optional[str] = "analisis"
    historial: Optional[List[Dict[str, Any]]] = None

@app.get("/api/papers/list")
def list_papers(q: Optional[str] = Query(default=None), categoria: Optional[str] = Query(default=None)):
    return {"papers": papers_service.list_papers(q=q, categoria=categoria), "total": len(papers_service.catalogo)}

@app.get("/api/papers/detail")
def get_paper_detail(id: str = Query(...), tipo: str = Query(default="analisis")):
    res = papers_service.get_paper(id, tipo=tipo)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res

@app.post("/api/papers/download")
def download_paper(req: PaperDownloadRequest):
    ws_path = req.workspace_path or file_mgr.base_dir
    res = papers_service.download_paper(req.paper_id, ws_path, tipo=req.tipo or "analisis")
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/papers/ask")
def ask_paper(req: PaperAskRequest):
    modelo = req.modelo or ai_engine.config.get("agent1_model", "qwen2.5-coder:7b")
    return StreamingResponse(
        papers_service.ask_paper_stream(
            paper_id=req.paper_id,
            pregunta=req.pregunta,
            ai_engine=ai_engine,
            modelo=modelo,
            tipo=req.tipo or "analisis",
            historial=req.historial
        ),
        media_type="text/plain; charset=utf-8"
    )



# ==========================================
# ENDPOINTS: APRENDIZAJE GUIADO (rutas unificadas)
# ==========================================

class GuidedGenerateRequest(BaseModel):
    goal: str
    topics: str = ""
    level: str = "Intermedio"
    focus: str = "Práctico"
    mode: str = "rapido"          # rapido | profundo
    model: str = "qwen2.5-coder:7b"

class GuidedProgressRequest(BaseModel):
    completed_blocks: List[str]

@app.get("/api/guided/list")
def guided_list():
    return {"paths": guided.list_paths()}

@app.post("/api/guided/generate")
def guided_generate(req: GuidedGenerateRequest):
    """ Una sola puerta de entrada; la diferencia es la profundidad del análisis """
    try:
        if req.mode == "profundo":
            path = guided.generate_deep(req.goal, req.topics, level=req.level,
                                        focus=req.focus, model=req.model)
        else:
            if not req.topics.strip():
                raise HTTPException(status_code=400,
                                    detail="El modo rápido necesita una lista de temas.")
            path = guided.generate_fast(req.goal, req.topics, level=req.level,
                                        focus=req.focus, model=req.model)
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"No se pudo generar la ruta: {err}")
    return path.model_dump()

@app.post("/api/guided/generate/stream")
def guided_generate_stream(req: GuidedGenerateRequest):
    """ Emite en tiempo real las etapas, pensamientos del modelo y el resultado final en formato NDJSON """
    def emit():
        try:
            if req.mode == "profundo":
                gen = guided.generate_deep_stream(req.goal, req.topics, level=req.level,
                                                   focus=req.focus, model=req.model)
            else:
                if not req.topics.strip():
                    yield json.dumps({"type": "error", "message": "El modo rápido necesita una lista de temas."}, ensure_ascii=False) + "\n"
                    return
                gen = guided.generate_fast_stream(req.goal, req.topics, level=req.level,
                                                   focus=req.focus, model=req.model)
            for event in gen:
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as err:
            yield json.dumps({"type": "error", "message": str(err)}, ensure_ascii=False) + "\n"

    return StreamingResponse(emit(), media_type="application/x-ndjson")

@app.post("/api/guided/cancel")
@app.post("/api/ai/cancel")
def cancel_guided_generation():
    """ Detiene de inmediato la generación activa en Ollama liberando sockets y cómputo GPU/CPU """
    count = ai_engine.cancel_active_requests() + gemini_motor.cancelar_todo()
    return {"status": "cancelled", "active_requests_cancelled": count}

@app.post("/api/guided/migrate")
def guided_migrate():
    """ Trae los planes de estudio antiguos al sistema unificado. Idempotente. """
    return guided.migrate_legacy_plans()

@app.get("/api/guided/{path_id}")
def guided_get(path_id: str):
    path = guided.get(path_id)
    if not path:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    return path.model_dump()

@app.delete("/api/guided/{path_id}")
def guided_delete(path_id: str):
    if not guided.delete(path_id):
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    return {"status": "deleted", "id": path_id}

@app.post("/api/guided/{path_id}/progress")
def guided_progress(path_id: str, req: GuidedProgressRequest):
    path = guided.get(path_id)
    if not path:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")

    ahora = datetime.now().isoformat()
    nuevos = set(req.completed_blocks) - set(path.completed_blocks)
    for bid in nuevos:
        path.completion_dates[bid] = ahora
    for bid in set(path.completed_blocks) - set(req.completed_blocks):
        path.completion_dates.pop(bid, None)

    path.completed_blocks = req.completed_blocks
    guided.repo.save(path)
    dataset_mgr.build_and_save_dataset()
    return path.model_dump()


# ==========================================
# ENDPOINTS: BANDERAS, MÉTRICAS DE APRENDIZAJE Y SALUD DEL ENTORNO
# ==========================================

class FlagUpdateRequest(BaseModel):
    name: str
    enabled: Optional[bool] = None   # None = volver al valor por defecto

@app.get("/api/flags")
def get_flags():
    return flags.all()

@app.post("/api/flags")
def set_flag(req: FlagUpdateRequest):
    try:
        value = flags.reset(req.name) if req.enabled is None else flags.set(req.name, req.enabled)
    except KeyError as err:
        raise HTTPException(status_code=404, detail=str(err))
    return {"name": req.name, "enabled": value, "flags": flags.all()}

@app.get("/api/learning/metrics")
def learning_metrics(days: int = Query(default=30, ge=1, le=365)):
    """ Métricas de competencia real, derivadas de ejecutar el código del alumno """
    return telemetry.metrics(days=days)

@app.get("/api/system/health")
def system_health():
    """ ¿Puede este equipo con el modelo elegido? Hoy el usuario lo descubre
    esperando cinco minutos a que algo no responda. """
    stats = get_system_stats()
    gpu = stats.get("gpu", {})
    vram_total = gpu.get("vram_total_mb", 0)
    vram_free = max(0, vram_total - gpu.get("vram_used_mb", 0))

    detail = ai_engine.get_detailed_models()
    models = detail.get("models", []) if detail.get("online") else []

    active = ai_engine.config.get("agent1_model")
    evaluados = []
    for m in models:
        # Regla práctica: un modelo necesita algo más de VRAM que su tamaño en disco
        needed_mb = int(m.get("size_gb", 0) * 1024 * 1.2)
        evaluados.append({
            "name": m.get("name"),
            "size_gb": m.get("size_gb"),
            "estimated_vram_mb": needed_mb,
            "fits_in_gpu": bool(vram_total) and needed_mb <= vram_total,
            "fits_now": bool(vram_free) and needed_mb <= vram_free,
            "is_active": m.get("name") == active,
        })

    warnings: List[str] = []
    if not detail.get("online"):
        warnings.append("Ollama no responde: el tutor y los ejercicios no funcionarán.")
    if not gpu.get("has_gpu"):
        warnings.append("Sin GPU detectada: la inferencia irá por CPU y será notablemente más lenta.")
    activo = next((m for m in evaluados if m["is_active"]), None)
    if activo and not activo["fits_in_gpu"]:
        warnings.append(
            f"El modelo activo ({activo['name']}) necesita ~{activo['estimated_vram_mb']} MB "
            f"y la GPU tiene {vram_total} MB: se descargará parcialmente a RAM."
        )

    return {
        "ollama_online": detail.get("online", False),
        "cpu_pct": stats.get("cpu_pct"),
        "ram_total_gb": stats.get("ram_total_gb"),
        "gpu": gpu,
        "vram_free_mb": vram_free,
        "active_model": active,
        "models": sorted(evaluados, key=lambda m: not m["fits_now"]),
        "warnings": warnings,
    }


# ==========================================
# ENDPOINTS: EJERCICIOS VERIFICABLES POR EJECUCIÓN
# ==========================================

class ExerciseGenerateRequest(BaseModel):
    concept: str
    model: str = "qwen2.5-coder:7b"
    level: str = "intermedio"
    attempts: int = 3

class ExerciseSubmitRequest(BaseModel):
    exercise_id: str
    code: str
    hints_used: int = 0

@app.post("/api/exercise/generate")
def generate_exercise(req: ExerciseGenerateRequest):
    """ Devuelve un ejercicio YA VERIFICADO: su solución de referencia pasa sus
    propios tests y esos tests fallan con el código de partida. """
    result = exercise_engine.generate_validated(
        req.concept, model=req.model, level=req.level, attempts=max(1, min(req.attempts, 5))
    )
    if not result["ok"]:
        raise HTTPException(
            status_code=422,
            detail=f"No se pudo generar un ejercicio verificable sobre '{req.concept}'. "
                   f"Prueba otro modelo o reformula el concepto."
        )

    exercise = result["exercise"]
    exercise_store.save(exercise)

    if flags.is_enabled("learning_telemetry"):
        telemetry.record(exercise["exercise_id"], req.concept, "generated",
                         attempt_num=exercise.get("attempts_used", 1))

    public = ExerciseEngine.public_view(exercise)
    public["generation_history"] = result["history"]
    return public

@app.post("/api/exercise/submit")
def submit_exercise(req: ExerciseSubmitRequest):
    """ Corrige la entrega ejecutándola contra los tests ocultos """
    exercise = exercise_store.get(req.exercise_id)
    if not exercise:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado. Genera uno nuevo.")

    result = exercise_engine.grade_submission(exercise, req.code)

    if flags.is_enabled("learning_telemetry"):
        attempt = telemetry.attempt_number(req.exercise_id)
        telemetry.record(
            req.exercise_id, exercise.get("concept", ""), "submission",
            passed=result["passed"], attempt_num=attempt,
            hints_used=req.hints_used, stderr=result.get("stderr", ""),
            elapsed=result.get("elapsed", 0),
        )
        result["attempt"] = attempt

    return result

@app.get("/api/exercise/recent")
def list_recent_exercises(limit: int = Query(default=20, ge=1, le=100),
                          concept: Optional[str] = Query(default=None)):
    """ Ejercicios guardados, para poder retomar uno a medias tras reiniciar """
    return {"exercises": exercise_store.list_recent(limit=limit, concept=concept),
            "total": exercise_store.count()}

@app.get("/api/exercise/{exercise_id}")
def get_exercise(exercise_id: str):
    exercise = exercise_store.get(exercise_id)
    if not exercise:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado.")
    return ExerciseEngine.public_view(exercise)

class ExerciseHintRequest(BaseModel):
    level: int = 1
    model: str = "qwen2.5-coder:7b"

@app.post("/api/exercise/{exercise_id}/hint")
def exercise_hint(exercise_id: str, req: ExerciseHintRequest):
    """ Pista graduada: conceptual, de estructura o concreta """
    exercise = exercise_store.get(exercise_id)
    if not exercise:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado.")
    return exercise_engine.hint(exercise, level=req.level, model=req.model)

@app.get("/api/exercise/{exercise_id}/solution")
def reveal_solution(exercise_id: str):
    """ Solución de referencia, solo cuando el alumno la pide explícitamente """
    exercise = exercise_store.get(exercise_id)
    if not exercise:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado.")

    # Pedir la solución es un dato pedagógico: significa que el alumno se rindió
    if flags.is_enabled("learning_telemetry"):
        telemetry.record(exercise_id, exercise.get("concept", ""), "solution_revealed")

    return {
        "exercise_id": exercise_id,
        "reference_solution": exercise["reference_solution"],
        "tests": exercise["tests"],
    }


# ==========================================
# ENDPOINTS: MOTOR DE CONOCIMIENTO (RAG SOBRE LA BIBLIOTECA)
# ==========================================

class KnowledgeIndexRequest(BaseModel):
    force: bool = False

class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 8
    expand: bool = True
    model: str = "qwen2.5-coder:7b"
    max_context_tokens: Optional[int] = None

class KnowledgeAskRequest(BaseModel):
    query: str
    model: str = "qwen2.5-coder:7b"
    top_k: int = 6
    expand: bool = True
    max_context_tokens: Optional[int] = None

@app.get("/api/knowledge/status")
def knowledge_status():
    return knowledge_service.get_status()

@app.post("/api/knowledge/index")
def knowledge_index(req: KnowledgeIndexRequest):
    """ Indexa la biblioteca en segundo plano; el progreso se lee en /status """
    return knowledge_service.index_library_async(force=req.force)

def _context_budget(requested: Optional[int] = None) -> int:
    """ Presupuesto de evidencias en función de la ventana configurada.

    Estaba fijo en 1800 tokens: con num_ctx=2048 desbordaba y con 32768 desperdiciaba
    casi toda la ventana. Se reserva ~45% para las evidencias y el resto para el
    prompt de sistema, la pregunta y la respuesta.
    """
    try:
        num_ctx = int(ai_engine.config.get("num_ctx", 4096))
    except (TypeError, ValueError):
        num_ctx = 4096
    budget = max(400, int(num_ctx * 0.45))
    return min(requested, budget) if requested else budget


def _expanded(query: str, expand: bool, model: str) -> List[str]:
    if not expand or not flags.is_enabled("query_expansion"):
        return []
    try:
        return ai_engine.expand_query(query, model=model)
    except Exception:
        return []

@app.post("/api/knowledge/search")
def knowledge_search(req: KnowledgeSearchRequest):
    """ Recuperación pura, sin modelo: rápida y verificable de un vistazo """
    return knowledge_service.search(
        req.query,
        top_k=req.top_k,
        max_context_tokens=_context_budget(req.max_context_tokens),
        expansions=_expanded(req.query, req.expand, req.model)
    )

def _contexto_destilado(pregunta: str, presupuesto: int) -> Optional[Dict[str, Any]]:
    """ Contexto a partir de afirmaciones verificadas, si la base lo tiene.

    Es mejor material que los fragmentos crudos: ya está clasificado por tipo, ya
    trae la cita comprobada contra el texto original y ya reúne lo que dicen varios
    libros del mismo concepto. Cuando la base no conoce el tema, se devuelve None y
    se recae en la recuperación por fragmentos, que siempre encuentra algo.
    """
    try:
        if not knowledge_base.estadisticas().get("libros"):
            return None
        ctx = context_assembler.ensamblar(pregunta, presupuesto_tokens=presupuesto)
        return None if ctx.get("vacio") else ctx
    except Exception:
        return None


@app.post("/api/knowledge/ask")
def knowledge_ask(req: KnowledgeAskRequest):
    """ Respuesta del tutor fundamentada en la biblioteca, con citas """
    presupuesto = _context_budget(req.max_context_tokens)
    destilado = _contexto_destilado(req.query, presupuesto)

    result = knowledge_service.search(
        req.query,
        top_k=req.top_k,
        # Si hay contexto destilado se deja sitio para él: los fragmentos pasan a
        # ser complemento, no la fuente principal.
        max_context_tokens=(presupuesto // 3 if destilado else presupuesto),
        expansions=_expanded(req.query, req.expand, req.model)
    )

    if destilado:
        contexto = (destilado["texto"] + "\n\n--- FRAGMENTOS ADICIONALES ---\n"
                    + result["context_prompt"]) if result["found"] else destilado["texto"]
    else:
        contexto = result["context_prompt"]

    def event_stream():
        # Las fuentes van primero para que la interfaz pueda pintarlas mientras
        # el modelo todavía está redactando.
        yield json.dumps({
            "type": "sources",
            "found": result["found"] or bool(destilado),
            "evidence": result.get("evidence"),
            "verificado": bool(destilado),
            "conceptos": destilado["conceptos"] if destilado else [],
            "citas": destilado["fuentes"] if destilado else [],
            "chunks": [
                {
                    "n": i + 1,
                    "chunk_id": c["chunk_id"],
                    "source_id": c["source_id"],
                    "source_title": c.get("source_title", c["source_id"]),
                    "page": c["page"],
                    "content_type": c["content_type"],
                    "preview": c["content"][:220],
                }
                for i, c in enumerate(result["chunks"])
            ],
            "stats": result["stats"],
        }, ensure_ascii=False) + "\n"

        for chunk in ai_engine.answer_from_library(
            req.query, contexto, model=req.model
        ):
            yield json.dumps({"type": "token", "text": chunk}, ensure_ascii=False) + "\n"

        yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

# ======================================================================
# Base de conocimiento: paquetes extraídos de libros completos
# ======================================================================

PACKS_DIR = os.path.join(os.path.expanduser("~/.prig_books"), "packs")


class PackImportRequest(BaseModel):
    ruta: Optional[str] = None      # un .prigpack concreto; si falta, toda la carpeta
    forzar: bool = False


class ContextRequest(BaseModel):
    pregunta: str
    presupuesto_tokens: Optional[int] = None
    dominio: Optional[str] = None
    nivel: str = "intermedio"


@app.get("/api/kb/status")
def kb_status():
    """ Lo que hay en la base y si está listo para consultarse """
    os.makedirs(PACKS_DIR, exist_ok=True)
    disponibles = [f for f in sorted(os.listdir(PACKS_DIR)) if f.endswith(".prigpack")]
    try:
        stats = knowledge_base.estadisticas()
    except Exception as e:
        return {"disponible": False, "error": str(e), "packs_en_carpeta": disponibles}
    with knowledge_base.conectar() as c:
        dentro = {r[0] for r in c.execute("SELECT source_id FROM books;")}
    return {
        "disponible": bool(stats.get("libros")),
        "carpeta_packs": PACKS_DIR,
        "packs_en_carpeta": disponibles,
        "sin_importar": [f for f in disponibles
                         if not _pack_ya_importado(os.path.join(PACKS_DIR, f), dentro)],
        **stats,
    }


def _pack_ya_importado(ruta: str, dentro: Optional[set] = None) -> bool:
    """ Un paquete ya está dentro si su libro figura en la base.

    Solo se lee el manifiesto. Verificar el paquete entero aquí obligaría a
    descomprimir y resumir con sha256 cada archivo de cada paquete: con cien
    libros eso convierte una consulta de estado en varios segundos de disco.
    """
    try:
        with zipfile.ZipFile(ruta) as z:
            source_id = json.loads(z.read("manifest.json")).get("source_id")
    except Exception:
        return False
    if not source_id:
        return False
    if dentro is not None:
        return source_id in dentro
    with knowledge_base.conectar() as c:
        return c.execute("SELECT 1 FROM books WHERE source_id = ?;",
                         (source_id,)).fetchone() is not None


@app.post("/api/kb/verify")
def kb_verify_pack(req: PackImportRequest):
    """ Revisa un paquete sin tocar la base """
    ruta = req.ruta or ""
    if not os.path.isabs(ruta):
        ruta = os.path.join(PACKS_DIR, os.path.basename(ruta))
    if not os.path.isfile(ruta):
        raise HTTPException(status_code=404, detail=f"No existe el paquete: {ruta}")
    try:
        return pack_importer.verificar(ruta)
    except PackImportError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/kb/import")
def kb_import(req: PackImportRequest):
    """ Importa, unifica conceptos, precomputa dosieres y verifica.

    Es una sola operación a propósito: un paquete importado sin unificar deja
    afirmaciones sin concepto canónico, y eso no da error — simplemente el tutor
    deja de encontrarlas.
    """
    os.makedirs(PACKS_DIR, exist_ok=True)
    try:
        if req.ruta:
            ruta = req.ruta if os.path.isabs(req.ruta) else os.path.join(
                PACKS_DIR, os.path.basename(req.ruta))
            if not os.path.isfile(ruta):
                raise HTTPException(status_code=404, detail=f"No existe: {ruta}")
            importacion = {"importados": [pack_importer.importar(ruta, forzar=req.forzar)],
                           "fallidos": [], "total": 1}
        else:
            importacion = pack_importer.importar_carpeta(PACKS_DIR)
        unificacion = pack_importer.unificar()
        dosieres = pack_importer.construir_dosieres()
        # Compilar el contexto denso aquí y no al responder: al importar sobra
        # tiempo, y al responder es cuando menos margen hay.
        compilacion = compilador_contexto.precompilar()
        # El índice semántico es lo que evita servirle al modelo conceptos que no
        # vienen a cuento. Si el embebedor no está descargado, se omite sin ruido:
        # todo sigue funcionando con la búsqueda por palabras.
        indexado = indice_semantico.indexar(compilador_contexto)
        verificacion = pack_importer.verificar_integridad()
    except PackImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"importacion": importacion, "unificacion": unificacion,
            "dosieres": dosieres, "compilacion": compilacion,
            "indice_semantico": indexado, "verificacion": verificacion}


@app.get("/api/kb/books")
def kb_books():
    """ Informe libro a libro: qué se guardó de cada uno y si quedó completo """
    return pack_importer.verificar_integridad()


@app.get("/api/kb/concept")
def kb_concept(nombre: str = Query(...)):
    """ El dosier completo de un concepto, por cualquiera de sus nombres """
    concepto = knowledge_base.resolver(nombre)
    if not concepto:
        raise HTTPException(status_code=404,
                            detail=f"'{nombre}' no aparece en la biblioteca")
    dosier = context_assembler.dosier(concepto["concept_id"])
    return {"concepto": concepto, "dosier": dosier,
            "prerrequisitos": knowledge_base.prerrequisitos(concepto["concept_id"])}


@app.post("/api/kb/compilar")
def kb_compilar():
    """ Recompila el contexto denso de todos los conceptos.

    Se hace solo al importar; esto es para cuando cambias el formato o quieres
    medir cuánto se ahorra sobre lo que ya tienes.
    """
    return compilador_contexto.precompilar()


@app.get("/api/kb/contexto")
def kb_contexto(pregunta: str = Query(...), presupuesto: int = Query(default=1200),
                compilado: bool = Query(default=True)):
    """ El contexto exacto que recibiría el modelo, en el formato que se pida.

    Expuesto para poder comparar los dos formatos sobre la misma pregunta: si el
    tutor responde mal, lo primero es ver qué tenía delante y cuánto le costó.
    """
    r = context_assembler.ensamblar(pregunta, presupuesto_tokens=presupuesto,
                                    compilado=compilado)
    return {k: v for k, v in r.items() if k != "fuentes"} | {
        "citas_disponibles": len(r.get("fuentes") or [])}


@app.get("/api/kb/indice")
def kb_indice_estado():
    """ Si el índice semántico está en pie y con qué modelo """
    return indice_semantico.estado()


@app.post("/api/kb/indexar")
def kb_indexar():
    """ Reconstruye el índice semántico.

    Se hace solo al importar; esto es para cuando descargas el embebedor después
    de haber importado ya, o cambias de modelo.
    """
    r = indice_semantico.indexar(compilador_contexto)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("motivo", "no se pudo indexar"))
    return r


@app.get("/api/kb/bridges")
def kb_bridges(limite: int = Query(default=50, le=200)):
    """ Conceptos que aparecen en varios campos: los atajos entre materias """
    return {"puentes": knowledge_base.puentes(limite=limite)}


@app.post("/api/kb/search")
def kb_search(req: KnowledgeSearchRequest):
    return {"resultados": knowledge_base.buscar(req.query, limite=req.top_k or 20)}


@app.post("/api/kb/context")
def kb_context(req: ContextRequest):
    """ El contexto que se le inyectaría al tutor para esta pregunta.

    Expuesto aparte del chat para poder verlo: si el tutor responde mal, lo primero
    que hay que saber es qué material tenía delante.
    """
    return context_assembler.prompt_tutor(
        req.pregunta,
        presupuesto_tokens=_context_budget(req.presupuesto_tokens),
        dominio_preferido=req.dominio,
        nivel=req.nivel,
    )


# ======================================================================
# Preparar el trabajo para la GPU externa
# ======================================================================

JOBS_DIR = os.path.join(os.path.expanduser("~/.prig_books"), "jobs")


class JobPrepareRequest(BaseModel):
    # [{"path": "...", "domain": "math", "ajustes": {...}}, ...]
    libros: List[Dict[str, Any]]
    max_chunk_tokens: int = 500


def _libro_aceptable(ruta: str) -> Optional[str]:
    """ Por qué NO se puede meter este archivo en un trabajo, o None si se puede.

    El alcance correcto aquí es el del explorador, no el de `file_manager`. Son dos
    permisos distintos: `file_manager` guarda la lectura y escritura de archivos
    cualesquiera (el editor de código) y tiene que seguir siendo estrecho; esto solo
    lee LIBROS que el usuario ha señalado uno a uno en su propia carpeta personal.
    Confundirlos era lo que hacía que preparar un libro del Escritorio respondiera
    "Ruta no permitida" sin explicar nada.
    """
    if not ruta:
        return "ruta vacía"
    completa = os.path.abspath(os.path.expanduser(str(ruta)))
    if not os.path.exists(completa):
        return "el archivo ya no está ahí"
    if not os.path.isfile(completa):
        return "no es un archivo"
    if os.path.splitext(completa)[1].lower() not in explorador_extensiones:
        return (f"no es un libro ({os.path.splitext(completa)[1] or 'sin extensión'}); "
                f"se admiten " + ", ".join(sorted(explorador_extensiones)))
    if not explorador.permitida(completa):
        return ("está fuera de tu carpeta personal. Cópialo dentro, o ábrelo desde "
                "Buscar libros")
    return None


@app.get("/api/job/books")
def job_books():
    """ Libros que se pueden mandar a extraer, con el campo que se les propone.

    El campo se propone solo por el nombre del archivo: abrir cien PDF para mirar
    su primera página tardaría demasiado para una lista. Se revisa antes de enviar,
    porque un libro mal clasificado contamina todo lo que salga de él.
    """
    from domains import DOMAINS as _D, sugerir_dominio_con_confianza as _sug
    libros, vistos = [], {}
    for b in job_exporter.libros_disponibles():
        try:
            clave = (os.path.getsize(b["path"]), os.path.basename(b["path"]))
        except OSError:
            continue
        propuesta = _sug("", b["name"])
        libros.append({**b,
                       "domain": propuesta["dominio"],
                       "revisar": not propuesta["seguro"],
                       "motivo": propuesta["motivo"],
                       "duplicado": clave in vistos,
                       "duplicado_de": vistos.get(clave)})
        vistos.setdefault(clave, b["path"])
    return {"libros": libros,
            "dominios": {k: {"nombre": v["name"], "icono": v.get("icon", "")}
                         for k, v in _D.items()},
            "carpeta_trabajos": JOBS_DIR}


def _preparar_trabajo(libros: List[Dict[str, Any]], max_chunk_tokens: int,
                      progreso=None) -> Dict[str, Any]:
    """ Valida la selección y trocea lo que sea válido, sin abortar por lo que no.

    Rechazar el lote entero por un libro es la peor respuesta posible cuando has
    seleccionado veinte: obliga a repetir todo lo que ya había salido bien.
    """
    aceptados, rechazados = [], []
    for l in libros:
        ruta = l.get("path") or l.get("ruta")
        motivo = _libro_aceptable(ruta)
        if motivo:
            rechazados.append({"ruta": ruta, "nombre": os.path.basename(str(ruta or "")),
                               "motivo": motivo})
        else:
            aceptados.append({"path": os.path.abspath(os.path.expanduser(str(ruta))),
                              "domain": l.get("domain"),
                              "ajustes": l.get("ajustes") or {}})

    if not aceptados:
        detalle = "; ".join(f"{r['nombre'] or r['ruta']}: {r['motivo']}"
                            for r in rechazados[:4]) or "no has elegido ningún libro"
        raise HTTPException(status_code=400, detail=f"No se puede preparar nada. {detalle}")

    os.makedirs(JOBS_DIR, exist_ok=True)
    destino = os.path.join(JOBS_DIR, f"prig_job_{datetime.now():%Y%m%d_%H%M%S}")
    manifest = job_exporter.preparar(aceptados, destino,
                                     max_chunk_tokens=max_chunk_tokens,
                                     progreso=progreso)
    manifest["rechazados"] = rechazados
    if not manifest.get("total_books"):
        motivos = [f["motivo"] for f in manifest.get("failed", [])][:3]
        raise HTTPException(
            status_code=400,
            detail="Ningún libro se pudo trocear. " + ("; ".join(motivos) or
                   "Revisa que no estén escaneados."))
    return manifest


@app.post("/api/job/prepare")
def job_prepare(req: JobPrepareRequest):
    """ Trocea los libros y deja la carpeta lista para subir a Kaggle.

    Se hace en local a propósito: el troceado no necesita GPU, el resultado pesa
    mucho menos que los PDF y así los libros originales no salen del equipo.
    """
    if not req.libros:
        raise HTTPException(status_code=400, detail="No has elegido ningún libro")
    try:
        return _preparar_trabajo(req.libros, req.max_chunk_tokens)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo preparar: {e}")


@app.post("/api/job/prepare-stream")
def job_prepare_stream(req: JobPrepareRequest):
    """ Igual, pero informando libro a libro según avanza.

    Un PDF de 600 páginas tarda unos segundos en trocearse, y una selección de
    veinte son minutos. Sin avance, la pantalla parece colgada y no hay forma de
    saber si va bien o se atascó en uno concreto.
    """
    if not req.libros:
        raise HTTPException(status_code=400, detail="No has elegido ningún libro")

    cola: "queue.Queue" = queue.Queue()
    resultado: Dict[str, Any] = {}

    def trabajar():
        try:
            resultado["manifest"] = _preparar_trabajo(
                req.libros, req.max_chunk_tokens, progreso=cola.put)
        except HTTPException as e:
            resultado["error"] = e.detail
        except Exception as e:
            resultado["error"] = str(e)
        finally:
            cola.put(None)

    hilo = threading.Thread(target=trabajar, daemon=True)
    hilo.start()

    def emitir():
        yield json.dumps({"tipo": "inicio", "total": len(req.libros)}) + "\n"
        while True:
            evento = cola.get()
            if evento is None:
                break
            yield json.dumps(evento, ensure_ascii=False) + "\n"
        hilo.join(timeout=5)
        if resultado.get("error"):
            yield json.dumps({"tipo": "error", "mensaje": resultado["error"]},
                             ensure_ascii=False) + "\n"
        else:
            yield json.dumps({"tipo": "fin", "manifest": resultado.get("manifest", {})},
                             ensure_ascii=False) + "\n"

    return StreamingResponse(emitir(), media_type="application/x-ndjson")


@app.get("/api/job/list")
def job_list():
    """ Trabajos ya preparados, para volver a subirlos o borrarlos """
    os.makedirs(JOBS_DIR, exist_ok=True)
    salida = []
    for nombre in sorted(os.listdir(JOBS_DIR), reverse=True):
        ruta = os.path.join(JOBS_DIR, nombre)
        manifiesto = os.path.join(ruta, "manifest.json")
        if not os.path.isfile(manifiesto):
            continue
        try:
            with open(manifiesto, encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            continue
        salida.append({
            "nombre": nombre, "ruta": ruta,
            "job_id": m.get("job_id"), "creado": m.get("created_at"),
            "libros": m.get("total_books"), "fragmentos": m.get("total_chunks"),
            "dominios": m.get("domains", []),
            "mb": round(sum(os.path.getsize(os.path.join(ruta, f))
                            for f in os.listdir(ruta)) / (1024 * 1024), 2),
        })
    return {"trabajos": salida, "carpeta": JOBS_DIR}


# ======================================================================
# Flujos de agentes
# ======================================================================

class FlujoGuardar(BaseModel):
    id: Optional[str] = None
    nombre: str
    descripcion: str = ""
    ambito: str = "libre"
    pasos: List[Dict[str, Any]] = []


class FlujoEjecutar(BaseModel):
    flujo: Optional[Dict[str, Any]] = None   # un flujo sin guardar
    flujo_id: Optional[str] = None           # o uno guardado
    entrada: str = ""
    consulta_contexto: str = ""              # con qué buscar en la biblioteca
    guardar_historial: bool = True


def _motor_flujos() -> FlowEngine:
    global _active_flow_engine
    try:
        num_ctx = int(ai_engine.config.get("num_ctx", 4096))
    except (TypeError, ValueError):
        num_ctx = 4096
    _active_flow_engine = FlowEngine(
        ai_engine, context_assembler, num_ctx=num_ctx,
        gobernador=recursos_termico.gobernador())
    return _active_flow_engine


_active_flow_engine_v2 = None

def _motor_flujos_v2() -> DynamicFlowEngine:
    global _active_flow_engine_v2
    try:
        num_ctx = int(ai_engine.config.get("num_ctx", 8192))
    except (TypeError, ValueError):
        num_ctx = 8192
    _active_flow_engine_v2 = DynamicFlowEngine(
        ai_engine,
        gobernador=recursos_termico.gobernador(),
        num_ctx=num_ctx
    )
    return _active_flow_engine_v2


def _veredictos_flujos():
    """ Veredicto de la calculadora para cada modelo, en el uso "flujos".

    Antes se comparaba el tamaño del archivo con la VRAM menos un margen fijo: daba
    "cabe" a modelos que en realidad se repartían con la CPU (la caché y el búfer
    también ocupan) y "no cabe" a un MoE que va a 22 tok/s repartido.
    """
    try:
        g = recursos_gestor()
        maq = g.maquina()
        instalados = {f["nombre"]: f for f in g.fichas_instaladas()}
    except Exception:
        maq, instalados = None, {}

    def calcular(nombre: str, info: Dict[str, Any]) -> Dict[str, Any]:
        if info.get("embedding"):
            return {"cabe": True, "veredicto": "embeddings",
                    "etiqueta": "Embeddings en CPU", "motivo": "Se ejecuta en la CPU."}
        if maq is None:
            margen = agent_flows.VRAM_TIPICA_GB - 0.6
            return {"cabe": (info.get("vram_gb") or 0) <= margen, "veredicto": None}
        try:
            f = instalados.get(nombre) or recursos_ficha.desde_catalogo(nombre, info)
            r = recursos_calc.recomendar(f, maq, "flujos", "equilibrado")
        except Exception as e:
            return {"cabe": False, "veredicto": None, "motivo": str(e)}
        return {"cabe": r["veredicto"] in ("entero", "ajustando"),
                "util": r["veredicto"] in ("entero", "ajustando", "parcial", "solo_cpu"),
                "veredicto": r["veredicto"], "etiqueta": r["etiqueta"],
                "tok_s": r["estimacion"].get("tok_s"), "motivo": r["motivo"],
                "estimado": bool(f.get("estimada"))}
    return calcular


@app.get("/api/flujos/catalogo")
def flujos_catalogo():
    """ Modelos, roles y variables: lo que la interfaz necesita para montar un flujo.

    Los modelos se cruzan con los que tienes descargados para no ofrecerte en el
    desplegable uno que no está y que solo daría un error a mitad de la ejecución.
    """
    try:
        detalle = ai_engine.get_detailed_models().get("models", [])
    except Exception:
        detalle = []
    tamanos = {m["name"]: m.get("size_gb") or 0 for m in detalle}
    version = _version_ollama()
    instalados = set(tamanos)
    veredicto = _veredictos_flujos()

    catalogo = []
    for nombre, info in {**agent_flows.MODELOS,
                         **{k: {**v, "embedding": True}
                            for k, v in agent_flows.MODELOS_EMBEDDING.items()}}.items():
        # Si lo tienes descargado manda su tamaño real, no el estimado del catálogo
        vram = (tamanos.get(nombre) or tamanos.get(f"{nombre}:latest")
                or info["vram_gb"])
        # Ollama guarda los modelos con la etiqueta puesta: "qwen3:8b" se instala
        # así, pero "phi4-mini" aparece como "phi4-mini:latest". Comparar a secas
        # marcaba como no instalado algo que sí estaba.
        instalado = nombre in instalados or f"{nombre}:latest" in instalados
        # Un modelo que tu Ollama no puede descargar tiene que verse ANTES de
        # pulsar: el registro responde con un error que no dice qué versión tienes.
        minima = agent_flows.ollama_necesario(nombre)
        bloqueado = bool(minima and not agent_flows.version_suficiente(version, minima))
        catalogo.append({**info, "modelo": nombre, "vram_gb": round(vram, 1),
                         "instalado": instalado,
                         **veredicto(nombre if not instalado or nombre in instalados
                                     else f"{nombre}:latest", info),
                         "piensa": info.get("piensa", "no"),
                         "ollama_minimo": minima,
                         "necesita_actualizar": bloqueado})

    # Los que tienes y no están en el catálogo también sirven, pero su tamaño hay
    # que mirarlo: darlo por bueno ofrecería como válido un 32B de 18 GB en una
    # tarjeta de 6, y el flujo moriría a mitad del segundo paso.
    #
    # Ollama guarda "bge-m3" como "bge-m3:latest": sin quitar ese sufijo, el
    # catálogo enseñaba la misma cosa dos veces, una marcada como instalada y
    # otra no.
    del_catalogo = set(agent_flows.MODELOS) | set(agent_flows.MODELOS_EMBEDDING)
    del_catalogo |= {f"{n}:latest" for n in del_catalogo}
    for nombre in sorted(instalados - del_catalogo):
        vram = tamanos.get(nombre) or 0
        v = veredicto(nombre, {"vram_gb": vram})
        catalogo.append({"modelo": nombre, "instalado": True, **v,
                         "vram_gb": round(vram, 1), "familia": "otro", "razona": 0,
                         "fuerte_en": [],
                         "nota": "No está en el catálogo de Prig. " + v.get("motivo", "")})
    catalogo.sort(key=lambda m: (bool(m.get("embedding")),
                                 m.get("necesita_actualizar", False),
                                 not m["instalado"], not m["cabe"],
                                 -m.get("razona", 0)))

    bloqueados = sorted({m["modelo"].split(":")[0] for m in catalogo
                         if m.get("necesita_actualizar")})
    return {
        "ollama": version,
        "ollama_bloquea": bloqueados,
        "modelos": catalogo,
        "roles": [{"id": k, **{x: v[x] for x in ("nombre", "icono", "formato",
                                                 "temperatura", "ayuda")}}
                  for k, v in agent_flows.ROLES.items()],
        "variables": agent_flows.VARIABLES,
        "variables_libro": agent_flows.VARIABLES_LIBRO,
        "vram_gb": agent_flows.VRAM_TIPICA_GB,
        "max_pasos": agent_flows.MAX_PASOS,
    }


class DescargaRequest(BaseModel):
    modelo: str


@app.post("/api/flujos/descargar")
def flujos_descargar(req: DescargaRequest):
    """ Descarga un modelo desde el propio panel de flujos.

    Solo se admiten los del catálogo: es lo que evita que un nombre mal escrito se
    convierta en una descarga de veinte gigas que no era la que se quería.
    """
    ai_engine.try_autostart_ollama()
    minima = agent_flows.ollama_necesario(req.modelo)
    version = _version_ollama()
    if minima and not agent_flows.version_suficiente(version, minima):
        raise HTTPException(
            status_code=400,
            detail=f"'{req.modelo}' necesita Ollama {minima} o posterior y tienes la "
                   f"{version}. Actualiza con:  "
                   f"curl -fsSL https://ollama.com/install.sh | sh")

    conocidos = set(agent_flows.MODELOS) | set(agent_flows.MODELOS_EMBEDDING)
    conocidos |= {f"{n}:latest" for n in conocidos}
    conocidos |= {n.replace(":latest", "") for n in conocidos}
    es_valido_personalizado = bool(re.match(r"^[a-zA-Z0-9_\.\-]+(/[a-zA-Z0-9_\.\-]+)?(:[a-zA-Z0-9_\.\-]+)?$", req.modelo))
    if req.modelo not in conocidos and not es_valido_personalizado:
        raise HTTPException(
            status_code=400,
            detail=f"'{req.modelo}' no tiene un formato de modelo válido de Ollama.")

    info = (agent_flows.MODELOS.get(req.modelo)
            or agent_flows.MODELOS_EMBEDDING.get(req.modelo) or {})

    def emitir():
        yield json.dumps({"tipo": "inicio", "modelo": req.modelo,
                          "gb": info.get("vram_gb"),
                          "ollama": _version_ollama()}, ensure_ascii=False) + "\n"
        fallo = None
        try:
            for linea in ai_engine.pull_model(req.modelo):
                texto = linea.strip()
                # pull_model informa de los errores como una línea más de texto.
                # Sin mirarlas, una descarga fallida terminaba anunciando éxito.
                if texto.lower().startswith(("error", "error en descarga")):
                    fallo = texto
                    break
                yield json.dumps({"tipo": "avance", "texto": texto},
                                 ensure_ascii=False) + "\n"
        except Exception as err:
            fallo = str(err)

        if fallo:
            yield json.dumps({"tipo": "error", "mensaje": _explicar_fallo(fallo, req.modelo)},
                             ensure_ascii=False) + "\n"
            return

        # Que Ollama diga que terminó no basta: se comprueba que el modelo está.
        try:
            instalados = {m["name"] for m in ai_engine.get_detailed_models().get("models", [])}
        except Exception:
            instalados = set()
        if req.modelo not in instalados and f"{req.modelo}:latest" not in instalados:
            yield json.dumps({"tipo": "error", "mensaje":
                              f"La descarga terminó pero '{req.modelo}' no aparece "
                              f"instalado. Inténtalo de nuevo."}, ensure_ascii=False) + "\n"
            return
        yield json.dumps({"tipo": "fin", "modelo": req.modelo}) + "\n"

    return StreamingResponse(emitir(), media_type="application/x-ndjson")


def _version_ollama() -> str:
    # 1. Intentar consultar el servicio activo en ejecución
    active_ver = None
    try:
        import requests as _rq
        res = _rq.get(f"{ai_engine.base_url}/api/version", timeout=3)
        if res.status_code == 200:
            active_ver = res.json().get("version")
    except Exception:
        pass

    # 2. Consultar el mejor binario instalado en el sistema/Prig
    best = None
    try:
        best = ai_engine.get_best_ollama_binary()
    except Exception:
        pass
    best_ver = best[1] if best and best[1] != "0.0.0" else None

    # Si hay versión activa y binario disponible:
    if active_ver and best_ver:
        if hasattr(ai_engine, "_version_ge") and ai_engine._version_ge(best_ver, active_ver):
            return best_ver
        return active_ver

    if active_ver:
        return active_ver
    if best_ver:
        return best_ver

    return "?"


def _explicar_fallo(mensaje: str, modelo: str) -> str:
    """ Traduce el error de Ollama a algo con lo que se pueda hacer algo.

    El 412 es el caso importante y el más opaco: significa que tu Ollama es
    anterior al modelo que pides. Los modelos nuevos necesitan una versión nueva,
    y el mensaje original no dice cuál tienes.
    """
    motor = explicar_error_motor(mensaje)
    if motor:
        return motor
    if "412" in mensaje or "newer version" in mensaje.lower():
        return (f"Tu Ollama ({_version_ollama()}) es anterior a '{modelo}' y no puede "
                f"descargarlo. Actualízalo y vuelve a intentarlo:\n"
                f"    curl -fsSL https://ollama.com/install.sh | sh\n"
                f"En Linux eso conserva los modelos que ya tienes.")
    if "no space" in mensaje.lower() or "espacio" in mensaje.lower():
        return f"No hay espacio en disco para '{modelo}'. {mensaje}"
    if "connection" in mensaje.lower() or "refused" in mensaje.lower():
        return "Ollama no responde. Arráncalo con 'ollama serve' y reinténtalo."
    return mensaje


@app.get("/api/flujos")
def flujos_listar():
    guardados = flow_store.listar()
    sugerido = _modelo_que_razona()
    base = ai_engine.config.get("agent1_model", "qwen2.5-coder:7b")
    plantillas_v1 = agent_flows.plantillas(base, sugerido)
    plantillas_v2 = agent_flows_v2.plantillas_profesionales_sota(base, sugerido)
    return {"flujos": guardados,
            "plantillas": plantillas_v2 + plantillas_v1,
            "plantillas_sota": plantillas_v2,
            "modelo_base": base, "modelo_razona": sugerido}


@app.get("/api/flujos/v2/plantillas")
def flujos_v2_plantillas():
    sugerido = _modelo_que_razona()
    base = ai_engine.config.get("agent1_model", "qwen2.5-coder:7b")
    return {
        "plantillas": agent_flows_v2.plantillas_profesionales_sota(base, sugerido),
        "roles": agent_flows_v2.ROLES_V2,
        "modelo_base": base,
        "modelo_razona": sugerido
    }


def _modelo_que_razona() -> str:
    """ El mejor modelo de razonamiento que tengas descargado, si hay alguno """
    try:
        instalados = {m["name"] for m in ai_engine.get_detailed_models().get("models", [])}
    except Exception:
        return ""
    candidatos = [(info.get("razona", 0), nombre)
                  for nombre, info in agent_flows.MODELOS.items()
                  if nombre in instalados and "criticar" in info.get("fuerte_en", [])
                  and info["vram_gb"] <= agent_flows.VRAM_TIPICA_GB - 0.6]
    return max(candidatos)[1] if candidatos else ""


@app.post("/api/flujos/validar")
def flujos_validar(req: FlujoGuardar):
    flujo = req.model_dump()
    return {"problemas": agent_flows.validar_flujo(flujo),
            "plan": agent_flows.plan_de_modelos(flujo)}


@app.post("/api/flujos")
def flujos_guardar(req: FlujoGuardar):
    flujo = req.model_dump()
    problemas = agent_flows.validar_flujo(flujo)
    if problemas:
        raise HTTPException(status_code=400, detail="; ".join(problemas))
    return flow_store.guardar(flujo)


@app.delete("/api/flujos/{flujo_id}")
def flujos_borrar(flujo_id: str):
    if not flow_store.borrar(flujo_id):
        raise HTTPException(status_code=404, detail="Ese flujo no existe")
    return {"borrado": flujo_id}


@app.post("/api/flujos/ejecutar")
def flujos_ejecutar(req: FlujoEjecutar):
    """ Ejecuta el flujo emitiendo cada paso según va ocurriendo.
    Soporta automáticamente grafos v2 dinámicos y recursivos con sandbox, o flujos clásicos v1.
    """
    flujo = req.flujo or flow_store.obtener(req.flujo_id or "")
    if not flujo:
        raise HTTPException(status_code=404, detail="No se encontró el flujo")

    # Detectar si es un grafo dinámico / recursivo v2
    es_v2 = bool(flujo.get("nodos") or flujo.get("nodo_inicial") or flujo.get("es_v2") or str(flujo.get("id", "")).startswith("sota_"))

    if es_v2:
        motor_v2 = _motor_flujos_v2()
        def emitir_v2():
            try:
                for evento in motor_v2.ejecutar_grafo(flujo, entrada_inicial=req.entrada):
                    yield json.dumps(evento, ensure_ascii=False) + "\n"
            except Exception as err:
                yield json.dumps({"tipo": "error", "mensaje": str(err)}, ensure_ascii=False) + "\n"
        return StreamingResponse(emitir_v2(), media_type="application/x-ndjson")

    motor = _motor_flujos()

    def emitir():
        registro, segundos = [], 0.0
        try:
            for evento in motor.ejecutar(flujo, entrada=req.entrada,
                                         consulta_contexto=req.consulta_contexto):
                if evento.get("tipo") == "fin":
                    registro = evento.get("registro", [])
                    segundos = evento.get("segundos", 0)
                    evento = {k: v for k, v in evento.items() if k != "registro"}
                yield json.dumps(evento, ensure_ascii=False) + "\n"
        except Exception as err:
            yield json.dumps({"tipo": "error", "mensaje": str(err)},
                             ensure_ascii=False) + "\n"
            return
        if req.guardar_historial and registro:
            eid = flow_store.anotar_ejecucion(flujo, req.entrada, registro, segundos)
            yield json.dumps({"tipo": "guardado", "ejecucion": eid}) + "\n"

    return StreamingResponse(emitir(), media_type="application/x-ndjson")


@app.get("/api/flujos/historial")
def flujos_historial(flujo_id: Optional[str] = None, limite: int = 20):
    return {"ejecuciones": flow_store.historial(flujo_id, limite)}


@app.get("/api/flujos/ejecucion/{eid}")
def flujos_ejecucion(eid: str):
    """ Una ejecución con el prompt exacto que recibió cada agente.

    Es lo que permite arreglar un flujo que da malos resultados: sin ver qué leyó
    cada paso, ajustar los prompts es adivinar cuál de los cinco lo estropeó.
    """
    ejecucion = flow_store.ejecucion(eid)
    if not ejecucion:
        raise HTTPException(status_code=404, detail="Esa ejecución ya no está guardada")
    return ejecucion


# ======================================================================
# Ficha de libro: analizar un libro entero con un flujo de agentes
# ======================================================================

class FichaRequest(BaseModel):
    source_id: str
    flujo: Optional[Dict[str, Any]] = None   # si no, la plantilla de ficha
    flujo_id: Optional[str] = None


@app.get("/api/libros/analizables")
def libros_analizables():
    """ Los libros importados, con cuánto material hay de cada uno.

    Se enseña el recuento porque decide si merece la pena analizarlo: un libro con
    veinte conceptos y sin capítulos detectados dará una ficha pobre hagas lo que
    hagas, y más vale volver a extraerlo que gastar siete pasos de modelo.
    """
    return {"libros": perfil_libro.listar()}


@app.get("/api/libros/ficha/{source_id}")
def libro_ficha(source_id: str):
    ficha = perfil_libro.obtener(source_id)
    if not ficha:
        raise HTTPException(status_code=404, detail="Ese libro todavía no tiene ficha")
    return ficha


@app.get("/api/libros/resumen/{source_id}")
def libro_resumen(source_id: str):
    """ Lo que leería el flujo, tal cual. Sirve para ver por qué falló un análisis. """
    variables = perfil_libro.variables(source_id)
    if not variables:
        raise HTTPException(status_code=404, detail="Ese libro no está en la base")
    return {"variables": variables,
            "tokens": {k: int(len(v) / 3.6) for k, v in variables.items()}}


@app.post("/api/libros/ficha")
def libro_analizar(req: FichaRequest):
    """ Corre el flujo sobre un libro y guarda la ficha que produce.

    La ficha se monta EN CÓDIGO juntando lo que devolvió cada paso, no pidiéndole a
    un octavo agente que reúna los siete anteriores: no cabrían en la ventana y
    podría reescribir datos que ya estaban bien.
    """
    variables = perfil_libro.variables(req.source_id)
    if not variables:
        raise HTTPException(status_code=404,
                            detail="Ese libro no está importado en la base de conocimiento")

    flujo = req.flujo or flow_store.obtener(req.flujo_id or "")
    if not flujo:
        base = ai_engine.config.get("agent1_model", "qwen2.5-coder:7b")
        flujo = next(f for f in agent_flows.plantillas(base, _modelo_que_razona())
                     if f["id"] == "plantilla_ficha_libro")

    motor = _motor_flujos()
    titulo = variables.get("libro:titulo", req.source_id)

    def emitir():
        salidas, datos, registro, modelos, segundos = {}, {}, [], [], 0.0
        try:
            for evento in motor.ejecutar(flujo, entrada=titulo,
                                         consulta_contexto=titulo, extra=variables):
                if evento.get("tipo") == "fin":
                    salidas = evento.get("salidas", {})
                    datos = evento.get("datos", {})
                    registro = evento.get("registro", [])
                    modelos = evento.get("modelos", [])
                    segundos = evento.get("segundos", 0)
                    evento = {k: v for k, v in evento.items() if k != "registro"}
                yield json.dumps(evento, ensure_ascii=False) + "\n"
        except Exception as err:
            yield json.dumps({"tipo": "error", "mensaje": str(err)}, ensure_ascii=False) + "\n"
            return

        # Lo que devolvió cada paso en JSON manda; si un paso no dio JSON válido se
        # guarda su texto, que es mejor que perderlo.
        piezas = {pid: datos.get(pid, salidas.get(pid)) for pid in salidas}
        ficha = perfil_libro.montar_ficha(req.source_id, piezas, modelos)
        perfil_libro.guardar(req.source_id, ficha)
        if registro:
            flow_store.anotar_ejecucion(flujo, f"ficha de {titulo}", registro, segundos)
        yield json.dumps({"tipo": "ficha", "ficha": ficha}, ensure_ascii=False) + "\n"

    return StreamingResponse(emitir(), media_type="application/x-ndjson")


@app.get("/api/libros/material")
def libro_material(concepto: str = Query(...)):
    """ Con qué se puede montar un ejercicio sobre este concepto.

    Devuelve de qué libro sale, en qué páginas, qué ejemplos resueltos hay cerca y
    qué preguntas trae el propio texto. Un ejercicio construido sobre esto remite a
    algo que el alumno puede ir a leer; uno inventado, no.
    """
    return perfil_libro.material_para_ejercicio(concepto)


@app.get("/api/libros/contexto-plan")
def libro_contexto_plan(objetivo: str = Query(default="")):
    """ Las fichas resumidas, para que quien arma un plan sepa con qué cuenta """
    return {"contexto": perfil_libro.contexto_para_plan(objetivo)}


# ======================================================================
# Explorar carpetas y sondear libros antes de extraerlos
# ======================================================================

class SondeoRequest(BaseModel):
    rutas: List[str] = []           # uno o varios libros
    carpeta: Optional[str] = None   # o una carpeta entera
    con_modelo: bool = True
    modelo: Optional[str] = None
    tope: int = 40


@app.get("/api/explorador/atajos")
def explorador_atajos():
    """ Dónde suele haber libros, para no empezar navegando desde la raíz """
    return {"atajos": explorador.atajos()}


@app.get("/api/explorador/listar")
def explorador_listar(ruta: Optional[str] = None, recursivo: bool = False):
    """ Carpetas y libros de una ruta. Solo nombres y tamaños, nunca contenido. """
    try:
        return explorador.listar(ruta, recursivo=recursivo)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (NotADirectoryError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/explorador/buscar")
def explorador_buscar(q: str = Query(...), desde: Optional[str] = None):
    """ Buscar un libro por su nombre, para cuando no recuerdas dónde lo dejaste """
    try:
        return {"resultados": explorador.buscar(q, desde)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.post("/api/sondeo")
def sondear_libros(req: SondeoRequest):
    """ Sondeo rápido: mide el archivo y, si se pide, lo clasifica con el modelo.

    Va en flujo continuo porque una carpeta de treinta libros son treinta medidas
    y treinta llamadas cortas al modelo: ver los resultados aparecer uno a uno es
    lo que permite parar en cuanto se ve que la carpeta no era la que tocaba.
    """
    rutas = list(req.rutas)
    if req.carpeta:
        try:
            listado = explorador.listar(req.carpeta, recursivo=True)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except (NotADirectoryError, FileNotFoundError) as e:
            raise HTTPException(status_code=404, detail=str(e))
        rutas += [l["ruta"] for l in listado["libros"]]

    # Solo lo que el explorador dejaría navegar: el sondeo SÍ lee el archivo, así
    # que aquí el límite tiene que comprobarse de verdad.
    rutas = [r for r in dict.fromkeys(rutas) if explorador.permitida(r)][:req.tope]
    if not rutas:
        raise HTTPException(status_code=400,
                            detail="No hay ningún libro que sondear en esa selección")

    modelo = req.modelo or ai_engine.config.get("agent1_model", "qwen2.5-coder:7b")

    def emitir():
        yield json.dumps({"tipo": "inicio", "total": len(rutas)}) + "\n"
        for n, ruta in enumerate(rutas, 1):
            yield json.dumps({"tipo": "sondeando", "n": n, "total": len(rutas),
                              "nombre": os.path.basename(ruta)}, ensure_ascii=False) + "\n"
            try:
                r = sondeo.sondear(ruta, modelo=modelo, con_modelo=req.con_modelo)
                r["tipo"] = "resultado"
                r["n"] = n
            except Exception as err:
                r = {"tipo": "fallo", "n": n, "ruta": ruta,
                     "nombre": os.path.basename(ruta), "mensaje": str(err)}
            yield json.dumps(r, ensure_ascii=False) + "\n"
        yield json.dumps({"tipo": "fin"}) + "\n"

    return StreamingResponse(emitir(), media_type="application/x-ndjson")


@app.post("/api/sondeo/preparar")
def sondeo_preparar(req: JobPrepareRequest):
    """ Del sondeo al trabajo de extracción, con los ajustes que recomendó.

    Es el paso que evita tener que recordar qué decía el sondeo: los libros van con
    el campo ya elegido y el tamaño de fragmento que les convenía.
    """
    return job_prepare(req)


# Kaggle: buscar notebooks de la comunidad y leerlos celda a celda con un modelo
# (backend/kaggle_lector.py). Sustituye al catálogo fijo de seis notebooks y a la
# «importación» que generaba una plantilla inventada en vez del notebook real.

class KaggleCredencialesRequest(BaseModel):
    texto: str


class KaggleRefRequest(BaseModel):
    ref: str
    modelo: Optional[str] = None
    regenerar: bool = False
    incluir_datos: Optional[bool] = True


class KaggleExplicarRequest(KaggleRefRequest):
    indice: int
    nivel: str = "intermedio"


class KagglePreguntarRequest(KaggleRefRequest):
    indice: Optional[int] = None
    mensajes: List[Dict[str, str]]


def _kaggle(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except kaggle_lector.ErrorKaggle as e:
        raise HTTPException(status_code=400, detail=str(e))


class KaggleDatosRequest(BaseModel):
    tipo: str                                  # "dataset" | "competicion"
    ref: str
    modelo: Optional[str] = None
    regenerar: bool = False


def _kaggle_ficha(tipo: str, ref: str):
    if tipo == "dataset":
        return _kaggle(kaggle_explorar.dataset, ref, file_mgr.base_dir)
    if tipo == "competicion":
        return _kaggle(kaggle_explorar.competicion, ref, file_mgr.base_dir)
    raise HTTPException(status_code=400, detail="Tipo desconocido: dataset o competicion.")


@app.get("/api/kaggle/datasets")
def kaggle_datasets(q: str = "", orden: str = "populares", pagina: int = Query(default=1, ge=1, le=100), tipo_archivo: str = "",
                    licencia: str = "", tamano: str = "", usuario: str = ""):
    return _kaggle(kaggle_explorar.buscar_datasets, q, orden, pagina, tipo_archivo, licencia, tamano, usuario)


@app.get("/api/kaggle/dataset")
def kaggle_dataset(ref: str):
    return _kaggle_ficha("dataset", ref)


@app.get("/api/kaggle/competiciones")
def kaggle_competiciones(q: str = "", categoria: str = "", orden: str = "agrupadas", pagina: int = Query(default=1, ge=1, le=100),
                         grupo: str = ""):
    return _kaggle(kaggle_explorar.buscar_competiciones, q, categoria, orden, pagina, grupo)


@app.get("/api/kaggle/competicion")
def kaggle_competicion(ref: str):
    return _kaggle_ficha("competicion", ref)


@app.post("/api/kaggle/descargar")
def kaggle_descargar(req: KaggleDatosRequest):
    """ Baja y descomprime los datos en kaggle_datos/<slug>/ del proyecto (NDJSON con el progreso) """
    if req.tipo not in ("dataset", "competicion"):
        raise HTTPException(status_code=400, detail="Tipo desconocido: dataset o competicion.")
    cancelar = threading.Event()
    with ai_engine._streams_lock:
        ai_engine.__dict__.setdefault("_cancelables", set()).add(cancelar)

    def trabajo(avisar):
        try:
            return kaggle_explorar.descargar(req.tipo, req.ref, file_mgr.base_dir, avisar, cancelar)
        finally:
            with ai_engine._streams_lock:
                ai_engine._cancelables.discard(cancelar)
    return _ndjson_en_hilo(trabajo)


class KaggleColeccionRequest(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    color: Optional[str] = None


class KaggleItemRequest(BaseModel):
    tipo: str
    ref: str
    datos: Optional[Dict[str, Any]] = None
    nota: Optional[str] = None


class KagglePdfRequest(BaseModel):
    ref: Optional[str] = None                  # un notebook…
    coleccion: Optional[str] = None            # …o todos los de una colección
    nivel: Optional[str] = None
    solo_explicadas: bool = False
    guia: bool = True
    salidas: bool = True
    chat: Optional[List[Dict[str, str]]] = None


@app.get("/api/kaggle/colecciones")
def kaggle_colecciones_listar():
    return {"colecciones": kaggle_colecciones.listar(), "guardados": kaggle_colecciones.guardados(),
            "colores": list(kaggle_colecciones.COLORES)}


@app.post("/api/kaggle/colecciones")
def kaggle_colecciones_crear(req: KaggleColeccionRequest):
    return _kaggle(kaggle_colecciones.crear, req.nombre or "", req.descripcion or "", req.color)


@app.get("/api/kaggle/colecciones/{id_}")
def kaggle_coleccion(id_: str):
    return _kaggle(kaggle_colecciones.obtener, id_)


@app.patch("/api/kaggle/colecciones/{id_}")
def kaggle_coleccion_editar(id_: str, req: KaggleColeccionRequest):
    return _kaggle(kaggle_colecciones.editar, id_, req.nombre, req.descripcion, req.color)


@app.delete("/api/kaggle/colecciones/{id_}")
def kaggle_coleccion_borrar(id_: str):
    return _kaggle(kaggle_colecciones.borrar, id_)


@app.post("/api/kaggle/colecciones/{id_}/items")
def kaggle_coleccion_anadir(id_: str, req: KaggleItemRequest):
    return _kaggle(kaggle_colecciones.anadir, id_, req.tipo, req.ref, req.datos)


@app.delete("/api/kaggle/colecciones/{id_}/items")
def kaggle_coleccion_quitar(id_: str, tipo: str, ref: str):
    return _kaggle(kaggle_colecciones.quitar, id_, tipo, ref)


@app.patch("/api/kaggle/colecciones/{id_}/items")
def kaggle_coleccion_nota(id_: str, req: KaggleItemRequest):
    return _kaggle(kaggle_colecciones.anotar, id_, req.tipo, req.ref, req.nota or "")


@app.post("/api/kaggle/pdf")
def kaggle_pdf_crear(req: KagglePdfRequest):
    """ Notebook(s) explicado(s) en PDF, en <proyecto>/kaggle_pdf/ """
    opciones = {"nivel": req.nivel, "solo_explicadas": req.solo_explicadas, "guia": req.guia,
                "salidas": req.salidas, "chat": req.chat}
    if req.coleccion:
        coleccion = _kaggle(kaggle_colecciones.obtener, req.coleccion)
        return _kaggle(kaggle_pdf.pdf_coleccion, coleccion, file_mgr.base_dir, opciones)
    if not req.ref:
        raise HTTPException(status_code=400, detail="Falta el notebook o la colección.")
    return _kaggle(kaggle_pdf.pdf_notebook, req.ref, file_mgr.base_dir, opciones)


def _ruta_pdf_segura(ruta: str) -> str:
    raiz = os.path.realpath(os.path.join(file_mgr.base_dir, kaggle_pdf.CARPETA_PDF))
    real = os.path.realpath(ruta)
    if not real.startswith(raiz + os.sep) or not real.endswith(".pdf") or not os.path.isfile(real):
        raise HTTPException(status_code=404, detail="Ese PDF no existe.")
    return real


@app.get("/api/kaggle/pdf")
def kaggle_pdf_archivo(ruta: str, descargar: bool = False):
    """ El PDF generado: para verlo dentro de Prig o para «Guardar como…» """
    real = _ruta_pdf_segura(ruta)
    return FileResponse(real, media_type="application/pdf", filename=os.path.basename(real),
                        content_disposition_type="attachment" if descargar else "inline")


@app.post("/api/kaggle/pdf/abrir")
def kaggle_pdf_abrir(req: KaggleRefRequest):
    """ Abre el PDF con el visor del sistema """
    real = _ruta_pdf_segura(req.ref)
    cmd = ["xdg-open", real] if sys.platform.startswith("linux") else (["open", real] if sys.platform == "darwin" else ["cmd", "/c", "start", "", real])
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="No hay un visor de PDF configurado en el sistema.")
    return {"ok": True}


@app.get("/api/kaggle/mis_datos")
def kaggle_mis_datos():
    return {"datos": kaggle_explorar.mis_datos(file_mgr.base_dir), "carpeta": kaggle_explorar.CARPETA_DATOS}


@app.get("/api/kaggle/previa")
def kaggle_previa(ruta: str):
    return _kaggle(kaggle_explorar.vista_previa, ruta, file_mgr.base_dir)


@app.get("/api/kaggle/archivo")
def kaggle_archivo(ruta: str):
    """ Una imagen de los datos descargados, para verla en la vista previa """
    raiz = os.path.realpath(os.path.join(file_mgr.base_dir, kaggle_explorar.CARPETA_DATOS))
    real = os.path.realpath(ruta)
    if not real.startswith(raiz + os.sep) or not os.path.isfile(real) or \
            not real.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        raise HTTPException(status_code=404, detail="No encontrado.")
    return FileResponse(real)


@app.post("/api/kaggle/explicar_datos")
def kaggle_explicar_datos(req: KaggleDatosRequest):
    ficha = _kaggle_ficha(req.tipo, req.ref)
    motor, nombre = _motor_desafios(req.modelo, "explicar")
    modelo = _modelo_desafios(req.modelo, "explicar")
    huella = kaggle_explorar.huella(ficha)
    guardada = None if req.regenerar else kaggle_explorar.explicacion_datos(req.tipo, ficha["ref"], modelo, huella)
    if guardada:
        return _ndjson_en_hilo(lambda avisar: {"texto": guardada, "guardada": True})

    def trabajo(avisar):
        texto = _consumir(kaggle_explorar.explicar_datos(motor, nombre, ficha, file_mgr.base_dir), avisar)
        if not texto.strip():
            raise kaggle_lector.ErrorKaggle("El modelo no devolvió nada. Prueba otra vez u otro modelo.")
        kaggle_explorar.guardar_explicacion_datos(req.tipo, ficha["ref"], modelo, huella, texto)
        return {"texto": texto, "guardada": False}
    return _ndjson_en_hilo(trabajo)


# ==========================================
# GITHUB: buscar repositorios y leerlos con el profesor (github_lector.py)
# ==========================================

class GithubRefRequest(BaseModel):
    ref: str
    ruta: Optional[str] = None
    nivel: str = "intermedio"
    modelo: Optional[str] = None
    regenerar: bool = False
    nota: Optional[str] = None
    mensajes: Optional[List[Dict[str, str]]] = None


class GithubTokenRequest(BaseModel):
    texto: str


def _github(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except github_lector.ErrorGitHub as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/github/estado")
def github_estado():
    return github_lector.estado()


@app.post("/api/github/token")
def github_token(req: GithubTokenRequest):
    return _github(github_lector.guardar_token, req.texto)


@app.delete("/api/github/token")
def github_borrar_token():
    return github_lector.borrar_token()


@app.get("/api/github/buscar")
def github_buscar(q: str = "", lenguaje: str = "", orden: str = "estrellas", pagina: int = Query(default=1, ge=1, le=50),
                  estrellas_min: int = Query(default=0, ge=0), tema: str = ""):
    return _github(github_lector.buscar, q, lenguaje, orden, pagina, estrellas_min, tema)


@app.get("/api/github/repo")
def github_repo(ref: str, refrescar: bool = False):
    info = dict(_github(github_lector.abrir, ref, refrescar))
    info["explicadas"] = github_lector.explicadas(info)
    info["guardado"] = any(g["ref"] == info["ref"] for g in github_lector.guardados())
    info["local"] = github_lector.local(info["ref"], file_mgr.base_dir)
    return info


@app.get("/api/github/archivo")
def github_archivo(ref: str, ruta: str):
    return _github(github_lector.leer_archivo, ref, ruta)


def _github_con_cache(info, ruta, nivel, modelo, regenerar, generador):
    guardada = None if regenerar else github_lector.explicacion_guardada(info, ruta, nivel, modelo)
    if guardada:
        return _ndjson_en_hilo(lambda avisar: {"texto": guardada, "guardada": True})

    def trabajo(avisar):
        texto = _consumir(generador(), avisar)
        if not texto.strip():
            raise github_lector.ErrorGitHub("El modelo no devolvió nada. Prueba otra vez u otro modelo.")
        github_lector.guardar_explicacion(info, ruta, nivel, modelo, texto)
        return {"texto": texto, "guardada": False}
    return _ndjson_en_hilo(trabajo)


@app.post("/api/github/explicar")
def github_explicar(req: GithubRefRequest):
    """ Sin «ruta», el repositorio en conjunto; con ella, ese archivo """
    info = _github(github_lector.abrir, req.ref)
    motor, nombre = _motor_desafios(req.modelo, "explicar")
    modelo = _modelo_desafios(req.modelo, "explicar")
    nivel = req.nivel if req.nivel in github_lector.NIVELES else "intermedio"
    if req.ruta:
        if not any(a["ruta"] == req.ruta for a in info["archivos"]):
            raise HTTPException(status_code=400, detail="Ese archivo no está en el repositorio.")
        return _github_con_cache(info, req.ruta, nivel, modelo, req.regenerar,
                                 lambda: github_lector.explicar_archivo(motor, nombre, info, req.ruta, nivel))
    return _github_con_cache(info, None, "", modelo, req.regenerar,
                             lambda: github_lector.explicar_repo(motor, nombre, info))


@app.post("/api/github/preguntar")
def github_preguntar(req: GithubRefRequest):
    if not req.mensajes:
        raise HTTPException(status_code=400, detail="Escribe una pregunta.")
    info = _github(github_lector.abrir, req.ref)
    motor, nombre = _motor_desafios(req.modelo, "explicar")

    def trabajo(avisar):
        return {"texto": _consumir(github_lector.preguntar(motor, nombre, info, req.ruta, req.mensajes), avisar)}
    return _ndjson_en_hilo(trabajo)


@app.get("/api/github/guardados")
def github_guardados():
    return {"repos": github_lector.guardados()}


@app.post("/api/github/guardados")
def github_guardar(req: GithubRefRequest):
    return {"repos": _github(github_lector.guardar, req.ref, req.nota or "")}


@app.delete("/api/github/guardados")
def github_quitar(ref: str):
    return {"repos": github_lector.quitar(ref)}


@app.post("/api/github/descargar")
def github_descargar(req: GithubRefRequest):
    """ El repositorio en <proyecto>/github_repos/<nombre>/ (NDJSON con el progreso) """
    cancelar = threading.Event()
    with ai_engine._streams_lock:
        ai_engine.__dict__.setdefault("_cancelables", set()).add(cancelar)

    def trabajo(avisar):
        try:
            return github_lector.descargar(req.ref, file_mgr.base_dir, avisar, cancelar)
        finally:
            with ai_engine._streams_lock:
                ai_engine._cancelables.discard(cancelar)
    return _ndjson_en_hilo(trabajo)


@app.post("/api/github/exportar")
def github_exportar(req: GithubRefRequest):
    """ nota="md": la explicación en Markdown; nota="pdf": el código explicado en PDF """
    fn = github_lector.exportar_pdf if (req.nota or "pdf") == "pdf" else github_lector.exportar_markdown
    return _github(fn, req.ref, file_mgr.base_dir)


@app.get("/api/github/exportado")
def github_exportado(ruta: str, descargar: bool = False):
    raiz = os.path.realpath(os.path.join(file_mgr.base_dir, github_lector.CARPETA_EXPORT))
    real = os.path.realpath(ruta)
    if not real.startswith(raiz + os.sep) or not os.path.isfile(real):
        raise HTTPException(status_code=404, detail="No existe.")
    tipo = "application/pdf" if real.endswith(".pdf") else "text/markdown; charset=utf-8"
    return FileResponse(real, media_type=tipo, filename=os.path.basename(real),
                        content_disposition_type="attachment" if descargar else "inline")


@app.get("/api/kaggle/estado")
def kaggle_estado():
    """ Si hay cuenta conectada; nunca devuelve la clave ni el token """
    return kaggle_lector.estado()


@app.post("/api/kaggle/credenciales")
def kaggle_credenciales(req: KaggleCredencialesRequest):
    return _kaggle(kaggle_lector.guardar_credenciales, req.texto)


@app.delete("/api/kaggle/credenciales")
def kaggle_borrar_credenciales():
    return kaggle_lector.borrar_credenciales()


@app.get("/api/kaggle/buscar")
def kaggle_buscar(q: str = "", orden: str = "relevancia", pagina: int = Query(default=1, ge=1, le=100),
                  competicion: str = "", dataset: str = "", usuario: str = "", tipo: str = "",
                  votos_min: int = Query(default=0, ge=0), dias: int = Query(default=0, ge=0),
                  gpu: Optional[bool] = None, padre: str = ""):
    return _kaggle(kaggle_lector.buscar, q, orden, pagina, competicion, dataset, usuario,
                   tipo=tipo, votos_min=votos_min, dias=dias, gpu=gpu, padre=padre)


@app.get("/api/kaggle/notebook")
def kaggle_notebook(ref: str, refrescar: bool = False):
    nb = _kaggle(kaggle_lector.abrir, ref, refrescar)
    vista = kaggle_lector.vista(nb)
    vista["explicaciones"] = kaggle_lector.explicaciones(nb["ref"])
    vista["datos"] = kaggle_explorar.datos_del_notebook(nb, file_mgr.base_dir)
    try:
        vista["resumen_datos"] = kaggle_explorar.obtener_contexto_datasets_notebook(nb, file_mgr.base_dir)
    except Exception as e:
        logger.warning(f"Error obteniendo resumen de datos de {ref}: {e}")
        vista["resumen_datos"] = {"fuentes": [], "contexto_texto": ""}
    return vista


@app.post("/api/kaggle/importar")
def kaggle_importar(req: KaggleRefRequest):
    """ El .ipynb ORIGINAL en kaggle_notebooks/ del proyecto abierto """
    return _kaggle(kaggle_lector.guardar_en_workspace, req.ref, file_mgr.base_dir)


@app.get("/api/kaggle/lecturas")
def kaggle_lecturas():
    return {"lecturas": kaggle_lector.resumen_lecturas()}


def _kaggle_con_cache(nb, indice, nivel, modelo, regenerar, generador):
    """ Explicación guardada si ya existe; si no, se pide al modelo y se guarda """
    guardada = None if regenerar else kaggle_lector.explicacion_guardada(nb, indice, nivel, modelo)
    if guardada:
        if indice is not None:
            kaggle_lector.marcar_leida(nb, indice)
        return _ndjson_en_hilo(lambda avisar: {"texto": guardada, "guardada": True})

    def trabajo(avisar):
        texto = _consumir(generador(), avisar)
        if not texto.strip():
            raise kaggle_lector.ErrorKaggle("El modelo no devolvió nada. Prueba otra vez u otro modelo.")
        kaggle_lector.guardar_explicacion(nb, indice, nivel, modelo, texto)
        return {"texto": texto, "guardada": False}
    return _ndjson_en_hilo(trabajo)


def _obtener_contexto_datos(nb, req: KaggleRefRequest) -> Optional[str]:
    if not getattr(req, "incluir_datos", True):
        return None
    try:
        resumen = kaggle_explorar.obtener_contexto_datasets_notebook(nb, file_mgr.base_dir)
        return resumen.get("contexto_texto")
    except Exception as e:
        logger.warning(f"Error obteniendo contexto de datos: {e}")
        return None


@app.post("/api/kaggle/explicar")
def kaggle_explicar(req: KaggleExplicarRequest):
    nb = _kaggle(kaggle_lector.abrir, req.ref)
    motor, nombre = _motor_desafios(req.modelo, "explicar")
    modelo = _modelo_desafios(req.modelo, "explicar")
    nivel = req.nivel if req.nivel in kaggle_lector.NIVELES else "intermedio"
    if not 0 <= req.indice < len(nb["celdas"]):
        raise HTTPException(status_code=400, detail="Esa celda no existe.")
    ctx_datos = _obtener_contexto_datos(nb, req)
    return _kaggle_con_cache(nb, req.indice, nivel, modelo, req.regenerar,
                             lambda: kaggle_lector.explicar(motor, nombre, nb, req.indice, nivel, contexto_datos=ctx_datos))


@app.post("/api/kaggle/guia")
def kaggle_guia(req: KaggleRefRequest):
    nb = _kaggle(kaggle_lector.abrir, req.ref)
    motor, nombre = _motor_desafios(req.modelo, "explicar")
    ctx_datos = _obtener_contexto_datos(nb, req)
    return _kaggle_con_cache(nb, None, "", _modelo_desafios(req.modelo, "explicar"), req.regenerar,
                             lambda: kaggle_lector.guia(motor, nombre, nb, contexto_datos=ctx_datos))


@app.post("/api/kaggle/notebook/estudio_optimo")
def kaggle_estudio_optimo(req: KaggleRefRequest):
    nb = _kaggle(kaggle_lector.abrir, req.ref)
    motor, nombre = _motor_desafios(req.modelo, "explicar")
    modelo = _modelo_desafios(req.modelo, "explicar")
    ctx_datos = _obtener_contexto_datos(nb, req)
    return _kaggle_con_cache(nb, None, "estudio", modelo, req.regenerar,
                             lambda: kaggle_lector.estudio_optimo(motor, nombre, nb, contexto_datos=ctx_datos))


@app.post("/api/kaggle/preguntar")
def kaggle_preguntar(req: KagglePreguntarRequest):
    if not req.mensajes:
        raise HTTPException(status_code=400, detail="Escribe una pregunta.")
    nb = _kaggle(kaggle_lector.abrir, req.ref)
    motor, nombre = _motor_desafios(req.modelo, "explicar")
    ctx_datos = _obtener_contexto_datos(nb, req)

    def trabajo(avisar):
        return {"texto": _consumir(kaggle_lector.preguntar(motor, nombre, nb, req.indice, req.mensajes, contexto_datos=ctx_datos), avisar)}
    return _ndjson_en_hilo(trabajo)

@app.get("/api/workspace")
def get_workspace():
    return {
        "path": file_mgr.base_dir,
        "name": os.path.basename(file_mgr.base_dir) or file_mgr.base_dir
    }

@app.post("/api/workspace/open")
def open_workspace(req: OpenFolderRequest):
    res = file_mgr.set_base_dir(req.path)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    rebind_workspace(file_mgr.base_dir)
    ide.anotar_reciente(file_mgr.base_dir)
    return res

@app.post("/api/workspace/browse")
def browse_workspace():
    res = file_mgr.browse_folder_native()
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    rebind_workspace(file_mgr.base_dir)
    ide.anotar_reciente(file_mgr.base_dir)
    return res


# ===========================================================================
# Opciones de IDE: ir a archivo, buscar en archivos, renombrar, problemas…
# ===========================================================================

ide = ServiciosIDE(file_mgr)


def _ide(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ErrorIDE as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ide/archivos")
def ide_archivos():
    return ide.listar()


class IdeBuscarRequest(BaseModel):
    consulta: str
    reemplazo: Optional[str] = None
    regex: bool = False
    mayusculas: bool = False
    palabra: bool = False
    incluir: str = ""
    excluir: str = ""
    solo: Optional[List[str]] = None


@app.post("/api/ide/buscar")
def ide_buscar(req: IdeBuscarRequest):
    return _ide(ide.buscar, req.consulta, req.regex, req.mayusculas, req.palabra,
                req.incluir, req.excluir)


@app.post("/api/ide/reemplazar")
def ide_reemplazar(req: IdeBuscarRequest):
    if req.reemplazo is None:
        raise HTTPException(status_code=400, detail="Falta el texto de reemplazo.")
    return _ide(ide.reemplazar, req.consulta, req.reemplazo, req.regex, req.mayusculas,
                req.palabra, req.incluir, req.excluir, req.solo)


class IdeRenombrarRequest(BaseModel):
    path: str
    destino: str


@app.post("/api/ide/renombrar")
def ide_renombrar(req: IdeRenombrarRequest):
    return _ide(ide.renombrar, req.path, req.destino)


class IdeRutaRequest(BaseModel):
    path: str


@app.post("/api/ide/duplicar")
def ide_duplicar(req: IdeRutaRequest):
    return _ide(ide.duplicar, req.path)


@app.post("/api/ide/mostrar-en-sistema")
def ide_mostrar(req: IdeRutaRequest):
    return _ide(ide.mostrar_en_sistema, req.path)


class IdeProblemasRequest(BaseModel):
    lenguaje: str
    codigo: str


@app.post("/api/ide/problemas")
def ide_problemas(req: IdeProblemasRequest):
    return {"problemas": ide.problemas(req.lenguaje, req.codigo)}


@app.get("/api/ide/recientes")
def ide_recientes():
    return {"carpetas": ide.recientes()}


@app.delete("/api/ide/recientes")
def ide_olvidar_recientes():
    ide.olvidar_recientes()
    return {"ok": True}


@app.post("/api/ide/pantalla-completa")
def ide_pantalla_completa():
    """ La ventana nativa (pywebview) no deja al JavaScript ponerse a pantalla
    completa: se hace desde aquí, que corre en el mismo proceso que la ventana. """
    try:
        import webview
        ventanas = list(getattr(webview, "windows", []) or [])
    except Exception:
        ventanas = []
    if not ventanas:
        raise HTTPException(status_code=409, detail="No hay ventana nativa (¿abierto en el navegador?)")
    ventanas[0].toggle_fullscreen()
    return {"ok": True}


@app.get("/api/ide/acerca")
def ide_acerca():
    import platform
    return {
        "prig": "Prig IDE",
        "python": platform.python_version(),
        "sistema": f"{platform.system()} {platform.release()}",
        "ollama": _version_ollama(),
        "workspace": file_mgr.base_dir,
        "backend": os.path.dirname(os.path.abspath(__file__)),
    }

@app.get("/api/tree")
def get_tree(path: Optional[str] = None):
    return file_mgr.get_file_tree(path)

@app.get("/api/raw-file")
def get_raw_file(path: str):
    try:
        abs_path = file_mgr.resolve(path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if os.path.isfile(abs_path):
        return FileResponse(abs_path)
    raise HTTPException(status_code=404, detail="Archivo no encontrado")

@app.get("/api/file")
def read_file(path: str):
    res = file_mgr.read_file(path)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/file")
def write_file(req: FileWriteRequest):
    res = file_mgr.write_file(req.path, req.content)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/create")
def create_item(req: FileCreateRequest):
    res = file_mgr.create_item(req.path, req.is_dir)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.delete("/api/file")
def delete_item(path: str):
    res = file_mgr.delete_item(path)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

def _exec_timeout() -> int:
    try:
        return max(1, int(ai_engine.config.get("exec_timeout", 25)))
    except (TypeError, ValueError):
        return 25

@app.post("/api/run")
def run_code(req: CodeRunRequest):
    return runner.run_file(req.path, timeout=_exec_timeout(), run_id=req.run_id)

@app.post("/api/run/cancel")
def cancel_run(req: RunCancelRequest):
    """ Detiene una ejecución en curso. El cliente envía su propio run_id al lanzar,
    porque /api/run no responde hasta que el proceso termina. """
    return runner.cancel(req.run_id)

@app.post("/api/notebook/cell/run")
def run_cell(req: CellRunRequest):
    cwd = os.path.dirname(req.path) if req.path else file_mgr.base_dir
    # session_id = ruta del cuaderno: cada cuaderno conserva su propio espacio de nombres
    return runner.run_cell_code(req.code, cwd, session_id=req.path, timeout=_exec_timeout())

@app.post("/api/notebook/session/reset")
def reset_notebook_session(req: SessionResetRequest):
    return runner.reset_session(req.path)

@app.post("/api/app/shutdown")
def api_shutdown():
    """ Endpoint para solicitar el apagado seguro de análisis y procesos desde el cliente """
    cleanup_all_processes()
    return {"status": "ok", "message": "Análisis y procesos apagados correctamente."}

@app.get("/api/ai/status")
def get_ai_status():
    return ai_engine.check_ollama_status()

@app.post("/api/ai/reload")
@app.get("/api/ai/reload")
def reload_ollama():
    return ai_engine.reload_ollama()

@app.get("/api/ai/ollama/version-info")
def get_ollama_version_info():
    """ Devuelve versión actual de Ollama y comprueba si hay nueva versión en los servidores oficiales """
    current = _version_ollama()
    latest = None
    try:
        import requests as _rq
        r = _rq.get("https://api.github.com/repos/ollama/ollama/releases/latest",
                    headers={"User-Agent": "Prig-IDE"}, timeout=5)
        if r.status_code == 200:
            latest = r.json().get("tag_name", "").lstrip("v")
    except Exception:
        pass

    has_update = False
    if current != "?" and latest:
        has_update = not agent_flows.version_suficiente(current, latest)

    return {
        "current_version": current,
        "latest_version": latest or "desconocida",
        "has_update": has_update,
        "command": "curl -fsSL https://ollama.com/install.sh | sh"
    }

@app.post("/api/ai/ollama/update")
def update_ollama_stream():
    """ Descarga e instala la última versión oficial de Ollama directamente en Prig """
    import platform
    import tempfile
    import tarfile
    import time

    def emit():
        yield json.dumps({"stage": "inicio", "porcentaje": 5, "mensaje": "Iniciando proceso de actualización de Ollama..."}) + "\n"

        system = platform.system()
        if system != "Linux":
            yield json.dumps({
                "stage": "error",
                "mensaje": f"La actualización automática directa está optimizada para Linux (detectado: {system}).",
                "comando_manual": "curl -fsSL https://ollama.com/install.sh | sh"
            }) + "\n"
            return

        arch_raw = platform.machine().lower()
        if arch_raw in ("x86_64", "amd64"):
            arch = "amd64"
        elif arch_raw in ("aarch64", "arm64"):
            arch = "arm64"
        else:
            yield json.dumps({
                "stage": "error",
                "mensaje": f"Arquitectura del procesador no soportada para descarga directa: {arch_raw}.",
                "comando_manual": "curl -fsSL https://ollama.com/install.sh | sh"
            }) + "\n"
            return

        prig_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        download_url = f"https://github.com/ollama/ollama/releases/latest/download/ollama-linux-{arch}.tar.zst"
        fallback_url = f"https://ollama.com/download/ollama-linux-{arch}.tar.zst"
        legacy_tgz_url = f"https://ollama.com/download/ollama-linux-{arch}.tgz"

        yield json.dumps({"stage": "info", "porcentaje": 15, "mensaje": f"Conectando con servidores oficiales de Ollama (Linux {arch})..."}) + "\n"

        temp_tar = None
        try:
            import requests as _rq
            req_stream = None
            for url in (download_url, fallback_url, legacy_tgz_url):
                try:
                    r = _rq.get(url, stream=True, timeout=15, headers={"User-Agent": "Prig-IDE"})
                    if r.status_code == 200:
                        req_stream = r
                        break
                except Exception:
                    continue

            if not req_stream:
                yield json.dumps({
                    "stage": "error",
                    "mensaje": "No se pudo conectar a los servidores de descarga de Ollama. Usa el botón de terminal oficial de abajo.",
                    "comando_manual": "curl -fsSL https://ollama.com/install.sh | sh"
                }) + "\n"
                return

            total_len = req_stream.headers.get("Content-Length")
            total_bytes = int(total_len) if total_len and total_len.isdigit() else 0
            downloaded = 0

            suffix = ".tar.zst" if ".zst" in req_stream.url else ".tgz"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                temp_tar = f.name
                last_pct = -1
                for chunk in req_stream.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_bytes > 0:
                            pct = 15 + int((downloaded / total_bytes) * 65)
                            if pct != last_pct and pct % 5 == 0:
                                last_pct = pct
                                mb_down = round(downloaded / (1024 * 1024), 1)
                                mb_tot = round(total_bytes / (1024 * 1024), 1)
                                yield json.dumps({
                                    "stage": "descarga",
                                    "porcentaje": pct,
                                    "mensaje": f"Descargando paquete oficial ({mb_down} MB / {mb_tot} MB - {pct}%)..."
                                }) + "\n"

            yield json.dumps({"stage": "extraccion", "porcentaje": 85, "mensaje": "Desempaquetando binarios y bibliotecas en Prig..."}) + "\n"

            # Extraer sobre prig_root
            if temp_tar.endswith(".zst"):
                res = subprocess.run(["tar", "--zstd", "-xf", temp_tar, "-C", prig_root], capture_output=True, text=True)
                if res.returncode != 0:
                    subprocess.run(f"zstd -d -c '{temp_tar}' | tar -xf - -C '{prig_root}'", shell=True, check=True)
            else:
                with tarfile.open(temp_tar, "r:gz") as tar:
                    for member in tar.getmembers():
                        if member.name.startswith("/") or ".." in member.name:
                            continue
                        tar.extract(member, path=prig_root)

            ollama_bin = os.path.join(prig_root, "bin", "ollama")
            if os.path.exists(ollama_bin):
                os.chmod(ollama_bin, 0o755)
                # Sincronizar bin/bin/ollama si existe la carpeta bin/bin
                bin_bin_ollama = os.path.join(prig_root, "bin", "bin", "ollama")
                if os.path.exists(os.path.dirname(bin_bin_ollama)):
                    try:
                        shutil.copy2(ollama_bin, bin_bin_ollama)
                        os.chmod(bin_bin_ollama, 0o755)
                    except Exception:
                        pass

            # Sincronizar en ~/.local/bin si la carpeta existe
            local_bin_dir = os.path.join(os.path.expanduser("~"), ".local", "bin")
            if os.path.exists(local_bin_dir):
                local_bin_ollama = os.path.join(local_bin_dir, "ollama")
                try:
                    if os.path.islink(local_bin_ollama) or os.path.exists(local_bin_ollama):
                        os.remove(local_bin_ollama)
                    shutil.copy2(ollama_bin, local_bin_ollama)
                    os.chmod(local_bin_ollama, 0o755)
                except Exception:
                    pass

            yield json.dumps({"stage": "reinicio", "porcentaje": 95, "mensaje": "Reiniciando el servicio de Ollama..."}) + "\n"

            # Recargar y reiniciar Ollama
            ai_engine.reload_ollama()
            time.sleep(2)

            nueva_ver = _version_ollama()
            yield json.dumps({
                "stage": "fin",
                "porcentaje": 100,
                "version": nueva_ver,
                "mensaje": f"¡Ollama se ha actualizado con éxito! Versión activa: {nueva_ver}"
            }) + "\n"

        except Exception as e:
            yield json.dumps({
                "stage": "error",
                "mensaje": f"Fallo durante la actualización: {str(e)}",
                "comando_manual": "curl -fsSL https://ollama.com/install.sh | sh"
            }) + "\n"
        finally:
            if temp_tar and os.path.exists(temp_tar):
                try:
                    os.remove(temp_tar)
                except Exception:
                    pass

    return StreamingResponse(emit(), media_type="application/x-ndjson")


@app.post("/api/ai/ollama/launch-terminal-update")
def launch_terminal_update():
    """ Abre una ventana de terminal nativa para ejecutar la actualización oficial con soporte interactivo de sudo """
    import shutil
    cmd = (
        "echo '=================================================='; "
        "echo '      🚀 Actualizador Oficial de Ollama           '; "
        "echo '=================================================='; "
        "echo ''; "
        "echo 'Descargando e instalando con el script oficial...'; "
        "echo ''; "
        "curl -fsSL https://ollama.com/install.sh | sh; "
        "echo ''; "
        "echo '=================================================='; "
        "echo '✅ ¡Proceso finalizado! Ya puedes cerrar esta ventana.'; "
        "echo '=================================================='; "
        "read -p 'Presiona Enter para salir...' dummy"
    )

    candidates = [
        ["gnome-terminal", "--", "bash", "-c", cmd],
        ["x-terminal-emulator", "-e", f"bash -c \"{cmd}\""],
        ["xterm", "-e", f"bash -c \"{cmd}\""]
    ]

    for terminal_cmd in candidates:
        if shutil.which(terminal_cmd[0]):
            try:
                subprocess.Popen(terminal_cmd, start_new_session=True)
                return {"status": "ok", "message": f"Terminal abierta con {terminal_cmd[0]}"}
            except Exception:
                continue

    return {"status": "error", "message": "No se encontró un emulador de terminal compatible instalado en el sistema."}

@app.get("/api/ai/config")
def get_ai_config():
    return ai_engine.get_config()

class AIConfigUpdateRequest(BaseModel):
    ollama_url: Optional[str] = None
    agent1_model: Optional[str] = None
    agent2_model: Optional[str] = None
    agent3_model: Optional[str] = None
    designer_model: Optional[str] = None
    modelo_codigo: Optional[str] = None
    modelo_explicar: Optional[str] = None
    modelo_autocompletar: Optional[str] = None
    depth_level: Optional[str] = None
    temperature: Optional[float] = None
    num_ctx: Optional[int] = None
    num_gpu: Optional[int] = None
    num_thread: Optional[int] = None
    num_predict: Optional[int] = None
    low_vram: Optional[bool] = None
    f16_kv: Optional[bool] = None
    muestreo_del_modelo: Optional[bool] = None
    keep_alive: Optional[str] = None
    top_k: Optional[int] = None
    top_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    exec_timeout: Optional[int] = None

@app.post("/api/ai/config")
def update_ai_config(req: AIConfigUpdateRequest):
    data = req.model_dump(exclude_unset=True)
    return ai_engine.update_config(data)

@app.get("/api/ai/catalog")
def get_ai_catalog():
    """ Devuelve el catálogo completo de modelos soportados de Prig (incluyendo qwen3:14b),
    cruzado con la disponibilidad local en Ollama """
    try:
        detalle = ai_engine.get_detailed_models().get("models", [])
    except Exception:
        detalle = []
    tamanos = {m["name"]: m.get("size_gb") or 0 for m in detalle}
    instalados = set(tamanos)

    lista = []
    for nombre, info in agent_flows.MODELOS.items():
        instalado = nombre in instalados or f"{nombre}:latest" in instalados
        lista.append({
            "name": nombre,
            "familia": info.get("familia", ""),
            "vram_gb": info.get("vram_gb", 0),
            "razona": info.get("razona", 0),
            "piensa": info.get("piensa", "no"),
            "fuerte_en": info.get("fuerte_en", []),
            "nota": info.get("nota", ""),
            "instalado": instalado,
            "size_gb": tamanos.get(nombre) or tamanos.get(f"{nombre}:latest") or info.get("vram_gb", 0)
        })
    return {"catalog": lista}


@app.get("/api/system/stats")
def get_system_stats():
    import subprocess
    
    cpu_pct = 0
    ram_pct = 0
    ram_used_gb = 0.0
    ram_total_gb = 0.0

    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        ram_pct = mem.percent
        ram_used_gb = round(mem.used / (1024**3), 1)
        ram_total_gb = round(mem.total / (1024**3), 1)
    except Exception:
        pass

    gpu_info = {"has_gpu": False, "gpu_pct": 0, "vram_used_mb": 0, "vram_total_mb": 0}

    # NVML primero: la barra de estado pregunta cada 3 s y un nvidia-smi por vez calentaba la CPU
    try:
        from recursos import nvml
        por_nvml = nvml.lectura()
    except Exception:
        por_nvml = None
    if por_nvml:
        g = por_nvml[0]
        return {"cpu_pct": cpu_pct, "ram_pct": ram_pct, "ram_used_gb": ram_used_gb, "ram_total_gb": ram_total_gb,
                "gpu": {"has_gpu": True, "gpu_pct": g["uso_pct"] or 0, "vram_used_mb": g["vram_usada_mb"] or 0,
                        "vram_total_mb": g["vram_total_mb"] or 0}}

    try:
        res = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=1
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().split(',')]
            gpu_info = {
                "has_gpu": True,
                "gpu_pct": int(parts[0]),
                "vram_used_mb": int(parts[1]),
                "vram_total_mb": int(parts[2])
            }
    except Exception:
        pass

    return {
        "cpu_pct": cpu_pct,
        "ram_pct": ram_pct,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "gpu": gpu_info
    }

class ModelDeleteRequest(BaseModel):
    model: str

@app.get("/api/ai/models")
def get_ai_models():
    status = ai_engine.check_health()
    return {"models": status.get("models", [])}

@app.get("/api/ai/models/detailed")
def get_detailed_models():
    return ai_engine.get_detailed_models()

@app.post("/api/ai/models/delete")
def delete_ai_model(req: ModelDeleteRequest):
    success = ai_engine.delete_model(req.model)
    return {"status": "success" if success else "error", "model": req.model}

@app.post("/api/ai/pull")
def pull_model(req: ModelPullRequest):
    def event_stream():
        try:
            for status_msg in ai_engine.pull_model(req.model):
                yield status_msg
        except Exception as e:
            yield f"Error en el servidor backend: {str(e)}\n"
    return StreamingResponse(event_stream(), media_type="text/plain")

@app.post("/api/ai/workflow/run")
def run_workflow(req: WorkflowRequest):
    def event_stream():
        # Detectar si el workflow usa características v2 (bucles, tipos de nodo, router o grafo)
        es_v2 = bool(req.grafo or req.nodos or any((s.loop or (s.tipo and s.tipo != "agent") or s.herramienta) for s in (req.steps or [])))
        
        if es_v2:
            if req.grafo:
                grafo = req.grafo
            elif req.nodos:
                grafo = {"nodos": req.nodos, "nodo_inicial": req.nodos[0].get("id", "step_1")}
            else:
                nodos = []
                for idx, s in enumerate(req.steps or []):
                    sid = s.id or f"step_{idx+1}"
                    next_id = (s.next_node or (f"step_{idx+2}" if idx + 1 < len(req.steps) else None))
                    nodos.append({
                        "id": sid,
                        "nombre": s.name or f"Agente {idx+1}",
                        "tipo": s.tipo or "agent",
                        "rol": s.role or "programmer",
                        "modelo": s.model,
                        "prompt": s.prompt,
                        "temperature": s.temperature,
                        "system_prompt": s.system_prompt,
                        "loop": s.loop,
                        "routing_rules": s.routing_rules,
                        "herramienta": s.herramienta,
                        "next_node": next_id
                    })
                grafo = {"nodos": nodos, "nodo_inicial": nodos[0]["id"] if nodos else None}
            
            motor_v2 = _motor_flujos_v2()
            for evento in motor_v2.ejecutar_grafo(grafo, entrada_inicial=req.initial_input):
                yield json.dumps(evento, ensure_ascii=False) + "\n"
            return

        # Modo secuencial clásico si no hay bucles ni herramientas complejas
        current_context = req.initial_input
        for idx, step in enumerate(req.steps or []):
            yield json.dumps({"step": idx, "status": "running", "model": step.model, "name": step.name}) + "\n"
            
            prompt = f"{step.prompt}\n\nContexto / Input Anterior:\n{current_context}"
            result = ai_engine.run_workflow_step(
                prompt=prompt, 
                model=step.model, 
                role=step.role,
                temperature=step.temperature,
                custom_sys_prompt=step.system_prompt
            )
            
            current_context = result
            yield json.dumps({"step": idx, "status": "completed", "result": result, "name": step.name}) + "\n"
            
        yield json.dumps({"status": "finished", "final_result": current_context}) + "\n"
        
    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

class AIInlineCompleteRequest(BaseModel):
    code_prefix: str
    code_suffix: str = ""
    model: Optional[str] = None

@app.post("/api/ai/search")
def search_web(req: AISearchRequest):
    context, sources = ai_engine.web_search.get_web_context(req.query)
    return {"context": context, "sources": sources}

def _modelo_autocompletado(pedido: Optional[str]) -> Optional[str]:
    """ Un modelo con la capacidad `insert` (rellenar al medio): el pedido si la tiene,
    si no el más pequeño instalado que la tenga, para que responda rápido. """
    if pedido and "insert" in ai_engine.capacidades(pedido):
        return pedido
    try:
        candidatos = []
        for m in requests_lib.get(f"{ai_engine.base_url}/api/tags", timeout=5).json().get("models", []):
            if "insert" in ai_engine.capacidades(m["name"]):
                candidatos.append((m.get("size", 0), m["name"]))
        return min(candidatos)[1] if candidatos else None
    except Exception:
        return None


@app.post("/api/ai/inline-complete")
def inline_complete(req: AIInlineCompleteRequest):
    # Con lo que hay DESPUÉS del cursor el modelo rellena el medio (verificado con
    # qwen2.5-coder: completó el cuerpo de una función que ya tenía su return)
    elegido = ai_engine.modelo_para("autocompletar", req.model)
    if elegido and "insert" not in ai_engine.capacidades(elegido):
        # El elegido no sabe rellenar al medio: se respeta la elección y completa la línea
        modelo_fim = None
    else:
        modelo_fim = _modelo_autocompletado(elegido)
    if modelo_fim:
        payload = {"model": modelo_fim, "prompt": req.code_prefix[-4000:], "suffix": req.code_suffix[:2000],
                   "stream": False,
                   "options": ai_engine._build_options({"num_predict": 64, "temperature": 0.2, "stop": ["\n\n"]},
                                                       modelo_fim, "autocompletado")}
        ai_engine._completar_payload(payload, modelo_fim, "autocompletado", False, "")
        try:
            r = requests_lib.post(f"{ai_engine.base_url}/api/generate", json=payload, timeout=30)
            texto = (r.json().get("response") or "") if r.status_code == 200 else ""
            return {"completion": texto.rstrip(), "modelo": modelo_fim, "relleno_al_medio": True}
        except Exception:
            return {"completion": ""}
    prefix = req.code_prefix[-600:]
    prompt = f"Completa la siguiente línea de código de forma exacta y concisa:\n```python\n{prefix}"
    sys_prompt = "Eres un motor de autocompletado de código en tiempo real. Devuelve ÚNICAMENTE la sintaxis faltante de la siguiente línea de código sin explicaciones, formato markdown ni intros."
    
    completion_parts = []
    try:
        for chunk in ai_engine.generate_response(prompt, model=elegido or "qwen2.5-coder:7b", system_prompt=sys_prompt,
                                                 uso="autocompletado"):
            completion_parts.append(chunk)
            if len("".join(completion_parts)) > 100:
                break
        raw = "".join(completion_parts).strip().replace("```python", "").replace("```", "")
        completion = raw.split("\n")[0] if raw else ""
        return {"completion": completion}
    except Exception:
        return {"completion": ""}

@app.post("/api/ai/inline-prompt")
def ai_inline_prompt(req: AIInlinePromptRequest):
    """
    Ejecuta una instrucción 'Prig//: <prompt>' directamente dentro del archivo de código.
    Devuelve el código generado listo para insertarse en esa posición exacta.
    """
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Debes escribir una instrucción después de 'Prig//: '")

    # 1. Intentar autoiniciar Ollama si está apagado
    try:
        if not ai_engine.is_online():
            ai_engine.try_autostart_ollama()
    except Exception:
        pass

    # 2. Reconstruir contexto de código
    indent = ""
    if req.file_content:
        lines = req.file_content.splitlines()
        line_num = req.line_number or 1
        line_idx = max(0, min(line_num - 1, len(lines) - 1)) if lines else 0
        current_line = lines[line_idx] if lines else ""
        indent_match = re.match(r"^(\s*)", current_line)
        indent = indent_match.group(1) if indent_match else ""
        start_line = max(0, line_idx - 40)
        end_line = min(len(lines), line_idx + 40)
        context_before = "\n".join(lines[start_line:line_idx])
        context_after = "\n".join(lines[line_idx + 1:end_line])
    else:
        context_before = req.prefix_code or ""
        context_after = req.suffix_code or ""
        if context_before:
            for l in reversed(context_before.splitlines()):
                if l.strip():
                    m = re.match(r"^(\s*)", l)
                    if m:
                        indent = m.group(1)
                    break

    lang = req.language or "python"
    filename = req.file_path or f"archivo.{lang}"

    system_prompt = (
        f"Eres Prig AI, un asistente experto de programación integrado directamente en el editor de código.\n"
        f"El usuario ha escrito una instrucción en un comentario 'Prig//: ' en el archivo '{filename}'.\n"
        f"Tu tarea es generar ÚNICAMENTE el código en {lang} que cumple la instrucción para insertarse en esa posición.\n"
        f"REGLAS CRÍTICAS:\n"
        f"1. Devuelve SOLAMENTE el código fuente válido en {lang}.\n"
        f"2. NO devuelvas explicaciones, texto introductorio ni conclusiones en prosa.\n"
        f"3. Si usas bloques markdown de código (```), asegúrate de que solo contengan el código solicitado.\n"
        f"4. Mantén la coherencia con las variables, funciones e importaciones del código circundante.\n"
        f"5. Ajusta la indentación para que encaje de forma natural en el archivo."
    )

    user_prompt = (
        f"Archivo: {filename} (Lenguaje: {lang})\n\n"
        f"--- Código previo a la instrucción ---\n{context_before}\n\n"
        f"--- INSTRUCCIÓN DEL USUARIO ---\n{req.prompt}\n\n"
        f"--- Código posterior a la instrucción ---\n{context_after}\n\n"
        f"Genera el código correspondiente para cumplir la instrucción en esa posición:"
    )

    # 3. Determinar el modelo local o fallback seguro
    raw_model = ai_engine.modelo_para("codigo", req.model) or ai_engine.config.get("agent1_model") or "qwen2.5-coder:7b"
    clean_model = (raw_model or "qwen2.5-coder:7b").split(" (")[0].strip()

    # Comprobar modelos instalados en Ollama para no lanzar 404
    try:
        r = requests_lib.get(f"{ai_engine.base_url}/api/tags", timeout=2)
        if r.status_code == 200:
            installed = [m.get("name") for m in r.json().get("models", [])]
            if installed:
                matched = any(clean_model in m or m in clean_model for m in installed)
                if not matched:
                    coders = [m for m in installed if "coder" in m or "code" in m or "qwen" in m]
                    clean_model = coders[0] if coders else installed[0]
    except Exception:
        pass

    try:
        chunks = []
        for chunk in ai_engine.generate_response(user_prompt, model=clean_model, system_prompt=system_prompt, uso="programador"):
            chunks.append(chunk)
        raw_code = "".join(chunks).strip()

        if raw_code.startswith("[Error Ollama:") or raw_code.startswith("[Error:"):
            raise RuntimeError(raw_code)

        # Limpiar posibles bloques markdown ```lang ... ```
        if "```" in raw_code:
            match = re.search(r"```(?:\w+)?\n?(.*?)\n?```", raw_code, re.DOTALL)
            if match:
                raw_code = match.group(1).strip()
            else:
                raw_code = raw_code.replace("```", "").strip()

        # Ajustar indentación
        code_lines = raw_code.splitlines()
        adjusted_lines = []
        for l in code_lines:
            if l.strip():
                if not l.startswith(indent):
                    adjusted_lines.append(indent + l)
                else:
                    adjusted_lines.append(l)
            else:
                adjusted_lines.append("")
        final_code = "\n".join(adjusted_lines)

        return {
            "status": "ok",
            "code": final_code,
            "prompt": req.prompt,
            "line_number": req.line_number or 1,
            "model_used": clean_model
        }
    except Exception as e:
        err_str = str(e)
        if "Connection refused" in err_str or "Failed to establish a new connection" in err_str:
            raise HTTPException(
                status_code=503,
                detail="Ollama no está en marcha o no responde en el puerto 11434. Inicia Ollama ('ollama serve') para usar el autocompletado con IA."
            )
        raise HTTPException(status_code=500, detail=f"Error al generar código: {err_str}")

def _formatear_gancho(hooked_files: Optional[List[Dict[str, str]]]) -> str:
    if not hooked_files:
        return ""
    bloques = []
    for f in hooked_files:
        r = f.get("path", "archivo")
        c = f.get("content", "")
        bloques.append(f"### Archivo: {r}\n```\n{c}\n```")
    return (
        "ARCHIVOS ENGANCHADOS POR EL USUARIO (GANCHO):\n"
        "El usuario ha seleccionado estos archivos del proyecto para que tengas acceso directo y puedas navegar y escribir código sobre ellos.\n"
        "Cuando propongas cambios, correcciones o nuevo código para estos archivos, indica siempre el archivo de destino con el encabezado '### Archivo: <ruta>' justo antes del bloque de código correspondiente:\n\n"
        + "\n\n".join(bloques)
    )

def _formatear_citas(citas: Optional[List[Dict[str, Any]]] = None, citas_lib: Optional[List[Dict[str, Any]]] = None) -> str:
    todas = []
    if isinstance(citas, list):
        for c in citas:
            copia = dict(c)
            if citas_lib is not None:
                copia.setdefault("tipo", "libro")
            todas.append(copia)
    if isinstance(citas_lib, list):
        for c in citas_lib:
            copia = dict(c)
            copia.setdefault("tipo", "libreria")
            todas.append(copia)

    if not todas:
        return ""

    lineas = []
    for c in todas:
        tipo = c.get("tipo", "libro")
        if tipo == "libreria":
            lib = c.get("libreria", "Librería")
            func = c.get("funcion") or c.get("funcion_o_clase") or c.get("tema") or "API"
            snip = c.get("snippet") or c.get("codigo_ejemplo") or ""
            exp = c.get("explicacion", "")
            lineas.append(f"- [Librería {lib} | API/Función: {func}]\n  Explicación: {exp}\n  Snippet de código verificado:\n  ```python\n  {snip}\n  ```")
        else:
            libro = c.get("titulo") or c.get("libro", "Libro")
            pag = c.get("pagina", "?")
            txt = c.get("texto", "")
            nota = c.get("nota", "")
            tags = ", ".join(c.get("tags", [])) if isinstance(c.get("tags"), list) else str(c.get("tags", ""))
            lineas.append(f"- [Libro: {libro} | Pág. {pag} | Tags: {tags}]\n  Cita: \"{txt}\"" + (f"\n  Nota del usuario: {nota}" if nota else ""))
    return (
        "CITAS BIBLIOGRÁFICAS Y DE LIBRERÍAS CARGADAS (FUNDAMENTACIÓN):\n"
        "El usuario ha aportado estas citas extraídas de libros y documentación oficial de librerías.\n"
        "Razona sobre ellas y fundamenta tu respuesta citando expresamente el libro, la página o la librería correspondiente para enriquecer tu explicación técnica y teórica:\n\n"
        + "\n\n".join(lineas)
    )

@app.post("/api/ai/chat")
def ai_chat(req: AIChatRequest):
    sys_prompt = ai_engine.get_tutor_system_prompt(req.mode)
    prompt = req.prompt

    citas_contexto = _formatear_citas(req.selected_citations)
    if not citas_contexto:
        try:
            auto_citas = []
            auto_citas.extend(book_service.get_all_citations_for_ai(req.prompt, max_results=4))
            auto_citas.extend(librerias_service.get_all_library_citations_for_ai(req.prompt, max_results=3))
            if auto_citas:
                citas_contexto = _formatear_citas(auto_citas)
        except Exception:
            pass

    if citas_contexto:
        prompt = f"{citas_contexto}\n\n{prompt}"

    gancho_contexto = _formatear_gancho(req.hooked_files)
    if gancho_contexto:
        prompt = f"{gancho_contexto}\n\n{prompt}"
    if req.code_context:
        prompt = f"```\n{req.code_context}\n```\n\n{prompt}"

    if req.eventos:
        return StreamingResponse(_chat_eventos(req, prompt, sys_prompt), media_type="application/x-ndjson")

    def event_stream():
        should_web_search = req.use_web or ai_engine.web_search.should_auto_search(req.prompt)
        if should_web_search:
            for chunk in ai_engine.generate_response_with_web_search(prompt, req.model, sys_prompt):
                yield chunk
        else:
            for chunk in ai_engine.generate_response(prompt, req.model, sys_prompt, uso="tutor"):
                yield chunk

    return StreamingResponse(event_stream(), media_type="text/plain")


def _chat_eventos(req: AIChatRequest, prompt: str, sys_prompt: str):
    fuentes = []
    if req.use_web or ai_engine.web_search.should_auto_search(req.prompt):
        try:
            contexto_web, fuentes = ai_engine.web_search.get_web_context(req.prompt)
            if contexto_web:
                prompt = f"{prompt}\n\n{contexto_web}"
        except Exception:
            fuentes = []
    mensajes = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}]
    if req.continuar:
        mensajes.append({"role": "assistant", "content": req.continuar})
    herramientas = None
    if req.herramientas:
        herramientas = Herramientas(knowledge_base, file_mgr, ide, runner,
                                    permitir_codigo=req.permitir_codigo, timeout=_exec_timeout())
    for evento in ai_engine.chat_eventos(mensajes, req.model, "tutor", think=req.think,
                                         logprobs=max(0, min(int(req.logprobs or 0), 5)),
                                         herramientas=herramientas,
                                         gobernador=recursos_termico.gobernador()):
        if evento.get("t") == "herramienta":
            evento["etiqueta"] = ETIQUETAS_HERRAMIENTAS.get(evento.get("nombre"), evento.get("nombre"))
        yield json.dumps(evento, ensure_ascii=False, default=str) + "\n"
    if fuentes:
        texto = "\n\n---\n**Fuentes consultadas:**\n" + "".join(f"- [{f['title']}]({f['url']})\n" for f in fuentes)
        yield json.dumps({"t": "texto", "v": texto}, ensure_ascii=False) + "\n"

# ==========================================
# ENDPOINTS: SISTEMA DE PLAN DE ESTUDIO (3 AGENTES ESPECIALISTAS)
# ==========================================

class StudyPlanInitRequest(BaseModel):
    user_goal: str

class StudyPlanAgentRunRequest(BaseModel):
    plan_id: str
    model: str = "qwen2.5-coder:7b"

class StudyPlanApproveRequest(BaseModel):
    plan_id: str
    step: str # "knowledge" | "practical" | "learning"

class StudyPlanChangeRequestInput(BaseModel):
    plan_id: str
    user_prompt: str
    model: str = "qwen2.5-coder:7b"

@app.post("/api/study-plan/init")
def init_study_plan(req: StudyPlanInitRequest):
    state = study_plan_engine.create_new_plan(req.user_goal)
    return state.model_dump()

@app.get("/api/study-plan/list")
def list_study_plans():
    return study_plan_engine.list_all_plans()

@app.get("/api/study-plan/state/{plan_id}")
def get_study_plan_state(plan_id: str, version: Optional[int] = Query(default=None)):
    state = study_plan_engine.load_state(plan_id, version)
    if not state:
        raise HTTPException(status_code=404, detail="Plan de estudio no encontrado.")
    return state.model_dump()

@app.delete("/api/study-plan/{plan_id}")
def delete_study_plan(plan_id: str):
    success = study_plan_engine.delete_plan(plan_id)
    if not success:
        raise HTTPException(status_code=404, detail="Plan no encontrado para eliminar.")
    return {"status": "deleted", "plan_id": plan_id}


@app.post("/api/study-plan/agent1")
def run_agent1_knowledge_architect(req: StudyPlanAgentRunRequest):
    state = study_plan_engine.load_state(req.plan_id)
    if not state:
        raise HTTPException(status_code=404, detail="Plan no encontrado.")

    library_items = book_service.list_books()
    
    try:
        raw_kmap = ai_engine.run_knowledge_architect(state.user_goal, library_items, model=req.model)
        kmap = KnowledgeMap.model_validate(raw_kmap)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar Agente 1 (Knowledge Architect): {str(err)}")
    
    # Validación Determinista Cruzada con PlanValidator
    warnings = PlanValidator.validate_knowledge_map(kmap, library_items)

    state.knowledge_map = kmap
    state.status = PlanStatusEnum.KNOWLEDGE_REVIEW
    
    steps = [
        TraceStep(step="ANALYZING_GOAL", message=f"Objetivo analizado: '{state.user_goal}'"),
        TraceStep(step="SCANNING_LIBRARY", message=f"Fuentes escaneadas en Biblioteca: {len(library_items)} ítems"),
        TraceStep(step="EXTRACTING_CONCEPTS", message="Conceptos y matriz de dependencias extraída con evidencias"),
        TraceStep(step="BUILDING_KNOWLEDGE_MAP", message="KNOWLEDGE_MAP construido exitosamente")
    ]
    if warnings:
        steps.append(TraceStep(step="PLAN_VALIDATOR_CHECK", message=f"⚠️ PlanValidator detectó {len(warnings)} advertencias de IDs: {'; '.join(warnings)}", status="WARNING"))
    else:
        steps.append(TraceStep(step="PLAN_VALIDATOR_CHECK", message="✅ PlanValidator: Validación cruzada de IDs 100% Correcta", status="DONE"))

    trace = DecisionTrace(
        agent_name="Knowledge Architect",
        status="COMPLETED",
        steps=steps,
        stats={
            "sources_scanned": len(library_items),
            "domains_count": len(kmap.domains),
            "prerequisites_count": len(kmap.prerequisites),
            "validator_warnings": len(warnings)
        }
    )
    state.decision_traces.append(trace)
    study_plan_engine.save_state(state)
    return state.model_dump()

@app.post("/api/study-plan/agent2")
def run_agent2_practice_architect(req: StudyPlanAgentRunRequest):
    state = study_plan_engine.load_state(req.plan_id)
    if not state or not state.knowledge_map:
        raise HTTPException(status_code=400, detail="Se requiere aprobar o ejecutar el Módulo 1 (KnowledgeMap) primero.")

    try:
        raw_curr = ai_engine.run_practice_architect(state.knowledge_map.model_dump(), model=req.model)
        curr = PracticalCurriculum.model_validate(raw_curr)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar Agente 2 (Practice Architect): {str(err)}")

    # Validación Determinista Cruzada con PlanValidator (Conceptos vs KnowledgeMap)
    warnings = PlanValidator.validate_practical_curriculum(curr, state.knowledge_map)


    state.practical_curriculum = curr
    state.status = PlanStatusEnum.PRACTICAL_REVIEW

    steps = [
        TraceStep(step="RECEIVING_KNOWLEDGE_MAP", message="KNOWLEDGE_MAP procesado"),
        TraceStep(step="BUILDING_PRACTICAL_MODULES", message=f"Creados {len(curr.modules)} módulos de objetivos prácticos"),
        TraceStep(step="DEFINING_VALIDATION_CRITERIA", message="Criterios de validación del estudiante (validation_criteria) establecidos")
    ]
    if warnings:
        steps.append(TraceStep(step="PLAN_VALIDATOR_CHECK", message=f"⚠️ PlanValidator: {'; '.join(warnings)}", status="WARNING"))
    else:
        steps.append(TraceStep(step="PLAN_VALIDATOR_CHECK", message="✅ PlanValidator: Coincidencia cruzada de concept_ids 100% Correcta", status="DONE"))

    trace = DecisionTrace(
        agent_name="Practice & Curriculum Architect",
        status="COMPLETED",
        steps=steps,
        stats={"modules_count": len(curr.modules), "objectives_count": len(curr.objectives), "validator_warnings": len(warnings)}
    )
    state.decision_traces.append(trace)
    study_plan_engine.save_state(state)
    return state.model_dump()

@app.post("/api/study-plan/agent3")
def run_agent3_notebook_manager(req: StudyPlanAgentRunRequest):
    state = study_plan_engine.load_state(req.plan_id)
    if not state or not state.practical_curriculum:
        raise HTTPException(status_code=400, detail="Se requiere ejecutar el Módulo 2 (PracticalCurriculum) primero.")

    library_items = book_service.list_books()
    code_items = [b for b in library_items if b.get("category_id") in ["code", "notebooks"] or b.get("ext") in ["py", "ipynb"]]

    try:
        raw_exec = ai_engine.run_notebook_manager(state.practical_curriculum.model_dump(), code_items, model=req.model)
        exec_plan = ExecutableLearningPlan.model_validate(raw_exec)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar Agente 3 (Notebook Manager): {str(err)}")

    # Validación Determinista Cruzada
    warnings = PlanValidator.validate_executable_plan(exec_plan, state.practical_curriculum)


    # Ejecutar duplicación física de cuadernos fuera de la biblioteca e inyección de celdas explicativas
    workspace_notebooks_dir = os.path.join(study_plan_engine.workspace_dir, "notebooks_plan")
    os.makedirs(workspace_notebooks_dir, exist_ok=True)

    curr_modules_dict = {m.module_id: m for m in state.practical_curriculum.modules} if state.practical_curriculum else {}

    for mod in exec_plan.modules_notebooks:
        curr_mod = curr_modules_dict.get(mod.module_id)
        mod_name = curr_mod.name if curr_mod else mod.module_name
        mod_obj = curr_mod.objective if curr_mod else "Practicar los conceptos del módulo"
        val_criteria = curr_mod.validation_criteria if curr_mod else []

        for nb in mod.notebooks:
            dest_file_name = f"{mod.module_id}_{nb.notebook_id}.ipynb"
            dest_path = os.path.join(workspace_notebooks_dir, dest_file_name)
            
            source_code = ""
            if nb.source_library_notebook and os.path.exists(nb.source_library_notebook):
                try:
                    with open(nb.source_library_notebook, 'r', encoding='utf-8', errors='ignore') as sf:
                        source_code = sf.read()
                except Exception:
                    pass

            nb_content = NotebookSafetyLayer.generate_explained_notebook_content(
                module_name=mod_name,
                objective=mod_obj,
                validation_criteria=val_criteria,
                source_code=source_code
            )

            try:
                written_path = NotebookSafetyLayer.write_executable_notebook(dest_path, nb_content)
                nb.executable_path = written_path
                nb.is_original_protected = True
                nb.line_by_line_explanations_added = True
                nb.validation_tests_included = True
            except Exception as err:
                print("Advertencia en generación de cuaderno:", err)


    state.executable_learning_plan = exec_plan
    state.status = PlanStatusEnum.LEARNING_REVIEW

    steps = [
        TraceStep(step="SCANNING_LIBRARY_CODE", message=f"Archivos de código analizados: {len(code_items)}"),
        TraceStep(step="PHYSICAL_COPY_ENFORCEMENT", message="🔒 Copias editables generadas fuera de ~/.prig_books/ (Originales 100% Protegidos)"),
        TraceStep(step="PLAN_READY", message="EXECUTABLE_LEARNING_PLAN generado exitosamente")
    ]
    if warnings:
        steps.append(TraceStep(step="PLAN_VALIDATOR_CHECK", message=f"⚠️ PlanValidator: {'; '.join(warnings)}", status="WARNING"))
    else:
        steps.append(TraceStep(step="PLAN_VALIDATOR_CHECK", message="✅ PlanValidator: Validación de cuadernos y módulos 100% Correcta", status="DONE"))

    trace = DecisionTrace(
        agent_name="Notebook & Learning Manager",
        status="COMPLETED",
        steps=steps,
        stats={
            "notebooks_copied": exec_plan.total_notebooks_copied_and_edited,
            "notebooks_created": exec_plan.total_notebooks_created,
            "validator_warnings": len(warnings)
        }
    )
    state.decision_traces.append(trace)
    study_plan_engine.save_state(state)
    return state.model_dump()


@app.post("/api/study-plan/approve")
def approve_study_plan_step(req: StudyPlanApproveRequest):
    steps = {
        "knowledge": study_plan_engine.approve_knowledge_step,
        "practical": study_plan_engine.approve_practical_step,
        "learning": study_plan_engine.approve_learning_step,
    }
    handler = steps.get(req.step)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Paso de aprobación no válido: {req.step}")
    try:
        state = handler(req.plan_id)
    except ValueError as err:
        # Plan inexistente o transición de estado no permitida: es un error del cliente
        raise HTTPException(status_code=400, detail=str(err))
    return state.model_dump()

@app.post("/api/study-plan/change-request")
def handle_change_request(req: StudyPlanChangeRequestInput):
    state = study_plan_engine.load_state(req.plan_id)
    if not state:
        raise HTTPException(status_code=404, detail="Plan no encontrado.")

    try:
        # Asistente Diseñador interpreta la solicitud del usuario en un ChangeRequest estructurado
        raw_cr = ai_engine.interpret_change_request(req.user_prompt, state.status.value, model=req.model)
        cr = ChangeRequest(
            target_agent=raw_cr.get("target_agent", "KNOWLEDGE_ARCHITECT"),
            action=raw_cr.get("action", ActionEnum.ADD_PREREQUISITE),
            target=raw_cr.get("target", "General"),
            parameter=raw_cr.get("parameter", ""),
            user_prompt=req.user_prompt,
            reason=raw_cr.get("reason", "Solicitud del usuario")
        )
        updated_state = study_plan_engine.apply_change_request(req.plan_id, cr)
        return updated_state.model_dump()
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error al procesar solicitud de cambio: {str(err)}")


class ToggleCriterionRequest(BaseModel):
    plan_id: str
    module_id: str
    criterion_text: str

class ToggleNotebookRequest(BaseModel):
    plan_id: str
    notebook_id: str

@app.post("/api/study-plan/progress/toggle-criterion")
def toggle_criterion_progress(req: ToggleCriterionRequest):
    try:
        state = study_plan_engine.toggle_validation_criterion(req.plan_id, req.module_id, req.criterion_text)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))
    return state.model_dump()

@app.post("/api/study-plan/progress/toggle-notebook")
def toggle_notebook_progress(req: ToggleNotebookRequest):
    try:
        state = study_plan_engine.toggle_notebook_completion(req.plan_id, req.notebook_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))
    return state.model_dump()

class SeguimientoGenerateRequest(BaseModel):
    goal: str
    topics: str
    level: str = "Intermedio"
    focus: str = "Práctico"
    model: str = "qwen2.5-coder:7b"

@app.post("/api/seguimiento/generate")
def generate_seguimiento_path(req: SeguimientoGenerateRequest):
    """ OBSOLETO: usa /api/guided/generate. Se mantiene por compatibilidad. """
    try:
        raw_path = ai_engine.run_topic_organizer(req.goal, req.topics, level=req.level, focus=req.focus, model=req.model)
        path_obj = SeguimientoPath.model_validate(raw_path)
        path_obj.goal = req.goal
        path_obj.topics_raw = req.topics
        seguimiento_repo.save(path_obj)
        return path_obj.model_dump()
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error al generar el seguimiento: {str(err)}")

@app.get("/api/seguimiento/list")
def list_seguimientos():
    """ OBSOLETO: usa /api/guided/list. """
    return seguimiento_repo.list_all()

@app.get("/api/seguimiento/{seg_id}")
def get_seguimiento(seg_id: str):
    path_obj = seguimiento_repo.load(seg_id)
    if not path_obj:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")
    return path_obj.model_dump()

@app.delete("/api/seguimiento/{seg_id}")
def delete_seguimiento(seg_id: str):
    success = seguimiento_repo.delete(seg_id)
    if not success:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")
    return {"status": "deleted", "id": seg_id}

class SeguimientoExplainRequest(BaseModel):
    goal: str
    block: dict
    model: str = "qwen2.5-coder:7b"
    use_web: bool = True

@app.post("/api/guided/explain")
@app.post("/api/seguimiento/explain")
def explain_seguimiento_block(req: SeguimientoExplainRequest):
    def generator():
        try:
            for chunk in ai_engine.explain_seguimiento_block(req.goal, req.block, model=req.model, use_web=req.use_web):
                yield chunk
        except Exception as e:
            yield f"\n[Error: {str(e)}]"
            
    return StreamingResponse(generator(), media_type="text/plain")

class SeguimientoQuizRequest(BaseModel):
    goal: str
    block: dict
    model: str = "qwen2.5-coder:7b"

@app.post("/api/guided/quiz")
@app.post("/api/seguimiento/quiz")
def generate_seguimiento_quiz(req: SeguimientoQuizRequest):
    try:
        quiz = ai_engine.generate_block_quiz(req.goal, req.block, model=req.model)
        return quiz
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error al generar quiz: {str(err)}")


class SeguimientoChallengeRequest(BaseModel):
    goal: str
    block: dict
    model: str = "qwen2.5-coder:7b"

class SeguimientoVerifySolutionRequest(BaseModel):
    goal: str
    block: dict
    user_code: str
    model: str = "qwen2.5-coder:7b"
    exercise_id: Optional[str] = None

@app.post("/api/guided/challenge")
@app.post("/api/seguimiento/challenge")
def get_block_challenge(req: SeguimientoChallengeRequest):
    """ Reto del bloque como ejercicio VERIFICADO.

    Antes el reto era texto libre y la corrección se la pedíamos al modelo. Ahora se
    genera con el mismo motor que el resto: tests ocultos y comprobación ejecutando.
    Si el motor no logra uno válido, se cae al reto antiguo para no dejar al alumno
    sin nada, avisando de que ese no se puede corregir automáticamente.
    """
    topics = ", ".join(req.block.get("topics", [])) or req.block.get("title", "")
    concepto = f"{req.block.get('title', '')} ({topics})".strip()

    try:
        result = exercise_engine.generate_validated(concepto, model=req.model, attempts=3)
    except Exception as err:
        result = {"ok": False, "error": str(err)}

    if result.get("ok"):
        exercise = result["exercise"]
        exercise_store.save(exercise)
        if flags.is_enabled("learning_telemetry"):
            telemetry.record(exercise["exercise_id"], concepto, "generated",
                             attempt_num=exercise.get("attempts_used", 1))

        public = ExerciseEngine.public_view(exercise)
        return {
            "verified": True,
            "exercise_id": public["exercise_id"],
            "challenge_title": public["title"],
            "instructions": public["statement"],
            "starter_code": public["starter_code"],
            "function_name": public["function_name"],
            "expected_output_hint": f"Debe definir {public['function_name']} y pasar los tests ocultos.",
        }

    # Reserva sin verificación automática
    try:
        challenge = ai_engine.generate_challenge_for_block(req.goal, req.block, model=req.model)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error al generar reto: {str(err)}")
    challenge["verified"] = False
    return challenge

@app.post("/api/guided/verify-solution")
@app.post("/api/seguimiento/verify-solution")
def verify_solution(req: SeguimientoVerifySolutionRequest):
    """ Corrige el reto. Si viene de un ejercicio verificado, EJECUTA el código contra
    sus tests; preguntarle al modelo si el código está bien daba falsos aprobados. """
    if req.exercise_id:
        exercise = exercise_store.get(req.exercise_id)
        if exercise:
            veredicto = exercise_engine.grade_submission(exercise, req.user_code)

            if flags.is_enabled("learning_telemetry"):
                intento = telemetry.attempt_number(req.exercise_id)
                telemetry.record(req.exercise_id, exercise.get("concept", ""), "submission",
                                 passed=veredicto["passed"], attempt_num=intento,
                                 stderr=veredicto.get("stderr", ""), elapsed=veredicto.get("elapsed", 0))

            return {
                "verified_by_execution": True,
                "passed": veredicto["passed"],
                "score": 100 if veredicto["passed"] else 0,
                "feedback": veredicto["reason"],
                "stdout": veredicto.get("stdout", ""),
                "stderr": veredicto.get("stderr", ""),
                "suggestions": [],
            }

    # Reto antiguo sin tests: solo queda la valoración del modelo, y se dice.
    try:
        res = ai_engine.verify_user_code_solution(req.goal, req.block, req.user_code, model=req.model)
        res["verified_by_execution"] = False
        return res
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error al verificar solución: {str(err)}")

@app.post("/api/guided/{seg_id}/generate-notebook")
@app.post("/api/seguimiento/{seg_id}/generate-notebook")
def generate_seguimiento_notebook(seg_id: str):
    path_obj = seguimiento_repo.load(seg_id)
    if not path_obj:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    cells = []
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            f"# 📓 Cuaderno de Aprendizaje: {path_obj.goal}\n",
            f"**Generado automáticamente por Prig IDE** | Total de Bloques: {len(path_obj.blocks)}\n\n",
            "---\n"
        ]
    })

    for i, b in enumerate(path_obj.blocks, start=1):
        cells.append({
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                f"## Bloque {i}: {b.title}\n",
                f"**Descripción:** {b.description}\n\n",
                f"🎯 **Objetivo:** {b.learning_objective}\n\n",
                f"⚡ **Hito de Validación:** {b.validation_check}\n\n",
                f"📌 **Temas:** {', '.join(b.topics)}\n"
            ]
        })

        cells.append({
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                f"# ==========================================\n",
                f"# BLOQUE {i}: {b.title.upper()}\n",
                f"# ==========================================\n\n",
                f"print('=== Ejecutando Bloque {i}: {b.title} ===')\n"
            ]
        })

        cells.append({
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                f"# 🎯 RETO PRÁCTICO PARA BLOQUE {i}\n",
                f"# Hito: {b.validation_check}\n\n",
                f"def resolver_reto_bloque_{i}():\n",
                f"    # TODO: Escribe tu solución de código aquí\n",
                f"    pass\n\n",
                f"resolver_reto_bloque_{i}()\n"
            ]
        })

    notebook_dict = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (ipykernel)",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "name": "python",
                "version": "3.10"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 4
    }

    safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', path_obj.goal[:30])
    filename = f"Ruta_{safe_title}_{seg_id[:6]}.ipynb"
    file_path = os.path.join(file_mgr.base_dir, filename)

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(notebook_dict, f, indent=2, ensure_ascii=False)

    return {
        "status": "ok",
        "file_path": file_path,
        "filename": filename,
        "message": f"Cuaderno Jupyter '{filename}' generado exitosamente."
    }

class SeguimientoProgressRequest(BaseModel):
    completed_blocks: List[str]

@app.post("/api/seguimiento/{seg_id}/progress")
def update_seguimiento_progress(seg_id: str, req: SeguimientoProgressRequest):
    path_obj = seguimiento_repo.load(seg_id)
    if not path_obj:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    # Sellar la fecha real en que se marcó cada bloque: el mapa de calor lo necesita
    # (antes toda la actividad histórica se acumulaba en el día de hoy).
    now_iso = datetime.now().isoformat()
    newly_completed = set(req.completed_blocks) - set(path_obj.completed_blocks)
    for block_id in newly_completed:
        path_obj.completion_dates[block_id] = now_iso
    for block_id in set(path_obj.completed_blocks) - set(req.completed_blocks):
        path_obj.completion_dates.pop(block_id, None)

    path_obj.completed_blocks = req.completed_blocks
    seguimiento_repo.save(path_obj)
    dataset_mgr.build_and_save_dataset()
    return path_obj.model_dump()

# ==========================================
# DATASET UNIFICADO DE APRENDIZAJE
# ==========================================

@app.get("/api/dataset/summary")
def get_dataset_summary():
    ds = dataset_mgr.build_and_save_dataset()
    return ds.model_dump()

@app.get("/api/dataset/export")
def export_dataset_file():
    ds = dataset_mgr.build_and_save_dataset()
    if os.path.exists(dataset_mgr.dataset_file):
        return FileResponse(
            dataset_mgr.dataset_file,
            media_type="application/json",
            filename="user_learning_dataset.json"
        )
    raise HTTPException(status_code=404, detail="Dataset file not found")

# ==========================================
# LANZADOR DE VENTANA NATIVA INDEPENDIENTE PARA NOTE
# ==========================================

@app.post("/api/note/open-standalone")
def open_note_standalone():
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script_path = os.path.join(root_dir, "launch_note.py")
        python_exec = sys.executable
        p = subprocess.Popen([python_exec, script_path], close_fds=True, start_new_session=True)
        with _tracked_lock:
            _tracked_child_processes.append(p)
        return {"status": "success", "message": "Ventana nativa Note lanzada como aplicación independiente."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

class NoteExplainRequest(BaseModel):
    topic: str
    model: str = "qwen2.5-coder:7b"

@app.post("/api/note/explain")
def note_explain(req: NoteExplainRequest):
    sys_prompt = """Eres un TUTOR PEDAGÓGICO DE IA EXPERTO EN TECNOLOGÍA Y PROGRAMACIÓN.
Tu tarea es explicar el tema solicitado de forma profunda, pedagógica y clara en APROXIMADAMENTE 500 PALABRAS.

ESTRUCTURA DE LA EXPLICACIÓN:
1. Concepto Fundamental e Importancia.
2. Principios y Funcionamiento Clave (usando viñetas explicativas).
3. Ejemplo de Código Práctico o Caso de Uso.
4. Conclusión / Resumen Técnico.

Formatea la respuesta en Markdown limpio (títulos ##, ###, bloques de código ```). No agregues saludos ni intros informales."""
    
    prompt = f"Por favor, explica en detalle el siguiente tema en aproximadamente 500 palabras:\nTema: {req.topic}"

    def stream_explanation():
        for chunk in ai_engine.generate_response(prompt, model=req.model, system_prompt=sys_prompt):
            yield chunk

    return StreamingResponse(stream_explanation(), media_type="text/plain")

# ==========================================
# ENDPOINTS EXPORTADOR PDF CARPETAS & NOTEBOOKS
# ==========================================

class PDFExportRequest(BaseModel):
    folder_path: str
    file_paths: List[str]
    theme: str = "light"
    options: Optional[Dict[str, Any]] = None

@app.get("/api/folder/code-files")
def get_folder_code_files(path: str = Query(...)):
    pdf_exp = PDFExporter()
    return pdf_exp.list_folder_code_files(path)

@app.post("/api/export/pdf-preview")
def pdf_preview(req: PDFExportRequest):
    pdf_exp = PDFExporter()
    html_content = pdf_exp.generate_styled_html(req.folder_path, req.file_paths, req.theme, req.options)
    return {"html": html_content}

@app.post("/api/export/pdf-download")
def pdf_download(req: PDFExportRequest):
    pdf_exp = PDFExporter()
    pdf_bytes = pdf_exp.generate_pdf_bytes(req.folder_path, req.file_paths, req.theme, req.options)
    folder_name = os.path.basename(os.path.abspath(req.folder_path)) or "export"
    filename = f"{folder_name}_code_notebooks.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ===========================================================================
# Gestión de recursos: el botón "Recomendado"
# ===========================================================================

def recursos_gestor():
    catalogo = {**agent_flows.MODELOS,
                **{k: {**v, "embedding": True} for k, v in agent_flows.MODELOS_EMBEDDING.items()}}
    return _gestor_recursos(catalogo)


_recursos_cancelar = threading.Event()

# Qué campo de la configuración de IA corresponde a cada opción recomendada.
# Solo el tutor vive en esa configuración; los demás usos guardan lo aplicado en el
# almacén de recursos y lo leen de ahí.
_CAMPOS_TUTOR = ("agent1_model", "num_ctx", "num_gpu", "keep_alive")


def _config_tutor() -> Dict[str, Any]:
    cfg = ai_engine.get_config()
    return {k: cfg.get(k) for k in _CAMPOS_TUTOR}


def _propuesta_tutor(rec: Dict[str, Any]) -> Dict[str, Any]:
    opc = rec.get("opciones") or {}
    return {"agent1_model": rec["modelo"], "num_ctx": opc.get("num_ctx"),
            # Automático: forzar capas no aceleró nada y provocó falta de memoria
            "num_gpu": -1, "keep_alive": opc.get("keep_alive")}


def _diferencias(actual: Dict[str, Any], propuesta: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"campo": k, "actual": actual.get(k), "nuevo": v}
            for k, v in propuesta.items() if v is not None and actual.get(k) != v]


def _perfil_valido(perfil: str, tirador: str = "equilibrado"):
    if perfil not in RECURSOS_PERFILES:
        raise HTTPException(status_code=400, detail=f"Perfil desconocido: {perfil}")
    if tirador not in RECURSOS_TIRADORES:
        raise HTTPException(status_code=400, detail=f"Preferencia desconocida: {tirador}")


def _ndjson_en_hilo(trabajo):
    """ Ejecuta `trabajo(avisar)` en un hilo y emite sus eventos como NDJSON """
    cola: "queue.Queue" = queue.Queue()
    resultado: Dict[str, Any] = {}

    def correr():
        try:
            resultado["fin"] = trabajo(cola.put)
        except recursos_cal.Cancelado:
            resultado["error"] = "Cancelado."
        except Exception as e:
            resultado["error"] = str(e)
        finally:
            cola.put(None)

    hilo = threading.Thread(target=correr, daemon=True)
    hilo.start()

    def emitir():
        while True:
            evento = cola.get()
            if evento is None:
                break
            yield json.dumps(evento, ensure_ascii=False, default=str) + "\n"
        hilo.join(timeout=5)
        if "error" in resultado:
            yield json.dumps({"tipo": "error", "mensaje": resultado["error"]},
                             ensure_ascii=False) + "\n"
        else:
            yield json.dumps({"tipo": "fin", "resultado": resultado.get("fin")},
                             ensure_ascii=False, default=str) + "\n"
    return StreamingResponse(emitir(), media_type="application/x-ndjson")


def _gpu_ocupada() -> bool:
    with ai_engine._streams_lock:
        return bool(ai_engine._active_streams)


@app.get("/api/recursos/maquina")
def recursos_maquina(fresca: bool = False):
    g = recursos_gestor()
    try:
        maq = g.maquina(fresca=fresca)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo analizar la máquina: {e}")
    rad = maq.radiografia
    cal = recursos_almacen().calibracion(rad["huella"])
    return {
        "huella": rad["huella"],
        "sistema": rad.get("sistema"), "cpu": rad.get("cpu"), "memoria": rad.get("memoria"),
        "gpus": rad.get("gpus"), "disco": rad.get("disco"), "energia": rad.get("energia"),
        "ancho_banda_ram_gbps": rad.get("ancho_banda_ram_gbps"),
        "resumen": maq.resumen(),
        "servidor": recursos_srv.estado(rad.get("ollama")),
        "calibracion": ({k: v for k, v in cal.items() if k not in ("muestras", "detalle")}
                        if cal else None),
        "vivo": g.estado_vivo(),
    }


@app.get("/api/recursos/estado")
def recursos_estado():
    return recursos_gestor().estado_vivo()


@app.get("/api/recursos/perfiles")
def recursos_perfiles():
    return {"perfiles": [{"id": k, **v} for k, v in RECURSOS_PERFILES.items()],
            "tiradores": [{"id": k, "nombre": v} for k, v in RECURSOS_TIRADORES.items()]}


@app.get("/api/recursos/modelos")
def recursos_modelos(perfil: str = "tutor", tirador: str = "equilibrado"):
    _perfil_valido(perfil, tirador)
    return recursos_gestor().veredictos(perfil, tirador)


class RecursosRecomendarRequest(BaseModel):
    modelo: Optional[str] = None
    perfil: str = "tutor"
    tirador: str = "equilibrado"


@app.post("/api/recursos/recomendar")
def recursos_recomendar(req: RecursosRecomendarRequest):
    """ Sin modelo: elige el mejor instalado para el uso. Con modelo: cómo abrirlo. """
    _perfil_valido(req.perfil, req.tirador)
    g = recursos_gestor()
    modelo = req.modelo
    ranking = None
    if not modelo:
        ranking = g.veredictos(req.perfil, req.tirador)["modelos"]
        utiles = [m for m in ranking if m.get("util")]
        if not ranking:
            raise HTTPException(status_code=404, detail="No hay modelos instalados.")
        modelo = (utiles or ranking)[0]["modelo"]
    try:
        rec = g.recomendar(modelo, req.perfil, req.tirador)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    rec["elegido_automaticamente"] = not req.modelo
    if ranking is not None:
        rec["ranking"] = [{k: m.get(k) for k in ("modelo", "veredicto", "etiqueta", "util",
                                                  "calidad_esperada", "puntos")}
                          | {"tok_s": m["estimacion"].get("tok_s")} for m in ranking[:8]]
    if req.perfil == "tutor":
        rec["cambios"] = _diferencias(_config_tutor(), _propuesta_tutor(rec))
    else:
        previo = recursos_almacen().aplicado(req.perfil) or {}
        actual = {"modelo": previo.get("modelo"), **(previo.get("opciones") or {})}
        rec["cambios"] = _diferencias(actual, {"modelo": rec["modelo"], **rec["opciones"]})
    rec["aplicado"] = recursos_almacen().aplicado(req.perfil)
    rec["gpu_ocupada"] = _gpu_ocupada()
    return rec


class RecursosAplicarRequest(BaseModel):
    modelo: str
    perfil: str = "tutor"
    tirador: str = "equilibrado"


@app.post("/api/recursos/aplicar")
def recursos_aplicar(req: RecursosAplicarRequest):
    """ Aplica la recomendación, guardando lo que había para poder restaurarlo.

    La recomendación se recalcula aquí y no se acepta del cliente: lo aplicado es
    siempre lo que la calculadora dice para la máquina de ESTE momento.
    """
    _perfil_valido(req.perfil, req.tirador)
    g = recursos_gestor()
    try:
        rec = g.recomendar(req.modelo, req.perfil, req.tirador)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if rec["veredicto"] == "no_viable":
        raise HTTPException(status_code=409, detail=rec["motivo"])
    if req.perfil == "tutor":
        actual = _config_tutor()
        propuesta = _propuesta_tutor(rec)
        cambios = _diferencias(actual, propuesta)
        recursos_almacen().registrar_aplicado("tutor", rec["modelo"], rec["opciones"], actual)
        ai_engine.update_config({k: v for k, v in propuesta.items() if v is not None})
    else:
        previo = recursos_almacen().aplicado(req.perfil) or {}
        cambios = _diferencias({"modelo": previo.get("modelo"), **(previo.get("opciones") or {})},
                               {"modelo": rec["modelo"], **rec["opciones"]})
        recursos_almacen().registrar_aplicado(req.perfil, rec["modelo"], rec["opciones"], {})
    return {"ok": True, "cambios": cambios, "recomendacion": rec,
            "config": ai_engine.get_config()}


class RecursosPerfilRequest(BaseModel):
    perfil: str = "tutor"


@app.post("/api/recursos/restaurar")
def recursos_restaurar(req: RecursosPerfilRequest):
    _perfil_valido(req.perfil)
    anterior = recursos_almacen().quitar_aplicado(req.perfil)
    if anterior is None:
        raise HTTPException(status_code=404, detail="No hay nada aplicado que restaurar.")
    if req.perfil == "tutor" and anterior:
        ai_engine.update_config({k: v for k, v in anterior.items() if v is not None})
    return {"ok": True, "restaurado": anterior, "config": ai_engine.get_config()}


class RecursosProbarRequest(BaseModel):
    modelo: str
    perfil: str = "tutor"
    tirador: str = "equilibrado"
    forzar: bool = False


@app.post("/api/recursos/probar")
def recursos_probar(req: RecursosProbarRequest):
    """ Prueba real y corta de la recomendación; guarda lo medido """
    _perfil_valido(req.perfil, req.tirador)
    if _gpu_ocupada() and not req.forzar:
        raise HTTPException(status_code=409,
                            detail="Hay una generación en curso; espera a que termine.")
    g = recursos_gestor()
    try:
        f = g.ficha(req.modelo, red=False)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if f.get("estimada"):
        raise HTTPException(status_code=409, detail="Descarga el modelo antes de probarlo.")
    _recursos_cancelar.clear()

    def trabajo(avisar):
        maq = g.maquina(fresca=True)
        r = recursos_cal.probar_recomendacion(f, maq, req.perfil, req.tirador,
                                              avisar, _recursos_cancelar)
        huella = maq.radiografia["huella"]
        guardar = {k: v for k, v in r.items() if k != "recomendacion"}
        recursos_almacen().guardar_prueba(huella, f["nombre"], req.perfil, guardar)
        if r.get("deducido"):
            previa = recursos_almacen().calibracion(huella)
            recursos_almacen().guardar_calibracion(
                huella, recursos_cal.combinar(previa, [r["deducido"]]))
        return guardar
    return _ndjson_en_hilo(trabajo)


@app.post("/api/recursos/calibrar")
def recursos_calibrar():
    if _gpu_ocupada():
        raise HTTPException(status_code=409,
                            detail="Hay una generación en curso; espera a que termine.")
    g = recursos_gestor()
    _recursos_cancelar.clear()

    def trabajo(avisar):
        maq = g.maquina(fresca=True)
        huella = maq.radiografia["huella"]
        previa = recursos_almacen().calibracion(huella)
        r = recursos_cal.calibrar(g.fichas_instaladas(), maq, avisar,
                                  _recursos_cancelar, previa)
        for p in r.get("pruebas", []):
            if p.get("ok"):
                recursos_almacen().guardar_prueba(huella, p["modelo"], "calibracion", p)
        if r.get("ok"):
            recursos_almacen().guardar_calibracion(huella, r["valores"],
                                                   {"pruebas": len(r["pruebas"])})
            r["maquina"] = g.maquina().resumen()
        return r
    return _ndjson_en_hilo(trabajo)


@app.post("/api/recursos/cancelar")
def recursos_cancelar():
    _recursos_cancelar.set()
    return {"ok": True}


@app.post("/api/recursos/olvidar-calibracion")
def recursos_olvidar():
    recursos_almacen().olvidar_calibracion()
    return {"ok": True}


@app.get("/api/recursos/servidor")
def recursos_servidor():
    return recursos_srv.estado()


class RecursosServidorRequest(BaseModel):
    cambios: Dict[str, Optional[str]]
    reiniciar: bool = True
    forzar: bool = False


@app.post("/api/recursos/servidor")
def recursos_servidor_aplicar(req: RecursosServidorRequest):
    if _gpu_ocupada() and req.reiniciar and not req.forzar:
        raise HTTPException(status_code=409,
                            detail="Hay una generación en curso: reiniciar Ollama la cortaría.")
    try:
        r = recursos_srv.aplicar(req.cambios, ai_engine, req.reiniciar, req.forzar)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    recursos_gestor().radiografia(fresca=True)
    return r


@app.get("/api/recursos/temperaturas")
def recursos_temperaturas(historial: bool = False):
    """ Temperaturas de los componentes y estado del gobernador térmico """
    mon = recursos_termico.monitor()
    gob = recursos_termico.gobernador()
    lectura = mon.lectura()
    datos = {**lectura, "gobernador": gob.estado(),
             "umbrales": {"gpu_limite": gob.limite, "gpu_reanudar": gob.reanudar,
                          "cpu_aviso": recursos_termico.CPU_AVISO,
                          "cpu_alto": recursos_termico.CPU_ALTO}}
    if historial:
        datos["historial"] = list(mon.historial)
    return datos


class RecursosTermicoRequest(BaseModel):
    limite_gpu: Optional[float] = None
    olvidar: bool = False


class RitmoRequest(BaseModel):
    activo: Optional[bool] = None
    objetivo_c: Optional[float] = None
    rampa_s: Optional[float] = None
    ritmo_minimo: Optional[float] = None
    tramo_s: Optional[float] = None
    cpu_eficiente: Optional[bool] = None


@app.get("/api/recursos/ritmo")
def recursos_ritmo():
    """ Modo suave: ajustes, fracción de trabajo ahora mismo y núcleos de eficiencia """
    gob = recursos_termico.gobernador()
    return {**gob.ritmo.estado(gob.monitor.gpu()), "motor": gob.estado_motor()}


@app.post("/api/recursos/ritmo")
def recursos_ritmo_ajustar(req: RitmoRequest):
    gob = recursos_termico.gobernador()
    cambios = {k: v for k, v in req.model_dump().items() if v is not None}
    gob.ritmo.fijar(cambios)
    gob.aplicar_motor_suave()
    gob.controlador.paso()
    if gob.ritmo.activo and gob.ritmo.ajustes.get("cpu_eficiente"):
        gob.fijador.aplicar(forzar=True)
    else:
        gob.fijador.soltar()
    return {**gob.ritmo.estado(gob.monitor.gpu()), "motor": gob.estado_motor()}


@app.post("/api/recursos/termico")
def recursos_termico_ajustar(req: RecursosTermicoRequest):
    gob = recursos_termico.gobernador()
    try:
        if req.limite_gpu is not None:
            gob.fijar_limite(req.limite_gpu)
        if req.olvidar:
            gob.olvidar()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return gob.estado()


@app.get("/api/recursos/eventos")
def recursos_eventos(limite: int = 50):
    return {"eventos": recursos_almacen().eventos(max(1, min(limite, 200)))}


# ===========================================================================
# Modelos: todo lo configurable de Ollama (solo lo verificado)
# ===========================================================================

gestor_modelos = GestorModelos(ai_engine.base_url)


def _modelos(fn, *args, **kwargs):
    gestor_modelos.base = ai_engine.base_url.rstrip("/")
    try:
        return fn(*args, **kwargs)
    except (ErrorConfig, ErrorGestion) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except requests_lib.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Ollama no responde: {e}")


def _ndjson(generador):
    def emitir():
        try:
            for evento in generador:
                yield json.dumps(evento, ensure_ascii=False, default=str) + "\n"
            yield json.dumps({"fase": "fin"}) + "\n"
        except (ErrorConfig, ErrorGestion, requests_lib.RequestException) as e:
            yield json.dumps({"fase": "error", "mensaje": str(e)}, ensure_ascii=False) + "\n"
    return StreamingResponse(emitir(), media_type="application/x-ndjson")


def _num_gpus() -> int:
    try:
        return max(1, len(recursos_gestor().radiografia().get("gpus") or []))
    except Exception:
        return 1


@app.get("/api/modelos/catalogo")
def modelos_catalogo():
    return ollama_opciones.catalogo(_num_gpus())


@app.get("/api/modelos")
def modelos_lista():
    return {"modelos": _modelos(gestor_modelos.instalados), "disco": _modelos(gestor_modelos.uso_disco)}


@app.get("/api/modelos/ficha")
def modelos_ficha(modelo: str):
    return _modelos(gestor_modelos.ficha, modelo)


@app.get("/api/modelos/config")
def modelos_config(modelo: Optional[str] = None, uso: Optional[str] = None):
    cfg = ollama_opciones.config()
    capas = {"global": cfg.capa("global")}
    if modelo:
        capas["modelo"] = _modelos(cfg.capa, "modelo", modelo)
    if uso:
        capas["uso"] = _modelos(cfg.capa, "uso", None, uso)
        if modelo:
            capas["modelo_uso"] = _modelos(cfg.capa, "modelo_uso", modelo, uso)
    del_modelo = {}
    if modelo:
        try:
            del_modelo = gestor_modelos.ficha(modelo)["parametros"]
        except Exception:
            del_modelo = {}
    # Lo que la configuración global de IA sigue enviando (contexto, tope, hilos…)
    globales = ai_engine._build_options(None)
    for k in list(cfg.resolver(None, None)["opciones"]):
        globales.pop(k, None)
    return {"capas": capas, "efectivo": cfg.resolver(modelo, uso), "del_modelo": del_modelo,
            "configuracion_ia": globales}


class ModelosConfigRequest(BaseModel):
    capa: str
    modelo: Optional[str] = None
    uso: Optional[str] = None
    valores: Dict[str, Any] = {}
    reemplazar: bool = False


@app.post("/api/modelos/config")
def modelos_config_fijar(req: ModelosConfigRequest):
    return {"capa": _modelos(ollama_opciones.config().fijar, req.capa, req.valores, req.modelo, req.uso, req.reemplazar)}


class ModelosPlantillaRequest(BaseModel):
    capa: str
    plantilla: str
    modelo: Optional[str] = None
    uso: Optional[str] = None


@app.post("/api/modelos/plantilla")
def modelos_plantilla(req: ModelosPlantillaRequest):
    plantilla = ollama_opciones.PLANTILLAS.get(req.plantilla)
    if not plantilla:
        raise HTTPException(status_code=400, detail="Plantilla desconocida")
    cfg = ollama_opciones.config()
    actual = _modelos(cfg.capa, req.capa, req.modelo, req.uso)
    muestreo = {"temperature", "top_k", "top_p", "min_p", "seed", "repeat_penalty", "repeat_last_n",
                "presence_penalty", "frequency_penalty"}
    nuevo = {k: v for k, v in actual.items() if k not in muestreo}
    nuevo.update(plantilla["valores"])
    return {"capa": _modelos(cfg.fijar, req.capa, nuevo, req.modelo, req.uso, True)}


class ModelosProbarRequest(BaseModel):
    modelo: str
    prompt: str = ""
    uso: Optional[str] = None
    system: Optional[str] = None
    opciones: Dict[str, Any] = {}
    think: Optional[bool] = None
    format: Optional[Any] = None          # "json" o un esquema JSON
    logprobs: int = 0
    raw: bool = False
    template: Optional[str] = None
    suffix: Optional[str] = None


@app.post("/api/modelos/probar")
def modelos_probar(req: ModelosProbarRequest):
    opciones = _modelos(ollama_opciones.validar, req.opciones)
    op_motor, campos = ollama_opciones.separar(opciones)
    payload = {"model": req.modelo, "prompt": req.prompt,
               "options": ai_engine._build_options(op_motor, req.modelo, req.uso)}
    sistema = ai_engine._completar_payload(payload, req.modelo, req.uso,
                                           req.think if req.think is not None else campos.get("think"),
                                           req.system or "")["sistema"]
    for clave in ("keep_alive", "truncate", "shift"):
        if clave in campos:
            payload[clave] = campos[clave]
    if sistema:
        payload["system"] = sistema
    if req.format is not None and req.format != "":
        if isinstance(req.format, str) and req.format != "json":
            try:
                payload["format"] = json.loads(req.format)
            except ValueError:
                raise HTTPException(status_code=400, detail="El esquema JSON no es válido")
        else:
            payload["format"] = req.format
    if req.logprobs:
        payload["logprobs"] = True
        payload["top_logprobs"] = max(1, min(int(req.logprobs), 5))
    if req.raw:
        payload["raw"] = True
    if req.template:
        payload["template"] = req.template
    if req.suffix:
        if "insert" not in ai_engine.capacidades(req.modelo):
            raise HTTPException(status_code=400, detail=f"{req.modelo} no admite rellenar al medio (suffix)")
        payload["suffix"] = req.suffix
    datos = _modelos(gestor_modelos.probar, payload)
    return {
        "respuesta": datos.get("response", ""),
        "pensamiento": datos.get("thinking", ""),
        "metricas": ai_engine.metricas(datos, payload["options"].get("num_ctx")),
        "logprobs": [{"token": p.get("token"), "logprob": p.get("logprob"),
                      "alternativas": [{"token": a.get("token"), "logprob": a.get("logprob")} for a in (p.get("top_logprobs") or [])]}
                     for p in (datos.get("logprobs") or [])[:4000]],
        "peticion": {k: v for k, v in payload.items() if k != "prompt"},
    }


class ModelosCrearRequest(BaseModel):
    nombre: str
    desde: str
    system: str = ""
    parametros: Dict[str, Any] = {}
    mensajes: List[Dict[str, str]] = []
    licencia: str = ""


# Los que se comprobó que Ollama guarda al crear una variante (show → parameters)
PARAMETROS_VARIANTE = {"temperature", "top_k", "top_p", "min_p", "seed", "repeat_penalty", "repeat_last_n",
                       "presence_penalty", "frequency_penalty", "num_predict", "stop", "num_ctx", "num_keep"}


@app.post("/api/modelos/crear")
def modelos_crear(req: ModelosCrearRequest):
    fuera = set(req.parametros) - PARAMETROS_VARIANTE
    if fuera:
        raise HTTPException(status_code=400, detail=f"No se pueden guardar en una variante: {', '.join(sorted(fuera))}")
    gestor_modelos.base = ai_engine.base_url.rstrip("/")
    return _ndjson(gestor_modelos.crear_variante(req.nombre, req.desde, req.system, req.parametros,
                                                 req.mensajes, req.licencia))


class ModelosCopiarRequest(BaseModel):
    origen: str
    destino: str
    copiar_config: bool = True


@app.post("/api/modelos/copiar")
def modelos_copiar(req: ModelosCopiarRequest):
    r = _modelos(gestor_modelos.copiar, req.origen, req.destino)
    if req.copiar_config:
        ollama_opciones.config().renombrar_modelo(req.origen, r["modelo"])
    return r


class ModelosNombreRequest(BaseModel):
    modelo: str
    uso: Optional[str] = None


@app.post("/api/modelos/borrar")
def modelos_borrar(req: ModelosNombreRequest):
    return _modelos(gestor_modelos.borrar, req.modelo)


class ModelosImportarRequest(BaseModel):
    ruta: str
    nombre: str


@app.post("/api/modelos/importar")
def modelos_importar(req: ModelosImportarRequest):
    ruta = os.path.realpath(os.path.expanduser(req.ruta))
    casa = os.path.realpath(os.path.expanduser("~"))
    if not (ruta + os.sep).startswith(casa + os.sep):
        raise HTTPException(status_code=403, detail="Solo se importan archivos de tu carpeta personal")
    if not ruta.lower().endswith(".gguf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser .gguf")
    gestor_modelos.base = ai_engine.base_url.rstrip("/")
    return _ndjson(gestor_modelos.importar_gguf(ruta, req.nombre))


@app.get("/api/modelos/actualizaciones")
def modelos_actualizaciones():
    return {"modelos": _modelos(gestor_modelos.actualizaciones)}


@app.get("/api/modelos/cargados")
def modelos_cargados():
    return {"modelos": _modelos(gestor_modelos.cargados)}


@app.post("/api/modelos/precargar")
def modelos_precargar(req: ModelosNombreRequest):
    campos = ai_engine._campos_peticion(req.modelo, req.uso)
    opciones = {k: v for k, v in ai_engine._build_options(None, req.modelo, req.uso).items()
                if k in ("num_ctx", "num_gpu", "num_batch", "num_thread", "use_mmap", "main_gpu")}
    return _modelos(gestor_modelos.precargar, req.modelo, opciones,
                    campos.get("keep_alive", ai_engine.config.get("keep_alive")))


@app.post("/api/modelos/descargar")
def modelos_descargar(req: ModelosNombreRequest):
    return _modelos(gestor_modelos.descargar, req.modelo)


def _carpeta_modelos_servidor() -> Optional[str]:
    try:
        entorno = (recursos_srv.estado().get("entorno") or {})
        return entorno.get("OLLAMA_MODELS")
    except Exception:
        return None


@app.get("/api/modelos/parciales")
def modelos_parciales():
    return gestor_modelos.parciales(_carpeta_modelos_servidor())


@app.delete("/api/modelos/parciales")
def modelos_borrar_parciales():
    return gestor_modelos.borrar_parciales(_carpeta_modelos_servidor())


@app.get("/api/modelos/registro")
def modelos_registro(lineas: int = 400):
    try:
        dueno = recursos_srv.estado().get("dueno")
    except Exception:
        dueno = None
    return recursos_srv.leer_registro(lineas, dueno)


@app.get("/api/modelos/embeddings")
def modelos_embeddings():
    return {"ajustes": ollama_opciones.config().embeddings(), "indice": indice_semantico.estado()}


class ModelosEmbeddingsRequest(BaseModel):
    modelo: Optional[str] = None
    dimensiones: Optional[int] = None
    truncar: Optional[bool] = None
    quitar_dimensiones: bool = False


@app.post("/api/modelos/embeddings")
def modelos_embeddings_fijar(req: ModelosEmbeddingsRequest):
    if req.modelo and "embedding" not in ai_engine.capacidades(req.modelo):
        raise HTTPException(status_code=400, detail=f"{req.modelo} no es un modelo de embeddings")
    ajustes = _modelos(ollama_opciones.config().fijar_embeddings, req.modelo, req.dimensiones,
                       req.truncar, req.quitar_dimensiones)
    return {"ajustes": ajustes, "indice": indice_semantico.estado()}


class ModelosEmbeddingsProbarRequest(BaseModel):
    texto: str = "Prueba de embeddings"


@app.post("/api/modelos/embeddings/probar")
def modelos_embeddings_probar(req: ModelosEmbeddingsProbarRequest):
    import time as _t
    t0 = _t.time()
    try:
        vectores = indice_semantico.embeber([req.texto], timeout=120)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo generar el embedding: {e}")
    return {"dimensiones": len(vectores[0]) if vectores else 0, "ms": round((_t.time() - t0) * 1000),
            "muestra": [round(x, 4) for x in (vectores[0][:8] if vectores else [])]}


# ===========================================================================
# Buscador de modelos (Ollama, Hugging Face, ModelScope) y cola de descargas
# ===========================================================================

def _buscador(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ErrorBuscador as e:
        raise HTTPException(status_code=400, detail=str(e))
    except requests_lib.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Sin conexión con la plataforma: {e}")


def _instalados_tags() -> List[Dict[str, Any]]:
    try:
        return requests_lib.get(f"{ai_engine.base_url}/api/tags", timeout=10).json().get("models", [])
    except Exception:
        return []


def _nombres_instalados() -> set:
    nombres = set()
    for m in _instalados_tags():
        nombres.add(m["name"])
        if m["name"].endswith(":latest"):
            nombres.add(m["name"][:-7])
    return nombres


def _al_terminar_descarga(item):
    try:
        recursos_gestor().olvidar_fichas()
    except Exception:
        pass
    try:
        seguimiento.marcar_actualizado(item["ref"])
    except Exception:
        pass


descargas = Descargas(lambda: ai_engine.base_url.rstrip("/"),
                      lambda: _carpeta_modelos_servidor() or gestor_modelos.carpeta_modelos(),
                      al_terminar=_al_terminar_descarga)
seguimiento = buscador_modelos.Seguimiento()


@app.get("/api/buscador/fuentes")
def buscador_fuentes():
    return {"fuentes": buscador_modelos.FUENTES, "ordenes": buscador_modelos.ORDENES,
            "capacidades_ollama": buscador_modelos.CAPACIDADES_OLLAMA}


@app.get("/api/buscador/buscar")
def buscador_buscar(q: str = "", fuentes: str = "ollama,huggingface,modelscope", orden: str = "relevancia",
                    capacidad: Optional[str] = None, pagina_ollama: Optional[int] = None,
                    pagina_huggingface: Optional[str] = None, pagina_modelscope: Optional[int] = None):
    r = buscador_modelos.buscar(q.strip(), [f.strip() for f in fuentes.split(",") if f.strip()], orden, capacidad,
                                {"ollama": pagina_ollama, "huggingface": pagina_huggingface, "modelscope": pagina_modelscope})
    _marcar_modelos([m for datos in r["fuentes"].values() for m in datos["modelos"]])
    return r


def _marcar_modelos(modelos):
    """ Añade a cada resultado si el usuario lo sigue y si ya tiene alguna variante instalada """
    seguidos = {f"{x['fuente']}:{x['id']}" for x in seguimiento.lista()}
    instalados = {n.lower() for n in _nombres_instalados()}
    for m in modelos:
        m["seguido"] = f"{m['fuente']}:{m['id']}" in seguidos
        prefijo = {"ollama": m["id"], "huggingface": f"hf.co/{m['id']}", "modelscope": f"modelscope.cn/{m['id']}"}[m["fuente"]].lower()
        m["instalado"] = any(n == prefijo or n.startswith(prefijo + ":") for n in instalados)


@app.get("/api/buscador/localizar")
def buscador_localizar(texto: str):
    """ Un modelo concreto por nombre, «propietario/repo», orden de Ollama o enlace de cualquier plataforma """
    r = _buscador(buscador_modelos.localizar, texto)
    _marcar_modelos(r["exactos"] + r["parecidos"])
    return r


@app.get("/api/buscador/variantes")
def buscador_variantes(fuente: str, id: str):
    datos = _buscador(buscador_modelos.variantes, fuente, id)
    instalados = _nombres_instalados()
    for v in datos["variantes"]:
        v["instalado"] = v["ref"] in instalados or v["ref"].lower() in {n.lower() for n in instalados}
    return datos


@app.get("/api/buscador/comprobar")
def buscador_comprobar(ref: str):
    return _buscador(buscador_modelos.comprobar, ref)


@app.get("/api/buscador/analizar")
def buscador_analizar(ref: str):
    try:
        return buscador_modelos.analizar_variante(ref)
    except ErrorBuscador as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo leer la cabecera del modelo: {e}")


@app.get("/api/buscador/novedades")
def buscador_novedades():
    return buscador_modelos.novedades()


@app.get("/api/buscador/actualizaciones")
def buscador_actualizaciones(max_edad: int = 86400, forzar: bool = False):
    return _buscador(seguimiento.actualizaciones, _instalados_tags, max_edad, forzar)


class SeguirRequest(BaseModel):
    fuente: str
    id: str
    titulo: Optional[str] = None


@app.get("/api/buscador/seguidos")
def buscador_seguidos(revisar: bool = False):
    return {"seguidos": _buscador(seguimiento.revisar) if revisar else seguimiento.lista()}


@app.post("/api/buscador/seguidos")
def buscador_seguir(req: SeguirRequest):
    return _buscador(seguimiento.seguir, req.fuente, req.id, req.titulo)


@app.post("/api/buscador/seguidos/dejar")
def buscador_dejar(req: SeguirRequest):
    seguimiento.dejar(req.fuente, req.id)
    return {"ok": True}


@app.post("/api/buscador/seguidos/visto")
def buscador_visto(req: SeguirRequest):
    return _buscador(seguimiento.marcar_visto, req.fuente, req.id)


class DescargaModeloRequest(BaseModel):
    ref: str
    titulo: Optional[str] = None


@app.post("/api/descargas")
def descargas_encolar(req: DescargaModeloRequest):
    return _buscador(descargas.encolar, req.ref, req.titulo)


@app.get("/api/descargas")
def descargas_lista():
    return {"descargas": descargas.lista()}


@app.post("/api/descargas/{id_}/cancelar")
def descargas_cancelar(id_: int):
    return _buscador(descargas.cancelar, id_)


@app.post("/api/descargas/{id_}/reintentar")
def descargas_reintentar(id_: int):
    return _buscador(descargas.reintentar, id_)


@app.delete("/api/descargas/terminadas")
def descargas_limpiar():
    return {"borradas": descargas.limpiar_terminadas()}

# ===========================================================================
# Desafíos: enunciado, caja de razonamiento, páginas de código y pruebas ocultas
# ===========================================================================

from desafios import ejecucion as des_ejec, fuentes as des_fuentes, tutor as des_tutor, catalogo_github as des_catalogo
import progreso
import gemini_motor
from desafios.almacen import Almacen as AlmacenDesafios, ahora as desafios_ahora
from desafios.ejecucion import ErrorDesafio

desafios_almacen = AlmacenDesafios()


def _desafio(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ErrorDesafio as e:
        raise HTTPException(status_code=400, detail=str(e))


def _modelo_desafios(modelo: Optional[str], rol: Optional[str] = None) -> str:
    """ El pedido; si no, el modelo elegido para ese rol en Configuración; si no, el del tutor """
    return ai_engine.modelo_para(rol, modelo) or ai_engine.config.get("agent1_model") or "qwen2.5-coder:7b"


def _motor_desafios(modelo: Optional[str], rol: Optional[str] = None):
    """ (motor, nombre del modelo): Ollama en local o Gemini en la nube si el nombre empieza por «gemini:» """
    nombre = _modelo_desafios(modelo, rol)
    if gemini_motor.es_gemini(nombre):
        if not gemini_motor.clave_actual()[0]:
            raise HTTPException(status_code=400, detail="Gemini no está conectado: conéctalo o elige un modelo local.")
        return gemini_motor.MotorGemini(ai_engine._extract_and_parse_json), nombre[len(gemini_motor.PREFIJO):]
    return ai_engine, nombre


def _consumir(generador, avisar):
    """ Reenvía los eventos de un generador del tutor y devuelve su valor final """
    try:
        while True:
            avisar(next(generador))
    except StopIteration as fin:
        return fin.value


class DesafioCrearRequest(BaseModel):
    tema: str = ""
    nivel: str = "intermedio"
    lenguaje: str = "python"
    modelo: Optional[str] = None
    conversacion: List[Dict[str, str]] = []
    ruta_id: Optional[str] = None
    bloque_id: Optional[str] = None
    basado_en: Optional[str] = None
    ajuste: Optional[str] = None          # parecido | mas_dificil | mas_facil


class DesafioImportarRequest(BaseModel):
    fuente: str
    ref: str
    funcion: Optional[str] = None
    lenguaje: Optional[str] = "python"
    tema: Optional[str] = None
    ruta_id: Optional[str] = None
    bloque_id: Optional[str] = None


class DesafioReplicarGitHubRequest(BaseModel):
    ref: str
    ruta: str
    contenido: Optional[str] = None
    lenguaje: Optional[str] = "python"
    tema: Optional[str] = None
    nivel: Optional[str] = "intermedio"
    modelo: Optional[str] = None


class DesafioPaginasRequest(BaseModel):
    paginas: List[Dict[str, Any]]


class DesafioEjecutarRequest(BaseModel):
    paginas: List[Dict[str, Any]]
    pagina: str


class DesafioModeloRequest(BaseModel):
    modelo: Optional[str] = None
    paginas: List[Dict[str, Any]] = []
    regenerar: bool = False


class DesafioPlanRequest(BaseModel):
    plan: str
    modelo: Optional[str] = None


class DesafioPistaRequest(BaseModel):
    nivel: int = 1
    modelo: Optional[str] = None
    paginas: List[Dict[str, Any]] = []


class DesafioPasosRequest(BaseModel):
    pasos_vistos: int


class DesafioChatRequest(BaseModel):
    mensajes: List[Dict[str, str]]
    modelo: Optional[str] = None
    desafio_id: Optional[str] = None
    paginas: List[Dict[str, Any]] = []


class DesafioAnalizarPropuestaRequest(BaseModel):
    propuesta: str
    lenguaje: Optional[str] = "python"
    nivel: Optional[str] = "intermedio"
    modelo: Optional[str] = None


def _contexto_bloque(ruta_id: Optional[str], bloque_id: Optional[str]) -> Dict[str, Any]:

    if not ruta_id:
        return {}
    ruta = guided.get(ruta_id)
    if not ruta:
        raise HTTPException(status_code=404, detail="Ruta de aprendizaje no encontrada")
    bloque = next((b for b in ruta.blocks if b.block_id == bloque_id), None) if bloque_id else None
    if bloque_id and not bloque:
        raise HTTPException(status_code=404, detail="Bloque no encontrado en la ruta")
    info = {"ruta_id": ruta.id, "meta": ruta.goal}
    if bloque:
        info.update(bloque_id=bloque.block_id, bloque=bloque.title, temas=bloque.topics,
                    objetivo=bloque.learning_objective, validacion=bloque.validation_check)
    return info


def _registrar_telemetria(d: Dict[str, Any], evento: str, **extra):
    if not flags.is_enabled("learning_telemetry"):
        return
    try:
        concepto = ", ".join(d.get("conceptos") or []) or d.get("titulo", "")
        if evento == "submission":
            extra["attempt_num"] = telemetry.attempt_number(d["id"])
        telemetry.record(d["id"], concepto, evento, **extra)
    except Exception as e:
        print(f"⚠️ Telemetría de desafíos: {e}")


class GeminiClaveRequest(BaseModel):
    clave: str
    acepto_aviso: bool = False


def _gemini(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except gemini_motor.ErrorGemini as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/gemini/estado")
def gemini_estado():
    """ Nunca devuelve la clave: solo si hay una y sus 4 primeros y últimos caracteres """
    return gemini_motor.estado()


@app.post("/api/gemini/clave")
def gemini_guardar_clave(req: GeminiClaveRequest):
    return _gemini(gemini_motor.guardar_clave, req.clave, req.acepto_aviso)


@app.delete("/api/gemini/clave")
def gemini_borrar_clave():
    return gemini_motor.borrar_clave()


@app.get("/api/gemini/modelos")
def gemini_modelos():
    return {"modelos": _gemini(gemini_motor.listar_modelos)}


class ProgresoAnalisisRequest(BaseModel):
    modelo: Optional[str] = None
    regenerar: bool = False


@app.get("/api/progreso/resumen")
def progreso_resumen(dias: int = Query(default=120, ge=7, le=365)):
    """ Todo el avance en un sitio: desafíos, plan de estudios, ejercicios y biblioteca """
    return _desafio(progreso.resumen, desafios_almacen, guided, telemetry, dataset_mgr, dias, kaggle_lector)


class InicioPerfilRequest(BaseModel):
    nombre: Optional[str] = None
    objetivo: Optional[str] = None
    nivel: Optional[str] = None
    mostrar_al_abrir: Optional[bool] = None
    favoritas: Optional[List[str]] = None


@app.get("/api/inicio")
def inicio_resumen():
    """ Todo lo de la pantalla de Inicio en una petición; cada bloque falla por separado """
    def temperaturas():
        lectura = recursos_termico.monitor().lectura()
        gob = recursos_termico.gobernador()
        gpu = next((c for c in lectura.get("componentes", []) if c.get("tipo") == "gpu"), None)
        cpu = next((c for c in lectura.get("componentes", []) if c.get("tipo") == "cpu"), None)
        return {"gpu": gpu and gpu.get("temp"), "cpu": cpu and cpu.get("temp"), "limite": gob.limite,
                "pausa": bool(gob.pausa)}
    fuentes = {
        "progreso": lambda: progreso.resumen(desafios_almacen, guided, telemetry, dataset_mgr, 120, kaggle_lector),
        "historial": lambda: progreso.historial(desafios_almacen, limite=30),
        "lecturas": kaggle_lector.resumen_lecturas,
        "colecciones_recientes": lambda: kaggle_colecciones.recientes(12),
        "colecciones": kaggle_colecciones.listar,
        "descargas": lambda: kaggle_explorar.mis_datos(file_mgr.base_dir),
        "ejercicios": lambda: telemetry.recientes(12),
        "modelos": lambda: gestor_modelos.instalados(),
        "cargados": lambda: gestor_modelos.cargados(),
        "modelo_tutor": lambda: ai_engine.config.get("agent1_model"),
        "gemini": gemini_motor.estado,
        "sistema": get_system_stats,
        "temperaturas": temperaturas,
        "proyecto": lambda: {"path": file_mgr.base_dir, "name": os.path.basename(file_mgr.base_dir) or file_mgr.base_dir},
        "recientes": ide.recientes,
        "kaggle_cuenta": kaggle_lector.estado,
    }
    return inicio.resumen(fuentes)


@app.get("/api/inicio/perfil")
def inicio_perfil():
    return inicio.perfil()


@app.patch("/api/inicio/perfil")
def inicio_perfil_guardar(req: InicioPerfilRequest):
    return inicio.guardar_perfil({k: v for k, v in req.model_dump().items() if v is not None})


@app.get("/api/progreso/historial")
def progreso_historial(estado: Optional[str] = None, concepto: Optional[str] = None,
                       fuente: Optional[str] = None, limite: int = Query(default=200, ge=1, le=500)):
    return {"desafios": _desafio(progreso.historial, desafios_almacen, estado, concepto, fuente, limite)}


@app.get("/api/progreso/analisis")
def progreso_analisis_guardado():
    return {"analisis": progreso.analisis_guardado()}


@app.post("/api/progreso/analisis")
def progreso_analisis(req: ProgresoAnalisisRequest):
    """ El modelo (local o Gemini) lee el avance medido y propone los próximos pasos """
    guardado = progreso.analisis_guardado()
    filas = progreso.historial(desafios_almacen, limite=progreso.MAX_HISTORIAL)
    if guardado and not req.regenerar and guardado.get("desafios") == len(filas):
        return _ndjson_en_hilo(lambda avisar: guardado)
    if not filas:
        raise HTTPException(status_code=409, detail="Todavía no hay desafíos que analizar: empieza uno en la sección Desafíos.")
    motor, nombre_modelo = _motor_desafios(req.modelo)
    r = progreso.resumen(desafios_almacen, guided, telemetry, dataset_mgr, kaggle=kaggle_lector)
    contexto = progreso.contexto_para_modelo(r, filas)

    def trabajo(avisar):
        texto = _consumir(des_tutor.analisis_progreso(motor, nombre_modelo, contexto), avisar)
        if not texto.strip():
            raise ErrorDesafio("El modelo no devolvió nada. Prueba otra vez o con otro modelo.")
        return progreso.guardar_analisis(texto, _modelo_desafios(req.modelo), len(filas))
    return _ndjson_en_hilo(trabajo)


@app.get("/api/desafios")
def desafios_lista():
    return {"desafios": desafios_almacen.lista()}


@app.get("/api/desafios/fuentes")
def desafios_fuentes():
    return {"fuentes": [{"id": f.ID, "nombre": f.NOMBRE, "licencia": f.LICENCIA} for f in des_fuentes.FUENTES.values()],
            "no_incluidas": "LeetCode, HackerRank y Codewars no permiten copiar su contenido."}


@app.get("/api/desafios/github/catalogo")
def desafios_github_catalogo(lenguaje: Optional[str] = None, categoria: Optional[str] = None,
                             q: Optional[str] = None):
    return {
        "categorias": des_catalogo.CATEGORIAS,
        "repositorios": des_catalogo.listar_repositorios(lenguaje=lenguaje, categoria=categoria, busqueda=q)
    }


@app.get("/api/desafios/github/ejercicios")
def desafios_github_ejercicios(ref: str, ruta: Optional[str] = ""):
    return _github(des_catalogo.listar_ejercicios_repo, ref, ruta or "")


@app.post("/api/desafios/github/replicar")
def desafios_github_replicar(req: DesafioReplicarGitHubRequest):
    """ Replica cualquier archivo o ejercicio de GitHub en un desafío interactivo y evaluable de Prig (NDJSON). """
    modelo = _modelo_desafios(req.modelo, "codigo")
    motor, nombre_modelo = _motor_desafios(modelo)

    contenido = req.contenido
    if not contenido:
        info_archivo = _github(github_lector.leer_archivo, req.ref, req.ruta)
        contenido = info_archivo.get("contenido") or ""

    lenguaje = req.lenguaje or ("cpp" if req.ruta.endswith((".cpp", ".cc", ".cxx", ".h", ".hpp")) else "python")

    def trabajo(avisar):
        d = des_tutor.replicar_desde_github(
            motor, runner, nombre_modelo, req.ref, req.ruta, contenido,
            lenguaje=lenguaje, tema=req.tema or "", nivel=req.nivel or "intermedio",
            avisar=avisar
        )
        d = desafios_almacen.guardar(d)
        _registrar_telemetria(d, "replicated_from_github", attempt_num=len(d.get("intentos_creacion") or [1]))
        return AlmacenDesafios.publico(d)

    return _ndjson_en_hilo(trabajo)



@app.get("/api/desafios/internet/buscar")
def desafios_buscar(tema: str, nivel: Optional[str] = None, fuentes: Optional[str] = None,
                    modelo: Optional[str] = None, ayuda_modelo: bool = False,
                    lenguaje: Optional[str] = None):
    """ Desafíos de internet sobre un tema. Con ayuda_modelo, si no hay nada, el modelo
    propone términos en inglés y se vuelve a buscar. """
    lista = [f for f in (fuentes or "").split(",") if f] or None
    r = _desafio(des_fuentes.buscar, tema, nivel, lista, lenguaje=lenguaje)
    if not r["resultados"] and ayuda_modelo and tema.strip():
        motor, nombre = _motor_desafios(modelo)
        extra = des_tutor.palabras_clave(motor, nombre, tema)
        if extra:
            r = _desafio(des_fuentes.buscar, tema, nivel, lista, extra, lenguaje=lenguaje)
            r["terminos_del_modelo"] = extra
    return r


@app.post("/api/desafios/internet/importar")
def desafios_importar(req: DesafioImportarRequest):
    d = _desafio(des_fuentes.importar, req.fuente, req.ref, runner, req.funcion, req.lenguaje)
    d["origen"].update({k: v for k, v in _contexto_bloque(req.ruta_id, req.bloque_id).items()})
    if req.tema:
        d["origen"]["tema"] = req.tema
    if req.lenguaje:
        d["lenguaje"] = req.lenguaje
        d["origen"]["lenguaje"] = req.lenguaje
    d = desafios_almacen.guardar(d)
    _registrar_telemetria(d, "generated")
    return AlmacenDesafios.publico(d)


@app.post("/api/desafios/crear")
def desafios_crear(req: DesafioCrearRequest):
    """ El modelo crea el desafío; solo se entrega si se comprueba ejecutándolo (NDJSON) """
    modelo = _modelo_desafios(req.modelo, "codigo")
    motor, nombre_modelo = _motor_desafios(modelo)
    bloque = _contexto_bloque(req.ruta_id, req.bloque_id)
    partes, tema, nivel = [], req.tema.strip(), req.nivel
    if bloque:
        partes.append(f"Ruta de aprendizaje: {bloque.get('meta')}")
        if bloque.get("bloque"):
            partes.append(f"Bloque: {bloque['bloque']}. Temas: {', '.join(bloque.get('temas') or [])}. "
                          f"Objetivo: {bloque.get('objetivo') or ''}. Cómo se comprueba que lo aprendió: {bloque.get('validacion') or ''}")
            tema = tema or f"{bloque['bloque']} ({', '.join(bloque.get('temas') or [])})"
    if req.conversacion:
        partes.append("Conversación con el alumno sobre qué quiere practicar:\n" + des_tutor.conversacion_como_contexto(req.conversacion))
    if req.basado_en:
        previo = _desafio(desafios_almacen.obtener, req.basado_en)
        tema = tema or ", ".join(previo.get("conceptos") or []) or previo.get("titulo", "")
        orden = {"mas_dificil": "más difícil", "mas_facil": "más fácil"}.get(req.ajuste or "", "parecido en dificultad")
        partes.append(f"El alumno acaba de trabajar el desafío «{previo.get('titulo')}» (nivel {previo.get('nivel')}). "
                      f"Crea uno DISTINTO sobre los mismos conceptos, {orden}.")
        if req.ajuste in ("mas_dificil", "mas_facil") and previo.get("nivel") in des_tutor.NIVELES:
            i = des_tutor.NIVELES.index(previo["nivel"]) + (1 if req.ajuste == "mas_dificil" else -1)
            nivel = des_tutor.NIVELES[max(0, min(len(des_tutor.NIVELES) - 1, i))]
        else:
            nivel = previo.get("nivel") or nivel

    def trabajo(avisar):
        d = des_tutor.crear(motor, runner, nombre_modelo, tema, nivel, "\n\n".join(partes), avisar=avisar, lenguaje=req.lenguaje)
        nube = gemini_motor.es_gemini(modelo)
        d["lenguaje"] = req.lenguaje
        d["origen"] = {"tipo": "plan" if bloque else "modelo",
                       "nombre": ("Plan de estudios" if bloque else "Modelo") + (" · Google Gemini" if nube else ""),
                       "modelo": modelo, "motor": "gemini" if nube else "ollama", "tema": tema,
                       "lenguaje": req.lenguaje, **bloque}
        if req.basado_en:
            d["origen"]["basado_en"] = req.basado_en
        d = desafios_almacen.guardar(d)
        _registrar_telemetria(d, "generated", attempt_num=len(d.get("intentos_creacion") or [1]))
        return AlmacenDesafios.publico(d)
    return _ndjson_en_hilo(trabajo)


@app.get("/api/desafios/{id_}")
def desafios_obtener(id_: str):
    return AlmacenDesafios.publico(_desafio(desafios_almacen.obtener, id_))


@app.delete("/api/desafios/{id_}")
def desafios_borrar(id_: str):
    _desafio(desafios_almacen.obtener, id_)
    return {"borrado": desafios_almacen.borrar(id_)}


@app.put("/api/desafios/{id_}/paginas")
def desafios_guardar_paginas(id_: str, req: DesafioPaginasRequest):
    """ Guardado automático del trabajo del alumno """
    paginas = _desafio(des_ejec.validar_paginas, req.paginas)

    def cambio(d):
        solo_lectura = {p["nombre"]: p for p in d.get("paginas") or [] if p.get("solo_lectura")}
        d["paginas_usuario"] = [solo_lectura.get(p["nombre"], {"nombre": p["nombre"], "contenido": p["contenido"],
                                                               "descripcion": p.get("descripcion", "")}) for p in paginas]
        AlmacenDesafios.empezar(d)
    d = _desafio(desafios_almacen.modificar, id_, cambio)
    return {"guardado": d["actualizado"], "estado": d["progreso"]["estado"]}


@app.post("/api/desafios/{id_}/ejecutar")
def desafios_ejecutar(id_: str, req: DesafioEjecutarRequest):
    _desafio(desafios_almacen.obtener, id_)
    return _desafio(des_ejec.ejecutar_pagina, runner, req.paginas, req.pagina, run_id=f"desafio_{id_}")


@app.post("/api/desafios/{id_}/detener")
def desafios_detener(id_: str):
    return runner.cancel(f"desafio_{id_}")


@app.post("/api/desafios/{id_}/comprobar")
def desafios_comprobar(id_: str, req: DesafioPaginasRequest):
    d = _desafio(desafios_almacen.obtener, id_)
    paginas = _desafio(des_ejec.validar_paginas, req.paginas)
    resultado = _desafio(des_ejec.comprobar, runner, paginas, d.get("privado") or {}, run_id=f"desafio_{id_}")
    if not resultado["comprobable"]:
        return {**resultado, "progreso": d.get("progreso")}

    def cambio(x):
        x["paginas_usuario"] = [{"nombre": p["nombre"], "contenido": p["contenido"], "descripcion": p.get("descripcion", "")} for p in paginas]
        AlmacenDesafios.registrar_comprobacion(x, resultado)
        x["ultima_comprobacion"] = {k: resultado[k] for k in ("aprobado", "total", "pasados", "fallos", "error")}
    d = _desafio(desafios_almacen.modificar, id_, cambio)
    _registrar_telemetria(d, "submission", passed=resultado["aprobado"], hints_used=d["progreso"].get("pistas", 0),
                          stderr=resultado.get("error") or resultado.get("stderr") or "", elapsed=resultado.get("elapsed", 0))
    return {**resultado, "progreso": d["progreso"]}


@app.post("/api/desafios/{id_}/razonamiento")
def desafios_razonamiento(id_: str, req: DesafioModeloRequest):
    """ Caja de razonamiento: se genera una vez y se guarda (NDJSON) """
    d = _desafio(desafios_almacen.obtener, id_)
    if d.get("razonamiento") and not req.regenerar:
        guardado = d["razonamiento"]

        def ya_hecho(avisar):
            return guardado
        return _ndjson_en_hilo(ya_hecho)
    modelo = _modelo_desafios(req.modelo)
    motor, nombre_modelo = _motor_desafios(modelo)

    def trabajo(avisar):
        pasos = _consumir(des_tutor.razonamiento(motor, nombre_modelo, d), avisar)
        if not pasos:
            raise ErrorDesafio("El modelo no devolvió el razonamiento. Prueba otra vez u otro modelo.")
        r = {"pasos": pasos, "modelo": modelo}

        def cambio(x):
            x["razonamiento"] = r
        desafios_almacen.modificar(id_, cambio)
        return r
    return _ndjson_en_hilo(trabajo)


@app.post("/api/desafios/{id_}/razonamiento/visto")
def desafios_pasos_vistos(id_: str, req: DesafioPasosRequest):
    def cambio(d):
        p = d["progreso"]
        p["pasos_vistos"] = max(p.get("pasos_vistos", 0), max(0, min(req.pasos_vistos, 10)))
        AlmacenDesafios.empezar(d)
    d = _desafio(desafios_almacen.modificar, id_, cambio)
    return {"pasos_vistos": d["progreso"]["pasos_vistos"]}


@app.post("/api/desafios/{id_}/plan")
def desafios_plan(id_: str, req: DesafioPlanRequest):
    d = _desafio(desafios_almacen.obtener, id_)
    motor, nombre_modelo = _motor_desafios(req.modelo)

    def cambio(x):
        x["progreso"]["plan"] = req.plan[:5000]
        AlmacenDesafios.empezar(x)
    _desafio(desafios_almacen.modificar, id_, cambio)

    def trabajo(avisar):
        return {"texto": _consumir(des_tutor.revisar_plan(motor, nombre_modelo, d, req.plan), avisar)}
    return _ndjson_en_hilo(trabajo)


@app.post("/api/desafios/{id_}/pista")
def desafios_pista(id_: str, req: DesafioPistaRequest):
    """ nivel 0: pistas del ejercicio original (si las trae); 1-3: pistas graduadas del modelo """
    d = _desafio(desafios_almacen.obtener, id_)

    def contar(x):
        x["progreso"]["pistas"] = max(x["progreso"].get("pistas", 0), req.nivel if req.nivel else 1)
        AlmacenDesafios.empezar(x)
    if req.nivel == 0:
        texto = (d.get("privado") or {}).get("pistas_fuente")
        if not texto:
            raise HTTPException(status_code=404, detail="Este desafío no trae pistas propias.")
        _desafio(desafios_almacen.modificar, id_, contar)
        return {"titulo": "Pistas del ejercicio original", "texto": texto}
    motor, nombre_modelo = _motor_desafios(req.modelo)
    paginas = _desafio(des_ejec.validar_paginas, req.paginas) if req.paginas else (d.get("paginas_usuario") or d["paginas"])
    _desafio(desafios_almacen.modificar, id_, contar)

    def trabajo(avisar):
        return {"texto": _consumir(des_tutor.pista(motor, nombre_modelo, d, req.nivel, paginas, d.get("ultima_comprobacion")), avisar)}
    return _ndjson_en_hilo(trabajo)


@app.post("/api/desafios/{id_}/rendirse")
def desafios_rendirse(id_: str):
    """ Solución de referencia. Si aún no estaba resuelto, queda como rendido. """
    def cambio(d):
        p = d["progreso"]
        if p.get("estado") != "resuelto":
            p["estado"], p["rendido"] = "rendido", desafios_ahora()
    d = _desafio(desafios_almacen.modificar, id_, cambio)
    priv = d.get("privado") or {}
    c = priv.get("comprobacion") or {}
    pruebas = (c.get("archivos") if c.get("tipo") == "unittest" else c.get("ejemplos") if c.get("tipo") == "doctest"
               else c.get("asserts") if c.get("tipo") == "asserts" else None)
    return {"referencia": priv.get("referencia") or [], "pruebas": pruebas, "tipo": c.get("tipo"), "progreso": d["progreso"]}


@app.post("/api/desafios/{id_}/reflexion")
def desafios_reflexion(id_: str, req: DesafioModeloRequest):
    d = _desafio(desafios_almacen.obtener, id_)
    if (d.get("progreso") or {}).get("estado") != "resuelto":
        raise HTTPException(status_code=409, detail="La reflexión se abre al resolver el desafío.")
    motor, nombre_modelo = _motor_desafios(req.modelo)
    paginas = _desafio(des_ejec.validar_paginas, req.paginas) if req.paginas else (d.get("paginas_usuario") or d["paginas"])

    def trabajo(avisar):
        return {"texto": _consumir(des_tutor.reflexion(motor, nombre_modelo, d, paginas), avisar)}
    return _ndjson_en_hilo(trabajo)


@app.post("/api/desafios/{id_}/traducir")
def desafios_traducir(id_: str, req: DesafioModeloRequest):
    """ Enunciado (y teoría) al español; se guarda la traducción """
    d = _desafio(desafios_almacen.obtener, id_)
    if d.get("enunciado_es") and not req.regenerar:
        guardado = {"enunciado_es": d["enunciado_es"], "teoria_es": d.get("teoria_es", "")}
        return _ndjson_en_hilo(lambda avisar: guardado)
    motor, nombre_modelo = _motor_desafios(req.modelo)

    def trabajo(avisar):
        enunciado = _consumir(des_tutor.traducir(motor, nombre_modelo, d.get("enunciado") or ""), avisar)
        teoria = ""
        if d.get("teoria"):
            avisar({"tipo": "progreso", "mensaje": "Traduciendo la teoría…"})
            teoria = _consumir(des_tutor.traducir(motor, nombre_modelo, d["teoria"]), lambda e: None)

        def cambio(x):
            x["enunciado_es"], x["teoria_es"] = enunciado, teoria
        desafios_almacen.modificar(id_, cambio)
        return {"enunciado_es": enunciado, "teoria_es": teoria}
    return _ndjson_en_hilo(trabajo)


@app.post("/api/desafios/chat")
def desafios_chat(req: DesafioChatRequest):
    if not req.mensajes:
        raise HTTPException(status_code=400, detail="Escribe un mensaje.")
    d = _desafio(desafios_almacen.obtener, req.desafio_id) if req.desafio_id else None
    paginas = req.paginas or ((d.get("paginas_usuario") or d.get("paginas")) if d else [])
    motor, nombre_modelo = _motor_desafios(req.modelo)

    def trabajo(avisar):
        return {"texto": _consumir(des_tutor.chat(motor, nombre_modelo, req.mensajes, d, paginas,
                                                  (d or {}).get("ultima_comprobacion")), avisar)}
    return _ndjson_en_hilo(trabajo)


@app.post("/api/desafios/analizar-propuesta")
def desafios_analizar_propuesta(req: DesafioAnalizarPropuestaRequest):
    """ Analiza la propuesta o idea del usuario y devuelve evaluación, complejidad y lo solicitado (NDJSON). """
    if not (req.propuesta or "").strip():
        raise HTTPException(status_code=400, detail="Escribe tu propuesta o planteo.")
    motor, nombre_modelo = _motor_desafios(req.modelo)

    def trabajo(avisar):
        return {"texto": _consumir(des_tutor.analizar_propuesta(motor, nombre_modelo, req.propuesta,
                                                               req.lenguaje or "python",
                                                               req.nivel or "intermedio"), avisar)}
    return _ndjson_en_hilo(trabajo)



# Serve frontend static assets

if os.path.exists(frontend_dir):


    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))
