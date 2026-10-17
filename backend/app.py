import os
import re
import asyncio
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import queue
import shutil
import signal
import logging
import threading
import subprocess
import requests as requests_lib
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("prig")

from file_manager import FileManager
from runner import CodeRunner
from ai_engine import AIEngine
from ai_engine.ai_engine_class import explicar_error_motor, fijar_cancelacion
from book_service import BookService
import librerias_service
from knowledge_service import KnowledgeService
from knowledge_base import KnowledgeBase
from knowledge_context import ContextAssembler
from contexto_modelo import CompiladorContexto
from indice_semantico import IndiceSemantico
import agent_flows
from agent_flows import FlowEngine, FlowStore
import agent_flows_v2
from agent_flows_v2 import DynamicFlowEngine, plantillas_profesionales_sota, ROLES_V2
from perfil_libro import PerfilLibro
from explorador import Explorador
from ide_servicios import ServiciosIDE
import ollama_opciones
from ollama_opciones import ErrorConfig
from ollama_gestion import GestorModelos, ErrorGestion
from herramientas_chat import Herramientas, ETIQUETAS as ETIQUETAS_HERRAMIENTAS
import banco_proyecto
import memoria_consulta
import lectura_unidades
import buscador_modelos
from buscador_modelos import ErrorBuscador
from descargas_modelos import Descargas
from recursos.gestor import gestor as _gestor_recursos
from recursos import calculadora as recursos_calc, ficha as recursos_ficha
from recursos import calibracion as recursos_cal, servidor as recursos_srv
from recursos.almacen import almacen as recursos_almacen
from recursos import termico as recursos_termico
from feature_flags import FeatureFlags
from learning_telemetry import LearningTelemetry
from guided_learning import GuidedLearningService
import kaggle_lector
import kaggle_colecciones
import inicio
import github_lector

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Un llama-server del motor MoE que sobrevivió a un cierre brusco de Prig sigue ocupando la VRAM. Un segundo
    # backend (el comparador de rutas, una prueba) no debe tocarlo: sería el del Prig que está abierto.
    # (el llama-server del motor MoE que sobrevivió a un cierre brusco lo cierra el servidor de Rust, su dueño)
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
# Único punto de indexación y consulta del conocimiento. Comparte carpeta con
# book_service: los mismos archivos, pero fragmentados y buscables.
knowledge_service = KnowledgeService(book_service.books_dir)

# Todos los repositorios cuelgan del workspace activo (no de os.getcwd()).
dataset_mgr = LearnerDatasetManager(file_mgr.base_dir)


knowledge_base = KnowledgeBase()
compilador_contexto = CompiladorContexto(knowledge_base)
context_assembler = ContextAssembler(knowledge_base, compilador_contexto)
indice_semantico = IndiceSemantico(knowledge_base)


def _gpu_libre_para_banco() -> bool:
    """ El banco embebe en la GPU solo si no hay ningún generador en ella (motor MoE u Ollama) """
    try:
        from ai_engine import motor_moe as _mm
        if _mm.pid_en_marcha() is not None:
            return False
        cargados = requests_lib.get(f"{ai_engine.base_url}/api/ps", timeout=2).json().get("models", [])
    except Exception:
        return False
    return all(any(e in (m.get("name") or "") for e in ("embed", "bge-")) for m in cargados)


def _embebedor_en_gpu():
    # Así el motor MoE (y unload_models) lo descargan antes de ocupar la GPU
    usados = ai_engine.__dict__.setdefault("_usados", set())
    usados.update({embebedor_banco.modelo, embebedor_banco.modelo + ":latest"})


embebedor_banco = banco_proyecto.Embebedor(ai_engine.base_url, gpu_libre=_gpu_libre_para_banco,
                                           al_usar_gpu=_embebedor_en_gpu)
bancos = banco_proyecto.Bancos(embeber=embebedor_banco, embebedor_listo=embebedor_banco.disponible)
_chats_usuario = [0]                 # respuestas del chat en curso: el analista autónomo les cede el paso
_chats_lock = threading.Lock()


def _guardia_analista() -> Optional[str]:
    """ Motivo para que el analista autónomo espere, o None si puede trabajar. Nunca compite con el
    usuario ni lleva los componentes al límite. """
    if _chats_usuario[0]:
        return "el chat está respondiendo"
    try:
        import psutil
        libre_gb = psutil.virtual_memory().available / 1024 ** 3
        if libre_gb < 6:
            return f"poca RAM libre ({libre_gb:.1f} GB)"
    except Exception:
        pass
    try:
        gob = recursos_termico.gobernador()
        gpu = gob.monitor.gpu(max_edad=5)
        if gpu is not None and gpu >= gob.limite - 3:
            return f"GPU a {gpu:.0f} °C (límite {gob.limite:.0f})"
        cpu = recursos_termico.temp_cpu(recursos_termico.leer_sensores())
        if cpu is not None and cpu >= 85:
            return f"CPU a {cpu:.0f} °C"
    except Exception:
        pass
    return None


bancos.guardia = _guardia_analista
flow_store = FlowStore(file_mgr.base_dir)
perfil_libro = PerfilLibro(knowledge_base)
explorador = Explorador(file_mgr.base_dir)
flags = FeatureFlags()
telemetry = LearningTelemetry(file_mgr.base_dir)

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
    global dataset_mgr, telemetry, guided
    dataset_mgr = LearnerDatasetManager(new_base_dir)
    telemetry = LearningTelemetry(new_base_dir)
    guided = GuidedLearningService(new_base_dir, ai_engine, book_service)
    # el explorador de libros también deja navegar el espacio de trabajo: el abierto ahora, no el del arranque
    explorador.workspace = os.path.abspath(new_base_dir)


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
    # Motor MoE: solo código (sin razonar, sin explicar; la salida limitada a bloques de código)
    solo_codigo: bool = False
    # Banco del proyecto (banco_proyecto.py): mapa, código relevante, cambios, memoria y herramientas
    banco: bool = False
    # False: sin la memoria de respuestas anteriores (ni se inyectan ni se guarda esta). Para medir: si no,
    # cada corrida del examen ve las respuestas de la anterior (docs/estudio-banco.md, E1)
    memoria: bool = True
    # auto | general | unidad (None: el de la configuración, banco_modo). docs/plan-texto-primero.md
    banco_modo: Optional[str] = None

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

class BookImportRequest(BaseModel):
    path: str
    category: Optional[str] = None

# La lista, leer, la ficha de IA, los recortes, el lector de PDF y las citas de los libros: servidor de Rust
# (routes/estante.rs y routes/libros.rs). Importar sigue aquí, con la indexación del conocimiento.

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


# =========================================================================
# ANALISTA DE LIBRERÍAS Y CITAS TÉCNICAS (libreria.json)
# =========================================================================

# Las librerías y sus citas: servidor de Rust (routes/librerias.rs)


# ==========================================
# ENDPOINTS: PAPERS Y ALGORITMOS SEMINALES ML
# ==========================================

# Listar, leer, guardar en el proyecto y preguntarle a una monografía: servidor de Rust (routes/biblioteca.rs)


# ==========================================
# ENDPOINTS: REFERENCIAS DE ML (libros, papers, formularios; backend/referencias_ml.py)
# ==========================================
import referencias_ml  # noqa: E402

MAX_PDF_REFERENCIA = 80 * 1024 * 1024


# Las referencias (listar, detalle, relacionadas, pdf, abrir) son del servidor de Rust (routes/referencias.rs);
# guardar el PDF en la biblioteca sigue aquí, con la indexación de libros.
class ReferenciaAccionRequest(BaseModel):
    id: str


def _referencia_o_404(ref_id: str) -> Dict[str, Any]:
    r = referencias_ml.referencia(ref_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"No existe la referencia «{ref_id}»")
    return r


def _pdf_de_referencia(r: Dict[str, Any]) -> Optional[str]:
    """ El PDF de una referencia: el enlace directo al PDF, o la página si ya es un PDF """
    if r.get("url_pdf"):
        return r["url_pdf"]
    return r["url"] if r["url"].lower().split("?")[0].endswith(".pdf") else None


def _descargar_pdf(url: str) -> bytes:
    """ Solo URLs del catálogo verificado (nunca una URL que mande el cliente) """
    import urllib.request
    peticion = urllib.request.Request(url, headers={"User-Agent": referencias_ml.AGENTE, "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(peticion, timeout=60) as resp:
        datos = resp.read(MAX_PDF_REFERENCIA + 1)
    if len(datos) > MAX_PDF_REFERENCIA:
        raise HTTPException(status_code=413, detail="El PDF supera 80 MB: ábrelo en el navegador.")
    if datos[:5] != b"%PDF-":
        raise HTTPException(status_code=502, detail="El enlace no devolvió un PDF: ábrelo en el navegador.")
    return datos


@app.post("/api/referencias/guardar")
def referencias_guardar(req: ReferenciaAccionRequest):
    """ Descarga el PDF a la biblioteca local (libros o papers) y lo indexa, para que el tutor lo lea y
    lo cite por página con «Mi biblioteca» """
    r = _referencia_o_404(req.id)
    url = _pdf_de_referencia(r)
    if not url:
        raise HTTPException(status_code=400, detail="Esta referencia no tiene PDF directo para guardar.")
    datos = _descargar_pdf(url)
    autores = r.get("autores") or []
    quien = (autores[0].split()[-1] + (" et al" if len(autores) > 1 else "")) if autores else "Referencia"
    nombre = re.sub(r"[^\w\s.,-]", "", f"{quien} {r.get('anio') or ''} - {r['titulo']}", flags=re.UNICODE).strip()[:150] + ".pdf"
    import tempfile
    carpeta = tempfile.mkdtemp(prefix="prig_ref_")
    origen = os.path.join(carpeta, nombre)
    try:
        with open(origen, "wb") as f:
            f.write(datos)
        categoria = "books" if r.get("tipo") == "libro" else "papers"
        res = book_service.import_file(origen, categoria)
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    try:
        ingest = knowledge_service.index_single(res["path"], res.get("category", "book").lower())
        res["indexed"] = ingest.get("status") in ("INGESTED", "ALREADY_EXISTS")
        res["chunks_count"] = ingest.get("chunks_count", 0)
    except Exception as err:
        res["indexed"] = False
        res["index_error"] = str(err)
    return res


# ==========================================
# ENDPOINTS: APRENDIZAJE GUIADO (rutas unificadas)
# ==========================================

# Generar (rápido y profundo, con o sin flujo), migrar los planes antiguos y detener: servidor de Rust
# (routes/guiado_ia.rs y routes/asistente.rs)

# ==========================================
# ENDPOINTS: BANDERAS, MÉTRICAS DE APRENDIZAJE Y SALUD DEL ENTORNO
# ==========================================

class FlagUpdateRequest(BaseModel):
    name: str
    enabled: Optional[bool] = None   # None = volver al valor por defecto

# ==========================================
# ENDPOINTS: EJERCICIOS VERIFICABLES POR EJECUCIÓN
# ==========================================

# Generar (verificado ejecutándolo), corregir, las pistas, la solución y los recientes: servidor de Rust
# (routes/ejercicios.rs)

# ==========================================
# ENDPOINTS: MOTOR DE CONOCIMIENTO (RAG SOBRE LA BIBLIOTECA)
# ==========================================

# El estado del índice, indexar, buscar y preguntar: servidor de Rust (prig_biblioteca::conocimiento,
# routes/conocimiento.rs)

# ======================================================================
# Base de conocimiento: paquetes extraídos de libros completos
# ======================================================================

# La base de conocimiento entera (estado, búsqueda, conceptos, contexto del tutor, compilar, índice semántico y
# verificar e importar paquetes): servidor de Rust (prig_biblioteca::{base_kb, contexto_kb, paquetes}, routes/kb.rs)


# ======================================================================
# Preparar el trabajo para la GPU externa
# ======================================================================

# Preparar el trabajo de extracción (libros disponibles, preparar, la lista): servidor de Rust
# (prig_biblioteca::trabajos, routes/trabajos.rs)


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

    return StreamingResponse(_flujo_cancelable(emitir()), media_type="application/x-ndjson")


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
        return StreamingResponse(_flujo_cancelable(emitir_v2()), media_type="application/x-ndjson")

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

    return StreamingResponse(_flujo_cancelable(emitir()), media_type="application/x-ndjson")


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
# Perfiles de Configuración del Entorno (Apariencia, Movimiento, IA)
# ======================================================================

# Las aplicaciones con audio, la fuente, el análisis y /ws/audio_reactivo: servidor de Rust (routes/escritorio.rs)

# ======================================================================
# Ficha de libro: analizar un libro entero con un flujo de agentes
# ======================================================================

class FichaRequest(BaseModel):
    source_id: str
    flujo: Optional[Dict[str, Any]] = None   # si no, la plantilla de ficha
    flujo_id: Optional[str] = None


# Los libros analizables, la ficha guardada y lo que leería el flujo: servidor de Rust (routes/kb.rs)


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

    return StreamingResponse(_flujo_cancelable(emitir()), media_type="application/x-ndjson")


# El material para un ejercicio y el contexto para el plan: servidor de Rust (prig_biblioteca::perfil)


# ======================================================================
# Explorar carpetas y sondear libros antes de extraerlos
# ======================================================================

# El sondeo de libros y preparar desde él: servidor de Rust (prig_biblioteca::sondeo, routes/trabajos.rs)


# Kaggle: buscar notebooks de la comunidad y leerlos celda a celda con un modelo
# (backend/kaggle_lector.py). Sustituye al catálogo fijo de seis notebooks y a la
# «importación» que generaba una plantilla inventada en vez del notebook real.

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


@app.get("/api/kaggle/colecciones/{id_}")
def kaggle_coleccion(id_: str):
    return _kaggle(kaggle_colecciones.obtener, id_)


@app.patch("/api/kaggle/colecciones/{id_}")
def kaggle_coleccion_editar(id_: str, req: KaggleColeccionRequest):
    return _kaggle(kaggle_colecciones.editar, id_, req.nombre, req.descripcion, req.color)


@app.delete("/api/kaggle/colecciones/{id_}")
def kaggle_coleccion_borrar(id_: str):
    return _kaggle(kaggle_colecciones.borrar, id_)

# Explicar los datos de un dataset o una competición: servidor de Rust (routes/profesor.rs)


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

class GithubWidgetPreviewRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None
    extras: Optional[Dict[str, Any]] = None

def _github(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except github_lector.ErrorGitHub as e:
        raise HTTPException(status_code=400, detail=str(e))

# Explicar un repositorio o un archivo y las preguntas: servidor de Rust (routes/profesor.rs)


@app.get("/api/github/guardados")
def github_guardados():
    return {"repos": github_lector.guardados()}


@app.post("/api/github/guardados")
def github_guardar(req: GithubRefRequest):
    return {"repos": _github(github_lector.guardar, req.ref, req.nota or "")}


@app.delete("/api/github/guardados")
def github_quitar(ref: str):
    return {"repos": github_lector.quitar(ref)}

# Explicar un notebook (celda, guía, ruta de estudio, preguntas): servidor de Rust (routes/profesor.rs)


class SegundaCarpetaRequest(BaseModel):
    path: Optional[str] = None

# ===========================================================================
# Opciones de IDE: ir a archivo, buscar en archivos, renombrar, problemas…
# ===========================================================================

ide = ServiciosIDE(file_mgr)

class IdeBuscarRequest(BaseModel):
    consulta: str
    reemplazo: Optional[str] = None
    regex: bool = False
    mayusculas: bool = False
    palabra: bool = False
    incluir: str = ""
    excluir: str = ""
    solo: Optional[List[str]] = None


class IdeRenombrarRequest(BaseModel):
    path: str
    destino: str


class IdeRutaRequest(BaseModel):
    path: str


class IdeProblemasRequest(BaseModel):
    lenguaje: str
    codigo: str


# ---------------------------------------------------------------------------
# Gestión de proyectos y exploración de directorios
# ---------------------------------------------------------------------------

class SaveProjectRequest(BaseModel):
    path: str
    name: Optional[str] = None
    source: Optional[str] = "biblioteca"


class RemoveProjectRequest(BaseModel):
    path: str

# La pantalla completa la alterna la ventana de Rust (routes/escritorio.rs)


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

    return StreamingResponse(_flujo_cancelable(emit()), media_type="application/x-ndjson")


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

class ModelDeleteRequest(BaseModel):
    model: str

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
        
    return StreamingResponse(_flujo_cancelable(event_stream()), media_type="application/x-ndjson")

class AIInlineCompleteRequest(BaseModel):
    code_prefix: str
    code_suffix: str = ""
    model: Optional[str] = None

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

def _con_referencias(texto_para_buscar: str, prompt: str) -> Tuple[str, List[Dict[str, Any]]]:
    """ (prompt con el bloque de referencias de ML relacionadas delante, referencias elegidas). Lo usan los
    chats de todas las secciones: así un resumen o una explicación puede citar el libro o el paper del tema """
    try:
        bloque, refs = referencias_ml.bloque_para_prompt(texto_para_buscar)
    except Exception as err:  # el catálogo nunca debe romper un chat
        logger.warning(f"Referencias de ML no disponibles: {err}")
        return prompt, []
    return (f"{bloque}\n\n{prompt}" if bloque else prompt), refs


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

INSTRUCCION_BANCO = (
    "BANCO DEL PROYECTO: tienes el mapa del proyecto y, con cada pregunta, el código relevante copiado "
    "literalmente del disco, los cambios desde tu última respuesta y lo que ya se sabe (definiciones, "
    "decisiones y preguntas resueltas).\n"
    "Reglas:\n"
    "1. Responde a partir de ese código y cita archivo:línea.\n"
    "2. No inventes nombres de funciones, constantes, valores ni fragmentos de código. Si algo no está "
    "en el banco, búscalo con la consola (P.buscar, P.ficha, P.codigo) o ver_simbolo antes de "
    "afirmarlo; si tampoco aparece, dilo.\n"
    "3. Para mostrar código que ya existe, cópialo tal cual del banco; no lo reescribas de memoria.\n"
    "4. Si descubres algo que valga para futuras preguntas (una definición del dominio, una decisión de "
    "diseño, teoría que explica el código), guárdalo con anotar.\n"
    "5. Sé breve: lo esencial en 150-400 palabras, salvo que te pidan más detalle. Primero consulta lo que "
    "necesites y después responde una sola vez; no narres lo que vas a hacer."
)
# Con la memoria del chat desactivada no se le pide guardar nada (y anotar no escribe: herramientas_chat.py)
_REGLA_ANOTAR = ("4. Si descubres algo que valga para futuras preguntas (una definición del dominio, una decisión de "
                 "diseño, teoría que explica el código), guárdalo con anotar.\n")
assert _REGLA_ANOTAR in INSTRUCCION_BANCO
INSTRUCCION_BANCO_SIN_MEMORIA = INSTRUCCION_BANCO.replace(_REGLA_ANOTAR, "").replace("\n5. Sé breve", "\n4. Sé breve")

# Tope de la respuesta en el chat con banco. Sin él, una respuesta en bucle (texto que se repite) seguía hasta
# llenar el contexto, el motor lo agrandaba y la volvía a empezar desde cero: medido 31.937 tokens en 17 min y
# 11.459 hasta llenar 32K (docs/estudio-banco.md). 4096 es lo que el motor ya reserva para la salida al elegir el
# contexto (motor_moe.estimar_tokens), así que no cambia su elección; la respuesta correcta más larga medida
# rondaba los 1.500. Cortada por el tope, se puede «Continuar».
TOPE_RESPUESTA_BANCO = 4096
# Con «Pensar», el razonamiento cuenta dentro del tope: con 4096, revisar una función gastaba todo en razonar y la
# respuesta salía vacía (2 de 2; docs/estudio-banco.md, «Corrige los fallos»). Este tope deja lugar a razonar y responder;
# el motor reserva ese espacio al elegir el contexto (motor_moe.estimar_tokens) y el bucle sigue acotado
TOPE_RESPUESTA_BANCO_PENSANDO = 16384
# Rondas de herramientas con el banco: en la última se le pide responder (ai_engine_class.chat_eventos), así que son 8
# de consultas y una para responder. Medido: con 9 o más consultas, 1 de 5 respuestas correctas.
RONDAS_BANCO = 9


EMPUJONES_MAX = 2
# Revisando una función que se puede ejecutar (memoria_consulta.sugiere_ejecutar), si respondió sin ejecutarla: una vez.
# Con la pista sola, B2 de E8 (la línea perdida al cortar) lo encontraron las que la ejecutaron, y la ejecutó 1 de 3
EJECUTALA = ("Antes de cerrar: ejecuta la función con P.cargar, como indican los hechos, con casos borde (vacío, un "
             "elemento, justo en el límite, apenas por encima) y compara lo que devuelve con lo que debería devolver. "
             "Después confirma o corrige tu conclusión, en pocas líneas.")
# Con «Pensar», si el razonamiento llena el tope sin llegar a responder, se responde sin razonar (B2 de E8: 16.384
# tokens de razonamiento y una respuesta vacía)
SIN_RAZONAR = "El razonamiento llenó el tope sin llegar a responder: se responde ahora sin razonar."
EMPUJON = ("Continúa: haz ahora con las herramientas la consulta que anunciaste y termina la respuesta. "
           "No anuncies lo que vas a hacer: hazlo.")
_ANUNCIO = re.compile(r"(?:^|[\n.:!?]\s*)(?:ahora|voy a|vamos a|veamos|veo si|busco|buscaré|reviso|revisaré|consulto|"
                      r"consultaré|compruebo|comprobaré|déjame|a continuación|primero|luego)\b[^\n]{0,220}$", re.I)


RESPONDE_CON_RESULTADO = "Responde la pregunta con este resultado, en palabras (sin escribir código de P)."
_LINEA_P = re.compile(r"^\s*(?:[A-Za-z_]\w*\s*=\s*)?(?:P\.\w+\(.*\)|print\(.*\))\s*$")


def codigo_de_consola_escrito(texto: str) -> Optional[str]:
    """ Si la respuesta es SOLO código de la consola (una o más líneas P.…(…)), ese código """
    limpio = re.sub(r"^```\w*\s*|\s*```$", "", (texto or "").strip())
    lineas = [l for l in limpio.splitlines() if l.strip()]
    if not lineas or len(lineas) > 8 or not any("P." in l for l in lineas):
        return None
    return "\n".join(lineas) if all(_LINEA_P.match(l) for l in lineas) else None


def anuncia_sin_hacer(texto: str) -> bool:
    """ ¿La respuesta termina anunciando una consulta en vez de concluir? (el último párrafo es un
    «voy a…/ahora busco…» corto, sin código ni lista de resultados) """
    ultimo = (texto or "").strip().rsplit("\n\n", 1)[-1].strip()
    if not ultimo or len(ultimo) > 300 or "```" in ultimo or ultimo.startswith(("-", "*", "|", "#", "1.")):
        return False
    return bool(_ANUNCIO.search(ultimo))


INSTRUCCION_CONSOLA = (
    "MEMORIA DE CONSULTA: con la herramienta consola ejecutas Python sobre el proyecto entero, que es el "
    "objeto P. No necesitas tenerlo en tu contexto: consúltalo, crúzalo y cuenta con código, y guarda lo "
    "intermedio en variables. Para preguntas exactas usa P.hechos o P.sql; para leer mucho texto con "
    "criterio, recorre trozos con P.llm (map-reduce).\n" + memoria_consulta.AYUDA
)

# Lo que debe ceñirse a datos (subllamadas, análisis): el perfil «preciso» del motor MoE
MUESTREO_PRECISO = {"temperature": 0.3, "top_p": 0.9, "top_k": 20, "min_p": 0.0}

SISTEMA_SUBLLAMADA = ("Eres un analista de código dentro de un análisis más grande. Responde breve y preciso, "
                      "solo con lo que está en el contexto; si no está, dilo. Nombres y líneas exactos.")


def _generador_subllamadas(modelo: str):
    """ P.llm: el mismo modelo lee un trozo con un tope de tokens, sin razonar en voz alta """
    def generar(pregunta: str, contexto: str, max_tokens: int) -> str:
        prompt = f"{contexto}\n\n---\n{pregunta}" if contexto else pregunta
        return "".join(ai_engine.generate_response(prompt, model=modelo, system_prompt=SISTEMA_SUBLLAMADA, think=False,
                                                   options={"num_predict": int(max_tokens), **MUESTREO_PRECISO},
                                                   uso="programador")).strip()
    return generar


BANCO_MODOS = ("auto", "general", "unidad")


def _unidad_para(req: "AIChatRequest", modelo: str, banco) -> Tuple[Optional[Dict[str, Any]], str]:
    """ (unidad, motivo): la unidad cuya lectura usa esta pregunta (lectura_unidades.py), o None para el modo
    general, y por qué. El modo sale de la petición o de la configuración (banco_modo; docs/plan-texto-primero.md):
      auto     la unidad solo si su lectura está guardada; si no, modo general
      general  siempre modo general: el contexto se arma con el texto del banco, sin estados del motor
      unidad   la unidad aunque no tenga lectura guardada: se lee antes de responder (_chat_eventos)
    El modo unidad pide el motor MoE, eventos y herramientas, y nada de archivos enganchados ni código del editor
    (cambiarían el prefijo guardado). """
    from ai_engine import motor_moe as motor_moe_mod
    if banco is None:
        return None, "sin banco"
    modo = str(req.banco_modo or ai_engine.config.get("banco_modo") or "auto").strip().lower()
    if modo not in BANCO_MODOS:
        modo = "auto"
    if modo == "general":
        return None, "forzado: modo general"
    for falla, razon in ((not req.eventos, "sin eventos"), (not motor_moe_mod.es_moe(modelo), "no es el motor MoE"),
                         (req.solo_codigo, "solo código"), (req.hooked_files, "archivos enganchados"),
                         (req.code_context, "código del editor"), (req.continuar, "continuación"),
                         (req.think, "con razonamiento")):
        if falla:
            return None, f"modo unidad no disponible: {razon}"
    try:
        lector = lectura_unidades.LectorUnidades(banco, ai_engine, modelo=modelo, generar_sub=_generador_subllamadas(modelo))
        if not lector._unidades:
            return None, "el proyecto todavía no está partido en unidades"
        eleccion = lector.elegir_unidad(req.prompt)
        if eleccion.get("orden") is None:
            return None, f"la pregunta reparte su peso entre unidades: {eleccion.get('motivo') or 'ninguna se destaca'}"
        unidad = {**eleccion, "lector": lector, "datos": lector._unidades[eleccion["orden"]]}
        nombre = eleccion.get("nombre") or f"unidad {eleccion['orden']}"
        if not eleccion.get("vigente"):
            if modo == "unidad":
                return {**unidad, "leer_antes": True}, f"forzado: «{nombre}» no tiene lectura guardada; se lee ahora"
            return None, f"«{nombre}» no tiene lectura guardada: modo general"
        return unidad, "lectura guardada de la unidad"
    except Exception as e:
        return None, f"no se pudo elegir unidad: {type(e).__name__}"


def _presupuesto_banco(modelo: str) -> Tuple[int, int]:
    """ (tokens de contexto por pregunta, tokens del mapa). El motor MoE crece el contexto solo;
    con Ollama se respeta el num_ctx del modelo. """
    from ai_engine import motor_moe as motor_moe_mod
    pregunta = int(ai_engine.config.get("banco_presupuesto") or 6000)
    mapa = int(ai_engine.config.get("banco_mapa") or 3000)
    if not motor_moe_mod.es_moe(modelo):
        try:
            ctx = int(ai_engine._build_options(None, modelo, "tutor").get("num_ctx") or 8192)
        except Exception:
            ctx = 8192
        pregunta = min(pregunta, int(ctx * 0.35))
        mapa = min(mapa, int(ctx * 0.12))
    return pregunta, mapa


def _preparar_banco(req: "AIChatRequest", modelo: str):
    """ (banco, info, mapa, contexto) para la carpeta de trabajo; (None, …) si no hay carpeta """
    raiz = file_mgr.base_dir
    if not raiz or not os.path.isdir(raiz):
        return None, None, "", ""
    try:
        banco = bancos.para(raiz)
        sincronia = banco.sincronizar()           # lo que cambió desde el último vistazo del vigilante
        bancos.vigilar(raiz)
        presupuesto, presupuesto_mapa = _presupuesto_banco(modelo)
        enganchados = {str(f.get("path") or "").strip("./") for f in (req.hooked_files or [])}
        paquete = banco.componer(req.prompt, presupuesto, excluir_rutas=enganchados, usar_resoluciones=req.memoria)
        mapa = banco.mapa(presupuesto_mapa)
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}"}, "", ""
    info = {k: paquete[k] for k in ("tokens", "fragmentos", "archivos", "cambios", "conocimiento",
                                   "resoluciones", "vectores", "version", "segundos")}
    info.update({"mapa_tokens": banco_proyecto.estimar_tokens(mapa), "proyecto": os.path.basename(raiz),
                 "sincronizados": sincronia["nuevos"] + sincronia["modificados"] + sincronia["borrados"],
                 "inicial": sincronia["inicial"]})
    return banco, info, mapa, paquete["texto"]


@app.post("/api/ai/chat")
def ai_chat(req: AIChatRequest):
    sys_prompt = ai_engine.get_tutor_system_prompt(req.mode)
    prompt = req.prompt
    from ai_engine import motor_moe as motor_moe_mod
    # Motor MoE: nada automático que el usuario no pidió (citas de libros ni búsqueda web): cada una
    # añadía miles de tokens a leer, y la web además espera a la red (medido: +2.200 tokens y
    # «Fuentes: Python docs» en una pregunta sobre el código del proyecto)
    solo_lo_pedido = motor_moe_mod.es_moe(req.model or "")
    if req.solo_codigo and solo_lo_pedido:
        # Solo código: sin el prompt de tutor (pide explicar); el motor además limita la salida
        sys_prompt = motor_moe_mod.INSTRUCCION_SOLO_CODIGO

    citas_contexto = _formatear_citas(req.selected_citations)
    if not citas_contexto and not solo_lo_pedido:
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

    # Referencias de ML del catálogo (libros, papers, formularios) que vienen al caso, para que el modelo
    # las cite con su enlace. No en preguntas sobre el código del proyecto (banco) ni en «solo código»
    referencias: List[Dict[str, Any]] = []
    if not req.banco and not req.solo_codigo:
        prompt, referencias = _con_referencias(req.prompt, prompt)

    modelo = req.model or _modelo_desafios(None, "tutor")

    gancho_contexto = _formatear_gancho(req.hooked_files)
    # Motor MoE: los archivos enganchados van en su propio mensaje, antes de la pregunta. El motor
    # guarda en disco el estado tras leerlos y las preguntas siguientes sobre el mismo proyecto lo
    # restauran en ~0,1 s en lugar de releerlo (ai_engine/motor_moe.py). Lo que cambia en cada
    # pregunta (código del editor, citas, web) va con la pregunta.
    from ai_engine import motor_moe as motor_moe_mod
    contexto_fijo = gancho_contexto if (gancho_contexto and req.eventos and motor_moe_mod.es_moe(modelo)) else ""
    if gancho_contexto and not contexto_fijo:
        prompt = f"{gancho_contexto}\n\n{prompt}"
    banco, banco_info, unidad = None, None, None
    if req.banco:
        banco, banco_info, mapa, contexto_banco = _preparar_banco(req, modelo)
        unidad, motivo_modo = _unidad_para(req, modelo, banco)
        if banco is not None and banco_info is not None:
            banco_info.update({"modo": "unidad" if unidad is not None else "general", "motivo": motivo_modo})
        if unidad is not None and banco_info is not None:
            banco_info.update({"unidad": unidad["nombre"], "unidad_orden": unidad["orden"],
                               "unidad_cuota": unidad.get("cuota")})
        if banco is not None and unidad is None:
            # Modo general, el camino normal desde el plan «texto primero»: los mismos hechos del banco que recibe el
            # modo unidad (definición, llamadores, rutas, configuración…). En el estudio, el general era el más fiable
            # (97 % frente a 86 %; docs/plan-texto-primero.md)
            try:
                hechos = memoria_consulta.hechos_de_la_pregunta(banco, req.prompt)
            except Exception:
                hechos = ""
            if hechos:
                # Después del paquete, pegados a la pregunta (como en el modo unidad). Arriba de todo quedaban a ~21.000
                # caracteres de la pregunta y el modelo los ignoraba o descartaba; pegados a ella, el general acertó 3 de
                # 3 y verificó lo «sin resolver» (T7, docs/estudio-banco.md, «Texto primero: medición corta»)
                contexto_banco = f"{contexto_banco}\n\n{hechos}" if contexto_banco else hechos
            if banco_info is not None:
                banco_info["hechos_caracteres"] = len(hechos)
        if banco is not None:
            if contexto_banco:
                prompt = f"{contexto_banco}\n\n{prompt}"
            if mapa:
                if req.eventos and motor_moe_mod.es_moe(modelo):
                    # El mapa es estable: con el gancho, en el mensaje fijo que el motor reaprovecha
                    contexto_fijo = f"{mapa}\n\n{contexto_fijo}".strip()
                else:
                    prompt = f"{mapa}\n\n{prompt}"
            if not (req.solo_codigo and solo_lo_pedido):
                sys_prompt = f"{sys_prompt}\n\n{INSTRUCCION_BANCO if req.memoria else INSTRUCCION_BANCO_SIN_MEMORIA}"
    if req.code_context:
        prompt = f"```\n{req.code_context}\n```\n\n{prompt}"

    if gemini_motor.es_gemini(modelo):
        if not gemini_motor.clave_actual()[0]:
            raise HTTPException(status_code=400, detail="Gemini no está conectado: conéctalo o elige un modelo local.")
        motor_gem = gemini_motor.MotorGemini(ai_engine._extract_and_parse_json)
        nombre_gem = modelo[len(gemini_motor.PREFIJO):]
        if req.eventos:
            def gemini_eventos():
                for chunk in motor_gem.generate_response(prompt, nombre_gem, sys_prompt):
                    yield json.dumps({"t": "texto", "v": chunk}, ensure_ascii=False) + "\n"
            return StreamingResponse(_flujo_cancelable(gemini_eventos()), media_type="application/x-ndjson")
        else:
            return StreamingResponse(_flujo_cancelable(motor_gem.generate_response(prompt, nombre_gem, sys_prompt)), media_type="text/plain")

    if req.eventos:
        return StreamingResponse(_flujo_cancelable(_chat_eventos(req, prompt, sys_prompt, modelo=modelo,
                                                                 contexto_fijo=contexto_fijo,
                                                                 banco=banco, banco_info=banco_info,
                                                                 unidad=unidad, referencias=referencias)),
                                 media_type="application/x-ndjson")

    def event_stream():
        should_web_search = req.use_web or ai_engine.web_search.should_auto_search(req.prompt)
        if should_web_search:
            for chunk in ai_engine.generate_response_with_web_search(prompt, modelo, sys_prompt):
                yield chunk
        else:
            for chunk in ai_engine.generate_response(prompt, modelo, sys_prompt, uso="tutor"):
                yield chunk

    return StreamingResponse(_flujo_cancelable(event_stream()), media_type="text/plain")


def _leer_unidad_antes(unidad: Dict[str, Any]):
    """ Modo «unidad» forzado y la unidad sin lectura guardada (docs/plan-texto-primero.md, T5). Con caché, se lee antes
    de responder (LectorUnidades.leer: el motor guarda su estado si cabe y queda registrada, así que las preguntas
    siguientes la restauran en ~0,3 s). Con el caché apagado (moe_cache_gb = 0) no: leería el prefijo dos veces sin
    poder guardarlo; se lee junto con la pregunta. Emite los avisos para el chat """
    def aviso(texto: str) -> str:
        return json.dumps({"t": "aviso", "v": texto}, ensure_ascii=False) + "\n"
    try:
        tope = ai_engine.config.get("moe_cache_gb")
        tope = None if tope in (None, "") else float(tope)
    except (TypeError, ValueError):
        tope = None
    nombre = unidad.get("nombre") or f"unidad {unidad.get('orden')}"
    if tope == 0:
        yield aviso(f"«{nombre}» no tiene lectura guardada y el caché está apagado: se lee junto con la pregunta "
                    "(≈30 s más).")
        return
    yield aviso(f"Leyendo «{nombre}» antes de responder (≈30–40 s; queda guardada para las próximas preguntas)…")
    try:
        r = unidad["lector"].leer(unidad["orden"]) or {}
        yield aviso(f"Unidad leída: {int(r.get('tokens') or 0):,} tokens en {r.get('segundos') or 0} s.".replace(",", "."))
    except Exception as e:
        yield aviso(f"No se pudo leer antes ({type(e).__name__}): se lee junto con la pregunta.")


def _chat_eventos(req: AIChatRequest, prompt: str, sys_prompt: str, modelo: Optional[str] = None,
                  contexto_fijo: str = "", banco=None, banco_info: Optional[Dict[str, Any]] = None,
                  unidad: Optional[Dict[str, Any]] = None, referencias: Optional[List[Dict[str, Any]]] = None):
    mod = modelo or req.model or _modelo_desafios(None, "tutor")
    if banco_info:
        yield json.dumps({"t": "banco", "v": banco_info}, ensure_ascii=False, default=str) + "\n"
    if referencias:
        yield json.dumps({"t": "referencias", "v": [referencias_ml.resumen_publico(r) for r in referencias]},
                         ensure_ascii=False) + "\n"
    fuentes = []
    from ai_engine import motor_moe as motor_moe_mod
    # Motor MoE: la web solo si el usuario la marca (ver ai_chat)
    automatica = not motor_moe_mod.es_moe(mod) and ai_engine.web_search.should_auto_search(req.prompt)
    if req.use_web or automatica:
        try:
            contexto_web, fuentes = ai_engine.web_search.get_web_context(req.prompt)
            if contexto_web:
                prompt = f"{prompt}\n\n{contexto_web}"
        except Exception:
            fuentes = []
    mensajes = [{"role": "system", "content": sys_prompt}]
    if contexto_fijo:
        mensajes.append({"role": "user", "content": contexto_fijo})
    mensajes.append({"role": "user", "content": prompt})
    if req.continuar:
        mensajes.append({"role": "assistant", "content": req.continuar})
    solo_codigo = bool(req.solo_codigo and motor_moe_mod.es_moe(mod))
    herramientas = None
    consola = None
    # Con el banco, las herramientas del proyecto van siempre (si el modelo las admite), y con ellas la
    # memoria de consulta: una consola aislada donde el proyecto entero es el objeto P
    if (req.herramientas or banco is not None) and not solo_codigo:   # la gramática de solo código no admite llamadas
        if banco is not None and "tools" in ai_engine.capacidades(mod):
            consola = memoria_consulta.Consola(banco, generar=_generador_subllamadas(mod), escribir=req.memoria)
            mensajes[0]["content"] = f"{mensajes[0]['content']}\n\n{INSTRUCCION_CONSOLA}"
        herramientas = Herramientas(knowledge_base, file_mgr, ide, runner,
                                    permitir_codigo=req.permitir_codigo, timeout=_exec_timeout(), banco=banco,
                                    consola=consola, escribir=req.memoria)
    if unidad is not None and consola is not None:
        # Modo unidad: la conversación empieza exactamente con el prefijo de la lectura guardada de esa
        # unidad (sistema del lector + tarjeta + contexto + código) y sus herramientas fijas; el motor la
        # restaura en ~0,3 s con sus expertos, y la consola cubre el resto del proyecto. Con la pregunta van
        # los hechos del banco sobre lo que nombra (lo que el modo general ya recibe)
        mensajes = unidad["lector"].mensajes(unidad["datos"]) + [
            {"role": "user", "content": unidad["lector"].pregunta_con_contexto(unidad["datos"], req.prompt, hechos=True)}]
        herramientas = Herramientas(banco=banco, consola=consola, solo=list(lectura_unidades.HERRAMIENTAS_UNIDAD),
                                    escribir=req.memoria)
        if unidad.get("leer_antes"):
            yield from _leer_unidad_antes(unidad)
    extra_moe = None
    if solo_codigo:
        extra_moe = {motor_moe_mod.SOLO_CODIGO: True}
    elif banco is not None and motor_moe_mod.es_moe(mod) and not req.think:
        # Con el banco la respuesta debe ceñirse al código: muestreo «preciso» (ai_engine/motor_moe.py)
        extra_moe = {motor_moe_mod.PERFIL: "preciso"}
    respuesta = []
    hubo_aviso = False
    with _chats_lock:
        _chats_usuario[0] += 1
    try:
        conversacion = mensajes
        pensar = bool(req.think) and not solo_codigo
        try:
            ejecutar = consola is not None and banco is not None and memoria_consulta.sugiere_ejecutar(banco, req.prompt)
        except Exception:
            ejecutar = False
        cargo = False                       # ¿alguna consulta ejecutó código del proyecto (P.cargar)?
        for intento in range(1 + (EMPUJONES_MAX if consola is not None else 0) + int(pensar) + int(ejecutar)):
            inicio_ronda = len(respuesta)
            pensado = False
            for evento in ai_engine.chat_eventos(conversacion, mod, "tutor", think=pensar,
                                                 logprobs=max(0, min(int(req.logprobs or 0), 5)),
                                                 herramientas=herramientas,
                                                 max_rondas=RONDAS_BANCO if banco is not None else 6,
                                                 gobernador=recursos_termico.gobernador(),
                                                 extra=extra_moe,
                                                 max_tokens=None if banco is None else (
                                                     TOPE_RESPUESTA_BANCO_PENSANDO if pensar else TOPE_RESPUESTA_BANCO)):
                if evento.get("t") == "herramienta":
                    evento["etiqueta"] = ETIQUETAS_HERRAMIENTAS.get(evento.get("nombre"), evento.get("nombre"))
                    if "P.cargar(" in json.dumps(evento.get("argumentos") or {}, ensure_ascii=False):
                        cargo = True
                elif evento.get("t") == "pensando":
                    pensado = True
                elif evento.get("t") == "texto":
                    respuesta.append(str(evento.get("v") or ""))
                elif evento.get("t") in ("error", "aviso"):
                    hubo_aviso = True
                yield json.dumps(evento, ensure_ascii=False, default=str) + "\n"
            if pensar and pensado and not "".join(respuesta[inicio_ronda:]).strip():
                pensar = False
                yield json.dumps({"t": "aviso", "v": SIN_RAZONAR}, ensure_ascii=False) + "\n"
                continue
            # Con herramientas, el modelo a veces anuncia la próxima consulta («Ahora busco qué
            # endpoints…») y cierra el turno sin hacerla (visto en el examen del proyecto). Se le pide
            # que la haga, con lo que ya dijo delante.
            if consola is None:
                break
            codigo = codigo_de_consola_escrito("".join(respuesta[inicio_ronda:]))
            if codigo:
                # Escribió la consulta como respuesta en vez de llamar a la herramienta (visto en modo
                # unidad): se ejecuta aquí y se le pide que responda con el resultado
                yield json.dumps({"t": "herramienta", "nombre": "consola", "argumentos": {"codigo": codigo},
                                  "etiqueta": ETIQUETAS_HERRAMIENTAS.get("consola", "consola")}, ensure_ascii=False) + "\n"
                resultado = memoria_consulta.formatear(consola.ejecutar(codigo))
                yield json.dumps({"t": "resultado", "nombre": "consola", "v": resultado}, ensure_ascii=False) + "\n"
                conversacion = conversacion + [{"role": "assistant", "content": "".join(respuesta[inicio_ronda:])},
                                               {"role": "user", "content": f"Resultado de la consola:\n{resultado}\n\n{RESPONDE_CON_RESULTADO}"}]
                del respuesta[inicio_ronda:]
                continue
            if not anuncia_sin_hacer("".join(respuesta)):
                if ejecutar and not cargo and "".join(respuesta).strip():
                    ejecutar = False
                    yield json.dumps({"t": "aviso", "v": "Se le pide que ejecute la función con un caso antes de "
                                                         "cerrar (P.cargar)."}, ensure_ascii=False) + "\n"
                    conversacion = conversacion + [{"role": "assistant", "content": "".join(respuesta)},
                                                   {"role": "user", "content": EJECUTALA}]
                    respuesta.append("\n\n")
                    yield json.dumps({"t": "texto", "v": "\n\n"}, ensure_ascii=False) + "\n"
                    continue
                break
            conversacion = conversacion + [{"role": "assistant", "content": "".join(respuesta)},
                                           {"role": "user", "content": EMPUJON}]
            respuesta.append("\n\n")
            yield json.dumps({"t": "texto", "v": "\n\n"}, ensure_ascii=False) + "\n"
        if not "".join(respuesta).strip() and not hubo_aviso:
            # Ni texto ni aviso: el motor pudo detenerse a mitad (visto en el estudio del banco: respuestas
            # vacías en 1 s mientras el vigía lo relanzaba). Mejor decirlo que devolver nada
            yield json.dumps({"t": "error", "v": "El modelo no devolvió ninguna respuesta (el motor pudo haberse "
                                                 "reiniciado). Vuelve a intentarlo."}, ensure_ascii=False) + "\n"
    finally:
        with _chats_lock:
            _chats_usuario[0] -= 1
        if consola is not None:
            consola.cerrar()
    if banco is not None and respuesta and req.memoria:
        # Historial de resoluciones: la próxima pregunta parecida parte de esta
        try:
            banco.registrar_resolucion(req.prompt, (req.continuar or "") + "".join(respuesta), mod,
                                       rutas=herramientas.rutas_consultadas if herramientas else None)
        except Exception:
            pass
    if fuentes:
        texto = "\n\n---\n**Fuentes consultadas:**\n" + "".join(f"- [{f['title']}]({f['url']})\n" for f in fuentes)
        yield json.dumps({"t": "texto", "v": texto}, ensure_ascii=False) + "\n"

# ==========================================
# ENDPOINTS: BANCO DEL PROYECTO (banco_proyecto.py)
# ==========================================

class BancoConocimientoRequest(BaseModel):
    tipo: str = "nota"
    titulo: str
    texto: str
    rutas: Optional[List[str]] = None


class BancoAnalizarRequest(BaseModel):
    modelo: Optional[str] = None
    limite: Optional[int] = None
    continuo: bool = False        # analista autónomo: sigue vivo y rehace lo que cambie


class BancoAjustesRequest(BaseModel):
    presupuesto: Optional[int] = None
    mapa: Optional[int] = None
    modo: Optional[str] = None          # auto | general | unidad (docs/plan-texto-primero.md)


def _banco_actual(crear: bool = True) -> "banco_proyecto.BancoProyecto":
    raiz = file_mgr.base_dir
    if not raiz or not os.path.isdir(raiz):
        raise HTTPException(status_code=400, detail="No hay carpeta de trabajo abierta.")
    if not crear and not bancos.existe(raiz):
        raise HTTPException(status_code=404, detail="Este proyecto todavía no tiene banco: actívalo primero.")
    return bancos.para(raiz)


def _modelo_analisis(pedido: Optional[str]) -> str:
    from ai_engine import motor_moe as motor_moe_mod
    if pedido:
        return pedido
    if ai_engine.config.get("banco_modelo"):
        return ai_engine.config["banco_modelo"]
    if motor_moe_mod.Motor.disponible().get("disponible"):
        return motor_moe_mod.NOMBRE
    return ai_engine.config.get("agent1_model") or "qwen2.5-coder:7b"


@app.get("/api/banco")
def banco_estado():
    raiz = file_mgr.base_dir
    existe = bool(raiz) and bancos.existe(raiz)
    presupuesto, mapa = _presupuesto_banco(ai_engine.config.get("agent1_model") or "")
    datos: Dict[str, Any] = {"raiz": raiz, "existe": existe, "vigilando": bancos.vigilado == os.path.abspath(raiz or "."),
                             "analisis": {k: v for k, v in bancos.analisis.items() if k != "inicio"},
                             "embebedor": {"modelo": embebedor_banco.modelo, "disponible": embebedor_banco.disponible()},
                             "presupuesto": int(ai_engine.config.get("banco_presupuesto") or 6000),
                             "mapa": int(ai_engine.config.get("banco_mapa") or 3000),
                             "modo": ai_engine.config.get("banco_modo") or "auto",
                             "modelo_analisis": _modelo_analisis(None), "error": bancos.ultimo_error}
    if existe:
        datos["banco"] = bancos.para(raiz).estado()
    return datos


@app.post("/api/banco/activar")
def banco_activar():
    banco = _banco_actual()
    r = banco.sincronizar()
    bancos.vigilar(banco.raiz)
    return {"sincronizacion": r, "banco": banco.estado()}


@app.post("/api/banco/sincronizar")
def banco_sincronizar(forzar: bool = Query(default=False)):
    banco = _banco_actual(crear=False)
    return {"sincronizacion": banco.sincronizar(forzar=forzar), "banco": banco.estado()}


@app.post("/api/banco/ajustes")
def banco_ajustes(req: BancoAjustesRequest):
    cambios: Dict[str, Any] = {}
    if req.presupuesto is not None:
        cambios["banco_presupuesto"] = max(1000, min(int(req.presupuesto), 100000))
    if req.mapa is not None:
        cambios["banco_mapa"] = max(0, min(int(req.mapa), 30000))
    if req.modo is not None:
        modo = str(req.modo).strip().lower()
        if modo not in BANCO_MODOS:
            raise HTTPException(status_code=400, detail="modo: auto, general o unidad")
        cambios["banco_modo"] = modo
    if cambios:
        ai_engine.update_config(cambios)
    return {"presupuesto": ai_engine.config.get("banco_presupuesto"), "mapa": ai_engine.config.get("banco_mapa"),
            "modo": ai_engine.config.get("banco_modo") or "auto"}


@app.get("/api/banco/buscar")
def banco_buscar(q: str = Query(...), k: int = Query(default=12)):
    banco = _banco_actual(crear=False)
    filas = banco.buscar(q, k=max(1, min(k, 50)))
    return {"resultados": [{c: f[c] for c in ("ruta", "simbolo", "tipo", "ini", "fin", "tokens", "puntos")}
                           | {"inicio": "\n".join(f["texto"].splitlines()[:8])} for f in filas]}


@app.get("/api/banco/contexto")
def banco_contexto(q: str = Query(...), presupuesto: int = Query(default=6000)):
    """ Lo que recibiría el modelo con esta pregunta (para ver y ajustar el banco) """
    banco = _banco_actual(crear=False)
    return banco.componer(q, max(500, min(presupuesto, 100000)))


@app.get("/api/banco/mapa")
def banco_mapa(presupuesto: int = Query(default=3000)):
    banco = _banco_actual(crear=False)
    texto = banco.mapa(max(200, min(presupuesto, 30000)))
    return {"texto": texto, "tokens": banco_proyecto.estimar_tokens(texto)}


@app.get("/api/banco/cambios")
def banco_cambios(desde: Optional[int] = Query(default=None), limite: int = Query(default=50)):
    banco = _banco_actual(crear=False)
    version = max(0, banco.version - 20) if desde is None else desde
    return {"version": banco.version, "cambios": banco.cambios_desde(version, limite=max(1, min(limite, 500)))}


@app.get("/api/banco/conocimiento")
def banco_conocimiento():
    return {"conocimiento": _banco_actual(crear=False).listar_conocimiento()}


@app.post("/api/banco/conocimiento")
def banco_anotar(req: BancoConocimientoRequest):
    try:
        return _banco_actual().anotar(req.tipo, req.titulo, req.texto, req.rutas or [], origen="usuario")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/banco/conocimiento/{id_conocimiento}")
def banco_olvidar_conocimiento(id_conocimiento: int):
    if not _banco_actual(crear=False).olvidar_conocimiento(id_conocimiento):
        raise HTTPException(status_code=404, detail="No existe.")
    return {"ok": True}


@app.get("/api/banco/resoluciones")
def banco_resoluciones(limite: int = Query(default=100)):
    return {"resoluciones": _banco_actual(crear=False).listar_resoluciones(max(1, min(limite, 1000)))}


@app.get("/api/banco/resoluciones/{id_resolucion}")
def banco_resolucion(id_resolucion: int):
    r = _banco_actual(crear=False).resolucion(id_resolucion)
    if not r:
        raise HTTPException(status_code=404, detail="No existe.")
    return r


@app.delete("/api/banco/resoluciones/{id_resolucion}")
def banco_olvidar_resolucion(id_resolucion: int):
    if not _banco_actual(crear=False).olvidar_resolucion(id_resolucion):
        raise HTTPException(status_code=404, detail="No existe.")
    return {"ok": True}


@app.post("/api/banco/analizar")
def banco_analizar(req: BancoAnalizarRequest):
    """ Un modelo lee cada archivo que cambió desde el último análisis y deja su resumen y las
    definiciones del dominio (en segundo plano; se puede cancelar) """
    banco = _banco_actual(crear=False)
    modelo = _modelo_analisis(req.modelo)

    def generar(prompt: str) -> str:
        return "".join(ai_engine.generate_response(prompt, model=modelo, system_prompt="Respond only with valid JSON.",
                                                   think=False, options=dict(MUESTREO_PRECISO), uso="programador"))
    bancos.vigilar(banco.raiz)
    return bancos.analizar_en_fondo(banco, generar, modelo, limite=req.limite, continuo=req.continuo)


class BancoConsolaRequest(BaseModel):
    codigo: str
    reiniciar: bool = False


_consola_usuario: Dict[str, Any] = {"raiz": None, "consola": None}


@app.post("/api/banco/consola")
def banco_consola(req: BancoConsolaRequest):
    """ La memoria de consulta para el usuario: la misma API P que usa el modelo """
    banco = _banco_actual(crear=False)
    actual = _consola_usuario.get("consola")
    if req.reiniciar or actual is None or _consola_usuario.get("raiz") != banco.raiz:
        if actual is not None:
            actual.cerrar()
        actual = memoria_consulta.Consola(banco, generar=_generador_subllamadas(_modelo_analisis(None)))
        _consola_usuario.update({"raiz": banco.raiz, "consola": actual})
    if not req.codigo.strip():
        return {"salida": "", "error": None, "variables": []}
    return actual.ejecutar(req.codigo)


@app.post("/api/banco/analizar/cancelar")
def banco_cancelar_analisis():
    bancos.cancelar_analisis()
    return {"ok": True}


@app.delete("/api/banco")
def banco_borrar():
    raiz = file_mgr.base_dir
    if not raiz:
        raise HTTPException(status_code=400, detail="No hay carpeta de trabajo abierta.")
    return {"borrado": bancos.borrar(raiz)}


# Plan de estudio de los tres agentes (/api/study-plan/*): en el servidor de Rust (routes/plan_estudio.rs y guiado.rs)


# Seguimiento: generar, la clase, el quiz, el reto verificado, corregirlo y el cuaderno: servidor de Rust
# (routes/guiado_ia.rs)

# ==========================================
# DATASET UNIFICADO DE APRENDIZAJE
# ==========================================

# ==========================================
# LANZADOR DE VENTANA NATIVA INDEPENDIENTE PARA NOTE
# ==========================================

# El bloc de notas suelto (`prig --nota`) y explicar un tema: servidor de Rust (routes/escritorio.rs)

# ==========================================
# ENDPOINTS EXPORTADOR PDF CARPETAS & NOTEBOOKS
# ==========================================

# La lista de archivos, la vista previa y el PDF los atiende el servidor de Rust (prig-server/src/routes/exportar.rs)


# ===========================================================================
# Gestión de recursos: el botón "Recomendado"
# ===========================================================================

def recursos_gestor():
    catalogo = {**agent_flows.MODELOS,
                **{k: {**v, "embedding": True} for k, v in agent_flows.MODELOS_EMBEDDING.items()}}
    return _gestor_recursos(catalogo)


def _flujo_cancelable(contenido):
    """ Envuelve el cuerpo de una respuesta en streaming para que se detenga si el cliente se va.

    El generador síncrono se ejecuta entero en un hilo propio, con SU evento de cancelación
    (lo leen generate_response y chat_eventos). Si el cliente cierra la conexión (cierra la
    sección, recarga, pulsa Detener), se cancela en el acto solo esta petición: el modelo deja
    de generar. Antes Starlette tardaba en cerrar el generador y el modelo seguía en la GPU,
    y para cortarlo había que usar /api/ai/cancel, que detenía TODAS las secciones.
    Un generador asíncrono se devuelve tal cual (ya se entera de la desconexión). """
    if hasattr(contenido, "__aiter__"):
        return contenido
    cola: "queue.Queue" = queue.Queue()
    cancelar = threading.Event()
    FIN = object()

    def correr():
        fijar_cancelacion(cancelar)
        try:
            for trozo in contenido:
                if cancelar.is_set():
                    break
                cola.put(trozo)
        except BaseException as e:           # se vuelve a lanzar del lado de la respuesta
            cola.put(e)
        finally:
            fijar_cancelacion(None)
            cerrar = getattr(contenido, "close", None)
            if cancelar.is_set() and cerrar:
                try:
                    cerrar()                  # sus finally sueltan la conexión con Ollama
                except Exception:
                    pass
            cola.put(FIN)

    async def emitir():
        threading.Thread(target=correr, daemon=True).start()
        bucle = asyncio.get_running_loop()
        completo = False
        try:
            while True:
                trozo = await bucle.run_in_executor(None, cola.get)
                if trozo is FIN:
                    break
                if isinstance(trozo, BaseException):
                    raise trozo
                yield trozo
            completo = True
        finally:
            if not completo:
                cancelar.set()
    return emitir()


def _ndjson_en_hilo(trabajo):
    """ Ejecuta `trabajo(avisar)` en un hilo y emite sus eventos como NDJSON.

    Si el cliente se va antes del final (cerró la sección, recargó, pulsó Cancelar), se
    activa la cancelación de ESTA petición: el modelo deja de generar. Antes el hilo seguía
    hasta terminar, ocupando la GPU para nadie. Las demás secciones no se enteran. """
    cola: "queue.Queue" = queue.Queue()
    resultado: Dict[str, Any] = {}
    cancelar = threading.Event()

    def correr():
        fijar_cancelacion(cancelar)
        try:
            resultado["fin"] = trabajo(cola.put)
        except recursos_cal.Cancelado:
            resultado["error"] = "Cancelado."
        except Exception as e:
            resultado["error"] = str(e)
        finally:
            fijar_cancelacion(None)
            cola.put(None)

    hilo = threading.Thread(target=correr, daemon=True)
    hilo.start()

    async def emitir():
        # Asíncrono a propósito: si el cliente se va, Starlette cancela esta tarea y el
        # CancelledError llega aquí en el acto (con un generador síncrono quedaba bloqueado en
        # un hilo y la cancelación no se enteraba hasta mucho después)
        bucle = asyncio.get_running_loop()
        completo = False
        try:
            while True:
                evento = await bucle.run_in_executor(None, cola.get)
                if evento is None:
                    break
                yield json.dumps(evento, ensure_ascii=False, default=str) + "\n"
            await bucle.run_in_executor(None, hilo.join, 5)
            if "error" in resultado:
                yield json.dumps({"tipo": "error", "mensaje": resultado["error"]},
                                 ensure_ascii=False) + "\n"
            else:
                yield json.dumps({"tipo": "fin", "resultado": resultado.get("fin")},
                                 ensure_ascii=False, default=str) + "\n"
            completo = True
        finally:
            if not completo:
                cancelar.set()
    return StreamingResponse(_flujo_cancelable(emitir()), media_type="application/x-ndjson")


def _gpu_ocupada() -> bool:
    with ai_engine._streams_lock:
        return bool(ai_engine._active_streams)


class ArchivoGuardadoRequest(BaseModel):
    path: str
    content: str


@app.post("/api/interno/archivo-guardado")
def interno_archivo_guardado(req: ArchivoGuardadoRequest):
    """ El servidor de Rust guarda los archivos del editor y avisa aquí: la memoria del director (llm_director, en
    desarrollo) anota lo leído """
    try:
        from llm_director import director_llm
        ext = os.path.splitext(req.path)[1].lower()
        lenguaje = "python" if ext == ".py" else ("javascript" if ext in (".js", ".jsx") else ("typescript" if ext in (".ts", ".tsx") else ("html" if ext == ".html" else ("css" if ext == ".css" else ("c_cpp" if ext in (".c", ".cpp", ".h") else ("rust" if ext == ".rs" else "text"))))))
        director_llm.memoria.registrar_lectura_archivo(archivo=req.path, codigo=req.content, lenguaje=lenguaje)
    except Exception as e:
        logger.debug("Error registrando memoria AST al guardar archivo: %s", e)
    return {"ok": True}


def _firma_config():
    try:
        st = os.stat(file_mgr.config_path)
        return (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return None


_config_visto: Dict[str, Any] = {"firma": _firma_config()}     # lo que había al arrancar ya se leyó


@app.middleware("http")
async def _seguir_espacio_de_trabajo(request, call_next):
    """ El espacio de trabajo y la segunda carpeta los abre el servidor de Rust y los guarda en ~/.prig_config.json:
    cuando el archivo cambia, se toman aquí y se reapuntan los servicios (rebind_workspace). Solo con una carpeta
    guardada que exista; nunca se cae al directorio actual. """
    firma = _firma_config()
    if firma != _config_visto["firma"]:
        _config_visto["firma"] = firma
        if firma is not None:
            try:
                cfg = file_mgr._leer_config()
                guardado = cfg.get("last_workspace")
                if isinstance(guardado, str) and os.path.isdir(guardado) and \
                        os.path.abspath(guardado) != os.path.abspath(file_mgr.base_dir):
                    file_mgr.base_dir = os.path.abspath(guardado)
                    rebind_workspace(file_mgr.base_dir)
                segunda = cfg.get("segunda_carpeta")
                file_mgr.segunda_dir = segunda if isinstance(segunda, str) and os.path.isdir(segunda) else None
            except Exception as e:
                logger.debug("No se pudo seguir el espacio de trabajo: %s", e)
    return await call_next(request)


@app.post("/api/interno/cancelar")
def interno_cancelar():
    """ «Detener» lo atiende el servidor de Rust; aquí se corta lo que siga generando este backend """
    return {"active_requests_cancelled": ai_engine.cancel_active_requests() + gemini_motor.cancelar_todo()}


class HerramientaInternaRequest(BaseModel):
    sesion: str
    nombre: str
    argumentos: Any = None


@app.post("/api/interno/herramienta")
def interno_herramienta(req: HerramientaInternaRequest):
    """ El servidor de Rust genera el chat y pide aquí cada herramienta (siguen en Python mientras su subsistema no
    pase a Rust) """
    from ai_engine.ai_engine_class import SESIONES_HERRAMIENTAS
    herramientas = SESIONES_HERRAMIENTAS.get(req.sesion)
    if herramientas is None:
        raise HTTPException(status_code=404, detail="Esa conversación ya terminó.")
    try:
        resultado = herramientas.ejecutar(req.nombre, req.argumentos if req.argumentos is not None else {})
    except Exception as e:
        resultado = f"Error al ejecutar {req.nombre}: {e}"
    return {"resultado": str(resultado)}


@app.get("/api/ai/ocupada")
def ai_ocupada():
    """ Para el servidor de Rust (dueño de los recursos): ¿está generando este backend? """
    return {"ocupada": _gpu_ocupada()}


# La máquina, los perfiles, los veredictos, recomendar, aplicar, restaurar, probar, calibrar y el servidor de Ollama:
# los sirve el servidor de Rust (routes/recursos.rs; prig_ia::gestor)

# Temperaturas y gobernador, modo suave (ritmo), modo frío, energía, eventos y el motor MoE: los sirve el servidor de
# Rust, dueño de los controladores (backend-rust/crates/prig-server/src/routes/recursos.rs y moe.rs; prig_ia::vivo)


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


# Las rutas de modelos (/api/modelos, catalogo, ficha, config, plantilla, probar, crear, copiar, borrar, importar,
# actualizaciones, cargados, precargar, descargar, parciales, registro) son del servidor de Rust (routes/modelos.rs).
# Aquí quedan los embeddings, con el índice semántico.


def _carpeta_modelos_servidor() -> Optional[str]:
    try:
        entorno = (recursos_srv.estado().get("entorno") or {})
        return entorno.get("OLLAMA_MODELS")
    except Exception:
        return None


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
                      al_terminar=_al_terminar_descarga,
                      workspace_dir_fn=lambda: file_mgr.base_dir)
seguimiento = buscador_modelos.Seguimiento()


# El buscador de modelos (/api/buscador/*) lo atiende el servidor de Rust (prig_modelos::explorar); aquí queda el
# seguimiento para que una descarga terminada lo marque al día


class DescargaModeloRequest(BaseModel):
    ref: str
    titulo: Optional[str] = None
    tipo: Optional[str] = "ollama"
    variante: Optional[str] = None
    destino: Optional[str] = None


@app.post("/api/descargas")
def descargas_encolar(req: DescargaModeloRequest):
    return _buscador(descargas.encolar, req.ref, req.titulo, tipo=req.tipo or "ollama",
                     variante=req.variante, destino=req.destino)


@app.get("/api/buscador/hf/inspeccionar_completo")
def buscador_hf_inspeccionar_completo(repo: Optional[str] = None, repo_id: Optional[str] = None, variante: Optional[str] = None):
    """Inspecciona los archivos de configuración y pesos de un repositorio de Hugging Face
    para preparar una descarga y respaldo completo contra borrado."""
    ident = repo or repo_id
    if not ident:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Falta el identificador del repositorio ('repo' o 'repo_id').")
    from descargas_hf_completo import inspeccionar_modelo_hf
    return _buscador(inspeccionar_modelo_hf, ident, variante=variante)


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
from desafios.almacen import Almacen as AlmacenDesafios
from desafios.ejecucion import ErrorDesafio

desafios_almacen = AlmacenDesafios()


def _desafio(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ErrorDesafio as e:
        raise HTTPException(status_code=400, detail=str(e))


def _modelo_desafios(modelo: Optional[str], rol: Optional[str] = None) -> str:
    """ El pedido; si no, el modelo elegido para ese rol en Configuración; si no, el del tutor / explicación """
    tutor = ai_engine.config.get("agent1_model") or ai_engine.config.get("agent2_model") or "qwen2.5-coder:7b"
    if modelo:
        return modelo
    if rol:
        return ai_engine.modelo_para(rol) or tutor
    return tutor


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

class DesafioEjecutarRequest(BaseModel):
    paginas: List[Dict[str, Any]]
    pagina: str


class DesafioPasosRequest(BaseModel):
    pasos_vistos: int


class YouTubeAnalisisRequest(BaseModel):
    video_id: str
    titulo: str
    canal: Optional[str] = "YouTube"
    duracion: Optional[str] = ""
    descripcion: Optional[str] = ""
    categoria: Optional[str] = ""
    nivel: Optional[str] = "intermedio"
    texto_usuario: Optional[str] = ""
    notas_usuario: Optional[str] = ""
    modo: Optional[str] = "ambos"  # "resumen" | "objetivos" | "ambos"
    modelo: Optional[str] = None


class YouTubeCrearDesafioRequest(BaseModel):
    video_id: str
    titulo_video: str
    objetivo_id: Optional[str] = None
    objetivo_titulo: Optional[str] = ""
    objetivo_descripcion: Optional[str] = ""
    conceptos: Optional[List[str]] = None
    nivel: Optional[str] = "intermedio"
    lenguaje: Optional[str] = "python"
    modelo: Optional[str] = None


class YouTubeTraducirRequest(BaseModel):
    texto: str
    de: Optional[str] = "auto"
    a: Optional[str] = "es"
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


# Gemini (estado, clave, modelos): los sirve el servidor de Rust (routes/ia.rs; prig_ia::gemini)


class ProgresoAnalisisRequest(BaseModel):
    modelo: Optional[str] = None
    regenerar: bool = False


# Inicio, su perfil y el estado de la máquina (/api/system/stats, /api/system/health): servidor de Rust
# (routes/inicio.rs)
class InicioPerfilRequest(BaseModel):
    nombre: Optional[str] = None
    objetivo: Optional[str] = None
    nivel: Optional[str] = None
    mostrar_al_abrir: Optional[bool] = None
    favoritas: Optional[List[str]] = None

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
    lenguaje = req.lenguaje or ("cpp" if req.ruta.endswith((".cpp", ".cc", ".cxx", ".h", ".hpp")) else "python")

    def trabajo(avisar):
        contenido = req.contenido
        if not contenido:
            avisar({"tipo": "progreso", "mensaje": f"Descargando archivo desde GitHub ({req.ref}/{req.ruta})…"})
            contenido = des_catalogo.descargar_contenido_archivo(req.ref, req.ruta)
            if not contenido:
                try:
                    info_archivo = _github(github_lector.leer_archivo, req.ref, req.ruta)
                    contenido = info_archivo.get("contenido") or ""
                except Exception:
                    contenido = ""

        if not (contenido or "").strip():
            raise des_tutor.ErrorDesafio(
                f"No se pudo obtener el contenido del archivo '{req.ruta}' de '{req.ref}'. "
                "Verifica que el archivo exista y que haya conexión con GitHub."
            )

        if req.ruta.lower().endswith((".ipynb", ".json")):
            avisar({"tipo": "progreso", "mensaje": "Extrayendo celdas de teoría y código del cuaderno Jupyter…"})
            contenido = des_tutor.extraer_contenido_cuaderno(contenido)

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


# La caja de razonamiento, el plan, las pistas, la reflexión, traducir, el chat, analizar una propuesta y
# evaluar la salida: servidor de Rust (routes/desafios_tutor.rs)


# Analizar un video y traducir un fragmento: servidor de Rust (routes/profesor.rs)


@app.post("/api/youtube/crear-desafio")
def youtube_crear_desafio(req: YouTubeCrearDesafioRequest):
    """ Crea un desafío de programación didáctico a partir de un objetivo o tema del video (NDJSON) """
    modelo = _modelo_desafios(req.modelo, "codigo")
    motor, nombre_modelo = _motor_desafios(modelo)

    tema = req.objetivo_titulo or req.titulo_video
    conceptos_str = ", ".join(req.conceptos or []) if req.conceptos else "conceptos vistos en la clase"
    contexto = (
        f"El alumno está estudiando el curso de YouTube: «{req.titulo_video}» en Prig IDE.\n"
        f"Objetivo de aprendizaje a dominar: «{tema}».\n"
        f"Detalles didácticos: {req.objetivo_descripcion or 'Demostrar dominio práctico resolviendo el problema'}.\n"
        f"Conceptos clave: {conceptos_str}.\n"
        f"Crea un desafío didáctico e interactivo en {req.lenguaje or 'python'} con pruebas unitarias que verifiquen "
        f"estos conceptos específicos y un esqueleto limpio con comentarios TODO."
    )

    def trabajo(avisar):
        d = des_tutor.crear(
            motor, runner, nombre_modelo, tema, req.nivel or "intermedio",
            contexto, avisar=avisar, lenguaje=req.lenguaje or "python"
        )
        nube = gemini_motor.es_gemini(modelo)
        d["lenguaje"] = req.lenguaje or "python"
        d["origen"] = {
            "tipo": "youtube",
            "nombre": f"YouTube · {req.titulo_video}" + (" · Google Gemini" if nube else ""),
            "modelo": modelo,
            "motor": "gemini" if nube else "ollama",
            "video_id": req.video_id,
            "tema": tema,
            "objetivo_id": req.objetivo_id,
            "lenguaje": req.lenguaje or "python"
        }
        d = desafios_almacen.guardar(d)
        _registrar_telemetria(d, "generated", attempt_num=len(d.get("intentos_creacion") or [1]))
        return AlmacenDesafios.publico(d)

    return _ndjson_en_hilo(trabajo)


# ----------------------------------------------------------------------------
# YouTube Search Engine & Registered Keywords (Deep Learning, Machine Learning, Python, C++)
# ----------------------------------------------------------------------------
# ============================================================================
# Prig Hub: tu aprendizaje en texto plano, versionado en git (backend/hub, docs/prig-hub.md)
# ============================================================================
from hub.api import crear_router as _hub_router  # noqa: E402

app.include_router(_hub_router(
    runner=runner, motor=_motor_desafios, consumir=_consumir, ndjson=_ndjson_en_hilo, desafios=desafios_almacen,
    telemetria=_registrar_telemetria, publico=AlmacenDesafios.publico, validar_desafio=des_ejec.validar_desafio,
    autor=lambda: inicio.perfil().get("nombre") or ""))

# ============================================================================
# API DIRECTOR NARRATIVO Y DE AGENTES ASCII (Modelos 7B / Ollama / Local)
# ============================================================================
from llm_director import director_llm

class LLMDirectorRequest(BaseModel):
    tema_id: str = "tema_mecha_patrol"
    contexto: Dict[str, Any] = {}
    modelo: Optional[str] = None
    endpoint: Optional[str] = None

@app.post("/api/llm/director_decision")
def obtener_decision_director(req: LLMDirectorRequest):
    """
    Retorna directivas de movimiento, animaciones y diálogos de fondo
    generados por un modelo 7B o motor procedural.
    """
    try:
        decision = director_llm.consultar_director(
            tema_id=req.tema_id,
            contexto_editor=req.contexto,
            modelo_personalizado=req.modelo,
            endpoint_personalizado=req.endpoint
        )
        return {"ok": True, "data": decision}
    except Exception as e:
        logger.error(f"Error en director LLM: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/llm/director_stream")
def obtener_decision_director_stream(req: LLMDirectorRequest):
    """
    Emite tokens progresivos en streaming (Server-Sent Events) con latencia < 150ms
    y entrega la decisión completa estructurada al finalizar.
    """
    try:
        gen = director_llm.consultar_director_stream(
            tema_id=req.tema_id,
            contexto_editor=req.contexto,
            modelo_personalizado=req.modelo,
            endpoint_personalizado=req.endpoint
        )
        return StreamingResponse(gen, media_type="text/event-stream")
    except Exception as e:
        logger.error(f"Error en streaming del director LLM: {e}")
        return {"ok": False, "error": str(e)}

class PreguntaCerebroRequest(BaseModel):
    pregunta: str
    modelo: Optional[str] = None
    endpoint: Optional[str] = None

@app.get("/api/llm/memoria_archivos")
def obtener_memoria_archivos():
    """
    Retorna la lista de archivos leídos y comprimidos semánticamente (TC-AST)
    junto con las estadísticas de ahorro de tokens.
    """
    try:
        archivos = director_llm.memoria.obtener_resumen_memoria()
        stats = director_llm.memoria.obtener_estadisticas_tokens()
        return {
            "ok": True,
            "archivos": archivos,
            "stats": stats,
            "historial_preguntas": director_llm.memoria.historial_preguntas
        }
    except Exception as e:
        logger.error(f"Error obteniendo memoria de archivos: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/llm/preguntar_cerebro")
def preguntar_cerebro_memoria(req: PreguntaCerebroRequest):
    """
    Responde preguntas sobre los archivos leídos utilizando únicamente
    la memoria semántica comprimida (ahorrando ~90% tokens).
    """
    try:
        res = director_llm.memoria.preguntar_al_cerebro(
            pregunta=req.pregunta,
            director_instancia=director_llm,
            modelo=req.modelo,
            endpoint=req.endpoint
        )
        return res
    except Exception as e:
        logger.error(f"Error consultando al cerebro: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/llm/limpiar_memoria_cerebro")
def limpiar_memoria_cerebro():
    """Limpia el almacén de memoria comprimida"""
    try:
        director_llm.memoria.archivos_memorizados.clear()
        director_llm.memoria.historial_preguntas.clear()
        director_llm.memoria._guardar_memoria()
        return {"ok": True, "mensaje": "Memoria del cerebro reiniciada"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

class EjecutarPensamientoProyectoRequest(BaseModel):
    carpeta: Optional[str] = ""
    tema_id: Optional[str] = "tema_mecha_patrol"
    modelo: Optional[str] = None
    endpoint: Optional[str] = None

@app.post("/api/llm/ejecutar_pensamiento_proyecto")
def ejecutar_pensamiento_proyecto_endpoint(req: EjecutarPensamientoProyectoRequest):
    """
    Ejecuta el razonamiento y pensamiento del personaje temático sobre la carpeta
    o proyecto y lo materializa en un archivo markdown estructurado en el disco.
    """
    try:
        res = director_llm.ejecutar_pensamiento_en_archivo(
            carpeta=req.carpeta,
            tema_id=req.tema_id or "tema_mecha_patrol",
            modelo_personalizado=req.modelo,
            endpoint_personalizado=req.endpoint
        )
        return res
    except Exception as e:
        logger.error(f"Error ejecutando pensamiento del proyecto: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


# ============================================================================
# API MOTOR DE APRENDIZAJE POR GRAFO DE NODOS (YouTube, GitHub, Kaggle, Prig Hub)
# ============================================================================
from motor_aprendizaje_nodos import motor_aprendizaje

class EjecutarTareaAprendizajeRequest(BaseModel):
    codigo: Optional[str] = ""
    usar_solucion: bool = False

class ProgresoNodoAprendizajeRequest(BaseModel):
    completado: bool = True

@app.get("/api/aprendizaje/grafo")
def obtener_grafo_aprendizaje(nivel: Optional[str] = None):
    """Retorna el árbol de conocimiento estructurado en DAG con dependencias y estado."""
    try:
        return motor_aprendizaje.obtener_grafo(filtro_nivel=nivel)
    except Exception as e:
        logger.error(f"Error obteniendo grafo de aprendizaje: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/api/aprendizaje/nodo/{nodo_id}")
def obtener_nodo_aprendizaje(nodo_id: str):
    """Retorna el detalle conceptual, recursos de 4 herramientas y tarea pre-respondida."""
    try:
        nodo = motor_aprendizaje.obtener_nodo(nodo_id)
        if not nodo:
            raise HTTPException(status_code=404, detail=f"Nodo '{nodo_id}' no encontrado")
        return {"ok": True, "nodo": nodo}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo nodo de aprendizaje {nodo_id}: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/api/aprendizaje/buscar")
def buscar_aprendizaje(q: str = "", limite: int = 15):
    """Búsqueda semántica ultra-rápida (<5ms) a través de nodos, teoría, videos y datasets."""
    try:
        resultados = motor_aprendizaje.buscar(query=q, limite=limite)
        return {"ok": True, "total": len(resultados), "resultados": resultados}
    except Exception as e:
        logger.error(f"Error en búsqueda de aprendizaje: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/aprendizaje/nodo/{nodo_id}/ejecutar")
def ejecutar_tarea_nodo(nodo_id: str, req: EjecutarTareaAprendizajeRequest):
    """Ejecuta de manera segura la solución y verifica contra tests unitarios en <50ms."""
    try:
        return motor_aprendizaje.ejecutar_tarea(
            nodo_id=nodo_id,
            codigo_usuario=req.codigo or "",
            usar_solucion=req.usar_solucion
        )
    except Exception as e:
        logger.error(f"Error ejecutando tarea del nodo {nodo_id}: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/aprendizaje/nodo/{nodo_id}/abrir_en_editor")
def abrir_nodo_en_editor(nodo_id: str):
    """Genera los archivos locales en el workspace y los abre en el Editor Prig."""
    try:
        return motor_aprendizaje.abrir_en_editor(nodo_id=nodo_id)
    except Exception as e:
        logger.error(f"Error abriendo nodo {nodo_id} en editor: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/aprendizaje/nodo/{nodo_id}/progreso")
def actualizar_progreso_nodo(nodo_id: str, req: ProgresoNodoAprendizajeRequest):
    """Marca manualmente un nodo como completado o pendiente."""
    try:
        motor_aprendizaje.marcar_progreso(nodo_id=nodo_id, completado=req.completado)
        return {"ok": True, "nodo_id": nodo_id, "completado": req.completado}
    except Exception as e:
        logger.error(f"Error actualizando progreso del nodo {nodo_id}: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/api/aprendizaje/estadisticas")
def obtener_estadisticas_aprendizaje():
    """Retorna métricas globales de avance pedagógico por nivel (Junior a Senior)."""
    try:
        stats = motor_aprendizaje.obtener_estadisticas_progreso()
        return {"ok": True, "estadisticas": stats}
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas de aprendizaje: {e}")
        return {"ok": False, "error": str(e)}


# ===========================================================================
# Módulo SQL Studio (Compatibilidad y fallback Python con dialecto MySQL)
# El motor principal de alto rendimiento reside en Rust (backend-rust/crates/prig-server/src/routes/sql.rs)
# ===========================================================================

# Serve frontend static assets


if os.path.exists(frontend_dir):


    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

@app.get("/")
def serve_index():
    # no-cache: el navegador puede guardarlo, pero lo revalida siempre. Sin esto, tras
    # actualizar Prig la ventana seguía con un index.html viejo que pedía versiones viejas
    # de los scripts (las nuevas llevan otro ?v=, pero solo si index.html es el nuevo).
    return FileResponse(os.path.join(frontend_dir, "index.html"), headers={"Cache-Control": "no-cache"})
