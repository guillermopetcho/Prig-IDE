import os
import re
import asyncio
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import queue
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
from ai_engine.ai_engine_class import fijar_cancelacion
from book_service import BookService
import librerias_service
from knowledge_service import KnowledgeService
from knowledge_base import KnowledgeBase
from knowledge_context import ContextAssembler
from contexto_modelo import CompiladorContexto
import agent_flows
from explorador import Explorador
from ide_servicios import ServiciosIDE
from ollama_gestion import GestorModelos
from herramientas_chat import Herramientas, ETIQUETAS as ETIQUETAS_HERRAMIENTAS
import banco_proyecto
import memoria_consulta
import lectura_unidades
import buscador_modelos
from buscador_modelos import ErrorBuscador
from descargas_modelos import Descargas
from recursos.gestor import gestor as _gestor_recursos
from recursos import calibracion as recursos_cal, servidor as recursos_srv
from recursos.almacen import almacen as recursos_almacen
from recursos import termico as recursos_termico
from feature_flags import FeatureFlags
from learning_telemetry import LearningTelemetry
from guided_learning import GuidedLearningService
import inicio

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
explorador = Explorador(file_mgr.base_dir)
flags = FeatureFlags()
telemetry = LearningTelemetry(file_mgr.base_dir)

# Aprendizaje Guiado: sistema único de rutas. Sustituye a Recorrido y Seguimiento,
# que hacían casi lo mismo con dos modelos, dos interfaces y dos almacenes.
guided = GuidedLearningService(file_mgr.base_dir, ai_engine, book_service)

_tracked_child_processes: List[subprocess.Popen] = []
_tracked_lock = threading.Lock()

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

    # 2. Los flujos de agentes los ejecuta el servidor de Rust (routes/flujos.rs)

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



# La lista, leer, la ficha de IA, los recortes, el lector de PDF, las citas e importar (con su indexación) los
# libros: servidor de Rust (routes/estante.rs y routes/libros.rs).


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

# Las referencias (listar, detalle, relacionadas, pdf, abrir y guardar el PDF en la biblioteca, indexado): servidor
# de Rust (routes/referencias.rs)


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

# Los flujos, su catálogo y su historial, la ficha de un libro con un flujo y el workflow del editor: servidor de
# Rust (routes/flujos.rs y routes/flujos_motor.rs)





# ======================================================================
# Perfiles de Configuración del Entorno (Apariencia, Movimiento, IA)
# ======================================================================

# Las aplicaciones con audio, la fuente, el análisis y /ws/audio_reactivo: servidor de Rust (routes/escritorio.rs)

# ======================================================================
# Ficha de libro: analizar un libro entero con un flujo de agentes
# ======================================================================



# Los libros analizables, la ficha guardada y lo que leería el flujo: servidor de Rust (routes/kb.rs)



# El material para un ejercicio y el contexto para el plan: servidor de Rust (prig_biblioteca::perfil)


# ======================================================================
# Explorar carpetas y sondear libros antes de extraerlos
# ======================================================================

# El sondeo de libros y preparar desde él: servidor de Rust (prig_biblioteca::sondeo, routes/trabajos.rs)


# Kaggle y GitHub (buscar, leer, colecciones, guardados): servidor de Rust (routes/integraciones.rs, routes/desafios.rs)

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

# Ejecutar archivos y celdas de cuaderno, cancelar y reiniciar la sesión: servidor de Rust (routes/ejecutar.rs)

@app.post("/api/app/shutdown")
def api_shutdown():
    """ Endpoint para solicitar el apagado seguro de análisis y procesos desde el cliente """
    cleanup_all_processes()
    return {"status": "ok", "message": "Análisis y procesos apagados correctamente."}

# La versión de Ollama, actualizarlo y abrir la terminal con el instalador: servidor de Rust (routes/ia.rs)

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


# Las rutas de modelos (/api/modelos, catalogo, ficha, config, plantilla, probar, crear, copiar, borrar, importar,
# actualizaciones, cargados, precargar, descargar, parciales, registro, embeddings) son del servidor de Rust
# (routes/modelos.rs).


def _carpeta_modelos_servidor() -> Optional[str]:
    try:
        entorno = (recursos_srv.estado().get("entorno") or {})
        return entorno.get("OLLAMA_MODELS")
    except Exception:
        return None


# Los embeddings (ajustes, fijar y probar): servidor de Rust (routes/modelos.rs, con el índice de routes/kb.rs)


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

from desafios import ejecucion as des_ejec
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


class YouTubeTraducirRequest(BaseModel):
    texto: str
    de: Optional[str] = "auto"
    a: Optional[str] = "es"
    modelo: Optional[str] = None


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


# Inicio, su perfil y el estado de la máquina (/api/system/stats, /api/system/health): servidor de Rust
# (routes/inicio.rs)
class InicioPerfilRequest(BaseModel):
    nombre: Optional[str] = None
    objetivo: Optional[str] = None
    nivel: Optional[str] = None
    mostrar_al_abrir: Optional[bool] = None
    favoritas: Optional[List[str]] = None

# Analizar el avance con el modelo (POST /api/progreso/analisis): servidor de Rust (routes/desafios_tutor.rs)

# Las fuentes de internet, buscar e importar, el catálogo de GitHub, crear y replicar desafíos (y crear uno desde un
# video de YouTube): servidor de Rust (routes/desafios_fuentes.rs y routes/desafios_crear.rs)


# La caja de razonamiento, el plan, las pistas, la reflexión, traducir, el chat, analizar una propuesta y
# evaluar la salida: servidor de Rust (routes/desafios_tutor.rs)


# Analizar un video y traducir un fragmento: servidor de Rust (routes/profesor.rs)


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
